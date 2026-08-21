"""Dedicated Zigbee / IEEE 802.15.4 detector edge-case guard.

The universal ``test_protocol_detector_no_misfire`` auto-covers ``is_zigbee``
firing only on its own benchmark. This file adds the Zigbee-SPECIFIC edge
cases called out as HARD constraints when the class was added:

  * is_zigbee is CONTENT-ONLY and STRUCTURAL — a bare "Zigbee" or "802.15.4"
    name token in prose is NOT sufficient on its own.
  * is_zigbee fires on the canonical 802.15.4 + Zigbee structural signature
    (O-QPSK/DSSS + CSMA-CA + four MAC frame types + PAN ID + superframe/GTS +
    FFD/RFD + ZDO/APS/ZCL/mesh + AES-128-CCM*).
  * MUTEX: is_zigbee MUST NOT fire on a BLE-primary doc (GAP/GATT/advertising),
    an NFC-primary doc (ISO 14443 / PCD / PICC / 13.56 MHz), or a LoRa-primary
    doc (chirp spread spectrum / spreading factor / LoRaWAN).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zigbee_protocol_synth import is_zigbee


def test_empty_and_none_safe():
    assert is_zigbee("") is False
    assert is_zigbee(None) is False  # type: ignore[arg-type]


def test_does_not_fire_on_bare_name_token_in_prose():
    # A passing mention of the name with NO structural signature must not fire.
    assert is_zigbee("Our gateway also supports Zigbee in a future release.") \
        is False
    assert is_zigbee("Compare against an 802.15.4 radio for reference.") \
        is False


def test_fires_on_canonical_802154_zigbee_structure():
    blob = (
        "IEEE 802.15.4 LR-WPAN. The 2.4 GHz PHY uses O-QPSK over DSSS with a "
        "32-chip spreading sequence at a chip rate of 2.0 Mchip/s on 16 "
        "channels (channel 11-26), 250 kbps. The MAC uses CSMA-CA channel "
        "access and defines four frame types: beacon, data, acknowledgement, "
        "and MAC command. Devices carry a 16-bit PAN ID with a 16-bit short "
        "address and a 64-bit extended EUI-64 address. A beacon-enabled "
        "superframe provides a CAP and a CFP with Guaranteed Time Slots (GTS). "
        "Device types are FFD and RFD. The Zigbee NWK layer provides mesh "
        "routing; ZDO and APS sit above it with ZCL clusters; roles are "
        "Coordinator, Router, and End Device. Security is AES-128 in CCM* mode "
        "with a network key, a link key, and a Trust Center."
    )
    assert is_zigbee(blob) is True


def test_fires_via_phy_plus_mac_score_without_full_zigbee():
    # 802.15.4 PHY + strong MAC structure alone (no Zigbee app layer) fires.
    blob = (
        "2.4 GHz O-QPSK DSSS spread spectrum PHY. CSMA-CA channel access. MAC "
        "frame types include the beacon, data, acknowledgement and MAC command "
        "frames. The superframe carries GTS Guaranteed Time Slots in the CFP. "
        "PAN ID plus 64-bit extended address and short address. FFD and RFD "
        "device types."
    )
    assert is_zigbee(blob) is True


def test_mutex_does_not_fire_on_ble_primary():
    blob = (
        "Bluetooth Low Energy (BLE). The Generic Access Profile (GAP) and "
        "Generic Attribute Profile (GATT) sit above the Attribute Protocol "
        "(ATT). Advertising and scanning precede a connection; the connection "
        "interval and 40 channels (3 advertising) are used in the 2.4 GHz "
        "band. Beacon advertising packets carry a data payload."
    )
    assert is_zigbee(blob) is False


def test_mutex_does_not_fire_on_nfc_primary():
    blob = (
        "ISO/IEC 14443 contactless smart card at 13.56 MHz. The PCD (reader) "
        "polls the PICC (card) with REQA; the PICC answers with ATQA and a "
        "SAK after anticollision. MIFARE Classic UID handling. No PAN ID, no "
        "superframe."
    )
    assert is_zigbee(blob) is False


def test_mutex_does_not_fire_on_lora_primary():
    blob = (
        "LoRa / LoRaWAN sub-GHz long-range radio. The PHY uses Chirp Spread "
        "Spectrum (CSS) with a configurable spreading factor (SF7-SF12) and "
        "bandwidth. A chirp sweeps across the band. No O-QPSK, no superframe, "
        "no PAN ID, no ZDO or ZCL."
    )
    assert is_zigbee(blob) is False


def test_module_exports_apply_and_detector():
    import zigbee_protocol_synth as z
    assert callable(z.is_zigbee)
    assert callable(z.apply_zigbee_synth)


def test_self_fires_on_real_spec_doc():
    spec = (Path(__file__).resolve().parents[4]
            / "benchmark-data" / "evaluation" / "phase1_parity" / "zigbee" / "input" / "docs"
            / "zigbee_spec.txt")
    if spec.is_file():
        assert is_zigbee(spec.read_text(encoding="utf-8", errors="ignore")) \
            is True
