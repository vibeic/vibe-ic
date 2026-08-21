"""System Management Bus (SMBus 3.x) + Power Management Bus (PMBus 1.3)
protocol synth helper.

v0.1.91 — protocol #52 of the Phase-1 doc-extraction sweep. ic_class-gated
overlay for a doc that exhibits the SMBus/PMBus structural signature: a
two-wire system-management bus DERIVED FROM I2C (SMBCLK/SMBDAT, 7-bit
addressing) that adds the SMBus-specific structure — the fixed protocol set
(Quick Command / Send-Receive Byte / Write-Read Byte-Word / Process Call /
Block Write-Read / Host Notify), the Packet Error Code (PEC, a CRC-8 over the
whole transaction), the SMBALERT# interrupt line + Alert Response Address
(ARA), the Address Resolution Protocol (ARP) with a 128-bit UDID, and SMBus
timeouts — together with the PMBus application layer on top: the standard
COMMAND CODE set (OPERATION/VOUT_COMMAND/PAGE/STATUS_WORD/READ_VOUT/IOUT/
TEMPERATURE...), the LINEAR11 / LINEAR16(ULINEAR16) / DIRECT / VID numeric
data formats, the CONTROL pin, WRITE_PROTECT, and the group/zone command
protocols. Applies SMBus 3.1 (2018) + PMBus 1.3.1 (2015) spec-canonical
content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
SMBus/PMBus signatures (PEC/CRC-8, SMBALERT#/ARA, ARP/UDID, the bus-protocol
element set, and the PMBus command-code/data-format vocabulary) read from the
L-doc CONTENT blob ONLY. It NEVER reads the input-document filename or the
benchmark folder name. (A code review flagged exactly a filename read as a
HIGH defect on the AHB+APB detector; this module does not repeat it.)

------------------------------------------------------------------------------
CHICKEN-AND-EGG MUTEX vs the I2C detector (the hard part — like I3C-extends-I2C)
------------------------------------------------------------------------------
SMBus/PMBus is DERIVED FROM I2C and shares the wired-AND open-drain two-wire
model and 7-bit addressing. The existing runner-side ``_is_i2c`` predicate
(v0.1.79, tightened in v0.1.84) requires BOTH a wire/condition signature
( (SDA AND SCL) OR (START condition AND STOP condition AND slave address) )
AND an explicit I2C-name token ("I2C" / "I²C" / "I2C-bus"). The I2C benchmark
spec (NXP UM10204) literally names SDA/SCL and "I2C-bus".

To avoid cross-firing in BOTH directions:

  (a) ``is_smbus_pmbus`` REQUIRES SMBus/PMBus-only vocabulary that a plain-I2C
      spec does NOT contain — at least one of {PEC / Packet Error Code,
      SMBALERT#, ARP / Address Resolution Protocol, Host Notify, Quick Command,
      Block Write/Read, the PMBus command set (OPERATION / VOUT_COMMAND / PAGE
      / STATUS_WORD / READ_VOUT...), the PMBus data formats (LINEAR11 / DIRECT
      / VID / VOUT_MODE), the CONTROL pin, group/zone command} — and DEFERS
      when the doc is plain-I2C-primary (just SDA/SCL + 7-bit addressing +
      START/STOP with NONE of the SMBus/PMBus vocabulary). A NXP-UM10204 I2C
      doc has none of {PEC, SMBALERT, ARP, PMBus commands}, so the predicate
      stays False on it.

  (b) The SMBus/PMBus benchmark doc names its wires SMBCLK/SMBDAT (not
      SDA/SCL) and the generated L1+L2 blob does NOT contain "STOP condition",
      so the runner's ``_is_i2c`` (which keys on SDA+SCL OR
      START+STOP+slave-address) does NOT fire on the L1+L2 blob and the I2C
      synth never touches the base docs. (Empirically confirmed at build time
      — see the field-report.) Even if a future doc phrasing did trip
      ``_is_i2c``, this module is wired to run AFTER the I2C synth and
      FORCE-ASSIGNS (direct assignment, NOT setdefault) every L1/L2/L3/L4/...
      key the I2C synth would populate — the cross-protocol force-overwrite
      doctrine (NVMe-on-PCIe, I3C-extends-I2C). So I2C output, if present, is
      fully replaced by the SMBus/PMBus-canonical values and cannot leak
      through.

Public entry: ``apply_smbus_pmbus_synth(generated_docs_dir, is_smbus_pmbus,
smbus_pmbus_ic_name)``.
"""
from __future__ import annotations

import json
import re
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

# Canonical SMBus/PMBus structural facts (SMBus 3.1, 2018 / PMBus 1.3.1, 2015).
_SMBUS_PROTOCOLS = [
    "Quick Command", "Send Byte", "Receive Byte", "Write Byte", "Write Word",
    "Read Byte", "Read Word", "Process Call", "Block Write", "Block Read",
    "Block Write-Block Read Process Call", "Host Notify",
]
_PMBUS_DATA_FORMATS = ["LINEAR11", "LINEAR16/ULINEAR16", "DIRECT", "VID"]


# ----------------------------------------------------------------------
# Module-level CONTENT-ONLY detector (the runner wires this; evaluated on the
# input_doc-augmented L-doc blob, NEVER on a filename).
# ----------------------------------------------------------------------
def is_smbus_pmbus(blob: str) -> bool:
    """SMBus 3.x / PMBus 1.3 — a system-management/power-management bus
    DERIVED FROM I2C.

    MUTEX vs plain I2C: a plain-I2C spec (SDA/SCL + 7-bit addressing +
    START/STOP) carries NONE of the SMBus/PMBus-specific vocabulary below, so
    requiring at least one SMBus-only structural feature (PEC / SMBALERT# /
    ARP / Host Notify / Quick Command / Block Write-Read) OR a PMBus-only
    feature (the command-code set, the LINEAR/DIRECT/VID data formats, the
    CONTROL pin, group/zone commands) keeps the predicate False on a
    NXP-UM10204-style I2C document while firing on a genuine SMBus/PMBus doc.
    All checks read ``blob`` only — no filename / folder / benchmark-name read.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- SMBus-specific structural features (absent from a plain-I2C spec) ---
    # v0.2.13: "PEC" must be a WHOLE WORD. A bare substring match also hits
    # "ADI_SPEC" / "SPECIFICATION" / "EXPECTED", which — combined with any
    # CRC-8 mention — false-fired on the eSPI benchmark (eSPI has CRC-8 and
    # the token "ADI_SPEC" in L5). The SMBus Packet Error Code is always
    # written "PEC" as a standalone mnemonic, so a word boundary is exact.
    pec = (
        "Packet Error Code" in blob
        or (re.search(r"\bPEC\b", blob) and ("CRC-8" in blob or "CRC8" in blob))
    )
    smbalert = ("SMBALERT" in blob or "Alert Response Address" in blob
                or "Alert Response" in blob)
    arp = (
        "Address Resolution Protocol" in blob
        or ("ARP" in blob and "UDID" in blob)
        or "Unique Device Identifier" in blob
    )
    host_notify = "Host Notify" in blob
    quick_cmd = "Quick Command" in blob
    block_rw = ("Block Write" in blob and "Block Read" in blob)
    smbus_wires = ("SMBCLK" in blob and "SMBDAT" in blob)

    smbus_specific = (
        pec or smbalert or arp or host_notify or quick_cmd
        or (block_rw and smbus_wires)
    )

    # --- PMBus-specific application-layer features ---
    pmbus_named = ("PMBus" in blob or "Power Management Bus" in blob)
    pmbus_cmds = (
        ("OPERATION" in blob and "VOUT_COMMAND" in blob)
        or ("STATUS_WORD" in blob and "PAGE" in blob)
        or ("READ_VOUT" in blob and "VOUT_MODE" in blob)
    )
    pmbus_formats = (
        ("LINEAR11" in blob or "LINEAR16" in blob or "ULINEAR16" in blob)
        and ("DIRECT" in blob or "VID" in blob)
    )
    pmbus_ctrl = ("CONTROL pin" in blob or "WRITE_PROTECT" in blob
                  or "group command" in low or "zone command" in low
                  or "Zone Read" in blob or "Zone Write" in blob)
    pmbus_specific = pmbus_named and (pmbus_cmds or pmbus_formats or pmbus_ctrl)

    # --- DEFER if the doc is plain-I2C-primary (no SMBus/PMBus vocabulary) ---
    if not (smbus_specific or pmbus_specific):
        return False

    # Anchor: it must actually be the SMBus/PMBus family (a system-management
    # / power-management bus derived from the 2-wire I2C model), not some
    # unrelated doc that merely happens to contain one token.
    family = (
        "SMBus" in blob
        or "System Management Bus" in blob
        or pmbus_named
        or smbus_wires
    )
    return bool(family and (smbus_specific or pmbus_specific))


def apply_smbus_pmbus_synth(generated_docs_dir: Path, is_smbus_pmbus: bool,
                            smbus_pmbus_ic_name: Optional[str]) -> None:
    """Apply SMBus 3.1 / PMBus 1.3 synth when the signature matched.

    SMBus/PMBus DERIVES FROM I2C; if the I2C synth ran first this routine
    FORCE-OVERWRITES (direct assignment, NOT setdefault) every key the I2C
    synth would populate with the SMBus/PMBus-canonical value, so I2C output
    cannot leak through (cross-protocol force-overwrite doctrine).
    """
    if not is_smbus_pmbus:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if smbus_pmbus_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = smbus_pmbus_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = smbus_pmbus_ic_name
                d["ic_name"] = smbus_pmbus_ic_name
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
# L1 — SMBus/PMBus datasheet header (FORCE-OVERWRITE).
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "System Management Bus (SMBus) 3.1 + Power Management Bus (PMBus) 1.3 "
        "Specification")
    d["version"] = "SMBus 3.1 (2018) / PMBus 1.3.1 (2015)"
    d["revised_date"] = "2018 (SMBus 3.1) / 2015 (PMBus 1.3.1)"
    d["manufacturer"] = "System Management Interface Forum (SMIF)"
    d["copyright"] = "© System Management Interface Forum (SMIF)"
    d["abstract"] = (
        "SMBus is a two-wire system-management bus derived from I2C, using a "
        "serial clock (SMBCLK) and serial data (SMBDAT) line, that adds a "
        "fixed set of bus protocols (Quick Command, Send/Receive Byte, "
        "Write/Read Byte/Word, Process Call, Block Write/Read, Block "
        "Write-Block Read Process Call, Host Notify), an optional Packet Error "
        "Code (PEC, a CRC-8 over the whole transaction), an SMBALERT# "
        "interrupt line with an Alert Response Address (ARA), an Address "
        "Resolution Protocol (ARP) using a 128-bit UDID for dynamic "
        "addressing, and bus timeouts. PMBus is an open-standard "
        "power-management application layer ON TOP of SMBus: a standard "
        "command-code language (OPERATION, ON_OFF_CONFIG, VOUT_COMMAND, PAGE, "
        "STATUS_WORD, READ_VIN/VOUT/IOUT/TEMPERATURE...), numeric data formats "
        "(LINEAR11, LINEAR16/ULINEAR16, DIRECT, VID), a CONTROL pin, "
        "WRITE_PROTECT, multi-rail PAGE addressing, and group/zone command "
        "protocols for configuring, controlling, and monitoring power "
        "converters.")
    d["keywords"] = [
        "SMBus", "System Management Bus", "SMBCLK", "SMBDAT", "PEC",
        "Packet Error Code", "CRC-8", "SMBALERT#", "Alert Response Address",
        "ARA", "ARP", "Address Resolution Protocol", "UDID", "Host Notify",
        "Quick Command", "Block Read", "Block Write", "Process Call",
        "PMBus", "Power Management Bus", "OPERATION", "VOUT_COMMAND", "PAGE",
        "STATUS_WORD", "READ_VOUT", "LINEAR11", "DIRECT", "VID", "VOUT_MODE",
        "CONTROL pin", "WRITE_PROTECT", "group command", "zone command",
    ]
    d["external_pins"] = [
        "SMBCLK — serial clock line (open-drain, pulled up to VDD); driven by "
        "the master/host, may be clock-low-extended (stretched) within "
        "timeout limits",
        "SMBDAT — bidirectional serial data line (open-drain, pulled up to "
        "VDD); wired-AND",
        "SMBALERT# — optional active-low open-drain shared interrupt line "
        "(wired-OR) for the Alert Response (ARA) mechanism / PMBus fault "
        "signaling",
        "CONTROL — (PMBus) hardware enable input on a power device; combines "
        "with OPERATION + ON_OFF_CONFIG to turn the output on/off and select "
        "margining",
        "VDD / GND — supply and ground; pull-ups bias SMBCLK/SMBDAT/SMBALERT#",
    ]
    d["address_bits"] = 7
    d["supported_bus_speed_kHz"] = {
        "smbus_2_0_min": 10, "smbus_2_0_max": 100, "smbus_3_x_max": 1000,
        "pmbus_typical_max": 400, "pmbus_optional_max": 1000}
    d["smbus_protocols"] = list(_SMBUS_PROTOCOLS)
    d["pmbus_data_formats"] = list(_PMBUS_DATA_FORMATS)
    d["modes_of_operation"] = [
        {"name": "SMBus transport (Part I)",
         "description": "I2C-derived 2-wire SMBCLK/SMBDAT transactions with "
         "7-bit addressing, the fixed SMBus protocol set, optional PEC CRC-8, "
         "SMBALERT#/ARA, ARP, and timeouts."},
        {"name": "PMBus command language (Part II)",
         "description": "Power-management application layer: standard command "
         "codes, LINEAR/DIRECT/VID data formats, PAGE multi-rail addressing, "
         "CONTROL pin, WRITE_PROTECT, group/zone commands."},
        {"name": "High-speed mode (SMBus 3.x)",
         "description": "Up to 1 MHz clock (vs 100 kHz baseline) for higher "
         "throughput."},
    ]
    d["key_features"] = [
        "Two-wire system-management bus derived from I2C: SMBCLK + SMBDAT, "
        "open-drain wired-AND, 7-bit addressing.",
        "Bus speed 10-100 kHz (SMBus 2.0) up to 1 MHz (SMBus 3.x); PMBus "
        "typically up to 400 kHz.",
        "Fixed protocol set: Quick Command, Send/Receive Byte, Write/Read "
        "Byte/Word, Process Call, Block Write/Read, Block Write-Block Read "
        "Process Call, Host Notify.",
        "Optional Packet Error Code (PEC): a CRC-8 (poly x^8+x^2+x^1+1, 0x07) "
        "over the whole transaction for end-to-end integrity that base I2C "
        "lacks.",
        "SMBALERT# shared open-drain interrupt + Alert Response Address (ARA): "
        "alerting devices arbitrate, lowest address wins, host discovers who "
        "asserted.",
        "Address Resolution Protocol (ARP): dynamic plug-and-play address "
        "assignment using a 128-bit Unique Device Identifier (UDID) at the "
        "SMBus Device Default Address.",
        "Bus timeouts (Ttimeout 25-35 ms, Tlow:sext <= 25 ms, Tlow:mext "
        "<= 10 ms): detect and recover a hung device — absent in base I2C.",
        "PMBus application layer: standard command-code set (OPERATION 0x01, "
        "VOUT_COMMAND 0x21, PAGE 0x00, STATUS_WORD 0x79, READ_VOUT 0x8B, "
        "READ_IOUT 0x8C, READ_TEMPERATURE_1 0x8D...).",
        "PMBus numeric data formats: LINEAR11 (5-bit exp + 11-bit mantissa), "
        "LINEAR16/ULINEAR16 (VOUT with VOUT_MODE exponent), DIRECT (m/b/R "
        "coefficients), VID.",
        "PMBus CONTROL pin + ON_OFF_CONFIG for hardware/command enable; "
        "WRITE_PROTECT to guard configuration.",
        "PMBus PAGE for multi-rail devices, plus group command and Zone "
        "Read/Write (PMBus 1.3) for coordinating many devices.",
    ]
    d["topology_summary"] = (
        "Multi-drop 2-wire bus: all devices share SMBCLK and SMBDAT via "
        "open-drain wired-AND, with optional shared SMBALERT# (wired-OR). At "
        "most one host (a managing master); other devices are masters and/or "
        "slaves. PMBus power devices hang off the same bus and add a CONTROL "
        "pin.")
    d["use_cases"] = [
        "Battery / smart-battery management (the original SMBus use case)",
        "Power-supply and DC/DC converter / point-of-load monitoring and "
        "control via PMBus",
        "Thermal and voltage telemetry to a baseboard management controller "
        "(BMC)",
        "Plug-and-play module identification and dynamic addressing via ARP",
        "Fault interrupt aggregation over SMBALERT# / Alert Response",
        "Multi-rail and multi-device power sequencing via PAGE / group / zone "
        "commands",
    ]
    d["revision_history"] = [
        {"version": "SMBus 1.0/2.0", "date": "1995/2000",
         "description": "100 kHz; defined the protocol set, PEC, ARP, "
                        "SMBALERT#, Host Notify, and timeouts."},
        {"version": "SMBus 3.0/3.1", "date": "2014/2018",
         "description": "Added a 1 MHz high-speed mode, clarified larger block "
                        "transfers, and additional electrical options."},
        {"version": "PMBus 1.0-1.2", "date": "2005-2010",
         "description": "Established the command language, LINEAR/DIRECT/VID "
                        "formats, OPERATION/ON_OFF_CONFIG/CONTROL, STATUS "
                        "registers, and PAGE."},
        {"version": "PMBus 1.3 (1.3.1)", "date": "2015",
         "description": "Added Zone Read/Write, additional commands, and "
                        "AVSBus references."},
    ]
    d["overview"] = (
        "The System Management Bus (SMBus) is a two-wire control bus derived "
        "from I2C (SMBCLK + SMBDAT, open-drain wired-AND, 7-bit addressing) "
        "specialized for system and power management. SMBus adds, over base "
        "I2C, a fixed set of bus protocols (Quick Command, Send/Receive Byte, "
        "Write/Read Byte/Word, Process Call, Block Write/Read, Block "
        "Write-Block Read Process Call, Host Notify), an optional Packet Error "
        "Code (PEC, a CRC-8 over the entire transaction) for integrity, an "
        "SMBALERT# shared interrupt line with an Alert Response Address (ARA) "
        "so the host can discover which device needs service, an Address "
        "Resolution Protocol (ARP) that dynamically assigns 7-bit addresses "
        "using each device's 128-bit UDID, and bus timeouts that recover a "
        "hung bus. The Power Management Bus (PMBus) is an open standard layered "
        "on top of SMBus: it defines a standard command language (command "
        "codes such as OPERATION, VOUT_COMMAND, PAGE, STATUS_WORD, READ_VOUT/"
        "IOUT/TEMPERATURE) and numeric data formats (LINEAR11, LINEAR16/"
        "ULINEAR16, DIRECT, VID) so a host can configure, control, and monitor "
        "power converters interoperably, plus a CONTROL pin, WRITE_PROTECT, "
        "multi-rail PAGE addressing, and group/zone command protocols.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — SMBus/PMBus functional requirement set + protocol overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Two-wire system-management/power-management bus derived from I2C "
        "(SMBCLK/SMBDAT, open-drain wired-AND, 7-bit addressing). SMBus is the "
        "transport (fixed protocol set + PEC + SMBALERT#/ARA + ARP + "
        "timeouts); PMBus is the power-management application layer on top "
        "(command-code language + LINEAR/DIRECT/VID data formats + CONTROL "
        "pin + PAGE + group/zone).")
    po["duplex"] = (
        "half-duplex (single bidirectional SMBDAT line shared by all devices; "
        "one transaction at a time, arbitrated).")
    po["synchronous_serial"] = True
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["clock_line"] = "SMBCLK (driven by the master/host; open-drain)"
    po["data_line"] = "SMBDAT (bidirectional, open-drain, wired-AND)"
    po["derived_from"] = "I2C (Inter-Integrated Circuit) two-wire bus"
    po["address_bits"] = 7
    po["bus_speed_kHz"] = {"smbus_min": 10, "smbus_2_0_max": 100,
                           "smbus_3_x_max": 1000, "pmbus_typical_max": 400}
    po["smbus_protocols"] = list(_SMBUS_PROTOCOLS)
    po["pec"] = {
        "name": "Packet Error Code", "type": "CRC-8",
        "polynomial": "x^8 + x^2 + x^1 + 1 (0x07)", "initial_value": "0x00",
        "coverage": "the complete transaction (address byte(s) + command code "
                    "+ all data bytes)",
        "result": "one PEC byte appended before STOP; optional/negotiated",
    }
    po["smbalert"] = {
        "line": "SMBALERT# (active-low, open-drain, wired-OR, shared)",
        "alert_response_address": "ARA = 0b0001100 (0x0C)",
        "mechanism": "host issues Receive Byte to ARA; alerting devices "
                     "arbitrate on SMBDAT (lowest address wins); winner "
                     "returns its 7-bit address.",
    }
    po["arp"] = {
        "name": "Address Resolution Protocol",
        "udid_bits": 128,
        "default_address": "SMBus Device Default Address = 0b1100001",
        "commands": ["Prepare to ARP", "Reset Device", "Get UDID",
                     "Assign Address"],
        "purpose": "dynamic plug-and-play 7-bit address assignment.",
    }
    po["timeouts"] = {
        "Ttimeout_ms": "25 to 35", "Tlow_sext_ms": "<= 25",
        "Tlow_mext_ms": "<= 10",
        "note": "clock-low timeouts let SMBus detect/recover a hung device "
                "(absent in base I2C, which has no minimum clock).",
    }
    po["pmbus_layer"] = {
        "is_application_layer_on_smbus": True,
        "command_code_set": True,
        "data_formats": list(_PMBUS_DATA_FORMATS),
        "control_pin": True, "write_protect": True,
        "page_multi_rail": True, "group_command": True,
        "zone_read_write_pmbus_1_3": True,
    }
    d["protocol_overview"] = po
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "SMBus is a two-wire bus (SMBCLK + "
         "SMBDAT) derived from I2C: open-drain, wired-AND, pulled up to VDD, "
         "with 7-bit device addressing."},
        {"id": "FR-SPEED-02", "text": "Clock is 10 kHz (min) to 100 kHz "
         "(SMBus 2.0 max), extended to 1 MHz in SMBus 3.x; PMBus typically "
         "runs up to 400 kHz."},
        {"id": "FR-PROTO-03", "text": "The bus carries data using the fixed "
         "SMBus protocol set: Quick Command, Send Byte, Receive Byte, Write "
         "Byte/Word, Read Byte/Word, Process Call, Block Write, Block Read, "
         "Block Write-Block Read Process Call, and Host Notify."},
        {"id": "FR-PEC-04", "text": "An optional Packet Error Code (PEC) byte "
         "— a CRC-8 with polynomial x^8+x^2+x^1+1 (0x07) over the entire "
         "transaction — may be appended before STOP; a PEC mismatch causes the "
         "receiver to reject the transaction."},
        {"id": "FR-ALERT-05", "text": "SMBALERT# is an optional shared "
         "active-low open-drain interrupt; the host services it with a Receive "
         "Byte to the Alert Response Address (ARA), and alerting devices "
         "arbitrate (lowest address wins) to return their address."},
        {"id": "FR-ARP-06", "text": "The Address Resolution Protocol (ARP) "
         "dynamically assigns 7-bit addresses using each device's 128-bit "
         "UDID via Prepare-to-ARP / Get-UDID / Assign-Address at the SMBus "
         "Device Default Address."},
        {"id": "FR-TIMEOUT-07", "text": "SMBus defines bus timeouts "
         "(Ttimeout 25-35 ms, Tlow:sext <= 25 ms, Tlow:mext <= 10 ms) so a "
         "hung device cannot lock the bus; a master aborts and a slave "
         "releases the bus on timeout."},
        {"id": "FR-NOTIFY-08", "text": "Host Notify lets a device act as a "
         "master and write its address plus a 16-bit value to the reserved "
         "Host Notify address, asynchronously notifying the host."},
        {"id": "FR-PMBUS-09", "text": "PMBus is an application layer on SMBus: "
         "a standard command-code set (OPERATION, ON_OFF_CONFIG, VOUT_COMMAND, "
         "VOUT_MODE, PAGE, STATUS_BYTE/WORD, READ_VIN/VOUT/IOUT/TEMPERATURE) "
         "carried in SMBus Write/Read Byte/Word/Block transactions."},
        {"id": "FR-FORMAT-10", "text": "PMBus numeric values use defined data "
         "formats: LINEAR11 (5-bit signed exponent + 11-bit signed mantissa, "
         "X = Y*2^N), LINEAR16/ULINEAR16 (16-bit unsigned mantissa with a "
         "VOUT_MODE exponent), DIRECT (m/b/R coefficients), and VID."},
        {"id": "FR-CONTROL-11", "text": "A PMBus power device has a CONTROL "
         "pin whose interaction with OPERATION is set by ON_OFF_CONFIG; "
         "WRITE_PROTECT restricts which commands may be written."},
        {"id": "FR-PAGE-12", "text": "PAGE selects which output/rail of a "
         "multi-rail device subsequent commands apply to (0xFF = all pages); "
         "group commands and Zone Read/Write (PMBus 1.3) coordinate multiple "
         "devices."},
        {"id": "FR-FAULT-13", "text": "A PMBus device monitors VOUT/IOUT/VIN/"
         "temperature against programmable fault and warning limits, sets the "
         "relevant STATUS bits, asserts SMBALERT#, and takes the configured "
         "fault response."},
    ]
    d["error_response_conditions"] = [
        "PEC mismatch — the receiver NACKs/discards the transaction.",
        "Bus timeout (clock held low past Ttimeout) — master aborts, slave "
        "releases the bus and resets its interface.",
        "Addressed device not present / NACK on address — master aborts.",
        "WRITE_PROTECT violation — a write to a protected command is rejected "
        "and flagged in STATUS (CML).",
        "PMBus fault (VOUT/IOUT/VIN/temperature over/under limit) — STATUS "
        "bit set, SMBALERT# asserted, configured fault response taken.",
        "Invalid/unsupported command code — flagged in STATUS_CML "
        "(communication/memory/logic).",
    ]
    d["compliance_requirements"] = [
        "Two-wire SMBCLK/SMBDAT open-drain bus with 7-bit addressing, derived "
        "from I2C.",
        "Implement the relevant subset of the fixed SMBus protocol set.",
        "Honor SMBus bus timeouts (Ttimeout / Tlow:sext / Tlow:mext).",
        "Where claimed: PEC (CRC-8 0x07 over the whole transaction), "
        "SMBALERT#/ARA, and ARP (128-bit UDID).",
        "PMBus devices: implement the mandatory command subset, report the "
        "data format via VOUT_MODE and revision via PMBUS_REVISION, support "
        "STATUS reporting, and signal faults on SMBALERT#.",
        "PMBus multi-rail devices: support PAGE; PMBus 1.3 devices may support "
        "Zone Read/Write.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — SMBus protocol element set + PMBus command framing.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "I2C-derived byte-oriented bus protocol with a fixed set of SMBus "
        "transaction formats. Each transaction is START, slave-address+RW, "
        "[command code], [byte count], data byte(s), [PEC], STOP. PMBus "
        "carries its command codes in the SMBus Write/Read Byte/Word/Block "
        "transactions.")
    d["byte_oriented"] = True
    d["burst_based"] = False
    d["pec_crc"] = {
        "name": "Packet Error Code (PEC)", "type": "CRC-8",
        "polynomial": "x^8 + x^2 + x^1 + 1", "polynomial_hex": "0x07",
        "initial_value": "0x00",
        "coverage": "all bytes of the transaction (address byte(s) including "
                    "the R/W bit, command code, and all data bytes)",
        "placement": "one byte appended immediately before STOP",
        "optional": True,
    }
    d["channels"] = [
        {"name": "SMBCLK", "direction": "master -> bus (open-drain)",
         "description": "Serial clock; may be clock-low-extended (stretched) "
         "by master or slave within timeout limits."},
        {"name": "SMBDAT", "direction": "bidirectional (open-drain, "
         "wired-AND)",
         "description": "Serial data; carries address, command, data, and PEC "
         "bytes MSB-first."},
        {"name": "SMBALERT#", "direction": "device -> host (open-drain, "
         "wired-OR)",
         "description": "Optional shared interrupt; serviced via the Alert "
         "Response Address."},
        {"name": "CONTROL (PMBus)", "direction": "host -> device",
         "description": "Hardware enable input on a power device; combines "
         "with OPERATION/ON_OFF_CONFIG."},
    ]
    d["smbus_protocol_formats"] = [
        {"name": "Quick Command",
         "format": "START, Address+RW, STOP",
         "description": "The single R/W bit conveys the whole message; no data "
         "byte, no PEC."},
        {"name": "Send Byte",
         "format": "START, Address+Wr, Data, [PEC], STOP",
         "description": "Send one command/data byte."},
        {"name": "Receive Byte",
         "format": "START, Address+Rd, Data, [PEC], STOP",
         "description": "Read one byte (no command code)."},
        {"name": "Write Byte / Write Word",
         "format": "START, Address+Wr, Command, Data [, Data high], [PEC], "
         "STOP",
         "description": "Write 1 byte (Byte) or 2 bytes low+high (Word) to a "
         "command code."},
        {"name": "Read Byte / Read Word",
         "format": "START, Address+Wr, Command, Sr, Address+Rd, Data "
         "[, Data high], [PEC], STOP",
         "description": "Write the command then repeated-START read 1 (Byte) "
         "or 2 (Word) data bytes."},
        {"name": "Process Call",
         "format": "START, Address+Wr, Command, DataLo, DataHi, Sr, "
         "Address+Rd, DataLo, DataHi, [PEC], STOP",
         "description": "16-bit write-then-read in one transaction."},
        {"name": "Block Write",
         "format": "START, Address+Wr, Command, ByteCount N, Data1..DataN, "
         "[PEC], STOP",
         "description": "Byte Count (1..255) tells the slave how many data "
         "bytes follow."},
        {"name": "Block Read",
         "format": "START, Address+Wr, Command, Sr, Address+Rd, ByteCount N, "
         "Data1..DataN, [PEC], STOP",
         "description": "Slave returns a Byte Count then that many data "
         "bytes."},
        {"name": "Block Write-Block Read Process Call",
         "format": "Block Write immediately followed by Block Read",
         "description": "Variable-length call-and-response."},
        {"name": "Host Notify",
         "format": "device-as-master writes to Host Notify address: own "
         "address + 16-bit data",
         "description": "Asynchronous device-to-host notification."},
    ]
    d["addressing"] = {
        "address_bits": 7,
        "rw_bit": "8th bit of the address byte (0 = write, 1 = read)",
        "reserved_addresses": {
            "alert_response_address_ARA": "0b0001100",
            "smbus_device_default_address_ARP": "0b1100001",
            "host_notify_address": "0b0001000",
        },
        "dynamic_assignment": "via ARP using the 128-bit UDID.",
    }
    d["pmbus_command_framing"] = {
        "note": "PMBus command codes are the SMBus command byte; the command "
                "determines whether the transaction is Write/Read Byte, "
                "Word, or Block.",
        "examples": [
            {"command": "PAGE", "code": "0x00", "smbus_txn": "Write Byte"},
            {"command": "OPERATION", "code": "0x01", "smbus_txn": "Write Byte"},
            {"command": "VOUT_MODE", "code": "0x20", "smbus_txn": "Read Byte"},
            {"command": "VOUT_COMMAND", "code": "0x21",
             "smbus_txn": "Write Word (ULINEAR16)"},
            {"command": "STATUS_BYTE", "code": "0x78",
             "smbus_txn": "Read Byte"},
            {"command": "STATUS_WORD", "code": "0x79",
             "smbus_txn": "Read Word"},
            {"command": "READ_VIN", "code": "0x88",
             "smbus_txn": "Read Word (LINEAR11)"},
            {"command": "READ_VOUT", "code": "0x8B",
             "smbus_txn": "Read Word (ULINEAR16)"},
            {"command": "READ_IOUT", "code": "0x8C",
             "smbus_txn": "Read Word (LINEAR11)"},
            {"command": "READ_TEMPERATURE_1", "code": "0x8D",
             "smbus_txn": "Read Word (LINEAR11)"},
            {"command": "MFR_ID", "code": "0x99", "smbus_txn": "Block Read"},
        ],
    }
    d["frame_format"] = {
        "bit_order": "MSB-first per byte; each byte ACK/NACK'd on the 9th "
                     "clock.",
        "transaction_framing": "START condition, then address+RW, then "
        "protocol-specific bytes (command / byte-count / data), optional PEC, "
        "STOP condition.",
        "repeated_start": "Read Byte/Word, Process Call, and Block Read use a "
        "repeated START (Sr) to turn the bus around.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — PMBus command-code register/command map (over SMBus).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "SMBus itself is command/protocol-oriented rather than register-mapped; "
        "ARP/PEC/SMBALERT# state is per-device. PMBus, however, defines a "
        "standard command-code 'register' map: each command code (0x00..0xFF) "
        "addresses a configuration, control, or read-back function accessed "
        "through SMBus Write/Read Byte/Word/Block transactions, paged per rail "
        "by PAGE.")
    d["address_space"] = {
        "command_code_width_bits": 8, "range": "0x00..0xFF",
        "paged_by": "PAGE (0x00); 0xFF addresses all pages",
    }
    d["pmbus_command_groups"] = [
        {"group": "Paging / identification", "commands": [
            {"name": "PAGE", "code": "0x00", "access": "R/W Byte"},
            {"name": "PMBUS_REVISION", "code": "0x98", "access": "R Byte"},
            {"name": "MFR_ID", "code": "0x99", "access": "R Block"},
            {"name": "MFR_MODEL", "code": "0x9A", "access": "R Block"}]},
        {"group": "On/off & protection control", "commands": [
            {"name": "OPERATION", "code": "0x01", "access": "R/W Byte"},
            {"name": "ON_OFF_CONFIG", "code": "0x02", "access": "R/W Byte"},
            {"name": "WRITE_PROTECT", "code": "0x10", "access": "R/W Byte"}]},
        {"group": "Output-voltage configuration", "commands": [
            {"name": "VOUT_MODE", "code": "0x20", "access": "R Byte"},
            {"name": "VOUT_COMMAND", "code": "0x21",
             "access": "R/W Word (ULINEAR16)"},
            {"name": "VOUT_MAX", "code": "0x24",
             "access": "R/W Word (ULINEAR16)"}]},
        {"group": "Fault limits", "commands": [
            {"name": "VIN_ON", "code": "0x35", "access": "R/W Word"},
            {"name": "VOUT_OV_FAULT_LIMIT", "code": "0x40",
             "access": "R/W Word"},
            {"name": "IOUT_OC_FAULT_LIMIT", "code": "0x46",
             "access": "R/W Word"},
            {"name": "OT_FAULT_LIMIT", "code": "0x4F", "access": "R/W Word"}]},
        {"group": "Status registers", "commands": [
            {"name": "STATUS_BYTE", "code": "0x78", "access": "R Byte"},
            {"name": "STATUS_WORD", "code": "0x79", "access": "R Word"},
            {"name": "STATUS_VOUT", "code": "0x7A", "access": "R Byte"},
            {"name": "STATUS_IOUT", "code": "0x7B", "access": "R Byte"},
            {"name": "STATUS_TEMPERATURE", "code": "0x7D",
             "access": "R Byte"}]},
        {"group": "Telemetry read-back", "commands": [
            {"name": "READ_VIN", "code": "0x88",
             "access": "R Word (LINEAR11)"},
            {"name": "READ_VOUT", "code": "0x8B",
             "access": "R Word (ULINEAR16)"},
            {"name": "READ_IOUT", "code": "0x8C",
             "access": "R Word (LINEAR11)"},
            {"name": "READ_TEMPERATURE_1", "code": "0x8D",
             "access": "R Word (LINEAR11)"}]},
    ]
    d["status_word_bit_groups"] = [
        "VOUT", "IOUT", "INPUT", "MFR_SPECIFIC", "POWER_GOOD#",
        "FANS", "OTHER", "UNKNOWN", "TEMPERATURE", "CML "
        "(communication/memory/logic)", "VOUT (lower byte)", "OFF", "BUSY",
    ]
    d["write_protect_levels"] = [
        "0x80: disable all writes except WRITE_PROTECT",
        "0x40: allow writes only to WRITE_PROTECT, OPERATION, PAGE",
        "0x20: allow writes only to WRITE_PROTECT, OPERATION, PAGE, "
        "ON_OFF_CONFIG, VOUT_COMMAND",
        "0x00: enable all writes",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — SMBus electrical / signaling spec (open-drain 2-wire derived from I2C).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Two open-drain (open-collector) lines SMBCLK and SMBDAT pulled up to "
        "VDD, wired-AND, derived from I2C electrical signaling. SMBus tightens "
        "I2C's DC parameters for low-power management devices: defined VIL/VIH "
        "thresholds, a leakage/pull-up window, a 10 kHz minimum clock, and "
        "clock-low timeouts. SMBALERT# is an additional open-drain wired-OR "
        "interrupt line. Data is sampled while SMBCLK is high; transitions "
        "occur while SMBCLK is low.")
    d["logic_thresholds"] = {
        "VIL_max": "0.8 V (fixed-threshold devices)",
        "VIH_min": "2.1 V (fixed-threshold devices)",
        "note": "SMBus defines both fixed and VDD-relative threshold device "
                "classes; values are spec-class-dependent.",
    }
    d["bus_speed_kHz"] = {"min": 10, "smbus_2_0_max": 100,
                          "smbus_3_x_max": 1000, "pmbus_typical_max": 400}
    d["timeouts_ms"] = {"Ttimeout": "25 to 35", "Tlow_sext": "<= 25",
                        "Tlow_mext": "<= 10"}
    d["clocking"] = (
        "Synchronous to SMBCLK driven by the master; not source-synchronous, "
        "not embedded-clock. Clock stretching (clock-low extending) is allowed "
        "within Tlow:sext / Tlow:mext.")
    d["pull_up"] = (
        "External pull-up resistors on SMBCLK/SMBDAT (and SMBALERT#) bias the "
        "open-drain lines to VDD; size depends on bus capacitance and speed.")
    d["derived_from"] = "I2C electrical layer (open-drain wired-AND)"
    d["pmbus_control_pin_electrical"] = (
        "The PMBus CONTROL pin is a logic input on the power device, "
        "polarity-configurable via ON_OFF_CONFIG; it is a discrete hardware "
        "enable, not part of the SMBus 2-wire signaling.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — SMBus transaction FSM + PMBus converter-control state machine.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states"] = [
        {"name": "IDLE", "description": "Bus free; device listening for a "
         "START and its address. PMBus output may be off."},
        {"name": "START", "description": "Master drives a START condition "
         "(SMBDAT falls while SMBCLK high)."},
        {"name": "ADDRESS", "description": "Master shifts the 7-bit address + "
         "R/W bit; the addressed slave ACKs."},
        {"name": "COMMAND", "description": "For Write/Read Byte/Word/Block and "
         "PMBus, the command code byte is transferred and ACK'd."},
        {"name": "DATA", "description": "Data byte(s) transferred MSB-first, "
         "each ACK/NACK'd; Block transfers include a Byte Count."},
        {"name": "PEC", "description": "Optional Packet Error Code (CRC-8) "
         "byte transferred and checked before STOP."},
        {"name": "STOP", "description": "Master drives a STOP condition "
         "(SMBDAT rises while SMBCLK high); bus returns to IDLE."},
        {"name": "ALERT_RESPONSE", "description": "On SMBALERT# low the host "
         "issues Receive Byte to the ARA; alerting devices arbitrate and the "
         "winner returns its address."},
        {"name": "ARP", "description": "Address Resolution: Prepare-to-ARP / "
         "Get-UDID / Assign-Address at the Device Default Address."},
        {"name": "FAULT", "description": "(PMBus) a monitored quantity crossed "
         "a limit: STATUS bits set, SMBALERT# asserted, configured fault "
         "response taken."},
        {"name": "TIMEOUT", "description": "SMBCLK held low past Ttimeout; "
         "master aborts, slave releases the bus and resets its interface."},
    ]
    d["pmbus_output_control_logic"] = {
        "inputs": ["OPERATION command", "CONTROL pin", "ON_OFF_CONFIG"],
        "rule": "ON_OFF_CONFIG selects whether the output is enabled by the "
                "CONTROL pin, by the OPERATION command, by both (AND), or by "
                "neither, and sets CONTROL polarity and turn-off behavior.",
        "states": ["OFF", "ON / REGULATING", "MARGIN_HIGH", "MARGIN_LOW"],
    }
    d["fsm_hints"] = {
        "trigger": "A START + matching address begins a transaction; STOP "
        "ends it. SMBALERT# low triggers the Alert Response sequence.",
        "rule": "If PEC is enabled, the CRC-8 over the whole transaction is "
        "checked before the data is committed; a mismatch NACKs the "
        "transaction.",
        "abort": "Clock-low past Ttimeout (25-35 ms) aborts the transaction "
        "and resets the slave interface.",
    }
    d["anti_deadlock_rule"] = (
        "SMBus bus timeouts (Ttimeout / Tlow:sext / Tlow:mext) guarantee a "
        "hung device cannot lock the bus indefinitely — the master aborts and "
        "all devices release the bus, returning to IDLE. This is the key "
        "robustness addition over base I2C.")
    d["exit_from_reset_or_poweron"] = (
        "After power-on/reset a device enters IDLE with its output off "
        "(PMBus), listening for its address. It adopts its address either from "
        "hardware strapping or, if ARP-capable, from the ARP master via "
        "Assign-Address. PMBus output enable then follows OPERATION + CONTROL "
        "pin + ON_OFF_CONFIG.")
    d["configurations"] = [
        {"name": "PEC enabled", "description": "Every transaction carries a "
         "CRC-8 PEC byte for integrity."},
        {"name": "SMBALERT# / ARA", "description": "Shared interrupt with "
         "host-driven Alert Response."},
        {"name": "ARP-capable", "description": "Dynamic address assignment via "
         "128-bit UDID."},
        {"name": "PMBus multi-rail", "description": "PAGE selects the rail; "
         "group/zone commands coordinate devices."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — observability: STATUS registers, SMBALERT#, PEC, ARP enumeration.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "PMBus STATUS registers", "purpose": "STATUS_BYTE / "
         "STATUS_WORD plus detailed STATUS_VOUT / STATUS_IOUT / "
         "STATUS_TEMPERATURE localize faults and warnings."},
        {"name": "SMBALERT# / Alert Response", "purpose": "Out-of-band "
         "interrupt; the host enumerates alerting devices via the ARA."},
        {"name": "Telemetry read-back", "purpose": "READ_VIN/VOUT/IOUT/"
         "TEMPERATURE_1 give live measurements for monitoring/debug."},
        {"name": "PEC", "purpose": "CRC-8 over each transaction detects bus "
         "bit errors; mismatch is observable as a NACK."},
        {"name": "ARP / Get-UDID", "purpose": "Enumerate devices and read "
         "their 128-bit UDID for identification."},
        {"name": "PMBUS_REVISION / MFR_ID / MFR_MODEL", "purpose": "Identify "
         "the device's PMBus revision and manufacturer/model."},
    ]
    d["error_detection_mechanisms"] = [
        "Packet Error Code (CRC-8) detects transaction bit errors.",
        "Per-byte ACK/NACK on the 9th clock detects missing/unresponsive "
        "devices.",
        "Bus timeouts detect a hung device holding SMBCLK low.",
        "PMBus STATUS bits (incl. CML) flag communication/command/fault "
        "conditions.",
        "WRITE_PROTECT rejection flags illegal configuration writes.",
    ]
    d["notes"] = (
        "SMBus/PMBus observability is in-band: the host reads STATUS and "
        "telemetry over the same two wires, services SMBALERT# via the ARA, "
        "verifies integrity with PEC, and enumerates devices with ARP. There "
        "is no separate scan/JTAG layer in the protocol; chip-level DFT is the "
        "device implementer's concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — SMBus/PMBus widths and PEC polynomial.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "ADDRESS_BITS": 7,
        "RW_BIT": 1,
        "DATA_BYTE_BITS": 8,
        "WORD_BITS": 16,
        "BYTE_COUNT_FIELD_BITS": 8,
        "BLOCK_MAX_BYTES": 255,
        "PEC_WIDTH_BITS": 8,
        "PEC_POLYNOMIAL_HEX": "0x07",
        "PEC_POLYNOMIAL": "x^8 + x^2 + x^1 + 1",
        "PEC_INIT": "0x00",
        "UDID_BITS": 128,
        "COMMAND_CODE_BITS": 8,
        "PMBUS_LINEAR11_EXP_BITS": 5,
        "PMBUS_LINEAR11_MANTISSA_BITS": 11,
        "PMBUS_LINEAR16_MANTISSA_BITS": 16,
        "SMBUS_MIN_CLOCK_KHZ": 10,
        "SMBUS_2_0_MAX_CLOCK_KHZ": 100,
        "SMBUS_3_X_MAX_CLOCK_KHZ": 1000,
        "PMBUS_TYPICAL_MAX_CLOCK_KHZ": 400,
        "TTIMEOUT_MS_MIN": 25,
        "TTIMEOUT_MS_MAX": 35,
        "TLOW_SEXT_MS_MAX": 25,
        "TLOW_MEXT_MS_MAX": 10,
    })
    d["key_constants_for_RTL_authoring"] = {
        "is_two_wire": True,
        "is_open_drain": True,
        "derived_from_i2c": True,
        "address_bits": 7,
        "msb_first": True,
        "ack_on_9th_clock": True,
        "pec_crc8_poly_hex": "0x07",
        "pec_optional": True,
        "block_byte_count_present": True,
        "udid_bits": 128,
        "smbalert_open_drain_wired_or": True,
        "clock_stretching_allowed": True,
        "bus_timeout_required": True,
        "pmbus_command_code_bits": 8,
        "pmbus_data_formats": list(_PMBUS_DATA_FORMATS),
    }
    d["reserved_addresses"] = {
        "alert_response_address": "0b0001100",
        "smbus_device_default_address": "0b1100001",
        "host_notify_address": "0b0001000",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — SMBus transaction + PEC + timeout waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["bus_waveform"] = {
        "start": "SMBDAT falls while SMBCLK is high.",
        "stop": "SMBDAT rises while SMBCLK is high.",
        "repeated_start": "A new START without an intervening STOP (Read "
                          "Byte/Word, Process Call, Block Read).",
        "bit_sampling": "Data is valid/sampled while SMBCLK is high; data "
                        "changes while SMBCLK is low.",
        "ack": "Receiver pulls SMBDAT low on the 9th clock to ACK.",
        "bit_order": "MSB-first.",
    }
    d["transaction_waveform"] = {
        "generic": "START | Addr[6:0]+RW | ACK | (Command | ACK) | (ByteCount "
                   "| ACK) | Data | ACK ... | (PEC | ACK) | STOP",
        "quick_command": "START | Addr+RW | ACK | STOP (no data).",
        "block": "...Command | ByteCount N | Data1..DataN | [PEC] | STOP.",
    }
    d["pec_waveform"] = {
        "definition": "CRC-8 (poly 0x07, init 0x00) over every transmitted "
                      "byte; the PEC byte is the last byte before STOP.",
        "check": "Receiver recomputes the CRC and NACKs on mismatch.",
    }
    d["timeout_waveform"] = {
        "Ttimeout_ms": "25 to 35 (max SMBCLK-low time before abort/reset)",
        "Tlow_sext_ms": "<= 25 (cumulative slave clock-low extend)",
        "Tlow_mext_ms": "<= 10 (cumulative master clock-low extend per byte)",
    }
    d["clock_waveform"] = {
        "min_freq_kHz": 10, "smbus_2_0_max_kHz": 100, "smbus_3_x_max_kHz": 1000,
        "pmbus_typical_max_kHz": 400,
        "clock_stretching": "allowed within Tlow:sext / Tlow:mext.",
    }
    d["general_timing_rule"] = (
        "SMBus is synchronous to SMBCLK (master-driven). Each byte is 8 bits "
        "MSB-first followed by an ACK/NACK clock. Optional PEC adds one byte. "
        "Unlike I2C, SMBus mandates a 10 kHz minimum clock and clock-low "
        "timeouts so a stalled transaction is detected and the bus recovered.")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec (SMBus/PMBus device on a system-management bus).
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "System-management / power-management bus interface: an I2C-derived "
        "two-wire SMBCLK/SMBDAT slave (and optionally master/host) that "
        "implements the SMBus protocol set with optional PEC, SMBALERT#/ARA, "
        "ARP, and timeouts, optionally exposing the PMBus command language "
        "(command codes + LINEAR/DIRECT/VID + CONTROL pin + PAGE + group/zone) "
        "for power-converter control and monitoring.")
    d["topology_description"] = (
        "Multi-drop 2-wire bus: all devices share SMBCLK and SMBDAT "
        "(open-drain wired-AND) and an optional shared SMBALERT# (wired-OR). "
        "At most one host manages the bus; PMBus power devices add a CONTROL "
        "pin.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "address_bits": 7,
        "wires": ["SMBCLK", "SMBDAT", "SMBALERT# (optional)",
                  "CONTROL (PMBus)"],
        "derived_from": "I2C",
        "pec_optional_crc8": True,
        "arp_dynamic_addressing": True,
        "smbalert_interrupt": True,
        "bus_speed_kHz": {"min": 10, "smbus_2_0_max": 100,
                          "smbus_3_x_max": 1000, "pmbus_typical_max": 400},
        "pmbus_application_layer": True,
        "pmbus_data_formats": list(_PMBUS_DATA_FORMATS),
        "host_side_register_spec": "PMBus command-code map (0x00..0xFF), paged "
        "by PAGE; STATUS_WORD/BYTE for fault summary; READ_* for telemetry.",
    })
    d["interface_categories"] = [
        "SMBus transport — SMBCLK/SMBDAT 2-wire, 7-bit addressing, protocol "
        "set, PEC, timeouts.",
        "SMBALERT# / Alert Response — out-of-band shared interrupt + ARA.",
        "ARP — dynamic address assignment via 128-bit UDID.",
        "PMBus command language — command-code register map + LINEAR/DIRECT/"
        "VID data formats.",
        "CONTROL pin + ON_OFF_CONFIG — hardware/command output enable "
        "(PMBus).",
        "PAGE / group / zone — multi-rail and multi-device coordination "
        "(PMBus).",
    ]
    d["soc_dependent_items"] = [
        "Pull-up resistor sizing for SMBCLK/SMBDAT/SMBALERT# vs bus "
        "capacitance and target speed.",
        "Device address (hardware strap vs ARP-assigned).",
        "Whether PEC, SMBALERT#, and ARP are implemented/claimed.",
        "PMBus command subset, declared data format (VOUT_MODE), and rail "
        "count (PAGE).",
        "CONTROL-pin polarity and ON_OFF_CONFIG enable source.",
        "Bus speed (100 kHz vs up to 1 MHz) and timeout compliance.",
    ]
    d["default_signal_values_when_omitted"] = (
        "SMBCLK/SMBDAT idle high (released, pulled up); SMBALERT# released "
        "high (no alert); PMBus output off after reset until enabled by "
        "OPERATION + CONTROL pin per ON_OFF_CONFIG.")
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
        "partial - the specification defines protocol behaviors and "
        "compliance points (protocol set, PEC, timeouts, SMBALERT#/ARA, ARP, "
        "PMBus command/format conformance) but is not itself a testbench.")
    d["derived_compliance_test_categories"] = [
        "Each SMBus protocol: Quick Command, Send/Receive Byte, Write/Read "
        "Byte/Word, Process Call, Block Write/Read, Block Write-Block Read "
        "Process Call, Host Notify.",
        "PEC: correct CRC-8 (poly 0x07) over the whole transaction; NACK on "
        "mismatch; both write and read phases.",
        "Bus timeouts: Ttimeout (25-35 ms), Tlow:sext (<= 25 ms), Tlow:mext "
        "(<= 10 ms); hung-device recovery.",
        "SMBALERT#: assertion, Alert Response at the ARA, arbitration "
        "(lowest address wins), release.",
        "ARP: Prepare-to-ARP, Get-UDID (128-bit), Assign-Address, "
        "UDID-arbitration enumeration.",
        "Clock range: 10 kHz min, 100 kHz (2.0) / 1 MHz (3.x) max; clock "
        "stretching within limits.",
        "PMBus commands: PAGE, OPERATION, ON_OFF_CONFIG, VOUT_MODE, "
        "VOUT_COMMAND, STATUS_BYTE/WORD, READ_VIN/VOUT/IOUT/TEMPERATURE_1.",
        "PMBus data formats: LINEAR11 decode (Y*2^N), LINEAR16/ULINEAR16 with "
        "VOUT_MODE exponent, DIRECT (m/b/R), VID.",
        "CONTROL pin + ON_OFF_CONFIG: enable-source and polarity combinations.",
        "WRITE_PROTECT: each level rejects the correct command set.",
        "Faults: limit crossing sets STATUS bits, asserts SMBALERT#, takes "
        "configured response.",
        "PAGE multi-rail; group command; Zone Read/Write (PMBus 1.3).",
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
        {"field": "UDID (Unique Device Identifier)", "width_bits": 128,
         "location": "ARP-accessible", "note": "Device capabilities, version, "
         "vendor ID, device ID, interface, subsystem, and a unique number; "
         "used by ARP for dynamic addressing."},
        {"field": "Default / strapped SMBus address", "width_bits": 7,
         "location": "hardware strap or ARP-assigned",
         "note": "7-bit device address."},
        {"field": "PMBUS_REVISION", "width_bits": 8, "location": "command 0x98",
         "note": "PMBus revision the device complies with."},
        {"field": "MFR_ID / MFR_MODEL", "width_bits": "block",
         "location": "commands 0x99 / 0x9A",
         "note": "Manufacturer identity (Block Read)."},
        {"field": "VOUT_MODE", "width_bits": 8, "location": "command 0x20",
         "note": "Declares the data format (LINEAR16 exponent / DIRECT / VID) "
                 "for voltage commands."},
    ]
    d["notes"] = (
        "SMBus/PMBus do not define OTP as a protocol concept. Identity and "
        "capability are exposed through the 128-bit UDID (ARP), PMBUS_REVISION, "
        "MFR_ID/MFR_MODEL, and VOUT_MODE; an implementation may back these "
        "with fuses but the spec only requires they be discoverable over the "
        "bus.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences (transactions, PEC, alert, ARP, fault).
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["write_word_with_pec_sequence"] = [
        "1. Master issues START.",
        "2. Master sends Address + Write; slave ACKs.",
        "3. Master sends Command code (e.g. VOUT_COMMAND 0x21); slave ACKs.",
        "4. Master sends Data Low then Data High; slave ACKs each.",
        "5. Master sends the PEC byte (CRC-8 over all prior bytes).",
        "6. Slave checks PEC: ACK if good, NACK if mismatch.",
        "7. Master issues STOP; on good PEC the command is committed.",
    ]
    d["read_word_sequence"] = [
        "1. START, Address + Write, Command code (e.g. READ_VOUT 0x8B), slave "
        "ACKs each.",
        "2. Repeated START (Sr), Address + Read; slave ACKs.",
        "3. Slave returns Data Low then Data High (master ACKs Low, then "
        "ACK+PEC or NACK).",
        "4. Optional PEC byte; master/slave check.",
        "5. Master issues STOP; host decodes per the data format (ULINEAR16 + "
        "VOUT_MODE).",
    ]
    d["block_read_sequence"] = [
        "1. START, Address + Write, Command code; slave ACKs.",
        "2. Repeated START, Address + Read; slave ACKs.",
        "3. Slave sends Byte Count N, then Data1..DataN.",
        "4. Optional PEC; STOP.",
    ]
    d["alert_response_sequence"] = [
        "1. A device asserts SMBALERT# low.",
        "2. Host issues Receive Byte to the Alert Response Address (ARA).",
        "3. Alerting devices arbitrate on SMBDAT; the lowest address wins and "
        "returns its 7-bit address.",
        "4. Host services that device (e.g. reads STATUS); device releases "
        "SMBALERT#.",
        "5. Host repeats until SMBALERT# is released by all devices.",
    ]
    d["arp_sequence"] = [
        "1. ARP master sends Prepare to ARP at the Device Default Address.",
        "2. Get UDID — devices return their 128-bit UDID + current address; "
        "lowest UDID wins arbitration, enumerating all devices.",
        "3. Assign Address — master writes a UDID + a new 7-bit address; the "
        "matching device adopts it.",
        "4. Repeat until all devices are addressed.",
    ]
    d["pmbus_turn_on_sequence"] = [
        "1. Host sets configuration (VOUT_COMMAND, limits) via Write Word "
        "(subject to WRITE_PROTECT).",
        "2. Host sends OPERATION = on (and/or asserts the CONTROL pin per "
        "ON_OFF_CONFIG).",
        "3. Converter ramps and regulates to the commanded VOUT.",
        "4. Host monitors via READ_VOUT/IOUT/TEMPERATURE and STATUS_WORD.",
    ]
    d["fault_sequence"] = [
        "1. A monitored quantity (VOUT/IOUT/VIN/temperature) crosses its fault "
        "limit.",
        "2. The device sets the relevant STATUS bit(s) and asserts SMBALERT#.",
        "3. The device takes the configured fault response (shut down / retry "
        "/ continue).",
        "4. Host reads STATUS_WORD then STATUS_VOUT/IOUT/TEMPERATURE to "
        "localize the fault.",
    ]
    d["reset_sequence"] = [
        "1. Power-on/reset -> IDLE, output off (PMBus).",
        "2. Address from strap or ARP Assign-Address.",
        "3. Output enabled per OPERATION + CONTROL pin + ON_OFF_CONFIG.",
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
        {"name": "Bus timing", "purpose": "Verify SMBCLK frequency range "
         "(10 kHz-1 MHz), setup/hold, and clock-low timeouts (Ttimeout, "
         "Tlow:sext, Tlow:mext)."},
        {"name": "DC thresholds", "purpose": "Confirm VIL/VIH and pull-up / "
         "leakage windows for the device's threshold class."},
        {"name": "PEC integrity", "purpose": "Inject bit errors and confirm "
         "the CRC-8 PEC catches them (NACK)."},
        {"name": "SMBALERT# / ARA", "purpose": "Verify alert assertion, "
         "arbitration, and release."},
        {"name": "ARP enumeration", "purpose": "Verify UDID read and dynamic "
         "Assign-Address."},
        {"name": "PMBus telemetry accuracy", "purpose": "Compare READ_VOUT/"
         "IOUT/TEMPERATURE against references; validate LINEAR/DIRECT/VID "
         "decoding."},
        {"name": "Fault response", "purpose": "Force limit crossings and "
         "verify STATUS bits, SMBALERT#, and the configured response."},
    ]
    d["notes"] = (
        "Characterization centers on the I2C-derived electrical bus (timing, "
        "thresholds, pull-ups), the SMBus robustness features (PEC, timeouts, "
        "SMBALERT#, ARP), and PMBus telemetry/format accuracy and fault "
        "behavior.")
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
        "System Management Bus (SMBus) Specification 3.1 (2018) + Power "
        "Management Bus (PMBus) Specification Part I/II Rev 1.3.1 (2015)")
    f["previous_versions"] = [
        "SMBus 1.0 (1995) / 2.0 (2000) — 100 kHz; protocol set, PEC, ARP, "
        "SMBALERT#, Host Notify, timeouts.",
        "SMBus 3.0 (2014) — 1 MHz high-speed mode.",
        "PMBus 1.0-1.2 — command language, LINEAR/DIRECT/VID, "
        "OPERATION/CONTROL, STATUS, PAGE.",
    ]
    f["key_changes"] = [
        {"version": "SMBus 3.1", "summary": "1 MHz high-speed mode, larger "
         "block transfers clarified, additional electrical options; protocol "
         "set, PEC, ARP, SMBALERT#, and timeouts carried forward."},
        {"version": "PMBus 1.3", "summary": "Adds Zone Read/Write, additional "
         "commands, and AVSBus references; the command language, data "
         "formats, OPERATION/CONTROL, STATUS, and PAGE are unchanged."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "SMBus_is_not_plain_I2C",
         "rule": "SMBus adds a 10 kHz minimum clock and clock-low timeouts.",
         "trap": "An I2C device with no minimum clock or that stretches the "
                 "clock past Ttimeout will be aborted on an SMBus."},
        {"trap_name": "PEC_must_be_agreed",
         "rule": "PEC is optional; both ends must agree to use it.",
         "trap": "Sending an unexpected PEC byte (or omitting an expected "
                 "one) breaks the transaction byte count."},
        {"trap_name": "VOUT_uses_VOUT_MODE_exponent",
         "rule": "READ_VOUT/VOUT_COMMAND use ULINEAR16 whose exponent is in "
                 "VOUT_MODE, NOT in the data word.",
         "trap": "Decoding VOUT as LINEAR11 (exponent-in-word) gives a wrong "
                 "voltage."},
        {"trap_name": "PAGE_is_stateful",
         "rule": "PAGE selects the active rail; subsequent commands apply to "
                 "it until PAGE changes.",
         "trap": "Forgetting to set PAGE reads/writes the wrong rail in a "
                 "multi-rail device."},
        {"trap_name": "Address_may_be_ARP_assigned",
         "rule": "ARP can reassign a device's 7-bit address dynamically.",
         "trap": "Assuming a fixed address on an ARP bus can target the wrong "
                 "device after enumeration."},
    ]
    f["version_naming_history_note"] = (
        "SMBus is maintained by the System Management Interface Forum (SMIF); "
        "PMBus is an open standard layered on SMBus (PMBus Part I transport = "
        "SMBus; Part II = command language). Facts here are grounded in the "
        "public SMBus 3.x and PMBus 1.3 specifications.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding/command/format tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["smbus_protocol_table"] = {
        "header_columns": ["Protocol", "Command byte?", "Data", "PEC?"],
        "rows": [
            ["Quick Command", "no", "none (R/W bit only)", "no"],
            ["Send Byte", "no", "1 byte", "optional"],
            ["Receive Byte", "no", "1 byte", "optional"],
            ["Write Byte", "yes", "1 byte", "optional"],
            ["Write Word", "yes", "2 bytes (lo,hi)", "optional"],
            ["Read Byte", "yes", "1 byte", "optional"],
            ["Read Word", "yes", "2 bytes (lo,hi)", "optional"],
            ["Process Call", "yes", "2 wr + 2 rd", "optional"],
            ["Block Write", "yes", "count + N bytes", "optional"],
            ["Block Read", "yes", "count + N bytes", "optional"],
            ["Block Wr-Block Rd Process Call", "yes", "wr block + rd block",
             "optional"],
            ["Host Notify", "n/a", "addr + 16-bit data", "no"],
        ],
    }
    f["pmbus_command_table"] = {
        "header_columns": ["Command", "Code", "Access", "Format"],
        "rows": [
            ["PAGE", "0x00", "R/W Byte", "-"],
            ["OPERATION", "0x01", "R/W Byte", "bitfield"],
            ["ON_OFF_CONFIG", "0x02", "R/W Byte", "bitfield"],
            ["WRITE_PROTECT", "0x10", "R/W Byte", "bitfield"],
            ["VOUT_MODE", "0x20", "R Byte", "mode+exp"],
            ["VOUT_COMMAND", "0x21", "R/W Word", "ULINEAR16"],
            ["STATUS_BYTE", "0x78", "R Byte", "bitfield"],
            ["STATUS_WORD", "0x79", "R Word", "bitfield"],
            ["READ_VIN", "0x88", "R Word", "LINEAR11"],
            ["READ_VOUT", "0x8B", "R Word", "ULINEAR16"],
            ["READ_IOUT", "0x8C", "R Word", "LINEAR11"],
            ["READ_TEMPERATURE_1", "0x8D", "R Word", "LINEAR11"],
            ["PMBUS_REVISION", "0x98", "R Byte", "-"],
        ],
    }
    f["data_format_table"] = {
        "header_columns": ["Format", "Layout", "Value"],
        "rows": [
            ["LINEAR11", "5-bit signed exp N + 11-bit signed mantissa Y",
             "X = Y * 2^N"],
            ["LINEAR16/ULINEAR16", "16-bit unsigned mantissa; exp in VOUT_MODE",
             "VOUT = V * 2^(VOUT_MODE exp)"],
            ["DIRECT", "16-bit raw value X; coefficients m, b, R",
             "Y = (1/m)*(X*10^(-R) - b)"],
            ["VID", "VID code per a named VID table", "table lookup"],
        ],
    }
    f["pec_table"] = {
        "header_columns": ["Property", "Value"],
        "rows": [
            ["Type", "CRC-8"],
            ["Polynomial", "x^8 + x^2 + x^1 + 1 (0x07)"],
            ["Initial value", "0x00"],
            ["Coverage", "whole transaction (addr + cmd + data)"],
            ["Placement", "last byte before STOP"],
        ],
    }
    f["reserved_address_table"] = {
        "header_columns": ["Name", "Address"],
        "rows": [
            ["Alert Response Address (ARA)", "0b0001100"],
            ["SMBus Device Default Address (ARP)", "0b1100001"],
            ["Host Notify Address", "0b0001000"],
        ],
    }
    f["tables"] = [
        "SMBus protocol table",
        "PMBus command-code table",
        "PMBus data-format table (LINEAR11 / LINEAR16 / DIRECT / VID)",
        "PEC (CRC-8) table",
        "Reserved-address table",
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
        "Two-wire SMBCLK/SMBDAT open-drain bus derived from I2C, 7-bit "
        "addressing.",
        "The relevant subset of the fixed SMBus protocol set.",
        "Bus timeouts (Ttimeout / Tlow:sext / Tlow:mext) for hung-device "
        "recovery.",
        "10 kHz minimum clock; 100 kHz (2.0) / up to 1 MHz (3.x) maximum.",
        "Where claimed: PEC (CRC-8 0x07 over the whole transaction).",
        "Where claimed: SMBALERT# + Alert Response Address.",
        "Where claimed: ARP with a 128-bit UDID.",
        "PMBus: standard command codes carried in SMBus transactions.",
        "PMBus: LINEAR11 / LINEAR16(ULINEAR16) / DIRECT / VID data formats "
        "(declared via VOUT_MODE).",
        "PMBus: CONTROL pin + ON_OFF_CONFIG; WRITE_PROTECT; STATUS reporting; "
        "PAGE for multi-rail.",
    ]
    f["must_not_have_properties"] = [
        "No minimum clock or clock-low timeout (that is plain I2C, not "
        "SMBus).",
        "An unnegotiated/mismatched PEC byte.",
        "Decoding VOUT (ULINEAR16) as LINEAR11 (wrong exponent source).",
        "Ignoring PAGE state on a multi-rail PMBus device.",
        "Differential or push-pull mainband signaling (SMBus is open-drain "
        "wired-AND, except UFm-style push-pull options).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Timeout non-compliance", "trigger": "Device holds SMBCLK "
         "low past Ttimeout without releasing."},
        {"mode": "PEC mismatch", "trigger": "CRC-8 over the transaction does "
         "not match the PEC byte."},
        {"mode": "Alert not released", "trigger": "Device keeps SMBALERT# low "
         "after being serviced."},
        {"mode": "ARP collision", "trigger": "Two devices fail to arbitrate "
         "on UDID during Get-UDID."},
        {"mode": "Wrong data-format decode", "trigger": "Host applies the "
         "wrong LINEAR/DIRECT/VID format vs VOUT_MODE."},
        {"mode": "WRITE_PROTECT bypass", "trigger": "A protected command is "
         "written and accepted."},
    ]
    f["smbus_pmbus_distinguishers"] = (
        "SMBus/PMBus is identified by ALL of: an I2C-derived two-wire "
        "SMBCLK/SMBDAT open-drain bus with 7-bit addressing; the fixed SMBus "
        "protocol set (Quick Command, Send/Receive Byte, Write/Read "
        "Byte/Word, Process Call, Block Write/Read, Host Notify); the optional "
        "Packet Error Code (CRC-8, poly 0x07); SMBALERT# + Alert Response "
        "Address; ARP with a 128-bit UDID; and bus timeouts. PMBus adds the "
        "standard command-code language, the LINEAR11/LINEAR16/DIRECT/VID data "
        "formats, the CONTROL pin, WRITE_PROTECT, PAGE, and group/zone "
        "commands. This is DISTINCT from plain I2C (which has SDA/SCL, 7-bit "
        "addressing, and START/STOP but NONE of PEC/SMBALERT#/ARP/PMBus "
        "vocabulary).")
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
        {"name": "SMBCLK", "direction": "master -> bus (open-drain)",
         "purpose": "Serial clock.", "active_levels": "pulled up to VDD; "
         "driven low by master (clock stretching allowed)",
         "idle_level": "high (released)"},
        {"name": "SMBDAT", "direction": "bidirectional (open-drain, "
         "wired-AND)", "purpose": "Serial data (address/command/data/PEC).",
         "active_levels": "pulled up to VDD; driven low for 0",
         "idle_level": "high (released)"},
        {"name": "SMBALERT#", "direction": "device -> host (open-drain, "
         "wired-OR)", "purpose": "Shared interrupt; serviced via the ARA.",
         "active_levels": "low = alert", "idle_level": "high (released)"},
        {"name": "CONTROL (PMBus)", "direction": "host -> device",
         "purpose": "Hardware enable for the converter output.",
         "active_levels": "polarity per ON_OFF_CONFIG",
         "idle_level": "per ON_OFF_CONFIG"},
    ]
    f["global_signals"] = [
        {"name": "SMBCLK", "purpose": "Shared bus clock."},
        {"name": "SMBDAT", "purpose": "Shared bus data."},
        {"name": "SMBALERT#", "purpose": "Shared wired-OR interrupt."},
    ]
    f["packet_types_summary"] = [
        {"class": "SMBus protocol", "members": list(_SMBUS_PROTOCOLS),
         "count": len(_SMBUS_PROTOCOLS)},
        {"class": "PMBus data format", "members": list(_PMBUS_DATA_FORMATS),
         "count": len(_PMBUS_DATA_FORMATS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "bus_wires": 2,
        "optional_interrupt_lines": 1,
        "pmbus_control_pins": 1,
        "address_bits": 7,
        "data_byte_bits": 8,
        "word_bits": 16,
        "pec_width_bits": 8,
        "udid_bits": 128,
        "smbus_protocol_count": len(_SMBUS_PROTOCOLS),
        "pmbus_data_format_count": len(_PMBUS_DATA_FORMATS),
    })
    f["handshake_pairs"] = [
        {"name": "Address+RW / ACK", "from": "master", "to": "slave",
         "rule": "Slave ACKs the 9th clock if its address matches."},
        {"name": "Byte / ACK", "from": "transmitter", "to": "receiver",
         "rule": "Each byte ACK/NACK'd on the 9th clock; MSB-first."},
        {"name": "PEC / check", "from": "transmitter", "to": "receiver",
         "rule": "CRC-8 over the transaction; NACK on mismatch."},
        {"name": "SMBALERT# / Alert Response", "from": "device", "to": "host",
         "rule": "Device pulls SMBALERT# low; host reads the ARA; lowest "
         "address wins."},
        {"name": "ARP Get-UDID / Assign-Address", "from": "ARP master",
         "to": "device", "rule": "Enumerate by 128-bit UDID, then assign a "
         "7-bit address."},
    ]
    f["dependency_graph"] = {
        "common_rule": "All devices share SMBCLK/SMBDAT (open-drain "
        "wired-AND); a transaction is framed by START/STOP; bytes are "
        "MSB-first with per-byte ACK. SMBALERT# is an independent wired-OR "
        "interrupt. The PMBus command meaning depends on the active PAGE.",
        "data_dependency": "A valid transaction requires: (1) bus free (no "
        "active transaction), (2) addressed device present (ACK), (3) PEC "
        "match if PEC is enabled. PMBus reads/writes depend on the active "
        "PAGE; output-enable depends on OPERATION + CONTROL pin + "
        "ON_OFF_CONFIG.",
    }
    f["ordering_rules"] = {
        "bit_order_on_wire": "MSB-first per byte.",
        "byte_order": "PMBus multi-byte values are little-endian on the bus "
        "(low byte first) for Word transactions.",
        "transaction_atomicity": "One transaction at a time on the shared bus; "
        "group/zone commands defer action to a common STOP.",
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
        "Multi-drop 2-wire bus derived from I2C: all devices share SMBCLK and "
        "SMBDAT via open-drain wired-AND, with an optional shared SMBALERT# "
        "(wired-OR). At most one host manages the bus; PMBus power devices add "
        "a CONTROL pin.")
    f["supported_topologies"] = [
        {"name": "Single-host multi-device", "description": "One host plus "
         "multiple SMBus/PMBus slaves on the shared 2-wire bus."},
        {"name": "Multi-master", "description": "Multiple masters arbitrate "
         "for the bus (wired-AND arbitration, lowest address/data wins)."},
        {"name": "PMBus multi-rail / multi-device", "description": "PAGE "
         "selects rails within a device; group and Zone Read/Write commands "
         "coordinate many devices."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host", "description": "Special master that manages the bus, "
         "handles SMBALERT#/Host Notify, and runs ARP (at most one)."},
        {"role": "Master", "description": "Initiates transactions (drives "
         "SMBCLK, START/STOP, address)."},
        {"role": "Slave / Device", "description": "Responds to its 7-bit "
         "address; a PMBus power device is a slave with a CONTROL pin."},
    ]
    f["interconnect_role"] = (
        "SMBus is a shared control/management bus; PMBus is the power-"
        "management application protocol on top. Devices are addressed by "
        "7-bit address (optionally ARP-assigned); the host configures, "
        "controls, and monitors them, and is interrupted via SMBALERT#.")
    f["ordering_guarantees"] = {
        "single_transaction": "One transaction at a time on the shared bus.",
        "group_zone": "Group / Zone commands defer the action to a common "
        "STOP so multiple devices act together.",
        "alert_arbitration": "Lowest address wins the Alert Response; lowest "
        "UDID wins ARP enumeration.",
    }
    f["memory_vs_peripheral_regions"] = (
        "SMBus/PMBus is command/protocol-oriented, not memory-mapped. PMBus "
        "exposes a command-code space (0x00..0xFF) paged by PAGE; there is no "
        "linear memory address space on the bus.")
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
        "signaling": "open-drain wired-AND 2-wire (SMBCLK + SMBDAT), derived "
                     "from I2C",
        "address_bits": 7,
        "bus_speed_kHz": {"min": 10, "smbus_2_0_max": 100,
                          "smbus_3_x_max": 1000, "pmbus_typical_max": 400},
        "timeouts_ms": {"Ttimeout": "25 to 35", "Tlow_sext": "<= 25",
                        "Tlow_mext": "<= 10"},
        "pec": {"type": "CRC-8", "polynomial_hex": "0x07", "init": "0x00",
                "optional": True},
        "smbalert": "open-drain wired-OR shared interrupt; ARA = 0b0001100",
        "arp_udid_bits": 128,
        "pull_up": "external pull-ups to VDD on SMBCLK/SMBDAT/SMBALERT#; sized "
                   "vs bus capacitance and speed",
        "pmbus_control_pin": "discrete logic enable, polarity per "
                             "ON_OFF_CONFIG",
    }
    f["notes"] = (
        "SMBus fixes the I2C-derived electrical bus (open-drain, pull-ups, "
        "thresholds), the 10 kHz minimum clock, and the clock-low timeouts; "
        "PMBus adds the CONTROL-pin electrical behavior. Pull-up sizing, "
        "board capacitance, and AFE characterization are board/implementer "
        "concerns; the interoperability-critical constraints are the timeouts, "
        "thresholds, PEC, and the PMBus data-format declarations.")
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
        {"name": "PMBus STATUS registers", "purpose": "STATUS_BYTE/WORD + "
         "STATUS_VOUT/IOUT/TEMPERATURE expose fault/warning state."},
        {"name": "Telemetry read-back", "purpose": "READ_VIN/VOUT/IOUT/"
         "TEMPERATURE_1 for live monitoring."},
        {"name": "SMBALERT# / ARA", "purpose": "Out-of-band fault interrupt + "
         "host enumeration of alerting devices."},
        {"name": "PEC", "purpose": "CRC-8 integrity check per transaction."},
        {"name": "ARP / Get-UDID", "purpose": "Device enumeration and "
         "identification by 128-bit UDID."},
    ]
    f["internal_diagnostics_observability"] = [
        "Fault/warning STATUS bits (VOUT/IOUT/INPUT/TEMPERATURE/CML).",
        "Measured VIN/VOUT/IOUT/temperature.",
        "PEC error (NACK) and bus-timeout events.",
        "PMBus revision / manufacturer identity (PMBUS_REVISION / MFR_ID / "
        "MFR_MODEL).",
    ]
    f["notes"] = (
        "SMBus/PMBus DFT is entirely in-band over the two wires (STATUS + "
        "telemetry + PEC + SMBALERT# + ARP). There is no protocol-defined "
        "scan/JTAG layer; chip-level scan/BIST is the device implementer's "
        "concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (PMBus output control + bus power).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["managed_power_states"] = [
        {"state": "OFF", "description": "PMBus output disabled (OPERATION off "
         "or CONTROL pin de-asserted per ON_OFF_CONFIG)."},
        {"state": "ON / REGULATING", "description": "Output enabled and "
         "regulating to the commanded VOUT."},
        {"state": "MARGIN_HIGH / MARGIN_LOW", "description": "Output margined "
         "up/down per OPERATION for test."},
        {"state": "FAULT_SHUTDOWN", "description": "Output disabled by a fault "
         "response."},
    ]
    f["output_enable_logic"] = (
        "Output enable is the combination of the OPERATION command, the "
        "CONTROL pin, and ON_OFF_CONFIG (which selects the controlling "
        "source(s), polarity, and turn-off behavior).")
    f["bus_power"] = (
        "SMBCLK/SMBDAT/SMBALERT# are pulled up to VDD; the bus interface is "
        "low-power. PMBus targets manage the converter's own power output, "
        "not the bus rail.")
    f["notes"] = (
        "PMBus is fundamentally a power-management protocol: it controls "
        "converter output enable/voltage/margining via OPERATION + CONTROL + "
        "ON_OFF_CONFIG and reports power telemetry and faults. The SMBus bus "
        "itself is a low-power open-drain control bus.")
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
        "SMBus protocol coverage — all formats (Quick/Send/Receive/Write/Read "
        "Byte-Word/Process Call/Block/Host Notify).",
        "PEC — CRC-8 correctness, mismatch NACK, write and read phases.",
        "Bus timeouts — Ttimeout / Tlow:sext / Tlow:mext; hung-device "
        "recovery.",
        "SMBALERT# / ARA — assertion, arbitration, release.",
        "ARP — Prepare/Get-UDID/Assign-Address; UDID arbitration enumeration.",
        "Clock range and stretching — 10 kHz-1 MHz; Tlow extends within "
        "limits.",
        "PMBus commands — PAGE/OPERATION/ON_OFF_CONFIG/VOUT_MODE/VOUT_COMMAND/"
        "STATUS/READ_*.",
        "PMBus data formats — LINEAR11 / LINEAR16(ULINEAR16) / DIRECT / VID "
        "decode.",
        "CONTROL pin + ON_OFF_CONFIG enable logic; WRITE_PROTECT levels.",
        "Fault injection — STATUS bits, SMBALERT#, configured response.",
        "PAGE multi-rail; group command; Zone Read/Write (PMBus 1.3).",
    ]
    f["notes"] = (
        "SMBus/PMBus ship no formal testbench, but the specifications imply a "
        "verification plan spanning the SMBus transport (protocol set, PEC, "
        "timeouts, SMBALERT#/ARA, ARP) and the PMBus command language (commands, "
        "data formats, CONTROL/WRITE_PROTECT, PAGE/group/zone, faults).")
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
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "Packet Error Code (CRC-8) detects transaction bit errors.",
        "Per-byte ACK/NACK detects missing/unresponsive devices.",
        "Bus timeouts recover a hung bus instead of locking up.",
        "WRITE_PROTECT guards configuration commands against accidental "
        "writes.",
        "PMBus STATUS reporting + SMBALERT# surface faults promptly.",
    ]
    f["anti_tampering_features"] = [
        "WRITE_PROTECT can lock out configuration writes (a soft guard, not "
        "cryptographic).",
    ]
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "SMBus/PMBus traffic is plaintext on a board-local bus; physical "
        "access is the trust boundary.",
        "WRITE_PROTECT and host-side policy are the main mis-configuration "
        "guards; there is no in-protocol encryption or device authentication.",
    ]
    f["notes"] = (
        "SMBus/PMBus built-in protections are anti-corruption and "
        "mis-write guards only (PEC, ACK/NACK, timeouts, WRITE_PROTECT, STATUS/"
        "SMBALERT#). There is no cryptographic confidentiality, integrity, or "
        "authentication in the base protocol; the bus is trusted at the board "
        "level.")
    _write(p, d)
