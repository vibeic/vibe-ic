"""UFS (Universal Flash Storage) protocol synth helper.

v0.1.89 — ic_class-gated overlay for storage / command-driven specs that
exhibit the UFS structural signature. Applies JEDEC JESD220 / UFS 4.0
spec-canonical content to L1-L23 (UFS = MIPI M-PHY physical + MIPI UniPro
transport + UPIU/UTP + SCSI-based UFS Command Set + UFSHCI host controller).

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / SD-MMC / PCIe /
NVMe / SATA synth approach). Any UFS-family device (eUFS, UFS Card, any
UFS 2.x/3.x/4.x generation) exhibits the same layered M-PHY + UniPro +
UPIU + SCSI signature.

Detector signature (read by the runner from L1/L2 CONTENT only — NEVER from
input-doc filenames or the benchmark folder name; that is a general-not-
keyword doctrine violation flagged on the AHB+APB detector and must not be
repeated here). The runner builds `_spi_blob` from the CONTENT of
L1_DATASHEET.json + L2_FRS.json and evaluates:

    _is_ufs = (
        ("UFS" in _spi_blob and "UniPro" in _spi_blob)
        or ("UPIU" in _spi_blob)
        or ("Universal Flash Storage" in _spi_blob)
        or ("UFS" in _spi_blob and "M-PHY" in _spi_blob
            and "JESD220" in _spi_blob))

SIBLING DISAMBIGUATION
----------------------
UFS is a modern storage protocol that is positioned as the successor to
eMMC / SD-MMC and whose UFSHCI 4.0 MCQ is *described as analogous to* the
NVMe SQ/CQ model. Two sibling detectors must therefore be considered:

  * SD/MMC (`sdmmc_protocol_synth`, fires first): its signature keys on
    CMD0 + ACMD41 + CID + CSD + OCR, OR "SD Card"+"CMD line"+"DAT", OR
    "MultiMediaCard"+"CMD line", OR "SD Memory Card"+CID/CSD. A correctly
    authored UFS L1/L2 contains NONE of those (UFS is SCSI/UPIU based — no
    CMD0/ACMD41/CID/CSD/OCR registers, no "SD Card"/"CMD line"/"DAT"
    command-line tokens). So the SD/MMC detector does NOT false-fire on
    UFS. But because SD/MMC runs *before* UFS in the runner's detector
    chain, this module FORCE-OVERWRITES (direct-assign, not setdefault)
    every L1/L2/L3/L4 key the SD/MMC synth populates, so any residual
    SD/MMC pollution is replaced with UFS-canonical values.

  * NVMe (`nvme_protocol_synth`): its signature keys on "Submission
    Queue"+"Completion Queue"+"doorbell", OR "NVMe"+"Admin Command"+
    "I/O Command", OR "NVM Express"+register tokens. A correctly authored
    UFS L1/L2 uses the UFS-specific MCQ vocabulary ("Multi-Circular
    Queue" / "UTRD" / UPIU) and does NOT spell the NVMe Submission/
    Completion-Queue triple, so NVMe does not false-fire. The UFS
    version-specific structural token set ("UniPro" + "M-PHY" + "UPIU" +
    "JESD220" + "UFSHCI") is what uniquely identifies UFS — none of the
    sibling storage/queue protocols carry the UniPro+M-PHY+UPIU triad.

The detector MUST NOT false-fire on SD/MMC (which lacks UniPro / UPIU /
M-PHY) and MUST NOT be false-fired-on by the SD/MMC sibling (whose
CMD0/ACMD41/CID/CSD tokens are absent from UFS docs).

Public entry: `apply_ufs_synth(generated_docs_dir, is_ufs, ufs_ic_name)`.
"""
from __future__ import annotations

import json
import re
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
    """setdefault-None bug fix: if the value is None / empty, replace with {}."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    if not isinstance(d.get(key), dict):
        d[key] = {}
    return d[key]


def _fields(d: dict) -> dict:
    """L14-L23 wrap content inside a 'fields' object."""
    return _ensure_dict(d, "fields")


# Documents whose ic_name lives at the top level (L1-L23 + L8 timing).
_TOP_LEVEL_DOCS = [
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
    "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
]

# Documents whose ic_name lives inside "fields" (L14-L23).
_FIELDS_DOCS = [
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
]


def apply_ufs_synth(generated_docs_dir, is_ufs: bool,
                    ufs_ic_name: Optional[str]) -> None:
    """Apply UFS-specific synth when the structural signature matched."""
    if not is_ufs:
        return
    gd = Path(generated_docs_dir)

    # ---- Force ic_name across all 24 L docs FIRST (top-level for L1-L23 +
    # L8 timing; inside "fields" for L14-L23).
    if ufs_ic_name is not None:
        for n in _TOP_LEVEL_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ufs_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _fields(d)
                f["ic_name"] = ufs_ic_name
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
# L1 datasheet metadata
# ---------------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-override SD/MMC-polluted identity fields (SD/MMC synth runs first).
    d["document_title"]  = "Universal Flash Storage (UFS) Standard"
    d["document_number"] = "JEDEC JESD220 (UFS) + JESD223 (UFSHCI)"
    d["version"]         = "UFS 4.0 (UFSHCI 4.0)"
    d["revised_date"]    = "August 17, 2022"
    d["manufacturer"]    = "JEDEC Solid State Technology Association"
    d["publisher"]       = ("JEDEC Solid State Technology Association, 3103 North "
                            "10th Street, Suite 240 South, Arlington, VA 22201-2107 USA")
    d["copyright"]       = "Copyright JEDEC Solid State Technology Association"
    d["abstract"] = (
        "Universal Flash Storage (UFS) is a high-performance mobile flash "
        "storage standard, positioned as the successor to eMMC and SD cards. "
        "UFS is layered on the MIPI M-PHY physical layer and the MIPI UniPro "
        "transport/network stack, and uses a SCSI-based command set carried "
        "in UFS Protocol Information Units (UPIUs). UFS 4.0 pairs M-PHY 5.0 "
        "(HS-Gear 5, 23.2 Gbit/s per lane) with UniPro v2.0 over up to 2 lanes "
        "per direction, and adds the UFSHCI 4.0 Multi-Circular Queue (MCQ) "
        "host-controller interface.")
    d["overview"] = (
        "Universal Flash Storage (UFS) is a flash storage specification for "
        "mobile phones, digital cameras and consumer electronic devices, "
        "positioned as a replacement for eMMC and SD cards. The standard "
        "encompasses both permanently embedded packages (eUFS, via ball grid "
        "array) and removable UFS memory cards. The electrical interface uses "
        "the MIPI M-PHY high-speed serial PHY; the transport stack is MIPI "
        "UniPro. Unlike eMMC, UFS is based on the SCSI architectural model and "
        "supports SCSI Tagged Command Queuing, exchanging UPIUs (UFS Protocol "
        "Information Units) between host and device. UFS 4.0 uses M-PHY 5.0 "
        "(HS-Gear 5, 23.2 Gbit/s per lane), UniPro v2.0, and UFSHCI 4.0 with "
        "the native Multi-Circular Queue (MCQ). The standard is developed by, "
        "and available from, the JEDEC Solid State Technology Association as "
        "JESD220 (UFS) and JESD223 (UFSHCI).")
    d["topology_summary"] = (
        "Point-to-point host-to-device link. The UFS host (master, via the UFS "
        "host controller / UFSHCI) drives REF_CLK and RESET_n; the UFS device "
        "(slave) communicates over M-PHY differential RX/TX lane pairs under "
        "the UniPro transport stack. The host initiates all transactions by "
        "submitting Command UPIUs; the device returns Response / Data In / RTT "
        "/ Query / Task-Management Response UPIUs.")
    # Force-override SD/MMC pin/keyword/feature lists (different protocol).
    d["external_pins"] = [
        "RESET_n", "REF_CLK",
        "DIN0_t/DIN0_c (M-PHY RX lane 0 differential pair)",
        "DOUT0_t/DOUT0_c (M-PHY TX lane 0 differential pair)",
        "DIN1_t/DIN1_c (M-PHY RX lane 1 differential pair)",
        "DOUT1_t/DOUT1_c (M-PHY TX lane 1 differential pair)",
        "VCC (NAND core supply)", "VCCQ (low-voltage core supply)",
        "VCCQ2 (interface supply)", "VSS (ground)",
    ]
    d["external_pin_count"] = 10
    # Remove SD/MMC-only keys that do not apply to UFS, if SD/MMC synth set them.
    for stale in ("external_pins_sd_mode", "external_pins_spi_mode",
                  "card_capacity_classes"):
        d.pop(stale, None)
    d["keywords"] = [
        "UFS", "Universal Flash Storage", "UniPro", "M-PHY", "UPIU",
        "JESD220", "UFSHCI", "RPMB", "HPB", "WriteBooster", "HS-Gear",
        "MCQ", "W-LUN", "SCSI", "LUN",
    ]
    d["key_features"] = [
        "Layered architecture: MIPI M-PHY (physical) + MIPI UniPro (transport/network/data-link) + UFS Transport Protocol (UTP) carrying UPIUs + SCSI-based UFS Command Set (UCS) + UFSHCI host controller interface.",
        "MIPI M-PHY 5.0 physical layer: high-speed differential serial (LVDS-style), HS-Gear 1..5 plus PWM low-speed modes, RMMI (Reference M-PHY Module Interface) to UniPro.",
        "HS-Gear 5 = 23.2 Gbit/s per lane (~2900 MB/s per lane); UFS uses up to 2 lanes per direction (RX/TX pairs).",
        "MIPI UniPro v2.0 transport: reliable, in-order delivery, flow control, error handling, CPorts (logical connection endpoints), L1.5 PHY-adapter layer.",
        "UPIU (UFS Protocol Information Unit) transaction packets: Command / Response / Data In / Data Out / Ready-To-Transfer (RTT) / Task Management Request+Response / Query Request+Response / NOP In+Out / Reject.",
        "SCSI-based UFS Command Set (based on the SCSI architectural model; supports SCSI Tagged Command Queuing) plus UFS-native command extensions.",
        "Multiple Logical Units (LUNs) plus Well-known LUNs: REPORT LUNS, UFS DEVICE, BOOT, RPMB.",
        "RPMB (Replay Protected Memory Block): 256-bit authentication key + monotonic write counter + HMAC-SHA256 MAC for anti-replay secure storage.",
        "UFSHCI 4.0 host controller interface with legacy single Transfer Request List (UTRD ring + doorbell) and native Multi-Circular Queue (MCQ) multi-queue submission/completion model.",
        "WriteBooster: pseudo-SLC turbo-write buffer for higher burst write throughput, later flushed to the main TLC/QLC area.",
        "HPB (Host Performance Booster): optional caching of the device L2P (logical-to-physical) mapping in host DRAM to cut device-side lookup latency.",
        "Full-duplex serial differential interface, scaling better to higher bandwidths than eMMC's parallel half-duplex bus.",
    ]
    d["revision_history"] = [
        {"version": "1.0", "date": "February 24, 2011", "description": "Initial JESD220 UFS standard; 300 MB/s per lane; M-PHY 1.0; UniPro 1.4."},
        {"version": "1.1", "date": "June 25, 2012", "description": "Update to UFS v1.0."},
        {"version": "2.0", "date": "September 18, 2013", "description": "JESD220B; increased link bandwidth, security features extension, additional power-saving features; HS-Gear 3 class; M-PHY 3.x; UniPro 1.6."},
        {"version": "2.1", "date": "April 4, 2016", "description": "600 MB/s per lane class."},
        {"version": "3.0", "date": "January 30, 2018", "description": "11.6 Gbit/s per lane (1450 MB/s); MIPI M-PHY v4.1 (HS-Gear 4); UniPro v1.8."},
        {"version": "3.1", "date": "January 30, 2020", "description": "Added WriteBooster, Deep Sleep, Performance Throttling Notification, Host Performance Booster (optional)."},
        {"version": "4.0", "date": "August 17, 2022", "description": "Doubled bandwidth to 23.2 Gbit/s per lane (2900 MB/s); MIPI M-PHY v5.0 (HS-Gear 5); UniPro v2.0; UFSHCI 4.0 Multi-Circular Queue (MCQ); File Based Optimization."},
    ]
    d.setdefault("lun_classes", [
        {"name": "Normal LUN", "description": "User-data Logical Unit; individually configurable size / type / write-protect / memory type via the Unit Descriptor."},
        {"name": "REPORT LUNS W-LUN", "description": "Well-known LUN that enumerates the active LUNs."},
        {"name": "UFS DEVICE W-LUN", "description": "Well-known LUN for device-level commands / power management / device-wide operations."},
        {"name": "BOOT W-LUN", "description": "Well-known LUN exposing the boot partition (maps to the LU designated by bBootLunEn)."},
        {"name": "RPMB W-LUN", "description": "Well-known LUN for Replay Protected Memory Block access (authenticated secure storage)."},
    ])
    d["use_cases"] = [
        "Flagship smartphones and tablets (embedded UFS / eUFS)",
        "Automotive infotainment and ADAS storage",
        "Removable UFS memory cards (UFS Card Extension)",
        "AR/VR and high-frame-rate camera capture storage",
        "Edge-AI devices requiring high random-read throughput",
        "Set-top boxes and consumer electronics with high terabytes-written endurance",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L2 FRS
# ---------------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-override SD/MMC-polluted protocol_overview (different protocol).
    po = _ensure_dict(d, "protocol_overview")
    # Clear SD/MMC-only sub-keys then set the UFS shape.
    for stale in ("wire_names_sd_mode", "wire_count_sd_mode",
                  "wire_names_spi_mode", "wire_count_spi_mode",
                  "supports_1bit_mode", "supports_4bit_mode",
                  "supports_spi_mode", "card_role"):
        po.pop(stale, None)
    po["type"] = (
        "Layered host-mastered storage protocol. SCSI-based command set "
        "carried in UFS Protocol Information Units (UPIUs) over the UFS "
        "Transport Protocol (UTP), transported by MIPI UniPro over the MIPI "
        "M-PHY high-speed serial physical layer.")
    po["duplex"] = ("full-duplex (independent M-PHY TX and RX differential "
                    "lane pairs per direction)")
    po["synchronous"] = True
    po["wire_names"] = [
        "REF_CLK (host -> device reference clock)",
        "RESET_n (host -> device reset, active low)",
        "DOUT_t/DOUT_c (device TX differential pair per lane)",
        "DIN_t/DIN_c (device RX differential pair per lane)",
    ]
    po["lane_count_max"] = 2
    po["physical_layer"] = ("MIPI M-PHY 5.0 (HS-Gear 1..5 + PWM low-speed "
                            "modes; RMMI interface to UniPro)")
    po["transport_layer"] = ("MIPI UniPro v2.0 (data-link L2 + network L3 + "
                             "transport L4 + L1.5 PHY-adapter; CPorts as "
                             "logical connection endpoints)")
    po["command_set"] = ("SCSI-based UFS Command Set (UCS); supports SCSI "
                         "Tagged Command Queuing")
    po["host_role"] = (
        "Bus master; submits Command / Query / Task-Management Request / NOP "
        "Out UPIUs via the UFS host controller (UFSHCI); fetches/posts data "
        "buffers; rings doorbells.")
    po["device_role"] = (
        "Bus slave; returns Response / Data In / RTT / Query Response / "
        "Task-Management Response / NOP In / Reject UPIUs; exposes multiple "
        "LUNs and Well-known LUNs.")
    d["functional_requirements"] = [
        {"id": "FR-LAYER-01", "text": "The UFS interface shall be layered: MIPI M-PHY (physical) + MIPI UniPro (data-link/network/transport) + UFS Transport Protocol (UTP) carrying UPIUs + SCSI-based UFS Command Set + UFSHCI host controller interface."},
        {"id": "FR-PHY-02", "text": "The physical layer shall be MIPI M-PHY 5.0 supporting HS-Gear 1..5 high-speed (8b/10b) modes and PWM low-speed modes, connected to UniPro via the RMMI. UFS 4.0 HS-Gear 5 = 23.2 Gbit/s per lane."},
        {"id": "FR-LANES-03", "text": "UFS shall support up to 2 lanes per direction (independent TX and RX differential pairs), giving up to ~46.4 Gbit/s aggregate per direction in HS-Gear 5."},
        {"id": "FR-UNIPRO-04", "text": "The transport stack shall be MIPI UniPro v2.0 providing reliable in-order delivery, flow control, error recovery and CPort logical connection endpoints."},
        {"id": "FR-UPIU-05", "text": "Host and device shall exchange UPIUs (UFS Protocol Information Units); each UPIU header carries a Transaction Type, Flags, LUN, Task Tag, Command Set Type, and data-segment/extra-header-segment lengths."},
        {"id": "FR-UPIU-TYPES-06", "text": "Defined UPIU transaction types shall include Command, Response, Data In, Data Out, Ready-To-Transfer (RTT), Task Management Request, Task Management Response, Query Request, Query Response, NOP Out, NOP In, and Reject."},
        {"id": "FR-SCSI-07", "text": "The command set shall be SCSI-based (UFS is based on the SCSI architectural model and supports SCSI Tagged Command Queuing); Command UPIUs carry a SCSI/UFS CDB (Command Descriptor Block)."},
        {"id": "FR-LUN-08", "text": "A UFS device shall expose multiple Logical Units (LUNs), each individually configurable via the Unit Descriptor, plus the Well-known LUNs: REPORT LUNS, UFS DEVICE, BOOT, RPMB."},
        {"id": "FR-RTT-09", "text": "For write transfers the device shall control inbound data flow via Ready-To-Transfer (RTT) UPIUs; the number of outstanding RTTs is bounded by bMaxNumOfRTT."},
        {"id": "FR-TASKMGMT-10", "text": "The device shall support task-management functions (ABORT TASK, ABORT TASK SET, CLEAR TASK SET, LOGICAL UNIT RESET, QUERY TASK) via Task Management Request UPIUs."},
        {"id": "FR-QUERY-11", "text": "The host shall be able to read/write Descriptors, Attributes and Flags via Query Request/Response UPIUs without using the SCSI command path."},
        {"id": "FR-MCQ-12", "text": "UFSHCI 4.0 shall support legacy command queueing (single Transfer Request List / UTRD ring + doorbell) and native Multi-Circular Queue (MCQ) with multiple hardware submission/completion queue pairs, each with its own doorbell and head/tail pointers."},
        {"id": "FR-RPMB-13", "text": "The device shall provide an RPMB (Replay Protected Memory Block) area via the RPMB W-LUN, authenticated with a one-time-programmed 256-bit key, a monotonic write counter, and an HMAC-SHA256 MAC over the RPMB frame."},
        {"id": "FR-WB-14", "text": "The device should support WriteBooster (pseudo-SLC turbo-write buffer) to raise burst write throughput, flushed to the main TLC/QLC area during idle time."},
        {"id": "FR-HPB-15", "text": "The device may support Host Performance Booster (HPB, optional) to cache the L2P mapping in host DRAM in Host-control or Device-control mode."},
    ]
    d["configurations"] = [
        {"name": "Single-lane HS-Gear", "description": "One M-PHY RX + one M-PHY TX differential pair per direction; lower pin count."},
        {"name": "Dual-lane HS-Gear 5 (UFS 4.0)", "description": "Two M-PHY lanes per direction at 23.2 Gbit/s each (~5800 MB/s class aggregate)."},
        {"name": "Legacy command queueing", "description": "UFSHCI single Transfer Request List (UTRD ring + doorbell) with SCSI Tagged Command Queuing."},
        {"name": "MCQ mode (UFSHCI 4.0)", "description": "Native Multi-Circular Queue: multiple SQ/CQ pairs with independent doorbells for higher concurrency."},
    ]
    d["error_response_conditions"] = [
        "Invalid or unsupported UPIU received by the device -> device returns a Reject UPIU.",
        "SCSI command error -> device returns a Response UPIU with CHECK CONDITION status and SCSI sense data.",
        "UniPro data-link error (CRC/sequence) -> UniPro retransmits the frame; persistent failure escalates to error recovery.",
        "M-PHY line errors / loss of sync -> link re-initialization via UniPro link startup sequence.",
        "RPMB MAC mismatch or write-counter mismatch -> device returns an RPMB result code indicating authentication/replay failure; no data is written.",
        "Task-management timeout -> host issues a Task Management Request (ABORT TASK / LOGICAL UNIT RESET).",
    ]
    d["compliance_requirements"] = [
        "Host shall assert RESET_n and complete the UniPro link startup sequence (M-PHY power-mode change to HS-Gear) before issuing Command UPIUs.",
        "Host shall use Query Request UPIUs to read device Descriptors/Attributes/Flags and configure LUNs before normal SCSI I/O.",
        "Device shall honour bMaxNumOfRTT and only request as much write data as the host has buffered.",
        "RPMB access shall authenticate every write with HMAC-SHA256 over the frame using the programmed key and shall increment the monotonic write counter on each successful write.",
        "Under MCQ, the host shall map each I/O queue pair to its own doorbell and shall not exceed the negotiated queue depth.",
        "M-PHY power-mode and gear changes shall be negotiated via UniPro DME (Device Management Entity) before high-speed data transfer.",
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
    # Force-override SD/MMC command-line protocol with the UPIU model.
    d["protocol_type"] = (
        "Host-mastered, UPIU-based transaction protocol. The host submits "
        "Command UPIUs carrying SCSI/UFS CDBs over the UFS Transport Protocol "
        "(UTP); the device returns Response, Data In, RTT, Query Response, "
        "Task-Management Response, NOP In and Reject UPIUs. Transport is MIPI "
        "UniPro over MIPI M-PHY.")
    # Strip SD/MMC-only structures that do not exist in UFS.
    for stale in ("cmd_format", "response_classes", "data_block_format",
                  "command_classes_ccc", "key_commands", "key_acmds"):
        d.pop(stale, None)
    d["upiu_header_format"] = {
        "description": "Every UPIU begins with a Basic Header that identifies the transaction. The header carries Transaction Type, Flags, LUN, Task Tag, Command Set Type, Query/Task function, Total EHS (Extra Header Segment) length and Data Segment length fields.",
        "fields": [
            {"name": "Transaction Type", "description": "Identifies the UPIU (Command / Response / Data In / Data Out / RTT / Task Mgmt Req+Resp / Query Req+Resp / NOP In+Out / Reject)."},
            {"name": "Flags", "description": "Transaction flags (e.g. read/write direction, overflow/underflow, end-of-data)."},
            {"name": "LUN", "description": "Target Logical Unit Number (normal LUN or Well-known LUN)."},
            {"name": "Task Tag", "description": "Identifies the outstanding task for tagged command queueing."},
            {"name": "Command Set Type", "description": "SCSI command set or UFS-specific command set."},
            {"name": "Query/Task Function", "description": "Function code for Query Request and Task Management Request UPIUs."},
            {"name": "Total EHS Length", "description": "Length of the Extra Header Segment."},
            {"name": "Data Segment Length", "description": "Length of the UPIU data segment payload."},
        ],
    }
    d["upiu_transaction_types"] = [
        {"name": "Command UPIU", "direction": "host -> device", "description": "Carries a SCSI/UFS CDB (Command Descriptor Block); initiates a read/write/admin command."},
        {"name": "Response UPIU", "direction": "device -> host", "description": "Returns command status (GOOD / CHECK CONDITION) and SCSI sense data."},
        {"name": "Data In UPIU", "direction": "device -> host", "description": "Carries read payload from device to host."},
        {"name": "Data Out UPIU", "direction": "host -> device", "description": "Carries write payload from host to device, gated by RTT."},
        {"name": "Ready To Transfer (RTT) UPIU", "direction": "device -> host", "description": "Flow-control token telling the host how much write data it may send next; outstanding RTTs bounded by bMaxNumOfRTT."},
        {"name": "Task Management Request UPIU", "direction": "host -> device", "description": "ABORT TASK, ABORT TASK SET, CLEAR TASK SET, LOGICAL UNIT RESET, QUERY TASK."},
        {"name": "Task Management Response UPIU", "direction": "device -> host", "description": "Result of a task-management function."},
        {"name": "Query Request UPIU", "direction": "host -> device", "description": "Read/write Descriptors, Attributes, Flags without the SCSI command path."},
        {"name": "Query Response UPIU", "direction": "device -> host", "description": "Query result."},
        {"name": "NOP Out UPIU", "direction": "host -> device", "description": "No-operation / link keep-alive / ping."},
        {"name": "NOP In UPIU", "direction": "device -> host", "description": "No-operation response."},
        {"name": "Reject UPIU", "direction": "device -> host", "description": "Rejection of an invalid or unsupported UPIU."},
    ]
    d["scsi_command_examples"] = [
        {"opcode": "TEST UNIT READY", "description": "Check whether a LUN is ready for commands."},
        {"opcode": "INQUIRY", "description": "Return device identification / capabilities for a LUN."},
        {"opcode": "READ (10) / READ (16)", "description": "Read logical blocks; payload returned via Data In UPIUs."},
        {"opcode": "WRITE (10) / WRITE (16)", "description": "Write logical blocks; payload sent via Data Out UPIUs gated by RTT."},
        {"opcode": "REPORT LUNS", "description": "Enumerate active LUNs (issued to the REPORT LUNS W-LUN)."},
        {"opcode": "REQUEST SENSE", "description": "Return SCSI sense data for the prior command."},
        {"opcode": "START STOP UNIT", "description": "Power / spin control at the LUN level."},
        {"opcode": "SYNCHRONIZE CACHE", "description": "Flush cached write data to the medium."},
        {"opcode": "UNMAP", "description": "Deallocate / discard logical blocks (trim)."},
        {"opcode": "SECURITY PROTOCOL IN / OUT", "description": "Transport for RPMB and security operations."},
    ]
    d["query_request_objects"] = [
        {"object": "Descriptor", "description": "Read/write structured device descriptors (Device, Configuration, Unit, Geometry, Interconnect, String, Power, Health, etc.)."},
        {"object": "Attribute", "description": "Read/write scalar device attributes (e.g. bMaxNumOfRTT, bCurrentPowerMode, dCurrentLBASize)."},
        {"object": "Flag", "description": "Read/set/clear/toggle boolean device flags (e.g. fDeviceInit, fPermanentWPEn, fWriteBoosterEn)."},
    ]
    d["command_queueing"] = [
        {"mode": "Legacy SCSI Tagged Command Queuing", "description": "Host tags outstanding commands; the device may reorder/complete them out of order. In legacy UFSHCI a single doorbell register and a Transfer Request List (UTRD ring, one bit per task tag) track outstanding transfer requests."},
        {"mode": "Native MCQ (UFSHCI 4.0)", "description": "Multi-Circular Queue: multiple hardware submission and completion queue pairs, each with its own doorbell and head/tail pointers, analogous to NVMe SQ/CQ pairs, improving parallelism and multi-core scaling."},
    ]
    d["channels"] = [
        {"name": "REF_CLK", "direction": "host -> device", "description": "Reference clock supplied by the host to the device."},
        {"name": "RESET_n", "direction": "host -> device", "description": "Active-low device reset."},
        {"name": "M-PHY TX lanes (DOUT)", "direction": "device -> host", "description": "Device transmit differential pairs (up to 2 lanes), HS-Gear 1..5."},
        {"name": "M-PHY RX lanes (DIN)", "direction": "host -> device", "description": "Device receive differential pairs (up to 2 lanes), HS-Gear 1..5."},
    ]
    d["valid_ready_handshake_rules"] = [
        "There is no wire-level VALID/READY handshake; reliability is provided by UniPro data-link retransmission and in-order delivery.",
        "Write data flow is gated by Ready-To-Transfer (RTT) UPIUs from the device; the host sends Data Out UPIUs only up to the granted amount.",
        "Read data flows from device to host via Data In UPIUs after the Command UPIU.",
        "Completion is reported by a Response UPIU; under MCQ the controller posts a completion to the Completion Queue and rings the completion doorbell.",
    ]
    d["burst_based"] = True
    d["byte_oriented"] = False
    d["frame_format"] = {
        "upiu_layout": "Basic Header (Transaction Type + Flags + LUN + Task Tag + Command Set Type + lengths) + optional Extra Header Segment(s) + optional Data Segment.",
        "command_upiu": "Header + 16-byte (or extended) SCSI/UFS CDB carried in the Command UPIU.",
        "data_transport": "Read payload in Data In UPIUs; write payload in Data Out UPIUs gated by RTT UPIUs.",
        "transport_stack": "UPIUs are carried by the UFS Transport Protocol over UniPro segments/packets/frames over M-PHY symbols.",
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L4 registers
# ---------------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-override SD/MMC register set with the UFSHCI + descriptor model.
    d["register_map_present"] = True
    d["notes"] = (
        "UFS exposes two distinct register/structure surfaces. (1) The UFSHCI "
        "host controller register file (memory-mapped in the host, defined by "
        "JESD223 / UFSHCI 4.0) used by the host driver to submit requests, "
        "ring doorbells, and manage the legacy Transfer Request List or the "
        "native Multi-Circular Queue (MCQ). (2) The device-side configuration "
        "surface, accessed via Query Request/Response UPIUs as structured "
        "Descriptors, scalar Attributes, and boolean Flags (not a flat "
        "memory-mapped offset). The on-bus command set itself is SCSI-based "
        "UPIU transactions.")
    d["register_count"] = 0
    # Remove SD/MMC-only register list.
    d.pop("registers", None)
    d["ufshci_register_summary"] = [
        {"name": "CAP", "long_name": "Host Controller Capabilities", "description": "Reports supported features, number of UTP transfer/task-management request slots, legacy vs MCQ support, 64-bit addressing."},
        {"name": "VER", "long_name": "UFS Version", "description": "UFSHCI version (e.g. 4.0)."},
        {"name": "HCS", "long_name": "Host Controller Status", "description": "Device-present, UTP ready, error status."},
        {"name": "HCE", "long_name": "Host Controller Enable", "description": "Enables the host controller and triggers UniPro link startup."},
        {"name": "IS / IE", "long_name": "Interrupt Status / Interrupt Enable", "description": "Aggregated interrupt status and mask."},
        {"name": "UTRLBA / UTRLBAU", "long_name": "UTP Transfer Request List Base Address (lower/upper)", "description": "Base address of the legacy Transfer Request List (UTRD ring)."},
        {"name": "UTRLDBR", "long_name": "UTP Transfer Request List Doorbell", "description": "Legacy doorbell; one bit per transfer-request slot (task tag)."},
        {"name": "UTMRLBA / UTMRLBAU", "long_name": "UTP Task Management Request List Base Address", "description": "Base address of the task-management request list."},
        {"name": "UTMRLDBR", "long_name": "UTP Task Management Request List Doorbell", "description": "Task-management doorbell."},
        {"name": "UICCMD / UCMDARG", "long_name": "UIC Command + Arguments", "description": "UniPro Interface Control (DME) command interface for M-PHY/UniPro power-mode and gear control."},
        {"name": "MCQ registers", "long_name": "Multi-Circular Queue configuration + per-queue doorbells (UFSHCI 4.0)", "description": "Per-queue submission/completion base addresses, head/tail pointers, and doorbells for native multi-queue operation."},
    ]
    d["device_descriptors"] = [
        {"name": "Device Descriptor", "description": "Top-level device identity, spec version, number of LUNs, bootable flag, UFS features."},
        {"name": "Configuration Descriptor", "description": "Host-writable LUN provisioning (size, type, write-protect, memory type) applied via Query writes."},
        {"name": "Unit Descriptor", "description": "Per-LUN parameters (logical block size, capacity, write-protect, memory type, provisioning)."},
        {"name": "Geometry Descriptor", "description": "Device geometry (total capacity, segment/allocation-unit sizes, RPMB region size)."},
        {"name": "Interconnect Descriptor", "description": "UniPro/M-PHY version and link parameters."},
        {"name": "Device Health Descriptor", "description": "Pre-EOL information, device life-time estimation."},
        {"name": "Power Parameters Descriptor", "description": "Active/sleep power levels."},
        {"name": "String Descriptor", "description": "Unicode strings (manufacturer, product name, serial number, OEM ID)."},
    ]
    d["device_attributes_examples"] = [
        {"name": "bMaxNumOfRTT", "description": "Maximum number of outstanding RTT UPIUs the host may have."},
        {"name": "bCurrentPowerMode", "description": "Current UFS power mode."},
        {"name": "bActiveICCLevel", "description": "Active interface configuration / current-limit level."},
        {"name": "dCurrentLBASize / bRefClkFreq", "description": "Current logical block size / reference clock frequency selection."},
        {"name": "bWriteBoosterBufferType / dWriteBoosterBufferSize", "description": "WriteBooster buffer configuration."},
    ]
    d["device_flags_examples"] = [
        {"name": "fDeviceInit", "description": "Set by host to start device initialization; device clears it when ready."},
        {"name": "fPermanentWPEn", "description": "Permanent write-protect enable."},
        {"name": "fPowerOnWPEn", "description": "Power-on write-protect enable."},
        {"name": "fWriteBoosterEn", "description": "Enable the WriteBooster buffer."},
        {"name": "fHpbEn", "description": "Enable Host Performance Booster."},
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L5 ADI
# ---------------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    # UFS genuinely has an analog M-PHY physical layer (override SD/MMC False).
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "The UFS physical layer is MIPI M-PHY 5.0, a high-speed differential "
        "serial interface (LVDS-style, impedance-controlled differential "
        "pairs). M-PHY transmits using two signaling families: a high-speed "
        "(HS) mode using 8b/10b line coding (HS-Gear 1..5) and a low-speed "
        "(LS) mode using PWM encoding. UFS 4.0 HS-Gear 5 = 23.2 Gbit/s per "
        "lane. Communication occurs in bursts with extended low-power idle "
        "periods (SLEEP / STALL / HIBERN8) between bursts, suiting "
        "battery-powered mobile devices. The host supplies a reference clock "
        "(REF_CLK) and an active-low RESET_n; data flows on separate device "
        "TX (DOUT) and RX (DIN) differential pairs (up to 2 lanes each "
        "direction).")
    # Remove SD/MMC-only voltage-class structures.
    for stale in ("voltage_classes", "input_threshold_levels_3v3",
                  "input_threshold_levels_1v8"):
        d.pop(stale, None)
    d.setdefault("phy_layer", "MIPI M-PHY 5.0 (embedded-clock serial; supersedes D-PHY for storage)")
    d.setdefault("power_modes_mphy", [
        {"name": "HS-BURST", "description": "High-speed burst transmission (8b/10b), HS-Gear 1..5."},
        {"name": "PWM-BURST", "description": "Low-speed PWM-encoded burst for low data rates / startup."},
        {"name": "SLEEP", "description": "Low-power idle in low-speed (SYS) state."},
        {"name": "STALL", "description": "Low-power idle in high-speed (SYS) state."},
        {"name": "HIBERN8", "description": "Deepest line low-power state with fast wake; lanes parked while retaining configuration."},
    ])
    d.setdefault("gear_table", [
        {"gear": "HS-Gear 1", "rate_class": "1.25 / 1.45 Gbit/s per lane (Rate A / B)"},
        {"gear": "HS-Gear 2", "rate_class": "2.5 / 2.9 Gbit/s per lane"},
        {"gear": "HS-Gear 3", "rate_class": "5.0 / 5.8 Gbit/s per lane"},
        {"gear": "HS-Gear 4", "rate_class": "11.6 Gbit/s per lane (UFS 3.x, M-PHY 4.1)"},
        {"gear": "HS-Gear 5", "rate_class": "23.2 Gbit/s per lane (UFS 4.0, M-PHY 5.0)"},
    ])
    d.setdefault("power_rails", [
        {"name": "VCC", "purpose": "NAND core supply (typically ~2.5 V or ~3.3 V class for the flash array)."},
        {"name": "VCCQ", "purpose": "Low-voltage core / controller logic supply (~1.2 V class)."},
        {"name": "VCCQ2", "purpose": "Interface / I/O supply for the M-PHY and reference clock domain (~1.8 V class)."},
    ])
    d["notes"] = (
        "Unlike a purely digital wire-level protocol, UFS genuinely contains "
        "an analog physical layer: the M-PHY uses differential signaling over "
        "impedance-controlled traces with electrical termination, line "
        "equalization at HS-Gear 5, and analog low-power idle states. The "
        "internal NAND flash array, charge pumps and read-margining circuitry "
        "are additionally analog but vendor-specific and out of scope of the "
        "JESD220 interface definition; M-PHY electrical signoff is at the "
        "differential lane pads.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L6 control logic
# ---------------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-override SD/MMC card state machine with the UFS device FSM.
    for stale in ("fsm_states_card", "fsm_states_host", "fsm_transitions_major"):
        d.pop(stale, None)
    d["fsm_states_device"] = [
        {"name": "POWER_OFF", "description": "No supply / RESET_n asserted; device unpowered."},
        {"name": "LINK_STARTUP", "description": "After reset, M-PHY and UniPro perform the link startup sequence (DME link startup, power-mode negotiation)."},
        {"name": "DEVICE_INIT", "description": "Host sets fDeviceInit flag (Query); device initializes internal structures and clears fDeviceInit when ready."},
        {"name": "IDLE", "description": "Link active, no outstanding tasks; device awaits UPIUs."},
        {"name": "COMMAND_EXEC", "description": "Device executing a SCSI/UFS command from a Command UPIU."},
        {"name": "DATA_TRANSFER", "description": "Device issuing RTT + receiving Data Out UPIUs (write) or sending Data In UPIUs (read)."},
        {"name": "TASK_MGMT", "description": "Device processing a Task Management Request (ABORT TASK / LU RESET / etc.)."},
        {"name": "LOW_POWER", "description": "M-PHY in SLEEP / STALL / HIBERN8; UniPro link parked; fast wake on host activity."},
    ]
    d["fsm_states_host_controller"] = [
        {"name": "HC_DISABLED", "description": "UFSHCI disabled (HCE=0)."},
        {"name": "HC_LINK_STARTUP", "description": "Host enables HCE, drives UIC link startup via UICCMD, brings M-PHY to HS-Gear."},
        {"name": "HC_DEVICE_INIT", "description": "Host sends NOP Out / NOP In handshake then sets fDeviceInit and reads device Descriptors via Query."},
        {"name": "HC_CONFIG", "description": "Host provisions LUNs (Configuration Descriptor), sets bMaxNumOfRTT, enables WriteBooster/HPB as desired."},
        {"name": "HC_RUN", "description": "Host submits transfer requests (legacy UTRD doorbell or MCQ submission queues) and reaps completions."},
        {"name": "HC_LOW_POWER", "description": "Host requests M-PHY power-mode change to HIBERN8 for idle power saving."},
    ]
    d["fsm_hints"] = {
        "trigger": "Host always initiates transactions by submitting UPIUs; the device never initiates a command. Link startup must complete before any UPIU exchange.",
        "rule": "Device init handshake: host sends NOP Out, device replies NOP In, host sets fDeviceInit flag, device clears it when internal init completes.",
        "abort": "Task Management Request UPIU (ABORT TASK / ABORT TASK SET / CLEAR TASK SET / LOGICAL UNIT RESET) aborts outstanding work; a full UniPro link reset re-initializes the link.",
    }
    d["anti_deadlock_rule"] = (
        "Write data flow is bounded by Ready-To-Transfer (RTT) UPIUs and "
        "bMaxNumOfRTT, so the host can never overrun the device buffer. "
        "UniPro provides credit-based flow control at the data-link layer; "
        "persistent transport errors escalate to UniPro error recovery rather "
        "than blocking indefinitely.")
    d["exit_from_reset_or_poweron"] = (
        "On RESET_n release / power-on the M-PHY+UniPro execute the link "
        "startup sequence to negotiate lanes and power mode; the host then "
        "performs the NOP handshake and sets fDeviceInit. Only after "
        "fDeviceInit clears does normal SCSI/UPIU I/O begin.")
    d["default_ready_state_recommendation"] = {
        "REF_CLK": "Driven by host at the configured frequency (selected via bRefClkFreq) before link startup.",
        "RESET_n": "Held LOW during reset; released to HIGH to start the link.",
        "M-PHY lanes": "Parked in HIBERN8 / SLEEP when idle; brought to HS-BURST for high-speed transfer.",
    }
    d["configurations"] = [
        {"name": "Legacy single-queue", "description": "One Transfer Request List (UTRD ring) with a single doorbell; SCSI Tagged Command Queuing across task tags."},
        {"name": "MCQ multi-queue (UFSHCI 4.0)", "description": "Multiple submission/completion queue pairs, each with its own doorbell; higher concurrency and multi-core scaling."},
    ]
    d["timing_dependency_rule"] = (
        "All high-speed data movement is bursty and clocked by the M-PHY "
        "recovered/embedded clock; the host's REF_CLK seeds the device PLL. "
        "Power-mode and gear transitions (PWM <-> HS-Gear, HIBERN8 "
        "entry/exit) are negotiated through the UniPro DME (Device Management "
        "Entity) via UIC commands before data transfer, so the host and "
        "device always agree on the active gear and lane count.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L7 test/debug
# ---------------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = "partial"
    d["spec_provided_observability"] = [
        {"name": "Response UPIU status + SCSI sense data", "purpose": "Every command returns a Response UPIU with SCSI status (GOOD / CHECK CONDITION) and sense data for error diagnosis."},
        {"name": "Reject UPIU", "purpose": "Device reports invalid/unsupported UPIUs explicitly."},
        {"name": "Device Health Descriptor", "purpose": "Pre-EOL information and estimated device life-time (bDeviceLifeTimeEstA/B) for endurance monitoring."},
        {"name": "Query Attributes/Flags", "purpose": "Read current power mode, RTT limits, error counters, and feature-enable state without the SCSI path."},
        {"name": "UFSHCI Interrupt Status (IS) + error registers", "purpose": "Host controller reports UTP errors, UIC errors, and link-layer error aggregation."},
        {"name": "UniPro DME error counters", "purpose": "UniPro Device Management Entity exposes PHY-adapter and data-link error counters via UIC GET commands."},
    ]
    d["scope_observability"] = [
        "High-speed differential probing of the M-PHY lane pairs requires a high-bandwidth oscilloscope and a UFS/M-PHY protocol analyzer; eye-diagram and gear/power-mode transitions are observable at the lane.",
        "Protocol analyzers decode UniPro frames and UPIU transactions to trace command/response/data flow.",
        "RESET_n and REF_CLK are low-speed and directly probeable.",
    ]
    d["ate_or_dft"] = (
        "Internal NAND test, ECC scrub, scan and BIST are vendor-specific and "
        "accessed at wafer/package probe, not exposed over the UFS link. The "
        "link-level observability is via UPIU status, Query "
        "Descriptors/Attributes/Flags, UFSHCI error registers, and UniPro DME "
        "counters.")
    d["notes"] = (
        "UFS does not define a JTAG/scan port on the device package edge. "
        "Host-side debug relies on (a) Response UPIU status + SCSI sense, "
        "(b) Reject UPIUs, (c) Query-readable Health/Attributes, (d) UFSHCI "
        "interrupt/error registers, and (e) M-PHY/UniPro protocol-analyzer "
        "captures of the differential lanes.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 RTL constants
# ---------------------------------------------------------------------------
def _l8_const(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-override SD/MMC width_parameters (different protocol constants).
    d["width_parameters"] = {
        "MAX_LANES_PER_DIRECTION": 2,
        "HS_GEAR_MAX": 5,
        "MPHY_VERSION": "5.0",
        "UNIPRO_VERSION": "2.0",
        "UFSHCI_VERSION": "4.0",
        "HS_GEAR5_RATE_GBPS_PER_LANE": 23.2,
        "HS_GEAR4_RATE_GBPS_PER_LANE": 11.6,
        "RPMB_AUTH_KEY_BITS": 256,
        "RPMB_MAC_ALGORITHM": "HMAC-SHA256",
        "LINE_CODE_HS": "8b/10b",
        "LINE_CODE_LS": "PWM",
    }
    # Remove SD/MMC-only constant blocks.
    for stale in ("crc_polynomials", "voltage_levels", "clock_constants",
                  "max_throughput_table", "tuning_block_constants"):
        d.pop(stale, None)
    d["speed_generation_table"] = [
        {"ufs_version": "1.x", "hs_gear": "1", "rate_gbps_per_lane": 1.45, "mphy": "1.0", "unipro": "1.4"},
        {"ufs_version": "2.0/2.1", "hs_gear": "3", "rate_gbps_per_lane": 5.8, "mphy": "3.x", "unipro": "1.6"},
        {"ufs_version": "3.0/3.1", "hs_gear": "4", "rate_gbps_per_lane": 11.6, "mphy": "4.1", "unipro": "1.8"},
        {"ufs_version": "4.0", "hs_gear": "5", "rate_gbps_per_lane": 23.2, "mphy": "5.0", "unipro": "2.0"},
    ]
    d["upiu_transaction_type_enum"] = {
        "NOP_OUT": "host -> device no-operation",
        "NOP_IN": "device -> host no-operation",
        "COMMAND": "host -> device SCSI/UFS CDB",
        "RESPONSE": "device -> host status + sense",
        "DATA_OUT": "host -> device write payload",
        "DATA_IN": "device -> host read payload",
        "READY_TO_TRANSFER": "device -> host write flow-control token (RTT)",
        "TASK_MGMT_REQUEST": "host -> device task management",
        "TASK_MGMT_RESPONSE": "device -> host task-management result",
        "QUERY_REQUEST": "host -> device descriptor/attribute/flag access",
        "QUERY_RESPONSE": "device -> host query result",
        "REJECT": "device -> host invalid-UPIU rejection",
    }
    d["well_known_lun_enum"] = {
        "REPORT_LUNS_WLUN": "enumerate active LUNs",
        "UFS_DEVICE_WLUN": "device-level commands / power management",
        "BOOT_WLUN": "boot partition (bBootLunEn)",
        "RPMB_WLUN": "Replay Protected Memory Block",
    }
    d["key_constants_for_RTL_authoring"] = {
        "host_initiates_all_transactions": True,
        "is_layered_protocol": True,
        "physical_layer": "MIPI M-PHY 5.0",
        "transport_layer": "MIPI UniPro v2.0",
        "command_set": "SCSI-based (UFS Command Set)",
        "write_flow_control": "Ready-To-Transfer (RTT) UPIU, bounded by bMaxNumOfRTT",
        "command_queueing_legacy": "single Transfer Request List (UTRD) + doorbell, one bit per task tag",
        "command_queueing_native": "MCQ (Multi-Circular Queue) submission/completion pairs",
        "rpmb_replay_protection": "monotonic write counter + HMAC-SHA256 over the RPMB frame",
        "low_power_idle_state": "HIBERN8",
        "full_duplex": True,
    }
    d["default_signal_values_when_idle"] = {
        "REF_CLK": "Host-driven at the configured reference frequency.",
        "RESET_n": "HIGH (deasserted) during normal operation; LOW resets the device.",
        "M-PHY lanes": "Parked in HIBERN8 / SLEEP between bursts.",
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 TIMING
# ---------------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-override SD/MMC timing waveforms with the M-PHY/UniPro timing.
    for stale in ("clock_waveform", "cmd_frame_waveform", "data_block_waveform",
                  "busy_waveform", "voltage_switch_waveform_uhs_i",
                  "timing_tables_referenced", "voltage_thresholds"):
        d.pop(stale, None)
    d["physical_layer_timing"] = {
        "phy": "MIPI M-PHY 5.0",
        "line_coding_hs": "8b/10b (HS-BURST)",
        "line_coding_ls": "PWM (PWM-BURST)",
        "hs_gear5_rate_gbps_per_lane": 23.2,
        "embedded_clock": "M-PHY uses an embedded/recovered clock; the host supplies REF_CLK to seed the device PLL.",
        "burst_oriented": "Communication occurs in bursts separated by low-power idle (SLEEP / STALL / HIBERN8) states.",
    }
    d["link_startup_sequence"] = {
        "step_1": "Host releases RESET_n and enables the host controller (HCE=1).",
        "step_2": "M-PHY performs lane discovery; UniPro DME executes the link startup sequence.",
        "step_3": "Host issues UIC commands to negotiate power mode and HS-Gear (e.g. HS-Gear 5, 2 lanes).",
        "step_4": "Host and device exchange NOP Out / NOP In to confirm the transport is up.",
        "step_5": "Host sets fDeviceInit; device clears it when internal initialization completes.",
    }
    d["write_transfer_waveform"] = {
        "step_1": "Host submits a Command UPIU (WRITE) referencing a LUN and LBA range.",
        "step_2": "Device sends one or more Ready-To-Transfer (RTT) UPIUs granting write-data credit (bounded by bMaxNumOfRTT).",
        "step_3": "Host sends Data Out UPIUs up to the granted amount.",
        "step_4": "Device returns a Response UPIU with final status when the write completes.",
    }
    d["read_transfer_waveform"] = {
        "step_1": "Host submits a Command UPIU (READ).",
        "step_2": "Device returns Data In UPIUs with the read payload.",
        "step_3": "Device returns a Response UPIU with final status.",
    }
    d["power_mode_transitions"] = {
        "HIBERN8_ENTER": "Host requests HIBERN8 via UIC command; lanes park while retaining configuration for fast wake.",
        "HIBERN8_EXIT": "Host or device activity triggers fast wake back to the previously negotiated gear.",
        "gear_change": "PWM <-> HS-Gear transitions and lane-count changes are negotiated via the UniPro DME before high-speed transfer.",
    }
    d["general_timing_rule"] = (
        "All high-speed bus timing is defined by the MIPI M-PHY 5.0 "
        "electrical specification (eye width/height, jitter, equalization per "
        "HS-Gear) and the UniPro v2.0 data-link timing (credit-based flow "
        "control, retransmission timeouts). The host-supplied REF_CLK "
        "frequency is selected via the bRefClkFreq attribute. Detailed "
        "electrical timing tables are normative in the MIPI M-PHY "
        "specification referenced by JESD220.")
    d["voltage_signaling"] = {
        "type": "Differential (LVDS-style) on M-PHY lane pairs",
        "interface_rail": "VCCQ2 (~1.8 V class) for the M-PHY/REF_CLK domain",
        "termination": "Impedance-controlled differential termination at HS gears",
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L9 integration
# ---------------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Point-to-point high-speed storage interface between a UFS host "
        "controller (master, per UFSHCI/JESD223) and a UFS device (slave, per "
        "UFS/JESD220). Defines the layered stack (M-PHY physical + UniPro "
        "transport + UPIU/UTP + SCSI command set) and the UFSHCI "
        "register/queue model. A concrete UFS host controller IP integrates "
        "the UFSHCI register file behind a system bus (AXI/AHB) and a "
        "UniPro+M-PHY hard-macro PHY.")
    # Force-override SD/MMC top_module + integration_overview.
    _ptm.apply(d, "UFS_Device")
    for stale in ("integration_overview", "pull_up_resistors"):
        d.pop(stale, None)
    d["integration_overview"] = {
        "link_type": "Point-to-point host <-> device (no shared bus, no multi-drop).",
        "max_lanes_per_direction": 2,
        "phy": "MIPI M-PHY 5.0 differential RX/TX lane pairs.",
        "transport": "MIPI UniPro v2.0.",
        "sideband": "REF_CLK (host -> device) and RESET_n (host -> device, active low).",
        "command_model": "Host submits UPIUs via UFSHCI; legacy single Transfer Request List or native MCQ.",
        "full_duplex": "Independent TX and RX lanes allow simultaneous bidirectional transfer.",
    }
    d["interface_categories"] = [
        "Power (VCC NAND core, VCCQ logic, VCCQ2 interface, VSS ground)",
        "Reference clock (REF_CLK)",
        "Reset (RESET_n)",
        "M-PHY high-speed differential lanes (DOUT TX pairs, DIN RX pairs, up to 2 each direction)",
    ]
    d["interconnect_topologies_supported"] = [
        "Single host + single embedded UFS device (eUFS, BGA solder-down)",
        "Single host + single removable UFS card (UFS Card Extension)",
        "Single-lane or dual-lane M-PHY configurations",
    ]
    d["default_signal_values_when_omitted"] = (
        "REF_CLK is driven by the host at the frequency selected via "
        "bRefClkFreq. RESET_n idles HIGH. M-PHY lanes are parked in HIBERN8 / "
        "SLEEP when no transfer is in progress; the link must be brought up "
        "via the UniPro startup sequence before UPIU exchange.")
    d["soc_dependent_items"] = [
        "UFS host controller (UFSHCI 4.0) register file behind the SoC system bus (AXI/AHB).",
        "UniPro + M-PHY hard-macro PHY with PLL seeded by REF_CLK.",
        "Reference clock source (e.g. 19.2 / 26 / 38.4 / 52 MHz, selected via bRefClkFreq).",
        "Power-rail regulators for VCC (NAND), VCCQ (logic), VCCQ2 (interface).",
        "DMA / scatter-gather engine for UTP transfer descriptors / MCQ.",
        "Interrupt routing for UFSHCI completion / error events (legacy doorbell or MCQ completion queues).",
        "Secure key provisioning path for the RPMB 256-bit authentication key.",
    ]
    lpm = _ensure_dict(d, "low_power_modes")
    # Clear SD/MMC sub-keys then set the UFS shape.
    for stale in ("Clock_Stop", "Sleep", "Power_Off", "FXE_Power_Management"):
        lpm.pop(stale, None)
    lpm["HIBERN8"] = "Deepest M-PHY line low-power state with fast wake; the primary idle state."
    lpm["SLEEP"] = "Device sleep power mode (UFS power mode), reduces device activity."
    lpm["Deep Sleep"] = "Lower-power device state (UFS 3.1+) with longer wake latency."
    lpm["Power_Off"] = "Host removes supplies; full state loss (boot LU repopulated on next power-up)."
    d["compatibility_notes"] = [
        "UFS is the successor to eMMC; both are JEDEC mobile-storage standards, but UFS uses a full-duplex M-PHY/UniPro serial link and a SCSI/UPIU command model, whereas eMMC uses a parallel half-duplex bus with a CMD/DAT command-line protocol.",
        "UFS 4.0 (M-PHY 5.0, UniPro 2.0, HS-Gear 5) is backward-interoperable down to lower gears for link startup; the host and device negotiate the highest mutually supported gear.",
        "The UFS Card Extension (JESD220-2/-3) reuses the same protocol stack for removable cards with additions for hot-removal.",
    ]
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
        "partial - the spec defines the layered stack, UPIU transaction "
        "types, descriptor/attribute/flag set, command queueing models and "
        "power modes that map directly to compliance test scenarios; "
        "JEDEC/MIPI maintain separate normative conformance test suites (UFS, "
        "UFSHCI, UniPro, M-PHY CTS) out of scope of this extraction.")
    d["derived_compliance_test_categories"] = [
        "Link startup - RESET_n release -> M-PHY lane discovery -> UniPro DME link startup -> power-mode/gear negotiation (verify HS-Gear 5, 2 lanes for UFS 4.0).",
        "Device init handshake - NOP Out / NOP In exchange, set fDeviceInit flag, verify device clears it when ready.",
        "Query Request - read Device / Configuration / Unit / Geometry / Health Descriptors; read/write Attributes and Flags.",
        "LUN provisioning - write Configuration Descriptor to create normal LUNs; enumerate via REPORT LUNS W-LUN.",
        "Well-known LUN access - REPORT LUNS, UFS DEVICE, BOOT, RPMB W-LUNs respond correctly.",
        "Command UPIU READ - single and multi-block reads; verify Data In UPIUs + Response UPIU GOOD status.",
        "Command UPIU WRITE - verify device issues RTT UPIUs, host sends Data Out UPIUs up to bMaxNumOfRTT, Response UPIU GOOD.",
        "RTT flow control - exceed/respect bMaxNumOfRTT; verify host never overruns device buffer.",
        "Task Management - ABORT TASK, ABORT TASK SET, CLEAR TASK SET, LOGICAL UNIT RESET, QUERY TASK via Task Management Request UPIUs.",
        "Reject UPIU - send an invalid/unsupported UPIU; verify device returns Reject UPIU.",
        "SCSI error path - induce CHECK CONDITION; verify Response UPIU sense data via REQUEST SENSE.",
        "RPMB - program 256-bit auth key; authenticated write with HMAC-SHA256 + monotonic write counter; verify replay/MAC-mismatch is rejected.",
        "WriteBooster - enable fWriteBoosterEn; verify higher burst write throughput and flush behavior.",
        "HPB (optional) - enable fHpbEn; verify L2P cache hit reduces read latency (Host-control / Device-control mode).",
        "MCQ (UFSHCI 4.0) - configure multiple submission/completion queue pairs; verify per-queue doorbells and out-of-order completion.",
        "Legacy queueing - single Transfer Request List doorbell, SCSI Tagged Command Queuing across task tags.",
        "Power modes - enter/exit HIBERN8; SLEEP / Deep Sleep transitions; verify fast wake.",
        "Gear/lane negotiation - fall back to lower gears for interop; verify negotiated gear matches both endpoints.",
        "UNMAP / SYNCHRONIZE CACHE - discard blocks and flush write cache.",
        "Boot - read from BOOT W-LUN per bBootLunEn provisioning.",
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
    d["otp_summary"] = (
        "UFS exposes several one-time-programmable / permanent surfaces. The "
        "RPMB authentication key is a one-time-programmed 256-bit secret "
        "(programmable exactly once; subsequent program attempts fail). "
        "Permanent write-protect (fPermanentWPEn) is an irreversible flag. "
        "The device serial number, manufacturer ID and product name (String "
        "Descriptors) are factory-programmed and read-only. LUN provisioning "
        "written to the Configuration Descriptor can be made permanent.")
    # Remove SD/MMC-only OTP register list.
    d.pop("otp_registers", None)
    d["otp_or_permanent_items"] = [
        {"name": "RPMB Authentication Key", "width_bits": 256, "factory_programmed": False, "host_programmable_once": True,
         "description": "256-bit secret programmed exactly once (typically during secure provisioning). After programming, the key cannot be read back or reprogrammed; it is used to compute the HMAC-SHA256 MAC over every RPMB frame."},
        {"name": "fPermanentWPEn (Permanent Write Protect)", "factory_programmed": False, "host_programmable": "one-shot",
         "description": "Boolean flag that permanently write-protects the configured area; once set it can never be cleared (irreversible)."},
        {"name": "Device String Descriptors (Manufacturer / Product Name / Serial Number / OEM ID)", "factory_programmed": True, "host_programmable": False,
         "description": "Factory-programmed Unicode identity strings, read-only over the link; serve as the device fingerprint."},
        {"name": "Configuration Descriptor (LUN provisioning)", "factory_programmed": False, "host_programmable": "lockable",
         "description": "Host-written LUN layout (sizes, types, write-protect); can be configured once and then locked by setting the appropriate descriptor lock / permanent write-protect flags."},
    ]
    d["non_otp_device_state"] = (
        "Runtime attributes (bCurrentPowerMode, bMaxNumOfRTT), flags "
        "(fDeviceInit, fWriteBoosterEn, fHpbEn), and the RPMB write counter "
        "are dynamic / volatile or monotonically updated. The RPMB monotonic "
        "write counter only ever increments and is part of the anti-replay "
        "mechanism (not itself OTP, but irreversibly increasing).")
    d["notes"] = (
        "From a security standpoint the RPMB 256-bit key is the most "
        "safety-critical OTP-style item: it is write-once, never-readable, "
        "and underpins the HMAC-SHA256 replay-protection of the RPMB region "
        "(anti-rollback counters, secure boot state, DRM secrets). "
        "fPermanentWPEn is the most safety-critical permanent flag.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L12 behavioral sequences
# ---------------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove SD/MMC-only sequences.
    for stale in ("initialization_sequence", "single_block_read_sequence",
                  "multi_block_read_sequence", "single_block_write_sequence",
                  "multi_block_write_sequence", "erase_sequence",
                  "voltage_switch_sequence_uhs_i",
                  "tuning_sequence_uhs_i_sdr104", "hot_removal_recovery"):
        d.pop(stale, None)
    d["link_startup_and_init_sequence"] = [
        "1. Host applies power rails (VCC, VCCQ, VCCQ2) and drives REF_CLK; RESET_n is held LOW then released HIGH.",
        "2. Host enables the UFS host controller (UFSHCI HCE=1).",
        "3. M-PHY performs lane discovery; UniPro DME executes the link startup sequence.",
        "4. Host issues UIC commands to negotiate the power mode and HS-Gear (e.g. HS-Gear 5, 2 lanes for UFS 4.0).",
        "5. Host sends a NOP Out UPIU; device replies with a NOP In UPIU (transport confirmed up).",
        "6. Host sets the fDeviceInit flag via a Query Request UPIU; device performs internal initialization and clears fDeviceInit.",
        "7. Host reads the Device / Geometry / Unit Descriptors via Query Request UPIUs and reads bMaxNumOfRTT.",
        "8. Host provisions LUNs (writes Configuration Descriptor) if not already provisioned, and enumerates via REPORT LUNS (W-LUN).",
        "9. (Optional) Host enables WriteBooster (fWriteBoosterEn) and/or HPB (fHpbEn).",
        "10. Device is now ready for SCSI/UFS I/O (READ / WRITE / etc.).",
    ]
    d["read_sequence"] = [
        "1. Host submits a Command UPIU carrying a SCSI READ CDB (LUN + LBA + transfer length).",
        "2. Device returns one or more Data In UPIUs with the read payload.",
        "3. Device returns a Response UPIU with GOOD status (or CHECK CONDITION + sense on error).",
        "4. Under MCQ, the controller posts the completion to the Completion Queue and rings the completion doorbell.",
    ]
    d["write_sequence"] = [
        "1. Host submits a Command UPIU carrying a SCSI WRITE CDB.",
        "2. Device returns one or more Ready-To-Transfer (RTT) UPIUs, each granting a chunk of write-data credit (total outstanding bounded by bMaxNumOfRTT).",
        "3. Host sends Data Out UPIUs up to the granted credit.",
        "4. Device writes the data (optionally via the WriteBooster pseudo-SLC buffer) and returns a Response UPIU with final status.",
    ]
    d["query_sequence"] = [
        "1. Host submits a Query Request UPIU (read/write Descriptor, read/write/set/clear/toggle Attribute or Flag).",
        "2. Device returns a Query Response UPIU with the requested object or completion status.",
    ]
    d["task_management_sequence"] = [
        "1. Host submits a Task Management Request UPIU (e.g. ABORT TASK for a given task tag, or LOGICAL UNIT RESET for a LUN).",
        "2. Device performs the function and returns a Task Management Response UPIU with the result.",
        "3. On persistent transport failure, the host may force a UniPro link reset and re-run the link startup sequence.",
    ]
    d["rpmb_authenticated_write_sequence"] = [
        "1. (One-time) Host programs the 256-bit RPMB authentication key (write-once).",
        "2. Host reads the current RPMB write counter (authenticated read).",
        "3. Host builds an RPMB data frame (address, block count, data, nonce, write counter) and computes an HMAC-SHA256 MAC over the frame using the key.",
        "4. Host issues the authenticated write via SECURITY PROTOCOL OUT to the RPMB W-LUN.",
        "5. Device verifies the MAC and that the supplied write counter matches; on success it writes the data, increments the write counter, and returns a result frame with the new counter; on MAC/counter mismatch it rejects the write (anti-replay).",
    ]
    d["power_mode_sequence"] = [
        "1. When idle, host requests HIBERN8 entry via a UIC command; M-PHY lanes park while retaining configuration.",
        "2. On new activity, host (or device) triggers HIBERN8 exit (fast wake) back to the previously negotiated gear.",
        "3. For deeper saving, host may move the device to SLEEP / Deep Sleep power modes via the UFS DEVICE W-LUN / Query path.",
    ]
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
    d["calibration_summary"] = (
        "Unlike a purely digital protocol, UFS has a genuine high-speed "
        "analog physical layer (MIPI M-PHY 5.0) that requires link-level "
        "adaptation and electrical characterization. The principal closed "
        "loops are: (1) M-PHY/UniPro link startup with power-mode and HS-Gear "
        "negotiation; (2) high-speed receiver equalization / adaptation at "
        "HS-Gear 4/5; (3) reference-clock frequency selection. These are "
        "host-and-PHY-controlled; the host adapts the link to the device's "
        "capabilities rather than trimming the device.")
    # Remove SD/MMC-only calibration blocks.
    for stale in ("voltage_switch_sequence", "tuning_procedure_uhs_i",
                  "no_card_side_trim", "vdd_ramp_characterization"):
        d.pop(stale, None)
    d["link_adaptation_loop"] = {
        "purpose": "Bring the M-PHY/UniPro link from PWM-BURST startup up to the highest mutually supported HS-Gear and lane count.",
        "procedure": [
            "Execute UniPro DME link startup at low speed (PWM).",
            "Read both endpoints' M-PHY/UniPro capabilities (max gear, lane count, rate series A/B).",
            "Issue UIC power-mode-change commands to step up to the negotiated HS-Gear (e.g. HS-Gear 5) and lane count (up to 2).",
            "Verify the link is stable at the target gear before enabling high-speed data transfer.",
        ],
    }
    d["hs_equalization_loop"] = {
        "purpose": "At HS-Gear 4/5 the M-PHY receiver applies equalization/adaptation to open the eye over the channel.",
        "note": "Equalization parameters and adaptation are part of the MIPI M-PHY 5.0 electrical specification and the PHY hard-macro; characterized on the bench with a high-bandwidth scope and an M-PHY compliance/CTS fixture.",
    }
    d["reference_clock_selection"] = {
        "purpose": "The device PLL is seeded by the host REF_CLK; the host selects the reference frequency via the bRefClkFreq attribute.",
        "typical_frequencies_MHz": [19.2, 26, 38.4, 52],
    }
    d["no_device_side_analog_trim_on_link"] = (
        "The UFS link does not expose vendor analog NAND trim registers; "
        "internal read-margining and charge-pump trim are vendor-specific and "
        "not visible over the UFS interface. Link-level adaptation is the "
        "host/PHY's responsibility.")
    d["notes"] = (
        "M-PHY electrical compliance (eye diagram, jitter, equalization per "
        "HS-Gear) and UniPro link-startup interoperability are verified "
        "against the MIPI M-PHY and UniPro conformance test suites referenced "
        "by JESD220; these are the lab-bench calibration/characterization "
        "activities for a UFS interface.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L14 protocol versioning
# ---------------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["spec_version"] = ("UFS 4.0 (JEDEC JESD220) with UFSHCI 4.0 (JESD223), "
                         "M-PHY 5.0, UniPro v2.0 (August 17, 2022)")
    # Remove SD/MMC-only lineage keys.
    for stale in ("spec_lineage_sd", "spec_lineage_mmc_emmc_sibling"):
        f.pop(stale, None)
    f["spec_lineage_ufs"] = [
        {"version": "1.0", "date": "February 24, 2011", "summary": "Initial JESD220 UFS standard; 300 MB/s per lane; M-PHY 1.0; UniPro 1.4."},
        {"version": "1.1", "date": "June 25, 2012", "summary": "Update to UFS v1.0."},
        {"version": "2.0", "date": "September 18, 2013", "summary": "JESD220B; increased link bandwidth, security extension, additional power saving; M-PHY 3.x; UniPro 1.6; HS-Gear 3 class."},
        {"version": "2.1", "date": "April 4, 2016", "summary": "600 MB/s per lane class."},
        {"version": "3.0", "date": "January 30, 2018", "summary": "11.6 Gbit/s per lane (1450 MB/s); M-PHY v4.1 (HS-Gear 4); UniPro v1.8."},
        {"version": "3.1", "date": "January 30, 2020", "summary": "WriteBooster, Deep Sleep, Performance Throttling Notification, Host Performance Booster (optional)."},
        {"version": "4.0", "date": "August 17, 2022", "summary": "23.2 Gbit/s per lane (2900 MB/s); M-PHY v5.0 (HS-Gear 5); UniPro v2.0; UFSHCI 4.0 MCQ; File Based Optimization."},
        {"version": "4.1 (Pro)", "date": "January 8, 2025", "summary": "Zoned Storage for UFS; same M-PHY 5.0 / UniPro 2.0 generation per-lane rate."},
    ]
    f["spec_lineage_emmc_predecessor"] = [
        {"version": "eMMC v5.0", "summary": "Predecessor JEDEC mobile-storage family; parallel half-duplex CMD/DAT bus; HS400 strobe-based 200 MHz DDR."},
        {"version": "eMMC v5.1", "summary": "Added Command Queueing (CQ) and Secure Removal; UFS is positioned as eMMC's successor with a full-duplex M-PHY/UniPro serial link and SCSI/UPIU model."},
    ]
    f["layered_spec_dependencies"] = [
        {"layer": "Physical", "spec": "MIPI M-PHY v5.0 (referenced by JESD220)"},
        {"layer": "Transport/Network/Data-link", "spec": "MIPI UniPro v2.0"},
        {"layer": "Host Controller Interface", "spec": "UFSHCI 4.0 (JEDEC JESD223)"},
        {"layer": "Command Set", "spec": "SCSI-based UFS Command Set (UCS)"},
    ]
    f["key_changes"] = [
        {"version": "UFS 3.0 (2018)", "summary": "Doubled per-lane rate to 11.6 Gbit/s (HS-Gear 4) via M-PHY 4.1 + UniPro 1.8."},
        {"version": "UFS 3.1 (2020)", "summary": "Added WriteBooster turbo-write buffer + Host Performance Booster (optional L2P caching in host DRAM)."},
        {"version": "UFS 4.0 (2022)", "summary": "Doubled per-lane rate to 23.2 Gbit/s (HS-Gear 5) via M-PHY 5.0 + UniPro 2.0; added UFSHCI 4.0 native Multi-Circular Queue (MCQ) and File Based Optimization."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "gear_negotiation_required",
         "rule": "UFS 4.0 endpoints must negotiate the highest mutually supported HS-Gear during link startup; they begin in PWM/low gear.",
         "trap": "A host that assumes HS-Gear 5 without negotiation, or that fails to fall back, will not link up with a lower-gear device."},
        {"trap_name": "mcq_vs_legacy_queue",
         "rule": "UFSHCI 4.0 supports both the legacy single Transfer Request List (doorbell per task tag) and native MCQ; the model in use is configured by the host.",
         "trap": "A driver that hard-codes the legacy doorbell model will not exploit MCQ parallelism, and a driver assuming MCQ on a controller that only advertises legacy mode will fail."},
        {"trap_name": "rpmb_key_program_once",
         "rule": "The RPMB 256-bit authentication key can be programmed exactly once and never read back.",
         "trap": "Re-provisioning flows that attempt to reprogram the key will fail; the key must be escrowed at first provisioning."},
        {"trap_name": "hpb_optional",
         "rule": "Host Performance Booster is OPTIONAL (added UFS 3.1); not all devices implement it.",
         "trap": "A host relying on HPB L2P caching must first verify device support via the Device Descriptor / flags before enabling fHpbEn."},
    ]
    f["version_naming_history_note"] = (
        "UFS is standardized by the JEDEC Solid State Technology Association "
        "as JESD220 (device) and JESD223 (UFSHCI host controller interface). "
        "The physical and transport layers are MIPI Alliance specifications "
        "(M-PHY and UniPro). The Universal Flash Storage Association (UFSA) "
        "was founded in 2010 to promote the standard. UFS is the JEDEC "
        "successor to eMMC; both share JEDEC stewardship, but UFS replaces "
        "eMMC's parallel half-duplex CMD/DAT bus with a full-duplex "
        "M-PHY/UniPro serial link and a SCSI/UPIU command model.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L15 encoding tables
# ---------------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    # Remove SD/MMC-only encoding tables.
    for stale in ("command_format_table", "response_class_table",
                  "card_state_encoding_R1_bits_12_9_table",
                  "data_response_token_write_table",
                  "command_classes_ccc_table", "ocr_register_table",
                  "crc_polynomial_table", "bus_speed_mode_uhs_i_table",
                  "card_capacity_class_table", "speed_class_table"):
        f.pop(stale, None)
    f["upiu_transaction_type_table"] = {
        "header_columns": ["UPIU", "Direction", "Purpose"],
        "rows": [
            ["NOP Out", "host -> device", "No-operation / link keep-alive"],
            ["NOP In", "device -> host", "No-operation response"],
            ["Command", "host -> device", "Carries SCSI/UFS CDB"],
            ["Response", "device -> host", "Status + SCSI sense data"],
            ["Data Out", "host -> device", "Write payload (gated by RTT)"],
            ["Data In", "device -> host", "Read payload"],
            ["Ready To Transfer (RTT)", "device -> host", "Write flow-control token"],
            ["Task Management Request", "host -> device", "ABORT TASK / LU RESET / etc."],
            ["Task Management Response", "device -> host", "Task-management result"],
            ["Query Request", "host -> device", "Descriptor / Attribute / Flag access"],
            ["Query Response", "device -> host", "Query result"],
            ["Reject", "device -> host", "Invalid / unsupported UPIU rejection"],
        ],
    }
    f["well_known_lun_table"] = {
        "header_columns": ["Well-known LUN", "Purpose"],
        "rows": [
            ["REPORT LUNS", "Enumerate active LUNs"],
            ["UFS DEVICE", "Device-level commands / power management"],
            ["BOOT", "Boot partition (bBootLunEn)"],
            ["RPMB", "Replay Protected Memory Block"],
        ],
    }
    f["speed_generation_table"] = {
        "header_columns": ["UFS Version", "HS-Gear", "Per-lane Rate", "M-PHY", "UniPro"],
        "rows": [
            ["1.0/1.1", "1", "1.45 Gbit/s (300 MB/s class)", "1.0", "1.4"],
            ["2.0/2.1", "3", "5.8 Gbit/s (600 MB/s class)", "3.x", "1.6"],
            ["3.0/3.1", "4", "11.6 Gbit/s (1450 MB/s)", "4.1", "1.8"],
            ["4.0", "5", "23.2 Gbit/s (2900 MB/s)", "5.0", "2.0"],
        ],
    }
    f["mphy_line_coding_table"] = {
        "header_columns": ["Mode", "Encoding", "Use"],
        "rows": [
            ["HS-BURST", "8b/10b", "High-speed data (HS-Gear 1..5)"],
            ["PWM-BURST", "PWM", "Low-speed data / startup"],
            ["HIBERN8", "(line low-power)", "Idle with fast wake"],
        ],
    }
    f["query_object_table"] = {
        "header_columns": ["Object", "Access", "Examples"],
        "rows": [
            ["Descriptor", "read / write", "Device, Configuration, Unit, Geometry, Health, String"],
            ["Attribute", "read / write", "bMaxNumOfRTT, bCurrentPowerMode, dCurrentLBASize"],
            ["Flag", "read / set / clear / toggle", "fDeviceInit, fPermanentWPEn, fWriteBoosterEn, fHpbEn"],
        ],
    }
    f["rpmb_frame_field_table"] = {
        "header_columns": ["Field", "Purpose"],
        "rows": [
            ["Key / MAC", "256-bit key based HMAC-SHA256 MAC over the frame"],
            ["Data", "Payload to read/write"],
            ["Nonce", "Random value for read authentication"],
            ["Write Counter", "Monotonic counter for anti-replay"],
            ["Address", "RPMB block address"],
            ["Block Count", "Number of half-sector blocks"],
            ["Result", "Operation result code"],
            ["Request/Response Type", "RPMB message type"],
        ],
    }
    f["tables"] = [
        "UPIU Transaction Type table (UFS Command Set / UTP)",
        "Well-known LUN table",
        "Descriptor / Attribute / Flag tables (Query)",
        "M-PHY HS-Gear / rate-series table (MIPI M-PHY 5.0)",
        "UniPro layer/data-unit table (MIPI UniPro v2.0)",
        "RPMB data-frame field table",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L16 compliance properties
# ---------------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["must_have_properties"] = [
        "The interface shall be layered: MIPI M-PHY (physical) + MIPI UniPro (data-link/network/transport) + UFS Transport Protocol carrying UPIUs + SCSI-based UFS Command Set.",
        "The host shall complete the UniPro/M-PHY link startup and power-mode/HS-Gear negotiation before exchanging UPIUs.",
        "Host and device shall exchange UPIUs with a Basic Header carrying Transaction Type, Flags, LUN, and Task Tag.",
        "The command set shall be SCSI-based; Command UPIUs shall carry a SCSI/UFS CDB.",
        "The device shall expose multiple LUNs plus the Well-known LUNs REPORT LUNS, UFS DEVICE, BOOT, RPMB.",
        "Write data flow shall be gated by Ready-To-Transfer (RTT) UPIUs and bounded by bMaxNumOfRTT.",
        "The device shall support task management via Task Management Request/Response UPIUs.",
        "RPMB writes shall be authenticated with HMAC-SHA256 over the frame and protected against replay by a monotonic write counter.",
        "UFS 4.0 shall use M-PHY 5.0 (HS-Gear 5, 23.2 Gbit/s per lane) and UniPro v2.0.",
        "UFSHCI 4.0 shall support both legacy single-queue (Transfer Request List + doorbell) and native MCQ submission/completion queue pairs.",
        "The device init handshake shall use NOP Out / NOP In and the fDeviceInit flag.",
    ]
    f["must_not_have_properties"] = [
        "The device shall not initiate a command transaction; the host is always the initiator.",
        "The host shall not send more write data than the device has granted via RTT (no buffer overrun).",
        "The RPMB authentication key shall not be readable, and shall not be reprogrammable after the one-time program.",
        "fPermanentWPEn shall not be clearable once set.",
        "The device shall not accept an RPMB write whose MAC or write counter does not verify (anti-replay).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Link startup failure", "trigger": "M-PHY lane discovery or UniPro DME startup fails; no UPIU exchange possible."},
        {"mode": "Gear negotiation mismatch", "trigger": "Host and device cannot agree on a mutually supported HS-Gear/lane count."},
        {"mode": "Invalid UPIU", "trigger": "Device returns a Reject UPIU for an unsupported/malformed UPIU."},
        {"mode": "SCSI CHECK CONDITION", "trigger": "Response UPIU returns CHECK CONDITION with sense data; host issues REQUEST SENSE."},
        {"mode": "RTT overrun", "trigger": "Host sends Data Out beyond granted RTT credit; protocol violation."},
        {"mode": "RPMB authentication failure", "trigger": "MAC mismatch or write-counter mismatch; device rejects the write."},
        {"mode": "Task-management timeout", "trigger": "Outstanding task does not complete; host issues ABORT TASK / LOGICAL UNIT RESET."},
        {"mode": "UniPro data-link error", "trigger": "CRC/sequence error; UniPro retransmits; persistent failure escalates to error recovery."},
    ]
    f["min_link_constraint"] = (
        "Link startup begins at low speed (PWM); the host must negotiate up "
        "to the target HS-Gear. The device PLL requires a valid host REF_CLK "
        "at a frequency selected via bRefClkFreq.")
    f["reset_behavior_compliance"] = (
        "RESET_n (active low) resets the device; on release the M-PHY/UniPro "
        "link must be re-started via the UniPro link startup sequence, "
        "followed by the NOP handshake and fDeviceInit before normal I/O. "
        "Three reset scopes exist: link reset (UniPro), logical-unit reset "
        "(Task Management), and full device reset (RESET_n / power-cycle).")
    # Strip SD/MMC-only key if present.
    f.pop("min_clock_constraint", None)
    _write(p, d)


# ---------------------------------------------------------------------------
# L17 channel/signal catalog
# ---------------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    # Remove SD/MMC-only sub-structures.
    f.pop("spi_mode_pin_aliases", None)
    f["channels"] = [
        {"name": "REF_CLK", "direction_host": "output", "direction_device": "input", "purpose": "Reference clock supplied by the host; seeds the device PLL. Frequency selected via bRefClkFreq (e.g. 19.2 / 26 / 38.4 / 52 MHz).", "active_levels": "CMOS single-ended", "idle_level": "Free-running while the link is active."},
        {"name": "RESET_n", "direction_host": "output", "direction_device": "input", "purpose": "Active-low device reset.", "active_levels": "CMOS single-ended", "idle_level": "HIGH (deasserted) in normal operation."},
        {"name": "DOUT0_t/DOUT0_c", "direction": "device -> host", "purpose": "M-PHY TX lane 0 differential pair (device transmit).", "active_levels": "Differential LVDS-style; HS-Gear 1..5 (8b/10b) or PWM.", "idle_level": "Parked in HIBERN8 / SLEEP between bursts."},
        {"name": "DIN0_t/DIN0_c", "direction": "host -> device", "purpose": "M-PHY RX lane 0 differential pair (device receive).", "active_levels": "Differential LVDS-style.", "idle_level": "Parked in HIBERN8 / SLEEP between bursts."},
        {"name": "DOUT1_t/DOUT1_c", "direction": "device -> host", "purpose": "M-PHY TX lane 1 differential pair (optional second lane).", "active_levels": "Differential LVDS-style.", "idle_level": "Parked / unused in single-lane configs."},
        {"name": "DIN1_t/DIN1_c", "direction": "host -> device", "purpose": "M-PHY RX lane 1 differential pair (optional second lane).", "active_levels": "Differential LVDS-style.", "idle_level": "Parked / unused in single-lane configs."},
    ]
    f["power_pins"] = [
        {"name": "VCC", "purpose": "NAND core supply (flash array)."},
        {"name": "VCCQ", "purpose": "Low-voltage core / controller logic supply (~1.2 V class)."},
        {"name": "VCCQ2", "purpose": "Interface / I/O supply for the M-PHY and REF_CLK domain (~1.8 V class)."},
        {"name": "VSS", "purpose": "Ground."},
    ]
    f["global_signals"] = [
        {"name": "REF_CLK", "purpose": "Host-supplied reference clock for the device PLL."},
        {"name": "RESET_n", "purpose": "Active-low global device reset."},
    ]
    f["channel_counts"] = {
        "reference_clock_lines": 1,
        "reset_lines": 1,
        "mphy_tx_lanes_max": 2,
        "mphy_rx_lanes_max": 2,
        "mphy_differential_pairs_max": 4,
        "power_pins": 3,
        "ground_pins": 1,
    }
    f["ordering_rules"] = {
        "transport_ordering": "UniPro v2.0 provides reliable in-order delivery within a CPort connection; UPIUs for a given task are delivered in order.",
        "command_ordering": "SCSI Tagged Command Queuing allows the device to complete commands out of order across task tags; under MCQ, completions are posted per completion queue.",
    }
    # Force-overwrite dependency_graph for the UFS shape (per task spec).
    f["dependency_graph"] = {
        "common_rule": "Host supplies REF_CLK and controls RESET_n. After link startup and gear negotiation, the host initiates all transactions by submitting Command/Query/Task-Management/NOP-Out UPIUs; the device responds with Response/Data-In/RTT/Query-Response/Task-Management-Response/NOP-In/Reject UPIUs. Write data is gated by RTT.",
        "data_dependency": "Read payload (Data In) and write grants (RTT) depend on a prior Command UPIU. UniPro delivers UPIUs reliably and in order; M-PHY carries UniPro frames as 8b/10b symbols in HS bursts.",
    }
    f["handshake_pairs"] = [
        {"name": "NOP_OUT_IN", "from": "host", "to": "device", "rule": "Host sends NOP Out; device replies NOP In to confirm transport is up."},
        {"name": "COMMAND_RESPONSE", "from": "host", "to": "device", "rule": "Host sends Command UPIU; device returns Data In/Out flow then a Response UPIU with status."},
        {"name": "RTT_DATAOUT", "from": "device", "to": "host", "rule": "Device sends RTT UPIU granting write credit; host sends Data Out UPIUs up to the grant (bounded by bMaxNumOfRTT)."},
        {"name": "QUERY_REQ_RESP", "from": "host", "to": "device", "rule": "Host sends Query Request; device returns Query Response with the Descriptor/Attribute/Flag."},
        {"name": "TASKMGMT_REQ_RESP", "from": "host", "to": "device", "rule": "Host sends Task Management Request; device returns Task Management Response."},
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L18 interconnect topology
# ---------------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["topology_type"] = (
        "Point-to-point host-master / device-slave high-speed serial link. "
        "One UFS host controller connects to exactly one UFS device over MIPI "
        "M-PHY differential lanes (up to 2 per direction) under the MIPI "
        "UniPro transport stack. There is no shared/multi-drop bus.")
    f["supported_topologies"] = [
        {"name": "Single host + embedded UFS device (eUFS)", "description": "BGA solder-down device; most common in mobile SoCs."},
        {"name": "Single host + removable UFS card", "description": "UFS Card Extension; same protocol stack with hot-removal handling."},
        {"name": "Single-lane M-PHY", "description": "One RX + one TX differential pair per direction; lower pin count."},
        {"name": "Dual-lane M-PHY (UFS 4.0)", "description": "Two lanes per direction at HS-Gear 5 for maximum aggregate bandwidth."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host (master)", "description": "Via the UFS host controller (UFSHCI): drives REF_CLK + RESET_n, runs link startup, negotiates gear/lanes, submits UPIUs, manages legacy/MCQ queues."},
        {"role": "Device (slave)", "description": "Responds to UPIUs; exposes LUNs and Well-known LUNs; controls write flow via RTT; never initiates a command."},
    ]
    f["interconnect_role"] = (
        "UniPro defines a routable transport (up to 128 UniPro devices via "
        "switches in the general MIPI UniPro architecture), but a UFS link is "
        "a dedicated point-to-point host<->device connection; no "
        "router/bridge is used in a UFS storage link.")
    f["ordering_guarantees"] = {
        "within_a_connection": "UniPro v2.0 provides reliable, in-order delivery of UPIUs within a CPort connection.",
        "across_commands": "SCSI Tagged Command Queuing permits out-of-order completion across task tags; MCQ posts completions per completion queue.",
    }
    f["memory_vs_peripheral_regions"] = (
        "The device exposes per-LUN logical block address (LBA) spaces "
        "(user-data LUNs) plus special Well-known LUNs (REPORT LUNS, UFS "
        "DEVICE, BOOT, RPMB). The host-side UFSHCI register file is "
        "memory-mapped in the host's address space, separate from the device "
        "LBA space.")
    f["device_classification"] = {
        "embedded_device_eUFS": "Soldered BGA UFS device in a mobile SoC.",
        "removable_card": "UFS Card Extension removable card.",
        "host_controller": "UFSHCI-compliant host controller IP integrated into the SoC, behind AXI/AHB.",
        "phy_macro": "UniPro + M-PHY hard-macro implementing the physical and transport layers.",
    }
    f["default_signal_values_evidence_tables"] = [
        "M-PHY lane assignment (MIPI M-PHY 5.0)",
        "UniPro protocol-stack layer table (MIPI UniPro v2.0)",
        "UFSHCI register map (JEDEC JESD223)",
        "UPIU transaction-type table (UFS Command Set)",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L19 constraints / PDK
# ---------------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    # UFS extends the MIPI sibling synth (M-PHY lanes), which fires first and
    # leaves constraints_present=True. JESD220 (with MIPI M-PHY 5.0 / UniPro
    # v2.0) defines only the interface electricals — it carries NO internal
    # PDK / floorplan / SDC / die-area / power-budget content (source spec has
    # zero such terms). So the implementable-constraint flag is False here;
    # direct-assign to override the sibling default.
    f["constraints_present"] = False
    # Remove SD/MMC-only summary key.
    f.pop("card_internal_constraints", None)
    f["host_pcb_constraints_summary"] = [
        "Impedance-controlled, length-matched differential routing for the M-PHY lane pairs (DOUT/DIN); critical at HS-Gear 4 (11.6 Gbit/s) and HS-Gear 5 (23.2 Gbit/s).",
        "Differential termination per the MIPI M-PHY 5.0 electrical specification; AC coupling where required.",
        "Clean reference clock (REF_CLK) with low jitter to seed the device PLL; frequency per bRefClkFreq.",
        "Separate, well-regulated VCC (NAND), VCCQ (logic), VCCQ2 (interface) rails with proper decoupling near the device.",
        "Minimized via stubs and controlled crosstalk between lanes at HS-Gear 5 to preserve eye opening.",
        "ESD protection appropriate to the package (BGA eUFS or card edge).",
    ]
    f["device_internal_constraints"] = (
        "Device-internal PDK / floorplan / NAND-array layout constraints are "
        "vendor-specific and intentionally out of scope of the JESD220 "
        "interface definition. Device electrical signoff is at the M-PHY "
        "differential lane pads and the REF_CLK/RESET_n CMOS pads.")
    f["notes"] = (
        "JESD220 (with the referenced MIPI M-PHY 5.0 and UniPro v2.0 specs) "
        "defines the interface electricals (differential signaling levels, "
        "eye masks, jitter, equalization per HS-Gear) but no internal PDK / "
        "floorplan / SDC content. A UFS host controller IP and the "
        "UniPro+M-PHY hard-macro ship with their own SDC/UPF/DFT collateral "
        "at the SoC integration level.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L20 DFT / scan topology
# ---------------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["dft_present"] = "partial"
    f["exposed_dft_features"] = [
        {"name": "M-PHY/UniPro loopback + link startup", "purpose": "The MIPI M-PHY/UniPro link startup sequence and loopback test modes exercise the high-speed lanes and verify gear/lane negotiation - a built-in lane bring-up/self-test mechanism."},
        {"name": "UniPro DME error counters", "purpose": "The UniPro Device Management Entity exposes PHY-adapter and data-link error counters readable via UIC GET commands - built-in observability for link health."},
        {"name": "Device Health Descriptor", "purpose": "Pre-EOL information and device life-time estimation (bDeviceLifeTimeEstA/B) - built-in endurance observability."},
        {"name": "Query Attributes / Flags", "purpose": "Read current power mode, error/feature state without the SCSI path."},
        {"name": "UFSHCI error / interrupt registers", "purpose": "Host controller aggregates UTP, UIC and link errors for diagnosis."},
    ]
    f["no_jtag_on_device_package"] = (
        "There is no JTAG / scan / boundary-scan port exposed on the UFS "
        "device package over the UFS link. Vendor SiP debug (internal scan, "
        "NAND BIST, ECC scrub, read margining) is accessed at wafer/package "
        "probe, not over the UFS interface.")
    f["notes"] = (
        "UFS does not define a formal DFT/scan architecture at the link "
        "interface. Link-level observability is via M-PHY/UniPro loopback + "
        "link-startup, UniPro DME error counters, the Device Health "
        "Descriptor, Query Attributes/Flags, and the UFSHCI error/interrupt "
        "registers. Internal flash test is vendor-specific and out of scope "
        "of JESD220.")
    # Strip SD/MMC-only key if present.
    f.pop("no_jtag_on_edge_connector", None)
    _write(p, d)


# ---------------------------------------------------------------------------
# L21 power intent
# ---------------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["power_intent_present"] = True
    # Remove SD/MMC-only power blocks.
    for stale in ("power_limit_per_interface_table",
                  "fxe_power_management_register_set"):
        f.pop(stale, None)
    f["power_domains_summary"] = {
        "VCC": "NAND core supply for the flash array (typically ~2.5 V / ~3.3 V class, vendor-defined).",
        "VCCQ": "Low-voltage core / controller logic supply (~1.2 V class).",
        "VCCQ2": "Interface / I/O supply for the M-PHY high-speed lanes and the REF_CLK domain (~1.8 V class).",
        "VSS": "Common ground.",
    }
    f["power_up_sequence"] = [
        "1. Host brings up VCC, VCCQ, VCCQ2 in the device-specified order.",
        "2. Host drives REF_CLK and holds RESET_n LOW, then releases RESET_n HIGH.",
        "3. Host enables the UFS host controller (HCE=1) and runs the UniPro/M-PHY link startup.",
        "4. Host negotiates power mode and HS-Gear, then performs the NOP handshake and sets fDeviceInit.",
    ]
    f["low_power_modes_summary"] = {
        "HIBERN8": "Deepest M-PHY line low-power state with fast wake; lanes parked while retaining configuration. Primary idle state.",
        "SLEEP": "UFS device sleep power mode; reduced device activity.",
        "Deep_Sleep": "Lower-power device state (UFS 3.1+) with longer wake latency; supply may be reduced.",
        "Power_Off": "Host removes supplies; full state loss; boot LU and device init repeated on next power-up.",
        "Performance_Throttling_Notification": "UFS 3.1+ mechanism by which the device notifies the host of thermal/performance throttling so the host can pace I/O.",
    }
    f["power_management_features"] = {
        "WriteBooster": "Pseudo-SLC turbo-write buffer flushed during idle time; improves burst write power-efficiency.",
        "HPB": "Host Performance Booster reduces device-side L2P lookups, lowering read energy.",
        "Reference_Clock_Gating": "REF_CLK and the M-PHY lanes can be parked (HIBERN8) when idle for power saving.",
    }
    f["notes"] = (
        "UFS power management spans two layers: the M-PHY/UniPro line power "
        "states (HS-BURST / PWM-BURST / SLEEP / STALL / HIBERN8) controlled "
        "via UIC power-mode commands, and the UFS device power modes (Active "
        "/ Idle / Sleep / Deep Sleep / Power Down) controlled via the UFS "
        "DEVICE W-LUN and Query attributes. The three-rail scheme (VCC / "
        "VCCQ / VCCQ2) lets the NAND core, logic, and interface domains be "
        "powered and gated independently.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L22 verification plan
# ---------------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Link startup and gear/lane negotiation - M-PHY lane discovery, UniPro DME startup, HS-Gear 5 + 2-lane negotiation for UFS 4.0, fallback to lower gears.",
        "Device init handshake - NOP Out / NOP In, fDeviceInit flag set/clear.",
        "UPIU coverage - Command, Response, Data In, Data Out, RTT, Task Mgmt Req/Resp, Query Req/Resp, NOP In/Out, Reject.",
        "SCSI command coverage - INQUIRY, TEST UNIT READY, READ(10/16), WRITE(10/16), REPORT LUNS, REQUEST SENSE, START STOP UNIT, SYNCHRONIZE CACHE, UNMAP, SECURITY PROTOCOL IN/OUT.",
        "LUN coverage - normal LUNs + Well-known LUNs (REPORT LUNS, UFS DEVICE, BOOT, RPMB).",
        "Query coverage - read/write Descriptors, read/write/set/clear/toggle Attributes and Flags.",
        "Write flow control - RTT issuance and bMaxNumOfRTT bounding; no host overrun.",
        "Command queueing - legacy single Transfer Request List + doorbell, and native MCQ multi-queue with out-of-order completion.",
        "RPMB - key program-once, authenticated read (nonce), authenticated write (HMAC-SHA256 + monotonic counter), replay/MAC-mismatch rejection.",
        "WriteBooster - enable/flush behavior and throughput.",
        "HPB (optional) - L2P caching in Host-control / Device-control mode.",
        "Power modes - HIBERN8 enter/exit (fast wake), SLEEP / Deep Sleep, Performance Throttling Notification.",
        "Reset scopes - UniPro link reset, LOGICAL UNIT RESET (task management), RESET_n / power-cycle.",
        "Error injection - Reject UPIU, SCSI CHECK CONDITION + sense, UniPro CRC/retransmission, M-PHY loss-of-sync recovery.",
        "M-PHY electrical compliance - eye mask, jitter, equalization per HS-Gear (MIPI M-PHY CTS).",
        "UniPro conformance - data-link flow control, retransmission, CPort behavior (MIPI UniPro CTS).",
        "Reference-clock selection - bRefClkFreq values (19.2 / 26 / 38.4 / 52 MHz).",
    ]
    f["notes"] = (
        "The JESD220/JESD223 specs do not embed a single testbench; the "
        "categories above derive from the layered stack (M-PHY, UniPro, "
        "UTP/UPIU, UFS Command Set) and the UFSHCI register/queue model. "
        "JEDEC and MIPI maintain separate normative conformance test suites "
        "(UFS CTS, UFSHCI, UniPro CTS, M-PHY CTS) that are out of scope of "
        "this extraction.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L23 security requirements
# ---------------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _fields(d)
    f["security_requirements_present"] = True
    f["security_summary"] = (
        "UFS provides data-integrity at the transport layer (UniPro CRC + "
        "retransmission) and a dedicated authenticated, replay-protected "
        "secure-storage region: RPMB (Replay Protected Memory Block). RPMB is "
        "accessed via the RPMB Well-known LUN, authenticated with a write-once "
        "256-bit key and a monotonic write counter, with an HMAC-SHA256 MAC "
        "computed over each RPMB frame. UFS also provides write-protection "
        "(permanent and power-on) and a Security Send/Receive transport "
        "(SECURITY PROTOCOL IN/OUT) for vendor/TCG security features. Bulk "
        "user data confidentiality is not provided at the protocol layer and "
        "is expected to be handled by host/inline encryption.")
    f["security_features"] = [
        {"name": "RPMB (Replay Protected Memory Block)", "type": "authenticated anti-replay secure storage", "scope": "RPMB Well-known LUN",
         "description": "256-bit one-time-programmed authentication key + monotonic write counter; every RPMB frame carries an HMAC-SHA256 MAC computed over the frame using the shared key. The device verifies the MAC and the write counter before any write, defeating replay attacks. Used to store anti-rollback counters, secure boot state, and DRM secrets."},
        {"name": "UniPro data-link integrity (CRC + retransmission)", "type": "integrity", "scope": "every UniPro frame on the link",
         "description": "UniPro protects each frame with CRC and retransmits on error, providing reliable in-order delivery. This is wire-error integrity, not a cryptographic MAC for the bulk path."},
        {"name": "Permanent Write Protect (fPermanentWPEn)", "type": "permanent read-only", "scope": "configured LUN / area",
         "description": "Irreversible flag; once set the protected area can never be written again."},
        {"name": "Power-On Write Protect (fPowerOnWPEn)", "type": "soft read-only", "scope": "configured LUN / area",
         "description": "Write-protect asserted from power-on until cleared by the host; protects boot/critical regions during early boot."},
        {"name": "Security Protocol transport (SECURITY PROTOCOL IN / OUT)", "type": "opaque security transport", "scope": "device security features",
         "description": "SCSI Security Protocol commands carry RPMB and vendor/TCG security payloads between host and device."},
        {"name": "Device identity (factory String Descriptors)", "type": "identity", "scope": "device-level",
         "description": "Factory-programmed manufacturer ID / product name / serial number serve as a read-only device fingerprint (not authenticated by themselves)."},
    ]
    f["no_base_layer_bulk_confidentiality"] = (
        "The UFS protocol does not encrypt bulk user data on the M-PHY lanes; "
        "an attacker with high-speed link access could in principle capture "
        "plaintext blocks. Confidentiality for user data is expected from "
        "host-side / inline storage encryption (e.g. filesystem-level or "
        "block-layer encryption) above the UFS driver. RPMB is the "
        "authenticated, replay-protected exception for small secure-state "
        "storage.")
    f["comparison_to_predecessor_emmc"] = (
        "UFS inherits and modernizes eMMC's RPMB concept: both use a "
        "write-once key + monotonic write counter + HMAC-SHA256 over the RPMB "
        "frame. UFS adds the layered UniPro integrity and a richer "
        "Query/Descriptor-based write-protection model.")
    f["notes"] = (
        "The security-critical surfaces are (1) the write-once, "
        "never-readable 256-bit RPMB key underpinning HMAC-SHA256 replay "
        "protection, and (2) the irreversible fPermanentWPEn flag. All "
        "bulk-data confidentiality is delegated to host/inline encryption "
        "above the protocol.")
    # Strip SD/MMC-only keys if present.
    for stale in ("no_base_layer_confidentiality", "comparison_to_sibling_emmc"):
        f.pop(stale, None)
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def _wb(tok: str, blob: str) -> bool:
    """Word-boundary token match (avoids substring false-positives)."""
    return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None


def is_ufs(blob: str) -> bool:
    """Content-only `ufs` detector (importable, lifted from the runner) WITH a
    FOREIGN-PRIMARY DEFER (mirrors `is_mipi` / `is_soundwire` defer doctrine).

    The structural signature below ("UFS"+"UniPro", or "UPIU", or
    "Universal Flash Storage", or "UFS"+"M-PHY"+"JESD220") is necessary but
    NOT sufficient as a STANDALONE superset predicate: the runner's generic
    storage / serial-interface vocabulary injects incidental UFS comparison
    tokens ("Universal Flash Storage" as the eMMC/SD successor, "UFS"+"UniPro"
    as a high-speed-serial example) into the generated L-docs of FOREIGN
    benchmarks whose true subject is a different protocol. Empirically two
    foreign benchmarks trip the loose branches below:

      * ONFI (Open NAND Flash Interface): an asynchronous/source-synchronous
        raw-NAND command bus. Its L-docs name UFS as the managed-NAND
        comparison, tripping the "Universal Flash Storage" branch. ONFI's own
        structural signature (raw-NAND CLE/ALE latch-enable strobes, DQ data
        bus with WE#/RE# write/read strobes, the Parameter Page + R/B#
        ready/busy pin) is absent from every real UFS spec (UFS is a layered
        SCSI/UPIU-over-UniPro-over-M-PHY protocol with no raw-NAND pinout).

      * SoundWire (MIPI audio control+data bus): its L-docs cite UFS/UniPro as
        a MIPI-family high-speed-serial sibling, tripping the "UFS"+"UniPro"
        branch. SoundWire's own structural signature (the SoundWire Data Port
        framing with Master/Slave roles, or SoundWire streams over Data Ports,
        or dense "SoundWire" subject density) is absent from every real UFS
        spec (UFS has no SoundWire / Data-Port framing).

    Guard (general, content-only — structural protocol tokens + density
    counts only, NO benchmark-directory / chip / SKU literal): if the blob's
    DOMINANT subject is one of those foreign protocols, defer (False), so the
    generic UFS synth never fires on a foreign spec that only mentions
    UFS / UniPro / Universal Flash Storage incidentally.

    Empty-safe. Reads ONLY ``blob`` (spec text).
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT UFS). ---
    # ONFI-primary: the raw-NAND command-bus structural signature. CLE/ALE
    # (command/address latch enable), the DQ data bus with WE#/RE# strobes,
    # and the Parameter Page + R/B# ready/busy pin uniquely identify ONFI and
    # are absent from a layered UPIU/UniPro UFS spec.
    onfi_primary = (
        ("onfi" in low and "nand" in low
            and _wb("CLE", blob) and _wb("ALE", blob))
        or ("nand" in low and _wb("DQ", blob)
            and "we#" in low and "re#" in low)
        or ("parameter page" in low and "r/b#" in low and "onfi" in low))
    # SoundWire-primary: the MIPI SoundWire Data-Port framing signature, or
    # dense "SoundWire" subject density. UFS has no SoundWire / Data-Port
    # construct, so deferring on it is safe.
    soundwire_primary = (
        ("soundwire" in low and "data port" in low
            and ("master" in low or "manager" in low)
            and ("slave" in low or "peripheral" in low))
        or ("soundwire" in low and "stream" in low and "data port" in low)
        or (low.count("soundwire") >= 8))
    if onfi_primary or soundwire_primary:
        return False

    # --- STRUCTURAL UFS signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("UFS" in blob and "UniPro" in blob)
        or ("UPIU" in blob)
        or ("Universal Flash Storage" in blob)
        or ("UFS" in blob and "M-PHY" in blob
            and "JESD220" in blob))
