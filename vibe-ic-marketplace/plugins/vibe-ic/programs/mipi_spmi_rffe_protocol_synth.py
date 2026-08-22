"""MIPI System Power Management Interface (SPMI) + RF Front-End Control
Interface (RFFE) protocol synth helper.

Protocol #57 of the Phase-1 doc-extraction sweep (one combined class covering
BOTH MIPI control buses, exactly as ``smbus_pmbus_protocol_synth`` is one class
for SMBus + PMBus). ic_class-gated overlay for a doc that exhibits the
SPMI/RFFE structural signature: a MIPI low-power TWO-WIRE control bus that names
its wires SCLK + SDATA (NOT I2C's SDA/SCL, NOT SPI's MOSI/MISO/SS), frames every
transaction with a Sequence Start Condition (SSC) and a Bus Park Cycle (NOT an
I2C START/STOP), protects every frame with odd parity, and addresses devices
with 4-bit identifiers, together with at least one of:
  * the SPMI signature — multi-master (up to 4 masters) / multi-slave (up to 16
    slaves), 4-bit MASTER_ID + SLAVE_ID, bus arbitration, slave Request, the
    Device Descriptor Block (DDB), and the SPMI command set (Register Read/Write,
    Extended/Long Register Read/Write, Register 0 Write, Authenticated, Master
    Read/Write, Transfer Bus Ownership, Reset/Sleep/Shutdown/Wakeup); OR
  * the RFFE signature — single bus master, up to 15 slaves, 4-bit USID + GSID,
    and the RFFE command set (Register Write/Read, Extended Register Write/Read
    Long, Register 0 Write, Masked Write, Interrupt Read/Identification &
    Clearing, Timed/Triggered access via trigger registers, Mapped Register
    Write) controlling RF front-end slaves (PA / LNA / switch / tuner / PMIC).

Applies MIPI SPMI v2.0 + RFFE v3.0 spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL SPMI/RFFE
signatures (SCLK+SDATA two-wire, the Sequence Start Condition, per-frame parity,
4-bit MASTER_ID/SLAVE_ID/USID/GSID, and the MIPI command vocabulary) read from
the L-doc CONTENT blob ONLY. It NEVER reads the input-document filename or the
benchmark folder name. (A code review flagged exactly a filename read as a HIGH
defect on the AHB+APB detector; this module does not repeat it.)

------------------------------------------------------------------------------
CHICKEN-AND-EGG MUTEX vs the I2C / SMBus-PMBus / SPI detectors
------------------------------------------------------------------------------
A faithful SPMI/RFFE document must contrast itself with I2C and SPI, so its
prose (and therefore the generated L1/L2 blob) contains the words SDA/SCL,
START/STOP, slave address, MOSI/MISO, and even "SMBus"/"PMBus" (the latter are
injected by the I2C synth's related-bus keyword list when ``_is_i2c`` fires
first). This means:

  * the runner's ``_is_i2c`` ((SDA AND SCL) OR (START+STOP+slave-address) AND an
    I2C-name token) DOES fire on the L1+L2 blob (empirically confirmed at build
    time — the spec literally names SDA/SCL and "I2C-bus" in its NOT-I2C
    section), so the I2C synth touches the base docs first; and
  * the SMBus/PMBus detector then ALSO fires (because the I2C synth injected
    "System Management Bus (SMBus)" / "Power Management Bus (PMBus)" into the L1
    keyword list), so the SMBus/PMBus synth may touch the base docs too.

Two defenses, mirroring the I3C-extends-I2C / NVMe-on-PCIe cross-protocol
doctrine:

  (a) ``is_mipi_spmi_rffe`` REQUIRES the SPMI/RFFE-only signature that neither a
      plain-I2C, an SMBus/PMBus, nor an SPI doc contains — the MIPI two-wire
      SCLK+SDATA naming, the Sequence Start Condition (SSC), 4-bit IDs, AND the
      MIPI command vocabulary — and DEFERS when the doc is I2C-primary (SDA/SCL +
      START/STOP + 7-bit address with NONE of the MIPI SSC/4-bit-ID/SPMI-RFFE
      vocabulary), SMBus-primary (PEC/SMBALERT/ARP/PMBus commands and no MIPI
      SSC/SPMI/RFFE signature), or SPI-primary (MOSI/MISO/SS 4-wire with no SSC
      and no MIPI command vocabulary). A genuine I2C/SMBus/SPI doc has no
      "Sequence Start Condition", no "USID"/"GSID", no "SPMI"/"RFFE", so the
      predicate stays False on them.

  (b) The runner is wired to run ``apply_mipi_spmi_rffe_synth`` AFTER the I2C and
      SMBus/PMBus synths, and this routine FORCE-ASSIGNS (direct assignment, NOT
      setdefault) every L1/L2/L3/L4/... key those sibling synths populate with
      the SPMI/RFFE-canonical value, so any I2C / SMBus-PMBus output is fully
      replaced and cannot leak through (cross-protocol force-overwrite
      doctrine). This is the v0.1.89 KEY LESSON applied: a sibling that
      over-fires would silently overwrite — running last + force-assign makes the
      MIPI-canonical values win deterministically.

Public entry: ``apply_mipi_spmi_rffe_synth(generated_docs_dir,
is_mipi_spmi_rffe, ic_name)``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict."""
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

# Canonical SPMI/RFFE structural facts (MIPI SPMI v2.0 / RFFE v3.0).
_SPMI_COMMANDS = [
    "Register Write", "Register Read", "Extended Register Write",
    "Extended Register Read", "Extended Register Write Long",
    "Extended Register Read Long", "Register 0 Write", "Authenticated",
    "Master Write", "Master Read", "Device Descriptor Block Master Read",
    "Device Descriptor Block Slave Read", "Transfer Bus Ownership",
    "Reset", "Sleep", "Shutdown", "Wakeup",
]
_RFFE_COMMANDS = [
    "Register Write", "Register Read", "Extended Register Write",
    "Extended Register Read", "Extended Register Write Long",
    "Extended Register Read Long", "Register 0 Write", "Masked Write",
    "Interrupt Read / Interrupt Identification and Clearing",
    "Timed / Triggered access", "Mapped Register Write",
]
_RFFE_SLAVE_TYPES = ["PA (power amplifier)", "LNA (low-noise amplifier)",
                     "switch", "tuner", "PMIC"]


# ----------------------------------------------------------------------
# Module-level CONTENT-ONLY detector (the runner wires this; evaluated on the
# input_doc-augmented L-doc blob, NEVER on a filename).
# ----------------------------------------------------------------------
def is_mipi_spmi_rffe(blob: str) -> bool:
    """MIPI SPMI + RFFE — low-power two-wire (SCLK/SDATA) control buses.

    MUTEX vs I2C / SMBus-PMBus / SPI: SPMI/RFFE name their wires SCLK + SDATA
    (not SDA/SCL, not MOSI/MISO), frame transactions with a Sequence Start
    Condition (SSC) (not I2C START/STOP), use 4-bit IDs (MASTER_ID/SLAVE_ID for
    SPMI, USID/GSID for RFFE) (not a 7-bit I2C address), and carry the MIPI
    command vocabulary. Requiring the MIPI two-wire naming + SSC + 4-bit-ID +
    the SPMI-or-RFFE command vocabulary keeps the predicate False on a plain
    I2C / SMBus-PMBus / SPI document while firing on a genuine SPMI/RFFE doc.
    All checks read ``blob`` only — no filename / folder / benchmark-name read.
    """
    if not blob:
        return False

    # --- MIPI two-wire naming (SCLK + SDATA), NOT I2C SDA/SCL nor SPI 4-wire ---
    mipi_wires = ("SCLK" in blob and "SDATA" in blob)
    # The SSC is the defining MIPI control-bus framing element (vs I2C
    # START/STOP).
    ssc = ("Sequence Start Condition" in blob or "SSC" in blob)
    # Per-frame parity protection (a MIPI command-bus structural feature).
    parity_frames = ("parity" in blob.lower())

    # --- SPMI-only signature ------------------------------------------------
    spmi_named = "SPMI" in blob or "System Power Management Interface" in blob
    spmi_ids = ("MASTER_ID" in blob and "SLAVE_ID" in blob)
    spmi_features = (
        ("multi-master" in blob.lower() or "Transfer Bus Ownership" in blob)
        or ("Device Descriptor Block" in blob or "DDB" in blob)
        or ("Register 0 Write" in blob and ("Sleep" in blob
                                            and "Shutdown" in blob
                                            and "Wakeup" in blob))
    )
    spmi_specific = spmi_named and (spmi_ids or spmi_features)

    # --- RFFE-only signature ------------------------------------------------
    rffe_named = "RFFE" in blob or "RF Front-End Control Interface" in blob
    rffe_ids = ("USID" in blob or "Unique Slave ID" in blob
                or "GSID" in blob or "Group Slave ID" in blob)
    rffe_front_end = (
        "RF front-end" in blob or "RF Front-End" in blob
        or ("power amplifier" in blob.lower()
            and ("low-noise amplifier" in blob.lower() or "LNA" in blob))
    )
    rffe_cmds = (
        ("Masked Write" in blob)
        or ("Mapped Register Write" in blob)
        or ("trigger register" in blob.lower() or "Triggered" in blob)
    )
    rffe_specific = rffe_named and (rffe_ids and (rffe_front_end or rffe_cmds))

    # --- DEFER if neither MIPI bus signature is present ---------------------
    if not (spmi_specific or rffe_specific):
        return False

    # Anchor: it must actually be a MIPI low-power two-wire control bus framed
    # by an SSC (the SPMI/RFFE family), not some unrelated doc that merely
    # happens to contain one token. Require the MIPI two-wire + SSC framing so
    # the predicate cannot fire on a plain I2C / SMBus-PMBus / SPI doc.
    mipi_family = mipi_wires and ssc and parity_frames
    return bool(mipi_family and (spmi_specific or rffe_specific))


def apply_mipi_spmi_rffe_synth(generated_docs_dir: Path,
                               is_mipi_spmi_rffe: bool,
                               ic_name: Optional[str]) -> None:
    """Apply MIPI SPMI v2.0 / RFFE v3.0 synth when the signature matched.

    A faithful SPMI/RFFE doc trips the sibling I2C (and, via the I2C synth's
    keyword injection, SMBus/PMBus) detectors first. This routine runs LAST and
    FORCE-OVERWRITES (direct assignment, NOT setdefault) every key those sibling
    synths populate with the SPMI/RFFE-canonical value, so sibling output cannot
    leak through (cross-protocol force-overwrite doctrine).
    """
    if not is_mipi_spmi_rffe:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = ic_name
                d["ic_name"] = ic_name
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
# L1 — MIPI SPMI/RFFE datasheet header (FORCE-OVERWRITE the I2C-sibling
# datasheet + keyword list).
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "MIPI System Power Management Interface (SPMI) + RF Front-End Control "
        "Interface (RFFE) Specification")
    d["version"] = "SPMI v2.0 + RFFE v3.0 (MIPI Alliance)"
    d["revised_date"] = "MIPI Alliance (SPMI v2.0 / RFFE v3.0)"
    d["manufacturer"] = "MIPI Alliance"
    d["copyright"] = "© MIPI Alliance"
    d["abstract"] = (
        "MIPI SPMI and RFFE are two related MIPI Alliance low-power two-wire "
        "control buses that share a common electrical and framing model: a "
        "serial clock line (SCLK) and a bidirectional serial data line (SDATA) "
        "carry chip-to-chip control of power-management and RF front-end "
        "components. Both frame every transaction with a Sequence Start "
        "Condition (SSC) and a Bus Park Cycle, protect every command/address/"
        "data frame with odd parity, and address devices with 4-bit "
        "identifiers — deliberately distinct from I2C (SDA/SCL open-drain, "
        "7-bit addressing, START/STOP) and SPI (4-wire MOSI/MISO/SCLK/SS). SPMI "
        "is a multi-master (up to 4 masters), multi-slave (up to 16 slaves) "
        "system-power-management bus using 4-bit MASTER_ID + SLAVE_ID, bus "
        "arbitration, a slave Request capability, the Device Descriptor Block "
        "(DDB), and commands including Register Read/Write, Extended (Long) "
        "Register Read/Write, Register 0 Write, Authenticated, Master "
        "Read/Write, Transfer Bus Ownership, Reset, Sleep, Shutdown, and "
        "Wakeup. RFFE is a single-master, multi-slave (up to 15 slaves) RF "
        "front-end control bus using 4-bit USID + GSID and commands including "
        "Register Write/Read, Extended Register Write/Read (Long), Register 0 "
        "Write, Masked Write, Interrupt Read/Identification & Clearing, "
        "Timed/Triggered access via trigger registers, and Mapped Register "
        "Write, controlling RF slaves such as PA, LNA, switch, tuner, and "
        "PMIC.")
    d["keywords"] = [
        "MIPI", "SPMI", "System Power Management Interface", "RFFE",
        "RF Front-End Control Interface", "SCLK", "SDATA", "two-wire",
        "Sequence Start Condition", "SSC", "parity", "Bus Park Cycle",
        "MASTER_ID", "SLAVE_ID", "USID", "GSID", "Unique Slave ID",
        "Group Slave ID", "multi-master", "arbitration", "Request",
        "Device Descriptor Block", "DDB", "Register 0 Write",
        "Extended Register", "Authenticated", "Transfer Bus Ownership",
        "Reset", "Sleep", "Shutdown", "Wakeup", "Masked Write",
        "Mapped Register Write", "trigger register", "Interrupt",
        "PA", "LNA", "switch", "tuner", "PMIC", "26 MHz", "52 MHz",
    ]
    d["external_pins"] = [
        "SCLK — serial clock line, driven by the (active) bus master; CMOS "
        "push-pull; idles low",
        "SDATA — bidirectional serial data line, driven by master or slave "
        "during their respective frame phases; CMOS push-pull; idles low",
        "VIO / GND — interface supply and ground (the two-wire bus is "
        "low-power CMOS)",
    ]
    d["wire_protocol"] = (
        "Two-wire MIPI control bus: SCLK + SDATA, MSB-first, per-frame odd "
        "parity, framed by a Sequence Start Condition (SSC) and a Bus Park "
        "Cycle. NOT I2C (no SDA/SCL open-drain, no START/STOP, no 7-bit "
        "address) and NOT SPI (no 4-wire MOSI/MISO/SS).")
    d["modes_of_operation"] = [
        {"name": "SPMI — System Power Management Interface",
         "description": "Multi-master (<=4 masters) / multi-slave (<=16 "
         "slaves) bus with 4-bit MASTER_ID + SLAVE_ID, arbitration, slave "
         "Request, DDB, and the SPMI command set including Reset/Sleep/"
         "Shutdown/Wakeup power-state commands."},
        {"name": "RFFE — RF Front-End Control Interface",
         "description": "Single-master / multi-slave (<=15 slaves) bus with "
         "4-bit USID + GSID and the RFFE command set (Masked Write, "
         "Timed/Triggered access, Mapped Register Write, Interrupt) controlling "
         "PA/LNA/switch/tuner/PMIC."},
        {"name": "High clock rate",
         "description": "SPMI up to 26 MHz; RFFE up to 26 MHz (v1/v2) and up to "
         "52 MHz (v3.0); master-supplied clock, no clock recovery."},
    ]
    d["key_features"] = [
        "Common MIPI two-wire control bus: SCLK + SDATA, CMOS push-pull, "
        "MSB-first, framed by a Sequence Start Condition (SSC) and a Bus Park "
        "Cycle.",
        "Per-frame odd parity protects every command, address, and data frame.",
        "4-bit device identifiers: SPMI MASTER_ID + SLAVE_ID; RFFE USID + GSID "
        "(group).",
        "SPMI: multi-master (up to 4 masters), multi-slave (up to 16 slaves), "
        "bus arbitration on priority/MASTER_ID, slave-initiated Request.",
        "SPMI command set: Register Read/Write, Extended (Long) Register "
        "Read/Write, Register 0 Write (short 7-bit write to register 0), "
        "Authenticated, Master Read/Write, DDB Master/Slave Read, Transfer Bus "
        "Ownership.",
        "SPMI power-state commands: Reset, Sleep, Shutdown, Wakeup — applied to "
        "a slave or a group (Group Sub-ID) in one transaction.",
        "RFFE: single bus master controls up to 15 slaves (PA/LNA/switch/tuner/"
        "PMIC); no multi-master arbitration.",
        "RFFE command set: Register Write/Read, Extended Register Write/Read "
        "(Long, byte count), Register 0 Write, Masked Write, Interrupt "
        "Read/Identification & Clearing, Timed/Triggered access, Mapped "
        "Register Write.",
        "RFFE Trigger mechanism: pre-load several slaves and change state "
        "simultaneously on a single trigger event (glitch-free RF "
        "re-configuration; PM triggers).",
        "Clock rate up to 26 MHz (SPMI / RFFE v1-v2) and up to 52 MHz (RFFE "
        "v3.0); master-supplied SCLK, no embedded/recovered clock.",
        "Device Descriptor Block (SPMI) and product/manufacturer ID registers "
        "(RFFE) for discovery and enumeration.",
        "Distinct from I2C (SDA/SCL, 7-bit address, START/STOP) and SPI "
        "(MOSI/MISO/SS 4-wire).",
    ]
    d["system_use_cases"] = [
        "System power management: a platform power controller places PMICs and "
        "sub-PMICs into Sleep/Shutdown/Wakeup via SPMI.",
        "RF front-end control: the modem/transceiver RFFE master configures PA "
        "bias, LNA, antenna/band switches, and tuners with precise triggered "
        "timing.",
        "Coordinated multi-device power state changes via SPMI Group Sub-ID "
        "broadcast.",
        "Glitch-free simultaneous RF state changes across several front-end "
        "slaves via RFFE triggers.",
        "Device discovery/enumeration via the SPMI Device Descriptor Block.",
        "Coexistence of SPMI (system power) and RFFE (RF front-end) on the same "
        "smartphone/modem platform.",
    ]
    d["overview"] = (
        "This specification covers two related MIPI Alliance low-power "
        "two-wire control buses with a shared electrical/framing model. The "
        "System Power Management Interface (SPMI) is a multi-master "
        "(up to 4 masters), multi-slave (up to 16 slaves) bus for system power "
        "management: each transaction names a 4-bit MASTER_ID and 4-bit "
        "SLAVE_ID, masters arbitrate for the bus, slaves can raise a Request, "
        "and the command set (Register Read/Write, Extended/Long Register "
        "Read/Write, Register 0 Write, Authenticated, Master Read/Write, Device "
        "Descriptor Block Read, Transfer Bus Ownership, Reset, Sleep, Shutdown, "
        "Wakeup) lets a power controller manage device power states. The RF "
        "Front-End Control Interface (RFFE) is a single-master, multi-slave "
        "(up to 15 slaves) bus for RF front-end control: each slave has a 4-bit "
        "USID and may belong to a 4-bit GSID, and the command set (Register "
        "Write/Read, Extended Register Write/Read Long, Register 0 Write, Masked "
        "Write, Interrupt Read/Identification & Clearing, Timed/Triggered "
        "access via trigger registers, Mapped Register Write) controls "
        "front-end slaves such as PA, LNA, switch, tuner, and PMIC. Both buses "
        "use SCLK + SDATA, begin every transaction with a Sequence Start "
        "Condition (SSC), protect every frame with odd parity, address devices "
        "with 4-bit identifiers, and run at up to 26 MHz (SPMI / RFFE v1-v2) or "
        "52 MHz (RFFE v3.0) — distinct from I2C and SPI.")
    d["release_history_note"] = (
        "SPMI v1.0 -> v2.0 established and extended multi-master arbitration, "
        "the DDB, Authenticated commands, Master Read/Write, and the power-state "
        "command set. RFFE v1.0 -> v2.0 -> v3.0 added Extended Register Long, "
        "Masked Write, Mapped Register Write, the Trigger/Timed mechanism, Group "
        "(GSID) commands, and raised the maximum clock to 52 MHz. Facts here are "
        "grounded in the public MIPI Alliance SPMI and RFFE specifications.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — SPMI/RFFE functional requirements + protocol overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "MIPI low-power two-wire control bus (SCLK + SDATA), MSB-first, "
        "per-frame odd parity, framed by a Sequence Start Condition (SSC) and "
        "a Bus Park Cycle. One combined class for SPMI (multi-master "
        "system-power-management bus; MASTER_ID/SLAVE_ID; arbitration; "
        "Request; DDB; Reset/Sleep/Shutdown/Wakeup) and RFFE (single-master "
        "RF-front-end control bus; USID/GSID; Masked Write; Timed/Triggered "
        "access; Mapped Register Write).")
    po["duplex"] = (
        "half-duplex (single bidirectional SDATA line turned around within a "
        "transaction; one transaction at a time, master-driven on SPMI after "
        "arbitration, single-master on RFFE).")
    po["synchronous_serial"] = True
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["clock_line"] = "SCLK (driven by the active bus master; CMOS push-pull)"
    po["data_line"] = "SDATA (bidirectional, CMOS push-pull; idles low)"
    po["framing"] = ("Sequence Start Condition (SSC) starts a transaction; a "
                     "Bus Park Cycle ends it. NOT I2C START/STOP.")
    po["bit_order"] = "MSB-first"
    po["parity"] = "odd parity bit appended to every command/address/data frame"
    po["address_bits"] = 4
    po["clock_rate_MHz"] = {"spmi_max": 26, "rffe_v1_v2_max": 26,
                            "rffe_v3_max": 52}
    po["spmi"] = {
        "role": "multi-master / multi-slave",
        "max_masters": 4, "max_slaves": 16,
        "identifiers": {"MASTER_ID_bits": 4, "SLAVE_ID_bits": 4},
        "arbitration": "masters contend; higher command priority and/or lower "
                       "MASTER_ID wins; resolved before the winner's SSC.",
        "request": "a slave raises a Request during the arbitration window to "
                   "be serviced.",
        "ddb": "Device Descriptor Block (manufacturer/product/revision/"
               "function) read via DDB Master/Slave Read.",
        "commands": list(_SPMI_COMMANDS),
        "power_state_commands": ["Reset", "Sleep", "Shutdown", "Wakeup"],
        "group_sub_id": True,
    }
    po["rffe"] = {
        "role": "single-master / multi-slave",
        "max_masters": 1, "max_slaves": 15,
        "identifiers": {"USID_bits": 4, "GSID_bits": 4},
        "slave_types": list(_RFFE_SLAVE_TYPES),
        "commands": list(_RFFE_COMMANDS),
        "trigger": "trigger registers + a Trigger event let several slaves "
                   "change state simultaneously (glitch-free RF "
                   "re-configuration; PM triggers).",
        "masked_write": "updates only mask-selected bits of a register.",
        "mapped_register_write": "writes through a logical-to-physical address "
                                 "mapping.",
        "interrupt": "Interrupt Read / Interrupt Identification and Clearing "
                     "over the two-wire bus (no dedicated interrupt wire).",
    }
    d["protocol_overview"] = po
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "SPMI and RFFE are MIPI two-wire buses "
         "(SCLK + SDATA), CMOS push-pull, MSB-first; the bus idles with SCLK "
         "and SDATA low. They are NOT I2C (no open-drain SDA/SCL) and NOT SPI "
         "(no 4-wire MOSI/MISO/SS)."},
        {"id": "FR-SSC-02", "text": "Every transaction begins with a Sequence "
         "Start Condition (SSC) — a defined SDATA pulse pattern while SCLK is "
         "low — and ends with a Bus Park Cycle; there is no I2C START/STOP "
         "condition."},
        {"id": "FR-PARITY-03", "text": "Every command, address, and data frame "
         "is protected by a single odd parity bit; a parity error causes the "
         "receiver to ignore the frame."},
        {"id": "FR-ID-04", "text": "Devices are addressed by 4-bit "
         "identifiers: SPMI uses MASTER_ID + SLAVE_ID; RFFE uses USID + GSID "
         "(group). 4 bits give up to 16 identities."},
        {"id": "FR-CLK-05", "text": "The master supplies SCLK at up to 26 MHz "
         "(SPMI / RFFE v1-v2) or up to 52 MHz (RFFE v3.0); there is no embedded "
         "or recovered clock."},
        {"id": "FR-SPMI-MM-06", "text": "SPMI supports up to 4 masters and up "
         "to 16 slaves; masters arbitrate for the bus on command priority and "
         "MASTER_ID, exactly one master owns the bus at a time, and ownership "
         "is handed over with Transfer Bus Ownership."},
        {"id": "FR-SPMI-REQ-07", "text": "An SPMI slave can asynchronously "
         "raise a Request during the arbitration window so a master will "
         "address it."},
        {"id": "FR-SPMI-CMD-08", "text": "SPMI commands include Register "
         "Read/Write, Extended (Long) Register Read/Write, Register 0 Write, "
         "Authenticated, Master Read/Write, Device Descriptor Block "
         "Master/Slave Read, Transfer Bus Ownership, and the power-state "
         "commands Reset, Sleep, Shutdown, Wakeup."},
        {"id": "FR-SPMI-PWR-09", "text": "Reset, Sleep, Shutdown, and Wakeup "
         "are first-class SPMI commands and may be applied to a single slave or "
         "a group of slaves (Group Sub-ID) in one transaction."},
        {"id": "FR-SPMI-DDB-10", "text": "Each SPMI device exposes a Device "
         "Descriptor Block (manufacturer ID, product ID, revision, function) "
         "read via DDB Master/Slave Read for discovery and enumeration."},
        {"id": "FR-RFFE-SM-11", "text": "RFFE has exactly one bus master "
         "controlling up to 15 slaves (PA, LNA, switch, tuner, PMIC); there is "
         "no multi-master arbitration and the master fully controls bus "
         "timing."},
        {"id": "FR-RFFE-ID-12", "text": "Each RFFE slave has a 4-bit Unique "
         "Slave ID (USID); slaves may be assigned a 4-bit Group Slave ID "
         "(GSID) so the master can write to a group at once, and a broadcast "
         "USID addresses all slaves."},
        {"id": "FR-RFFE-CMD-13", "text": "RFFE commands include Register "
         "Write/Read, Extended Register Write/Read (Long, byte count), Register "
         "0 Write, Masked Write, Interrupt Read/Identification & Clearing, "
         "Timed/Triggered access via trigger registers, and Mapped Register "
         "Write."},
        {"id": "FR-RFFE-TRIG-14", "text": "RFFE defines trigger registers and "
         "a Trigger mechanism so several slaves can be pre-loaded and change "
         "state simultaneously on a single trigger event (glitch-free RF "
         "re-configuration; PM triggers)."},
        {"id": "FR-REG-15", "text": "Both buses expose an 8-bit (standard) or "
         "16-bit (Extended Long) register address space per slave; Register 0 "
         "is a special low-overhead register and Register 0 Write carries 7 "
         "data bits in the command frame itself."},
    ]
    d["error_response_conditions"] = [
        "Frame parity error — the receiver ignores the frame.",
        "SPMI arbitration loss — a master backs off and retries after the "
        "winning transaction.",
        "Addressed slave not present / no response — the master aborts the "
        "transaction.",
        "Authentication failure (SPMI Authenticated command) — protected "
        "register access is denied.",
        "RFFE interrupt asserted — the master must Interrupt Read / "
        "Identify & Clear to service it.",
        "Malformed SSC / missing Bus Park — devices stay idle and ignore the "
        "sequence.",
    ]
    d["compliance_requirements"] = [
        "Two-wire SCLK/SDATA CMOS bus, MSB-first, framed by SSC + Bus Park "
        "Cycle, with per-frame odd parity.",
        "4-bit device identifiers (MASTER_ID/SLAVE_ID for SPMI; USID/GSID for "
        "RFFE).",
        "SPMI: multi-master arbitration, slave Request, DDB, and the SPMI "
        "command set including Reset/Sleep/Shutdown/Wakeup.",
        "RFFE: single-master operation, up to 15 slaves, and the RFFE command "
        "set including Masked Write, Timed/Triggered access, Mapped Register "
        "Write, and Interrupt handling.",
        "Clock rate within spec (<=26 MHz SPMI / RFFE v1-v2; <=52 MHz RFFE "
        "v3.0).",
        "Register 0 Write supported as the low-overhead single-frame write.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — SPMI/RFFE command/frame protocol (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "MIPI two-wire command-frame protocol. Each transaction is "
        "SSC -> Command Frame (+parity) -> [Address Frame (+parity)] -> "
        "[Data Frame(s) (+parity)] -> Bus Park Cycle. The Command Frame's top "
        "bits select the slave (SLAVE_ID for SPMI, USID/GSID for RFFE) and the "
        "low bits select the command (or, for Register 0 Write, carry 7 data "
        "bits). All bits are MSB-first.")
    d["byte_oriented"] = True
    d["burst_based"] = False
    d["channels"] = [
        {"name": "SCLK", "direction": "master -> bus (CMOS push-pull)",
         "description": "Serial clock supplied by the active master; idles "
         "low; up to 26 MHz (SPMI / RFFE v1-v2) or 52 MHz (RFFE v3.0)."},
        {"name": "SDATA", "direction": "bidirectional (CMOS push-pull)",
         "description": "Serial data carrying command/address/data frames "
         "MSB-first, each with an odd parity bit; turned around within a "
         "transaction; idles low."},
    ]
    d["frame_types"] = [
        {"name": "Sequence Start Condition (SSC)",
         "description": "A defined SDATA pulse while SCLK is low that starts "
         "every transaction and synchronizes all devices."},
        {"name": "Command Frame",
         "description": "Slave identifier (SLAVE_ID / USID-GSID) + command "
         "opcode, MSB-first, + odd parity. Register 0 Write carries 7 data "
         "bits here."},
        {"name": "Address Frame",
         "description": "8-bit (standard) or 16-bit (Extended Long) register "
         "address, MSB-first, + odd parity."},
        {"name": "Data Frame",
         "description": "8 data bits MSB-first + odd parity; Extended/Long "
         "commands carry a byte count so the number of data frames is "
         "explicit."},
        {"name": "Bus Park Cycle",
         "description": "Terminates the transaction and returns the bus to "
         "idle (SCLK toggling, SDATA released)."},
    ]
    d["spmi_commands"] = list(_SPMI_COMMANDS)
    d["rffe_commands"] = list(_RFFE_COMMANDS)
    d["spmi_command_details"] = [
        {"name": "Register Write", "data": "1 byte", "addr": "in frame"},
        {"name": "Register Read", "data": "1 byte", "addr": "in frame"},
        {"name": "Extended Register Write", "data": "up to 16 bytes",
         "addr": "8-bit + byte count"},
        {"name": "Extended Register Read", "data": "up to 16 bytes",
         "addr": "8-bit + byte count"},
        {"name": "Extended Register Write Long", "data": "multi-byte",
         "addr": "16-bit"},
        {"name": "Extended Register Read Long", "data": "multi-byte",
         "addr": "16-bit"},
        {"name": "Register 0 Write", "data": "7 bits in command frame",
         "addr": "register 0"},
        {"name": "Authenticated", "data": "authentication payload",
         "addr": "protected register"},
        {"name": "Master Write", "data": "to another master", "addr": "-"},
        {"name": "Master Read", "data": "from another master", "addr": "-"},
        {"name": "Device Descriptor Block Master Read", "data": "DDB",
         "addr": "-"},
        {"name": "Device Descriptor Block Slave Read", "data": "DDB",
         "addr": "-"},
        {"name": "Transfer Bus Ownership", "data": "-", "addr": "-"},
        {"name": "Reset", "data": "-", "addr": "slave or group"},
        {"name": "Sleep", "data": "-", "addr": "slave or group"},
        {"name": "Shutdown", "data": "-", "addr": "slave or group"},
        {"name": "Wakeup", "data": "-", "addr": "slave or group"},
    ]
    d["rffe_command_details"] = [
        {"name": "Register Write", "data": "1 byte", "addr": "8-bit"},
        {"name": "Register Read", "data": "1 byte", "addr": "8-bit"},
        {"name": "Extended Register Write", "data": "N bytes (byte count)",
         "addr": "8-bit"},
        {"name": "Extended Register Read", "data": "N bytes (byte count)",
         "addr": "8-bit"},
        {"name": "Extended Register Write Long", "data": "multi-byte",
         "addr": "16-bit"},
        {"name": "Extended Register Read Long", "data": "multi-byte",
         "addr": "16-bit"},
        {"name": "Register 0 Write", "data": "7 bits in command frame",
         "addr": "register 0"},
        {"name": "Masked Write", "data": "value + mask",
         "addr": "8-bit (only masked bits change)"},
        {"name": "Interrupt Read / Interrupt Identification and Clearing",
         "data": "interrupt status", "addr": "-"},
        {"name": "Timed / Triggered access", "data": "into trigger register",
         "addr": "applied on a Trigger event"},
        {"name": "Mapped Register Write", "data": "via address mapping",
         "addr": "logical -> physical"},
    ]
    d["addressing"] = {
        "identifier_bits": 4,
        "spmi": "4-bit MASTER_ID + 4-bit SLAVE_ID",
        "rffe": "4-bit USID + 4-bit GSID (group); broadcast USID = all slaves",
        "register_address_bits": "8 (standard) / 16 (Extended Long)",
        "register_0": "special low-overhead register; Register 0 Write carries "
                      "7 data bits in the command frame.",
    }
    d["frame_format"] = {
        "bit_order": "MSB-first per frame.",
        "parity": "each frame ends with one odd parity bit.",
        "transaction_framing": "SSC, then Command Frame, then optional Address "
        "Frame and Data Frame(s), then Bus Park Cycle.",
        "no_i2c_start_stop": "Framing is by SSC + Bus Park Cycle, NOT an I2C "
        "START (SDA falling while SCL high) / STOP condition.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — SPMI/RFFE register model (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "SPMI and RFFE expose a per-slave register space addressed by an 8-bit "
        "(standard) or 16-bit (Extended Long) register address. Register 0 is a "
        "special low-overhead register accessed by Register 0 Write (7 data "
        "bits in the command frame). RFFE Masked Write updates only "
        "mask-selected bits; RFFE Mapped Register Write goes through a "
        "logical-to-physical mapping; SPMI Authenticated commands protect "
        "selected registers. Identity/capability is exposed through the SPMI "
        "Device Descriptor Block and the slave's product/manufacturer ID "
        "registers (RFFE).")
    d["address_space"] = {
        "register_address_bits_standard": 8,
        "register_address_bits_extended_long": 16,
        "register_0_special": True,
        "data_byte_bits": 8,
    }
    d["register_groups"] = [
        {"group": "Standard registers", "fields": [
            "8-bit register address (0x00..0xFF)",
            "Register 0 (special low-overhead, 7-bit write via Register 0 "
            "Write)",
            "Register Read / Register Write access one byte"]},
        {"group": "Extended (Long) registers", "fields": [
            "16-bit register address for Extended Register Read/Write Long",
            "byte-count field for multi-byte transfers (up to 16 bytes "
            "standard Extended)"]},
        {"group": "Identity / capability", "fields": [
            "SPMI Device Descriptor Block: manufacturer ID, product ID, "
            "revision, function",
            "RFFE product/manufacturer ID registers",
            "USID / GSID assignment (RFFE)"]},
        {"group": "RFFE control", "fields": [
            "Trigger registers (Timed/Triggered access)",
            "Masked Write target registers",
            "Mapped register space (Mapped Register Write)",
            "Interrupt status registers"]},
        {"group": "SPMI power state", "fields": [
            "Per-slave/group power-state targets for Reset/Sleep/Shutdown/"
            "Wakeup"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — SPMI/RFFE electrical / signaling (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Two-wire CMOS push-pull-capable signaling: a master-driven serial "
        "clock SCLK and a bidirectional serial data line SDATA, both idling "
        "low. Unlike I2C, SPMI/RFFE are not open-drain wired-AND on SDA/SCL; "
        "unlike SPI there is no separate MOSI/MISO/SS. Data is MSB-first; every "
        "frame carries an odd parity bit. The Sequence Start Condition (SSC) — "
        "an SDATA pulse while SCLK is low — frames the transaction, and a Bus "
        "Park Cycle ends it. SCLK runs up to 26 MHz (SPMI / RFFE v1-v2) or "
        "52 MHz (RFFE v3.0).")
    d["logic_levels"] = {
        "type": "CMOS push-pull (VIO-referenced)",
        "idle_state": "SCLK low, SDATA low",
        "note": "Levels are VIO-relative per the MIPI SPMI/RFFE electrical "
                "spec; not I2C open-drain.",
    }
    d["clock_rate_MHz"] = {"spmi_max": 26, "rffe_v1_v2_max": 26,
                           "rffe_v3_max": 52}
    d["clocking"] = (
        "Synchronous to SCLK driven by the active master; not "
        "source-synchronous forwarded-clock, not embedded/recovered clock.")
    d["framing"] = (
        "Sequence Start Condition (SSC) starts a transaction (SDATA pulse while "
        "SCLK low); a Bus Park Cycle returns the bus to idle.")
    d["parity"] = "odd parity per command/address/data frame."
    d["not_i2c_not_spi"] = (
        "SCLK/SDATA two-wire CMOS bus, framed by SSC, parity-protected, 4-bit "
        "IDs — NOT I2C (SDA/SCL open-drain, 7-bit address, START/STOP) and NOT "
        "SPI (MOSI/MISO/SCLK/SS 4-wire).")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — SPMI/RFFE transaction + arbitration FSM (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states"] = [
        {"name": "IDLE", "description": "Bus idle (SCLK low, SDATA low); "
         "devices listen for an SSC."},
        {"name": "ARBITRATION", "description": "(SPMI) Masters contend for the "
         "bus on command priority / MASTER_ID; slaves may raise a Request. "
         "Resolved before the winner's SSC. (RFFE has a single master, no "
         "arbitration.)"},
        {"name": "SSC", "description": "The winning/sole master drives the "
         "Sequence Start Condition (SDATA pulse while SCLK low)."},
        {"name": "COMMAND", "description": "Command Frame: slave identifier "
         "(SLAVE_ID / USID-GSID) + opcode, MSB-first + odd parity."},
        {"name": "ADDRESS", "description": "Address Frame (for register-"
         "addressed commands): 8-bit or 16-bit register address + parity."},
        {"name": "DATA", "description": "Data Frame(s): 8 data bits MSB-first + "
         "parity each; Extended/Long carry a byte count."},
        {"name": "BUS_PARK", "description": "Bus Park Cycle terminates the "
         "transaction and returns the bus to IDLE."},
        {"name": "PARITY_ERROR", "description": "A frame parity check fails; the "
         "receiver ignores the frame."},
        {"name": "TRIGGER", "description": "(RFFE) A Trigger event applies "
         "previously written trigger-register values simultaneously."},
        {"name": "POWER_STATE", "description": "(SPMI) Reset / Sleep / Shutdown "
         "/ Wakeup applied to a slave or group."},
    ]
    d["arbitration_rule"] = (
        "(SPMI) Up to 4 masters arbitrate per transaction: higher command "
        "priority and/or lower MASTER_ID wins; exactly one master owns the bus "
        "at a time; ownership is transferred with Transfer Bus Ownership. A "
        "slave's Request during the arbitration window flags its need for "
        "service. RFFE has a single master and therefore no arbitration.")
    d["fsm_hints"] = {
        "trigger": "An SSC begins a transaction; a Bus Park Cycle ends it. "
        "(SPMI) arbitration precedes the SSC of the winning master.",
        "rule": "Every frame is MSB-first with an odd parity bit; a parity "
        "mismatch makes the receiver ignore the frame.",
        "abort": "Loss of arbitration (SPMI) makes a master back off and "
        "retry; a missing/invalid SSC or Bus Park leaves devices idle.",
    }
    d["anti_deadlock_rule"] = (
        "(SPMI) Bounded arbitration on priority/MASTER_ID guarantees exactly "
        "one master wins each round, and Transfer Bus Ownership hands the bus "
        "over cleanly, so no master can hold the bus indefinitely. The Bus Park "
        "Cycle always returns the bus to a known idle state. (RFFE) the single "
        "master fully controls timing.")
    d["exit_from_reset"] = (
        "After power-on/reset a device enters IDLE listening for an SSC. SPMI "
        "slaves adopt their SLAVE_ID and RFFE slaves their USID (assigned/"
        "strapped); the controller may issue Reset/Wakeup (SPMI) or initialize "
        "registers (RFFE) before normal operation.")
    d["default_ready_state_recommendation"] = {
        "bus_idle": "SCLK low, SDATA low; listen for SSC.",
        "spmi_master": "Arbitrate only when it has a transaction; release "
                       "ownership when done.",
        "rffe_master": "Drive SCLK and frames directly (single master).",
    }
    d["configurations"] = [
        {"name": "SPMI multi-master", "description": "Up to 4 masters arbitrate "
         "for up to 16 slaves; slave Request supported."},
        {"name": "RFFE single-master", "description": "One master controls up "
         "to 15 slaves; no arbitration."},
        {"name": "RFFE triggered", "description": "Trigger registers + Trigger "
         "event for simultaneous multi-slave state change."},
        {"name": "SPMI grouped power state", "description": "Reset/Sleep/"
         "Shutdown/Wakeup applied to a group via Group Sub-ID."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — observability (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "SPMI Device Descriptor Block (DDB)", "purpose": "Read "
         "manufacturer/product/revision/function for discovery and "
         "enumeration."},
        {"name": "RFFE product/manufacturer ID registers", "purpose": "Identify "
         "the RFFE slave and its USID/GSID."},
        {"name": "RFFE Interrupt Read / Identification & Clearing",
         "purpose": "Discover which slave(s) raised an interrupt and clear "
         "it."},
        {"name": "Per-frame odd parity", "purpose": "Detects bus bit errors; a "
         "parity mismatch is observable as an ignored frame."},
        {"name": "SPMI arbitration / Request", "purpose": "Observe which "
         "master wins and which slave requested service."},
        {"name": "Register read-back", "purpose": "Register Read / Extended "
         "Register Read give live device state for monitoring/debug."},
    ]
    d["error_detection_mechanisms"] = [
        "Odd parity per command/address/data frame detects bit errors.",
        "SPMI arbitration resolves multi-master contention deterministically.",
        "Missing/invalid SSC or Bus Park leaves the bus idle (no spurious "
        "transaction).",
        "RFFE interrupt mechanism surfaces slave-side events.",
        "SPMI Authenticated commands gate protected-register access.",
    ]
    d["notes"] = (
        "SPMI/RFFE observability is in-band over the two wires: DDB / ID "
        "registers for discovery, register read-back for state, RFFE interrupt "
        "handling for events, and per-frame parity for integrity. There is no "
        "separate scan/JTAG layer in the protocol; chip-level DFT is the device "
        "implementer's concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — SPMI/RFFE widths and rates (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "MASTER_ID_BITS": 4,
        "SLAVE_ID_BITS": 4,
        "USID_BITS": 4,
        "GSID_BITS": 4,
        "DATA_BYTE_BITS": 8,
        "REGISTER_ADDR_BITS_STANDARD": 8,
        "REGISTER_ADDR_BITS_EXTENDED_LONG": 16,
        "REGISTER_0_WRITE_DATA_BITS": 7,
        "PARITY_BITS_PER_FRAME": 1,
        "PARITY_TYPE": "odd",
        "SPMI_MAX_MASTERS": 4,
        "SPMI_MAX_SLAVES": 16,
        "RFFE_MAX_MASTERS": 1,
        "RFFE_MAX_SLAVES": 15,
        "SPMI_MAX_CLOCK_MHZ": 26,
        "RFFE_V1_V2_MAX_CLOCK_MHZ": 26,
        "RFFE_V3_MAX_CLOCK_MHZ": 52,
        "EXTENDED_REGISTER_MAX_BYTES": 16,
    })
    d["key_constants_for_RTL_authoring"] = {
        "is_two_wire": True,
        "is_open_drain": False,
        "is_cmos_push_pull": True,
        "derived_from_i2c": False,
        "is_spi": False,
        "wires": ["SCLK", "SDATA"],
        "msb_first": True,
        "per_frame_odd_parity": True,
        "framed_by_ssc": True,
        "bus_park_cycle": True,
        "identifier_bits": 4,
        "spmi_multi_master": True,
        "rffe_single_master": True,
        "register_0_write_data_bits": 7,
        "spmi_commands": list(_SPMI_COMMANDS),
        "rffe_commands": list(_RFFE_COMMANDS),
    }
    d["clock_rate_MHz"] = {"spmi_max": 26, "rffe_v1_v2_max": 26,
                           "rffe_v3_max": 52}
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — SPMI/RFFE transaction waveform (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove I2C-sibling waveform keys that do not apply (no SDA/SCL
    # START/STOP, no I2C speed-mode timing tables).
    for stale in ("start_stop_waveform", "clock_stretching_waveform",
                  "timing_parameters_standard_mode",
                  "timing_parameters_fast_mode",
                  "timing_parameters_fast_mode_plus",
                  "timing_parameters_high_speed_mode",
                  "synchronization_waveform"):
        d.pop(stale, None)
    d["bus_waveform"] = {
        "idle": "SCLK low, SDATA low.",
        "ssc": "Sequence Start Condition — SDATA pulse while SCLK is low — "
               "starts a transaction.",
        "bit_sampling": "MSB-first; SDATA sampled on the defined SCLK edge.",
        "parity": "one odd parity bit follows each command/address/data frame.",
        "bus_park": "Bus Park Cycle (SCLK toggling, SDATA released) ends the "
                    "transaction.",
        "no_i2c_start_stop": True,
    }
    d["transaction_waveform"] = {
        "generic": "SSC | Command Frame + parity | [Address Frame + parity] | "
                   "[Data Frame + parity ...] | Bus Park Cycle",
        "register_0_write": "SSC | Command Frame (incl. 7 data bits) + parity | "
                            "Bus Park Cycle",
        "extended": "...Command | Address | byte count | Data1..DataN + parity "
                    "each | Bus Park",
    }
    d["arbitration_waveform"] = {
        "spmi": "Masters contend on SDATA during the arbitration window before "
                "the SSC; higher priority / lower MASTER_ID wins; a slave "
                "Request is asserted in the same window.",
        "rffe": "single master — no arbitration window.",
    }
    d["trigger_waveform"] = {
        "rffe": "Trigger-register values are pre-loaded; a Trigger event "
                "applies them to several slaves simultaneously.",
    }
    d["clock_waveform"] = {
        "spmi_max_MHz": 26, "rffe_v1_v2_max_MHz": 26, "rffe_v3_max_MHz": 52,
        "source": "master-supplied SCLK; no clock recovery; no forwarded-clock "
                  "lane.",
    }
    d["general_timing_rule"] = (
        "SPMI/RFFE are synchronous to the master-supplied SCLK. Each frame is "
        "MSB-first plus one odd parity bit. An SSC starts a transaction and a "
        "Bus Park Cycle ends it. SPMI resolves multi-master arbitration before "
        "the SSC; RFFE has a single master. RFFE triggers apply pre-loaded "
        "values simultaneously across slaves.")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec (FORCE-OVERWRITE I2C base).
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "MIPI two-wire control-bus interface: an SCLK/SDATA master and/or slave "
        "that frames transactions with a Sequence Start Condition (SSC) and Bus "
        "Park Cycle, protects every frame with odd parity, and uses 4-bit "
        "identifiers. As SPMI it is multi-master/multi-slave with arbitration, "
        "Request, DDB, and Reset/Sleep/Shutdown/Wakeup; as RFFE it is "
        "single-master controlling up to 15 RF front-end slaves with Masked "
        "Write, Timed/Triggered access, Mapped Register Write, and Interrupt "
        "handling.")
    d["topology_description"] = (
        "Multi-drop two-wire bus: devices share SCLK and SDATA. SPMI allows up "
        "to 4 masters and 16 slaves with arbitration and Transfer Bus "
        "Ownership; RFFE has a single master and up to 15 slaves (PA/LNA/"
        "switch/tuner/PMIC). Both coexist on a smartphone/modem platform.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "wires": ["SCLK", "SDATA"],
        "identifier_bits": 4,
        "framed_by": "Sequence Start Condition (SSC) + Bus Park Cycle",
        "per_frame_odd_parity": True,
        "spmi": {"role": "multi-master/multi-slave", "max_masters": 4,
                 "max_slaves": 16, "arbitration": True, "request": True,
                 "ddb": True,
                 "power_state_commands": ["Reset", "Sleep", "Shutdown",
                                          "Wakeup"]},
        "rffe": {"role": "single-master/multi-slave", "max_masters": 1,
                 "max_slaves": 15, "slave_types": list(_RFFE_SLAVE_TYPES),
                 "trigger": True, "masked_write": True,
                 "mapped_register_write": True, "interrupt": True},
        "clock_rate_MHz": {"spmi_max": 26, "rffe_v1_v2_max": 26,
                           "rffe_v3_max": 52},
        "host_side_register_spec": "Per-slave 8/16-bit register space; Register "
        "0 special; SPMI DDB and RFFE ID registers for discovery.",
    })
    d["interface_categories"] = [
        "MIPI two-wire transport — SCLK/SDATA, MSB-first, odd parity, SSC + Bus "
        "Park framing.",
        "SPMI — multi-master arbitration, slave Request, DDB, power-state "
        "commands.",
        "RFFE — single-master control, USID/GSID, triggers, Masked/Mapped "
        "writes, interrupts.",
        "Register model — 8/16-bit register address, Register 0 short write.",
    ]
    d["interconnect_topologies_supported"] = [
        "SPMI multi-master / multi-slave (<=4 masters, <=16 slaves).",
        "RFFE single-master / multi-slave (<=15 slaves).",
        "Group addressing: SPMI Group Sub-ID; RFFE GSID.",
        "Coexisting SPMI (system power) + RFFE (RF front-end) buses on one "
        "platform.",
    ]
    d["default_signal_values_when_idle"] = (
        "SCLK low, SDATA low (bus idle); devices listen for the next Sequence "
        "Start Condition.")
    d["soc_dependent_items"] = [
        "Number of masters/slaves and their MASTER_ID/SLAVE_ID (SPMI) or "
        "USID/GSID (RFFE) assignment.",
        "Target clock rate (<=26 MHz SPMI / RFFE v1-v2; <=52 MHz RFFE v3.0).",
        "Which commands are implemented (e.g. Authenticated, Masked Write, "
        "Mapped Register Write, triggers).",
        "RFFE trigger mapping and PM-trigger coordination with the modem "
        "timeline.",
        "SPMI arbitration priority assignment and bus-ownership policy.",
        "Register-space layout and Register 0 usage.",
    ]
    d["low_power_modes"] = {
        "spmi": "Reset / Sleep / Shutdown / Wakeup commands place slaves (or "
                "groups) into defined power states.",
        "bus": "Two-wire CMOS bus idles low; low static power.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — derived compliance/test categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines protocol behaviors and compliance "
        "points (two-wire framing, SSC, parity, 4-bit IDs, the SPMI and RFFE "
        "command sets, arbitration, triggers) but is not itself a testbench.")
    d["derived_compliance_test_categories"] = [
        "Two-wire framing: SSC starts a transaction; Bus Park Cycle ends it; "
        "MSB-first.",
        "Per-frame odd parity: correct generation and parity-error handling.",
        "4-bit IDs: SPMI MASTER_ID/SLAVE_ID; RFFE USID/GSID; broadcast/group.",
        "SPMI commands: Register Read/Write, Extended/Long Register Read/Write, "
        "Register 0 Write, Authenticated, Master Read/Write, DDB Read, Transfer "
        "Bus Ownership.",
        "SPMI power state: Reset, Sleep, Shutdown, Wakeup to slave and group.",
        "SPMI arbitration: priority/MASTER_ID resolution; slave Request; "
        "ownership transfer.",
        "RFFE commands: Register Write/Read, Extended Register Write/Read Long, "
        "Register 0 Write, Masked Write, Mapped Register Write.",
        "RFFE triggers: Timed/Triggered access; simultaneous multi-slave "
        "application; PM triggers.",
        "RFFE interrupts: Interrupt Read / Identification & Clearing.",
        "Register model: 8/16-bit address; Register 0 short write; "
        "Extended/Long byte-count handling.",
        "Clock range: up to 26 MHz (SPMI / RFFE v1-v2) and 52 MHz (RFFE v3.0).",
        "Distinction from I2C/SPI: no SDA/SCL START/STOP, no MOSI/MISO/SS.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — capability/identity fields (no OTP as a protocol concept).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "SPMI Device Descriptor Block (DDB)", "width_bits": "block",
         "location": "DDB-accessible registers",
         "note": "Manufacturer ID, product ID, revision, and function; read "
         "via DDB Master/Slave Read for discovery."},
        {"field": "SLAVE_ID / MASTER_ID (SPMI)", "width_bits": 4,
         "location": "assigned/strapped",
         "note": "4-bit identifiers for SPMI slaves and masters."},
        {"field": "USID (RFFE Unique Slave ID)", "width_bits": 4,
         "location": "assigned/strapped",
         "note": "4-bit unique slave identifier."},
        {"field": "GSID (RFFE Group Slave ID)", "width_bits": 4,
         "location": "assigned",
         "note": "4-bit group identifier for group writes."},
        {"field": "RFFE product/manufacturer ID", "width_bits": "register",
         "location": "ID registers",
         "note": "Identify the RFFE slave."},
    ]
    d["notes"] = (
        "SPMI/RFFE do not define OTP as a protocol concept. Identity and "
        "capability are exposed through the SPMI Device Descriptor Block and "
        "RFFE ID registers, and device identifiers (SLAVE_ID/MASTER_ID/USID/"
        "GSID) are assigned or strapped. An implementation may back these with "
        "fuses, but the spec only requires they be discoverable over the bus.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["spmi_register_write_sequence"] = [
        "1. (Multi-master) Masters arbitrate on command priority / MASTER_ID; "
        "the winner proceeds.",
        "2. Master drives the Sequence Start Condition (SSC).",
        "3. Command Frame: SLAVE_ID + Register Write opcode + odd parity.",
        "4. Address Frame: register address + odd parity.",
        "5. Data Frame: data byte + odd parity.",
        "6. Bus Park Cycle ends the transaction; the addressed slave commits "
        "the write if parity checks pass.",
    ]
    d["spmi_register_read_sequence"] = [
        "1. SSC, then Command Frame: SLAVE_ID + Register Read opcode + parity.",
        "2. Address Frame: register address + parity.",
        "3. Bus turnaround; the slave drives the Data Frame: data byte + "
        "parity.",
        "4. Bus Park Cycle ends the transaction.",
    ]
    d["spmi_power_state_sequence"] = [
        "1. SSC, then Command Frame: SLAVE_ID (or Group Sub-ID) + "
        "Sleep/Shutdown/Wakeup/Reset opcode + parity.",
        "2. Bus Park Cycle; the targeted slave(s) enter the commanded power "
        "state.",
    ]
    d["spmi_arbitration_sequence"] = [
        "1. Multiple masters want the bus; each asserts its priority/MASTER_ID "
        "during the arbitration window.",
        "2. A slave needing service raises a Request in the same window.",
        "3. Highest priority / lowest MASTER_ID wins; others back off.",
        "4. The winner drives the SSC and runs its transaction; ownership can "
        "later be handed over via Transfer Bus Ownership.",
    ]
    d["rffe_register_write_sequence"] = [
        "1. The (single) master drives the SSC.",
        "2. Command Frame: USID + Register Write opcode + parity.",
        "3. Address Frame: 8-bit register address + parity.",
        "4. Data Frame: data byte + parity.",
        "5. Bus Park Cycle ends the transaction.",
    ]
    d["rffe_masked_write_sequence"] = [
        "1. SSC, then Command Frame: USID + Masked Write opcode + parity.",
        "2. Address + mask + data frames (only mask-selected bits change).",
        "3. Bus Park Cycle ends the transaction.",
    ]
    d["rffe_triggered_sequence"] = [
        "1. The master writes new values into the trigger registers of one or "
        "more slaves (each with its own SSC...Bus Park transaction).",
        "2. The master issues a Trigger event.",
        "3. All pre-loaded slaves apply their new values simultaneously "
        "(glitch-free RF re-configuration / PM trigger).",
    ]
    d["rffe_interrupt_sequence"] = [
        "1. A slave raises an interrupt.",
        "2. The master issues Interrupt Read / Interrupt Identification and "
        "Clearing to discover which slave(s) interrupted.",
        "3. The master services and clears the interrupt.",
    ]
    d["register_0_write_sequence"] = [
        "1. SSC, then a single Command Frame that encodes the Register 0 Write "
        "opcode plus 7 data bits + parity.",
        "2. Bus Park Cycle — the lowest-overhead single-frame write.",
    ]
    d["reset_sequence"] = [
        "1. Power-on/reset -> bus IDLE (SCLK low, SDATA low).",
        "2. Devices adopt their identifiers (SLAVE_ID/MASTER_ID/USID/GSID).",
        "3. Controller may issue Reset/Wakeup (SPMI) or initialize registers "
        "(RFFE) before normal operation.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab/characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Bus timing", "purpose": "Verify SCLK frequency range "
         "(<=26 MHz SPMI / RFFE v1-v2; <=52 MHz RFFE v3.0), setup/hold, and "
         "SSC / Bus Park timing."},
        {"name": "Signal levels", "purpose": "Confirm CMOS push-pull SCLK/SDATA "
         "levels and idle-low state."},
        {"name": "Parity integrity", "purpose": "Inject bit errors and confirm "
         "the odd-parity check ignores the faulty frame."},
        {"name": "SPMI arbitration", "purpose": "Verify priority/MASTER_ID "
         "resolution, slave Request, and Transfer Bus Ownership."},
        {"name": "RFFE triggers", "purpose": "Verify simultaneous multi-slave "
         "application on a Trigger event and PM-trigger timing."},
        {"name": "Command coverage", "purpose": "Exercise the SPMI and RFFE "
         "command sets including Register 0 Write, Extended/Long, Masked/Mapped "
         "writes, and DDB/ID reads."},
    ]
    d["notes"] = (
        "Characterization centers on the two-wire CMOS bus (timing, levels), "
        "the MIPI framing (SSC, Bus Park, per-frame parity), SPMI arbitration "
        "and power-state behavior, and RFFE trigger timing and command "
        "coverage.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — versioning + backward-compat traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "MIPI System Power Management Interface (SPMI) v2.0 + RF Front-End "
        "Control Interface (RFFE) v3.0 (MIPI Alliance)")
    f["previous_versions"] = [
        "SPMI v1.0 — initial multi-master two-wire system-power-management bus; "
        "Register Read/Write, Extended Register, Register 0 Write.",
        "RFFE v1.0 / v2.0 — single-master RF-front-end control bus; Register "
        "Write/Read, Extended Register, Register 0 Write; up to 26 MHz.",
    ]
    f["key_changes"] = [
        {"version": "SPMI v2.0", "summary": "Extended multi-master "
         "arbitration, the Device Descriptor Block, Authenticated commands, "
         "Master Read/Write, and the Reset/Sleep/Shutdown/Wakeup power-state "
         "command set; the two-wire SCLK/SDATA + SSC + parity + 4-bit-ID model "
         "is carried forward."},
        {"version": "RFFE v3.0", "summary": "Added Extended Register Long, "
         "Masked Write, Mapped Register Write, the Trigger/Timed mechanism, "
         "Group (GSID) commands, and raised the maximum clock to 52 MHz; the "
         "two-wire framing model is unchanged."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Not_I2C",
         "rule": "SPMI/RFFE use SCLK/SDATA + SSC + Bus Park, not SDA/SCL + "
                 "START/STOP.",
         "trap": "Treating the bus as I2C (open-drain, 7-bit address, "
                 "START/STOP) breaks framing and addressing."},
        {"trap_name": "Not_SPI",
         "rule": "Two-wire (SCLK + bidirectional SDATA), not 4-wire "
                 "MOSI/MISO/SS.",
         "trap": "Expecting separate MOSI/MISO or a chip-select pin fails — "
                 "slaves are selected by 4-bit ID in the command frame."},
        {"trap_name": "Parity_is_mandatory",
         "rule": "Every frame carries an odd parity bit.",
         "trap": "Omitting or mis-computing parity makes the receiver ignore "
                 "the frame."},
        {"trap_name": "Register_0_is_special",
         "rule": "Register 0 Write carries 7 data bits in the command frame "
                 "(single-frame).",
         "trap": "Treating Register 0 Write like a normal Register Write adds "
                 "spurious frames."},
        {"trap_name": "RFFE_single_master",
         "rule": "RFFE has one master; SPMI is multi-master with arbitration.",
         "trap": "Implementing RFFE arbitration (or omitting SPMI arbitration) "
                 "is wrong for the respective bus."},
    ]
    f["version_naming_history_note"] = (
        "SPMI and RFFE are maintained by the MIPI Alliance. They share a "
        "two-wire SCLK/SDATA control-bus model (SSC framing, per-frame parity, "
        "4-bit IDs) and are specified here as one combined control-bus class. "
        "Facts here are grounded in the public MIPI SPMI and RFFE "
        "specifications.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding/command tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["frame_structure_table"] = {
        "header_columns": ["Frame", "Contents", "Parity"],
        "rows": [
            ["Sequence Start Condition (SSC)", "start-of-transaction pulse",
             "n/a"],
            ["Command Frame", "slave ID + opcode (or Reg0 7 data bits)", "odd"],
            ["Address Frame", "8-bit or 16-bit register address", "odd"],
            ["Data Frame", "8 data bits", "odd"],
            ["Bus Park Cycle", "end-of-transaction idle", "n/a"],
        ],
    }
    f["spmi_command_table"] = {
        "header_columns": ["Command", "Purpose"],
        "rows": [
            ["Register Write", "write 1 byte to a register"],
            ["Register Read", "read 1 byte from a register"],
            ["Extended Register Write", "Long write (up to 16 bytes)"],
            ["Extended Register Read", "Long read (up to 16 bytes)"],
            ["Extended Register Write Long", "16-bit address write"],
            ["Extended Register Read Long", "16-bit address read"],
            ["Register 0 Write", "short 7-bit write to register 0"],
            ["Authenticated", "protected register access"],
            ["Master Write", "write to another master"],
            ["Master Read", "read from another master"],
            ["Device Descriptor Block Master Read", "read a master's DDB"],
            ["Device Descriptor Block Slave Read", "read a slave's DDB"],
            ["Transfer Bus Ownership", "hand bus to another master"],
            ["Reset", "reset slave/group"],
            ["Sleep", "low-power sleep"],
            ["Shutdown", "shut down output"],
            ["Wakeup", "wake from sleep/shutdown"],
        ],
    }
    f["rffe_command_table"] = {
        "header_columns": ["Command", "Purpose"],
        "rows": [
            ["Register Write", "write 1 byte (8-bit address)"],
            ["Register Read", "read 1 byte (8-bit address)"],
            ["Extended Register Write", "Long write, byte count"],
            ["Extended Register Read", "Long read, byte count"],
            ["Extended Register Write Long", "16-bit address write"],
            ["Extended Register Read Long", "16-bit address read"],
            ["Register 0 Write", "short 7-bit write to register 0"],
            ["Masked Write", "write only mask-selected bits"],
            ["Interrupt Read / Identification and Clearing",
             "discover/clear interrupts"],
            ["Timed / Triggered access", "apply on a Trigger event"],
            ["Mapped Register Write", "write via logical->physical mapping"],
        ],
    }
    f["identifier_table"] = {
        "header_columns": ["Bus", "Identifier", "Bits"],
        "rows": [
            ["SPMI", "MASTER_ID", "4"],
            ["SPMI", "SLAVE_ID", "4"],
            ["RFFE", "USID (Unique Slave ID)", "4"],
            ["RFFE", "GSID (Group Slave ID)", "4"],
        ],
    }
    f["tables"] = [
        "Frame-structure table (SSC / Command / Address / Data / Bus Park)",
        "SPMI command table",
        "RFFE command table",
        "Identifier table (MASTER_ID / SLAVE_ID / USID / GSID)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties / distinguishers.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Two-wire SCLK/SDATA CMOS bus, MSB-first.",
        "Sequence Start Condition (SSC) starting and Bus Park Cycle ending each "
        "transaction.",
        "Per-frame odd parity on command/address/data frames.",
        "4-bit device identifiers (SPMI MASTER_ID/SLAVE_ID; RFFE USID/GSID).",
        "SPMI: multi-master arbitration, slave Request, DDB, and the "
        "Reset/Sleep/Shutdown/Wakeup power-state commands.",
        "RFFE: single-master, up to 15 slaves, Masked Write, Timed/Triggered "
        "access, Mapped Register Write, and Interrupt handling.",
        "Register 0 Write as the low-overhead single-frame write.",
        "Clock within spec (<=26 MHz SPMI / RFFE v1-v2; <=52 MHz RFFE v3.0).",
    ]
    f["must_not_have_properties"] = [
        "I2C SDA/SCL open-drain wiring with START/STOP and a 7-bit address.",
        "SPI 4-wire MOSI/MISO/SCLK/SS with a chip-select.",
        "Frames without parity.",
        "Multi-master arbitration on RFFE (RFFE is single-master).",
        "An embedded/recovered clock (the master supplies SCLK).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Parity error", "trigger": "Frame parity does not match; the "
         "receiver ignores the frame."},
        {"mode": "Arbitration violation (SPMI)", "trigger": "Two masters drive "
         "conflicting frames without resolving on priority/MASTER_ID."},
        {"mode": "Missing SSC / Bus Park", "trigger": "A transaction without a "
         "valid SSC or terminating Bus Park."},
        {"mode": "Wrong identifier width", "trigger": "Using a 7-bit address "
         "instead of a 4-bit ID."},
        {"mode": "Trigger desync (RFFE)", "trigger": "Slaves fail to apply "
         "trigger-register values simultaneously on the Trigger event."},
    ]
    f["mipi_spmi_rffe_distinguishers"] = (
        "MIPI SPMI/RFFE is identified by ALL of: a two-wire SCLK/SDATA CMOS "
        "control bus; transactions framed by a Sequence Start Condition (SSC) "
        "and a Bus Park Cycle (NOT I2C START/STOP); per-frame odd parity; and "
        "4-bit device identifiers. SPMI adds multi-master arbitration, slave "
        "Request, the Device Descriptor Block, and Reset/Sleep/Shutdown/Wakeup; "
        "RFFE adds single-master operation, USID/GSID, Masked Write, "
        "Timed/Triggered access, Mapped Register Write, and Interrupt handling. "
        "This is DISTINCT from I2C (SDA/SCL open-drain, 7-bit address, "
        "START/STOP) and from SPI (4-wire MOSI/MISO/SCLK/SS).")
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
        {"name": "SCLK", "direction": "master -> bus (CMOS push-pull)",
         "purpose": "Serial clock supplied by the active master.",
         "active_levels": "toggled by master; idles low",
         "idle_level": "low"},
        {"name": "SDATA", "direction": "bidirectional (CMOS push-pull)",
         "purpose": "Serial data (command/address/data frames, MSB-first, odd "
         "parity).", "active_levels": "driven by master or slave per phase",
         "idle_level": "low"},
    ]
    f["global_signals"] = [
        {"name": "SCLK", "purpose": "Shared bus clock."},
        {"name": "SDATA", "purpose": "Shared bidirectional bus data."},
    ]
    f["packet_types_summary"] = [
        {"class": "SPMI command", "members": list(_SPMI_COMMANDS),
         "count": len(_SPMI_COMMANDS)},
        {"class": "RFFE command", "members": list(_RFFE_COMMANDS),
         "count": len(_RFFE_COMMANDS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "bus_wires": 2,
        "identifier_bits": 4,
        "data_byte_bits": 8,
        "register_addr_bits_standard": 8,
        "register_addr_bits_extended_long": 16,
        "parity_bits_per_frame": 1,
        "spmi_max_masters": 4,
        "spmi_max_slaves": 16,
        "rffe_max_slaves": 15,
        "spmi_command_count": len(_SPMI_COMMANDS),
        "rffe_command_count": len(_RFFE_COMMANDS),
    })
    f["handshake_pairs"] = [
        {"name": "SSC / sequence detect", "from": "master", "to": "all devices",
         "rule": "All devices detect the Sequence Start Condition to "
         "synchronize on a new transaction."},
        {"name": "Frame / parity", "from": "transmitter", "to": "receiver",
         "rule": "Each frame is MSB-first with an odd parity bit; a mismatch "
         "makes the receiver ignore the frame."},
        {"name": "Arbitration / Request", "from": "masters/slaves",
         "to": "bus", "rule": "(SPMI) higher priority / lower MASTER_ID wins; "
         "a slave Request flags need for service."},
        {"name": "Trigger / apply", "from": "RFFE master", "to": "slaves",
         "rule": "A Trigger event applies pre-loaded trigger-register values "
         "simultaneously."},
        {"name": "Interrupt / clear", "from": "RFFE slave", "to": "master",
         "rule": "Slave raises an interrupt; master Interrupt-Reads and "
         "clears."},
    ]
    f["dependency_graph"] = {
        "common_rule": "All devices share SCLK/SDATA; a transaction is framed "
        "by an SSC and a Bus Park Cycle; frames are MSB-first with odd parity. "
        "Slave selection is by 4-bit ID inside the Command Frame.",
        "data_dependency": "A valid transaction requires: (1) bus idle / "
        "arbitration won (SPMI), (2) a valid SSC, (3) correct parity on every "
        "frame. RFFE triggered writes depend on a subsequent Trigger event; "
        "SPMI power-state changes depend on the targeted SLAVE_ID/Group "
        "Sub-ID.",
    }
    f["ordering_rules"] = {
        "bit_order_on_wire": "MSB-first per frame.",
        "transaction_atomicity": "One transaction at a time on the shared bus; "
        "SPMI arbitration serializes masters; RFFE triggers defer application "
        "to a common Trigger event.",
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
        "Multi-drop two-wire MIPI control bus: devices share SCLK and SDATA. "
        "SPMI is multi-master (<=4 masters) / multi-slave (<=16 slaves) with "
        "arbitration and Transfer Bus Ownership; RFFE is single-master / "
        "multi-slave (<=15 slaves).")
    f["supported_topologies"] = [
        {"name": "SPMI multi-master", "description": "Up to 4 masters arbitrate "
         "for up to 16 slaves; slaves may raise a Request."},
        {"name": "RFFE single-master", "description": "One master controls up "
         "to 15 RF front-end slaves (PA/LNA/switch/tuner/PMIC); no "
         "arbitration."},
        {"name": "Group addressing", "description": "SPMI Group Sub-ID and RFFE "
         "GSID coordinate multiple slaves with one transaction."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "SPMI Master", "description": "Initiates transactions after "
         "winning arbitration; one of up to 4 masters; can Transfer Bus "
         "Ownership."},
        {"role": "SPMI Slave", "description": "Responds to its 4-bit SLAVE_ID; "
         "may raise a Request; one of up to 16 slaves."},
        {"role": "RFFE Master", "description": "The single bus master; fully "
         "controls SCLK and timing."},
        {"role": "RFFE Slave", "description": "RF front-end device addressed by "
         "4-bit USID (and GSID); PA/LNA/switch/tuner/PMIC."},
    ]
    f["interconnect_role"] = (
        "SPMI is a shared system-power-management control bus; RFFE is the RF "
        "front-end control bus. Slaves are addressed by 4-bit ID; the master(s) "
        "configure, control, and monitor them, with SPMI power-state commands "
        "and RFFE triggers/interrupts.")
    f["ordering_guarantees"] = {
        "single_transaction": "One transaction at a time on the shared bus.",
        "spmi_arbitration": "Higher priority / lower MASTER_ID wins each "
        "round.",
        "rffe_trigger": "Trigger-register values apply simultaneously on the "
        "Trigger event.",
    }
    f["memory_vs_peripheral_regions"] = (
        "SPMI/RFFE are command/register-oriented, not memory-mapped. Each slave "
        "exposes an 8-bit (or 16-bit Extended Long) register space addressed "
        "per command; there is no linear memory address space on the bus.")
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — channel/electrical constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "two-wire CMOS push-pull (SCLK + bidirectional SDATA); "
                     "idles low",
        "identifier_bits": 4,
        "clock_rate_MHz": {"spmi_max": 26, "rffe_v1_v2_max": 26,
                           "rffe_v3_max": 52},
        "framing": "Sequence Start Condition (SSC) + Bus Park Cycle",
        "parity": "odd parity per frame",
        "register_addr_bits": {"standard": 8, "extended_long": 16},
        "not_open_drain": True,
        "not_spi_4wire": True,
    }
    f["notes"] = (
        "SPMI/RFFE define a low-power two-wire CMOS control bus framed by an "
        "SSC, with per-frame odd parity and 4-bit IDs. Pull/termination and AFE "
        "characterization are board/implementer concerns; the "
        "interoperability-critical constraints are the framing (SSC/Bus Park), "
        "parity, identifier widths, command sets, and clock rate.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / in-band test facilities.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "SPMI Device Descriptor Block", "purpose": "Discovery / "
         "enumeration and identity read-back."},
        {"name": "RFFE ID registers", "purpose": "Identify slaves and "
         "USID/GSID."},
        {"name": "Register read-back", "purpose": "Register Read / Extended "
         "Register Read for live state."},
        {"name": "RFFE Interrupt Read / Identification & Clearing",
         "purpose": "Surface and clear slave events."},
        {"name": "Per-frame parity", "purpose": "Detect bus bit errors "
         "in-band."},
    ]
    f["internal_diagnostics_observability"] = [
        "DDB / ID register contents.",
        "Register state read-back.",
        "Interrupt status (RFFE).",
        "Parity-error events.",
        "SPMI arbitration outcome / Request status.",
    ]
    f["notes"] = (
        "SPMI/RFFE DFT is entirely in-band over the two wires (DDB/ID "
        "registers, register read-back, RFFE interrupts, per-frame parity). "
        "There is no protocol-defined scan/JTAG layer; chip-level scan/BIST is "
        "the device implementer's concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (SPMI power-state control + bus power).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["managed_power_states"] = [
        {"state": "ACTIVE", "description": "Slave powered and operating "
         "normally."},
        {"state": "SLEEP", "description": "(SPMI Sleep) low-power state entered "
         "by command."},
        {"state": "SHUTDOWN", "description": "(SPMI Shutdown) output shut down "
         "by command."},
        {"state": "WAKEUP", "description": "(SPMI Wakeup) returns a slave from "
         "Sleep/Shutdown."},
        {"state": "RESET", "description": "(SPMI Reset) slave reset by "
         "command."},
    ]
    f["output_enable_logic"] = (
        "SPMI power-state commands (Reset/Sleep/Shutdown/Wakeup) place a slave "
        "or a group (Group Sub-ID) into a defined power state — the core "
        "system-power-management purpose of SPMI. RFFE controls RF front-end "
        "device enable/bias through register writes and triggers; RFFE PM "
        "triggers coordinate front-end power state with the modem.")
    f["bus_power"] = (
        "SCLK/SDATA are low-power CMOS lines idling low; the two-wire bus "
        "itself consumes little static power.")
    f["notes"] = (
        "SPMI is fundamentally a system-power-management bus: it commands "
        "device power states directly (Reset/Sleep/Shutdown/Wakeup) per slave "
        "or group. RFFE manages RF front-end device power/bias via register and "
        "triggered writes (PM triggers). The bus electrical layer is itself "
        "low-power.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan categories.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Two-wire framing — SSC start, Bus Park end, MSB-first.",
        "Per-frame odd parity — generation and error handling.",
        "4-bit identifiers — SPMI MASTER_ID/SLAVE_ID; RFFE USID/GSID; "
        "broadcast/group.",
        "SPMI command coverage — Register/Extended/Long/Reg0/Authenticated/"
        "Master/DDB/Transfer Bus Ownership.",
        "SPMI power state — Reset/Sleep/Shutdown/Wakeup to slave and group.",
        "SPMI arbitration — priority/MASTER_ID; slave Request; ownership "
        "transfer.",
        "RFFE command coverage — Register/Extended/Long/Reg0/Masked/Mapped.",
        "RFFE triggers — Timed/Triggered access; simultaneous application; PM "
        "triggers.",
        "RFFE interrupts — Interrupt Read / Identification & Clearing.",
        "Register model — 8/16-bit address; Register 0 short write; byte-count "
        "handling.",
        "Clock range — <=26 MHz (SPMI / RFFE v1-v2); <=52 MHz (RFFE v3.0).",
        "Negative — reject I2C/SPI framing assumptions.",
    ]
    f["notes"] = (
        "SPMI/RFFE ship no formal testbench, but the specifications imply a "
        "verification plan spanning the two-wire transport (SSC/Bus Park/"
        "parity/IDs), the SPMI command and arbitration/power-state behavior, "
        "and the RFFE command, trigger, and interrupt behavior.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security / robustness.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = True
    f["anti_corruption_features"] = [
        "Per-frame odd parity detects bus bit errors.",
        "SPMI arbitration resolves multi-master contention deterministically.",
        "SSC + Bus Park framing prevents spurious partial transactions.",
        "RFFE interrupt handling surfaces slave events promptly.",
    ]
    f["anti_tampering_features"] = [
        "SPMI Authenticated commands gate access to protected registers "
        "(an in-protocol authentication payload).",
    ]
    f["confidentiality_features"] = []
    f["authentication_features"] = [
        "SPMI Authenticated commands carry an authentication payload for "
        "protected register access.",
    ]
    f["future_security_pointers"] = [
        "SPMI/RFFE traffic is plaintext on a board-local bus; physical access "
        "is the trust boundary.",
        "SPMI Authenticated commands are the main in-protocol access guard; "
        "RFFE relies on host-side policy. There is no bus-wide encryption.",
    ]
    f["notes"] = (
        "SPMI offers an in-protocol Authenticated-command mechanism to protect "
        "selected registers; otherwise SPMI/RFFE built-in protections are "
        "anti-corruption (per-frame parity, deterministic arbitration, SSC/Bus "
        "Park framing). There is no bus-wide cryptographic confidentiality; the "
        "bus is trusted at the board level.")
    _write(p, d)
