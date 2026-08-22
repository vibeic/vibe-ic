"""HDLC / SDLC-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the HDLC / SDLC structural signature. Applies ISO/IEC
13239:2002 canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
HDLC has many variants (LAPB / LAPD / LAPM / LAPF / PPP / Cisco HDLC /
SDLC) but they all share the same Flag/Address/Control/Information/FCS/
Flag frame skeleton, the bit-stuffing + flag-delimited framing, and the
I/S/U frame discriminator.

Detection signature (one of):
  - HDLC + I-frame + S-frame + U-frame
  - HDLC + flag + 0x7E + bit stuffing
  - HDLC + SDLC + SABM

Public entry: `apply_hdlc_synth(generated_docs_dir, is_hdlc, hdlc_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def apply_hdlc_synth(generated_docs_dir: Path, is_hdlc: bool,
                     hdlc_ic_name: Optional[str]) -> None:
    """Apply HDLC / SDLC-specific synth when the structural signature matched."""
    if not is_hdlc:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if hdlc_ic_name is not None:
        for n in [
            "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
            "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
            "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
            "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
            "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
            "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = hdlc_ic_name
                _write(q, d)

    # L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title",
            "High-Level Data Link Control (HDLC) — Information technology — Telecommunications and information exchange between systems — High-level data link control (HDLC) procedures")
        d.setdefault("version", "ISO/IEC 13239:2002")
        d.setdefault("manufacturer",
            "International Organization for Standardization (ISO) / IEC; based on IBM Synchronous Data Link Control (SDLC)")
        d.setdefault("revised_date",
            "2002 (ISO/IEC 13239:2002 — current consolidated edition)")
        d.setdefault("copyright",
            "© ISO/IEC 13239:2002. Original derivative work: IBM SDLC. Earlier ISO standards: ISO 3309-1979 (Frame Structure), ISO 4335-1979 (Elements of Procedure), ISO 6159-1980 (Unbalanced Classes of Procedure), ISO 6256-1981 (Balanced Classes of Procedure) — all replaced by ISO/IEC 13239:2002.")
        d.setdefault("document_layout", [
            "Frame structure — Flag / Address / Control / Information / FCS / Flag (originally ISO 3309).",
            "Elements of procedure — frame types (I / S / U), sequence numbers, P/F bit, mode-set commands (originally ISO 4335).",
            "Unbalanced classes of procedure — NRM, ARM (primary/secondary; originally ISO 6159).",
            "Balanced classes of procedure — ABM (peer-to-peer; originally ISO 6256).",
            "Functional extensions / options — extended addressing, extended numbering, 32-bit FCS, mode-reset, data-link test, group polling, single-frame retransmission (SREJ).",
        ])
        d.setdefault("key_features", [
            "Bit-oriented synchronous data link layer protocol (OSI Layer 2).",
            "Frame delimited by 0x7E flag (binary 01111110) at start and end of every frame.",
            "Bit stuffing (zero-bit insertion) — after 5 consecutive 1-bits, transmitter inserts a 0-bit so payload can never contain the flag sequence 0x7E.",
            "Three fundamental frame types: I-frame (Information, user data + sequence numbers), S-frame (Supervisory, flow + error control), U-frame (Unnumbered, link management).",
            "16-bit CRC-CCITT (polynomial 0x1021, initial register 0xFFFF) frame check sequence; optional 32-bit CRC-32 (IEEE 802.3 polynomial 0x04C11DB7).",
            "3-bit modulo-8 sequence numbers (normal control field) or 7-bit modulo-128 (extended control field) for sliding-window flow control.",
            "Piggybacked acknowledgment via N(R) receive sequence number in any I or S frame.",
            "Poll/Final (P/F) bit token for command/response solicitation; central to checkpoint retransmission.",
            "Three operational modes: NRM (Normal Response Mode, primary polls), ARM (Asynchronous Response Mode, unsolicited secondary transmit), ABM (Asynchronous Balanced Mode, peer-to-peer).",
            "Abort sequence — seven or more consecutive 1-bits force receiver to detect error and discard current frame.",
            "Idle line — continuous 1-bits OR continuous flag bytes.",
            "Sliding window flow control: up to 7 outstanding I-frames with mod-8 numbering, up to 127 with mod-128.",
            "Forms the framing basis for IEEE 802.2 LLC, PPP (RFC 1662), X.25 LAPB, ISDN LAPD, V.42 LAPM, Frame Relay LAPF, and Cisco HDLC.",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "Normal Response Mode (NRM)",       "description": "Unbalanced configuration — only the primary terminal may initiate transmission; secondaries transmit only in response to a poll. Allows operation over half-duplex links."},
            {"name": "Asynchronous Response Mode (ARM)", "description": "Unbalanced configuration — secondary may transmit without prior permission, but a distinguished primary retains responsibility for line initialization, error recovery, and logical disconnect."},
            {"name": "Asynchronous Balanced Mode (ABM)", "description": "Balanced configuration — both stations are combined terminals (can act as both primary and secondary); peer-to-peer; initiator sends SABM. Used in point-to-point links (PPP, X.25 LAPB, ISDN LAPD)."},
            {"name": "Disconnected mode (DM)",           "description": "Initial / non-operational state before initialization or after a DISC. Secondary responds DM to almost every frame other than a mode-set command."},
        ])
        d.setdefault("domain_of_application", [
            "Point-to-point synchronous serial WAN links (PPP, leased lines).",
            "X.25 packet-switched networks (LAPB at layer 2).",
            "ISDN D-channel signalling (LAPD).",
            "V.42 modem error-correction (LAPM).",
            "Frame Relay (LAPF) and Cisco HDLC (with added protocol-field header).",
            "Multidrop SDLC networks (IBM SNA — primary + multiple secondaries).",
            "Multi-channel telephone control channels on E-carrier (E1) and SONET (Cisco HDLC, Nokia HDLC).",
        ])
        d.setdefault("layered_structure", [
            {"layer": "Physical Layer",  "scope": "Synchronous (NRZI on synchronous links) or asynchronous (RS-232 with octet stuffing) bit transport. NOT defined by HDLC — integrator picks V.24, RS-232, RS-422, V.35, etc."},
            {"layer": "Data Link Layer", "scope": "Frame delimitation (flag), bit stuffing or octet stuffing, addressing, sequenced delivery, error detection (FCS), flow control (window + RR/RNR/REJ/SREJ), link management (SABM/SABME/DISC/UA/DM/FRMR/XID/TEST/UI). This is HDLC."},
            {"layer": "Network Layer",   "scope": "Out of scope — HDLC carries an opaque INFORMATION field; upper-layer protocols (IP, X.25 PLP, CLNP) define payload semantics."},
        ])
        d.setdefault("overview",
            "High-Level Data Link Control (HDLC) is a bit-oriented synchronous data link protocol, defined by ISO/IEC 13239:2002 and originally developed by ISO as a generalization of IBM Synchronous Data Link Control (SDLC). HDLC provides reliable point-to-point or multidrop data transfer between two devices over a serial link, with framing, bit stuffing, sequenced delivery, and error detection via a Frame Check Sequence (FCS). HDLC was the ancestor of LAPB (X.25), LAPD (ISDN), LAPF (Frame Relay), LAPM (V.42), PPP framing (RFC 1662), and IEEE 802.2 LLC. ISO/IEC 13239:2002 consolidated the original ISO 3309 (frame structure), ISO 4335 (elements of procedure), ISO 6159 (unbalanced classes), and ISO 6256 (balanced classes) into a single revised standard.")
        d.setdefault("compatibility_note",
            "HDLC was the inspiration for IEEE 802.2 LLC, PPP framing (RFC 1662), and is the basis for the framing mechanism used on synchronous WAN lines. HDLC variants (SDLC, LAPB, LAPD, LAPM, LAPF, Cisco HDLC) differ in elements of procedure (mode set, supervisory frames, optional functions) but share the common Flag/Address/Control/Information/FCS/Flag frame skeleton and bit-stuffing rules. Mixed-variant interoperability is generally NOT guaranteed: e.g. LAPB uses ABM only with 1-byte address + 1-byte control; SDLC uses NRM with multi-drop addressing; Cisco HDLC inserts a protocol-type field; PPP uses an asynchronous octet-stuffing variant.")
        _write(p, d)

    # L2
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type", "Bit-oriented synchronous data link protocol with frame delimitation, bit stuffing, sequenced delivery, and sliding-window flow control.")
            po.setdefault("duplex", "Half-duplex (NRM, ARM) or full-duplex (ABM); both modes carried over a single serial link (or multidrop bus in SDLC).")
            po.setdefault("synchronous", True)
            po.setdefault("framing", "Frame boundaries marked by 0x7E flag (binary 01111110); end-of-frame flag MAY be shared as start-of-frame for next frame.")
            po.setdefault("physical_layer", "Not specified — typical implementations use V.24/RS-232 (asynchronous octet-stuffing variant), V.35, V.42, X.21, RS-422, or generic bit-synchronous links.")
            po.setdefault("bit_coding_synchronous", "NRZI on synchronous links; bit stuffing (0-bit insertion after 5 consecutive 1-bits) ensures sufficient signal transitions and prevents flag emulation inside the frame.")
            po.setdefault("bit_coding_asynchronous", "NRZ on asynchronous (RS-232) links; control-octet transparency (byte stuffing): escape octet 0x7D with bit-5 inversion of the next data octet (so 0x7E becomes 0x7D 0x5E and 0x7D becomes 0x7D 0x5D).")
            po.setdefault("addressing", "Address field is 1 byte (default) or extended (multiple bytes; top bit = 0 means address continues to next byte). On point-to-point links the address still distinguishes command vs response.")
            po.setdefault("multimaster", False)
            po.setdefault("broadcast_capable", "Yes — group polling via UP command in ABM; SDLC broadcast address.")
            po.setdefault("endianness_within_byte", "Least significant bit transmitted first (NOT to be confused with byte-ordering within multi-byte fields).")
        fr = [
            {"id": "FR-FLAG-01",       "text": "Every frame begins and ends with the 8-bit flag sequence 0x7E (binary 01111110). The end-flag of one frame MAY be shared as the start-flag of the next."},
            {"id": "FR-STUFF-02",      "text": "Bit stuffing (synchronous links): in the Address + Control + Information + FCS portion, after 5 consecutive 1-bits the transmitter MUST insert a 0-bit; the receiver MUST strip a 0-bit following 5 consecutive 1-bits. After 5 ones followed by a 1-bit: if the 7th bit is 0 it is a flag; if the 7th bit is 1 it is an abort."},
            {"id": "FR-OCTSTUFF-03",   "text": "Octet stuffing (asynchronous links): control-escape octet is 0x7D. Any occurrence of 0x7E or 0x7D in payload is transmitted as 0x7D followed by the original octet with bit 5 inverted (0x7E → 0x7D 0x5E; 0x7D → 0x7D 0x5D)."},
            {"id": "FR-ABORT-04",      "text": "An ABORT sequence is at least 7 consecutive 1-bits without a 0-bit. On synchronous links this is signalled in-frame; on asynchronous links the sequence 0x7D 0x7E ends a packet with an incomplete byte-stuff sequence."},
            {"id": "FR-IDLE-05",       "text": "An idle line is continuous 1-bits OR continuous flag bytes 0x7E."},
            {"id": "FR-FRAME-06",      "text": "Frame structure (between flags): Address (1+ octets) → Control (1 or 2 octets) → Information (0..N octets) → FCS (2 or 4 octets)."},
            {"id": "FR-CONTROL-07",    "text": "Control field encodes the frame type: low-bit = 0 → I-frame; low-2-bits = 01 → S-frame; low-2-bits = 11 → U-frame. Normal control = 1 byte; extended control = 2 bytes."},
            {"id": "FR-IFRAME-08",     "text": "I-frame normal control field (8 bits) = N(R)[3] | P/F[1] | N(S)[3] | 0; extended (16 bits) = N(R)[7] | P/F[1] | N(S)[7] | 0."},
            {"id": "FR-SFRAME-09",     "text": "S-frame normal control field = N(R)[3] | P/F[1] | type[2] | 01; type encoding 00=RR (Receive Ready), 01=REJ (Reject), 10=RNR (Receive Not Ready), 11=SREJ (Selective Reject). Extended = N(R)[7] | P/F[1] | 0000 | type[2] | 01."},
            {"id": "FR-UFRAME-10",     "text": "U-frame control field (8 bits) = M[3] | P/F[1] | M[2] | 11. The five M-bits select one of up to 32 U-frame subtypes (SABM/SABME/DISC/UA/DM/FRMR/UI/UIH/UP/SNRM/SARM/SARME/SNRME/RSET/XID/TEST/SM/SIM/RIM/RD/NR0..NR3/AC0/AC1/CFGR/BCN)."},
            {"id": "FR-NS-11",         "text": "N(S) send sequence number is incremented modulo 8 (normal) or modulo 128 (extended) for each successive I-frame transmitted; up to 7 (or 127) I-frames may be outstanding awaiting acknowledgment."},
            {"id": "FR-NR-12",         "text": "N(R) receive sequence number acknowledges all I-frames with N(S) up to N(R)-1 (modulo 8 or 128) have been received; N(R) is the next N(S) expected. Carried in every I and S frame."},
            {"id": "FR-PF-13",         "text": "P/F (Poll/Final) bit is a single bit token: Poll when set in a command (primary solicits a response), Final when set in a response (secondary signals end of transmission). Only one P/F token may exist at a time on the link. Central to checkpoint retransmission."},
            {"id": "FR-FCS-14",        "text": "Frame Check Sequence covers Address + Control + Information. Default: 16-bit CRC-CCITT, polynomial 0x1021 (X^16 + X^12 + X^5 + 1), initial value 0xFFFF, transmitted with bits inverted, residue 0x1D0F. Optional 32-bit CRC-32 (IEEE 802.3 polynomial 0x04C11DB7) selectable as a functional extension."},
            {"id": "FR-MODESET-15",    "text": "A station enters operational mode upon successful mode-set handshake: command SNRM/SARM/SABM (or extended SNRME/SARME/SABME) → response UA. If the command is unacceptable the secondary responds DM or FRMR. Mode-set establishes 3-bit (normal) or 7-bit (extended) sequence numbering."},
            {"id": "FR-DISC-16",       "text": "DISC (Disconnect) command terminates the logical link; secondary acknowledges with UA and enters disconnected mode. Any unacknowledged I-frames are lost."},
            {"id": "FR-FRMR-17",       "text": "FRMR (Frame Reject) response is sent on an unrecoverable error (invalid control field, information field in S-frame, invalid N(R), I-frame too large). Cleared only by a subsequent mode-set or RSET command."},
            {"id": "FR-CHKPT-18",      "text": "Checkpoint retransmission: when a station receives a P/F bit, it may assume that any frames it sent before its last P/F transmission and not yet acknowledged will never arrive, and so must be retransmitted."},
            {"id": "FR-WINDOW-19",     "text": "Sliding-window flow control: outstanding-frame limit = 2^(sequence-number bits) - 1 = 7 (mod-8) or 127 (mod-128). RR cancels prior RNR; RNR throttles peer; REJ requests retransmission starting at N(R); SREJ (optional) requests retransmission of only N(R)."},
            {"id": "FR-LSB-20",        "text": "Bits within an octet are transmitted LSB first; this applies to the Control field encoding rows shown in the standard (rightmost bit transmitted first)."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "FCS mismatch — silently discard frame and either send REJ/SREJ negative acknowledgement or rely on timer-driven retransmission.",
            "Abort sequence (7 consecutive 1-bits) — discard the frame in progress and resume on the next flag.",
            "Invalid N(R) (outside acknowledged-frame window) — respond FRMR with Z error flag set.",
            "Invalid N(S) (outside receive window) — respond REJ (go-back-N) or SREJ (selective reject).",
            "Information field present in an S-frame, or in a U-frame that does not allow an information field — respond FRMR with X error flag set.",
            "Information field larger than secondary can accept — respond FRMR with Y error flag set.",
            "Unimplemented or undefined frame type — respond FRMR with W error flag set.",
            "Invalid send sequence number — respond FRMR with V error flag (only possible if transmit window size smaller than maximum negotiated).",
            "Frame check sequence error and link timeout — sender retransmits unacknowledged frame after T1 timer expiry.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Frame MUST be delimited by 0x7E flag at start and end.",
                "Bit stuffing MUST be applied in Address + Control + Information + FCS portions on synchronous links (or octet stuffing on asynchronous links).",
                "Control field MUST encode I/S/U discriminator per the standard control-field bit pattern.",
                "FCS MUST be 16-bit CRC-CCITT (polynomial 0x1021) OR 32-bit CRC-32 (polynomial 0x04C11DB7) selected by the implementation.",
                "Sequence numbers MUST be incremented modulo 8 (normal) or modulo 128 (extended) per successive I-frame.",
                "Mode-set command MUST be acknowledged with UA (acceptance) or DM/FRMR (rejection).",
                "Bus-off-equivalent — a secondary in disconnected mode MUST respond DM to every command except an acceptable mode-set command (or alternatively FRMR).",
                "Bits within an octet MUST be transmitted least significant bit first.",
                "Minimum frame size = Flag + Address(1) + Control(1) + FCS(2) + Flag = 6 octets (8 with extended control + 4-byte FCS).",
            ]
        d.setdefault("performance_of_error_detection", [
            "16-bit CRC-CCITT detects all 1-bit, 2-bit, and odd-numbered errors in the FCS-covered region.",
            "All burst errors of length ≤ 16 bits.",
            "All bursts of length 17 bits with probability 1 - 2^-15 (≈ 1 - 0.0000305).",
            "All bursts of length 18 or longer with probability 1 - 2^-16 (≈ 1 - 0.0000153).",
            "32-bit CRC-32 extends burst-detection capability to ≤ 32 bits and reduces residual error probability proportionally.",
            "Bit-stuffing additionally enforces that the FLAG sequence 0x7E cannot appear inside a frame, providing implicit framing-boundary protection.",
        ])
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Bit-oriented synchronous data link protocol; frame-based with I/S/U frame discriminator, sliding-window sequence numbering, and link-management U-frame command/response set.")
        if _empty(d.get("opcodes")):
            d["opcodes"] = [
                {"name": "RR",    "frame_class": "S-frame",  "type_bits": "00", "direction": "C/R", "description": "Receive Ready — positive acknowledgement; cancels prior RNR; can also be used by primary with P-bit to solicit secondary status."},
                {"name": "REJ",   "frame_class": "S-frame",  "type_bits": "01", "direction": "C/R", "description": "Reject — go-back-N negative acknowledgement; requests retransmission starting at N(R)."},
                {"name": "RNR",   "frame_class": "S-frame",  "type_bits": "10", "direction": "C/R", "description": "Receive Not Ready — acknowledges packets but throttles peer until further notice."},
                {"name": "SREJ",  "frame_class": "S-frame",  "type_bits": "11", "direction": "C/R", "description": "Selective Reject — requests retransmission of only N(R); optional functional extension."},
                {"name": "SNRM",  "frame_class": "U-frame",  "M_bits": "100 00",  "direction": "C", "description": "Set Normal Response Mode (3-bit sequence numbers, 1-byte control field)."},
                {"name": "SNRME", "frame_class": "U-frame",  "M_bits": "100 11",  "direction": "C", "description": "Set Normal Response Mode Extended (7-bit sequence numbers, 2-byte control field)."},
                {"name": "SARM",  "frame_class": "U-frame",  "M_bits": "000 11",  "direction": "C", "description": "Set Asynchronous Response Mode (3-bit sequence numbers)."},
                {"name": "SARME", "frame_class": "U-frame",  "M_bits": "010 11",  "direction": "C", "description": "Set Asynchronous Response Mode Extended (7-bit sequence numbers)."},
                {"name": "SABM",  "frame_class": "U-frame",  "M_bits": "001 11",  "direction": "C", "description": "Set Asynchronous Balanced Mode (3-bit sequence numbers, peer-to-peer)."},
                {"name": "SABME", "frame_class": "U-frame",  "M_bits": "011 11",  "direction": "C", "description": "Set Asynchronous Balanced Mode Extended (7-bit sequence numbers)."},
                {"name": "SM",    "frame_class": "U-frame",  "M_bits": "110 01",  "direction": "C", "description": "Set Mode generic — new in ISO/IEC 13239; carries an information field selecting parameters including 15-/31-bit sequence numbers."},
                {"name": "SIM",   "frame_class": "U-frame",  "M_bits": "010 01",  "direction": "C", "description": "Set Initialization Mode — vendor-specific secondary initialization (e.g. firmware download)."},
                {"name": "RIM",   "frame_class": "U-frame",  "M_bits": "010 01",  "direction": "R", "description": "Request Initialization Mode — secondary requests primary to send SIM in lieu of DM."},
                {"name": "DISC",  "frame_class": "U-frame",  "M_bits": "010 00",  "direction": "C", "description": "Disconnect — terminate logical link; secondary acknowledges with UA and enters disconnected mode."},
                {"name": "RD",    "frame_class": "U-frame",  "M_bits": "010 00",  "direction": "R", "description": "Request Disconnect — secondary requests primary to send DISC."},
                {"name": "UA",    "frame_class": "U-frame",  "M_bits": "011 00",  "direction": "R", "description": "Unnumbered Acknowledge — secondary's acceptance of an acceptable mode-set or DISC command."},
                {"name": "DM",    "frame_class": "U-frame",  "M_bits": "000 11",  "direction": "R", "description": "Disconnected Mode — secondary is in disconnected state; rejects any command other than acceptable mode-set."},
                {"name": "UI",    "frame_class": "U-frame",  "M_bits": "000 00",  "direction": "C/R", "description": "Unnumbered Information — unacknowledged datagram-style data; no sequence number; loss is undetected."},
                {"name": "UIH",   "frame_class": "U-frame",  "M_bits": "111 00",  "direction": "C/R", "description": "UI with Header Check — ISO/IEC 13239 addition; FCS covers only a configurable-length header prefix."},
                {"name": "UP",    "frame_class": "U-frame",  "M_bits": "001 00",  "direction": "C", "description": "Unnumbered Poll — group polling; solicits a response from a secondary; used in SDLC."},
                {"name": "RSET",  "frame_class": "U-frame",  "M_bits": "100 01",  "direction": "C", "description": "Reset — reset secondary's receive sequence number to 0 (ABM only)."},
                {"name": "XID",   "frame_class": "U-frame",  "M_bits": "101 11",  "direction": "C/R", "description": "Exchange Identification — exchange link-level capabilities; ISO 8885 information-field format."},
                {"name": "TEST",  "frame_class": "U-frame",  "M_bits": "111 00",  "direction": "C/R", "description": "Test — ping/loopback; TEST response echoes the TEST command payload."},
                {"name": "FRMR",  "frame_class": "U-frame",  "M_bits": "100 01",  "direction": "R", "description": "Frame Reject — unrecoverable error response carrying W/X/Y/Z/V error flags."},
            ]
        d.setdefault("channels", [
            {"name": "Synchronous serial link",  "direction": "half-duplex (NRM/ARM) or full-duplex (ABM)",
             "description": "Single bit-synchronous serial channel; NRZI-encoded on the wire; bit stuffing applied between flags."},
            {"name": "Asynchronous serial link", "direction": "RS-232-style asynchronous octet stream",
             "description": "Single asynchronous octet channel (e.g. RS-232 with start/stop bits per byte); control-octet transparency via 0x7D byte stuffing."},
            {"name": "Multidrop bus (SDLC)",     "direction": "primary-driven multidrop",
             "description": "Single shared link with one primary terminal and multiple secondary terminals addressed by Address field; primary polls each secondary in turn."},
        ])
        d.setdefault("frame_types", [
            {"name": "I-frame (Information)",   "purpose": "Carries user data; includes N(S) send sequence + P/F + N(R) receive sequence (3-bit or 7-bit).", "low_bits": "0"},
            {"name": "S-frame (Supervisory)",   "purpose": "Flow + error control without information field: RR / RNR / REJ / SREJ.",                              "low_bits": "01"},
            {"name": "U-frame (Unnumbered)",    "purpose": "Link management — mode set, disconnect, frame reject, XID, TEST, UI.",                                  "low_bits": "11"},
        ])
        d.setdefault("frame_field_layout", [
            {"field": "Flag",        "size": "8 bits",   "value": "0x7E (binary 01111110)", "stuffed": False},
            {"field": "Address",     "size": "8+ bits",  "value": "1 byte (default) or extended (multi-byte; top bit = 0 means continue)", "stuffed": True},
            {"field": "Control",     "size": "8 or 16 bits", "value": "1 byte normal / 2 bytes extended; encodes I/S/U + N(S) + N(R) + P/F + U-frame M-bits", "stuffed": True},
            {"field": "Information", "size": "Variable, 8*N bits", "value": "Opaque payload (0..N bytes); present in I-frames and some U-frames (UI/UIH/XID/TEST/SM/FRMR); ABSENT in S-frames", "stuffed": True},
            {"field": "FCS",         "size": "16 or 32 bits", "value": "CRC-CCITT (poly 0x1021, init 0xFFFF) — 16 bits default; or CRC-32 (poly 0x04C11DB7) — 32 bits optional", "stuffed": True},
            {"field": "Flag",        "size": "8 bits",   "value": "0x7E", "stuffed": False},
        ])
        d.setdefault("control_field_encoding", {
            "normal_8bit": {
                "I-frame":  "bit7..bit0 = N(R)[2:0] | P/F | N(S)[2:0] | 0",
                "S-frame":  "bit7..bit0 = N(R)[2:0] | P/F | type[1:0] | 01",
                "U-frame":  "bit7..bit0 = M[4:2] | P/F | M[1:0] | 11",
            },
            "extended_16bit": {
                "I-frame":  "bit15..bit0 = N(R)[6:0] | P/F | N(S)[6:0] | 0",
                "S-frame":  "bit15..bit0 = N(R)[6:0] | P/F | 0000 | type[1:0] | 01",
            },
            "lsb_first_note": "All control-field bits are transmitted least-significant-bit first; the I-frame discriminator is therefore the FIRST transmitted bit (a 0).",
        })
        d.setdefault("s_frame_types", [
            {"name": "RR",   "type_bits": "00", "purpose": "Receive Ready — positive ack; cancel prior RNR; primary may use with P-bit to solicit secondary status."},
            {"name": "REJ",  "type_bits": "01", "purpose": "Reject — go-back-N negative ack; sender retransmits starting at N(R)."},
            {"name": "RNR",  "type_bits": "10", "purpose": "Receive Not Ready — acknowledges but throttles peer."},
            {"name": "SREJ", "type_bits": "11", "purpose": "Selective Reject — retransmit only N(R); optional."},
        ])
        d.setdefault("u_frame_subset_minimum_required", [
            "Commands: I, RR, RNR, DISC, and one of {SNRM, SARM, SABM}.",
            "Responses: I, RR, RNR, UA, DM, FRMR.",
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no AMBA-style per-cycle VALID/READY handshake — HDLC is frame-level.",
            "Per-frame acknowledgement is piggybacked on N(R) in any I or S frame.",
            "Flow control via RR (resume) / RNR (pause) / REJ (go-back-N retransmit) / SREJ (selective retransmit).",
            "Mode-set commands are acknowledged with UA (acceptance) or DM/FRMR (rejection).",
            "P/F bit serves as a checkpoint token — only one in flight on the link at a time.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented_within_information_field", True)
        d.setdefault("byte_order_within_information_field", "LSB-first within each octet on the wire; multi-octet field byte-order is implementation-defined.")
        d.setdefault("interframe_state", {
            "idle":          "Continuous 1-bits OR continuous 0x7E flag bytes.",
            "abort":         "Seven or more consecutive 1-bits without a 0-bit (synchronous); 0x7D 0x7E (asynchronous incomplete byte-stuff).",
            "frame_sharing": "End-flag of one frame MAY be shared as start-flag of next (single shared 0x7E).",
        })
        _write(p, d)

    # L4 wire-level — no register map
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "HDLC / SDLC is a wire-level data link protocol specification "
            "(ISO/IEC 13239), not a peripheral block guide. There is no "
            "architectural register map at the protocol layer. Concrete "
            "HDLC controller IP blocks (e.g. Zilog Z85C30 SCC, Intel 82530, "
            "Motorola MC68302 SCP, Infineon DS28E15, Altera Avalon-ST HDLC, "
            "Xilinx LogiCORE HDLC) define their own register file "
            "(typically: mode/control / status / receive-FIFO / transmit-"
            "FIFO / address-filter / sequence-number / FCS-error-count / "
            "interrupt-mask registers) at the SoC integration level — "
            "covered by individual block guides, not by ISO/IEC 13239.")
        _write(p, d)

    # L5 — overwrite signaling
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "HDLC / SDLC is a logical / data-link protocol specification "
            "— physical signal levels are intentionally not defined to "
            "allow implementation flexibility (V.24/RS-232, V.35, V.42, "
            "X.21, RS-422, fiber, etc.). On synchronous links bits are "
            "typically NRZI-encoded (a 0-bit causes a signal-level change; "
            "a 1-bit no change), providing clock recovery via signal "
            "transitions enforced by bit stuffing. On asynchronous links "
            "(RS-232 style), the protocol uses NRZ encoding with the byte "
            "stream surrounded by start/stop bits per octet, and octet "
            "stuffing replaces in-frame escaping. Idle line is signalled "
            "by continuous 1-bits or continuous 0x7E flag bytes.")
        _write(p, d)

    # L6 control logic
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("operational_states", [
            {"name": "Disconnected (DM)",                "description": "Initial / power-up state; secondary responds DM to any command except an acceptable mode-set."},
            {"name": "Initialization (SIM/RIM)",         "description": "Optional vendor-specific initialization (e.g. firmware download); entered via SIM command, requested via RIM response."},
            {"name": "Normal Response Mode (NRM)",       "description": "Unbalanced; primary polls each secondary; secondary transmits only on poll. Half-duplex friendly."},
            {"name": "Asynchronous Response Mode (ARM)", "description": "Unbalanced; secondary may transmit at any time; primary still owns initialization + error recovery + disconnect."},
            {"name": "Asynchronous Balanced Mode (ABM)", "description": "Balanced; both stations are combined terminals (peer); full-duplex point-to-point."},
            {"name": "Frame-reject (FRMR)",              "description": "Unrecoverable error condition; station repeats FRMR until cleared by mode-set or RSET."},
        ])
        d.setdefault("fsm_hints_transmitter", [
            {"name": "TX_IDLE",       "description": "Output continuous 1-bits or 0x7E flags; wait for command from upper layer."},
            {"name": "TX_OPEN_FLAG",  "description": "Drive opening 0x7E flag (suspend bit stuffing for the flag itself)."},
            {"name": "TX_ADDRESS",    "description": "Drive Address octet(s) with bit stuffing engaged."},
            {"name": "TX_CONTROL",    "description": "Drive Control octet (1 byte normal / 2 bytes extended); encode I/S/U + N(S) + N(R) + P/F."},
            {"name": "TX_INFO",       "description": "Drive Information octet(s) (only for I, UI, UIH, XID, TEST, SM, FRMR) with bit stuffing engaged."},
            {"name": "TX_FCS",        "description": "Drive 16-bit CRC-CCITT (or 32-bit CRC-32) over Address+Control+Information with bit stuffing engaged."},
            {"name": "TX_CLOSE_FLAG", "description": "Drive closing 0x7E flag; may be shared as next opening flag if back-to-back transmission."},
            {"name": "TX_ABORT",      "description": "If aborting in-flight frame, drive 7 or more consecutive 1-bits."},
        ])
        d.setdefault("fsm_hints_receiver", [
            {"name": "RX_HUNT",        "description": "Search for opening 0x7E flag pattern in incoming bit stream."},
            {"name": "RX_FLAG_LOCKED", "description": "Flag found; begin frame de-stuffing (strip 0 after 5 ones)."},
            {"name": "RX_ADDRESS",     "description": "Collect Address octet(s); if extended addressing, continue while top bit = 0."},
            {"name": "RX_CONTROL",     "description": "Collect Control octet(s); decode I/S/U discriminator + N(S)/N(R)/P/F/M-bits."},
            {"name": "RX_INFO",        "description": "Collect Information octets (variable length) until closing flag detected."},
            {"name": "RX_FCS_CHECK",   "description": "Validate FCS residue; CRC-CCITT residue = 0x1D0F; CRC-32 residue = 0xC704DD7B (or 0 depending on convention)."},
            {"name": "RX_ABORT",       "description": "On 7+ consecutive 1-bits, abort frame in progress and return to RX_HUNT."},
            {"name": "RX_DELIVER",     "description": "On successful FCS, deliver decoded frame (I-frame payload → upper layer; S/U-frame → state machine)."},
        ])
        d.setdefault("synchronization_rules", [
            "Synchronous links — receiver clock is recovered from bit transitions; bit stuffing guarantees a transition every 6 bit times within frame body and every 7 bit times during continuous flag idle.",
            "Asynchronous links — receiver re-syncs per octet via start/stop bits; bit stuffing is replaced by octet stuffing.",
            "Bit stuffing is logically transparent: stuffing and de-stuffing operate on the Address+Control+Information+FCS region only — flags themselves are NEVER stuffed.",
            "Frame boundary: opening flag and closing flag are the SAME 0x7E pattern; they MAY share a single octet between back-to-back frames.",
        ])
        d.setdefault("arbitration_rule",
            "No bus arbitration at the protocol layer — HDLC is point-to-point (NRM/ARM unbalanced or ABM balanced) or polled multidrop (SDLC NRM). In SDLC NRM, the primary's poll explicitly grants the secondary permission to transmit (poll token).")
        d.setdefault("anti_deadlock_rule",
            "P/F bit is a single-token mechanism — only one poll/final token may be in flight at a time. If a primary's P-bit response does not arrive within timeout T1, the primary times out and re-sends P. In ABM, each combined station maintains its own independent P/F checkpoint cycle.")
        d.setdefault("exit_from_reset_or_disconnected",
            "On power-up the secondary is in disconnected mode (DM). The primary issues SNRM/SARM/SABM (or SNRME/SARME/SABME for extended numbering); secondary responds UA on acceptance and enters the requested operational mode with N(S)=N(R)=0. RSET command (ABM only) resets receive sequence number to 0 without re-establishing the link.")
        d.setdefault("default_signal_state_when_link_idle",
            "Continuous 1-bits OR continuous 0x7E flag bytes; receiver remains in RX_HUNT.")
        d.setdefault("checkpoint_retransmission_rule",
            "When a station receives a P/F bit, it may assume any unacknowledged frames it had sent before its last P/F transmission will never arrive and so must be retransmitted; this is the core retransmission mechanism that all variants (REJ, SREJ, etc.) merely optimize.")
        d.setdefault("go_back_n_vs_selective", {
            "go_back_n":       "REJ — receiver requests retransmission of N(R) and all subsequent frames; transmitter discards N(S)<N(R) acks and resumes from N(R).",
            "selective_reject":"SREJ — receiver requests retransmission of only N(R); transmitter retransmits only the explicitly-requested frame; SREJ is optional (not all variants support it).",
        })
        _write(p, d)

    # L7 test/debug
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "FCS error count",        "purpose": "Counts FCS-mismatch frames; used by upper-layer keepalive / link-quality monitoring."},
            {"name": "Abort sequence count",   "purpose": "Counts frames aborted via 7+ consecutive 1-bits (transmitter-side abort)."},
            {"name": "FRMR response",          "purpose": "Standardized error-flag (W/X/Y/Z/V) response carrying the rejected control field + send/receive sequence numbers."},
            {"name": "XID exchange",           "purpose": "Peer discovery / capability exchange before mode-set; ISO 8885 information-field format."},
            {"name": "TEST frame loopback",    "purpose": "Ping-equivalent for link-level diagnostics; TEST response echoes the TEST command information field."},
            {"name": "BCN (Beacon) response",  "purpose": "SDLC-era unidirectional-fault localization — secondary that has not received any frames for a long time begins emitting a stream of BCN responses."},
        ])
        d.setdefault("self_check_mechanisms", [
            "Frame Check Sequence — 16-bit CRC-CCITT (poly 0x1021) over Address+Control+Information; optional 32-bit CRC-32 (poly 0x04C11DB7).",
            "Bit Stuffing — receiver-side de-stuffing detects framing errors (e.g. 6 consecutive 1-bits + 0 = flag; 6 consecutive 1-bits + 1 = error/abort).",
            "Sequence number checking — N(S) out of receive window → REJ; N(R) outside ack window → FRMR (Z flag).",
            "Frame-type validity — invalid control field, info field in S-frame, info field too large → FRMR (W/X/Y flags).",
            "FRMR error flags W/X/Y/Z/V — encoded in FRMR response information field for diagnosis.",
        ])
        d.setdefault("frmr_error_flag_meanings", [
            {"flag": "W", "meaning": "Frame type (control field) is not understood or not implemented."},
            {"flag": "X", "meaning": "Frame type is not understood with a non-empty information field, but one was present."},
            {"flag": "Y", "meaning": "Frame included an information field larger than secondary can accept."},
            {"flag": "Z", "meaning": "Frame included an invalid receive sequence number N(R), one which is not between the previously received value and the highest N(S) transmitted. Cleared only by SENDING RSET."},
            {"flag": "V", "meaning": "Frame included an invalid send sequence number N(S), greater than last-acknowledged + transmit-window-size. Only possible if transmit window size smaller than maximum negotiated."},
        ])
        d.setdefault("frmr_payload_format",
            "FRMR information field: byte 0..1 = copy of rejected control field (1 or 2 bytes); byte 2..3 = secondary's current send + receive sequence numbers (+ command/response indicator in balanced mode); byte 4..5 = W/X/Y/Z/V error flags padded with 0-bits to byte boundary. HDLC permits frames not a multiple of a byte but FRMR is typically padded.")
        d.setdefault("test_commands", [
            {"name": "XID",  "purpose": "Exchange Identification — primary advertises capabilities in XID command; secondary responds with its own capabilities in XID response. Used before mode-set."},
            {"name": "TEST", "purpose": "Data-link ping — TEST command information field is echoed in TEST response; allows round-trip diagnosis without entering operational mode."},
        ])
        d.setdefault("notes",
            "ISO/IEC 13239 does not specify scan / JTAG / BIST. Built-in protocol-level self-checking (CRC + bit-stuffing detection + sequence-number checking + frame-type validity + FRMR error flags + XID/TEST debug commands) provides a self-checking link layer. SoC-integrated HDLC controller IP (Zilog SCC, Motorola QUICC, Infineon, Xilinx LogiCORE) adds standard scan insertion at the integrator level.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "FLAG_WIDTH_bits": 8,
                "FLAG_VALUE_hex": "0x7E",
                "FLAG_VALUE_binary": "01111110",
                "ADDRESS_WIDTH_BASIC_bits": 8,
                "ADDRESS_EXTENDED_unit_bits": 8,
                "ADDRESS_EXTENDED_continuation_bit_rule": "top bit = 0 means 'address continues into next byte'; top bit = 1 means 'last address byte'",
                "CONTROL_WIDTH_NORMAL_bits": 8,
                "CONTROL_WIDTH_EXTENDED_bits": 16,
                "NS_WIDTH_NORMAL_bits": 3,
                "NR_WIDTH_NORMAL_bits": 3,
                "NS_WIDTH_EXTENDED_bits": 7,
                "NR_WIDTH_EXTENDED_bits": 7,
                "NS_MODULO_NORMAL": 8,
                "NS_MODULO_EXTENDED": 128,
                "WINDOW_SIZE_MAX_NORMAL": 7,
                "WINDOW_SIZE_MAX_EXTENDED": 127,
                "PF_BIT_WIDTH": 1,
                "S_FRAME_TYPE_FIELD_WIDTH_bits": 2,
                "U_FRAME_M_FIELD_WIDTH_bits": 5,
                "INFORMATION_FIELD_UNIT_bits": 8,
                "INFORMATION_FIELD_LENGTH_BITS": "variable, typically 8 * N (where N is implementation-defined)",
                "FCS_WIDTH_CRC_CCITT_bits": 16,
                "FCS_WIDTH_CRC_32_bits": 32,
                "ABORT_SEQUENCE_MIN_consecutive_1_bits": 7,
                "BIT_STUFF_THRESHOLD_consecutive_1_bits": 5,
                "MINIMUM_FRAME_SIZE_bytes": 6,
                "MINIMUM_FRAME_SIZE_with_extended_control_and_CRC32_bytes": 10,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("fcs_polynomial_default_crc_ccitt", {
            "name": "CRC-CCITT (X.25 / V.41)",
            "polynomial": "X^16 + X^12 + X^5 + 1",
            "hex_polynomial_value": "0x1021",
            "polynomial_width_bits": 16,
            "initial_register_value": "0xFFFF",
            "transmit_output_inversion": True,
            "residue_on_correct_receive_hex": "0x1D0F",
            "coverage": "Address + Control + Information (NOT Flag, NOT stuffed bits, NOT FCS itself)",
        })
        d.setdefault("fcs_polynomial_optional_crc_32", {
            "name": "CRC-32 (IEEE 802.3 / Ethernet)",
            "polynomial": "X^32 + X^26 + X^23 + X^22 + X^16 + X^12 + X^11 + X^10 + X^8 + X^7 + X^5 + X^4 + X^2 + X + 1",
            "hex_polynomial_value": "0x04C11DB7",
            "polynomial_width_bits": 32,
            "initial_register_value": "0xFFFFFFFF",
            "transmit_output_inversion": True,
            "residue_on_correct_receive_hex": "0xC704DD7B (or 0 by post-inversion convention)",
            "coverage": "Address + Control + Information",
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "flag_byte": "0x7E (binary 01111110)",
            "escape_byte_asynchronous": "0x7D (binary 01111101)",
            "escape_xor_mask_asynchronous": "0x20 (toggles bit 5; e.g. 0x7E ^ 0x20 = 0x5E, 0x7D ^ 0x20 = 0x5D)",
            "bit_stuff_pattern": "after 5 consecutive 1-bits in Address/Control/Information/FCS region, insert one 0-bit",
            "bit_destuff_pattern": "after 5 consecutive 1-bits, strip the following 0-bit; if 7th bit is 1 → abort/error; if 7th bit is 0 → flag",
            "abort_sequence_bits": ">=7 consecutive 1-bits without a 0-bit",
            "idle_pattern": "continuous 1-bits OR continuous 0x7E flag bytes",
            "wire_bit_order": "LSB first within each octet",
            "iframe_discriminator_bit": "low-bit of control field = 0",
            "sframe_discriminator_bits": "low-two-bits of control field = 01",
            "uframe_discriminator_bits": "low-two-bits of control field = 11",
            "modulo_8_window_size": 7,
            "modulo_128_window_size": 127,
        })
        d.setdefault("control_field_bit_layout_normal_8bit", {
            "I-frame":  {"bit7-bit5": "N(R)[2:0]", "bit4": "P/F", "bit3-bit1": "N(S)[2:0]", "bit0": "0"},
            "S-frame":  {"bit7-bit5": "N(R)[2:0]", "bit4": "P/F", "bit3-bit2": "type[1:0]", "bit1": "0", "bit0": "1"},
            "U-frame":  {"bit7-bit5": "M[4:2]",     "bit4": "P/F", "bit3-bit2": "M[1:0]",     "bit1": "1", "bit0": "1"},
        })
        d.setdefault("control_field_bit_layout_extended_16bit", {
            "I-frame":  {"bit15-bit9": "N(R)[6:0]", "bit8": "P/F", "bit7-bit1": "N(S)[6:0]", "bit0": "0"},
            "S-frame":  {"bit15-bit9": "N(R)[6:0]", "bit8": "P/F", "bit7-bit4": "0000",      "bit3-bit2": "type[1:0]", "bit1": "0", "bit0": "1"},
        })
        d.setdefault("s_frame_type_encoding", {
            "RR":   "00 (0x00 in type-field bit-order)",
            "REJ":  "01 (0x08)",
            "RNR":  "10 (0x04)",
            "SREJ": "11 (0x0C)",
        })
        d.setdefault("u_frame_encoding_table_note",
            "U-frame encoding splits 5 M-bits across bit7-bit5 (M[4:2]) and bit3-bit2 (M[1:0]). The standard tabulates 32 possible encodings; ~17 are assigned (SABM/SABME/SARM/SARME/SNRM/SNRME/DISC/UA/DM/UI/UIH/UP/RSET/XID/TEST/FRMR/SM/SIM/RIM/RD plus SDLC-era NR0..NR3/AC0/AC1/CFGR/BCN).")
        d.setdefault("timer_constants_typical", {
            "T1_retransmission_timer_typical_seconds": "0.5..3 (link-rate dependent; implementation-defined)",
            "T2_acknowledgment_holdoff_timer_seconds": "0.05..0.5 (implementation-defined)",
            "T3_idle_link_keepalive_seconds":          "10..60 (implementation-defined)",
            "N1_max_information_field_bytes":          "implementation-defined; commonly 256..4096",
            "N2_max_retransmission_count":             "implementation-defined; commonly 5..10",
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("bit_timing_structure", {
            "BIT_TIME":      "1 / Bit Rate. HDLC does not constrain bit rate — common deployments: 2400 bps (asynchronous), 9.6/64/2048 kbps (synchronous V.24/V.35), 2.048 Mbps (E1), 1.544 Mbps (T1).",
            "CLOCK_RECOVERY_SYNC": "NRZI encoding + guaranteed bit-stuffing transition rule (max 6 ones followed by a stuffed 0 → at least one transition every 6 bit times within frame body; max 7 bit times during continuous flag idle).",
            "CLOCK_RECOVERY_ASYNC": "Receiver re-syncs per octet via start/stop bits (RS-232 style); not bit-stuffing dependent.",
            "SAMPLE_POINT": "Mid-bit (typical UART convention) on asynchronous; clock-recovered on synchronous; protocol does not mandate a specific within-bit sample point.",
        })
        d.setdefault("synchronization_waveform", {
            "FLAG_HUNT":     "Receiver scans incoming bit stream for the 8-bit 0x7E pattern (01111110). On match, receiver enters frame body de-stuffing.",
            "FLAG_SHARING":  "End-flag of one frame MAY be shared as start-flag of next: bit sequence '01111110 01111110' becomes '011111101111110' with the middle '0' shared (saves 1 octet on back-to-back frames).",
            "ABORT_DETECT":  "Receiver counts consecutive 1-bits within frame body; 7 or more without a 0-bit = abort, return to FLAG_HUNT.",
        })
        d.setdefault("frame_waveform", {
            "I_FRAME":     "FLAG (8b 0x7E) → ADDRESS (8+ bits, stuffed) → CONTROL (8 or 16 bits, stuffed; low-bit=0) → INFORMATION (variable, stuffed) → FCS (16 or 32 bits, stuffed) → FLAG (8b 0x7E)",
            "S_FRAME":     "FLAG → ADDRESS → CONTROL (low-bits=01, no info) → FCS → FLAG",
            "U_FRAME":     "FLAG → ADDRESS → CONTROL (low-bits=11) → INFORMATION (only for UI/UIH/XID/TEST/SM/FRMR) → FCS → FLAG",
            "ABORT":       "ARBITRARY-LENGTH partial frame → 7+ consecutive 1-bits → next FLAG (or continuous 1-idle)",
            "BACK_TO_BACK":"FLAG-shared transmission: ...FCS (frame N) → 0x7E shared flag → ADDRESS (frame N+1)...",
        })
        d.setdefault("interframe_state_waveform", {
            "IDLE_CONTINUOUS_ONES":  "Continuous 1-bit level; receiver remains in FLAG_HUNT.",
            "IDLE_CONTINUOUS_FLAGS": "Continuous repeating 0x7E pattern; both serve as link-active idle.",
            "DEAD_LINK":             "No signal / continuous 0-bits (synchronous): indicates loss of carrier; receiver loses bit-clock recovery.",
        })
        d.setdefault("synchronous_framing_continuous_waveform_initial_state_dependence",
            "When no frames are transmitted on a simplex or full-duplex synchronous link, a frame delimiter is continuously transmitted. Two continuous waveforms result depending on initial state — both have a 0-to-1 transition pattern that maintains modem clock recovery.")
        d.setdefault("asynchronous_framing_octet_stuffing_waveform", {
            "flag_octet_in_payload":   "0x7E in payload is transmitted as 0x7D 0x5E (escape octet 0x7D followed by 0x7E XOR 0x20 = 0x5E).",
            "escape_octet_in_payload": "0x7D in payload is transmitted as 0x7D 0x5D (escape octet 0x7D followed by 0x7D XOR 0x20 = 0x5D).",
            "abort_sequence":          "0x7D 0x7E ends a packet with an incomplete byte-stuff sequence (forcing receiver to detect error).",
            "other_escapable_octets":  "XON (0x11) / XOFF (0x13) MAY be escaped via the same 0x7D + (octet XOR 0x20) mechanism for in-band flow control transparency.",
        })
        d.setdefault("poll_final_waveform", {
            "Poll":          "P-bit set in command frame; primary station solicits response from secondary.",
            "Final":         "F-bit set in response frame; secondary indicates response (or end of transmission).",
            "checkpoint":    "Only one P/F token in flight per direction; arrival of P/F at a station signals that any frames it sent before its last P/F transmission and not yet acknowledged will never arrive.",
        })
        d.setdefault("max_consecutive_1bits_in_frame_body", 5)
        d.setdefault("max_consecutive_1bits_in_continuous_flag_idle", 6)
        d.setdefault("max_consecutive_1bits_before_abort", 7)
        _write(p, d)

    # L9 integration
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Bit-oriented synchronous data link protocol (OSI Layer 2) providing reliable framed data transfer between two devices over a serial link. Specification scopes frame delimitation, bit / octet stuffing, addressing, sequencing, error detection (FCS), and link-management elements of procedure; leaves physical-layer encoding and upper-layer payload semantics out of scope.")
        d.setdefault("layered_structure_summary", [
            "Application / Upper Layers — out of scope of HDLC.",
            "Network Layer (IP / X.25 PLP / CLNP) — carried opaquely in the HDLC Information field.",
            "Data Link Layer (HDLC) — frame structure (flag/address/control/info/FCS/flag) + elements of procedure (I/S/U frames, mode-set, sequence numbers, FCS).",
            "Physical Layer — out of scope (NRZI synchronous, RS-232 asynchronous, V.35, fibre, etc., chosen by integrator).",
        ])
        d.setdefault("integration_overview", {
            "topology":              "Point-to-point (most common — ABM peer-to-peer over WAN) OR multidrop (SDLC NRM with one primary + N secondaries).",
            "drive_type":            "Push-pull or differential serial driver per the physical-layer standard (V.24, V.35, RS-422, etc.).",
            "addressing":            "One-byte address field (default) or extended addressing (multi-byte; top-bit-0 = continue). In ABM the address still serves to distinguish command frames vs response frames.",
            "uniform_bit_rate":      "Both ends operate at the same nominal bit rate; clock is recovered via NRZI transitions guaranteed by bit stuffing.",
            "typical_bit_rates":     "2400 bps (V.21 modem) ... 64 kbps (V.24 ISDN B-channel) ... 2.048 Mbps (E1) ... higher in proprietary deployments.",
        })
        d.setdefault("interface_categories", [
            "Primary terminal — originates commands; polls secondaries; owns initialization and error recovery (NRM/ARM).",
            "Secondary terminal — responds to commands; transmits only when polled (NRM) or at will (ARM); never owns disconnect.",
            "Combined terminal — acts as both primary and secondary; only used in ABM (peer-to-peer).",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Point-to-point synchronous serial link (most common; PPP, X.25 LAPB, ISDN LAPD use ABM).",
            "Multidrop SDLC bus — one primary + multiple secondaries; primary polls each in turn (NRM).",
            "Asynchronous serial link with octet stuffing — RS-232-style; PPP-async uses this variant.",
            "Loop topology (SDLC) — primary + secondaries arranged in a closed loop with Go-Ahead bit relay.",
            "Mixed encoding — different segments of a WAN may use HDLC framing with different FCS sizes (16-bit ↔ 32-bit) or different control field widths (normal ↔ extended); compatibility requires explicit negotiation via XID.",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Idle link = continuous 1-bits OR continuous 0x7E flag bytes; receiver remains in FLAG_HUNT state until next opening flag is detected.")
        d.setdefault("soc_dependent_items", [
            "Physical-layer transceiver choice (RS-232 line driver, RS-422 differential driver, V.35 high-speed, optical).",
            "Crystal / oscillator selection for required bit-rate accuracy (e.g. ±100 ppm typical).",
            "FCS choice (16-bit CRC-CCITT default vs 32-bit CRC-32 for higher-error-rate links).",
            "Control-field width (normal 8-bit vs extended 16-bit) and sequence-number modulo (8 vs 128).",
            "Window size N1 / max-info-field size N2 / timer values T1 (retransmit) / T2 (ack-holdoff) / T3 (keepalive).",
            "Address-filter programming (multidrop SDLC).",
            "Interrupt routing for frame-received / FCS-error / abort / FRMR / timer-expiry events.",
            "DMA channel allocation for transmit / receive FIFOs.",
        ])
        d.setdefault("low_power_modes_summary",
            "HDLC at the protocol layer has no defined sleep/wake. Link-level idle (continuous flags) consumes per-bit-rate switching power; some controllers gate the transmitter during true idle. Disconnected mode (DM) is the protocol's logical-off state — secondary's bus drivers may be electrically off in DM.")
        _write(p, d)

    # L11 OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "HDLC / SDLC is a wire-level data link protocol spec; no "
            "OTP / fuse / configuration ROM at the protocol layer. "
            "Concrete HDLC controllers (Zilog SCC, Motorola QUICC, "
            "Infineon, Xilinx LogiCORE HDLC) may use OTP to lock the "
            "station address, FCS-polynomial selection, or default mode "
            "parameters, but this is a per-device feature, not protocol-"
            "defined.")
        _write(p, d)

    # L12 behavioral
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_link_establishment_sequence_ABM", [
            "1. Power-up: both stations in disconnected mode (DM).",
            "2. Combined Station A transmits SABM command with P=1.",
            "3. Combined Station B (if accepting) responds with UA response with F=1; transitions to ABM with N(S)=N(R)=0.",
            "4. Station A enters ABM on receipt of UA; N(S)=N(R)=0.",
            "5. Either station may now transmit I-frames; piggyback acknowledgement via N(R).",
        ])
        d.setdefault("typical_link_establishment_sequence_NRM", [
            "1. Power-up: primary and secondaries all start in DM.",
            "2. Primary transmits SNRM command (or SNRME for extended) addressed to secondary X with P=1.",
            "3. Secondary X responds UA with F=1; enters NRM; N(S)=N(R)=0.",
            "4. Primary may now poll secondary X with I- or S-frames with P=1; secondary responds with F=1 on its last response frame.",
            "5. Repeat for each secondary on the multidrop bus.",
        ])
        d.setdefault("typical_iframe_transmit_sequence", [
            "1. Upper layer queues a data buffer.",
            "2. Transmitter waits until link is in operational mode (NRM/ARM/ABM) AND outstanding-frame window has room.",
            "3. Compose frame body: Address | Control(N(R)=expected | P/F | N(S)=current_seq | 0) | Information | FCS.",
            "4. Compute 16-bit CRC-CCITT (or 32-bit CRC-32) over Address+Control+Information.",
            "5. Apply bit stuffing to Address+Control+Information+FCS region (insert 0 after 5 consecutive 1s).",
            "6. Drive opening FLAG (0x7E).",
            "7. Drive stuffed Address+Control+Information+FCS bits.",
            "8. Drive closing FLAG (0x7E) — MAY be shared as next opening FLAG.",
            "9. Increment N(S) modulo 8 (or 128).",
            "10. Start T1 retransmission timer; wait for N(R)>this_N(S) acknowledgement.",
        ])
        d.setdefault("typical_receive_sequence", [
            "1. Receiver in FLAG_HUNT: scan for 0x7E pattern.",
            "2. On flag detect, enter frame body; apply bit de-stuffing (strip 0 after 5 ones).",
            "3. On detect of 7+ consecutive 1-bits → abort; discard partial frame; return to FLAG_HUNT.",
            "4. On detect of next 0x7E → end-of-frame; validate FCS residue.",
            "5. If FCS bad → discard silently; eventually peer's REJ/SREJ or T1-expiry triggers retransmission.",
            "6. If FCS good → decode Control field:",
            "   6a. low-bit = 0 → I-frame: update peer's N(R) ack; if N(S) = expected → deliver Information to upper layer; increment local N(R); piggyback N(R) on next I/S frame; else if N(S) > expected → send REJ.",
            "   6b. low-2-bits = 01 → S-frame: process RR/RNR/REJ/SREJ flow control.",
            "   6c. low-2-bits = 11 → U-frame: process mode-set / DISC / UA / DM / FRMR / UI / XID / TEST / RSET / UP.",
            "7. If frame caused unrecoverable error → send FRMR with W/X/Y/Z/V flags set.",
        ])
        d.setdefault("abort_sequence", [
            "1. Transmitter mid-frame, decides to abort (e.g. underrun, upper-layer cancel).",
            "2. Drive 7 or more consecutive 1-bits without a 0-bit.",
            "3. Resume idle (continuous 1s or flags).",
            "4. Receiver detects 7+ consecutive 1s in frame body → discard partial frame → return to FLAG_HUNT.",
            "5. Both ends rely on T1 timer to eventually retransmit.",
        ])
        d.setdefault("frmr_sequence", [
            "1. Receiver detects unrecoverable frame error (e.g. invalid control field, info field in S-frame, info field too large, invalid N(R)).",
            "2. Transmit FRMR response with W/X/Y/Z/V error flags + copy of rejected control field + own send/receive sequence numbers.",
            "3. Repeat FRMR in response to every poll until cleared by a mode-set command (SABM/SNRM/SARM) or RSET (ABM).",
            "4. Mode-set re-establishes link with N(S)=N(R)=0.",
            "5. RSET resets only N(R) on the secondary; faster recovery than full mode-set.",
        ])
        d.setdefault("disconnect_sequence", [
            "1. One station decides to terminate link (upper-layer close / inactivity timeout).",
            "2. Transmit DISC command with P=1.",
            "3. Peer responds UA with F=1; enters DM.",
            "4. Any unacknowledged I-frames at either station are lost.",
            "5. Both stations are now in DM; further commands (except acceptable mode-set) receive DM response.",
        ])
        d.setdefault("checkpoint_retransmission_sequence", [
            "1. Station A sends I-frames N(S)=0,1,2,3 with last one P=1.",
            "2. Some frames are lost in transit.",
            "3. Station B's response with F=1 contains N(R)=2 (acks N(S)=0,1).",
            "4. Station A receives N(R)=2; knows N(S)=2,3 were lost.",
            "5. Station A retransmits N(S)=2,3 (go-back-N from N(R)).",
        ])
        d.setdefault("sliding_window_full_sequence", [
            "1. Station A's window is mod-8 with size 7.",
            "2. Station A sends N(S)=0..6 (7 outstanding frames); window now full.",
            "3. Station A must NOT transmit N(S)=7 until peer acks at least one frame.",
            "4. Peer responds with RR N(R)=3 (acks 0,1,2); window slides; A can now send N(S)=7,0,1,2 (mod-8).",
            "5. Window-slide continues as more N(R) acks arrive.",
        ])
        d.setdefault("mode_escalation_sequence_NRM_to_ABM", [
            "1. Link operational in NRM.",
            "2. Primary transmits DISC command with P=1.",
            "3. Secondary responds UA with F=1; enters DM.",
            "4. Either station (now both peers) transmits SABM with P=1.",
            "5. Other station responds UA with F=1; both enter ABM with N(S)=N(R)=0.",
        ])
        d.setdefault("asynchronous_octet_stuffing_transmit_sequence", [
            "1. Compose frame body (Address+Control+Information+FCS).",
            "2. For each octet, if octet ∈ {0x7E, 0x7D, optionally XON/XOFF}: replace with 0x7D followed by (octet XOR 0x20).",
            "3. Drive opening 0x7E flag.",
            "4. Drive stuffed octet stream.",
            "5. Drive closing 0x7E flag.",
            "6. To abort: drive 0x7D 0x7E sequence (forces incomplete byte-stuff).",
        ])
        d.setdefault("wakeup_sequence_disconnected_to_operational", [
            "1. Primary issues SNRM (NRM) or SABM (ABM) addressed to secondary.",
            "2. Secondary previously in DM transitions to requested mode.",
            "3. Secondary responds UA with F=1.",
            "4. Primary may now poll / data-transfer.",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "HDLC / SDLC is a wire-level data link protocol; no analog "
            "reference / trim / calibration loop. Bit-rate accuracy is a "
            "system-integration concern (typical ±100 ppm crystal); NRZI "
            "bit-stuffing transition guarantees and per-octet start/stop "
            "bits (asynchronous variant) substitute for any calibration "
            "loop at the protocol level.")
        _write(p, d)

    # L14 versioning
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version",
            "ISO/IEC 13239:2002 (High-Level Data Link Control procedures — consolidated edition)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "IBM SDLC (1975) — Synchronous Data Link Control, layer 2 protocol for IBM SNA. Predecessor of HDLC.",
                "ISO 3309-1979 — Frame Structure (original HDLC frame layout).",
                "ISO 4335-1979 — Elements of Procedure (frame types, sequence numbers, mode-set commands).",
                "ISO 6159-1980 — Unbalanced Classes of Procedure (NRM, ARM).",
                "ISO 6256-1981 — Balanced Classes of Procedure (ABM).",
                "ITU-T X.25 LAPB (1976+) — extended HDLC for X.25 packet-switched networks.",
                "ANSI ADCCP (1979) — essentially identical to HDLC; ANSI's parallel standardization.",
                "IEEE 802.2 LLC (1985) — adopted HDLC frame structure for LANs.",
                "PPP framing (RFC 1662, 1994) — HDLC-like framing for serial PPP.",
                "V.42 LAPM (1988) — modem error correction; HDLC-derived.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "SDLC → HDLC (ISO 3309/4335)", "summary": "Generalized IBM SDLC into a vendor-neutral ISO standard; same frame structure; broader U-frame command set."},
                {"version": "HDLC unbalanced + balanced split (ISO 6159 + 6256)", "summary": "Codified NRM/ARM (unbalanced primary-secondary) and ABM (balanced peer-to-peer) as separate classes."},
                {"version": "ISO/IEC 13239:2002 consolidation", "summary": "Replaced ISO 3309 + 4335 + 6159 + 6256 with a single revised standard. Added: SM (generic Set Mode) with parameter information field, UIH (UI with header check), 15-bit and 31-bit extended sequence numbers (selected only via SM command)."},
                {"version": "Cisco HDLC", "summary": "Cisco's proprietary variant: adds a 2-byte protocol-type field after the standard Control field to identify the upper-layer protocol (similar to PPP's PPP-protocol field)."},
                {"version": "PPP (RFC 1662)", "summary": "PPP adopts HDLC-like framing but always uses Address=0xFF (all-stations) and Control=0x03 (UI command, no sequence numbers); upper-layer PPP-protocol field follows. Asynchronous PPP uses octet stuffing."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "extended_vs_normal_control_field",
                 "normal_control":       "1 byte; sequence numbers mod-8; max 7 outstanding I-frames.",
                 "extended_control":     "2 bytes; sequence numbers mod-128; max 127 outstanding I-frames.",
                 "trap": "Normal and extended control field widths are NOT auto-negotiable on-the-fly — they are selected by the mode-set command (SNRM vs SNRME, SABM vs SABME, etc.). Mismatched assumption causes immediate decode failure."},
                {"trap_name": "fcs_size_16_vs_32",
                 "default_16bit":        "CRC-CCITT polynomial 0x1021, residue 0x1D0F.",
                 "optional_32bit":       "CRC-32 polynomial 0x04C11DB7, residue 0xC704DD7B.",
                 "trap": "FCS size MUST be agreed at link setup (typically via XID); a 32-bit FCS sender to a 16-bit FCS receiver will produce gibberish at the data-link layer."},
                {"trap_name": "asynchronous_byte_stuffing_vs_synchronous_bit_stuffing",
                 "sync_bit_stuffing":    "0-bit inserted after 5 consecutive 1-bits in frame body.",
                 "async_octet_stuffing": "0x7E and 0x7D in payload are escaped with 0x7D + (octet XOR 0x20).",
                 "trap": "PPP-async and PPP-sync both use HDLC framing but with different stuffing rules; a PPP-async-only receiver cannot decode a synchronous bit-stuffed HDLC stream and vice-versa."},
                {"trap_name": "shared_flag_octet",
                 "shared_allowed":       "Spec allows the 0-bit at the end of a closing flag to be SHARED with the start-of-next-flag: bits '011111101111110' (15 bits, not 16).",
                 "trap": "Some hardware does not support shared-flag receive and gets confused on back-to-back frames; spec text explicitly notes this incompatibility."},
                {"trap_name": "sdlc_vs_hdlc_u_frame_encodings",
                 "sdlc_specific":       "SDLC defined NR0..NR3 (Nonreserved), CFGR (Configure), BCN (Beacon), AC0/AC1 — these are NOT part of ISO/IEC 13239 HDLC.",
                 "trap": "An SDLC frame on an HDLC-only receiver will decode the U-frame M-bits as 'unknown' and trigger FRMR with W flag set."},
            ]
        f.setdefault("version_naming_history_note",
            "Bosch-style: there is no single 'manufacturer' for HDLC. ISO/IEC 13239:2002 is the current authoritative reference. PPP framing (RFC 1662) inherits HDLC frame structure but specifies its own elements of procedure (no sequence numbers, fixed Address+Control). LAPB (X.25), LAPD (ISDN Q.921), LAPF (Frame Relay Q.922), LAPM (V.42) are all HDLC variants with bespoke option sets.")
        d["fields"] = f
        _write(p, d)

    # L15 encoding tables
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("frame_structure_table", {
            "header_columns": ["Flag", "Address", "Control", "Information", "FCS", "Flag"],
            "row_widths":     ["8 bits", "8 or more bits", "8 or 16 bits", "Variable length, 8*N bits", "16 or 32 bits", "8 bits"],
            "note": "Standard HDLC frame structure from ISO/IEC 13239:2002. End-flag of one frame may be (but does not have to be) the start-flag of the next.",
        })
        f.setdefault("flag_octet_table", {
            "header_columns": ["Name", "Hex", "Binary", "Notes"],
            "rows": [
                ["Flag",  "0x7E", "01111110", "Opens and closes every HDLC frame. NEVER stuffed."],
                ["Escape (async)", "0x7D", "01111101", "Control-octet transparency escape on asynchronous links; following octet is XOR'd with 0x20."],
                ["Flag-in-payload escaped (async)",  "0x7D 0x5E", "01111101 01011110", "0x7E in payload, asynchronous variant."],
                ["Escape-in-payload escaped (async)", "0x7D 0x5D", "01111101 01011101", "0x7D in payload, asynchronous variant."],
            ],
        })
        f.setdefault("control_field_normal_8bit_table", {
            "header_columns": ["Bit 7", "Bit 6", "Bit 5", "Bit 4", "Bit 3", "Bit 2", "Bit 1", "Bit 0", "Frame Type"],
            "rows": [
                ["N(R)[2]", "N(R)[1]", "N(R)[0]", "P/F", "N(S)[2]", "N(S)[1]", "N(S)[0]", "0",   "I-frame"],
                ["N(R)[2]", "N(R)[1]", "N(R)[0]", "P/F", "type[1]", "type[0]", "0",       "1",   "S-frame"],
                ["M[4]",    "M[3]",    "M[2]",    "P/F", "M[1]",    "M[0]",    "1",       "1",   "U-frame"],
            ],
            "transmission_order_note": "Bit 0 is the FIRST bit transmitted on the wire (LSB-first).",
        })
        f.setdefault("control_field_extended_16bit_table", {
            "header_columns": ["Bit 15..9", "Bit 8", "Bit 7..1", "Bit 0", "Frame Type"],
            "rows": [
                ["N(R)[6:0]", "P/F", "N(S)[6:0]",                "0", "Extended I-frame"],
                ["N(R)[6:0]", "P/F", "0000 type[1:0] 0",          "1", "Extended S-frame"],
            ],
        })
        f.setdefault("s_frame_type_encoding_table", {
            "header_columns": ["Name", "Command/Response", "type[1:0]", "Description", "Info"],
            "rows": [
                ["RR",   "C/R", "00", "Positive Acknowledgement",                "Ready to receive I-frame N(R)"],
                ["REJ",  "C/R", "01", "Negative Acknowledgement (go-back-N)",     "Retransmit starting with N(R)"],
                ["RNR",  "C/R", "10", "Positive Acknowledgement + flow stop",    "Not ready to receive"],
                ["SREJ", "C/R", "11", "Negative Acknowledgement (selective)",     "Retransmit only N(R)"],
            ],
        })
        f.setdefault("u_frame_encoding_table", {
            "header_columns": ["Name", "Cmd/Rsp", "Description", "Info field", "Bit 7", "Bit 6", "Bit 5", "Bit 4", "Bit 3", "Bit 2", "Bit 1", "Bit 0"],
            "rows": [
                ["SNRM",  "C",    "Set Normal Response Mode",                  "Use 3-bit seq #",  "1", "0", "0", "P",   "0", "0", "1", "1"],
                ["SNRME", "C",    "Set Normal Response Mode Extended",         "Use 7-bit seq #",  "1", "1", "0", "P",   "1", "1", "1", "1"],
                ["SARM",  "C",    "Set Asynchronous Response Mode",            "Use 3-bit seq #",  "0", "0", "0", "P",   "1", "1", "1", "1"],
                ["SARME", "C",    "Set Asynchronous Response Mode Extended",   "Use 7-bit seq #",  "0", "1", "0", "P",   "1", "1", "1", "1"],
                ["SABM",  "C",    "Set Asynchronous Balanced Mode",            "Use 3-bit seq #",  "0", "0", "1", "P",   "1", "1", "1", "1"],
                ["SABME", "C",    "Set Asynchronous Balanced Mode Extended",   "Use 7-bit seq #",  "0", "1", "1", "P",   "1", "1", "1", "1"],
                ["SM",    "C",    "Set Mode (generic, new in ISO 13239)",      "Parameters in info field", "1", "1", "0", "P", "0", "0", "1", "1"],
                ["SIM",   "C",    "Set Initialization Mode",                   "",                "0", "0", "0", "P",   "0", "1", "1", "1"],
                ["RIM",   "R",    "Request Initialization Mode",               "Request for SIM",  "0", "0", "0", "F",   "0", "1", "1", "1"],
                ["DISC",  "C",    "Disconnect",                                "Future I/S frames return DM", "0", "1", "0", "P", "0", "0", "1", "1"],
                ["RD",    "R",    "Request Disconnect",                        "",                "0", "1", "0", "F",   "0", "0", "1", "1"],
                ["UA",    "R",    "Unnumbered Acknowledgement",                "",                "0", "1", "1", "F",   "0", "0", "1", "1"],
                ["DM",    "R",    "Disconnected Mode",                         "Mode set required","0", "0", "0", "F",   "1", "1", "1", "1"],
                ["UI",    "C/R", "Unnumbered Information",                     "Has a payload",    "0", "0", "0", "P/F", "0", "0", "1", "1"],
                ["UIH",   "C/R", "UI with Header Check (new in ISO 13239)",    "Header-only FCS",  "1", "1", "1", "P/F", "1", "1", "1", "1"],
                ["UP",    "C",    "Unnumbered Poll",                           "Solicit control info","0", "0", "1", "P", "0", "0", "1", "1"],
                ["RSET",  "C",    "Reset",                                     "Resets N(R) not N(S)","1", "0", "0", "P", "1", "1", "1", "1"],
                ["XID",   "C/R", "Exchange Identification",                    "Capabilities exchange","1", "0", "1", "P/F", "1", "1", "1", "1"],
                ["TEST",  "C/R", "Test",                                       "Echo for testing", "1", "1", "1", "P/F", "0", "0", "1", "1"],
                ["FRMR",  "R",    "Frame Reject",                              "Rejected control + flags","1","0","0","F","0","1","1","1"],
            ],
            "note": "U-frame M-field encodings vary slightly across HDLC variants. The above reflects ISO/IEC 13239:2002 + commonly-used SDLC-era SDLC extensions. Bit-order convention is the standard's LSB-first transmission.",
        })
        f.setdefault("fcs_polynomial_table", {
            "header_columns": ["FCS Type", "Width (bits)", "Polynomial", "Hex Value", "Init Value", "Residue"],
            "rows": [
                ["CRC-CCITT", "16", "X^16 + X^12 + X^5 + 1", "0x1021", "0xFFFF", "0x1D0F"],
                ["CRC-32",    "32", "X^32 + X^26 + X^23 + X^22 + X^16 + X^12 + X^11 + X^10 + X^8 + X^7 + X^5 + X^4 + X^2 + X + 1", "0x04C11DB7", "0xFFFFFFFF", "0xC704DD7B (or 0 depending on convention)"],
            ],
        })
        f.setdefault("p_f_bit_semantics_table", {
            "header_columns": ["Bit value", "In Command frame", "In Response frame", "Meaning"],
            "rows": [
                ["0", "no Poll",   "no Final",  "Normal data transfer; no poll/final token transferred."],
                ["1", "Poll (P)",  "Final (F)", "Primary solicits response from secondary (P); secondary signals end of response (F). Token-passing mechanism."],
            ],
        })
        f.setdefault("frmr_error_flags_table", {
            "header_columns": ["Flag", "Meaning"],
            "rows": [
                ["W", "Frame type (control field) is not understood or not implemented."],
                ["X", "Frame type is not understood with a non-empty information field, but one was present."],
                ["Y", "Frame included an information field that is larger than secondary can accept."],
                ["Z", "Frame included an invalid N(R), one not between previously-received N(R) and highest N(S) transmitted. Cleared only by SENDING RSET."],
                ["V", "Frame included an invalid N(S), greater than last-acked + transmit-window-size. Only possible if window size smaller than max negotiated."],
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Frame structure (Flag/Address/Control/Information/FCS/Flag)",
                "HDLC control fields — normal 8-bit (I-frame / S-frame / U-frame)",
                "Extended HDLC control fields — 16-bit (Extended I-frame / Extended S-frame)",
                "S-frame type encoding (RR / REJ / RNR / SREJ)",
                "U-frame binary encoding (SABM/SABME/SARM/SARME/SNRM/SNRME/SM/SIM/RIM/DISC/RD/UA/DM/UI/UIH/UP/RSET/XID/TEST/FRMR)",
                "FCS polynomial selection (CRC-CCITT / CRC-32)",
                "P/F bit semantics in command vs response",
                "FRMR error flags W/X/Y/Z/V",
            ]
        d["fields"] = f
        _write(p, d)

    # L16 compliance
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Every frame opens and closes with the 8-bit flag 0x7E (binary 01111110).",
            "Bit stuffing on synchronous links: after 5 consecutive 1-bits in Address+Control+Information+FCS region, transmitter inserts a 0-bit; receiver strips it.",
            "Octet stuffing on asynchronous links: 0x7E in payload → 0x7D 0x5E; 0x7D in payload → 0x7D 0x5D.",
            "Flags are NEVER stuffed (synchronous) and NEVER octet-stuffed (asynchronous).",
            "Abort sequence: 7 or more consecutive 1-bits (synchronous) or 0x7D 0x7E sequence (asynchronous) forces receiver to discard the in-progress frame.",
            "Idle line: continuous 1-bits OR continuous 0x7E flag bytes.",
            "Control field discriminator: low-bit = 0 → I-frame; low-2-bits = 01 → S-frame; low-2-bits = 11 → U-frame.",
            "Normal control field is 1 byte with 3-bit sequence numbers (mod-8); extended control field is 2 bytes with 7-bit sequence numbers (mod-128).",
            "I-frame carries N(S) (send seq), N(R) (receive seq / piggyback ack), and P/F bit.",
            "S-frame types: RR (00), REJ (01), RNR (10), SREJ (11); S-frames carry N(R) but NOT N(S) and do NOT include an information field.",
            "U-frame carries 5 M-bits (split bit7-bit5 + bit3-bit2) plus the P/F bit; some U-frames (UI, UIH, XID, TEST, SM, FRMR) carry an information field.",
            "FCS covers Address + Control + Information (NOT flags, NOT stuffed bits, NOT FCS itself).",
            "Default FCS: 16-bit CRC-CCITT, polynomial 0x1021, initial register 0xFFFF, output inverted, residue 0x1D0F.",
            "Optional FCS: 32-bit CRC-32, polynomial 0x04C11DB7, initial register 0xFFFFFFFF.",
            "Mode-set commands (SNRM, SARM, SABM, SNRME, SARME, SABME, SM, SIM) MUST be acknowledged with UA or rejected with DM/FRMR.",
            "After acceptance of mode-set, N(S) = N(R) = 0 at both stations.",
            "Sequence numbers are incremented modulo 8 (normal) or modulo 128 (extended).",
            "Maximum outstanding I-frames: 7 (mod-8) or 127 (mod-128).",
            "P/F bit is a single-token mechanism — only one in flight per direction at a time.",
            "Bits within an octet are transmitted least-significant-bit first.",
            "FRMR response carries copy of rejected control field + send/receive sequence numbers + W/X/Y/Z/V error flags.",
        ])
        f.setdefault("must_not_have_properties", [
            "Embedding raw 0x7E in payload (synchronous: prevented by bit stuffing; asynchronous: must be octet-stuffed).",
            "Embedding raw 0x7D in payload on asynchronous links (must be octet-stuffed).",
            "Generating an information field in an S-frame.",
            "Generating an information field longer than the negotiated N1 maximum.",
            "Using N(R) outside the valid acknowledgement window.",
            "Using N(S) outside the transmit window.",
            "Transmitting in disconnected mode (DM) other than the DM response itself.",
            "Generating an N(S) increment when the outstanding-frame window is full.",
            "Using normal and extended control fields concurrently on the same link without re-mode-set.",
            "Mixing 16-bit and 32-bit FCS on the same link without XID negotiation.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "FCS_ERROR",         "trigger": "Calculated FCS residue mismatches received FCS; frame silently discarded; retransmission triggered by REJ/SREJ or T1 timer."},
            {"mode": "ABORT_DETECTED",    "trigger": "7+ consecutive 1-bits in frame body (synchronous) or 0x7D 0x7E (asynchronous); frame discarded."},
            {"mode": "UNKNOWN_FRAME_W",   "trigger": "Control field not implemented; respond FRMR with W flag set."},
            {"mode": "UNEXPECTED_INFO_X", "trigger": "Frame type does not allow info field but one was present; respond FRMR with X flag."},
            {"mode": "INFO_TOO_LARGE_Y",  "trigger": "Information field exceeds N1; respond FRMR with Y flag."},
            {"mode": "INVALID_NR_Z",      "trigger": "N(R) outside ack window; respond FRMR with Z flag; cleared only by SENDING RSET."},
            {"mode": "INVALID_NS_V",      "trigger": "N(S) outside transmit window; respond FRMR with V flag (only if window smaller than negotiated max)."},
            {"mode": "T1_TIMEOUT",        "trigger": "Retransmission timer expires; transmitter retransmits unacknowledged frames; after N2 retries link is declared down."},
            {"mode": "INVALID_NS_GAP",    "trigger": "Receiver detects gap in N(S) (e.g. expected 2, received 3); responds REJ N(R)=2 (go-back-N) or SREJ N(R)=2 (selective)."},
        ])
        f.setdefault("performance_of_error_detection", [
            "CRC-CCITT detects 100 % of 1-bit and 2-bit errors in the FCS-covered region.",
            "CRC-CCITT detects 100 % of all odd-bit errors.",
            "CRC-CCITT detects 100 % of all burst errors of length ≤ 16 bits.",
            "CRC-CCITT detects burst errors of length 17 with probability 1 − 2^-15 ≈ 0.99997.",
            "CRC-CCITT detects burst errors of length ≥ 18 with probability 1 − 2^-16 ≈ 0.99998.",
            "CRC-32 extends burst-detection to length ≤ 32 bits and reduces residual error probability by ~2^16 relative to CRC-CCITT.",
            "Bit-stuffing additionally enforces that the FLAG 0x7E cannot appear inside a frame body, providing implicit framing-boundary protection.",
        ])
        f.setdefault("recovery_time_bound",
            "Bounded by min(T1 retransmission timer, peer's REJ/SREJ response time). Typically T1 = 0.5..3 s on V.24 / V.35 links; on multi-megabit synchronous links T1 may be tens of milliseconds.")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {
                "name": "Synchronous serial link (NRZI)",
                "direction": "half-duplex (NRM/ARM) or full-duplex (ABM)",
                "purpose": "Single bit-synchronous serial channel carrying NRZI-encoded bit stream with bit stuffing for transparency and clock-recovery transition guarantee.",
                "physical_realization": "Typical: V.24/RS-232 (low-speed), V.35 (medium-speed), V.36/V.10/V.11 differential, E1/T1 carrier (DS0 or full E1 framing). Spec leaves PHY unspecified.",
            },
            {
                "name": "Asynchronous serial link (RS-232 style)",
                "direction": "full-duplex",
                "purpose": "Single asynchronous octet stream carrying NRZ-encoded bytes with octet stuffing for control-octet transparency.",
                "physical_realization": "Typical: RS-232 (V.24/V.28); used by PPP-async, V.42 LAPM, and HDLC over modem dial-up.",
            },
            {
                "name": "Multidrop bus (SDLC)",
                "direction": "primary-driven multidrop",
                "purpose": "Single shared synchronous link with one primary terminal and N secondaries, addressed by Address field.",
                "physical_realization": "Typical: RS-485 or current-loop multidrop in IBM SNA deployments.",
            },
        ]
        f["logical_signal_states"] = [
            {"name": "Flag",              "value": "0x7E (01111110)", "rule": "Opens and closes every frame; never appears within frame body (synchronous: bit stuffing prevents it; asynchronous: octet stuffing prevents it)."},
            {"name": "Idle line",         "value": "continuous 1s OR continuous 0x7E", "rule": "Receiver remains in FLAG_HUNT until next opening flag."},
            {"name": "Abort sequence",    "value": "7+ consecutive 1-bits", "rule": "Forces receiver to discard in-progress frame and return to FLAG_HUNT."},
            {"name": "Escape octet (async)", "value": "0x7D (01111101)", "rule": "Asynchronous control-octet transparency; following octet is XOR'd with 0x20."},
        ]
        f["frame_fields_as_signal_segments"] = [
            {"name": "FLAG",          "type": "delimiter",    "form": "8 bits = 0x7E"},
            {"name": "ADDRESS",       "type": "address",      "form": "8+ bits; top-bit-0 means continue"},
            {"name": "CONTROL",       "type": "control",      "form": "8 or 16 bits; encodes I/S/U + N(S)/N(R) + P/F + M-bits"},
            {"name": "INFORMATION",   "type": "payload",      "form": "Variable, 8*N bits; present in I, UI, UIH, XID, TEST, SM, FRMR"},
            {"name": "FCS",           "type": "integrity",    "form": "16 or 32 bits; CRC-CCITT default, CRC-32 optional"},
            {"name": "FLAG",          "type": "delimiter",    "form": "8 bits = 0x7E; MAY be shared with next opening flag"},
            {"name": "IDLE",          "type": "interframe",   "form": "continuous 1s or continuous 0x7E"},
            {"name": "ABORT",         "type": "error signal", "form": "7+ consecutive 1-bits"},
        ]
        f["channel_counts"] = {
            "logical_channels": 1,
            "flag_octet_count": 1,
            "frame_field_count": 5,
            "frame_types": 3,
            "s_frame_subtypes": 4,
            "u_frame_subtypes_max": 32,
            "control_field_widths_supported": 2,
            "fcs_widths_supported": 2,
            "sequence_number_moduli_supported": 2,
            "operational_modes": 3,
        }
        # Force-overwrite dependency_graph (earlier steps may have written
        # AXI-leaning content; HDLC shape is single serial channel with
        # bit stuffing + flag delimitation).
        f["dependency_graph"] = {
            "common_rule": "Single serial channel: sender drives one bit at a time; receiver de-stuffs and decodes; frame boundary is the 0x7E flag.",
            "data_dependency": "FCS depends on (Address + Control + Information). Bit stuffing depends on (last 5 transmitted bits being all 1). N(S) depends on local transmit counter. N(R) depends on local receive counter.",
            "ack_dependency":  "Acknowledgement of I-frame N(S)=k delivered via peer's later N(R)=k+1 (mod-8/128) piggybacked on any I or S frame.",
        }
        f["handshake_pairs"] = [
            {"name": "MODE_SET",           "from": "primary (or initiator)", "to": "secondary (or peer)", "rule": "SNRM/SARM/SABM (+E variants) command → UA response (accept) or DM/FRMR (reject)."},
            {"name": "PIGGYBACK_ACK",      "from": "receiver",               "to": "transmitter",         "rule": "N(R) field of any I or S frame acknowledges all I-frames with N(S) < N(R) (mod-8/128)."},
            {"name": "POLL_FINAL_TOKEN",   "from": "command issuer",         "to": "response issuer",     "rule": "P-bit set in command solicits response; F-bit set in response signals end-of-response; only one token in flight."},
            {"name": "GO_BACK_N_RETRANS",  "from": "receiver",               "to": "transmitter",         "rule": "REJ N(R)=k requests retransmission of N(S)=k and all subsequent."},
            {"name": "SELECTIVE_RETRANS",  "from": "receiver",               "to": "transmitter",         "rule": "SREJ N(R)=k requests retransmission of ONLY N(S)=k; optional."},
            {"name": "FLOW_CONTROL_STOP",  "from": "receiver",               "to": "transmitter",         "rule": "RNR pauses transmitter; cleared by next RR."},
            {"name": "DISCONNECT",         "from": "either end",             "to": "peer",                "rule": "DISC command → UA response; both enter DM."},
        ]
        f.setdefault("ordering_rules", {
            "within_a_byte":     "Least-significant bit transmitted first within each octet.",
            "frame_field_order": "Flag → Address → Control → Information → FCS → Flag.",
            "global_ordering":   "Frames serialised on the wire; N(S) gives application-level ordering within a station's transmit stream; receiver delivers in N(S) order (go-back-N) or holds out-of-order (selective reject buffer).",
        })
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Point-to-point or multidrop bit-synchronous serial data link; bit-oriented framing with sequence-number-based reliable delivery and sliding-window flow control."
        f["supported_topologies"] = [
            {"name": "Point-to-point ABM (most common)", "description": "Two combined stations exchange data peer-to-peer; full-duplex; used by PPP, X.25 LAPB, ISDN LAPD, V.42 LAPM, Frame Relay LAPF."},
            {"name": "Point-to-point NRM/ARM",          "description": "One primary terminal + one secondary terminal; unbalanced; used in older wide-area deployments and modem-controlled links."},
            {"name": "Multidrop NRM (SDLC)",            "description": "One primary + multiple secondaries on a shared bus; primary polls each in turn using SDLC Go-Ahead bit or modern selective addressing."},
            {"name": "Loop topology (SDLC)",            "description": "Primary + secondaries arranged in a closed loop; messages relay via Go-Ahead bit; rarely used in modern deployments."},
            {"name": "Asynchronous serial (PPP-async)", "description": "Point-to-point asynchronous RS-232 link with octet stuffing; PPP-async is the most prevalent example."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Primary terminal",     "description": "Originates commands; polls secondaries; owns initialization, error recovery, and disconnect (NRM/ARM)."},
            {"role": "Secondary terminal",   "description": "Responds to commands from the primary; transmits only when polled (NRM) or at will (ARM); never owns disconnect."},
            {"role": "Combined terminal",    "description": "Acts as both primary and secondary; used only in ABM (peer-to-peer)."},
            {"role": "Error-recovery owner", "description": "Primary in NRM/ARM; either combined terminal in ABM."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer interconnect (no router or bridge). "
            "HDLC operates at the data link layer between two adjacent "
            "stations on a single physical link. Multi-hop routing is the "
            "responsibility of the network layer (X.25 PLP, IP, etc.) and "
            "is carried opaquely inside the HDLC Information field.")
        f["ordering_guarantees"] = {
            "single_link":   "Bits are transmitted in strict order; receiver reconstructs the bit stream and recovers the frame boundary via FLAG_HUNT.",
            "frame_level":   "N(S) provides per-frame ordering within a station's transmit stream; N(R) provides cumulative acknowledgement of received I-frames.",
            "delivery_mode": "Reliable in-order delivery in NRM/ARM/ABM (sequence-number checking + retransmission); unreliable datagram delivery for UI/UIH (no sequence numbers).",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — HDLC is wire-level. Per-controller transmit/receive FIFO/DMA, address-filter, and sequence-counter register maps live in the SoC integration spec.")
        f.setdefault("slave_classification", {
            "addressable_target":   "Secondary in NRM/ARM (multidrop SDLC) or peer in ABM. Address field provides destination addressing on multidrop bus.",
            "data_producer":        "Any operational station may transmit I-frames or UI/UIH datagrams; primary in NRM only transmits when initiating; secondary in NRM only transmits in response to poll.",
            "data_consumer":        "Any station receives every frame on the wire and applies address-filter to determine if frame is for it.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Frame structure table — Flag/Address/Control/Information/FCS/Flag",
            "Control field bit layout — normal 8-bit + extended 16-bit",
            "U-frame binary encoding table — 32 possible M-bit combinations",
            "FCS polynomial table — 16-bit CRC-CCITT default, 32-bit CRC-32 optional",
        ])
        f.setdefault("multidrop_addressing_topology", {
            "addressing_mode":      "Address field carries secondary's address; 1 byte default (256 secondaries) or extended (multiple bytes, top-bit-0 means continue).",
            "broadcast_address":    "Implementation-defined; SDLC commonly uses 0xFF as group/broadcast address.",
            "primary_no_address":   "Primary terminal in NRM is NOT assigned an address — all commands come FROM primary TO secondary, and all responses come FROM secondary back; direction implicitly identifies primary.",
        })
        f.setdefault("loop_topology_sdlc", {
            "go_ahead_bit":      "In loop SDLC, a special Go-Ahead bit pattern (continuous 11111111) circulates around the loop; receiving Go-Ahead grants a secondary permission to transmit.",
            "primary_role":      "Primary launches the loop; secondaries relay frames they don't address themselves and append their own frames before relaying Go-Ahead.",
        })
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "HDLC / SDLC (ISO/IEC 13239) is a wire-level data link "
            "protocol spec; no PDK / SDC / floorplan constraints at the "
            "protocol layer. Per-controller integration constraints "
            "(clock-tree budget for receive-clock recovery, transmit-"
            "clock jitter requirements, FIFO depth for back-pressure "
            "absorption, address-filter table size, FCS hardware engine "
            "vs software fallback) live in the SoC integration spec, "
            "not in ISO/IEC 13239.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "HDLC / SDLC (ISO/IEC 13239) does not specify DFT / scan / "
            "BIST. Protocol-level self-checking (FCS + bit-stuffing "
            "detection + sequence-number checking + frame-type validity "
            "+ FRMR error flags + XID/TEST diagnostic frames) provides "
            "system-level diagnostics. SoC-integrated HDLC controller IP "
            "(Zilog Z85230 SCC, Motorola QUICC MC68360 SCC, Infineon "
            "Falc56 framers, Xilinx LogiCORE HDLC) adds standard scan "
            "insertion at the integrator level.")
        d["fields"] = f
        _write(p, d)

    # L21 power
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "disconnected_mode_DM": "Logical-off state at the protocol layer; secondary's bus drivers may be electrically off; only an acceptable mode-set command brings the link back to operational mode.",
            "link_idle":            "Continuous 1-bits or continuous 0x7E flags transmitted on the wire; per-bit-rate switching power; some controllers gate the transmitter when no frames are pending and an upper-layer keepalive (RR / XID) is not due.",
            "wake_up":              "No protocol-defined wake-up mechanism. SoC-integrated controllers may use receive-line carrier-detect to wake a sleeping host CPU.",
        }
        f["notes"] = (
            "Power-domain partitioning is deferred to the SoC + line-"
            "driver IP. The protocol-defined disconnected mode (DM) is "
            "the only power-related state in ISO/IEC 13239.")
        d["fields"] = f
        _write(p, d)

    # L23 security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "HDLC / SDLC (ISO/IEC 13239) is a wire-level data link "
            "protocol spec; no confidentiality / integrity / "
            "authentication features beyond the FCS. Any node tapping "
            "the link can read every frame. Built-in security primitive "
            "is the 16-bit CRC-CCITT FCS (anti-corruption only, NOT "
            "anti-tampering — an attacker can easily recompute the FCS "
            "after modifying a frame). Modern data-link security on "
            "HDLC-based links (V.42bis + V.92 modem encryption, PPP "
            "PAP/CHAP/EAP authentication and PPP CCP encryption, ISDN "
            "B-channel encryption, IPsec at the network layer above "
            "HDLC) is layered on top — not part of ISO/IEC 13239.")
        d["fields"] = f
        _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_hdlc(blob: str) -> bool:
    """Content-only `hdlc` detector (importable, lifted from the runner) with
    a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The structural HDLC signature
    below is byte-for-byte the same boolean the runner used inline, but it is
    necessary, NOT sufficient: a Bluetooth Low Energy (BLE) spec that mentions
    HDLC framing only incidentally (one "HDLC" token, a passing "bit stuffing"
    mention, a "flag"/"0x7E" elsewhere in the link-layer framing prose) would
    otherwise trip the loose ``HDLC + flag + 0x7E + bit stuffing`` branch and
    have the generic HDLC synth inject ISO/IEC-13239 LAPB/SDLC content into a
    BLE spec's L-docs.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, no chip/SKU/benchmark-name literal as detection logic): if
    the blob's DOMINANT subject is a foreign protocol, defer (return False),
    so the generic HDLC synth never fires on a foreign spec that only mentions
    HDLC incidentally:
      - BLE (Bluetooth Low Energy): the Bluetooth Core LE structural signature
        (Bluetooth Low Energy + advertising + connection, OR BLE + GAP + GATT,
        OR Bluetooth + LE + 2.4 GHz + 40 channels). This mirrors
        ble_protocol_synth.is_ble exactly. The BLE signature is absent from
        every real HDLC benchmark (HDLC is a wired OSI-L2 link protocol with no
        GATT/GAP/advertising/2.4-GHz-channel-hopping concept), so deferring on
        it is safe.

    Empirically verified corpus-clean: the real HDLC benchmark trips NONE of
    these defers and stays True; the BLE benchmark trips ble_primary and is
    suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT HDLC). ---
    ble_primary = bool(
        ("Bluetooth Low Energy" in blob
         and "advertising" in low
         and "connection" in low)
        or ("BLE" in blob and "GAP" in blob and "GATT" in blob)
        or ("Bluetooth" in blob and "LE" in blob
            and "2.4 GHz" in blob and "40 channels" in blob))
    if ble_primary:
        return False

    # --- STRUCTURAL HDLC / SDLC signature (unchanged from the runner's
    #     inline detector). ---
    return bool(
        ("HDLC" in blob and "I-frame" in blob
         and "S-frame" in blob and "U-frame" in blob)
        or ("HDLC" in blob and "flag" in low
            and "0x7E" in blob and "bit stuffing" in low)
        or ("HDLC" in blob and "SDLC" in blob
            and "SABM" in blob))
