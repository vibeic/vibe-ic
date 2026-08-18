"""Interlaken protocol synth helper.

Drop-in protocol synth discovered by the runner's generic auto-dispatch
(`AUTO_DISPATCH = True`). Applies the Interlaken Protocol Definition (Rev 1.2,
Cortina Systems + Cisco) canonical content to L1-L23 when the Interlaken
structural signature is present.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
read from the L-doc / input_doc CONTENT blob only (never a filename or folder
name): the 64B/67B word encoding (64 payload bits + 3 framing bits, bit 64 =
control/data type, bit 65 = scrambled, bit 66 = inversion), the metaframe with
its four control words (Synchronization / Scrambler State / Skip / Diagnostic),
the Burst/Idle Control Word burst framing (SOP / EOP / channel number /
EOP_Format), the per-burst CRC-24 + per-lane CRC-32 diagnostic, channelized
bursts, and the in-band per-channel XON/XOFF flow-control calendar over bonded
SerDes lanes.

Sibling disambiguation — Interlaken vs Ethernet / 800G-Ethernet / AXI-Stream.
  * Ethernet (and 800G/Terabit Ethernet) carries MAC frames with preamble/SFD
    and 48-bit MAC source/destination addresses through an 8B/10B or 64B/66B
    PCS; it has CSMA/CD, MII/XGMII/CDGMII, and no metaframe, no Burst/Idle
    Control Word, no CRC-24-per-burst. Interlaken has NO MAC frame, NO preamble,
    NO MAC address — it has 64B/67B, the metaframe, BURST/IDLE control words and
    channelized bursts. The detector requires the Interlaken-only signature, so
    an Ethernet-primary spec cannot false-fire.
  * AXI4-Stream is a single-channel point-to-point TVALID/TREADY handshake with
    TDATA/TLAST/TKEEP/TSTRB qualifiers and no 64B/67B encoding, no metaframe, no
    bonded SerDes lanes, no CRC-24 burst integrity. Interlaken is NOT AXI-Stream.
The detector DEFERS (returns False) unless the Interlaken name token AND the
Interlaken-only structural quorum are met.

Public entry: ``apply_interlaken_synth(generated_docs_dir, is_interlaken_flag, ic_name)``.
Module-level ``is_interlaken(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp

# Generic auto-dispatch opt-in (read by phase1_doc_one_shot_runner [14e2b/15]).
AUTO_DISPATCH = True
IC_NAME = "Interlaken Protocol Definition"

# Docs whose canonical content sits at the TOP level of the L-doc JSON.
_FLAT_DOCS = (
    "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP", "L5_ADI_SPEC",
    "L6_CONTROL_LOGIC", "L7_TEST_DEBUG", "L8_RTL_CONSTANTS",
    "L8_TIMING_WAVEFORM", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
    "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_LAB_CALIBRATION",
)
# Docs whose canonical content sits under a "fields" wrapper.
_FIELDS_DOCS = (
    "L14_PROTOCOL_VERSIONING", "L15_ENCODING_TABLES",
    "L16_COMPLIANCE_PROPERTIES", "L17_CHANNEL_SIGNAL_CATALOG",
    "L18_INTERCONNECT_TOPOLOGY", "L19_CONSTRAINTS_PDK",
    "L20_DFT_SCAN_TOPOLOGY", "L21_POWER_INTENT", "L22_VERIFICATION_PLAN",
    "L23_SECURITY_REQUIREMENTS",
)


def is_interlaken(blob: str) -> bool:
    """Content-only Interlaken detector with Ethernet / AXI-Stream MUTEX."""
    if not blob:
        return False
    low = blob.lower()
    # Name token (structural identifier — NECESSARY condition).
    name_token = "interlaken" in low
    if not name_token:
        return False
    # Ethernet-primary deferral: if the spec is dominated by MAC-frame /
    # CSMA-CD vocabulary AND lacks the Interlaken 64B/67B + metaframe signature,
    # do not fire (a comparison mention of "Interlaken" inside an Ethernet spec
    # must not trigger). Handled implicitly by the strict quorum below.
    # Interlaken-only structural quorum.
    encoding_64b67b = ("64b/67b" in low or "64b67b" in low
                       or ("64b" in low and "67b" in low)
                       or "67-bit" in low)
    metaframe = "metaframe" in low and (
        ("synchronization" in low or "sync word" in low)
        and "scrambler" in low
        and ("skip word" in low or "skip" in low)
        and "diagnostic" in low)
    burst_ctrl = (("burst control word" in low or "idle control word" in low
                   or "burst/idle" in low)
                  and ("sop" in low or "eop" in low or "eop_format" in low))
    crc24 = "crc-24" in low or "crc24" in low or "crc-32" in low or "crc32" in low
    channelized = ("channel number" in low or "channelized" in low
                   or "calendar" in low)
    flow_control = ("xon" in low or "xoff" in low
                    or "flow control" in low or "flow-control" in low)
    score = sum(bool(x) for x in
                (encoding_64b67b, metaframe, burst_ctrl, crc24, channelized,
                 flow_control))
    # Require the metaframe + Burst/Idle-control-word signature plus a strong
    # quorum (64B/67B encoding gates against any non-Interlaken spec).
    return encoding_64b67b and metaframe and burst_ctrl and score >= 5


# ----------------------------------------------------------------------
# Canonical Interlaken content (Interlaken Protocol Definition Rev 1.2).
# ----------------------------------------------------------------------
def _canon():
    return {
        "L1_DATASHEET": {
            "ic_name": IC_NAME,
            "document_title": "Interlaken Protocol Definition",
            "document_number": "Interlaken Rev 1.2",
            "manufacturer": "Cortina Systems and Cisco Systems",
            "revised_date": "Revision 1.2",
            "external_pins": ["TX_SERDES[N-1:0]", "RX_SERDES[N-1:0]", "TXCLK",
                              "RXCLK", "FC_SYNC", "FC_DATA", "FC_CLK"],
            "external_pin_count": 7,
            "package": "Chip-to-chip SerDes interface (no dedicated package)",
            "key_features": [
                "Narrow, high-speed, channelized chip-to-chip packet interface over multiple bonded SerDes lanes",
                "64B/67B word encoding: 64 payload bits + 3 framing bits (bit 64 control/data, bit 65 scrambled, bit 66 inversion)",
                "Burst framing: packets segmented into bursts delimited by Burst/Idle Control Words (SOP, EOP, channel, flow control)",
                "Metaframe inserts four control words per lane: Synchronization, Scrambler State, Skip, Diagnostic",
                "Channelized: up to 65536 logical channels multiplexed over one physical link",
                "Per-burst CRC-24 integrity (poly 0x328B63) plus per-lane CRC-32 diagnostic (poly 0x04C11DB7)",
                "In-band per-channel XON/XOFF flow-control calendar; optional out-of-band LVDS flow control",
                "Self-synchronous scrambler x^58 + x^39 + 1 per lane for DC balance and transition density",
            ],
            "io_voltage": "SerDes differential signaling (implementation-defined)",
            "clock_frequency": "Per-lane SerDes line rate (e.g. 6.25 / 10.3125 / 12.5 Gbps)",
            "electrical_specs": [
                {"name": "Per-lane SerDes line rate", "min_typ_max": {"min": 6.25, "typ": 10.3125, "max": 12.5}, "unit": "Gbps",
                 "conditions": "64B/67B encoded, per bonded lane", "evidence": {"literal": "each lane runs at the SerDes line rate (e.g. 6.25, 10.3125, 12.5 Gbps)"}},
                {"name": "Bonded lane count N", "min_typ_max": {"min": 4, "typ": 12, "max": 24}, "unit": "lanes",
                 "conditions": "implementation-defined lane bonding", "evidence": {"literal": "The number of lanes N is implementation-defined (e.g. 4, 10, 12, 24 lanes)"}},
                {"name": "Word wire width (64B/67B)", "min_typ_max": {"min": 67, "typ": 67, "max": 67}, "unit": "bits",
                 "conditions": "64 payload + 3 framing bits", "evidence": {"literal": "Every 67-bit word carries 64 payload bits plus 3 framing bits"}},
            ],
        },
        "L2_FRS": {
            "ic_name": IC_NAME,
            "protocol_overview": {
                "type": "Channelized chip-to-chip packet interface over N bonded SerDes lanes",
                "half_duplex": False,
                "layers": ["Protocol Layer (bursts, channels, flow control)",
                           "Framing Layer (64B/67B, metaframe, lane striping, integrity)",
                           "SerDes lanes (PCS/PMA)"],
                "encoding": "64B/67B (64 payload bits + 3 framing bits)",
                "word_types": ["Control Word (bit 64 = 1)", "Data Word (bit 64 = 0)"],
                "channels_max": 65536,
                "scrambler_poly": "x^58 + x^39 + 1",
                "crc24_poly": "0x328B63",
                "crc32_poly": "0x04C11DB7",
                "sync_word": "0x78f678f678f6",
                "metaframe_control_words": ["Synchronization", "Scrambler State", "Skip", "Diagnostic"],
                "defined_by": "Cortina Systems and Cisco Systems",
            },
            "functional_requirements": [
                "Each lane encodes payload as 64B/67B: 64 payload bits plus bit 64 (control/data type), bit 65 (scrambled), bit 66 (inversion).",
                "The Protocol Layer segments each packet into bursts delimited by Control Words; the Burst Control Word carries SOP, channel number and flow-control status; the Idle/Burst Control Word carries EOP, error and EOP_Format (valid-byte count).",
                "Burst length is bounded by BurstMax / BurstShort / BurstMin parameters.",
                "The Framing Layer inserts a metaframe every MetaFrameLength words on each lane: Synchronization, Scrambler State, Skip and Diagnostic control words.",
                "Per-burst integrity uses CRC-24 in the Burst/Idle Control Word; per-lane diagnostic integrity uses CRC-32 in the Diagnostic Word.",
                "Words are striped round-robin across N bonded SerDes lanes; the receiver word-locks, descrambles, deskews (clock-compensates via Skip Words) and de-stripes.",
                "In-band flow control carries a calendar of per-channel XON/XOFF status in Control Words; an out-of-band LVDS flow-control bus is also defined.",
                "Interlaken has no MAC frame, no preamble/SFD, and no MAC addresses — it is not Ethernet.",
            ],
        },
        "L3_CMD_PROTOCOL": {
            "ic_name": IC_NAME,
            "protocol_type": "Word-framed channelized packet protocol; 64B/67B words; Control Words frame bursts; Data Words carry payload.",
            "opcodes": [
                {"hex": "bit64=1", "name": "CONTROL_WORD", "purpose": "Framing-layer word (Burst/Idle or metaframe control word)"},
                {"hex": "bit64=0", "name": "DATA_WORD", "purpose": "8 bytes of packet payload"},
                {"hex": "0x78f6", "name": "SYNCHRONIZATION_WORD", "purpose": "Metaframe word lock / lane alignment pattern 0x78f678f678f6"},
                {"hex": "SCRAM", "name": "SCRAMBLER_STATE_WORD", "purpose": "Metaframe word carrying scrambler state for descrambler sync"},
                {"hex": "SKIP", "name": "SKIP_WORD", "purpose": "Metaframe word added/deleted for clock compensation"},
                {"hex": "DIAG", "name": "DIAGNOSTIC_WORD", "purpose": "Metaframe word carrying per-lane CRC-32 + lane health/status"},
                {"hex": "BURST", "name": "BURST_CONTROL_WORD", "purpose": "Starts a burst: SOP, channel number, flow-control calendar, CRC-24"},
                {"hex": "IDLE", "name": "IDLE_CONTROL_WORD", "purpose": "Ends a burst / fills between bursts: EOP, error, EOP_Format, CRC-24"},
            ],
            "control_word_fields": [
                {"field": "Control Type", "desc": "Burst Control Word vs Idle Control Word"},
                {"field": "SOP", "desc": "Start-Of-Packet"},
                {"field": "EOP_Format", "desc": "0 = not EOP, 1..8 = valid bytes in last Data Word"},
                {"field": "Error", "desc": "Marks the burst as errored"},
                {"field": "Channel Number", "desc": "Logical channel of the burst (up to 65536)"},
                {"field": "Flow Control", "desc": "In-band per-channel XON/XOFF calendar bits"},
                {"field": "CRC-24", "desc": "Per-burst integrity, polynomial 0x328B63"},
                {"field": "Reset Calendar", "desc": "Resets the flow-control calendar position"},
            ],
            "crc": {"name": "CRC-24", "poly_hex": "0x328B63", "scope": "per-burst",
                    "coverage": "burst Data Words plus the Burst/Idle Control Word"},
            "crc32": {"name": "CRC-32", "poly_hex": "0x04C11DB7", "scope": "per-lane",
                      "coverage": "metaframe on each lane; carried in the Diagnostic Word"},
            "encoding": "64B/67B — 64 payload bits + bit 64 (control/data) + bit 65 (scrambled) + bit 66 (inversion)",
            "channelized": True,
            "channels_max": 65536,
            "byte_oriented": False,
            "word_oriented": True,
        },
        "L4_REGMAP": {
            "ic_name": IC_NAME,
            "registers": [
                {"name": "MetaFrameLength", "desc": "Words between metaframe control-word groups on each lane (e.g. 2048)"},
                {"name": "BurstMax", "desc": "Maximum payload bytes between Control Words (typical 256)"},
                {"name": "BurstShort", "desc": "Burst size for packets shorter than BurstMin (typical 32)"},
                {"name": "BurstMin", "desc": "Minimum payload between Control Words for a non-final burst (multiple of 32, typical 64)"},
                {"name": "LaneCount", "desc": "Number of bonded SerDes lanes N (implementation-defined, e.g. 4/10/12/24)"},
                {"name": "ChannelCount", "desc": "Number of active logical channels (up to 65536)"},
            ],
            "note": "Interlaken is a protocol definition, not a register-file device; these are link configuration parameters.",
        },
        "L5_ADI_SPEC": {
            "ic_name": IC_NAME,
            "analog_mixed_signal": "Rides on bonded SerDes lanes (differential PCS/PMA); the protocol layer is digital. SerDes electrical layer is implementation-defined.",
            "io_standard": "SerDes differential signaling (e.g. CEI-6G/CEI-11G); optional LVDS out-of-band flow-control bus.",
            "not_applicable_reason": "Interlaken defines the protocol/framing layers; the analog SerDes is left to the implementation.",
        },
        "L6_CONTROL_LOGIC": {
            "ic_name": IC_NAME,
            "control_logic": {
                "tx_fsm": ["Segment packet into bursts", "Emit Burst Control Word (SOP, channel, flow control)",
                           "Emit Data Words", "Emit Idle/Burst Control Word (EOP, EOP_Format, CRC-24)",
                           "Stripe words across lanes", "Insert metaframe every MetaFrameLength words",
                           "Scramble per lane", "64B/67B encode per lane"],
                "rx_fsm": ["Word-lock each lane on Synchronization Word", "Synchronize descrambler via Scrambler State Word",
                           "Deskew lanes on metaframe boundaries", "Clock-compensate via Skip Words",
                           "De-stripe words", "Check CRC-24 per burst and CRC-32 per lane",
                           "Reassemble bursts into packets using SOP/EOP/EOP_Format"],
                "flow_control": "In-band XON/XOFF calendar in Control Words advances through channels; XOFF back-pressures a channel, XON permits sending.",
                "alignment": "Link up when all lanes are word-locked, descrambler-synchronized, deskewed, and Diagnostic Word reports lanes operational.",
            },
        },
        "L7_TEST_DEBUG": {
            "ic_name": IC_NAME,
            "test_debug": {
                "lane_health": "Diagnostic Word reports per-lane status (operational) and lane number",
                "per_lane_crc": "CRC-32 (poly 0x04C11DB7) in the Diagnostic Word detects per-lane bit errors",
                "per_burst_crc": "CRC-24 (poly 0x328B63) in the Burst/Idle Control Word detects burst errors",
                "word_lock": "Receiver locks on the Synchronization Word 0x78f678f678f6",
                "skip_word": "Skip Words added/deleted for clock compensation and observable for rate-match debug"},
        },
        "L8_RTL_CONSTANTS": {
            "ic_name": IC_NAME,
            "width_parameters": {
                "WORD_PAYLOAD_BITS": {"width_bits": 64},
                "WORD_WIRE_BITS": {"width_bits": 67},
                "CHANNEL_NUMBER_BITS": {"width_bits": 16},
                "CRC24_BITS": {"width_bits": 24},
                "CRC32_BITS": {"width_bits": 32},
                "EOP_FORMAT_BITS": {"width_bits": 4}},
            "key_constants": {
                "WORD_PAYLOAD_BITS": 64, "WORD_WIRE_BITS": 67,
                "CTRL_TYPE_BIT": 64, "SCRAMBLED_BIT": 65, "INVERSION_BIT": 66,
                "CHANNEL_NUMBER_BITS": 16, "CHANNELS_MAX": 65536,
                "CRC24_POLY": "0x328B63", "CRC32_POLY": "0x04C11DB7",
                "SCRAMBLER_POLY": "x^58 + x^39 + 1", "SYNC_WORD": "0x78f678f678f6",
                "METAFRAME_LENGTH": 2048, "BURST_MAX": 256, "BURST_SHORT": 32,
                "BURST_MIN": 64},
            "framing_bit_encodings": {"bit64": "1=Control Word, 0=Data Word",
                                      "bit65": "1=scrambled", "bit66": "1=inverted"},
            "eop_format_encodings": {"0": "not EOP", "1": "1 valid byte", "8": "8 valid bytes"},
        },
        "L8_TIMING_WAVEFORM": {
            "ic_name": IC_NAME,
            "timing_constants": {"per_lane_line_rate_gbps": [6.25, 10.3125, 12.5],
                                 "word_payload_bits": 64, "word_wire_bits": 67,
                                 "metaframe_length_words": 2048},
            "framing_waveform": {"word_encoding": "64B/67B per lane",
                                 "control_data_bit": "bit 64 (1=Control, 0=Data)",
                                 "scrambled_bit": "bit 65", "inversion_bit": "bit 66",
                                 "metaframe": "Sync, Scrambler State, Skip, Diagnostic every MetaFrameLength words"},
            "burst_waveform": {"order": ["Burst Control Word (SOP, channel, flow control)",
                                         "Data Words (payload)",
                                         "Idle/Burst Control Word (EOP, EOP_Format, CRC-24)",
                                         "Idle Control Words between bursts"]},
        },
        "L9_INTEGRATION_SPEC": {
            "ic_name": IC_NAME,
            "integration_overview": {
                "role": "Chip-to-chip interconnect between packet processors, traffic managers, framers, and switch fabrics",
                "endpoints": ["Packet processor / NPU", "Traffic manager", "Framer / MAC", "Switch fabric"],
                "topology": "Point-to-point over N bonded SerDes lanes per direction; words striped across lanes",
                "lane_count": "Implementation-defined N (e.g. 4 / 10 / 12 / 24 lanes)",
                "channels": "Up to 65536 logical channels multiplexed over the link",
                "init_sequence": "Receiver word-locks each lane on the Synchronization Word, synchronizes descramblers via Scrambler State Words, deskews on metaframe boundaries (clock-compensating with Skip Words), then de-stripes; link up when Diagnostic Words report all lanes operational."},
        },
        "L10_TEST_CASES": {
            "ic_name": IC_NAME,
            "test_cases": [
                {"name": "word_lock", "desc": "Receiver locks word boundary on the Synchronization Word 0x78f678f678f6."},
                {"name": "lane_deskew", "desc": "Bonded lanes are deskewed using successive metaframe boundaries."},
                {"name": "descrambler_sync", "desc": "Scrambler State Word synchronizes the per-lane descrambler (x^58 + x^39 + 1)."},
                {"name": "burst_framing", "desc": "Burst Control Word (SOP) and Idle/Burst Control Word (EOP, EOP_Format) delimit a packet's bursts."},
                {"name": "crc24_error", "desc": "Corrupted burst flagged by CRC-24 (poly 0x328B63) mismatch -> burst errored."},
                {"name": "crc32_lane_error", "desc": "Diagnostic Word CRC-32 (poly 0x04C11DB7) detects a per-lane error."},
                {"name": "flow_control_xoff", "desc": "XOFF in the calendar back-pressures a channel; XON resumes it."},
                {"name": "skip_clock_comp", "desc": "Skip Words are added/deleted to absorb the clock-rate difference."}],
        },
        "L11_OTP_CONTENT": {
            "ic_name": IC_NAME,
            "otp_content": "N/A — Interlaken is a chip-to-chip protocol, no one-time-programmable fuse content defined.",
            "applicable": False,
        },
        "L12_BEHAVIORAL_SEQUENCES": {
            "ic_name": IC_NAME,
            "transmit_sequence": ["Protocol Layer segments the packet into bursts (bounded by BurstMax/BurstMin).",
                                  "Emit a Burst Control Word with SOP, channel number and the flow-control calendar.",
                                  "Emit the burst's Data Words.",
                                  "Emit the Idle/Burst Control Word with EOP, EOP_Format (valid bytes 1..8) and CRC-24.",
                                  "Framing Layer stripes words across the N lanes and scrambles each lane.",
                                  "Insert the metaframe (Sync, Scrambler State, Skip, Diagnostic) every MetaFrameLength words.",
                                  "64B/67B-encode each lane (bit 64 control/data, bit 65 scrambled, bit 66 inversion)."],
            "receive_sequence": ["Word-lock each lane on the Synchronization Word.",
                                 "Synchronize the descrambler using the Scrambler State Word.",
                                 "Deskew the bonded lanes on metaframe boundaries; absorb clock difference via Skip Words.",
                                 "De-stripe words back into the ordered word stream.",
                                 "Verify CRC-24 per burst and CRC-32 per lane (Diagnostic Word).",
                                 "Reassemble bursts into packets using SOP / EOP / EOP_Format."],
            "flow_control_sequence": ["Each Control Word advances the per-channel XON/XOFF calendar.",
                                      "XOFF on a channel back-pressures the far end for that channel.",
                                      "XON re-enables transmission on that channel."],
        },
        "L13_LAB_CALIBRATION": {
            "ic_name": IC_NAME,
            "lab_calibration": "N/A — protocol/framing layers are digital; SerDes electrical calibration (CDR, equalization) is implementation-defined.",
            "applicable": False,
        },
        "L14_PROTOCOL_VERSIONING": {
            "spec_version": "Interlaken Protocol Definition Revision 1.2 (Cortina Systems + Cisco Systems)",
            "lineage": [
                {"version": "Interlaken 1.0", "year": "2007", "summary": "Initial Interlaken Protocol Definition by Cortina Systems and Cisco Systems."},
                {"version": "Interlaken 1.1", "year": "2008", "summary": "Clarifications and errata to the framing/metaframe definition."},
                {"version": "Interlaken 1.2", "year": "2008", "summary": "Current base protocol definition: 64B/67B, metaframe, burst framing, flow control."}],
            "backward_compat_traps": [
                {"trap_name": "Not_Ethernet", "rule": "Interlaken uses 64B/67B, a metaframe (Sync/Scrambler/Skip/Diagnostic) and Burst/Idle Control Words with channelized bursts; it has no MAC frame, no preamble/SFD and no MAC addresses.", "trap": "Decoding Interlaken as Ethernet (MAC frames, preamble, 8B/10B or 64B/66B PCS) is wrong."},
                {"trap_name": "Not_AXI_Stream", "rule": "Interlaken is a multi-lane channelized SerDes framing protocol with metaframe and per-burst CRC-24; it is not a single-channel TVALID/TREADY handshake.", "trap": "Treating Interlaken as AXI4-Stream misses the 64B/67B encoding, metaframe and lane bonding."}],
        },
        "L15_ENCODING_TABLES": {
            "word_type_table": {"header_columns": ["bit 64", "Word Type"], "rows": [
                ["1", "Control Word"], ["0", "Data Word"]]},
            "framing_bit_table": {"header_columns": ["Bit", "Meaning"], "rows": [
                ["bit 64", "Control/Data type (1=Control, 0=Data)"],
                ["bit 65", "Scrambled"], ["bit 66", "Inversion"]]},
            "metaframe_word_table": {"header_columns": ["Control Word", "Purpose"], "rows": [
                ["Synchronization Word", "Word lock / lane alignment (0x78f678f678f6)"],
                ["Scrambler State Word", "Descrambler synchronization (x^58 + x^39 + 1)"],
                ["Skip Word", "Clock compensation (rate match)"],
                ["Diagnostic Word", "Per-lane CRC-32 + lane health/status"]]},
            "control_word_field_table": {"header_columns": ["Field", "Meaning"], "rows": [
                ["SOP", "Start-Of-Packet"], ["EOP_Format", "0=not EOP, 1..8=valid bytes in last Data Word"],
                ["Error", "Burst errored"], ["Channel Number", "Logical channel (up to 65536)"],
                ["Flow Control", "Per-channel XON/XOFF calendar"], ["CRC-24", "Per-burst integrity (0x328B63)"]]},
            "crc_table": {"header_columns": ["CRC", "Polynomial", "Scope"], "rows": [
                ["CRC-24", "0x328B63", "Per burst (Burst/Idle Control Word)"],
                ["CRC-32", "0x04C11DB7", "Per lane (Diagnostic Word)"]]},
            "burst_param_table": {"header_columns": ["Parameter", "Typical"], "rows": [
                ["BurstMax", "256 bytes"], ["BurstShort", "32 bytes"], ["BurstMin", "64 bytes (multiple of 32)"]]},
        },
        "L16_COMPLIANCE_PROPERTIES": {
            "must_have_properties": [
                "Every word is 64B/67B: 64 payload bits + bit 64 (control/data) + bit 65 (scrambled) + bit 66 (inversion).",
                "A burst is a run of Data Words delimited by Control Words; the Burst Control Word carries SOP, channel number and the flow-control calendar.",
                "The Idle/Burst Control Word carries EOP, the Error bit and EOP_Format (1..8 valid bytes in the last Data Word).",
                "The metaframe inserts Synchronization, Scrambler State, Skip and Diagnostic control words every MetaFrameLength words on each lane.",
                "Per-burst integrity is CRC-24 (poly 0x328B63) in the Burst/Idle Control Word; per-lane integrity is CRC-32 (poly 0x04C11DB7) in the Diagnostic Word.",
                "Words are striped across N bonded SerDes lanes and the receiver word-locks, descrambles, deskews (Skip-Word clock comp) and de-stripes.",
                "In-band flow control carries a per-channel XON/XOFF calendar in Control Words; an out-of-band LVDS flow-control bus is also defined."],
            "interlaken_distinguishers": [
                "64B/67B word encoding (not 8B/10B or 64B/66B Ethernet PCS).",
                "Metaframe with Synchronization/Scrambler-State/Skip/Diagnostic control words.",
                "Burst/Idle Control Words framing channelized bursts (no MAC frame, no preamble, no MAC address).",
                "Per-burst CRC-24 plus per-lane CRC-32 diagnostic.",
                "In-band per-channel XON/XOFF flow-control calendar over bonded SerDes lanes."],
        },
        "L17_CHANNEL_SIGNAL_CATALOG": {
            "channels": [
                {"name": "TX_SERDES[N-1:0]", "direction": "output (differential)", "purpose": "N transmit SerDes lanes; words striped across them."},
                {"name": "RX_SERDES[N-1:0]", "direction": "input (differential)", "purpose": "N receive SerDes lanes; de-striped after word-lock/deskew."},
                {"name": "TXCLK", "direction": "output", "purpose": "Transmit-direction SerDes reference clock."},
                {"name": "RXCLK", "direction": "input", "purpose": "Receive-direction SerDes reference clock."},
                {"name": "FC_SYNC", "direction": "bidirectional", "purpose": "Out-of-band flow-control LVDS sync."},
                {"name": "FC_DATA", "direction": "bidirectional", "purpose": "Out-of-band flow-control LVDS data."},
                {"name": "FC_CLK", "direction": "bidirectional", "purpose": "Out-of-band flow-control LVDS clock."}],
            "logical_channels": {"count_max": 65536, "selector": "Channel Number field in the Burst Control Word",
                                 "flow_control": "Per-channel XON/XOFF calendar in Control Words"},
            "metaframe_control_words": ["Synchronization Word", "Scrambler State Word", "Skip Word", "Diagnostic Word"],
            "channel_counts": {"serdes_lanes": "N (implementation-defined)", "logical_channels_max": 65536,
                               "metaframe_control_words": 4, "framing_bits_per_word": 3},
        },
        "L18_INTERCONNECT_TOPOLOGY": {
            "topology_type": "Point-to-point chip-to-chip over N bonded SerDes lanes per direction; Protocol-over-Framing-over-SerDes layering.",
            "supported_topologies": [
                {"name": "Bonded multi-lane link", "description": "Words striped round-robin across N SerDes lanes; each lane self-framed with its own metaframe."},
                {"name": "Channelized multiplex", "description": "Up to 65536 logical channels share the physical link, selected by the Burst Control Word channel number."}],
            "device_classification": {"endpoints": ["Packet processor / NPU", "Traffic manager", "Framer / MAC", "Switch fabric"]},
            "lane_bonding": "Round-robin striping across N lanes; receiver deskews on metaframe boundaries and clock-compensates with Skip Words.",
        },
        "L19_CONSTRAINTS_PDK": {"pdk_target": "N/A (protocol definition, not a tapeout)",
                                "serdes_line_rate_gbps": [6.25, 10.3125, 12.5],
                                "lane_count": "implementation-defined N"},
        "L20_DFT_SCAN_TOPOLOGY": {"scan_topology": "N/A — protocol definition, no DFT defined.",
                                  "in_band_diagnostics": "Per-lane Diagnostic Word (CRC-32 + lane status) provides link health observability."},
        "L21_POWER_INTENT": {"power_domains": ["SerDes core/IO supplies (implementation-defined)"],
                             "power_considerations": "64B/67B has lower overhead than 8B/10B (1.5625% vs 25%), improving power efficiency per useful bit; lane count scales power with bandwidth."},
        "L22_VERIFICATION_PLAN": {"verification_items": ["Word lock on Synchronization Word", "Lane deskew on metaframe boundaries",
                                  "Descrambler synchronization", "Burst framing (SOP/EOP/EOP_Format)", "CRC-24 per-burst error detection",
                                  "CRC-32 per-lane diagnostic", "XON/XOFF flow-control calendar", "Skip-Word clock compensation"]},
        "L23_SECURITY_REQUIREMENTS": {"attack_surface": [
            "Interlaken is a chip-to-chip board-level interconnect; the primary threat is physical board access, not a network attacker.",
            "No encryption or authentication is defined; integrity is error-detection (CRC-24/CRC-32) not cryptographic."],
            "security_notes": "Interlaken defines no confidentiality or authentication; deployments relying on it for security must add protection above the link."},
    }


def apply_interlaken_synth(generated_docs_dir, is_interlaken_flag: bool,
                           ic_name: Optional[str]) -> None:
    """Force-merge Interlaken-canonical content into the generated L-docs when
    the Interlaken signature matched. No-op otherwise."""
    if not is_interlaken_flag:
        return
    gd = Path(generated_docs_dir)
    canon = _canon()
    name = ic_name or IC_NAME
    for doc in _FLAT_DOCS:
        p = gd / f"{doc}.json"
        if not p.is_file():
            continue
        d = json.loads(p.read_text())
        d.update(canon.get(doc, {}))
        d["ic_name"] = name
        _stamp.dump(p, d)
    for doc in _FIELDS_DOCS:
        p = gd / f"{doc}.json"
        if not p.is_file():
            continue
        d = json.loads(p.read_text())
        f = d.get("fields")
        if not isinstance(f, dict):
            f = {}
        f.update(canon.get(doc, {}))
        d["fields"] = f
        d["ic_name"] = name
        _stamp.dump(p, d)
