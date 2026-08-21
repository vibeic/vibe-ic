"""Synthetic per-protocol fixture blobs for the protocol-detector no-misfire guards.

Self-contained, chip-AGNOSTIC, hand-written structural specs — NOT the real private
``benchmark_phase1/`` corpus. Each blob carries ONLY the public structural signature
of its own protocol (the conjunction its ``is_<stem>`` module-level detector keys on),
so the no-misfire matrix asserts each detector fires on EXACTLY its own benchmark and
on NO foreign one.

These let ``test_protocol_detector_no_misfire`` and
``test_protocol_detector_no_misfire_matrix`` actually RUN (instead of SKIP) without the
private corpus. Verified: against the full module-level detector set, each blob fires on
its own stem and zero foreign stems.

The fixture-builder (``build_synthetic_benchmark_phase1``) materializes a benchmark tree:

    <root>/<stem>/phase1/input_doc/spec.txt              (raw source spec)
    <root>/<stem>/phase1/generated_docs/L1_DATASHEET.json  (generated L-doc)
    <root>/<stem>/phase1/claude_extracted/L1_DATASHEET.json (the "gold")

which matches the on-disk shape both guards expect (input_doc + generated_docs for the
superset blob; claude_extracted L1-L3 for the gold blob).
"""
from __future__ import annotations

import json
from pathlib import Path

# stem -> structural spec text. Each is the smallest blob that satisfies its own
# detector's conjunction AND no other module-level detector. Keep additions in this
# same spirit: real public structural vocabulary only, no benchmark/filename keying.
SYNTHETIC_BLOBS: dict[str, str] = {
    "flexray": (
        "FlexRay Communication Controller Datasheet\n"
        "The FlexRay protocol uses a dual channel architecture: Channel A and Channel B.\n"
        "Each communication cycle is divided into a static segment and a dynamic segment.\n"
        "The static segment uses a TDMA scheme with fixed slots; the dynamic segment uses\n"
        "minislots (FTDMA). Timing is derived from the macrotick and microtick hierarchy.\n"
        "Protocol Operation Control (POC) reaches the NORMAL_ACTIVE state after startup.\n"
    ),
    "canopen": (
        "CANopen Application Layer (CiA 301) Specification\n"
        "The Object Dictionary is the central data structure, addressed by a 16-bit index\n"
        "and an 8-bit sub-index. Standardized entries include 0x1000 (device type) and\n"
        "0x1018 (identity object). Communication objects: PDO (Process Data Object, both\n"
        "TPDO and RPDO), SDO (Service Data Object) and NMT (Network Management).\n"
        "Each message carries a COB-ID derived from the Node-ID. The predefined connection\n"
        "set defines default COB-IDs. The node enters the pre-operational state on reset.\n"
        "Heartbeat and EMCY (emergency object) are supported. canopen / CAN in Automation.\n"
    ),
    "profibus": (
        "PROFIBUS-DP Specification (Process Field Bus, Decentralized Periphery)\n"
        "PROFIBUS uses a hybrid medium access: token passing between masters plus\n"
        "master-slave slave polling. Telegram start delimiters SD1, SD2, SD3, SD4 frame\n"
        "the telegrams. Service levels DPV0, DPV1, DPV2 are defined. The GSD general\n"
        "station description (device database, ident_number) describes each device.\n"
        "Service access points DSAP and SSAP address the data link. Runs over RS-485.\n"
    ),
    "spacewire": (
        "SpaceWire Link Interface Specification (ECSS-E-ST-50-12C)\n"
        "SpaceWire uses Data-Strobe (DS) encoding over LVDS, where the clock is the XOR of\n"
        "the Data and Strobe signals. Control characters include FCT (Flow Control Token),\n"
        "EOP (End of Packet) and EEP (Error End of Packet). The exchange-level link\n"
        "initialization state machine progresses ErrorReset -> ErrorWait -> Started ->\n"
        "Connecting -> Run. Credit-based flow control: each FCT grants 8 N-Char credits.\n"
    ),
    "lora": (
        "LoRaWAN Class A/B/C End-Device Specification\n"
        "The LoRa PHY uses Chirp Spread Spectrum (CSS) modulation with a spreading factor\n"
        "from SF7 to SF12, a 125 kHz bandwidth, and a configurable coding rate. LoRaWAN\n"
        "defines device classes Class A, Class B and Class C. Activation is by OTAA\n"
        "(over-the-air activation) or ABP. Join keys: DevEUI and AppKey. The network server\n"
        "and gateway serve the end-device. ADR (adaptive data rate). RX1 and RX2 windows.\n"
        "This is an LPWAN low-power wide-area technology with a strong link budget.\n"
    ),
    "sent": (
        "SENT (SAE J2716) Single Edge Nibble Transmission Sensor Interface\n"
        "SENT is a single signal wire, falling edge to falling edge, nibble pulse-width\n"
        "interface. Each nibble pulse period = 12 + value ticks (tick time / unit time\n"
        "3 us). Frames begin with a 56-tick synchronization/calibration pulse. A 4-bit\n"
        "CRC nibble (CRC-4) protects the data nibbles. This is a three-wire sensor\n"
        "interface (single signal line for data).\n"
    ),
    "jesd204": (
        "JESD204B/C Serial Interface for Data Converters\n"
        "This JESD204 link connects a data converter device (ADC and DAC) to a logic\n"
        "device. Link bring-up uses Code Group Synchronization (CGS) with K28.5, then\n"
        "Initial Lane Alignment (ILAS), aligned to the Local Multiframe Clock (LMFC) /\n"
        "multiframe boundary. Subclass 1 uses SYSREF for deterministic latency.\n"
        "Converter-frame parameters: octets per frame, samples per converter, and\n"
        "frames per multiframe (the L/M/F/S parameter set).\n"
    ),
    "profinet": (
        "PROFINET IO Specification\n"
        "Device roles: IO-Controller, IO-Device and IO-Supervisor. Each device is\n"
        "described by a GSDML XML file. The DCP (Discovery and Configuration Protocol)\n"
        "assigns names and addresses. The connection model uses an Application Relation\n"
        "(AR) containing an IO-CR, Alarm-CR and Record-Data-CR (Communication Relation).\n"
        "Cyclic data carries IOPS and IOCS provider/consumer status with an APDU Cycle\n"
        "Counter. The RT EtherType is 0x8892. Conformance Class CC-B is supported.\n"
    ),
}


def build_synthetic_benchmark_phase1(root: Path) -> Path:
    """Materialize a synthetic benchmark_phase1-shaped tree under ``root``.

    Returns ``root``. Idempotent: re-writing the same content is a no-op for the
    detectors. Each benchmark dir is named after its protocol stem so the guards'
    self-fire assertion (bench == stem) holds.
    """
    root = Path(root)
    for stem, blob in SYNTHETIC_BLOBS.items():
        p1 = root / stem / "phase1"
        idir = p1 / "input_doc"
        gdir = p1 / "generated_docs"
        xdir = p1 / "claude_extracted"
        for d in (idir, gdir, xdir):
            d.mkdir(parents=True, exist_ok=True)
        # Raw source spec (input_doc) — leads the superset blob.
        (idir / "spec.txt").write_text(blob, encoding="utf-8")
        # Generated + gold L-docs embed the SAME structural text so the detector
        # fires the same way on generated/superset and gold blobs.
        l1 = json.dumps({"ic_name": f"{stem.upper()} Reference", "spec_text": blob},
                        indent=2)
        l2 = json.dumps({"functional_requirements": blob}, indent=2)
        l3 = json.dumps({"command_protocol": blob}, indent=2)
        for docdir in (gdir, xdir):
            (docdir / "L1_DATASHEET.json").write_text(l1, encoding="utf-8")
            (docdir / "L2_FRS.json").write_text(l2, encoding="utf-8")
            (docdir / "L3_CMD_PROTOCOL.json").write_text(l3, encoding="utf-8")
    return root


if __name__ == "__main__":  # pragma: no cover - manual regen helper
    import sys
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "synthetic_benchmark_phase1")
    build_synthetic_benchmark_phase1(dest)
    print(f"wrote synthetic benchmark_phase1 tree -> {dest}")
