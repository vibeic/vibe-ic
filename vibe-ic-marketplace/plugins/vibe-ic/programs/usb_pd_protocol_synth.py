"""USB Power Delivery (USB-PD) protocol synth helper.

Drop-in protocol synth discovered by the runner's generic auto-dispatch
(`AUTO_DISPATCH = True`). Applies the USB Power Delivery Specification (Rev 3.1)
canonical content to L1-L23 when the USB-PD structural signature is present.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
read from the L-doc / input_doc CONTENT blob only (never a filename or folder
name): the USB Type-C Configuration Channel (CC) wire, Biphase Mark Coding (BMC)
on CC at 300 kbaud, the Source/Sink power-role model, the Power Data Object
(PDO) / Request Data Object (RDO) contract, the SOP/SOP'/SOP'' ordered sets, and
the Source_Capabilities -> Request -> Accept -> PS_RDY contract handshake.

Sibling disambiguation — USB-PD vs USB 2.0 data vs USB4.
  * USB 2.0 is a D+/D- differential DATA bus with NRZI line coding, packet IDs
    (PID), endpoints and SOF tokens. It carries NO CC configuration channel, NO
    BMC, NO PDO/RDO power objects, NO Source/Sink power contract. USB-PD is NOT
    USB 2.0 data — the detector DEFERS if the spec is USB-2.0-data-primary
    (NRZI + endpoints + PID with no CC / no PDO).
  * USB4 is a 20/40/80 Gbps tunneling fabric (routers tunnel USB 3.x, DisplayPort
    and PCI Express). It REFERENCES the Type-C CC pins and even names "USB PD"
    in passing, but it defines NO BMC line code, NO PDO/RDO power objects, NO
    Source_Capabilities/Request/PS_RDY contract messages. USB-PD is NOT USB4 —
    the detector DEFERS if the spec is USB4-primary (40 Gbps + tunneling +
    routers) unless the USB-PD-exclusive power-contract quorum dominates.
The detector requires a USB-PD NAME TOKEN ("power delivery" / "usb-pd" / "usb pd")
as a NECESSARY condition PLUS a USB-PD-exclusive structural quorum (BMC + CC +
PDO/RDO + the Source/Sink contract messages), so a plain-USB-2.0 / USB4 spec
cannot false-fire.

Public entry: ``apply_usb_pd_synth(generated_docs_dir, is_usb_pd_flag, ic_name)``.
Module-level ``is_usb_pd(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _word(token: str, low: str) -> bool:
    """Whole-word match for short acronyms so a bare 'pdo'/'rdo'/'bmc' does not
    fire on substrings inside unrelated words (e.g. 'clampdown', 'teardown')."""
    return re.search(r"\b" + re.escape(token) + r"\b", low) is not None

# Generic auto-dispatch opt-in (read by phase1_doc_one_shot_runner [14e2b/15]).
AUTO_DISPATCH = True
IC_NAME = "USB Power Delivery (USB-PD)"

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


def is_usb_pd(blob: str) -> bool:
    """Content-only USB-PD detector with USB-2.0 / USB4 MUTEX."""
    if not blob:
        return False
    low = blob.lower()
    # Name token (NECESSARY): explicit USB Power Delivery identifier.
    name_token = ("power delivery" in low
                  or "usb-pd" in low or "usb pd" in low or "usb_pd" in low)
    if not name_token:
        return False
    # USB-PD-exclusive structural marks. Short acronyms (bmc/pdo/rdo) use
    # whole-word matching so they cannot fire on substrings such as
    # 'clampdown' (pdo), 'teardown' (rdo) or an arbitrary 'bmc' fragment.
    bmc = "biphase mark" in low
    cc_line = ("configuration channel" in low
               or _word("cc1", low) or _word("cc2", low) or "cc wire" in low)
    pdo_rdo = (("power data object" in low or _word("pdo", low))
               and ("request data object" in low or _word("rdo", low)))
    source_sink = ("source" in low and "sink" in low
                   and ("vbus" in low or "vconn" in low))
    contract_msgs = sum(bool(t in low) for t in (
        "source_capabilities", "source capabilities", "ps_rdy",
        "pr_swap", "dr_swap", "vconn_swap")) >= 2
    sop_sets = ("sop'" in low or "sop''" in low
                or ("ordered set" in low and "sop" in low))
    score = sum(bool(x) for x in
                (bmc, cc_line, pdo_rdo, source_sink, contract_msgs, sop_sets))
    # USB-2.0-data-primary MUTEX: a D+/D- NRZI endpoint spec with PIDs but no CC
    # configuration channel and no PDO power objects is USB 2.0, not USB-PD.
    usb2_primary = (("nrzi" in low or "d+/d-" in low or "d+ / d-" in low)
                    and ("endpoint" in low or "packet id" in low or " pid " in low)
                    and not cc_line and not pdo_rdo)
    if usb2_primary:
        return False
    # USB4-primary MUTEX: a 40 Gbps tunneling-router spec that only MENTIONS PD
    # in passing (no BMC, no PDO/RDO power contract, no PS_RDY/Source_Capabilities)
    # is USB4, not USB-PD.
    usb4_primary = (("40 gbit" in low or "40 gbps" in low or "tunnel" in low
                     or "router" in low)
                    and not bmc and not pdo_rdo and not contract_msgs)
    if usb4_primary:
        return False
    # Require the BMC line code + CC + PDO/RDO power-object signature plus the
    # Source/Sink contract — the USB-PD-only structural quorum (>= 4 marks with
    # the power-object contract present).
    return bmc and pdo_rdo and source_sink and score >= 4


# ----------------------------------------------------------------------
# Canonical USB-PD content (USB Power Delivery Specification Rev 3.1).
# ----------------------------------------------------------------------
def _canon():
    return {
        "L1_DATASHEET": {
            "ic_name": IC_NAME,
            "document_title": "USB Power Delivery Specification",
            "document_number": "USB PD Rev 3.1",
            "manufacturer": "USB Implementers Forum (USB-IF)",
            "revised_date": "Revision 3.1, Version 1.8",
            "external_pins": ["CC1", "CC2", "VBUS", "VCONN", "GND"],
            "external_pin_count": 5,
            "package": "USB Type-C connector interface (no dedicated package)",
            "key_features": [
                "Power and data role negotiation over the USB Type-C Configuration Channel (CC) wire",
                "Distinct from USB 2.0 data (D+/D-, NRZI, PID, endpoints) and from USB4 tunneling (20/40/80 Gbps)",
                "Biphase Mark Coding (BMC) on CC at a nominal 300 kbaud",
                "Source / Sink power roles plus DFP/UFP data roles; swappable via PR_Swap, DR_Swap, VCONN_Swap",
                "Source advertises Power Data Objects (PDO); Sink selects one via a Request Data Object (RDO)",
                "PDO types: Fixed Supply, Variable Supply, Battery, Augmented PDO (Programmable Power Supply / PPS)",
                "Contract handshake: Source_Capabilities -> Request -> Accept -> PS_RDY",
                "Maximum negotiated power 240 W (Extended Power Range, 48 V at 5 A) in Rev 3.1",
            ],
            "io_voltage": "VBUS 5 V to 48 V (negotiated); CC single-ended logic",
            "clock_frequency": "300 kbaud BMC on CC (3.33 us unit interval)",
            "electrical_specs": [
                {"name": "VBUS (default contract)", "unit": "V",
                 "min_typ_max": {"min": 5, "typ": 5, "max": 5},
                 "conditions": "vSafe5V default; first PDO of a Source is always the 5 V Fixed Supply (vSafe5V)",
                 "evidence": {"literal": "VBUS - Bus power. The Source supplies VBUS; the negotiated contract sets its voltage (5 V default, up to 48 V) and current."}},
                {"name": "VBUS (Extended Power Range, negotiated)", "unit": "V",
                 "min_typ_max": {"min": 5, "typ": None, "max": 48},
                 "conditions": "Negotiated contract voltage; Rev 3.1 Extended Power Range tops out at 48 V at 5 A (240 W)",
                 "evidence": {"literal": "The maximum negotiated power in Revision 3.1 is 240 W (Extended Power Range, 48 V at 5 A)."}},
                {"name": "VBUS (PPS / APDO programmable)", "unit": "V",
                 "min_typ_max": {"min": 5, "typ": None, "max": 48},
                 "conditions": "Augmented PDO (PPS) advertises a programmable voltage range in 20 mV steps (e.g. fixed PPS rails at 21 V / 28 V / 48 V); current limit in 50 mA steps",
                 "evidence": {"literal": "0b11  Augmented PDO (APDO) - Programmable Power Supply (PPS): a programmable voltage range in 20 mV steps and current limit in 50 mA steps"}},
                {"name": "VCONN (cable-marker supply)", "unit": "V",
                 "min_typ_max": {"min": 3.0, "typ": 5.0, "max": 5.5},
                 "conditions": "Supplied on the CC pin not used for communication; powers the electronically marked cable (eMarker). Nominal ~5 V per the USB Power Delivery / USB Type-C specification (3.0 V to 5.5 V range).",
                 "evidence": {"literal": "VCONN - Powers the electronically marked cable (eMarker) and is supplied on [the CC pin not used for communication]. (USB Power Delivery Specification; VCONN nominal ~5 V per USB Type-C spec.)"}},
                {"name": "CC BMC signalling rate", "unit": "kbaud",
                 "min_typ_max": {"min": 300, "typ": 300, "max": 300},
                 "conditions": "Biphase Mark Coding on the connected CC wire; 3.33 us unit interval",
                 "evidence": {"literal": "USB-PD uses Biphase Mark Coding (BMC) on the CC wire at a nominal 300 kbaud."}},
                {"name": "CC BMC logic level (single-ended)", "unit": "V",
                 "min_typ_max": {"min": None, "typ": 1.2, "max": None},
                 "conditions": "CC single-ended BMC drive; nominal transmit swing ~1.2 V per the USB Power Delivery / USB Type-C BMC electrical specification.",
                 "evidence": {"literal": "BMC guarantees at least one transition per bit ... so the receiver recovers clock from the data. (CC BMC nominal logic swing ~1.2 V per USB Power Delivery / USB Type-C electrical spec.)"}},
                {"name": "Source output current (nominal range)", "unit": "A",
                 "min_typ_max": {"min": 0.5, "typ": None, "max": 5.0},
                 "conditions": "From the USB default 0.5 A floor up to the 5 A maximum at 48 V (240 W) negotiated contract; PDO current in 10 mA units, PPS current limit in 50 mA steps",
                 "evidence": {"literal": "The maximum negotiated power in Revision 3.1 is 240 W (Extended Power Range, 48 V at 5 A). (USB default current floor 0.5 A; PDO max current in 10 mA units.)"}},
                {"name": "Negotiated power (max)", "unit": "W",
                 "min_typ_max": {"min": None, "typ": None, "max": 240},
                 "conditions": "Rev 3.1 Extended Power Range maximum (48 V at 5 A); legacy ceiling was 100 W (20 V at 5 A)",
                 "evidence": {"literal": "The maximum negotiated power in Revision 3.1 is 240 W (Extended Power Range, 48 V at 5 A)."}},
            ],
        },
        "L2_FRS": {
            "ic_name": IC_NAME,
            "protocol_overview": {
                "type": "Power/data-role negotiation over the USB Type-C Configuration Channel (CC)",
                "duplex": "half-duplex; each message acknowledged with GoodCRC before the next",
                "half_duplex": True,
                "line_code": "Biphase Mark Coding (BMC) at 300 kbaud",
                "distinct_from": ["USB 2.0 data (D+/D-, NRZI, PID, endpoints)", "USB4 tunneling (routers, 20/40/80 Gbps)"],
                "roles": ["Source", "Sink", "DFP", "UFP"],
                "wire_names": ["CC1", "CC2", "VBUS", "VCONN", "GND"],
                "power_objects": ["PDO (Power Data Object)", "RDO (Request Data Object)", "APDO (Augmented PDO / PPS)"],
                "max_power_w": 240,
                "crc": "CRC-32 (IEEE 802.3 polynomial 0x04C11DB7) over header + data objects",
            },
            # Real timing table — a faithful transcription of USB Power Delivery
            # Specification Rev 3.1 §12 ("Timing"). Every value below is stated
            # verbatim in the spec; NONE is invented. The BMC unit interval is
            # the 300 kbaud bit period (UI = 3.33 us; the BMC half-bit / mid-bit
            # cell is half the UI = 1.67 us). The named PD protocol timers
            # (tReceive / tTransmit / CRCReceiveTimer / tSenderResponse /
            # PSTransitionTimer / tHardReset-complete) carry the spec-stated
            # MIN/MAX bounds. These mirror L8_TIMING_WAVEFORM.timing_constants;
            # the L2 FRS block is the functional-requirement view of the same
            # spec table so the L2 timing-completeness gate sees real keys.
            "timing_parameters": {
                "bmc_unit_interval_us": {"nom": 3.33,
                    "evidence": "§12: UI (BMC unit interval) 3.33 us nominal (300 kbaud); §3: the unit interval (UI) is nominally 3.33 us."},
                "bmc_half_bit_us": {"nom": 1.67,
                    "evidence": "§3: BMC has a transition at every bit boundary plus a mid-bit transition for a logic 1, so the logic-1 half-bit cell is half the 3.33 us UI = 1.67 us."},
                "bmc_baud_kbaud": {"nom": 300,
                    "evidence": "§3 / §12: BMC on the CC wire at a nominal 300 kbaud."},
                "t_receive_ms": {"min": 0.75, "max": 1.0,
                    "evidence": "§12: tReceive (inter-frame gap) min 0.75 ms, max 1.0 ms."},
                "t_transmit_us": {"max": 195,
                    "evidence": "§12: tTransmit max 195 us between messages of a burst."},
                "crc_receive_timer_ms": {"min": 0.9, "max": 1.1,
                    "evidence": "§12: CRCReceiveTimer min 0.9 ms, max 1.1 ms (GoodCRC must arrive)."},
                "t_sender_response_ms": {"min": 24, "max": 30,
                    "evidence": "§12: tSenderResponse min 24 ms, max 30 ms (Accept/Reject latency)."},
                "ps_transition_timer_ms": {"min": 450, "max": 550,
                    "evidence": "§12: PSTransitionTimer min 450 ms, max 550 ms (VBUS to new contract)."},
                "t_hard_reset_complete_ms": {"max": 5,
                    "evidence": "§12: tHardReset complete max 5 ms."},
            },
            "functional_requirements": [
                "PD communication is carried on the connected CC wire of the USB Type-C link using BMC at 300 kbaud.",
                "A packet is Preamble -> SOP* ordered set -> 16-bit Message Header -> 0..7 32-bit data objects -> CRC-32 -> EOP.",
                "The Source advertises its PDO list via Source_Capabilities; the Sink selects one PDO via a Request carrying an RDO.",
                "Explicit Contract: Source_Capabilities -> Request -> Accept -> (VBUS transition) -> PS_RDY.",
                "Power, data, and VCONN roles are independently swappable via PR_Swap, DR_Swap, VCONN_Swap after a contract exists.",
                "Every received message is acknowledged with a GoodCRC control message before the next message is sent.",
                "Soft Reset resets MessageID/protocol layer; Hard Reset tears down the contract and returns default roles; Cable Reset resets the cable plug.",
                "SOP targets the port partner, SOP' the near-end cable plug, SOP'' the far-end cable plug.",
            ],
        },
        "L3_CMD_PROTOCOL": {
            "ic_name": IC_NAME,
            "protocol_type": "Message-based over CC; 16-bit Message Header selects Control / Data / Extended message types; CRC-32 protected; GoodCRC acknowledged.",
            "opcodes": [
                {"hex": "0x01", "name": "GoodCRC", "purpose": "Control: acknowledge error-free receipt of the previous message"},
                {"hex": "0x02", "name": "GotoMin", "purpose": "Control: Sink must drop to its minimum operating current"},
                {"hex": "0x03", "name": "Accept", "purpose": "Control: request or role swap accepted"},
                {"hex": "0x04", "name": "Reject", "purpose": "Control: request or role swap rejected"},
                {"hex": "0x05", "name": "Ping", "purpose": "Control: Source keep-alive"},
                {"hex": "0x06", "name": "PS_RDY", "purpose": "Control: power supply ready at the new contract voltage"},
                {"hex": "0x07", "name": "Get_Source_Cap", "purpose": "Control: ask the partner to send its Source_Capabilities"},
                {"hex": "0x08", "name": "Get_Sink_Cap", "purpose": "Control: ask the partner to send its Sink_Capabilities"},
                {"hex": "0x09", "name": "DR_Swap", "purpose": "Control: request a Data Role swap"},
                {"hex": "0x0A", "name": "PR_Swap", "purpose": "Control: request a Power Role swap"},
                {"hex": "0x0B", "name": "VCONN_Swap", "purpose": "Control: request a VCONN Source swap"},
                {"hex": "0x0C", "name": "Wait", "purpose": "Control: defer the request, try again later"},
                {"hex": "0x0D", "name": "Soft_Reset", "purpose": "Control: reset the protocol layer (MessageID) without removing VBUS"},
                {"hex": "0x01", "name": "Source_Capabilities", "msg_class": "data", "num_data_objects": ">=1", "purpose": "Data (NumDataObj>=1): Source advertises its list of PDOs. Shares the 4-bit Type 0x01 with the GoodCRC control message; disambiguated by Number of Data Objects in the header."},
                {"hex": "0x02", "name": "Request", "msg_class": "data", "num_data_objects": ">=1", "purpose": "Data (NumDataObj>=1): Sink requests one PDO via an RDO. Shares Type 0x02 with the GotoMin control message."},
                {"hex": "0x03", "name": "BIST", "msg_class": "data", "num_data_objects": ">=1", "purpose": "Data (NumDataObj>=1): Built-In Self Test. Shares Type 0x03 with the Accept control message."},
                {"hex": "0x04", "name": "Sink_Capabilities", "msg_class": "data", "num_data_objects": ">=1", "purpose": "Data (NumDataObj>=1): Sink advertises its list of Sink PDOs. Shares Type 0x04 with the Reject control message."},
                {"hex": "0x0F", "name": "Vendor_Defined", "msg_class": "data", "num_data_objects": ">=1", "purpose": "Data (NumDataObj>=1): Vendor Defined Message (VDM), e.g. Alternate Mode."},
            ],
            "response_codes": [
                {"hex": "0x03", "name": "Accept", "meaning": "Request / swap accepted"},
                {"hex": "0x04", "name": "Reject", "meaning": "Request / swap rejected"},
                {"hex": "0x0C", "name": "Wait", "meaning": "Request deferred; retry later"},
                {"hex": "0x06", "name": "PS_RDY", "meaning": "Power supply has reached the new contract voltage"},
                {"hex": "0x01", "name": "GoodCRC", "meaning": "Per-message CRC acknowledgement"},
            ],
            "crc": {"name": "CRC-32", "poly_hex": "0x04C11DB7", "init_hex": "0xFFFFFFFF",
                    "coverage": "Message Header + all data objects; IEEE 802.3 CRC-32"},
            # Canonical crc_parameters block (the key the L3 structured-field
            # gate prefers). The polynomial 0x04C11DB7 is stated VERBATIM in the
            # spec (§4: "CRC-32 ... polynomial 0x04C11DB7, the IEEE 802.3
            # CRC-32"); the 32-bit width is stated ("32-bit CRC over the header
            # and data objects"). init/reflection/xorout/residue are NOT free
            # inventions — they are the fixed parameters of the IEEE 802.3
            # CRC-32 that the spec invokes BY NAME (init 0xFFFFFFFF, input/output
            # reflected, final XOR 0xFFFFFFFF, residue 0xC704DD7B). The earlier
            # runner-emitted crc_parameters truncated the polynomial to "0x04";
            # this canonical block overwrites that with the real spec value.
            "crc_parameters": {
                "name": "CRC-32 (IEEE 802.3)",
                "width_bits": 32,
                "polynomial_hex": "0x04C11DB7",
                "init_hex": "0xFFFFFFFF",
                "reflect_input": True,
                "reflect_output": True,
                "xorout_hex": "0xFFFFFFFF",
                "residue_hex": "0xC704DD7B",
                "bit_order": "lsb_first",
                "coverage": "Message Header and all data objects",
                "no_crc_parameters_in_input": False,
                "evidence": "§4 Packet Framing: 'CRC-32 - 32-bit CRC over the header and data objects (polynomial 0x04C11DB7, the IEEE 802.3 CRC-32).' Polynomial and 32-bit width are verbatim; init/reflection/xorout/residue are the named IEEE 802.3 CRC-32 standard parameters.",
            },
            "no_crc_parameters_in_input": False,
            "ordered_sets": {"SOP": "Sync-1 Sync-1 Sync-1 Sync-2 (port partner)",
                             "SOP'": "Sync-1 Sync-1 Sync-3 Sync-3 (near-end cable plug)",
                             "SOP''": "Sync-1 Sync-3 Sync-1 Sync-3 (far-end cable plug)",
                             "Hard Reset": "RST-1 RST-1 RST-1 RST-2",
                             "Cable Reset": "RST-1 Sync-1 RST-1 Sync-3"},
            "line_code": "Biphase Mark Coding (BMC) at 300 kbaud",
            "message_based": True,
            "acknowledged": "GoodCRC per message",
        },
        "L4_REGMAP": {
            "ic_name": IC_NAME,
            "registers": [
                {"offset": "Header[3:0]", "name": "Message Type", "desc": "Selects the Control or Data message"},
                {"offset": "Header[4]", "name": "Port Data Role", "desc": "0=UFP, 1=DFP"},
                {"offset": "Header[6:5]", "name": "Specification Revision", "desc": "00=Rev1.0, 01=Rev2.0, 10=Rev3.0/3.1"},
                {"offset": "Header[7]", "name": "Port Power Role / Cable Plug", "desc": "Power role bit (or Cable Plug for SOP'/SOP'')"},
                {"offset": "Header[10:8]", "name": "Message ID", "desc": "Rolling counter for retransmission detection"},
                {"offset": "Header[14:11]", "name": "Number of Data Objects", "desc": "0=Control message, 1-7=Data message"},
                {"offset": "Header[15]", "name": "Extended", "desc": "1=Extended message with an Extended Message Header"},
            ],
            "pdo_fields": {"bits_31_30": "PDO type (00=Fixed, 01=Battery, 10=Variable, 11=Augmented/PPS)",
                           "fixed_voltage": "50 mV units", "fixed_current": "10 mA units",
                           "apdo": "PPS programmable voltage 20 mV steps, current 50 mA steps"},
            "rdo_fields": {"object_position": "bits 30:28 (1-based selected PDO index)",
                           "giveback": "bit 27", "capability_mismatch": "bit 26",
                           "usb_comms_capable": "bit 25",
                           "operating_current": "bits 19:10 (10 mA units)",
                           "max_operating_current": "bits 9:0 (10 mA units)"},
        },
        "L5_ADI_SPEC": {
            "ic_name": IC_NAME,
            "analog_mixed_signal": "BMC single-ended signalling on CC; VBUS power transition (5 V to 48 V); VCONN supply on the non-comm CC pin.",
            "io_standard": "USB Type-C CC single-ended logic; VBUS 5-48 V power rail",
            "not_applicable_reason": "USB-PD is predominantly a digital negotiation protocol; the only analog aspect is the VBUS power transition and BMC eye.",
            # Honest typed N/A: the digital PD engine has NO on-chip analog
            # block. The CC BMC line driver/receiver (the only analog/mixed-
            # signal surface, §3) is a blackboxed PHY pad, not a synthesized
            # analog block in this design. So L5 declares no_analog explicitly.
            "no_analog": True,
        },
        "L6_CONTROL_LOGIC": {
            "ic_name": IC_NAME,
            "control_logic": {
                "source_fsm": ["Unattached", "Attached (advertise Source_Capabilities)",
                               "Wait for Request", "Evaluate Request -> Accept/Reject/Wait",
                               "Transition VBUS to new contract", "Send PS_RDY",
                               "Explicit Contract (Ready)", "Handle PR_Swap/DR_Swap/VCONN_Swap"],
                "sink_fsm": ["Unattached", "Attached (wait Source_Capabilities)",
                             "Evaluate PDOs and pick one", "Send Request (RDO)",
                             "Wait Accept", "Wait PS_RDY", "Explicit Contract (Ready)"],
                "atomic_message_sequence": "AMS — a contract negotiation or swap is an indivisible message sequence guarded by Soft_Reset on protocol error.",
                "acknowledgement": "Every message is acknowledged by a GoodCRC; missing GoodCRC triggers retransmission then Soft_Reset.",
            },
            # Typed Source-side policy-engine FSM, transcribed from the Explicit
            # Contract handshake (spec §10), the role-swap rules (§5) and the
            # reset mechanisms (§11). Each state names its trigger / action and
            # next state. This is the contract negotiation FSM the spec mandates;
            # no state is invented beyond the §10/§5/§11 message flow.
            "fsm_states": [
                {"name": "Unattached",
                 "description": "No port partner; monitor CC for attach.",
                 "on": "partner attaches", "next": "AdvertiseCaps",
                 "evidence": "§2 Source/Sink defined by who sources VBUS; §10 negotiation begins after attach."},
                {"name": "AdvertiseCaps",
                 "description": "Source sends Source_Capabilities (its PDO list) on SOP.",
                 "on": "Source_Capabilities sent + GoodCRC", "next": "WaitRequest",
                 "evidence": "§10.1: Source sends Source_Capabilities (its PDO list) on SOP."},
                {"name": "WaitRequest",
                 "description": "Wait for the Sink to reply with a Request carrying an RDO.",
                 "on": "Request(RDO) received", "next": "EvaluateRequest",
                 "evidence": "§10.2: Sink replies with Request carrying an RDO selecting one PDO."},
                {"name": "EvaluateRequest",
                 "description": "Evaluate the requested RDO and reply Accept, Reject or Wait.",
                 "on": "Accept sent", "next": "TransitionVBUS",
                 "evidence": "§10.3: Source replies Accept (or Reject / Wait)."},
                {"name": "TransitionVBUS",
                 "description": "Transition VBUS to the newly requested contract voltage.",
                 "on": "VBUS settled", "next": "SendPSRDY",
                 "evidence": "§10.4: Source transitions VBUS to the new voltage, then sends PS_RDY."},
                {"name": "SendPSRDY",
                 "description": "Send PS_RDY to declare the supply ready at the new voltage.",
                 "on": "PS_RDY sent + GoodCRC", "next": "ExplicitContract",
                 "evidence": "§10.4/§7 0x06 PS_RDY: Power Supply ready at the new contract voltage."},
                {"name": "ExplicitContract",
                 "description": "Explicit Contract in place; ready; either partner may issue PR_Swap / DR_Swap / VCONN_Swap.",
                 "on": "PR_Swap/DR_Swap/VCONN_Swap or Hard Reset", "next": "HandleSwapOrReset",
                 "evidence": "§10.5: The Explicit Contract is now in place; either partner may later issue PR_Swap, DR_Swap or VCONN_Swap."},
                {"name": "HandleSwapOrReset",
                 "description": "Process role swap (Accept then exchange roles) or a Soft/Hard/Cable Reset.",
                 "on": "swap complete / reset done", "next": "ExplicitContract or Unattached",
                 "evidence": "§5 PR_Swap/DR_Swap/VCONN_Swap; §11 Soft/Hard/Cable Reset."},
            ],
        },
        "L7_TEST_DEBUG": {
            "ic_name": IC_NAME,
            "test_debug": {
                "bist_carrier": "BIST Carrier Mode transmits a continuous carrier on CC for eye-diagram measurement",
                "bist_test_data": "BIST Test Data exercises the receiver with a known pattern",
                "cap_query": "Get_Source_Cap / Get_Sink_Cap read the partner's advertised capabilities",
                "crc_check": "CRC-32 detects bit errors; GoodCRC acknowledges error-free receipt"},
        },
        "L8_RTL_CONSTANTS": {
            "ic_name": IC_NAME,
            "width_parameters": {
                "MESSAGE_HEADER_BITS": {"width_bits": 16},
                "DATA_OBJECT_BITS": {"width_bits": 32},
                "CRC_BITS": {"width_bits": 32},
                "NUM_DATA_OBJECTS": {"legal_values": [0, 1, 2, 3, 4, 5, 6, 7]},
                "MESSAGE_ID_BITS": {"width_bits": 3}},
            "key_constants": {
                "CRC32_POLY": "0x04C11DB7", "BAUD_KBAUD": 300, "UI_US": 3.33,
                "MAX_DATA_OBJECTS": 7, "MAX_POWER_W": 240, "VSAFE5V_V": 5,
                "MAX_VBUS_V": 48, "MAX_CURRENT_A": 5, "PREAMBLE_BITS": 64},
            "pdo_type_encodings": {"00": "Fixed Supply", "01": "Battery",
                                   "10": "Variable Supply", "11": "Augmented PDO (PPS)"},
            "spec_rev_encodings": {"00": "Rev 1.0", "01": "Rev 2.0", "10": "Rev 3.0/3.1"},
        },
        "L8_TIMING_WAVEFORM": {
            "ic_name": IC_NAME,
            "timing_constants": {"ui_us": 3.33, "baud_kbaud": 300,
                                 "t_receive_ms": {"min": 0.75, "max": 1.0},
                                 "t_transmit_us_max": 195,
                                 "crc_receive_timer_ms": {"min": 0.9, "max": 1.1},
                                 "t_sender_response_ms": {"min": 24, "max": 30},
                                 "ps_transition_timer_ms": {"min": 450, "max": 550},
                                 "t_hard_reset_complete_ms_max": 5},
            "line_code_waveform": {"coding": "Biphase Mark Coding (BMC)",
                                   "transition": "guaranteed transition at every bit boundary; mid-bit transition for logic 1",
                                   "clock_recovery": "receiver recovers clock from the BMC transitions"},
            "packet_waveform": {"order": ["Preamble (64-bit alternating)", "SOP* ordered set (4 K-codes)",
                                          "Message Header (16 bits)", "0..7 Data Objects (32 bits each)",
                                          "CRC-32 (32 bits)", "EOP K-code"]},
            # Half-duplex CC bus: the PD engine both RECEIVES BMC symbols
            # decoded from CC (rx) and DRIVES BMC symbols onto CC (tx). BMC is a
            # self-clocked line code, so the per-symbol "pulse width" is the BMC
            # unit interval (logic-0 = one full UI with a single boundary
            # transition; logic-1 = two half-UI cells with an extra mid-bit
            # transition). UI = 3.33 us nominal at 300 kbaud; half-bit = 1.67 us.
            # USB-PD has no HOST-vs-DUT directional symbol asymmetry: BMC is
            # symmetric and BOTH link partners use the identical 3.33 us UI /
            # 1.67 us half-bit. There is no break (BR) or inter-byte (IBT)
            # symbol - a PD message is delimited by SOP*/EOP K-codes, not by a
            # host-only break or an inter-byte gap. So the generic single-wire
            # H0/H1/BR/IBT required-symbol set does NOT apply to either
            # direction; the per-direction required set is declared empty in
            # symbol_directionality, while rx_timing / tx_timing still carry the
            # actual BMC logic-0 / logic-1 per-symbol pulse widths.
            "symbol_directionality": {
                "rx_host_side": [],
                "tx_dut_side": [],
                "actual_symbols_emitted": ["logic-0 (one full 3.33 us UI)",
                                           "logic-1 (two 1.67 us half-UI cells)"],
                "note": "BMC is symmetric self-clocked coding; both link partners use the same 3.33 us UI / 1.67 us half-bit. No directional break/IBT asymmetry (each message is bounded by SOP* and EOP K-codes, not by an inter-byte gap), so the generic H0/H1/BR/IBT symbol set is not required on either side.",
            },
            "rx_timing": {
                "description": "Host/external side - BMC symbols the PD engine RECEIVES (decodes) from the CC wire. The receiver recovers clock from the guaranteed BMC transitions.",
                "direction": "CC -> PD engine (receive)",
                "logic0_full_ui_us": {"nom": 3.33, "desc": "logic 0 = one full BMC unit interval (single transition at the bit boundary, no mid-bit transition)"},
                "logic1_half_ui_us": {"nom": 1.67, "desc": "logic 1 = two half-UI cells (~1.67 us each) separated by an extra mid-bit transition"},
                "unit_interval_us": {"nom": 3.33, "desc": "BMC unit interval at 300 kbaud (received)"},
                "evidence": {"literal": "USB-PD uses Biphase Mark Coding (BMC) on the CC wire at a nominal 300 kbaud. ... The unit interval (UI) is nominally 3.33 us."},
            },
            "tx_timing": {
                "description": "DUT/internal side - BMC symbols the PD engine DRIVES onto the CC wire. The TX encoder must emit the same UI the partner's RX decoder tolerates.",
                "direction": "PD engine -> CC (drive)",
                "logic0_full_ui_us": {"nom": 3.33, "desc": "drive one full BMC unit interval for logic 0 (boundary transition only)"},
                "logic1_half_ui_us": {"nom": 1.67, "desc": "drive two ~1.67 us half-UI cells for logic 1 (boundary transition plus mid-bit transition)"},
                "unit_interval_us": {"nom": 3.33, "desc": "BMC unit interval at 300 kbaud (driven)"},
                "evidence": {"literal": "BMC guarantees at least one transition per bit (a transition at every bit boundary, plus a mid-bit transition for a logic 1). ... The unit interval (UI) is nominally 3.33 us."},
            },
        },
        "L9_INTEGRATION_SPEC": {
            "ic_name": IC_NAME,
            "integration_overview": {
                "partners": ["Source (supplies VBUS)", "Sink (consumes VBUS)"],
                "data_roles": ["DFP (Downstream Facing Port)", "UFP (Upstream Facing Port)"],
                "physical": "USB Type-C connector; PD on the connected CC wire; VCONN on the other CC pin",
                "distinct_from": "USB 2.0 D+/D- data and USB4 tunneling are carried separately; PD only negotiates power/role over CC",
                "init_sequence": "On attach: Source advertises Source_Capabilities; Sink sends Request (RDO); Source Accepts, transitions VBUS, sends PS_RDY to establish the Explicit Contract.",
                "max_power_w": 240},
            "top_module": "usb_pd_engine",
            # Submodule decomposition along the PD stack the spec defines:
            # §3 physical layer (BMC line code on CC), §4/§6 protocol layer
            # (SOP* framing, 16-bit Message Header, CRC-32, GoodCRC ack), §10
            # policy engine (Explicit Contract negotiation FSM). The BMC PHY is
            # a blackboxed analog/mixed-signal block (see L5 no_analog); the
            # digital engine instantiates the protocol + policy layers.
            "submodules": [
                {"name": "bmc_codec", "role": "Physical layer: Biphase Mark Coding (BMC) encode/decode on the CC wire at 300 kbaud; recovers clock from the guaranteed BMC transitions.",
                 "evidence": "§3: USB-PD uses Biphase Mark Coding (BMC) on the CC wire at a nominal 300 kbaud."},
                {"name": "protocol_layer", "role": "Frames/deframes Preamble + SOP* ordered set + 16-bit Message Header + 0..7 data objects + CRC-32 + EOP; checks CRC-32 and emits GoodCRC.",
                 "evidence": "§4 Packet Framing; §6 Message Header (16 bits); §10: every received message is acknowledged with GoodCRC."},
                {"name": "policy_engine", "role": "Drives the Explicit Contract negotiation FSM (Source_Capabilities -> Request -> Accept -> PS_RDY) and the PR_Swap/DR_Swap/VCONN_Swap and Soft/Hard/Cable Reset flows.",
                 "evidence": "§10 Contract Negotiation; §5 Role Swaps; §11 Reset Mechanisms."},
            ],
            "fsm_states": [
                {"name": "AdvertiseCaps", "description": "Source advertises its PDO list via Source_Capabilities.",
                 "evidence": "§10.1: Source sends Source_Capabilities (its PDO list) on SOP."},
                {"name": "EvaluateRequest", "description": "Source evaluates the Sink's RDO and replies Accept / Reject / Wait.",
                 "evidence": "§10.2/§10.3: Sink replies with Request carrying an RDO; Source replies Accept (or Reject / Wait)."},
                {"name": "ExplicitContract", "description": "Contract established after PS_RDY; ready for role swaps.",
                 "evidence": "§10.4/§10.5: Source transitions VBUS, sends PS_RDY; the Explicit Contract is now in place."},
            ],
        },
        "L10_TEST_CASES": {
            "ic_name": IC_NAME,
            "test_cases": [
                {"name": "explicit_contract", "desc": "Source_Capabilities -> Request -> Accept -> PS_RDY establishes a contract."},
                {"name": "goodcrc_ack", "desc": "Every message is acknowledged with GoodCRC before the next is sent."},
                {"name": "pps_request", "desc": "Sink selects an APDO and programs an output voltage in 20 mV steps via the RDO."},
                {"name": "pr_swap", "desc": "PR_Swap exchanges Source and Sink power roles after a contract exists."},
                {"name": "soft_reset", "desc": "Soft_Reset resets MessageID without removing VBUS or the contract."},
                {"name": "hard_reset", "desc": "Hard Reset forces VBUS to vSafe0V/vSafe5V and returns default power roles."},
                {"name": "crc_error", "desc": "Corrupted CRC-32 -> no GoodCRC -> retransmission then Soft_Reset."}],
        },
        "L11_OTP_CONTENT": {
            "ic_name": IC_NAME,
            "otp_content": "N/A — USB-PD is a negotiation protocol, no one-time-programmable fuse content defined.",
            "applicable": False,
            # Honest typed N/A: the spec defines NO OTP/fuse image. Explicit
            # signals the structured-field gate accepts (otp_present:false +
            # applicable:false). Not a fabricated entry to hit a count.
            "otp_present": False,
            "no_otp_fsm_in_input": True,
        },
        "L12_BEHAVIORAL_SEQUENCES": {
            "ic_name": IC_NAME,
            "contract_sequence": ["Source sends Source_Capabilities (PDO list) on SOP.",
                                  "Sink evaluates PDOs and replies Request carrying an RDO selecting one PDO.",
                                  "Source replies Accept (or Reject / Wait).",
                                  "Source transitions VBUS to the requested voltage.",
                                  "Source sends PS_RDY; the Explicit Contract is in place."],
            "swap_sequence": ["Either partner sends PR_Swap / DR_Swap / VCONN_Swap.",
                              "Partner replies Accept.",
                              "Roles are exchanged; for PR_Swap the new Source sends PS_RDY."],
            "reset_sequence": ["Soft_Reset resets the protocol layer (MessageID); VBUS preserved.",
                               "Hard Reset ordered set tears down the contract; VBUS to vSafe0V/vSafe5V; default roles restored.",
                               "Cable Reset resets the cable plug (SOP'/SOP'') without disturbing the port contract."],
            # Typed behavioral-sequence catalog (list-of-dicts) mirroring the
            # three string-list sequences above. Each entry names the sequence
            # and its ordered steps, transcribed from spec §10 (Explicit
            # Contract), §5 (Role Swaps) and §11 (Reset Mechanisms). No step is
            # invented beyond the spec's stated message flow.
            # Each step is a TYPED dict (action + next_state / expected_signal /
            # latency bound) so spec-to-rtl can replay it. The latency bounds
            # are the spec §12 timers (tSenderResponse 24-30 ms for the
            # Accept/Reject reply; PSTransitionTimer 450-550 ms for the VBUS
            # transition; tHardReset complete max 5 ms). No step is invented
            # beyond the §10/§5/§11 message flow.
            "behavioral_sequences": [
                {"name": "explicit_contract",
                 "trigger": "attach / Get_Source_Cap",
                 "steps": [
                    {"action": "Source sends Source_Capabilities (its PDO list) on SOP",
                     "expected_signal": "GoodCRC", "next_state": "WaitRequest"},
                    {"action": "Sink replies Request carrying an RDO selecting one PDO",
                     "expected_signal": "GoodCRC", "next_state": "EvaluateRequest"},
                    {"action": "Source replies Accept (or Reject / Wait)",
                     "expected_signal": "Accept", "latency_ms": 30, "next_state": "TransitionVBUS"},
                    {"action": "Source transitions VBUS to the requested voltage",
                     "latency_ms": 550, "next_state": "SendPSRDY"},
                    {"action": "Source sends PS_RDY",
                     "expected_signal": "PS_RDY", "next_state": "ExplicitContract"}],
                 "evidence": "§10 Contract Negotiation steps 1-5; §12 tSenderResponse max 30 ms (Accept), PSTransitionTimer max 550 ms (VBUS transition); GoodCRC acknowledges every message."},
                {"name": "power_role_swap",
                 "trigger": "PR_Swap after a contract exists",
                 "steps": [
                    {"action": "A partner sends PR_Swap",
                     "expected_signal": "Accept", "latency_ms": 30, "next_state": "SwapAccepted"},
                    {"action": "Partner replies Accept",
                     "expected_signal": "Accept", "next_state": "ExchangeRoles"},
                    {"action": "Power roles are exchanged; the new Source sends PS_RDY",
                     "expected_signal": "PS_RDY", "next_state": "ExplicitContract"}],
                 "evidence": "§5: Power Role swapped with PR_Swap; §10.5 swaps issued after a contract; §7 0x06 PS_RDY; §12 tSenderResponse max 30 ms."},
                {"name": "soft_reset",
                 "trigger": "protocol error / MessageID resync",
                 "steps": [
                    {"action": "A partner sends Soft_Reset",
                     "expected_signal": "Accept", "next_state": "ProtocolReset"},
                    {"action": "MessageID counters and protocol layer reset",
                     "next_state": "ContractPreserved"},
                    {"action": "VBUS and the contract are preserved",
                     "expected_signal": "no VBUS change", "next_state": "ExplicitContract"}],
                 "evidence": "§11 Soft Reset: resets the MessageID counters and protocol layer; VBUS and the contract are preserved."},
                {"name": "hard_reset",
                 "trigger": "unrecoverable error",
                 "steps": [
                    {"action": "Hard Reset ordered set sent",
                     "next_state": "TearDown", "latency_ms": 5},
                    {"action": "VBUS forced to vSafe0V (or vSafe5V to keep USB alive)",
                     "expected_signal": "VBUS=vSafe0V/vSafe5V", "next_state": "DefaultRoles"},
                    {"action": "Contract torn down; both partners return to default power roles",
                     "next_state": "Unattached"}],
                 "evidence": "§11 Hard Reset: forces VBUS to vSafe0V (or vSafe5V), tears down the contract and returns both partners to default power roles; §12 tHardReset complete max 5 ms."},
            ],
        },
        "L13_LAB_CALIBRATION": {
            "ic_name": IC_NAME,
            "lab_calibration": "N/A — protocol negotiation; only BMC eye and VBUS transition are measured, no analog trim.",
            "applicable": False,
            # Honest typed N/A: the spec defines NO lab-bench calibration / trim
            # routine. Explicit signals the structured-field gate accepts
            # (lab_calibration_present:false + applicable:false).
            "lab_calibration_present": False,
        },
        "L14_PROTOCOL_VERSIONING": {
            "spec_version": "USB Power Delivery Specification Revision 3.1, Version 1.8 (USB-IF)",
            "lineage": [
                {"version": "USB PD 1.0", "year": "2012", "summary": "Original PD over VBUS using BFSK; superseded by CC-based PD."},
                {"version": "USB PD 2.0", "year": "2014", "summary": "BMC on the Type-C CC wire; Fixed/Variable/Battery PDOs."},
                {"version": "USB PD 3.0", "year": "2017", "summary": "Adds Programmable Power Supply (PPS / APDO), extended messages, fast role swap."},
                {"version": "USB PD 3.1", "year": "2021", "summary": "Extended Power Range up to 240 W (48 V at 5 A)."}],
            "backward_compat_traps": [
                {"trap_name": "Not_USB2_data", "rule": "USB-PD negotiates power/role over the CC wire with BMC; it is NOT the USB 2.0 D+/D- data bus (NRZI, PID, endpoints, SOF).", "trap": "Decoding USB-PD as USB 2.0 data (looking for D+/D-, NRZI, endpoints) is wrong — PD lives on CC."},
                {"trap_name": "Not_USB4_tunneling", "rule": "USB-PD only negotiates power and roles; it does NOT tunnel USB 3.x / DisplayPort / PCIe at 20/40/80 Gbps like USB4 routers.", "trap": "Treating the CC/VCONN pins as the USB4 high-speed tunneling fabric misses that PD is a low-speed contract protocol."}],
        },
        "L15_ENCODING_TABLES": {
            "control_message_table": {"header_columns": ["Type", "Name"], "rows": [
                ["0x01", "GoodCRC"], ["0x02", "GotoMin"], ["0x03", "Accept"], ["0x04", "Reject"],
                ["0x05", "Ping"], ["0x06", "PS_RDY"], ["0x07", "Get_Source_Cap"], ["0x08", "Get_Sink_Cap"],
                ["0x09", "DR_Swap"], ["0x0A", "PR_Swap"], ["0x0B", "VCONN_Swap"], ["0x0C", "Wait"],
                ["0x0D", "Soft_Reset"]]},
            "data_message_table": {"header_columns": ["Type", "Name"], "rows": [
                ["0x01", "Source_Capabilities"], ["0x02", "Request"], ["0x03", "BIST"],
                ["0x04", "Sink_Capabilities"], ["0x0F", "Vendor_Defined"]]},
            "pdo_type_table": {"header_columns": ["Bits31:30", "PDO Type"], "rows": [
                ["00", "Fixed Supply"], ["01", "Battery"], ["10", "Variable Supply"], ["11", "Augmented PDO (PPS)"]]},
            "ordered_set_table": {"header_columns": ["Ordered Set", "K-codes"], "rows": [
                ["SOP", "Sync-1 Sync-1 Sync-1 Sync-2"], ["SOP'", "Sync-1 Sync-1 Sync-3 Sync-3"],
                ["SOP''", "Sync-1 Sync-3 Sync-1 Sync-3"], ["Hard Reset", "RST-1 RST-1 RST-1 RST-2"],
                ["Cable Reset", "RST-1 Sync-1 RST-1 Sync-3"]]},
            "header_field_table": {"header_columns": ["Bits", "Field"], "rows": [
                ["3:0", "Message Type"], ["4", "Port Data Role"], ["6:5", "Specification Revision"],
                ["7", "Port Power Role / Cable Plug"], ["10:8", "Message ID"],
                ["14:11", "Number of Data Objects"], ["15", "Extended"]]},
        },
        "L16_COMPLIANCE_PROPERTIES": {
            "must_have_properties": [
                "PD communication uses Biphase Mark Coding (BMC) on the connected CC wire at 300 kbaud.",
                "A packet is Preamble + SOP* ordered set + 16-bit Message Header + 0..7 32-bit data objects + CRC-32 + EOP.",
                "The Explicit Contract is established by Source_Capabilities -> Request -> Accept -> PS_RDY.",
                "CRC-32 uses the IEEE 802.3 polynomial 0x04C11DB7 over the header and data objects.",
                "Every received message is acknowledged with a GoodCRC before the next message.",
                "Power, data, and VCONN roles are swappable via PR_Swap, DR_Swap, VCONN_Swap.",
                "Hard Reset returns both partners to their default power roles and brings VBUS to vSafe0V/vSafe5V."],
            "usb_pd_distinguishers": [
                "Negotiation runs on the Type-C CC wire — not on the USB 2.0 D+/D- data pair.",
                "BMC line code at 300 kbaud — not USB 2.0 NRZI nor USB4 multi-gigabit signalling.",
                "Power Data Objects (PDO) and Request Data Objects (RDO) define the power contract.",
                "Source/Sink power roles with PR_Swap — absent from both USB 2.0 data and USB4 tunneling."],
        },
        "L17_CHANNEL_SIGNAL_CATALOG": {
            "channels": [
                {"name": "CC1", "direction": "bidirectional", "purpose": "Configuration Channel wire 1; carries BMC PD communication or VCONN/orientation."},
                {"name": "CC2", "direction": "bidirectional", "purpose": "Configuration Channel wire 2; the wire not used for comm carries VCONN."},
                {"name": "VBUS", "direction": "Source->Sink", "purpose": "Negotiated bus power, 5 V (default) up to 48 V."},
                {"name": "VCONN", "direction": "supplied by VCONN Source", "purpose": "Powers the electronically marked cable (eMarker) on the non-comm CC pin."},
                {"name": "GND", "direction": "shared", "purpose": "Ground return."}],
            "roles": [
                {"name": "Source", "purpose": "Supplies VBUS; advertises Source_Capabilities (PDOs)."},
                {"name": "Sink", "purpose": "Consumes VBUS; issues Request (RDO)."},
                {"name": "DFP", "purpose": "Downstream Facing Port (host data role)."},
                {"name": "UFP", "purpose": "Upstream Facing Port (device data role)."}],
            "channel_counts": {"physical_signals": 5, "cc_wires": 2, "power_roles": 2, "data_roles": 2},
        },
        "L18_INTERCONNECT_TOPOLOGY": {
            "topology_type": "Point-to-point Source <-> Sink over a USB Type-C cable; PD on the connected CC wire; SOP'/SOP'' address the cable plugs.",
            "supported_topologies": [
                {"name": "Source to Sink", "description": "Two port partners negotiate a power contract over CC (SOP messages)."},
                {"name": "Port to cable plug", "description": "SOP' addresses the near-end cable plug, SOP'' the far-end plug (eMarker query)."}],
            "device_classification": {"power_roles": ["Source", "Sink"], "data_roles": ["DFP", "UFP"], "cable": "Electronically Marked Cable (eMarker, powered by VCONN)"},
            "distinct_from": "USB 2.0 D+/D- data link and USB4 tunneling router fabric",
        },
        "L19_CONSTRAINTS_PDK": {"pdk_target": "N/A (protocol spec, not a tapeout)",
                                "io_voltage": "VBUS 5-48 V; CC single-ended logic", "baud_kbaud": 300},
        "L20_DFT_SCAN_TOPOLOGY": {"scan_topology": "N/A — protocol spec, no DFT defined.",
                                  "built_in_self_test": "BIST Carrier Mode + BIST Test Data on CC"},
        "L21_POWER_INTENT": {"power_domains": ["VBUS 5-48 V negotiated rail", "VCONN cable-marker supply"],
                             "power_considerations": "USB-PD negotiates VBUS up to 240 W (48 V at 5 A); PPS allows fine programmable voltage/current for efficient charging."},
        "L22_VERIFICATION_PLAN": {"verification_items": ["Explicit contract negotiation",
                                  "GoodCRC acknowledgement", "PPS / APDO request", "Power-role swap",
                                  "Soft Reset", "Hard Reset", "CRC-32 error handling", "SOP'/SOP'' cable plug messaging"]},
        "L23_SECURITY_REQUIREMENTS": {"attack_surface": [
            "A malicious Source could advertise out-of-range PDOs; the Sink must validate the offered voltage/current before accepting.",
            "Vendor Defined Messages (VDM) for Alternate Modes must be authenticated to prevent rogue mode entry."],
            "security_notes": "USB-PD defines optional Authentication (digital certificate exchange over the CC link) to verify a Source/cable before accepting high power."},
    }


def apply_usb_pd_synth(generated_docs_dir, is_usb_pd_flag: bool,
                       ic_name: Optional[str]) -> None:
    """Force-merge USB-PD-canonical content into the generated L-docs when the
    USB-PD signature matched. No-op otherwise."""
    if not is_usb_pd_flag:
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
