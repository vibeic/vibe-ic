"""Open Core Protocol (OCP) SoC-bus protocol synth helper (protocol #70).

ic_class-gated overlay for the Open Core Protocol structural signature: the
bus-independent, point-to-point, synchronous master/slave core interface
(socket) defined by the OCP-IP Association "Open Core Protocol Specification"
(later contributed to Accellera). OCP isolates an IP core from the on-chip
interconnect: a core wrapped with an OCP socket can be reused with any bus that
provides an OCP wrapper, because the core only ever speaks OCP.

OCP signals are organized into three groups:
  - Dataflow signals — the request/datahandshake/response transfer. Basic
    signals MCmd / MAddr / MData / MByteEn / SCmdAccept / SResp / SData /
    MRespAccept, plus simple / burst / tag / thread extensions.
  - Sideband signals — out-of-band control / status / interrupt / error / reset
    (Control / Status / MFlag / SFlag / SInterrupt / MError / SError / Reset_n).
  - Test signals — scan, JTAG (IEEE 1149.1), and clock control.

A transfer is decomposed into phases: a request phase (master drives MCmd; slave
asserts SCmdAccept), an optional datahandshake phase (MDataValid / SDataAccept),
and a response phase (slave drives SResp / SData; master asserts MRespAccept).
MCmd encodes IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST; SResp encodes NULL/DVA/FAIL/ERR.
OCP is highly configurable via the RTL configuration (addr_wdth, data_wdth,
mthreadid_width, tags, ...) and named profiles; the socket is the complete set
of OCP signals on one side.

Doctrine — GENERAL not keyword: detection uses the canonical STRUCTURAL OCP
signature (the M/S-prefixed signal model: MCmd command + SCmdAccept request
accept + SResp response + MRespAccept response accept, with MData/SData and
MAddr, and the dataflow/sideband/test signal grouping) read from the L-doc /
input_doc CONTENT blob only. It NEVER reads the input-document filename or the
benchmark folder name, and it does NOT fire on a bare "ocp" name token alone —
a structural set of the M/S-prefixed handshake signals is always required.

Sibling disambiguation — OCP vs AXI / AHB / Wishbone / Avalon / TileLink. All
six are SoC interconnect protocols. They are distinguished by their wire-level
handshake vocabulary:

  - AXI uses five independent channels with xVALID/xREADY (ARVALID/AWVALID/
    RVALID/BVALID/WVALID) handshakes.
  - AHB uses HADDR/HTRANS/HREADY/HRESP with a pipelined address/data phase.
  - Wishbone uses CYC/STB/ACK (cycle/strobe/acknowledge) handshake.
  - Avalon uses waitrequest (wait-state) + readdatavalid (pipelined-read) on
    Avalon-MM, and source/sink ready/valid + startofpacket/endofpacket on
    Avalon-ST.
  - TileLink uses Get/Put/Acquire/Grant on TL-UL/TL-UH/TL-C channels.
  - OCP keys on the M/S-prefixed signal model: MCmd / SCmdAccept / SResp /
    MRespAccept + MData / SData + MAddr, with the dataflow / sideband / test
    signal groups and the OCP socket.

The OCP detector REQUIRES the M/S-prefixed structural signature and DEFERS when
the doc is AXI-primary / AHB-primary / Wishbone-primary / Avalon-primary /
TileLink-primary with NO OCP signature, so it cannot false-fire on a sibling
SoC-bus spec. Because OCP classifies as `digital_arithmetic_primitive` under the
universal detector (like Avalon and Wishbone), it is wired into the runner's R55
path (the [14e/15] block that enters for that class); a sibling synth may have
populated L1/L2/... first, so this routine FORCE-OVERWRITES (direct assignment)
every key it owns and is wired to run after the sibling SoC-bus synths.

Public entry: ``apply_ocp_synth(generated_docs_dir, is_ocp, ocp_ic_name)``.
Module-level ``is_ocp(blob)`` is the content-only structural detector.
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

# Canonical OCP facts (OCP-IP Open Core Protocol Specification).
_SIGNAL_GROUPS = ["Dataflow", "Sideband", "Test"]

# Dataflow basic signals.
_DATAFLOW_BASIC = [
    "Clk", "EnableClk", "MAddr", "MCmd", "MData", "MDataValid",
    "MRespAccept", "SCmdAccept", "SData", "SDataAccept", "SResp",
]
# Dataflow simple extension signals.
_DATAFLOW_SIMPLE = [
    "MAddrSpace", "MByteEn", "MDataByteEn", "MDataInfo", "SDataInfo",
    "MReqInfo", "SRespInfo",
]
# Dataflow burst extension signals.
_DATAFLOW_BURST = [
    "MBurstLength", "MBurstSeq", "MBurstPrecise", "MBurstSingleReq",
    "MReqLast", "MDataLast", "SRespLast", "MAtomicLength",
    "MReqRowLast", "MDataRowLast", "SRespRowLast",
    "MBlockHeight", "MBlockStride",
]
# Dataflow tag extension signals.
_DATAFLOW_TAG = ["MTagID", "STagID", "MTagInOrder", "STagInOrder"]
# Dataflow thread extension signals.
_DATAFLOW_THREAD = [
    "MThreadID", "SThreadID", "MConnID", "SThreadBusy", "MThreadBusy",
    "MDataThreadBusy",
]
# Sideband signals.
_SIDEBAND_SIGNALS = [
    "Control", "ControlBusy", "ControlWr", "Status", "StatusBusy",
    "StatusRd", "MError", "SError", "MFlag", "SFlag", "SInterrupt",
    "MReset_n", "SReset_n", "Reset_n",
]
# Test signals.
_TEST_SIGNALS = [
    "Scanctrl", "Scanin", "Scanout", "TCK", "TMS", "TDI", "TDO",
    "TRST_N", "ClkByp", "TestClk",
]

# MCmd 3-bit command encoding.
_MCMD_ENCODING = [
    ("0", "IDLE", "no request this cycle"),
    ("1", "WR", "write"),
    ("2", "RD", "read"),
    ("3", "RDEX", "read exclusive (locks for atomic read-modify-write)"),
    ("4", "RDL", "read linked (load-linked; pairs with WRC)"),
    ("5", "WRNP", "write non-posted (a response is returned)"),
    ("6", "WRC", "write conditional (store-conditional)"),
    ("7", "BCST", "broadcast"),
]
# SResp 2-bit response encoding.
_SRESP_ENCODING = [
    ("0", "NULL", "no response (slave idle / no data this cycle)"),
    ("1", "DVA", "data valid / accept (read data valid, or write accepted)"),
    ("2", "FAIL", "request failed (e.g. exclusive access lost)"),
    ("3", "ERR", "response error (request could not be serviced)"),
]
# Burst address sequences (MBurstSeq).
_BURST_SEQ = ["INCR", "WRAP", "STRM", "XOR", "UNKN", "DFLT1", "DFLT2", "BLCK"]


def is_ocp(blob: str) -> bool:
    """Content-only OCP detector with an AXI/AHB/Wishbone/Avalon/TileLink MUTEX.

    Fire on the canonical OCP structural signature: the M/S-prefixed signal
    model — MCmd (master command) + SCmdAccept (slave request accept) + SResp
    (slave response) + MRespAccept (master response accept), corroborated by
    MData/SData and MAddr and the dataflow / sideband / test signal grouping
    and the OCP socket. Defer if the doc is a sibling SoC-bus (AXI-primary /
    AHB-primary / Wishbone-primary / Avalon-primary / TileLink-primary) with NO
    OCP signature. Reads ONLY the spec text `blob` — never a filename or a
    benchmark name, and never fires on a bare "ocp" token alone.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- HARD STRUCTURAL GATE (word-boundary, case-sensitive signal names). ---
    # The OCP-specific positive signals are the M/S-prefixed handshake names.
    # We use word-boundary matches on the canonical mixed-case signal names so
    # an incidental substring (e.g. "mcmd" inside another word) cannot fire.
    def has(tok: str) -> bool:
        return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None

    mcmd = has("MCmd")
    scmdaccept = has("SCmdAccept")
    sresp = has("SResp")
    mrespaccept = has("MRespAccept")
    mdata = has("MData")
    sdata = has("SData")
    maddr = has("MAddr")

    # The command/accept core: a master command + a slave request-accept + a
    # slave response. This M/S-prefixed handshake trio is unique to OCP among
    # the SoC buses (AXI/AHB/Wishbone/Avalon/TileLink use entirely different
    # signal names). Require the command core plus the data and response
    # corroboration so a stray single token cannot fire.
    command_core = mcmd and scmdaccept and sresp
    response_accept = mrespaccept
    data_signals = mdata and sdata and maddr

    # MCmd command-encoding corroboration (real OCP command mnemonics).
    cmd_encoding = (("RDEX" in blob or "WRNP" in blob)
                    and ("BCST" in blob or "IDLE" in blob))

    # Signal-group corroboration: OCP organizes signals into the three named
    # groups dataflow / sideband / test.
    signal_groups = ("dataflow" in low and "sideband" in low
                     and "test" in low)

    # The hard gate: the OCP command/response/accept handshake trio plus at
    # least one corroborating structural fact (master response accept, the
    # MData/SData/MAddr data signals, the MCmd command encoding, or the
    # three-group signal model). The trio alone is already OCP-unique; the
    # corroboration makes a false fire on a foreign doc essentially impossible.
    has_hard_structure = command_core and (
        response_accept or data_signals or cmd_encoding or signal_groups)
    if not has_hard_structure:
        return False

    # --- Sibling MUTEX. ---
    # Defer if the doc is a sibling SoC-bus primary with NO OCP signature. Each
    # branch requires that the OCP command core did NOT also match (belt-and-
    # braces; has_hard_structure already gates this), so an OCP doc that merely
    # mentions a sibling protocol for comparison is not deferred.
    not_ocp = not command_core

    axi_primary = (
        (("arvalid" in low or "awvalid" in low or "rvalid" in low
          or "bvalid" in low or "wvalid" in low)
         or ("axi" in low and "xvalid" in low))
        and not_ocp)
    ahb_primary = (
        ("htrans" in low and "hready" in low
         and ("haddr" in low or "hresp" in low))
        and not_ocp)
    wishbone_primary = (
        (("cyc_o" in low or "stb_o" in low or "ack_i" in low)
         or ("wishbone" in low and "cyc" in low and "stb" in low
             and "ack" in low))
        and not_ocp)
    avalon_primary = (
        ("waitrequest" in low and "readdatavalid" in low)
        and not_ocp)
    tilelink_primary = (
        (("tilelink" in low or "tl-ul" in low or "tl-c" in low)
         and "acquire" in low and "grant" in low)
        and not_ocp)
    if (axi_primary or ahb_primary or wishbone_primary
            or avalon_primary or tilelink_primary):
        return False

    return True


def apply_ocp_synth(generated_docs_dir: Path, is_ocp_flag: bool,
                    ocp_ic_name: Optional[str]) -> None:
    """Apply OCP synth when the OCP signature matched.

    Because OCP classifies as `digital_arithmetic_primitive` (like Avalon and
    Wishbone), a sibling SoC-bus synth may have populated L1/L2/... first. This
    routine FORCE-OVERWRITES (direct assignment) every key it owns with the
    OCP-canonical value; the runner wires it to run after the sibling SoC-bus
    synths so OCP wins.
    """
    if not is_ocp_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if ocp_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ocp_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = ocp_ic_name
                d["ic_name"] = ocp_ic_name
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
# L1 — OCP datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "Open Core Protocol Specification"
    d["version"] = "OCP-IP Open Core Protocol (OCP) Specification"
    d["revised_date"] = "OCP-IP Association (contributed to Accellera)"
    d["manufacturer"] = "OCP-IP Association"
    d["copyright"] = "© OCP-IP Association / Accellera Systems Initiative"
    d["abstract"] = (
        "The Open Core Protocol (OCP) defines a high-performance, "
        "bus-independent, point-to-point, synchronous interface between two "
        "communicating entities — a master (the controlling entity that "
        "presents commands) and a slave (which responds). OCP is organized as "
        "a bus-independent socket that isolates an IP core from the on-chip "
        "interconnect: a core wrapped with an OCP socket can be reused on any "
        "bus that provides an OCP wrapper. OCP signals are divided into three "
        "groups: dataflow (the request/datahandshake/response transfer), "
        "sideband (out-of-band control/status/interrupt/error/reset), and test "
        "(scan/JTAG/clock control). The dataflow basic signals are MCmd "
        "(master command), MAddr, MData, MByteEn, SCmdAccept (slave request "
        "accept), SResp (slave response), SData, and MRespAccept (master "
        "response accept). MCmd encodes IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST; "
        "SResp encodes NULL/DVA/FAIL/ERR. OCP supports bursts (precise/"
        "imprecise, INCR/WRAP/STRM/XOR/2D), tags (out-of-order responses within "
        "a thread), and threads (concurrent independent flows). OCP is highly "
        "configurable through the RTL configuration (addr_wdth, data_wdth, "
        "mthreadid_width, tags, datahandshake, ...) and named profiles.")
    d["keywords"] = [
        "OCP", "Open Core Protocol", "OCP-IP", "socket", "master", "slave",
        "bus-independent", "point-to-point", "synchronous", "MCmd",
        "SCmdAccept", "SResp", "MRespAccept", "MAddr", "MData", "SData",
        "MByteEn", "dataflow", "sideband", "test", "request phase",
        "response phase", "datahandshake", "burst", "thread", "tag",
        "MThreadID", "MTagID", "IDLE", "WR", "RD", "RDEX", "WRNP", "BCST",
        "NULL", "DVA", "FAIL", "ERR", "Accellera",
    ]
    d["external_pins"] = [
        "Dataflow basic: Clk, EnableClk, MAddr, MCmd, MData, MDataValid, "
        "MRespAccept, SCmdAccept, SData, SDataAccept, SResp (interface uses "
        "the subset it needs)",
        "Dataflow simple extensions: MAddrSpace, MByteEn, MDataByteEn, "
        "MDataInfo, SDataInfo, MReqInfo, SRespInfo",
        "Dataflow burst extensions: MBurstLength, MBurstSeq, MBurstPrecise, "
        "MBurstSingleReq, MReqLast, MDataLast, SRespLast, MAtomicLength",
        "Dataflow tag extensions: MTagID, STagID, MTagInOrder, STagInOrder",
        "Dataflow thread extensions: MThreadID, SThreadID, MConnID, "
        "SThreadBusy, MThreadBusy",
        "Sideband: Control/Status, MFlag/SFlag, SInterrupt, MError/SError, "
        "Reset_n",
        "Test: Scanctrl/Scanin/Scanout, TCK/TMS/TDI/TDO/TRST_N (JTAG), "
        "ClkByp/TestClk",
    ]
    d["interface_types"] = list(_SIGNAL_GROUPS)
    d["ocp_dataflow_basic_signals"] = list(_DATAFLOW_BASIC)
    d["ocp_sideband_signals"] = list(_SIDEBAND_SIGNALS)
    d["ocp_test_signals"] = list(_TEST_SIGNALS)
    d["modes_of_operation"] = [
        {"name": "Request phase",
         "roles": "master -> slave",
         "note": "Master drives MCmd (+MAddr/MData/MByteEn and any "
                 "burst/tag/thread qualifiers); slave asserts SCmdAccept to "
                 "accept the request."},
        {"name": "Datahandshake phase",
         "roles": "master -> slave (datahandshake extension)",
         "note": "Write data transferred separately: MDataValid + MData / "
                 "MDataByteEn, accepted by SDataAccept; decouples write data "
                 "from the write command."},
        {"name": "Response phase",
         "roles": "slave -> master",
         "note": "Slave drives SResp (NULL/DVA/FAIL/ERR) + SData; master "
                 "asserts MRespAccept to accept the response."},
        {"name": "Burst", "roles": "master / slave",
         "note": "Precise or imprecise bursts; INCR/WRAP/STRM/XOR address "
                 "sequences plus 2D block bursts; MBurstLength / MBurstSeq / "
                 "MReqLast / MDataLast / SRespLast."},
        {"name": "Threads & tags", "roles": "master / slave",
         "note": "MThreadID/SThreadID give concurrent independent flows; "
                 "MTagID/STagID give out-of-order responses within a thread."},
        {"name": "Sideband", "roles": "master / slave",
         "note": "Out-of-band Control/Status registers, MFlag/SFlag, "
                 "SInterrupt, MError/SError, and Reset_n."},
        {"name": "Test", "roles": "DFT",
         "note": "Scan (Scanctrl/Scanin/Scanout), JTAG (IEEE 1149.1), and "
                 "clock control (ClkByp/TestClk)."},
    ]
    d["topology_summary"] = (
        "OCP is point-to-point: each OCP instance connects exactly one master "
        "to one slave. Peer-to-peer communication between two entities uses two "
        "OCP instances (one in each direction). A bus wrapper translates OCP to "
        "the on-chip interconnect, so the same OCP-wrapped core can be moved "
        "between systems by swapping only the wrapper.")
    d["use_cases"] = [
        "Wrapping an IP core with a bus-independent socket so it can be reused "
        "across on-chip buses",
        "Connecting a processor / DMA master to memory and peripheral slaves",
        "Out-of-order, multi-threaded, high-throughput SoC dataflow (threads + "
        "tags)",
        "Burst transfers (cache-line WRAP/XOR fills, streaming STRM, 2D DMA "
        "tiling)",
        "Decoupling write data from write address via the datahandshake phase",
        "Sideband control/status register access and interrupt signaling",
    ]
    d["revision_history"] = [
        {"version": "OCP Specification",
         "date": "OCP-IP Association (contributed to Accellera)",
         "description": "Bus-independent point-to-point synchronous master/"
                        "slave core interface (socket) with dataflow, "
                        "sideband, and test signal groups; configurable via "
                        "RTL configuration and named profiles."},
    ]
    d["overview"] = (
        "The Open Core Protocol (OCP) is a bus-independent, point-to-point, "
        "synchronous interface between an IP core and an on-chip bus wrapper. "
        "One entity is the master (the controlling entity — only the master "
        "presents commands) and the other is the slave (which responds). OCP "
        "is organized as a socket that isolates the core from the specifics of "
        "the interconnect, so an OCP-wrapped core can be reused with any bus "
        "that provides an OCP wrapper. OCP signals are divided into dataflow, "
        "sideband, and test groups. A transfer is decomposed into a request "
        "phase (master drives MCmd; slave asserts SCmdAccept), an optional "
        "datahandshake phase (MDataValid / SDataAccept) that decouples write "
        "data from the write command, and a response phase (slave drives SResp "
        "and SData; master asserts MRespAccept). MCmd encodes "
        "IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST; SResp encodes NULL/DVA/FAIL/ERR. "
        "OCP supports precise and imprecise bursts (INCR/WRAP/STRM/XOR plus 2D "
        "block bursts), tags for out-of-order responses within a thread, and "
        "threads for concurrent independent flows. The interface is highly "
        "configurable through the RTL configuration parameters (addr_wdth, "
        "data_wdth, mthreadid_width, tags, datahandshake, ...) and named "
        "profiles.")
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
        "Bus-independent, point-to-point, synchronous master/slave core "
        "interface (socket). Signals are grouped into dataflow (request/"
        "datahandshake/response), sideband (out-of-band control/status/"
        "interrupt/error/reset), and test (scan/JTAG/clock). A bus wrapper "
        "translates OCP to the on-chip interconnect.")
    po["duplex"] = (
        "Point-to-point. A single OCP instance carries master->slave requests "
        "and slave->master responses; peer-to-peer needs two OCP instances "
        "(one per direction).")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["forwarded_clock"] = False
    po["parallel_synchronous"] = True
    po["encoding"] = (
        "Parallel synchronous-logic interface; no line code. All OCP signals "
        "(except Reset_n and the optional asynchronous interrupt/error signals) "
        "are sampled on the rising edge of Clk. Byte selection is by MByteEn.")
    po["roles"] = {"ocp": "master / slave"}
    po["signal_groups"] = list(_SIGNAL_GROUPS)
    po["dataflow_basic_signals"] = list(_DATAFLOW_BASIC)
    po["sideband_signals"] = list(_SIDEBAND_SIGNALS)
    po["test_signals"] = list(_TEST_SIGNALS)
    po["phases"] = [
        "Request phase: master drives MCmd (+MAddr/MData/MByteEn); slave "
        "asserts SCmdAccept.",
        "Datahandshake phase (optional): MDataValid + MData/MDataByteEn "
        "accepted by SDataAccept.",
        "Response phase: slave drives SResp + SData; master asserts "
        "MRespAccept.",
    ]
    po["flow_control"] = (
        "SCmdAccept gates the request phase, SDataAccept gates the "
        "datahandshake phase, and MRespAccept gates the response phase. When an "
        "accept signal is not configured, that phase completes in a single "
        "cycle with no wait state.")
    po["configurability"] = (
        "Highly configurable via the RTL configuration: addr_wdth, data_wdth, "
        "addrspace_wdth, byteen, mthreadid_width, sthreadid_width, tags, "
        "connid_wdth, burstlength, datahandshake, readex_enable, "
        "writeresp_enable; named profiles bundle parameter sets for "
        "interoperability.")
    d["functional_requirements"] = [
        {"id": "FR-OCP-01", "text": "An OCP interface connects exactly one "
         "master to one slave, point-to-point. Only the master presents "
         "commands (MCmd); the slave responds. The OCP socket isolates the IP "
         "core from the on-chip interconnect."},
        {"id": "FR-OCP-02", "text": "All OCP signals (except Reset_n and the "
         "optional asynchronous interrupt/error signals) are synchronous to "
         "the rising edge of the OCP clock Clk; EnableClk qualifies active "
         "OCP edges."},
        {"id": "FR-OCP-03", "text": "OCP signals are divided into three groups: "
         "dataflow (the transfer), sideband (out-of-band control/status/"
         "interrupt/error/reset), and test (scan/JTAG/clock control)."},
        {"id": "FR-OCP-04", "text": "The request phase: the master drives MCmd "
         "(plus MAddr, MData/MByteEn for a write that does not use "
         "datahandshake, and any burst/tag/thread qualifiers); the slave "
         "accepts by asserting SCmdAccept. The request handshake completes when "
         "MCmd is valid and SCmdAccept is asserted."},
        {"id": "FR-OCP-05", "text": "The datahandshake phase (when configured) "
         "transfers write data separately using MDataValid and MData/"
         "MDataByteEn, accepted by SDataAccept; it decouples the write command "
         "from the write data and is required for pipelined write bursts."},
        {"id": "FR-OCP-06", "text": "The response phase: for reads (and writes "
         "that request a response) the slave drives SResp (the response code) "
         "and SData (read data); the master accepts by asserting MRespAccept. "
         "The response handshake completes when SResp is non-NULL and "
         "MRespAccept is asserted."},
        {"id": "FR-OCP-07", "text": "MCmd is a 3-bit field encoding "
         "IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST. SResp is a 2-bit field encoding "
         "NULL/DVA/FAIL/ERR."},
        {"id": "FR-OCP-08", "text": "OCP supports bursts: precise (length known "
         "up front via MBurstLength) or imprecise (last transfer marked by "
         "MReqLast/MDataLast). Address sequences (MBurstSeq) include INCR, "
         "WRAP, STRM, XOR, and 2D block bursts (BLCK)."},
        {"id": "FR-OCP-09", "text": "Tags (MTagID/STagID) allow responses to "
         "return out of order with respect to requests within a single "
         "thread. Threads (MThreadID/SThreadID) provide concurrent independent "
         "flows with no inter-thread ordering; SThreadBusy/MThreadBusy provide "
         "per-thread flow control."},
        {"id": "FR-OCP-10", "text": "Sideband signals carry out-of-band "
         "Control/Status registers, MFlag/SFlag, SInterrupt, MError/SError, "
         "and Reset_n; the interface is held idle while Reset_n is asserted."},
        {"id": "FR-OCP-11", "text": "OCP is highly configurable: an interface "
         "instance carries only the signals the connected core needs, selected "
         "by the RTL configuration parameters (addr_wdth, data_wdth, "
         "mthreadid_width, tags, datahandshake, ...) or a named profile."},
    ]
    d["error_response_conditions"] = [
        "SResp = FAIL — the request failed (e.g. an exclusive access lost its "
        "reservation).",
        "SResp = ERR — the slave could not service the request (response "
        "error).",
        "MError / SError sideband — error indication outside the dataflow.",
        "SCmdAccept held deasserted — the request phase stalls until the slave "
        "accepts (flow control, no base-protocol time-out).",
        "SThreadBusy / MThreadBusy asserted — a thread is back-pressured and "
        "cannot currently accept a transfer.",
    ]
    d["compliance_requirements"] = [
        "Master/slave roles with the declared dataflow signal subset (MCmd, "
        "SCmdAccept, SResp, MRespAccept as needed, plus MAddr/MData/SData/"
        "MByteEn).",
        "Correct phase handshakes: SCmdAccept gates the request, SDataAccept "
        "the datahandshake, MRespAccept the response.",
        "Legal MCmd command encoding (IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST) and "
        "SResp response encoding (NULL/DVA/FAIL/ERR).",
        "Burst behavior consistent with MBurstSeq / MBurstLength / "
        "MBurstPrecise and the MReqLast/MDataLast/SRespLast markers.",
        "Thread/tag ordering rules (in-order within a thread unless tagged; no "
        "inter-thread ordering).",
        "Configuration consistency between master and slave (matched profile / "
        "parameters).",
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
        "Phased master/slave transfer protocol. The master presents a command "
        "on MCmd in the request phase (accepted by SCmdAccept); write data may "
        "be transferred in a separate datahandshake phase (MDataValid / "
        "SDataAccept); the slave returns a response on SResp + SData in the "
        "response phase (accepted by MRespAccept). MCmd encodes "
        "IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST; SResp encodes NULL/DVA/FAIL/ERR.")
    d["channels"] = [
        {"name": "Dataflow (request/datahandshake/response)",
         "direction": "bidirectional master<->slave",
         "description": "Master drives MCmd/MAddr/MData/MByteEn; slave drives "
         "SCmdAccept/SResp/SData; MDataValid/SDataAccept for the optional "
         "datahandshake phase; MRespAccept gates the response."},
        {"name": "Sideband",
         "direction": "bidirectional master<->slave (out-of-band)",
         "description": "Control/Status registers, MFlag/SFlag, SInterrupt, "
         "MError/SError, and Reset_n outside the dataflow handshake."},
        {"name": "Test",
         "direction": "DFT access",
         "description": "Scan (Scanctrl/Scanin/Scanout), JTAG "
         "(TCK/TMS/TDI/TDO/TRST_N), and clock control (ClkByp/TestClk)."},
    ]
    d["dataflow_signals"] = {
        "MCmd": "master->slave; 3-bit command (IDLE/WR/RD/RDEX/RDL/WRNP/WRC/"
                "BCST)",
        "MAddr": "master->slave; transfer address (width addr_wdth)",
        "MData": "master->slave; write data (width data_wdth)",
        "MByteEn": "master->slave; byte enables selecting active byte lanes",
        "MDataValid": "master->slave; write data valid (datahandshake phase)",
        "MRespAccept": "master->slave; master accepts the slave response",
        "SCmdAccept": "slave->master; slave accepts the request",
        "SData": "slave->master; read data (width data_wdth)",
        "SDataAccept": "slave->master; slave accepts the write data "
                       "(datahandshake)",
        "SResp": "slave->master; 2-bit response (NULL/DVA/FAIL/ERR)",
    }
    d["mcmd_encoding"] = [
        {"code": c, "name": n, "meaning": m} for (c, n, m) in _MCMD_ENCODING
    ]
    d["sresp_encoding"] = [
        {"code": c, "name": n, "meaning": m} for (c, n, m) in _SRESP_ENCODING
    ]
    d["transfer_types"] = [
        {"name": "Single read (RD)",
         "description": "Master drives MCmd=RD + MAddr; SCmdAccept accepts; "
         "slave returns SResp=DVA + SData; MRespAccept accepts."},
        {"name": "Posted write (WR)",
         "description": "Master drives MCmd=WR + MAddr + MData + MByteEn; "
         "SCmdAccept accepts; no response (posted)."},
        {"name": "Non-posted write (WRNP)",
         "description": "Master drives MCmd=WRNP; SCmdAccept accepts; slave "
         "returns SResp=DVA confirming the write; MRespAccept accepts."},
        {"name": "Read exclusive / read linked (RDEX / RDL)",
         "description": "Atomic read-modify-write: RDEX locks; RDL pairs with "
         "WRC store-conditional (SResp=FAIL if the reservation was lost)."},
        {"name": "Burst transfer",
         "description": "MBurstLength words moved as one transaction; MBurstSeq "
         "selects INCR/WRAP/STRM/XOR/BLCK; MReqLast/MDataLast/SRespLast mark "
         "the last beats; MBurstSingleReq allows one request for many data "
         "beats."},
        {"name": "Datahandshake write",
         "description": "Write data sent separately: MDataValid + MData/"
         "MDataByteEn accepted by SDataAccept, decoupled from the request."},
        {"name": "Broadcast (BCST)",
         "description": "A broadcast write command to multiple targets."},
    ]
    d["addressing"] = {
        "note": "OCP is address-based: the master drives MAddr (width "
                "addr_wdth) and an optional MAddrSpace selecting an address "
                "space/region. OCP is point-to-point, so the address selects a "
                "location within the connected slave, not a target on a bus.",
        "address_units": "OCP-word aligned; MByteEn selects byte lanes within "
                          "the word.",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = False
    d["packet_oriented"] = False
    d["bit_stuffing"] = False
    d["arbitration_based"] = False
    d["arbitration_note"] = (
        "OCP itself is point-to-point and has no arbitration; arbitration "
        "between multiple masters is the job of the on-chip bus / interconnect "
        "behind the OCP wrapper. Concurrency within an OCP socket is provided "
        "by threads (MThreadID/SThreadID), not by bus arbitration.")
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / configuration parameter model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "An OCP slave is itself an address-mapped target: the master reads and "
        "writes slave locations via MAddr + MCmd(RD/WR) + MData/SData + "
        "MByteEn. The OCP specification defines the *interface* (signal roles, "
        "phases, and transfer timing), not a fixed register map; each slave IP "
        "core defines its own register map within its OCP address space. OCP "
        "additionally provides the sideband Control/Status register window. The "
        "parameters below are the OCP configuration parameters an interface "
        "declares.")
    d["register_access"] = {
        "transport": "OCP address-based read/write (master -> slave) via "
                     "MCmd/MAddr/MData/SData",
        "purpose": "Read/write slave registers and memory; MByteEn selects "
                   "byte lanes; the sideband Control/Status window provides "
                   "out-of-band register access.",
        "addressing": "MAddr (addr_wdth) + optional MAddrSpace; OCP-word "
                      "aligned with MByteEn byte selection",
    }
    d["sideband_register_window"] = {
        "Control": "master-written control register (ControlWr); ControlBusy "
                   "provides flow control",
        "Status": "master-read status register (StatusRd); StatusBusy provides "
                  "flow control",
        "note": "The Control/Status sideband window is distinct from the "
                "MAddr-addressed dataflow register space and is used for slow "
                "configuration/status.",
    }
    d["configuration_parameters"] = [
        {"param": "addr_wdth", "meaning": "width of MAddr (address bus)"},
        {"param": "data_wdth", "meaning": "width of MData / SData"},
        {"param": "addrspace_wdth", "meaning": "width of MAddrSpace"},
        {"param": "byteen", "meaning": "whether MByteEn is present"},
        {"param": "mthreadid_width", "meaning": "width of MThreadID (threads)"},
        {"param": "sthreadid_width", "meaning": "width of SThreadID"},
        {"param": "tags", "meaning": "number of tags (MTagID/STagID width)"},
        {"param": "connid_wdth", "meaning": "width of MConnID"},
        {"param": "burstlength", "meaning": "burst enable / MBurstLength width"},
        {"param": "datahandshake",
         "meaning": "whether the separate datahandshake phase is present"},
        {"param": "readex_enable / writeresp_enable / rdlwrc_enable",
         "meaning": "which MCmd commands are legal"},
        {"param": "sdatainfo_wdth / mdatainfo_wdth / reqinfo_wdth / "
                  "respinfo_wdth",
         "meaning": "widths of the info side-channels"},
    ]
    d["profiles_note"] = (
        "A profile is a named, pre-agreed bundle of OCP configuration "
        "parameters that masters and slaves use to interoperate (e.g. a block "
        "data flow profile, a register access profile, or a sequential "
        "undefined-length data flow profile).")
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / physical signaling spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = False
    d["signaling_summary"] = (
        "OCP is a synchronous-logic on-chip core interface, not an electrical/"
        "analog interface. All OCP signals (except the asynchronous Reset_n and "
        "optional interrupt/error signals) are single-ended synchronous-logic "
        "signals timed to the rising edge of the OCP clock Clk; there is no "
        "line code, no differential signaling, and no physical-layer electrical "
        "specification in the OCP specification. Physical/electrical behavior "
        "is a chip-implementation concern, not part of the OCP contract.")
    d["modulation"] = "n/a (synchronous-logic interface; no modulation)"
    d["clocking"] = (
        "All OCP signals are sampled on the rising edge of the OCP clock Clk "
        "(except Reset_n and the optional asynchronous interrupt/error "
        "signals); EnableClk qualifies which rising edges are active OCP "
        "edges. OCP is a single-clock synchronous interface.")
    d["signal_levels"] = (
        "Single-ended synchronous-logic levels. OCP defines signal roles and "
        "timing, not voltage levels.")
    d["encoding_role_in_analog"] = (
        "OCP defines no line code. Byte selection is by MByteEn; data/response "
        "integrity is reported by SResp (FAIL/ERR) and the optional MError/"
        "SError sideband and MDataInfo/SDataInfo info channels, not by an OCP "
        "physical layer.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / transfer FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_request"] = [
        {"name": "IDLE", "description": "MCmd=IDLE; no request presented this "
         "cycle."},
        {"name": "REQ", "description": "Master drives a valid MCmd (+MAddr and, "
         "for a non-datahandshake write, MData/MByteEn). The request handshake "
         "completes on the cycle MCmd is valid and SCmdAccept is asserted."},
        {"name": "REQ_WAIT", "description": "Slave holds SCmdAccept deasserted; "
         "the master holds the request stable until the slave accepts."},
    ]
    d["fsm_states_datahandshake"] = [
        {"name": "DH_IDLE", "description": "No write-data beat presented."},
        {"name": "DH_VALID", "description": "Master asserts MDataValid with "
         "MData/MDataByteEn; the beat is accepted when SDataAccept is "
         "asserted."},
        {"name": "DH_WAIT", "description": "Slave holds SDataAccept deasserted; "
         "the master holds the write-data beat stable."},
    ]
    d["fsm_states_response"] = [
        {"name": "RESP_IDLE", "description": "SResp=NULL; no response this "
         "cycle."},
        {"name": "RESP", "description": "Slave drives SResp (DVA/FAIL/ERR) and "
         "SData for a read; the response handshake completes when SResp is "
         "non-NULL and MRespAccept is asserted."},
        {"name": "RESP_WAIT", "description": "Master holds MRespAccept "
         "deasserted; the slave holds the response stable."},
    ]
    d["fsm_hints"] = {
        "trigger": "A transfer begins when the master drives a non-IDLE MCmd "
        "with a valid MAddr; the request completes when SCmdAccept is asserted.",
        "rule": "The master must hold the request (and, in the datahandshake "
        "phase, the write-data beat) stable until the corresponding accept "
        "(SCmdAccept / SDataAccept) is asserted; the slave must hold the "
        "response stable until MRespAccept is asserted.",
        "abort": "There is no protocol-level abort; a phase simply stalls while "
        "the corresponding accept signal is deasserted (or a thread is busy).",
    }
    d["anti_deadlock_rule"] = (
        "Each accept signal (SCmdAccept / SDataAccept / MRespAccept) must "
        "eventually assert so the corresponding phase can complete; "
        "SThreadBusy/MThreadBusy back-pressure individual threads without "
        "stalling the whole socket. When an accept signal is not configured, "
        "that phase completes in a single cycle.")
    d["thread_concurrency_rule"] = (
        "Transfers on different threads (MThreadID/SThreadID) have no ordering "
        "constraint; within one thread, transfers complete in order unless "
        "tags (MTagID/STagID) permit out-of-order responses.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug architecture.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "SResp response code", "purpose": "NULL/DVA/FAIL/ERR reports "
         "transfer success/failure to the master."},
        {"name": "MError / SError sideband", "purpose": "Out-of-band error "
         "indication outside the dataflow handshake."},
        {"name": "Phase handshake timing", "purpose": "Observable SCmdAccept / "
         "SDataAccept / MRespAccept handshakes for bring-up and protocol "
         "checking."},
        {"name": "MReqInfo / SRespInfo / MDataInfo / SDataInfo", "purpose": "Info "
         "side-channels carry extra information (e.g. parity) with the "
         "request/response/data."},
        {"name": "Test signal group", "purpose": "Scan (Scanctrl/Scanin/"
         "Scanout), JTAG (IEEE 1149.1), and clock control (ClkByp/TestClk) for "
         "DFT access."},
    ]
    d["error_detection_mechanisms"] = [
        "SResp = FAIL / ERR flags failed or unserviceable transfers rather "
        "than silently corrupting.",
        "MError / SError sideband signals report errors out of band.",
        "MByteEn / MDataByteEn ensure only intended byte lanes are written.",
        "Protocol checkers verify the request/datahandshake/response handshake "
        "rules (SCmdAccept / SDataAccept / MRespAccept timing).",
    ]
    d["test_modes"] = [
        {"name": "Scan test", "purpose": "Scanctrl/Scanin/Scanout drive the "
         "scan chains for manufacturing DFT."},
        {"name": "JTAG boundary scan", "purpose": "TCK/TMS/TDI/TDO/TRST_N per "
         "IEEE 1149.1."},
        {"name": "Clock control", "purpose": "ClkByp/TestClk bypass/override "
         "the functional clock for at-speed test."},
        {"name": "Protocol assertion checking", "purpose": "Simulation-time "
         "checks of OCP phase-handshake legality."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Interrupt", "trigger": "Slave asserts SInterrupt to the "
         "master."},
        {"event": "Transfer error", "trigger": "SResp = FAIL / ERR."},
        {"event": "Sideband error", "trigger": "MError / SError asserted."},
        {"event": "Thread busy", "trigger": "SThreadBusy / MThreadBusy "
         "asserted (a thread cannot accept a transfer)."},
    ]
    d["notes"] = (
        "OCP's protocol-level test surface is the SResp response codes, the "
        "MError/SError sideband, the SInterrupt mechanism, the info "
        "side-channels, and the observability of the phase handshakes. The "
        "dedicated test signal group (scan, JTAG IEEE 1149.1, clock control) "
        "provides chip-level DFT access through the OCP socket.")
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
        "OCP_SPEC": "OCP-IP Open Core Protocol Specification",
        "SIGNAL_GROUPS": "Dataflow / Sideband / Test",
        "SIGNALING": "single-ended synchronous logic",
        "LINE_ENCODING": "none",
        "EMBEDDED_CLOCK": False,
        "FORWARDED_CLOCK": False,
        "PARALLEL_SYNCHRONOUS": True,
        "MASTER_SLAVE": True,
        "POINT_TO_POINT": True,
        "MCMD_WIDTH_BITS": 3,
        "SRESP_WIDTH_BITS": 2,
        "REQUEST_RESPONSE_PHASES": True,
        "DATAHANDSHAKE_PHASE": True,
        "BURST_SUPPORTED": True,
        "THREADS_SUPPORTED": True,
        "TAGS_SUPPORTED": True,
    })
    d["dataflow_signal_constants"] = {s: True for s in _DATAFLOW_BASIC}
    d["sideband_signal_constants"] = {s: True for s in _SIDEBAND_SIGNALS}
    d["test_signal_constants"] = {s: True for s in _TEST_SIGNALS}
    d["configuration_parameter_constants"] = {
        "addr_wdth": "configurable (MAddr width)",
        "data_wdth": "configurable (MData/SData width)",
        "mthreadid_width": "configurable (number of threads)",
        "tags": "configurable (MTagID/STagID width)",
        "connid_wdth": "configurable (MConnID width)",
        "byteen": True,
        "datahandshake": "configurable",
        "burstlength": "configurable",
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": False,
        "is_parallel_synchronous": True,
        "embedded_clock": False,
        "forwarded_clock": False,
        "master_slave": True,
        "point_to_point": True,
        "mcmd_command_field_bits": 3,
        "sresp_response_field_bits": 2,
        "request_handshake": "SCmdAccept",
        "datahandshake": "MDataValid / SDataAccept",
        "response_handshake": "MRespAccept",
        "byteen": True,
        "burst": True,
        "threads": True,
        "tags": True,
        "mcmd_commands": [n for (_, n, _) in _MCMD_ENCODING],
        "sresp_responses": [n for (_, n, _) in _SRESP_ENCODING],
        "burst_sequences": list(_BURST_SEQ),
    })
    d["default_signal_values_when_idle"] = {
        "request_idle": "MCmd=IDLE.",
        "response_idle": "SResp=NULL.",
        "accepts": "SCmdAccept/SDataAccept/MRespAccept reflect readiness.",
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
    d["request_waveform"] = {
        "accept": "Master drives a non-IDLE MCmd (+MAddr); the request "
                  "handshake completes on the rising edge where MCmd is valid "
                  "and SCmdAccept is asserted.",
        "wait": "Slave holds SCmdAccept low to stall; the master holds the "
                "request stable until SCmdAccept asserts.",
    }
    d["datahandshake_waveform"] = {
        "beat": "Master asserts MDataValid with MData/MDataByteEn; the beat is "
                "accepted on the rising edge where SDataAccept is asserted.",
        "burst": "Write-burst data beats stream behind the request, each "
                 "accepted by SDataAccept; MDataLast marks the final beat.",
    }
    d["response_waveform"] = {
        "accept": "Slave drives SResp (DVA/FAIL/ERR) + SData; the response "
                  "handshake completes on the rising edge where SResp is "
                  "non-NULL and MRespAccept is asserted.",
        "burst": "A read burst returns SRespLast-terminated response beats, "
                 "each carrying SData and accepted by MRespAccept.",
    }
    d["clocking_note"] = (
        "All OCP signals (except Reset_n and the optional asynchronous "
        "interrupt/error signals) are sampled on the rising edge of the OCP "
        "clock Clk; EnableClk qualifies active edges. There is no forwarded or "
        "embedded clock and no line code.")
    d["general_timing_rule"] = (
        "Each phase is gated by its accept signal: the request by SCmdAccept, "
        "the datahandshake by SDataAccept, and the response by MRespAccept. "
        "When an accept signal is not configured the phase completes in one "
        "cycle. All signals are sampled on the OCP clock edge.")
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
        "Bus-independent core interface socket: an IP core advertises an OCP "
        "master and/or slave socket, and a bus wrapper translates OCP to the "
        "on-chip interconnect. The OCP socket isolates the core from the bus so "
        "the core can be reused by swapping only the wrapper.")
    d["topology_description"] = (
        "OCP is point-to-point: each OCP instance connects one master to one "
        "slave. A master core's OCP master socket connects to a bus wrapper's "
        "OCP slave socket (and vice-versa); the bus behind the wrapper carries "
        "the traffic between sockets. Peer-to-peer needs two OCP instances.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "spec": "OCP-IP Open Core Protocol Specification",
        "signal_groups": list(_SIGNAL_GROUPS),
        "roles": "master / slave",
        "dataflow_basic_signals": list(_DATAFLOW_BASIC),
        "sideband_signals": list(_SIDEBAND_SIGNALS),
        "test_signals": list(_TEST_SIGNALS),
        "phases": "request (SCmdAccept) / datahandshake (MDataValid, "
                  "SDataAccept) / response (MRespAccept)",
        "mcmd_commands": [n for (_, n, _) in _MCMD_ENCODING],
        "sresp_responses": [n for (_, n, _) in _SRESP_ENCODING],
        "concurrency": "threads (MThreadID/SThreadID) + tags (MTagID/STagID)",
        "configurability": "RTL configuration parameters / named profiles",
        "host_side_register_spec": "each OCP slave IP defines its own register "
        "map within its OCP address space; the OCP spec defines the interface, "
        "not the registers.",
    })
    d["interface_categories"] = [
        "Dataflow — request/datahandshake/response transfer "
        "(MCmd/SCmdAccept/MDataValid/SDataAccept/SResp/MRespAccept).",
        "Sideband — out-of-band Control/Status, MFlag/SFlag, SInterrupt, "
        "MError/SError, Reset_n.",
        "Test — scan, JTAG (IEEE 1149.1), clock control.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single OCP master socket to single OCP slave socket (point-to-point).",
        "Master core <-> bus-wrapper slave socket, and bus-wrapper master "
        "socket <-> slave core (the wrapper bridges OCP to the bus).",
        "Two OCP instances for peer-to-peer (one per direction).",
        "Multi-threaded socket (MThreadID/SThreadID) for concurrent flows.",
    ]
    d["default_signal_values_when_omitted"] = (
        "An OCP interface carries only the signals the connected core needs; "
        "omitted control signals take their inactive default (MCmd=IDLE, "
        "SResp=NULL, accepts reflect readiness, MByteEn all-ones when absent). "
        "When an accept signal is not configured, its phase completes in one "
        "cycle.")
    d["soc_dependent_items"] = [
        "Which OCP socket each IP advertises (master and/or slave) and the "
        "selected profile.",
        "Configuration parameters: addr_wdth, data_wdth, MByteEn presence.",
        "mthreadid_width / sthreadid_width (number of threads) and tags width.",
        "Whether the datahandshake phase, bursts, and which MCmd commands "
        "(RDEX/RDL/WRC/BCST) are enabled.",
        "MConnID usage for connection tracking (QoS / security / routing).",
        "The bus wrapper that bridges OCP to the chosen on-chip interconnect.",
    ]
    d["low_power_modes"] = {
        "note": "OCP defines no protocol-level power states; EnableClk can "
                "qualify active clock edges and Reset_n holds the interface "
                "idle, but power management (clock gating, power domains) is an "
                "SoC/chip concern.",
    }
    d["device_classes_examples"] = [
        "Processor / DMA engine (OCP master socket)",
        "On-chip memory / memory controller (OCP slave socket)",
        "Register-based peripheral (OCP slave socket)",
        "On-chip bus / interconnect wrapper (OCP master + slave sockets)",
        "Multi-threaded accelerator (threaded OCP socket)",
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
        "partial - the OCP specification defines the interface phases, signal "
        "roles, command/response encodings, and timing rather than a packaged "
        "testbench; OCP protocol checkers / BFMs exercise them.")
    d["derived_compliance_test_categories"] = [
        "Request handshake: master MCmd accepted by SCmdAccept, with and "
        "without wait states.",
        "Single read (RD): SResp=DVA + SData returned and accepted by "
        "MRespAccept.",
        "Posted write (WR): accepted by SCmdAccept with no response.",
        "Non-posted write (WRNP): SResp=DVA response returned.",
        "Datahandshake write: MDataValid/SDataAccept decoupled from the "
        "request.",
        "Burst read (precise INCR, single request): SRespLast-terminated "
        "response beats.",
        "Burst write with datahandshake: MDataLast-terminated data beats.",
        "Address sequences: INCR / WRAP / STRM / XOR / 2D block (BLCK).",
        "MByteEn byte-lane selection on partial-width transfers.",
        "Read exclusive / read linked (RDEX/RDL) + WRC store-conditional "
        "(SResp=FAIL on lost reservation).",
        "Response codes: NULL / DVA / FAIL / ERR.",
        "Threads (MThreadID/SThreadID): concurrent flows, no inter-thread "
        "ordering.",
        "Tags (MTagID/STagID): out-of-order responses within a thread.",
        "Per-thread flow control: SThreadBusy / MThreadBusy.",
        "Sideband: Control/Status register access, SInterrupt, MError/SError.",
        "Reset: interface held idle while Reset_n is asserted.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP-equivalent fields (n/a for an interface spec).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = []
    d["notes"] = (
        "OCP is an on-chip core interface specification; it defines no OTP/fuse "
        "content. Any configuration (address/data widths, threads, tags, "
        "datahandshake, which commands are legal) is set at design/elaboration "
        "time via the RTL configuration parameters or a named profile, not "
        "burned into fuses. This layer is genuinely N/A for the OCP contract.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["single_read_sequence"] = [
        "1. Master drives MCmd=RD and MAddr.",
        "2. Slave asserts SCmdAccept; the request handshake completes on that "
        "rising edge.",
        "3. Slave drives SResp=DVA and SData in the response phase.",
        "4. Master asserts MRespAccept; the response handshake completes.",
    ]
    d["single_write_sequence"] = [
        "1. Master drives MCmd=WR, MAddr, MData, MByteEn.",
        "2. Slave asserts SCmdAccept; the (posted) write is accepted — no "
        "response.",
    ]
    d["non_posted_write_sequence"] = [
        "1. Master drives MCmd=WRNP, MAddr, MData.",
        "2. Slave asserts SCmdAccept.",
        "3. Slave drives SResp=DVA (write accepted); master asserts "
        "MRespAccept.",
    ]
    d["burst_read_sequence"] = [
        "1. Master drives MCmd=RD, MAddr, MBurstLength=N, MBurstSeq=INCR, "
        "MBurstSingleReq=1; slave asserts SCmdAccept.",
        "2. Slave returns N response beats, each SResp=DVA + SData, with "
        "SRespLast on the last beat; master asserts MRespAccept each beat.",
    ]
    d["datahandshake_write_burst_sequence"] = [
        "1. Master drives MCmd=WR, MAddr, MBurstLength=N, MBurstSeq=INCR; slave "
        "asserts SCmdAccept.",
        "2. Master sends N MDataValid beats (MData/MDataByteEn), MDataLast on "
        "the last; each accepted by SDataAccept.",
    ]
    d["interrupt_sequence"] = [
        "1. The slave asserts SInterrupt.",
        "2. The master services the interrupt and clears the source (via a "
        "sideband Status read or an OCP register access).",
    ]
    d["reset_sequence"] = [
        "1. Reset_n asserted (active low): the OCP interface is held in its "
        "idle state (MCmd=IDLE, SResp=NULL).",
        "2. Reset_n deasserted: transfers resume subject to the SCmdAccept / "
        "SDataAccept / MRespAccept handshakes.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration (n/a; synchronous-logic interface).
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Handshake timing closure", "purpose": "Verify the OCP phase "
         "handshakes (SCmdAccept / SDataAccept / MRespAccept) meet setup/hold "
         "at the OCP clock (an STA / timing-closure concern, not a lab-bench "
         "measurement)."},
        {"name": "EnableClk gating correctness", "purpose": "Validate that "
         "active OCP edges qualified by EnableClk behave correctly."},
    ]
    d["notes"] = (
        "OCP is a synchronous-logic on-chip interface; there is no analog/lab "
        "calibration in the specification. Timing is closed by synthesis/STA, "
        "not by bench calibration. This layer is essentially N/A for the OCP "
        "contract.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — versioning + traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "OCP-IP Open Core Protocol Specification"
    f["previous_versions"] = [
        "The OCP specification was maintained by the OCP-IP Association across "
        "successive releases and later contributed to Accellera Systems "
        "Initiative.",
    ]
    f["key_changes"] = [
        {"version": "OCP Specification",
         "summary": "Defines the bus-independent point-to-point synchronous "
         "master/slave socket with dataflow, sideband, and test signal groups; "
         "the request/datahandshake/response phases; MCmd/SResp encodings; and "
         "burst/tag/thread extensions, all configurable via the RTL "
         "configuration and named profiles."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "Accellera stewardship",
         "summary": "OCP-IP work was contributed to Accellera; OCP remains a "
         "reference bus-independent core socket alongside AMBA-family "
         "interfaces."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "master_only_presents_commands",
         "rule": "Only the master presents commands on MCmd; the slave only "
                 "responds.",
         "trap": "Expecting a slave to initiate a transfer."},
        {"trap_name": "accept_gates_each_phase",
         "rule": "SCmdAccept gates the request, SDataAccept the datahandshake, "
                 "MRespAccept the response; the driver must hold its phase "
                 "stable until its accept asserts.",
         "trap": "Changing MCmd/MData/SResp before the corresponding accept "
                 "completes the phase."},
        {"trap_name": "datahandshake_is_optional",
         "rule": "The datahandshake phase exists only when configured; "
                 "otherwise write data rides with the request.",
         "trap": "Assuming MDataValid/SDataAccept exist on an interface that "
                 "did not configure datahandshake."},
        {"trap_name": "thread_vs_tag_ordering",
         "rule": "No ordering across threads; in-order within a thread unless "
                 "tags permit out-of-order responses.",
         "trap": "Assuming responses always return in request order."},
        {"trap_name": "ocp_is_not_axi_or_wishbone",
         "rule": "OCP uses the M/S-prefixed MCmd/SCmdAccept/SResp/MRespAccept "
                 "model, not AXI xVALID/xREADY 5-channel, AHB HTRANS/HREADY, "
                 "Wishbone CYC/STB/ACK, Avalon waitrequest/readdatavalid, or "
                 "TileLink Get/Put/Acquire/Grant.",
         "trap": "Wiring a sibling-bus handshake directly to OCP without a "
                 "bus wrapper."},
    ]
    f["version_naming_history_note"] = (
        "The Open Core Protocol Specification is maintained by the OCP-IP "
        "Association (contributed to Accellera). Facts here are grounded in the "
        "public OCP specification: the bus-independent point-to-point "
        "synchronous master/slave socket; the dataflow / sideband / test "
        "signal groups; the dataflow basic signals MCmd / MAddr / MData / "
        "MByteEn / SCmdAccept / SResp / SData / MRespAccept (+ MDataValid / "
        "SDataAccept); the request/datahandshake/response phases; the MCmd "
        "encoding (IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST) and SResp encoding "
        "(NULL/DVA/FAIL/ERR); the burst (MBurstSeq INCR/WRAP/STRM/XOR/BLCK), "
        "tag (MTagID/STagID), and thread (MThreadID/SThreadID) extensions; and "
        "the RTL-configuration / named-profile configurability.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / property tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["signal_group_table"] = {
        "header_columns": ["Group", "Purpose"],
        "rows": [
            ["Dataflow", "request/datahandshake/response transfer"],
            ["Sideband", "out-of-band control/status/interrupt/error/reset"],
            ["Test", "scan / JTAG (IEEE 1149.1) / clock control"],
        ],
    }
    f["mcmd_encoding_table"] = {
        "header_columns": ["Code", "Command", "Meaning"],
        "rows": [[c, n, m] for (c, n, m) in _MCMD_ENCODING],
    }
    f["sresp_encoding_table"] = {
        "header_columns": ["Code", "Response", "Meaning"],
        "rows": [[c, n, m] for (c, n, m) in _SRESP_ENCODING],
    }
    f["dataflow_signal_table"] = {
        "header_columns": ["Signal", "Direction", "Role"],
        "rows": [
            ["MCmd", "master->slave", "3-bit command"],
            ["MAddr", "master->slave", "transfer address"],
            ["MData", "master->slave", "write data"],
            ["MByteEn", "master->slave", "byte-lane select"],
            ["MDataValid", "master->slave", "write data valid (datahandshake)"],
            ["MRespAccept", "master->slave", "accept the response"],
            ["SCmdAccept", "slave->master", "accept the request"],
            ["SData", "slave->master", "read data"],
            ["SDataAccept", "slave->master", "accept write data (datahandshake)"],
            ["SResp", "slave->master", "2-bit response"],
        ],
    }
    f["burst_sequence_table"] = {
        "header_columns": ["MBurstSeq", "Meaning"],
        "rows": [
            ["INCR", "incrementing address burst"],
            ["WRAP", "wrapping (cache-line) address burst"],
            ["STRM", "streaming (constant address) burst"],
            ["XOR", "XOR (critical-word-first) address sequence"],
            ["UNKN", "unknown / user-defined sequence"],
            ["DFLT1/DFLT2", "user-defined default sequences"],
            ["BLCK", "2-dimensional block burst"],
        ],
    }
    f["encoding_note"] = (
        "OCP defines no line code; it is a synchronous-logic interface. Byte "
        "selection is by MByteEn. The 'tables' here are the signal-group, "
        "MCmd command-encoding, SResp response-encoding, dataflow signal-role, "
        "and MBurstSeq burst-sequence tables from the OCP specification.")
    f["tables"] = [
        "Signal-group table (Dataflow / Sideband / Test)",
        "MCmd command-encoding table (3-bit, 8 commands)",
        "SResp response-encoding table (2-bit, 4 responses)",
        "Dataflow signal-role table",
        "MBurstSeq burst-sequence table",
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
        "Master/slave roles with the declared dataflow signal subset (MCmd, "
        "SCmdAccept, SResp, MRespAccept as needed, + MAddr/MData/SData/"
        "MByteEn).",
        "Correct phase handshakes: SCmdAccept gates the request, SDataAccept "
        "the datahandshake, MRespAccept the response.",
        "Legal MCmd encoding (IDLE/WR/RD/RDEX/RDL/WRNP/WRC/BCST) and SResp "
        "encoding (NULL/DVA/FAIL/ERR).",
        "Driver holds its phase stable until the corresponding accept asserts.",
        "Burst behavior consistent with MBurstSeq/MBurstLength/MBurstPrecise "
        "and the MReqLast/MDataLast/SRespLast markers.",
        "Thread/tag ordering (no inter-thread ordering; in-order within a "
        "thread unless tagged).",
        "Matched configuration / profile between master and slave.",
    ]
    f["must_not_have_properties"] = [
        "AXI-style xVALID/xREADY 5-channel handshakes presented as native OCP.",
        "AHB HTRANS/HREADY or Wishbone CYC/STB/ACK presented as native OCP.",
        "Avalon waitrequest/readdatavalid or TileLink Get/Put/Acquire/Grant "
        "presented as native OCP.",
        "A line code or differential physical layer (OCP is "
        "synchronous-logic).",
        "Changing MCmd / MData / SResp before the corresponding accept "
        "completes the phase.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "request handshake violation", "trigger": "Master changes the "
         "request before SCmdAccept asserts."},
        {"mode": "datahandshake violation", "trigger": "Master changes the "
         "write-data beat before SDataAccept asserts."},
        {"mode": "response handshake violation", "trigger": "Slave changes the "
         "response before MRespAccept asserts."},
        {"mode": "illegal command/response", "trigger": "MCmd or SResp outside "
         "the defined encoding."},
        {"mode": "ordering violation", "trigger": "Out-of-order responses "
         "within a thread without tags, or assumed ordering across threads."},
    ]
    f["min_link_constraint"] = (
        "A compliant connection requires a matched master/slave socket pair "
        "with a compatible configuration (or a named profile both agree on), "
        "connected point-to-point (a bus wrapper bridges to the interconnect).")
    f["reset_behavior_compliance"] = (
        "While Reset_n is asserted the OCP interface is held idle (MCmd=IDLE, "
        "SResp=NULL); after reset, transfers proceed subject to the phase "
        "accept handshakes.")
    f["ocp_distinguishers"] = (
        "OCP is identified by the M/S-prefixed signal model: MCmd (master "
        "command) + SCmdAccept (slave request accept) + SResp (slave response) "
        "+ MRespAccept (master response accept), with MData/SData and MAddr, "
        "the request/datahandshake/response phases, and the dataflow / "
        "sideband / test signal grouping. This is distinct from AXI "
        "(xVALID/xREADY 5-channel), AHB (HADDR/HTRANS/HREADY), Wishbone "
        "(CYC/STB/ACK), Avalon (waitrequest/readdatavalid), and TileLink "
        "(Get/Put/Acquire/Grant).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog + dependency graph.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Dataflow", "direction": "bidirectional master<->slave",
         "purpose": "Request/datahandshake/response transfer.",
         "active_levels": "MCmd/MAddr/MData/MByteEn master->slave; "
         "SCmdAccept/SResp/SData slave->master; MRespAccept master->slave",
         "idle_level": "MCmd=IDLE, SResp=NULL"},
        {"name": "Sideband", "direction": "bidirectional master<->slave",
         "purpose": "Out-of-band control/status/interrupt/error/reset.",
         "active_levels": "Control/ControlWr/MFlag/MError master->slave; "
         "Status/SFlag/SInterrupt/SError slave->master; Reset_n",
         "idle_level": "flags/interrupt deasserted"},
        {"name": "Test", "direction": "DFT access",
         "purpose": "Scan / JTAG / clock control.",
         "active_levels": "Scanctrl/Scanin/TCK/TMS/TDI in; Scanout/TDO out",
         "idle_level": "test inactive"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "request accepted",
         "meaning": "MCmd valid and SCmdAccept asserted on the same edge."},
        {"name": "request wait",
         "meaning": "SCmdAccept deasserted; master holds the request."},
        {"name": "write-data beat accepted",
         "meaning": "MDataValid and SDataAccept asserted on the same edge."},
        {"name": "response accepted",
         "meaning": "SResp non-NULL and MRespAccept asserted on the same "
         "edge."},
        {"name": "thread busy", "meaning": "SThreadBusy/MThreadBusy asserted; "
         "the thread cannot accept a transfer."},
    ]
    f["packet_types_summary"] = [
        {"class": "OCP command (MCmd)",
         "members": [n for (_, n, _) in _MCMD_ENCODING],
         "count": len(_MCMD_ENCODING)},
        {"class": "OCP response (SResp)",
         "members": [n for (_, n, _) in _SRESP_ENCODING],
         "count": len(_SRESP_ENCODING)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "signal_group_count": len(_SIGNAL_GROUPS),
        "dataflow_basic_signal_count": len(_DATAFLOW_BASIC),
        "sideband_signal_count": len(_SIDEBAND_SIGNALS),
        "test_signal_count": len(_TEST_SIGNALS),
        "mcmd_command_count": len(_MCMD_ENCODING),
        "sresp_response_count": len(_SRESP_ENCODING),
        "role_pair": "master / slave",
    })
    f["global_signals"] = [
        {"name": "Clk", "purpose": "OCP clock; all signals (except Reset_n / "
         "async interrupt/error) sampled on its rising edge."},
        {"name": "EnableClk", "purpose": "Qualifies active OCP clock edges."},
        {"name": "Reset_n", "purpose": "Active-low reset; interface held idle "
         "while asserted."},
        {"name": "SInterrupt", "purpose": "Slave-to-master interrupt request."},
    ]
    f["dependency_graph"] = {
        "common_rule": "All OCP signals (except Reset_n and async interrupt/"
        "error) are synchronous to Clk and respect Reset_n. The request phase "
        "depends on SCmdAccept; the datahandshake phase on SDataAccept; the "
        "response phase on MRespAccept.",
        "data_dependency": "SData (read) depends on an accepted RD request and "
        "the slave's latency; the datahandshake write beat depends on "
        "MDataValid + SDataAccept; thread progress depends on "
        "SThreadBusy/MThreadBusy.",
    }
    f["handshake_pairs"] = [
        {"name": "MCmd/SCmdAccept", "from": "master", "to": "slave",
         "rule": "Request phase: completes when MCmd is valid and SCmdAccept "
         "is asserted."},
        {"name": "MDataValid/SDataAccept", "from": "master", "to": "slave",
         "rule": "Datahandshake phase: write-data beat accepted when both are "
         "asserted."},
        {"name": "SResp/MRespAccept", "from": "slave", "to": "master",
         "rule": "Response phase: completes when SResp is non-NULL and "
         "MRespAccept is asserted."},
        {"name": "SThreadBusy/MThreadBusy", "from": "receiver", "to": "sender",
         "rule": "Per-thread back-pressure without stalling the whole socket."},
        {"name": "SInterrupt", "from": "slave", "to": "master",
         "rule": "Sideband interrupt request."},
    ]
    f["ordering_rules"] = {
        "intra_thread": "Within a single thread, transfers complete in order "
        "unless tags (MTagID/STagID) permit out-of-order responses.",
        "inter_thread": "Across threads (MThreadID/SThreadID) there is no "
        "ordering constraint; responses may interleave.",
        "connection": "MConnID identifies the initiator connection for "
        "QoS/security/routing.",
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
        "Point-to-point bus-independent core socket. Each OCP instance connects "
        "one master to one slave; a bus wrapper translates OCP to the on-chip "
        "interconnect so the core is isolated from the bus. Concurrency within "
        "a socket comes from threads, not from a shared bus.")
    f["supported_topologies"] = [
        {"name": "Master core <-> bus wrapper", "description": "An IP core's "
         "OCP master socket connects point-to-point to a bus wrapper's OCP "
         "slave socket."},
        {"name": "Bus wrapper <-> slave core", "description": "A bus wrapper's "
         "OCP master socket connects to a slave core's OCP slave socket."},
        {"name": "Peer-to-peer (two instances)", "description": "Two entities "
         "communicate peer-to-peer with two OCP instances, one per "
         "direction."},
        {"name": "Multi-threaded socket", "description": "A single OCP socket "
         "carrying concurrent independent threads (MThreadID/SThreadID)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "OCP master", "description": "The controlling entity; the "
         "only entity that presents commands (MCmd)."},
        {"role": "OCP slave", "description": "Responds to commands; asserts "
         "SCmdAccept and drives SResp/SData."},
        {"role": "Bus wrapper", "description": "Presents an OCP slave socket to "
         "a master core and an OCP master socket to a slave core, bridging OCP "
         "to the on-chip interconnect."},
    ]
    f["interconnect_role"] = (
        "OCP itself does not define an interconnect — it is a point-to-point "
        "socket. The on-chip bus behind the OCP wrapper provides address "
        "decoding, arbitration between masters, and routing; the wrapper "
        "translates between OCP phases and the bus protocol, so an OCP-wrapped "
        "core can be reused on any bus that provides an OCP wrapper.")
    f["ordering_guarantees"] = {
        "intra_thread": "In order within a thread unless tags permit "
        "out-of-order responses.",
        "inter_thread": "No ordering across threads.",
        "connection_tracking": "MConnID identifies the initiator connection.",
    }
    f["memory_vs_peripheral_regions"] = (
        "An OCP slave is address-mapped: the master drives MAddr (+ optional "
        "MAddrSpace) to select a location within the connected slave. OCP is "
        "point-to-point, so address decoding to multiple targets is the job of "
        "the bus behind the wrapper.")
    dc = _ensure_dict(f, "device_classification")
    dc["master"] = "Processor / DMA / bus-wrapper presenting commands."
    dc["slave"] = "Memory / register peripheral responding to commands."
    dc["bus_wrapper"] = "Translates OCP to the on-chip interconnect."
    dc["threaded_master"] = "Issues concurrent transfers on multiple threads."
    f["default_signal_values_evidence_tables"] = [
        "OCP-IP Open Core Protocol Specification — signal groups and dataflow "
        "signal roles",
        "Request / datahandshake / response phase timing figures",
        "MCmd command encoding and SResp response encoding tables",
        "Burst (MBurstSeq), tag (MTagID/STagID), and thread "
        "(MThreadID/SThreadID) extension descriptions",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK (interface-level, not PDK).
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["interface_constraints"] = {
        "signaling": "single-ended synchronous logic",
        "line_encoding": "none",
        "clocking": "synchronous to the OCP clock Clk; EnableClk qualifies "
                    "active edges",
        "request_handshake": "MCmd / SCmdAccept",
        "datahandshake": "MDataValid / SDataAccept (when configured)",
        "response_handshake": "SResp / MRespAccept",
        "mcmd_width_bits": 3,
        "sresp_width_bits": 2,
        "burst_supported": True,
        "threads_supported": True,
        "tags_supported": True,
        "topology": "point-to-point",
    }
    f["notes"] = (
        "OCP is an on-chip interface specification; it imposes interface "
        "timing/handshake constraints (the per-phase accept handshakes, "
        "synchronous sampling on Clk), not PDK-specific SDC/floorplan rules. "
        "Physical constraints (timing closure at the OCP clock, the bus "
        "wrapper's implementation) are chip/SoC concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan (interface-level observability).
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = True
    f["in_band_test_facilities"] = [
        {"name": "Scan signals", "purpose": "Scanctrl/Scanin/Scanout drive the "
         "scan chains for manufacturing DFT — part of the OCP test signal "
         "group."},
        {"name": "JTAG (IEEE 1149.1)", "purpose": "TCK/TMS/TDI/TDO/TRST_N "
         "boundary scan in the OCP test signal group."},
        {"name": "Clock control", "purpose": "ClkByp/TestClk bypass/override "
         "the functional clock for at-speed test."},
        {"name": "SResp / MError / SError", "purpose": "Response and error "
         "qualifiers report transfer/data faults."},
        {"name": "Info side-channels", "purpose": "MDataInfo/SDataInfo can "
         "carry parity for data integrity."},
    ]
    f["internal_diagnostics_observability"] = [
        "Phase-handshake observability (SCmdAccept / SDataAccept / "
        "MRespAccept).",
        "SResp response codes (NULL/DVA/FAIL/ERR).",
        "MError/SError sideband error indication.",
        "SThreadBusy/MThreadBusy per-thread flow-control observability.",
        "SInterrupt interrupt status.",
    ]
    f["out_of_band_test_facilities"] = [
        "OCP protocol checkers / BFMs in simulation.",
        "JTAG (IEEE 1149.1) boundary scan via the test signal group.",
    ]
    f["notes"] = (
        "OCP has a dedicated test signal group (scan, JTAG IEEE 1149.1, clock "
        "control) in addition to the protocol-level response/error qualifiers "
        "and per-thread busy observability. This makes DFT access part of the "
        "OCP socket itself rather than a purely chip-level concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (n/a at protocol level).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = False
    f["link_power_management_states"] = []
    f["notes"] = (
        "The OCP specification defines no protocol-level power states. "
        "EnableClk can qualify active OCP clock edges (enabling clock gating) "
        "and Reset_n holds the interface idle, but power management (power "
        "domains, retention) is an SoC/chip concern, not part of the OCP "
        "interface contract.")
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
        "Request handshake (MCmd/SCmdAccept) with and without wait states.",
        "Single read (RD) and posted write (WR).",
        "Non-posted write (WRNP) with SResp=DVA response.",
        "Datahandshake write (MDataValid/SDataAccept).",
        "Burst read (precise INCR, single request, SRespLast).",
        "Burst write with datahandshake (MDataLast).",
        "Address sequences INCR/WRAP/STRM/XOR and 2D block (BLCK).",
        "MByteEn byte-lane selection.",
        "Read exclusive / read linked (RDEX/RDL) + WRC store-conditional.",
        "Response codes NULL/DVA/FAIL/ERR.",
        "Threads (MThreadID/SThreadID): concurrency and inter-thread "
        "independence.",
        "Tags (MTagID/STagID): out-of-order responses within a thread.",
        "Per-thread flow control (SThreadBusy/MThreadBusy).",
        "Sideband Control/Status, SInterrupt, MError/SError.",
        "Reset behavior (interface idle while Reset_n asserted).",
    ]
    f["notes"] = (
        "The OCP specification does not ship a packaged testbench, but implies "
        "a verification plan covering the request/datahandshake/response "
        "handshakes, the MCmd/SResp encodings, bursts, byte enables, atomic "
        "(RDEX/RDL/WRC) commands, threads, tags, per-thread flow control, "
        "sideband, and reset. OCP protocol checkers / BFMs provide the "
        "conformance checks.")
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
        "SResp = FAIL / ERR flag failed / unserviceable transfers rather than "
        "silently corrupting.",
        "MError / SError sideband signals report errors out of band.",
        "MByteEn / MDataByteEn ensure only intended byte lanes are written.",
        "MDataInfo / SDataInfo info channels can carry parity for data "
        "integrity.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Access control / isolation is an interconnect/SoC concern: MConnID "
        "identifies the initiator connection so the system can apply "
        "QoS/security/routing policy per master.",
        "Carried-application security (encryption, authentication) is the "
        "responsibility of the connected IP, not of the OCP interface "
        "contract.",
    ]
    f["notes"] = (
        "OCP is an on-chip core interface specification with no built-in "
        "cryptography. Its protections are anti-corruption qualifiers (SResp "
        "FAIL/ERR, MError/SError, byte enables, info-channel parity) and the "
        "access-control/isolation the interconnect can apply using MConnID. "
        "Confidentiality/integrity/authentication are out of scope for the OCP "
        "contract.")
    _write(p, d)
