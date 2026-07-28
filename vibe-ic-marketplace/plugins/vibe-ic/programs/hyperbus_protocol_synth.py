"""HyperBus (HyperRAM / HyperFlash) protocol synth helper (protocol #55).

ic_class-gated overlay for the Cypress/Infineon HyperBus structural
signature: a low-pin-count, high-speed, double-data-rate (DDR) memory
interface that connects a host (master) to one or more HyperBus memory
devices (slaves) over a differential clock (CK / CK#), a per-device chip
select (CS#), an 8-bit DDR command/address/data bus (DQ[7:0]), and a
bidirectional Read-Write Data Strobe (RWDS). Every transaction starts with
a 48-bit Command-Address (CA) sequence on DQ[7:0] over three clocks (six
DDR bytes) encoding R/W#, address space (memory vs register), burst type
(linear/wrapped), and the row+column address; the device then inserts a
Configuration-Register-programmed initial latency (3..7 clocks, fixed or
variable) before the DDR data phase. RWDS has three roles: variable-latency
indicator during the CA phase (RWDS during CA = additional latency), read
data strobe edge-aligned with read data, and write data byte mask.
HyperRAM is a self-refresh pseudo-static RAM (DRAM core, SRAM-like
interface, distributed refresh, deep power down); HyperFlash is NOR flash
on the identical bus. Registers: ID0/ID1 (read-only identification) and
CR0/CR1 (configuration: latency count, fixed/variable latency, drive
strength, burst length, refresh control). Up to 333 MB/s (DDR @ 166 MHz,
8-bit); 1.8 V (single-ended CK option) and 3.0 V (differential CK/CK#)
variants. Applies the Cypress/Infineon HyperBus Specification
spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
signatures (RWDS strobe + 48-bit Command-Address cycle + 8-bit DDR DQ bus +
HyperRAM/HyperFlash vocabulary) read from the L-doc / input_doc CONTENT
blob only. It NEVER reads the input-document filename or the benchmark
folder name.

Sibling disambiguation — HyperBus vs SPI / QSPI. HyperBus is distinct from
the Motorola SPI family: SPI uses SCLK / MOSI / MISO / CS with single (or,
for QSPI, quad IO0-IO3) data-rate full-duplex shift-register transfers and
has NO RWDS strobe, NO 48-bit Command-Address cycle, and NO
HyperRAM/HyperFlash device family. The HyperBus detector therefore REQUIRES
the HyperBus-only structural vocabulary (RWDS + the 48-bit / Command-Address
cycle + 8-bit DDR DQ + HyperRAM/HyperFlash) and DEFERS when the doc is
SPI-primary (MOSI/MISO/SCLK without RWDS / CA-cycle / HyperRAM), so it
cannot false-fire on a plain SPI or QSPI spec.

Public entry: ``apply_hyperbus_synth(generated_docs_dir, is_hyperbus,
hyperbus_ic_name)``. Module-level ``is_hyperbus(blob)`` is the content-only
detector. Because the runner's universal SPI synth may touch base docs, the
overlay FORCE-ASSIGNS (not setdefault) every key so HyperBus wins when
wired last.
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

# Canonical HyperBus facts (Cypress/Infineon HyperBus Specification).
_DQ_WIDTH = 8                             # DQ[7:0]
_CA_BITS = 48                             # Command-Address sequence
_CA_CLOCKS = 3                            # 3 clocks = 6 DDR bytes
_CA_DDR_BYTES = 6
_LATENCY_CODES = [3, 4, 5, 6, 7]          # configurable initial latency (clocks)
_MAX_FREQ_MHZ = 166
_MAX_THROUGHPUT_MB_S = 333                # 2 x 166 MHz x 1 byte
_BURST_LENGTHS = [16, 32, 64, 128]        # wrapped burst lengths (bytes)
_VOLTAGES = [1.8, 3.0]
_REGISTERS = ["ID0", "ID1", "CR0", "CR1"]


def is_hyperbus(blob: str) -> bool:
    """Content-only HyperBus detector with an SPI / QSPI sibling MUTEX.

    Fire on the HyperBus structural signature: the RWDS Read-Write Data
    Strobe + the 48-bit Command-Address (CA) cycle + the 8-bit DDR DQ bus +
    the HyperRAM / HyperFlash device family (and/or the HyperBus name token).
    Defer if the doc is SPI-primary (MOSI/MISO/SCLK shift-register full-duplex
    vocabulary with NONE of RWDS / Command-Address-cycle / HyperRAM /
    HyperFlash), so a plain SPI or QSPI spec cannot false-fire. Reads ONLY the
    spec text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # "ddr" must be a WHOLE WORD — a plain substring search matches inside
    # "command-a*ddr*ess", which would wrongly mark a non-DDR doc. Likewise
    # an 8-bit-bus token must be the standalone "8-bit"/"8 bit"/"dq[7:0]" and
    # NOT the "8-bit" that sits inside "4*8-bit*" (the 48-bit CA length).
    _ddr_word = re.search(r"\bddr\b", low) is not None
    _ddr_phrase = ("double data rate" in low or "double-data-rate" in low)
    _eight_bit_bus = (
        "dq[7:0]" in low or "dq[7:0" in low
        or re.search(r"(?<!\d)8[- ]bit", low) is not None
    )

    # HyperBus-only structural tokens (absent from SPI / QSPI).
    rwds = ("rwds" in low or "read-write data strobe" in low
            or "read write data strobe" in low)
    ca_cycle = (
        ("command-address" in low or "command address" in low)
        and ("48-bit" in low or "48 bit" in low or "48bit" in low
             or "ca[47" in low or "three clock" in low or "3 clock" in low
             or "six ddr" in low or "6 ddr" in low)
    )
    ca_token = ("ca[47" in low or "command-address" in low
                or "command address" in low)
    dq8_ddr = _eight_bit_bus and (_ddr_word or _ddr_phrase)
    hyper_family = ("hyperram" in low or "hyperflash" in low)
    name_token = "hyperbus" in low

    hyperbus_structure = (
        rwds
        and (ca_cycle or ca_token)
        and (dq8_ddr or hyper_family or name_token)
    )

    # Strength of the HyperBus signature: how many DISTINCT HyperBus-only
    # structural tokens are present. A genuine HyperBus doc carries several
    # (RWDS + CA-cycle + DDR-DQ + HyperRAM/HyperFlash + the name); an SPI/QSPI
    # doc that merely name-drops or NEGATES one of them ("unlike HyperBus, QSPI
    # has no RWDS") carries at most one and must not be mistaken for HyperBus.
    hyperbus_token_count = (
        int(rwds) + int(ca_token) + int(hyper_family)
        + int(dq8_ddr) + int(name_token)
    )

    # Sibling MUTEX: an SPI-primary doc keys on the SCLK/MOSI/MISO
    # shift-register full-duplex model (or QSPI's IO0..IO3 quad lines). If those
    # SPI markers are present AND the HyperBus signature is WEAK (fewer than two
    # distinct HyperBus-only structural tokens), defer — so a plain SPI/QSPI
    # spec, even one that mentions HyperBus in a comparison or negation, cannot
    # false-fire.
    spi_markers = (
        ("mosi" in low or "miso" in low)
        or ("sclk" in low and ("shift register" in low or "cpol" in low
                               or "cpha" in low))
        or ("io0" in low and "io3" in low and "quad" in low)
    )
    # When SPI/QSPI markers are present, require a STRONG, POSITIVE HyperBus
    # structural core to override the MUTEX: at least two distinct HyperBus
    # tokens AND the genuine 8-bit-DDR-DQ data-bus signature (which an SPI/QSPI
    # spec — even one that compares itself to HyperBus in prose/negation — does
    # not carry, since SPI/QSPI use SCLK + MOSI/MISO or IO0..IO3, not an 8-bit
    # DDR DQ bus). This blocks negated/comparative HyperBus mentions in an
    # SPI-primary doc from tripping the detector.
    if spi_markers and not (hyperbus_token_count >= 2 and dq8_ddr):
        return False

    return bool(
        hyperbus_structure
        or (name_token and (rwds or ca_token or hyper_family))
        or (hyper_family and rwds)
    )


def apply_hyperbus_synth(generated_docs_dir: Path, is_hyperbus_flag: bool,
                         hyperbus_ic_name: Optional[str]) -> None:
    """Apply HyperBus synth when the HyperBus signature matched.

    The runner's universal SPI synth may have touched base docs, so every key
    is FORCE-ASSIGNED (direct assignment, not setdefault) and this overlay is
    wired LAST so the HyperBus values win.
    """
    if not is_hyperbus_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if hyperbus_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = hyperbus_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = hyperbus_ic_name
                d["ic_name"] = hyperbus_ic_name  # belt-and-braces top-level
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
# L1 — HyperBus datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "HyperBus Interface Specification (HyperRAM / HyperFlash)")
    d["version"] = "HyperBus Specification (Cypress / Infineon)"
    d["revised_date"] = "Cypress Semiconductor / Infineon Technologies"
    d["manufacturer"] = "Cypress Semiconductor / Infineon Technologies"
    d["copyright"] = "© Cypress Semiconductor / Infineon Technologies"
    d["abstract"] = (
        "HyperBus is a low-pin-count, high-speed, double-data-rate (DDR) "
        "memory interface connecting a host controller (master) to one or "
        "more HyperBus memory devices (slaves) over a small signal set: a "
        "differential clock (CK / CK#; single-ended CK allowed at 1.8 V), a "
        "per-device chip select (CS#), an 8-bit DDR command/address/data bus "
        "(DQ[7:0]), and a bidirectional Read-Write Data Strobe (RWDS), plus "
        "optional RESET# / INT#. Two device families use the bus: HyperRAM (a "
        "self-refresh pseudo-static RAM with a DRAM core and SRAM-like "
        "interface) and HyperFlash (NOR flash on the identical bus). Every "
        "transaction begins with a 48-bit Command-Address (CA) sequence sent "
        "on DQ[7:0] over three clocks (six DDR bytes) encoding R/W#, address "
        "space (memory vs register), burst type (linear / wrapped), and the "
        "row+column address; the device then inserts a Configuration-Register "
        "programmed initial latency (typically 3..7 clocks, fixed or variable) "
        "before the DDR data phase. HyperBus reaches up to 333 MB/s at 166 MHz "
        "DDR on the 8-bit bus.")
    d["keywords"] = [
        "HyperBus", "HyperRAM", "HyperFlash", "RWDS", "Read-Write Data Strobe",
        "Command-Address", "48-bit CA", "DQ[7:0]", "DDR", "double data rate",
        "CK", "CK#", "differential clock", "CS#", "chip select",
        "initial latency", "variable latency", "fixed latency",
        "Configuration Register", "CR0", "CR1", "ID register",
        "self-refresh", "deep power down", "wrapped burst", "linear burst",
        "166 MHz", "333 MB/s", "low pin count", "Cypress", "Infineon",
    ]
    d["external_pins"] = [
        "CK / CK# : differential clock driven by the host (single-ended CK "
        "option at 1.8 V); data is double-data-rate (both clock edges)",
        "CS# : chip select, active low, one per HyperBus device; asserted low "
        "for the whole transaction",
        "DQ[7:0] : 8-bit bidirectional DDR command/address/data bus (CA, then "
        "read/write data)",
        "RWDS : Read-Write Data Strobe (bidirectional) — variable-latency "
        "indicator during CA, read data strobe during reads, write data byte "
        "mask during writes",
        "RESET# : hardware reset, active low (optional) — returns the device "
        "to power-up defaults",
        "INT# : interrupt / status output (optional, device-dependent)",
        "VCC / VCCQ / VSS : supply and ground",
    ]
    d["data_bus_width_bits"] = _DQ_WIDTH
    d["command_address_bits"] = _CA_BITS
    d["command_address_clocks"] = _CA_CLOCKS
    d["supported_initial_latency_clocks"] = list(_LATENCY_CODES)
    d["max_clock_freq_MHz"] = _MAX_FREQ_MHZ
    d["max_throughput_MB_s"] = _MAX_THROUGHPUT_MB_S
    d["supported_voltages_V"] = list(_VOLTAGES)
    d["modes_of_operation"] = [
        {"name": "Memory read",
         "ca_bits": "R/W#=1, Address Space=0",
         "note": "48-bit CA, then initial latency, then DDR read data on "
                 "DQ[7:0] with RWDS as the edge-aligned read strobe until CS# "
                 "deasserts."},
        {"name": "Memory write",
         "ca_bits": "R/W#=0, Address Space=0",
         "note": "48-bit CA, then initial latency (array writes), then DDR "
                 "write data on DQ[7:0] with RWDS driven by the host as a byte "
                 "data mask."},
        {"name": "Register read",
         "ca_bits": "R/W#=1, Address Space=1",
         "note": "Reads the ID (ID0/ID1) or Configuration (CR0/CR1) registers "
                 "in the register address space."},
        {"name": "Register write",
         "ca_bits": "R/W#=0, Address Space=1",
         "note": "Writes the Configuration Registers (CR0/CR1) — latency "
                 "count, fixed/variable latency, drive strength, burst length, "
                 "refresh control."},
    ]
    d["key_features"] = [
        "Low-pin-count, high-speed, double-data-rate (DDR) memory interface; "
        "up to 333 MB/s at 166 MHz on an 8-bit bus.",
        "Signal set: differential clock CK/CK# (single-ended CK at 1.8 V), "
        "per-device chip select CS#, 8-bit DDR bus DQ[7:0], and a "
        "bidirectional Read-Write Data Strobe RWDS (plus optional RESET#, "
        "INT#).",
        "Every transaction starts with a 48-bit Command-Address (CA) sequence "
        "on DQ[7:0] over three clocks (six DDR bytes) encoding R/W#, address "
        "space (memory vs register), burst type, and the row+column address.",
        "RWDS has three roles: variable-latency indicator during the CA phase, "
        "source-synchronous read data strobe (edge-aligned with read data), "
        "and write data byte mask.",
        "Configurable initial latency (typically 3..7 clocks) selected in "
        "Configuration Register 0; fixed-latency (always 2x) or variable "
        "(1x/2x via RWDS-during-CA) models.",
        "HyperRAM: self-refresh pseudo-static RAM (DRAM core, SRAM-like "
        "interface, distributed refresh, deep power down).",
        "HyperFlash: NOR flash on the identical HyperBus interface and "
        "pin-out, sharing the board footprint with HyperRAM.",
        "Registers: ID0/ID1 (read-only identification) and CR0/CR1 "
        "(configuration: latency, drive strength, burst length, refresh).",
        "Wrapped (16/32/64/128-byte) and linear bursts, plus a Hybrid Burst "
        "(wrapped then linear) option.",
        "1.8 V (single-ended-clock option) and 3.0 V (differential-clock) "
        "supply variants; programmable output drive strength.",
    ]
    d["topology_summary"] = (
        "Point-to-point or multi-drop: a host controller drives CK/CK#, "
        "DQ[7:0], and RWDS shared across devices, with one CS# per HyperBus "
        "device selecting which device participates in a transaction.")
    d["use_cases"] = [
        "Expansion RAM (HyperRAM) for cost- and pin-sensitive embedded / IoT / "
        "wearable systems",
        "Execute-in-place code and data storage (HyperFlash)",
        "Frame / line buffers and scratch memory in microcontroller and "
        "display systems",
        "Systems where pin count and board area are constrained but DDR "
        "throughput is needed",
    ]
    d["revision_history"] = [
        {"version": "HyperBus", "date": "Cypress Semiconductor",
         "description": "Cypress HyperBus interface: differential CK/CK#, CS#, "
                        "8-bit DDR DQ[7:0], RWDS, 48-bit Command-Address, "
                        "configurable latency, HyperRAM + HyperFlash."},
        {"version": "Infineon", "date": "post-acquisition",
         "description": "HyperBus maintained by Infineon Technologies after "
                        "the Cypress acquisition; same interface (CA, RWDS, "
                        "DDR DQ, configurable latency, HyperRAM/HyperFlash)."},
    ]
    d["overview"] = (
        "HyperBus is a low-pin-count, high-speed double-data-rate memory "
        "interface from Cypress Semiconductor (now Infineon). A host (master) "
        "talks to one or more HyperBus memory devices (slaves) over a "
        "differential clock CK/CK# (single-ended CK allowed at 1.8 V), a "
        "per-device chip select CS#, an 8-bit DDR command/address/data bus "
        "DQ[7:0], and a bidirectional Read-Write Data Strobe RWDS. After CS# "
        "goes low, every transaction sends a 48-bit Command-Address sequence "
        "on DQ[7:0] over three clocks (six DDR bytes): CA[47]=R/W#, "
        "CA[46]=Address Space (memory vs register), CA[45]=Burst Type "
        "(wrapped/linear), CA[44:16]=row & upper column address, "
        "CA[15:3]=reserved, CA[2:0]=lower column address. The device then "
        "inserts the configured initial latency (3..7 clocks, fixed or "
        "variable; in variable latency RWDS during the CA phase signals 1x vs "
        "2x) before the DDR data phase, during which RWDS is the read strobe "
        "or the write byte mask. HyperRAM is a self-refresh pseudo-static RAM "
        "(DRAM core, distributed refresh, deep power down); HyperFlash is NOR "
        "flash on the same bus. Device behaviour is set through the ID "
        "(ID0/ID1) and Configuration (CR0/CR1) registers. HyperBus reaches up "
        "to 333 MB/s at 166 MHz DDR.")
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
        "Low-pin-count, high-speed, double-data-rate (DDR) memory interface. A "
        "host (master) drives CK/CK#, CS# (one per device), the 8-bit DDR bus "
        "DQ[7:0], and the bidirectional RWDS strobe. Every transaction begins "
        "with a 48-bit Command-Address sequence over three clocks, followed by "
        "a configurable initial latency and a DDR data phase.")
    po["duplex"] = (
        "Half-duplex: DQ[7:0] is a single shared bidirectional bus driven by "
        "the host during the CA and write-data phases and by the memory during "
        "the read-data phase; RWDS is likewise driven by the memory (read "
        "strobe / variable-latency indicator) or the host (write byte mask).")
    po["synchronous_serial"] = False
    po["source_synchronous"] = True
    po["embedded_clock"] = False
    po["forwarded_clock"] = True
    po["double_data_rate"] = True
    po["encoding"] = (
        "No line code: command, address, and data are clocked at double data "
        "rate on both edges of CK. Read data is captured against the "
        "memory-driven RWDS strobe (source-synchronous), not re-derived from "
        "CK.")
    po["modulation"] = "Single-ended CMOS (DQ/RWDS); CK is differential (CK/CK#)."
    po["data_bus_width_bits"] = _DQ_WIDTH
    po["command_address_bits"] = _CA_BITS
    po["command_address_clocks"] = _CA_CLOCKS
    po["command_address_ddr_bytes"] = _CA_DDR_BYTES
    po["initial_latency_clocks_options"] = list(_LATENCY_CODES)
    po["max_clock_freq_MHz"] = _MAX_FREQ_MHZ
    po["max_throughput_MB_s"] = _MAX_THROUGHPUT_MB_S
    po["supported_voltages_V"] = list(_VOLTAGES)
    po["device_families"] = ["HyperRAM (self-refresh pseudo-SRAM)",
                             "HyperFlash (NOR flash)"]
    po["latency_models"] = ["fixed (always 2x configured latency)",
                            "variable (1x or 2x; RWDS during CA selects)"]
    po["rwds_roles"] = [
        "Variable-latency indicator during the Command-Address phase "
        "(RWDS asserted = additional / 2x latency)",
        "Source-synchronous read data strobe, edge-aligned with read data on "
        "DQ[7:0]",
        "Write data byte mask (RWDS high masks the byte, RWDS low writes it)",
    ]
    d["functional_requirements"] = [
        {"id": "FR-PINS-01", "text": "HyperBus uses a differential clock "
         "CK/CK# (single-ended CK option at 1.8 V), a per-device chip select "
         "CS# (active low), an 8-bit double-data-rate command/address/data bus "
         "DQ[7:0], and a bidirectional Read-Write Data Strobe RWDS, plus "
         "optional RESET# and INT#."},
        {"id": "FR-CA-02", "text": "Every transaction begins, after CS# goes "
         "low, with a 48-bit Command-Address (CA) sequence transferred on "
         "DQ[7:0] across three clock cycles (six DDR bytes), most-significant "
         "byte first."},
        {"id": "FR-CABITS-03", "text": "The CA encodes CA[47]=R/W# (1=read, "
         "0=write), CA[46]=Address Space (0=memory array, 1=register space), "
         "CA[45]=Burst Type (0=wrapped, 1=linear), CA[44:16]=row & upper "
         "column address, CA[15:3]=reserved, CA[2:0]=lower column address."},
        {"id": "FR-LAT-04", "text": "After the CA the device inserts a "
         "configurable initial latency (typically 3..7 clocks) programmed in "
         "Configuration Register 0, before the DDR data phase begins."},
        {"id": "FR-VARLAT-05", "text": "In variable-latency mode the device "
         "drives RWDS during the CA phase to indicate whether additional (2x) "
         "latency is required (RWDS asserted) or single (1x) latency suffices "
         "(RWDS low); fixed-latency mode always uses 2x latency."},
        {"id": "FR-DDR-06", "text": "Data is transferred at double data rate "
         "on both edges of CK, one byte per edge on DQ[7:0], reaching up to "
         "333 MB/s at 166 MHz."},
        {"id": "FR-RWDS-07", "text": "RWDS serves as the source-synchronous "
         "read data strobe (edge-aligned with read data) during reads and as "
         "the write data byte mask (RWDS high masks, RWDS low writes) during "
         "writes."},
        {"id": "FR-REG-08", "text": "The device exposes a register address "
         "space (selected by Address Space=1) containing the read-only "
         "Identification Registers ID0/ID1 and the read/write Configuration "
         "Registers CR0/CR1."},
        {"id": "FR-HRAM-09", "text": "HyperRAM is a self-refresh pseudo-static "
         "RAM: it performs distributed (self) refresh of its DRAM cells "
         "transparently and uses the variable-latency mechanism to hide "
         "refresh-collision delays; it supports a Deep Power Down mode via "
         "CR0."},
        {"id": "FR-HFLASH-10", "text": "HyperFlash is a NOR flash memory "
         "presenting the identical HyperBus interface and pin-out; reads use "
         "the same CA + latency + DDR flow, and program/erase use NOR command "
         "sequences."},
        {"id": "FR-BURST-11", "text": "The device supports wrapped bursts of "
         "the configured length (16/32/64/128 bytes) and linear bursts that "
         "increment until CS# deasserts, plus an optional Hybrid Burst "
         "(wrapped then linear)."},
        {"id": "FR-RESET-12", "text": "A hardware RESET# (when present) "
         "returns the device to its power-up default configuration (default "
         "latency, latency model, drive strength, and burst length)."},
    ]
    d["error_response_conditions"] = [
        "CS# deasserted early — terminates the transaction; partial burst data "
        "is discarded by the host.",
        "Latency mismatch — host not honouring the configured initial latency "
        "(or ignoring RWDS-during-CA in variable mode) corrupts data capture.",
        "Refresh collision (HyperRAM) — handled transparently via the variable "
        "latency 2x indication on RWDS; no data loss.",
        "Deep Power Down access (HyperRAM) — accessing during DPD before the "
        "wake-up time yields invalid data.",
        "Drive-strength / signal-integrity error — DQ/RWDS drive strength "
        "(CR0) mis-set for the board can cause capture failures at high "
        "frequency.",
    ]
    d["compliance_requirements"] = [
        "Differential CK/CK# (or single-ended CK at 1.8 V), per-device CS#, "
        "8-bit DDR DQ[7:0], bidirectional RWDS.",
        "48-bit Command-Address over three clocks (six DDR bytes), MSB byte "
        "first, with correct R/W# / Address Space / Burst Type bits.",
        "Configurable initial latency (3..7 clocks) honoured; "
        "variable-latency RWDS-during-CA sampling for 1x vs 2x.",
        "RWDS as read data strobe (reads) and write byte mask (writes).",
        "ID (ID0/ID1) and Configuration (CR0/CR1) registers in the register "
        "address space.",
        "HyperRAM self-refresh transparency; HyperFlash NOR command/erase on "
        "the same bus.",
        "Wrapped (16/32/64/128-byte) / linear / Hybrid bursts; DDR data up to "
        "166 MHz / 333 MB/s.",
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
        "Command-Address + DDR data memory protocol. After the host asserts "
        "CS#, it sends a 48-bit Command-Address on DQ[7:0] over three clocks "
        "(R/W#, Address Space, Burst Type, row+column address); the device "
        "inserts the configured initial latency (fixed or variable, the latter "
        "signalled by RWDS during CA); then DDR data flows on DQ[7:0] with RWDS "
        "as the read strobe (reads) or write byte mask (writes) until CS# "
        "deasserts.")
    d["channels"] = [
        {"name": "CK / CK# (clock)", "direction": "host -> memory",
         "description": "Differential clock (single-ended CK at 1.8 V); data "
         "is double-data-rate on both edges."},
        {"name": "CS# (chip select)", "direction": "host -> memory",
         "description": "Active-low, one per device; held low for the whole "
         "transaction; selects which device on the shared bus participates."},
        {"name": "DQ[7:0] (command/address/data)", "direction": "bidirectional",
         "description": "8-bit DDR bus carrying the 48-bit CA, then read or "
         "write data one byte per clock edge."},
        {"name": "RWDS (Read-Write Data Strobe)", "direction": "bidirectional",
         "description": "Variable-latency indicator during CA, read data "
         "strobe during reads, write data byte mask during writes."},
        {"name": "RESET# / INT# (optional)", "direction": "host->memory / "
         "memory->host",
         "description": "Hardware reset (active low) and optional interrupt / "
         "status output."},
    ]
    d["command_address"] = {
        "bits": _CA_BITS,
        "clocks": _CA_CLOCKS,
        "ddr_bytes": _CA_DDR_BYTES,
        "order": "most-significant byte first on the first rising edge after "
                 "CS# low",
        "fields": {
            "CA[47]": "R/W# : 1 = Read, 0 = Write",
            "CA[46]": "Address Space (AS) : 0 = Memory array, 1 = Register "
                      "space",
            "CA[45]": "Burst Type : 0 = Wrapped, 1 = Linear",
            "CA[44:16]": "Row & Upper Column Address",
            "CA[15:3]": "Reserved (transmitted as 0)",
            "CA[2:0]": "Lower Column Address (byte address within the burst)",
        },
        "operation_select": "CA[47] (R/W#) x CA[46] (Address Space) selects "
                            "memory read, memory write, register read, or "
                            "register write.",
    }
    d["latency"] = {
        "initial_latency_clocks_options": list(_LATENCY_CODES),
        "configured_in": "Configuration Register 0 (CR0)",
        "fixed_latency": "Always inserts 2x the configured initial latency "
                         "(deterministic timing).",
        "variable_latency": "Inserts 1x or 2x; the device drives RWDS during "
                            "the CA phase (RWDS asserted = 2x / additional "
                            "latency required, e.g. HyperRAM refresh "
                            "collision; RWDS low = 1x).",
    }
    d["rwds_function_by_phase"] = {
        "command_address_phase": "Memory drives RWDS to indicate 1x vs 2x "
                                 "latency (variable-latency mode).",
        "read_data_phase": "Memory drives RWDS as the edge-aligned "
                          "source-synchronous read data strobe.",
        "write_data_phase": "Host drives RWDS as the byte data mask (RWDS high "
                           "= mask/skip the byte, RWDS low = write the byte).",
    }
    d["burst"] = {
        "wrapped_lengths_bytes": list(_BURST_LENGTHS),
        "linear": "Address increments linearly until CS# deasserts.",
        "wrapped": "Wraps within the configured burst-length boundary.",
        "hybrid": "Begins as a wrapped burst then continues linearly past the "
                  "wrap boundary.",
        "burst_length_config": "Configuration Register 0 (CR0).",
    }
    d["addressing"] = {
        "note": "HyperBus addresses the memory array by the row+upper-column "
                "address in CA[44:16] plus the lower-column byte address in "
                "CA[2:0]; the register space is selected by Address Space=1 "
                "(CA[46]) and addresses the ID/Configuration registers.",
        "row_upper_column_bits": "CA[44:16]",
        "lower_column_bits": "CA[2:0]",
        "register_space_select": "CA[46] = 1",
    }
    d["byte_oriented"] = True
    d["double_data_rate"] = True
    d["bit_stuffing"] = False
    d["arbitration_based"] = False
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / configuration model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "HyperBus devices expose a small register space (selected by Address "
        "Space = 1 in the Command-Address): read-only Identification Registers "
        "ID0/ID1 and read/write Configuration Registers CR0/CR1. CR0/CR1 set "
        "the operating parameters (initial latency count, fixed/variable "
        "latency, output drive strength, burst length / hybrid burst, deep "
        "power down, refresh control). A register access uses R/W#=0/1 with "
        "Address Space=1 in the CA.")
    d["register_access"] = {
        "transport": "HyperBus Command-Address with Address Space (CA[46]) = 1",
        "register_read": "R/W#=1, Address Space=1",
        "register_write": "R/W#=0, Address Space=1",
        "configured_at": "power-up defaults; reprogrammed by the host before "
                         "high-frequency operation",
    }
    d["registers"] = [
        {"name": "ID0", "access": "read-only",
         "purpose": "Manufacturer/device identification, row/column address "
                    "bit counts, device-size information."},
        {"name": "ID1", "access": "read-only",
         "purpose": "Additional device identification."},
        {"name": "CR0", "access": "read/write",
         "purpose": "Deep Power Down enable (HyperRAM), output Drive Strength, "
                    "Initial Latency count (3..7 clocks), Fixed/Variable "
                    "Latency select, Burst Length (16/32/64/128 bytes) + "
                    "Hybrid Burst enable, Burst Type default."},
        {"name": "CR1", "access": "read/write",
         "purpose": "Refresh interval / distributed-refresh control (HyperRAM) "
                    "and other device-specific options."},
    ]
    d["register_fields_cr0"] = [
        "Deep Power Down enable (HyperRAM)",
        "Output Drive Strength (DQ / RWDS impedance)",
        "Initial Latency count (e.g. 3..7 clocks)",
        "Fixed vs Variable Latency select",
        "Burst Length (16 / 32 / 64 / 128 bytes) + Hybrid Burst enable",
        "Burst Type default (wrapped / linear)",
    ]
    d["protocol_fields"] = {
        "command_address_bits": _CA_BITS,
        "data_bus_width_bits": _DQ_WIDTH,
        "initial_latency_clocks_options": list(_LATENCY_CODES),
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
        "Single-ended CMOS signalling on DQ[7:0] and RWDS with a differential "
        "clock CK/CK# (single-ended CK option at 1.8 V). Data is double-data-"
        "rate (clocked on both CK edges). Read data is captured against the "
        "memory-driven RWDS strobe (source-synchronous, edge-aligned), so the "
        "host does not re-derive read timing from CK. Output Drive Strength of "
        "DQ and RWDS is programmable (CR0) to tune board signal integrity. The "
        "interface supports 1.8 V and 3.0 V supply variants and reaches up to "
        "166 MHz / 333 MB/s.")
    d["modulation"] = (
        "Single-ended CMOS levels on DQ/RWDS; differential CK/CK# clock.")
    d["clocking"] = (
        "Host-forwarded clock CK/CK# (source-synchronous, double data rate); "
        "read data is strobed by the memory-driven RWDS, not by a recovered "
        "clock.")
    d["transmitter_specs_canonical"] = {
        "data_bus_width_bits": _DQ_WIDTH,
        "double_data_rate": True,
        "max_clock_freq_MHz": _MAX_FREQ_MHZ,
        "max_throughput_MB_s": _MAX_THROUGHPUT_MB_S,
        "clock": "differential CK/CK# (single-ended CK at 1.8 V)",
        "drive_strength": "programmable output drive strength (CR0) on DQ and "
                          "RWDS",
        "supply_voltages_V": list(_VOLTAGES),
    }
    d["receiver_specs_canonical"] = {
        "read_strobe": "RWDS — memory-driven, edge-aligned with DDR read data "
                       "on DQ[7:0]",
        "write_mask": "RWDS driven by the host as a byte data mask during "
                      "writes",
        "capture": "source-synchronous DDR capture against RWDS (reads)",
    }
    d["bit_time_note"] = (
        "At 166 MHz DDR the effective data period is ~3 ns per byte (one byte "
        "per clock edge); throughput = 2 x 166 MHz x 1 byte = 333 MB/s.")
    d["supported_voltages_V"] = list(_VOLTAGES)
    d["encoding_role_in_analog"] = (
        "HyperBus uses no line code: integrity comes from the source-"
        "synchronous RWDS strobe (read capture timing) and the programmable "
        "drive strength rather than from a DC-balancing code. The "
        "differential clock and short, low-pin-count channel keep the DDR eye "
        "open up to 166 MHz.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / transaction FSM.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_transaction"] = [
        {"name": "IDLE", "description": "CS# high; bus idle; clock may be "
         "stopped; HyperRAM continues self-refresh."},
        {"name": "CA_PHASE", "description": "CS# low; host drives the 48-bit "
         "Command-Address on DQ[7:0] over three clocks (six DDR bytes)."},
        {"name": "LATENCY", "description": "Device inserts the configured "
         "initial latency (3..7 clocks); in variable-latency mode RWDS during "
         "CA selected 1x or 2x."},
        {"name": "READ_DATA", "description": "Memory drives DDR read data on "
         "DQ[7:0] with RWDS as the edge-aligned read strobe."},
        {"name": "WRITE_DATA", "description": "Host drives DDR write data on "
         "DQ[7:0] with RWDS as the byte data mask."},
        {"name": "END", "description": "CS# high deasserts and ends the "
         "transaction; return to IDLE."},
    ]
    d["fsm_states_power"] = [
        {"name": "ACTIVE", "description": "A transaction is in progress (CS# "
         "low)."},
        {"name": "STANDBY", "description": "CS# high, clock may stop; HyperRAM "
         "retains data via self-refresh."},
        {"name": "DEEP_POWER_DOWN", "description": "HyperRAM ultra-low-power "
         "state entered via CR0; exit requires a defined wake-up time."},
    ]
    d["fsm_hints"] = {
        "trigger": "CS# falling edge begins CA_PHASE; the 48-bit CA selects "
        "read/write and memory/register; after LATENCY the data phase runs "
        "until CS# rises.",
        "rule": "In variable-latency mode the host MUST sample RWDS during the "
        "CA phase to decide 1x vs 2x latency; in fixed mode latency is always "
        "2x.",
        "abort": "A CS# rising edge at any time ends the transaction "
        "immediately.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up (or after RESET#) the device holds its default "
        "configuration (default initial latency, latency model, drive "
        "strength, burst length). The host typically reads ID0/ID1, programs "
        "CR0/CR1 for the operating frequency, then begins memory "
        "transactions.")
    d["default_ready_state_recommendation"] = {
        "bus_idle": "CS# high; DQ/RWDS released (high-Z); clock may be "
                    "stopped.",
        "tx_active": "Assert CS# low and drive the 48-bit CA, then data on the "
                     "appropriate edges.",
        "rx_idle": "Release DQ/RWDS for the memory to drive read data + "
                   "strobe.",
    }
    d["configurations"] = [
        {"name": "HyperRAM (self-refresh PSRAM)", "description": "Variable "
         "latency hides refresh collisions; deep power down via CR0."},
        {"name": "HyperFlash (NOR flash)", "description": "Same CA/latency/DDR "
         "read flow; NOR program/erase command sequences."},
        {"name": "Fixed-latency host", "description": "Always 2x latency; "
         "simplest deterministic timing."},
        {"name": "Variable-latency host", "description": "1x/2x via "
         "RWDS-during-CA; higher average throughput."},
    ]
    d["timing_dependency_rule"] = (
        "All command, address, and data are referenced to CK edges (double "
        "data rate). Read capture is referenced to the memory-driven RWDS "
        "strobe. The initial latency between CA and data is fixed by CR0 (and, "
        "in variable mode, by the RWDS level during the CA phase).")
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
        {"name": "Identification Registers (ID0/ID1)", "purpose": "Read-only "
         "manufacturer/device ID, row/column address bit counts, and device "
         "size — used to discover and validate the attached device."},
        {"name": "Configuration Registers (CR0/CR1)", "purpose": "Read back "
         "the configured latency, latency model, drive strength, burst "
         "length, and refresh control to confirm host programming."},
        {"name": "RWDS during CA", "purpose": "Observe the variable-latency "
         "1x/2x indication for timing bring-up."},
        {"name": "RWDS read strobe", "purpose": "The edge-aligned read strobe "
         "is the key signal-integrity / timing observable during read "
         "bring-up."},
    ]
    d["error_detection_mechanisms"] = [
        "Read-back of ID/Configuration registers verifies device presence and "
        "host programming.",
        "RWDS strobe alignment confirms DDR read capture timing.",
        "Variable-latency RWDS-during-CA indicates refresh-collision delays "
        "(HyperRAM).",
        "Drive-strength adjustment (CR0) addresses board signal-integrity "
        "failures.",
    ]
    d["test_modes"] = [
        {"name": "Register read/write", "purpose": "Exercise ID0/ID1 and "
         "CR0/CR1 access in the register address space."},
        {"name": "Latency sweep", "purpose": "Validate each configurable "
         "initial-latency code (3..7) at the target frequency."},
        {"name": "Burst type / length", "purpose": "Exercise wrapped, linear, "
         "and hybrid bursts at each configured length."},
        {"name": "Deep power down (HyperRAM)", "purpose": "Enter DPD via CR0 "
         "and verify wake-up timing."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Transaction start", "trigger": "CS# falling edge."},
        {"event": "Transaction end", "trigger": "CS# rising edge."},
        {"event": "Variable-latency 2x", "trigger": "RWDS asserted during the "
         "CA phase."},
        {"event": "INT# (optional)", "trigger": "Device-dependent "
         "interrupt/status output."},
    ]
    d["notes"] = (
        "HyperBus's protocol-level test surface is the ID/Configuration "
        "register space plus the RWDS strobe behaviour (variable-latency "
        "indication and read-data strobe). Chip-level JTAG/scan/BIST remain "
        "controller / SoC-integrator concerns.")
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
        "INTERFACE": "HyperBus",
        "DATA_BUS_WIDTH_BITS": _DQ_WIDTH,
        "COMMAND_ADDRESS_BITS": _CA_BITS,
        "COMMAND_ADDRESS_CLOCKS": _CA_CLOCKS,
        "COMMAND_ADDRESS_DDR_BYTES": _CA_DDR_BYTES,
        "DOUBLE_DATA_RATE": True,
        "INITIAL_LATENCY_CLOCKS_OPTIONS": list(_LATENCY_CODES),
        "MAX_CLOCK_FREQ_MHZ": _MAX_FREQ_MHZ,
        "MAX_THROUGHPUT_MB_S": _MAX_THROUGHPUT_MB_S,
        "BURST_LENGTHS_BYTES": list(_BURST_LENGTHS),
        "SUPPORTED_VOLTAGES_V": list(_VOLTAGES),
        "DIFFERENTIAL_CLOCK": True,
        "FORWARDED_CLOCK": True,
        "EMBEDDED_CLOCK": False,
        "RWDS_BIDIRECTIONAL": True,
        "CS_ACTIVE_LOW": True,
    })
    d["command_address_constants"] = {
        "ca_bits": _CA_BITS,
        "ca_clocks": _CA_CLOCKS,
        "ca_ddr_bytes": _CA_DDR_BYTES,
        "rw_bit": "CA[47]",
        "address_space_bit": "CA[46]",
        "burst_type_bit": "CA[45]",
        "row_upper_column_bits": "CA[44:16]",
        "reserved_bits": "CA[15:3]",
        "lower_column_bits": "CA[2:0]",
    }
    d["latency_constants"] = {
        "initial_latency_clocks_options": list(_LATENCY_CODES),
        "fixed_multiplier": 2,
        "variable_multipliers": [1, 2],
        "configured_in": "CR0",
        "variable_indicator": "RWDS driven during the CA phase",
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_memory_interface": True,
        "is_serial": False,
        "is_parallel_dq": True,
        "data_bus_width_bits": _DQ_WIDTH,
        "double_data_rate": True,
        "differential_clock": True,
        "forwarded_clock": True,
        "embedded_clock": False,
        "command_address_bits": _CA_BITS,
        "command_address_clocks": _CA_CLOCKS,
        "rwds_bidirectional": True,
        "rwds_roles": ["variable-latency indicator (CA)", "read data strobe",
                       "write byte mask"],
        "initial_latency_clocks_options": list(_LATENCY_CODES),
        "fixed_or_variable_latency": True,
        "burst_lengths_bytes": list(_BURST_LENGTHS),
        "device_families": ["HyperRAM", "HyperFlash"],
        "registers": list(_REGISTERS),
        "max_clock_freq_MHz": _MAX_FREQ_MHZ,
        "max_throughput_MB_s": _MAX_THROUGHPUT_MB_S,
        "cs_active_low": True,
    })
    d["default_signal_values_when_idle"] = {
        "bus_idle": "CS# high; DQ[7:0] and RWDS released (high-Z); clock may "
                    "be stopped.",
        "tx_gating": "CS# asserted low only for the duration of a "
                     "transaction.",
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
        "clock": "differential CK/CK# (single-ended CK at 1.8 V)",
        "double_data_rate": True,
        "max_freq_MHz": _MAX_FREQ_MHZ,
        "note": "Command, address, and data are clocked on both edges of CK.",
    }
    d["command_address_waveform"] = {
        "bits": _CA_BITS,
        "clocks": _CA_CLOCKS,
        "ddr_bytes": _CA_DDR_BYTES,
        "order": "MSB byte first on the first rising edge after CS# low",
        "sequence": "CA[47:40], CA[39:32], CA[31:24], CA[23:16], CA[15:8], "
                    "CA[7:0]",
    }
    d["latency_waveform"] = {
        "initial_latency_clocks_options": list(_LATENCY_CODES),
        "fixed": "always 2x configured latency",
        "variable": "1x or 2x; RWDS driven during CA selects (asserted = 2x)",
        "configured_in": "CR0",
    }
    d["read_data_waveform"] = {
        "bus": "DQ[7:0] at double data rate, one byte per edge",
        "strobe": "RWDS driven by the memory, edge-aligned with read data "
                  "(source-synchronous capture)",
    }
    d["write_data_waveform"] = {
        "bus": "DQ[7:0] at double data rate, one byte per edge",
        "mask": "RWDS driven by the host as a byte data mask (high = mask, "
                "low = write)",
    }
    d["transaction_waveform"] = {
        "order": ["CS# low", "48-bit CA (3 clocks)", "initial latency",
                  "DDR data phase", "CS# high"],
        "burst": "wrapped (16/32/64/128 B) / linear / hybrid; ends on CS# "
                 "high",
    }
    d["general_timing_rule"] = (
        "All command/address/data are referenced to CK edges at double data "
        "rate; read capture is referenced to the memory-driven RWDS strobe; "
        "the CA-to-data initial latency is set by CR0 (and the RWDS level "
        "during CA in variable mode). Peak throughput is 2 x 166 MHz x 1 byte "
        "= 333 MB/s.")
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
        "Low-pin-count DDR memory interface connecting a host controller "
        "(master) to one or more HyperBus memory devices (HyperRAM / "
        "HyperFlash slaves) over CK/CK#, CS# (per device), DQ[7:0], and RWDS, "
        "with a 48-bit Command-Address transaction, configurable latency, and "
        "DDR data up to 166 MHz / 333 MB/s.")
    d["topology_description"] = (
        "A host drives the shared CK/CK#, DQ[7:0], and RWDS, with one CS# per "
        "HyperBus device. Devices are selected by their individual CS#; "
        "HyperRAM and HyperFlash share the same pin-out and may coexist on the "
        "bus.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "interface": "HyperBus",
        "data_bus_width_bits": _DQ_WIDTH,
        "double_data_rate": True,
        "differential_clock": True,
        "command_address_bits": _CA_BITS,
        "command_address_clocks": _CA_CLOCKS,
        "initial_latency_clocks_options": list(_LATENCY_CODES),
        "rwds_bidirectional": True,
        "burst_lengths_bytes": list(_BURST_LENGTHS),
        "max_clock_freq_MHz": _MAX_FREQ_MHZ,
        "max_throughput_MB_s": _MAX_THROUGHPUT_MB_S,
        "supported_voltages_V": list(_VOLTAGES),
        "device_families": ["HyperRAM", "HyperFlash"],
        "registers": list(_REGISTERS),
        "host_side_register_spec": "ID0/ID1 (read-only) + CR0/CR1 "
        "(configuration: latency count, fixed/variable latency, drive "
        "strength, burst length, deep power down, refresh control) in the "
        "register address space.",
    })
    d["interface_categories"] = [
        "Clock — differential CK/CK# (single-ended CK at 1.8 V), host-driven, "
        "double data rate.",
        "Chip select — CS# per device, active low.",
        "Data — 8-bit bidirectional DDR bus DQ[7:0] (CA, then read/write "
        "data).",
        "Strobe — RWDS (variable-latency indicator / read strobe / write byte "
        "mask).",
        "Optional — RESET#, INT#.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single HyperBus device (point-to-point host <-> memory).",
        "Multiple devices sharing CK/DQ/RWDS, selected by individual CS#.",
        "Mixed HyperRAM + HyperFlash on the same bus (shared pin-out).",
    ]
    d["default_signal_values_when_omitted"] = (
        "CS# high (idle); DQ[7:0] and RWDS high-Z; clock optionally stopped. "
        "RESET#/INT# are optional and may be tied off if unused.")
    d["soc_dependent_items"] = [
        "Host HyperBus controller (CA generation, latency tracking, RWDS "
        "capture, DDR PHY).",
        "Number of devices and CS# routing on the shared bus.",
        "Operating frequency and the matching CR0 initial-latency code.",
        "Drive-strength setting for the board signal integrity.",
        "Supply-voltage variant (1.8 V single-ended CK vs 3.0 V differential "
        "CK).",
        "HyperRAM refresh / deep-power-down policy; HyperFlash program/erase "
        "command driver.",
    ]
    d["device_classes_examples"] = [
        "HyperRAM expansion-RAM device (self-refresh pseudo-SRAM)",
        "HyperFlash code/data NOR-flash device",
        "Host MCU/SoC with an integrated HyperBus controller",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — test cases / compliance categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines compliance behaviours (CA "
        "format, latency model, RWDS roles, register access, burst types) but "
        "does not ship a full testbench.")
    d["derived_compliance_test_categories"] = [
        "48-bit Command-Address: three clocks (six DDR bytes), MSB byte first, "
        "correct R/W# / Address Space / Burst Type / address bits.",
        "Initial latency: each configurable code (3..7) honoured at the target "
        "frequency.",
        "Fixed vs variable latency: variable RWDS-during-CA selects 1x vs 2x.",
        "RWDS read strobe: edge-aligned DDR read capture.",
        "RWDS write mask: byte masking on writes (high = mask, low = write).",
        "Register access: ID0/ID1 read, CR0/CR1 read/write in the register "
        "address space.",
        "Burst types: wrapped (16/32/64/128 B), linear, hybrid.",
        "HyperRAM self-refresh transparency and refresh-collision variable "
        "latency.",
        "Deep Power Down entry/exit (HyperRAM) and wake-up timing.",
        "HyperFlash NOR program/erase command sequences on the same bus.",
        "DDR data throughput up to 166 MHz / 333 MB/s.",
        "1.8 V (single-ended CK) and 3.0 V (differential CK) variants.",
        "RESET# returns the device to power-up default configuration.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned fields (capability equivalents).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "Manufacturer / Device ID", "location": "ID0/ID1 (read-only "
         "Identification Registers)",
         "note": "Factory-set device identity, readable over the register "
                 "address space."},
        {"field": "Row / Column Address bit counts", "location": "ID0",
         "note": "Define the device's array geometry / size."},
        {"field": "Device family (HyperRAM / HyperFlash)",
         "location": "ID registers",
         "note": "Identifies the memory type on the shared HyperBus."},
        {"field": "Default Configuration", "location": "CR0/CR1 power-up "
         "defaults",
         "note": "Default initial latency, latency model, drive strength, and "
                 "burst length applied at power-up / RESET#."},
    ]
    d["notes"] = (
        "HyperBus does not define OTP/fuse content as a protocol concept. The "
        "interoperability-relevant facts (manufacturer/device ID, array "
        "geometry, device family) are factory-set and read from the read-only "
        "Identification Registers (ID0/ID1); the Configuration Registers "
        "(CR0/CR1) hold reprogrammable defaults applied at power-up / RESET#.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["read_transaction_sequence"] = [
        "1. Host drives CS# low.",
        "2. Host drives the differential clock CK / CK#.",
        "3. Host sends the 48-bit Command-Address on DQ[7:0] over three clocks "
        "(R/W#=1 for read).",
        "4. (Variable latency) the memory drives RWDS during CA to signal 1x "
        "or 2x latency.",
        "5. Device inserts the configured initial latency (CR0).",
        "6. Memory drives DDR read data on DQ[7:0] with RWDS as the "
        "edge-aligned read strobe.",
        "7. Host captures the DDR read burst using RWDS.",
        "8. Host drives CS# high to end the transaction.",
    ]
    d["write_transaction_sequence"] = [
        "1. Host drives CS# low.",
        "2. Host sends the 48-bit Command-Address on DQ[7:0] (R/W#=0 for "
        "write).",
        "3. Device inserts the initial latency (memory-array writes).",
        "4. Host drives DDR write data on DQ[7:0]; the host drives RWDS as a "
        "byte data mask (high = mask/skip, low = write).",
        "5. Host drives CS# high to end the transaction.",
    ]
    d["register_access_sequence"] = [
        "1. Host drives CS# low and sends a CA with Address Space=1.",
        "2. Register read (R/W#=1): the device returns the ID0/ID1 or CR0/CR1 "
        "contents.",
        "3. Register write (R/W#=0): the host writes CR0/CR1 (latency, drive "
        "strength, burst length, refresh control).",
        "4. Host drives CS# high to end the access.",
    ]
    d["deep_power_down_sequence"] = [
        "1. Host writes CR0 to enter Deep Power Down (HyperRAM).",
        "2. Device enters ultra-low-power state; array retention is per "
        "device variant.",
        "3. Host wakes the device (CS#/CR0 per datasheet) and waits the "
        "wake-up time before normal access.",
    ]
    d["reset_sequence"] = [
        "1. RESET# asserted (active low) — device returns to power-up default "
        "configuration.",
        "2. RESET# deasserted — host may re-read ID and reprogram CR0/CR1 "
        "before transactions.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration / characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "DDR data eye vs RWDS strobe", "purpose": "Verify read data "
         "on DQ[7:0] is correctly captured against the memory-driven RWDS "
         "strobe up to 166 MHz."},
        {"name": "Initial latency", "purpose": "Confirm the configured "
         "initial-latency code (3..7) matches the operating frequency."},
        {"name": "Variable-latency RWDS-during-CA", "purpose": "Confirm the "
         "device's 1x/2x indication and the host's correct response."},
        {"name": "Drive strength", "purpose": "Tune DQ/RWDS output drive "
         "(CR0) for board signal integrity at the target frequency."},
        {"name": "Deep power down wake-up", "purpose": "Measure HyperRAM DPD "
         "exit / wake-up time."},
        {"name": "Throughput", "purpose": "Confirm up to 333 MB/s at 166 MHz "
         "DDR on the 8-bit bus."},
    ]
    d["notes"] = (
        "HyperBus characterization centres on the DDR data-vs-RWDS-strobe "
        "timing, the CA-to-data initial latency (and variable-latency RWDS "
        "indication), and the programmable drive strength. Per-board bring-up "
        "tunes the latency code and drive strength for the operating "
        "frequency.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — versioning.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "HyperBus Interface Specification (Cypress Semiconductor / Infineon "
        "Technologies)")
    f["previous_versions"] = [
        "Cypress HyperBus — original definition: differential CK/CK#, CS#, "
        "8-bit DDR DQ[7:0], RWDS, 48-bit Command-Address, configurable "
        "latency, HyperRAM + HyperFlash.",
    ]
    f["key_changes"] = [
        {"version": "Infineon (post-Cypress acquisition)",
         "summary": "HyperBus maintained by Infineon Technologies; the "
         "interface (CA format, RWDS roles, configurable latency, DDR DQ, "
         "HyperRAM/HyperFlash families, ID/Configuration registers) is carried "
         "forward unchanged."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "RWDS_is_multi-role",
         "rule": "RWDS is a variable-latency indicator during CA, a read "
                 "strobe during reads, and a write byte mask during writes.",
         "trap": "Treating RWDS as a single fixed-direction signal corrupts "
                 "either latency selection, read capture, or write masking."},
        {"trap_name": "Latency_must_match_frequency",
         "rule": "The CR0 initial-latency code (3..7) must be increased for "
                 "higher clock frequencies.",
         "trap": "Running at high frequency with a low latency code corrupts "
                 "data capture."},
        {"trap_name": "Fixed_vs_variable_latency",
         "rule": "Fixed = always 2x; variable = 1x/2x signalled by "
                 "RWDS-during-CA.",
         "trap": "Assuming fixed timing in a variable-latency configuration "
                 "(ignoring RWDS during CA) mis-aligns the data phase."},
        {"trap_name": "CA_is_48-bit_over_3_clocks",
         "rule": "The Command-Address is 48 bits sent MSB-byte-first over "
                 "three clocks (six DDR bytes).",
         "trap": "Truncating or mis-ordering the CA selects the wrong "
                 "operation / address."},
    ]
    f["version_naming_history_note"] = (
        "HyperBus was defined by Cypress Semiconductor and is now maintained "
        "by Infineon Technologies (which acquired Cypress). The interface "
        "(differential clock, low pin count, 48-bit Command-Address, RWDS, "
        "configurable latency, HyperRAM and HyperFlash device families) is "
        "consistent across the Cypress and Infineon documentation.")
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
    f["command_address_field_table"] = {
        "header_columns": ["CA Bits", "Field", "Meaning"],
        "rows": [
            ["CA[47]", "R/W#", "1 = Read, 0 = Write"],
            ["CA[46]", "Address Space", "0 = Memory array, 1 = Register space"],
            ["CA[45]", "Burst Type", "0 = Wrapped, 1 = Linear"],
            ["CA[44:16]", "Row & Upper Column Address", "Upper address bits"],
            ["CA[15:3]", "Reserved", "Transmitted as 0"],
            ["CA[2:0]", "Lower Column Address", "Byte address within burst"],
        ],
    }
    f["operation_select_table"] = {
        "header_columns": ["R/W# (CA[47])", "Address Space (CA[46])",
                           "Operation"],
        "rows": [
            ["1", "0", "Memory read"],
            ["0", "0", "Memory write"],
            ["1", "1", "Register read"],
            ["0", "1", "Register write"],
        ],
    }
    f["rwds_role_table"] = {
        "header_columns": ["Phase", "RWDS driven by", "Role"],
        "rows": [
            ["Command-Address (variable latency)", "Memory",
             "1x vs 2x latency indicator (asserted = 2x)"],
            ["Read data", "Memory", "Edge-aligned read data strobe"],
            ["Write data", "Host", "Byte data mask (high = mask, low = write)"],
        ],
    }
    f["register_table"] = {
        "header_columns": ["Register", "Access", "Purpose"],
        "rows": [
            ["ID0", "read-only", "Manufacturer/device ID, array geometry"],
            ["ID1", "read-only", "Additional identification"],
            ["CR0", "read/write", "Latency, drive strength, burst length, DPD"],
            ["CR1", "read/write", "Refresh control, device options"],
        ],
    }
    f["latency_table"] = {
        "header_columns": ["Initial Latency (clocks)", "Typical use"],
        "rows": [
            ["3", "Lowest frequency"],
            ["4", "Low frequency"],
            ["5", "Mid frequency"],
            ["6", "High frequency"],
            ["7", "Highest frequency (e.g. 166 MHz)"],
        ],
    }
    f["burst_length_table"] = {
        "header_columns": ["Wrapped Burst Length (bytes)"],
        "rows": [["16"], ["32"], ["64"], ["128"]],
    }
    f["encoding_note"] = (
        "HyperBus uses no DC-balancing line code; integrity comes from the "
        "source-synchronous RWDS read strobe and programmable drive strength. "
        "The 48-bit Command-Address (sent MSB-byte-first over three clocks) "
        "is the protocol's encoding primitive.")
    f["tables"] = [
        "Command-Address field table (CA[47:0])",
        "Operation-select table (R/W# x Address Space)",
        "RWDS role-by-phase table",
        "Register table (ID0/ID1/CR0/CR1)",
        "Initial-latency table (3..7 clocks)",
        "Wrapped-burst-length table (16/32/64/128 B)",
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
        "Differential clock CK/CK# (single-ended CK option at 1.8 V), "
        "host-driven, double data rate.",
        "Per-device chip select CS#, active low, held low for the whole "
        "transaction.",
        "8-bit bidirectional DDR bus DQ[7:0] for CA and data.",
        "Bidirectional RWDS strobe: variable-latency indicator (CA), read "
        "strobe, write byte mask.",
        "48-bit Command-Address over three clocks, MSB byte first, with R/W# / "
        "Address Space / Burst Type / address fields.",
        "Configurable initial latency (3..7 clocks) in CR0, fixed or variable.",
        "ID (ID0/ID1) and Configuration (CR0/CR1) registers in the register "
        "address space.",
        "HyperRAM self-refresh transparency; HyperFlash NOR command set on the "
        "same bus.",
        "Wrapped (16/32/64/128 B) / linear / hybrid bursts.",
    ]
    f["must_not_have_properties"] = [
        "An embedded/recovered data clock (HyperBus uses a forwarded "
        "differential clock plus the RWDS read strobe).",
        "A single-data-rate-only data phase (HyperBus is double data rate).",
        "SPI-style separate MOSI/MISO unidirectional data lines (HyperBus uses "
        "one shared 8-bit bidirectional DQ bus).",
        "Ignoring RWDS during CA in a variable-latency configuration.",
        "A fixed latency that does not scale with operating frequency.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "CA mis-format", "trigger": "Wrong R/W#/AS/Burst-Type or "
         "wrong byte order in the 48-bit Command-Address."},
        {"mode": "Latency mismatch", "trigger": "Host latency does not match "
         "CR0 / the RWDS-during-CA indication."},
        {"mode": "RWDS mis-handling", "trigger": "Read strobe not used for "
         "capture, or write mask not driven."},
        {"mode": "Refresh-collision data loss", "trigger": "Variable latency "
         "ignored so a HyperRAM refresh corrupts data."},
        {"mode": "DPD access", "trigger": "Accessing HyperRAM during Deep "
         "Power Down before wake-up."},
    ]
    f["reset_behavior_compliance"] = (
        "RESET# (active low) returns the device to its power-up default "
        "configuration (default latency, latency model, drive strength, burst "
        "length); the host re-reads ID and reprograms CR0/CR1 before "
        "operating.")
    f["hyperbus_distinguishers"] = (
        "HyperBus is identified by ALL of: a low-pin-count DDR memory "
        "interface with a differential clock CK/CK#, a per-device CS#, an "
        "8-bit bidirectional DDR bus DQ[7:0], and a bidirectional Read-Write "
        "Data Strobe RWDS; a 48-bit Command-Address sent over three clocks "
        "(six DDR bytes) encoding R/W# / Address Space / Burst Type / address; "
        "a Configuration-Register-programmed initial latency (fixed or "
        "variable via RWDS-during-CA); and the HyperRAM (self-refresh "
        "pseudo-SRAM) and HyperFlash (NOR flash) device families. This is "
        "distinct from SPI/QSPI (SCLK/MOSI/MISO single/quad data-rate "
        "shift-register transfers with no RWDS, no 48-bit CA cycle, and no "
        "HyperRAM/HyperFlash family).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog + dependency graph (force-overwrite).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CK / CK#", "direction": "host -> memory",
         "purpose": "Differential clock (single-ended CK at 1.8 V); double "
                    "data rate.",
         "active_levels": "toggling clock up to 166 MHz",
         "idle_level": "may be stopped when CS# high"},
        {"name": "CS#", "direction": "host -> memory",
         "purpose": "Chip select, active low, one per device.",
         "active_levels": "low during a transaction",
         "idle_level": "high (deasserted)"},
        {"name": "DQ[7:0]", "direction": "bidirectional",
         "purpose": "8-bit DDR command/address/data bus (CA then data).",
         "active_levels": "driven by host (CA/write) or memory (read)",
         "idle_level": "high-Z"},
        {"name": "RWDS", "direction": "bidirectional",
         "purpose": "Variable-latency indicator (CA) / read data strobe / "
                    "write byte mask.",
         "active_levels": "memory-driven (CA indicator, read strobe) or "
                          "host-driven (write mask)",
         "idle_level": "high-Z"},
        {"name": "RESET#", "direction": "host -> memory",
         "purpose": "Hardware reset (active low, optional).",
         "active_levels": "low to reset", "idle_level": "high"},
        {"name": "INT#", "direction": "memory -> host",
         "purpose": "Interrupt / status output (optional, device-dependent).",
         "active_levels": "device-dependent", "idle_level": "high"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "CA phase", "meaning": "Host drives the 48-bit "
         "Command-Address on DQ[7:0] over three clocks."},
        {"name": "Read data", "meaning": "Memory drives DDR data on DQ[7:0] "
         "with RWDS as the edge-aligned read strobe."},
        {"name": "Write data", "meaning": "Host drives DDR data on DQ[7:0] "
         "with RWDS as the byte mask."},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "data_bus_width_bits": _DQ_WIDTH,
        "clock_pair": 2,
        "chip_select_per_device": 1,
        "rwds_count": 1,
        "command_address_bits": _CA_BITS,
        "command_address_clocks": _CA_CLOCKS,
    })
    f["global_signals"] = [
        {"name": "CK / CK#", "purpose": "Shared differential clock for the "
         "bus."},
        {"name": "RWDS", "purpose": "Shared bidirectional strobe / mask."},
        {"name": "RESET#", "purpose": "Optional shared hardware reset."},
    ]
    f["dependency_graph"] = {
        "common_rule": "CS# low begins a transaction; the 48-bit "
        "Command-Address on DQ[7:0] precedes the initial latency, which "
        "precedes the DDR data phase. Read capture depends on the "
        "memory-driven RWDS strobe; variable latency depends on the RWDS level "
        "during the CA phase.",
        "data_dependency": "Data transfer requires: (1) CS# asserted, (2) a "
        "valid 48-bit CA, (3) the configured initial latency elapsed (fixed, "
        "or variable per RWDS-during-CA). Read data is captured against RWDS; "
        "write data is masked by RWDS.",
    }
    f["handshake_pairs"] = [
        {"name": "CS#-transaction", "from": "host", "to": "memory",
         "rule": "CS# low frames the whole transaction; CS# high ends it."},
        {"name": "RWDS-variable-latency", "from": "memory", "to": "host",
         "rule": "RWDS driven during CA tells the host 1x vs 2x latency."},
        {"name": "RWDS-read-strobe", "from": "memory", "to": "host",
         "rule": "RWDS strobes DDR read data for source-synchronous capture."},
        {"name": "RWDS-write-mask", "from": "host", "to": "memory",
         "rule": "RWDS masks/enables each write byte."},
    ]
    f["ordering_rules"] = {
        "ca_order": "48-bit Command-Address sent MSB byte first over three "
        "clocks (six DDR bytes).",
        "data_order": "DDR data one byte per CK edge on DQ[7:0]; wrapped / "
        "linear / hybrid bursts.",
        "tx_rx_simultaneity": "Half-duplex on the shared DQ bus; only one "
        "direction at a time.",
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
        "Host-to-memory bus: a host controller (master) drives the shared "
        "CK/CK#, DQ[7:0], and RWDS, with one CS# per HyperBus device (slave). "
        "Devices are selected by their individual CS#; HyperRAM and HyperFlash "
        "share the same pin-out and may coexist on the bus.")
    f["supported_topologies"] = [
        {"name": "Point-to-point", "description": "One host, one HyperBus "
         "device."},
        {"name": "Multi-device shared bus", "description": "Several devices "
         "share CK/DQ/RWDS, each with its own CS#."},
        {"name": "Mixed HyperRAM + HyperFlash", "description": "RAM and flash "
         "on the same bus (shared pin-out / footprint)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host controller (master)", "description": "Drives CK/CK#, "
         "CS#, the CA, and write data/RWDS-mask; captures read data using "
         "RWDS."},
        {"role": "HyperBus device (slave)", "description": "HyperRAM or "
         "HyperFlash; responds to its CS#; drives read data + RWDS strobe and "
         "the variable-latency RWDS indication."},
    ]
    f["interconnect_role"] = (
        "HyperBus is a host-to-memory interface: the host originates every "
        "transaction (CA + latency + data) and the selected device responds. "
        "There is no peer arbitration — the host owns the bus and selects one "
        "device at a time via CS#.")
    f["ordering_guarantees"] = {
        "transaction_order": "Transactions are issued one at a time by the "
        "host, framed by CS#.",
        "burst_order": "Wrapped bursts wrap within the configured length; "
        "linear bursts increment until CS# deasserts.",
    }
    f["memory_vs_peripheral_regions"] = (
        "HyperBus addresses a memory array (Address Space=0; row+upper-column "
        "in CA[44:16], lower-column byte in CA[2:0]) and a register space "
        "(Address Space=1; ID0/ID1, CR0/CR1).")
    dc = _ensure_dict(f, "device_classification")
    dc["hyperram"] = ("Self-refresh pseudo-static RAM (DRAM core, SRAM-like "
                      "interface, distributed refresh, deep power down).")
    dc["hyperflash"] = ("NOR flash on the identical HyperBus interface; "
                        "program/erase via NOR command sequences.")
    dc["host_controller"] = ("Master that drives CK/CS#/CA/RWDS and the DDR "
                             "PHY.")
    f["default_signal_values_evidence_tables"] = [
        "HyperBus signal list (CK/CK#, CS#, DQ[7:0], RWDS, RESET#, INT#)",
        "48-bit Command-Address field table (CA[47:0])",
        "RWDS role-by-phase table",
        "ID/Configuration register table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — channel constraints / PDK.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "single-ended CMOS DQ/RWDS; differential CK/CK# (single-"
                     "ended CK at 1.8 V)",
        "data_bus_width_bits": _DQ_WIDTH,
        "double_data_rate": True,
        "max_clock_freq_MHz": _MAX_FREQ_MHZ,
        "max_throughput_MB_s": _MAX_THROUGHPUT_MB_S,
        "supported_voltages_V": list(_VOLTAGES),
        "drive_strength": "programmable (CR0) on DQ and RWDS",
        "initial_latency_clocks_options": list(_LATENCY_CODES),
        "burst_lengths_bytes": list(_BURST_LENGTHS),
        "read_capture": "source-synchronous against the memory-driven RWDS "
                        "strobe",
    }
    f["notes"] = (
        "HyperBus fixes the electrical/timing channel model (single-ended "
        "DDR DQ/RWDS with a differential clock, source-synchronous read "
        "capture against RWDS, programmable drive strength, configurable "
        "latency). It does not impose PDK-specific SDC/floorplan constraints; "
        "those (DDR PHY, board routing, drive-strength tuning) are "
        "controller / SoC-integrator concerns.")
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
        {"name": "Identification Registers (ID0/ID1)", "purpose": "Discover "
         "and validate the attached device (manufacturer/device ID, array "
         "geometry)."},
        {"name": "Configuration Registers (CR0/CR1)", "purpose": "Read back "
         "the configured latency, drive strength, burst length, and refresh "
         "control."},
        {"name": "RWDS observation", "purpose": "Observe the "
         "variable-latency indication and read strobe for timing bring-up."},
        {"name": "Burst / latency sweeps", "purpose": "Exercise each latency "
         "code and burst type to validate the timing window."},
    ]
    f["internal_diagnostics_observability"] = [
        "ID/Configuration register read-back.",
        "RWDS strobe alignment for DDR read capture.",
        "Variable-latency 1x/2x indication (HyperRAM refresh collision).",
        "Deep Power Down entry/exit status (HyperRAM).",
    ]
    f["out_of_band_test_facilities"] = [
        "Vendor device characterization / ATE — implementation-defined, not "
        "part of the HyperBus interface spec.",
    ]
    f["notes"] = (
        "HyperBus's protocol-level test surface is the ID/Configuration "
        "register space plus the RWDS strobe behaviour. Chip-level JTAG / scan "
        "/ BIST remain controller / SoC-integrator concerns.")
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
    f["power_states"] = [
        {"state": "ACTIVE", "name": "Active", "description": "A transaction "
         "is in progress (CS# low).",
         "exit_latency_estimate": "n/a (active)"},
        {"state": "STANDBY", "name": "Standby / Idle", "description": "CS# "
         "high; clock may stop; HyperRAM retains data via self-refresh.",
         "exit_latency_estimate": "fast (resume on CS# low)"},
        {"state": "DEEP_POWER_DOWN", "name": "Deep Power Down",
         "description": "HyperRAM ultra-low-power state entered via CR0; "
         "exit requires a defined wake-up time.",
         "exit_latency_estimate": "wake-up time (device-defined)"},
    ]
    f["power_rails"] = [
        {"rail": "VCC", "purpose": "Core supply."},
        {"rail": "VCCQ", "purpose": "I/O supply (1.8 V or 3.0 V variant)."},
        {"rail": "VSS", "purpose": "Ground."},
    ]
    f["supported_voltages_V"] = list(_VOLTAGES)
    f["power_considerations"] = (
        "HyperBus's low pin count and single-ended DDR signalling keep I/O "
        "power modest. HyperRAM offers a Deep Power Down mode (via CR0) for "
        "ultra-low standby current, and a Standby state where the clock can be "
        "stopped while self-refresh maintains data. The 1.8 V variant (with a "
        "single-ended-clock option) reduces I/O power versus the 3.0 V "
        "differential-clock variant.")
    f["notes"] = (
        "Power states are ACTIVE / STANDBY / DEEP POWER DOWN, with self-refresh "
        "(HyperRAM) maintaining data in standby. Supply variants are 1.8 V and "
        "3.0 V.")
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
        "Command-Address — 48-bit, three clocks, MSB-byte-first, all "
        "R/W#/AS/Burst-Type/address combinations.",
        "Initial latency — each configurable code (3..7) at the target "
        "frequency.",
        "Fixed vs variable latency — RWDS-during-CA 1x/2x selection.",
        "RWDS read strobe — edge-aligned DDR read capture.",
        "RWDS write mask — byte masking on writes.",
        "Register access — ID0/ID1 read, CR0/CR1 read/write.",
        "Burst types — wrapped (16/32/64/128 B), linear, hybrid.",
        "HyperRAM self-refresh transparency + refresh-collision variable "
        "latency.",
        "Deep Power Down entry/exit and wake-up timing.",
        "HyperFlash NOR program/erase command sequences.",
        "Throughput — up to 166 MHz / 333 MB/s.",
        "Voltage variants — 1.8 V (single-ended CK) and 3.0 V (differential "
        "CK).",
        "RESET# — return to power-up default configuration.",
    ]
    f["notes"] = (
        "HyperBus does not ship a formal testbench, but the specification "
        "implies a verification plan spanning the Command-Address format, the "
        "latency model (fixed/variable, RWDS-during-CA), the RWDS read/write "
        "roles, register access, burst types, the HyperRAM refresh / power "
        "modes, and the HyperFlash command set, up to the rated frequency.")
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
        "Source-synchronous RWDS read strobe preserves DDR read-capture "
        "integrity.",
        "Variable-latency RWDS-during-CA prevents refresh-collision data loss "
        "(HyperRAM).",
        "Programmable drive strength (CR0) maintains signal integrity at high "
        "frequency.",
        "RESET# returns the device to a known default configuration.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Memory-content protection (encryption, secure-boot of HyperFlash "
        "code) is a system/controller responsibility above the HyperBus "
        "interface.",
        "Some HyperFlash devices add a one-time-programmable / protection "
        "region as a device feature, not a HyperBus-interface requirement.",
    ]
    f["notes"] = (
        "HyperBus is a memory-interface specification: its built-in "
        "protections are anti-corruption only (RWDS read strobe, "
        "variable-latency refresh hiding, programmable drive strength, "
        "RESET# default). Confidentiality / integrity / authentication of the "
        "stored data are the host/SoC's responsibility, not part of the "
        "HyperBus data path.")
    _write(p, d)
