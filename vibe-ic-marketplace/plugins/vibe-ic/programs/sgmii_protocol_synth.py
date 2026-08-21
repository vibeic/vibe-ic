"""Serial-GMII (SGMII) protocol synth helper.

Drop-in protocol synth discovered by the runner's generic auto-dispatch
(`AUTO_DISPATCH = True`). Applies the Cisco Serial-GMII (SGMII) Specification
canonical content to L1-L23 when the SGMII structural signature is present.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
read from the L-doc / input_doc CONTENT blob only (never a filename or folder
name): the SGMII name token, the GMII-over-SerDes serialization model, the
fixed 1.25 GBd line rate, 8B/10B line coding with the /K28.5/ comma, and the
redefined 16-bit Auto-Negotiation Config_Reg that embeds Link Speed (bits
11:10), Duplex (bit 12) and Link (bit 15).

Sibling disambiguation — SGMII vs the Ethernet siblings (ethernet,
automotive_ethernet, ethernet_800g) and RGMII.
  * SGMII is the MAC<->PHY SERDES LINK, not the Ethernet MAC frame layer.
    A plain Ethernet-MAC spec is preamble/SFD + 48-bit MAC addresses + the
    Ethernet FCS (CRC-32) frame; it has no SGMII name token, no fixed 1.25 GBd
    serialized-GMII lane and no redefined SGMII Config_Reg. The detector
    REQUIRES the "sgmii" name token, so an Ethernet-MAC-primary spec
    (ethernet / automotive_ethernet / ethernet_800g) can never false-fire.
  * RGMII is the PARALLEL reduced-pin GMII (two 4-bit DDR data buses at 125
    MHz). SGMII serializes GMII onto ONE 1.25 GBd differential pair with
    8B/10B; the detector requires the serial 1.25 GBd + 8B/10B signature,
    which RGMII lacks.
The detector DEFERS (returns False) unless the SGMII-only structural quorum is
met AND the "sgmii" name token is present, so a sibling Ethernet / RGMII /
1000BASE-X-only spec cannot false-fire.

Public entry: ``apply_sgmii_synth(generated_docs_dir, is_sgmii_flag, ic_name)``.
Module-level ``is_sgmii(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp

# Generic auto-dispatch opt-in (read by phase1_doc_one_shot_runner [14e2b/15]).
AUTO_DISPATCH = True
IC_NAME = "Serial Gigabit Media Independent Interface (SGMII)"

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


def is_sgmii(blob: str) -> bool:
    """Content-only SGMII detector with Ethernet-MAC / RGMII MUTEX.

    NECESSARY: the "sgmii" / "serial-gmii" name token. SUFFICIENT extra:
    the GMII-over-SerDes + 1.25 GBd + 8B/10B + redefined Config_Reg quorum.
    """
    if not blob:
        return False
    low = blob.lower()
    # SUBJECT-DOMINANCE (v0.2.13): "SGMII" is referenced inside the full IEEE
    # 802.3 spec (it is a recognised PHY interface), so a whole-blob name-token
    # scan fires on the ethernet benchmark. To fire ONLY on a doc that is ABOUT
    # SGMII, the name token must appear in the blob HEAD. The runner builds the
    # auto-dispatch blob input_doc-FIRST, so the head is the source spec's
    # title/abstract — a real SGMII spec ("Serial-GMII (SGMII) Specification")
    # names it up front; the full-Ethernet doc mentions it only in a buried
    # clause. v0.1.94 subject-dominance / foreign-exclusive-defer doctrine.
    head = low[:3500]
    name_in_head = ("sgmii" in head or "serial-gmii" in head
                    or "serial gmii" in head
                    or "serial gigabit media independent interface" in head)
    if not name_in_head:
        return False
    # Name token (NECESSARY — never fires on a sibling without it).
    name_token = ("sgmii" in low
                  or "serial-gmii" in low or "serial gmii" in low
                  or "serial gigabit media independent interface" in low)
    if not name_token:
        return False
    # SGMII-only structural quorum.
    gmii_over_serdes = (
        "gmii" in low
        and ("serdes" in low or "serialized" in low or "serialize" in low
             or "differential pair" in low))
    line_rate = ("1.25 gbd" in low or "1.25 gbaud" in low
                 or "1.25 gigabaud" in low or "1.25gbd" in low
                 or "625 mhz" in low)
    eight_b_ten_b = ("8b/10b" in low or "8b10b" in low or "8b 10b" in low
                     or "k28.5" in low or "running disparity" in low)
    # Redefined Auto-Negotiation config word carrying speed/duplex/link.
    config_word = (
        ("config_reg" in low or "tx_config_reg" in low
         or "configuration ordered set" in low or "/c/" in low)
        and ("link speed" in low or "11:10" in low
             or "duplex" in low or "auto-negotiat" in low or "clause 37" in low))
    # Embedded speed/duplex/link signature in the config word.
    embedded_sdl = (("11:10" in low or "10 mbps" in low or "1000 mbps" in low)
                    and "duplex" in low)
    score = sum(bool(x) for x in
                (gmii_over_serdes, line_rate, eight_b_ten_b, config_word,
                 embedded_sdl))
    # Require GMII-over-SerDes + the redefined config word, plus a 3+ quorum.
    return gmii_over_serdes and config_word and score >= 3


# ----------------------------------------------------------------------
# Canonical SGMII content (Cisco Serial-GMII Specification, ENG-46158).
# ----------------------------------------------------------------------
def _canon():
    return {
        "L1_DATASHEET": {
            "ic_name": IC_NAME,
            "document_title": "Serial-GMII (SGMII) Specification",
            "document_number": "ENG-46158",
            "manufacturer": "Cisco Systems, Inc.",
            "revised_date": "Revision 1.8",
            "external_pins": ["TXP", "TXN", "RXP", "RXN", "TXCLKP", "TXCLKN",
                              "RXCLKP", "RXCLKN"],
            "external_pin_count": 8,
            "package": "Chip-to-chip / chip-to-module SerDes link (no dedicated package)",
            "key_features": [
                "Carries GMII (10/100/1000 Mbps Ethernet MAC<->PHY) over a single differential pair per direction",
                "Replaces the wide 10-bit parallel GMII data path with one serialized 1.25 GBd lane each way",
                "1.25 Gbaud LVDS/CML differential signaling, fixed for all Ethernet speeds",
                "Optional 625 MHz DDR source-synchronous clock",
                "8B/10B line code with running disparity and /K28.5/ comma alignment",
                "Auto-Negotiation reuses the 1000BASE-X (Clause 37) PCS with a REDEFINED 16-bit Config_Reg",
                "Config_Reg encodes Link Speed (bits 11:10), Duplex (bit 12), ACK (bit 14), Link (bit 15)",
                "GMII octet replicated x100 (10 Mbps) / x10 (100 Mbps) to hold the line rate constant",
            ],
            "io_voltage": "LVDS / CML differential",
            "clock_frequency": "1.25 GBd line rate; 625 MHz DDR clock",
            "electrical_specs": [
                {"name": "Serial line rate", "min_typ_max": {"min": 1.25, "typ": 1.25, "max": 1.25}, "unit": "GBd",
                 "conditions": "8B/10B, one differential pair per direction", "evidence": {"literal": "1.25 GBd serial line rate per direction"}},
                {"name": "DDR clock", "min_typ_max": {"min": 625, "typ": 625, "max": 625}, "unit": "MHz",
                 "conditions": "double-data-rate recovered clock option", "evidence": {"literal": "625 MHz DDR clock"}},
                {"name": "Unit interval (bit period)", "min_typ_max": {"min": 0.8, "typ": 0.8, "max": 0.8}, "unit": "ns",
                 "conditions": "1/1.25 GBd", "evidence": {"literal": "0.8 ns UI at 1.25 GBd"}},
                {"name": "Code-group period", "min_typ_max": {"min": 8, "typ": 8, "max": 8}, "unit": "ns",
                 "conditions": "10-bit 8B/10B code-group at 1.25 GBd", "evidence": {"literal": "8 ns per 10-bit code-group"}},
                {"name": "Auto-negotiation link_timer", "min_typ_max": {"min": 1.6, "typ": 1.6, "max": 1.6}, "unit": "ms",
                 "conditions": "SGMII shortened Clause-37 AN link timer", "evidence": {"literal": "1.6 ms auto-negotiation link_timer"}},
                {"name": "Payload rate (10/100/1000)", "min_typ_max": {"min": 10, "typ": 1000, "max": 1000}, "unit": "Mbps",
                 "conditions": "GMII byte replication 100x/10x at 10/100 Mbps", "evidence": {"literal": "10/100/1000 Mbps Ethernet payload"}},
            ],
        },
        "L2_FRS": {
            "ic_name": IC_NAME,
            "protocol_overview": {
                "type": "SerDes link serializing GMII (Gigabit Media Independent Interface) between an Ethernet MAC and a PHY",
                "half_duplex": False,
                "duplex": "full-duplex, one differential pair per direction",
                "serial": True,
                "replaces": "the parallel 10-bit GMII data path (and RGMII parallel DDR)",
                "line_rate_gbd": 1.25,
                "ddr_clock_mhz": 625,
                "line_code": "8B/10B with running disparity, /K28.5/ comma alignment",
                "speeds_mbps": [10, 100, 1000],
                "signals": ["TXP/TXN", "RXP/RXN", "TXCLKP/TXCLKN", "RXCLKP/RXCLKN"],
                "auto_negotiation": "1000BASE-X (Clause 37) PCS with redefined SGMII Config_Reg",
                "scope_note": "MAC<->PHY link only; NOT the Ethernet MAC frame layer (no preamble/SFD, MAC address, or CRC-32 here)",
            },
            "functional_requirements": [
                "Serialize the 8-bit GMII octet stream onto one 1.25 GBd differential pair per direction.",
                "Encode octets with 8B/10B (1000BASE-X Clause 36), maintain running disparity, align on /K28.5/.",
                "Hold the serial line at 1.25 GBd for 10/100/1000 Mbps by replicating each GMII octet x100/x10/x1.",
                "Run Clause-37-style Auto-Negotiation exchanging /C/ ordered sets carrying the 16-bit Config_Reg.",
                "PHY drives resolved Link Speed (bits 11:10), Duplex (bit 12), Link (bit 15); MAC echoes with ACK (bit 14).",
                "Complete the page exchange after three consecutive identical /C/ ordered sets (consistency check).",
                "Re-present recovered GMII (RXD/RX_DV/RX_ER/RX_CLK) to the MAC after 8B/10B decode and ordered-set strip.",
                "Delimit frames with /S/ (Start), /T/ (Terminate), /R/ (Carrier_Extend), and /I/ (Idle /I1//I2/) between frames.",
            ],
        },
        "L3_CMD_PROTOCOL": {
            "ic_name": IC_NAME,
            "protocol_type": "8B/10B-coded ordered-set stream over a 1.25 GBd SerDes lane; control via /K/ ordered sets; no byte-opcode command table.",
            "ordered_sets": [
                {"name": "/I1/", "code": "/K28.5/ /D5.6/", "purpose": "Idle, used when running disparity is positive"},
                {"name": "/I2/", "code": "/K28.5/ /D16.2/", "purpose": "Idle, used when running disparity is negative"},
                {"name": "/C/", "code": "/K28.5/ /D21.5/ + Config(low), /K28.5/ /D2.2/ + Config(high)", "purpose": "Configuration ordered set carrying the 16-bit Config_Reg during Auto-Negotiation"},
                {"name": "/S/", "code": "/K27.7/", "purpose": "Start_of_Packet (replaces the first preamble octet)"},
                {"name": "/T/", "code": "/K29.7/", "purpose": "End_of_Packet (terminate)"},
                {"name": "/R/", "code": "/K23.7/", "purpose": "Carrier_Extend / fill"},
                {"name": "/V/", "code": "/K30.7/", "purpose": "Error_Propagation (invalid code-group / error)"},
            ],
            "comma": {"name": "/K28.5/", "purpose": "Comma; code-group alignment / byte synchronization character"},
            "line_code": {"name": "8B/10B", "running_disparity": True,
                          "reference": "1000BASE-X PCS (IEEE 802.3 Clause 36)"},
            "auto_negotiation": "1000BASE-X (Clause 37) state machine exchanging /C/ ordered sets with the 16-bit SGMII Config_Reg",
            "byte_oriented": False,
            "serial": True,
        },
        "L4_REGMAP": {
            "ic_name": IC_NAME,
            "config_reg_bits": {
                "0": "1 (must be set, identifies the SGMII Config_Reg)",
                "9:1": "Reserved (0)",
                "11:10": "Link Speed (00=10 Mbps, 01=100 Mbps, 10=1000 Mbps, 11=Reserved)",
                "12": "Duplex (1=Full, 0=Half)",
                "13": "Reserved (0)",
                "14": "Acknowledge (ACK, set by the MAC in its reply)",
                "15": "Link (1=link up, 0=link down)"},
            "registers": [
                {"name": "tx_config_reg", "width_bits": 16, "desc": "Config_Reg transmitted in /C/ ordered sets"},
                {"name": "rx_config_reg", "width_bits": 16, "desc": "Config_Reg received from the link partner"},
                {"name": "an_enable", "width_bits": 1, "desc": "Enable Clause-37-style Auto-Negotiation"},
                {"name": "an_restart", "width_bits": 1, "desc": "Restart the Auto-Negotiation page exchange"},
                {"name": "an_link_status", "width_bits": 1, "desc": "Resolved link status derived from rx_config_reg"}],
        },
        "L5_ADI_SPEC": {
            "ic_name": IC_NAME,
            "analog_mixed_signal": "High-speed SerDes PHY: 1.25 GBd LVDS/CML differential TX/RX with CDR (clock-data recovery) on RX.",
            "io_standard": "LVDS / CML differential, 1.25 GBd",
            "serdes": {"line_rate_gbd": 1.25, "ui_ns": 0.8, "ddr_clock_mhz": 625,
                       "cdr": "Receiver recovers the clock from the 8B/10B transition density"},
        },
        "L6_CONTROL_LOGIC": {
            "ic_name": IC_NAME,
            "control_logic": {
                "tx_pcs": ["Accept GMII octet (GMII_TXD/TX_EN/TX_ER)",
                           "Insert /S/ for Start_of_Packet", "8B/10B encode packet octets",
                           "Insert /T/ then /R/ to close the frame", "Send /I/ idle between frames",
                           "Replicate octet x100/x10 for 10/100 Mbps"],
                "rx_pcs": ["Recover clock (CDR)", "Align on /K28.5/ comma", "Establish 10-bit code-group boundary",
                           "Track running disparity", "8B/10B decode", "Strip ordered sets",
                           "De-replicate (sample 1 of N octets)", "Re-present GMII (RXD/RX_DV/RX_ER/RX_CLK)"],
                "an_fsm": ["AN_ENABLE", "AN_RESTART", "ABILITY_DETECT", "ACKNOWLEDGE_DETECT",
                           "COMPLETE_ACKNOWLEDGE", "IDLE_DETECT", "LINK_OK"],
                "consistency": "Page exchange completes after 3 consecutive identical /C/ ordered sets",
                "link_timer_ms": 1.6,
            },
        },
        "L7_TEST_DEBUG": {
            "ic_name": IC_NAME,
            "test_debug": {
                "comma_alignment": "Confirm /K28.5/ comma detection establishes code-group sync",
                "disparity_check": "Verify running disparity errors are flagged",
                "config_readback": "Read rx_config_reg to confirm negotiated speed/duplex/link",
                "an_restart": "an_restart re-runs the Clause-37 page exchange",
                "loopback": "Serial near-end / far-end loopback for SerDes bring-up"},
        },
        "L8_RTL_CONSTANTS": {
            "ic_name": IC_NAME,
            "width_parameters": {
                "CONFIG_REG_BITS": {"width_bits": 16}, "CODE_GROUP_BITS": {"width_bits": 10},
                "GMII_DATA_BITS": {"width_bits": 8}, "LINK_SPEED_BITS": {"width_bits": 2},
                "SPEED_SELECT": {"legal_values": [10, 100, 1000]}},
            "key_constants": {
                "LINE_RATE_GBD": "1.25", "DDR_CLOCK_MHZ": 625, "UI_NS": "0.8",
                "CODE_GROUP_NS": 8, "COMMA": "K28.5", "REPL_10M": 100, "REPL_100M": 10,
                "REPL_1000M": 1, "LINK_TIMER_MS": "1.6", "CONFIG_REG_BIT0": 1,
                "ACK_BIT": 14, "LINK_BIT": 15, "DUPLEX_BIT": 12},
            "link_speed_encodings": {"00": "10 Mbps", "01": "100 Mbps", "10": "1000 Mbps", "11": "Reserved"},
            "duplex_encodings": {"1": "Full duplex", "0": "Half duplex"},
        },
        "L8_TIMING_WAVEFORM": {
            "ic_name": IC_NAME,
            "timing_constants": {"line_rate_gbd": 1.25, "ddr_clock_mhz": 625, "ui_ns": 0.8,
                                 "code_group_ns": 8, "link_timer_ms": 1.6,
                                 "octet_replication": {"10Mbps": 100, "100Mbps": 10, "1000Mbps": 1}},
            "clock_and_data_waveform": {"signaling": "differential LVDS/CML",
                                        "clock": "625 MHz DDR (data on both edges) — optional source-synchronous",
                                        "alignment": "comma /K28.5/ establishes 10-bit code-group boundary"},
            "stream_waveform": {"order": ["/I/ idle", "/C/ (Config_Reg) during Auto-Negotiation",
                                          "/S/ Start_of_Packet", "8B/10B packet octets",
                                          "/T/ Terminate", "/R/ Carrier_Extend", "/I/ idle"]},
        },
        "L9_INTEGRATION_SPEC": {
            "ic_name": IC_NAME,
            "integration_overview": {
                "endpoints": ["Ethernet MAC", "Ethernet PHY"],
                "topology": "point-to-point, one differential pair per direction (TXP/TXN, RXP/RXN)",
                "replaces": "the parallel 10-bit GMII data path between MAC and PHY",
                "pin_count": 8,
                "init_sequence": "Bring up SerDes; align on /K28.5/; run Clause-37 Auto-Negotiation exchanging /C/; PHY drives speed/duplex/link, MAC ACKs; on LINK_OK pass GMII data with x100/x10/x1 octet replication."},
        },
        "L10_TEST_CASES": {
            "ic_name": IC_NAME,
            "test_cases": [
                {"name": "comma_alignment", "desc": "Receiver aligns code groups on the /K28.5/ comma."},
                {"name": "autoneg_1000", "desc": "PHY Config_Reg bits 11:10 = 10 -> resolved 1000 Mbps full duplex, link up."},
                {"name": "autoneg_100", "desc": "Config_Reg bits 11:10 = 01 -> 100 Mbps; GMII octet replicated x10."},
                {"name": "autoneg_10", "desc": "Config_Reg bits 11:10 = 00 -> 10 Mbps; GMII octet replicated x100."},
                {"name": "ack_handshake", "desc": "MAC echoes Config_Reg with ACK bit 14 set; completes after 3 identical /C/."},
                {"name": "disparity_error", "desc": "Injected running-disparity error is detected and flagged."}],
        },
        "L11_OTP_CONTENT": {
            "ic_name": IC_NAME,
            "otp_content": "N/A — SGMII is a SerDes link protocol, no one-time-programmable fuse content defined.",
            "applicable": False,
        },
        "L12_BEHAVIORAL_SEQUENCES": {
            "ic_name": IC_NAME,
            "autoneg_sequence": ["Both ends transmit /C/ with Config_Reg = 0 (AN_RESTART, link_timer running).",
                                 "PHY transmits /C/ with tx_config_reg encoding resolved Link Speed/Duplex/Link.",
                                 "Each end watches rx_config_reg for 3 consecutive identical /C/ (ability_match).",
                                 "MAC echoes the Config_Reg with Acknowledge (bit 14) set.",
                                 "On COMPLETE_ACKNOWLEDGE both ends switch to /I/ idle (IDLE_DETECT).",
                                 "LINK_OK: link_status up, GMII data passes."],
            "packet_sequence": ["Idle /I/ between frames.",
                                "/S/ replaces the first preamble octet at Start_of_Packet.",
                                "8B/10B-encoded packet octets stream at 1.25 GBd.",
                                "/T/ Terminate then /R/ Carrier_Extend close the frame.",
                                "Return to /I/ idle."],
            "speed_adaptation_sequence": ["At 10 Mbps replicate each GMII octet 100x onto the line.",
                                          "At 100 Mbps replicate each GMII octet 10x.",
                                          "At 1000 Mbps send each octet once.",
                                          "Receiver de-replicates by sampling 1 of every N identical octets."],
        },
        "L13_LAB_CALIBRATION": {
            "ic_name": IC_NAME,
            "lab_calibration": "SerDes bring-up: TX de-emphasis / RX equalization and CDR lock; eye-diagram margin at 1.25 GBd; comma-lock verification.",
            "applicable": True,
        },
        "L14_PROTOCOL_VERSIONING": {
            "spec_version": "Serial-GMII (SGMII) Specification Revision 1.8 (Cisco ENG-46158)",
            "lineage": [
                {"version": "GMII", "year": "1998", "summary": "Parallel 8-bit Gigabit Media Independent Interface (the wide bus SGMII serializes)."},
                {"version": "1000BASE-X / Clause 36-37", "year": "1998", "summary": "8B/10B PCS + Auto-Negotiation SGMII reuses."},
                {"version": "SGMII 1.7", "year": "2001", "summary": "Cisco Serial-GMII; serialized GMII over 1.25 GBd."},
                {"version": "SGMII 1.8", "year": "2005", "summary": "Clarified Config_Reg speed/duplex/link encoding and optional 625 MHz DDR clock."}],
            "backward_compat_traps": [
                {"trap_name": "Not_Ethernet_MAC", "rule": "SGMII is the MAC<->PHY SerDes link, not the Ethernet MAC frame layer; it defines no preamble/SFD, no 48-bit MAC address, and no Ethernet CRC-32 framing.", "trap": "Decoding SGMII as an Ethernet MAC frame (looking for preamble/addresses/FCS) is wrong."},
                {"trap_name": "Not_RGMII", "rule": "SGMII serializes GMII onto ONE 1.25 GBd differential pair with 8B/10B; RGMII is a PARALLEL two 4-bit DDR bus at 125 MHz.", "trap": "Treating SGMII as a parallel reduced-pin GMII (RGMII) misses the SerDes 8B/10B serialization."},
                {"trap_name": "Config_Reg_redefined", "rule": "SGMII reuses the 1000BASE-X Clause-37 AN machine but REDEFINES the 16-bit Config_Reg to carry speed (11:10)/duplex(12)/link(15) instead of 1000BASE-X ability bits.", "trap": "Interpreting the SGMII Config_Reg as 1000BASE-X duplex/pause ability fields is wrong."}],
        },
        "L15_ENCODING_TABLES": {
            "ordered_set_table": {"header_columns": ["Ordered Set", "Code", "Meaning"], "rows": [
                ["/I1/", "/K28.5/ /D5.6/", "Idle (RD positive)"],
                ["/I2/", "/K28.5/ /D16.2/", "Idle (RD negative)"],
                ["/C/", "/K28.5/ /D21.5/+Config, /K28.5/ /D2.2/+Config", "Configuration (Config_Reg)"],
                ["/S/", "/K27.7/", "Start_of_Packet"],
                ["/T/", "/K29.7/", "End_of_Packet (Terminate)"],
                ["/R/", "/K23.7/", "Carrier_Extend / fill"],
                ["/V/", "/K30.7/", "Error_Propagation"]]},
            "config_reg_table": {"header_columns": ["Bits", "Field", "Encoding"], "rows": [
                ["0", "Validity", "1 (identifies SGMII Config_Reg)"],
                ["9:1", "Reserved", "0"],
                ["11:10", "Link Speed", "00=10M, 01=100M, 10=1000M, 11=Reserved"],
                ["12", "Duplex", "1=Full, 0=Half"],
                ["14", "Acknowledge", "set by MAC reply"],
                ["15", "Link", "1=up, 0=down"]]},
            "speed_replication_table": {"header_columns": ["Speed", "Config 11:10", "Octet replication"], "rows": [
                ["10 Mbps", "00", "x100"], ["100 Mbps", "01", "x10"], ["1000 Mbps", "10", "x1"]]},
        },
        "L16_COMPLIANCE_PROPERTIES": {
            "must_have_properties": [
                "The serial lane runs at a fixed 1.25 GBd in both directions for all Ethernet speeds.",
                "Octets are 8B/10B-coded with running disparity and aligned on the /K28.5/ comma.",
                "Auto-Negotiation exchanges /C/ ordered sets carrying the 16-bit SGMII Config_Reg.",
                "Config_Reg encodes Link Speed in bits 11:10, Duplex in bit 12, ACK in bit 14, Link in bit 15.",
                "Bit 0 of the SGMII Config_Reg is always 1.",
                "Page exchange completes after three consecutive identical /C/ ordered sets.",
                "Each GMII octet is replicated x100 (10 Mbps) or x10 (100 Mbps) to hold the line rate constant.",
                "The recovered GMII byte stream is presented transparently between MAC and PHY."],
            "sgmii_distinguishers": [
                "Serializes GMII onto one 1.25 GBd differential pair per direction — not the parallel GMII/RGMII bus.",
                "Reuses the 1000BASE-X Clause-37 AN machine with a REDEFINED Config_Reg (speed/duplex/link).",
                "Is a MAC<->PHY SerDes link, not the Ethernet MAC frame layer (no preamble/SFD/MAC-address/CRC-32)."],
        },
        "L17_CHANNEL_SIGNAL_CATALOG": {
            "channels": [
                {"name": "TXP", "direction": "output (MAC to PHY)", "purpose": "Transmit differential + at 1.25 GBd."},
                {"name": "TXN", "direction": "output (MAC to PHY)", "purpose": "Transmit differential - at 1.25 GBd."},
                {"name": "RXP", "direction": "input (PHY to MAC)", "purpose": "Receive differential + at 1.25 GBd."},
                {"name": "RXN", "direction": "input (PHY to MAC)", "purpose": "Receive differential - at 1.25 GBd."},
                {"name": "TXCLKP", "direction": "output", "purpose": "Optional 625 MHz DDR transmit clock +."},
                {"name": "TXCLKN", "direction": "output", "purpose": "Optional 625 MHz DDR transmit clock -."},
                {"name": "RXCLKP", "direction": "input", "purpose": "Optional 625 MHz DDR receive clock +."},
                {"name": "RXCLKN", "direction": "input", "purpose": "Optional 625 MHz DDR receive clock -."}],
            "lanes": [
                {"name": "TX lane", "rate_gbd": 1.25, "direction": "MAC to PHY", "code": "8B/10B"},
                {"name": "RX lane", "rate_gbd": 1.25, "direction": "PHY to MAC", "code": "8B/10B"}],
            "channel_counts": {"physical_signals": 8, "differential_pairs": 4, "data_lanes": 2},
        },
        "L18_INTERCONNECT_TOPOLOGY": {
            "topology_type": "Point-to-point MAC<->PHY; one differential pair per direction (TXP/TXN, RXP/RXN).",
            "supported_topologies": [
                {"name": "MAC to PHY", "description": "Direct chip-to-chip SerDes link replacing the parallel GMII."},
                {"name": "MAC to module", "description": "MAC to a pluggable PHY module over the same 1.25 GBd lanes."}],
            "device_classification": {"endpoint_a": "Ethernet MAC", "endpoint_b": "Ethernet PHY"},
            "replaces": "the parallel 10-bit GMII data path (and the RGMII parallel DDR bus)",
        },
        "L19_CONSTRAINTS_PDK": {"pdk_target": "N/A (protocol spec, not a tapeout)",
                               "io_standard": "LVDS / CML differential",
                               "line_rate_gbd": 1.25, "ddr_clock_mhz": 625},
        "L20_DFT_SCAN_TOPOLOGY": {"scan_topology": "N/A — protocol spec; SerDes BIST/loopback used for bring-up, no DFT scan defined."},
        "L21_POWER_INTENT": {"power_domains": ["SerDes analog (LVDS/CML)", "PCS digital core"],
                             "power_considerations": "Serializing GMII onto one differential pair per direction cuts pin count and switching power vs the parallel 10-bit GMII/RGMII bus."},
        "L22_VERIFICATION_PLAN": {"verification_items": ["Comma /K28.5/ alignment", "8B/10B running-disparity check",
                                  "Auto-Negotiation page exchange (Clause 37)", "Config_Reg speed/duplex/link decode",
                                  "ACK handshake (bit 14) + 3-consecutive consistency", "Octet replication x100/x10/x1",
                                  "GMII transparency MAC<->PHY"]},
        "L23_SECURITY_REQUIREMENTS": {"attack_surface": [
            "Auto-Negotiation Config_Reg is unauthenticated — a rogue link partner can force a speed/duplex/link state.",
            "SGMII defines no link encryption; payload confidentiality is the responsibility of higher layers (MACsec)."],
            "security_notes": "SGMII itself defines no encryption or authentication; protect at the MAC/MACsec layer above."},
    }


def apply_sgmii_synth(generated_docs_dir, is_sgmii_flag: bool,
                      ic_name: Optional[str]) -> None:
    """Force-merge SGMII-canonical content into the generated L-docs when the
    SGMII signature matched. No-op otherwise."""
    if not is_sgmii_flag:
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
