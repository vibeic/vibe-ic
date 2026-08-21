"""Bluetooth Low Energy 5.2-class protocol synth helper.

v0.1.84+ — ic_class-gated overlay for `serial_peripheral_protocol`
(extended to wireless PAN) specs that exhibit the BLE 5.x structural
signature (Bluetooth Low Energy + advertising + connection terminology,
OR BLE + GAP + GATT, OR Bluetooth + LE + 2.4 GHz + 40 channels). Applies
Bluetooth Core Specification v5.2 canonical content to L1-L18 + L21 +
L23.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any Bluetooth Core 4.x / 5.x family variant (LE 1M / 2M / Coded;
Extended Advertising; Periodic Advertising; Direction Finding; LE Audio
Isochronous Channels) exhibits the same structural signature.

Public entry: `apply_ble_synth(generated_docs_dir, is_ble, ble_ic_name)`.
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


def _force(d: dict, key: str, value) -> None:
    """Unconditional set — used when an earlier R53 universal serial-peripheral
    synth seeded a generic placeholder (or a sibling protocol synth such as
    UART/USB/RS-485/HDLC pre-seeded its own canonical value because BLE fires
    last in the R55 chain). `setdefault` would silently no-op against the
    pre-seeded value, so for BLE-canonical values we must force-overwrite."""
    d[key] = value


def apply_ble_synth(generated_docs_dir: Path, is_ble: bool,
                    ble_ic_name: Optional[str]) -> None:
    """Apply BLE-specific synth when the structural signature matched."""
    if not is_ble:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs (L1..L13 + L8_TIMING).
    if ble_ic_name is not None:
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
                d["ic_name"] = ble_ic_name
                _write(q, d)

    # L1 DATASHEET
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite identity fields: UART (PC16550D) / USB / RS-485 /
        # HDLC synths in the R55 chain may have already populated these with
        # their own canonical values because BLE fires LAST in the Tier-3
        # detector tuple. The protocol identity is BLE — must dominate.
        _force(d, "document_title", "Bluetooth Core Specification")
        _force(d, "version", "v5.2")
        _force(d, "manufacturer", "Bluetooth SIG, Inc.")
        _force(d, "revised_date", "December 31, 2019")
        _force(d, "copyright", "© 2019 Bluetooth SIG, Inc. All rights reserved.")
        _force(d, "external_pins", ["ANT (2.4 GHz RF antenna)", "RF GND", "VDD (radio supply)", "VSS (ground)"])
        _force(d, "external_pin_count", 4)
        d.setdefault("modes_of_operation", [
            {"name": "LE 1M PHY",      "max_bit_rate": "1 Msym/s (1 Mb/s)",       "use_case": "Default BLE 4.0/4.1/4.2 PHY; GFSK modulation; mandatory in 5.x for backward compatibility."},
            {"name": "LE 2M PHY",      "max_bit_rate": "2 Msym/s (2 Mb/s)",       "use_case": "BLE 5 high-throughput PHY; halves on-air time; optional but widely supported."},
            {"name": "LE Coded S=2",   "max_bit_rate": "500 ksym/s (~500 kb/s)",  "use_case": "Long-range PHY with 2x FEC redundancy; ~2x range vs 1M."},
            {"name": "LE Coded S=8",   "max_bit_rate": "125 ksym/s (~125 kb/s)",  "use_case": "Long-range PHY with 8x FEC redundancy; ~4x range vs 1M."},
        ])
        d.setdefault("key_features", [
            "Operates in the unlicensed 2.4 GHz ISM band (2.400-2.4835 GHz).",
            "40 RF channels each 2 MHz wide: 37 data channels (0-36) + 3 primary advertising channels (37/2402 MHz, 38/2426 MHz, 39/2480 MHz).",
            "GFSK modulation with BT = 0.5 and modulation index 0.45-0.55 (LE 1M / LE 2M); LE Coded uses additional FEC interleaving (S=2 or S=8).",
            "Symbol rate: 1 Msym/s (LE 1M, LE Coded), 2 Msym/s (LE 2M).",
            "Adaptive Frequency Hopping (AFH) using Channel Selection Algorithm #1 (legacy) or #2 (BLE 5).",
            "Connection event interval programmable from 7.5 ms to 4.0 s in 1.25 ms units.",
            "Slave latency 0-499 events; supervision timeout 100 ms to 32 s.",
            "BLE 5 additions: LE 2M PHY, LE Coded PHY, Extended Advertising (up to 1650 octets per AdvData chain), Periodic Advertising broadcast slots.",
            "BLE 5.1 additions: Direction Finding (AoA + AoD) using CTE (Constant Tone Extension), Channel Sounding precursor, randomized advertising channel indexing, GATT Caching.",
            "BLE 5.2 additions: LE Audio (Isochronous Channels CIS + BIS, LE Audio profiles BAP/PACS/CSIP/MCP/TMAP), Enhanced ATT (EATT) multi-bearer, LE Power Control + Path-Loss Monitoring, Isochronous Adaptation Layer (LL-ISOAL).",
            "Built-in CRC-24 protection on every PDU (polynomial 0x100065B).",
            "AES-128 CCM authenticated encryption on the Link Layer + LE Secure Connections pairing (ECDH P-256).",
            "Maximum TX output power up to +20 dBm (transmit class 1); minimum receiver sensitivity ≤ -70 dBm at 1M PHY, ≤ -82 dBm at LE Coded S=8.",
            "Roles: Broadcaster, Observer, Peripheral, Central, plus Initiator + Scanner transient roles.",
        ])
        _force(d, "overview",
            "Bluetooth Low Energy (BLE) is a short-range wireless personal-area-network technology operating in the 2.4 GHz ISM band, designed for ultra-low-power applications such as fitness, healthcare, beacons, sensors and human-interface devices. The Bluetooth Core Specification v5.2 (December 2019) defines the full BLE stack: PHY layer (Volume 6 Part A), Link Layer (Volume 6 Part B), Host Controller Interface (Volume 4 Part E), L2CAP (Volume 3 Part A), Attribute Protocol (Volume 3 Part F), Generic Attribute Profile (Volume 3 Part G), Security Manager (Volume 3 Part H), Generic Access Profile (Volume 3 Part C). v5.2 introduces LE Audio (Isochronous Channels), Enhanced ATT (EATT), and LE Power Control.")
        d.setdefault("previous_versions", [
            "1.0 (1999) — original Basic Rate (BR/EDR) Bluetooth; no LE.",
            "2.0 + EDR (2004) — 3 Mb/s EDR added to BR/EDR.",
            "2.1 + EDR (2007) — Secure Simple Pairing.",
            "3.0 + HS (2009) — alternate-MAC/PHY (802.11 high-speed).",
            "4.0 (2010) — first version with Bluetooth Low Energy (BLE / LE / Bluetooth Smart).",
            "4.1 (2013) — dual-mode topology cleanups, LE link-layer improvements.",
            "4.2 (2014) — LE Secure Connections (ECDH P-256), LE Data Length Extension (up to 251-octet PDU), IPv6 over BLE (IPSP).",
            "5.0 (2016) — LE 2M PHY, LE Coded PHY, Extended Advertising, Periodic Advertising, Channel Selection Algorithm #2.",
            "5.1 (2019) — Direction Finding (AoA + AoD), Periodic Advertising Sync Transfer, GATT Caching, Random Advertising Channel Indexing, Path Loss Reporting precursor.",
            "5.2 (December 2019) — LE Audio (CIS + BIS + LE Audio profiles), Enhanced ATT (EATT), LE Power Control + Path-Loss Monitoring, Isochronous Adaptation Layer.",
        ])
        _force(d, "topology_summary",
            "BLE supports star + scatternet topologies. Roles: a Central device may connect to one or more Peripherals; a Broadcaster transmits advertising packets without bidirectional connection; an Observer listens for advertising packets. In BLE 5.2 a single device may simultaneously act in multiple roles (multi-role). Connection topology = master (Central) + slave (Peripheral); after CONNECT_IND the master schedules each connection event at a programmable interval.")
        _force(d, "package_summary",
            "Bluetooth Core Specification v5.2 is a wireless protocol spec; physical realization is a 2.4 GHz radio SoC (typically with integrated antenna). External pins are radio-related (ANT / RF-GND / VDD / VSS); the stack itself is host-controller-interface-based (HCI) over UART / USB / SDIO / SPI.")
        _write(p, d)

    # L2 FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite protocol_overview sub-fields: UART R59 / USB R65 /
        # RS-485 R137 / HDLC R158 synths populate type/duplex/wire_count with
        # their own canonical values; for BLE the type is wireless PAN,
        # duplex is half-duplex (TX/RX time-multiplexed), wire_count is 4.
        po = d.get("protocol_overview")
        if not isinstance(po, dict):
            po = {}
            d["protocol_overview"] = po
        _force(po, "type", "Wireless personal-area-network protocol over 2.4 GHz ISM band; packet-based; master-polled connections with periodic advertising broadcasts.")
        _force(po, "duplex", "half-duplex (TX and RX time-multiplexed within each connection event)")
        po.setdefault("synchronous_serial", False)
        po.setdefault("wire_names", ["ANT (RF antenna)", "RF GND", "VDD (radio)", "VSS (ground)"])
        _force(po, "wire_count", 4)
        po.setdefault("modulation", "GFSK with BT=0.5, modulation index 0.45-0.55 (LE 1M / 2M); LE Coded adds S=2 or S=8 FEC.")
        po.setdefault("ism_band_low_MHz",  2400)
        po.setdefault("ism_band_high_MHz", 2483.5)
        po.setdefault("channel_count", 40)
        po.setdefault("data_channel_count", 37)
        po.setdefault("primary_advertising_channel_count", 3)
        po.setdefault("primary_advertising_channels_MHz", [2402, 2426, 2480])
        po.setdefault("channel_spacing_MHz", 2)
        po.setdefault("min_connection_interval_ms", 7.5)
        po.setdefault("max_connection_interval_ms", 4000)
        po.setdefault("connection_interval_step_ms", 1.25)
        po.setdefault("supported_PHYs", ["LE 1M (1 Msym/s)", "LE 2M (2 Msym/s)", "LE Coded S=2 (~500 kb/s)", "LE Coded S=8 (~125 kb/s)"])
        fr = [
            {"id": "FR-RF-01",   "text": "Radio operates in the 2.4-2.4835 GHz ISM band on 40 channels, each 2 MHz wide, indexed 0..39."},
            {"id": "FR-RF-02",   "text": "Channels 37 / 38 / 39 are the three primary advertising channels at 2402 / 2426 / 2480 MHz; channels 0..36 are data channels used during connections and Periodic Advertising."},
            {"id": "FR-MOD-03",  "text": "Default modulation = GFSK with BT=0.5 and modulation index in 0.45..0.55. LE 1M = 1 Msym/s; LE 2M = 2 Msym/s; LE Coded = 1 Msym/s symbol rate with S=2 or S=8 FEC."},
            {"id": "FR-PKT-04",  "text": "Link Layer packet format: Preamble (1 or 2 octets, repeated 0xAA/0x55) | Access Address (4 octets) | PDU (Header 2 + Payload 0..255 octets) | CRC (3 octets)."},
            {"id": "FR-ACC-05",  "text": "Advertising packets use fixed Access Address 0x8E89BED6; connection packets use a per-connection random Access Address with specific entropy + Hamming requirements."},
            {"id": "FR-CRC-06",  "text": "CRC-24 polynomial = x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1 (0x100065B). CRC initial value is negotiated; advertising uses 0x555555."},
            {"id": "FR-WHTN-07", "text": "All Link Layer bits except Preamble and Access Address are whitened by a 7-bit LFSR seeded with the channel index (Section 3.2 of Vol 6 Part B)."},
            {"id": "FR-ADV-08",  "text": "Advertising PDU types (legacy): ADV_IND, ADV_DIRECT_IND, ADV_NONCONN_IND, ADV_SCAN_IND, SCAN_REQ, SCAN_RSP, CONNECT_IND. Extended (BLE 5): ADV_EXT_IND, AUX_ADV_IND, AUX_SYNC_IND, AUX_CHAIN_IND, AUX_SCAN_REQ, AUX_SCAN_RSP, AUX_CONNECT_REQ, AUX_CONNECT_RSP."},
            {"id": "FR-CONN-09", "text": "After a Central (Initiator) sends CONNECT_IND or AUX_CONNECT_REQ, a connection is established. The Central schedules each connection event at the negotiated interval (7.5 ms..4.0 s)."},
            {"id": "FR-LL-10",   "text": "Data PDU LLID encoding: 00=reserved; 01=LL Data PDU continuation/empty; 10=LL Data PDU start of L2CAP message; 11=LL Control PDU."},
            {"id": "FR-CTRL-11", "text": "LL Control PDUs include LL_CONNECTION_UPDATE_IND, LL_CHANNEL_MAP_IND, LL_TERMINATE_IND, LL_ENC_REQ/RSP, LL_START_ENC_REQ/RSP, LL_FEATURE_REQ/RSP, LL_VERSION_IND, LL_PING_REQ/RSP, LL_LENGTH_REQ/RSP, LL_PHY_REQ/RSP/UPDATE_IND, LL_POWER_CONTROL_REQ/RSP/IND (BLE 5.2)."},
            {"id": "FR-AFH-12",  "text": "Adaptive Frequency Hopping uses Channel Selection Algorithm #1 (legacy) or #2 (BLE 5) over the 37 data channels; bad channels are excluded by the Channel Map (5-octet bitmap)."},
            {"id": "FR-EXT-13",  "text": "Extended Advertising (BLE 5) splits the advertising payload across a primary ADV_EXT_IND on channels 37/38/39 plus auxiliary packets (AUX_ADV_IND etc.) on data channels, supporting up to 1650 octets per chained advertising set."},
            {"id": "FR-PER-14",  "text": "Periodic Advertising broadcasts AUX_SYNC_IND on a deterministic schedule at a programmable periodic-interval (7.5 ms..81.91875 s); receivers acquire sync via Periodic Advertising Sync Transfer (PAST) or by scanning."},
            {"id": "FR-DF-15",   "text": "Direction Finding (BLE 5.1) appends a Constant Tone Extension (CTE) of 16..160 µs to advertising or data packets; AoA receivers switch antennas during CTE to estimate angle of arrival; AoD transmitters switch antennas."},
            {"id": "FR-LE-AUD-16","text": "LE Audio (BLE 5.2): Isochronous Channels — Connected Isochronous Streams (CIS) and Broadcast Isochronous Streams (BIS) — provide deterministic-latency multi-stream audio; LL-ISOAL fragments/recombines SDUs."},
            {"id": "FR-EATT-17", "text": "Enhanced ATT (EATT, BLE 5.2) supports concurrent client requests over multiple L2CAP channels (one ATT bearer per channel) with separate flow control + per-bearer MTU."},
            {"id": "FR-PWR-18",  "text": "LE Power Control + Path Loss Monitoring (BLE 5.2): peers exchange LL_POWER_CONTROL_REQ/RSP/IND to request TX-power adjustments based on RSSI / path-loss thresholds."},
            {"id": "FR-SEC-19",  "text": "Link-layer encryption = AES-128 CCM. Pairing methods (Security Manager Protocol): Just Works, Passkey Entry, Numeric Comparison, Out-of-Band (OOB); LE Secure Connections uses ECDH P-256 key exchange."},
            {"id": "FR-GATT-20", "text": "GATT (Generic Attribute Profile) provides service / characteristic / descriptor abstraction over ATT; client / server roles; standard services + characteristics identified by 16-bit or 128-bit UUIDs."},
            {"id": "FR-GAP-21",  "text": "GAP (Generic Access Profile) defines device roles (Broadcaster, Observer, Peripheral, Central), discovery modes (non-discoverable / limited / general), connectability modes, and security modes."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "CRC error — receiver discards the PDU; in connection events the corresponding NESN is not toggled.",
            "Access Address mismatch — receiver discards the PDU silently.",
            "Whitening mismatch — observed as random CRC errors downstream.",
            "Supervision Timeout exceeded — connection lost; both ends drop to Standby state.",
            "Authentication failure during LL_ENC_REQ/RSP exchange — encryption setup aborts; LL_TERMINATE_IND issued with reason code.",
            "Pairing failure (SMP) — Security Manager Pairing Failed PDU with reason code (Passkey Entry Failed / OOB Not Available / Authentication Requirements / Confirm Value Failed / Pairing Not Supported / Encryption Key Size / Command Not Supported / Unspecified Reason / Repeated Attempts / Invalid Parameters / DHKey Check Failed / Numeric Comparison Failed / BR/EDR Pairing In Progress / Cross-Transport Key Derivation Not Allowed).",
            "PHY Update collision — LL_PHY_UPDATE_IND instant collision; restart procedure.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Backward compatibility with BLE 4.0/4.1/4.2 legacy advertising + connection PDUs.",
                "LE 1M PHY support is mandatory for any 5.x compliant device.",
                "If a device supports the LE 2M Feature bit, it must implement both LL_PHY_REQ/RSP/UPDATE_IND and the 2M PHY itself.",
                "Devices implementing Extended Advertising must follow the primary-advertising-channel + auxiliary-channel timing rules in Section 4.4.2.4 of Vol 6 Part B.",
                "Periodic Advertising sender + receiver must implement Channel Selection Algorithm #2.",
                "BLE 5.2 LE Audio devices must implement Isochronous Channels (CIS or BIS) + Isochronous Adaptation Layer (ISOAL) + LE Audio profiles (BAP / PACS / CSIP / VCP / MCP / TMAP).",
                "Coexistence: BLE radios must implement Adaptive Frequency Hopping to avoid 2.4 GHz interferers (Wi-Fi, microwave, ZigBee).",
                "Maximum advertising TX power: +20 dBm (Power Class 1.5); per-region regulatory limits apply.",
            ]
        _write(p, d)

    # L3 CMD_PROTOCOL
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        # Clear flat L3.opcodes — BLE has structured LL_Control opcodes +
        # ATT opcodes catalogued elsewhere, not a flat byte-opcode table.
        # The downstream gen_l10 step uses L3.opcodes to synthesize fake
        # send_<X> test_cases that get flagged as HALLUCINATED. Same fix
        # as JTAG v0.1.88.
        d["opcodes"] = []
        # Force-overwrite protocol_type: UART R59 / USB R65 / RS-485 R137 /
        # HDLC R158 already populated this with their own protocol identity.
        _force(d, "protocol_type",
            "Packet-based wireless protocol; Link-Layer state machine drives advertising / scanning / initiating / connection phases; connections are Central-polled with master-driven scheduling.")
        d.setdefault("channels", [
            {"name": "ANT",     "direction": "bidirectional RF",            "purpose": "2.4 GHz antenna interface; one differential pair or single-ended depending on radio implementation."},
            {"name": "RF GND",  "direction": "RF ground reference",          "purpose": "RF return path."},
            {"name": "VDD",     "direction": "power supply",                 "purpose": "Radio + baseband supply (typically 1.8 V or 3.3 V)."},
            {"name": "VSS",     "direction": "ground",                       "purpose": "Common ground."},
            {"name": "HCI",     "direction": "bidirectional host interface", "purpose": "Host Controller Interface to upper-layer host stack via UART / USB / SPI / SDIO (out-of-RF)."},
        ])
        d.setdefault("packet_classes", [
            {"class": "Advertising legacy",       "purpose": "Broadcast device presence / scan / connect.",
              "subtypes": ["ADV_IND", "ADV_DIRECT_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND"]},
            {"class": "Scanning + initiating",    "purpose": "Active scan / connection setup over advertising channels.",
              "subtypes": ["SCAN_REQ", "SCAN_RSP", "CONNECT_IND"]},
            {"class": "Advertising extended (BLE 5)", "purpose": "Extended advertising primary + auxiliary chain on data channels.",
              "subtypes": ["ADV_EXT_IND", "AUX_ADV_IND", "AUX_SYNC_IND", "AUX_CHAIN_IND", "AUX_SCAN_REQ", "AUX_SCAN_RSP", "AUX_CONNECT_REQ", "AUX_CONNECT_RSP"]},
            {"class": "Data PDU (LL_DATA)",       "purpose": "Connection-event data, L2CAP message fragments, or LL Control.",
              "subtypes": ["LL_DATA continuation (LLID=01)", "LL_DATA start-of-L2CAP (LLID=10)", "LL_CONTROL (LLID=11)"]},
            {"class": "Isochronous PDU (BLE 5.2)", "purpose": "Connected (CIS) or Broadcast (BIS) Isochronous Streams carrying audio / control / sensor SDUs.",
              "subtypes": ["CIS PDU (LLID=00/01)", "BIS PDU (LLID=00/01)", "CIS framed (LLID=10)", "BIS framed (LLID=10)"]},
        ])
        d.setdefault("ll_control_pdu_opcodes", {
            "purpose": "LLID=11 control-channel opcodes carried in the LL Data PDU payload (Opcode at byte 0 + CtrlData).",
            "examples_hex": {
                "LL_CONNECTION_UPDATE_IND": "0x00",
                "LL_CHANNEL_MAP_IND":       "0x01",
                "LL_TERMINATE_IND":         "0x02",
                "LL_ENC_REQ":               "0x03",
                "LL_ENC_RSP":               "0x04",
                "LL_START_ENC_REQ":         "0x05",
                "LL_START_ENC_RSP":         "0x06",
                "LL_UNKNOWN_RSP":           "0x07",
                "LL_FEATURE_REQ":           "0x08",
                "LL_FEATURE_RSP":           "0x09",
                "LL_PAUSE_ENC_REQ":         "0x0A",
                "LL_PAUSE_ENC_RSP":         "0x0B",
                "LL_VERSION_IND":           "0x0C",
                "LL_REJECT_IND":            "0x0D",
                "LL_SLAVE_FEATURE_REQ":     "0x0E",
                "LL_CONNECTION_PARAM_REQ":  "0x0F",
                "LL_CONNECTION_PARAM_RSP":  "0x10",
                "LL_REJECT_EXT_IND":        "0x11",
                "LL_PING_REQ":              "0x12",
                "LL_PING_RSP":              "0x13",
                "LL_LENGTH_REQ":            "0x14",
                "LL_LENGTH_RSP":            "0x15",
                "LL_PHY_REQ":               "0x16",
                "LL_PHY_RSP":               "0x17",
                "LL_PHY_UPDATE_IND":        "0x18",
                "LL_MIN_USED_CHANNELS_IND": "0x19",
                "LL_CTE_REQ":               "0x1A",
                "LL_CTE_RSP":               "0x1B",
                "LL_PERIODIC_SYNC_IND":     "0x1C",
                "LL_CLOCK_ACCURACY_REQ":    "0x1D",
                "LL_CLOCK_ACCURACY_RSP":    "0x1E",
                "LL_CIS_REQ":               "0x1F",
                "LL_CIS_RSP":               "0x20",
                "LL_CIS_IND":               "0x21",
                "LL_CIS_TERMINATE_IND":     "0x22",
                "LL_POWER_CONTROL_REQ":     "0x23",
                "LL_POWER_CONTROL_RSP":     "0x24",
                "LL_POWER_CHANGE_IND":      "0x25",
            },
        })
        d.setdefault("transaction_phases", [
            "Advertising phase — advertiser transmits on 37/38/39 (legacy) or 37/38/39 + AUX on data channels (extended).",
            "Scanning phase — observer listens passively (no SCAN_REQ) or actively (SCAN_REQ + SCAN_RSP).",
            "Initiating phase — initiator transmits CONNECT_IND (or AUX_CONNECT_REQ) in response to an ADV_IND / ADV_DIRECT_IND / ADV_EXT_IND with connectable flag.",
            "Connection event phase — Central starts a connection event by transmitting an LL_DATA PDU; Peripheral responds; both ends alternate until empty PDUs are exchanged or MD bit is 0.",
            "Periodic Advertising phase — broadcaster transmits AUX_SYNC_IND on a deterministic periodic schedule.",
            "Isochronous event phase (BLE 5.2) — CIS/BIS events carrying audio / control SDUs with deterministic latency.",
        ])
        # Force-overwrite addressing block — UART R59 / USB R65 etc. set
        # device_address_width_bits to their own protocol's value (UART=7,
        # USB=7), but BLE uses 48-bit BD_ADDR.
        addr = d.get("addressing")
        if not isinstance(addr, dict):
            addr = {}
            d["addressing"] = addr
        _force(addr, "device_address_width_bits", 48)
        addr.setdefault("device_address_types", ["Public (IEEE OUI prefix)", "Random Static", "Random Private Resolvable (RPA)", "Random Private Non-Resolvable"])
        addr.setdefault("access_address_width_bits", 32)
        addr.setdefault("advertising_access_address_hex", "0x8E89BED6")
        addr.setdefault("connection_access_address_constraints", "Must have ≥ 2 transitions in the 6 most-significant bits; not equal to 0x8E89BED6; not all-zero or all-one; not 4 identical octets; no more than 24 transitions overall.")
        addr.setdefault("connection_handle_width_bits", 12)
        d.setdefault("valid_ready_handshake_rules", [
            "Each LL Data PDU carries SN (Sequence Number) + NESN (Next Expected Sequence Number) 1-bit fields in the header.",
            "Receiver toggles its expected SN by setting NESN = received_SN xor 1 when the PDU is accepted (CRC OK + matches expected SN).",
            "If CRC fails OR received_SN != expected_SN, NESN is not toggled — transmitter must retransmit.",
            "MD (More Data) bit in the header signals whether the sender has more data queued for the current connection event.",
            "Empty PDU (length=0, LLID=01) is a valid keep-alive used to close a connection event.",
            "Encryption: when LL encryption is active, payload is encrypted with AES-CCM using per-direction Packet Counter; MIC (4 octets) appended.",
        ])
        # Force-overwrite burst_based: UART R59 sets False (UART is byte-by-byte
        # framed, not burst). BLE is burst-based (a connection event allows
        # multiple PDUs back-to-back within the window).
        _force(d, "burst_based", True)
        d.setdefault("burst_unit", "Connection event — a window opened by the Central each interval; both ends may transmit multiple PDUs back-to-back within the window subject to MD bit and CE Length budget.")
        _write(p, d)

    # L4 REGMAP (BLE LL PDU header layouts + HCI command groups)
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d.setdefault("ll_data_pdu_header_layout", {
            "purpose": "Link-Layer Data PDU header — 2 octets immediately after the 4-octet Access Address; whitened.",
            "fields": {
                "LLID_bits1_0":     "Logical Link Identifier (00 reserved; 01 LL Data continuation/empty; 10 LL Data start-of-L2CAP; 11 LL Control PDU)",
                "NESN_bit2":         "Next Expected Sequence Number — receiver toggles to acknowledge a successful PDU",
                "SN_bit3":           "Sequence Number — toggled by transmitter on each new data PDU",
                "MD_bit4":           "More Data — indicates the transmitter has additional PDUs queued for this connection event",
                "CP_bit5":           "CTE Info Present (BLE 5.1) — indicates a CTE Info field follows the header",
                "RFU_bits7_6":       "Reserved for future use; transmit as 0, receiver ignores",
                "Length_byte1":      "Payload length (0..255 octets); for LE 1M/2M PHY the high bit may be used to extend",
            },
        })
        d.setdefault("ll_adv_pdu_header_layout", {
            "purpose": "Advertising-channel PDU header — 2 octets immediately after the 4-octet Access Address (0x8E89BED6).",
            "fields": {
                "PDU_Type_bits3_0":    "Advertising PDU type: 0x0=ADV_IND, 0x1=ADV_DIRECT_IND, 0x2=ADV_NONCONN_IND, 0x3=SCAN_REQ / AUX_SCAN_REQ, 0x4=SCAN_RSP / AUX_SCAN_RSP, 0x5=CONNECT_IND / AUX_CONNECT_REQ, 0x6=ADV_SCAN_IND, 0x7=ADV_EXT_IND / AUX_ADV_IND / AUX_SYNC_IND / AUX_CHAIN_IND, 0x8=AUX_CONNECT_RSP",
                "RFU_bit4":            "Reserved",
                "ChSel_bit5":          "Channel Selection bit; 1 = supports Algorithm #2 (BLE 5)",
                "TxAdd_bit6":          "Tx Address type — 0=public, 1=random",
                "RxAdd_bit7":          "Rx Address type — 0=public, 1=random",
                "Length_byte1":        "Payload length (legacy 6..37 octets; extended up to 255 in AUX_xxx)",
            },
        })
        d.setdefault("extended_advertising_header_extension", {
            "purpose": "Optional extended-header (BLE 5) — first byte is Length + AdvMode, followed by an extended-header-flags byte, followed by selected fields.",
            "extended_header_flags": {
                "AdvA_present_bit0":             "Advertiser Address (6 octets)",
                "TargetA_present_bit1":          "Target Address (6 octets, directed advertising)",
                "CTEInfo_present_bit2":          "CTE Info (1 octet, BLE 5.1)",
                "AdvDataInfo_present_bit3":      "AdvDataInfo (2 octets — DID + SID)",
                "AuxPtr_present_bit4":           "AuxPtr (3 octets — Channel + CA + Offset Units + AUX Offset + AUX PHY)",
                "SyncInfo_present_bit5":         "SyncInfo (18 octets) for Periodic Advertising sync",
                "TxPower_present_bit6":          "Tx Power (1 octet, signed dBm)",
                "RFU_bit7":                       "Reserved for future use",
            },
        })
        d.setdefault("hci_command_groups", [
            {"OGF_hex": "0x01", "name": "Link Control",            "purpose": "Disconnect / Read Remote Version / Authentication (BR/EDR origin)"},
            {"OGF_hex": "0x02", "name": "Link Policy",             "purpose": "Hold / Sniff / Park / QoS (BR/EDR origin)"},
            {"OGF_hex": "0x03", "name": "Controller & Baseband",   "purpose": "Reset / Set Event Mask / Read Local Supported Commands / Read Buffer Size / etc."},
            {"OGF_hex": "0x04", "name": "Informational Parameters", "purpose": "Read Local Version / Read Local Supported Features / Read BD_ADDR / etc."},
            {"OGF_hex": "0x05", "name": "Status Parameters",       "purpose": "Read RSSI / Read Failed Contact Counter / etc."},
            {"OGF_hex": "0x06", "name": "Testing Commands",        "purpose": "Read Loopback Mode / Write Loopback Mode / Enable Device Under Test Mode / etc."},
            {"OGF_hex": "0x08", "name": "LE Controller Commands",  "purpose": "All BLE-specific HCI commands: LE Set Advertising Parameters / LE Set Scan Parameters / LE Create Connection / LE Set PHY / LE Enable Encryption / LE Set Extended Advertising Parameters / LE Set Periodic Advertising Parameters / LE Set CIG Parameters / LE Create CIS / LE Enhanced Read Transmit Power Level / etc."},
            {"OGF_hex": "0x3F", "name": "Vendor Specific",          "purpose": "Vendor-defined commands"},
        ])
        d.setdefault("ll_feature_set_bitmap_examples_first_octet", {
            "purpose": "LL_FEATURE_REQ / LL_FEATURE_RSP carries an 8-octet Features bitmap (Section 4.6 Vol 6 Part B).",
            "bits": {
                "bit0":  "LE Encryption",
                "bit1":  "Connection Parameters Request Procedure",
                "bit2":  "Extended Reject Indication",
                "bit3":  "Slave-initiated Features Exchange",
                "bit4":  "LE Ping",
                "bit5":  "LE Data Packet Length Extension",
                "bit6":  "LL Privacy",
                "bit7":  "Extended Scanner Filter Policies",
            },
        })
        d.setdefault("ll_feature_set_bitmap_examples_second_octet", {
            "bits": {
                "bit8":   "LE 2M PHY",
                "bit9":   "Stable Modulation Index — Transmitter",
                "bit10":  "Stable Modulation Index — Receiver",
                "bit11":  "LE Coded PHY",
                "bit12":  "LE Extended Advertising",
                "bit13":  "LE Periodic Advertising",
                "bit14":  "Channel Selection Algorithm #2",
                "bit15":  "LE Power Class 1",
            },
        })
        d.setdefault("ll_feature_set_bitmap_examples_later_octets", {
            "bits": {
                "bit16":  "Minimum Number of Used Channels Procedure",
                "bit17":  "Connection CTE Request (BLE 5.1)",
                "bit18":  "Connection CTE Response (BLE 5.1)",
                "bit19":  "Connectionless CTE Transmitter (BLE 5.1)",
                "bit20":  "Connectionless CTE Receiver (BLE 5.1)",
                "bit21":  "Antenna Switching During CTE Transmission (AoD)",
                "bit22":  "Antenna Switching During CTE Reception (AoA)",
                "bit23":  "Receiving Constant Tone Extensions",
                "bit24":  "Periodic Advertising Sync Transfer — Sender (BLE 5.1)",
                "bit25":  "Periodic Advertising Sync Transfer — Recipient (BLE 5.1)",
                "bit26":  "Sleep Clock Accuracy Updates",
                "bit27":  "Remote Public Key Validation",
                "bit28":  "Connected Isochronous Streams — Master (BLE 5.2)",
                "bit29":  "Connected Isochronous Streams — Slave (BLE 5.2)",
                "bit30":  "Isochronous Broadcaster (BLE 5.2)",
                "bit31":  "Synchronized Receiver (BLE 5.2)",
                "bit32":  "Connected Isochronous Stream — Host Support",
                "bit33":  "LE Power Control Request (BLE 5.2)",
                "bit34":  "LE Power Change Indication (BLE 5.2)",
                "bit35":  "LE Path Loss Monitoring (BLE 5.2)",
            },
        })
        d["notes"] = (
            "Bluetooth Core v5.2 is a wireless protocol + host-controller-"
            "interface spec; no controller-internal register map is mandated. "
            "The closest controller-visible register set is the HCI "
            "command/event interface (Volume 4 Part E) plus the LL Data PDU "
            "header + Advertising PDU header bitfield layouts above. SoC-"
            "integrated BLE controllers expose additional vendor-specific "
            "control registers but those are out of scope of the Core Spec.")
        _write(p, d)

    # L5 ADI_SPEC
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d["analog_digital_interface_present"] = True
        d["signaling_summary"] = (
            "Bluetooth Low Energy 5.2 is a wireless 2.4 GHz radio protocol. "
            "The analog/RF parameters specified by Vol 6 Part A include: "
            "GFSK modulation with bandwidth-time product BT = 0.5; "
            "modulation index 0.45..0.55 (LE 1M / LE Coded), 0.45..0.55 "
            "(LE 2M with stable modulation index = 0.495..0.505 if SMI "
            "feature bit set); 40 RF channels each 2 MHz wide spanning "
            "2.4000-2.4835 GHz; symbol rate 1 Msym/s (LE 1M, LE Coded) or "
            "2 Msym/s (LE 2M); maximum transmit power +20 dBm (Class 1) / "
            "+10 dBm (Class 1.5) / +4 dBm (Class 2) / 0 dBm (Class 3); "
            "minimum receiver sensitivity ≤ -70 dBm at LE 1M, ≤ -75 dBm at "
            "LE 2M, ≤ -75 dBm at LE Coded S=2, ≤ -82 dBm at LE Coded S=8; "
            "frequency accuracy ≤ ±50 ppm over voltage / temperature; "
            "symbol timing accuracy ≤ ±50 ppm; in-band blocking, image "
            "rejection, and out-of-band blocking masks defined in Section "
            "4 of Vol 6 Part A.")
        d.setdefault("rf_parameters_summary", {
            "frequency_band_low_MHz":       2400.0,
            "frequency_band_high_MHz":      2483.5,
            "channel_count":                40,
            "channel_spacing_MHz":           2.0,
            "channel_0_center_MHz":         2402.0,
            "channel_36_center_MHz":        2478.0,
            "primary_adv_channel_37_MHz":   2402,
            "primary_adv_channel_38_MHz":   2426,
            "primary_adv_channel_39_MHz":   2480,
            "symbol_rate_1M_Msym_s":         1.0,
            "symbol_rate_2M_Msym_s":         2.0,
            "modulation":                    "GFSK, BT=0.5",
            "modulation_index_min":           0.45,
            "modulation_index_max":           0.55,
            "frequency_tolerance_ppm":        50,
            "symbol_timing_tolerance_ppm":    50,
        })
        d.setdefault("tx_power_classes", [
            {"class": "Class 1",   "max_tx_dBm":  20, "min_tx_dBm": -20,  "use_case": "Long-range, high-power applications; +20 dBm only on LE Coded with regulatory compliance."},
            {"class": "Class 1.5", "max_tx_dBm":  10, "min_tx_dBm": -20,  "use_case": "Mid-range power; common in BLE 5 LE Coded use."},
            {"class": "Class 2",   "max_tx_dBm":   4, "min_tx_dBm": -20,  "use_case": "Mid-power consumer (smartphones, BLE peripherals)."},
            {"class": "Class 3",   "max_tx_dBm":   0, "min_tx_dBm": -20,  "use_case": "Low-power coin-cell devices."},
        ])
        d.setdefault("receiver_sensitivity", [
            {"PHY": "LE 1M",       "max_sensitivity_dBm": -70, "BER_pct_target": 0.1, "notes": "30.7% packet error rate at -70 dBm with 37-byte payload."},
            {"PHY": "LE 2M",       "max_sensitivity_dBm": -70, "BER_pct_target": 0.1, "notes": "Same PER target as 1M; lower sensitivity due to higher bandwidth."},
            {"PHY": "LE Coded S=2", "max_sensitivity_dBm": -75, "BER_pct_target": 0.1, "notes": "FEC + interleaver improve sensitivity ~5 dB over LE 1M."},
            {"PHY": "LE Coded S=8", "max_sensitivity_dBm": -82, "BER_pct_target": 0.1, "notes": "Up to 12 dB improvement over LE 1M — ~4x range."},
        ])
        d.setdefault("voltage_classes", [
            "VDD_RADIO  — typically 1.8 V or 3.3 V; per-controller-vendor",
            "VDD_DIGITAL — typically 0.9-1.2 V core supply",
            "VDD_IO     — 1.8 V / 3.3 V I/O ring",
            "Coin-cell battery operation common (CR2032 nominal 3.0 V) for low-power Peripherals",
            "Energy harvesting (NFC / solar / piezo) supported in LE 5.2 LE Audio Hearing Access scenarios",
        ])
        d.setdefault("rssi_path_loss_5_2",
            "BLE 5.2 LE Power Control + Path Loss Monitoring exchange RSSI estimates over LL_POWER_CONTROL_REQ / LL_POWER_CONTROL_RSP / LL_POWER_CHANGE_IND, allowing TX-power adjustment per remote-peer feedback. Path-Loss thresholds (HIGH / MIDDLE / LOW) can be set per zone; controller raises a Path Loss Threshold Event when crossing a zone.")
        _write(p, d)

    # L6 CONTROL_LOGIC
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("device_visible_states", [
            {"name": "Standby",     "description": "Initial / idle state. No packets transmitted or received. Entered after power-on or after the Link Layer terminates a connection or aborts a procedure."},
            {"name": "Advertising", "description": "Device transmits advertising PDUs (ADV_IND, ADV_DIRECT_IND, ADV_NONCONN_IND, ADV_SCAN_IND, ADV_EXT_IND) on primary advertising channels 37 / 38 / 39 at a programmable advertising interval."},
            {"name": "Scanning",    "description": "Device listens for advertising PDUs; passive scan (RX only) or active scan (RX + SCAN_REQ + SCAN_RSP exchange)."},
            {"name": "Initiating",  "description": "Device listens on primary advertising channels for ADV_IND / ADV_DIRECT_IND from a target peer; on match transmits CONNECT_IND (or AUX_CONNECT_REQ for extended) to establish a connection."},
            {"name": "Connection",  "description": "After successful CONNECT_IND exchange, two devices enter the Connection state. The Central (master) schedules each connection event; the Peripheral (slave) listens at the scheduled anchor."},
            {"name": "Synchronization (BLE 5)", "description": "Receiver synchronized to a Periodic Advertising train; receives AUX_SYNC_IND on a deterministic periodic schedule on data channels."},
            {"name": "Isochronous Broadcast (BLE 5.2)", "description": "Broadcaster transmits BIS PDUs on data channels per ISO event schedule; receivers acquire BIG sync via Broadcast Audio Source Endpoint (BASE) discovery."},
        ])
        # Force-merge BLE FSM sub-keys: UART R59 already populated fsm_hints
        # with tx_trigger/rx_trigger/oversampling and default_ready_state_rec
        # with SOUT_idle/SIN_idle. setdefault on the parent dict no-ops in
        # that case. Merge BLE-canonical sub-keys instead.
        fh = d.get("fsm_hints")
        if not isinstance(fh, dict):
            fh = {}
            d["fsm_hints"] = fh
        fh.setdefault("central_role",  "Initiates the connection (Initiating state → Connection state). Schedules and starts each connection event by transmitting the first LL Data PDU. Manages Channel Map updates, Connection Parameter updates, Encryption setup, PHY Update, CIS creation.")
        fh.setdefault("peripheral_role", "Advertises in Advertising state; accepts CONNECT_IND from an Initiator. Once in Connection state, listens at each anchor for the Central's PDU and responds. May reject parameter updates by issuing LL_REJECT_IND or LL_REJECT_EXT_IND.")
        fh.setdefault("advertiser_role", "Broadcaster — transmits advertising PDUs without expectation of a response (ADV_NONCONN_IND / ADV_SCAN_IND); cycles through channels 37/38/39 per advertising event.")
        fh.setdefault("scanner_role",  "Observer — passive scan listens for broadcast packets; active scan additionally sends SCAN_REQ to elicit a SCAN_RSP carrying extra data.")
        # v0.1.90 — force-overwrite (not setdefault): the USB synth fires first
        # on the BLE doc (LL framing resembles Token/Data/Handshake) and leaves a
        # USB DATA-toggle "rule"; BLE's LL FSM is the correct one-of-six.
        fh["rule"] =                   "The Link Layer FSM is one-of-six (Standby / Advertising / Scanning / Initiating / Connection / Synchronization); state transitions are triggered by HCI commands (LE Set Advertising Enable / LE Set Scan Enable / LE Create Connection / LE Periodic Advertising Create Sync / LE Set Extended Advertising Enable / LE Disconnect) and by Link-Layer procedures (CONNECT_IND received, supervision timeout)."
        # Force-overwrite anti_deadlock_rule + exit_from_reset_or_poweron —
        # UART R59 populated these with UART-specific text.
        _force(d, "anti_deadlock_rule",
            "Each connection event has a Connection Event Length budget; if both ends exhaust the budget the event ends and the next event resumes at the next anchor. Supervision Timeout (100 ms..32 s) bounds maximum link-loss detection latency; on expiry the Link Layer drops to Standby and signals HCI Disconnection Complete to the host.")
        _force(d, "exit_from_reset_or_poweron",
            "After radio reset the Link Layer is in Standby. The host issues HCI Reset, then LE Set Random Address / LE Set Advertising Parameters / LE Set Advertising Enable (to advertise) or LE Set Scan Parameters / LE Set Scan Enable (to scan) or LE Create Connection (to initiate). For BLE 5 extended use, LE Set Extended Advertising Parameters / LE Set Extended Advertising Data / LE Set Extended Advertising Enable are used instead.")
        drs = d.get("default_ready_state_recommendation")
        if not isinstance(drs, dict):
            drs = {}
            d["default_ready_state_recommendation"] = drs
        drs.setdefault("radio_off",        "Radio powered down to save energy; controller in Standby.")
        drs.setdefault("advertising",      "Cycle through channels 37/38/39 every advertising interval; reset interval timer on each event.")
        drs.setdefault("scanning",         "Switch RX channel per scan window / scan interval; passive scan does not transmit.")
        drs.setdefault("connection_event", "Central starts event on the scheduled channel per Channel Selection Algorithm #1 or #2; Peripheral listens at the same channel; both ends use the same hop sequence.")
        d.setdefault("advertising_pdu_relationships", [
            {"name": "ADV_IND",         "next_state_after_CONNECT_IND": "Connection",        "rule": "Connectable + scannable undirected advertising; any scanner may issue SCAN_REQ; any initiator may issue CONNECT_IND."},
            {"name": "ADV_DIRECT_IND",   "next_state_after_CONNECT_IND": "Connection",        "rule": "Connectable directed advertising; only the InitA target may respond with CONNECT_IND; high-duty-cycle mode for fast reconnect."},
            {"name": "ADV_NONCONN_IND",  "next_state_after_CONNECT_IND": "(never connects)",   "rule": "Non-connectable + non-scannable; broadcast only; iBeacon / Eddystone use this."},
            {"name": "ADV_SCAN_IND",     "next_state_after_CONNECT_IND": "(never connects)",   "rule": "Scannable non-connectable; scanner may issue SCAN_REQ for SCAN_RSP extra data."},
            {"name": "ADV_EXT_IND",      "next_state_after_CONNECT_IND": "Connection",        "rule": "Extended advertising primary; AdvData may be empty or point to AUX_ADV_IND via AuxPtr."},
            {"name": "AUX_ADV_IND",      "next_state_after_CONNECT_IND": "Connection",        "rule": "Auxiliary advertising on a data channel carrying the bulk of extended advertising data."},
            {"name": "AUX_SYNC_IND",     "next_state_after_CONNECT_IND": "(never connects)",   "rule": "Periodic Advertising broadcast on data channels at the periodic interval; no scan / connect handshake."},
        ])
        d.setdefault("data_channel_index_rule",
            "During a connection (or Periodic Advertising sync), the channel for the next event is computed by Channel Selection Algorithm #1 (sequential ring) or #2 (BLE 5 deterministic permutation with anti-collision); bad channels in the Channel Map are skipped, and the event uses the next good channel in the sequence.")
        d.setdefault("supervision_timeout_rule",
            "If no valid CRC-passing PDU is received within the Supervision Timeout window (100 ms..32 s, 10 ms steps, must exceed (1 + Slave Latency) * Connection Interval * 2), the Link Layer terminates the connection and signals Disconnection Complete to the host.")
        _write(p, d)

    # L7 TEST_DEBUG (DTM)
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d["test_debug_architecture_present"] = True
        d.setdefault("direct_test_mode_DTM_present", True)
        d.setdefault("direct_test_mode_overview",
            "Volume 6 Part F (Direct Test Mode) defines a test interface allowing a tester to drive the controller into a deterministic RF state (LE Test, LE Transmitter Test, LE Receiver Test, LE Test End) over either HCI or a 2-wire UART for production-line / certification testing. All 40 channels can be selected; LE 1M, LE 2M, LE Coded S=2, LE Coded S=8 are supported.")
        d.setdefault("dtm_command_set", [
            {"name": "LE_TRANSMITTER_TEST",                 "purpose": "Start transmitter test on a given channel with a given packet pattern (PRBS9 / 11110000 / 10101010 / PRBS15 / all-1 / all-0 / 0000_1111 / 0101_0101) and length."},
            {"name": "LE_RECEIVER_TEST",                    "purpose": "Start receiver test on a given channel; reports number of packets received."},
            {"name": "LE_TEST_END",                         "purpose": "End the test; for receiver test returns packet count; for transmitter returns success only."},
            {"name": "LE_ENHANCED_TRANSMITTER_TEST",        "purpose": "Like LE_TRANSMITTER_TEST but parameterized by PHY (1M / 2M / Coded S=2 / Coded S=8) and modulation index (Standard / Stable)."},
            {"name": "LE_ENHANCED_RECEIVER_TEST",           "purpose": "Like LE_RECEIVER_TEST with PHY + modulation-index selection."},
            {"name": "LE_TRANSMITTER_TEST_v3",              "purpose": "Adds antenna-switching pattern (CTE) for direction-finding test (BLE 5.1)."},
            {"name": "LE_RECEIVER_TEST_v3",                 "purpose": "Adds antenna-switching pattern for AoA test (BLE 5.1)."},
        ])
        d.setdefault("spec_provided_observability", [
            {"name": "HCI Read RSSI",                      "purpose": "Returns RSSI value in dBm for a given connection handle."},
            {"name": "HCI LE Read Channel Map",            "purpose": "Returns the 37-bit Channel Map currently in use for a connection."},
            {"name": "HCI LE Read Remote Features",        "purpose": "Triggers LL_FEATURE_REQ + reports remote LL feature bitmap."},
            {"name": "HCI Read Local Supported Features",  "purpose": "Returns the controller's supported LMP / LL feature bitmap."},
            {"name": "HCI LE Read Local P-256 Public Key", "purpose": "Returns local ECDH P-256 public key for LE Secure Connections debug."},
            {"name": "HCI LE Read Transmit Power",         "purpose": "Returns min/max TX power capability."},
            {"name": "HCI LE Enhanced Read Transmit Power Level (BLE 5.2)", "purpose": "Returns current + max TX power for a given PHY + connection handle."},
            {"name": "HCI LE Path Loss Threshold Event (BLE 5.2)",          "purpose": "Reports current path-loss zone transition (HIGH / MIDDLE / LOW)."},
            {"name": "HCI LE Transmit Power Reporting Event (BLE 5.2)",     "purpose": "Reports a remote-peer-driven TX power change."},
        ])
        d.setdefault("error_detection_mechanisms", [
            "CRC-24 on every PDU (polynomial 0x100065B) — receivers silently drop CRC-failing PDUs.",
            "Access Address mismatch — receiver discards packet at preamble correlation.",
            "Per-PHY symbol-error correction: LE Coded S=2 uses BCH FEC over 4-bit blocks; LE Coded S=8 adds an 8x repetition stage.",
            "Sequence Number / NESN tracking forces retransmission on dropped data PDUs in a connection.",
            "Encryption MIC failure (AES-CCM 4-octet MIC) terminates the connection with reason 'MIC Failure' (0x3D).",
        ])
        d.setdefault("interrupt_or_event_sources", [
            {"event": "HCI Disconnection Complete",                       "trigger": "Connection terminated (timeout / LL_TERMINATE_IND / encryption failure)."},
            {"event": "HCI LE Connection Complete",                       "trigger": "CONNECT_IND processed; new connection ready."},
            {"event": "HCI LE Advertising Report",                         "trigger": "Scanner received a non-connectable advertising packet."},
            {"event": "HCI LE Extended Advertising Report (BLE 5)",        "trigger": "Scanner received any extended advertising packet."},
            {"event": "HCI LE Periodic Advertising Sync Established",      "trigger": "Periodic Advertising sync acquired."},
            {"event": "HCI LE Periodic Advertising Report",                "trigger": "AUX_SYNC_IND received during periodic sync."},
            {"event": "HCI LE CIS Established Event (BLE 5.2)",            "trigger": "CIS_REQ/RSP/IND sequence completed."},
            {"event": "HCI LE Path Loss Threshold Event (BLE 5.2)",        "trigger": "Path-loss zone change."},
            {"event": "HCI LE Channel Selection Algorithm Event",          "trigger": "Connection now uses Algorithm #2."},
        ])
        # Force-overwrite notes (UART R59 / USB R65 populate this with their
        # 16450/16550 lineage / EHCI Debug Port narrative).
        _force(d, "notes",
            "Beyond Direct Test Mode (Vol 6 Part F) and HCI status/event APIs, the spec leaves SoC-internal scan/JTAG/BIST to the chip integrator. Bluetooth Qualification (Profile Tuning Suite, PTS) tests cover protocol-level conformance and interoperability — they consume DTM + HCI but do not extend the spec itself.")
        # BLE-canonical absent key: no USB-style HS test modes apply.
        d.setdefault("test_modes_high_speed_only_compat", [
            "Not applicable — BLE has no equivalent of USB 'HS test modes'; DTM is the standardized production-line test mechanism."
        ])
        _write(p, d)

    # L8 RTL_CONSTANTS
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.get("width_parameters")
        if not isinstance(wp, dict):
            wp = {}
            d["width_parameters"] = wp
        # Force-overwrite DEVICE_ADDRESS_WIDTH_bits — USB R65 pre-seeded 7
        # for USB device-address; BLE BD_ADDR is 48-bit.
        _force(wp, "DEVICE_ADDRESS_WIDTH_bits", 48)
        if True:
            for k, v in {
                "ACCESS_ADDRESS_WIDTH_bits":            32,
                "PREAMBLE_WIDTH_bits_1M":                 8,
                "PREAMBLE_WIDTH_bits_2M":                16,
                "PREAMBLE_WIDTH_bits_Coded":             80,
                "PDU_HEADER_WIDTH_bits":                 16,
                "LLID_WIDTH_bits":                         2,
                "NESN_WIDTH_bits":                         1,
                "SN_WIDTH_bits":                           1,
                "MD_WIDTH_bits":                           1,
                "CP_WIDTH_bits":                           1,
                "ADV_PDU_TYPE_WIDTH_bits":                4,
                "ADV_RFU_WIDTH_bits":                      1,
                "ADV_ChSel_WIDTH_bits":                    1,
                "ADV_TxAdd_WIDTH_bits":                    1,
                "ADV_RxAdd_WIDTH_bits":                    1,
                "PDU_LENGTH_WIDTH_bits":                   8,
                "CRC_WIDTH_bits":                         24,
                "MIC_WIDTH_bits":                         32,
                "CHANNEL_INDEX_WIDTH_bits":                6,
                "DATA_CHANNEL_COUNT":                    37,
                "PRIMARY_ADV_CHANNEL_COUNT":               3,
                "TOTAL_RF_CHANNEL_COUNT":                40,
                "CHANNEL_MAP_WIDTH_bits":                37,
                "CONNECTION_INTERVAL_UNIT_us":          1250,
                "CONNECTION_INTERVAL_MIN_value":           6,
                "CONNECTION_INTERVAL_MAX_value":        3200,
                "SLAVE_LATENCY_MAX":                     499,
                "SUPERVISION_TIMEOUT_UNIT_ms":             10,
                "SUPERVISION_TIMEOUT_MIN_value":          10,
                "SUPERVISION_TIMEOUT_MAX_value":        3200,
                "INTER_FRAME_SPACE_T_IFS_us":            150,
                "INTER_FRAME_SPACE_T_IFS_tolerance_us":    2,
                "MIC_LENGTH_bytes":                        4,
                "PACKET_COUNTER_WIDTH_bits":              39,
                "PERIODIC_ADV_INTERVAL_UNIT_125us":       125,
                "PERIODIC_ADV_INTERVAL_MIN_value":          6,
                "PERIODIC_ADV_INTERVAL_MAX_value":      65535,
                "MAX_PDU_PAYLOAD_LEGACY_bytes":           37,
                "MAX_PDU_PAYLOAD_DATA_LE_4_2_bytes":      251,
                "MAX_PDU_PAYLOAD_EXTENDED_bytes":         255,
                "EXTENDED_ADV_MAX_DATA_per_chain_bytes": 1650,
                "BIG_MAX_NUM_BIS":                        31,
                "CIG_MAX_NUM_CIS":                        31,
            }.items():
                wp.setdefault(k, v)
        # Merge BLE CRC-24 sub-keys into crc_polynomials — UART R59 / USB R65
        # pre-populated CRC5/CRC16 here for their respective protocols.
        cp = d.get("crc_polynomials")
        if not isinstance(cp, dict):
            cp = {}
            d["crc_polynomials"] = cp
        cp.setdefault("CRC24_polynomial",  "x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1")
        cp.setdefault("CRC24_hex",         "0x100065B")
        cp.setdefault("CRC24_covers",      "PDU header + payload (excluding Preamble + Access Address)")
        cp.setdefault("CRC24_initial_value_advertising", "0x555555")
        cp.setdefault("CRC24_initial_value_data",         "Per-connection negotiated value (derived from CONNECT_IND CRCInit field)")
        cp.setdefault("CRC24_LSB_first",   "Yes — bits sent LSB first; polynomial reversed in implementation")
        # Merge BLE PHY sub-keys into signaling_speeds.
        ss = d.get("signaling_speeds")
        if not isinstance(ss, dict):
            ss = {}
            d["signaling_speeds"] = ss
        ss.setdefault("LE_1M",       {"symbol_rate_Msym_s": 1.0, "bit_rate_Mb_s": 1.0,    "preamble_bits":  8, "use_case": "BLE 4.x default; mandatory for any 5.x device"})
        ss.setdefault("LE_2M",       {"symbol_rate_Msym_s": 2.0, "bit_rate_Mb_s": 2.0,    "preamble_bits": 16, "use_case": "BLE 5 high-throughput PHY"})
        ss.setdefault("LE_Coded_S2", {"symbol_rate_Msym_s": 1.0, "effective_rate_kb_s": 500, "preamble_bits": 80, "use_case": "BLE 5 long-range S=2 (FEC 2x)"})
        ss.setdefault("LE_Coded_S8", {"symbol_rate_Msym_s": 1.0, "effective_rate_kb_s": 125, "preamble_bits": 80, "use_case": "BLE 5 long-range S=8 (FEC 8x)"})
        d.setdefault("channel_frequency_table_summary", {
            "data_channel_0_MHz":      2404,
            "data_channel_1_MHz":      2406,
            "data_channel_2_MHz":      2408,
            "data_channel_3_MHz":      2410,
            "data_channel_4_MHz":      2412,
            "data_channel_5_MHz":      2414,
            "data_channel_6_MHz":      2416,
            "data_channel_7_MHz":      2418,
            "data_channel_8_MHz":      2420,
            "data_channel_9_MHz":      2422,
            "data_channel_10_MHz":     2424,
            "data_channel_11_MHz":     2428,
            "data_channel_12_MHz":     2430,
            "data_channel_36_MHz":     2478,
            "primary_adv_channel_37_MHz": 2402,
            "primary_adv_channel_38_MHz": 2426,
            "primary_adv_channel_39_MHz": 2480,
            "note": "Data channel indices 0..10 map to 2404..2424 MHz (skipping 2402 which is adv-37); 11..36 map to 2428..2478 MHz (skipping 2426 which is adv-38). Primary advertising 37=2402, 38=2426, 39=2480 MHz.",
        })
        # Merge BLE RTL constants into existing dict — UART R59 already
        # populated key_constants_for_RTL_authoring with UART sub-keys
        # (oversampling_x / start_bit_value etc.).
        kc = d.get("key_constants_for_RTL_authoring")
        if not isinstance(kc, dict):
            kc = {}
            d["key_constants_for_RTL_authoring"] = kc
        for _k, _v in {
            "modulation":                "GFSK with BT=0.5; modulation index 0.45..0.55 (Standard); 0.495..0.505 (Stable Modulation Index)",
            "whitening_polynomial":      "x^7 + x^4 + 1 (7-bit LFSR seeded with channel index || 1, LSB position 6 first)",
            "advertising_access_address_hex": "0x8E89BED6",
            "advertising_crc_init_hex":  "0x555555",
            "T_IFS_us":                  150,
            "T_IFS_tolerance_us":        2,
            "min_connection_interval_ms": 7.5,
            "max_connection_interval_ms": 4000.0,
            "connection_interval_step_ms": 1.25,
            "min_supervision_timeout_ms":  100,
            "max_supervision_timeout_ms": 32000,
            "max_slave_latency":          499,
            "primary_adv_min_interval_ms": 20,
            "primary_adv_max_interval_ms": 10240,
            "scan_window_min_ms":          2.5,
            "scan_window_max_ms":      10240.0,
            "ce_length_unit_us":          625,
            "encryption":                 "AES-128 CCM with per-direction 39-bit packet counter + 4-octet MIC",
            "ecdh_curve":                 "NIST P-256 for LE Secure Connections",
            "preamble_pattern_1M":        "0xAA (alternating 0/1, 8 bits)",
            "preamble_pattern_2M":        "0xAAAA (alternating 0/1, 16 bits)",
            "preamble_pattern_Coded":     "10 octets of 00111100 (80 bits, conventional preamble)",
        }.items():
            kc.setdefault(_k, _v)
        # Merge BLE idle states into existing default_signal_state_when_idle
        # — UART R59 set SOUT_idle/SIN_idle there.
        ds = d.get("default_signal_state_when_idle")
        if not isinstance(ds, dict):
            ds = {}
            d["default_signal_state_when_idle"] = ds
        ds.setdefault("radio_off",       "Radio fully powered down to save energy.")
        ds.setdefault("advertising_off", "No transmissions; baseband may be clock-gated.")
        ds.setdefault("scanning_off",    "Receiver off; antenna terminated.")
        _write(p, d)

    # L8 TIMING_WAVEFORM
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("connection_event_structure", {
            "anchor_point_definition":          "First bit of the Master's first packet starts each connection event; the anchor recurs every Connection Interval.",
            "Connection_Interval_unit_us":      1250,
            "Connection_Interval_min_value":       6,
            "Connection_Interval_max_value":    3200,
            "min_Connection_Interval_ms":          7.5,
            "max_Connection_Interval_ms":       4000.0,
            "Slave_Latency_max":                 499,
            "Supervision_Timeout_unit_ms":        10,
            "Supervision_Timeout_min_value":      10,
            "Supervision_Timeout_max_value":    3200,
            "T_IFS_us":                          150,
            "T_IFS_tolerance_us":                  2,
            "CE_Length_unit_us":                 625,
        })
        d.setdefault("advertising_event_structure", {
            "Advertising_Interval_unit_625us":  625,
            "Advertising_Interval_min_value":     32,
            "Advertising_Interval_max_value":  16384,
            "min_Advertising_Interval_ms":         20,
            "max_Advertising_Interval_ms":      10240,
            "Advertising_Delay_max_ms":            10,
            "AUX_Offset_units_us":               [30, 300],
            "extended_adv_PHY_options":          ["LE 1M (primary)", "LE Coded (primary)", "LE 1M / 2M / Coded (aux)"],
        })
        d.setdefault("periodic_advertising_event_structure", {
            "Periodic_Advertising_Interval_unit_us":  1250,
            "Periodic_Advertising_Interval_min_ms":     7.5,
            "Periodic_Advertising_Interval_max_ms": 81918.75,
            "Sync_Timeout_unit_ms":                    10,
            "Sync_Timeout_min_value":                  10,
            "Sync_Timeout_max_value":               16384,
        })
        d.setdefault("isochronous_event_structure_5_2", {
            "ISO_Interval_unit_1_25_ms":           1.25,
            "ISO_Interval_min_ms":                  5,
            "ISO_Interval_max_ms":                  4000,
            "SDU_Interval_unit_us":                  1,
            "Max_Transport_Latency_unit_ms":        1,
            "FT_Flush_Timeout_min":                  1,
            "FT_Flush_Timeout_max":                 15,
            "BN_Burst_Number_min":                   1,
            "BN_Burst_Number_max":                  15,
            "NSE_Number_of_Subevents_min":           1,
            "NSE_Number_of_Subevents_max":          31,
        })
        # Merge BLE packet_timing into existing dict — USB R65 / UART R59
        # pre-seeded their own packet timing sub-keys.
        pt = d.get("packet_timing")
        if not isinstance(pt, dict):
            pt = {}
            d["packet_timing"] = pt
        for _k, _v in {
            "Preamble_bits_LE_1M":                8,
            "Preamble_bits_LE_2M":               16,
            "Preamble_bits_LE_Coded":            80,
            "Access_Address_bits":               32,
            "PDU_header_bits":                    16,
            "Payload_max_bytes_legacy_data":      37,
            "Payload_max_bytes_data_LE_4_2":     251,
            "Payload_max_bytes_extended_adv":    255,
            "CRC_bits":                          24,
            "MIC_bits_when_encrypted":           32,
            "T_IFS_us_between_consecutive_PDUs": 150,
            "primary_to_auxiliary_AuxOffset_us_min": 300,
            "primary_to_auxiliary_AuxOffset_us_max": 245700,
        }.items():
            pt.setdefault(_k, _v)
        sw = d.get("signaling_waveforms")
        if not isinstance(sw, dict):
            sw = {}
            d["signaling_waveforms"] = sw
        for _k, _v in {
            "GFSK_modulation":               "GFSK with BT=0.5; pre-modulation Gaussian low-pass filter applied before VCO frequency modulation",
            "modulation_index":              "Standard: 0.45..0.55; Stable Modulation Index (BLE 5): 0.495..0.505",
            "transmit_power_step_dB":         2,
            "transmit_power_step_tolerance_dB": 2,
            "Power_Control_lower_limit_dBm":   -20,
            "LE_1M_eye_pattern":              "Defined by Section 4 of Vol 6 Part A; tolerated frequency deviation per symbol",
            "LE_2M_eye_pattern":              "Tighter due to higher symbol rate; same dF tolerance scaled to 1 µs symbol",
            "LE_Coded_S2_FEC":                "Block-coded BCH with rate 1/2 + 4-bit block; interleaved across 32-bit blocks",
            "LE_Coded_S8_FEC":                "BCH 1/2 + 8x repetition; effective rate 1/8 per uncoded bit",
        }.items():
            sw.setdefault(_k, _v)
        dt = d.get("data_signaling_rate_tolerance")
        if not isinstance(dt, dict):
            dt = {}
            d["data_signaling_rate_tolerance"] = dt
        for _k, _v in {
            "frequency_tolerance_ppm": 50,
            "symbol_timing_tolerance_ppm": 50,
            "active_clock_accuracy_ppm_options": [20, 30, 50, 75, 100, 150, 250, 500],
            "sleep_clock_accuracy_ppm_options":  [251, 151, 101, 76, 51, 31, 21, 1],
        }.items():
            dt.setdefault(_k, _v)
        d.setdefault("channel_dwell_times", {
            "scan_window_min_ms":   2.5,
            "scan_window_max_ms":  10240.0,
            "scan_interval_min_ms": 2.5,
            "scan_interval_max_ms": 10240.0,
        })
        d.setdefault("antenna_switching_CTE_5_1", {
            "CTE_Type":             ["AoA (Angle of Arrival)", "AoD 1 µs slot (Angle of Departure)", "AoD 2 µs slot"],
            "CTE_Length_min_us":     16,
            "CTE_Length_max_us":    160,
            "CTE_Length_unit_us":     8,
            "switching_slot_us":      1,
            "switching_slot_us_AoD":  2,
            "reference_period_us":    4,
        })
        _write(p, d)

    # L9 INTEGRATION_SPEC
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite identity narratives — UART R59 / USB R65 / RS-485 R137
        # populated these with their own protocol's module_role /
        # topology_description / idle defaults.
        _force(d, "module_role",
            "Wireless personal-area-network protocol stack specification. Defines the full BLE stack (Volume 6 LE Controller PHY + Link Layer + Direct Test Mode; Volume 3 Host = L2CAP, ATT, GATT, SMP, GAP) plus the Host Controller Interface (Volume 4 Part E) that bridges Controller and Host. SoC-internal hardware register map of a BLE controller is NOT specified — that is vendor-specific.")
        _force(d, "topology_description",
            "Star or scatternet. A Central may simultaneously hold multiple connections (typical phone-class controllers support 1..20 connections); a Peripheral typically holds 1 connection (some BLE 5 stacks support multi-link). Broadcasters + Observers are connectionless. BLE 5 LE Audio adds Connected (CIG / CIS) + Broadcast (BIG / BIS) Isochronous Groups for multi-stream audio.")
        # Merge BLE integration_overview sub-keys — USB R65 may have
        # populated integration_overview with USB-specific keys.
        io = d.get("integration_overview")
        if not isinstance(io, dict):
            io = {}
            d["integration_overview"] = io
        for _k, _v in {
            "host_controller_split_supported":      True,
            "hci_transports":                       ["UART (H4 / H5)", "USB (Bluetooth HCI USB)", "SDIO", "SPI", "vendor-defined"],
            "rf_pin_count_typical":                 1,
            "antenna_options":                      ["integrated PCB chip antenna", "external antenna via U.FL connector", "antenna-array for AoA/AoD direction finding"],
            "supply_typical_V":                     [1.8, 3.0, 3.3],
            "min_battery_voltage_for_BLE_typical_V": 1.8,
            "low_power_modes":                      ["radio-off / standby", "advertising idle slots", "connection sleep latency", "sleep clock accuracy 251..500 ppm in deep sleep"],
        }.items():
            io.setdefault(_k, _v)
        d.setdefault("interface_categories", [
            "BLE Controller (PHY + Link Layer; Volume 6 + Volume 1 Part A)",
            "Host (L2CAP + ATT + GATT + SMP + GAP; Volume 3)",
            "Host Controller Interface (Volume 4 Part E)",
            "BLE Audio Profiles (BAP / PACS / CSIP / VCP / MCP / TMAP) layered on GATT (Volume 3 + supplemental profile specs)",
            "GATT-based application profiles (Heart Rate / Battery / Cycling Speed / Mesh / etc.)",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Star — one Central connected to multiple Peripherals.",
            "Scatternet — device acts as Central in one piconet and Peripheral in another (multi-role).",
            "Broadcaster + Observer — connectionless one-to-many broadcast.",
            "Mesh (Bluetooth Mesh) — layered on top of BLE advertising / GATT bearers (not Core spec, separate Mesh spec).",
            "Connected Isochronous Group (CIG) — BLE 5.2; one Central + multiple Peripherals share a synchronized isochronous transport (LE Audio Unicast).",
            "Broadcast Isochronous Group (BIG) — BLE 5.2; one Broadcaster + multiple Synchronized Receivers (LE Audio Broadcast).",
        ])
        # Force-overwrite — UART R59 wrote "See L4 register reset values..."
        _force(d, "default_signal_values_when_omitted",
            "Radio in Standby; antenna terminated; baseband clock-gated. Controller's HCI transport remains active to receive commands from host.")
        d.setdefault("soc_dependent_items", [
            "Choice of 2.4 GHz radio architecture (zero-IF / low-IF / direct conversion).",
            "Frequency synthesis (integer-N / fractional-N PLL; crystal frequency 16 MHz / 24 MHz / 32 MHz / 48 MHz typical).",
            "Baseband modem (GFSK modulator, coherent / non-coherent demodulator, optional Coded PHY BCH decoder).",
            "AES-128 cryptographic accelerator (CCM + ECDH P-256 for LE Secure Connections).",
            "Antenna interface (single-ended or differential; impedance matching network).",
            "Antenna array + RF switch for AoA/AoD direction finding.",
            "Sleep clock source (typically 32.768 kHz crystal; sleep-clock-accuracy 21..500 ppm options).",
            "HCI transport peripheral block (UART / USB device / SDIO / SPI / proprietary).",
            "Power-management for coin-cell-class operation (1.8 V LDO + DC-DC boost).",
            "Energy-harvesting front-end for LE 5.2 Hearing Access scenarios.",
        ])
        # Merge BLE low_power_modes sub-keys — USB R65 may have populated
        # this with USB suspend/remote-wake terminology.
        lp = d.get("low_power_modes")
        # Hazard: top-level `low_power_modes` is also used as a LIST under
        # integration_overview. For L9 top-level it should be a dict.
        if not isinstance(lp, dict):
            lp = {}
            d["low_power_modes"] = lp
        for _k, _v in {
            "Radio_Off":                          "Radio fully powered down; controller wakes via host or scheduler.",
            "Advertising_Idle":                    "Between advertising events; entire RF chain off; ~µA-class power.",
            "Connection_Slave_Latency":            "Peripheral skips up to Slave Latency connection events without responding; allows long sleep between anchors.",
            "Periodic_Advertising_Idle":           "Receiver wakes only at the periodic-adv anchor; otherwise sleeps.",
            "Deep_Sleep_with_Sleep_Clock":         "Active RF off; 32.768 kHz sleep clock counts down to next anchor; SCA 21..500 ppm options trade accuracy vs current.",
        }.items():
            lp.setdefault(_k, _v)
        d.setdefault("device_classes_examples", [
            "Heart Rate Sensor / Blood Pressure / Glucose Meter (Medical Device Profile)",
            "Beacon / Eddystone / iBeacon (Broadcaster only, ADV_NONCONN_IND)",
            "Wireless Headphone / Hearing Aid (LE Audio CIS, BLE 5.2)",
            "Mesh light bulb / sensor (Bluetooth Mesh, BLE advertising bearer)",
            "Bluetooth keyboard / mouse (HID over GATT)",
            "Smart watch / fitness band (multi-role Peripheral + Central)",
            "Indoor positioning anchor (AoA / AoD, BLE 5.1)",
        ])
        _write(p, d)

    # L10 TEST_CASES
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        # Clear gen_l10's per-opcode test_cases — BLE is packet-based, not
        # byte-opcode-driven (same fix as JTAG/HDLC v0.1.88).
        d["test_cases"] = []
        d["extraction_evidence"] = {}
        d["test_cases_present"] = (
            "partial - the spec defines compliance behaviors that map to "
            "formal qualification (Bluetooth SIG Profile Tuning Suite, PTS) "
            "plus Direct Test Mode (Vol 6 Part F) for production RF tests, "
            "but the spec itself does not include a testbench.")
        d.setdefault("derived_compliance_test_categories", [
            "Advertising on channels 37 / 38 / 39 — channel cycle order + advertising interval honoring.",
            "Scanning passive vs active — active scan SCAN_REQ → SCAN_RSP handshake.",
            "Initiating + connection setup — CONNECT_IND parameters (Access Address entropy + Hamming requirements, CRCInit, WinSize, WinOffset, Interval, Latency, Timeout, ChM, Hop, SCA) validated.",
            "Connection event scheduling — anchor recurrence at Connection Interval; T_IFS = 150 ± 2 µs honored.",
            "Sequence Number / NESN — retransmission on CRC error + correct toggle on success.",
            "Channel Selection Algorithm #1 (sequential ring) — every connection or PA event.",
            "Channel Selection Algorithm #2 (BLE 5 deterministic permutation) — anti-collision behavior.",
            "Channel Map update via LL_CHANNEL_MAP_IND — instant honored.",
            "Connection Parameter Update via LL_CONNECTION_UPDATE_IND or LL_CONNECTION_PARAM_REQ/RSP — instant honored.",
            "PHY Update via LL_PHY_REQ/RSP/UPDATE_IND — successful 1M → 2M / 1M → Coded / 2M → Coded transitions and back.",
            "LE Data Length Extension — LL_LENGTH_REQ/RSP — up to 251-octet payload accepted.",
            "Encryption setup via LL_ENC_REQ / LL_ENC_RSP / LL_START_ENC_REQ / LL_START_ENC_RSP — AES-CCM key derivation + MIC verification.",
            "LE Secure Connections pairing — ECDH P-256 key exchange + Numeric Comparison / Passkey / Just Works / OOB methods.",
            "LL_PING_REQ / LL_PING_RSP — authenticated payload protection.",
            "Extended Advertising — ADV_EXT_IND + AUX chain with AUX_ADV_IND, AUX_SYNC_IND, AUX_CHAIN_IND, AUX_SCAN_REQ, AUX_SCAN_RSP, AUX_CONNECT_REQ, AUX_CONNECT_RSP.",
            "Periodic Advertising — sync acquisition via PAST + scanning.",
            "Direction Finding — CTE transmit / receive on both AoA (1 µs slot) + AoD (1 µs and 2 µs slot).",
            "LE Power Control + Path Loss Monitoring (BLE 5.2) — LL_POWER_CONTROL_REQ/RSP/IND exchange + threshold-zone events.",
            "Connected Isochronous Streams (BLE 5.2) — CIG creation, CIS_REQ/RSP/IND/TERMINATE_IND, BN/NSE/FT honored.",
            "Broadcast Isochronous Streams (BLE 5.2) — BIG creation, BIS sync via BASE.",
            "Enhanced ATT (BLE 5.2) — multi-bearer ATT with per-bearer flow control.",
            "Supervision Timeout — Link Layer drops to Standby on expiry; HCI Disconnection Complete generated.",
            "Random address types — Public / Random Static / RPA / Random Private Non-Resolvable accepted in CONNECT_IND.",
            "GATT discovery — Primary Service Discovery / Characteristic Discovery / Descriptor Discovery.",
            "GATT notification + indication — Handle Value Notification / Handle Value Indication + Handle Value Confirmation.",
            "ATT MTU exchange — Exchange MTU Request / Response sets per-bearer MTU.",
            "L2CAP CoC (Connection-Oriented Channels) — flow-controlled and credit-based modes.",
            "SMP pairing — all four methods (Just Works / Passkey Entry / Numeric Comparison / OOB) successful + failure paths.",
            "Direct Test Mode — LE_TRANSMITTER_TEST + LE_RECEIVER_TEST on all 40 channels with PRBS9 / 11110000 / 10101010 / PRBS15 / all-1 / all-0 patterns at LE 1M / 2M / Coded S=2 / Coded S=8.",
        ])
        _write(p, d)

    # L11 OTP_CONTENT
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "Bluetooth Core v5.2 is a wireless protocol spec; it does not "
            "mandate OTP / fuse content at the controller layer. Individual "
            "BLE SoCs typically program (a) IEEE-issued 48-bit Bluetooth "
            "Device Address (BD_ADDR / Public Address), (b) trim values "
            "for the 2.4 GHz radio (PLL, LO leakage, mixer), (c) AES key "
            "storage for OOB pairing or LE Secure Connections debug keys, "
            "and (d) optionally the OEM identifier into OTP. The Bluetooth "
            "SIG assigns a Manufacturer Identifier (Company Identifier "
            "Code) per organization (16-bit value, used in advertising "
            "Manufacturer Specific Data fields). However these are per-"
            "implementation choices, not protocol-defined.")
        _write(p, d)

    # L12 BEHAVIORAL_SEQUENCES
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("advertising_event_sequence", [
            "1. Host issues HCI_LE_Set_Advertising_Parameters (or HCI_LE_Set_Extended_Advertising_Parameters for BLE 5).",
            "2. Host issues HCI_LE_Set_Advertising_Data + HCI_LE_Set_Scan_Response_Data.",
            "3. Host issues HCI_LE_Set_Advertising_Enable=1.",
            "4. Controller transitions Standby → Advertising; transmits advertising PDU on channel 37; immediately transmits on 38; immediately on 39.",
            "5. Sleeps until next advertising-interval anchor (+ random delay 0..10 ms to avoid lock-step collisions); repeats steps 4-5.",
        ])
        d.setdefault("scanning_event_sequence", [
            "1. Host issues HCI_LE_Set_Scan_Parameters (passive / active; window + interval).",
            "2. Host issues HCI_LE_Set_Scan_Enable=1.",
            "3. Controller transitions Standby → Scanning; opens scan window on channel 37 (or 38 / 39 per rotation).",
            "4. On reception of an advertising PDU passes payload to host via HCI_LE_Advertising_Report or HCI_LE_Extended_Advertising_Report.",
            "5. Active scanner additionally transmits SCAN_REQ when allowed by scan filter policy; receives SCAN_RSP and reports.",
            "6. At end of scan window, switches to next channel; resumes step 3.",
        ])
        d.setdefault("connection_setup_sequence", [
            "1. Host issues HCI_LE_Create_Connection (legacy) or HCI_LE_Extended_Create_Connection with target peer address + InitiatorFilterPolicy + Connection parameters.",
            "2. Controller transitions Standby → Initiating; scans channels 37/38/39 for matching ADV_IND / ADV_DIRECT_IND.",
            "3. On match, controller transmits CONNECT_IND (legacy) or AUX_CONNECT_REQ (extended) with WinSize / WinOffset / Interval / Latency / Timeout / ChM / Hop / SCA / CRCInit / Access Address.",
            "4. After Window Offset both Central and Peripheral move to Connection state.",
            "5. First connection event anchor occurs at 1.25 ms * WinOffset after CONNECT_IND end.",
            "6. Central transmits LL Data PDU (often empty) at anchor; Peripheral responds; alternate until MD=0 or CE Length reached.",
            "7. HCI_LE_Connection_Complete (legacy) or HCI_LE_Enhanced_Connection_Complete event delivered to both hosts.",
        ])
        d.setdefault("connection_event_sequence", [
            "1. Anchor point starts the event; Central transmits first.",
            "2. Each PDU may carry LL Data, LL Control, or empty (LLID=01, length=0).",
            "3. T_IFS = 150 µs between consecutive PDUs.",
            "4. Receiver toggles NESN on successful CRC; transmitter retransmits same SN on CRC failure.",
            "5. Either end with MD=0 + no queued data may end the event.",
            "6. Next event scheduled at anchor + Connection Interval (skipping up to Slave Latency events on the Peripheral side).",
        ])
        d.setdefault("ll_phy_update_sequence_BLE_5", [
            "1. Either Central or Peripheral sends LL_PHY_REQ with TX_PHYS / RX_PHYS bitmaps (LE 1M / 2M / Coded).",
            "2. Peer responds with LL_PHY_RSP indicating its preferences.",
            "3. Central computes the common PHY + sends LL_PHY_UPDATE_IND with TX_PHY + RX_PHY + Instant (16-bit connection event counter).",
            "4. Both ends switch PHY at the Instant connection event.",
        ])
        d.setdefault("encryption_setup_sequence", [
            "1. Central sends LL_ENC_REQ with Rand / EDIV (legacy) or zero (LE Secure Connections).",
            "2. Peripheral responds with LL_ENC_RSP carrying SKDs (Session Key Diversifier slave) + IVs.",
            "3. Both compute Long Term Key (LTK) via SMP previously, then derive Session Key (SK) = AES-128(LTK, SKD_combined).",
            "4. Peripheral sends LL_START_ENC_REQ encrypted with the new key.",
            "5. Central responds with LL_START_ENC_RSP — encryption now active.",
            "6. All subsequent PDUs encrypted with AES-CCM + per-direction 39-bit packet counter + 32-bit MIC.",
        ])
        d.setdefault("smp_pairing_sequence", [
            "1. Initiator sends Pairing_Request with IO Capabilities, OOB Flag, AuthReq, Max Encryption Key Size, Initiator/Responder Key Distribution.",
            "2. Responder sends Pairing_Response with its capabilities.",
            "3. Both derive Pairing Method per IO-Capability matrix (Just Works / Passkey Entry / Numeric Comparison / OOB).",
            "4. LE Legacy: STK derivation via TK + Random; LE Secure Connections: ECDH P-256 public key exchange + DHKey check.",
            "5. Confirm value exchange (Mc / Sc) + Random exchange (Mr / Sr).",
            "6. (Numeric Comparison) User confirms identical 6-digit value displayed on both devices.",
            "7. Long Term Key (LTK) derived; stored in Bonding Data slot if bonding requested.",
            "8. Higher-layer encryption (LL_ENC_REQ) follows.",
        ])
        d.setdefault("extended_advertising_sequence_BLE_5", [
            "1. Host issues HCI_LE_Set_Extended_Advertising_Parameters with Advertising_Handle / Primary_Adv_PHY / Secondary_Adv_PHY / Advertising_SID / etc.",
            "2. Host issues HCI_LE_Set_Extended_Advertising_Data + HCI_LE_Set_Extended_Scan_Response_Data with fragmented data.",
            "3. Host issues HCI_LE_Set_Extended_Advertising_Enable=1.",
            "4. Controller transmits ADV_EXT_IND on 37/38/39 (Primary_Adv_PHY); ADV_EXT_IND carries an AuxPtr to AUX_ADV_IND on a data channel.",
            "5. AUX_ADV_IND carries actual ext-advertising payload (or partial); may chain AUX_CHAIN_IND PDUs.",
            "6. Scanners follow AuxPtr to receive the full payload.",
        ])
        d.setdefault("periodic_advertising_sequence", [
            "1. Periodic-advertising-capable advertiser issues HCI_LE_Set_Periodic_Advertising_Parameters + Data + Enable.",
            "2. Controller transmits AUX_SYNC_IND on a deterministic schedule (periodic_adv_interval, 7.5 ms..81.91875 s).",
            "3. Receiver acquires sync via Periodic Advertising Sync Transfer (PAST) or by scanning AUX_ADV_IND and following the SyncInfo field.",
            "4. After sync, receiver delivers AUX_SYNC_IND payload via HCI_LE_Periodic_Advertising_Report.",
        ])
        d.setdefault("cis_setup_sequence_5_2", [
            "1. Central (CIG manager) issues HCI_LE_Set_CIG_Parameters with CIG_ID, SDU_Interval, Worst_Case_SCA, Packing, Framing, Max_Transport_Latency, list of CIS parameters.",
            "2. Central issues HCI_LE_Create_CIS with Connection_Handle list + CIS_Handle list.",
            "3. Central sends LL_CIS_REQ with CIS_ID / CIG_ID / PHY_M_to_S / PHY_S_to_M / Max_SDU + Subevent + Burst parameters.",
            "4. Peripheral responds LL_CIS_RSP (accept / reject).",
            "5. On accept, Central sends LL_CIS_IND with anchor info.",
            "6. CIS established; both ends exchange ISO data PDUs per CIS event schedule (SDU_Interval / BN / NSE / FT).",
            "7. HCI_LE_CIS_Established event delivered.",
        ])
        d.setdefault("le_power_control_sequence_5_2", [
            "1. Either peer sends LL_POWER_CONTROL_REQ specifying PHY + Delta + APR_Enable.",
            "2. Peer responds LL_POWER_CONTROL_RSP with achieved TX power delta + min/max bounds.",
            "3. Independently, a peer may send LL_POWER_CHANGE_IND when it spontaneously changes TX power.",
            "4. Path-loss zone change triggers HCI_LE_Path_Loss_Threshold event when zone HIGH / MIDDLE / LOW crossed.",
        ])
        d.setdefault("termination_sequence", [
            "1. Either end may send LL_TERMINATE_IND with an Error Code reason.",
            "2. Peer acknowledges by toggling NESN on the LL_TERMINATE_IND.",
            "3. Both ends drop to Standby; HCI_Disconnection_Complete delivered with the reason code.",
            "4. Supervision Timeout expiry implicitly does the same without LL_TERMINATE_IND.",
        ])
        _write(p, d)

    # L13 LAB_CALIBRATION
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "Bluetooth Core v5.2 is a wireless protocol spec; it does not "
            "define a calibration loop at the protocol layer. SoC-"
            "integrated BLE radios typically include vendor-specific "
            "factory-trim loops for crystal frequency (XO trim), PLL VCO "
            "gain, mixer LO leakage, TX power, RX gain, and antenna match. "
            "Volume 6 Part F (Direct Test Mode) provides the deterministic "
            "RF interface used at the production line for these trims "
            "(PRBS9 / PRBS15 / 11110000 / 10101010 / all-1 / all-0 packet "
            "patterns + per-channel transmitter + receiver tests at LE 1M / "
            "2M / Coded S=2 / Coded S=8). Bluetooth qualification by the "
            "Bluetooth SIG additionally requires RF compliance per Vol 6 "
            "Part A — frequency accuracy, modulation accuracy, in-band "
            "emission, out-of-band emission, blocking, intermodulation, "
            "image rejection.")
        _write(p, d)

    # L14 PROTOCOL_VERSIONING
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        # Force-overwrite — UART R59 wrote PC16550D / National Semi history.
        _force(f, "spec_version", "Bluetooth Core Specification v5.2 (December 31, 2019)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "1.0 (1999) — original Basic Rate (BR/EDR); no LE.",
                "1.1 (2002) — interoperability + errata to 1.0.",
                "1.2 (2003) — Adaptive Frequency Hopping (AFH), eSCO.",
                "2.0 + EDR (2004) — Enhanced Data Rate (π/4-DQPSK / 8-DPSK) up to 3 Mb/s.",
                "2.1 + EDR (2007) — Secure Simple Pairing (SSP), Low-Energy QoS.",
                "3.0 + HS (2009) — Alternate MAC/PHY (802.11 high-speed).",
                "4.0 (2010) — Bluetooth Low Energy (BLE) introduced — LE 1M PHY, AES-128 LL encryption, ATT / GATT / SMP / L2CAP LE.",
                "4.1 (2013) — dual-mode topology cleanups, LE link-layer improvements, IPv4/IPv6 support.",
                "4.2 (2014) — LE Secure Connections (ECDH P-256), LE Data Length Extension (up to 251-octet PDU), LE Privacy 1.2, IPv6-over-BLE (IPSP).",
                "5.0 (2016) — LE 2M PHY, LE Coded PHY (S=2 / S=8), Extended Advertising (up to 255-octet payload + chaining to 1650-octet ext-adv sets), Periodic Advertising, Channel Selection Algorithm #2, slot availability mask, mesh foundational.",
                "5.1 (2019) — Direction Finding (AoA + AoD via Constant Tone Extension), Periodic Advertising Sync Transfer (PAST), GATT Caching, Random Advertising Channel Indexing, Advertising Channel Index in PERIODIC_SYNC_IND, HCI support for Set Advertising Set Random Address.",
                "5.2 (December 2019) — LE Audio (Isochronous Channels CIS + BIS), Enhanced Attribute Protocol (EATT), LE Power Control + Path Loss Monitoring, Isochronous Adaptation Layer (ISOAL); foundational for LE Audio Hearing Access Profile + Broadcast Audio.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "4.0",  "summary": "Introduced BLE (Bluetooth Smart). LE 1M PHY; AES-128 LL encryption; ATT / GATT / SMP / L2CAP-LE; advertising on channels 37/38/39; connection state with Central + Peripheral roles."},
                {"version": "4.1",  "summary": "Dual-mode coexistence improvements; LE link-layer enhancements; LE topology multi-role; LE Ping LL_PING_REQ/RSP."},
                {"version": "4.2",  "summary": "LE Secure Connections (ECDH P-256); LE Data Length Extension (up to 251-octet PDU); LE Privacy 1.2 with Resolvable Private Address resolution at controller; IPSP (6LoWPAN-over-BLE)."},
                {"version": "5.0",  "summary": "LE 2M PHY (double symbol rate); LE Coded PHY (S=2 / S=8 long-range); Extended Advertising up to 1650-octet ext-adv sets; Periodic Advertising; Channel Selection Algorithm #2; new advertising PDU types ADV_EXT_IND / AUX_xxx."},
                {"version": "5.1",  "summary": "Direction Finding AoA + AoD via Constant Tone Extension (CTE) appended to PDUs; Periodic Advertising Sync Transfer (PAST); GATT Caching; randomized advertising channel indexing for collision avoidance."},
                {"version": "5.2",  "summary": "LE Audio: Isochronous Channels — Connected Isochronous Streams (CIS) + Broadcast Isochronous Streams (BIS) — for deterministic-latency multi-stream audio; Enhanced ATT (EATT) multi-bearer with per-bearer flow control; LE Power Control + Path Loss Monitoring; Isochronous Adaptation Layer (LL-ISOAL)."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "LE_2M_negotiation_required",
                 "BLE_4_x_device": "Only supports LE 1M PHY; receives LL_PHY_REQ with TX_PHYS=LE 2M and responds Reject with reason 0x1A (Unsupported LMP / LL Parameter Value).",
                 "BLE_5_x_device":  "Must include LE 1M in TX_PHYS / RX_PHYS for backward compatibility; falls back to 1M if peer rejects.",
                 "trap": "BLE 5 devices that only offer 2M / Coded without 1M cannot connect to legacy 4.x peers."},
                {"trap_name": "Extended_Advertising_not_visible_to_legacy_scanner",
                 "BLE_4_x_scanner": "Sees only legacy ADV_IND / ADV_DIRECT_IND / ADV_NONCONN_IND / ADV_SCAN_IND.",
                 "BLE_5_x_advertiser": "When using ADV_EXT_IND (extended), legacy scanners see only the primary header (no AdvData); they cannot follow the AuxPtr to AUX_ADV_IND.",
                 "trap": "Extended Advertising data is invisible to BLE 4.x scanners; use legacy advertising for broad compatibility."},
                {"trap_name": "Channel_Selection_Algorithm_2_must_be_enabled",
                 "BLE_4_x":   "Always uses Algorithm #1 (sequential ring).",
                 "BLE_5_x":   "Algorithm #2 only enabled if ChSel bit is set in CONNECT_IND header AND both ends support the feature.",
                 "trap": "If only one side supports Algorithm #2, connection falls back to Algorithm #1."},
                {"trap_name": "LE_Audio_CIS_BIS_BLE_5_2_only",
                 "BLE_5_0_5_1_device": "Does not implement CIG / CIS / BIG / BIS; HCI_LE_Set_CIG_Parameters returns Unknown Command.",
                 "BLE_5_2_device":      "Required to implement Isochronous Channels + ISOAL for LE Audio support.",
                 "trap": "LE Audio products require BLE 5.2 — older controllers cannot participate even if otherwise BLE 5.0+ capable."},
                {"trap_name": "EATT_multi_bearer_unsupported_on_pre_5_2",
                 "pre_5_2": "Single ATT bearer per connection.",
                 "5_2":      "Multiple concurrent ATT bearers, each its own L2CAP channel with per-bearer credits + MTU.",
                 "trap": "Apps that assume single-bearer behavior may receive out-of-order responses on EATT-enabled peers."},
                {"trap_name": "LE_Power_Control_unsupported_on_pre_5_2",
                 "pre_5_2": "TX power negotiated at HCI level once; no LL feedback loop.",
                 "5_2":      "LL_POWER_CONTROL_REQ/RSP/IND + Path-Loss thresholds; adapts TX power across the link in real time.",
                 "trap": "Mixed pre-5.2 / 5.2 links use static TX power on the pre-5.2 side."},
            ]
        _force(f, "version_naming_history_note",
            "The Bluetooth SIG maintains the Bluetooth Core Specification. The brand 'Bluetooth Smart' / 'Bluetooth Smart Ready' was used to differentiate BLE-only / dual-mode products during 4.0-4.2 era; since 5.0 the brand is unified as 'Bluetooth'. BLE Audio (5.2) is also marketed under the 'LE Audio' brand. Subsequent versions: 5.3 (July 2021) added Periodic Advertising with Responses, Channel Classification Enhancement, Encrypted Advertising Data, Subrating; 5.4 (February 2023) added Periodic Advertising with Responses (PAwR), Encrypted Advertising Data, LE GATT Security Levels.")
        d["fields"] = f
        _write(p, d)

    # L15 ENCODING_TABLES
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("advertising_pdu_type_encoding", {
            "header_columns": ["PDU Type", "PDU Type[3:0]", "Used On", "Description"],
            "rows": [
                {"name": "ADV_IND",          "pdu_type_3_0": "0000", "channels": "37/38/39", "description": "Connectable + scannable undirected advertising"},
                {"name": "ADV_DIRECT_IND",   "pdu_type_3_0": "0001", "channels": "37/38/39", "description": "Connectable directed advertising; only InitA target may respond"},
                {"name": "ADV_NONCONN_IND",  "pdu_type_3_0": "0010", "channels": "37/38/39", "description": "Non-connectable + non-scannable broadcast"},
                {"name": "SCAN_REQ",          "pdu_type_3_0": "0011", "channels": "37/38/39", "description": "Active-scan request (or AUX_SCAN_REQ on aux channel)"},
                {"name": "SCAN_RSP",          "pdu_type_3_0": "0100", "channels": "37/38/39", "description": "Response to SCAN_REQ carrying extra data"},
                {"name": "CONNECT_IND",       "pdu_type_3_0": "0101", "channels": "37/38/39", "description": "Connection request (legacy) or AUX_CONNECT_REQ on aux"},
                {"name": "ADV_SCAN_IND",      "pdu_type_3_0": "0110", "channels": "37/38/39", "description": "Scannable + non-connectable undirected advertising"},
                {"name": "ADV_EXT_IND / AUX_ADV_IND / AUX_SYNC_IND / AUX_CHAIN_IND", "pdu_type_3_0": "0111", "channels": "37/38/39 or data", "description": "Extended advertising primary or auxiliary (BLE 5)"},
                {"name": "AUX_CONNECT_RSP",   "pdu_type_3_0": "1000", "channels": "data",     "description": "Auxiliary connect response (BLE 5)"},
            ],
        })
        f.setdefault("ll_data_pdu_llid_encoding", {
            "header_columns": ["LLID[1:0]", "Meaning"],
            "rows": [
                ["00", "Reserved for future use (was used for Isochronous PDU unframed in BLE 5.2)"],
                ["01", "LL Data PDU — continuation fragment or empty PDU"],
                ["10", "LL Data PDU — start of an L2CAP message"],
                ["11", "LL Control PDU — Opcode + CtrlData"],
            ],
        })
        f.setdefault("ll_control_opcode_encoding", {
            "header_columns": ["Opcode (hex)", "Name", "Direction"],
            "rows": [
                ["0x00", "LL_CONNECTION_UPDATE_IND",  "M→S"],
                ["0x01", "LL_CHANNEL_MAP_IND",        "M→S"],
                ["0x02", "LL_TERMINATE_IND",          "M↔S"],
                ["0x03", "LL_ENC_REQ",                "M→S"],
                ["0x04", "LL_ENC_RSP",                "S→M"],
                ["0x05", "LL_START_ENC_REQ",          "S→M"],
                ["0x06", "LL_START_ENC_RSP",          "M→S then S→M"],
                ["0x07", "LL_UNKNOWN_RSP",             "M↔S"],
                ["0x08", "LL_FEATURE_REQ",            "M→S"],
                ["0x09", "LL_FEATURE_RSP",            "S→M"],
                ["0x0A", "LL_PAUSE_ENC_REQ",          "M→S"],
                ["0x0B", "LL_PAUSE_ENC_RSP",          "S→M"],
                ["0x0C", "LL_VERSION_IND",            "M↔S"],
                ["0x0D", "LL_REJECT_IND",             "M↔S"],
                ["0x0E", "LL_SLAVE_FEATURE_REQ",      "S→M"],
                ["0x0F", "LL_CONNECTION_PARAM_REQ",   "M↔S"],
                ["0x10", "LL_CONNECTION_PARAM_RSP",   "M↔S"],
                ["0x11", "LL_REJECT_EXT_IND",         "M↔S"],
                ["0x12", "LL_PING_REQ",               "M↔S"],
                ["0x13", "LL_PING_RSP",               "M↔S"],
                ["0x14", "LL_LENGTH_REQ",             "M↔S"],
                ["0x15", "LL_LENGTH_RSP",             "M↔S"],
                ["0x16", "LL_PHY_REQ",                "M↔S"],
                ["0x17", "LL_PHY_RSP",                "M↔S"],
                ["0x18", "LL_PHY_UPDATE_IND",         "M→S"],
                ["0x19", "LL_MIN_USED_CHANNELS_IND",  "S→M"],
                ["0x1A", "LL_CTE_REQ",                "M↔S"],
                ["0x1B", "LL_CTE_RSP",                "M↔S"],
                ["0x1C", "LL_PERIODIC_SYNC_IND",      "M↔S"],
                ["0x1D", "LL_CLOCK_ACCURACY_REQ",     "M↔S"],
                ["0x1E", "LL_CLOCK_ACCURACY_RSP",     "M↔S"],
                ["0x1F", "LL_CIS_REQ",                "M→S"],
                ["0x20", "LL_CIS_RSP",                "S→M"],
                ["0x21", "LL_CIS_IND",                "M→S"],
                ["0x22", "LL_CIS_TERMINATE_IND",      "M↔S"],
                ["0x23", "LL_POWER_CONTROL_REQ",      "M↔S"],
                ["0x24", "LL_POWER_CONTROL_RSP",      "M↔S"],
                ["0x25", "LL_POWER_CHANGE_IND",       "M↔S"],
            ],
            "note": "Direction labels: M = Master / Central; S = Slave / Peripheral. M↔S = either side may initiate; M→S = master to slave only.",
        })
        f.setdefault("att_opcode_encoding", {
            "header_columns": ["Opcode (hex)", "Name", "Method", "Authenticated", "Signed"],
            "rows": [
                ["0x01", "Error Response",                "Response",       "no",  "no"],
                ["0x02", "Exchange MTU Request",           "Request",        "no",  "no"],
                ["0x03", "Exchange MTU Response",           "Response",       "no",  "no"],
                ["0x04", "Find Information Request",        "Request",        "no",  "no"],
                ["0x05", "Find Information Response",       "Response",       "no",  "no"],
                ["0x06", "Find By Type Value Request",      "Request",        "no",  "no"],
                ["0x07", "Find By Type Value Response",     "Response",       "no",  "no"],
                ["0x08", "Read By Type Request",            "Request",        "no",  "no"],
                ["0x09", "Read By Type Response",           "Response",       "no",  "no"],
                ["0x0A", "Read Request",                    "Request",        "no",  "no"],
                ["0x0B", "Read Response",                   "Response",       "no",  "no"],
                ["0x0C", "Read Blob Request",               "Request",        "no",  "no"],
                ["0x0D", "Read Blob Response",              "Response",       "no",  "no"],
                ["0x0E", "Read Multiple Request",           "Request",        "no",  "no"],
                ["0x0F", "Read Multiple Response",          "Response",       "no",  "no"],
                ["0x10", "Read By Group Type Request",      "Request",        "no",  "no"],
                ["0x11", "Read By Group Type Response",     "Response",       "no",  "no"],
                ["0x12", "Write Request",                   "Request",        "no",  "no"],
                ["0x13", "Write Response",                  "Response",       "no",  "no"],
                ["0x16", "Prepare Write Request",           "Request",        "no",  "no"],
                ["0x17", "Prepare Write Response",          "Response",       "no",  "no"],
                ["0x18", "Execute Write Request",           "Request",        "no",  "no"],
                ["0x19", "Execute Write Response",          "Response",       "no",  "no"],
                ["0x1B", "Handle Value Notification",        "Notification",   "no",  "no"],
                ["0x1D", "Handle Value Indication",          "Indication",     "no",  "no"],
                ["0x1E", "Handle Value Confirmation",        "Confirmation",   "no",  "no"],
                ["0x20", "Read Multiple Variable Length Request",  "Request",  "no",  "no"],
                ["0x21", "Read Multiple Variable Length Response", "Response", "no",  "no"],
                ["0x23", "Multiple Handle Value Notification",     "Notification", "no", "no"],
                ["0x52", "Write Command",                   "Command",         "no",  "no"],
                ["0xD2", "Signed Write Command",            "Command",         "no",  "yes"],
            ],
        })
        f.setdefault("smp_pairing_method_matrix", {
            "header_columns": ["Initiator IO", "Responder DisplayOnly", "Responder DisplayYesNo", "Responder KeyboardOnly", "Responder NoInputNoOutput", "Responder KeyboardDisplay"],
            "rows": [
                {"init": "DisplayOnly",      "DisplayOnly": "Just Works",     "DisplayYesNo": "Just Works",         "KeyboardOnly": "Passkey Entry (R)", "NoInputNoOutput": "Just Works", "KeyboardDisplay": "Passkey Entry (R)"},
                {"init": "DisplayYesNo",     "DisplayOnly": "Just Works",     "DisplayYesNo": "Numeric Comparison", "KeyboardOnly": "Passkey Entry (R)", "NoInputNoOutput": "Just Works", "KeyboardDisplay": "Numeric Comparison"},
                {"init": "KeyboardOnly",     "DisplayOnly": "Passkey Entry (I)", "DisplayYesNo": "Passkey Entry (I)", "KeyboardOnly": "Passkey Entry",     "NoInputNoOutput": "Just Works", "KeyboardDisplay": "Passkey Entry (I)"},
                {"init": "NoInputNoOutput",  "DisplayOnly": "Just Works",     "DisplayYesNo": "Just Works",         "KeyboardOnly": "Just Works",        "NoInputNoOutput": "Just Works", "KeyboardDisplay": "Just Works"},
                {"init": "KeyboardDisplay",  "DisplayOnly": "Passkey Entry (I)", "DisplayYesNo": "Numeric Comparison", "KeyboardOnly": "Passkey Entry (R)", "NoInputNoOutput": "Just Works", "KeyboardDisplay": "Numeric Comparison"},
            ],
            "note": "(I) = Initiator displays passkey; (R) = Responder displays passkey. Numeric Comparison only available on LE Secure Connections.",
        })
        f.setdefault("phy_encoding", {
            "header_columns": ["PHY", "PHY bit (LE Set PHY HCI)", "Symbol Rate", "Effective Rate"],
            "rows": [
                ["LE 1M",       "0x01", "1 Msym/s", "1 Mb/s"],
                ["LE 2M",       "0x02", "2 Msym/s", "2 Mb/s"],
                ["LE Coded S=2", "0x04 (with S=2 sub-encoding)", "1 Msym/s", "~500 kb/s"],
                ["LE Coded S=8", "0x04 (with S=8 sub-encoding)", "1 Msym/s", "~125 kb/s"],
            ],
        })
        f.setdefault("advertising_data_AD_type_examples", {
            "header_columns": ["AD Type (hex)", "Name"],
            "rows": [
                ["0x01", "Flags"],
                ["0x02", "Incomplete List of 16-bit Service UUIDs"],
                ["0x03", "Complete List of 16-bit Service UUIDs"],
                ["0x04", "Incomplete List of 32-bit Service UUIDs"],
                ["0x05", "Complete List of 32-bit Service UUIDs"],
                ["0x06", "Incomplete List of 128-bit Service UUIDs"],
                ["0x07", "Complete List of 128-bit Service UUIDs"],
                ["0x08", "Shortened Local Name"],
                ["0x09", "Complete Local Name"],
                ["0x0A", "TX Power Level"],
                ["0x16", "Service Data — 16-bit UUID"],
                ["0x19", "Appearance"],
                ["0x1B", "LE Bluetooth Device Address"],
                ["0x1C", "LE Role"],
                ["0xFF", "Manufacturer Specific Data"],
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Table 2.1 PDU Type encoding (Vol 6 Part B Section 2.3)",
                "Table 2.3 LLID encoding (Vol 6 Part B Section 2.4)",
                "Table 2.6 LL Control PDU Opcodes (Vol 6 Part B Section 2.4.2)",
                "Table 3.3 IO Capabilities Mapping to Pairing Method (Vol 3 Part H Section 2.3.5.1)",
                "Section 3 RF Properties (Vol 6 Part A Section 3.1) — channel + modulation parameters",
                "Section 4 Direct Test Mode (Vol 6 Part F) — production test command set",
                "Core Specification Supplement (CSS) — assigned numbers for AD Types",
            ]
        d["fields"] = f
        _write(p, d)

    # L16 COMPLIANCE_PROPERTIES
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Radio operates in 2.4-2.4835 GHz ISM band on 40 channels each 2 MHz wide.",
            "Channels 37 / 38 / 39 fixed at 2402 / 2426 / 2480 MHz are the primary advertising channels.",
            "GFSK modulation with BT=0.5; modulation index 0.45..0.55 (Standard) or 0.495..0.505 (Stable Modulation Index).",
            "Symbol rate 1 Msym/s (LE 1M / LE Coded) or 2 Msym/s (LE 2M).",
            "CRC-24 with polynomial x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1 (0x100065B) on every PDU.",
            "Advertising Access Address = 0x8E89BED6.",
            "Advertising CRC Init = 0x555555.",
            "Whitening with x^7+x^4+1 LFSR seeded with channel index || 1.",
            "T_IFS = 150 ± 2 µs between consecutive PDUs.",
            "Connection Interval = 1.25 ms * N where N ∈ [6, 3200] (7.5 ms..4.0 s).",
            "Supervision Timeout = 10 ms * M where M ∈ [10, 3200] (100 ms..32 s) AND > (1 + Slave_Latency) * Connection_Interval * 2.",
            "Slave Latency in [0, 499] AND < (Supervision Timeout / Connection Interval) - 1.",
            "Connection events follow Channel Selection Algorithm #1 or #2; bad channels in the Channel Map are skipped.",
            "SN / NESN 1-bit tracking provides reliable in-order delivery of LL Data PDUs.",
            "Encryption uses AES-128 CCM with per-direction 39-bit packet counter + 4-octet MIC.",
            "LE Secure Connections uses ECDH P-256 for key exchange.",
            "Direct Test Mode (Vol 6 Part F) is mandatory for production-line RF compliance.",
            "If LE 2M PHY feature bit is set, controller must implement both LL_PHY_REQ/RSP/UPDATE_IND and the 2M PHY itself.",
            "If LE Coded PHY feature bit is set, controller must implement both S=2 and S=8 coding schemes.",
            "Extended Advertising primary PDU (ADV_EXT_IND) carries only metadata; AdvData lives in AUX_ADV_IND / AUX_CHAIN_IND.",
            "Periodic Advertising sender + receiver must implement Channel Selection Algorithm #2.",
            "BLE 5.2 LE Audio requires Isochronous Channels (CIS or BIS) + Isochronous Adaptation Layer (ISOAL).",
        ])
        f.setdefault("must_not_have_properties", [
            "Transmit on a channel not in the active Channel Map.",
            "Drive an Access Address with fewer than 2 transitions in the 6 most-significant bits (entropy requirement).",
            "Use the advertising Access Address 0x8E89BED6 for a data-channel connection.",
            "Use a Connection Interval below 7.5 ms or above 4.0 s.",
            "Continue transmitting after a successful LL_TERMINATE_IND exchange.",
            "Accept a CRC-failing PDU as a successful reception (must silently drop).",
            "Toggle NESN on a PDU with mismatched expected SN (must not consume).",
            "Use ChSel=1 on a CONNECT_IND when controller does not support Algorithm #2.",
            "Transmit a CTE on a PDU without the CP=1 bit + valid CTE Info.",
            "Exceed Max Transport Latency or Max SDU configured during CIG / BIG setup.",
            "Continue Periodic Advertising sync after Sync Timeout expiry without re-sync.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "CRC failure",                 "trigger": "CRC-24 mismatch on PDU — receiver silently drops; NESN not toggled."},
            {"mode": "Access Address mismatch",     "trigger": "Preamble correlated but Access Address differs — receiver silently drops."},
            {"mode": "Encryption MIC failure",       "trigger": "AES-CCM MIC verification fails — LL_TERMINATE_IND with reason 0x3D 'MIC Failure'."},
            {"mode": "Supervision Timeout",          "trigger": "No CRC-passing PDU within window — connection lost; HCI Disconnection Complete reason 0x08."},
            {"mode": "Connection Failed to Establish","trigger": "Initiator did not see Peripheral response within 6 connection events post-CONNECT_IND — HCI LE Connection Complete reason 0x3E."},
            {"mode": "Instant Passed",               "trigger": "Procedure Instant has already passed before peer can apply — LL_REJECT_IND reason 0x28 'Instant Passed'."},
            {"mode": "Pairing failure",              "trigger": "SMP Pairing Failed PDU with specific reason code (Passkey Entry Failed / OOB Not Available / etc.)."},
            {"mode": "PHY Update collision",          "trigger": "LL_PHY_UPDATE_IND with Instant in past — reset PHY Update procedure."},
        ])
        f.setdefault("spec_volume_layout", [
            "Volume 0 — Master Table of Contents + Compliance Requirements",
            "Volume 1 — Architecture + Terminology Overview",
            "Volume 2 — Core System Package [BR/EDR Controller]",
            "Volume 3 — Core System Package [Host]: L2CAP, GAP, GATT, ATT, SMP",
            "Volume 4 — Host Controller Interface (Vol 4 Part A UART / Part B USB / Part C SDIO / Part D 3-Wire UART / Part E HCI Functional)",
            "Volume 5 — Core System Package [AMP Controller]",
            "Volume 6 — Core System Package [Low Energy Controller]: PHY (Part A) / Link Layer (Part B) / Sample Data (Part C) / Direct Test Mode (Part F)",
            "Volume 7 — Wireless Coexistence",
        ])
        f.setdefault("regulatory_compliance_pointers", [
            "FCC Part 15 (US) — 2.4 GHz ISM band emissions",
            "ETSI EN 300 328 (EU) — 2400-2483.5 MHz wideband transmission",
            "ARIB STD-T66 (JP) — 2.4 GHz ISM device emissions",
            "RoHS / WEEE for product disposal",
            "Bluetooth Qualification Process (BQP) for SIG-recognized products",
        ])
        # Force-overwrite — UART R59 wrote MR-pulse / Table I narrative.
        _force(f, "reset_behavior_compliance",
            "On HCI Reset, controller returns to Standby state; all advertising / scanning / connections aborted; HCI buffers flushed; LL feature bitmap re-initialized.")
        d["fields"] = f
        _write(p, d)

    # L17 CHANNEL_SIGNAL_CATALOG
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {"name": "ANT",     "direction": "bidirectional RF", "purpose": "2.4 GHz antenna interface; single-ended or differential depending on radio architecture.", "active_levels": "50 Ω typical impedance; GFSK modulated 1 / 2 MHz wide channels."},
            {"name": "RF GND",  "direction": "RF return path",    "purpose": "Ground reference for RF signal."},
            {"name": "VDD",     "direction": "power supply",      "purpose": "Radio + baseband supply 1.8 / 3.0 / 3.3 V."},
            {"name": "VSS",     "direction": "ground",            "purpose": "Common ground."},
        ]
        f["logical_rf_channels"] = [
            {"name": "Primary Adv 37", "freq_MHz": 2402, "purpose": "Primary advertising channel (lowest frequency)"},
            {"name": "Primary Adv 38", "freq_MHz": 2426, "purpose": "Primary advertising channel (middle)"},
            {"name": "Primary Adv 39", "freq_MHz": 2480, "purpose": "Primary advertising channel (highest)"},
            {"name": "Data 0..36",     "freq_MHz_range": "2404..2478 (skipping 2426)", "purpose": "Data channels — used in connection events + Periodic Advertising + Isochronous Channels"},
        ]
        f["packet_types_summary"] = [
            {"class": "Legacy Advertising",          "members": ["ADV_IND", "ADV_DIRECT_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND"], "PDU_count": 4},
            {"class": "Scanning / Initiating",       "members": ["SCAN_REQ", "SCAN_RSP", "CONNECT_IND"],                              "PDU_count": 3},
            {"class": "Extended Advertising (BLE 5)", "members": ["ADV_EXT_IND", "AUX_ADV_IND", "AUX_SYNC_IND", "AUX_CHAIN_IND", "AUX_SCAN_REQ", "AUX_SCAN_RSP", "AUX_CONNECT_REQ", "AUX_CONNECT_RSP"], "PDU_count": 8},
            {"class": "LL Data PDU",                  "members": ["LLID=01 continuation / empty", "LLID=10 start-of-L2CAP", "LLID=11 LL Control"], "PDU_count": 3},
            {"class": "LL Control PDU",               "members": ["LL_CONNECTION_UPDATE_IND", "LL_CHANNEL_MAP_IND", "LL_TERMINATE_IND", "LL_ENC_REQ/RSP", "LL_START_ENC_REQ/RSP", "LL_FEATURE_REQ/RSP", "LL_VERSION_IND", "LL_PING_REQ/RSP", "LL_LENGTH_REQ/RSP", "LL_PHY_REQ/RSP/UPDATE_IND", "LL_CTE_REQ/RSP", "LL_CIS_REQ/RSP/IND/TERMINATE_IND", "LL_POWER_CONTROL_REQ/RSP", "LL_POWER_CHANGE_IND"], "opcode_count_5_2": 38},
            {"class": "Isochronous PDU (BLE 5.2)",    "members": ["CIS PDU unframed (LLID=00 reserved)", "CIS framed (LLID=10)", "BIS unframed", "BIS framed"], "PDU_count": 4},
        ]
        f["channel_counts"] = {
            "external_wire_count":          4,
            "rf_pin_count":                  1,
            "total_rf_channels":            40,
            "data_channels":                37,
            "primary_advertising_channels":  3,
            "channel_spacing_MHz":           2,
            "max_connections_per_central":  "implementation-defined (1..N)",
            "max_connections_per_peripheral": "implementation-defined (typically 1, multi-link optional)",
            "LL_control_opcode_count_5_2": 38,
            "advertising_PDU_count":        15,
            "ATT_opcode_count":             31,
            "SMP_opcode_count":             13,
        }
        f["global_signals"] = [
            {"name": "Active_Clock", "purpose": "Active clock for radio + baseband; tolerance ±50 ppm."},
            {"name": "Sleep_Clock",  "purpose": "Sleep clock for deep-sleep wake-up; 21..500 ppm SCA options."},
            {"name": "VDD",          "purpose": "Radio + baseband supply rail."},
            {"name": "VSS",          "purpose": "Common ground."},
        ]
        # Force-overwrite dependency_graph for BLE shape.
        f["dependency_graph"] = {
            "common_rule":     "Central initiates every connection event; Peripheral schedules its receiver around the anchor + window-widening based on its sleep-clock SCA.",
            "data_dependency": "Each LL Data PDU carries SN + NESN; receiver toggles NESN on successful CRC + matched expected SN. Empty PDU closes a connection event when both ends have MD=0.",
        }
        f["handshake_pairs"] = [
            {"name": "ADV_IND-CONNECT_IND",   "from": "advertiser", "to": "initiator",  "rule": "Advertiser broadcasts ADV_IND; initiator responds with CONNECT_IND to start a connection."},
            {"name": "ADV_IND-SCAN_REQ-SCAN_RSP", "from": "advertiser-scanner", "to": "advertiser", "rule": "Advertiser broadcasts ADV_IND; active scanner sends SCAN_REQ; advertiser responds with SCAN_RSP."},
            {"name": "LL_DATA-(SN/NESN)",     "from": "transmitter",  "to": "receiver",  "rule": "Receiver toggles NESN on success; transmitter retransmits same SN on CRC fail."},
            {"name": "LL_ENC_REQ-LL_ENC_RSP", "from": "Central",      "to": "Peripheral","rule": "Encryption setup; Peripheral provides SKDs + IVs."},
            {"name": "LL_START_ENC_REQ-LL_START_ENC_RSP", "from": "Peripheral", "to": "Central", "rule": "First encrypted PDU; both ends switch to AES-CCM."},
            {"name": "LL_PHY_REQ-LL_PHY_RSP-LL_PHY_UPDATE_IND", "from": "any", "to": "Central", "rule": "PHY Update negotiation; Central drives Instant + final TX/RX PHY."},
            {"name": "LL_CIS_REQ-LL_CIS_RSP-LL_CIS_IND", "from": "Central", "to": "Peripheral", "rule": "BLE 5.2 CIS setup handshake."},
            {"name": "LL_POWER_CONTROL_REQ-LL_POWER_CONTROL_RSP", "from": "any", "to": "peer", "rule": "BLE 5.2 LE Power Control."},
        ]
        # Merge BLE-canonical ordering rules — UART R59 wrote
        # byte_ordering/register_ordering for the UART register file already.
        ord_r = f.get("ordering_rules")
        if not isinstance(ord_r, dict):
            ord_r = {}
            f["ordering_rules"] = ord_r
        ord_r.setdefault("bit_order_within_byte",    "LSB-first on the wire after whitening.")
        ord_r.setdefault("byte_order_within_field",  "Little-endian for multi-byte fields (Access Address, Connection Interval, Timeout, ChM, etc.).")
        ord_r.setdefault("tx_rx_simultaneity",       "Half-duplex; T_IFS = 150 µs between TX and RX in connection events.")
        ord_r.setdefault("preamble_first_then_AA_then_PDU_then_CRC", "Always in this order; whitening starts at PDU header (Preamble + Access Address are not whitened).")
        d["fields"] = f
        _write(p, d)

    # L18 INTERCONNECT_TOPOLOGY
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Star (Central + N Peripherals) + Broadcaster-Observer "
            "(connectionless) + Connected Isochronous Group (BLE 5.2 LE "
            "Audio Unicast) + Broadcast Isochronous Group (BLE 5.2 LE "
            "Audio Broadcast); multi-role devices may simultaneously be "
            "Central in one piconet + Peripheral in another (scatternet).")
        f["supported_topologies"] = [
            {"name": "Star — Central + Peripherals",          "description": "One Central holds 1..N connections to Peripherals; each Peripheral typically holds 1 connection."},
            {"name": "Broadcaster + Observer (connectionless)", "description": "Broadcaster transmits ADV_NONCONN_IND on channels 37/38/39; Observer passively scans + reports."},
            {"name": "Multi-role (scatternet)",                 "description": "Same device acts as Central in one piconet + Peripheral in another simultaneously; supported since BLE 4.1."},
            {"name": "Periodic Advertising train",              "description": "Broadcaster sends AUX_SYNC_IND on deterministic schedule on data channels; receivers acquire sync (BLE 5)."},
            {"name": "Connected Isochronous Group (CIG)",       "description": "BLE 5.2 LE Audio Unicast — Central manages a CIG of CIS streams to one or more Peripherals."},
            {"name": "Broadcast Isochronous Group (BIG)",       "description": "BLE 5.2 LE Audio Broadcast — Broadcaster transmits BIS streams to unlimited Synchronized Receivers."},
            {"name": "Bluetooth Mesh (separate spec)",          "description": "Layered on BLE advertising bearer (ADV) + GATT bearer; supports many-to-many relay topology."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Central",                "description": "Connection master; initiates all connection events; assigns Access Address + CRCInit + ChM + Hop + Interval + Timeout; schedules data + control PDUs."},
            {"role": "Peripheral",             "description": "Connection slave; listens at scheduled anchors; responds to Central; may reject parameter updates with LL_REJECT_IND."},
            {"role": "Broadcaster",            "description": "Connectionless transmitter — advertises but does not accept SCAN_REQ or CONNECT_IND."},
            {"role": "Observer",               "description": "Connectionless receiver — passively scans for advertising packets."},
            {"role": "Scanner",                "description": "Transient role within Observer; passive or active (issues SCAN_REQ)."},
            {"role": "Initiator",              "description": "Transient role within Central; transmits CONNECT_IND on receipt of matching ADV_IND."},
            {"role": "Isochronous Broadcaster", "description": "BLE 5.2 LE Audio Broadcast source; transmits BIS PDUs on a BIG schedule."},
            {"role": "Synchronized Receiver",   "description": "BLE 5.2 LE Audio Broadcast sink; acquires BIG via BASE + decodes BIS PDUs."},
        ]
        f["interconnect_role"] = (
            "BLE link layer carries L2CAP traffic between Controller and "
            "Host. Above L2CAP: ATT / GATT for attribute access; SMP for "
            "pairing / bonding; GAP for role + discovery; LE Audio profiles "
            "(BAP / PACS / CSIP / VCP / MCP / TMAP) for unicast / broadcast "
            "audio.")
        f["ordering_guarantees"] = {
            "per_LL_connection_in_order":  "SN / NESN enforce in-order delivery of LL Data PDUs over a connection; CRC + Access Address + whitening enforce per-packet integrity.",
            "frame_boundary":              "All periodic events (Advertising, Connection, Periodic Advertising, Isochronous) follow deterministic interval schedules.",
            "host_scheduling":             "Above HCI, host stack schedules ATT requests + L2CAP fragments; EATT (BLE 5.2) adds per-bearer credits + flow control.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — BLE is wireless. Host-side stack lives on the host CPU; Controller is an embedded peripheral on the SoC. HCI bridges them.")
        # Merge BLE roles into existing device_classification — USB R65 wrote
        # function/hub/compound_device etc. for USB device classes already.
        dc = f.get("device_classification")
        if not isinstance(dc, dict):
            dc = {}
            f["device_classification"] = dc
        dc.setdefault("broadcaster",         "Connectionless transmitter — beacons, sensors, iBeacon, Eddystone.")
        dc.setdefault("observer",            "Connectionless receiver — beacon scanners, indoor positioning anchors.")
        dc.setdefault("peripheral",          "Connection slave — heart rate sensor, blood pressure monitor, keyboard, mouse.")
        dc.setdefault("central",             "Connection master — smartphone, gateway, smart-home hub.")
        dc.setdefault("multi_role",          "Both Central + Peripheral simultaneously — smartwatch, fitness band, audio dongle.")
        dc.setdefault("isochronous_broadcaster", "BLE 5.2 broadcast audio source — public-venue audio, TV with hearing-aid broadcast.")
        dc.setdefault("synchronized_receiver", "BLE 5.2 broadcast audio sink — LE Audio hearing aids, broadcast-audio earbuds.")
        f.setdefault("default_signal_values_evidence_tables", [
            "Section 1 of Vol 6 Part A — RF Channels + Frequency Plan",
            "Section 2 of Vol 6 Part B — Packet Format + Whitening + CRC",
            "Section 4.4.2 of Vol 6 Part B — Advertising state",
            "Section 4.5 of Vol 6 Part B — Connection state",
            "Section 4.6 of Vol 6 Part B — LL Feature Set bitmap",
            "Section 5 of Vol 6 Part B — LE Audio Isochronous Channels (BLE 5.2)",
            "Volume 3 Part C — GAP roles + procedures",
            "Volume 3 Part F — ATT",
            "Volume 3 Part G — GATT",
        ])
        d["fields"] = f
        _write(p, d)

    # L19 CONSTRAINTS_PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "Bluetooth Core v5.2 is a wireless protocol + host-controller-"
            "interface spec; it does not include PDK / SDC / floorplan "
            "constraints. Per-controller integration constraints (2.4 GHz "
            "front-end matching network, balun, BAW / SAW filter selection, "
            "PCB stack-up for 50 Ω antenna trace, ESD protection on RF "
            "pads, sleep clock 32.768 kHz crystal load capacitance, active "
            "clock 16-48 MHz crystal start-up time, decoupling for radio + "
            "baseband supplies) live in the SoC integration spec and per-"
            "device datasheets — not in the Bluetooth Core Spec itself. "
            "Volume 6 Part A (PHY) gives the RF compliance envelope "
            "(frequency accuracy ±50 ppm, modulation-index 0.45..0.55, TX "
            "power +20 dBm max, RX sensitivity targets), Volume 6 Part F "
            "(Direct Test Mode) gives the deterministic interface for "
            "verifying these at the production line.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT_SCAN_TOPOLOGY
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = "partial"
        f.setdefault("internal_diagnostics", [
            "Direct Test Mode (Vol 6 Part F) — LE_TRANSMITTER_TEST / LE_RECEIVER_TEST / LE_TEST_END exposed via HCI or 2-wire UART for production-line RF characterization. PRBS9 / PRBS15 / 11110000 / 10101010 / all-1 / all-0 test patterns at LE 1M / 2M / Coded S=2 / Coded S=8 on all 40 channels.",
            "Enhanced DTM (BLE 5) — LE_ENHANCED_TRANSMITTER_TEST + LE_ENHANCED_RECEIVER_TEST accept PHY + Modulation_Index parameters explicitly.",
            "Direction Finding DTM (BLE 5.1) — LE_TRANSMITTER_TEST_v3 + LE_RECEIVER_TEST_v3 with CTE antenna-switching pattern.",
            "HCI Read RSSI, HCI LE Read Channel Map, HCI LE Read Remote Features, HCI Read Local Supported Features — runtime diagnostic visibility.",
            "HCI LE Enhanced Read Transmit Power Level (BLE 5.2), HCI LE Read Remote Transmit Power Level, HCI LE Path Loss Threshold Event, HCI LE Transmit Power Reporting Event — power-control observability.",
            "LL_PING_REQ / LL_PING_RSP — authenticated link health check; can be used as a live-link diagnostic.",
            "Sleep clock accuracy reported per device via LL_CLOCK_ACCURACY_REQ / LL_CLOCK_ACCURACY_RSP (BLE 5).",
        ])
        f["notes"] = (
            "Bluetooth Core v5.2 mandates Direct Test Mode for production-"
            "line RF compliance + HCI commands for runtime observability. "
            "Scan / JTAG / BIST at the chip level are left to the SoC "
            "integrator. Bluetooth qualification (Profile Tuning Suite, "
            "PTS) maintained by the Bluetooth SIG is the canonical "
            "conformance suite, but it consumes DTM + HCI rather than "
            "mandating new test hooks.")
        d["fields"] = f
        _write(p, d)

    # L21 POWER_INTENT
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["power_intent_present"] = True
        f["low_power_modes_summary"] = {
            "radio_off":                     "Radio fully powered down; controller wakes via host or scheduler.",
            "advertising_idle":              "Between advertising events; entire RF chain off; ~µA-class current with sleep clock running.",
            "scanning_idle":                  "Receiver off during scan-interval-minus-scan-window gap.",
            "connection_slave_latency":      "Peripheral skips up to Slave_Latency connection events without responding; allows long deep-sleep between anchors.",
            "periodic_advertising_idle":     "Receiver wakes only at the periodic-adv anchor.",
            "deep_sleep_with_sleep_clock":   "Active RF off; 32.768 kHz sleep clock counts down; SCA 21..500 ppm options trade accuracy vs current.",
            "isochronous_event_idle_5_2":     "Between CIS / BIS events the radio is off; events are anchored to ISO_Interval (1.25 ms steps).",
        }
        f.setdefault("tx_power_control_5_2", {
            "LL_POWER_CONTROL_REQ":     "Either peer requests a TX power delta on a specific PHY.",
            "LL_POWER_CONTROL_RSP":     "Peer reports actual achieved TX power + min/max bounds.",
            "LL_POWER_CHANGE_IND":      "Spontaneous TX power change notification.",
            "Path_Loss_Threshold":      "Receiver-side path-loss zone tracking (HIGH / MIDDLE / LOW); zone change triggers HCI LE Path Loss Threshold Event.",
        })
        f.setdefault("tx_power_class_summary", [
            {"class": "Class 1",   "max_dBm":  20, "min_dBm": -20, "notes": "Long-range; +20 dBm only via LE Coded with regulatory compliance."},
            {"class": "Class 1.5", "max_dBm":  10, "min_dBm": -20, "notes": "Mid-power BLE 5 use case."},
            {"class": "Class 2",   "max_dBm":   4, "min_dBm": -20, "notes": "Smartphone / consumer."},
            {"class": "Class 3",   "max_dBm":   0, "min_dBm": -20, "notes": "Coin-cell low-power Peripheral."},
        ])
        f.setdefault("sleep_clock_accuracy_options_ppm", [251, 151, 101, 76, 51, 31, 21, "≤ 20 (best)"])
        f.setdefault("active_clock_accuracy_options_ppm", [500, 250, 150, 100, 75, 50, 30, 20])
        f.setdefault("VDD_specification_typical", {
            "radio_supply_V_options": [1.8, 3.0, 3.3],
            "core_supply_V_typical":     0.9,
            "io_supply_V_typical":      1.8,
            "battery_chemistry_examples": ["CR2032 (3.0 V coin cell)", "Li-Ion (3.7 V nominal)", "Energy-harvesting (NFC / piezo / solar) for LE 5.2 Hearing Access"],
        })
        f["notes"] = (
            "Bluetooth Core v5.2 explicitly specifies a power-control "
            "feedback loop (LL_POWER_CONTROL_REQ/RSP/IND + Path-Loss "
            "thresholds) and a Sleep-Clock-Accuracy framework (8 "
            "quantized levels 21..500 ppm). This is part of the protocol "
            "— the LL state machine relies on it to schedule connection "
            "events without misalignment. Per-controller integration of "
            "LDOs / DC-DC / power gating is vendor-specific.")
        d["fields"] = f
        _write(p, d)

    # L22 VERIFICATION_PLAN — only `notes` overlay; force-overwrite because
    # RS-485 R137 / UART R59 pre-seeded their own protocol's notes.
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        _force(f, "notes",
            "Bluetooth Core v5.2 does not include a formal verification plan inside the document — formal qualification is delegated to the Bluetooth SIG Profile Tuning Suite (PTS) for protocol conformance + interoperability and to Direct Test Mode (DTM, Vol 6 Part F) for production-line RF tests. Per-controller SoC verification (RTL coverage, gate-level sim, FPGA emulation, BFM) is vendor-specific. Compliance is closed by a combination of PTS test campaigns at the SIG-recognized BQT lab and RF compliance testing (TX power mask, frequency tolerance, sensitivity, blocking, intermodulation) per Vol 6 Part A.")
        d["fields"] = f
        _write(p, d)

    # L23 SECURITY_REQUIREMENTS
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["security_requirements_present"] = True
        f.setdefault("ll_encryption_summary", {
            "algorithm":          "AES-128 in CCM (Counter with CBC-MAC) mode",
            "key_size_bits":      128,
            "MIC_size_bits":      32,
            "packet_counter_width_bits": 39,
            "per_direction_counter": True,
            "encryption_setup_PDUs": ["LL_ENC_REQ", "LL_ENC_RSP", "LL_START_ENC_REQ", "LL_START_ENC_RSP", "LL_PAUSE_ENC_REQ", "LL_PAUSE_ENC_RSP"],
            "key_derivation": "Session Key = AES-128(LTK, SKD_combined) where SKD = SKDm || SKDs.",
        })
        f.setdefault("smp_pairing_methods", [
            {"method": "Just Works",            "key_strength": "no MITM protection; passive eavesdropper can derive STK in legacy pairing"},
            {"method": "Passkey Entry",         "key_strength": "20-bit entropy; LE Secure Connections version raises this via passkey-bit-by-bit confirmation"},
            {"method": "Numeric Comparison",    "key_strength": "user verifies identical 6-digit number on both devices; LE Secure Connections only"},
            {"method": "Out-of-Band (OOB)",     "key_strength": "OOB channel security; LE Secure Connections OOB exchanges r + ECDH PK over the OOB channel"},
        ])
        f.setdefault("le_secure_connections_summary", {
            "introduced_in":     "Bluetooth 4.2",
            "key_exchange":      "ECDH on NIST P-256 curve",
            "DHKey_size_bytes":  32,
            "confirmation_method": "f4 / f5 / f6 / g2 functions per spec",
            "advantages_over_legacy": "Passive-eavesdropper resistance; FIPS-compliant cryptographic strength.",
        })
        f.setdefault("privacy_features", [
            "LE Privacy 1.0 (BLE 4.0)   — host-resolved Random Private Address (RPA).",
            "LE Privacy 1.1 (BLE 4.1)    — controller-assisted RPA resolution.",
            "LE Privacy 1.2 (BLE 4.2)    — full controller-resolved RPA + Resolving List in Controller for filtered scan/advertise.",
            "Network Privacy (BLE 5.0)   — additional privacy controls in Extended Advertising.",
            "Random Private Addresses rotated at configurable interval (default 15 minutes).",
        ])
        f.setdefault("must_have_security_properties", [
            "AES-128 CCM encryption on every Link Layer PDU once encryption is established.",
            "39-bit per-direction packet counter prevents replay.",
            "32-bit MIC appended to every encrypted PDU; failure terminates the connection with reason 0x3D 'MIC Failure'.",
            "LE Secure Connections uses NIST P-256 ECDH for key exchange.",
            "Just Works pairing must be explicitly accepted by both ends.",
            "Privacy: Resolvable Private Address rotation prevents long-term tracking.",
            "LL_PING_REQ / LL_PING_RSP provide an authenticated payload to detect MITM injection.",
        ])
        f.setdefault("must_not_have_security_properties", [
            "Transmit unencrypted PDUs after a successful LL_START_ENC_RSP (encryption must remain active).",
            "Reuse a packet counter (would break CCM nonce uniqueness).",
            "Accept a Public Address from a peer claiming privacy via RPA.",
            "Persist LTK across sessions if Bonding was not requested.",
        ])
        f["notes"] = (
            "Bluetooth Core v5.2 specifies an end-to-end Link Layer "
            "security model: pairing (SMP) → LTK → AES-CCM encryption → "
            "MIC verification + privacy (RPA). Above the LL, GATT supports "
            "authenticated + encrypted attribute access. Higher-layer "
            "profiles (LE Audio in 5.2) may layer additional content "
            "protection (e.g., LC3 frame encryption for broadcast audio). "
            "Bluetooth qualification requires FIPS-compliant LE Secure "
            "Connections for sensitive applications (medical, automotive).")
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
def is_ble(blob: str) -> bool:
    """Content-only `ble` detector with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The original structural
    BLE signature (Bluetooth Low Energy + advertising + connection, OR
    BLE + GAP + GATT, OR Bluetooth + LE + 2.4 GHz + 40 channels) is
    necessary but NOT sufficient: a LoRa / LoRaWAN spec routinely cites
    BLE / GAP / GATT / Bluetooth Low Energy as a coexistence / comparison
    PAN technology, so all three loose branches below trip on a LoRa doc
    and the generic BLE synth would inject Bluetooth Core content into a
    LoRaWAN spec's L-docs.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, no chip/SKU/benchmark-name literal as detection logic):
    if the blob's DOMINANT subject is LoRa / LoRaWAN, defer (False). LoRa's
    distinctive PHY+MAC structural signature is Chirp Spread Spectrum (CSS)
    + Spreading Factor SF7-SF12, plus the LoRaWAN MAC framework (dense
    "lorawan", Class A/B/C device classes, OTAA/ABP activation). None of
    these tokens appear in a real Bluetooth Core / BLE spec, so deferring
    on them suppresses LoRa without touching own-fire. See
    test_protocol_detector_no_misfire.py.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT BLE). ---
    # LoRa-primary: the Semtech LoRa PHY (Chirp Spread Spectrum + Spreading
    # Factor) and/or the LoRaWAN MAC framework. A real BLE spec carries
    # zero of these; a LoRa spec carries them densely (CSS + SF, lorawan
    # mentions, the Class A/B/C device classes, OTAA/ABP activation).
    _lora_css = ("chirp spread spectrum" in low
                 or ("chirp" in low and "spread spectrum" in low))
    _lora_sf = ("spreading factor" in low
                or any(("sf" + str(n)) in low for n in range(7, 13)))
    _lora_phy = _lora_css and _lora_sf
    _lorawan_mac = (
        low.count("lorawan") >= 5
        or (("class a" in low and "class c" in low)
            and ("otaa" in low or "abp" in low
                 or "over-the-air activation" in low
                 or "activation by personalization" in low)))
    lora_primary = _lora_phy or _lorawan_mac
    if lora_primary:
        return False

    # --- STRUCTURAL BLE signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("Bluetooth Low Energy" in blob
         and "advertising" in blob.lower()
         and "connection" in blob.lower())
        or ("BLE" in blob and "GAP" in blob
            and "GATT" in blob)
        or ("Bluetooth" in blob and "LE" in blob
            and "2.4 GHz" in blob and "40 channels" in blob))
