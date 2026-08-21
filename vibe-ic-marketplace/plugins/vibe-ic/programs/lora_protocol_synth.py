"""LoRa / LoRaWAN protocol synth helper (low-power wide-area network, LPWAN).

ic_class-gated overlay for the LoRa/LoRaWAN structural signature: a two-layer
low-power wide-area network built from the Semtech LoRa physical layer — a
Chirp Spread Spectrum (CSS) modulation with a Spreading Factor SF7-SF12, a
channel bandwidth of 125 / 250 / 500 kHz, a coding-rate (4/5..4/8) forward
error correction, a preamble + sync-word + header + payload + CRC frame, and
a high link budget for long sub-GHz (EU868 / US915) range — together with the
LoRa Alliance LoRaWAN MAC: device Classes A / B / C, the end-device / gateway /
network-server / join-server / application-server star-of-stars architecture,
OTAA (DevEUI + JoinEUI/AppEUI + AppKey -> DevAddr + NwkSKey + AppSKey) or ABP
activation, Adaptive Data Rate (ADR), duty-cycle channel access, receive
windows RX1 / RX2, MAC commands, a frame counter (FCnt), and a 4-byte MIC
(AES-128-CMAC) with AES-128 payload encryption. Applies the Semtech LoRa PHY +
LoRa Alliance LoRaWAN L2 spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(CSS + Spreading Factor + SF7-SF12 + bandwidth + LoRaWAN Class A/B/C +
OTAA/ABP + gateway/network-server + ADR + DevEUI/AppKey + MIC/FCnt) read from
the L-doc / input_doc CONTENT blob only. It NEVER reads the input-document
filename or the benchmark folder name, and it does NOT fire on the bare token
"lora" alone — a STRUCTURAL co-occurrence is required.

Sibling disambiguation — LoRa vs BLE, NFC, and Zigbee (the short-range
wireless family). All four are wireless, but only LoRa has CSS chirp-spread-
spectrum modulation, a Spreading Factor SF7-SF12, a 125/250/500 kHz bandwidth,
the LoRaWAN Class A/B/C device classes, OTAA/ABP activation, a gateway +
network-server star-of-stars, and DevEUI/AppKey/NwkSKey/AppSKey. BLE has
GAP/GATT, advertising/connection events, and 2.4 GHz / 40 channels; NFC has
inductive coupling at 13.56 MHz with ISO 14443 / NDEF; Zigbee has DSSS / O-QPSK
modulation, an IEEE 802.15.4 PHY, a PAN-ID / coordinator-router-end-device mesh,
and the ZCL/ZDO application framework. The detector REQUIRES the LoRa-only
structural vocabulary and DEFERS when the doc is BLE-primary (GAP/GATT +
advertising, no CSS / spreading factor / LoRaWAN), NFC-primary (13.56 MHz +
ISO 14443 / NDEF, no CSS / LoRaWAN), or Zigbee-primary (DSSS / O-QPSK +
802.15.4 + PAN-ID + ZCL, no CSS / spreading factor / LoRaWAN), so it cannot
false-fire on a BLE / NFC / Zigbee spec.

Public entry: ``apply_lora_synth(generated_docs_dir, is_lora, lora_ic_name)``.
Module-level ``is_lora(blob)`` is the content-only detector.
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

# Canonical LoRa PHY + LoRaWAN MAC facts (Semtech CSS + LoRa Alliance L2 1.0.4).
_SPREADING_FACTORS = [7, 8, 9, 10, 11, 12]
_BANDWIDTHS_KHZ = [125, 250, 500]
_CODING_RATES = ["4/5", "4/6", "4/7", "4/8"]
_DEVICE_CLASSES = ["A", "B", "C"]
_PREAMBLE_DEFAULT_SYMBOLS = 8
_SYNC_WORD_PUBLIC = "0x34"
_SYNC_WORD_PRIVATE = "0x12"
_MIC_BYTES = 4
_AES_KEY_BITS = 128


# ----------------------------------------------------------------------
# Module-level content-only detector with a BLE / NFC / Zigbee MUTEX.
# ----------------------------------------------------------------------
def _wb(token: str, low: str) -> bool:
    """Word-boundary token test on lower-cased text."""
    return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
                     low) is not None


def is_lora(blob: str) -> bool:
    """Content-only LoRa/LoRaWAN detector with BLE/NFC/Zigbee sibling MUTEX.

    Fire on the LoRa structural signature: Chirp Spread Spectrum (CSS) +
    Spreading Factor SF7-SF12 + a 125/250/500 kHz bandwidth + a coding rate +
    the LoRaWAN Class A/B/C device classes + OTAA/ABP activation +
    gateway/network-server + ADR + DevEUI/AppKey + MIC/FCnt. Defer if the doc
    is BLE-primary (GAP/GATT/advertising, no CSS/SF/LoRaWAN), NFC-primary
    (13.56 MHz + ISO 14443/NDEF, no CSS/LoRaWAN), or Zigbee-primary
    (DSSS/O-QPSK + 802.15.4 + PAN-ID + ZCL, no CSS/SF/LoRaWAN). Reads ONLY the
    spec text `blob` — never a filename or benchmark name. Does NOT fire on the
    bare word "lora" alone; a structural co-occurrence is always required.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- LoRa PHY (CSS) structural tokens. ---
    css = ("chirp spread spectrum" in low
           or _wb("css", low)
           or ("chirp" in low and "spread spectrum" in low))
    # Spreading factor SF7..SF12 (any of the named SF tokens or the phrase).
    sf_named = any(_wb("sf" + str(n), low) for n in _SPREADING_FACTORS)
    spreading_factor = ("spreading factor" in low) or sf_named
    bandwidth = (("125 khz" in low) or ("250 khz" in low)
                 or ("500 khz" in low))
    coding_rate = ("coding rate" in low
                   or any(cr in blob for cr in _CODING_RATES))
    preamble_sync = ("preamble" in low and "sync word" in low)
    link_budget = ("link budget" in low or "lpwan" in low
                   or "low-power wide-area" in low
                   or "low power wide area" in low)

    lora_phy = (
        css
        and spreading_factor
        and (bandwidth or coding_rate or preamble_sync or link_budget)
    )

    # --- LoRaWAN MAC structural tokens. ---
    lorawan_name = "lorawan" in low
    device_classes = (
        ("class a" in low and "class c" in low)
        or ("class a" in low and "class b" in low and "class c" in low))
    activation = (
        ("otaa" in low or "over-the-air activation" in low
         or "over the air activation" in low)
        or ("abp" in low or "activation by personalization" in low))
    join_keys = (
        ("deveui" in low or "dev eui" in low)
        and ("appkey" in low or "app key" in low
             or "nwkskey" in low or "appskey" in low
             or "joineui" in low or "appeui" in low))
    server_roles = (
        ("network server" in low)
        and ("gateway" in low)
        and ("end-device" in low or "end device" in low))
    adr = ("adaptive data rate" in low or _wb("adr", low))
    rx_windows = (("rx1" in low and "rx2" in low)
                  or "receive window" in low)
    mic_fcnt = (
        ("mic" in low and ("aes-128" in low or "aes 128" in low
                           or "cmac" in low))
        or ("fcnt" in low or "frame counter" in low))

    lorawan_mac = (
        (lorawan_name or device_classes)
        and (activation or join_keys or server_roles)
        and (adr or rx_windows or mic_fcnt or device_classes)
    )

    # ------------------------------------------------------------------
    # Sibling MUTEX — defer if the doc is anchored by a sibling wireless
    # protocol AND the LoRa-only structure (CSS + spreading factor +
    # LoRaWAN) is absent.
    # ------------------------------------------------------------------
    lora_anchor = (css and spreading_factor) or lorawan_name

    # BLE-primary: GAP/GATT + advertising/connection at 2.4 GHz, no CSS/SF.
    ble_primary = (
        (("gap" in low and "gatt" in low)
         or ("bluetooth low energy" in low and "advertising" in low))
        and not lora_anchor)
    if ble_primary:
        return False

    # NFC-primary: 13.56 MHz inductive coupling + ISO 14443 / NDEF, no CSS.
    nfc_primary = (
        ("13.56 mhz" in low
         or "iso 14443" in low or "iso/iec 14443" in low
         or "ndef" in low
         or ("inductive coupling" in low and "near field" in low))
        and not lora_anchor)
    if nfc_primary:
        return False

    # Zigbee-primary: DSSS/O-QPSK + 802.15.4 + PAN-ID + ZCL/ZDO, no CSS/SF.
    zigbee_primary = (
        (("o-qpsk" in low or "oqpsk" in low or "dsss" in low
          or "802.15.4" in low)
         and ("pan-id" in low or "pan id" in low or "zcl" in low
              or "zdo" in low or "zigbee" in low))
        and not lora_anchor)
    if zigbee_primary:
        return False

    return bool(lora_phy or lorawan_mac or (lora_phy and lorawan_mac))


def apply_lora_synth(generated_docs_dir: Path, is_lora_flag: bool,
                     lora_ic_name: Optional[str]) -> None:
    """Apply Semtech LoRa PHY + LoRa Alliance LoRaWAN synth when matched."""
    if not is_lora_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if lora_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = lora_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = lora_ic_name
                d["ic_name"] = lora_ic_name  # belt-and-braces top-level
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
# L1 — LoRa/LoRaWAN datasheet header + CSS PHY + LPWAN facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "LoRa Physical Layer and LoRaWAN Specification (LPWAN)")
    d["version"] = "LoRaWAN L2 1.0.4"
    d["revised_date"] = "2020"
    d["manufacturer"] = "Semtech (LoRa PHY) / LoRa Alliance (LoRaWAN MAC)"
    d["copyright"] = "© LoRa Alliance"
    d["abstract"] = (
        "LoRa/LoRaWAN is a low-power wide-area network (LPWAN) built from two "
        "layers: the Semtech LoRa physical layer — a Chirp Spread Spectrum "
        "(CSS) modulation with a Spreading Factor (SF7-SF12), a channel "
        "bandwidth of 125/250/500 kHz, a 4/5..4/8 coding-rate FEC, and a "
        "preamble + sync-word + header + payload + CRC frame, giving a very "
        "high link budget (~154 dB) and long sub-GHz (EU868/US915) range — "
        "and the LoRa Alliance LoRaWAN MAC, a star-of-stars of end-devices, "
        "gateways, and a network server, with device Classes A/B/C, OTAA/ABP "
        "activation, Adaptive Data Rate (ADR), duty-cycle channel access, "
        "receive windows RX1/RX2, MAC commands, a frame counter (FCnt), and a "
        "4-byte MIC (AES-128-CMAC) with AES-128 payload encryption.")
    d["keywords"] = [
        "LoRa", "LoRaWAN", "Chirp Spread Spectrum", "CSS", "Spreading Factor",
        "SF7", "SF12", "bandwidth", "125 kHz", "coding rate", "preamble",
        "sync word", "link budget", "LPWAN", "sub-GHz", "EU868", "US915",
        "end-device", "gateway", "network server", "join server",
        "application server", "Class A", "Class B", "Class C", "OTAA", "ABP",
        "DevEUI", "JoinEUI", "AppKey", "DevAddr", "NwkSKey", "AppSKey",
        "adaptive data rate", "ADR", "duty cycle", "RX1", "RX2", "MAC command",
        "FCnt", "MIC", "AES-128",
    ]
    d["external_pins"] = [
        "RF antenna port (sub-GHz; EU868 863-870 MHz / US915 902-928 MHz) — "
        "CSS modulated LoRa signal",
        "Transceiver SPI register interface (SCK/MOSI/MISO/NSS) to an "
        "SX127x/SX126x-class LoRa modem",
        "DIO interrupt lines (TxDone / RxDone / RxTimeout / CAD) from the "
        "modem",
        "RESET (modem reset)",
        "VDD / GND (low-power supply rails)",
    ]
    d["spreading_factors"] = list(_SPREADING_FACTORS)
    d["bandwidths_khz"] = list(_BANDWIDTHS_KHZ)
    d["coding_rates"] = list(_CODING_RATES)
    d["device_classes"] = list(_DEVICE_CLASSES)
    d["modes_of_operation"] = [
        {"name": "Class A (mandatory)",
         "description": "Each uplink is followed by exactly two short downlink "
         "receive windows (RX1, RX2); lowest power; end-device-initiated.",
         "power": "lowest"},
        {"name": "Class B (beacon)",
         "description": "Adds scheduled ping-slot receive windows synchronized "
         "to a periodic gateway beacon for bounded-latency downlinks.",
         "power": "medium"},
        {"name": "Class C (continuous)",
         "description": "Receiver open continuously except while transmitting; "
         "lowest downlink latency, highest power (mains-powered).",
         "power": "highest"},
    ]
    d["key_features"] = [
        "LoRa PHY = Chirp Spread Spectrum (CSS): each symbol is a linear "
        "frequency chirp carrying SF bits (2^SF chips/symbol).",
        "Spreading Factor SF7-SF12 trades data rate for processing gain, "
        "sensitivity, and range; Tsym = 2^SF / BW.",
        "Channel bandwidth 125 / 250 / 500 kHz; symbol rate = BW / 2^SF.",
        "Forward-error-correction coding rate 4/5, 4/6, 4/7, or 4/8.",
        "Frame = preamble (default 8 up-chirps) + sync word (0x34 public / "
        "0x12 private) + optional explicit header + payload + 16-bit CRC.",
        "Sub-GHz ISM operation (EU868, US915, AS923, AU915, ...); link budget "
        "~154 dB, sensitivity ~-148 dBm at SF12/125 kHz; range up to >15 km.",
        "LoRaWAN star-of-stars: end-devices <-RF-> gateways <-IP-> network "
        "server; join server + application server.",
        "Device Classes A (mandatory), B (beacon ping slots), C (continuous "
        "receive).",
        "Activation OTAA (DevEUI + JoinEUI/AppEUI + AppKey -> DevAddr + "
        "NwkSKey + AppSKey) or ABP (pre-provisioned DevAddr/NwkSKey/AppSKey).",
        "Adaptive Data Rate (ADR) lets the network tune SF and TX power for "
        "battery life and capacity.",
        "Unslotted ALOHA channel access with regional duty-cycle limits "
        "(e.g. 1% in EU868).",
        "Receive windows RX1 (RECEIVE_DELAY1, default 1 s) and RX2 "
        "(RECEIVE_DELAY2, default 2 s, fixed freq/DR).",
        "Per-frame 4-byte MIC (AES-128-CMAC, NwkSKey) integrity + AES-128-CTR "
        "payload encryption (AppSKey); frame counter (FCnt) replay "
        "protection.",
    ]
    d["topology_summary"] = (
        "Star-of-stars: each end-device uplink is heard by every gateway in "
        "range and forwarded to a central network server, which deduplicates, "
        "checks the MIC and frame counter, runs ADR, and picks one gateway for "
        "any downlink. End-devices are not bound to a single gateway.")
    d["use_cases"] = [
        "Battery-powered IoT sensors (utility metering, agriculture, "
        "environmental monitoring)",
        "Asset tracking and logistics over long range at low power",
        "Smart-city infrastructure (street lighting, parking, waste)",
        "Industrial telemetry where cellular power/cost is prohibitive",
    ]
    d["revision_history"] = [
        {"version": "1.0", "date": "2015",
         "description": "Initial LoRaWAN MAC (OTAA/ABP, Classes A/B/C, ADR, "
                        "AES-128 security) over the Semtech LoRa CSS PHY."},
        {"version": "1.0.2", "date": "2016",
         "description": "Regional Parameters split out; clarifications."},
        {"version": "1.0.4", "date": "2020",
         "description": "Errata and security/identifier clarifications "
                        "(JoinEUI naming, key derivation)."},
        {"version": "1.1", "date": "2017",
         "description": "Adds rejoin, separate network/app session keys, "
                        "roaming (parallel branch)."},
    ]
    d["overview"] = (
        "LoRa/LoRaWAN is a low-power wide-area network. The LoRa physical "
        "layer (Semtech, proprietary) uses Chirp Spread Spectrum modulation: "
        "a LoRa symbol is a linear frequency chirp that sweeps the channel "
        "bandwidth and encodes SF bits by its cyclic start frequency. The "
        "Spreading Factor (SF7-SF12) and bandwidth (125/250/500 kHz) set the "
        "data rate, range, and sensitivity; a coding rate of 4/5..4/8 adds "
        "FEC. A frame is a preamble of up-chirps, a sync word (0x34 public / "
        "0x12 private), an optional explicit header, the payload, and a "
        "16-bit CRC. The combination yields a ~154 dB link budget and "
        "kilometre-scale sub-GHz range at milliwatt power. On top, the LoRa "
        "Alliance LoRaWAN MAC defines a star-of-stars of end-devices, "
        "transparent gateways, and a network server (plus join and "
        "application servers); device Classes A/B/C; OTAA/ABP activation with "
        "DevEUI/JoinEUI/AppKey and derived DevAddr/NwkSKey/AppSKey; Adaptive "
        "Data Rate; duty-cycle ALOHA access; RX1/RX2 receive windows; MAC "
        "commands; a frame counter; and AES-128 security (4-byte MIC + "
        "payload encryption).")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS: two-layer LPWAN model (CSS PHY + LoRaWAN MAC).
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Low-power wide-area network (LPWAN). Two layers: the Semtech LoRa "
        "PHY (Chirp Spread Spectrum, SF7-SF12, 125/250/500 kHz, coding rate "
        "4/5..4/8) and the LoRa Alliance LoRaWAN MAC (star-of-stars, Classes "
        "A/B/C, OTAA/ABP, ADR, duty cycle, RX1/RX2, MAC commands, FCnt, MIC).")
    po["duplex"] = (
        "half-duplex, end-device-initiated. Class A: each uplink is followed "
        "by two short downlink windows (RX1/RX2). Class B adds scheduled ping "
        "slots; Class C keeps the receiver open continuously.")
    po["modulation"] = (
        "Chirp Spread Spectrum (CSS): each symbol is a linear frequency chirp "
        "across the channel bandwidth, encoding SF bits by its cyclic start "
        "frequency; up-chirp / down-chirp.")
    po["spreading_factors"] = list(_SPREADING_FACTORS)
    po["bandwidths_khz"] = list(_BANDWIDTHS_KHZ)
    po["coding_rates"] = list(_CODING_RATES)
    po["symbol_time_formula"] = "Tsym = 2^SF / BW"
    po["symbol_rate_formula"] = "Rsym = BW / 2^SF"
    po["bit_rate_formula"] = "Rb = SF * (BW / 2^SF) * CR"
    po["sync_word_public"] = _SYNC_WORD_PUBLIC
    po["sync_word_private"] = _SYNC_WORD_PRIVATE
    po["preamble_default_symbols"] = _PREAMBLE_DEFAULT_SYMBOLS
    po["bands"] = ["EU868 (863-870 MHz)", "US915 (902-928 MHz)", "AS923",
                   "AU915", "IN865", "KR920", "CN470"]
    po["link_budget_dB"] = 154
    po["sensitivity_dBm_SF12_125kHz"] = -148
    po["device_classes"] = list(_DEVICE_CLASSES)
    po["activation_methods"] = ["OTAA", "ABP"]
    po["channel_access"] = "unslotted ALOHA with regional duty-cycle limits"
    po["security"] = (
        "AES-128: 4-byte MIC (AES-128-CMAC, NwkSKey) + payload encryption "
        "(AES-128-CTR, AppSKey); FCnt replay protection.")
    po["layers"] = [
        "Application layer (application payload, AppSKey end-to-end "
        "encryption)",
        "LoRaWAN MAC layer (Classes A/B/C, OTAA/ABP, ADR, MAC commands, "
        "FCnt/MIC, RX windows, duty cycle)",
        "LoRa PHY layer (CSS modulation, SF/BW/CR, preamble+sync+header+"
        "payload+CRC frame, sub-GHz RF)",
    ]
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "The PHY shall use Chirp Spread Spectrum "
         "(CSS): each symbol is a linear chirp over the channel bandwidth "
         "carrying SF bits (2^SF chips/symbol)."},
        {"id": "FR-SF-02", "text": "The Spreading Factor shall be one of "
         "SF7..SF12; symbol duration Tsym = 2^SF / BW. Higher SF gives more "
         "range/sensitivity and lower data rate."},
        {"id": "FR-BW-03", "text": "The channel bandwidth shall be 125, 250, "
         "or 500 kHz; the chip rate equals the bandwidth and the symbol rate "
         "is BW / 2^SF."},
        {"id": "FR-CR-04", "text": "A forward-error-correction coding rate of "
         "4/5, 4/6, 4/7, or 4/8 shall be applied."},
        {"id": "FR-FRAME-05", "text": "A PHY frame shall consist of a preamble "
         "(default 8 up-chirps), a sync word (0x34 public / 0x12 private), an "
         "optional explicit header (length, CR, header CRC), the payload, and "
         "a 16-bit payload CRC on uplinks."},
        {"id": "FR-ARCH-06", "text": "LoRaWAN shall use a star-of-stars: each "
         "uplink is received by all in-range gateways and forwarded to a "
         "central network server; gateways are transparent bridges."},
        {"id": "FR-CLASS-07", "text": "Every end-device shall implement Class "
         "A (two RX windows after each uplink); Class B (beacon ping slots) "
         "and Class C (continuous receive) are optional extensions."},
        {"id": "FR-ACT-08", "text": "A device shall be activated by OTAA "
         "(Join-Request with DevEUI/JoinEUI/DevNonce -> Join-Accept; derive "
         "DevAddr, NwkSKey, AppSKey from AppKey) or ABP (pre-provisioned "
         "DevAddr/NwkSKey/AppSKey)."},
        {"id": "FR-ADR-09", "text": "When the ADR bit is set, the network "
         "server may issue LinkADRReq to set the device's data rate (SF), TX "
         "power, and channel mask; the device answers with LinkADRAns."},
        {"id": "FR-RX-10", "text": "After a Class A uplink the device shall "
         "open RX1 at RECEIVE_DELAY1 (default 1 s, same channel/DR offset) "
         "and, if no RX1 downlink, RX2 at RECEIVE_DELAY2 (default 2 s, fixed "
         "region freq/DR)."},
        {"id": "FR-DUTY-11", "text": "Channel access shall be unslotted ALOHA "
         "subject to the regional duty-cycle limit (e.g. 1% per sub-band in "
         "EU868)."},
        {"id": "FR-SEC-12", "text": "Each frame shall carry a 4-byte MIC "
         "(AES-128-CMAC with NwkSKey); the application payload shall be "
         "encrypted with AES-128 (AppSKey); the frame counter (FCnt) shall be "
         "included in the MIC and checked for replay."},
        {"id": "FR-MAC-13", "text": "MAC commands (LinkCheck, LinkADR, "
         "DutyCycle, RXParamSetup, DevStatus, NewChannel, RXTimingSetup, "
         "TxParamSetup) shall manage the link, carried in FOpts or on FPort "
         "0."},
    ]
    d["error_response_conditions"] = [
        "MIC verification failure — frame discarded (integrity/authenticity "
        "check failed).",
        "Frame-counter (FCnt) not greater than the last accepted value — "
        "frame rejected as a replay.",
        "Payload CRC error on an uplink — frame dropped at the gateway/server.",
        "No downlink received in RX1 or RX2 — device returns to sleep "
        "(Class A).",
        "Join-Accept not received within the join windows — OTAA join retried "
        "with backoff.",
        "Duty-cycle budget exhausted — transmission deferred until the "
        "sub-band is available again.",
    ]
    d["compliance_requirements"] = [
        "CSS modulation with SF7-SF12 and 125/250/500 kHz bandwidth.",
        "Coding rate 4/5..4/8 FEC; preamble + sync word + payload + CRC "
        "frame.",
        "Class A mandatory; RX1/RX2 windows at the regional delays.",
        "OTAA and/or ABP activation with the LoRaWAN key hierarchy.",
        "ADR support and the standard MAC-command set.",
        "Regional duty-cycle / dwell-time compliance.",
        "AES-128 MIC (4 bytes) + payload encryption; FCnt replay protection.",
        "LoRa Alliance certification against LoRaWAN L2 + Regional "
        "Parameters.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command/MAC-frame protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "LoRaWAN MAC frame protocol over the LoRa CSS PHY. The PHY transports "
        "a frame (preamble + sync word + header + payload + CRC) modulated as "
        "Chirp Spread Spectrum; the MAC frame inside is MHDR | MACPayload | "
        "MIC, with MAC commands managing the link.")
    d["phy_frame_structure"] = [
        {"field": "Preamble",
         "description": "Programmable number of up-chirps (default 8) for "
         "detection/synchronization."},
        {"field": "Sync word",
         "description": "Network-identifying symbols; 0x34 public LoRaWAN, "
         "0x12 private."},
        {"field": "Start-of-frame delimiter",
         "description": "2.25 down-chirps marking the end of the preamble."},
        {"field": "Explicit header (optional)",
         "description": "Payload length, coding rate, header CRC; omitted in "
         "implicit-header mode."},
        {"field": "Payload", "description": "The LoRaWAN PHYPayload."},
        {"field": "Payload CRC",
         "description": "16-bit CRC for error detection (uplinks)."},
    ]
    d["mac_frame_format"] = {
        "PHYPayload": "MHDR | MACPayload | MIC",
        "MHDR_bytes": 1,
        "MHDR_fields": "MType (frame type) + Major version",
        "MType_values": ["Join-Request", "Join-Accept", "Unconfirmed Data Up",
                         "Unconfirmed Data Down", "Confirmed Data Up",
                         "Confirmed Data Down", "Rejoin-Request"],
        "MACPayload": "FHDR | FPort | FRMPayload",
        "FHDR": "DevAddr (4 B) | FCtrl (1 B) | FCnt (2 B) | FOpts (0-15 B)",
        "FCtrl_fields": "ADR | ADRACKReq | ACK | FPending | FOptsLen",
        "FPort_bytes": 1,
        "FPort_meaning": "0 = MAC-command-only; 1-223 = application data",
        "FRMPayload": "AES-128-CTR-encrypted application payload (AppSKey)",
        "MIC_bytes": _MIC_BYTES,
        "MIC_meaning": "AES-128-CMAC over the frame keyed by NwkSKey",
    }
    d["mac_commands"] = [
        {"name": "LinkCheckReq/Ans", "cid": "0x02",
         "purpose": "Device asks for link margin and gateway count."},
        {"name": "LinkADRReq/Ans", "cid": "0x03",
         "purpose": "Server sets data rate (SF), TX power, and channel mask."},
        {"name": "DutyCycleReq/Ans", "cid": "0x04",
         "purpose": "Server sets the device's maximum duty cycle."},
        {"name": "RXParamSetupReq/Ans", "cid": "0x05",
         "purpose": "Server sets RX1DROffset, RX2 data rate, RX2 frequency."},
        {"name": "DevStatusReq/Ans", "cid": "0x06",
         "purpose": "Server asks for battery level and demodulation margin."},
        {"name": "NewChannelReq/Ans", "cid": "0x07",
         "purpose": "Server defines or modifies a channel."},
        {"name": "RXTimingSetupReq/Ans", "cid": "0x08",
         "purpose": "Server sets RECEIVE_DELAY1."},
        {"name": "TxParamSetupReq/Ans", "cid": "0x09",
         "purpose": "Server sets max EIRP and dwell time."},
    ]
    d["activation_procedures"] = {
        "OTAA": "Join-Request (DevEUI, JoinEUI, DevNonce) -> Join-Accept "
                "(DevAddr, settings, AppNonce); derive NwkSKey + AppSKey from "
                "AppKey.",
        "ABP": "DevAddr, NwkSKey, AppSKey pre-provisioned; no join exchange.",
    }
    d["frame_counter"] = {
        "uplink": "FCntUp", "downlink": "FCntDown", "width_bits": 16,
        "role": "incremented per frame, included in the MIC, checked for "
                "replay (must increase).",
    }
    d["byte_oriented"] = True
    d["addressing"] = {
        "DevEUI_bits": 64, "JoinEUI_bits": 64, "DevAddr_bits": 32,
        "note": "DevEUI is the globally unique IEEE EUI-64; DevAddr is the "
                "32-bit network-local address assigned at join.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / parameter map (modem configuration + MAC session state).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "The LoRa modem (e.g. SX127x/SX126x) is configured through PHY "
        "parameters (frequency, SF, bandwidth, coding rate, preamble length, "
        "sync word, TX power, header/CRC mode). The LoRaWAN session context "
        "(DevAddr, NwkSKey, AppSKey, FCntUp, FCntDown, channel mask, RX1/RX2 "
        "settings) is MAC-layer state held by the end-device and network "
        "server.")
    d["phy_configuration_registers"] = [
        {"name": "Frequency", "purpose": "RF carrier (sub-GHz channel)."},
        {"name": "SpreadingFactor", "purpose": "SF7-SF12 chirp spreading "
         "factor."},
        {"name": "Bandwidth", "purpose": "125 / 250 / 500 kHz channel "
         "bandwidth."},
        {"name": "CodingRate", "purpose": "4/5..4/8 FEC coding rate."},
        {"name": "PreambleLength", "purpose": "Number of preamble symbols "
         "(default 8)."},
        {"name": "SyncWord", "purpose": "0x34 public / 0x12 private network."},
        {"name": "TxPower", "purpose": "Output power (regional EIRP limit)."},
        {"name": "HeaderMode", "purpose": "Explicit / implicit header."},
        {"name": "CrcEnable", "purpose": "Payload CRC on/off (on for "
         "uplinks)."},
        {"name": "LowDataRateOptimize", "purpose": "Set for long symbols "
         "(SF11/SF12 at 125 kHz)."},
    ]
    d["mac_session_state"] = [
        {"name": "DevAddr", "width_bits": 32, "purpose": "Network-local device "
         "address."},
        {"name": "NwkSKey", "width_bits": 128, "purpose": "Network session "
         "key (MIC + MAC-command security)."},
        {"name": "AppSKey", "width_bits": 128, "purpose": "Application session "
         "key (payload encryption)."},
        {"name": "FCntUp", "width_bits": 32, "purpose": "Uplink frame "
         "counter."},
        {"name": "FCntDown", "width_bits": 32, "purpose": "Downlink frame "
         "counter."},
        {"name": "ChannelMask", "purpose": "Enabled channels (set by "
         "LinkADRReq/NewChannelReq)."},
        {"name": "RxParams", "purpose": "RX1DROffset, RX2 DR, RX2 frequency, "
         "RECEIVE_DELAY1."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / RF (CSS sub-GHz signaling).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Sub-GHz RF (EU868 863-870 MHz / US915 902-928 MHz, etc.) modulated "
        "with Chirp Spread Spectrum: a linear frequency chirp sweeps the "
        "channel bandwidth (125/250/500 kHz) and encodes SF bits by its "
        "cyclic start frequency. CSS processing gain (2^SF chips/symbol) "
        "yields a ~154 dB link budget and ~-148 dBm sensitivity at "
        "SF12/125 kHz, enabling demodulation below the noise floor and "
        "kilometre-scale range at milliwatt TX power.")
    d["modulation"] = "Chirp Spread Spectrum (CSS), linear up-/down-chirp."
    d["rf_bands"] = ["EU868 (863-870 MHz)", "US915 (902-928 MHz)", "AS923",
                     "AU915", "IN865", "KR920", "CN470"]
    d["spreading_factors"] = list(_SPREADING_FACTORS)
    d["bandwidths_khz"] = list(_BANDWIDTHS_KHZ)
    d["chips_per_symbol"] = "2^SF"
    d["link_budget_dB"] = 154
    d["sensitivity_dBm"] = {"SF12_125kHz": -148, "note": "improves with "
                            "higher SF and narrower bandwidth"}
    d["transmitter_specs_canonical"] = {
        "modulation": "CSS", "spreading_factors": list(_SPREADING_FACTORS),
        "bandwidths_khz": list(_BANDWIDTHS_KHZ),
        "coding_rates": list(_CODING_RATES),
        "tx_power": "regional EIRP limit (e.g. +14 dBm EU868, +30 dBm US915)",
        "duty_cycle": "regional limit (e.g. 1% EU868)",
    }
    d["receiver_specs_canonical"] = {
        "modulation": "CSS de-chirp correlation",
        "sensitivity_dBm_SF12_125kHz": -148,
        "snr_floor": "demodulates below the noise floor (negative SNR) thanks "
                     "to CSS processing gain",
        "channel_activity_detection": "CAD detects a LoRa preamble at low "
                                      "power before full reception.",
    }
    d["range_km"] = {"urban": "2-5", "rural_los": ">15"}
    d["data_rate_table"] = [
        {"DR": 0, "config": "SF12/125kHz", "bit_per_s": 250},
        {"DR": 1, "config": "SF11/125kHz", "bit_per_s": 440},
        {"DR": 2, "config": "SF10/125kHz", "bit_per_s": 980},
        {"DR": 3, "config": "SF9/125kHz", "bit_per_s": 1760},
        {"DR": 4, "config": "SF8/125kHz", "bit_per_s": 3125},
        {"DR": 5, "config": "SF7/125kHz", "bit_per_s": 5470},
        {"DR": 6, "config": "SF7/250kHz", "bit_per_s": 11000},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / FSM (end-device MAC state machine).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_end_device_mac"] = [
        {"name": "IDLE_SLEEP", "description": "Low-power; radio off; waiting "
         "for application data."},
        {"name": "JOIN", "description": "(OTAA) send Join-Request, open join "
         "receive windows, await Join-Accept, derive NwkSKey/AppSKey."},
        {"name": "TX", "description": "Transmit an uplink LoRa frame "
         "(preamble, sync word, header, payload, CRC) on a duty-cycle-"
         "permitted channel."},
        {"name": "RX1_WAIT", "description": "Wait RECEIVE_DELAY1 (default "
         "1 s)."},
        {"name": "RX1", "description": "Open RX1 on the uplink channel/DR "
         "(offset by RX1DROffset); demodulate any downlink."},
        {"name": "RX2_WAIT", "description": "If no RX1 downlink, wait until "
         "RECEIVE_DELAY2 (default 2 s)."},
        {"name": "RX2", "description": "Open RX2 on the fixed region "
         "frequency/DR."},
        {"name": "PROCESS", "description": "Verify MIC (NwkSKey), check FCnt, "
         "decrypt FRMPayload (AppSKey), process MAC commands; return to "
         "IDLE_SLEEP."},
    ]
    d["fsm_hints"] = {
        "trigger": "An application uplink (or scheduled report) moves "
        "IDLE_SLEEP -> TX. On power-up an OTAA device enters JOIN first.",
        "rule": "Class A: every TX is followed by RX1 then (if needed) RX2; "
        "the radio sleeps otherwise. Class C keeps RX open continuously; "
        "Class B adds beacon-synchronized ping slots.",
        "abort": "MIC failure or FCnt replay -> discard frame and return to "
        "IDLE_SLEEP; failed join -> retry with backoff.",
    }
    d["class_behavior"] = {
        "A": "Two RX windows after each uplink; lowest power; mandatory.",
        "B": "Class A windows plus scheduled ping slots synchronized to a "
             "periodic gateway beacon.",
        "C": "Receiver open continuously except while transmitting; lowest "
             "downlink latency, highest power.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up an OTAA device enters JOIN and must complete the join "
        "procedure before sending data; an ABP device already holds "
        "DevAddr/NwkSKey/AppSKey, restores its frame counters from "
        "non-volatile memory, and may transmit immediately.")
    d["adr_control"] = (
        "When the ADR bit is set, the network server observes uplink SNR/link "
        "margin and issues LinkADRReq to raise the data rate (lower SF) and "
        "lower TX power; the device confirms with LinkADRAns. Mobile devices "
        "may disable ADR.")
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
        {"name": "DevStatusReq/Ans", "purpose": "Battery level and "
         "demodulation margin reported by the device."},
        {"name": "LinkCheckReq/Ans", "purpose": "Link margin and gateway "
         "count reported to the device."},
        {"name": "RSSI / SNR", "purpose": "Received-signal strength and "
         "signal-to-noise of each frame, reported by the gateway/network "
         "server."},
        {"name": "MIC-failure / FCnt counters", "purpose": "Integrity-failure "
         "and replay-detection telemetry at the network server."},
        {"name": "Channel Activity Detection (CAD)", "purpose": "Low-power "
         "preamble detection used to probe the channel."},
    ]
    d["error_detection_mechanisms"] = [
        "16-bit payload CRC on uplinks (PHY).",
        "4-byte MIC (AES-128-CMAC) integrity/authenticity check (MAC).",
        "Frame-counter (FCnt) replay detection.",
        "Header CRC in explicit-header mode.",
    ]
    d["test_modes"] = [
        {"name": "LoRa Alliance Certification", "purpose": "Conformance to "
         "LoRaWAN L2 + Regional Parameters (join, ADR, MAC commands, RX "
         "timing, class behaviors)."},
        {"name": "CAD test", "purpose": "Verify preamble detection at low "
         "power."},
        {"name": "Class-switch test", "purpose": "Verify Class A/B/C "
         "downlink-reception behavior."},
    ]
    d["notes"] = (
        "Observability is in-protocol: DevStatus/LinkCheck MAC commands, "
        "gateway-reported RSSI/SNR, and network-server MIC/FCnt counters. "
        "Conformance is established by the LoRa Alliance Certification "
        "program; chip-level scan/BIST is an integrator concern.")
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
        "LORAWAN_SPEC_VERSION": "1.0.4",
        "MODULATION": "CSS",
        "SPREADING_FACTORS": list(_SPREADING_FACTORS),
        "MIN_SPREADING_FACTOR": 7,
        "MAX_SPREADING_FACTOR": 12,
        "BANDWIDTHS_KHZ": list(_BANDWIDTHS_KHZ),
        "CODING_RATES": list(_CODING_RATES),
        "PREAMBLE_DEFAULT_SYMBOLS": _PREAMBLE_DEFAULT_SYMBOLS,
        "SYNC_WORD_PUBLIC": _SYNC_WORD_PUBLIC,
        "SYNC_WORD_PRIVATE": _SYNC_WORD_PRIVATE,
        "PAYLOAD_CRC_WIDTH_BITS": 16,
        "MIC_BYTES": _MIC_BYTES,
        "MIC_WIDTH_BITS": 32,
        "AES_KEY_BITS": _AES_KEY_BITS,
        "DEVEUI_BITS": 64,
        "JOINEUI_BITS": 64,
        "DEVADDR_BITS": 32,
        "FCNT_WIDTH_BITS": 16,
        "MHDR_BYTES": 1,
        "FHDR_FCTRL_BYTES": 1,
        "FPORT_BYTES": 1,
        "FOPTS_MAX_BYTES": 15,
        "DEVICE_CLASSES": list(_DEVICE_CLASSES),
        "RECEIVE_DELAY1_S": 1,
        "RECEIVE_DELAY2_S": 2,
        "LINK_BUDGET_DB": 154,
        "SENSITIVITY_DBM_SF12_125KHZ": -148,
    })
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_wireless": True,
        "is_lpwan": True,
        "modulation": "CSS",
        "spreading_factor_range": "SF7-SF12",
        "bandwidths_khz": list(_BANDWIDTHS_KHZ),
        "coding_rate_range": "4/5-4/8",
        "preamble_default_symbols": _PREAMBLE_DEFAULT_SYMBOLS,
        "sync_word_public": _SYNC_WORD_PUBLIC,
        "sync_word_private": _SYNC_WORD_PRIVATE,
        "mic_bytes": _MIC_BYTES,
        "aes_key_bits": _AES_KEY_BITS,
        "device_classes": list(_DEVICE_CLASSES),
        "activation": ["OTAA", "ABP"],
        "adr_supported": True,
        "duty_cycle_limited": True,
    })
    d["css_constants"] = {
        "chips_per_symbol": "2^SF",
        "symbol_time_formula": "Tsym = 2^SF / BW",
        "symbol_rate_formula": "Rsym = BW / 2^SF",
        "bit_rate_formula": "Rb = SF * (BW / 2^SF) * CR",
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
    d["phy_frame_waveform"] = {
        "order": ["Preamble (up-chirps, default 8)",
                  "Sync word (0x34 public / 0x12 private)",
                  "Start-of-frame delimiter (2.25 down-chirps)",
                  "Explicit header (optional) + header CRC",
                  "Payload",
                  "Payload CRC (16-bit, uplinks)"],
        "modulation": "CSS chirp per symbol; each symbol = 2^SF chips over "
                      "the bandwidth.",
    }
    d["symbol_timing"] = {
        "symbol_time_formula": "Tsym = 2^SF / BW",
        "examples": {
            "SF7_125kHz_ms": 1.024, "SF10_125kHz_ms": 8.192,
            "SF12_125kHz_ms": 32.768},
        "note": "Higher SF / narrower bandwidth -> longer symbol -> longer "
                "time-on-air.",
    }
    d["class_a_receive_window_timing"] = {
        "RX1_open": "RECEIVE_DELAY1 (default 1 s) after end of uplink, same "
                    "channel/DR (offset by RX1DROffset)",
        "RX2_open": "RECEIVE_DELAY2 (default 2 s) after uplink, fixed region "
                    "frequency/DR (e.g. 869.525 MHz / DR0 in EU868)",
        "rule": "If a valid downlink preamble is detected in RX1, RX2 is not "
                "opened.",
    }
    d["duty_cycle_timing"] = (
        "Unslotted ALOHA; regional duty-cycle limit (e.g. 1% per sub-band in "
        "EU868) bounds the fraction of time a device may transmit, enforcing "
        "an off-time proportional to the last time-on-air.")
    d["general_timing_rule"] = (
        "Time-on-air grows with spreading factor and shrinks with bandwidth; "
        "the receiver synchronizes on the preamble up-chirps and the sync "
        "word before demodulating the payload by de-chirp correlation.")
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
        "Low-power wide-area network end-device modem + MAC: a LoRa CSS PHY "
        "(SF7-SF12, 125/250/500 kHz, coding rate 4/5..4/8) under the LoRaWAN "
        "MAC (Classes A/B/C, OTAA/ABP, ADR, duty-cycle ALOHA, RX1/RX2, MAC "
        "commands, FCnt, AES-128 MIC + payload encryption) communicating with "
        "gateways and a network server over sub-GHz RF.")
    d["topology_description"] = (
        "Star-of-stars: each end-device uplink is received by all in-range "
        "gateways and relayed to a central network server; downlinks go "
        "through one server-selected gateway. End-devices are not bound to a "
        "single gateway.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "lorawan_spec_version": "1.0.4",
        "modulation": "CSS",
        "spreading_factors": list(_SPREADING_FACTORS),
        "bandwidths_khz": list(_BANDWIDTHS_KHZ),
        "coding_rates": list(_CODING_RATES),
        "device_classes": list(_DEVICE_CLASSES),
        "activation": ["OTAA", "ABP"],
        "adr_supported": True,
        "duty_cycle_limited": True,
        "rf_bands": ["EU868", "US915", "AS923", "AU915", "IN865", "KR920",
                     "CN470"],
        "host_side_register_spec": "Modem PHY config (freq/SF/BW/CR/preamble/"
        "sync word/TX power) over an SPI transceiver interface; LoRaWAN "
        "session state (DevAddr/NwkSKey/AppSKey/FCnt) in device + server.",
    })
    d["interface_categories"] = [
        "Application layer — application payload, AppSKey end-to-end "
        "encryption.",
        "LoRaWAN MAC — Classes A/B/C, OTAA/ABP, ADR, MAC commands, FCnt/MIC, "
        "RX windows, duty cycle.",
        "LoRa PHY — CSS modulation, SF/BW/CR, frame (preamble+sync+header+"
        "payload+CRC), sub-GHz RF.",
        "Gateway interface — transparent RF<->IP bridge to the network "
        "server.",
    ]
    d["interconnect_topologies_supported"] = [
        "Star-of-stars (end-devices -> multiple gateways -> network server).",
        "Single-gateway star (small private network).",
    ]
    d["soc_dependent_items"] = [
        "Regional band / duty-cycle / dwell-time plan (EU868, US915, ...).",
        "Device class (A mandatory; B beacon; C continuous receive).",
        "Activation method (OTAA vs ABP) and key provisioning.",
        "LoRa transceiver (SX127x/SX126x) and antenna front-end.",
        "Power budget / battery for the chosen class and ADR policy.",
    ]
    d["device_classes_examples"] = [
        "Class A battery sensor (metering, agriculture)",
        "Class B time-synchronized actuator with bounded downlink latency",
        "Class C mains-powered actuator with continuous receive",
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
        "partial - the spec defines compliance behaviors mapped to the LoRa "
        "Alliance Certification program (join, ADR, MAC commands, RX-window "
        "timing, class behaviors, security); no full RTL testbench in the "
        "document itself.")
    d["derived_compliance_test_categories"] = [
        "CSS modulation at each Spreading Factor SF7..SF12.",
        "Bandwidth 125 / 250 / 500 kHz operation.",
        "Coding rate 4/5..4/8 FEC encode/decode.",
        "Frame: preamble + sync word (0x34 public / 0x12 private) + header + "
        "payload + 16-bit CRC.",
        "OTAA join: Join-Request -> Join-Accept -> session-key derivation.",
        "ABP activation with pre-provisioned keys.",
        "Class A: RX1 at RECEIVE_DELAY1, RX2 at RECEIVE_DELAY2.",
        "Class B: beacon-synchronized ping slots.",
        "Class C: continuous receive.",
        "Adaptive Data Rate: LinkADRReq/Ans, link-margin tracking.",
        "Duty-cycle enforcement (e.g. 1% EU868).",
        "MAC commands (LinkCheck, LinkADR, DutyCycle, RXParamSetup, "
        "DevStatus, NewChannel, RXTimingSetup, TxParamSetup).",
        "MIC (AES-128-CMAC) verification and tamper rejection.",
        "AES-128 payload encryption/decryption (AppSKey).",
        "Frame-counter (FCnt) replay rejection.",
        "Regional band coverage (EU868, US915, ...).",
        "Link budget / sensitivity at SF12/125 kHz (~-148 dBm).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned identity fields.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "DevEUI", "width_bits": 64,
         "note": "Globally unique IEEE EUI-64 device identifier, provisioned "
                 "at manufacture."},
        {"field": "JoinEUI (AppEUI)", "width_bits": 64,
         "note": "Join-server identifier, provisioned for OTAA."},
        {"field": "AppKey", "width_bits": 128,
         "note": "AES-128 root key for OTAA session-key derivation; "
                 "device-unique secret."},
        {"field": "DevAddr (ABP)", "width_bits": 32,
         "note": "Pre-provisioned network address (ABP only)."},
        {"field": "NwkSKey (ABP)", "width_bits": 128,
         "note": "Pre-provisioned network session key (ABP only)."},
        {"field": "AppSKey (ABP)", "width_bits": 128,
         "note": "Pre-provisioned application session key (ABP only)."},
    ]
    d["notes"] = (
        "LoRaWAN does not mandate OTP/fuse as a protocol concept, but the "
        "root identity (DevEUI, JoinEUI, AppKey for OTAA; or "
        "DevAddr/NwkSKey/AppSKey for ABP) is device-unique secret material "
        "typically stored in secure/non-volatile memory at manufacture. An "
        "implementation may back these with fuses or a secure element.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences (join, uplink+RX, ADR, downlink).
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otaa_join_sequence"] = [
        "1. Device sends a Join-Request (DevEUI, JoinEUI, DevNonce) as a LoRa "
        "uplink.",
        "2. A gateway forwards it to the network/join server.",
        "3. The join server validates the request and returns a Join-Accept "
        "(DevAddr, settings, AppNonce) in a join receive window.",
        "4. Both ends derive NwkSKey and AppSKey from the AppKey.",
        "5. The device is now activated and may send data uplinks.",
    ]
    d["abp_activation_sequence"] = [
        "1. DevAddr, NwkSKey, AppSKey are pre-provisioned at manufacture.",
        "2. On power-up the device restores its frame counters from "
        "non-volatile memory.",
        "3. The device may transmit data uplinks immediately (no join).",
    ]
    d["uplink_with_rx_windows_sequence"] = [
        "1. Device builds a frame: MHDR | (DevAddr|FCtrl|FCnt|FOpts) | FPort | "
        "encrypted FRMPayload | MIC.",
        "2. Device transmits the LoRa frame (preamble, sync word, header, "
        "payload, CRC) on a duty-cycle-permitted channel.",
        "3. After RECEIVE_DELAY1 the device opens RX1 on the uplink "
        "channel/DR.",
        "4. If no downlink in RX1, after RECEIVE_DELAY2 it opens RX2 on the "
        "fixed region frequency/DR.",
        "5. A received downlink is MIC-verified (NwkSKey), FCnt-checked, and "
        "decrypted (AppSKey); MAC commands are processed.",
        "6. The device returns to sleep (Class A).",
    ]
    d["adr_sequence"] = [
        "1. Device sets the ADR bit in FCtrl.",
        "2. Network server tracks the uplink SNR / link margin.",
        "3. Server issues LinkADRReq to raise the data rate (lower SF) and "
        "lower TX power.",
        "4. Device applies the new parameters and answers LinkADRAns.",
    ]
    d["downlink_sequence"] = [
        "1. Network server queues a downlink and selects one gateway.",
        "2. The gateway transmits in the device's RX1 (or RX2) window "
        "(Class A), a ping slot (Class B), or anytime (Class C).",
        "3. The device demodulates, verifies the MIC, checks FCntDown, and "
        "decrypts the payload.",
    ]
    d["reset_sequence"] = [
        "1. Power-on / reset.",
        "2. OTAA device -> JOIN state (must join before data); ABP device "
        "restores keys/counters and may transmit.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab / characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Receiver sensitivity per SF/BW", "purpose": "Confirm "
         "~-148 dBm at SF12/125 kHz and the sensitivity ladder across "
         "SF7-SF12."},
        {"name": "Link budget", "purpose": "Verify ~154 dB end-to-end."},
        {"name": "Time-on-air per SF/BW/CR", "purpose": "Validate symbol time "
         "Tsym = 2^SF/BW and frame airtime."},
        {"name": "Frequency / channel accuracy", "purpose": "Confirm carrier "
         "and channel plan against the regional band."},
        {"name": "TX power / EIRP", "purpose": "Confirm regional power limit "
         "(e.g. +14 dBm EU868)."},
        {"name": "Duty-cycle compliance", "purpose": "Measure off-time "
         "enforcement (e.g. 1% EU868)."},
        {"name": "RX-window timing", "purpose": "Confirm RX1/RX2 open at "
         "RECEIVE_DELAY1 / RECEIVE_DELAY2."},
    ]
    d["notes"] = (
        "LoRa characterization centers on the CSS link: sensitivity and link "
        "budget per SF/BW, time-on-air, channel/frequency accuracy, TX "
        "power/EIRP, duty-cycle enforcement, and RX-window timing. "
        "Conformance is established by the LoRa Alliance Certification "
        "program.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — protocol versioning + traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "LoRa PHY (Semtech CSS) + LoRaWAN L2 1.0.4 (LoRa Alliance, 2020) + "
        "Regional Parameters")
    f["previous_versions"] = [
        "LoRaWAN 1.0 (2015) — initial MAC (OTAA/ABP, Classes A/B/C, ADR, "
        "AES-128).",
        "LoRaWAN 1.0.2 (2016) — Regional Parameters split out.",
    ]
    f["key_changes"] = [
        {"version": "1.0.4", "summary": "Errata and security/identifier "
         "clarifications (JoinEUI naming formerly AppEUI, key derivation); "
         "same CSS PHY, Classes A/B/C, OTAA/ABP, ADR, and AES-128 security."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "LoRaWAN 1.1 (2017)", "summary": "Adds rejoin, separate "
         "network/application session keys (FNwkSIntKey / SNwkSIntKey / "
         "NwkSEncKey), and roaming; backward-compatible PHY."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Sync_word_public_vs_private",
         "rule": "Public LoRaWAN uses sync word 0x34; private networks use "
                 "0x12.",
         "trap": "A device with the wrong sync word will not detect frames "
                 "from the intended network."},
        {"trap_name": "Class_A_always_mandatory",
         "rule": "Every end-device must implement Class A; B and C are "
                 "supersets.",
         "trap": "Assuming a Class C device can drop Class A behavior breaks "
                 "interoperability."},
        {"trap_name": "Duty_cycle_is_mandatory",
         "rule": "Regional duty-cycle limits (e.g. 1% EU868) bound airtime.",
         "trap": "Ignoring the duty cycle is non-compliant and degrades the "
                 "shared network."},
        {"trap_name": "FCnt_must_increase",
         "rule": "The frame counter must strictly increase; the receiver "
                 "rejects non-increasing counters as replays.",
         "trap": "Resetting FCnt without a rejoin (ABP) causes the server to "
                 "reject frames."},
        {"trap_name": "OTAA_vs_ABP_key_freshness",
         "rule": "OTAA derives fresh session keys at join; ABP uses static "
                 "keys.",
         "trap": "ABP's static keys are weaker; treating ABP as equivalent to "
                 "OTAA security is wrong."},
    ]
    f["version_naming_history_note"] = (
        "The LoRa PHY (Chirp Spread Spectrum) is a stable Semtech proprietary "
        "layer; the LoRaWAN MAC is an open LoRa Alliance standard layered on "
        "top. LoRaWAN 1.0 (2015) established OTAA/ABP, Classes A/B/C, ADR, and "
        "AES-128 security; 1.0.4 (2020) added errata and identifier/security "
        "clarifications; the parallel 1.1 (2017) branch added rejoin, split "
        "session keys, and roaming.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding tables (SF / data rate / coding rate / class / band).
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["data_rate_table"] = {
        "header_columns": ["DR", "SF", "Bandwidth (kHz)", "Bit rate (bit/s)"],
        "rows": [
            ["DR0", "SF12", "125", "250"],
            ["DR1", "SF11", "125", "440"],
            ["DR2", "SF10", "125", "980"],
            ["DR3", "SF9", "125", "1760"],
            ["DR4", "SF8", "125", "3125"],
            ["DR5", "SF7", "125", "5470"],
            ["DR6", "SF7", "250", "11000"],
        ],
    }
    f["spreading_factor_table"] = {
        "header_columns": ["SF", "Chips/symbol", "Relative range",
                           "Relative data rate"],
        "rows": [
            ["SF7", "128", "shortest", "highest"],
            ["SF8", "256", "", ""],
            ["SF9", "512", "", ""],
            ["SF10", "1024", "", ""],
            ["SF11", "2048", "", ""],
            ["SF12", "4096", "longest", "lowest"],
        ],
    }
    f["coding_rate_table"] = {
        "header_columns": ["Coding Rate", "Parity bits per 4 data bits",
                           "Overhead"],
        "rows": [
            ["4/5", "1", "lowest"],
            ["4/6", "2", ""],
            ["4/7", "3", ""],
            ["4/8", "4", "highest (strongest FEC)"],
        ],
    }
    f["device_class_table"] = {
        "header_columns": ["Class", "Downlink reception", "Power"],
        "rows": [
            ["A", "Two RX windows after each uplink", "lowest (mandatory)"],
            ["B", "Class A + scheduled beacon ping slots", "medium"],
            ["C", "Continuous receive (except TX)", "highest"],
        ],
    }
    f["sync_word_table"] = {
        "header_columns": ["Network", "Sync word"],
        "rows": [["Public LoRaWAN", _SYNC_WORD_PUBLIC],
                 ["Private", _SYNC_WORD_PRIVATE]],
    }
    f["band_table"] = {
        "header_columns": ["Region", "Band"],
        "rows": [["EU868", "863-870 MHz"], ["US915", "902-928 MHz"],
                 ["AS923", "915-928 MHz"], ["AU915", "915-928 MHz"],
                 ["IN865", "865-867 MHz"], ["KR920", "920-923 MHz"],
                 ["CN470", "470-510 MHz"]],
    }
    f["mtype_table"] = {
        "header_columns": ["MType", "Meaning"],
        "rows": [
            ["000", "Join-Request"], ["001", "Join-Accept"],
            ["010", "Unconfirmed Data Up"], ["011", "Unconfirmed Data Down"],
            ["100", "Confirmed Data Up"], ["101", "Confirmed Data Down"],
            ["110", "Rejoin-Request"], ["111", "Proprietary"]],
    }
    f["tables"] = [
        "Data-rate table (DR0-DR6: SF/BW/bit-rate)",
        "Spreading-factor table (SF7-SF12 chips/symbol)",
        "Coding-rate table (4/5-4/8)",
        "Device-class table (A/B/C)",
        "Sync-word table (public 0x34 / private 0x12)",
        "Regional band table (EU868/US915/...)",
        "MHDR MType table",
    ]
    f["encoding_note"] = (
        "LoRa encodes SF bits per CSS symbol by the chirp's cyclic start "
        "frequency; FEC adds a 4/5..4/8 coding rate. LoRaWAN frame types are "
        "set by the 3-bit MType in MHDR; data rates map (SF, BW) to a DR "
        "index per the Regional Parameters.")
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties + distinguishers.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Chirp Spread Spectrum (CSS) modulation with Spreading Factor "
        "SF7-SF12.",
        "Channel bandwidth 125 / 250 / 500 kHz and coding rate 4/5..4/8.",
        "Frame = preamble + sync word (0x34 public / 0x12 private) + optional "
        "header + payload + 16-bit CRC.",
        "Sub-GHz regional band operation (EU868 / US915 / ...).",
        "LoRaWAN star-of-stars with end-devices, gateways, and a network "
        "server.",
        "Class A mandatory (RX1/RX2 windows); Class B/C optional supersets.",
        "OTAA and/or ABP activation with the DevEUI/JoinEUI/AppKey -> "
        "DevAddr/NwkSKey/AppSKey key hierarchy.",
        "Adaptive Data Rate and the standard MAC-command set.",
        "Regional duty-cycle / dwell-time compliance.",
        "AES-128 4-byte MIC integrity + AES-128 payload encryption + FCnt "
        "replay protection.",
    ]
    f["must_not_have_properties"] = [
        "GAP/GATT or BLE advertising/connection events (that is Bluetooth Low "
        "Energy, not LoRa).",
        "13.56 MHz inductive coupling / ISO 14443 / NDEF (that is NFC).",
        "DSSS / O-QPSK / IEEE 802.15.4 / PAN-ID / ZCL (that is Zigbee).",
        "A frame counter that does not increase (replay-vulnerable).",
        "Ignoring the regional duty cycle.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Wrong sync word", "trigger": "Device uses 0x12 on a public "
         "0x34 network (or vice versa) and detects no frames."},
        {"mode": "MIC failure", "trigger": "AES-128-CMAC mismatch; frame "
         "discarded."},
        {"mode": "FCnt replay", "trigger": "Counter not greater than last "
         "accepted; frame rejected."},
        {"mode": "Duty-cycle violation", "trigger": "Device exceeds the "
         "regional airtime budget."},
        {"mode": "RX-window miss", "trigger": "RX1/RX2 opened at the wrong "
         "delay; downlink lost."},
        {"mode": "Join failure", "trigger": "Join-Accept not received in the "
         "join window; OTAA retried."},
    ]
    f["lora_distinguishers"] = (
        "LoRa/LoRaWAN is identified by ALL of: Chirp Spread Spectrum (CSS) "
        "modulation with a Spreading Factor SF7-SF12; a 125/250/500 kHz "
        "bandwidth and a 4/5..4/8 coding rate; a preamble + sync word + "
        "header + payload + CRC frame; sub-GHz LPWAN operation with a ~154 dB "
        "link budget; the LoRaWAN star-of-stars of end-devices, gateways, and "
        "a network server; device Classes A/B/C; OTAA/ABP activation with "
        "DevEUI/JoinEUI/AppKey -> DevAddr/NwkSKey/AppSKey; Adaptive Data Rate; "
        "duty-cycle ALOHA; RX1/RX2 receive windows; and an AES-128 4-byte MIC "
        "plus payload encryption. This is distinct from BLE (GAP/GATT, "
        "advertising, 2.4 GHz / 40 channels), NFC (13.56 MHz inductive "
        "coupling, ISO 14443/NDEF), and Zigbee (DSSS/O-QPSK, IEEE 802.15.4, "
        "PAN-ID, ZCL) — none of which use CSS, a spreading factor, or the "
        "LoRaWAN MAC.")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog (force-overwrite fields).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "RF antenna (sub-GHz)",
         "direction": "bidirectional (half-duplex)",
         "purpose": "CSS-modulated LoRa uplink/downlink in the regional band.",
         "active_levels": "SF7-SF12 chirps at 125/250/500 kHz",
         "idle_level": "radio off (Class A/B) or RX-listening (Class C)"},
        {"name": "Transceiver SPI (SCK/MOSI/MISO/NSS)",
         "direction": "host <-> modem",
         "purpose": "Configure the LoRa modem and move payloads.",
         "active_levels": "SPI clocked transfers", "idle_level": "NSS high"},
        {"name": "DIO interrupts (TxDone/RxDone/RxTimeout/CAD)",
         "direction": "modem -> host",
         "purpose": "Signal transmit/receive completion and channel-activity "
                    "detection.",
         "active_levels": "asserted on event", "idle_level": "de-asserted"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Uplink", "meaning": "End-device -> gateway(s) CSS frame "
         "(preamble + sync + header + payload + CRC)."},
        {"name": "Downlink", "meaning": "Gateway -> end-device CSS frame in an "
         "RX window / ping slot / continuous receive."},
    ]
    f["packet_types_summary"] = [
        {"class": "MAC frame type (MType)",
         "members": ["Join-Request", "Join-Accept", "Unconfirmed Data Up",
                     "Unconfirmed Data Down", "Confirmed Data Up",
                     "Confirmed Data Down", "Rejoin-Request"],
         "count": 7},
        {"class": "Device class",
         "members": ["Class A", "Class B", "Class C"], "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "spreading_factors": len(_SPREADING_FACTORS),
        "bandwidths": len(_BANDWIDTHS_KHZ),
        "coding_rates": len(_CODING_RATES),
        "device_classes": len(_DEVICE_CLASSES),
        "mic_bytes": _MIC_BYTES,
        "aes_key_bits": _AES_KEY_BITS,
        "deveui_bits": 64,
        "devaddr_bits": 32,
        "fcnt_width_bits": 16,
    })
    f["global_signals"] = [
        {"name": "Sync word", "purpose": "Network identifier (0x34 public / "
         "0x12 private)."},
        {"name": "Preamble", "purpose": "Up-chirps for detection / "
         "synchronization (default 8 symbols)."},
        {"name": "Beacon (Class B)", "purpose": "Periodic gateway beacon for "
         "ping-slot synchronization."},
    ]
    f["dependency_graph"] = {
        "common_rule": "An end-device must be activated (OTAA join or ABP) "
        "before sending data; every uplink (Class A) is followed by RX1 then "
        "RX2; the network server deduplicates multi-gateway receptions.",
        "data_dependency": "A data frame requires a valid session context "
        "(DevAddr/NwkSKey/AppSKey); the MIC is computed over the frame with "
        "FCnt and NwkSKey; FRMPayload is encrypted with AppSKey.",
    }
    f["handshake_pairs"] = [
        {"name": "Join", "from": "end-device", "to": "join server",
         "rule": "Join-Request -> Join-Accept; derive session keys (OTAA)."},
        {"name": "Uplink/RX", "from": "end-device", "to": "gateway/server",
         "rule": "Uplink then RX1/RX2 windows for any downlink."},
        {"name": "ADR", "from": "network server", "to": "end-device",
         "rule": "LinkADRReq -> LinkADRAns to set DR/TX-power/channel mask."},
        {"name": "MAC command", "from": "either", "to": "either",
         "rule": "Req/Ans carried in FOpts or on FPort 0."},
    ]
    f["ordering_rules"] = {
        "frame_order": "Frames are ordered by the frame counter (FCnt); "
        "non-increasing counters are rejected as replays.",
        "rx_priority": "RX1 is checked before RX2; a valid RX1 downlink "
        "suppresses RX2.",
        "duplex": "Half-duplex, end-device-initiated.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — interconnect topology (star-of-stars).
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Star-of-stars: end-devices communicate by RF with multiple "
        "transparent gateways, which bridge over IP to a central network "
        "server. End-devices are not bound to a single gateway; the server "
        "deduplicates uplinks and selects one gateway per downlink.")
    f["supported_topologies"] = [
        {"name": "Star-of-stars", "description": "Many end-devices -> many "
         "gateways -> one network server."},
        {"name": "Single-gateway star", "description": "Small private network "
         "with one gateway."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "End-device", "description": "Battery-powered sensor/actuator "
         "running LoRa PHY + LoRaWAN MAC; initiates communication."},
        {"role": "Gateway", "description": "Transparent RF<->IP concentrator; "
         "relays frames; runs no MAC."},
        {"role": "Network server", "description": "Frame dedup, MAC commands, "
         "ADR, FCnt/MIC checks, gateway selection for downlinks."},
        {"role": "Join server", "description": "Handles the OTAA join and "
         "session-key derivation."},
        {"role": "Application server", "description": "Application-payload "
         "encryption/decryption (AppSKey) and application logic."},
    ]
    f["interconnect_role"] = (
        "LoRaWAN is an LPWAN access network: end-devices reach the network "
        "server through any in-range gateway. The RF segment is LoRa CSS; the "
        "backhaul segment is IP. Reliability/security (MIC, FCnt, encryption) "
        "is end-to-end between the device and the network/application "
        "server.")
    f["ordering_guarantees"] = {
        "frame_sequence": "Per-device frame counter (FCnt) orders frames and "
        "rejects replays.",
        "dedup": "The network server deduplicates the same uplink received by "
        "multiple gateways.",
        "downlink": "One server-selected gateway transmits each downlink.",
    }
    dc = _ensure_dict(f, "device_classification")
    dc["end_device_class_a"] = "Mandatory; two RX windows after each uplink."
    dc["end_device_class_b"] = "Beacon-synchronized ping slots."
    dc["end_device_class_c"] = "Continuous receive (mains-powered)."
    dc["gateway"] = "Transparent RF<->IP bridge."
    dc["network_server"] = "Central MAC/ADR/security brain."
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — channel / RF constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["rf_channel_constraints"] = {
        "modulation": "CSS (Chirp Spread Spectrum)",
        "spreading_factors": list(_SPREADING_FACTORS),
        "bandwidths_khz": list(_BANDWIDTHS_KHZ),
        "coding_rates": list(_CODING_RATES),
        "bands": ["EU868 (863-870 MHz)", "US915 (902-928 MHz)", "AS923",
                  "AU915", "IN865", "KR920", "CN470"],
        "link_budget_dB": 154,
        "sensitivity_dBm_SF12_125kHz": -148,
        "tx_power_eirp": "regional limit (e.g. +14 dBm EU868, +30 dBm US915)",
        "duty_cycle": "regional limit (e.g. 1% per sub-band in EU868); some "
                      "regions use LBT and/or dwell-time limits",
        "channel_access": "unslotted ALOHA",
    }
    f["notes"] = (
        "LoRa/LoRaWAN fixes the RF channel model (CSS, SF, bandwidth, coding "
        "rate, regional band, duty cycle, link budget). It does NOT impose "
        "PDK-specific SDC/floorplan constraints — RF front-end, antenna "
        "matching, and the LoRa transceiver (SX127x/SX126x) are "
        "implementation/integrator concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / in-band test facilities.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "DevStatusReq/Ans", "purpose": "Battery level + demodulation "
         "margin telemetry."},
        {"name": "LinkCheckReq/Ans", "purpose": "Link margin + gateway "
         "count."},
        {"name": "RSSI / SNR reporting", "purpose": "Per-frame signal quality "
         "reported by the gateway/network server."},
        {"name": "Channel Activity Detection (CAD)", "purpose": "Low-power "
         "preamble detection for channel probing."},
        {"name": "MIC / FCnt counters", "purpose": "Integrity-failure and "
         "replay telemetry at the server."},
    ]
    f["internal_diagnostics_observability"] = [
        "End-device MAC state (IDLE/JOIN/TX/RX1/RX2/PROCESS).",
        "Negotiated data rate (SF/BW), TX power, channel mask.",
        "Join status and session-key context.",
        "Frame counters (FCntUp/FCntDown).",
        "RSSI / SNR / link margin.",
    ]
    f["out_of_band_test_facilities"] = [
        "LoRa Alliance Certification test harness (join, ADR, MAC commands, "
        "RX timing, class behaviors).",
        "Vendor modem (SX127x/SX126x) register debug — implementation-"
        "defined.",
    ]
    f["notes"] = (
        "LoRaWAN's protocol-level DFT surface is the DevStatus/LinkCheck MAC "
        "commands, gateway-reported RSSI/SNR, CAD, and server-side MIC/FCnt "
        "counters. Chip-level scan/BIST is an integrator concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (low-power classes).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["device_power_states"] = [
        {"state": "SLEEP", "description": "Radio + MCU in deep sleep; lowest "
         "current; the dominant state for a Class A device.",
         "power": "lowest"},
        {"state": "TX", "description": "Transmitting a LoRa frame; highest "
         "instantaneous current (TX power).", "power": "high"},
        {"state": "RX", "description": "Receiver active during RX1/RX2 (Class "
         "A), ping slots (Class B), or continuously (Class C).",
         "power": "medium-high"},
    ]
    f["class_power_summary"] = {
        "A": "Lowest average power; radio off except for TX + two short RX "
             "windows; battery life years.",
        "B": "Medium; periodic beacon + ping slots add scheduled RX wakeups.",
        "C": "Highest; continuous RX; typically mains-powered.",
    }
    f["low_power_modes_summary"] = {
        "sleep": "Deep sleep between transmissions dominates the energy "
                 "budget; CSS time-on-air and TX power set the active energy.",
        "adr_savings": "ADR lowers SF and TX power for good links, cutting "
                       "time-on-air and energy.",
    }
    f["notes"] = (
        "LoRa is built for multi-year battery life: a Class A device sleeps "
        "almost always and wakes only to transmit and briefly receive. "
        "Spreading factor and TX power dominate active energy (higher SF = "
        "longer time-on-air = more energy), which is why ADR is central to "
        "the power model.")
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
        "CSS modulation per SF7..SF12 and per bandwidth 125/250/500 kHz.",
        "Coding-rate 4/5..4/8 FEC encode/decode.",
        "Frame parsing: preamble + sync word + header + payload + CRC.",
        "OTAA join and session-key derivation; ABP activation.",
        "Class A RX1/RX2 timing; Class B ping slots; Class C continuous RX.",
        "Adaptive Data Rate (LinkADRReq/Ans) and link-margin tracking.",
        "Duty-cycle enforcement.",
        "MAC-command set (LinkCheck/LinkADR/DutyCycle/RXParamSetup/DevStatus/"
        "NewChannel/RXTimingSetup/TxParamSetup).",
        "MIC (AES-128-CMAC) verification + tamper rejection.",
        "AES-128 payload encryption/decryption.",
        "Frame-counter (FCnt) replay rejection.",
        "Regional band coverage and sensitivity/link-budget targets.",
    ]
    f["notes"] = (
        "LoRaWAN does not ship a formal RTL testbench, but the spec implies a "
        "verification plan spanning the CSS PHY (SF/BW/CR/frame), the MAC "
        "(join, classes, ADR, MAC commands, RX timing, duty cycle), and "
        "security (MIC, encryption, FCnt). The LoRa Alliance Certification "
        "program is the formal conformance suite.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security requirements (AES-128 MIC + encryption).
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = True
    f["anti_corruption_features"] = [
        "16-bit payload CRC on uplinks (PHY error detection).",
        "Header CRC in explicit-header mode.",
        "Coding-rate 4/5..4/8 forward error correction.",
    ]
    f["integrity_features"] = [
        "4-byte MIC (Message Integrity Code) = AES-128-CMAC over the frame "
        "keyed by the network session key (NwkSKey); detects tampering and "
        "corruption.",
        "Frame counter (FCnt) included in the MIC and checked to reject "
        "replays (must strictly increase).",
    ]
    f["confidentiality_features"] = [
        "Application payload (FRMPayload) encrypted with AES-128 in CTR mode "
        "using the application session key (AppSKey) — end-to-end between the "
        "device and the application server, opaque to the network operator.",
    ]
    f["authentication_features"] = [
        "OTAA join authenticates the device via the AppKey root secret and "
        "derives fresh NwkSKey + AppSKey per session.",
        "MIC authenticates every frame to the network server.",
    ]
    f["key_hierarchy"] = {
        "root_keys": ["AppKey (OTAA root, AES-128)"],
        "session_keys": ["NwkSKey (network session, MIC + MAC commands)",
                         "AppSKey (application session, payload encryption)"],
        "identifiers": ["DevEUI (64-bit)", "JoinEUI/AppEUI (64-bit)",
                        "DevAddr (32-bit)"],
        "derivation": "OTAA derives session keys at join from AppKey; ABP "
                      "pre-provisions DevAddr/NwkSKey/AppSKey.",
    }
    f["notes"] = (
        "LoRaWAN security is rooted in AES-128 symmetric cryptography: a "
        "4-byte MIC (AES-128-CMAC, NwkSKey) for per-frame integrity and "
        "authenticity, AES-128-CTR encryption of the application payload "
        "(AppSKey) for confidentiality, and the frame counter (FCnt) for "
        "replay protection. OTAA derives fresh session keys at join; ABP uses "
        "static pre-provisioned keys (weaker). Confidentiality is end-to-end "
        "between the device and the application server.")
    _write(p, d)
