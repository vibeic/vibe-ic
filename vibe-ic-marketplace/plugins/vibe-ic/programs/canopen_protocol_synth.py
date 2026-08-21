"""CANopen (CiA 301) protocol synth helper (protocol #70).

ic_class-gated overlay for the CANopen structural signature: the standardized
higher-layer (application-layer) communication profile that runs ON TOP OF a
Controller Area Network (CAN) data link layer, standardized by CAN in Automation
(CiA) as CiA 301 (EN 50325-4). CANopen adds, above the raw CAN frame, an Object
Dictionary (OD) addressed by a 16-bit Index + 8-bit Sub-index (standardized
entries 0x1000 device type, 0x1001 error register, 0x1018 identity object), a
predefined set of communication objects — PDO (Process Data Object, TPDO/RPDO,
mapping + transmission types), SDO (Service Data Object, client/server access to
the OD with expedited / segmented / block transfer), NMT (Network Management
master/slave state machine Initialisation -> Pre-operational -> Operational <->
Stopped with module-control commands start/stop/reset), SYNC, EMCY (emergency +
error register/codes), TIME, and Heartbeat / Node guarding — a COB-ID
(Communication Object Identifier mapping to the 11-bit CAN identifier) allocated
by the predefined connection set as a function of the Node-ID (1..127), and the
EDS / DCF device-description files plus device profiles (CiA 401 generic I/O,
CiA 402 motion/drives). Applies the CiA 301 CANopen spec-canonical content to
L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(Object Dictionary + index/sub-index + PDO + SDO + NMT + COB-ID + the CiA-301
predefined connection set) read from the L-doc / input_doc CONTENT blob ONLY. It
NEVER reads the input-document filename or the benchmark folder name, and it
never fires on a bare protocol-name token alone (a name token injected into a
foreign doc cannot trigger it — the OD + PDO/SDO/NMT structure is required).

Sibling disambiguation — CANopen vs CAN / CAN-FD (the CAN family). CANopen is the
APPLICATION LAYER above CAN: it REQUIRES the Object Dictionary + PDO/SDO/NMT +
COB-ID + the CiA-301 structure. A plain CAN / CAN-FD controller spec describes
the CAN frame format, arbitration by identifier, bit stuffing, and error frames,
with NO Object Dictionary, NO PDO/SDO/NMT, NO COB-ID, and NO CiA reference — that
is NOT CANopen. The detector REQUIRES the CANopen-only structural vocabulary and
DEFERS when the doc is raw-CAN-primary (CAN frame / arbitration / bit stuffing /
error frame, no OD / PDO / SDO / NMT / CiA), so it cannot false-fire on a CAN or
CAN-FD data-link-layer spec.

Public entry: ``apply_canopen_synth(generated_docs_dir, is_canopen, canopen_ic_name)``.
Module-level ``is_canopen(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


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

# Canonical CANopen facts (CiA 301 application layer and communication profile).
_INDEX_BITS = 16
_SUBINDEX_BITS = 8
_NODE_ID_MIN = 1
_NODE_ID_MAX = 127
_COB_ID_BITS = 11  # COB-ID maps to the CAN base-frame 11-bit identifier.
_COMM_OBJECTS = ["PDO", "SDO", "NMT", "SYNC", "TIME", "EMCY", "Heartbeat"]
_NMT_STATES = ["Initialisation", "Pre-operational", "Operational", "Stopped"]
_SDO_TRANSFERS = ["expedited", "segmented", "block"]


def is_canopen(blob: str) -> bool:
    """Content-only CANopen detector with a CAN / CAN-FD sibling MUTEX.

    Fire on the CANopen structural signature: the Object Dictionary addressed by
    a 16-bit index + 8-bit sub-index, the PDO / SDO / NMT communication objects,
    the COB-ID (mapping to the CAN identifier), the Node-ID, and the CiA-301
    predefined connection set / standardized OD entries (0x1000 / 0x1018). DEFER
    if the doc is raw-CAN-primary (CAN frame / arbitration / bit stuffing /
    error frame with NO Object Dictionary / PDO / SDO / NMT / CiA), so a plain
    CAN or CAN-FD data-link-layer spec cannot false-fire. Reads ONLY the spec
    text `blob` — never a filename or benchmark name. Requires STRUCTURE, not a
    bare name token.
    """
    if not blob:
        return False
    low = blob.lower()

    # CANopen-only application-layer structural tokens (absent from a raw
    # CAN/CAN-FD data-link spec).
    obj_dict = ("object dictionary" in low
                or ("index" in low and "sub-index" in low
                    and "0x1000" in low))
    index_subindex = ("sub-index" in low or "subindex" in low) and "index" in low
    pdo = ("pdo" in low or "process data object" in low)
    sdo = ("sdo" in low or "service data object" in low)
    nmt = ("nmt" in low or "network management" in low)
    cob_id = ("cob-id" in low or "cob id" in low
              or "communication object identifier" in low)
    node_id = "node-id" in low or "node id" in low
    pre_operational = "pre-operational" in low or "preoperational" in low
    predefined_set = ("predefined connection set" in low
                      or "pre-defined connection set" in low)
    std_entries = ("0x1018" in low or "identity object" in low
                   or "0x1000" in low or "device type" in low)
    cia = ("cia 301" in low or "cia301" in low or "cia 306" in low
           or "can in automation" in low or "en 50325" in low
           or "canopen" in low)
    tpdo_rpdo = (("tpdo" in low or "rpdo" in low)
                 or ("transmit-pdo" in low or "receive-pdo" in low))
    emcy = "emcy" in low or "emergency object" in low
    heartbeat = "heartbeat" in low

    # Communication-object triple — PDO + SDO + NMT is the CANopen kernel.
    comm_triple = pdo and sdo and nmt

    canopen_structure = (
        obj_dict
        and comm_triple
        and (cob_id or node_id)
        and (index_subindex or std_entries or predefined_set)
    )

    # Sibling MUTEX: a raw CAN / CAN-FD data-link-layer doc keys on the CAN
    # frame format / arbitration / bit stuffing / error frame and carries NO
    # Object Dictionary, NO PDO/SDO/NMT, NO COB-ID, and NO CiA reference. If
    # those CAN-DLL tokens are present and the CANopen application-layer
    # structure is absent, defer (do NOT fire).
    can_dll_tokens = (
        ("data frame" in low or "remote frame" in low or "error frame" in low
         or "overload frame" in low or "bit stuffing" in low
         or ("dominant" in low and "recessive" in low)
         or "arbitration field" in low)
    )
    canopen_app_tokens = (
        obj_dict or pdo or sdo or nmt or cob_id or predefined_set
        or "canopen" in low or cia
    )
    can_primary = can_dll_tokens and not canopen_app_tokens
    if can_primary:
        return False

    return bool(
        canopen_structure
        or (comm_triple and cob_id and (cia or predefined_set))
        or (obj_dict and comm_triple and tpdo_rpdo and (cob_id or node_id))
    )


def apply_canopen_synth(generated_docs_dir: Path, is_canopen_flag: bool,
                        canopen_ic_name: Optional[str]) -> None:
    """Apply CiA 301 CANopen synth when the CANopen signature matched.

    Runs AFTER the CAN / CAN-FD synth in the runner; it force-assigns the
    CANopen application-layer facts so a sibling CAN/CAN-FD synth that fired
    first (CANopen layers on CAN) is overwritten by the CANopen-correct values.
    """
    if not is_canopen_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if canopen_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = canopen_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = canopen_ic_name
                d["ic_name"] = canopen_ic_name
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
# L1 — CANopen datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "CANopen Application Layer and Communication Profile (CiA 301)")
    d["version"] = "CiA 301 — CANopen application layer and communication profile"
    d["revised_date"] = "CiA 301 v4.2.0 (EN 50325-4)"
    d["manufacturer"] = "CAN in Automation (CiA) e. V."
    d["copyright"] = "© CAN in Automation (CiA) e. V."
    d["abstract"] = (
        "CANopen is the standardized higher-layer (application-layer) "
        "communication protocol that runs on top of a Controller Area Network "
        "(CAN) data link layer. Specified by CAN in Automation as CiA 301 (and "
        "registered as EN 50325-4), CANopen adds — above the raw CAN frame — an "
        "Object Dictionary (OD) addressed by a 16-bit index and an 8-bit "
        "sub-index, a predefined set of communication objects (PDO, SDO, NMT, "
        "SYNC, TIME, EMCY, heartbeat / node guarding), a network-management "
        "boot-up state machine, the COB-ID (communication object identifier, "
        "mapping to the 11-bit CAN identifier), and a default identifier "
        "allocation as a function of the Node-ID (1..127). Devices are described "
        "by an Electronic Data Sheet (EDS) / Device Configuration File (DCF) and "
        "standardized by device profiles such as CiA 401 (generic I/O) and CiA "
        "402 (drives and motion control). CANopen does NOT redefine the CAN "
        "frame, CAN arbitration, CAN bit stuffing, or the CAN error frame; it is "
        "the application layer ABOVE CAN.")
    d["keywords"] = [
        "CANopen", "CiA 301", "EN 50325-4", "CAN in Automation",
        "application layer", "object dictionary", "index", "sub-index",
        "COB-ID", "Node-ID", "PDO", "TPDO", "RPDO", "SDO", "NMT",
        "Network Management", "SYNC", "TIME", "EMCY", "emergency object",
        "heartbeat", "node guarding", "life guarding",
        "predefined connection set", "transmission type", "PDO mapping",
        "expedited transfer", "segmented transfer", "block transfer",
        "boot-up", "Pre-operational", "Operational", "Stopped",
        "error register", "identity object", "device type", "EDS", "DCF",
        "CiA 401", "CiA 402", "producer/consumer", "client/server",
    ]
    d["external_pins"] = [
        "CAN_H / CAN_L: the underlying CAN bus differential pair (defined by the "
        "CAN physical layer, ISO 11898-2) — CANopen carries its communication "
        "objects over this CAN bus.",
        "CANopen itself adds no new pins; it is an application-layer profile "
        "over the CAN data link / physical layer.",
    ]
    d["object_dictionary_index_bits"] = _INDEX_BITS
    d["object_dictionary_subindex_bits"] = _SUBINDEX_BITS
    d["node_id_range"] = {"min": _NODE_ID_MIN, "max": _NODE_ID_MAX}
    d["cob_id_bits"] = _COB_ID_BITS
    d["communication_objects"] = list(_COMM_OBJECTS)
    d["modes_of_operation"] = [
        {"name": "PDO (Process Data Object)",
         "role": "real-time process data exchange",
         "note": "Producer/consumer model; up to 8 data bytes per CAN frame "
                 "with no overhead beyond the COB-ID. TPDO (transmit) and RPDO "
                 "(receive); mapping + transmission types (synchronous / "
                 "asynchronous / event-driven)."},
        {"name": "SDO (Service Data Object)",
         "role": "object-dictionary configuration access",
         "note": "Client/server access to an entry by index and sub-index; "
                 "expedited (<=4 bytes), segmented (7-byte segments + toggle), "
                 "or block transfer. Default server SDO request COB-ID = "
                 "0x600+Node-ID, response = 0x580+Node-ID."},
        {"name": "NMT (Network Management)",
         "role": "network state control + error control",
         "note": "Master/slave state machine Initialisation -> Pre-operational "
                 "-> Operational <-> Stopped, driven by module-control commands "
                 "(start / stop / enter pre-operational / reset node / reset "
                 "communication) sent with COB-ID 0."},
    ]
    d["key_features"] = [
        "Standardized higher-layer (application-layer) protocol over CAN; CiA "
        "301 / EN 50325-4 by CAN in Automation.",
        "Object Dictionary (OD): each entry addressed by a 16-bit index + 8-bit "
        "sub-index; standardized entries 0x1000 device type, 0x1001 error "
        "register, 0x1018 identity object.",
        "Communication objects: PDO (real-time), SDO (OD access), NMT (network "
        "management), SYNC, TIME, EMCY (emergency), heartbeat / node guarding.",
        "COB-ID (communication object identifier) maps to the 11-bit CAN "
        "identifier; predefined connection set allocates default COB-IDs as a "
        "function of the Node-ID.",
        "Node-ID range 1..127; one NMT master and up to 127 NMT slaves.",
        "PDO: TPDO / RPDO, mapping parameters, transmission types "
        "(synchronous cyclic/acyclic, asynchronous/event-driven).",
        "SDO: client/server with expedited, segmented, and block transfer; SDO "
        "abort with a 32-bit abort code.",
        "NMT slave state machine: Initialisation -> Pre-operational -> "
        "Operational <-> Stopped; boot-up message after Initialisation.",
        "Error control: heartbeat (producer/consumer) OR node guarding / life "
        "guarding (mutually exclusive).",
        "EMCY emergency object: 16-bit error code + 8-bit error register + 5 "
        "manufacturer bytes; pre-defined error field (0x1003).",
        "Device described by EDS / DCF; device profiles CiA 401 (generic I/O) "
        "and CiA 402 (drives / motion control).",
        "CANopen is ABOVE CAN: it reuses the CAN frame, CAN arbitration, CAN "
        "bit stuffing, and the CAN error frame unchanged.",
    ]
    d["topology_summary"] = (
        "A CANopen network is a multi-drop CAN bus with one NMT master and up "
        "to 127 NMT slaves, each with a Node-ID (1..127). Communication objects "
        "(PDO/SDO/NMT/SYNC/TIME/EMCY/heartbeat) are carried over the CAN bus "
        "with COB-IDs allocated by the predefined connection set.")
    d["use_cases"] = [
        "Industrial automation and machine control over CAN",
        "Motion control / drives (CiA 402 servo, stepper, frequency inverter)",
        "Generic distributed I/O modules (CiA 401)",
        "In-vehicle and off-highway subsystems on a CAN bus",
        "Medical, maritime, and rail embedded networks using CANopen profiles",
    ]
    d["revision_history"] = [
        {"version": "CiA 301 v4.0", "date": "earlier",
         "description": "CANopen application layer and communication profile: "
                        "object dictionary, PDO/SDO/NMT/SYNC/EMCY, predefined "
                        "connection set."},
        {"version": "CiA 301 v4.1", "date": "later",
         "description": "Refinements to heartbeat / node guarding, SDO block "
                        "transfer, and PDO transmission types."},
        {"version": "CiA 301 v4.2.0", "date": "current",
         "description": "Current CANopen application layer and communication "
                        "profile; registered as EN 50325-4."},
    ]
    d["overview"] = (
        "CANopen (CiA 301) is the standardized application layer and "
        "communication profile for CAN-based networks. It uses the services and "
        "frame format of the CAN data link layer (ISO 11898) but adds the "
        "structure that makes CAN devices interoperable. The central data "
        "structure of every CANopen device is the Object Dictionary, a grouped "
        "list of objects each addressed by a 16-bit index and an 8-bit "
        "sub-index; the communication-profile area 0x1000-0x1FFF holds "
        "standardized entries such as 0x1000 device type, 0x1001 error register, "
        "and 0x1018 identity object. CANopen communication objects are carried "
        "over CAN frames whose identifier is the COB-ID; the predefined "
        "connection set assigns default COB-IDs as a function of the Node-ID "
        "(1..127). PDOs exchange real-time process data (producer/consumer, "
        "TPDO/RPDO, mapping + transmission types); SDOs give client/server "
        "access to the object dictionary (expedited / segmented / block "
        "transfer); NMT controls the device state machine (Initialisation -> "
        "Pre-operational -> Operational <-> Stopped) with module-control "
        "commands; SYNC provides synchronisation; TIME distributes time; EMCY "
        "signals emergencies; and heartbeat or node guarding provides error "
        "control. Devices are described by EDS / DCF files and standardized by "
        "device profiles (CiA 401 generic I/O, CiA 402 motion). CANopen is the "
        "application layer ABOVE CAN and does not change the CAN frame, "
        "arbitration, bit stuffing, or error frame.")
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
        "Standardized higher-layer (application-layer) communication profile "
        "over a Controller Area Network (CAN) data link layer. Defines an Object "
        "Dictionary, the PDO/SDO/NMT/SYNC/TIME/EMCY/heartbeat communication "
        "objects, the COB-ID and predefined connection set, and the NMT boot-up "
        "state machine. Standardized by CAN in Automation as CiA 301 / EN "
        "50325-4.")
    po["layer"] = (
        "Application layer ABOVE CAN: reuses the CAN frame, CAN arbitration, "
        "CAN bit stuffing, and the CAN error frame unchanged.")
    po["communication_models"] = ["producer/consumer (PDO, SYNC, EMCY)",
                                   "client/server (SDO)",
                                   "master/slave (NMT)"]
    po["object_dictionary_index_bits"] = _INDEX_BITS
    po["object_dictionary_subindex_bits"] = _SUBINDEX_BITS
    po["cob_id_bits"] = _COB_ID_BITS
    po["node_id_range"] = {"min": _NODE_ID_MIN, "max": _NODE_ID_MAX}
    po["communication_objects"] = list(_COMM_OBJECTS)
    po["nmt_states"] = list(_NMT_STATES)
    po["sdo_transfer_modes"] = list(_SDO_TRANSFERS)
    po["underlying_bus"] = "CAN (ISO 11898); COB-ID maps to the CAN identifier."
    d["functional_requirements"] = [
        {"id": "FR-OD-01", "text": "A CANopen device shall implement an Object "
         "Dictionary whose entries are addressed by a 16-bit index and an 8-bit "
         "sub-index; sub-index 0 of an array/record holds the number of "
         "entries."},
        {"id": "FR-OD-02", "text": "The device shall implement the mandatory "
         "object-dictionary entries: 0x1000 device type, 0x1001 error register, "
         "and the 0x1018 identity object (vendor-ID, product code, revision "
         "number, serial number)."},
        {"id": "FR-COB-03", "text": "Each communication object shall be carried "
         "by CAN frames whose CAN identifier is the COB-ID; in the CAN base "
         "frame format the COB-ID is 11 bits wide."},
        {"id": "FR-NODE-04", "text": "Each device shall have a Node-ID in the "
         "range 1..127; the predefined connection set allocates default COB-IDs "
         "as a function of the Node-ID."},
        {"id": "FR-PDO-05", "text": "The device shall support Process Data "
         "Objects (PDO): transmit-PDO (TPDO) and receive-PDO (RPDO) carrying up "
         "to 8 bytes, with PDO communication parameters (COB-ID, transmission "
         "type, inhibit time, event timer) and PDO mapping parameters."},
        {"id": "FR-PDO-06", "text": "PDO transmission types shall include "
         "synchronous acyclic (0), synchronous cyclic (1..240), RTR-only (252/"
         "253), and asynchronous / event-driven (254/255), referenced to the "
         "SYNC object where synchronous."},
        {"id": "FR-SDO-07", "text": "The device shall support at least one SDO "
         "server giving client/server access to its object dictionary by index "
         "and sub-index, with expedited (<=4 bytes), segmented (7-byte segments "
         "+ toggle bit), and optionally block transfer."},
        {"id": "FR-SDO-08", "text": "A failed SDO transfer shall be terminated "
         "by an SDO abort transfer carrying a 32-bit abort code."},
        {"id": "FR-NMT-09", "text": "The device shall implement the NMT slave "
         "state machine Initialisation -> Pre-operational -> Operational <-> "
         "Stopped; the NMT master controls it with module-control commands "
         "(start / stop / enter pre-operational / reset node / reset "
         "communication) sent with COB-ID 0."},
        {"id": "FR-BOOT-10", "text": "After Initialisation the device shall "
         "transmit a boot-up message (COB-ID 0x700+Node-ID, one data byte 0x00) "
         "and enter Pre-operational."},
        {"id": "FR-ERR-11", "text": "The device shall provide one error-control "
         "mechanism: heartbeat (producer heartbeat time 0x1017, consumer "
         "heartbeat time 0x1016) OR node guarding / life guarding (guard time "
         "0x100C, life time factor 0x100D) — not both at once."},
        {"id": "FR-EMCY-12", "text": "On an internal error the device shall "
         "transmit an emergency (EMCY) object once per event: a 16-bit "
         "emergency error code, the 8-bit error register (0x1001), and 5 "
         "manufacturer-specific bytes (default COB-ID 0x080+Node-ID)."},
        {"id": "FR-SYNC-13", "text": "The SYNC object shall provide a "
         "network-wide synchronisation signal (default COB-ID 0x080); the "
         "communication cycle period is object 0x1006; synchronous PDOs are "
         "sampled/actuated relative to SYNC."},
        {"id": "FR-EDS-14", "text": "The device shall be describable by an "
         "Electronic Data Sheet (EDS, CiA 306); a Device Configuration File "
         "(DCF) is an EDS filled in with the actual values and Node-ID of one "
         "concrete device."},
    ]
    d["error_response_conditions"] = [
        "SDO abort transfer with a 32-bit abort code (e.g. 0x06020000 object "
        "does not exist, 0x06090011 sub-index does not exist, 0x08000000 "
        "general error).",
        "EMCY emergency object transmitted on an internal error (error code + "
        "error register + manufacturer bytes).",
        "Heartbeat / node-guarding timeout indicates a lost or failed node.",
        "Underlying CAN error handling (error frames, error counters) is "
        "provided by the CAN data link layer beneath CANopen.",
    ]
    d["compliance_requirements"] = [
        "Object Dictionary with 16-bit index + 8-bit sub-index addressing.",
        "Mandatory entries 0x1000 device type, 0x1001 error register, 0x1018 "
        "identity object.",
        "PDO (TPDO/RPDO) with mapping + transmission types; SDO client/server "
        "(expedited/segmented/block); NMT state machine.",
        "COB-ID mapping to the CAN identifier; predefined connection set "
        "keyed on the Node-ID (1..127).",
        "SYNC, TIME, EMCY objects; heartbeat or node guarding error control.",
        "Boot-up message after Initialisation.",
        "EDS / DCF device description; conformance with the relevant device "
        "profile (CiA 401 / CiA 402 / ...).",
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
        "Object-dictionary-centric application-layer protocol over CAN. "
        "Communication objects (PDO / SDO / NMT / SYNC / TIME / EMCY / "
        "heartbeat) are carried over CAN frames whose identifier is the COB-ID. "
        "SDO is client/server access to the object dictionary by index and "
        "sub-index; PDO is producer/consumer real-time process data; NMT is "
        "master/slave network-state control.")
    d["communication_objects"] = [
        {"name": "PDO", "full": "Process Data Object",
         "model": "producer/consumer",
         "purpose": "Real-time process data; TPDO (transmit) and RPDO (receive); "
                    "up to 8 bytes, mapping + transmission types."},
        {"name": "SDO", "full": "Service Data Object",
         "model": "client/server",
         "purpose": "Read/write an object-dictionary entry by index and "
                    "sub-index; expedited / segmented / block transfer."},
        {"name": "NMT", "full": "Network Management",
         "model": "master/slave",
         "purpose": "Control the device NMT state machine and error control."},
        {"name": "SYNC", "full": "Synchronisation object",
         "model": "producer/consumer",
         "purpose": "Network-wide synchronisation signal (default COB-ID "
                    "0x080); synchronous PDOs reference it."},
        {"name": "TIME", "full": "Time-stamp object",
         "model": "producer/consumer",
         "purpose": "Distribute network time (default COB-ID 0x100, 6-byte "
                    "TIME_OF_DAY)."},
        {"name": "EMCY", "full": "Emergency object",
         "model": "producer/consumer",
         "purpose": "Signal an internal error (default COB-ID 0x080+Node-ID)."},
        {"name": "Heartbeat", "full": "Heartbeat / node guarding",
         "model": "producer/consumer (heartbeat) or master/slave (guarding)",
         "purpose": "Error control / liveness (COB-ID 0x700+Node-ID)."},
    ]
    d["nmt_module_control_commands"] = [
        {"cs": "0x01", "name": "Start remote node",
         "effect": "-> Operational"},
        {"cs": "0x02", "name": "Stop remote node", "effect": "-> Stopped"},
        {"cs": "0x80", "name": "Enter pre-operational",
         "effect": "-> Pre-operational"},
        {"cs": "0x81", "name": "Reset node",
         "effect": "-> Initialisation (reset application)"},
        {"cs": "0x82", "name": "Reset communication",
         "effect": "-> Initialisation (reset communication)"},
    ]
    d["sdo_transfer_protocols"] = [
        {"name": "Expedited transfer", "purpose": "Up to 4 data bytes carried "
         "directly in the single request/response frame (the fast common "
         "case)."},
        {"name": "Segmented transfer", "purpose": "Data larger than 4 bytes is "
         "split into 7-byte segments, each with a toggle bit."},
        {"name": "Block transfer", "purpose": "Optional high-throughput mode "
         "transferring a sequence of segments before a single acknowledge."},
    ]
    d["pdo_transmission_types"] = [
        {"value": "0", "meaning": "synchronous, acyclic (on next SYNC after a "
         "change)"},
        {"value": "1..240", "meaning": "synchronous, cyclic (every n-th SYNC)"},
        {"value": "252", "meaning": "synchronous, RTR-only"},
        {"value": "253", "meaning": "asynchronous, RTR-only"},
        {"value": "254", "meaning": "asynchronous, manufacturer-specific event"},
        {"value": "255", "meaning": "asynchronous, device-profile-specific "
         "event"},
    ]
    d["addressing"] = {
        "object_dictionary": {"index_bits": _INDEX_BITS,
                              "subindex_bits": _SUBINDEX_BITS,
                              "note": "Each OD entry is addressed by a 16-bit "
                                      "index and an 8-bit sub-index."},
        "cob_id_bits": _COB_ID_BITS,
        "node_id_range": {"min": _NODE_ID_MIN, "max": _NODE_ID_MAX},
        "note": "The COB-ID maps to the CAN identifier; default COB-IDs are "
                "allocated by the predefined connection set from the Node-ID.",
    }
    d["sdo_abort"] = {
        "abort_code_bits": 32,
        "examples": ["0x06020000 object does not exist",
                     "0x06090011 sub-index does not exist",
                     "0x08000000 general error"],
    }
    d["byte_oriented"] = True
    d["object_dictionary_based"] = True
    d["over_can"] = True
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / object-dictionary model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "In CANopen the 'register map' is the Object Dictionary (OD): a grouped "
        "list of all objects that influence the device, each addressed by a "
        "16-bit index and an 8-bit sub-index. SDO gives client/server access to "
        "the OD; the communication-profile area (0x1000-0x1FFF) holds the "
        "standardized communication entries below.")
    d["register_access"] = {
        "transport": "SDO (client/server) read (upload) / write (download) by "
                     "index and sub-index; PDO maps a subset of OD entries for "
                     "real-time exchange.",
        "purpose": "Configure and read the object dictionary entries that "
                   "define device and communication behaviour.",
    }
    d["object_dictionary_layout"] = [
        {"index_range": "0x0001-0x009F", "description": "data types"},
        {"index_range": "0x1000-0x1FFF",
         "description": "communication profile area (CiA 301)"},
        {"index_range": "0x2000-0x5FFF",
         "description": "manufacturer-specific profile area"},
        {"index_range": "0x6000-0x9FFF",
         "description": "standardised device profile area (CiA 401/402/...)"},
        {"index_range": "0xA000-0xBFFF",
         "description": "standardised interface profile area"},
    ]
    d["register_groups"] = [
        {"group": "Communication profile (0x1000-0x1FFF)", "fields": [
            "0x1000 device type (VAR)",
            "0x1001 error register (VAR)",
            "0x1003 pre-defined error field (ARRAY)",
            "0x1005 COB-ID SYNC message (VAR)",
            "0x1006 communication cycle period (VAR)",
            "0x1014 COB-ID emergency message EMCY (VAR)",
            "0x1016 consumer heartbeat time (ARRAY)",
            "0x1017 producer heartbeat time (VAR)",
            "0x1018 identity object (RECORD: vendor-ID / product code / "
            "revision number / serial number)",
            "0x100C guard time / 0x100D life time factor"]},
        {"group": "SDO parameters", "fields": [
            "0x1200 SDO server parameter (RECORD)",
            "0x1280 SDO client parameter (RECORD)"]},
        {"group": "PDO parameters", "fields": [
            "0x1400 RPDO communication parameter (first RPDO)",
            "0x1600 RPDO mapping parameter (first RPDO)",
            "0x1800 TPDO communication parameter (first TPDO)",
            "0x1A00 TPDO mapping parameter (first TPDO)"]},
    ]
    d["mandatory_entries"] = [
        {"index": "0x1000", "name": "Device type",
         "note": "32-bit: lower 16 bits = device profile number (e.g. 401, "
                 "402), upper 16 bits = additional information."},
        {"index": "0x1001", "name": "Error register",
         "note": "single byte; bits flag generic / current / voltage / "
                 "temperature / communication / profile / manufacturer error "
                 "classes."},
        {"index": "0x1018", "name": "Identity object",
         "note": "RECORD: sub1 vendor-ID, sub2 product code, sub3 revision "
                 "number, sub4 serial number."},
    ]
    d["protocol_fields"] = {
        "index_bits": _INDEX_BITS,
        "subindex_bits": _SUBINDEX_BITS,
        "cob_id_bits": _COB_ID_BITS,
        "node_id_range": {"min": _NODE_ID_MIN, "max": _NODE_ID_MAX},
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
        "CANopen is an application-layer protocol and defines no analog "
        "signaling of its own. The physical and electrical signaling are those "
        "of the underlying CAN bus (ISO 11898-2 high-speed CAN): a differential "
        "two-wire bus (CAN_H / CAN_L) with dominant and recessive bus states, "
        "NRZ bit encoding with bit stuffing, and arbitration by identifier. "
        "CANopen carries its COB-ID-addressed communication objects over that "
        "CAN physical layer.")
    d["modulation"] = (
        "Differential dominant/recessive on CAN_H / CAN_L (CAN physical layer, "
        "ISO 11898-2) — defined by CAN, not by CANopen.")
    d["clocking"] = (
        "The bit timing (baud rate) is the CAN bus bit timing; CANopen-relevant "
        "Layer Setting Services (CiA 305) can configure the Node-ID and the "
        "bit-timing over the bus. CANopen adds no separate clock.")
    d["underlying_physical_layer"] = {
        "standard": "ISO 11898-2 (high-speed CAN)",
        "medium": "differential two-wire bus (CAN_H / CAN_L)",
        "bus_states": ["dominant", "recessive"],
        "bit_encoding": "NRZ with bit stuffing (CAN)",
        "note": "CANopen is the application layer above this CAN physical / "
                "data-link layer.",
    }
    d["encoding_role_in_analog"] = (
        "CANopen does not define line coding; it relies on the CAN data link "
        "layer (NRZ + bit stuffing, dominant/recessive arbitration, CAN CRC and "
        "error frames). The CANopen-level integrity constructs are the SDO "
        "abort codes, the EMCY emergency object, and heartbeat / node guarding "
        "timeouts — all above the CAN frame.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / NMT state machine.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_nmt"] = [
        {"name": "Initialisation", "description": "Entered automatically after "
         "power-on or reset; the device initialises, then transmits the boot-up "
         "message and enters Pre-operational."},
        {"name": "Pre-operational", "description": "SDO and NMT communication "
         "are allowed; PDOs are NOT exchanged. Reached automatically after "
         "boot-up."},
        {"name": "Operational", "description": "All communication objects are "
         "active, including PDOs."},
        {"name": "Stopped", "description": "Only NMT and the error-control "
         "objects (heartbeat / node guarding) are allowed; SDOs and PDOs are "
         "stopped."},
    ]
    d["nmt_transitions"] = [
        {"from": "Initialisation", "to": "Pre-operational",
         "trigger": "automatic after boot-up message"},
        {"from": "Pre-operational", "to": "Operational",
         "trigger": "NMT Start remote node (CS=0x01)"},
        {"from": "Operational", "to": "Stopped",
         "trigger": "NMT Stop remote node (CS=0x02)"},
        {"from": "Operational", "to": "Pre-operational",
         "trigger": "NMT Enter pre-operational (CS=0x80)"},
        {"from": "any", "to": "Initialisation",
         "trigger": "NMT Reset node (CS=0x81) / Reset communication (CS=0x82)"},
    ]
    d["fsm_hints"] = {
        "trigger": "Power-up / reset -> Initialisation -> (boot-up message) -> "
        "Pre-operational. NMT Start remote node moves the device to "
        "Operational; Stop remote node moves it to Stopped.",
        "rule": "PDOs are exchanged ONLY in the Operational state; SDO and NMT "
        "communication are allowed in Pre-operational; only NMT and error "
        "control are allowed in Stopped.",
        "reset": "Reset node restarts the application and communication; reset "
        "communication restarts only the communication; both re-enter "
        "Initialisation.",
    }
    d["nmt_module_control"] = {
        "cob_id": 0,
        "frame": "2-byte CAN frame: byte 0 = command specifier (CS), byte 1 = "
                 "addressed Node-ID (0 = all nodes).",
        "priority": "COB-ID 0 is the highest CAN priority.",
    }
    d["boot_up"] = (
        "After Initialisation the device sends a boot-up message (COB-ID "
        "0x700+Node-ID, one data byte 0x00) to announce it has entered "
        "Pre-operational.")
    d["exit_from_reset_or_poweron"] = (
        "On power-up / reset the device enters Initialisation, initialises its "
        "object dictionary and communication, transmits the boot-up message, "
        "and enters Pre-operational; it then waits for the NMT master to start "
        "it (Operational).")
    d["error_control"] = {
        "heartbeat": "Producer cyclically sends a heartbeat (COB-ID "
                     "0x700+Node-ID, data byte = NMT state); consumers monitor "
                     "it against 0x1016; producer time = 0x1017.",
        "node_guarding": "The NMT master polls each slave with an RTR guarding "
                         "frame; the slave answers with NMT state + toggle bit; "
                         "guard time = 0x100C, life time factor = 0x100D.",
        "mutual_exclusion": "A device implements either heartbeat or node "
                            "guarding, not both at once.",
    }
    d["default_ready_state_recommendation"] = {
        "after_reset": "Initialisation then automatically Pre-operational after "
                       "the boot-up message.",
        "operational": "PDO exchange requires the Operational state, entered by "
                       "the NMT Start remote node command.",
    }
    d["timing_dependency_rule"] = (
        "A device must complete Initialisation and send the boot-up message "
        "before it is Pre-operational; PDOs are exchanged only in Operational. "
        "Synchronous PDOs are sampled/actuated relative to the SYNC object, "
        "whose period is the communication cycle period (0x1006).")
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
        {"name": "SDO read of object dictionary", "purpose": "Read any OD entry "
         "by index/sub-index (device type 0x1000, error register 0x1001, "
         "identity 0x1018, error field 0x1003)."},
        {"name": "EMCY emergency object", "purpose": "Reports an internal error "
         "with a 16-bit error code, the error register, and manufacturer "
         "bytes."},
        {"name": "Pre-defined error field (0x1003)", "purpose": "Array of the "
         "most recent emergency error codes (error history)."},
        {"name": "Heartbeat / node guarding", "purpose": "Liveness and NMT "
         "state observability of each node."},
        {"name": "NMT state", "purpose": "Current device state (Initialisation "
         "/ Pre-operational / Operational / Stopped) reported in heartbeat / "
         "guarding."},
    ]
    d["error_detection_mechanisms"] = [
        "SDO abort transfer with a 32-bit abort code on a failed OD access.",
        "EMCY emergency object on an internal error event.",
        "Heartbeat / node-guarding timeout detects a lost node.",
        "Error register (0x1001) bit-flags the active error classes.",
        "Underlying CAN error frames / error counters (CAN data link layer).",
    ]
    d["test_modes"] = [
        {"name": "Object-dictionary readback", "purpose": "SDO-read every "
         "supported OD entry to verify the device against its EDS."},
        {"name": "PDO mapping verification", "purpose": "Verify the configured "
         "PDO mapping (0x1600 / 0x1A00) and transmission types."},
        {"name": "LSS (CiA 305)", "purpose": "Inquire/assign Node-ID and "
         "bit-timing over the bus to bring up unconfigured nodes."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Boot-up", "trigger": "Device enters Pre-operational after "
         "Initialisation."},
        {"event": "EMCY", "trigger": "Internal error event."},
        {"event": "SDO abort", "trigger": "Failed object-dictionary access."},
        {"event": "Heartbeat / guard timeout", "trigger": "Lost node."},
        {"event": "SYNC", "trigger": "Periodic synchronisation object."},
        {"event": "NMT state change", "trigger": "Module-control command."},
    ]
    d["notes"] = (
        "CANopen exposes its observability through the object dictionary "
        "(SDO-readable entries), the EMCY emergency object and pre-defined "
        "error field (0x1003), heartbeat / node-guarding liveness, and the NMT "
        "state reported in those messages. Lower-level frame errors are handled "
        "by the CAN data link layer beneath CANopen. Chip-level JTAG/scan/BIST "
        "remain controller-vendor / SoC concerns.")
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
        "CANOPEN_STANDARD": "CiA 301 (EN 50325-4)",
        "APPLICATION_LAYER_OVER": "CAN (ISO 11898)",
        "OD_INDEX_BITS": _INDEX_BITS,
        "OD_SUBINDEX_BITS": _SUBINDEX_BITS,
        "COB_ID_BITS": _COB_ID_BITS,
        "NODE_ID_MIN": _NODE_ID_MIN,
        "NODE_ID_MAX": _NODE_ID_MAX,
        "COMM_OBJECT_COUNT": len(_COMM_OBJECTS),
        "COMM_OBJECTS": list(_COMM_OBJECTS),
        "NMT_STATE_COUNT": len(_NMT_STATES),
        "NMT_STATES": list(_NMT_STATES),
        "SDO_TRANSFER_MODES": list(_SDO_TRANSFERS),
        "PDO_MAX_DATA_BYTES": 8,
        "SDO_EXPEDITED_MAX_BYTES": 4,
        "SDO_SEGMENT_DATA_BYTES": 7,
        "SDO_ABORT_CODE_BITS": 32,
        "EMCY_ERROR_CODE_BITS": 16,
        "ERROR_REGISTER_BITS": 8,
        "OBJECT_DICTIONARY_BASED": True,
    })
    d["object_dictionary_constants"] = {
        "index_bits": _INDEX_BITS,
        "subindex_bits": _SUBINDEX_BITS,
        "mandatory_entries": ["0x1000 device type", "0x1001 error register",
                              "0x1018 identity object"],
        "comm_profile_area": "0x1000-0x1FFF",
    }
    d["cob_id_constants"] = {
        "cob_id_bits": _COB_ID_BITS,
        "maps_to": "CAN base-frame 11-bit identifier",
        "default_sdo_rx": "0x600 + Node-ID",
        "default_sdo_tx": "0x580 + Node-ID",
        "default_emcy": "0x080 + Node-ID",
        "default_heartbeat_bootup": "0x700 + Node-ID",
        "sync": "0x080",
        "time": "0x100",
        "nmt_module_control": 0,
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_application_layer": True,
        "over_can": True,
        "object_dictionary_based": True,
        "od_index_bits": _INDEX_BITS,
        "od_subindex_bits": _SUBINDEX_BITS,
        "cob_id_bits": _COB_ID_BITS,
        "node_id_min": _NODE_ID_MIN,
        "node_id_max": _NODE_ID_MAX,
        "communication_objects": list(_COMM_OBJECTS),
        "nmt_states": list(_NMT_STATES),
        "sdo_transfer_modes": list(_SDO_TRANSFERS),
        "pdo_tpdo_rpdo": True,
        "pdo_max_data_bytes": 8,
        "sdo_expedited_max_bytes": 4,
        "sdo_segment_data_bytes": 7,
        "sdo_abort_code_bits": 32,
        "emcy_error_code_bits": 16,
        "error_register_bits": 8,
        "heartbeat_or_node_guarding": True,
    })
    d["default_signal_values_when_idle"] = {
        "pre_operational": "Only SDO and NMT communication; no PDOs.",
        "operational": "All communication objects active including PDOs.",
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
    d["frame_waveform"] = {
        "carrier": "Each CANopen communication object is carried in one or more "
                   "CAN frames whose identifier is the COB-ID.",
        "pdo": "A PDO is a single CAN data frame, up to 8 data bytes, no "
               "overhead beyond the COB-ID.",
        "sdo": "An SDO request/response is an 8-byte CAN frame; expedited "
               "carries <=4 data bytes, segmented carries 7 data bytes per "
               "segment with a toggle bit.",
        "nmt": "An NMT module-control frame is 2 bytes (CS + Node-ID) with "
               "COB-ID 0.",
    }
    d["sync_waveform"] = {
        "sync": "Periodic SYNC object (default COB-ID 0x080); the communication "
                "cycle period is object 0x1006.",
        "synchronous_pdo": "Synchronous PDOs are sampled/actuated relative to "
                           "the SYNC; transmission type 1..240 means every "
                           "n-th SYNC.",
    }
    d["state_waveform"] = {
        "boot_up": "After Initialisation: boot-up message (0x700+Node-ID, byte "
                   "0x00) -> Pre-operational.",
        "start": "NMT Start remote node -> Operational (PDOs begin).",
        "heartbeat": "Producer heartbeat every producer-heartbeat-time (0x1017) "
                     "carrying the NMT state byte.",
    }
    d["general_timing_rule"] = (
        "PDOs are exchanged only in the Operational state. Synchronous PDOs are "
        "timed relative to the SYNC object (period 0x1006). The TPDO inhibit "
        "time bounds the minimum gap between two transmissions of the same "
        "TPDO; the event timer can trigger periodic transmission.")
    d["underlying_bit_timing"] = (
        "Bit-level timing on the wire is the CAN bus bit timing (NRZ + bit "
        "stuffing on CAN_H/CAN_L), defined by the CAN data link / physical "
        "layer, not by CANopen; LSS (CiA 305) can set the bit-timing.")
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
        "CANopen application-layer controller over a CAN bus: implements the "
        "Object Dictionary (16-bit index + 8-bit sub-index), the PDO (TPDO/"
        "RPDO) producer/consumer real-time exchange with mapping + transmission "
        "types, the SDO (client/server) object-dictionary access (expedited / "
        "segmented / block), the NMT state machine (Initialisation -> "
        "Pre-operational -> Operational <-> Stopped) with boot-up, SYNC / TIME "
        "/ EMCY, and heartbeat / node guarding — all carried over CAN frames "
        "addressed by COB-ID per the predefined connection set.")
    d["topology_description"] = (
        "A CANopen network is a CAN multi-drop bus with one NMT master and up "
        "to 127 NMT slaves, each with a Node-ID (1..127). The predefined "
        "connection set assigns default COB-IDs (SDO 0x600/0x580+Node-ID, EMCY "
        "0x080+Node-ID, heartbeat/boot-up 0x700+Node-ID, SYNC 0x080, TIME "
        "0x100, NMT control COB-ID 0).")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "canopen_standard": "CiA 301 (EN 50325-4)",
        "application_layer_over": "CAN (ISO 11898)",
        "od_index_bits": _INDEX_BITS,
        "od_subindex_bits": _SUBINDEX_BITS,
        "cob_id_bits": _COB_ID_BITS,
        "node_id_range": {"min": _NODE_ID_MIN, "max": _NODE_ID_MAX},
        "communication_objects": list(_COMM_OBJECTS),
        "nmt_states": list(_NMT_STATES),
        "sdo_transfer_modes": list(_SDO_TRANSFERS),
        "error_control": "heartbeat OR node guarding (mutually exclusive)",
        "device_description": "EDS / DCF (CiA 306)",
        "device_profiles": ["CiA 401 generic I/O", "CiA 402 drives / motion"],
        "interfaces": {"can": "CAN_H / CAN_L bus",
                       "sdo": "client/server OD access",
                       "pdo": "producer/consumer process data"},
    })
    d["interface_categories"] = [
        "CAN bus interface — carries all CANopen communication objects (COB-ID "
        "maps to the CAN identifier).",
        "Object-dictionary interface — SDO client/server access by index / "
        "sub-index.",
        "Process-data interface — PDO (TPDO/RPDO) producer/consumer mapping.",
        "Network-management interface — NMT module-control + error control "
        "(heartbeat / node guarding).",
    ]
    d["interconnect_topologies_supported"] = [
        "CAN multi-drop bus with one NMT master and up to 127 NMT slaves.",
        "Producer/consumer PDO distribution (one producer, many consumers).",
        "Client/server SDO configuration access.",
        "Predefined connection set default COB-ID allocation by Node-ID.",
    ]
    d["default_signal_values_when_omitted"] = (
        "An unconfigured node uses the predefined connection set so it is "
        "operable with its default COB-IDs; LSS (CiA 305) can assign the "
        "Node-ID and bit-timing when several nodes initially share defaults.")
    d["soc_dependent_items"] = [
        "Node-ID assignment (1..127) and CAN bit-timing (baud rate).",
        "Object-dictionary content (manufacturer + device-profile entries).",
        "Number and mapping of PDOs (TPDO / RPDO) and transmission types.",
        "Error-control choice: heartbeat or node guarding, and timings.",
        "Device profile (CiA 401 / CiA 402 / ...) and its application objects.",
        "Underlying CAN controller / transceiver (physical layer).",
    ]
    d["device_classes_examples"] = [
        "CANopen NMT master / configuration manager",
        "CiA 401 generic I/O module (digital / analogue I/O)",
        "CiA 402 drive / motion controller (servo, stepper, inverter)",
        "CiA 406 encoder",
        "Sensor / actuator CANopen slave",
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
        "partial - the specification defines protocol behaviors rather than an "
        "embedded testbench; the categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "Object dictionary: SDO-read/write entries by index + sub-index; "
        "mandatory 0x1000 / 0x1001 / 0x1018.",
        "NMT state machine: Initialisation -> boot-up -> Pre-operational -> "
        "Operational <-> Stopped via module-control commands.",
        "Boot-up message after Initialisation (0x700+Node-ID, byte 0x00).",
        "PDO: TPDO / RPDO mapping (0x1600 / 0x1A00) and transmission types "
        "(synchronous / asynchronous / event-driven).",
        "SDO: expedited (<=4 bytes), segmented (7-byte segments + toggle), "
        "block transfer; SDO abort with 32-bit code.",
        "SYNC: periodic SYNC drives synchronous PDOs; communication cycle "
        "period (0x1006).",
        "EMCY: emergency object on error (code + error register + manufacturer "
        "bytes); pre-defined error field (0x1003).",
        "Error control: heartbeat (0x1016 / 0x1017) OR node guarding (0x100C / "
        "0x100D) timeout.",
        "Predefined connection set: default COB-IDs as a function of Node-ID "
        "(1..127).",
        "Device profile conformance (CiA 401 / CiA 402 application objects).",
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
        {"field": "Identity object (0x1018)",
         "location": "object dictionary",
         "note": "Vendor-ID (assigned by CiA), product code, revision number, "
                 "serial number; typically factory-set, not a protocol-fixed "
                 "OTP concept."},
        {"field": "Device type (0x1000)",
         "location": "object dictionary",
         "note": "Device profile number (lower 16 bits) + additional info; "
                 "fixed for a product."},
        {"field": "Node-ID",
         "location": "device configuration",
         "note": "Set by hardware switch, LSS (CiA 305), or configuration; "
                 "1..127."},
        {"field": "EDS / DCF defaults",
         "location": "device description file",
         "note": "Default values for OD entries; stored / configured, not "
                 "OTP-fixed."},
    ]
    d["notes"] = (
        "CANopen does not define OTP/fuse content as a protocol concept. The "
        "identity object (vendor-ID / product code / revision / serial), device "
        "type, and Node-ID are device configuration (often factory-set or "
        "assigned via LSS). The store/restore parameter objects (0x1010 / "
        "0x1011) let a device persist OD values to non-volatile memory, but the "
        "standard only requires they be configurable, not OTP-fixed.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["bootup_sequence"] = [
        "1. Power-up / reset -> the device enters Initialisation.",
        "2. The device initialises its object dictionary and communication.",
        "3. The device transmits the boot-up message (COB-ID 0x700+Node-ID, one "
        "data byte 0x00).",
        "4. The device enters Pre-operational (SDO and NMT allowed, no PDOs).",
    ]
    d["nmt_start_sequence"] = [
        "1. The NMT master sends Start remote node (COB-ID 0, CS=0x01, "
        "Node-ID).",
        "2. The addressed slave (or all nodes if Node-ID 0) enters Operational.",
        "3. All communication objects, including PDOs, become active.",
    ]
    d["sdo_access_sequence"] = [
        "1. The SDO client sends a download (write) or upload (read) request to "
        "the server SDO (COB-ID 0x600+Node-ID) addressing an OD index + "
        "sub-index.",
        "2. Expedited transfers carry up to 4 data bytes in the single frame; "
        "larger data uses segmented (7-byte segments + toggle) or block "
        "transfer.",
        "3. The server replies on COB-ID 0x580+Node-ID, or aborts with a 32-bit "
        "abort code on failure.",
    ]
    d["pdo_exchange_sequence"] = [
        "1. In Operational, a TPDO producer transmits its mapped process data "
        "(up to 8 bytes) per its transmission type.",
        "2. Synchronous TPDOs (type 1..240) transmit relative to the SYNC "
        "object; asynchronous TPDOs (254/255) transmit on an event / event "
        "timer, bounded by the inhibit time.",
        "3. RPDO consumers receive the data and apply it to their mapped OD "
        "entries.",
    ]
    d["emcy_sequence"] = [
        "1. On an internal error the device sets the relevant bit in the error "
        "register (0x1001).",
        "2. It transmits one EMCY object (COB-ID 0x080+Node-ID): 16-bit error "
        "code + error register + 5 manufacturer bytes.",
        "3. The error code is recorded in the pre-defined error field (0x1003).",
    ]
    d["error_control_sequence"] = [
        "1. Heartbeat: the producer sends a heartbeat (0x700+Node-ID) carrying "
        "its NMT state every producer-heartbeat-time (0x1017); a consumer times "
        "it out per 0x1016.",
        "2. Node guarding: the NMT master sends an RTR guarding frame; the "
        "slave answers with NMT state + toggle bit; a missed answer within "
        "guard time x life time factor is a life-guarding event.",
    ]
    d["reset_sequence"] = [
        "1. NMT Reset node (CS=0x81) restarts the application and "
        "communication; Reset communication (CS=0x82) restarts only the "
        "communication.",
        "2. The device re-enters Initialisation, re-sends the boot-up message, "
        "and returns to Pre-operational.",
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
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "CAN bit timing / baud rate", "purpose": "Verify the "
         "underlying CAN bit timing (sample point, baud rate) the CANopen "
         "device runs on; settable via LSS (CiA 305)."},
        {"name": "SYNC period", "purpose": "Confirm the SYNC object period "
         "(communication cycle period 0x1006) and synchronous-PDO timing."},
        {"name": "Heartbeat / guard timing", "purpose": "Validate producer "
         "heartbeat time (0x1017) and node-guarding guard time x life time "
         "factor (0x100C / 0x100D)."},
        {"name": "TPDO inhibit / event timer", "purpose": "Measure the minimum "
         "gap (inhibit time) and event-timer period of asynchronous TPDOs."},
        {"name": "Boot-up latency", "purpose": "Confirm the device sends its "
         "boot-up message and reaches Pre-operational within spec after "
         "reset."},
        {"name": "SDO round-trip", "purpose": "Confirm SDO upload/download "
         "round-trip and abort behaviour."},
    ]
    d["notes"] = (
        "CANopen characterization centers on the timing of the application-"
        "layer objects: SYNC period (0x1006), heartbeat / node-guarding timing "
        "(0x1017 / 0x100C / 0x100D), TPDO inhibit time and event timer, and "
        "boot-up latency, on top of the underlying CAN bit timing (set via "
        "LSS). Physical-layer (CAN_H/CAN_L) electrical calibration is a CAN / "
        "transceiver concern; conformance is established by CiA conformance "
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
    f["spec_version"] = (
        "CiA 301 v4.2.0 — CANopen application layer and communication profile "
        "(EN 50325-4)")
    f["previous_versions"] = [
        "CiA 301 v4.0 — CANopen application layer: object dictionary, "
        "PDO/SDO/NMT/SYNC/EMCY, predefined connection set.",
        "CiA 301 v4.1 — refinements to heartbeat / node guarding, SDO block "
        "transfer, and PDO transmission types.",
    ]
    f["key_changes"] = [
        {"version": "CiA 301 v4.1", "summary": "Clarified heartbeat / node "
         "guarding error control, SDO block transfer, and PDO transmission "
         "types; consolidated the predefined connection set."},
        {"version": "CiA 301 v4.2.0", "summary": "Current CANopen application "
         "layer and communication profile; the object dictionary, "
         "PDO/SDO/NMT/SYNC/TIME/EMCY/heartbeat objects, and COB-ID allocation "
         "are carried forward; registered as EN 50325-4."},
    ]
    f["related_specifications"] = [
        {"spec": "CiA 305", "summary": "Layer Setting Services (LSS): assign "
         "Node-ID and bit-timing over the bus."},
        {"spec": "CiA 306", "summary": "Electronic Data Sheet (EDS) "
         "specification."},
        {"spec": "CiA 401", "summary": "Device profile for generic I/O "
         "modules."},
        {"spec": "CiA 402", "summary": "Device profile for drives and motion "
         "control."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Application_layer_not_CAN",
         "rule": "CANopen is the application layer ABOVE CAN; it reuses the CAN "
                 "frame, arbitration, bit stuffing, and error frame unchanged.",
         "trap": "Treating CANopen as a redefinition of the CAN data link "
                 "layer is wrong — a raw CAN controller with no object "
                 "dictionary / PDO / SDO / NMT is NOT CANopen."},
        {"trap_name": "PDO_only_in_Operational",
         "rule": "PDOs are exchanged only in the Operational state.",
         "trap": "Expecting PDO traffic in Pre-operational or Stopped is "
                 "wrong."},
        {"trap_name": "Heartbeat_xor_node_guarding",
         "rule": "A device uses heartbeat OR node guarding, not both.",
         "trap": "Enabling both error-control mechanisms at once is "
                 "non-conformant."},
        {"trap_name": "COB_ID_maps_to_CAN_identifier",
         "rule": "The COB-ID maps to the CAN identifier; the predefined "
                 "connection set allocates defaults from the Node-ID.",
         "trap": "Assuming the COB-ID is independent of the CAN identifier is "
                 "wrong."},
    ]
    f["version_naming_history_note"] = (
        "CANopen is standardized by CAN in Automation (CiA) as CiA 301, the "
        "application layer and communication profile, registered as the "
        "European standard EN 50325-4. The version 4 series (v4.0 / v4.1 / "
        "v4.2.0) defines the object dictionary, the PDO/SDO/NMT/SYNC/TIME/EMCY/"
        "heartbeat communication objects, the COB-ID predefined connection set, "
        "and the NMT boot-up state machine. Companion specs (CiA 305 LSS, CiA "
        "306 EDS, CiA 401 / 402 device profiles) build on CiA 301.")
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
    f["predefined_connection_set_table"] = {
        "header_columns": ["Object", "Function code", "Default COB-ID"],
        "rows": [
            ["NMT module control", "0000", "0x000 (broadcast)"],
            ["SYNC", "-", "0x080 (broadcast)"],
            ["EMCY", "0001", "0x081-0x0FF (0x080+Node-ID)"],
            ["TIME", "-", "0x100 (broadcast)"],
            ["TPDO1", "0011", "0x181-0x1FF"],
            ["RPDO1", "0100", "0x201-0x27F"],
            ["TPDO2", "0101", "0x281-0x2FF"],
            ["RPDO2", "0110", "0x301-0x37F"],
            ["TPDO3", "0111", "0x381-0x3FF"],
            ["RPDO3", "1000", "0x401-0x47F"],
            ["TPDO4", "1001", "0x481-0x4FF"],
            ["RPDO4", "1010", "0x501-0x57F"],
            ["SDO (tx, server->client)", "1011", "0x581-0x5FF (0x580+Node-ID)"],
            ["SDO (rx, client->server)", "1100", "0x601-0x67F (0x600+Node-ID)"],
            ["NMT error control (heartbeat/guarding/boot-up)", "1110",
             "0x701-0x77F (0x700+Node-ID)"],
        ],
    }
    f["communication_object_table"] = {
        "header_columns": ["Object", "Full name", "Model"],
        "rows": [
            ["PDO", "Process Data Object", "producer/consumer"],
            ["SDO", "Service Data Object", "client/server"],
            ["NMT", "Network Management", "master/slave"],
            ["SYNC", "Synchronisation object", "producer/consumer"],
            ["TIME", "Time-stamp object", "producer/consumer"],
            ["EMCY", "Emergency object", "producer/consumer"],
            ["Heartbeat", "Heartbeat / node guarding", "error control"],
        ],
    }
    f["nmt_command_table"] = {
        "header_columns": ["CS", "Command", "Resulting state"],
        "rows": [
            ["0x01", "Start remote node", "Operational"],
            ["0x02", "Stop remote node", "Stopped"],
            ["0x80", "Enter pre-operational", "Pre-operational"],
            ["0x81", "Reset node", "Initialisation (reset application)"],
            ["0x82", "Reset communication", "Initialisation (reset comms)"],
        ],
    }
    f["pdo_transmission_type_table"] = {
        "header_columns": ["Value", "Meaning"],
        "rows": [
            ["0", "synchronous, acyclic"],
            ["1..240", "synchronous, cyclic (every n-th SYNC)"],
            ["252", "synchronous, RTR-only"],
            ["253", "asynchronous, RTR-only"],
            ["254", "asynchronous, manufacturer-specific event"],
            ["255", "asynchronous, device-profile-specific event"],
        ],
    }
    f["mandatory_object_table"] = {
        "header_columns": ["Index", "Object", "Type"],
        "rows": [
            ["0x1000", "Device type", "VAR"],
            ["0x1001", "Error register", "VAR"],
            ["0x1018", "Identity object", "RECORD"],
            ["0x1200", "SDO server parameter", "RECORD"],
            ["0x1400", "RPDO communication parameter", "RECORD"],
            ["0x1600", "RPDO mapping parameter", "RECORD"],
            ["0x1800", "TPDO communication parameter", "RECORD"],
            ["0x1A00", "TPDO mapping parameter", "RECORD"],
        ],
    }
    f["sdo_transfer_table"] = {
        "header_columns": ["Mode", "Description"],
        "rows": [
            ["expedited", "<=4 data bytes in the single frame"],
            ["segmented", "7-byte segments with a toggle bit"],
            ["block", "sequence of segments before one acknowledge"],
        ],
    }
    f["encoding_note"] = (
        "CANopen defines no line code; the bits on the wire are CAN (NRZ + bit "
        "stuffing). The CANopen-level encodings are the COB-ID allocation "
        "(predefined connection set keyed on the Node-ID), the object "
        "dictionary index/sub-index addressing, the PDO mapping entries "
        "(index/sub-index/length), the PDO transmission types, and the NMT "
        "command specifiers.")
    f["tables"] = [
        "Predefined connection set (default COB-ID by function code / Node-ID)",
        "Communication-object table (PDO/SDO/NMT/SYNC/TIME/EMCY/heartbeat)",
        "NMT module-control command table (CS -> state)",
        "PDO transmission-type table (0 / 1..240 / 252..255)",
        "Mandatory / standardized object-dictionary entry table",
        "SDO transfer table (expedited / segmented / block)",
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
        "Object Dictionary addressed by a 16-bit index + 8-bit sub-index.",
        "Mandatory entries 0x1000 device type, 0x1001 error register, 0x1018 "
        "identity object.",
        "PDO (TPDO/RPDO) with mapping + transmission types; SDO client/server "
        "(expedited/segmented/block); NMT state machine.",
        "COB-ID mapping to the CAN identifier; predefined connection set keyed "
        "on the Node-ID (1..127).",
        "SYNC, TIME, EMCY objects; one error-control mechanism (heartbeat or "
        "node guarding).",
        "Boot-up message after Initialisation; NMT states Initialisation -> "
        "Pre-operational -> Operational <-> Stopped.",
        "EDS / DCF device description; conformance with the relevant device "
        "profile.",
    ]
    f["must_not_have_properties"] = [
        "A redefinition of the CAN frame, CAN arbitration, CAN bit stuffing, or "
        "the CAN error frame (those are the CAN data link layer, used "
        "unchanged).",
        "PDO traffic outside the Operational state.",
        "Both heartbeat and node guarding enabled at the same time.",
        "A raw CAN controller with no object dictionary / PDO / SDO / NMT "
        "(that is plain CAN, not CANopen).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "SDO abort", "trigger": "Failed OD access; a 32-bit abort code "
         "is returned (e.g. object/sub-index does not exist)."},
        {"mode": "EMCY", "trigger": "Internal error event; emergency object "
         "transmitted with code + error register."},
        {"mode": "Heartbeat / guard timeout", "trigger": "A monitored node "
         "fails to report within its time -> node-lost event."},
        {"mode": "Wrong-state PDO", "trigger": "PDO exchanged outside "
         "Operational -> non-conformant."},
    ]
    f["min_requirement_constraint"] = (
        "A minimal CANopen device must implement the Object Dictionary "
        "(0x1000 / 0x1001 / 0x1018), at least one SDO server, the NMT slave "
        "state machine with boot-up, one error-control mechanism, and a Node-ID "
        "(1..127) with the predefined connection set.")
    f["reset_behavior_compliance"] = (
        "NMT Reset node / Reset communication re-enters Initialisation; the "
        "device re-sends the boot-up message and returns to Pre-operational.")
    f["canopen_distinguishers"] = (
        "CANopen is identified by ALL of: an Object Dictionary addressed by a "
        "16-bit index + 8-bit sub-index with standardized entries (0x1000 "
        "device type, 0x1001 error register, 0x1018 identity); the PDO / SDO / "
        "NMT communication objects (plus SYNC / TIME / EMCY / heartbeat); the "
        "COB-ID mapping to the CAN identifier with a predefined connection set "
        "keyed on the Node-ID (1..127); the NMT boot-up state machine "
        "(Initialisation -> Pre-operational -> Operational <-> Stopped); and "
        "EDS / DCF device description, standardized by CiA 301 (EN 50325-4). "
        "This is distinct from raw CAN / CAN-FD (the data link layer: CAN frame "
        "format, arbitration by identifier, bit stuffing, and error frames, "
        "with NO object dictionary, PDO, SDO, NMT, or COB-ID) — CANopen is the "
        "application layer ABOVE CAN.")
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
        {"name": "CAN bus (CAN_H / CAN_L)",
         "direction": "shared multi-drop",
         "purpose": "Carries all CANopen communication objects; each object's "
                    "CAN identifier is its COB-ID.",
         "active_levels": "dominant / recessive (CAN physical layer)",
         "idle_level": "recessive"},
        {"name": "COB-ID (logical)",
         "direction": "addressing",
         "purpose": "The CAN identifier of a communication object; maps the "
                    "predefined connection set onto the bus.",
         "active_levels": "N/A", "idle_level": "N/A"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Pre-operational", "meaning": "SDO and NMT communication "
         "allowed; no PDOs."},
        {"name": "Operational", "meaning": "All communication objects active "
         "including PDOs."},
        {"name": "Stopped", "meaning": "Only NMT and error control allowed."},
    ]
    f["communication_object_summary"] = [
        {"class": "Communication object", "members": list(_COMM_OBJECTS),
         "count": len(_COMM_OBJECTS)},
        {"class": "NMT state", "members": list(_NMT_STATES),
         "count": len(_NMT_STATES)},
        {"class": "SDO transfer mode", "members": list(_SDO_TRANSFERS),
         "count": len(_SDO_TRANSFERS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "communication_object_count": len(_COMM_OBJECTS),
        "nmt_state_count": len(_NMT_STATES),
        "od_index_bits": _INDEX_BITS,
        "od_subindex_bits": _SUBINDEX_BITS,
        "cob_id_bits": _COB_ID_BITS,
        "node_id_min": _NODE_ID_MIN,
        "node_id_max": _NODE_ID_MAX,
        "pdo_max_data_bytes": 8,
    })
    f["global_signals"] = [
        {"name": "SYNC", "purpose": "Network-wide synchronisation (default "
         "COB-ID 0x080) referenced by synchronous PDOs."},
        {"name": "TIME", "purpose": "Network time distribution (default COB-ID "
         "0x100)."},
        {"name": "NMT module control", "purpose": "Network-wide state control "
         "(COB-ID 0, highest priority)."},
        {"name": "Node-ID", "purpose": "1..127 identifier; keys the predefined "
         "connection set for the device's COB-IDs."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Every communication object is carried over a CAN frame "
        "whose identifier is its COB-ID, allocated by the predefined connection "
        "set from the Node-ID. A device must reach Operational (via NMT Start "
        "remote node) before PDOs flow; SDO and NMT are available from "
        "Pre-operational.",
        "data_dependency": "A synchronous PDO depends on the SYNC object; an "
        "SDO access depends on the addressed object existing in the object "
        "dictionary (index + sub-index); error control (heartbeat / guarding) "
        "depends on the configured times.",
    }
    f["handshake_pairs"] = [
        {"name": "NMT command / state change", "from": "NMT master",
         "to": "NMT slave", "rule": "Module-control command (COB-ID 0) drives "
                 "the slave's NMT state."},
        {"name": "SDO request / response", "from": "SDO client",
         "to": "SDO server", "rule": "Client reads/writes an OD entry "
                 "(0x600+Node-ID); server replies (0x580+Node-ID) or aborts."},
        {"name": "Boot-up", "from": "device", "to": "network",
         "rule": "After Initialisation the device announces Pre-operational "
                 "(0x700+Node-ID, byte 0x00)."},
        {"name": "Heartbeat", "from": "producer", "to": "consumer",
         "rule": "Cyclic heartbeat carries the NMT state; monitored against "
                 "the consumer heartbeat time."},
        {"name": "Node guarding", "from": "NMT master", "to": "NMT slave",
         "rule": "RTR guarding frame; slave answers NMT state + toggle bit."},
    ]
    f["ordering_rules"] = {
        "bus_arbitration": "Bus access is by CAN arbitration on the identifier "
        "(COB-ID); a lower COB-ID has higher priority. NMT control (COB-ID 0) "
        "is highest.",
        "state_order": "Initialisation -> Pre-operational -> Operational; PDOs "
        "only in Operational.",
        "sync_order": "Synchronous PDOs are ordered relative to the SYNC "
        "object.",
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
        "Multi-drop CAN bus shared by all nodes. A CANopen network has one NMT "
        "master and up to 127 NMT slaves, each with a Node-ID (1..127). "
        "Communication objects are distributed by COB-ID using the "
        "producer/consumer (PDO/SYNC/EMCY), client/server (SDO), and "
        "master/slave (NMT) models.")
    f["supported_topologies"] = [
        {"name": "CAN multi-drop bus", "description": "All nodes share the CAN "
         "bus; bus access is by CAN arbitration on the COB-ID."},
        {"name": "Producer/consumer (PDO)", "description": "One producer "
         "broadcasts a PDO; any number of consumers receive it."},
        {"name": "Client/server (SDO)", "description": "An SDO client accesses "
         "the object dictionary of an SDO server."},
        {"name": "Master/slave (NMT)", "description": "One NMT master controls "
         "the NMT state of all slaves."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "NMT master", "description": "Controls the NMT state machine "
         "of every slave (start / stop / reset) and may manage configuration."},
        {"role": "NMT slave", "description": "A CANopen device that implements "
         "the OD and the NMT slave state machine; up to 127 per network."},
        {"role": "SDO client", "description": "Reads/writes OD entries of a "
         "server (often the master or a config tool)."},
        {"role": "SDO server", "description": "Exposes its object dictionary "
         "for client access."},
        {"role": "PDO producer / consumer", "description": "Produces (TPDO) or "
         "consumes (RPDO) real-time process data."},
    ]
    f["interconnect_role"] = (
        "CANopen distributes data over a shared CAN bus by COB-ID. Real-time "
        "process data uses producer/consumer PDOs (broadcast, low overhead); "
        "configuration uses client/server SDOs (confirmed, addressed by index/"
        "sub-index); network state uses master/slave NMT. The predefined "
        "connection set makes a node operable with default COB-IDs derived from "
        "its Node-ID.")
    f["addressing_methods"] = ["COB-ID (CAN identifier) via predefined "
                              "connection set", "Node-ID (1..127)",
                              "object-dictionary index + sub-index (SDO)"]
    f["ordering_guarantees"] = {
        "arbitration": "CAN arbitration on the COB-ID gives a lower COB-ID "
        "higher priority; NMT control (COB-ID 0) is highest.",
        "pdo": "PDOs are exchanged only in Operational; synchronous PDOs are "
        "ordered relative to SYNC.",
        "sdo": "SDO is a confirmed client/server exchange.",
    }
    f["memory_vs_peripheral_regions"] = (
        "CANopen is not memory-mapped on a CPU bus; the device state is the "
        "Object Dictionary, addressed by a 16-bit index and 8-bit sub-index, "
        "reachable over SDO. Communication objects are addressed on the bus by "
        "COB-ID, not by a memory address.")
    dc = _ensure_dict(f, "device_classification")
    dc["nmt_master"] = "Controls NMT state of all slaves; manages the network."
    dc["nmt_slave"] = "CANopen device with an OD and NMT slave state machine."
    dc["sdo_client"] = "Accesses a server's object dictionary."
    dc["sdo_server"] = "Exposes its object dictionary for access."
    dc["pdo_producer_consumer"] = "Produces / consumes real-time process data."
    f["default_signal_values_evidence_tables"] = [
        "CANopen reference model (producer/consumer, client/server, "
        "master/slave)",
        "Predefined connection set figure (default COB-ID by Node-ID)",
        "NMT state machine diagram (Initialisation / Pre-operational / "
        "Operational / Stopped)",
        "Object dictionary layout (communication / manufacturer / device "
        "profile areas)",
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
    f["protocol_constraints"] = {
        "application_layer_over": "CAN (ISO 11898)",
        "od_index_bits": _INDEX_BITS,
        "od_subindex_bits": _SUBINDEX_BITS,
        "cob_id_bits": _COB_ID_BITS,
        "node_id_range": {"min": _NODE_ID_MIN, "max": _NODE_ID_MAX},
        "communication_objects": list(_COMM_OBJECTS),
        "nmt_states": list(_NMT_STATES),
        "sdo_transfer_modes": list(_SDO_TRANSFERS),
        "pdo_max_data_bytes": 8,
        "error_control": "heartbeat XOR node guarding",
    }
    f["notes"] = (
        "CANopen is an application-layer communication profile (CiA 301): it "
        "fixes the object-dictionary structure (16-bit index + 8-bit "
        "sub-index), the PDO/SDO/NMT/SYNC/TIME/EMCY/heartbeat objects, the "
        "COB-ID predefined connection set (Node-ID 1..127), and the NMT boot-up "
        "state machine. It does NOT impose PDK-specific SDC / floorplan "
        "constraints; the bit timing and electrical characteristics belong to "
        "the underlying CAN data link / physical layer (ISO 11898). The "
        "interoperability-critical constraints are the mandatory OD entries, "
        "the predefined connection set, the PDO/SDO/NMT behaviour, and the "
        "device-profile conformance.")
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
        {"name": "SDO object-dictionary readback", "purpose": "Read every "
         "supported OD entry by index/sub-index to verify the device against "
         "its EDS."},
        {"name": "EMCY + pre-defined error field (0x1003)", "purpose": "Error "
         "history and active error observability."},
        {"name": "Heartbeat / node guarding", "purpose": "Node liveness and "
         "NMT-state observability."},
        {"name": "LSS (CiA 305)", "purpose": "Inquire / assign Node-ID and "
         "bit-timing over the bus."},
        {"name": "Error register (0x1001)", "purpose": "Active error-class "
         "flags."},
    ]
    f["internal_diagnostics_observability"] = [
        "NMT state (Initialisation / Pre-operational / Operational / Stopped).",
        "Object-dictionary entry values (SDO-readable).",
        "Emergency error codes (EMCY + 0x1003 error field).",
        "Heartbeat / node-guarding liveness.",
        "Error register (0x1001) bit-flags.",
    ]
    f["out_of_band_test_facilities"] = [
        "CiA conformance testing for CANopen devices.",
        "Underlying CAN data-link error counters / bus monitoring "
        "(implementation-defined CAN controller).",
    ]
    f["notes"] = (
        "CANopen's protocol-level DFT surface is the SDO-readable object "
        "dictionary, the EMCY emergency object + pre-defined error field "
        "(0x1003), the error register (0x1001), heartbeat / node-guarding "
        "liveness, and LSS for Node-ID / bit-timing setup. Frame-level error "
        "handling is the CAN data link layer beneath CANopen. Chip-level JTAG / "
        "scan / BIST remain controller-vendor / SoC-integrator concerns; "
        "conformance is established by CiA conformance testing.")
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
    f["power_intent_present"] = False
    f["power_management_note"] = (
        "CANopen (CiA 301) does not define a power-domain / low-power "
        "specification at the application layer. The NMT Stopped state reduces "
        "communication to NMT and error control only, which can lower bus "
        "activity, and a device may enter a low-power mode of its CAN "
        "controller, but power management is an implementation / device-profile "
        "concern (and CAN bus power / wake behaviour belongs to the CAN "
        "physical layer).")
    f["power_rails"] = [
        {"rail": "VDD (controller)", "purpose": "CANopen / CAN controller "
         "logic supply."},
        {"rail": "CAN transceiver supply", "purpose": "CAN_H / CAN_L line "
         "driver supply (CAN physical layer)."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["notes"] = (
        "CANopen's protocol-level relationship to power is limited: the NMT "
        "Stopped state minimizes communication, and store/restore parameter "
        "objects (0x1010 / 0x1011) persist configuration across power cycles. "
        "Fine-grained power domains, low-power CAN modes, and wake behaviour "
        "are CAN physical-layer / implementation concerns, not part of CiA "
        "301.")
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
        "Object dictionary — SDO read/write of every supported entry; mandatory "
        "0x1000 / 0x1001 / 0x1018.",
        "NMT state machine — Initialisation -> boot-up -> Pre-operational -> "
        "Operational <-> Stopped; module-control commands.",
        "Boot-up message after Initialisation (0x700+Node-ID, byte 0x00).",
        "PDO — TPDO / RPDO mapping (0x1600 / 0x1A00) and all transmission types "
        "(synchronous / asynchronous / event-driven).",
        "SDO — expedited / segmented / block transfer; SDO abort (32-bit code).",
        "SYNC — period (0x1006) and synchronous-PDO timing.",
        "EMCY — emergency object (code + error register + manufacturer bytes); "
        "pre-defined error field (0x1003).",
        "Error control — heartbeat (0x1016 / 0x1017) or node guarding (0x100C / "
        "0x100D).",
        "Predefined connection set — default COB-IDs as a function of Node-ID.",
        "Device-profile conformance — CiA 401 / CiA 402 application objects.",
        "LSS (CiA 305) — Node-ID and bit-timing assignment.",
    ]
    f["notes"] = (
        "CANopen does not ship an embedded testbench, but CiA 301 implies a "
        "verification plan spanning the object dictionary (SDO access), the NMT "
        "state machine and boot-up, the PDO mapping and transmission types, the "
        "SDO transfer modes and abort, SYNC / TIME / EMCY, heartbeat / node "
        "guarding, and the predefined connection set, plus device-profile "
        "conformance. CiA conformance testing supplies the formal suite.")
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
        "Underlying CAN CRC and error frames detect frame corruption (CAN data "
        "link layer).",
        "SDO abort transfer (32-bit abort code) on a failed / invalid object "
        "access.",
        "EMCY emergency object reports internal errors with an error code and "
        "error register.",
        "Heartbeat / node guarding detects lost or failed nodes.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "CiA 301 CANopen provides no cryptographic confidentiality or "
        "authentication; the bus carries plaintext frames.",
        "Security extensions for CAN-based networks (e.g. CANopen FD security "
        "profiles, CiA 100x series, or higher-layer measures) are layered above "
        "or alongside CiA 301.",
    ]
    f["notes"] = (
        "CANopen is an application-layer communication profile over CAN: its "
        "built-in protections are anti-corruption / liveness (the underlying "
        "CAN CRC and error frames, SDO abort codes, the EMCY emergency object, "
        "and heartbeat / node guarding). The bus carries plaintext frames; "
        "cryptographic confidentiality / authentication are NOT part of CiA 301 "
        "and must be provided by higher-layer or companion security profiles.")
    _write(p, d)
