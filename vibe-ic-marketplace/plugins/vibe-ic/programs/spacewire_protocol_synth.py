"""SpaceWire protocol synth helper (ECSS-E-ST-50-12C).

ic_class-gated overlay for the SpaceWire structural signature: a high-speed
(2 Mbps .. 200+ Mbps), bidirectional, full-duplex, point-to-point serial
spacecraft-onboard data link (and the routers / networks built from them)
standardized by the European Cooperation for Space Standardization as
ECSS-E-ST-50-12C. SpaceWire signals over low-voltage differential signalling
(LVDS) using Data-Strobe (DS) encoding — Data (D) and Strobe (S) signals, one
differential pair each per direction (four pairs / eight wires per link), where
the clock is recovered as the exclusive-OR of Data and Strobe and only ONE of
D/S changes per bit. It is layered Physical -> Signal -> Character -> Exchange
-> Packet -> Network. The character set is 10-bit data characters and 4-bit
control characters FCT (Flow Control Token), EOP (End of Packet), EEP (Error
End of Packet) and ESC (Escape), plus NULL (ESC+FCT) and Time-Code (ESC + data
character). The exchange-level link initialization state machine runs
ErrorReset -> ErrorWait -> Ready -> Started -> Connecting -> Run with
credit-based flow control (one FCT grants eight N-Chars; max 56 outstanding).
Packets are <destination address><cargo><EOP/EEP>; networks use routers with
wormhole routing, path / logical / regional-logical addressing, a configuration
port (port 0) and group adaptive routing; Time-Codes (6-bit) distribute system
time; RMAP (ECSS-E-ST-50-52C) runs over SpaceWire for remote memory access.
Applies the ECSS-E-ST-50-12C spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(Data-Strobe / DS encoding over LVDS + the FCT/EOP/EEP/ESC control characters +
the ErrorReset..Run exchange state machine + credit-based FCT flow control) read
from the L-doc / input_doc CONTENT blob only. It NEVER reads the input-document
filename or the benchmark folder name. The name token "SpaceWire" alone is NOT
sufficient: every True path also requires a SpaceWire-specific STRUCTURAL
signature, so the detector cannot fire on a generic LVDS doc, a generic router
doc, or a generic serial / Ethernet doc.

Sibling disambiguation — SpaceWire is its own aerospace data-handling domain,
but a structural signature is required so it does not false-fire on the
neighbouring aerospace / serial standards. MIL-STD-1553B is a dual-redundant,
1 Mbps, transformer-coupled, Manchester-encoded command/response bus with a Bus
Controller and Remote Terminals (no DS encoding, no FCT/EOP/EEP, no
ErrorReset..Run FSM). ARINC 429 is a one-way, 32-bit-word, single-source
broadcast bus (no DS encoding, no link FSM, no routers/wormhole). Generic
Ethernet is MAC/PHY framing with MII/preamble/MAC-address (no DS encoding, no
FCT/EOP/EEP characters, no ErrorReset..Run FSM). The detector REQUIRES the
SpaceWire-only structural vocabulary (DS encoding + FCT/EOP/EEP + the exchange
FSM + LVDS) and so cannot fire on a 1553 / ARINC-429 / Ethernet spec.

Public entry: ``apply_spacewire_synth(generated_docs_dir, is_spacewire,
spacewire_ic_name)``. Module-level ``is_spacewire(blob)`` is the content-only
detector.
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

# Canonical SpaceWire facts (ECSS-E-ST-50-12C — Links, Nodes, Routers, Networks).
_MIN_RATE_MBPS = 2
_DEFAULT_RATE_MBPS = 10
_TYPICAL_RATE_MBPS = 200
_DATA_CHAR_BITS = 10
_CONTROL_CHAR_BITS = 4
_TIME_CODE_BITS = 6
_FCT_CREDIT = 8
_MAX_OUTSTANDING_FCT = 7
_MAX_OUTSTANDING_NCHARS = 56
_DIFF_PAIRS_PER_LINK = 4
_WIRES_PER_LINK = 8
_CONTROL_CHARS = ["FCT", "EOP", "EEP", "ESC"]
_COMPOSITE_CODES = ["NULL", "Time-Code"]
_EXCHANGE_STATES = [
    "ErrorReset", "ErrorWait", "Ready", "Started", "Connecting", "Run",
]
_PROTOCOL_LEVELS = [
    "Physical", "Signal", "Character", "Exchange", "Packet", "Network",
]


def _wb(blob_low: str, *tokens: str) -> bool:
    """Word-boundary OR-match of any token (case-insensitive) in blob_low."""
    for t in tokens:
        if re.search(r"(?<![a-z0-9])" + re.escape(t.lower()) + r"(?![a-z0-9])",
                     blob_low):
            return True
    return False


def is_spacewire(blob: str) -> bool:
    """Content-only SpaceWire detector with a structural signature + sibling MUTEX.

    Fire on the SpaceWire structural signature, which requires ALL of:
      (1) Data-Strobe (DS) encoding over LVDS — the D/S two-signal scheme where
          the clock is the XOR of Data and Strobe;
      (2) the SpaceWire control-character set — FCT (Flow Control Token) and at
          least one of EOP / EEP (End / Error-End of Packet);
      (3) the exchange-level link initialization state machine — at least two of
          the ErrorReset / ErrorWait / Started / Connecting / Run states (or the
          ErrorReset->Run progression).
    The name token "SpaceWire" alone is NOT sufficient (general-not-keyword); it
    only helps once the structural signature is also present. Defers (returns
    False) on a MIL-STD-1553 / ARINC-429 / Ethernet doc that lacks the DS +
    FCT/EOP/EEP + exchange-FSM signature, and on a bare LVDS / generic-router /
    generic-serial doc. Reads ONLY the spec text `blob` — never a filename or
    benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # (1) Data-Strobe (DS) encoding over LVDS — the SpaceWire signal level.
    lvds = "lvds" in low or "low-voltage differential" in low or \
           "low voltage differential" in low
    ds_encoding = (
        "data-strobe" in low or "data strobe" in low
        or ("ds encoding" in low)
        or ("data" in low and "strobe" in low
            and ("xor" in low or "exclusive-or" in low
                 or "exclusive or" in low))
    )
    # Require the strobe-signal concept explicitly (not just the word "data").
    strobe = _wb(low, "strobe")
    signal_level = ds_encoding and strobe and lvds

    # (2) SpaceWire control-character set: FCT + (EOP or EEP).
    fct = _wb(low, "fct") or "flow control token" in low
    eop = _wb(low, "eop") or "end of packet" in low
    eep = _wb(low, "eep") or "error end of packet" in low
    esc = _wb(low, "esc") or _wb(low, "escape")
    control_chars = fct and (eop or eep)

    # (3) Exchange-level link initialization state machine.
    exch_states = [
        "errorreset", "error reset", "errorwait", "error wait",
        "started", "connecting",
    ]
    exch_hits = sum(1 for s in exch_states if s in low)
    run_state = bool(re.search(r"(?<![a-z0-9])run(?![a-z0-9])", low))
    progression = ("errorreset" in low or "error reset" in low) and run_state
    exchange_fsm = exch_hits >= 2 or progression

    # Credit-based flow control (FCT grants 8) reinforces but is not required.
    credit_flow = (
        ("credit" in low and fct)
        or ("eight" in low and fct and ("n-char" in low or "nchar" in low))
        or ("grants" in low and fct)
    )

    name_token = "spacewire" in low or "space wire" in low

    # --- Sibling MUTEX: defer on neighbouring aerospace / serial standards
    # that lack the SpaceWire DS + FCT/EOP/EEP + exchange-FSM signature. ---
    structural = signal_level and control_chars and exchange_fsm

    mil1553 = (
        ("1553" in low or "mil-std-1553" in low or "mil std 1553" in low)
        and ("bus controller" in low or "remote terminal" in low
             or "manchester" in low)
        and not structural
    )
    if mil1553:
        return False

    arinc429 = (
        ("arinc 429" in low or "arinc429" in low or "arinc-429" in low)
        and not structural
    )
    if arinc429:
        return False

    # Generic Ethernet doc: MAC/PHY/MII framing, no DS / FCT-EOP-EEP / exch-FSM.
    ethernet_primary = (
        ("ethernet" in low or "mii" in low or "mac address" in low
         or "preamble" in low)
        and not structural
        and not name_token
    )
    if ethernet_primary:
        return False

    # Primary fire: the full structural signature.
    if structural:
        return True

    # Fallback: the unambiguous SpaceWire name token, but ONLY when it is
    # accompanied by a substantial structural signature (DS+strobe over LVDS,
    # plus the FCT/EOP/EEP control set, plus credit flow control or the
    # exchange FSM). This still refuses a bare "SpaceWire" mention with no
    # structure.
    if name_token and signal_level and control_chars and \
            (exchange_fsm or credit_flow or esc):
        return True

    return False


def apply_spacewire_synth(generated_docs_dir: Path, is_spacewire_flag: bool,
                          spacewire_ic_name: Optional[str]) -> None:
    """Apply ECSS-E-ST-50-12C SpaceWire synth when the signature matched."""
    if not is_spacewire_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if spacewire_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = spacewire_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = spacewire_ic_name
                d["ic_name"] = spacewire_ic_name
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
# L1 — SpaceWire datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "SpaceWire — Links, Nodes, Routers and Networks"
    d["version"] = "ECSS-E-ST-50-12C"
    d["revised_date"] = "ECSS-E-ST-50-12C (SpaceWire standard)"
    d["manufacturer"] = ("European Cooperation for Space Standardization "
                         "(ECSS)")
    d["copyright"] = "© ECSS"
    d["abstract"] = (
        "SpaceWire is a spacecraft-onboard data-handling network standard "
        "(ECSS-E-ST-50-12C) defining high-speed (2 Mbps to over 200 Mbps), "
        "bidirectional, full-duplex, point-to-point serial data links and the "
        "routing switches and networks built from them. A SpaceWire link uses "
        "low-voltage differential signalling (LVDS) and Data-Strobe (DS) "
        "encoding: a Data (D) signal and a Strobe (S) signal, one differential "
        "pair each per direction (four pairs / eight wires per bidirectional "
        "link), where the clock is recovered as the exclusive-OR of Data and "
        "Strobe and only one of the two signals changes per bit. SpaceWire is "
        "layered Physical -> Signal -> Character -> Exchange -> Packet -> "
        "Network. The character set is 10-bit data characters and 4-bit "
        "control characters FCT (Flow Control Token), EOP (End of Packet), EEP "
        "(Error End of Packet) and ESC (Escape), plus NULL (ESC+FCT) and "
        "Time-Code (ESC + data character). The exchange-level link "
        "initialization state machine runs ErrorReset -> ErrorWait -> Ready -> "
        "Started -> Connecting -> Run with credit-based flow control (one FCT "
        "grants eight N-Chars; up to 56 outstanding). SpaceWire is based on "
        "IEEE 1355-1995 and the ANSI/TIA/EIA-644 LVDS standard.")
    d["keywords"] = [
        "SpaceWire", "ECSS-E-ST-50-12C", "LVDS", "Data-Strobe", "DS encoding",
        "Data", "Strobe", "Data XOR Strobe", "FCT", "Flow Control Token",
        "EOP", "End of Packet", "EEP", "Error End of Packet", "ESC", "Escape",
        "NULL", "Time-Code", "data character", "control character",
        "ErrorReset", "ErrorWait", "Ready", "Started", "Connecting", "Run",
        "credit-based flow control", "N-Char", "wormhole routing", "router",
        "path address", "logical address", "regional logical addressing",
        "group adaptive routing", "configuration port", "port 0", "RMAP",
        "IEEE 1355", "parity", "disconnect error", "full-duplex",
        "point-to-point", "spacecraft onboard network",
    ]
    d["external_pins"] = [
        "Dout+ / Dout- : transmitted Data signal (differential LVDS pair)",
        "Sout+ / Sout- : transmitted Strobe signal (differential LVDS pair)",
        "Din+ / Din- : received Data signal (differential LVDS pair)",
        "Sin+ / Sin- : received Strobe signal (differential LVDS pair)",
        "Four LVDS differential pairs (eight wires) per bidirectional link; "
        "standard 9-pin micro-miniature D-type connector",
        "No separately forwarded clock wire — the clock is recovered as Data "
        "XOR Strobe (Data-Strobe encoding)",
    ]
    d["supported_data_rate_Mbps"] = {
        "min": _MIN_RATE_MBPS, "default_at_reset": _DEFAULT_RATE_MBPS,
        "typical": _TYPICAL_RATE_MBPS, "note": "2 Mbps to over 200 Mbps",
    }
    d["differential_pairs_per_link"] = _DIFF_PAIRS_PER_LINK
    d["wires_per_link"] = _WIRES_PER_LINK
    d["modes_of_operation"] = [
        {"name": "Node link", "role": "point-to-point data link",
         "note": "A bidirectional full-duplex SpaceWire link connecting two "
                 "nodes (or a node and a router)."},
        {"name": "Router / routing switch",
         "role": "network packet routing",
         "note": "A routing switch with multiple SpaceWire ports plus a "
                 "configuration port (port 0); forwards packets by wormhole "
                 "routing using path / logical / regional-logical addresses."},
        {"name": "Time-Code distribution", "role": "system time broadcast",
         "note": "A time master broadcasts 6-bit Time-Codes; nodes and routers "
                 "forward them to distribute synchronized system time."},
        {"name": "RMAP (over SpaceWire)", "role": "remote memory access",
         "note": "Remote Memory Access Protocol (ECSS-E-ST-50-52C) reads / "
                 "writes remote memory and registers, e.g. router config."},
    ]
    d["key_features"] = [
        "High-speed (2 Mbps .. 200+ Mbps), bidirectional, full-duplex, "
        "point-to-point serial spacecraft-onboard data link; ECSS-E-ST-50-12C.",
        "Low-voltage differential signalling (LVDS, ANSI/TIA/EIA-644) on Data "
        "(D) and Strobe (S) signals — two differential pairs per direction, "
        "four pairs / eight wires per link.",
        "Data-Strobe (DS) encoding: only one of D/S changes per bit; the clock "
        "is recovered as Clock = Data XOR Strobe, tolerating large D/S skew.",
        "Layered architecture: Physical -> Signal -> Character -> Exchange -> "
        "Packet -> Network.",
        "Character level: 10-bit data characters and 4-bit control characters "
        "FCT / EOP / EEP / ESC; composite codes NULL (ESC+FCT) and Time-Code "
        "(ESC + data character); odd parity per character.",
        "Exchange-level link initialization state machine ErrorReset -> "
        "ErrorWait -> Ready -> Started -> Connecting -> Run.",
        "Credit-based flow control: one FCT grants eight N-Chars; up to seven "
        "outstanding FCTs (56 N-Chars) bounded by the receive buffer.",
        "Packets are <destination address><cargo><EOP/EEP>; wormhole routing "
        "through routers; path, logical, and regional-logical addressing; "
        "group adaptive routing; configuration port (port 0).",
        "Time-Codes distribute a 6-bit system time across the network with low "
        "latency and jitter.",
        "Link error detection: disconnect, parity, escape, and credit errors; "
        "recovery by re-running the ErrorReset..Run handshake.",
        "RMAP (ECSS-E-ST-50-52C) runs over SpaceWire for remote memory / "
        "register access (with header and data CRC).",
    ]
    d["topology_summary"] = (
        "Point-to-point bidirectional full-duplex links connect nodes and "
        "routing switches into a SpaceWire network. Routers forward packets by "
        "wormhole routing using path / logical / regional-logical addresses; a "
        "configuration port (port 0) accesses the router's registers.")
    d["use_cases"] = [
        "Spacecraft onboard high-speed data handling (sensors, instruments, "
        "mass memory, downlink telemetry)",
        "Payload data buses for Earth-observation and science instruments",
        "Inter-subsystem links between processing units and mass-memory units",
        "Router-based onboard networks with redundancy (group adaptive "
        "routing)",
        "Remote configuration and memory access of onboard units via RMAP",
    ]
    d["revision_history"] = [
        {"version": "IEEE 1355-1995", "date": "1995",
         "description": "Heritage standard (DS-DE / DS-SE links) on which the "
                        "SpaceWire signal and exchange levels are based."},
        {"version": "ECSS-E-50-12A", "date": "2003",
         "description": "First ECSS SpaceWire standard (Links, Nodes, Routers "
                        "and Networks)."},
        {"version": "ECSS-E-ST-50-12C", "date": "2008",
         "description": "Current SpaceWire standard: LVDS + Data-Strobe "
                        "encoding, the FCT/EOP/EEP/ESC character set, the "
                        "ErrorReset..Run exchange state machine, credit-based "
                        "flow control, packets, routers, and Time-Codes."},
    ]
    d["overview"] = (
        "SpaceWire (ECSS-E-ST-50-12C) is a spacecraft-onboard serial data-link "
        "and network standard. A link is a bidirectional, full-duplex, "
        "point-to-point connection between two nodes (or a node and a router). "
        "Each direction carries a Data (D) and a Strobe (S) signal as LVDS "
        "differential pairs (four pairs / eight wires per link). Data-Strobe "
        "encoding ensures only one of D/S changes per bit, so the clock is "
        "recovered as Data XOR Strobe and the link tolerates large skew. The "
        "standard is layered Physical -> Signal -> Character -> Exchange -> "
        "Packet -> Network. Characters are 10-bit data characters (parity + "
        "data-control flag + 8 data bits) and 4-bit control characters: FCT "
        "(Flow Control Token), EOP (End of Packet), EEP (Error End of Packet), "
        "and ESC (Escape); ESC+FCT forms NULL and ESC+data-character forms a "
        "Time-Code. The exchange level runs a link initialization state "
        "machine ErrorReset -> ErrorWait -> Ready -> Started -> Connecting -> "
        "Run, synchronizing both ends by exchanging NULLs (link connected) and "
        "FCTs (credit available). Credit-based flow control grants eight "
        "N-Chars per FCT (up to 56 outstanding). Packets are <destination "
        "address><cargo><EOP/EEP> and are forwarded by routers using wormhole "
        "routing with path, logical, and regional-logical addressing, group "
        "adaptive routing, and a configuration port (port 0). Time-Codes "
        "distribute a 6-bit system time, and RMAP runs over SpaceWire for "
        "remote memory access. Link errors (disconnect, parity, escape, "
        "credit) drive the link back to ErrorReset for recovery.")
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
        "High-speed, bidirectional, full-duplex, point-to-point serial "
        "spacecraft-onboard data link (and the routers / networks built from "
        "them). LVDS signalling with Data-Strobe (DS) encoding; layered "
        "Physical/Signal/Character/Exchange/Packet/Network. Standardized as "
        "ECSS-E-ST-50-12C.")
    po["duplex"] = (
        "Full-duplex, bidirectional: each direction carries an independent "
        "Data (D) and Strobe (S) LVDS pair, so data flows both ways "
        "simultaneously.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "Data-Strobe (DS) encoding over LVDS: the Strobe signal changes "
        "whenever the Data signal does not, so exactly one of the two signals "
        "changes per bit and the clock is recovered as Clock = Data XOR "
        "Strobe. Characters carry odd parity.")
    po["modulation"] = ("LVDS differential on Data (D+/D-) and Strobe (S+/S-) "
                        "in each direction.")
    po["data_rate_Mbps"] = {
        "min": _MIN_RATE_MBPS, "default_at_reset": _DEFAULT_RATE_MBPS,
        "typical": _TYPICAL_RATE_MBPS,
    }
    po["protocol_levels"] = list(_PROTOCOL_LEVELS)
    po["control_characters"] = list(_CONTROL_CHARS)
    po["composite_codes"] = list(_COMPOSITE_CODES)
    po["exchange_states"] = list(_EXCHANGE_STATES)
    po["data_character_bits"] = _DATA_CHAR_BITS
    po["control_character_bits"] = _CONTROL_CHAR_BITS
    po["fct_credit"] = _FCT_CREDIT
    po["max_outstanding_nchars"] = _MAX_OUTSTANDING_NCHARS
    po["connection_oriented"] = True
    po["differential_pairs_per_link"] = _DIFF_PAIRS_PER_LINK
    po["topology"] = (
        "node <-> link <-> node / router; routers forward packets by wormhole "
        "routing into a SpaceWire network.")
    d["functional_requirements"] = [
        {"id": "FR-SIG-01", "text": "A SpaceWire link signals over LVDS "
         "(ANSI/TIA/EIA-644) using Data-Strobe (DS) encoding: a Data signal "
         "and a Strobe signal per direction, each a differential pair, so the "
         "clock is recovered as Data XOR Strobe and only one of D/S changes "
         "per bit."},
        {"id": "FR-PHY-02", "text": "A bidirectional full-duplex link uses "
         "four LVDS differential pairs (eight wires): Data and Strobe in each "
         "direction; there is no separately forwarded clock wire."},
        {"id": "FR-RATE-03", "text": "Links operate from 2 Mbps to over 200 "
         "Mbps; the default data signalling rate after reset is 10 Mbit/s."},
        {"id": "FR-CHAR-04", "text": "The character level defines 10-bit data "
         "characters (parity + data-control flag + 8 data bits, LSB first) and "
         "4-bit control characters (parity + data-control flag + 2 control "
         "bits)."},
        {"id": "FR-CTRL-05", "text": "The four control characters are FCT "
         "(Flow Control Token), EOP (End of Packet), EEP (Error End of "
         "Packet), and ESC (Escape); ESC+FCT forms NULL and ESC+data-character "
         "forms a Time-Code."},
        {"id": "FR-FSM-06", "text": "The exchange level runs a link "
         "initialization state machine ErrorReset -> ErrorWait -> Ready -> "
         "Started -> Connecting -> Run; both ends synchronize by exchanging "
         "NULLs (link connected) and FCTs (credit available)."},
        {"id": "FR-FLOW-07", "text": "Flow control is credit-based: each FCT "
         "received grants permission to send eight further N-Chars; up to "
         "seven FCTs (56 N-Chars) may be outstanding, bounded by the receive "
         "buffer."},
        {"id": "FR-PKT-08", "text": "Data is transferred in packets of the "
         "form <destination address><cargo><EOP or EEP>; packets are of "
         "arbitrary length and delimited by EOP (normal) or EEP (error)."},
        {"id": "FR-NET-09", "text": "A SpaceWire network is built from nodes "
         "and routing switches; routers forward packets by wormhole routing "
         "using path addressing, logical addressing, and regional-logical "
         "addressing, with optional group adaptive routing."},
        {"id": "FR-CFG-10", "text": "A router has a configuration port "
         "(port 0) that accesses its configuration registers (routing table, "
         "port control/status, error/status) via RMAP or packets to port 0."},
        {"id": "FR-TIME-11", "text": "Time-Codes (ESC + a data character "
         "carrying a 6-bit time value plus two flags) are broadcast by a time "
         "master and forwarded by nodes and routers to distribute a "
         "synchronized system time."},
        {"id": "FR-ERR-12", "text": "The exchange level detects disconnect, "
         "parity, escape, and credit errors and recovers by returning to "
         "ErrorReset and re-running the initialization handshake."},
    ]
    d["error_response_conditions"] = [
        "Disconnect error — the gap between Data/Strobe transitions exceeds the "
        "disconnect timeout (~850 ns); the other end stopped transmitting.",
        "Parity error — the odd parity covering a character fails.",
        "Escape error — an ESC is followed by another ESC or by an EOP/EEP "
        "(an invalid escape sequence).",
        "Credit error — an N-Char arrives with no credit granted, or the "
        "transmitter sends with no credit.",
        "On any of these errors the link goes to ErrorReset and re-runs the "
        "ErrorReset -> ErrorWait -> Ready -> Started -> Connecting -> Run "
        "handshake.",
    ]
    d["compliance_requirements"] = [
        "LVDS signalling with Data-Strobe (DS) encoding; clock = Data XOR "
        "Strobe; four differential pairs per bidirectional link.",
        "10-bit data characters and 4-bit control characters; FCT/EOP/EEP/ESC; "
        "NULL (ESC+FCT) and Time-Code (ESC + data character); odd parity.",
        "Exchange-level state machine ErrorReset -> ErrorWait -> Ready -> "
        "Started -> Connecting -> Run.",
        "Credit-based flow control: one FCT grants eight N-Chars; max 56 "
        "outstanding.",
        "Packets <destination address><cargo><EOP/EEP>; wormhole routing; "
        "path / logical / regional-logical addressing; group adaptive routing; "
        "configuration port (port 0).",
        "Time-Code (6-bit) system-time distribution.",
        "Link error detection (disconnect / parity / escape / credit) with "
        "ErrorReset recovery.",
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
        "Character-and-packet serial link protocol over LVDS with Data-Strobe "
        "encoding. The link is brought up by the exchange-level state machine "
        "(ErrorReset -> ErrorWait -> Ready -> Started -> Connecting -> Run) "
        "exchanging NULLs and FCTs; once in Run, data characters flow under "
        "credit-based flow control inside packets delimited by EOP/EEP, "
        "forwarded across a network by routers using wormhole routing.")
    d["protocol_levels"] = [
        {"name": "Physical", "purpose": "Connectors, cables, and PCB tracks."},
        {"name": "Signal", "purpose": "LVDS signalling and Data-Strobe (DS) "
         "encoding; clock = Data XOR Strobe."},
        {"name": "Character", "purpose": "10-bit data characters and 4-bit "
         "control characters (FCT/EOP/EEP/ESC; NULL; Time-Code)."},
        {"name": "Exchange", "purpose": "Link initialization state machine, "
         "flow control, link error detection and recovery."},
        {"name": "Packet", "purpose": "Splitting data into packets "
         "<address><cargo><EOP/EEP>."},
        {"name": "Network", "purpose": "Routers, wormhole routing, and "
         "addressing across a SpaceWire network."},
    ]
    d["character_types"] = [
        {"name": "Data character", "bits": _DATA_CHAR_BITS,
         "fields": "parity + data-control flag (=0) + 8 data bits (LSB first)"},
        {"name": "Control character", "bits": _CONTROL_CHAR_BITS,
         "fields": "parity + data-control flag (=1) + 2 control bits"},
    ]
    d["control_characters"] = [
        {"name": "FCT", "full": "Flow Control Token",
         "purpose": "Grants credit to send eight further N-Chars."},
        {"name": "EOP", "full": "End of Packet",
         "purpose": "Marks the normal end of a packet."},
        {"name": "EEP", "full": "Error End of Packet",
         "purpose": "Marks a premature end of a packet due to a network "
                    "error."},
        {"name": "ESC", "full": "Escape",
         "purpose": "Forms longer codes with the following character "
                    "(NULL = ESC+FCT; Time-Code = ESC + data character)."},
    ]
    d["composite_codes"] = [
        {"name": "NULL", "form": "ESC + FCT",
         "purpose": "Sent when nothing else is to be sent; keeps the link "
                    "active and confirms the connection."},
        {"name": "Time-Code", "form": "ESC + data character",
         "purpose": "Carries a 6-bit time value plus two flags for system-time "
                    "distribution."},
    ]
    d["character_classes"] = {
        "N-Char": "Normal characters passed to the host: data characters, EOP, "
                  "EEP.",
        "L-Char": "Link characters consumed by the link interface: FCT, ESC, "
                  "NULL, Time-Codes.",
    }
    d["link_initialization"] = {
        "states": list(_EXCHANGE_STATES),
        "handshake": "ErrorReset (reset ~6.4 us) -> ErrorWait (~12.8 us) -> "
                     "Ready (wait for enable) -> Started (send NULLs, wait for "
                     "a NULL) -> Connecting (send FCTs, wait for an FCT) -> "
                     "Run (full operation).",
        "synchronization": "Both ends exchange NULLs to confirm the link is "
                           "connected and FCTs to confirm credit before data "
                           "flows.",
    }
    d["flow_control"] = {
        "scheme": "credit-based",
        "fct_credit": _FCT_CREDIT,
        "max_outstanding_fct": _MAX_OUTSTANDING_FCT,
        "max_outstanding_nchars": _MAX_OUTSTANDING_NCHARS,
        "rule": "Each received FCT adds eight to the credit; each N-Char "
                "transmitted subtracts one; an N-Char may be sent only when "
                "credit > 0.",
    }
    d["packet_format"] = {
        "form": "<destination address> <cargo> <EOP or EEP>",
        "address": "path address (port numbers), logical address (one byte), "
                   "or regional-logical address.",
        "terminator": "EOP (normal) or EEP (error).",
        "length": "arbitrary (no maximum packet size).",
    }
    d["addressing"] = {
        "path": "Leading data character is an output port number (1..31), "
                "consumed (deleted) by each router.",
        "logical": "Leading data character is a logical address (32..255) "
                   "mapped to an output port by the router's routing table; "
                   "not deleted.",
        "regional_logical": "Combination of path and logical addressing for "
                            "large networks.",
        "group_adaptive": "A logical address may map to a group of output "
                          "ports for load sharing and redundancy.",
    }
    d["time_codes"] = {
        "form": "ESC + data character",
        "time_value_bits": _TIME_CODE_BITS,
        "rule": "Each node/router forwards a Time-Code whose value is one "
                "greater (modulo 64) than the last and signals a tick to its "
                "host.",
    }
    d["byte_oriented"] = True
    d["character_oriented"] = True
    d["packet_oriented"] = True
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
        "SpaceWire is a link/network standard rather than a fixed "
        "memory-mapped register IC. A routing switch exposes configuration and "
        "status through its configuration port (port 0), accessed by RMAP or "
        "by packets addressed to port 0; a link interface exposes link control "
        "and status. The groups below are the canonical SpaceWire "
        "configuration / status surfaces.")
    d["register_access"] = {
        "transport": "Router configuration port (port 0) via RMAP or "
                     "port-0-addressed packets; link-interface control/status "
                     "registers (implementation-defined).",
        "purpose": "Configure the routing table and port settings; read link "
                   "state, error counters, and time.",
    }
    d["register_groups"] = [
        {"group": "Router configuration (port 0)", "fields": [
            "Routing table (logical address -> output port)",
            "Group adaptive routing group membership",
            "Port enable / link rate / control",
            "Port status (link state, connection)",
            "Error and status registers (disconnect / parity / escape / "
            "credit error counts)"]},
        {"group": "Link interface", "fields": [
            "Link enable / Start / AutoStart",
            "Operating data signalling rate",
            "Link state (ErrorReset / ErrorWait / Ready / Started / "
            "Connecting / Run)",
            "Credit count / FCT control",
            "Error status (disconnect / parity / escape / credit)"]},
        {"group": "Time interface", "fields": [
            "Current Time-Code value (6-bit)",
            "Time master / tick control",
            "Time-Code flags"]},
    ]
    d["protocol_fields"] = {
        "data_character_bits": _DATA_CHAR_BITS,
        "control_character_bits": _CONTROL_CHAR_BITS,
        "time_code_bits": _TIME_CODE_BITS,
        "fct_credit": _FCT_CREDIT,
        "max_outstanding_nchars": _MAX_OUTSTANDING_NCHARS,
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
        "Each SpaceWire link direction carries a Data (D) signal and a Strobe "
        "(S) signal, each a low-voltage differential signalling (LVDS) pair "
        "(D+/D-, S+/S-). Data-Strobe (DS) encoding ensures exactly one of the "
        "two signals changes per bit, so the receiver recovers the clock as "
        "Clock = Data XOR Strobe. There is no separately forwarded clock wire. "
        "A bidirectional link uses four LVDS pairs (eight wires).")
    d["modulation"] = ("LVDS differential on Data (D+/D-) and Strobe (S+/S-) "
                       "per direction.")
    d["clocking"] = (
        "Embedded clock recovered by Data-Strobe decoding: Clock = Data XOR "
        "Strobe. Because only one of D/S changes per bit, the link tolerates "
        "large skew between the Data and Strobe wires (up to almost one bit "
        "period).")
    d["transmitter_specs_canonical"] = {
        "signaling": "LVDS (ANSI/TIA/EIA-644), differential",
        "signals_per_direction": ["Data (D+/D-)", "Strobe (S+/S-)"],
        "encoding": "Data-Strobe (DS); Strobe toggles when Data does not",
        "differential_output_mV": 350,
        "common_mode_V": 1.2,
        "data_rate_Mbps": {"min": _MIN_RATE_MBPS,
                            "default_at_reset": _DEFAULT_RATE_MBPS,
                            "typical": _TYPICAL_RATE_MBPS},
    }
    d["receiver_specs_canonical"] = {
        "signaling": "LVDS differential (Din/Sin pairs)",
        "clock_recovery": "Clock = Data XOR Strobe (DS decoding)",
        "skew_tolerance": "tolerates up to almost one bit period of D/S skew",
        "disconnect_timeout_ns": 850,
    }
    d["lvds"] = {
        "standard": "ANSI/TIA/EIA-644",
        "differential_output_mV": 350,
        "common_mode_V": 1.2,
        "purpose": "high-speed, low-power, low-EMI, noise-immune signalling",
    }
    d["differential_pairs_per_link"] = _DIFF_PAIRS_PER_LINK
    d["wires_per_link"] = _WIRES_PER_LINK
    d["encoding_role_in_analog"] = (
        "Data-Strobe encoding over LVDS is the heart of the SpaceWire signal "
        "level: the Strobe signal changes whenever Data does not, so the clock "
        "is the exclusive-OR of Data and Strobe. This avoids a forwarded clock "
        "and tolerates large wire-to-wire skew; integrity at the character "
        "level comes from odd parity, and at the link level from disconnect / "
        "escape / credit error detection.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / exchange + link FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_link"] = [
        {"name": "ErrorReset", "description": "Entered after reset or a link "
         "error; transmit/receive activity stopped and reset; remains ~6.4 us "
         "then moves to ErrorWait."},
        {"name": "ErrorWait", "description": "Waits ~12.8 us looking for "
         "receive activity; a disconnect/parity/escape error returns to "
         "ErrorReset, otherwise moves to Ready."},
        {"name": "Ready", "description": "Link ready to start; waits until "
         "enabled (Start or AutoStart), then moves to Started."},
        {"name": "Started", "description": "Transmitter enabled, sending "
         "NULLs; on receiving a NULL moves to Connecting; timeout returns to "
         "ErrorReset."},
        {"name": "Connecting", "description": "Transmitter sends FCTs as well "
         "as NULLs; on receiving an FCT moves to Run; timeout returns to "
         "ErrorReset."},
        {"name": "Run", "description": "Fully operational: NULLs, FCTs, "
         "Time-Codes, data characters, EOP/EEP flow with credit-based flow "
         "control; an error returns to ErrorReset."},
    ]
    d["fsm_hints"] = {
        "trigger": "Reset / link error -> ErrorReset -> ErrorWait -> Ready. "
        "Enable (Start/AutoStart) drives Ready -> Started; receiving a NULL "
        "drives Started -> Connecting; receiving an FCT drives Connecting -> "
        "Run.",
        "rule": "Data characters flow only in Run and only while credit > 0 "
        "(granted by received FCTs); NULLs keep an idle link active; both ends "
        "run the same state machine and synchronize by NULL/FCT exchange.",
        "abort": "A disconnect / parity / escape / credit error in any active "
        "state returns the link to ErrorReset to re-run the handshake.",
    }
    d["anti_deadlock_rule"] = (
        "Credit-based flow control bounds outstanding N-Chars to the receive "
        "buffer (max 56), so a receiver cannot be overrun; wormhole routing "
        "plus EOP/EEP termination and the ErrorReset recovery prevent a "
        "blocked or errored packet from stalling the link indefinitely.")
    d["exit_from_reset_or_poweron"] = (
        "On power-up / reset the link enters ErrorReset, waits the reset and "
        "error-wait times (ErrorWait), becomes Ready, and — once enabled — "
        "sends NULLs (Started) then FCTs (Connecting) until it reaches Run.")
    d["default_ready_state_recommendation"] = {
        "idle": "Send NULL characters to keep the link active and confirm the "
                "connection between data.",
        "credit": "Grant FCTs (each worth eight N-Chars) before the far end "
                  "may send data characters.",
    }
    d["configurations"] = [
        {"name": "Node-to-node link", "description": "Point-to-point "
         "bidirectional full-duplex link between two nodes."},
        {"name": "Node-to-router link", "description": "A node connected to a "
         "SpaceWire port of a routing switch."},
        {"name": "Router-to-router link", "description": "Two routing switches "
         "connected to grow the network."},
        {"name": "AutoStart vs Start", "description": "AutoStart starts the "
         "link when activity is detected; Start starts it under host control."},
    ]
    d["timing_dependency_rule"] = (
        "No data character flows until the link reaches Run (NULLs exchanged in "
        "Started, FCTs exchanged in Connecting). Credit (FCT) must be granted "
        "before N-Chars are sent. The reset (~6.4 us) and error-wait/timeout "
        "(~12.8 us) intervals and the disconnect timeout (~850 ns) bound the "
        "handshake and error detection.")
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
        {"name": "Link state", "purpose": "Observes the exchange FSM state "
         "(ErrorReset / ErrorWait / Ready / Started / Connecting / Run)."},
        {"name": "Error status", "purpose": "Indicates disconnect, parity, "
         "escape, and credit errors per link."},
        {"name": "Credit / FCT status", "purpose": "Outstanding credit and "
         "FCT counts for flow-control observability."},
        {"name": "Router status (port 0)", "purpose": "Per-port link state, "
         "routing-table contents, and error/status registers via RMAP / "
         "port-0 packets."},
        {"name": "Time-Code value", "purpose": "Current 6-bit time value and "
         "tick for time-distribution checking."},
        {"name": "EOP / EEP", "purpose": "Packet termination type indicates "
         "normal vs error end of packet."},
    ]
    d["error_detection_mechanisms"] = [
        "Odd parity per character detects single-bit character corruption.",
        "Disconnect error detects loss of the far end (gap > ~850 ns).",
        "Escape error detects an invalid ESC sequence (ESC+ESC or ESC+EOP/EEP).",
        "Credit error detects an N-Char received/sent with no credit.",
        "EEP marks a packet truncated by a network error.",
        "Re-running ErrorReset -> Run resynchronizes the link after any error.",
    ]
    d["test_modes"] = [
        {"name": "Link bring-up", "purpose": "Exercise the ErrorReset..Run "
         "handshake and NULL/FCT exchange at the target rate."},
        {"name": "Loopback / BER", "purpose": "Physical-layer characterization "
         "of the LVDS Data/Strobe pairs and DS decoding."},
        {"name": "Error injection", "purpose": "Inject parity / disconnect / "
         "escape / credit errors and confirm ErrorReset recovery."},
        {"name": "Time-Code exercise", "purpose": "Broadcast Time-Codes and "
         "verify forwarding and tick generation."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Link up", "trigger": "Link reaches Run."},
        {"event": "Link down / error", "trigger": "Disconnect / parity / "
         "escape / credit error returns the link to ErrorReset."},
        {"event": "Packet received", "trigger": "An EOP/EEP terminates a "
         "received packet."},
        {"event": "Tick", "trigger": "A valid Time-Code increments system "
         "time."},
        {"event": "Credit exhausted", "trigger": "No FCT credit remaining."},
    ]
    d["notes"] = (
        "SpaceWire exposes its protocol-level test/debug surface through the "
        "link state machine, per-link error status (disconnect / parity / "
        "escape / credit), credit/FCT counts, EOP/EEP packet termination, the "
        "router configuration port (port 0, via RMAP), and Time-Code "
        "observability, plus physical-layer loopback / BER. Chip-level JTAG / "
        "scan / BIST remain implementation / SoC concerns.")
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
        "SPACEWIRE_STANDARD": "ECSS-E-ST-50-12C",
        "SIGNALING": "LVDS (ANSI/TIA/EIA-644), differential",
        "ENCODING": "Data-Strobe (DS); Clock = Data XOR Strobe",
        "DATA_CHAR_BITS": _DATA_CHAR_BITS,
        "CONTROL_CHAR_BITS": _CONTROL_CHAR_BITS,
        "TIME_CODE_BITS": _TIME_CODE_BITS,
        "FCT_CREDIT": _FCT_CREDIT,
        "MAX_OUTSTANDING_FCT": _MAX_OUTSTANDING_FCT,
        "MAX_OUTSTANDING_NCHARS": _MAX_OUTSTANDING_NCHARS,
        "DIFF_PAIRS_PER_LINK": _DIFF_PAIRS_PER_LINK,
        "WIRES_PER_LINK": _WIRES_PER_LINK,
        "MIN_RATE_MBPS": _MIN_RATE_MBPS,
        "DEFAULT_RATE_MBPS": _DEFAULT_RATE_MBPS,
        "TYPICAL_RATE_MBPS": _TYPICAL_RATE_MBPS,
        "CONTROL_CHARS": list(_CONTROL_CHARS),
        "COMPOSITE_CODES": list(_COMPOSITE_CODES),
        "EXCHANGE_STATES": list(_EXCHANGE_STATES),
        "PROTOCOL_LEVELS": list(_PROTOCOL_LEVELS),
        "FULL_DUPLEX": True,
        "POINT_TO_POINT": True,
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
    })
    d["character_format_constants"] = {
        "data_character_bits": _DATA_CHAR_BITS,
        "control_character_bits": _CONTROL_CHAR_BITS,
        "control_characters": list(_CONTROL_CHARS),
        "composite_codes": list(_COMPOSITE_CODES),
        "parity": "odd",
    }
    d["flow_control_constants"] = {
        "scheme": "credit-based",
        "fct_credit": _FCT_CREDIT,
        "max_outstanding_fct": _MAX_OUTSTANDING_FCT,
        "max_outstanding_nchars": _MAX_OUTSTANDING_NCHARS,
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "is_full_duplex": True,
        "is_point_to_point": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "encoding": "Data-Strobe (Clock = Data XOR Strobe)",
        "signaling": "LVDS",
        "data_char_bits": _DATA_CHAR_BITS,
        "control_char_bits": _CONTROL_CHAR_BITS,
        "time_code_bits": _TIME_CODE_BITS,
        "control_chars": list(_CONTROL_CHARS),
        "composite_codes": list(_COMPOSITE_CODES),
        "exchange_states": list(_EXCHANGE_STATES),
        "fct_credit": _FCT_CREDIT,
        "max_outstanding_nchars": _MAX_OUTSTANDING_NCHARS,
        "diff_pairs_per_link": _DIFF_PAIRS_PER_LINK,
        "wormhole_routing": True,
        "addressing": ["path", "logical", "regional-logical"],
    })
    d["default_signal_values_when_idle"] = {
        "link_idle": "Send NULL (ESC+FCT) characters to keep the link active "
                     "and confirm the connection.",
        "no_data": "Data characters flow only in Run and only while credit > 0.",
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
    d["bit_waveform"] = {
        "signaling": "LVDS differential on Data (D+/D-) and Strobe (S+/S-)",
        "encoding": "Data-Strobe: Strobe toggles when Data does not; exactly "
                    "one of D/S changes per bit",
        "clock_recovery": "Clock = Data XOR Strobe; no forwarded clock",
        "skew_tolerance": "tolerates up to almost one bit period of D/S skew",
    }
    d["character_waveform"] = {
        "data_character": "10 bits: parity + data-control flag (0) + 8 data "
                          "bits (LSB first)",
        "control_character": "4 bits: parity + data-control flag (1) + 2 "
                             "control bits (FCT/EOP/EEP/ESC)",
        "composite": "NULL = ESC+FCT; Time-Code = ESC + data character",
    }
    d["link_init_waveform"] = {
        "handshake": "ErrorReset (~6.4 us) -> ErrorWait (~12.8 us) -> Ready -> "
                     "Started (NULLs) -> Connecting (FCTs) -> Run",
        "synchronization": "exchange NULLs (connected) then FCTs (credit)",
        "disconnect_timeout_ns": 850,
    }
    d["flow_control_waveform"] = {
        "fct": "each FCT grants eight N-Chars; up to 56 outstanding",
        "rule": "an N-Char may be sent only while credit > 0",
    }
    d["time_code_waveform"] = {
        "form": "ESC + data character carrying a 6-bit time value plus 2 flags",
        "rule": "forwarded if one greater (mod 64) than the last received",
    }
    d["general_timing_rule"] = (
        "The link must reach Run (NULLs then FCTs exchanged) before data "
        "characters flow; credit (FCT) must precede N-Chars; the disconnect "
        "timeout (~850 ns) and the reset / error-wait intervals (~6.4 / ~12.8 "
        "us) bound link bring-up and error detection.")
    d["data_rate_waveform"] = {
        "min_Mbps": _MIN_RATE_MBPS,
        "default_at_reset_Mbps": _DEFAULT_RATE_MBPS,
        "typical_Mbps": _TYPICAL_RATE_MBPS,
        "encoding": "Data-Strobe over LVDS",
    }
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
        "Spacecraft-onboard serial link / network controller: a SpaceWire link "
        "interface (LVDS Data/Strobe pairs, Data-Strobe encoding, the "
        "ErrorReset..Run exchange state machine, FCT/EOP/EEP/ESC character "
        "handling, credit-based flow control) and/or a routing switch "
        "(wormhole routing, path/logical/regional-logical addressing, group "
        "adaptive routing, configuration port port 0) connecting nodes into a "
        "SpaceWire network, with Time-Code distribution and RMAP support.")
    d["topology_description"] = (
        "node <-> point-to-point bidirectional full-duplex link <-> node / "
        "router. Routers forward packets by wormhole routing across the "
        "SpaceWire network; a configuration port (port 0) manages each "
        "router's routing table and ports.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "spacewire_standard": "ECSS-E-ST-50-12C",
        "signaling": "LVDS (ANSI/TIA/EIA-644), differential",
        "encoding": "Data-Strobe (Clock = Data XOR Strobe)",
        "data_rate_Mbps": {"min": _MIN_RATE_MBPS,
                           "default_at_reset": _DEFAULT_RATE_MBPS,
                           "typical": _TYPICAL_RATE_MBPS},
        "differential_pairs_per_link": _DIFF_PAIRS_PER_LINK,
        "control_characters": list(_CONTROL_CHARS),
        "exchange_states": list(_EXCHANGE_STATES),
        "fct_credit": _FCT_CREDIT,
        "max_outstanding_nchars": _MAX_OUTSTANDING_NCHARS,
        "clocking": "embedded (Data-Strobe decoding)",
        "full_duplex": True,
        "point_to_point": True,
        "wormhole_routing": True,
        "addressing": ["path", "logical", "regional-logical"],
        "interfaces": {"link": "Dout/Sout, Din/Sin LVDS pairs",
                       "config": "router configuration port (port 0) / RMAP",
                       "time": "Time-Code interface"},
    })
    d["interface_categories"] = [
        "Link interface — LVDS Data/Strobe differential pairs (four pairs per "
        "bidirectional link).",
        "Character/exchange interface — FCT/EOP/EEP/ESC handling, "
        "ErrorReset..Run FSM, credit-based flow control.",
        "Packet/network interface — wormhole routing, path/logical/"
        "regional-logical addressing, group adaptive routing.",
        "Configuration interface — router configuration port (port 0) via "
        "RMAP; Time-Code distribution.",
    ]
    d["interconnect_topologies_supported"] = [
        "Point-to-point node-to-node link.",
        "Node-to-router and router-to-router links.",
        "Router-based SpaceWire network with wormhole routing.",
        "Group adaptive routing for load sharing and redundancy.",
        "Time-Code broadcast tree for system-time distribution.",
    ]
    d["default_signal_values_when_omitted"] = (
        "An idle link exchanges NULL characters to stay active; data "
        "characters flow only in Run and only while FCT credit remains.")
    d["soc_dependent_items"] = [
        "Number of SpaceWire ports (link interfaces / router ports).",
        "Operating data signalling rate (2 .. 200+ Mbps).",
        "Routing-table contents and group adaptive routing groups.",
        "Logical address assignment per node.",
        "Time master / Time-Code distribution role.",
        "Physical connector / cable / PCB-track design (LVDS).",
    ]
    d["device_classes_examples"] = [
        "SpaceWire node / link interface (instrument, processor, mass memory)",
        "SpaceWire routing switch (router)",
        "SpaceWire-to-host bridge",
        "RMAP initiator / target",
        "Time master node",
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
        "Signal level: LVDS Data/Strobe pairs; Data-Strobe encoding; clock = "
        "Data XOR Strobe; D/S skew tolerance.",
        "Character level: 10-bit data characters and 4-bit control characters; "
        "FCT/EOP/EEP/ESC; NULL (ESC+FCT); Time-Code (ESC + data char); odd "
        "parity.",
        "Link initialization: ErrorReset -> ErrorWait -> Ready -> Started -> "
        "Connecting -> Run with NULL/FCT exchange; reset and timeout "
        "intervals.",
        "Credit-based flow control: one FCT grants eight N-Chars; max 56 "
        "outstanding; credit-error handling.",
        "Packet format: <address><cargo><EOP/EEP>; arbitrary length; EOP vs "
        "EEP termination.",
        "Addressing: path (port numbers, deleted hop-by-hop), logical (table "
        "lookup), regional-logical.",
        "Routing: wormhole routing through routers; group adaptive routing; "
        "configuration port (port 0).",
        "Time-Codes: 6-bit time distribution; forward-if-one-greater rule; "
        "tick generation.",
        "Link errors: disconnect (>~850 ns), parity, escape, credit; "
        "ErrorReset recovery.",
        "Data signalling rate: 2 Mbps .. 200+ Mbps; 10 Mbit/s default at "
        "reset.",
        "RMAP over SpaceWire: write / read / read-modify-write; header and "
        "data CRC.",
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
        {"field": "Logical address",
         "location": "node configuration",
         "note": "The node's logical address (32..255); assigned, not a "
                 "protocol-fixed OTP concept."},
        {"field": "Routing table",
         "location": "router configuration (port 0)",
         "note": "Logical-address-to-output-port map; programmed via RMAP / "
                 "port-0 packets, not OTP-fixed."},
        {"field": "Operating data rate",
         "location": "link configuration",
         "note": "The negotiated / configured 2..200+ Mbps signalling rate "
                 "(default 10 Mbit/s at reset)."},
        {"field": "Port enable / AutoStart",
         "location": "link configuration",
         "note": "Whether each port is enabled and starts automatically."},
    ]
    d["notes"] = (
        "SpaceWire does not define OTP/fuse content as a protocol concept. "
        "Logical addresses, routing tables, data rates, and port settings are "
        "node / router configuration (often via RMAP through the "
        "configuration port). An implementation may back defaults with "
        "non-volatile storage, but the standard only requires they be "
        "configurable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["link_initialization_sequence"] = [
        "1. Reset / link error -> ErrorReset: stop and reset TX/RX, wait the "
        "reset time (~6.4 us).",
        "2. ErrorWait (~12.8 us): look for receive activity; a disconnect / "
        "parity / escape error returns to ErrorReset.",
        "3. Ready: wait until enabled (Start or AutoStart).",
        "4. Started: send NULLs; on receiving a NULL move to Connecting "
        "(timeout returns to ErrorReset).",
        "5. Connecting: send FCTs as well as NULLs; on receiving an FCT move "
        "to Run (timeout returns to ErrorReset).",
        "6. Run: full operation — NULLs, FCTs, Time-Codes, data characters, "
        "EOP/EEP flow with credit-based flow control.",
    ]
    d["flow_control_sequence"] = [
        "1. The receiver sends an FCT for every eight N-Chars of buffer space "
        "it has available.",
        "2. The transmitter adds eight to its credit per received FCT.",
        "3. The transmitter sends an N-Char only while credit > 0, subtracting "
        "one per N-Char sent.",
        "4. Up to seven FCTs (56 N-Chars) may be outstanding; sending with no "
        "credit is a credit error -> ErrorReset.",
    ]
    d["packet_transfer_sequence"] = [
        "1. The source transmits the destination address (path / logical / "
        "regional-logical), then the cargo data characters.",
        "2. Each router uses the leading address character to select an output "
        "port (deleting a path character; keeping a logical one) and forwards "
        "the packet by wormhole routing.",
        "3. The source terminates the packet with EOP (normal) or EEP (error).",
        "4. The destination receives <cargo> up to the EOP/EEP.",
    ]
    d["time_code_sequence"] = [
        "1. A time master broadcasts a Time-Code (ESC + data character with a "
        "6-bit time value).",
        "2. Each node/router checks the value is one greater (mod 64) than the "
        "last received; if so it forwards it out of its other ports.",
        "3. The node signals a tick (the new time value) to its host.",
    ]
    d["error_recovery_sequence"] = [
        "1. A disconnect / parity / escape / credit error is detected in an "
        "active state.",
        "2. The link returns to ErrorReset and silences its transmitter.",
        "3. Both ends re-run ErrorReset -> ErrorWait -> Ready -> Started -> "
        "Connecting -> Run to resynchronize.",
    ]
    d["rmap_sequence"] = [
        "1. An RMAP initiator sends a command packet (write / read / "
        "read-modify-write) addressed to a target across the network.",
        "2. The target executes the memory / register access (no software "
        "needed) and checks the header and data CRC.",
        "3. The target returns a reply packet matched by transaction "
        "identifier.",
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
        {"name": "LVDS eye / levels", "purpose": "Verify the ~350 mV "
         "differential output around ~1.2 V common-mode on the Data/Strobe "
         "pairs."},
        {"name": "Data-Strobe skew tolerance", "purpose": "Confirm the link "
         "tolerates up to ~one bit period of D/S skew; clock = Data XOR "
         "Strobe."},
        {"name": "Data signalling rate", "purpose": "Validate operation from "
         "2 Mbps to 200+ Mbps; 10 Mbit/s default at reset."},
        {"name": "Link initialization timing", "purpose": "Measure the "
         "ErrorReset (~6.4 us) and ErrorWait/timeout (~12.8 us) intervals and "
         "NULL/FCT exchange."},
        {"name": "Disconnect timeout", "purpose": "Confirm disconnect "
         "detection at ~850 ns of inactivity."},
        {"name": "Flow-control credit", "purpose": "Verify one FCT grants "
         "eight N-Chars and at most 56 are outstanding."},
        {"name": "Time-Code latency / jitter", "purpose": "Measure system-time "
         "distribution latency and jitter across the network."},
    ]
    d["notes"] = (
        "SpaceWire characterization centers on the LVDS Data/Strobe eye and "
        "levels, Data-Strobe skew tolerance, the data signalling rate, the "
        "ErrorReset..Run initialization timing, the ~850 ns disconnect "
        "timeout, credit-based flow control, and Time-Code latency / jitter. "
        "Per-link SerDes and connector/cable calibration is done at bring-up; "
        "conformance is established by SpaceWire (ECSS) testing.")
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
    f["spec_version"] = "ECSS-E-ST-50-12C — SpaceWire (Links, Nodes, Routers, Networks)"
    f["previous_versions"] = [
        "IEEE 1355-1995 — heritage DS-DE / DS-SE link standard.",
        "ECSS-E-50-12A (2003) — first ECSS SpaceWire standard.",
        "ECSS-E-ST-50-12C (2008) — current SpaceWire standard.",
    ]
    f["key_changes"] = [
        {"version": "IEEE 1355 -> SpaceWire", "summary": "SpaceWire adopts the "
         "Data-Strobe encoding and exchange-level concepts of IEEE 1355 but "
         "standardizes LVDS signalling, the FCT/EOP/EEP/ESC character set, the "
         "ErrorReset..Run state machine, Time-Codes, and routers/networks for "
         "spacecraft use."},
        {"version": "ECSS-E-50-12A -> ECSS-E-ST-50-12C", "summary": "Refined "
         "and clarified the link, character, exchange, packet, and network "
         "levels; the LVDS + Data-Strobe signalling, credit-based flow "
         "control, wormhole routing, and Time-Code distribution are carried "
         "forward."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "SpaceWire-D / SpaceFibre (related)", "summary": "Related "
         "ECSS work adds deterministic/QoS scheduling (SpaceWire-D) and "
         "multi-Gbps serial links with lanes and virtual channels "
         "(SpaceFibre, ECSS-E-ST-50-11C); the SpaceWire packet model is "
         "preserved."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "DS_not_forwarded_clock",
         "rule": "The clock is recovered as Data XOR Strobe; only one of D/S "
                 "changes per bit.",
         "trap": "Treating Strobe as a separately forwarded clock is wrong; it "
                 "is the DS-encoding partner of Data."},
        {"trap_name": "Run_required_before_data",
         "rule": "Data characters flow only after the link reaches Run (NULLs "
                 "then FCTs exchanged).",
         "trap": "Sending data before Run / before FCT credit is a protocol "
                 "error."},
        {"trap_name": "EOP_vs_EEP",
         "rule": "EOP is a normal end of packet; EEP marks a packet truncated "
                 "by a network error.",
         "trap": "Treating EEP as a normal terminator hides a network error."},
        {"trap_name": "Not_1553_not_ARINC429",
         "rule": "SpaceWire is LVDS + Data-Strobe with FCT/EOP/EEP and the "
                 "ErrorReset..Run FSM and routers; MIL-STD-1553 is a "
                 "transformer-coupled Manchester command/response bus and "
                 "ARINC 429 is a one-way 32-bit-word broadcast bus.",
         "trap": "Applying 1553 BC/RT command-response or ARINC-429 "
                 "single-source-broadcast assumptions to SpaceWire is wrong."},
    ]
    f["version_naming_history_note"] = (
        "SpaceWire is standardized by the European Cooperation for Space "
        "Standardization (ECSS) as ECSS-E-ST-50-12C, based on IEEE 1355-1995 "
        "and the ANSI/TIA/EIA-644 LVDS standard. It defines the link "
        "(LVDS + Data-Strobe), character (FCT/EOP/EEP/ESC), exchange "
        "(ErrorReset..Run FSM + credit flow control), packet, and network "
        "(routers + wormhole routing) levels, plus Time-Codes. RMAP "
        "(ECSS-E-ST-50-52C) and SpaceFibre (ECSS-E-ST-50-11C) are companion "
        "standards.")
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
    f["control_character_table"] = {
        "header_columns": ["Character", "Bits", "Meaning"],
        "rows": [
            ["FCT", "4", "Flow Control Token (grants 8 N-Chars)"],
            ["EOP", "4", "End of Packet (normal)"],
            ["EEP", "4", "Error End of Packet"],
            ["ESC", "4", "Escape (forms NULL / Time-Code)"],
        ],
    }
    f["composite_code_table"] = {
        "header_columns": ["Code", "Form", "Meaning"],
        "rows": [
            ["NULL", "ESC + FCT", "keep-alive / connection confirm"],
            ["Time-Code", "ESC + data character", "6-bit system-time "
             "distribution"],
        ],
    }
    f["character_format_table"] = {
        "header_columns": ["Type", "Bits", "Fields"],
        "rows": [
            ["Data character", "10", "parity + data-control flag(0) + 8 data "
             "bits (LSB first)"],
            ["Control character", "4", "parity + data-control flag(1) + 2 "
             "control bits"],
        ],
    }
    f["exchange_state_table"] = {
        "header_columns": ["State", "Action"],
        "rows": [
            ["ErrorReset", "reset TX/RX (~6.4 us) -> ErrorWait"],
            ["ErrorWait", "wait ~12.8 us for activity -> Ready"],
            ["Ready", "wait for enable (Start/AutoStart) -> Started"],
            ["Started", "send NULLs; on NULL received -> Connecting"],
            ["Connecting", "send FCTs; on FCT received -> Run"],
            ["Run", "full operation; error -> ErrorReset"],
        ],
    }
    f["data_rate_table"] = {
        "header_columns": ["Parameter", "Value"],
        "rows": [
            ["Minimum rate", "2 Mbps"],
            ["Default rate at reset", "10 Mbit/s"],
            ["Typical / maximum", "200+ Mbps"],
        ],
    }
    f["flow_control_table"] = {
        "header_columns": ["Parameter", "Value"],
        "rows": [
            ["N-Chars granted per FCT", "8"],
            ["Max outstanding FCTs", "7"],
            ["Max outstanding N-Chars", "56"],
        ],
    }
    f["addressing_table"] = {
        "header_columns": ["Method", "Address", "Router action"],
        "rows": [
            ["Path", "output port number (1..31)", "select port, delete "
             "character"],
            ["Logical", "logical address (32..255)", "table lookup, keep "
             "character"],
            ["Regional-logical", "path + logical combination", "route within "
             "and between regions"],
        ],
    }
    f["encoding_note"] = (
        "SpaceWire signals over LVDS with Data-Strobe (DS) encoding: the Strobe "
        "signal changes whenever Data does not, so the clock is recovered as "
        "Clock = Data XOR Strobe. Characters are 10-bit data characters and "
        "4-bit control characters (FCT/EOP/EEP/ESC), with NULL (ESC+FCT) and "
        "Time-Code (ESC + data character) composite codes, all carrying odd "
        "parity.")
    f["tables"] = [
        "Control-character table (FCT/EOP/EEP/ESC)",
        "Composite-code table (NULL, Time-Code)",
        "Character-format table (10-bit data, 4-bit control)",
        "Exchange-state table (ErrorReset..Run)",
        "Data-rate table (2 / 10 / 200+ Mbps)",
        "Flow-control table (8 per FCT, max 56)",
        "Addressing table (path / logical / regional-logical)",
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
        "LVDS signalling with Data-Strobe (DS) encoding; clock = Data XOR "
        "Strobe; four differential pairs per bidirectional link.",
        "10-bit data characters and 4-bit control characters FCT/EOP/EEP/ESC; "
        "NULL (ESC+FCT); Time-Code (ESC + data character); odd parity.",
        "Exchange-level state machine ErrorReset -> ErrorWait -> Ready -> "
        "Started -> Connecting -> Run.",
        "Credit-based flow control: one FCT grants eight N-Chars; max 56 "
        "outstanding.",
        "Packets <destination address><cargo><EOP/EEP>; wormhole routing; "
        "path / logical / regional-logical addressing; group adaptive "
        "routing; configuration port (port 0).",
        "Time-Code (6-bit) system-time distribution.",
        "Link error detection (disconnect / parity / escape / credit) with "
        "ErrorReset recovery.",
    ]
    f["must_not_have_properties"] = [
        "A separately forwarded clock wire (the clock is Data XOR Strobe).",
        "A transformer-coupled Manchester command/response bus with a Bus "
        "Controller and Remote Terminals (that is MIL-STD-1553, not "
        "SpaceWire).",
        "A one-way single-source 32-bit-word broadcast bus (that is ARINC 429, "
        "not SpaceWire).",
        "MAC/PHY Ethernet framing (preamble / MAC address / MII) as the link "
        "(that is Ethernet, not SpaceWire).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Disconnect error", "trigger": "Gap between D/S transitions "
         "exceeds ~850 ns; link returns to ErrorReset."},
        {"mode": "Parity error", "trigger": "Odd parity on a character fails; "
         "link returns to ErrorReset."},
        {"mode": "Escape error", "trigger": "Invalid ESC sequence (ESC+ESC or "
         "ESC+EOP/EEP); link returns to ErrorReset."},
        {"mode": "Credit error", "trigger": "N-Char sent/received with no "
         "credit; link returns to ErrorReset."},
        {"mode": "EEP", "trigger": "A packet is truncated by a network error "
         "(error end of packet)."},
    ]
    f["min_link_constraint"] = (
        "A SpaceWire link requires both ends to run the exchange state machine, "
        "signal over LVDS Data/Strobe pairs with Data-Strobe encoding, exchange "
        "NULLs (Started) and FCTs (Connecting), and reach Run before data "
        "characters flow under credit-based flow control.")
    f["reset_behavior_compliance"] = (
        "On reset or link error the link enters ErrorReset (silences the "
        "transmitter, ~6.4 us), then ErrorWait (~12.8 us), Ready, Started "
        "(NULLs), Connecting (FCTs), and Run.")
    f["spacewire_distinguishers"] = (
        "SpaceWire is identified by ALL of: LVDS signalling with Data-Strobe "
        "(DS) encoding (clock = Data XOR Strobe; Data and Strobe pairs, only "
        "one changing per bit); the 10-bit data / 4-bit control character set "
        "with FCT/EOP/EEP/ESC, NULL, and Time-Codes; the exchange-level "
        "ErrorReset -> ErrorWait -> Ready -> Started -> Connecting -> Run state "
        "machine; credit-based flow control (one FCT grants eight N-Chars, max "
        "56 outstanding); packets <address><cargo><EOP/EEP> forwarded by "
        "wormhole routing with path/logical/regional-logical addressing through "
        "routers with a configuration port (port 0); and Time-Code system-time "
        "distribution. This is distinct from MIL-STD-1553B (a dual-redundant, "
        "1 Mbps, transformer-coupled, Manchester-encoded command/response bus "
        "with a Bus Controller and Remote Terminals) and from ARINC 429 (a "
        "one-way, single-source, 32-bit-word broadcast bus), neither of which "
        "has Data-Strobe encoding, the FCT/EOP/EEP character set, or the "
        "ErrorReset..Run exchange state machine.")
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
        {"name": "Dout+ / Dout-",
         "direction": "transmit (differential LVDS)",
         "purpose": "Outbound Data signal of the link.",
         "active_levels": "LVDS differential", "idle_level": "NULL characters"},
        {"name": "Sout+ / Sout-",
         "direction": "transmit (differential LVDS)",
         "purpose": "Outbound Strobe signal (toggles when Data does not).",
         "active_levels": "LVDS differential", "idle_level": "NULL characters"},
        {"name": "Din+ / Din-",
         "direction": "receive (differential LVDS)",
         "purpose": "Inbound Data signal of the link.",
         "active_levels": "LVDS differential", "idle_level": "NULL characters"},
        {"name": "Sin+ / Sin-",
         "direction": "receive (differential LVDS)",
         "purpose": "Inbound Strobe signal (DS partner of Din).",
         "active_levels": "LVDS differential", "idle_level": "NULL characters"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "NULL (idle)", "meaning": "Link active but no data in "
         "flight; ESC+FCT keep-alive."},
        {"name": "Run / data", "meaning": "Link in Run; data characters flow "
         "under FCT credit."},
    ]
    f["packet_types_summary"] = [
        {"class": "Control character", "members": list(_CONTROL_CHARS),
         "count": len(_CONTROL_CHARS)},
        {"class": "Composite code", "members": list(_COMPOSITE_CODES),
         "count": len(_COMPOSITE_CODES)},
        {"class": "Character", "members": ["data character", "control "
         "character"], "count": 2},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "differential_pairs_per_link": _DIFF_PAIRS_PER_LINK,
        "wires_per_link": _WIRES_PER_LINK,
        "signals_per_direction": 2,
        "control_character_count": len(_CONTROL_CHARS),
        "composite_code_count": len(_COMPOSITE_CODES),
        "exchange_state_count": len(_EXCHANGE_STATES),
        "data_character_bits": _DATA_CHAR_BITS,
        "control_character_bits": _CONTROL_CHAR_BITS,
        "time_code_bits": _TIME_CODE_BITS,
        "fct_credit": _FCT_CREDIT,
    })
    f["global_signals"] = [
        {"name": "Logical address", "purpose": "Identifies a destination node "
         "(32..255) for logical-address routing."},
        {"name": "Time-Code", "purpose": "6-bit system-time value broadcast "
         "across the network."},
        {"name": "Link state", "purpose": "ErrorReset..Run exchange-FSM state "
         "per link."},
    ]
    f["dependency_graph"] = {
        "common_rule": "A link must run the exchange FSM (ErrorReset -> "
        "ErrorWait -> Ready -> Started -> Connecting -> Run), exchanging NULLs "
        "and FCTs, before any data character flows. Routers forward packets by "
        "wormhole routing using the leading address character.",
        "data_dependency": "A data character (N-Char) requires: (1) the link "
        "in Run, (2) FCT credit > 0. Each FCT grants eight N-Chars; up to 56 "
        "may be outstanding. A packet ends with EOP/EEP.",
    }
    f["handshake_pairs"] = [
        {"name": "NULL exchange", "from": "link end", "to": "link end",
         "rule": "Both ends send/receive NULLs in Started to confirm the link "
                 "is connected."},
        {"name": "FCT exchange", "from": "receiver", "to": "transmitter",
         "rule": "An FCT in Connecting/Run grants eight N-Chars of credit."},
        {"name": "EOP/EEP", "from": "source", "to": "destination",
         "rule": "Terminates a packet (normal / error)."},
        {"name": "Time-Code", "from": "time master", "to": "all nodes",
         "rule": "Broadcasts and forwards the 6-bit system time."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "LVDS Data/Strobe; data character bits LSB first; "
        "clock = Data XOR Strobe.",
        "character_order": "Address characters precede cargo; EOP/EEP "
        "terminates a packet.",
        "credit": "An N-Char is sent only while FCT credit remains.",
        "routing": "Routers forward by wormhole routing as soon as the header "
        "is decoded.",
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
        "Point-to-point serial links between nodes and routing switches, "
        "interconnected into a SpaceWire network. Packets are forwarded by "
        "wormhole routing through routers using path / logical / "
        "regional-logical addresses; there is no shared parallel bus.")
    f["supported_topologies"] = [
        {"name": "Node-to-node link", "description": "Point-to-point "
         "bidirectional full-duplex link between two nodes."},
        {"name": "Node-to-router link", "description": "A node connected to a "
         "SpaceWire port of a routing switch."},
        {"name": "Router-to-router link", "description": "Two routers "
         "connected to extend the network."},
        {"name": "Wormhole-routed network", "description": "Multiple routers "
         "and nodes forming a SpaceWire network with wormhole routing."},
        {"name": "Group adaptive routing", "description": "A logical address "
         "maps to a group of output ports for load sharing / redundancy."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Node", "description": "Source / destination of packets "
         "(instrument, processor, mass memory); has one or more link "
         "interfaces."},
        {"role": "Routing switch (router)", "description": "Forwards packets "
         "by wormhole routing; has multiple ports plus a configuration port "
         "(port 0)."},
        {"role": "Time master", "description": "Broadcasts Time-Codes to "
         "distribute system time."},
        {"role": "RMAP initiator / target", "description": "Reads / writes "
         "remote memory and registers over SpaceWire."},
    ]
    f["interconnect_role"] = (
        "SpaceWire is a spacecraft-onboard serial network. Links are "
        "point-to-point and full-duplex; routers forward packets by wormhole "
        "routing using path addressing (port numbers consumed hop by hop), "
        "logical addressing (routing-table lookup), and regional-logical "
        "addressing, with group adaptive routing for redundancy. Credit-based "
        "flow control and Time-Codes operate across the network.")
    f["routing_methods"] = ["path addressing", "logical addressing",
                            "regional-logical addressing",
                            "group adaptive routing"]
    f["ordering_guarantees"] = {
        "link": "Characters are ordered within a link; a packet is delimited "
        "by EOP/EEP.",
        "wormhole": "A router begins forwarding as soon as the header is "
        "decoded; the packet worms through.",
        "credit": "Flow is paced by FCT credit so a receiver is not overrun.",
    }
    f["memory_vs_peripheral_regions"] = (
        "SpaceWire is not memory-mapped at the link level; packets are "
        "addressed by path / logical address, not by a memory address. RMAP "
        "(over SpaceWire) provides remote memory / register access; a router's "
        "configuration registers are reached through the configuration port "
        "(port 0).")
    dc = _ensure_dict(f, "device_classification")
    dc["node"] = "Source / destination of packets; one or more link ports."
    dc["router"] = "Forwards packets by wormhole routing; configuration port 0."
    dc["time_master"] = "Broadcasts Time-Codes for system-time distribution."
    dc["rmap_initiator"] = "Reads/writes remote memory and registers."
    dc["rmap_target"] = "Executes RMAP memory/register accesses, returns reply."
    f["default_signal_values_evidence_tables"] = [
        "SpaceWire protocol-level layering (Physical / Signal / Character / "
        "Exchange / Packet / Network)",
        "Link diagram (Data and Strobe LVDS pairs in each direction)",
        "Network topology figure (nodes and routers)",
        "Packet format figure (<address><cargo><EOP/EEP>)",
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
    f["electrical_channel_constraints"] = {
        "signaling": "LVDS (ANSI/TIA/EIA-644), differential, on Data and "
                     "Strobe pairs per direction",
        "encoding": "Data-Strobe (DS); Clock = Data XOR Strobe",
        "differential_output_mV": 350,
        "common_mode_V": 1.2,
        "data_rate_Mbps": {"min": _MIN_RATE_MBPS,
                           "default_at_reset": _DEFAULT_RATE_MBPS,
                           "typical": _TYPICAL_RATE_MBPS},
        "differential_pairs_per_link": _DIFF_PAIRS_PER_LINK,
        "disconnect_timeout_ns": 850,
        "clocking": "embedded (Data-Strobe decoding); no forwarded clock",
        "connector": "9-pin micro-miniature D-type; four twisted shielded "
                     "pairs + overall shield",
    }
    f["notes"] = (
        "SpaceWire is a link/network standard (ECSS-E-ST-50-12C): it fixes the "
        "LVDS + Data-Strobe signal level, the character set (FCT/EOP/EEP/ESC), "
        "the ErrorReset..Run exchange state machine, credit-based flow "
        "control, the packet format, wormhole routing, and Time-Codes. It does "
        "NOT impose PDK-specific SDC / floorplan constraints; LVDS electrical "
        "characterization, the connector, and cable design are physical-layer "
        "concerns. The interoperability-critical constraints are the "
        "DS-encoding, the character set, the exchange FSM, the flow-control "
        "credit, and the disconnect/parity/escape/credit error detection.")
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
        {"name": "Link state / error status", "purpose": "Per-link "
         "ErrorReset..Run state and disconnect/parity/escape/credit error "
         "observability."},
        {"name": "Router config port (port 0)", "purpose": "Routing-table and "
         "port status / error registers via RMAP / port-0 packets."},
        {"name": "Credit / FCT status", "purpose": "Flow-control credit "
         "observability."},
        {"name": "Time-Code value", "purpose": "System-time distribution "
         "observability."},
        {"name": "Loopback / BER", "purpose": "Physical-layer LVDS / "
         "Data-Strobe characterization."},
    ]
    f["internal_diagnostics_observability"] = [
        "Link state (ErrorReset / ErrorWait / Ready / Started / Connecting / "
        "Run).",
        "Operating data signalling rate.",
        "Disconnect / parity / escape / credit error counts.",
        "Outstanding FCT credit.",
        "EOP/EEP packet-termination counts; Time-Code value.",
    ]
    f["out_of_band_test_facilities"] = [
        "SpaceWire (ECSS) conformance / interoperability testing.",
        "Vendor LVDS / link-interface bring-up and characterization tooling "
        "(implementation-defined).",
    ]
    f["notes"] = (
        "SpaceWire's protocol-level DFT surface is the link state machine, "
        "per-link error status, credit/FCT counts, EOP/EEP termination, the "
        "router configuration port (port 0, via RMAP), Time-Code value, and "
        "physical-layer loopback / BER. Chip-level JTAG / scan / BIST remain "
        "implementation / SoC concerns; conformance is established by ECSS "
        "SpaceWire testing.")
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
        {"state": "Active", "name": "Run", "description": "Link in Run; data "
         "and NULLs/FCTs flowing."},
        {"state": "Idle", "name": "NULL keep-alive", "description": "Link up "
         "but only NULL characters transmitted between data."},
        {"state": "Stopped", "name": "ErrorReset / disabled", "description": "Link "
         "disabled or reset; transmitter silent."},
    ]
    f["wakeup_mechanism"] = (
        "A disabled or reset link re-runs the exchange handshake (ErrorReset "
        "-> ... -> Run) when enabled (Start) or on detected activity "
        "(AutoStart). LVDS low-power signalling keeps active-link power low.")
    f["power_rails"] = [
        {"rail": "VDD (link interface / LVDS)", "purpose": "Logic and LVDS "
         "driver/receiver supply."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["spacewire_power_considerations"] = (
        "LVDS signalling is chosen partly for low power and low EMI. The "
        "protocol-level power behavior is the AutoStart/Start enable and the "
        "NULL keep-alive idle; detailed rails and low-power SerDes behavior "
        "are physical-layer / implementation concerns.")
    f["notes"] = (
        "SpaceWire's protocol-level power intent is the link enable "
        "(Start/AutoStart), the ErrorReset (transmitter silent) state, and the "
        "NULL keep-alive idle rather than a fine-grained power-domain spec. "
        "LVDS is inherently low-power; detailed rails are implementation "
        "concerns.")
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
        "Signal level — LVDS Data/Strobe pairs; Data-Strobe encoding; clock = "
        "Data XOR Strobe; skew tolerance.",
        "Character level — 10-bit data / 4-bit control characters; "
        "FCT/EOP/EEP/ESC; NULL; Time-Code; odd parity.",
        "Link initialization — ErrorReset -> ErrorWait -> Ready -> Started -> "
        "Connecting -> Run; NULL/FCT exchange; reset/timeout intervals.",
        "Flow control — credit-based; one FCT grants eight N-Chars; max 56 "
        "outstanding; credit error.",
        "Packet — <address><cargo><EOP/EEP>; arbitrary length; EOP vs EEP.",
        "Routing — wormhole routing; path / logical / regional-logical "
        "addressing; group adaptive routing; configuration port (port 0).",
        "Time-Codes — 6-bit distribution; one-greater-mod-64 forwarding; tick.",
        "Link errors — disconnect (~850 ns) / parity / escape / credit; "
        "ErrorReset recovery.",
        "Data rate — 2 .. 200+ Mbps; 10 Mbit/s default at reset.",
        "RMAP over SpaceWire — write / read / read-modify-write; header and "
        "data CRC.",
    ]
    f["notes"] = (
        "SpaceWire does not ship an embedded testbench, but the standard "
        "implies a verification plan spanning the signal level (LVDS / "
        "Data-Strobe), the character set, the exchange state machine and flow "
        "control, packets and wormhole routing, Time-Codes, the link error "
        "detection, and RMAP. ECSS SpaceWire conformance / interoperability "
        "testing supplies the formal suite.")
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
        "Odd parity per character detects single-bit character corruption.",
        "Disconnect / escape / credit error detection guards link integrity.",
        "EEP marks a packet truncated by a network error.",
        "RMAP (over SpaceWire) carries a header CRC and a data CRC for "
        "integrity.",
        "The ErrorReset recovery resynchronizes the link after any error.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "The base SpaceWire protocol provides no cryptographic "
        "confidentiality or authentication on the link; parity, error "
        "detection, and RMAP CRCs are anti-corruption only.",
        "RMAP includes a 'key' field for simple access control, and "
        "higher-layer protocols / mission-specific encryption can be layered "
        "above SpaceWire for security.",
    ]
    f["notes"] = (
        "SpaceWire is a spacecraft-onboard serial link/network: its built-in "
        "protections are anti-corruption (odd parity, disconnect/escape/credit "
        "error detection, EEP, RMAP CRCs). The link carries plaintext "
        "characters; cryptographic confidentiality / authentication are NOT "
        "part of the base SpaceWire data path and must be layered above the "
        "protocol if required.")
    _write(p, d)
