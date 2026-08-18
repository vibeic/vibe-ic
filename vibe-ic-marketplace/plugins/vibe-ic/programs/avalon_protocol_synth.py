"""Intel/Altera Avalon Interface protocol synth helper (protocol #54).

ic_class-gated overlay for the Avalon structural signature: the family of
standard FPGA-SoC interfaces defined by the Intel (formerly Altera) "Avalon
Interface Specifications" (MNL-AVABUSREF) and used by Platform Designer (Qsys),
Nios II, and Quartus. The two primary interface types are:

  - Avalon Memory-Mapped (Avalon-MM): an address-based read/write interface
    with host (master) / agent (slave) roles, signals address / read / write /
    readdata / writedata / byteenable / waitrequest / readdatavalid /
    burstcount / chipselect, wait-state insertion via waitrequest, fixed and
    variable (readdatavalid) read latency, pipelined transfers, and bursts.
  - Avalon Streaming (Avalon-ST): a unidirectional source / sink interface
    with data / valid / ready / channel / error / startofpacket / endofpacket /
    empty, readyLatency backpressure, and packetized or non-packetized streams.

The supporting interface types are Conduit, Interrupt (irq), Clock, Reset, and
the Memory-Mapped Tristate Conduit (Avalon-TC). Applies the Intel Avalon
Interface Specifications (MNL-AVABUSREF) spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(the Avalon-MM waitrequest + readdatavalid wait-state/pipelined-read signature,
or the Avalon-ST source/sink ready/valid + startofpacket/endofpacket streaming
signature, together with the Avalon name/host-agent/Platform-Designer
vocabulary) read from the L-doc / input_doc CONTENT blob only. It NEVER reads
the input-document filename or the benchmark folder name.

Sibling disambiguation — Avalon vs AXI / AHB / Wishbone. All four are SoC
interconnect protocols and so classify as `bus_interconnect_protocol`. They are
distinguished by their wire-level handshake vocabulary:

  - AXI uses five independent channels with xVALID/xREADY (ARVALID/AWVALID/
    RVALID/BVALID/WVALID) handshakes.
  - AHB uses HADDR/HTRANS/HREADY/HRESP with a pipelined address/data phase.
  - Wishbone uses CYC_O/STB_O/ACK_I (cycle/strobe/acknowledge) handshake.
  - Avalon uses waitrequest (wait-state) + readdatavalid (pipelined-read
    completion) on Avalon-MM, and source/sink ready/valid +
    startofpacket/endofpacket framing on Avalon-ST.

The Avalon detector REQUIRES the Avalon-MM (waitrequest + readdatavalid) or
Avalon-ST (startofpacket + endofpacket + ready/valid streaming) structural
signature and DEFERS when the doc is AXI-primary (the xVALID/xREADY 5-channel
set dominates with no Avalon waitrequest/readdatavalid/Avalon-MM/Avalon-ST
signature) or Wishbone-primary (CYC/STB/ACK dominate with no Avalon signature),
so it cannot false-fire on an AXI / AHB / Wishbone spec. Because the Wishbone
runner sub-detector can false-fire on an Avalon spec that merely *mentions*
Wishbone, the Avalon synth FORCE-OVERWRITES (direct-assign, NOT setdefault)
every key it owns and is wired to run LAST so its Avalon-canonical values win.

Public entry: ``apply_avalon_synth(generated_docs_dir, is_avalon,
avalon_ic_name)``. Module-level ``is_avalon(blob)`` is the content-only
detector.
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

# Canonical Avalon facts (Intel/Altera Avalon Interface Specifications,
# MNL-AVABUSREF).
_INTERFACE_TYPES = [
    "Avalon Memory-Mapped (Avalon-MM)",
    "Avalon Streaming (Avalon-ST)",
    "Avalon Conduit",
    "Avalon Interrupt",
    "Avalon Clock",
    "Avalon Reset",
    "Avalon Memory-Mapped Tristate Conduit (Avalon-TC)",
]
_MM_SIGNALS = [
    "address", "read", "write", "writedata", "readdata", "byteenable",
    "waitrequest", "readdatavalid", "burstcount", "chipselect",
    "beginbursttransfer", "response", "writeresponsevalid", "lock",
    "debugaccess",
]
_ST_SIGNALS = [
    "data", "valid", "ready", "channel", "error", "startofpacket",
    "endofpacket", "empty",
]


def is_avalon(blob: str) -> bool:
    """Content-only Avalon detector with an AXI/AHB/Wishbone sibling MUTEX.

    Fire on the Avalon structural signature: Avalon-MM (waitrequest +
    readdatavalid wait-state/pipelined-read), or Avalon-ST (source/sink
    ready/valid + startofpacket/endofpacket streaming), and/or the Avalon
    name + host/agent + Platform-Designer vocabulary. Defer if the doc is
    AXI-primary (xVALID/xREADY 5-channel set with NO Avalon signature) or
    Wishbone-primary (CYC/STB/ACK with NO Avalon signature). Reads ONLY the
    spec text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    name_token = "avalon" in low
    mm_token = ("avalon-mm" in low or "avalon mm" in low
                or "memory-mapped" in low and name_token)
    st_token = ("avalon-st" in low or "avalon st" in low
                or "streaming" in low and name_token)
    host_agent = (("host" in low and "agent" in low)
                  or ("master" in low and "slave" in low))
    platform_designer = ("platform designer" in low or "qsys" in low
                         or "nios" in low)

    # Avalon-MM structural signature: waitrequest wait-state + readdatavalid
    # pipelined-read completion (both absent from AXI/AHB/Wishbone).
    waitrequest = "waitrequest" in low
    readdatavalid = "readdatavalid" in low
    mm_structure = waitrequest and readdatavalid

    # Avalon-ST structural signature: source/sink ready/valid +
    # startofpacket/endofpacket framing.
    sop_eop = "startofpacket" in low and "endofpacket" in low
    ready_valid = "ready" in low and "valid" in low
    st_structure = sop_eop and ready_valid

    # HARD STRUCTURAL GATE. The runner enumerates a generic bus vocabulary
    # that includes the literal token "Avalon" (and the L9 interface_types
    # regexes list it), so foreign benchmarks (ethercat / hdlc / modbus / ...)
    # carry "avalon" in a candidate-interface list, and common words like
    # "memory-mapped", "ready", "valid", "host"/"agent", "streaming" appear in
    # many specs. A name-token-only or weak-word branch therefore MIS-FIRES.
    # The ONLY reliable Avalon-specific positive signals are the Avalon signal
    # NAMES: Avalon-MM `waitrequest` + `readdatavalid` together (unique to
    # Avalon-MM), or Avalon-ST `startofpacket` + `endofpacket` (+ ready/valid).
    # EVERY path that returns True REQUIRES at least one of these hard
    # structural signatures; the name/host-agent/Platform-Designer tokens only
    # corroborate, they never fire on their own.
    has_hard_structure = mm_structure or st_structure
    if not has_hard_structure:
        return False

    # Sibling MUTEX. An AXI-primary doc keys on the xVALID/xREADY 5-channel
    # handshake; a Wishbone-primary doc keys on CYC/STB/ACK. If either keys are
    # present we still require the Avalon hard structure above to have matched,
    # so this is belt-and-braces: defer if the doc is AXI/Wishbone-primary and
    # the only "structure" is an incidental token collision.
    axi_primary = (
        (("arvalid" in low or "awvalid" in low or "rvalid" in low
          or "bvalid" in low or "wvalid" in low)
         or ("axi" in low and "xvalid" in low))
        and not (waitrequest and readdatavalid)
        and not sop_eop
        and not (mm_token or st_token or name_token))
    wishbone_primary = (
        (("cyc_o" in low or "stb_o" in low or "ack_i" in low)
         or ("wishbone" in low and "cyc" in low and "stb" in low
             and "ack" in low))
        and not (waitrequest and readdatavalid)
        and not sop_eop
        and not (mm_token or st_token or name_token))
    if axi_primary or wishbone_primary:
        return False

    # OCP-primary / AXI4-Stream-primary: these SoC-bus specs name Avalon's
    # signals in a comparison section (OCP mentions waitrequest/readdatavalid;
    # AXI4-Stream mentions startofpacket/endofpacket), tripping the hard
    # structure above. Defer on their OWN socket/stream signal signature, which
    # a real Avalon doc never carries: OCP = MCmd + SCmdAccept; AXI4-Stream =
    # the T-prefixed handshake TVALID + TREADY + TLAST.
    ocp_primary = ("mcmd" in low and "scmdaccept" in low)
    axi_stream_primary = ("tvalid" in low and "tready" in low and "tlast" in low)
    if ocp_primary or axi_stream_primary:
        return False

    return True


def apply_avalon_synth(generated_docs_dir: Path, is_avalon_flag: bool,
                       avalon_ic_name: Optional[str]) -> None:
    """Apply Avalon synth when the Avalon signature matched.

    Because Avalon classifies as `bus_interconnect_protocol`, a sibling synth
    (notably the Wishbone sub-detector, which can false-fire on an Avalon spec
    that merely mentions Wishbone) may have populated L1/L2/... first. This
    routine FORCE-OVERWRITES (direct assignment) every key it owns with the
    Avalon-canonical value; the runner wires it to run LAST so Avalon wins.
    """
    if not is_avalon_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if avalon_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = avalon_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = avalon_ic_name
                d["ic_name"] = avalon_ic_name
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
# L1 — Avalon datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "Avalon Interface Specifications"
    d["version"] = "Avalon Interface Specifications (MNL-AVABUSREF)"
    d["revised_date"] = "Intel/Altera Avalon Interface Specifications"
    d["manufacturer"] = "Intel Corporation (formerly Altera)"
    d["copyright"] = "© Intel Corporation"
    d["abstract"] = (
        "The Avalon Interface Specifications define a family of standard "
        "interfaces used to connect components (IP cores) inside an FPGA "
        "System-on-a-Chip. Avalon is the native interconnect contract of Intel "
        "(formerly Altera) Platform Designer (Qsys), the Nios II processor, and "
        "Quartus. Seven interface types are defined: Avalon Memory-Mapped "
        "(Avalon-MM), Avalon Streaming (Avalon-ST), Conduit, Interrupt, Clock, "
        "Reset, and Memory-Mapped Tristate Conduit (Avalon-TC). Avalon-MM is an "
        "address-based read/write interface with host (master) and agent "
        "(slave) roles, using address/read/write/readdata/writedata/byteenable "
        "with waitrequest wait-state insertion and readdatavalid pipelined-read "
        "completion, plus burst transfers. Avalon-ST is a unidirectional "
        "source-to-sink streaming interface using data/valid/ready with "
        "readyLatency backpressure and optional startofpacket/endofpacket "
        "packet framing. Platform Designer generates the interconnect fabric "
        "(address decoding, arbitration, data-path mux, width/burst adaptation, "
        "clock crossing) that wires Avalon interfaces together.")
    d["keywords"] = [
        "Avalon", "Avalon-MM", "Avalon-ST", "memory-mapped", "streaming",
        "host", "agent", "master", "slave", "waitrequest", "readdatavalid",
        "byteenable", "burstcount", "source", "sink", "ready", "valid",
        "startofpacket", "endofpacket", "Conduit", "Interrupt", "Clock",
        "Reset", "Tristate Conduit", "Platform Designer", "Qsys", "Nios II",
        "Quartus", "FPGA SoC", "interconnect",
    ]
    d["external_pins"] = [
        "Avalon-MM host/agent signals: address, read, write, writedata, "
        "readdata, byteenable, waitrequest, readdatavalid, burstcount, "
        "chipselect (interface uses the subset it needs)",
        "Avalon-ST source/sink signals: data, valid, ready, channel, error, "
        "startofpacket, endofpacket, empty",
        "Interrupt: irq (interrupt sender -> receiver)",
        "Conduit: arbitrary application-specific signals exported to the "
        "top level / device pins",
        "Clock: clk (clock source / sink); Reset: reset (reset source / sink)",
        "Tristate Conduit: shared tristate data/address signals to off-chip "
        "flash / SRAM",
    ]
    d["interface_types"] = list(_INTERFACE_TYPES)
    d["avalon_mm_signals"] = list(_MM_SIGNALS)
    d["avalon_st_signals"] = list(_ST_SIGNALS)
    d["modes_of_operation"] = [
        {"name": "Avalon-MM (Memory-Mapped)",
         "roles": "host (master) / agent (slave)",
         "note": "Address-based read/write; waitrequest wait-states; fixed and "
                 "variable (readdatavalid) read latency; pipelined reads; "
                 "byteenable; bursts (burstcount)."},
        {"name": "Avalon-ST (Streaming)",
         "roles": "source / sink",
         "note": "Unidirectional point-to-point; data/valid/ready handshake "
                 "with readyLatency backpressure; optional "
                 "startofpacket/endofpacket packet framing; channel/error/"
                 "empty."},
        {"name": "Conduit", "roles": "exporter",
         "note": "Arbitrary signals exported to the top level / pins."},
        {"name": "Interrupt", "roles": "sender / receiver",
         "note": "irq lines from senders to a receiver (typically the "
                 "processor)."},
        {"name": "Clock / Reset", "roles": "source / sink",
         "note": "Drive or receive clocks and resets; enable clock-crossing "
                 "and reset synchronization."},
        {"name": "Tristate Conduit (Avalon-TC)", "roles": "host / agent",
         "note": "Memory-mapped transfers to off-chip devices sharing tristate "
                 "bidirectional pins (flash, SRAM)."},
    ]
    d["key_features"] = [
        "Standard FPGA-SoC interface family for Intel/Altera Platform Designer "
        "(Qsys), Nios II, and Quartus.",
        "Seven interface types: Avalon-MM, Avalon-ST, Conduit, Interrupt, "
        "Clock, Reset, Tristate Conduit (Avalon-TC).",
        "Avalon-MM: address-based read/write; host (master) / agent (slave) "
        "roles; address/read/write/readdata/writedata/byteenable.",
        "waitrequest provides agent-driven wait-state insertion: the host "
        "holds address/data/controls until the agent deasserts waitrequest.",
        "readdatavalid provides variable-latency pipelined-read completion; "
        "fixed read latency (readLatency) is also supported.",
        "Pipelined reads allow multiple read transfers in flight; burst "
        "transfers via burstcount and beginbursttransfer.",
        "Avalon-ST: unidirectional source -> sink streaming; data/valid/ready "
        "handshake with readyLatency backpressure.",
        "Avalon-ST packets: startofpacket / endofpacket framing with empty on "
        "the final beat; channel and error qualifiers.",
        "Transfer properties: addressUnits (word vs byte), readLatency, "
        "setupTime, holdTime, waitrequestAllowance, burst alignment, "
        "readyLatency, symbolsPerBeat.",
        "Platform Designer generates the interconnect: address decoding, "
        "round-robin arbitration, data-path mux, width/burst adaptation, "
        "clock crossing.",
    ]
    d["topology_summary"] = (
        "Avalon-MM connects hosts to agents through Platform-Designer-generated "
        "interconnect (address decode + arbitration + data-path mux + width/"
        "burst adaptation + clock crossing). Avalon-ST is a direct "
        "point-to-point source-to-sink connection with optional automatically "
        "inserted adapters. Conduit/Interrupt/Clock/Reset/Tristate-Conduit are "
        "supporting interfaces.")
    d["use_cases"] = [
        "Connecting a Nios II processor to memory, registers, and peripherals "
        "over Avalon-MM",
        "High-throughput data pipelines (DSP, video, networking) over Avalon-ST",
        "Composing IP cores into an FPGA SoC with Platform Designer (Qsys)",
        "Exporting application signals to device pins via Conduit interfaces",
        "Connecting off-chip flash / SRAM with shared tristate pins via "
        "Avalon-TC",
        "Bridging to AXI / AHB through Platform-Designer-generated bridges",
    ]
    d["revision_history"] = [
        {"version": "Avalon Interface Specifications",
         "date": "Intel/Altera (MNL-AVABUSREF)",
         "description": "Family of Avalon interfaces (Avalon-MM, Avalon-ST, "
                        "Conduit, Interrupt, Clock, Reset, Tristate Conduit) "
                        "used by Platform Designer / Qsys / Nios II / "
                        "Quartus."},
    ]
    d["overview"] = (
        "The Avalon Interface Specifications (MNL-AVABUSREF) define the "
        "standard interfaces that connect IP cores inside an Intel/Altera FPGA "
        "System-on-a-Chip. Platform Designer (formerly Qsys) reads the Avalon "
        "interfaces a component advertises and generates the interconnect that "
        "wires them together. The two primary interfaces are Avalon "
        "Memory-Mapped (Avalon-MM) and Avalon Streaming (Avalon-ST). Avalon-MM "
        "is an address-based read/write interface between a host (master) and "
        "an agent (slave): the host drives address, read/write, writedata, and "
        "byteenable; the agent returns readdata. The agent stalls the host by "
        "asserting waitrequest (wait-state insertion), and signals "
        "variable-latency pipelined read data with readdatavalid (a "
        "fixed-latency readLatency mode is also supported). Bursts use "
        "burstcount/beginbursttransfer. Avalon-ST is a unidirectional "
        "point-to-point streaming interface between a source and a sink, using "
        "the data/valid/ready handshake with a readyLatency backpressure "
        "property; packetized streams are framed by startofpacket and "
        "endofpacket with empty marking unused symbols in the final beat. The "
        "supporting interface types are Conduit (arbitrary exported signals), "
        "Interrupt (irq sender/receiver), Clock, Reset, and the Memory-Mapped "
        "Tristate Conduit (Avalon-TC) for off-chip shared-pin devices.")
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
        "Family of FPGA-SoC interfaces. The primary types are Avalon "
        "Memory-Mapped (Avalon-MM, address-based read/write, host/agent) and "
        "Avalon Streaming (Avalon-ST, unidirectional source/sink). Supporting "
        "types: Conduit, Interrupt, Clock, Reset, Memory-Mapped Tristate "
        "Conduit (Avalon-TC). Interconnect is generated by Platform Designer "
        "(Qsys).")
    po["duplex"] = (
        "Avalon-MM is bidirectional (host writes writedata, reads readdata) on "
        "a shared address-mapped interface. Avalon-ST is unidirectional "
        "(source -> sink, point-to-point).")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["forwarded_clock"] = False
    po["parallel_synchronous"] = True
    po["encoding"] = (
        "Parallel synchronous logic interface; no line code. Avalon-MM data "
        "integrity / byte selection is by byteenable; Avalon-ST framing is by "
        "valid/ready and startofpacket/endofpacket.")
    po["roles"] = {
        "avalon_mm": "host (master) / agent (slave)",
        "avalon_st": "source / sink",
    }
    po["avalon_mm_signals"] = list(_MM_SIGNALS)
    po["avalon_st_signals"] = list(_ST_SIGNALS)
    po["interface_types"] = list(_INTERFACE_TYPES)
    po["mm_handshake"] = (
        "waitrequest (agent-driven wait-state insertion) + readdatavalid "
        "(variable-latency pipelined read completion); fixed readLatency mode "
        "also supported.")
    po["st_handshake"] = (
        "data/valid/ready with readyLatency backpressure; startofpacket / "
        "endofpacket / empty packet framing.")
    po["transfer_properties"] = [
        "addressUnits: word vs byte (symbol) addressing",
        "readLatency (fixed read latency)",
        "setupTime / holdTime",
        "waitrequestAllowance",
        "burst alignment / maximumPendingReadTransactions",
        "readyLatency (Avalon-ST)",
        "symbolsPerBeat / dataBitsPerSymbol (Avalon-ST)",
    ]
    po["platform_designer"] = (
        "Platform Designer (Qsys) generates interconnect: address decoding, "
        "round-robin arbitration, data-path multiplexing, width adaptation "
        "(byteenable), burst adaptation, and clock-domain crossing.")
    d["functional_requirements"] = [
        {"id": "FR-MM-01", "text": "An Avalon-MM interface is either a host "
         "(master) or an agent (slave). A host initiates read/write transfers "
         "by driving an address; an agent responds. Platform Designer routes a "
         "host transfer to the addressed agent and arbitrates when multiple "
         "hosts share an agent."},
        {"id": "FR-MM-02", "text": "The Avalon-MM signal set (address, read, "
         "write, writedata, readdata, byteenable, waitrequest, readdatavalid, "
         "burstcount, chipselect, ...) is a superset; an interface uses only "
         "the signals it needs. byteenable selects active byte lanes of "
         "writedata/readdata."},
        {"id": "FR-MM-03", "text": "An agent inserts wait-states by asserting "
         "waitrequest; the host holds address, read/write, writedata, and "
         "byteenable stable until the agent deasserts waitrequest, at which "
         "point the transfer completes."},
        {"id": "FR-MM-04", "text": "A fixed-latency pipelined agent returns "
         "readdata exactly readLatency cycles after a read is accepted "
         "(readLatency=0 is combinational). A variable-latency agent asserts "
         "readdatavalid on each cycle that carries valid readdata."},
        {"id": "FR-MM-05", "text": "Avalon-MM supports pipelined reads: a host "
         "may issue further reads before earlier reads return; readdatavalid "
         "decouples the address phase from the data phase."},
        {"id": "FR-MM-06", "text": "Burst transfers move burstcount words as a "
         "single burst; beginbursttransfer marks the first cycle. A read burst "
         "returns burstcount words each qualified by readdatavalid; a write "
         "burst drives writedata on each cycle that waitrequest is low."},
        {"id": "FR-ST-07", "text": "An Avalon-ST interface is a source (data "
         "producer) or a sink (data consumer); the connection is "
         "unidirectional and point-to-point. The source drives data and valid; "
         "the sink drives ready (backpressure)."},
        {"id": "FR-ST-08", "text": "The Avalon-ST handshake is ready/valid with "
         "a readyLatency property: with readyLatency=0 a transfer occurs when "
         "both ready and valid are asserted; with readyLatency=N the source may "
         "drive valid data if ready was asserted N cycles earlier."},
        {"id": "FR-ST-09", "text": "A packetized Avalon-ST stream frames data "
         "with startofpacket (first beat) and endofpacket (last beat); empty "
         "indicates unused symbol lanes in the final beat. channel identifies "
         "the virtual stream; error carries per-beat error bits."},
        {"id": "FR-SUP-10", "text": "Supporting interfaces: Conduit (arbitrary "
         "exported signals), Interrupt (irq sender/receiver), Clock (source/"
         "sink), Reset (source/sink), and Memory-Mapped Tristate Conduit "
         "(Avalon-TC) for off-chip shared-pin devices."},
        {"id": "FR-IC-11", "text": "Platform Designer (Qsys) generates the "
         "interconnect: address decoding, round-robin arbitration, data-path "
         "multiplexing, width adaptation, burst adaptation, and clock-domain "
         "crossing."},
    ]
    d["error_response_conditions"] = [
        "Avalon-MM response = SLAVEERROR — the agent could not complete the "
        "transfer.",
        "Avalon-MM response = DECODEERROR — no agent decoded at the address.",
        "waitrequest held indefinitely — the host stalls until the agent is "
        "ready (no time-out in the base protocol).",
        "Avalon-ST error bits asserted with a data beat — the source reports a "
        "data error on that beat.",
        "Backpressure (ready deasserted) — the sink stalls the source; data is "
        "not transferred until ready is asserted (per readyLatency).",
    ]
    d["compliance_requirements"] = [
        "Avalon-MM host/agent role with the declared signal subset (address, "
        "read/write, readdata/writedata, byteenable, waitrequest, "
        "readdatavalid, burstcount as needed).",
        "Correct waitrequest wait-state behavior (host holds command stable "
        "until waitrequest deasserts).",
        "Correct read-latency behavior: fixed readLatency or "
        "readdatavalid-qualified variable latency.",
        "Avalon-ST source/sink with data/valid/ready and the declared "
        "readyLatency; startofpacket/endofpacket/empty for packetized streams.",
        "Declared transfer properties (addressUnits, readLatency, setupTime, "
        "holdTime, waitrequestAllowance, readyLatency, symbolsPerBeat).",
        "Connectivity through Platform-Designer-generated interconnect.",
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
        "Address-mapped read/write transfer protocol (Avalon-MM) plus a "
        "unidirectional streaming protocol (Avalon-ST). An Avalon-MM host "
        "drives address + read/write + writedata + byteenable; the agent "
        "returns readdata, stalling with waitrequest and qualifying pipelined "
        "reads with readdatavalid. An Avalon-ST source drives data + valid; the "
        "sink drives ready (readyLatency backpressure); packets are framed by "
        "startofpacket / endofpacket.")
    d["channels"] = [
        {"name": "Avalon-MM (address-mapped)",
         "direction": "bidirectional host<->agent",
         "description": "Host drives address/read/write/writedata/byteenable; "
         "agent returns readdata; waitrequest wait-states; readdatavalid "
         "pipelined reads; burstcount bursts."},
        {"name": "Avalon-ST (streaming)",
         "direction": "unidirectional source->sink",
         "description": "Source drives data/valid; sink drives ready; "
         "readyLatency backpressure; startofpacket/endofpacket framing; "
         "channel/error/empty."},
        {"name": "Interrupt (irq)", "direction": "sender->receiver",
         "description": "Interrupt sender asserts irq to a receiver (typically "
         "the processor)."},
        {"name": "Conduit", "direction": "exported",
         "description": "Arbitrary application signals exported to the top "
         "level / device pins."},
    ]
    d["avalon_mm_signals"] = {
        "address": "host->agent; byte/word address selecting an agent "
                   "location",
        "read": "host->agent; request a read transfer",
        "write": "host->agent; request a write transfer",
        "writedata": "host->agent; write data",
        "readdata": "agent->host; read data",
        "byteenable": "host->agent; one bit per byte lane",
        "waitrequest": "agent->host; stall the host (wait-state insertion)",
        "readdatavalid": "agent->host; pipelined readdata valid this cycle",
        "burstcount": "host->agent; number of transfers in a burst",
        "chipselect": "host->agent; selects the agent",
        "beginbursttransfer": "host->agent; first cycle of a burst",
        "response": "agent->host; OKAY/RESERVED/SLAVEERROR/DECODEERROR",
    }
    d["avalon_st_signals"] = {
        "data": "source->sink; payload symbols",
        "valid": "source->sink; data valid this cycle",
        "ready": "sink->source; sink can accept (backpressure)",
        "channel": "source->sink; channel / virtual-stream id",
        "error": "source->sink; per-beat error bits",
        "startofpacket": "source->sink; first beat of a packet",
        "endofpacket": "source->sink; last beat of a packet",
        "empty": "source->sink; unused symbols in the final beat",
    }
    d["transfer_types"] = [
        {"name": "Slave read/write with waitrequest",
         "description": "Agent asserts waitrequest to insert wait-states; the "
         "host holds command stable until waitrequest deasserts, then the "
         "transfer completes."},
        {"name": "Fixed read latency (pipelined)",
         "description": "Read accepted when waitrequest is low; readdata valid "
         "exactly readLatency cycles later (no per-transfer readdatavalid)."},
        {"name": "Variable read latency (pipelined, readdatavalid)",
         "description": "Agent returns each readdata word with readdatavalid "
         "asserted; latency may vary; multiple reads may be in flight."},
        {"name": "Burst transfer",
         "description": "burstcount transfers as one burst; read burst returns "
         "burstcount words each qualified by readdatavalid; write burst drives "
         "writedata while waitrequest is low; beginbursttransfer marks the "
         "first cycle."},
    ]
    d["addressing"] = {
        "note": "Avalon-MM is address-mapped: a host drives an address and "
                "Platform Designer interconnect decodes it to the correct "
                "agent's address range. Avalon-ST is addressless (a "
                "point-to-point stream).",
        "address_units": "word addressing or byte (symbol) addressing per the "
                         "interface's declared addressUnits",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = False
    d["packet_oriented"] = True
    d["bit_stuffing"] = False
    d["arbitration_based"] = True
    d["arbitration_note"] = (
        "Platform Designer generates round-robin (fairness-based) arbitration "
        "when multiple Avalon-MM hosts share an agent; arbitration shares are "
        "configurable.")
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
        "Avalon-MM agents are themselves address-mapped register/memory "
        "targets: the host reads and writes agent locations via address + "
        "read/write + readdata/writedata + byteenable. The Avalon specification "
        "defines the *interface* (signal roles and transfer timing), not a "
        "fixed register map; each agent IP core defines its own register map "
        "within its Avalon-MM address space. The interface-level parameters "
        "below are the Avalon transfer properties an interface declares.")
    d["register_access"] = {
        "transport": "Avalon-MM address-based read/write (host -> agent)",
        "purpose": "Read/write agent registers and memory; byteenable selects "
                   "byte lanes.",
        "addressing": "word or byte (symbol) addressing per addressUnits",
    }
    d["interface_parameter_groups"] = [
        {"group": "Avalon-MM transfer properties", "fields": [
            "addressUnits (word vs symbol/byte)",
            "readLatency (fixed read latency)",
            "readWaitTime / writeWaitTime",
            "setupTime", "holdTime",
            "waitrequestAllowance",
            "maximumPendingReadTransactions (pipeline depth)",
            "burstcount width / burst alignment",
            "byteenable width (data width / symbol width)"]},
        {"group": "Avalon-ST data properties", "fields": [
            "symbolsPerBeat", "dataBitsPerSymbol",
            "readyLatency", "channel width / maxChannel",
            "error width",
            "firstSymbolInHighOrderBits (symbol ordering)",
            "packetized (startofpacket/endofpacket present)"]},
        {"group": "Interrupt properties", "fields": [
            "interrupt type (individual-requests / receiver-prioritized)",
            "irq width / assigned interrupt number"]},
    ]
    d["avalon_mm_signal_roles"] = list(_MM_SIGNALS)
    d["avalon_st_signal_roles"] = list(_ST_SIGNALS)
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
        "Avalon is a synchronous-logic on-chip interconnect contract, not an "
        "electrical/analog interface. All Avalon-MM and Avalon-ST signals are "
        "single-ended synchronous-logic signals timed to an Avalon Clock "
        "interface; there is no line code, no differential signaling, and no "
        "physical-layer electrical specification in the Avalon Interface "
        "Specifications. Off-chip electrical behavior is the concern of the "
        "FPGA IO standard / device pins (and, for shared-pin off-chip flash/"
        "SRAM, the Tristate Conduit), not of the Avalon interface contract.")
    d["modulation"] = "n/a (synchronous-logic interface; no modulation)"
    d["clocking"] = (
        "Each Avalon interface is associated with an Avalon Clock interface; "
        "transfers are synchronous to that clock. Platform Designer inserts "
        "clock-domain-crossing logic when a host and an agent are in different "
        "clock domains.")
    d["signal_levels"] = (
        "Single-ended synchronous-logic levels (FPGA core logic). The Tristate "
        "Conduit interface additionally drives tristate bidirectional signals "
        "for off-chip shared-pin devices.")
    d["encoding_role_in_analog"] = (
        "Avalon defines no line code. Avalon-MM byte selection is by "
        "byteenable; Avalon-ST framing/backpressure is by valid/ready and "
        "startofpacket/endofpacket; integrity is the responsibility of the "
        "connected IP, not of an Avalon physical layer.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / transfer FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_avalon_mm"] = [
        {"name": "IDLE", "description": "No transfer; read and write "
         "deasserted; waitrequest may be high or low."},
        {"name": "CMD", "description": "Host drives address + read/write + "
         "(writedata/byteenable). The transfer is accepted on a cycle where "
         "waitrequest is low."},
        {"name": "WAIT", "description": "Agent asserts waitrequest; the host "
         "holds address/read/write/writedata/byteenable stable (wait-state "
         "insertion)."},
        {"name": "READ_DATA", "description": "For fixed latency, readdata is "
         "valid readLatency cycles after acceptance; for variable latency, "
         "each readdata word is qualified by readdatavalid."},
        {"name": "BURST", "description": "burstcount transfers move as one "
         "burst; beginbursttransfer marks the first cycle; read-burst words "
         "are returned with readdatavalid."},
    ]
    d["fsm_states_avalon_st"] = [
        {"name": "ST_IDLE", "description": "Source valid deasserted and/or sink "
         "ready deasserted; no beat transferred."},
        {"name": "ST_XFER", "description": "Both valid and ready honored per "
         "readyLatency; a data beat (symbols) is transferred."},
        {"name": "ST_SOP", "description": "startofpacket asserted on the first "
         "beat of a packet."},
        {"name": "ST_EOP", "description": "endofpacket asserted on the last "
         "beat; empty marks unused symbols in the final beat."},
        {"name": "ST_BACKPRESSURE", "description": "Sink deasserts ready; the "
         "source must not transfer (and, per readyLatency, must hold off "
         "valid)."},
    ]
    d["fsm_hints"] = {
        "trigger": "Avalon-MM: a transfer begins when the host asserts read or "
        "write with a valid address; it completes when waitrequest is low (and "
        "for reads, when readdata is returned per latency model).",
        "rule": "The host must hold address/control/writedata stable for the "
        "duration of waitrequest; readdata is qualified by readLatency or "
        "readdatavalid.",
        "abort": "There is no protocol-level abort; a transfer simply stalls "
        "while waitrequest is asserted (or ready is deasserted on Avalon-ST).",
    }
    d["anti_deadlock_rule"] = (
        "Avalon-MM: an agent must eventually deassert waitrequest so a host "
        "transfer can complete; Platform Designer's round-robin arbiter "
        "guarantees fairness so no host is starved. Avalon-ST: a sink must "
        "eventually assert ready so the source can make progress; readyLatency "
        "bounds the source's commitment.")
    d["exit_from_reset_or_poweron"] = (
        "On reset, hosts deassert read/write (Avalon-MM) and valid "
        "(Avalon-ST); sinks may hold ready low until ready to accept. After "
        "reset, transfers proceed normally subject to waitrequest / ready "
        "backpressure.")
    d["default_ready_state_recommendation"] = {
        "mm_idle": "read and write deasserted; address/writedata don't-care.",
        "mm_active": "Assert read or write with a valid address; hold until "
        "waitrequest is low.",
        "st_idle": "Source valid deasserted; sink ready reflects acceptance "
        "capacity.",
    }
    d["configurations"] = [
        {"name": "Single host / single agent", "description": "One Avalon-MM "
         "host accessing one agent through interconnect."},
        {"name": "Multi-host shared agent", "description": "Several hosts "
         "share an agent; round-robin arbitration is generated."},
        {"name": "Streaming pipeline", "description": "Avalon-ST source -> "
         "sink chain with adapters inserted as needed."},
    ]
    d["timing_dependency_rule"] = (
        "All Avalon transfers are synchronous to the interface's Avalon Clock. "
        "Avalon-MM read data timing is governed by readLatency (fixed) or "
        "readdatavalid (variable); command acceptance is governed by "
        "waitrequest. Avalon-ST beat timing is governed by valid/ready and the "
        "readyLatency property. Cross-clock-domain connections use generated "
        "clock-crossing bridges.")
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
        {"name": "Avalon-MM response", "purpose": "OKAY/SLAVEERROR/DECODEERROR "
         "response codes report transfer success/failure to the host."},
        {"name": "debugaccess signal", "purpose": "Marks an Avalon-MM transfer "
         "as a debug access (e.g. from a debugger), allowing agents to permit "
         "otherwise-restricted accesses."},
        {"name": "waitrequest / readdatavalid timing", "purpose": "Observable "
         "wait-state and pipelined-read behavior for bring-up and protocol "
         "checking."},
        {"name": "Avalon-ST error bits", "purpose": "Per-beat error qualifier "
         "reports data errors on a stream."},
        {"name": "System Console / Avalon-MM master probes", "purpose": "Intel "
         "tools (System Console, JTAG-to-Avalon-MM master) issue Avalon-MM "
         "transfers for in-system debug."},
    ]
    d["error_detection_mechanisms"] = [
        "Avalon-MM response codes (SLAVEERROR, DECODEERROR) flag failed / "
        "unmapped transfers.",
        "Avalon-ST error bits flag per-beat data errors.",
        "byteenable mismatch / illegal access is reported by the agent via "
        "response.",
        "Protocol checkers (Platform Designer / simulation) verify "
        "waitrequest, readdatavalid, and ready/valid timing rules.",
    ]
    d["test_modes"] = [
        {"name": "Avalon-MM master debug", "purpose": "JTAG-to-Avalon-MM "
         "master / System Console drives read/write transfers for in-system "
         "register access."},
        {"name": "Protocol assertion checking", "purpose": "Simulation-time "
         "checks of Avalon-MM/Avalon-ST handshake legality."},
        {"name": "SignalTap probing", "purpose": "Capture Avalon signals "
         "on-chip for debug."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Interrupt (irq)", "trigger": "An interrupt sender asserts "
         "irq to the receiver (processor)."},
        {"event": "Transfer error", "trigger": "Avalon-MM response = "
         "SLAVEERROR / DECODEERROR."},
        {"event": "Stream error", "trigger": "Avalon-ST error bits asserted "
         "with a beat."},
        {"event": "Backpressure", "trigger": "Sink deasserts ready / agent "
         "asserts waitrequest."},
    ]
    d["notes"] = (
        "Avalon's protocol-level test surface is the response/error qualifiers, "
        "the debugaccess signal, the irq interrupt mechanism, and the "
        "observability of the handshake signals. Intel tools (System Console, "
        "JTAG-to-Avalon-MM master, SignalTap) provide in-system Avalon access; "
        "chip-level scan/BIST remain device/SoC concerns.")
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
        "AVALON_SPEC": "Avalon Interface Specifications (MNL-AVABUSREF)",
        "INTERFACE_FAMILY": "Avalon-MM / Avalon-ST / Conduit / Interrupt / "
                            "Clock / Reset / Tristate Conduit",
        "SIGNALING": "single-ended synchronous logic",
        "LINE_ENCODING": "none",
        "EMBEDDED_CLOCK": False,
        "FORWARDED_CLOCK": False,
        "PARALLEL_SYNCHRONOUS": True,
        "MM_HOST_AGENT": True,
        "ST_SOURCE_SINK": True,
        "WAITREQUEST": True,
        "READDATAVALID": True,
        "BYTEENABLE": True,
        "BURSTCOUNT": True,
        "READY_VALID_HANDSHAKE": True,
        "STARTOFPACKET_ENDOFPACKET": True,
    })
    d["avalon_mm_signal_constants"] = {
        s: True for s in _MM_SIGNALS
    }
    d["avalon_st_signal_constants"] = {
        s: True for s in _ST_SIGNALS
    }
    d["transfer_property_constants"] = {
        "address_units": "word | symbol(byte)",
        "read_latency_fixed_supported": True,
        "read_latency_variable_readdatavalid_supported": True,
        "pipelined_reads": True,
        "burst_supported": True,
        "ready_latency_supported": True,
        "setup_time_supported": True,
        "hold_time_supported": True,
        "waitrequest_allowance_supported": True,
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": False,
        "is_parallel_synchronous": True,
        "embedded_clock": False,
        "forwarded_clock": False,
        "mm_host_agent": True,
        "st_source_sink": True,
        "waitrequest": True,
        "readdatavalid": True,
        "byteenable": True,
        "burstcount": True,
        "ready_valid": True,
        "startofpacket_endofpacket": True,
        "arbitration": "round-robin (Platform-Designer-generated)",
        "address_units": "word | symbol(byte)",
        "read_latency_modes": ["fixed (readLatency)",
                               "variable (readdatavalid)"],
    })
    d["default_signal_values_when_idle"] = {
        "mm_idle": "read=0, write=0; agent waitrequest as needed.",
        "st_idle": "source valid=0; sink ready reflects capacity.",
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
    d["mm_read_waveform"] = {
        "fixed_latency": "Host drives address+read; transfer accepted when "
                         "waitrequest is low; readdata valid readLatency cycles "
                         "later.",
        "variable_latency": "Host drives address+read; agent returns each "
                            "readdata word with readdatavalid asserted; "
                            "multiple reads may be in flight.",
        "wait_states": "Agent holds waitrequest high to stall; host holds "
                       "address/read stable until waitrequest is low.",
    }
    d["mm_write_waveform"] = {
        "single": "Host drives address+write+writedata+byteenable; accepted "
                  "when waitrequest is low.",
        "burst": "Host drives burstcount+beginbursttransfer then writedata on "
                 "each cycle waitrequest is low until burstcount words sent.",
    }
    d["st_waveform"] = {
        "handshake": "A beat transfers when valid and ready are honored per "
                     "readyLatency (readyLatency=0: both asserted same cycle; "
                     "readyLatency=N: valid allowed if ready was high N cycles "
                     "earlier).",
        "packet": "startofpacket on the first beat, endofpacket on the last "
                  "beat, empty marks unused symbols on the final beat.",
        "backpressure": "Sink deasserts ready to stall the source.",
    }
    d["clocking_note"] = (
        "All Avalon transfers are synchronous to the interface's Avalon Clock; "
        "there is no forwarded or embedded clock and no line code. Cross-domain "
        "connections use Platform-Designer clock-crossing bridges.")
    d["general_timing_rule"] = (
        "Avalon-MM command acceptance is gated by waitrequest; read-data "
        "timing is governed by readLatency (fixed) or readdatavalid (variable). "
        "Avalon-ST beat timing is governed by valid/ready and readyLatency. All "
        "signals are sampled on the interface clock edge.")
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
        "Standard FPGA-SoC interface contract: a component advertises Avalon "
        "interfaces (Avalon-MM host/agent, Avalon-ST source/sink, and/or "
        "Conduit/Interrupt/Clock/Reset/Tristate-Conduit) and Platform Designer "
        "(Qsys) generates the interconnect that connects them (address decode, "
        "arbitration, data-path mux, width/burst adaptation, clock crossing).")
    d["topology_description"] = (
        "Avalon-MM hosts connect to agents through generated interconnect "
        "(many-to-many with arbitration). Avalon-ST sources connect "
        "point-to-point to sinks with optional adapters. Supporting interfaces "
        "(Conduit/Interrupt/Clock/Reset/Tristate-Conduit) attach the system to "
        "clocks, resets, interrupts, exported pins, and off-chip shared-pin "
        "devices.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "spec": "Avalon Interface Specifications (MNL-AVABUSREF)",
        "interface_types": list(_INTERFACE_TYPES),
        "mm_roles": "host (master) / agent (slave)",
        "st_roles": "source / sink",
        "mm_signals": list(_MM_SIGNALS),
        "st_signals": list(_ST_SIGNALS),
        "mm_handshake": "waitrequest + readdatavalid",
        "st_handshake": "valid/ready with readyLatency",
        "packet_framing": "startofpacket / endofpacket / empty",
        "arbitration": "round-robin, Platform-Designer-generated",
        "clock_crossing": "Platform-Designer-generated clock-domain bridges",
        "host_side_register_spec": "each Avalon-MM agent IP defines its own "
        "register map within its Avalon-MM address space; the Avalon spec "
        "defines the interface, not the registers.",
    })
    d["interface_categories"] = [
        "Avalon-MM — address-based read/write (host/agent); waitrequest + "
        "readdatavalid; byteenable; bursts.",
        "Avalon-ST — unidirectional source/sink streaming; valid/ready + "
        "readyLatency; startofpacket/endofpacket.",
        "Conduit — arbitrary signals exported to the top level / pins.",
        "Interrupt — irq sender/receiver.",
        "Clock / Reset — clock and reset sources/sinks (enable clock crossing "
        "/ reset sync).",
        "Tristate Conduit (Avalon-TC) — memory-mapped off-chip shared-pin "
        "devices (flash/SRAM).",
    ]
    d["interconnect_topologies_supported"] = [
        "Single Avalon-MM host to single agent.",
        "Multiple Avalon-MM hosts sharing agents (round-robin arbitration).",
        "Avalon-ST point-to-point source-to-sink pipelines with adapters.",
        "Mixed Avalon-MM + Avalon-ST systems with bridges.",
        "Avalon-to-AXI / Avalon-to-AHB bridges generated by Platform "
        "Designer.",
    ]
    d["default_signal_values_when_omitted"] = (
        "An Avalon interface uses only the signals it needs; omitted control "
        "signals take their inactive default (read/write/valid deasserted, "
        "byteenable all-ones, waitrequest low when ready, readdatavalid low "
        "until data is returned).")
    d["soc_dependent_items"] = [
        "Which Avalon interface types each IP advertises (MM/ST/Conduit/...).",
        "Avalon-MM address map (agent base addresses) and data widths.",
        "Read-latency model per agent (fixed readLatency vs readdatavalid).",
        "Burst support and depth (burstcount width).",
        "Avalon-ST symbolsPerBeat / dataBitsPerSymbol / readyLatency / "
        "channel / packetization.",
        "Clock and reset domains and required clock-crossing bridges.",
        "Arbitration shares for shared agents.",
        "Exported Conduit signals and pin assignments.",
    ]
    d["low_power_modes"] = {
        "note": "Avalon defines no protocol-level power states; clock gating "
                "and power management are SoC/device concerns. Clock/Reset "
                "interfaces enable a system to be clock-gated or reset "
                "per-domain.",
    }
    d["device_classes_examples"] = [
        "Nios II processor (Avalon-MM host)",
        "On-chip / external memory controller (Avalon-MM agent)",
        "Register-based peripheral (Avalon-MM agent)",
        "DSP / video / packet pipeline block (Avalon-ST source/sink)",
        "Interrupt-generating peripheral (Avalon Interrupt sender)",
        "Off-chip flash / SRAM controller (Avalon Tristate Conduit)",
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
        "partial - the Avalon Interface Specifications define interface timing "
        "and compliance behaviors (waitrequest, read latency, ready/valid, "
        "packet framing) rather than a packaged testbench; Platform Designer / "
        "BFMs and simulation protocol checkers exercise them.")
    d["derived_compliance_test_categories"] = [
        "Avalon-MM read with waitrequest wait-states: host holds command until "
        "waitrequest deasserts.",
        "Avalon-MM write with waitrequest wait-states.",
        "Avalon-MM fixed read latency (readLatency cycles to readdata).",
        "Avalon-MM variable read latency with readdatavalid; pipelined reads "
        "in flight.",
        "Avalon-MM byteenable byte-lane selection on partial-width transfers.",
        "Avalon-MM burst read/write (burstcount, beginbursttransfer, "
        "readdatavalid per word).",
        "Avalon-MM response codes (OKAY/SLAVEERROR/DECODEERROR).",
        "Avalon-ST ready/valid handshake at readyLatency 0 and N.",
        "Avalon-ST backpressure (sink deasserts ready).",
        "Avalon-ST packet framing (startofpacket/endofpacket/empty).",
        "Avalon-ST channel / error qualifiers.",
        "Interrupt: irq sender to receiver.",
        "Clock-domain crossing between host and agent in different domains.",
        "Multi-host arbitration (round-robin fairness, configurable shares).",
        "Width / burst adaptation between mismatched interfaces.",
        "Tristate Conduit access to off-chip shared-pin devices.",
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
        "Avalon is an on-chip interface specification; it defines no OTP/fuse "
        "content. Any configuration (address map, data width, read-latency "
        "model, burst/streaming properties) is set at design/elaboration time "
        "in Platform Designer, not burned into fuses. This layer is genuinely "
        "N/A for the Avalon interface contract.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["mm_read_sequence"] = [
        "1. Host drives address and asserts read (and byteenable).",
        "2. If the agent asserts waitrequest, the host holds address/read "
        "stable (wait-state insertion).",
        "3. The read is accepted on the cycle waitrequest is low.",
        "4a. Fixed latency: readdata is valid readLatency cycles later.",
        "4b. Variable latency: the agent asserts readdatavalid with each "
        "readdata word (latency may vary; reads may be pipelined).",
        "5. The host samples readdata when valid; response reports OKAY / "
        "SLAVEERROR / DECODEERROR.",
    ]
    d["mm_write_sequence"] = [
        "1. Host drives address, writedata, byteenable, and asserts write.",
        "2. If waitrequest is high, the host holds the command stable.",
        "3. The write completes on the cycle waitrequest is low.",
        "4. (Optional) writeresponsevalid + response report the write result.",
    ]
    d["mm_burst_sequence"] = [
        "1. Host drives burstcount and beginbursttransfer on the first cycle.",
        "2. Read burst: the agent returns burstcount words, each qualified by "
        "readdatavalid.",
        "3. Write burst: the host drives writedata on each cycle waitrequest "
        "is low until burstcount words are sent.",
    ]
    d["st_transfer_sequence"] = [
        "1. Sink asserts ready when it can accept (backpressure when "
        "deasserted).",
        "2. Source asserts valid with data (per readyLatency timing).",
        "3. A beat transfers on the honored ready/valid cycle.",
        "4. Packetized: startofpacket on the first beat, endofpacket on the "
        "last; empty marks unused symbols in the final beat.",
    ]
    d["interrupt_sequence"] = [
        "1. An interrupt sender asserts irq.",
        "2. The receiver (processor) services the interrupt and clears the "
        "source (via an Avalon-MM register access).",
    ]
    d["reset_sequence"] = [
        "1. Reset asserted: hosts deassert read/write and valid; agents/sinks "
        "return to a safe idle.",
        "2. Reset deasserted: transfers resume subject to waitrequest / ready "
        "backpressure.",
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
        {"name": "Handshake timing closure", "purpose": "Verify Avalon-MM "
         "waitrequest/readdatavalid and Avalon-ST valid/ready meet setup/hold "
         "at the interface clock (an STA / timing-closure concern, not a "
         "lab-bench measurement)."},
        {"name": "Clock-crossing correctness", "purpose": "Validate "
         "Platform-Designer clock-crossing bridges between domains."},
    ]
    d["notes"] = (
        "Avalon is a synchronous-logic on-chip interface; there is no "
        "analog or lab calibration in the specification. Timing is closed by FPGA "
        "synthesis/STA, not by bench calibration. This layer is essentially "
        "N/A for the Avalon contract.")
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
    f["spec_version"] = "Intel/Altera Avalon Interface Specifications (MNL-AVABUSREF)"
    f["previous_versions"] = [
        "Avalon interface family as maintained across Altera/Intel Quartus and "
        "Platform Designer (Qsys) releases; the host/agent terminology "
        "supersedes the earlier master/slave terminology.",
    ]
    f["key_changes"] = [
        {"version": "Avalon Interface Specifications",
         "summary": "Defines Avalon-MM, Avalon-ST, Conduit, Interrupt, Clock, "
         "Reset, and Tristate Conduit interfaces, their signal roles, transfer "
         "properties, and timing; consumed by Platform Designer / Qsys / Nios "
         "II / Quartus."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "Intel oneAPI / Quartus Prime Pro evolutions",
         "summary": "Avalon remains the native Intel FPGA interconnect; "
         "Platform Designer continues to generate Avalon interconnect and "
         "Avalon<->AXI/AHB bridges."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "host_agent_vs_master_slave",
         "rule": "host/agent are the modern names for master/slave.",
         "trap": "Assuming host/agent are new roles rather than renamed "
                 "master/slave."},
        {"trap_name": "waitrequest_must_be_honored",
         "rule": "A host must hold address/control/writedata stable while "
                 "waitrequest is asserted.",
         "trap": "Changing the command during a wait-state corrupts the "
                 "transfer."},
        {"trap_name": "fixed_vs_variable_read_latency",
         "rule": "Fixed-latency agents use readLatency; variable-latency "
                 "agents use readdatavalid.",
         "trap": "Sampling readdata at the wrong cycle when the latency model "
                 "is misconfigured."},
        {"trap_name": "readyLatency_semantics",
         "rule": "Avalon-ST readyLatency sets how many cycles after ready the "
                 "source may drive valid data.",
         "trap": "Treating readyLatency=0 and readyLatency=N identically "
                 "drops or duplicates beats."},
        {"trap_name": "avalon_is_not_axi",
         "rule": "Avalon uses waitrequest/readdatavalid (MM) and "
                 "valid/ready+sop/eop (ST), not the AXI xVALID/xREADY "
                 "5-channel set or Wishbone CYC/STB/ACK.",
         "trap": "Wiring AXI/AHB/Wishbone handshakes directly to Avalon "
                 "without a Platform-Designer bridge."},
    ]
    f["version_naming_history_note"] = (
        "The Avalon Interface Specifications (Intel document MNL-AVABUSREF) "
        "define the Intel/Altera FPGA-SoC interface family. Facts here are "
        "grounded in the public Intel Avalon Interface Specifications: the "
        "seven interface types, Avalon-MM host/agent signals (address, "
        "read/write, readdata/writedata, byteenable, waitrequest, "
        "readdatavalid, burstcount), Avalon-ST source/sink signals (data, "
        "valid, ready, startofpacket, endofpacket, empty, channel, error), the "
        "transfer properties (addressUnits, readLatency, setupTime, holdTime, "
        "waitrequestAllowance, readyLatency), and the Platform Designer (Qsys) "
        "interconnect generation.")
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
    f["interface_type_table"] = {
        "header_columns": ["Interface", "Role pair", "Purpose"],
        "rows": [
            ["Avalon-MM", "host / agent", "address-based read/write"],
            ["Avalon-ST", "source / sink", "unidirectional streaming"],
            ["Conduit", "exporter", "arbitrary exported signals"],
            ["Interrupt", "sender / receiver", "irq events"],
            ["Clock", "source / sink", "clock distribution"],
            ["Reset", "source / sink", "reset distribution"],
            ["Tristate Conduit (Avalon-TC)", "host / agent",
             "off-chip shared-pin memory-mapped"],
        ],
    }
    f["avalon_mm_signal_table"] = {
        "header_columns": ["Signal", "Direction", "Role"],
        "rows": [
            ["address", "host->agent", "select agent location"],
            ["read", "host->agent", "request read"],
            ["write", "host->agent", "request write"],
            ["writedata", "host->agent", "write data"],
            ["readdata", "agent->host", "read data"],
            ["byteenable", "host->agent", "byte-lane select"],
            ["waitrequest", "agent->host", "wait-state insertion"],
            ["readdatavalid", "agent->host", "pipelined read valid"],
            ["burstcount", "host->agent", "burst length"],
            ["response", "agent->host", "OKAY/SLAVEERROR/DECODEERROR"],
        ],
    }
    f["avalon_st_signal_table"] = {
        "header_columns": ["Signal", "Direction", "Role"],
        "rows": [
            ["data", "source->sink", "payload symbols"],
            ["valid", "source->sink", "data valid"],
            ["ready", "sink->source", "backpressure"],
            ["channel", "source->sink", "virtual stream id"],
            ["error", "source->sink", "per-beat error"],
            ["startofpacket", "source->sink", "first beat of packet"],
            ["endofpacket", "source->sink", "last beat of packet"],
            ["empty", "source->sink", "unused symbols in final beat"],
        ],
    }
    f["transfer_property_table"] = {
        "header_columns": ["Property", "Applies to", "Meaning"],
        "rows": [
            ["addressUnits", "Avalon-MM", "word vs symbol(byte) addressing"],
            ["readLatency", "Avalon-MM", "fixed read latency in cycles"],
            ["setupTime", "Avalon-MM", "address/control setup cycles"],
            ["holdTime", "Avalon-MM", "address/data hold cycles"],
            ["waitrequestAllowance", "Avalon-MM",
             "extra transfers after waitrequest"],
            ["readyLatency", "Avalon-ST", "cycles from ready to valid data"],
            ["symbolsPerBeat", "Avalon-ST", "symbols per valid cycle"],
        ],
    }
    f["encoding_note"] = (
        "Avalon defines no line code; it is a synchronous-logic interface. "
        "Avalon-MM byte selection is by byteenable; Avalon-ST framing is by "
        "valid/ready and startofpacket/endofpacket. The 'tables' here are the "
        "interface-type, signal-role, and transfer-property tables from the "
        "Avalon Interface Specifications.")
    f["tables"] = [
        "Interface-type table (7 Avalon interfaces)",
        "Avalon-MM signal table",
        "Avalon-ST signal table",
        "Transfer-property table (addressUnits, readLatency, readyLatency, "
        "...)",
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
        "Avalon-MM: host/agent roles with address + read/write + "
        "readdata/writedata (+ byteenable as needed).",
        "Avalon-MM: correct waitrequest wait-state behavior (host holds "
        "command stable until waitrequest deasserts).",
        "Avalon-MM: a defined read-latency model — fixed readLatency OR "
        "readdatavalid-qualified variable latency.",
        "Avalon-ST: source/sink with data/valid/ready and a declared "
        "readyLatency.",
        "Avalon-ST: startofpacket/endofpacket (+ empty) for packetized "
        "streams.",
        "Declared transfer properties (addressUnits, readLatency, setupTime, "
        "holdTime, waitrequestAllowance, readyLatency, symbolsPerBeat).",
        "Connectivity through Platform-Designer-generated interconnect.",
    ]
    f["must_not_have_properties"] = [
        "AXI-style xVALID/xREADY 5-channel handshakes presented as native "
        "Avalon (Avalon uses waitrequest/readdatavalid).",
        "Wishbone CYC/STB/ACK or AHB HTRANS/HREADY presented as native Avalon.",
        "A line code or differential physical layer (Avalon is "
        "synchronous-logic).",
        "Changing an Avalon-MM command while waitrequest is asserted.",
        "Driving Avalon-ST valid in violation of the declared readyLatency.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "waitrequest violation", "trigger": "Host changes "
         "address/control/writedata during a wait-state."},
        {"mode": "read-latency mismatch", "trigger": "readdata sampled at the "
         "wrong cycle vs readLatency / readdatavalid."},
        {"mode": "readyLatency violation", "trigger": "Source drives valid "
         "inconsistently with the declared readyLatency."},
        {"mode": "packet framing error", "trigger": "Missing/extra "
         "startofpacket or endofpacket, or wrong empty."},
        {"mode": "decode/slave error", "trigger": "Transfer to an unmapped "
         "address (DECODEERROR) or to a failing agent (SLAVEERROR)."},
    ]
    f["min_link_constraint"] = (
        "A compliant connection requires at least a matched role pair (host+"
        "agent for Avalon-MM, or source+sink for Avalon-ST) with compatible or "
        "adapter-bridgeable transfer properties, connected through "
        "Platform-Designer interconnect.")
    f["reset_behavior_compliance"] = (
        "On reset, hosts deassert read/write and sources deassert valid; after "
        "reset, transfers proceed subject to waitrequest/ready backpressure.")
    f["avalon_distinguishers"] = (
        "Avalon is identified by: the Avalon-MM waitrequest (wait-state) + "
        "readdatavalid (pipelined-read) signature with host/agent roles, "
        "and/or the Avalon-ST source/sink data/valid/ready + "
        "startofpacket/endofpacket streaming signature, plus the Platform "
        "Designer (Qsys) / Nios II / Quartus vocabulary. This is distinct from "
        "AXI (xVALID/xREADY 5-channel), AHB (HADDR/HTRANS/HREADY), and "
        "Wishbone (CYC/STB/ACK).")
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
        {"name": "Avalon-MM", "direction": "bidirectional host<->agent",
         "purpose": "Address-based read/write transfers.",
         "active_levels": "address/read/write/writedata/byteenable host->agent; "
         "readdata/waitrequest/readdatavalid agent->host",
         "idle_level": "read=0, write=0"},
        {"name": "Avalon-ST", "direction": "unidirectional source->sink",
         "purpose": "Streaming data with backpressure and optional packets.",
         "active_levels": "data/valid/startofpacket/endofpacket/empty/channel/"
         "error source->sink; ready sink->source",
         "idle_level": "valid=0 / ready reflects capacity"},
        {"name": "Interrupt (irq)", "direction": "sender->receiver",
         "purpose": "Event signaling to the processor.",
         "active_levels": "irq asserted", "idle_level": "irq deasserted"},
        {"name": "Conduit", "direction": "exported",
         "purpose": "Arbitrary signals to the top level / pins.",
         "active_levels": "user-defined", "idle_level": "user-defined"},
        {"name": "Clock / Reset", "direction": "source->sink",
         "purpose": "Clock and reset distribution.",
         "active_levels": "clk toggling / reset asserted",
         "idle_level": "n/a"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "MM command accepted",
         "meaning": "read or write asserted on a cycle waitrequest is low."},
        {"name": "MM wait-state",
         "meaning": "waitrequest asserted; host holds command stable."},
        {"name": "MM pipelined read data",
         "meaning": "readdatavalid asserted with a readdata word."},
        {"name": "ST beat",
         "meaning": "valid/ready honored per readyLatency; a data beat moves."},
        {"name": "ST backpressure", "meaning": "ready deasserted; source "
         "stalls."},
    ]
    f["packet_types_summary"] = [
        {"class": "Avalon-MM transfer",
         "members": ["read", "write", "burst read", "burst write"],
         "count": 4},
        {"class": "Avalon-ST stream",
         "members": ["non-packetized stream", "packetized stream "
                     "(sop/eop/empty)"], "count": 2},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "interface_type_count": 7,
        "avalon_mm_signal_count": len(_MM_SIGNALS),
        "avalon_st_signal_count": len(_ST_SIGNALS),
        "mm_role_pair": "host / agent",
        "st_role_pair": "source / sink",
    })
    f["global_signals"] = [
        {"name": "Clock", "purpose": "Avalon Clock interface times all "
         "transfers."},
        {"name": "Reset", "purpose": "Avalon Reset interface resets the "
         "interfaces."},
        {"name": "Interrupt (irq)", "purpose": "System-level interrupt "
         "signaling."},
    ]
    f["dependency_graph"] = {
        "common_rule": "All Avalon transfers are synchronous to the "
        "interface's Avalon Clock and respect its Avalon Reset. Avalon-MM "
        "command acceptance depends on waitrequest; read data depends on "
        "readLatency (fixed) or readdatavalid (variable). Avalon-ST beats "
        "depend on valid/ready per readyLatency. Cross-domain connections "
        "depend on Platform-Designer clock-crossing bridges.",
        "data_dependency": "Avalon-MM readdata requires an accepted read "
        "(waitrequest low) and the latency model; Avalon-ST data transfer "
        "requires both valid and ready honored per readyLatency. Multi-host "
        "agents depend on the generated round-robin arbiter.",
    }
    f["handshake_pairs"] = [
        {"name": "waitrequest", "from": "agent", "to": "host",
         "rule": "Wait-state insertion: host holds command stable until "
         "waitrequest deasserts."},
        {"name": "readdatavalid", "from": "agent", "to": "host",
         "rule": "Qualifies pipelined readdata; decouples address and data "
         "phases."},
        {"name": "valid/ready", "from": "source", "to": "sink",
         "rule": "Avalon-ST transfer honored per readyLatency; ready provides "
         "backpressure."},
        {"name": "startofpacket/endofpacket", "from": "source", "to": "sink",
         "rule": "Packet framing; empty marks unused symbols in the final "
         "beat."},
        {"name": "irq", "from": "interrupt sender", "to": "receiver",
         "rule": "Event signaling to the processor."},
    ]
    f["ordering_rules"] = {
        "mm_pipelined_reads": "Pipelined Avalon-MM read responses return in "
        "request order; readdatavalid marks each response.",
        "st_beat_order": "Avalon-ST beats are delivered in order; "
        "startofpacket/endofpacket bracket each packet.",
        "arbitration": "Round-robin arbitration orders contending hosts on a "
        "shared agent fairly.",
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
        "Platform-Designer-generated FPGA-SoC interconnect. Avalon-MM is a "
        "many-to-many host/agent fabric (address decode + arbitration + "
        "data-path mux); Avalon-ST is point-to-point source/sink with "
        "adapters. Conduit/Interrupt/Clock/Reset/Tristate-Conduit attach the "
        "system to pins, interrupts, clocks, resets, and off-chip shared-pin "
        "devices.")
    f["supported_topologies"] = [
        {"name": "Single host / single agent", "description": "One Avalon-MM "
         "host to one agent."},
        {"name": "Multi-host shared agent", "description": "Multiple hosts "
         "share agents with generated round-robin arbitration."},
        {"name": "Streaming pipeline", "description": "Avalon-ST source -> "
         "sink chain with auto-inserted adapters."},
        {"name": "Mixed MM + ST system", "description": "Memory-mapped and "
         "streaming subsystems in one Platform Designer system."},
        {"name": "Bridged to AXI/AHB", "description": "Avalon<->AXI/AHB "
         "bridges generated by Platform Designer."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Avalon-MM host (master)", "description": "Initiates "
         "read/write transfers by driving address."},
        {"role": "Avalon-MM agent (slave)", "description": "Responds to "
         "transfers; asserts waitrequest / readdatavalid."},
        {"role": "Avalon-ST source", "description": "Produces stream data; "
         "drives data/valid."},
        {"role": "Avalon-ST sink", "description": "Consumes stream data; drives "
         "ready (backpressure)."},
        {"role": "Interrupt sender / receiver", "description": "Generates / "
         "collects irq."},
    ]
    f["interconnect_role"] = (
        "Platform Designer generates the interconnect that connects Avalon "
        "interfaces: for Avalon-MM it provides address decoding, round-robin "
        "arbitration, data-path multiplexing, width adaptation (byteenable), "
        "burst adaptation, and clock crossing; for Avalon-ST it provides a "
        "point-to-point connection with data-format/channel/error/timing "
        "adapters.")
    f["ordering_guarantees"] = {
        "mm_ordering": "Pipelined Avalon-MM read responses return in order; "
        "writes complete in order to a given agent.",
        "st_ordering": "Avalon-ST beats and packets are delivered in order on "
        "a stream.",
        "arbitration_fairness": "Round-robin arbitration ensures no host is "
        "starved on a shared agent.",
    }
    f["memory_vs_peripheral_regions"] = (
        "Avalon-MM agents occupy address ranges in the system address map; the "
        "host's address is decoded by the interconnect to select the agent. "
        "Avalon-ST is addressless point-to-point streaming.")
    dc = _ensure_dict(f, "device_classification")
    dc["mm_host"] = "Processor / DMA / bridge initiating Avalon-MM transfers."
    dc["mm_agent"] = "Memory / register peripheral responding to Avalon-MM."
    dc["st_source"] = "Data producer (e.g. ADC front-end, packet generator)."
    dc["st_sink"] = "Data consumer (e.g. DMA, packet processor)."
    dc["interrupt_sender"] = "Peripheral generating irq."
    dc["tristate_conduit"] = "Off-chip flash / SRAM controller (shared pins)."
    f["default_signal_values_evidence_tables"] = [
        "Avalon Interface Specifications (MNL-AVABUSREF) — interface types and "
        "signal roles",
        "Avalon-MM transfer timing (waitrequest, fixed/variable read latency, "
        "burst) figures",
        "Avalon-ST transfer timing (ready/valid, readyLatency, packet) "
        "figures",
        "Platform Designer interconnect generation (arbitration, adaptation, "
        "clock crossing)",
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
        "signaling": "single-ended synchronous logic (FPGA core)",
        "line_encoding": "none",
        "clocking": "synchronous to the interface's Avalon Clock; "
                    "clock-domain crossing via generated bridges",
        "mm_handshake": "waitrequest + readdatavalid",
        "st_handshake": "valid/ready with readyLatency",
        "address_units": "word | symbol(byte)",
        "read_latency_models": ["fixed (readLatency)", "variable "
                                "(readdatavalid)"],
        "burst_supported": True,
        "byteenable_width": "data width / dataBitsPerSymbol",
        "arbitration": "round-robin (Platform-Designer-generated)",
    }
    f["notes"] = (
        "Avalon is an on-chip interface specification; it imposes interface "
        "timing/handshake constraints (waitrequest, read latency, ready/valid, "
        "readyLatency), not PDK-specific SDC/floorplan rules. Physical "
        "constraints (FPGA IO standards for exported Conduit / Tristate Conduit "
        "pins, timing closure at the interface clock) are device/Quartus "
        "concerns.")
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
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "JTAG-to-Avalon-MM master", "purpose": "Intel debug fabric "
         "issues Avalon-MM read/write transfers from JTAG for in-system "
         "register/memory access."},
        {"name": "System Console", "purpose": "Scriptable Avalon-MM access for "
         "bring-up and debug."},
        {"name": "debugaccess signal", "purpose": "Marks an Avalon-MM transfer "
         "as a debug access so agents can permit restricted accesses."},
        {"name": "SignalTap", "purpose": "On-chip capture of Avalon signals "
         "(handshake, data) for debug."},
        {"name": "Response / error qualifiers", "purpose": "Avalon-MM response "
         "and Avalon-ST error report transfer/data faults."},
    ]
    f["internal_diagnostics_observability"] = [
        "Avalon-MM waitrequest / readdatavalid handshake observability.",
        "Avalon-MM response codes (OKAY/SLAVEERROR/DECODEERROR).",
        "Avalon-ST valid/ready / sop/eop / error observability.",
        "irq interrupt status.",
        "Arbitration / clock-crossing behavior in simulation.",
    ]
    f["out_of_band_test_facilities"] = [
        "Quartus / Platform Designer simulation BFMs and protocol checkers.",
        "Vendor JTAG debug (System Console, JTAG-to-Avalon-MM master).",
    ]
    f["notes"] = (
        "Avalon's protocol-level DFT surface is the JTAG-to-Avalon-MM master / "
        "System Console in-system access path, the debugaccess signal, "
        "SignalTap capture, and the response/error qualifiers. Chip-level "
        "scan/BIST remain device/SoC concerns.")
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
        "The Avalon Interface Specifications define no protocol-level power "
        "states. Power management (clock gating, power domains) is an SoC / "
        "device concern; the Avalon Clock and Reset interfaces let a system be "
        "clock-gated or reset per domain, and Platform Designer generates "
        "clock-crossing bridges, but power intent itself is out of scope for "
        "the Avalon interface contract.")
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
        "Avalon-MM read/write with waitrequest wait-states.",
        "Avalon-MM fixed read latency (readLatency).",
        "Avalon-MM variable read latency (readdatavalid) + pipelined reads.",
        "Avalon-MM byteenable byte-lane selection.",
        "Avalon-MM burst read/write (burstcount, beginbursttransfer).",
        "Avalon-MM response codes (OKAY/SLAVEERROR/DECODEERROR).",
        "Avalon-ST ready/valid at readyLatency 0 and N.",
        "Avalon-ST backpressure.",
        "Avalon-ST packet framing (startofpacket/endofpacket/empty).",
        "Avalon-ST channel / error.",
        "Interrupt irq sender/receiver.",
        "Clock-domain crossing between host and agent.",
        "Multi-host round-robin arbitration / fairness.",
        "Width / burst adaptation between mismatched interfaces.",
        "Tristate Conduit off-chip shared-pin access.",
    ]
    f["notes"] = (
        "The Avalon Interface Specifications do not ship a packaged testbench, "
        "but imply a verification plan covering Avalon-MM transfer timing "
        "(waitrequest, fixed/variable read latency, bursts, byteenable, "
        "response), Avalon-ST transfer timing (ready/valid, readyLatency, "
        "packets, channel/error), interrupts, arbitration, clock crossing, and "
        "adaptation. Platform Designer BFMs and simulation protocol checkers "
        "provide the conformance checks.")
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
        "Avalon-MM response codes (SLAVEERROR/DECODEERROR) flag failed / "
        "unmapped transfers rather than silently corrupting.",
        "Avalon-ST error bits flag corrupt data beats.",
        "byteenable ensures only intended byte lanes are written.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Access control / isolation is an interconnect/SoC concern: Platform "
        "Designer can restrict which hosts reach which agents, and the "
        "debugaccess signal lets agents gate debug-only accesses.",
        "Carried-application security (encryption, authentication) is the "
        "responsibility of the connected IP, not of the Avalon interface "
        "contract.",
    ]
    f["notes"] = (
        "Avalon is an on-chip interface specification with no built-in "
        "cryptography. Its protections are anti-corruption qualifiers "
        "(response/error codes, byteenable) and the access-control/isolation "
        "and debugaccess gating provided by the interconnect and connected IP. "
        "Confidentiality/integrity/authentication are out of scope for the "
        "Avalon contract.")
    _write(p, d)
