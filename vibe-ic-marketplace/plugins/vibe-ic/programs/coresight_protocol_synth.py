"""ARM CoreSight on-chip debug & trace architecture synth helper (protocol #64).

ic_class-gated overlay for the CoreSight STRUCTURAL signature: an on-chip
debug-and-trace ARCHITECTURE that sits ON TOP of a JTAG or SWD transport. The
defining structural blocks are a Debug Access Port (DAP = Debug Port [SW-DP /
JTAG-DP] + memory-mapping Access Ports [AHB-AP / APB-AP / AXI-AP] reaching the
debug register space over a Debug APB), a trace TRANSPORT built on the AMBA
Trace Bus (ATB) with a FUNNEL (combine streams) and a REPLICATOR (fan-out),
trace SOURCES (ETM/ETMv4, PTM, ITM, STM), trace SINKS (TPIU off-chip, ETB/ETF
on-chip RAM, ETR routing to memory over AXI), a cross-trigger fabric (a CTI per
component plus a Cross Trigger Matrix CTM), and component discovery via ROM
Tables + the CIDR/PIDR/DEVARCH/DEVTYPE identification registers, with debug
authentication (DBGEN/NIDEN/SPIDEN/SPNIDEN). Applies ARM CoreSight
architecture content (public ARM ARM / public TRM level) to L1-L23.

Doctrine — GENERAL not keyword: detection uses the canonical CoreSight
STRUCTURAL signature (ATB trace bus + funnel + replicator + a trace sink
[TPIU/ETB/ETF/ETR] + a trace source [ETM/ITM/STM]), read from the L-doc /
input_doc CONTENT blob ONLY. It NEVER reads the input-document filename or the
benchmark folder name. A bare protocol NAME token (the runner injects protocol
names into foreign docs) is NEVER sufficient on its own — every True path
requires the CoreSight-specific trace-architecture structure.

Sibling disambiguation — CoreSight vs JTAG and SWD. JTAG (IEEE 1149.1: a TAP
state machine driven by TCK/TMS/TDI/TDO, BYPASS/IDCODE/EXTEST, boundary scan)
and SWD (Serial Wire Debug / ADIv5 two-wire SWDIO/SWCLK Debug Port with DP
CTRL/STAT + SELECT registers) are the wire-level TRANSPORT that CoreSight runs
on top of. CRITICALLY, the ADIv5 (SWD) specification text is itself rich in
CoreSight-adjacent vocabulary — it names the DAP, MEM-AP/AHB-AP, ROM Tables and
even "CoreSight" — so a detector keyed on DAP / AP / ROM-table / the bare word
"CoreSight" WOULD false-fire on the SWD doc. The discriminator that is present
in a CoreSight trace-architecture document and ABSENT from both the pure-JTAG
TAP doc and the ADIv5/SWD Debug-Port doc is the TRACE TRANSPORT + TRACE
SOURCE/SINK architecture: the ATB (AMBA Trace Bus) as a trace interconnect,
the trace FUNNEL, the trace REPLICATOR, the TPIU/ETB/ETF/ETR trace sinks, and
the ITM/STM/ETM trace sources. The detector therefore REQUIRES that
trace-architecture signature and DEFERS on a pure JTAG-TAP-only doc or a pure
SWD/ADIv5 Debug-Port-only doc that has no ATB/funnel/replicator/trace-sink/
trace-source architecture.

Because the runner's SWD synth (is_swd) fires on a CoreSight doc (the doc names
SWD/ADIv5/SWDIO/SWCLK and DP registers as the transport), this module runs
AFTER the SWD synth and FORCE-OVERWRITES (direct assignment, NOT setdefault)
every key the SWD/JTAG sibling populated with the CoreSight-canonical value, so
the CoreSight architecture wins.

SPEC-GROUNDING CAVEAT: ARM's full CoreSight Architecture Specification and the
per-component TRMs are ARM PROPRIETARY. This module is grounded in the
publicly-documented behavior (ARM Architecture Reference Manual, public
CoreSight TRMs, ARM public application notes): component roles, register names,
and architectural relationships. It invents NO exact numeric timing/electrical/
area values; quantities that are implementation-defined (STM stimulus-port
count, ETB/ETF depth, TPIU trace-data-pin count, CTM channel count, register
bit layouts) are described as implementation-defined rather than fabricated.

Public entry: ``apply_coresight_synth(generated_docs_dir, is_coresight,
coresight_ic_name)``. Module-level ``is_coresight(blob)`` is the content-only
detector (the universal guard test auto-covers it).
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

# Canonical CoreSight architecture facts (public ARM ARM / TRM level).
_TRACE_SOURCES = ["ETM (ETMv4)", "PTM", "ITM", "STM"]
_TRACE_SINKS = ["TPIU", "ETB", "ETF", "ETR"]
_TRACE_LINKS = ["ATB funnel", "ATB replicator"]
_ACCESS_PORTS = ["AHB-AP", "APB-AP", "AXI-AP", "JTAG-AP"]
_DEBUG_PORTS = ["SW-DP", "JTAG-DP", "SWJ-DP"]
_AUTH_SIGNALS = ["DBGEN", "NIDEN", "SPIDEN", "SPNIDEN"]
_ID_REGISTERS = ["CIDR0-CIDR3", "PIDR0-PIDR7", "DEVARCH", "DEVTYPE"]


def is_coresight(blob: str) -> bool:
    """Content-only ARM CoreSight detector with a JTAG / SWD sibling MUTEX.

    Fire on the CoreSight STRUCTURAL signature: the on-chip TRACE
    ARCHITECTURE — an AMBA Trace Bus (ATB) trace transport with a trace FUNNEL
    and a trace REPLICATOR, at least one trace SINK (TPIU/ETB/ETF/ETR), and at
    least one trace SOURCE (ETM/ITM/STM) — together with the DAP + Access-Port
    memory-mapped debug bus and ROM-table/component-ID discovery.

    DEFER (return False) on a pure JTAG-TAP-only doc (TAP state machine /
    boundary scan, no trace architecture) or a pure SWD/ADIv5 Debug-Port-only
    doc (serial-wire DP + MEM-AP + ROM-table but NO ATB/funnel/replicator/
    trace-sink/trace-source). The ADIv5 (SWD) spec text DOES name DAP / MEM-AP /
    ROM table / "CoreSight", so the discriminator is deliberately the
    trace-transport + trace-source/sink structure, which the ADIv5 doc lacks.

    Reads ONLY the spec text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- CoreSight trace-architecture structural tokens (word-boundary). ---
    # ATB used as a TRACE bus (not a stray AHB/AXI mention).
    atb = ("amba trace bus" in low) or (" atb " in f" {low} ") \
        or ("atb)" in low) or ("(atb" in low)
    funnel = "funnel" in low
    replicator = "replicator" in low
    # Trace sinks — match as standalone tokens / parenthetical expansions.
    tpiu = "tpiu" in low or "trace port interface unit" in low
    etb = "etb" in low or "embedded trace buffer" in low
    etf = "etf" in low or "embedded trace fifo" in low
    etr = "etr" in low or "embedded trace router" in low
    trace_sink_count = sum([tpiu, etb, etf, etr])
    # Trace sources.
    etm = "etm" in low or "embedded trace macrocell" in low
    itm = "itm" in low or "instrumentation trace" in low
    stm = ("stm" in low or "system trace macrocell" in low
           or "system trace protocol" in low)
    ptm = "ptm" in low or "program trace macrocell" in low
    trace_source_count = sum([etm, itm, stm, ptm])
    # Cross-trigger fabric.
    cti = " cti " in f" {low} " or "cross trigger interface" in low
    ctm = " ctm " in f" {low} " or "cross trigger matrix" in low
    cross_trigger = cti or ctm or "cross trigger" in low
    # DAP + Access Ports + ROM-table discovery (shared with ADIv5, used as
    # supporting context, NOT as the sole discriminator).
    dap = " dap " in f" {low} " or "debug access port" in low
    access_port = ("access port" in low or "mem-ap" in low
                   or "ahb-ap" in low or "apb-ap" in low or "axi-ap" in low)
    rom_table = "rom table" in low
    debug_apb = "debug apb" in low

    # Bare name token (NEVER sufficient on its own — see doctrine).
    name_token = "coresight" in low

    # --- The CoreSight trace-architecture signature. ---
    # ATB-as-trace-bus + funnel + replicator is the trace TRANSPORT that is
    # absent from a pure SWD/ADIv5 or pure JTAG-TAP doc.
    trace_transport = atb and funnel and replicator
    trace_arch = (
        trace_transport
        and trace_sink_count >= 1
        and trace_source_count >= 1
    )

    # Supporting debug-bus / discovery context (helps confirm a full CoreSight
    # system, but the trace_arch above is the load-bearing discriminator).
    debug_bus = dap and access_port
    discovery = rom_table or any(
        r.lower() in low for r in ("devarch", "devtype", "cidr", "pidr"))

    # --- Sibling MUTEX: pure JTAG-TAP-only doc. ---
    # A boundary-scan / TAP-state-machine doc with NO trace architecture and NO
    # DAP/Access-Port memory-mapped debug bus is JTAG, not CoreSight.
    jtag_tap = ("tap" in low or "boundary scan" in low or "boundary-scan" in low
                or "1149.1" in low)
    jtag_primary = (
        jtag_tap
        and not trace_transport
        and trace_sink_count == 0
        and not (funnel or replicator)
        and not debug_bus
    )
    if jtag_primary:
        return False

    # --- Sibling MUTEX: pure SWD / ADIv5 Debug-Port-only doc. ---
    # The ADIv5 doc names DAP/MEM-AP/ROM-table/CoreSight but has NO ATB
    # trace bus + funnel + replicator + trace sink/source architecture. If the
    # trace transport/architecture is absent, defer regardless of how many
    # DAP/AP/ROM-table/CoreSight mentions appear.
    swd_dp = ("swd" in low or "serial wire" in low or "swdio" in low
              or "adiv5" in low or "adiv6" in low or "debug port" in low)
    if not trace_transport or trace_sink_count == 0 or trace_source_count == 0:
        # No trace architecture at all → cannot be a CoreSight trace doc, even
        # if it is SWD/JTAG/DAP-rich. Defer.
        if swd_dp or jtag_tap or debug_bus or name_token:
            return False

    # --- Fire only on the full CoreSight trace-architecture signature. ---
    return bool(
        trace_arch
        and (debug_bus or cross_trigger or discovery or name_token)
    )


def apply_coresight_synth(generated_docs_dir: Path, is_coresight_flag: bool,
                          coresight_ic_name: Optional[str]) -> None:
    """Apply ARM CoreSight architecture synth when the signature matched.

    Runs AFTER the runner's SWD/JTAG sibling synth, so it FORCE-OVERWRITES
    (direct assignment) every L1..L23 key the sibling populated with the
    CoreSight-canonical value.
    """
    if not is_coresight_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if coresight_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = coresight_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = coresight_ic_name
                d["ic_name"] = coresight_ic_name
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
# L1 — FORCE-OVERWRITE the SWD/ADIv5 datasheet header with the CoreSight
# debug-and-trace architecture datasheet.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "ARM CoreSight On-Chip Debug and Trace Architecture")
    d["version"] = "CoreSight architecture (public ARM ARM / TRM level)"
    d["manufacturer"] = "Arm Limited"
    d["copyright"] = "ARM CoreSight is an Arm Limited architecture (proprietary)"
    d["abstract"] = (
        "ARM CoreSight is the on-chip debug and trace ARCHITECTURE that ties "
        "together the debug access path, the trace sources, the trace "
        "transport, the trace sinks, and the cross-trigger fabric of a "
        "System-on-Chip. CoreSight is NOT itself a wire-level transport: it "
        "sits ON TOP of a JTAG (IEEE 1149.1 TAP) or SWD (Serial Wire Debug, "
        "ADIv5) transport. An external debugger reaches the on-chip debug bus "
        "through a Debug Access Port (DAP) — a Debug Port (SW-DP / JTAG-DP / "
        "SWJ-DP) plus memory-mapping Access Ports (AHB-AP / APB-AP / AXI-AP) — "
        "and reads the CoreSight debug registers, which are memory-mapped over "
        "a Debug APB. Trace is generated by trace sources (ETM/ETMv4, PTM, "
        "ITM, STM), carried on the AMBA Trace Bus (ATB) through funnels (which "
        "combine streams) and replicators (which fan streams out), and "
        "captured by trace sinks (TPIU off-chip, ETB/ETF on-chip RAM, ETR into "
        "system memory over AXI). A Cross Trigger Interface (CTI) per component "
        "plus a Cross Trigger Matrix (CTM) distribute debug events such as "
        "synchronous halt and restart across cores. The system is "
        "self-describing: a debugger walks a hierarchy of ROM Tables and reads "
        "each component's identification registers (CIDR/PIDR/DEVARCH/DEVTYPE) "
        "to enumerate it. Invasive and non-invasive debug, Secure and "
        "Non-secure, are gated by the DBGEN/NIDEN/SPIDEN/SPNIDEN authentication "
        "signals. NOTE: ARM's full CoreSight Architecture Specification and "
        "the per-component TRMs are ARM proprietary; this datasheet describes "
        "documented behavior at the public ARM ARM / TRM level and fixes no "
        "implementation-defined numeric values.")
    d["keywords"] = [
        "CoreSight", "on-chip debug", "trace", "DAP", "Debug Access Port",
        "Debug Port", "SW-DP", "JTAG-DP", "Access Port", "AHB-AP", "APB-AP",
        "AXI-AP", "Debug APB", "ETM", "ETMv4", "PTM", "ITM", "STM",
        "ATB", "AMBA Trace Bus", "funnel", "replicator", "TPIU", "ETB", "ETF",
        "ETR", "CTI", "CTM", "Cross Trigger", "ROM Table", "CIDR", "PIDR",
        "DEVARCH", "DEVTYPE", "DBGEN", "NIDEN", "SPIDEN", "SPNIDEN", "ADIv5",
        "JTAG", "SWD",
    ]
    d["external_pins"] = [
        "Debug transport pins (transport-dependent): JTAG TAP (TCK, TMS, TDI, "
        "TDO, optional TRSTn) for a JTAG-DP, or Serial Wire (SWDIO, SWCLK) for "
        "an SW-DP; an SWJ-DP allows the same pins to switch between the two.",
        "Trace Port (off-chip, via the TPIU): trace clock TRACECLK + trace "
        "data lines TRACEDATA[n] (pin count implementation-defined, e.g. "
        "1/2/4/8/16), OR the single-pin Serial Wire Output (SWO) on a Serial "
        "Wire system.",
        "Debug authentication inputs: DBGEN, NIDEN, SPIDEN, SPNIDEN (gate "
        "invasive / non-invasive, Secure / Non-secure debug).",
        "Power-domain handshake (internal/SoC): CDBGPWRUPREQ/CDBGPWRUPACK and "
        "CSYSPWRUPREQ/CSYSPWRUPACK between the DP and the power controller.",
    ]
    d["key_features"] = [
        "On-chip debug-and-trace architecture layered over a JTAG or SWD "
        "transport — CoreSight is the architecture, not the wire transport.",
        "Debug Access Port (DAP): a Debug Port (SW-DP / JTAG-DP / SWJ-DP) plus "
        "memory-mapping Access Ports (AHB-AP / APB-AP / AXI-AP / JTAG-AP) for "
        "memory-mapped access to the debug bus and system memory.",
        "CoreSight debug registers are memory-mapped over a Debug APB; each "
        "component occupies a 4 KB register block.",
        "Trace sources: ETM/ETMv4 (instruction + optional data trace), PTM "
        "(program-flow trace), ITM (instrumentation trace), STM (MIPI System "
        "Trace).",
        "Trace transport on the AMBA Trace Bus (ATB): funnels combine multiple "
        "ATB streams, replicators fan one stream out to multiple sinks; each "
        "source carries an ATB trace ID for later demultiplexing.",
        "Trace sinks: TPIU (off-chip trace port / SWO), ETB (on-chip buffer), "
        "ETF (on-chip FIFO), ETR (route trace into system DRAM over AXI).",
        "Cross-trigger fabric: a CTI per component plus a Cross Trigger Matrix "
        "(CTM) distribute debug events (e.g. synchronous halt/restart across "
        "all cores).",
        "Self-describing discovery: a ROM Table hierarchy plus per-component "
        "identification registers (CIDR0-3, PIDR0-7, DEVARCH, DEVTYPE).",
        "Debug authentication: DBGEN / NIDEN / SPIDEN / SPNIDEN gate invasive "
        "and non-invasive debug for Non-secure and Secure state; AUTHSTATUS "
        "reflects the current permissions.",
        "Component management: CLAIMSET/CLAIMCLR claim tags and a "
        "LAR/LSR software lock coordinate multiple debug agents.",
    ]
    d["topology_summary"] = (
        "Star-of-buses on-chip: an external debugger drives the DAP Debug Port "
        "over JTAG/SWD; the DAP's Access Ports master the on-chip debug bus "
        "(Debug APB) and system buses (AHB/AXI). Trace flows the other way: "
        "many trace sources feed the ATB, funnels merge the ATB streams, "
        "replicators fan them to one or more sinks (TPIU off-chip / ETB-ETF "
        "on-chip / ETR to DRAM). A CTM channel fabric links the per-component "
        "CTIs for cross-triggering.")
    d["use_cases"] = [
        "Multi-core SoC software debug (halt/step/breakpoint) over a single "
        "JTAG/SWD connection",
        "Real-time instruction/data trace of one or more cores for "
        "performance analysis and post-mortem debug",
        "Software instrumentation trace (printf-style) via ITM/STM stimulus "
        "ports",
        "Synchronous multi-core halt/restart via CTI/CTM cross-triggering",
        "Off-chip high-bandwidth trace via the TPIU trace port, or buffered "
        "on-chip trace (ETB/ETF) and very large trace captured into DRAM via "
        "ETR over AXI",
        "Security-gated debug: enabling/disabling invasive and Secure debug "
        "via DBGEN/NIDEN/SPIDEN/SPNIDEN across the device lifecycle",
    ]
    d["overview"] = (
        "ARM CoreSight is Arm's on-chip debug and trace architecture. It "
        "defines how an external debugger gains memory-mapped access to a "
        "SoC's debug infrastructure and how trace is generated, transported, "
        "and captured. The debug access path is the Debug Access Port (DAP): a "
        "Debug Port (SW-DP for Serial Wire, JTAG-DP for JTAG, or a combined "
        "SWJ-DP) terminates the external transport, and Access Ports (AHB-AP, "
        "APB-AP, AXI-AP, JTAG-AP) bridge onto on-chip buses so the debugger "
        "can read and write the debug register space (memory-mapped over a "
        "Debug APB, 4 KB per component) and system memory. Trace is produced "
        "by trace sources — ETM/ETMv4 and PTM for program-flow (and optional "
        "data) trace, ITM for instrumentation trace, and STM for system trace "
        "— each tagging its stream with an ATB trace ID. The trace travels on "
        "the AMBA Trace Bus (ATB); funnels combine several ATB streams into "
        "one and replicators fan a stream out to multiple destinations. Trace "
        "sinks terminate the stream: the TPIU drives it off-chip on a parallel "
        "trace port or the single-pin SWO; the ETB and ETF capture it in "
        "on-chip RAM; the ETR routes it into system DRAM over AXI. A Cross "
        "Trigger Interface (CTI) on each component, linked through the Cross "
        "Trigger Matrix (CTM), distributes debug events so that, for example, "
        "halting one core halts them all. The whole system is self-describing "
        "through a ROM-Table hierarchy and per-component identification "
        "registers (CIDR/PIDR/DEVARCH/DEVTYPE), and access is gated by the "
        "DBGEN/NIDEN/SPIDEN/SPNIDEN authentication signals. CoreSight is "
        "explicitly an architecture layered ON TOP of the JTAG/SWD transport, "
        "not a replacement for it. (ARM's full specification and TRMs are "
        "proprietary; this is a public-architecture-level description.)")
    d["industry_standard_basis"] = (
        "ARM CoreSight architecture (proprietary, Arm Limited). The DAP "
        "follows the ARM Debug Interface ADIv5/ADIv6. Trace sources/sinks "
        "follow the CoreSight component architecture (ETM/ETMv4, PTM, ITM, "
        "STM[MIPI STP], TPIU, ETB/ETF/ETR[CoreSight Trace Memory Controller], "
        "ATB funnel/replicator). Underlying transports are IEEE 1149.1 (JTAG) "
        "and Serial Wire Debug (SWD).")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FORCE-OVERWRITE the SWD protocol_overview + FRS with the CoreSight
# debug-and-trace architecture model.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "On-chip debug and trace ARCHITECTURE layered over a JTAG (IEEE "
        "1149.1 TAP) or SWD (Serial Wire Debug / ADIv5) transport. Comprises a "
        "Debug Access Port (DAP = Debug Port + Access Ports onto the on-chip "
        "debug bus), trace sources (ETM/PTM/ITM/STM), an ATB trace transport "
        "with funnels and replicators, trace sinks (TPIU/ETB/ETF/ETR), and a "
        "CTI/CTM cross-trigger fabric.")
    po["layered_on_transport"] = {
        "jtag": "JTAG-DP: IEEE 1149.1 TAP (TCK/TMS/TDI/TDO) reaches the DAP.",
        "swd": "SW-DP: Serial Wire (SWDIO/SWCLK), ADIv5 Debug Port.",
        "swj": "SWJ-DP: pins switchable between SWD and JTAG.",
        "note": "CoreSight is NOT the transport; it is the architecture on "
                "top of the transport.",
    }
    po["debug_access_port"] = {
        "debug_ports": list(_DEBUG_PORTS),
        "access_ports": list(_ACCESS_PORTS),
        "debug_register_transport": "Debug APB (memory-mapped, 4 KB/component)",
        "note": "The DP terminates the transport and performs the "
                "debug/system power-up handshake; the AP masters an on-chip "
                "bus for memory-mapped register/memory access.",
    }
    po["trace_sources"] = list(_TRACE_SOURCES)
    po["trace_transport"] = {
        "bus": "AMBA Trace Bus (ATB)",
        "links": list(_TRACE_LINKS),
        "trace_id": "each source carries an ATB trace ID (TRACEIDR/"
                    "TRCTRACEIDR) so the merged stream can be demultiplexed",
        "flow_control": "ATB ATVALID/ATREADY back-pressure stalls upstream "
                        "sources; AFVALID/AFREADY flush signaling",
    }
    po["trace_sinks"] = list(_TRACE_SINKS)
    po["cross_trigger"] = {
        "cti": "Cross Trigger Interface per component — maps local trigger "
               "in/out onto channels",
        "ctm": "Cross Trigger Matrix — broadcasts channel events between CTIs",
        "use": "synchronous multi-core halt/restart, ETM trigger, PMU events",
    }
    po["discovery"] = {
        "rom_table": "MEM-AP BASE points at the top-level ROM Table; the table "
                     "tree lists component offsets",
        "id_registers": list(_ID_REGISTERS),
    }
    po["authentication"] = list(_AUTH_SIGNALS)
    # Remove SWD-sibling line-protocol keys that do not describe CoreSight.
    for stale in ("duplex", "synchronous_serial", "wire_count",
                  "line_protocol", "ack_response", "turnaround",
                  "packet_format", "bit_rate"):
        po.pop(stale, None)
    d["functional_requirements"] = [
        {"id": "FR-DAP-01", "text": "An external debugger SHALL access the "
         "on-chip debug bus through a Debug Access Port (DAP): a Debug Port "
         "(SW-DP / JTAG-DP / SWJ-DP) terminating the JTAG/SWD transport plus "
         "one or more Access Ports (AHB-AP / APB-AP / AXI-AP / JTAG-AP)."},
        {"id": "FR-DP-02", "text": "The Debug Port SHALL own the DP registers "
         "(DPIDR/IDCODE, CTRL/STAT, SELECT, RDBUFF) and SHALL perform the "
         "debug and system power-up handshake (CDBGPWRUPREQ/ACK, "
         "CSYSPWRUPREQ/ACK) before accesses proceed."},
        {"id": "FR-AP-03", "text": "Each MEM-AP SHALL expose CSW, TAR, DRW, "
         "BD0-BD3, CFG, BASE, and IDR; the debugger reaches a component by "
         "programming TAR with its base address and transferring through DRW."},
        {"id": "FR-DEBUGAPB-04", "text": "CoreSight debug registers SHALL be "
         "memory-mapped (over a Debug APB), with each component occupying a "
         "4 KB register block."},
        {"id": "FR-SOURCE-05", "text": "Trace sources (ETM/ETMv4, PTM, ITM, "
         "STM) SHALL generate trace and emit it onto the ATB, each tagging its "
         "stream with an ATB trace ID."},
        {"id": "FR-ATB-06", "text": "Trace SHALL be carried on the AMBA Trace "
         "Bus (ATB); funnels SHALL combine multiple ATB input streams into one "
         "and replicators SHALL fan one ATB stream out to multiple outputs."},
        {"id": "FR-SINK-07", "text": "Trace sinks SHALL terminate the stream: "
         "the TPIU drives it off-chip (trace port / SWO); the ETB and ETF "
         "capture it in on-chip RAM; the ETR routes it into system memory over "
         "AXI."},
        {"id": "FR-XTRIG-08", "text": "A Cross Trigger Interface (CTI) per "
         "component, linked by the Cross Trigger Matrix (CTM), SHALL "
         "distribute debug events (e.g. halt/restart) across components."},
        {"id": "FR-DISCOVERY-09", "text": "The system SHALL be discoverable: "
         "the MEM-AP BASE points at a top-level ROM Table; walking the ROM "
         "Table tree and reading each component's CIDR/PIDR/DEVARCH/DEVTYPE "
         "enumerates all debug and trace components."},
        {"id": "FR-AUTH-10", "text": "Invasive and non-invasive debug, Secure "
         "and Non-secure, SHALL be gated by DBGEN/NIDEN/SPIDEN/SPNIDEN; each "
         "component's AUTHSTATUS SHALL reflect the current permissions."},
        {"id": "FR-LOCKCLAIM-11", "text": "Components SHALL provide a software "
         "lock (LAR/LSR) and claim tags (CLAIMSET/CLAIMCLR) so multiple debug "
         "agents can coordinate without clobbering each other."},
    ]
    d["error_response_conditions"] = [
        "DP CTRL/STAT sticky error flags (e.g. WDATAERR, STICKYERR, "
        "STICKYORUN) — a faulted DAP access; must be cleared before "
        "continuing.",
        "MEM-AP access fault — addressed location not accessible (power down, "
        "permission, or no slave).",
        "Power-up handshake not granted (CDBGPWRUPACK/CSYSPWRUPACK low) — debug "
        "logic not powered; accesses cannot proceed.",
        "Authentication denied (DBGEN/NIDEN/SPIDEN/SPNIDEN deasserted) — "
        "invasive or Secure debug refused; AUTHSTATUS shows it.",
        "ATB back-pressure / overflow — a sink cannot accept trace fast "
        "enough; the funnel/source stalls or trace is dropped (sink-dependent).",
        "Locked component (LSR shows locked) — register writes ignored until "
        "the lock key is written to LAR.",
    ]
    d["compliance_requirements"] = [
        "A DAP with a conformant Debug Port (ADIv5/ADIv6) and at least one "
        "Access Port reaching the debug register space.",
        "Debug registers memory-mapped (Debug APB), 4 KB per component, with "
        "standard CIDR/PIDR/DEVARCH/DEVTYPE identification registers.",
        "At least one trace source (ETM/ITM/STM) emitting onto the ATB with a "
        "trace ID, and a trace sink (TPIU/ETB/ETF/ETR) to capture it; funnel/"
        "replicator where multiple streams/sinks are present.",
        "A discoverable ROM-Table hierarchy from the MEM-AP BASE register.",
        "Debug authentication gating (DBGEN/NIDEN/SPIDEN/SPNIDEN) and "
        "AUTHSTATUS reporting.",
        "Cross-trigger (CTI/CTM) where multi-component event distribution is "
        "required.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — FORCE-OVERWRITE the SWD line-protocol with the CoreSight component /
# DAP / ATB access model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Memory-mapped debug-register access architecture plus a trace "
        "transport. The debugger reaches every CoreSight component through the "
        "DAP (Debug Port + Access Port) as memory-mapped register accesses "
        "over the Debug APB; trace flows the other way as ATB transactions "
        "from sources through funnels/replicators to sinks. CoreSight is "
        "layered over the JTAG/SWD wire transport but is itself a "
        "component/register/trace architecture, not a line protocol.")
    d["channels"] = [
        {"name": "Debug transport (JTAG TAP or Serial Wire)",
         "direction": "debugger <-> DAP Debug Port",
         "description": "JTAG (TCK/TMS/TDI/TDO) into a JTAG-DP, or Serial Wire "
         "(SWDIO/SWCLK) into an SW-DP; an SWJ-DP switches between them."},
        {"name": "DAP internal bus (DP -> AP)",
         "direction": "internal",
         "description": "DPACC/APACC accesses select an Access Port and a "
         "register bank; the AP masters the on-chip bus."},
        {"name": "Debug APB (memory-mapped debug registers)",
         "direction": "AP master -> components",
         "description": "Each CoreSight component's 4 KB register block is "
         "memory-mapped here; reached via the MEM-AP TAR/DRW."},
        {"name": "AMBA Trace Bus (ATB)",
         "direction": "trace source -> funnel/replicator -> sink",
         "description": "Carries trace (ATDATA/ATID/ATVALID/ATREADY, "
         "AFVALID/AFREADY flush) from sources to sinks."},
        {"name": "Trace Port / SWO (off-chip)",
         "direction": "TPIU -> external analyzer",
         "description": "Parallel TRACECLK + TRACEDATA[n], or single-pin SWO."},
        {"name": "Cross-trigger channels (CTM)",
         "direction": "CTI <-> CTM <-> CTI",
         "description": "Broadcast debug events (halt/restart/trigger) across "
         "components."},
    ]
    d["access_model"] = {
        "register_access": "Debugger -> DP -> AP (MEM-AP) -> TAR=component "
                           "base, DRW=data -> component register over Debug "
                           "APB.",
        "discovery": "MEM-AP BASE -> top ROM Table -> walk entries -> read "
                     "CIDR/PIDR/DEVARCH/DEVTYPE at each component base.",
        "trace_path": "source(ETM/ITM/STM) -> ATB -> funnel(combine) -> "
                      "replicator(fan-out) -> sink(TPIU/ETB/ETF/ETR).",
    }
    d["component_classes"] = [
        {"class": "Debug Access Port (DAP)", "members": ["Debug Port (SW-DP/"
         "JTAG-DP/SWJ-DP)"] + list(_ACCESS_PORTS)},
        {"class": "Trace source", "members": list(_TRACE_SOURCES)},
        {"class": "Trace link", "members": list(_TRACE_LINKS)},
        {"class": "Trace sink", "members": list(_TRACE_SINKS)},
        {"class": "Cross trigger", "members": ["CTI", "CTM"]},
        {"class": "Discovery", "members": ["ROM Table"] + list(_ID_REGISTERS)},
    ]
    d["atb_signals"] = [
        "ATDATA — trace data", "ATID — ATB trace ID (per source)",
        "ATVALID / ATREADY — handshake + back-pressure",
        "ATBYTES — valid byte count", "AFVALID / AFREADY — flush handshake",
    ]
    d["addressing"] = {
        "note": "Components are addressed by their base address in the debug "
                "register space (discovered from the ROM Table); trace streams "
                "are identified by ATB trace ID, not by address.",
        "component_block_size_bytes": 4096,
        "trace_id_per_source": True,
    }
    d["frame_format"] = {
        "register_access": "Memory-mapped read/write of a component's 4 KB "
        "block via MEM-AP TAR (address) + DRW (data) over the Debug APB.",
        "trace_framing": "Trace sources emit protocol-specific packets "
        "(ETM trace protocol, MIPI STP for STM, ITM stimulus packets) onto the "
        "ATB; the TPIU/formatter wraps the merged stream so it can be split by "
        "trace ID off-chip.",
        "note": "There is no single wire 'frame'; CoreSight is a "
        "component-register + ATB-trace architecture over the JTAG/SWD "
        "transport.",
    }
    # Remove SWD-sibling line-protocol keys.
    for stale in ("packet_format", "request_packet", "ack_response",
                  "turnaround_phase", "data_phase", "line_protocol",
                  "wire_protocol", "bit_format"):
        d.pop(stale, None)
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — FORCE-OVERWRITE the SWD DP-register map with the CoreSight DAP +
# component register model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "CoreSight register space has three tiers: (1) the DAP Debug Port "
        "registers (DPIDR, CTRL/STAT, SELECT, RDBUFF); (2) the Access Port "
        "registers (CSW, TAR, DRW, BD0-3, CFG, BASE, IDR); (3) each "
        "CoreSight component's memory-mapped 4 KB register block (over the "
        "Debug APB), which always includes the identification registers "
        "(CIDR0-3, PIDR0-7, DEVARCH, DEVTYPE) and the management registers "
        "(CLAIMSET/CLAIMCLR, LAR/LSR, AUTHSTATUS, DEVID/DEVAFF) plus its "
        "function-specific registers. Exact bit layouts are ARM proprietary / "
        "implementation-defined.")
    d["register_groups"] = [
        {"group": "Debug Port (DP) registers", "fields": [
            "DPIDR / IDCODE — Debug Port identification",
            "CTRL/STAT — power-up request/ack (CDBGPWRUPREQ/ACK, "
            "CSYSPWRUPREQ/ACK), sticky error flags",
            "SELECT — selects the active Access Port and register bank",
            "RDBUFF — read buffer"]},
        {"group": "Access Port (MEM-AP) registers", "fields": [
            "CSW — control/status word (access size, auto-increment, mode)",
            "TAR — Transfer Address Register",
            "DRW — Data Read/Write",
            "BD0-BD3 — Banked Data registers",
            "CFG — configuration",
            "BASE — debug base address (points at the first ROM Table)",
            "IDR — AP identification register"]},
        {"group": "Component identification registers (every component)",
         "fields": [
            "CIDR0-CIDR3 — Component ID (preamble + class)",
            "PIDR0-PIDR7 — Peripheral ID (part number, JEP106 designer, "
            "revision, 4KB count)",
            "DEVARCH — architecture identification (CoreSight v3+)",
            "DEVTYPE — major/sub component type (source/sink/link/...)"]},
        {"group": "Component management registers (every component)",
         "fields": [
            "CLAIMSET / CLAIMCLR — claim tags for multi-agent coordination",
            "LAR / LSR — Lock Access / Lock Status (software lock)",
            "AUTHSTATUS — current debug authentication permissions",
            "DEVID / DEVAFF — device configuration / affinity"]},
        {"group": "Trace-source registers (e.g. ETM/ITM/STM)", "fields": [
            "Trace enable / programming control",
            "TRACEIDR / TRCTRACEIDR — ATB trace ID",
            "ETM: address-range/context-ID comparators, counters, sequencer",
            "ITM: stimulus port registers; STM: stimulus ports (MIPI STP)"]},
        {"group": "Trace-link / sink registers", "fields": [
            "Funnel: input-port enable + priority control",
            "Replicator: per-output ID filter",
            "TPIU: formatter + trace-port-width control",
            "ETB/ETF/ETR (CoreSight Trace Memory Controller): RAM/FIFO/router "
            "mode, buffer pointers, ETR AXI scatter-gather base"]},
    ]
    d["component_register_block_size_bytes"] = 4096
    d["identification_registers"] = list(_ID_REGISTERS)
    d["debug_port_registers"] = ["DPIDR", "CTRL/STAT", "SELECT", "RDBUFF"]
    d["mem_ap_registers"] = ["CSW", "TAR", "DRW", "BD0-BD3", "CFG", "BASE",
                             "IDR"]
    # Remove SWD-sibling DP-only register keys if present.
    for stale in ("dp_register_map", "ap_register_map", "swd_registers"):
        d.pop(stale, None)
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — overwrite the SWD electrical/ADI spec with the CoreSight
# transport/trace-port electrical context (mostly implementation-defined).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "CoreSight is a digital debug/trace architecture; its external "
        "electrical interfaces are the debug transport (JTAG TAP TCK/TMS/TDI/"
        "TDO or Serial Wire SWDIO/SWCLK) and the off-chip Trace Port from the "
        "TPIU (parallel TRACECLK + TRACEDATA[n]) or the single-pin SWO. The "
        "TAP/SWD signaling levels follow the JTAG/SWD transport spec, and the "
        "Trace Port pin count, drive, and maximum trace clock are "
        "implementation-defined (TPIU- and SoC-specific). CoreSight itself "
        "fixes no analog/electrical numeric values; this module invents none.")
    d["clocking"] = (
        "Debug transport clock is the externally-supplied TCK (JTAG) or SWCLK "
        "(Serial Wire). Internally CoreSight components run on the SoC debug/"
        "trace clocks (e.g. a trace clock domain feeding the ATB and the "
        "TPIU's TRACECLK output); the TPIU exports a TRACECLK with the off-chip "
        "trace data. Specific frequencies are implementation-defined.")
    d["external_interfaces"] = {
        "debug_in": "JTAG TAP (TCK/TMS/TDI/TDO[/TRSTn]) OR Serial Wire "
                    "(SWDIO/SWCLK).",
        "trace_out": "TPIU Trace Port: TRACECLK + TRACEDATA[n] "
                     "(n implementation-defined, e.g. 1/2/4/8/16), OR "
                     "single-pin Serial Wire Output (SWO).",
        "auth_in": "DBGEN / NIDEN / SPIDEN / SPNIDEN.",
        "power_handshake": "CDBGPWRUPREQ/ACK, CSYSPWRUPREQ/ACK.",
    }
    d["implementation_defined_quantities"] = [
        "TPIU trace-port data-pin count and maximum TRACECLK frequency",
        "STM stimulus-port count", "ETB/ETF RAM depth",
        "ETR AXI data width and scatter-gather page size",
        "Number of CTM channels", "Register bit layouts",
    ]
    # Remove SWD-sibling SerDes/electrical keys that do not apply.
    for stale in ("transmitter_specs_canonical", "receiver_specs_canonical",
                  "line_levels", "drive_strength", "swd_electrical"):
        d.pop(stale, None)
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — overwrite the SWD line FSM with the CoreSight DAP-access /
# trace-session FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove SWD-sibling FSM keys.
    for stale in ("fsm_states_swd_line", "fsm_states_dp", "fsm_states_tap",
                  "fsm_states_serial_wire"):
        d.pop(stale, None)
    d["fsm_states_dap_powerup"] = [
        {"name": "DP_RESET", "description": "Debug Port reset / line reset; DP "
         "registers in reset state."},
        {"name": "DPIDR_READ", "description": "Debugger reads DPIDR/IDCODE to "
         "identify the DP."},
        {"name": "PWRUP_REQ", "description": "Set CDBGPWRUPREQ and "
         "CSYSPWRUPREQ in CTRL/STAT to power the debug and system domains."},
        {"name": "PWRUP_ACK", "description": "Wait for CDBGPWRUPACK and "
         "CSYSPWRUPACK; only then may AP accesses proceed."},
        {"name": "AP_SELECT", "description": "Program SELECT to choose the "
         "Access Port and register bank."},
        {"name": "DAP_READY", "description": "DAP operational; MEM-AP "
         "TAR/DRW accesses to the debug register space allowed."},
    ]
    d["fsm_states_discovery"] = [
        {"name": "READ_BASE", "description": "Read the MEM-AP BASE register to "
         "locate the top-level ROM Table."},
        {"name": "WALK_ROMTABLE", "description": "Read ROM Table entries; each "
         "present entry gives a relative offset to a component or nested ROM "
         "Table."},
        {"name": "IDENTIFY", "description": "At each component base, read "
         "CIDR0-3 / PIDR0-7 / DEVARCH / DEVTYPE to positively identify it."},
        {"name": "ENUMERATED", "description": "Full component inventory "
         "(cores, ETMs, ITM/STM, funnel, replicator, CTIs, sinks) is known."},
    ]
    d["fsm_states_trace_session"] = [
        {"name": "UNLOCK_CLAIM", "description": "Write LAR lock key (unlock) "
         "and CLAIMSET claim tags on each component to be programmed."},
        {"name": "CFG_SOURCE", "description": "Program trace sources "
         "(ETM/ITM/STM): trace enable, ATB trace ID, comparators/stimulus."},
        {"name": "CFG_LINK", "description": "Enable the relevant funnel input "
         "ports and route the replicator output(s) to the chosen sink."},
        {"name": "CFG_SINK", "description": "Configure the sink: TPIU "
         "formatter/port-width, ETB/ETF buffer mode, or ETR AXI "
         "scatter-gather buffer."},
        {"name": "CFG_XTRIG", "description": "Program the CTIs (channel "
         "in/out mappings) and the CTM for cross-triggering."},
        {"name": "CAPTURE", "description": "Trace flows on the ATB to the "
         "sink; off-chip (TPIU/SWO), on-chip (ETB/ETF), or to DRAM (ETR/AXI)."},
        {"name": "DRAIN_DECODE", "description": "Stop capture, drain the buffer "
         "over the Debug APB (or from DRAM), and decode off-line using the "
         "trace IDs and the program image."},
    ]
    d["fsm_hints"] = {
        "trigger": "A debug session begins after the DP power-up handshake "
        "(CDBGPWRUPREQ/ACK, CSYSPWRUPREQ/ACK) completes; only then can the "
        "debugger walk ROM Tables and program components.",
        "rule": "A component's registers may need the software lock cleared "
        "(write the key to LAR) before writes take effect; AUTHSTATUS / the "
        "DBGEN-class signals gate whether invasive/Secure debug is permitted.",
        "abort": "If authentication is denied or the power-up ack is not "
        "granted, debug accesses fault and the session cannot proceed.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On connection, the DP is reset, DPIDR is read, the debug and system "
        "power domains are requested and acknowledged, an Access Port is "
        "selected, then the debugger reads BASE, walks the ROM Tables, "
        "identifies components by CIDR/PIDR/DEVARCH/DEVTYPE, and programs the "
        "trace sources/links/sinks and cross-triggers before capturing trace.")
    d["cross_trigger_logic"] = (
        "Each CTI maps local trigger inputs/outputs onto channels via "
        "CTIINEN/CTIOUTEN; an event raised with CTIAPPSET/CTIAPPPULSE on a "
        "channel is broadcast by the CTM to every CTI listening on that "
        "channel, which drives its mapped trigger output (e.g. a halt on one "
        "core halts all cores; a single restart releases them together).")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug surface.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["debug_features_present"] = True
    d["debug_summary"] = (
        "CoreSight IS the debug-and-trace surface: halting-mode debug of cores "
        "via the DAP, real-time instruction/data trace via ETM/PTM, software "
        "instrumentation trace via ITM/STM, cross-core triggering via CTI/CTM, "
        "and self-describing component discovery via ROM Tables.")
    d["debug_access"] = {
        "transport": "JTAG-DP or SW-DP (SWJ-DP switchable) into the DAP.",
        "memory_access": "MEM-AP (AHB-AP/APB-AP/AXI-AP) for memory-mapped "
                         "access to debug registers and system memory.",
        "power_handshake": "CDBGPWRUPREQ/ACK, CSYSPWRUPREQ/ACK.",
    }
    d["trace_facilities"] = [
        {"name": "ETM / ETMv4 / PTM", "purpose": "Real-time instruction "
         "(and optional data) trace of a processor; reconstructs program flow."},
        {"name": "ITM", "purpose": "Software instrumentation trace (printf-"
         "style stimulus ports) and timestamps."},
        {"name": "STM", "purpose": "System-wide instrumentation trace (MIPI "
         "STP) with many stimulus ports for concurrent software masters."},
        {"name": "ATB funnel / replicator", "purpose": "Combine and fan-out "
         "trace streams between sources and sinks."},
        {"name": "TPIU / ETB / ETF / ETR", "purpose": "Capture trace off-chip "
         "(TPIU/SWO), on-chip (ETB/ETF RAM), or into DRAM over AXI (ETR)."},
        {"name": "CTI / CTM", "purpose": "Cross-trigger debug events "
         "(synchronous halt/restart, ETM trigger, PMU overflow)."},
    ]
    d["observability"] = [
        "Per-component identification (CIDR/PIDR/DEVARCH/DEVTYPE) and "
        "discovery via ROM Tables.",
        "DP CTRL/STAT status and sticky error flags.",
        "Component AUTHSTATUS (current debug permissions).",
        "Trace IDs per source for demultiplexing the merged stream.",
        "SMP-style observability is N/A — CoreSight uses MEM-AP register reads "
        "and trace, not an in-band management protocol.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L8_RTL_CONSTANTS — architecture constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    d["constants_present"] = True
    d["architecture_constants"] = {
        "component_register_block_bytes": 4096,
        "trace_sources": list(_TRACE_SOURCES),
        "trace_sinks": list(_TRACE_SINKS),
        "trace_links": list(_TRACE_LINKS),
        "access_ports": list(_ACCESS_PORTS),
        "debug_ports": list(_DEBUG_PORTS),
        "id_registers": list(_ID_REGISTERS),
        "auth_signals": list(_AUTH_SIGNALS),
        "atb_signals": ["ATDATA", "ATID", "ATVALID", "ATREADY", "ATBYTES",
                        "AFVALID", "AFREADY"],
    }
    d["implementation_defined"] = [
        "STM stimulus-port count", "ETB/ETF depth", "TPIU trace-data-pin count",
        "ETR AXI width / page size", "CTM channel count", "register bit fields",
    ]
    d["notes"] = (
        "Numeric architecture constants are limited to those that are publicly "
        "documented as fixed (e.g. the 4 KB component register block and the "
        "named register/signal sets). All sizing values (port counts, buffer "
        "depths, channel counts, bit layouts) are implementation-defined and "
        "are NOT fabricated here; ARM's exact specification is proprietary.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8_TIMING_WAVEFORM — timing (mostly implementation-defined).
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["timing_present"] = "partial"
    d["timing_summary"] = (
        "CoreSight timing is dominated by the underlying transport and trace "
        "clocks. The JTAG TCK / Serial Wire SWCLK timing follows the JTAG/SWD "
        "transport. The ATB and TPIU run in the SoC trace clock domain; the "
        "TPIU exports a TRACECLK with the off-chip trace data. The DP power-up "
        "handshake (CDBGPWRUPREQ -> CDBGPWRUPACK, CSYSPWRUPREQ -> "
        "CSYSPWRUPACK) is a request/acknowledge sequence with no fixed "
        "architectural latency. Exact frequencies, setup/hold, and trace-port "
        "timing are implementation-defined; no numeric values are invented.")
    d["sequences"] = [
        {"name": "DP power-up handshake",
         "edges": "CDBGPWRUPREQ asserted -> CDBGPWRUPACK observed; "
                  "CSYSPWRUPREQ asserted -> CSYSPWRUPACK observed (then AP "
                  "accesses allowed)."},
        {"name": "ATB transfer",
         "edges": "ATVALID asserted with ATDATA/ATID; accepted when ATREADY is "
                  "high; back-pressure when ATREADY is low."},
        {"name": "Trace-port output",
         "edges": "TPIU drives TRACEDATA[n] synchronous to TRACECLK (or the "
                  "SWO single-pin stream)."},
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
    d["integration_present"] = True
    d["integration_summary"] = (
        "A CoreSight subsystem is integrated into a SoC by: instantiating a "
        "DAP (Debug Port matching the chosen transport + Access Ports onto the "
        "Debug APB / system AHB / AXI); attaching trace sources (ETM per core, "
        "ITM/STM) to the ATB; wiring the ATB through funnel(s) and "
        "replicator(s) to the chosen sink(s) (TPIU pins, ETB/ETF RAM, or ETR "
        "AXI master into DRAM); connecting the per-component CTIs to the CTM; "
        "and providing the ROM-Table hierarchy and authentication signals.")
    d["integration_points"] = [
        {"interface": "Debug transport pins",
         "detail": "JTAG TAP or Serial Wire pins to the device boundary "
                   "(shared with the SoC's test/debug connector)."},
        {"interface": "Debug APB / system buses",
         "detail": "APB-AP onto the Debug APB for component registers; "
                   "AHB-AP/AXI-AP onto system memory."},
        {"interface": "ATB fabric",
         "detail": "Sources -> funnel -> replicator -> sinks, each link an "
                   "ATB; trace IDs assigned per source."},
        {"interface": "TPIU trace-port pins / SWO",
         "detail": "Off-chip trace; pin count implementation-defined."},
        {"interface": "ETR AXI master",
         "detail": "ETR writes trace into system DRAM over AXI."},
        {"interface": "CTM channels",
         "detail": "Connect every CTI for cross-triggering."},
        {"interface": "Authentication signals",
         "detail": "DBGEN/NIDEN/SPIDEN/SPNIDEN from the SoC security/lifecycle "
                   "controller."},
    ]
    d["dependencies"] = [
        "Underlying JTAG or SWD transport must be present and connected to a "
        "Debug Port.",
        "Debug and system power domains must respond to the DP power-up "
        "handshake.",
        "A ROM-Table hierarchy must describe the component layout for "
        "discovery.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — test cases (behavioral; no opcode-hex vectors).
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = "implicit"
    d["test_cases"] = [
        {"name": "DAP power-up", "intent": "After connect, set "
         "CDBGPWRUPREQ/CSYSPWRUPREQ and verify CDBGPWRUPACK/CSYSPWRUPACK before "
         "any AP access."},
        {"name": "ROM-Table discovery", "intent": "Read MEM-AP BASE, walk the "
         "ROM Table tree, and verify each component's CIDR/PIDR/DEVARCH/"
         "DEVTYPE identify it correctly."},
        {"name": "ETM trace enable", "intent": "Program an ETM trace ID + "
         "enable, run the core, and verify instruction trace appears at the "
         "sink with the expected trace ID."},
        {"name": "Funnel merge", "intent": "Enable two source ports on a "
         "funnel and verify both trace IDs appear interleaved at the sink."},
        {"name": "Replicator fan-out", "intent": "Route trace to both an "
         "on-chip sink (ETB) and off-chip (TPIU) and verify both capture it."},
        {"name": "Cross-trigger halt", "intent": "Configure CTI/CTM so a halt "
         "on one core halts all cores synchronously, then restart together."},
        {"name": "Authentication gating", "intent": "Deassert SPIDEN and "
         "verify Secure invasive debug is refused and AUTHSTATUS reflects it."},
        {"name": "ETR to DRAM", "intent": "Program the ETR AXI scatter-gather "
         "buffer and verify a large trace capture lands in system memory."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP content (genuine N/A).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["notes"] = (
        "CoreSight defines no OTP/fuse content of its own. In practice a SoC's "
        "security/lifecycle fuses may DRIVE the CoreSight authentication "
        "signals (DBGEN/NIDEN/SPIDEN/SPNIDEN) to permanently disable debug in "
        "production, but that fuse policy is a SoC concern outside the "
        "CoreSight architecture itself.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["sequences_present"] = True
    d["behavioral_sequences"] = [
        {"name": "Connect and power up",
         "steps": ["Debugger drives JTAG/SWD line reset to the Debug Port",
                   "Read DPIDR/IDCODE",
                   "Set CDBGPWRUPREQ + CSYSPWRUPREQ in CTRL/STAT",
                   "Wait for CDBGPWRUPACK + CSYSPWRUPACK",
                   "Program SELECT to choose an Access Port"]},
        {"name": "Discover components",
         "steps": ["Read MEM-AP BASE -> top ROM Table",
                   "Walk ROM Table entries (relative offsets + present bit)",
                   "At each base, read CIDR/PIDR/DEVARCH/DEVTYPE",
                   "Build the component inventory"]},
        {"name": "Set up a trace session",
         "steps": ["Unlock (LAR) + claim (CLAIMSET) each component",
                   "Program trace source(s): trace ID + enable + filters",
                   "Enable funnel input port(s)",
                   "Route replicator output(s) to the chosen sink",
                   "Configure the sink (TPIU/ETB/ETF/ETR)",
                   "Program CTI/CTM channel mappings"]},
        {"name": "Capture and decode",
         "steps": ["Run the target; trace flows on the ATB to the sink",
                   "Stop capture; drain ETB/ETF (Debug APB) or read DRAM (ETR)",
                   "Demultiplex by ATB trace ID",
                   "Reconstruct ETM program flow using the program image"]},
        {"name": "Synchronous multi-core halt",
         "steps": ["A breakpoint on core A raises a CTI trigger on a channel",
                   "The CTM broadcasts the channel event to all CTIs",
                   "Each CTI drives its core's halt input -> all cores halt",
                   "A single restart channel event releases them together"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration (genuine N/A).
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["calibration_present"] = False
    d["notes"] = (
        "CoreSight defines no analog lab calibration of its own. Trace-port "
        "(TPIU) electrical bring-up — eye/skew/deskew of TRACECLK vs "
        "TRACEDATA, or SWO baud — is a board/probe characterization concern "
        "handled by the trace-analyzer tooling, not a CoreSight calibration "
        "procedure. No calibration constants are defined or invented.")
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
        "ARM CoreSight architecture (commonly referenced as CoreSight "
        "v1/v2/v3 in public material); DAP per ARM Debug Interface ADIv5/ADIv6")
    f["previous_versions"] = [
        "CoreSight v1 — original component architecture (ETM/ITM, ATB "
        "funnel/replicator, TPIU/ETB, DAP over ADIv5).",
        "CoreSight v2 — refined component identification and added/extended "
        "trace and cross-trigger components.",
    ]
    f["key_changes"] = [
        {"version": "CoreSight v2", "summary": "Refined the component "
         "identification scheme and extended the trace/cross-trigger "
         "components; broadened multi-core debug support."},
        {"version": "CoreSight v3", "summary": "Added the DEVARCH register "
         "(architecture identification) and modernised component discovery; "
         "aligned with ETMv4 and the CoreSight Trace Memory Controller "
         "(ETF/ETR)."},
        {"version": "ADIv6 (DAP)", "summary": "Successor to ADIv5 for the "
         "Debug Access Port, extending the addressing of Access Ports and "
         "component register access."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Architecture_not_transport",
         "rule": "CoreSight is the debug/trace architecture; JTAG and SWD are "
                 "the wire transports it runs over.",
         "trap": "Treating CoreSight as 'a kind of JTAG/SWD' confuses the "
                 "architecture with its transport."},
        {"trap_name": "DEVARCH_only_from_v3",
         "rule": "The DEVARCH register is present from CoreSight v3; older "
                 "components are identified by CIDR/PIDR/DEVTYPE only.",
         "trap": "Assuming DEVARCH exists on every component breaks discovery "
                 "of older parts."},
        {"trap_name": "Implementation_defined_sizes",
         "rule": "STM port count, ETB/ETF depth, TPIU pin count, and CTM "
                 "channel count are implementation-defined.",
         "trap": "Hard-coding any of these to a single value is wrong."},
    ]
    f["version_naming_history_note"] = (
        "ARM CoreSight is a proprietary Arm architecture that has evolved "
        "across generations (publicly referred to as CoreSight v1/v2/v3), "
        "with the Debug Access Port following the ARM Debug Interface ADIv5 "
        "then ADIv6. Successive generations refined component identification "
        "(adding DEVARCH in v3), aligned with newer trace components (ETMv4, "
        "the CoreSight Trace Memory Controller realizing ETF/ETR), and "
        "extended cross-trigger and multi-core debug. Exact version details "
        "and register layouts are in ARM proprietary documents.")
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
    f["component_class_table"] = {
        "header_columns": ["Class", "Members", "Role"],
        "rows": [
            ["Debug Access Port", "SW-DP/JTAG-DP/SWJ-DP + AHB-AP/APB-AP/AXI-AP/"
             "JTAG-AP", "memory-mapped debug-bus access"],
            ["Trace source", "ETM/ETMv4, PTM, ITM, STM", "generate trace onto "
             "the ATB"],
            ["Trace link", "ATB funnel, ATB replicator", "combine / fan-out "
             "trace streams"],
            ["Trace sink", "TPIU, ETB, ETF, ETR", "capture trace off-chip / "
             "on-chip / to DRAM"],
            ["Cross trigger", "CTI, CTM", "distribute debug events"],
            ["Discovery", "ROM Table, CIDR/PIDR/DEVARCH/DEVTYPE", "self-"
             "description / identification"],
        ],
    }
    f["access_port_table"] = {
        "header_columns": ["AP", "Masters", "Use"],
        "rows": [
            ["AHB-AP", "AMBA AHB", "system memory / memory-mapped peripherals"],
            ["APB-AP", "AMBA APB (Debug APB)", "CoreSight debug registers"],
            ["AXI-AP", "AMBA AXI", "high-throughput system memory access"],
            ["JTAG-AP", "legacy JTAG scan chain", "access a JTAG chain behind "
             "the DAP"],
        ],
    }
    f["id_register_table"] = {
        "header_columns": ["Register", "Purpose"],
        "rows": [
            ["CIDR0-CIDR3", "Component ID (preamble + class)"],
            ["PIDR0-PIDR7", "Peripheral ID (part/designer/revision/4KB-count)"],
            ["DEVARCH", "architecture identification (CoreSight v3+)"],
            ["DEVTYPE", "major/sub component type"],
        ],
    }
    f["auth_signal_table"] = {
        "header_columns": ["Signal", "Meaning"],
        "rows": [
            ["DBGEN", "Non-secure invasive debug enable"],
            ["NIDEN", "Non-secure non-invasive (trace/PMU) debug enable"],
            ["SPIDEN", "Secure invasive debug enable"],
            ["SPNIDEN", "Secure non-invasive debug enable"],
        ],
    }
    f["atb_signal_table"] = {
        "header_columns": ["Signal", "Meaning"],
        "rows": [
            ["ATDATA", "trace data"],
            ["ATID", "ATB trace ID (per source)"],
            ["ATVALID / ATREADY", "valid / ready (back-pressure) handshake"],
            ["ATBYTES", "valid byte count"],
            ["AFVALID / AFREADY", "flush handshake"],
        ],
    }
    f["encoding_note"] = (
        "CoreSight 'encoding' is the per-component trace protocol, not a "
        "line code: ETM/PTM use the ETM trace protocol (compressed program "
        "flow), ITM emits stimulus packets, and STM uses the MIPI System Trace "
        "Protocol (STP). Streams are tagged by ATB trace ID and the "
        "TPIU/formatter wraps the merged stream so it can be split off-chip. "
        "Register bit layouts and packet formats are ARM proprietary / "
        "implementation-defined and are not reproduced here.")
    f["tables"] = [
        "Component-class table (DAP / source / link / sink / cross-trigger / "
        "discovery)",
        "Access-Port table (AHB-AP / APB-AP / AXI-AP / JTAG-AP)",
        "Identification-register table (CIDR / PIDR / DEVARCH / DEVTYPE)",
        "Authentication-signal table (DBGEN / NIDEN / SPIDEN / SPNIDEN)",
        "ATB-signal table (ATDATA / ATID / ATVALID / ATREADY / ...)",
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
        "A Debug Access Port (DAP): a Debug Port (SW-DP/JTAG-DP/SWJ-DP) plus "
        "one or more Access Ports (AHB-AP/APB-AP/AXI-AP/JTAG-AP).",
        "CoreSight debug registers memory-mapped (Debug APB), 4 KB per "
        "component, with CIDR/PIDR/DEVARCH/DEVTYPE identification registers.",
        "A trace transport on the AMBA Trace Bus (ATB) with funnel(s) and "
        "replicator(s) where multiple streams/sinks exist.",
        "At least one trace source (ETM/PTM/ITM/STM) tagging its stream with "
        "an ATB trace ID, and at least one trace sink (TPIU/ETB/ETF/ETR).",
        "Self-describing discovery via a ROM-Table hierarchy from MEM-AP BASE.",
        "Debug authentication gating (DBGEN/NIDEN/SPIDEN/SPNIDEN) with "
        "AUTHSTATUS reporting.",
        "Cross-trigger fabric (CTI per component + CTM) for multi-component "
        "event distribution.",
        "Component management registers: CLAIMSET/CLAIMCLR and LAR/LSR lock.",
    ]
    f["must_not_have_properties"] = [
        "Being ONLY a JTAG TAP / boundary-scan transport with no DAP, no "
        "Access Ports, and no trace architecture (that is plain JTAG).",
        "Being ONLY a Serial Wire / ADIv5 Debug Port line protocol with DP "
        "registers but no Access Ports onto a debug bus and no ATB/funnel/"
        "replicator/trace-source/trace-sink architecture (that is plain SWD).",
        "Defining its own wire-level transport — CoreSight always runs over "
        "JTAG or SWD.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Power-up not acked", "trigger": "CDBGPWRUPACK/CSYSPWRUPACK "
         "not asserted; AP accesses must not proceed."},
        {"mode": "Authentication denied", "trigger": "DBGEN/NIDEN/SPIDEN/"
         "SPNIDEN deasserted; invasive/Secure debug refused, AUTHSTATUS shows "
         "it."},
        {"mode": "DP sticky error", "trigger": "A faulted DAP access sets a "
         "CTRL/STAT sticky flag that must be cleared."},
        {"mode": "ATB overflow / back-pressure", "trigger": "Sink cannot "
         "accept trace; sources stall or trace is dropped."},
        {"mode": "Locked component", "trigger": "LSR shows locked; writes "
         "ignored until the LAR key is written."},
    ]
    f["coresight_distinguishers"] = (
        "CoreSight is identified by the TRACE ARCHITECTURE layered on a "
        "debug-bus access path: a DAP (Debug Port + Access Ports onto the "
        "Debug APB) AND a trace transport on the AMBA Trace Bus (ATB) with "
        "funnel(s)/replicator(s) carrying trace from sources (ETM/PTM/ITM/STM) "
        "to sinks (TPIU/ETB/ETF/ETR), PLUS ROM-Table discovery, CTI/CTM "
        "cross-triggering, and DBGEN/NIDEN/SPIDEN/SPNIDEN authentication. This "
        "is distinct from JTAG (a bare IEEE 1149.1 TAP / boundary-scan "
        "transport with no DAP and no trace architecture) and from SWD (the "
        "two-wire ADIv5 Debug Port line protocol). CRUCIALLY, the ADIv5 (SWD) "
        "specification text itself names the DAP, MEM-AP, ROM Tables and even "
        "'CoreSight', so the distinguishing structure is the ATB trace bus + "
        "funnel + replicator + trace-source/trace-sink architecture, which a "
        "pure SWD/ADIv5 or JTAG-TAP document does not contain.")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog (FORCE-OVERWRITE per task: L17 force).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "JTAG TAP (TCK/TMS/TDI/TDO[/TRSTn])",
         "direction": "debugger <-> JTAG-DP",
         "purpose": "JTAG debug transport into the DAP.",
         "active_levels": "per IEEE 1149.1", "idle_level": "Run-Test/Idle"},
        {"name": "Serial Wire (SWDIO/SWCLK)",
         "direction": "debugger <-> SW-DP",
         "purpose": "Two-wire SWD/ADIv5 debug transport into the DAP.",
         "active_levels": "per SWD", "idle_level": "line idle"},
        {"name": "AMBA Trace Bus (ATB)",
         "direction": "source -> funnel/replicator -> sink",
         "purpose": "Carries trace (ATDATA/ATID/ATVALID/ATREADY).",
         "active_levels": "AMBA", "idle_level": "ATVALID low"},
        {"name": "Trace Port (TRACECLK + TRACEDATA[n]) / SWO",
         "direction": "TPIU -> external analyzer",
         "purpose": "Off-chip trace output.",
         "active_levels": "implementation-defined", "idle_level": "idle"},
        {"name": "Cross-trigger channels (CTM)",
         "direction": "CTI <-> CTM <-> CTI",
         "purpose": "Broadcast debug events across components.",
         "active_levels": "channel events", "idle_level": "no event"},
        {"name": "Authentication (DBGEN/NIDEN/SPIDEN/SPNIDEN)",
         "direction": "security controller -> components",
         "purpose": "Gate invasive/non-invasive, Secure/Non-secure debug.",
         "active_levels": "asserted = permitted", "idle_level": "deasserted "
         "= denied"},
    ]
    f["packet_types_summary"] = [
        {"class": "Trace source", "members": list(_TRACE_SOURCES),
         "count": len(_TRACE_SOURCES)},
        {"class": "Trace sink", "members": list(_TRACE_SINKS),
         "count": len(_TRACE_SINKS)},
        {"class": "Trace link", "members": list(_TRACE_LINKS),
         "count": len(_TRACE_LINKS)},
        {"class": "Access Port", "members": list(_ACCESS_PORTS),
         "count": len(_ACCESS_PORTS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "trace_source_count": len(_TRACE_SOURCES),
        "trace_sink_count": len(_TRACE_SINKS),
        "trace_link_count": len(_TRACE_LINKS),
        "access_port_count": len(_ACCESS_PORTS),
        "debug_port_count": len(_DEBUG_PORTS),
        "auth_signal_count": len(_AUTH_SIGNALS),
        "component_register_block_bytes": 4096,
    })
    f["global_signals"] = [
        {"name": "DBGEN/NIDEN/SPIDEN/SPNIDEN", "purpose": "Debug "
         "authentication gating."},
        {"name": "CDBGPWRUPREQ/ACK, CSYSPWRUPREQ/ACK", "purpose": "Debug / "
         "system power-up handshake."},
        {"name": "ATB trace ID (per source)", "purpose": "Demultiplex the "
         "merged trace stream."},
    ]
    f["handshake_pairs"] = [
        {"name": "Power-up", "from": "DP", "to": "power controller",
         "rule": "CDBGPWRUPREQ/CSYSPWRUPREQ -> CDBGPWRUPACK/CSYSPWRUPACK."},
        {"name": "ATB", "from": "trace source/link", "to": "downstream sink",
         "rule": "ATVALID + data; accepted on ATREADY; back-pressure when "
                 "ATREADY low."},
        {"name": "Flush", "from": "sink/controller", "to": "source",
         "rule": "AFVALID -> AFREADY flushes in-flight trace."},
    ]
    f["ordering_rules"] = {
        "trace": "Funnels interleave streams preserving each source's trace "
        "ID; the decoder demultiplexes by trace ID off-chip.",
        "register_access": "Memory-mapped accesses are ordered by the MEM-AP / "
        "Debug APB.",
        "cross_trigger": "CTM broadcasts channel events to all listening CTIs.",
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
        "Two superimposed on-chip fabrics: a debug-access fabric (debugger -> "
        "DAP Debug Port -> Access Ports -> Debug APB / system buses -> "
        "component registers) and a trace fabric (sources -> ATB -> funnel "
        "(merge) -> replicator (fan-out) -> sinks), plus a cross-trigger "
        "channel fabric (CTIs linked by the CTM). Components are discovered "
        "through a ROM-Table hierarchy.")
    f["supported_topologies"] = [
        {"name": "Single-core debug+trace", "description": "One DAP, one ETM, "
         "a small ATB path to one sink (e.g. ETB or TPIU)."},
        {"name": "Multi-core SoC", "description": "Per-core ETM/CTI; funnels "
         "merge the ATB streams; replicators fan trace to multiple sinks; "
         "CTM links all CTIs for synchronous halt/restart."},
        {"name": "Trace-to-DRAM", "description": "ETR masters AXI to write a "
         "large trace buffer into system memory."},
        {"name": "ROM-Table hierarchy", "description": "Nested ROM Tables "
         "describe the component layout for discovery."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Debugger / DAP", "description": "Master of the debug-access "
         "fabric; reads/writes component registers via Access Ports."},
        {"role": "Trace source", "description": "Produces trace onto the ATB "
         "(ETM/PTM/ITM/STM)."},
        {"role": "Trace link", "description": "Funnel (merge) / replicator "
         "(fan-out) route the ATB."},
        {"role": "Trace sink", "description": "Terminates trace (TPIU off-chip "
         "/ ETB-ETF on-chip / ETR to DRAM)."},
        {"role": "Cross trigger", "description": "CTIs exchange events over "
         "the CTM channel fabric."},
    ]
    f["interconnect_role"] = (
        "CoreSight stitches a SoC's debuggable components together: the DAP "
        "gives a debugger uniform memory-mapped access to every component's "
        "registers, the ATB carries trace from many sources to one or more "
        "sinks through funnels and replicators, and the CTM lets a debug event "
        "on one component act on others (e.g. synchronous halt). The ROM-Table "
        "hierarchy makes the whole assembly self-describing.")
    f["routing_methods"] = ["ROM-table-described component addressing",
                            "ATB trace-ID routing (funnel/replicator filters)",
                            "CTM channel broadcast"]
    f["memory_vs_peripheral_regions"] = (
        "CoreSight debug registers are memory-mapped in a debug register "
        "space (Debug APB), 4 KB per component, located via ROM-Table offsets; "
        "system memory is reached through AHB-AP/AXI-AP. Trace is identified "
        "by ATB trace ID, not by a memory address.")
    f["default_signal_values_evidence_tables"] = [
        "CoreSight system block diagram (DAP / sources / ATB funnel+"
        "replicator / sinks / CTI-CTM)",
        "ROM-Table hierarchy figure",
        "ATB trace-path figure (source -> funnel -> replicator -> sink)",
        "Cross-trigger figure (CTIs linked by the CTM)",
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
    f["architecture_constraints"] = {
        "debug_transport": "JTAG (IEEE 1149.1 TAP) or SWD (Serial Wire / "
                           "ADIv5)",
        "debug_register_transport": "Debug APB, 4 KB per component",
        "access_ports": list(_ACCESS_PORTS),
        "debug_ports": list(_DEBUG_PORTS),
        "trace_bus": "AMBA Trace Bus (ATB)",
        "trace_links": list(_TRACE_LINKS),
        "trace_sources": list(_TRACE_SOURCES),
        "trace_sinks": list(_TRACE_SINKS),
        "id_registers": list(_ID_REGISTERS),
        "auth_signals": list(_AUTH_SIGNALS),
    }
    f["notes"] = (
        "CoreSight is an architecture specification: it fixes the component "
        "model (DAP/AP, ATB funnel/replicator, trace sources/sinks, CTI/CTM), "
        "the register/discovery scheme (4 KB blocks, ROM Tables, CIDR/PIDR/"
        "DEVARCH/DEVTYPE), and the authentication signals. It does NOT impose "
        "PDK-specific SDC/floorplan constraints; trace-port electrical timing, "
        "buffer sizing, and area are implementation/PDK concerns. ARM's exact "
        "register layouts and component TRMs are proprietary; no "
        "implementation-defined numeric values are fabricated here.")
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
    f["dft_present"] = "yes"
    f["in_band_test_facilities"] = [
        {"name": "DAP register access", "purpose": "Memory-mapped read/write "
         "of any component register over the Debug APB for bring-up/debug."},
        {"name": "ROM-Table discovery", "purpose": "Enumerate and verify the "
         "presence/identity of every debug/trace component (CIDR/PIDR/DEVARCH/"
         "DEVTYPE)."},
        {"name": "Trace capture (ETM/ITM/STM -> sink)", "purpose": "Observe "
         "internal program flow and software instrumentation in real time."},
        {"name": "Cross-trigger (CTI/CTM)", "purpose": "Coordinate "
         "halt/restart/triggers across components for test."},
        {"name": "TPIU/ETB/ETF/ETR sinks", "purpose": "Off-chip or on-chip "
         "trace capture for post-mortem analysis."},
    ]
    f["internal_diagnostics_observability"] = [
        "Component identification and presence (ROM Table + ID registers).",
        "DP CTRL/STAT status / sticky error flags.",
        "AUTHSTATUS (debug permission state).",
        "Per-source ATB trace IDs and trace content at the sink.",
        "Cross-trigger channel state via the CTIs.",
    ]
    f["notes"] = (
        "CoreSight IS, in effect, a chip's in-system debug/trace DFT "
        "infrastructure layered over the JTAG/SWD boundary-scan transport. The "
        "JTAG TAP itself still provides classic boundary scan / IDCODE / "
        "scan-test access; CoreSight adds memory-mapped register access, "
        "real-time trace, and cross-triggering on top. Conformance is to ARM's "
        "(proprietary) CoreSight architecture.")
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
        {"state": "Debug powered down", "name": "PowerDown",
         "description": "Debug domain not powered; the DP power-up handshake "
         "has not (yet) been granted."},
        {"state": "Debug powered up", "name": "PowerUp",
         "description": "CDBGPWRUPACK/CSYSPWRUPACK granted; debug logic powered "
         "and clocked, AP accesses allowed."},
    ]
    f["wakeup_mechanism"] = (
        "The Debug Port requests power for the debug and system domains via "
        "CDBGPWRUPREQ and CSYSPWRUPREQ in CTRL/STAT; the SoC power controller "
        "acknowledges with CDBGPWRUPACK and CSYSPWRUPACK. A debugger can hold "
        "the debug domain powered so it survives the core's own low-power "
        "states.")
    f["power_rails"] = [
        {"rail": "Debug power domain", "purpose": "CoreSight debug/trace logic "
         "(can be powered independently of the cores)."},
        {"rail": "System power domain", "purpose": "The buses/memory the DAP "
         "reaches; requested via CSYSPWRUPREQ."},
    ]
    f["coresight_power_considerations"] = (
        "CoreSight's protocol-level power intent is the DAP power-up handshake "
        "(separately power the debug vs system domains) so debug can persist "
        "across core power-down. Fine-grained power-domain partitioning, "
        "isolation, and retention are SoC implementation concerns.")
    f["notes"] = (
        "The architectural power feature is the request/acknowledge handshake "
        "that brings up (and holds up) the debug and system power domains. "
        "Detailed UPF/power-domain structure is an implementation concern; no "
        "numeric power values are defined or invented.")
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
        "DAP bring-up — DPIDR read, power-up handshake (CDBGPWRUPREQ/ACK, "
        "CSYSPWRUPREQ/ACK), AP SELECT.",
        "MEM-AP access — CSW/TAR/DRW reads/writes, auto-increment, BASE read.",
        "Discovery — ROM-Table walk; CIDR/PIDR/DEVARCH/DEVTYPE identification.",
        "Trace sources — ETM/PTM program-flow trace, ITM stimulus, STM (MIPI "
        "STP) ports; correct ATB trace IDs.",
        "Trace transport — ATB handshake/back-pressure; funnel merge "
        "(interleave + ID preservation); replicator fan-out + ID filters.",
        "Trace sinks — TPIU formatter/port output (and SWO), ETB/ETF buffer "
        "modes, ETR AXI scatter-gather to DRAM.",
        "Cross-trigger — CTI channel mapping; CTM broadcast; synchronous "
        "multi-core halt/restart.",
        "Authentication — DBGEN/NIDEN/SPIDEN/SPNIDEN gating; AUTHSTATUS.",
        "Lock/claim — LAR/LSR lock; CLAIMSET/CLAIMCLR coordination.",
    ]
    f["notes"] = (
        "CoreSight ships no single embedded testbench, but the architecture "
        "implies a verification plan spanning DAP access and power-up, "
        "component discovery, every trace source/link/sink, the cross-trigger "
        "fabric, and the authentication/lock model. ARM provides "
        "(proprietary) architecture compliance material; this plan is derived "
        "from the publicly-documented behavior.")
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
    f["security_requirements_present"] = True
    f["authentication_features"] = [
        "DBGEN — gates Non-secure invasive (halting-mode) debug.",
        "NIDEN — gates Non-secure non-invasive (trace / PMU) debug.",
        "SPIDEN — gates Secure invasive debug.",
        "SPNIDEN — gates Secure non-invasive debug.",
        "AUTHSTATUS register per component reflects the current permissions.",
    ]
    f["access_control_features"] = [
        "LAR/LSR software lock — registers cannot be modified by memory-mapped "
        "accesses until the lock key is written.",
        "CLAIMSET/CLAIMCLR claim tags — coordinate multiple debug agents.",
        "Debug authentication signals are typically driven by the SoC "
        "security/lifecycle controller (and may be fused off in production).",
    ]
    f["anti_corruption_features"] = [
        "ATB handshake / back-pressure prevents trace-buffer overrun in the "
        "fabric (sink-dependent overflow handling).",
        "DP CTRL/STAT sticky error flags surface faulted accesses.",
    ]
    f["confidentiality_features"] = []
    f["future_security_pointers"] = [
        "CoreSight's security model is authorization/gating (which debug is "
        "permitted), not cryptographic confidentiality of the debug/trace "
        "data path.",
        "A production device commonly deasserts the Secure (and possibly all) "
        "authentication signals so the debug architecture cannot be used to "
        "extract Secure assets; a development device asserts them.",
    ]
    f["notes"] = (
        "CoreSight is itself a major security-relevant surface: debug and "
        "trace can expose a system's internal state, so the architecture "
        "provides explicit authentication gating (DBGEN/NIDEN/SPIDEN/SPNIDEN), "
        "per-component AUTHSTATUS, a software lock (LAR/LSR), and claim tags. "
        "The protections are authorization/gating; the architecture does not "
        "itself encrypt the debug or trace data path. Exact security behavior "
        "is defined in ARM proprietary documents.")
    _write(p, d)
