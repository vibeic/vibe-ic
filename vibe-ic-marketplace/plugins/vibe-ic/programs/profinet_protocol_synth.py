"""PROFINET IO (IEC 61158 Type 10 / IEC 61784-2 CPF 3) protocol synth helper.

PROFINET is the open Industrial Ethernet standard for automation. It re-uses
standard IEEE 802.3 Fast/Gigabit Ethernet at the physical and MAC layers and
adds, on top, a real-time application protocol for cyclic process-data exchange
between distributed field devices and controllers, a device model, engineering
and addressing protocols, and real-time scheduling. Because a PROFINET spec
necessarily mentions the Ethernet MII/MDIO/PHY/802.3 base layer, the inline
Ethernet sub-detector in the runner fires FIRST and populates the base L-docs
with generic IEEE-802.3 MAC+PHY content. This module therefore runs AFTER the
Ethernet synth and FORCE-OVERWRITES (direct assignment, NOT setdefault) every
L1..L23 key the Ethernet synth touches, replacing the generic-Ethernet values
with the PROFINET-IO-canonical values (IO-Controller/IO-Device/IO-Supervisor +
GSDML + DCP + AR/CR + RT/IRT/NRT classes + IOPS/IOCS + APDU Cycle Counter +
CL-RPC + conformance classes + PTCP sync + MRP).

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL wire-level
signatures (the PROFINET device-role triple, the GSDML XML device description,
the DCP addressing protocol, the AR/CR connection model, the RT EtherType
0x8892, the cyclic provider/consumer IOPS/IOCS with the APDU Cycle Counter, and
the conformance classes) read from the L-doc CONTENT blob only. It NEVER reads
the input-document filename or the benchmark folder name. The detector requires
PROFINET-specific structure so it does NOT false-fire on a plain Ethernet
(MAC/MII/802.3 only, no IO-Device/AR/CR), an EtherCAT (datagram/FMMU/SyncManager
/distributed-clock/ESC) or a PROFIBUS (RS-485 token-passing / SD1-SD4 telegram /
keyword GSD-not-GSDML / DPV1) spec.

SIGNATURE (evaluated on the L1/L2/L3 content blob, never on a filename):

    is_profinet(blob) fires when the PROFINET role/engineering structure is
    present (IO-Device + IO-Controller, OR a PROFINET role + GSDML, OR PROFINET
    + DCP + AR/CR, OR the RT EtherType 0x8892 + IOPS/IOCS) and the EtherCAT and
    PROFIBUS sibling structures are NOT dominant.

Public entry: `apply_profinet_synth(generated_docs_dir, is_profinet,
profinet_ic_name)`; module-level detector `is_profinet(blob)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ----------------------------------------------------------------------
# Detector — CONTENT-ONLY, word-boundary tokens, EtherCAT + PROFIBUS MUTEX.
# ----------------------------------------------------------------------
def _wb(token: str, low: str) -> bool:
    """Word-boundary token presence on the lowercased blob."""
    return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
                     low) is not None


def is_profinet(blob: str) -> bool:
    """Content-only PROFINET IO detector with EtherCAT / PROFIBUS MUTEX.

    Fire on the PROFINET structural signature: the IO-Controller /
    IO-Device / IO-Supervisor device roles, the GSDML XML device
    description, the DCP discovery-and-configuration addressing protocol,
    the Application Relation (AR) + Communication Relation (CR) connection
    model, the RT/IRT/NRT performance classes, the RT EtherType 0x8892, and
    the cyclic provider/consumer IOPS/IOCS with the APDU Cycle Counter.

    Defer (do NOT fire) when the doc is EtherCAT-primary (the EtherCAT
    datagram / FMMU / SyncManager / distributed-clock / ESC structure with
    NO PROFINET roles/AR/CR/GSDML/DCP) or PROFIBUS-primary (RS-485
    token-passing / SD1-SD4 telegram / DPV1 / keyword-GSD-not-GSDML with NO
    PROFINET Ethernet roles). Reads ONLY the spec text `blob` — never a
    filename or a benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    name_token = "profinet" in low

    # PROFINET-specific structural tokens (word-boundary where they could be
    # ambiguous; most are unique enough that substring is safe).
    io_controller = "io-controller" in low or "io controller" in low
    io_device = "io-device" in low or "io device" in low
    io_supervisor = "io-supervisor" in low or "io supervisor" in low
    gsdml = "gsdml" in low
    dcp = (_wb("dcp", low)
           or "discovery and configuration protocol" in low)
    application_relation = (
        "application relation" in low
        or (_wb("ar", low) and ("io-cr" in low or "io cr" in low
                                or "alarm-cr" in low or "record-data-cr" in low
                                or "record data cr" in low)))
    comm_relation = (
        "io-cr" in low or "io cr" in low or "alarm-cr" in low
        or "record-data-cr" in low or "record data cr" in low
        or "communication relation" in low)
    rt_ethertype = "0x8892" in low
    provider_consumer = (
        ("iops" in low and "iocs" in low)
        or ("provider status" in low and "consumer status" in low))
    cycle_counter = "cycle counter" in low
    rt_classes = (("irt" in low and "isochronous real-time" in low)
                  or ("rt" in low and "real-time" in low and "irt" in low))
    conformance_class = (
        "conformance class" in low
        or _wb("cc-a", low) or _wb("cc-b", low) or _wb("cc-c", low))
    ptcp = ("ptcp" in low
            or "precision transparent clock protocol" in low)
    clrpc = ("cl-rpc" in low or "dce-rpc" in low or "dce/rpc" in low
             or "connectionless rpc" in low)

    # PROFINET role/engineering structure: the device-role + engineering
    # signature that is unique to PROFINET IO and absent from plain
    # Ethernet / EtherCAT / PROFIBUS.
    device_roles = (io_controller and io_device) or (io_device and io_supervisor)
    engineering = gsdml or dcp
    connection_model = application_relation or comm_relation
    cyclic_pnio = (provider_consumer and cycle_counter) or rt_ethertype

    profinet_structure = (
        (device_roles and (engineering or connection_model or cyclic_pnio))
        or (device_roles and conformance_class)
        or (engineering and connection_model and cyclic_pnio)
        or (name_token and gsdml and dcp)
        or (name_token and connection_model and provider_consumer)
        or (name_token and conformance_class and (ptcp or clrpc)))

    # --- Sibling MUTEX: EtherCAT-primary ---
    # EtherCAT keys on the on-the-fly EtherCAT datagram + FMMU + SyncManager +
    # distributed clock + ESC (EtherCAT Slave Controller) structure. If that
    # dominates and the PROFINET role/engineering structure is absent, defer.
    ethercat_structure = (
        "ethercat" in low
        and (("fmmu" in low)
             or ("syncmanager" in low or "sync manager" in low)
             or ("distributed clock" in low)
             or (_wb("esc", low) and "datagram" in low)
             or ("0x88a4" in low)
             or ("subdevice" in low and "datagram" in low)))
    ethercat_primary = (
        ethercat_structure
        and not (device_roles or gsdml or dcp or application_relation
                 or rt_ethertype or (provider_consumer and cycle_counter)
                 or name_token))
    if ethercat_primary:
        return False

    # --- Sibling MUTEX: PROFIBUS-primary ---
    # PROFIBUS keys on the RS-485 token-passing serial fieldbus: SD1-SD4
    # telegram start delimiters, DPV1 acyclic services, the master/slave DP
    # roles, the keyword-based GSD (NOT GSDML XML), and token passing. If that
    # dominates and the PROFINET Ethernet role/engineering structure is absent,
    # defer (a sibling PROFIBUS agent owns that class).
    profibus_structure = (
        "profibus" in low
        and (("token passing" in low or "token-passing" in low)
             or ("dpv1" in low or "dp-v1" in low)
             or (_wb("sd1", low) and _wb("sd4", low))
             or ("dp master" in low and "dp slave" in low)
             or ("rs-485" in low and ("gsd" in low and "gsdml" not in low))))
    profibus_primary = (
        profibus_structure
        and not (device_roles or gsdml or dcp or application_relation
                 or rt_ethertype or (provider_consumer and cycle_counter)
                 or io_supervisor))
    if profibus_primary:
        return False

    # PROFIBUS-dominant doc: a PROFIBUS spec's migration section names PROFINET
    # roles (IO-Controller/IO-Device/GSDML), so the prior profibus_primary guard
    # (which defers only when PROFINET structure is ABSENT) is bypassed. But
    # RS-485 token-passing + the SD1..SD4 telegram delimiters are PROFIBUS-
    # EXCLUSIVE — a real PROFINET (Industrial Ethernet) doc never carries them.
    # Defer when that PROFIBUS-exclusive signature dominates and the doc lacks
    # the PROFINET-exclusive cyclic markers (RT EtherType / IOPS+IOCS / CC).
    profibus_dominant = (
        "profibus" in low
        and ("token passing" in low or "token-passing" in low)
        and (_wb("sd1", low) and _wb("sd4", low))
        and not (rt_ethertype
                 or (provider_consumer and cycle_counter)
                 or conformance_class)
    )
    if profibus_dominant:
        return False

    return bool(profinet_structure)


# ----------------------------------------------------------------------
# Synth plumbing (mirrors ucie/sas).
# ----------------------------------------------------------------------
def _ensure_dict(d: dict, key: str) -> dict:
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

# Canonical PROFINET IO facts (IEC 61158 Type 10 / IEC 61784-2 CPF 3).
_RT_ETHERTYPE = "0x8892"
_SEND_CLOCK_BASE_US = 31.25
_PERF_CLASSES = ["NRT", "RT", "IRT"]
_CONFORMANCE_CLASSES = ["CC-A", "CC-B", "CC-C"]
_DEVICE_ROLES = ["IO-Controller", "IO-Device", "IO-Supervisor"]


def apply_profinet_synth(generated_docs_dir: Path, is_profinet_flag: bool,
                         profinet_ic_name: Optional[str]) -> None:
    """Apply PROFINET IO synth when the PROFINET signature matched.

    Runs AFTER the Ethernet synth and FORCE-OVERWRITES (direct assignment)
    every L1..L23 key the Ethernet synth populated with the PROFINET-IO
    canonical value.
    """
    if not is_profinet_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if profinet_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = profinet_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = profinet_ic_name
                d["ic_name"] = profinet_ic_name
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
# L1 — FORCE-OVERWRITE the generic-Ethernet datasheet with the PROFINET IO
# Industrial-Ethernet datasheet.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "PROFINET IO — Industrial Ethernet Communication Specification "
        "(IEC 61158 Type 10 / IEC 61784-2 CPF 3)")
    d["version"] = "IEC 61158 / IEC 61784-2 (PI PROFINET IO)"
    d["revised_date"] = "IEC 61784-2 / IEC 61158-x-10"
    d["manufacturer"] = "PI (PROFIBUS & PROFINET International)"
    d["copyright"] = "© PI (PROFIBUS & PROFINET International)"
    d["abstract"] = (
        "PROFINET is the open Industrial Ethernet standard for automation, "
        "standardized in IEC 61158 (Type 10) and IEC 61784-2 (Communication "
        "Profile Family 3) and maintained by PI. It runs on standard 100 "
        "Mbit/s / 1 Gbit/s switched IEEE 802.3 Ethernet and standard Ethernet "
        "hardware, adding a real-time application protocol for cyclic "
        "process-data exchange between distributed field devices and "
        "controllers. PROFINET IO defines three performance classes — NRT "
        "(TCP/IP, UDP for configuration/diagnosis), RT (prioritized Layer-2 "
        "real-time on EtherType 0x8892 with VLAN PCP priority), and IRT "
        "(hardware-scheduled isochronous real-time with bandwidth reservation "
        "and a synchronized clock domain). Devices take one of three roles: "
        "IO-Controller (PLC), IO-Device (field device), and IO-Supervisor "
        "(engineering). Each IO-Device is described by a GSDML XML file; "
        "stations are addressed by name via the DCP (Discovery and "
        "Configuration Protocol); the IO-Controller establishes an Application "
        "Relation (AR) containing Communication Relations (IO-CR cyclic, "
        "Record-Data-CR acyclic, Alarm-CR). Cyclic PNIO data carries "
        "per-object provider/consumer status (IOPS/IOCS) plus an APDU Cycle "
        "Counter and Data Status; acyclic record data uses CL-RPC (DCE/RPC). "
        "Conformance Classes CC-A/CC-B/CC-C bundle features (CC-C = IRT); time "
        "synchronization uses PTCP and ring redundancy uses MRP.")
    d["keywords"] = [
        "PROFINET", "PROFINET IO", "Industrial Ethernet", "IEC 61158",
        "IEC 61784-2", "IO-Controller", "IO-Device", "IO-Supervisor", "GSDML",
        "DCP", "Application Relation", "AR", "IO-CR", "Record-Data-CR",
        "Alarm-CR", "RT", "IRT", "NRT", "0x8892", "IOPS", "IOCS",
        "Cycle Counter", "APDU Status", "CL-RPC", "DCE-RPC",
        "Conformance Class", "PTCP", "MRP", "LLDP", "slot", "subslot",
        "send clock", "provider/consumer",
    ]
    d["external_pins"] = [
        "Standard Ethernet ports (RJ45 / M12, 100BASE-TX or 1000BASE-T), full "
        "duplex — typically 2 ports per device for line/ring topology",
        "MDI/MDI-X twisted-pair TX/RX pairs per port (standard IEEE 802.3 PHY)",
        "MII/RMII/GMII between the PROFINET ASIC/MAC and the Ethernet PHY "
        "(implementation interface, not the wire)",
        "Link / Activity LEDs and a DCP Signal (flashing) LED per device for "
        "physical station location",
        "Power supply and ground (device-class dependent)",
    ]
    d.pop("external_pin_count_mii", None)
    d.pop("external_pin_count_gmii", None)
    d.pop("external_pin_count_rgmii", None)
    d.pop("supported_speeds_Mbps", None)
    d["supported_speeds_Mbps"] = [100, 1000]
    d["performance_classes"] = list(_PERF_CLASSES)
    d["conformance_classes"] = list(_CONFORMANCE_CLASSES)
    d["device_roles"] = list(_DEVICE_ROLES)
    d["rt_ethertype"] = _RT_ETHERTYPE
    d["modes_of_operation"] = [
        {"name": "NRT (Non-Real-Time)",
         "transport": "TCP/IP and UDP/IP (EtherType 0x0800)",
         "use": "Parameterization, configuration, diagnosis, acyclic services "
                "(CL-RPC); not time critical."},
        {"name": "RT (Real-Time)",
         "transport": "prioritized Layer-2 Ethernet, EtherType 0x8892, VLAN "
                      "PCP priority 6",
         "use": "Cyclic process data bypassing the TCP/IP stack; "
                "deterministic at the application level (RT_CLASS_1/2)."},
        {"name": "IRT (Isochronous Real-Time)",
         "transport": "hardware-scheduled, bandwidth-reserved Layer-2 on "
                      "EtherType 0x8892, sync domain",
         "use": "Jitter-free (< 1 us) clock-synchronized motion control "
                "(RT_CLASS_3); requires CC-C IRT hardware and PTCP sync."},
    ]
    d["key_features"] = [
        "Open Industrial Ethernet on standard switched 100 Mbit/s / 1 Gbit/s "
        "IEEE 802.3 (standard frames, cables, connectors, PHYs, switches).",
        "Three performance classes: NRT (TCP/IP, UDP), RT (Layer-2 EtherType "
        "0x8892, VLAN PCP), IRT (hardware-scheduled isochronous).",
        "Three device roles: IO-Controller (PLC), IO-Device (field device), "
        "IO-Supervisor (engineering / diagnostics).",
        "GSDML XML device description (VendorID/DeviceID, modules/submodules, "
        "I/O sizes, parameters, features) for engineering integration.",
        "DCP (Discovery and Configuration Protocol) for name-based station "
        "identity and IP assignment; LLDP for topology/neighbor detection.",
        "Application Relation (AR) groups Communication Relations: IO-CR "
        "(cyclic), Record-Data-CR (acyclic), Alarm-CR (alarms).",
        "Slot/subslot device model with the Device Access Point at slot 0 and "
        "Module/Submodule Ident Numbers matched to the expected configuration.",
        "Cyclic PNIO provider/consumer data with per-object IOPS (provider "
        "status) and IOCS (consumer status) for partial-validity signalling.",
        "APDU Status appended to each cyclic frame: 2-byte Cycle Counter, Data "
        "Status (DataValid / Provider State / Station Problem Indicator), "
        "Transfer Status.",
        "Acyclic record access (Read/Write/Control, I&M records) via CL-RPC "
        "(connectionless DCE/RPC over UDP).",
        "Send clock = 31.25 us base x send-clock factor (e.g. x32 = 1 ms cycle) "
        "with per-CR reduction ratio, phase, and watchdog (data-hold) factor.",
        "Conformance Classes CC-A / CC-B / CC-C (CC-C adds IRT) for "
        "interoperable certification.",
        "PTCP (Precision Transparent Clock Protocol) time synchronization in a "
        "sync domain; MRP (Media Redundancy Protocol) ring redundancy with "
        "<= 200 ms recovery.",
    ]
    d["topology_summary"] = (
        "Switched Ethernet line, star, tree, or ring (MRP). PROFINET devices "
        "commonly have an integrated 2-port switch so they can be daisy-chained "
        "into a line; a ring with one Media Redundancy Manager (MRM) provides "
        "redundancy. IRT requires a fixed, planned topology (LLDP + offline "
        "scheduling).")
    d["package_summary"] = (
        "PROFINET is a communication standard, not a chip package. A PROFINET "
        "IO-Device is typically built from a standard Ethernet PHY plus a "
        "PROFINET MAC/communication ASIC or FPGA (with the RT/IRT engine, DCP, "
        "AR/CR handling, and — for CC-C — the IRT scheduler and PTCP). "
        "Mechanical/connector form factors (RJ45, M12) follow the PI "
        "guidelines.")
    d["use_cases"] = [
        "Distributed field I/O for factory and process automation (remote I/O, "
        "valve terminals, sensor/actuator stations)",
        "Drive control and synchronized multi-axis motion (IRT / CC-C)",
        "Connecting a PLC (IO-Controller) to many field devices over one "
        "Ethernet network",
        "Engineering / commissioning / diagnostics from an IO-Supervisor",
        "Redundant ring networks (MRP) for high-availability cells",
        "Integration with higher-level IT (NRT TCP/IP coexisting with cyclic "
        "RT on the same wire)",
    ]
    d["revision_history"] = [
        {"version": "PROFINET IO (IEC 61158/61784-2)",
         "date": "PI specification",
         "description": "PROFINET IO: device roles (IO-Controller/IO-Device/"
                        "IO-Supervisor), GSDML, DCP, AR/CR, RT/IRT/NRT "
                        "classes, IOPS/IOCS cyclic data, CL-RPC acyclic, "
                        "conformance classes CC-A/CC-B/CC-C, PTCP, MRP. "
                        "(PROFINET CBA, the older component-based-automation "
                        "variant, is deprecated.)"},
    ]
    d["overview"] = (
        "PROFINET is the open Industrial Ethernet standard (IEC 61158 Type 10, "
        "IEC 61784-2 CPF 3, maintained by PI) for cyclic and acyclic data "
        "exchange between automation controllers and distributed field "
        "devices. It re-uses standard switched 100 Mbit/s / 1 Gbit/s IEEE "
        "802.3 Ethernet — standard frames, MAC addresses, PHYs, and switches — "
        "and layers on top a real-time application protocol. Three performance "
        "classes coexist: NRT (TCP/IP and UDP for configuration and "
        "diagnosis), RT (cyclic process data in Layer-2 frames with EtherType "
        "0x8892, prioritized by the VLAN PCP field, bypassing the IP stack), "
        "and IRT (hardware-scheduled isochronous real-time with reserved "
        "bandwidth and a synchronized clock domain for motion control). "
        "Devices are IO-Controllers (PLCs), IO-Devices (field devices), or "
        "IO-Supervisors (engineering). Each IO-Device ships a GSDML XML "
        "description; stations are addressed by name through DCP and located by "
        "LLDP topology. The IO-Controller establishes an Application Relation "
        "(AR) carrying an IO-CR (cyclic provider/consumer data with per-object "
        "IOPS/IOCS and an APDU Cycle Counter / Data Status), a Record-Data-CR "
        "(acyclic CL-RPC Read/Write records, including I&M), and an Alarm-CR. "
        "Conformance Classes CC-A/CC-B/CC-C define interoperable feature sets "
        "(CC-C = IRT); PTCP synchronizes time and MRP provides ring "
        "redundancy. PROFINET is the Ethernet successor to the RS-485 PROFIBUS "
        "fieldbus, replacing token-passing/SD1-SD4/GSD/DPV1 with switched "
        "Ethernet, GSDML, names, and the provider/consumer cyclic model.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FORCE-OVERWRITE the generic-Ethernet protocol_overview + FRS with
# the PROFINET IO real-time application model.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Industrial Ethernet application protocol on standard switched IEEE "
        "802.3 (100 Mbit/s / 1 Gbit/s). Cyclic provider/consumer process data "
        "(PNIO) plus acyclic record services, with three performance classes "
        "NRT / RT / IRT and a device model of IO-Controller / IO-Device / "
        "IO-Supervisor.")
    po["duplex"] = (
        "full-duplex switched Ethernet; cyclic data uses a provider/consumer "
        "model (the IO-Device provides inputs and consumes outputs, the "
        "IO-Controller the reverse), not request/response.")
    po["base_layer"] = (
        "Standard IEEE 802.3 Fast/Gigabit Ethernet — standard frames "
        "(preamble, SFD, MAC addresses, EtherType, payload, FCS/CRC-32), "
        "standard switching; PROFINET is NOT a separate PHY/MAC.")
    po["performance_classes"] = [
        {"name": "NRT", "transport": "TCP/IP, UDP/IP (EtherType 0x0800)",
         "use": "configuration, parameterization, diagnosis, acyclic"},
        {"name": "RT", "transport": "Layer-2 Ethernet, EtherType 0x8892, "
         "VLAN PCP priority 6", "use": "cyclic process data, RT_CLASS_1/2"},
        {"name": "IRT", "transport": "hardware-scheduled Layer-2 (sync "
         "domain), EtherType 0x8892", "use": "isochronous motion control, "
         "RT_CLASS_3"},
    ]
    po["rt_ethertype"] = _RT_ETHERTYPE
    po["vlan_priority"] = "IEEE 802.1Q VLAN tag; RT cyclic uses PCP = 6"
    po["device_roles"] = list(_DEVICE_ROLES)
    po["device_model"] = (
        "Slot / Subslot structure; Device Access Point (DAP) = slot 0; "
        "Module Ident Number / Submodule Ident Number matched to the expected "
        "engineering configuration.")
    po["device_description"] = "GSDML (GSDML-DeviceProfile XML)"
    po["addressing"] = (
        "Name-based: NameOfStation assigned via DCP (Discovery and "
        "Configuration Protocol); IP (address/mask/gateway) also via DCP "
        "(DHCP optional); LLDP for topology/neighbor detection.")
    po["connection_model"] = (
        "Application Relation (AR) established via CL-RPC Connect; carries "
        "IO-CR (cyclic), Record-Data-CR (acyclic Read/Write), Alarm-CR.")
    po["cyclic_data"] = (
        "PNIO: each submodule's IO data object travels with a 1-byte IOPS "
        "(provider status, Good/Bad) and the reverse frame carries IOCS "
        "(consumer status); the frame appends an APDU Status (2-byte Cycle "
        "Counter, Data Status, Transfer Status).")
    po["acyclic_data"] = (
        "CL-RPC (connectionless DCE/RPC over UDP): Connect/Release, Read/Write "
        "records (parameters, diagnosis, I&M0..I&M4), Control "
        "(ParameterEnd/ApplicationReady).")
    po["conformance_classes"] = list(_CONFORMANCE_CLASSES)
    po["time_sync"] = "PTCP (Precision Transparent Clock Protocol), sync domain"
    po["media_redundancy"] = "MRP (Media Redundancy Protocol, IEC 62439-2)"
    po["send_clock_base_us"] = _SEND_CLOCK_BASE_US
    # Remove the generic-Ethernet-only overview keys if present.
    for stale in ("csma_cd", "half_duplex", "autonegotiation_only",
                  "mii_interface_summary"):
        po.pop(stale, None)
    d["functional_requirements"] = [
        {"id": "FR-BASE-01", "text": "PROFINET runs on standard switched IEEE "
         "802.3 Fast/Gigabit Ethernet using standard frames and hardware; it "
         "adds an application protocol and does NOT define a new PHY/MAC."},
        {"id": "FR-CLASS-02", "text": "Three performance classes coexist: NRT "
         "(TCP/IP, UDP), RT (Layer-2 EtherType 0x8892, VLAN PCP priority), and "
         "IRT (hardware-scheduled isochronous real-time in a sync domain)."},
        {"id": "FR-ROLE-03", "text": "Devices take one of three roles: "
         "IO-Controller (PLC), IO-Device (field device), IO-Supervisor "
         "(engineering/diagnostics)."},
        {"id": "FR-GSDML-04", "text": "Each IO-Device is described by a GSDML "
         "XML file (VendorID/DeviceID, modules/submodules, I/O sizes, "
         "parameters, supported features) imported by the engineering tool."},
        {"id": "FR-DCP-05", "text": "Stations are addressed by NameOfStation "
         "via DCP (Identify/Get/Set/Hello); DCP also assigns the IP "
         "configuration (DHCP optional); LLDP provides topology/neighbor "
         "detection."},
        {"id": "FR-AR-06", "text": "The IO-Controller establishes an "
         "Application Relation (AR) to an IO-Device via CL-RPC Connect, "
         "carrying the expected configuration."},
        {"id": "FR-CR-07", "text": "An AR contains Communication Relations: "
         "one or more IO-CR (cyclic), a Record-Data-CR (acyclic Read/Write), "
         "and an Alarm-CR (alarms)."},
        {"id": "FR-SLOT-08", "text": "An IO-Device is organized in "
         "slots/subslots; the Device Access Point is slot 0; Module/Submodule "
         "Ident Numbers must match the expected configuration or diagnosis is "
         "raised."},
        {"id": "FR-PNIO-09", "text": "Cyclic IO-CR data carries each data "
         "object with its provider status IOPS (Good/Bad); the reverse frame "
         "carries the consumer status IOCS; partial validity is signalled "
         "per submodule."},
        {"id": "FR-APDU-10", "text": "Each cyclic frame appends an APDU Status: "
         "a 2-byte Cycle Counter (31.25 us ticks), a Data Status byte "
         "(DataValid, Provider State, Station Problem Indicator, "
         "Primary/Backup), and a Transfer Status byte."},
        {"id": "FR-TIMING-11", "text": "The cyclic timing is send_clock = "
         "31.25 us x send-clock-factor; each CR has a reduction ratio, phase, "
         "and watchdog (data-hold = reduction x send_clock x watchdog_factor); "
         "a watchdog miss flags the data invalid."},
        {"id": "FR-ACYC-12", "text": "Acyclic services use CL-RPC (DCE/RPC over "
         "UDP): Connect/Release, Read/Write records by (API, Slot, Subslot, "
         "Index), Control (ParameterEnd/ApplicationReady), and the I&M0..I&M4 "
         "identification records."},
        {"id": "FR-CC-13", "text": "Conformance Classes define interoperable "
         "feature sets: CC-A (RT), CC-B (CC-A + topology/diagnosis via "
         "SNMP/LLDP + MRP), CC-C (CC-B + IRT hardware)."},
        {"id": "FR-PTCP-14", "text": "IRT devices synchronize their clocks via "
         "PTCP within a sync domain (Sync Master + Sync Slaves; "
         "delay-request/response; sub-microsecond accuracy)."},
        {"id": "FR-MRP-15", "text": "MRP provides Ethernet ring redundancy with "
         "one Media Redundancy Manager blocking a port and <= 200 ms recovery "
         "(part of CC-B and above)."},
    ]
    d["error_response_conditions"] = [
        "Watchdog (data-hold) timeout — no valid cyclic frame within "
        "reduction x send_clock x watchdog_factor; consumer flags IOPS BAD / "
        "data invalid and the AR may abort.",
        "Configuration mismatch — plugged Module/Submodule Ident Number does "
        "not match the expected configuration; Connect or diagnosis flags it.",
        "AR abort — CL-RPC abort or fatal diagnosis tears down the AR; cyclic "
        "exchange stops and the device re-addresses/re-connects.",
        "DCP name/IP not set — device has no NameOfStation; the IO-Controller "
        "cannot resolve and connect it.",
        "Alarm — diagnosis/process/plug-pull alarms on the Alarm-CR with "
        "acknowledge; Station Problem Indicator set in the cyclic Data Status.",
        "Ethernet FCS/CRC error — the standard Ethernet frame check discards "
        "corrupted frames (treated as a missed cyclic frame by the consumer).",
    ]
    d["compliance_requirements"] = [
        "Standard IEEE 802.3 switched Ethernet base (100 Mbit/s / 1 Gbit/s, "
        "full duplex).",
        "DCP name/IP assignment and (CC-B+) LLDP topology / SNMP diagnosis.",
        "GSDML device description matching the real device.",
        "AR establishment via CL-RPC with IO-CR / Record-Data-CR / Alarm-CR.",
        "Cyclic provider/consumer data with per-object IOPS/IOCS and APDU "
        "Cycle Counter / Data Status.",
        "RT cyclic frames on EtherType 0x8892 with VLAN PCP prioritization.",
        "Declared conformance class behavior (CC-A / CC-B / CC-C); CC-C adds "
        "IRT scheduling and PTCP sync.",
        "MRP ring redundancy where claimed (CC-B+).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — FORCE-OVERWRITE the generic-Ethernet MAC/MDIO framing with the
# PROFINET RT-frame / channel / AR-CR model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Industrial Ethernet application protocol. Cyclic process data (PNIO) "
        "is sent in standard Ethernet frames with EtherType 0x8892 (RT/IRT), "
        "carrying per-submodule IO data objects with provider/consumer status "
        "(IOPS/IOCS) and an appended APDU Status (Cycle Counter / Data Status / "
        "Transfer Status). Acyclic services (Connect, Read/Write records, "
        "Control) use CL-RPC (DCE/RPC over UDP). Stations are addressed by name "
        "via DCP; the connection is an Application Relation (AR) carrying "
        "IO-CR / Record-Data-CR / Alarm-CR.")
    d["channels"] = [
        {"name": "IO-CR (cyclic, RT/IRT)",
         "direction": "Input-CR (IO-Device -> IO-Controller) and Output-CR "
                      "(IO-Controller -> IO-Device)",
         "description": "Cyclic process-data frame on EtherType 0x8892: IO data "
         "objects each followed by their 1-byte IOPS (provider status), the "
         "consumer-status IOCS for consumed objects, then the APDU Status. Sent "
         "every send_clock x reduction_ratio."},
        {"name": "Record-Data-CR (acyclic)",
         "direction": "bidirectional (controller/supervisor <-> device)",
         "description": "Acyclic Read/Write of records (parameters, diagnosis, "
         "I&M) addressed by (API, Slot, Subslot, Index) via CL-RPC."},
        {"name": "Alarm-CR (acyclic, real-time)",
         "direction": "IO-Device -> IO-Controller (with acknowledge)",
         "description": "Diagnosis / process / plug-pull / status alarms on "
         "EtherType 0x8892 alarm FrameIDs; low- and high-priority queues."},
        {"name": "NRT (TCP/IP, UDP)",
         "direction": "bidirectional",
         "description": "Standard IP traffic (EtherType 0x0800) for "
         "configuration, CL-RPC transport, diagnosis; not time critical."},
        {"name": "DCP / LLDP / PTCP control",
         "direction": "multicast / per-port",
         "description": "DCP (name/IP) and PTCP (time sync) on EtherType "
         "0x8892 control FrameIDs; LLDP topology on EtherType 0x88CC."},
    ]
    d["rt_frame_format"] = {
        "ethertype": _RT_ETHERTYPE,
        "fields": [
            "Standard Ethernet header (dest MAC, src MAC); optional 802.1Q "
            "VLAN tag (0x8100) with PCP priority (RT cyclic = 6)",
            "EtherType 0x8892 (PN-RT)",
            "FrameID (2 bytes) — identifies the frame class/connection",
            "Data — cyclic IO data objects + IOPS, consumer IOCS",
            "APDU Status — Cycle Counter (2B), Data Status (1B), Transfer "
            "Status (1B)",
            "Ethernet FCS (CRC-32)",
        ],
        "frameid_ranges": {
            "0x0100-0x0FFF": "IRT cyclic (high performance)",
            "0x8000-0xBFFF": "RT cyclic class 1/2",
            "0xFC00-0xFCFF": "DCP",
            "0xFE00-0xFEFF": "Acyclic / Alarm (low/high)",
            "0xFF00-0xFF8F": "PTCP (Sync / FollowUp / Delay)",
        },
        "payload_bytes": "46..1500 (standard Ethernet MTU; no jumbo frames)",
    }
    d["apdu_status_fields"] = [
        {"field": "Cycle Counter", "bytes": 2,
         "meaning": "increments every 31.25 us send-clock tick; detects "
                    "missed/duplicated/late frames."},
        {"field": "Data Status", "bytes": 1,
         "meaning": "State (Primary/Backup), Redundancy, DataValid (overall "
                    "provider valid), Provider State (Run/Stop), Station "
                    "Problem Indicator."},
        {"field": "Transfer Status", "bytes": 1,
         "meaning": "transfer-level status (0 = ok in the normal case)."},
    ]
    d["iops_iocs"] = {
        "IOPS": "IO Provider Status, 1 byte per data object — Good/Bad "
                "validity of the produced item.",
        "IOCS": "IO Consumer Status, 1 byte per data object — feedback that "
                "the consumer accepted the item.",
        "note": "Per-object status enables partial-validity signalling without "
                "invalidating the whole frame.",
    }
    d["addressing"] = {
        "primary_identity": "NameOfStation (assigned via DCP)",
        "ip_assignment": "DCP-Set (IP / mask / gateway); DHCP optional",
        "record_addressing": "(API, Slot, Subslot, Index, Length) for "
                             "acyclic Read/Write",
        "note": "PROFINET addresses devices by NAME, not by a fixed bus "
                "address; the name is the key for AR establishment.",
    }
    d["ar_cr_model"] = {
        "AR": "Application Relation — established once via CL-RPC Connect; "
              "groups all CRs.",
        "CRs": ["IO-CR (cyclic provider/consumer)", "Record-Data-CR (acyclic)",
                "Alarm-CR (alarms)"],
        "ar_types": ["IO-AR", "Supervisor-AR / DeviceAccess-AR", "Implicit-AR"],
    }
    d["acyclic_services"] = [
        "Connect / Release (AR establishment / teardown)",
        "Read / Write (record data by API/Slot/Subslot/Index, incl. I&M0..I&M4)",
        "Control (ParameterEnd, ApplicationReady, DControl/CControl)",
    ]
    d["cyclic_timing"] = {
        "send_clock_base_us": _SEND_CLOCK_BASE_US,
        "send_clock_factor_example": "32 -> 1 ms cycle (31.25 us x 32)",
        "send_clock_factor_range": "1..128 (31.25 us .. 4 ms)",
        "reduction_ratio": "CR transmitted every Nth send-clock (load "
                           "spreading via phase/offset).",
        "watchdog": "data-hold = reduction_ratio x send_clock x "
                    "watchdog_factor; miss -> data invalid.",
    }
    d["valid_ready_handshake_rules"] = [
        "Cyclic data uses a provider/consumer model: the provider sends every "
        "send_clock x reduction_ratio; the consumer validates via IOPS, Cycle "
        "Counter, Data Status, and the watchdog.",
        "AR establishment is an acyclic Connect/Connect-response handshake "
        "(CL-RPC) carrying the expected configuration.",
        "Alarms are acknowledged on the Alarm-CR.",
        "Parameterization is sequenced by Write records + ParameterEnd, then "
        "the device signals ApplicationReady before cyclic data starts.",
    ]
    # Force-overwrite the generic-Ethernet booleans / leftover keys.
    d["burst_based"] = False
    d["byte_oriented"] = False
    d.pop("mac_frame_format", None)
    d.pop("mdio_clause22_frame", None)
    d.pop("mdio_clause45_frame", None)
    d.pop("transaction_classes_split", None)
    d["frame_format"] = {
        "base": "Standard IEEE 802.3 Ethernet frame (preamble, SFD, dest MAC, "
                "src MAC, optional 802.1Q VLAN, EtherType, payload, FCS).",
        "rt_payload": "EtherType 0x8892: FrameID + cyclic IO data + IOPS/IOCS "
                      "+ APDU Status (Cycle Counter / Data Status / Transfer "
                      "Status).",
        "nrt_payload": "EtherType 0x0800: IP/UDP carrying CL-RPC for acyclic "
                       "services.",
        "note": "PROFINET uses the standard Ethernet FCS (CRC-32) for "
                "transmission integrity; no separate protocol CRC on the RT "
                "frame.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register/object model: PROFINET record/index model + DCP/AR objects.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "PROFINET does not expose a flat hardware register map on the wire; "
        "its addressable state is the record/index model accessed acyclically "
        "by (API, Slot, Subslot, Index) via CL-RPC, plus the DCP-managed "
        "station identity and the AR/CR parameters negotiated at Connect. The "
        "groups below describe these logical object groups.")
    for stale in ("mdio_register_map", "phy_registers_clause22",
                  "mmd_registers_clause45", "mac_control_registers"):
        d.pop(stale, None)
    d["register_groups"] = [
        {"group": "Station Identity (DCP-managed)", "fields": [
            "NameOfStation", "IP address / subnet mask / gateway",
            "MAC address", "VendorID / DeviceID", "DCP Signal (flash) state"]},
        {"group": "AR / CR Parameters (Connect-negotiated)", "fields": [
            "AR UUID / AR type", "IO-CR FrameID / data layout / send-clock "
            "factor / reduction ratio / phase", "Watchdog (data-hold) factor",
            "Record-Data-CR parameters", "Alarm-CR parameters"]},
        {"group": "Slot / Subslot Configuration", "fields": [
            "Module Ident Number (per slot)",
            "Submodule Ident Number (per subslot)",
            "Device Access Point = slot 0 (interface 0x8000, ports "
            "0x8001/0x8002)", "Expected vs real configuration"]},
        {"group": "I&M Records (acyclic, by Index)", "fields": [
            "I&M0 (VendorID, OrderID, SerialNumber, HW/SW revision)",
            "I&M1 (function tag, location tag)", "I&M2 (installation date)",
            "I&M3 (descriptor)", "I&M4 (signature)"]},
        {"group": "Diagnosis Records", "fields": [
            "ChannelErrorType", "ChannelNumber", "Severity "
            "(maintenance-required / maintenance-demanded / fault)",
            "Diagnosis source (channel/submodule/module)"]},
    ]
    d["record_addressing"] = {
        "key": "(API, Slot, Subslot, Index, Length)",
        "transport": "CL-RPC Read/Write (DCE/RPC over UDP)",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/PHY: standard Ethernet PHY; PROFINET adds no new analog spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "PROFINET uses the STANDARD IEEE 802.3 Ethernet physical layer "
        "unchanged: 100BASE-TX (MLT-3, 125 MBd) or 1000BASE-T (PAM-5) over "
        "twisted pair, full duplex, with a standard Ethernet PHY and "
        "transformer/magnetics. PROFINET does not define a new analog front "
        "end; its real-time behavior is achieved at the MAC/application layer "
        "(prioritized Layer-2 for RT, hardware scheduling for IRT), not by "
        "changing the line code.")
    d["modulation"] = ("Standard Ethernet: MLT-3 (100BASE-TX) / PAM-5 "
                       "(1000BASE-T); 4B/5B (100BASE-TX) line coding.")
    d["clocking"] = (
        "Standard Ethernet clock recovery at the PHY. IRT adds clock "
        "SYNCHRONIZATION across devices at the application level via PTCP "
        "(sync domain), not a new physical clocking scheme.")
    for stale in ("transmitter_specs_canonical", "receiver_specs_canonical",
                  "mii_electrical", "magnetics_spec"):
        d.pop(stale, None)
    d["phy_summary"] = {
        "speeds": [100, 1000],
        "media": "twisted pair (RJ45 / M12), full duplex, switched",
        "line_code_100m": "4B/5B + MLT-3 (100BASE-TX)",
        "line_code_1g": "8B1Q4 / PAM-5 (1000BASE-T)",
        "note": "standard IEEE 802.3 PHY; PROFINET-unmodified.",
    }
    d["irt_timing_note"] = (
        "For IRT (CC-C) the PROFINET ASIC schedules frame transmit/receive at "
        "planned times on planned ports (cut-through), giving deterministic "
        "latency and jitter < 1 us; this is a MAC/scheduling property, not an "
        "analog one.")
    d["encoding_role_in_analog"] = (
        "PROFINET inherits Ethernet's line coding (4B/5B, MLT-3, PAM-5) and FCS "
        "(CRC-32). Real-time determinism comes from Layer-2 prioritization (RT) "
        "and offline-planned hardware scheduling + PTCP sync (IRT), not from "
        "the analog/PHY layer.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — FSM: PROFINET IO start-up / AR state machine.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    for stale in ("fsm_states_mac", "fsm_states_autoneg",
                  "fsm_states_mdio", "fsm_states_csma_cd"):
        d.pop(stale, None)
    d["fsm_states_startup"] = [
        {"name": "POWER_UP", "description": "Device boots; Ethernet link comes "
         "up (auto-negotiation); MAC active."},
        {"name": "ADDRESSING_DCP", "description": "Device has or is assigned "
         "NameOfStation + IP via DCP (Set/Hello); the IO-Controller resolves "
         "the configured name (DCP-Identify by name)."},
        {"name": "CONNECT_AR", "description": "IO-Controller sends CL-RPC "
         "Connect.req with the expected configuration; IO-Device validates "
         "modules/submodules and answers Connect.res; IO-CR/Record-Data-CR/"
         "Alarm-CR created."},
        {"name": "PARAMETERIZATION", "description": "IO-Controller writes "
         "parameter records to each submodule (Write) and signals "
         "ParameterEnd."},
        {"name": "APPLICATION_READY", "description": "IO-Device signals "
         "ApplicationReady (DControl/CControl) when its modules are "
         "parameterized."},
        {"name": "DATA_EXCHANGE", "description": "Cyclic IO-CR frames flow at "
         "the send clock; IOPS/IOCS valid; APDU Cycle Counter running; "
         "watchdog armed. AR is 'in data exchange'."},
        {"name": "RUN", "description": "Alarms exchanged on events; acyclic "
         "Read/Write on demand; diagnosis maintained."},
        {"name": "ERROR_ABORT", "description": "Watchdog timeout, CL-RPC AR "
         "abort, or fatal diagnosis tears down the AR; device returns toward "
         "ADDRESSING/CONNECT to re-establish."},
    ]
    d["fsm_hints"] = {
        "trigger": "Power-up -> ADDRESSING_DCP -> CONNECT_AR -> "
        "PARAMETERIZATION -> APPLICATION_READY -> DATA_EXCHANGE -> RUN. "
        "Addressing must complete (name + IP) before the controller can "
        "Connect.",
        "rule": "Cyclic data starts only after ApplicationReady; the consumer "
        "uses IOPS + Cycle Counter + Data Status + watchdog to judge validity.",
        "abort": "A watchdog miss or AR abort returns the device toward "
        "addressing/connect; alarms set the Station Problem Indicator.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up the device brings up the Ethernet link, ensures its "
        "DCP-assigned NameOfStation + IP, then waits for the IO-Controller's "
        "CL-RPC Connect, completes parameterization, signals ApplicationReady, "
        "and enters cyclic data exchange.")
    d["default_ready_state_recommendation"] = {
        "before_data_exchange": "Submodule outputs in the substitute/safe "
        "state; IOPS = BAD until parameterized and ApplicationReady.",
        "in_data_exchange": "IOPS = GOOD for valid produced data; DataValid "
        "set in APDU Data Status.",
    }
    d["anti_deadlock_rule"] = (
        "The watchdog (data-hold) timer bounds how long a consumer trusts "
        "stale data; a miss forces a defined invalid state rather than a hang. "
        "AR abort cleanly tears down all CRs.")
    d["configurations"] = [
        {"name": "CC-A device", "description": "RT only; no topology "
         "requirements."},
        {"name": "CC-B device", "description": "CC-A + LLDP/SNMP topology & "
         "diagnosis + MRP redundancy."},
        {"name": "CC-C device", "description": "CC-B + IRT hardware scheduling "
         "+ PTCP sync (motion control)."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test/debug: DCP/LLDP/diagnosis/alarm observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "DCP Identify / Signal", "purpose": "Discover stations and "
         "physically locate one (flashing LED) for commissioning/debug."},
        {"name": "LLDP topology", "purpose": "Per-port neighbor/chassis/port "
         "IDs (EtherType 0x88CC) build the physical topology and detect cable "
         "swaps (CC-B+)."},
        {"name": "SNMP diagnosis", "purpose": "Network-level diagnosis/MIB "
         "access for the engineering tool (CC-B+)."},
        {"name": "Channel / submodule / module diagnosis", "purpose": "Read "
         "diagnosis records (ChannelErrorType, ChannelNumber, severity) "
         "acyclically and via the Alarm-CR."},
        {"name": "APDU Cycle Counter / Data Status", "purpose": "Per-frame "
         "liveness, DataValid, Provider State (Run/Stop), and Station Problem "
         "Indicator for run-time health."},
        {"name": "I&M records", "purpose": "Standardized identification & "
         "maintenance data (I&M0..I&M4) for asset management."},
    ]
    d["error_detection_mechanisms"] = [
        "Ethernet FCS (CRC-32) discards corrupted frames.",
        "APDU Cycle Counter detects missed/duplicated/late cyclic frames.",
        "Watchdog (data-hold) timeout detects loss of cyclic data.",
        "Per-object IOPS/IOCS signal partial data invalidity.",
        "Configuration mismatch (Module/Submodule Ident) detected at Connect / "
        "by diagnosis.",
        "Alarms (diagnosis/process/plug-pull) report faults with acknowledge.",
    ]
    d["test_modes"] = [
        {"name": "Conformance / interoperability test", "purpose": "PI "
         "certification per conformance class (CC-A/CC-B/CC-C)."},
        {"name": "DCP flashing", "purpose": "Physically identify a station "
         "found via DCP."},
        {"name": "Topology check", "purpose": "Compare LLDP-discovered "
         "topology to the planned topology (IRT requirement)."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Diagnosis alarm (appear/disappear)", "trigger": "channel/"
         "submodule fault detected/cleared."},
        {"event": "Process alarm", "trigger": "application-defined process "
         "event."},
        {"event": "Plug / Pull alarm", "trigger": "module inserted/removed in "
         "a slot."},
        {"event": "Return-of-submodule alarm", "trigger": "submodule becomes "
         "available again."},
        {"event": "AR abort", "trigger": "watchdog miss / CL-RPC abort / fatal "
         "diagnosis."},
    ]
    d["notes"] = (
        "PROFINET's observability is built around DCP (discovery/location), "
        "LLDP/SNMP (topology/diagnosis, CC-B+), the per-frame APDU "
        "status/IOPS/IOCS, and the acyclic diagnosis/I&M records plus the "
        "Alarm-CR. Conformance is established by the PI certification per "
        "conformance class.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — PROFINET timing/frame/class constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    for stale in ("MII_DATA_WIDTH", "GMII_DATA_WIDTH", "MDIO_REG_ADDR_WIDTH",
                  "PREAMBLE_BYTES", "SFD_BYTE", "MAC_ADDR_WIDTH_BITS"):
        wp.pop(stale, None)
    wp.update({
        "STANDARD": "IEC 61158 Type 10 / IEC 61784-2 CPF 3 (PROFINET IO)",
        "ETHERNET_SPEEDS_MBPS": [100, 1000],
        "RT_ETHERTYPE": _RT_ETHERTYPE,
        "VLAN_ETHERTYPE": "0x8100",
        "VLAN_PCP_RT_CYCLIC": 6,
        "LLDP_ETHERTYPE": "0x88CC",
        "IP_ETHERTYPE": "0x0800",
        "FRAMEID_BYTES": 2,
        "FRAMEID_IRT_CYCLIC": "0x0100-0x0FFF",
        "FRAMEID_RT_CYCLIC": "0x8000-0xBFFF",
        "FRAMEID_DCP": "0xFC00-0xFCFF",
        "FRAMEID_ALARM_ACYCLIC": "0xFE00-0xFEFF",
        "FRAMEID_PTCP": "0xFF00-0xFF8F",
        "IOPS_BYTES_PER_OBJECT": 1,
        "IOCS_BYTES_PER_OBJECT": 1,
        "APDU_CYCLE_COUNTER_BYTES": 2,
        "APDU_DATA_STATUS_BYTES": 1,
        "APDU_TRANSFER_STATUS_BYTES": 1,
        "SEND_CLOCK_BASE_US": _SEND_CLOCK_BASE_US,
        "SEND_CLOCK_FACTOR_RANGE": "1..128",
        "CYCLE_TIME_RANGE_US": "31.25 .. 4000",
        "PERFORMANCE_CLASSES": list(_PERF_CLASSES),
        "CONFORMANCE_CLASSES": list(_CONFORMANCE_CLASSES),
        "DEVICE_ROLES": list(_DEVICE_ROLES),
        "DAP_SLOT": 0,
        "ETHERNET_FCS_WIDTH_BITS": 32,
        "MRP_RECOVERY_MS_MAX": 200,
        "IRT_JITTER_US_MAX": 1,
    })
    d["frame_constants"] = {
        "rt_ethertype": _RT_ETHERTYPE,
        "frameid_bytes": 2,
        "apdu_status_bytes": 4,
        "ethernet_mtu_payload_bytes": "46..1500",
        "fcs_polynomial": "Standard Ethernet CRC-32",
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    for stale in ("is_mii", "is_gmii", "csma_cd", "half_duplex"):
        kc.pop(stale, None)
    kc.update({
        "base_layer": "standard switched IEEE 802.3 Ethernet",
        "rt_ethertype": _RT_ETHERTYPE,
        "cyclic_model": "provider/consumer (not request/response)",
        "iops_iocs_per_object": True,
        "apdu_cycle_counter": True,
        "send_clock_base_us": _SEND_CLOCK_BASE_US,
        "performance_classes": list(_PERF_CLASSES),
        "conformance_classes": list(_CONFORMANCE_CLASSES),
        "irt_hardware_scheduled": True,
        "ptcp_time_sync": True,
        "mrp_ring_redundancy": True,
        "addressing": "name-based (DCP)",
        "acyclic_transport": "CL-RPC (DCE/RPC over UDP)",
    })
    d["default_signal_values_when_idle"] = {
        "before_data_exchange": "IOPS BAD; outputs in substitute/safe state.",
        "in_data_exchange": "IOPS GOOD; DataValid set; Cycle Counter "
                            "incrementing.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — PROFINET cyclic / IRT timing waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    for stale in ("mii_waveform", "mdio_waveform", "preamble_waveform",
                  "autoneg_waveform"):
        d.pop(stale, None)
    d["cyclic_timing_waveform"] = {
        "send_clock_base_us": _SEND_CLOCK_BASE_US,
        "send_clock_factor_example": "x32 -> 1 ms cycle",
        "reduction_ratio": "CR sent every Nth send-clock; phase spreads frames "
                           "within the send cycle.",
        "watchdog": "data-hold = reduction_ratio x send_clock x "
                    "watchdog_factor; miss flags data invalid.",
        "cycle_counter": "increments every 31.25 us send-clock tick (2 bytes).",
    }
    d["irt_schedule_waveform"] = {
        "red_phase": "reserved time slot for scheduled IRT frames at planned "
                     "send/receive times on planned ports (cut-through).",
        "green_phase": "open phase for RT / NRT / best-effort traffic.",
        "jitter_us_max": 1,
        "note": "Offline-planned schedule (engineering tool); deterministic "
                "latency/jitter for motion control.",
    }
    d["ptcp_sync_waveform"] = {
        "sync_domain": "Sync Master + Sync Slaves",
        "messages": ["Sync", "FollowUp", "Delay request/response"],
        "ethertype": _RT_ETHERTYPE,
        "frameid": "0xFF00-0xFF8F",
        "accuracy": "sub-microsecond",
    }
    d["startup_transition_trigger_waveform"] = {
        "POWERUP_to_DCP": "link up; name/IP present or DCP-Set.",
        "DCP_to_CONNECT": "controller resolves name (DCP-Identify), sends "
                          "CL-RPC Connect.req.",
        "CONNECT_to_PARAM": "Connect.res ok; write parameter records.",
        "PARAM_to_APPRDY": "ParameterEnd; device signals ApplicationReady.",
        "APPRDY_to_DATAEX": "cyclic IO-CR frames begin at the send clock.",
        "DATAEX_to_ABORT": "watchdog miss / AR abort / fatal diagnosis.",
    }
    d["general_timing_rule"] = (
        "RT cyclic frames are sent every send_clock x reduction_ratio "
        "(send_clock = 31.25 us x factor); the consumer judges liveness from "
        "the 2-byte APDU Cycle Counter and the watchdog. IRT frames are sent "
        "at offline-planned exact times within the reserved red phase for "
        "jitter < 1 us. PTCP keeps all IRT clocks synchronized in the sync "
        "domain.")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration: PROFINET IO node integration.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "An Industrial Ethernet node that participates in PROFINET IO as an "
        "IO-Controller, IO-Device, or IO-Supervisor: it uses standard switched "
        "IEEE 802.3 Ethernet, is addressed by name via DCP, is described by a "
        "GSDML file, establishes/joins an Application Relation (AR) carrying "
        "IO-CR / Record-Data-CR / Alarm-CR, and exchanges cyclic "
        "provider/consumer process data (IOPS/IOCS + APDU status) plus acyclic "
        "CL-RPC records, in one of three performance classes (NRT/RT/IRT) per "
        "its conformance class (CC-A/CC-B/CC-C).")
    d["topology_description"] = (
        "Switched Ethernet line / star / tree / ring (MRP). Devices typically "
        "have an integrated 2-port switch for daisy-chaining into a line; a "
        "ring with a Media Redundancy Manager provides redundancy. IRT needs a "
        "fixed planned topology (LLDP + offline schedule).")
    io = _ensure_dict(d, "integration_overview")
    for stale in ("mii_pin_count", "gmii_pin_count", "mdio_pin_count",
                  "phy_address", "csma_cd"):
        io.pop(stale, None)
    io.update({
        "standard": "IEC 61158 Type 10 / IEC 61784-2 CPF 3",
        "base_layer": "standard switched IEEE 802.3 Ethernet (100M / 1G)",
        "device_roles": list(_DEVICE_ROLES),
        "performance_classes": list(_PERF_CLASSES),
        "conformance_classes": list(_CONFORMANCE_CLASSES),
        "rt_ethertype": _RT_ETHERTYPE,
        "addressing": "name-based via DCP (IP optional via DCP/DHCP)",
        "device_description": "GSDML XML",
        "connection_model": "AR (Application Relation) with IO-CR / "
                            "Record-Data-CR / Alarm-CR",
        "cyclic_model": "provider/consumer with IOPS/IOCS + APDU Cycle "
                        "Counter/Data Status",
        "acyclic_transport": "CL-RPC (DCE/RPC over UDP)",
        "time_sync": "PTCP (sync domain)",
        "media_redundancy": "MRP (IEC 62439-2)",
        "send_clock_base_us": _SEND_CLOCK_BASE_US,
        "host_side_register_spec": "record/index model (API, Slot, Subslot, "
        "Index) via CL-RPC plus DCP-managed station identity and "
        "Connect-negotiated AR/CR parameters.",
    })
    d["interface_categories"] = [
        "Ethernet ports (2-port integrated switch typical) — standard IEEE "
        "802.3 PHY/MAC.",
        "PROFINET communication core — RT/IRT engine, DCP, AR/CR, alarm, "
        "diagnosis (ASIC/FPGA/firmware).",
        "PTCP time-sync unit (CC-C / IRT).",
        "MRP ring-redundancy unit (CC-B+).",
        "Application interface — slot/subslot I/O data to the device's "
        "application; engineering data via GSDML.",
    ]
    d["interconnect_topologies_supported"] = [
        "Line (daisy-chain via integrated 2-port switches)",
        "Star / tree (external switches)",
        "Ring with MRP (Media Redundancy Manager + Clients)",
        "Planned fixed topology for IRT (CC-C)",
    ]
    d["soc_dependent_items"] = [
        "Conformance class target (CC-A / CC-B / CC-C) and whether IRT hardware "
        "+ PTCP are required.",
        "Number of Ethernet ports and integrated-switch choice.",
        "Send-clock factor / reduction ratio / watchdog factor for the IO-CR(s).",
        "GSDML module/submodule layout and I/O data sizes.",
        "MRP role (manager vs client) where redundancy is used.",
        "Standard Ethernet PHY selection (100BASE-TX / 1000BASE-T).",
    ]
    d["device_classes_examples"] = [
        "PLC / IO-Controller",
        "Remote-I/O IO-Device",
        "Drive / motion IO-Device (IRT / CC-C)",
        "Sensor/actuator station IO-Device",
        "Engineering / diagnostic IO-Supervisor",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — compliance test categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines conformance behaviors (per "
        "conformance class) certified by PI; the categories below are derived "
        "from the spec.")
    d["derived_compliance_test_categories"] = [
        "Ethernet base: standard 802.3 frames on 100M/1G switched full-duplex.",
        "DCP: Identify / Get / Set (NameOfStation, IP) / Hello / Signal "
        "(flash).",
        "LLDP topology discovery (CC-B+) and SNMP diagnosis.",
        "GSDML import vs real device module/submodule match.",
        "AR establishment via CL-RPC Connect with expected configuration.",
        "IO-CR cyclic exchange at send_clock x reduction_ratio; per-object "
        "IOPS/IOCS; APDU Cycle Counter / Data Status.",
        "RT prioritization: EtherType 0x8892, VLAN PCP = 6.",
        "Watchdog (data-hold) timeout -> data invalid handling.",
        "Acyclic Read/Write records (parameters, diagnosis, I&M0..I&M4) via "
        "CL-RPC.",
        "Alarm-CR: diagnosis / process / plug-pull alarms with acknowledge.",
        "Conformance class behavior: CC-A (RT), CC-B (+topology/diagnosis/MRP), "
        "CC-C (+IRT).",
        "IRT: offline-planned red/green schedule; jitter < 1 us; cut-through.",
        "PTCP time sync in a sync domain (Sync Master/Slaves; delay "
        "measurement).",
        "MRP ring redundancy: manager/client; <= 200 ms recovery on link "
        "failure.",
        "Start-up sequence: power-up -> DCP -> Connect -> parameterize -> "
        "ApplicationReady -> data exchange.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / identity (PROFINET has no protocol OTP; identity facts).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "MAC address", "width_bits": 48,
         "location": "device (factory)",
         "note": "Standard Ethernet MAC; factory-unique."},
        {"field": "VendorID / DeviceID", "width_bits": "16 / 16",
         "location": "GSDML + device identity",
         "note": "PI-assigned VendorID; manufacturer DeviceID; advertised via "
                 "DCP/I&M0."},
        {"field": "SerialNumber / Order ID / HW & SW revision",
         "width_bits": "string",
         "location": "I&M0 record",
         "note": "Identification data read acyclically (I&M0)."},
        {"field": "NameOfStation", "width_bits": "string",
         "location": "non-volatile (DCP-Set)",
         "note": "Primary station identity; set during commissioning and "
                 "stored non-volatilely."},
    ]
    d["notes"] = (
        "PROFINET defines no protocol-level OTP/fuse content. The "
        "interoperability-relevant identity (MAC, VendorID/DeviceID, "
        "SerialNumber, revisions) is hardware/factory data exposed via DCP and "
        "the I&M0 record; the NameOfStation is commissioned via DCP-Set and "
        "stored non-volatilely. An implementation may back some of these with "
        "fuses, but the spec only requires they be discoverable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    for stale in ("autoneg_sequence", "mdio_read_sequence",
                  "mdio_write_sequence", "mac_tx_sequence", "mac_rx_sequence"):
        d.pop(stale, None)
    d["startup_sequence"] = [
        "1. Power-up: device boots; Ethernet link up (auto-negotiation); MAC "
        "active.",
        "2. Addressing (DCP): device has/assigned NameOfStation + IP "
        "(DCP-Set/Hello); controller resolves the name (DCP-Identify).",
        "3. Connect (AR): controller sends CL-RPC Connect.req with expected "
        "configuration; device validates and answers Connect.res; CRs created.",
        "4. Parameterization: controller writes parameter records to each "
        "submodule; ParameterEnd.",
        "5. ApplicationReady: device signals readiness (DControl/CControl).",
        "6. Data exchange: cyclic IO-CR frames flow at the send clock; "
        "IOPS/IOCS valid; APDU Cycle Counter running; watchdog armed.",
        "7. Run: alarms on events; acyclic Read/Write on demand; diagnosis "
        "maintained.",
    ]
    d["cyclic_exchange_sequence"] = [
        "1. Provider builds the IO-CR frame: IO data objects + IOPS, consumer "
        "IOCS, then APDU Status (Cycle Counter, Data Status, Transfer Status).",
        "2. Frame sent on EtherType 0x8892 (VLAN PCP 6 for RT) every "
        "send_clock x reduction_ratio (IRT at planned times).",
        "3. Consumer checks Cycle Counter (liveness), Data Status (DataValid), "
        "and per-object IOPS; resets the watchdog.",
        "4. On watchdog miss the consumer flags data invalid (IOPS BAD) and "
        "may abort the AR.",
    ]
    d["dcp_sequence"] = [
        "1. IO-Supervisor/Controller sends DCP-Identify (multicast) to find "
        "stations.",
        "2. Device replies with NameOfStation + current address.",
        "3. DCP-Set assigns NameOfStation and IP; device stores the name "
        "non-volatilely.",
        "4. DCP-Signal flashes the device LED to locate it physically.",
    ]
    d["acyclic_sequence"] = [
        "1. Read/Write record addressed by (API, Slot, Subslot, Index) over "
        "CL-RPC.",
        "2. I&M0..I&M4 read for identification/maintenance.",
        "3. Diagnosis records read on demand or pushed via the Alarm-CR.",
    ]
    d["alarm_sequence"] = [
        "1. Device detects a channel/submodule fault (or plug/pull event).",
        "2. Device sends the alarm on the Alarm-CR (low/high priority queue).",
        "3. Controller acknowledges; Station Problem Indicator reflected in "
        "the cyclic Data Status.",
    ]
    d["mrp_sequence"] = [
        "1. Media Redundancy Manager blocks one ring port and sends MRP test "
        "frames.",
        "2. On a link/port failure the MRM unblocks the secondary port.",
        "3. Recovery within <= 200 ms; cyclic data resumes.",
    ]
    d["reset_sequence"] = [
        "1. AR abort / fatal diagnosis / watchdog miss tears down all CRs.",
        "2. Device returns toward DCP addressing / CL-RPC Connect to "
        "re-establish the AR.",
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
        {"name": "Cycle time / send clock", "purpose": "Verify the IO-CR is "
         "sent every send_clock x reduction_ratio (send_clock = 31.25 us x "
         "factor)."},
        {"name": "RT prioritization", "purpose": "Confirm RT cyclic frames use "
         "EtherType 0x8892 with VLAN PCP = 6 and are prioritized over NRT."},
        {"name": "IRT jitter", "purpose": "Measure IRT frame timing jitter "
         "(< 1 us) under load in the planned red/green schedule."},
        {"name": "PTCP sync accuracy", "purpose": "Verify sub-microsecond "
         "clock alignment across the sync domain."},
        {"name": "Watchdog behavior", "purpose": "Force a missing frame and "
         "confirm the data-hold timeout flags data invalid."},
        {"name": "MRP recovery time", "purpose": "Break a ring link and "
         "measure recovery (<= 200 ms)."},
        {"name": "DCP / topology", "purpose": "Verify name/IP assignment and "
         "LLDP-discovered topology match the plan."},
    ]
    d["notes"] = (
        "PROFINET characterization centers on cyclic timing (send clock, "
        "reduction ratio, watchdog), RT/IRT determinism (prioritization, IRT "
        "jitter, PTCP sync), and network behaviors (DCP addressing, LLDP "
        "topology, MRP recovery). Conformance is established by PI "
        "certification per conformance class. The underlying Ethernet PHY is "
        "characterized per standard IEEE 802.3.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — versioning (fields dict).
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "PROFINET IO — IEC 61158 (Type 10) and IEC 61784-2 (Communication "
        "Profile Family 3, CPF 3), maintained by PI (PROFIBUS & PROFINET "
        "International)")
    f["previous_versions"] = [
        "PROFINET CBA (Component Based Automation) — the older "
        "component-model variant; deprecated and superseded by PROFINET IO.",
    ]
    f["key_changes"] = [
        {"version": "PROFINET IO", "summary": "Defines the device roles "
         "(IO-Controller/IO-Device/IO-Supervisor), GSDML device description, "
         "DCP name-based addressing, the AR/CR connection model "
         "(IO-CR/Record-Data-CR/Alarm-CR), cyclic provider/consumer data with "
         "IOPS/IOCS and APDU Cycle Counter/Data Status, acyclic CL-RPC "
         "records, the performance classes NRT/RT/IRT, the conformance classes "
         "CC-A/CC-B/CC-C, PTCP time sync, and MRP media redundancy, all on "
         "standard switched IEEE 802.3 Ethernet."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "TSN-based PROFINET", "summary": "Later PI work maps "
         "PROFINET onto IEEE 802.1 Time-Sensitive Networking (TSN) for "
         "standardized scheduling/redundancy at higher speeds, preserving the "
         "same device/AR/CR/GSDML model."},
    ]
    f["deprecated_features"] = [
        "PROFINET CBA (Component Based Automation) — deprecated.",
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Name_not_address_is_identity",
         "rule": "PROFINET addresses devices by NameOfStation (DCP), not by a "
                 "fixed IP/bus address.",
         "trap": "Treating a fixed IP as the device identity breaks "
                 "name-based AR establishment and device replacement."},
        {"trap_name": "RT_is_layer2_not_ip",
         "rule": "RT cyclic data rides Layer-2 on EtherType 0x8892, bypassing "
                 "TCP/IP.",
         "trap": "Routing RT cyclic data through the IP stack defeats "
                 "real-time determinism."},
        {"trap_name": "IRT_needs_planned_topology",
         "rule": "IRT (CC-C) requires fixed, planned topology and offline "
                 "scheduling plus PTCP sync hardware.",
         "trap": "Assuming IRT works on an arbitrary/auto topology like RT "
                 "fails the schedule."},
        {"trap_name": "GSDML_not_GSD",
         "rule": "PROFINET uses the XML GSDML, NOT the keyword-based PROFIBUS "
                 "GSD text file.",
         "trap": "Re-using a PROFIBUS GSD as a PROFINET device description is "
                 "wrong."},
        {"trap_name": "Conformance_class_implies_hardware",
         "rule": "CC-C implies IRT-capable hardware (PROFINET ASIC/FPGA with "
                 "scheduler + PTCP); CC-A/CC-B may be software RT.",
         "trap": "Claiming CC-C on a standard NIC without IRT hardware fails "
                 "certification."},
    ]
    f["version_naming_history_note"] = (
        "PROFINET is standardized in IEC 61158 (Type 10) and IEC 61784-2 "
        "(Communication Profile Family 3) and maintained by PI (PROFIBUS & "
        "PROFINET International), the same organization behind the serial "
        "PROFIBUS fieldbus. PROFINET is the Ethernet successor to PROFIBUS, "
        "replacing RS-485 token-passing / SD1-SD4 telegrams / GSD / DPV1 with "
        "switched Ethernet, GSDML, names, and a provider/consumer cyclic "
        "model. The communication profiles RT_CLASS_1 / RT_CLASS_2 / "
        "RT_CLASS_3(IRT) / RT_CLASS_UDP correspond to the NRT/RT/IRT "
        "performance classes.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / parameter tables (fields dict).
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    for stale in ("mii_signal_table", "mdio_register_table",
                  "line_code_table_4b5b"):
        f.pop(stale, None)
    f["ethertype_table"] = {
        "header_columns": ["EtherType", "Use"],
        "rows": [
            ["0x8892", "PROFINET RT/IRT (PN-RT) — cyclic + DCP + PTCP + alarms"],
            ["0x8100", "IEEE 802.1Q VLAN tag (PCP priority; RT cyclic = 6)"],
            ["0x0800", "IPv4 (NRT: TCP/IP, UDP, CL-RPC transport)"],
            ["0x0806", "ARP"],
            ["0x88CC", "LLDP (topology / neighbor detection)"],
        ],
    }
    f["frameid_range_table"] = {
        "header_columns": ["FrameID range", "Class"],
        "rows": [
            ["0x0100-0x0FFF", "IRT cyclic (high performance)"],
            ["0x8000-0xBFFF", "RT cyclic class 1/2"],
            ["0xFC00-0xFCFF", "DCP"],
            ["0xFE00-0xFEFF", "Acyclic / Alarm (low/high)"],
            ["0xFF00-0xFF8F", "PTCP (Sync / FollowUp / Delay)"],
        ],
    }
    f["performance_class_table"] = {
        "header_columns": ["Class", "Transport", "Use"],
        "rows": [
            ["NRT", "TCP/IP, UDP (0x0800)", "config / diagnosis / acyclic"],
            ["RT", "Layer-2 (0x8892), VLAN PCP", "cyclic process data"],
            ["IRT", "HW-scheduled L2 (0x8892), sync domain",
             "isochronous motion control"],
        ],
    }
    f["conformance_class_table"] = {
        "header_columns": ["Class", "Adds"],
        "rows": [
            ["CC-A", "RT, DCP addressing, alarms, acyclic"],
            ["CC-B", "CC-A + LLDP/SNMP topology & diagnosis + MRP"],
            ["CC-C", "CC-B + IRT hardware scheduling + PTCP sync"],
        ],
    }
    f["apdu_status_table"] = {
        "header_columns": ["Field", "Bytes", "Meaning"],
        "rows": [
            ["Cycle Counter", "2", "31.25 us ticks; liveness"],
            ["Data Status", "1", "DataValid / Provider State / SPI / "
             "Primary-Backup"],
            ["Transfer Status", "1", "transfer-level status"],
        ],
    }
    f["timing_table"] = {
        "header_columns": ["Parameter", "Value"],
        "rows": [
            ["Send clock base", "31.25 us"],
            ["Send-clock factor", "1..128"],
            ["Cycle time range", "31.25 us .. 4 ms"],
            ["IRT jitter (max)", "< 1 us"],
            ["MRP recovery (max)", "<= 200 ms"],
        ],
    }
    f["encoding_note"] = (
        "PROFINET inherits Ethernet's line coding and FCS; its distinguishing "
        "tables are the EtherType/FrameID usage, the performance/conformance "
        "classes, the APDU status, and the cyclic timing parameters — not a "
        "new line code.")
    f["tables"] = [
        "EtherType usage table",
        "FrameID range table",
        "Performance class table (NRT/RT/IRT)",
        "Conformance class table (CC-A/CC-B/CC-C)",
        "APDU status table",
        "Cyclic timing table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties (fields dict).
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.pop("ethernet_distinguishers", None)
    f["must_have_properties"] = [
        "Standard switched IEEE 802.3 Ethernet base (100M/1G, full duplex).",
        "Device roles IO-Controller / IO-Device / IO-Supervisor.",
        "GSDML XML device description.",
        "DCP name-based addressing (Identify/Get/Set/Hello/Signal).",
        "Application Relation (AR) via CL-RPC with IO-CR / Record-Data-CR / "
        "Alarm-CR.",
        "Cyclic provider/consumer data with per-object IOPS/IOCS.",
        "APDU Status (2-byte Cycle Counter + Data Status + Transfer Status).",
        "RT cyclic frames on EtherType 0x8892 with VLAN PCP prioritization.",
        "Acyclic Read/Write records (incl. I&M0..I&M4) via CL-RPC.",
        "Declared conformance class behavior (CC-A/CC-B/CC-C); CC-C adds IRT "
        "and PTCP.",
    ]
    f["must_not_have_properties"] = [
        "RS-485 token-passing / SD1-SD4 telegram framing (that is PROFIBUS, "
        "not PROFINET).",
        "A keyword-based GSD text file as the device description (PROFINET "
        "uses XML GSDML).",
        "Fixed bus-address-only identity with no NameOfStation/DCP.",
        "Routing RT cyclic data through the TCP/IP stack (RT is Layer-2).",
        "The EtherCAT on-the-fly datagram / FMMU / distributed-clock model.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "No name/IP", "trigger": "device lacks DCP-assigned "
         "NameOfStation; controller cannot connect."},
        {"mode": "Configuration mismatch", "trigger": "plugged "
         "Module/Submodule Ident does not match expected; Connect/diagnosis "
         "fails."},
        {"mode": "Watchdog timeout", "trigger": "cyclic frame missing beyond "
         "data-hold time; data invalid / AR abort."},
        {"mode": "Wrong class hardware", "trigger": "CC-C claimed without IRT "
         "scheduler / PTCP."},
        {"mode": "Topology mismatch (IRT)", "trigger": "real topology differs "
         "from the planned schedule."},
    ]
    f["min_link_constraint"] = (
        "A device must come up on standard Ethernet, obtain a NameOfStation/IP "
        "via DCP, accept an AR via CL-RPC, and exchange at least one IO-CR "
        "cyclically with valid IOPS and a running Cycle Counter; otherwise it "
        "fails to enter data exchange.")
    f["reset_behavior_compliance"] = (
        "On reset/power-up the device re-establishes link, ensures its "
        "DCP-assigned name/IP, waits for CL-RPC Connect, completes "
        "parameterization, signals ApplicationReady, and resumes cyclic data "
        "exchange. An AR abort returns it to addressing/connect.")
    f["profinet_distinguishers"] = (
        "PROFINET is identified by ALL of: standard switched IEEE 802.3 "
        "Ethernet base; the IO-Controller/IO-Device/IO-Supervisor device "
        "roles; the GSDML XML device description; DCP name-based addressing; "
        "the AR/CR connection model (IO-CR/Record-Data-CR/Alarm-CR); cyclic "
        "provider/consumer data with per-object IOPS/IOCS and an APDU Cycle "
        "Counter/Data Status; RT cyclic frames on EtherType 0x8892 with VLAN "
        "PCP priority; acyclic CL-RPC records; the performance classes "
        "NRT/RT/IRT; and the conformance classes CC-A/CC-B/CC-C (CC-C adds IRT "
        "+ PTCP). This is distinct from plain Ethernet (which lacks the IO "
        "device/AR/CR model), from EtherCAT (on-the-fly datagram / FMMU / "
        "distributed clock / ESC), and from the serial PROFIBUS fieldbus "
        "(RS-485 token-passing / SD1-SD4 / GSD / DPV1).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog (fields dict).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "IO-CR (cyclic input)",
         "direction": "IO-Device -> IO-Controller",
         "purpose": "Cyclic input process data (provider = device).",
         "active_levels": "EtherType 0x8892 frame at send_clock x "
         "reduction_ratio; data + IOPS + IOCS + APDU Status",
         "idle_level": "IOPS BAD before data exchange"},
        {"name": "IO-CR (cyclic output)",
         "direction": "IO-Controller -> IO-Device",
         "purpose": "Cyclic output process data (provider = controller).",
         "active_levels": "EtherType 0x8892 frame; data + IOPS + IOCS + APDU "
         "Status", "idle_level": "outputs in substitute/safe state"},
        {"name": "Record-Data-CR",
         "direction": "bidirectional (acyclic)",
         "purpose": "Read/Write records (parameters, diagnosis, I&M) via "
         "CL-RPC.",
         "active_levels": "on demand", "idle_level": "idle"},
        {"name": "Alarm-CR",
         "direction": "IO-Device -> IO-Controller (acknowledged)",
         "purpose": "Diagnosis/process/plug-pull alarms.",
         "active_levels": "on event (low/high priority)", "idle_level": "idle"},
        {"name": "DCP / LLDP / PTCP control",
         "direction": "multicast / per-port",
         "purpose": "Addressing (DCP), topology (LLDP), time sync (PTCP).",
         "active_levels": "0x8892 (DCP/PTCP) / 0x88CC (LLDP)",
         "idle_level": "periodic"},
        {"name": "NRT (TCP/IP, UDP)",
         "direction": "bidirectional",
         "purpose": "Configuration / diagnosis / CL-RPC transport.",
         "active_levels": "EtherType 0x0800", "idle_level": "best-effort"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Provider status (IOPS)", "meaning": "1 byte per object: "
         "Good/Bad validity of produced data."},
        {"name": "Consumer status (IOCS)", "meaning": "1 byte per object: "
         "consumer accepted/rejected."},
        {"name": "Data Status", "meaning": "DataValid / Provider State "
         "(Run/Stop) / Station Problem Indicator / Primary-Backup."},
    ]
    f["packet_types_summary"] = [
        {"class": "Cyclic (RT/IRT)", "members": ["IO-CR input", "IO-CR output"],
         "count": 2},
        {"class": "Acyclic", "members": ["Record Read/Write (CL-RPC)",
         "Alarm", "Control"], "count": 3},
        {"class": "Control/management", "members": ["DCP", "LLDP", "PTCP"],
         "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    for stale in ("mii_signals", "gmii_signals", "mdio_signals"):
        cc.pop(stale, None)
    cc.update({
        "cyclic_crs_typical": 2,
        "acyclic_crs": 2,
        "performance_classes": len(_PERF_CLASSES),
        "conformance_classes": len(_CONFORMANCE_CLASSES),
        "device_roles": len(_DEVICE_ROLES),
        "apdu_status_bytes": 4,
        "iops_iocs_bytes_per_object": 1,
    })
    f["global_signals"] = [
        {"name": "DCP", "purpose": "Name/IP assignment + station location."},
        {"name": "LLDP", "purpose": "Topology / neighbor detection (CC-B+)."},
        {"name": "PTCP", "purpose": "Time synchronization in the sync domain "
         "(IRT)."},
        {"name": "MRP", "purpose": "Ring redundancy (CC-B+)."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Addressing (DCP name/IP) must complete before AR "
        "Connect; parameterization + ApplicationReady before cyclic data "
        "exchange. IRT additionally requires PTCP sync and a planned topology.",
        "data_dependency": "Cyclic exchange needs: (1) name/IP, (2) AR "
        "connected, (3) parameterized + ApplicationReady. The consumer trusts "
        "data only with valid IOPS, advancing Cycle Counter, and a non-expired "
        "watchdog.",
    }
    f["handshake_pairs"] = [
        {"name": "Connect/Connect-res", "from": "IO-Controller",
         "to": "IO-Device", "rule": "CL-RPC AR establishment with expected "
         "configuration."},
        {"name": "ParameterEnd/ApplicationReady", "from": "IO-Controller",
         "to": "IO-Device", "rule": "sequence parameterization before data "
         "exchange."},
        {"name": "Alarm/Alarm-Ack", "from": "IO-Device",
         "to": "IO-Controller", "rule": "alarm with explicit acknowledge."},
        {"name": "Provider/Consumer (IOPS/IOCS)", "from": "provider",
         "to": "consumer", "rule": "per-object validity + reverse acceptance."},
    ]
    f["ordering_rules"] = {
        "frame_liveness": "APDU Cycle Counter orders/validates cyclic frames "
        "(missed/duplicated/late detection).",
        "irt_scheduling": "IRT frames sent at offline-planned exact times in "
        "the red phase.",
        "priority": "RT cyclic uses VLAN PCP = 6 over NRT best-effort.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — interconnect topology (fields dict).
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Switched Ethernet line / star / tree / ring (MRP). PROFINET devices "
        "typically integrate a 2-port switch for daisy-chaining; a ring with a "
        "Media Redundancy Manager gives redundancy. IRT requires a fixed, "
        "planned topology (LLDP + offline schedule).")
    f["supported_topologies"] = [
        {"name": "Line", "description": "Daisy-chain via integrated 2-port "
         "switches."},
        {"name": "Star / tree", "description": "External Ethernet switches."},
        {"name": "Ring (MRP)", "description": "Media Redundancy Manager blocks "
         "one port; <= 200 ms recovery."},
        {"name": "Planned IRT topology", "description": "Fixed, LLDP-known "
         "topology with an offline-computed red/green schedule (CC-C)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "IO-Controller", "description": "PLC; establishes ARs, "
         "provides outputs, consumes inputs, handles alarms."},
        {"role": "IO-Device", "description": "Field device; provides inputs, "
         "consumes outputs; slot/subslot model."},
        {"role": "IO-Supervisor", "description": "Engineering/diagnostic "
         "station; acyclic read/write only."},
        {"role": "Media Redundancy Manager / Client", "description": "MRP ring "
         "roles (CC-B+)."},
        {"role": "Sync Master / Slave", "description": "PTCP roles in the sync "
         "domain (IRT)."},
    ]
    f["interconnect_role"] = (
        "PROFINET is a switched-Ethernet field network. The IO-Controller is "
        "the central master of each AR; IO-Devices are the field nodes. Cyclic "
        "data is provider/consumer, prioritized at Layer-2 (RT) or "
        "hardware-scheduled (IRT). Redundancy (MRP) and time sync (PTCP) are "
        "network-wide services.")
    f["ordering_guarantees"] = {
        "cyclic_liveness": "APDU Cycle Counter detects missed/late/duplicated "
        "frames.",
        "irt_determinism": "planned schedule gives bounded latency / jitter "
        "< 1 us.",
        "priority": "RT (PCP 6) prioritized over NRT.",
    }
    f["memory_vs_peripheral_regions"] = (
        "PROFINET's addressable state is the slot/subslot I/O image and the "
        "record/index model (API, Slot, Subslot, Index), not a flat memory "
        "map; control-plane identity is DCP-managed.")
    dc = _ensure_dict(f, "device_classification")
    for stale in ("mac_phy", "switch_port", "repeater"):
        dc.pop(stale, None)
    dc["io_controller"] = "PLC controlling field devices over ARs."
    dc["io_device"] = "Distributed field I/O / drive / sensor station."
    dc["io_supervisor"] = "Engineering / commissioning / diagnostics station."
    dc["mrp_manager_client"] = "Ring-redundancy roles (CC-B+)."
    dc["sync_master_slave"] = "PTCP time-sync roles (IRT)."
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / network rules (fields dict).
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["network_constraints"] = {
        "base": "standard switched IEEE 802.3 Ethernet, 100 Mbit/s / 1 Gbit/s, "
                "full duplex",
        "rt_ethertype": _RT_ETHERTYPE,
        "vlan_priority_rt_cyclic": 6,
        "send_clock_base_us": _SEND_CLOCK_BASE_US,
        "send_clock_factor_range": "1..128",
        "cycle_time_range_us": "31.25 .. 4000",
        "frame_payload_bytes": "46..1500 (no jumbo frames)",
        "irt_jitter_us_max": 1,
        "mrp_recovery_ms_max": 200,
        "ptcp_accuracy": "sub-microsecond",
        "topology_irt": "fixed/planned (LLDP + offline schedule)",
        "performance_classes": list(_PERF_CLASSES),
        "conformance_classes": list(_CONFORMANCE_CLASSES),
    }
    f["notes"] = (
        "PROFINET fixes communication constraints (Ethernet base, EtherType/"
        "FrameID usage, send-clock timing, RT prioritization, IRT "
        "scheduling/jitter, PTCP accuracy, MRP recovery), not PDK/SDC silicon "
        "constraints. The underlying Ethernet PHY follows standard IEEE 802.3; "
        "IRT (CC-C) requires PROFINET ASIC/FPGA hardware with the scheduler and "
        "PTCP.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / in-band test facilities (fields dict).
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "DCP", "purpose": "Discover and physically locate stations "
         "(flashing) for commissioning/debug."},
        {"name": "LLDP / SNMP", "purpose": "Topology and network diagnosis "
         "(CC-B+)."},
        {"name": "APDU status / IOPS/IOCS", "purpose": "Per-frame liveness, "
         "validity, and station-problem indication."},
        {"name": "Diagnosis / I&M records", "purpose": "Acyclic fault and "
         "identification data."},
        {"name": "Alarm-CR", "purpose": "Event-driven fault reporting with "
         "acknowledge."},
    ]
    f["internal_diagnostics_observability"] = [
        "AR / CR state (connected, in-data-exchange, aborted).",
        "Cycle Counter / watchdog status.",
        "Channel/submodule/module diagnosis (ChannelErrorType, severity).",
        "Topology (LLDP) vs planned topology.",
        "PTCP sync status; MRP ring status.",
    ]
    f["out_of_band_test_facilities"] = [
        "PI conformance test tools per conformance class (CC-A/CC-B/CC-C).",
        "Standard Ethernet PHY test (IEEE 802.3) — vendor/implementation.",
    ]
    f["notes"] = (
        "PROFINET's test surface is the in-band DCP/LLDP/SNMP, the per-frame "
        "APDU status and IOPS/IOCS, and the acyclic diagnosis/I&M records plus "
        "the Alarm-CR. Chip-level JTAG/scan/BIST is an implementation concern. "
        "Conformance is certified by PI per conformance class.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (fields dict).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["notes"] = (
        "PROFINET is a communication standard and does not define link "
        "power-management states like a SerDes link. Power behavior is "
        "implementation-defined at the device level (standard Ethernet PHY "
        "power, device supply). Determinism is a scheduling/prioritization "
        "property, not a power-state one. Some devices support Power over "
        "Ethernet (PoE) per the standard, but that is an Ethernet feature, not "
        "a PROFINET protocol state.")
    f["power_considerations"] = [
        "Standard Ethernet PHY power (100BASE-TX / 1000BASE-T).",
        "Device-level supply per device class (PI form-factor guidelines).",
        "Optional PoE per IEEE 802.3 (not a PROFINET protocol feature).",
        "IRT/CC-C devices add a PROFINET ASIC/FPGA (scheduler + PTCP) with its "
        "own power.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan (fields dict).
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Ethernet base — standard 802.3 frames on 100M/1G switched full-duplex.",
        "DCP addressing — Identify/Get/Set/Hello/Signal; name + IP.",
        "GSDML — device description vs real module/submodule layout.",
        "AR establishment — CL-RPC Connect with expected configuration.",
        "IO-CR cyclic — send-clock timing, reduction ratio, IOPS/IOCS, APDU "
        "Cycle Counter/Data Status.",
        "RT prioritization — EtherType 0x8892, VLAN PCP = 6.",
        "Watchdog — data-hold timeout -> data invalid.",
        "Acyclic — Read/Write records (parameters, diagnosis, I&M0..I&M4) via "
        "CL-RPC.",
        "Alarm-CR — diagnosis/process/plug-pull alarms with acknowledge.",
        "Conformance classes — CC-A / CC-B / CC-C behavior.",
        "IRT — red/green schedule, jitter < 1 us, cut-through.",
        "PTCP — sync domain accuracy.",
        "MRP — ring redundancy recovery <= 200 ms.",
        "Start-up FSM — power-up -> DCP -> Connect -> parameterize -> "
        "ApplicationReady -> data exchange -> run/abort.",
    ]
    f["notes"] = (
        "PROFINET does not ship a single testbench; the verification plan spans "
        "the Ethernet base, addressing (DCP/LLDP), engineering (GSDML), "
        "connection (AR/CR), cyclic (IO-CR/IOPS/IOCS/APDU), acyclic (CL-RPC "
        "records/alarms), and the network services (PTCP/MRP) per the declared "
        "conformance class. PI supplies the formal conformance/interoperability "
        "certification.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security (fields dict).
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "Standard Ethernet FCS (CRC-32) discards corrupted frames.",
        "APDU Cycle Counter detects missed/duplicated/late cyclic frames.",
        "Per-object IOPS/IOCS signal partial data invalidity.",
        "Watchdog (data-hold) timeout forces a defined invalid state on data "
        "loss.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Classic PROFINET IO relies on network segmentation / zones & conduits "
        "(IEC 62443) and defense-in-depth, not built-in crypto on the cyclic "
        "path.",
        "PROFINET Security (a later PI specification layer) adds authentication "
        "and integrity for the engineering and acyclic channels, layered above "
        "the classic IO data path.",
        "TSN-based PROFINET and higher-level IT security mechanisms can be "
        "applied on the shared Ethernet.",
    ]
    f["notes"] = (
        "Classic PROFINET IO has no built-in cryptographic protection of the "
        "cyclic real-time path; integrity against transmission errors comes "
        "from the Ethernet FCS plus the APDU Cycle Counter/Data Status and "
        "IOPS/IOCS. Security relies on network segmentation and "
        "defense-in-depth (IEC 62443); cryptographic authentication/integrity "
        "for engineering/acyclic channels is added by the separate PROFINET "
        "Security specification layer, out of scope for the base cyclic "
        "protocol.")
    _write(p, d)
