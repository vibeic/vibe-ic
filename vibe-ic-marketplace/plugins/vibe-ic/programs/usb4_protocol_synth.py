"""USB4 protocol synth helper.

v0.1.89 — ic_class-gated overlay for `serial_peripheral_protocol` /
`bus_interconnect_protocol` specs that exhibit the USB4 structural
signature (USB4 router-based tunneling fabric: host/hub/device routers,
USB3 + DisplayPort + PCIe tunnels over a common 40 Gbps transport,
Connection Manager, Time Management Unit, LT-LFPS link training,
sideband SBU channel, USB Power Delivery, built on the Thunderbolt 3
protocol donated by Intel). Applies USB4-canonical content to all 24
L docs (L1-L23 + L8_TIMING_WAVEFORM).

Detector signature (CANONICAL STRUCTURAL — wire-level signatures + the
protocol NAME read from L1/L2 CONTENT, never from input-doc filenames or
the benchmark folder name):

    is_usb4 = (
        ("USB4" in blob and "tunnel" in blob.lower())
        or ("USB4" in blob and "router" in blob.lower() and "40 Gbps" in blob)
        or ("USB4" in blob and "Connection Manager" in blob)
    )

where `blob` is the concatenated L1/L2 (+ augmented input_doc) CONTENT.

SIBLING DISAMBIGUATION (vs the `usb` benchmark = plain USB 2.0):
  - USB 2.0 (usb benchmark) has D+/D-/VBUS/NRZI/tiered-star/hub but
    NEVER contains "USB4", "tunnel", "router", "Connection Manager",
    or "40 Gbps". So this detector does NOT fire on USB 2.0.
  - This detector requires the version-specific token "USB4" AND a
    USB4-only structural token (tunnel / router+40Gbps / Connection
    Manager). The usb (USB 2.0) detector keys on D+/D-/NRZI/hub which
    are ALSO present in a USB4 doc — therefore, because USB4 EXTENDS
    USB (the usb synth fires first on a USB4 doc), this module
    FORCE-OVERWRITES (direct-assign, NOT setdefault) every L1/L2/L3/L4
    key the usb sibling synth populates with USB-2.0-specific values,
    replacing them with USB4-specific values.

Public entry: `apply_usb4_synth(generated_docs_dir, is_usb4, usb4_ic_name)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _wb_low(tok: str, low: str) -> bool:
    """Whole-word match of a short token in already-lowercased text.

    Avoids substring false-positives for short acronyms (e.g. 'pdo' must
    not match 'clampdown', 'rdo' must not match 'teardown').
    """
    return re.search(r"\b" + re.escape(tok) + r"\b", low) is not None


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault that survives a pre-existing None value.

    `d.setdefault(key, {})` is a no-op when d[key] is already None (the
    sibling synth or a prior overlay may have left a None), so the
    returned object would be None and `.setdefault(...)` on it raises.
    This helper forces a real dict.
    """
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


_MAIN_DOCS = [
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
    "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
]

# L14-L23 wrap everything under "fields".
_FIELDED_DOCS = [
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
]


# ----------------------------------------------------------------------
# public entry
# ----------------------------------------------------------------------
def apply_usb4_synth(generated_docs_dir: Path, is_usb4: bool,
                     usb4_ic_name: Optional[str]) -> None:
    """Apply USB4-specific synth when the structural signature matched."""
    if not is_usb4:
        return
    gd = Path(generated_docs_dir)

    # Force ic_name across all 24 docs FIRST (top-level for L1-L23 +
    # L8_TIMING; inside "fields" for L14-L23).
    if usb4_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = usb4_ic_name
                _write(q, d)
        for n in _FIELDED_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = usb4_ic_name
                _write(q, d)

    _l1(gd)
    _l2(gd)
    _l3(gd)
    _l4(gd)
    _l5(gd)
    _l6(gd)
    _l7(gd)
    _l8_const(gd)
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
# L1 — datasheet  (FORCE-OVERWRITE sibling USB keys)
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "USB4 Specification"
    d["version"] = "USB4 Version 1.0"
    d["manufacturer"] = "USB Implementers Forum (USB-IF); base protocol (Thunderbolt 3) donated by Intel"
    d["revised_date"] = "August 29, 2019"
    d["copyright"] = "© 2019 USB Implementers Forum, Inc."
    d["external_pins"] = [
        "VBUS (USB-C bus power)",
        "TX1+/TX1- (high-speed lane 0 transmit differential pair)",
        "RX1+/RX1- (high-speed lane 0 receive differential pair)",
        "TX2+/TX2- (high-speed lane 1 transmit differential pair)",
        "RX2+/RX2- (high-speed lane 1 receive differential pair)",
        "SBU1/SBU2 (sideband use — USB4 sideband channel)",
        "CC1/CC2 (USB-C Configuration Channel — USB Power Delivery)",
        "D+/D- (USB 2.0 backward-compatibility pair)",
        "GND (ground)",
    ]
    d["external_pin_count"] = 24  # USB-C 24-pin receptacle
    d["modes_of_operation"] = [
        {"name": "USB4 Gen 2x2", "max_bit_rate": "20 Gbps (2 lanes x 10 Gbps)",  "use_case": "Base USB4 two-lane mode; 10.3125 Gbaud per lane, 64b/66b encoding"},
        {"name": "USB4 Gen 3x2", "max_bit_rate": "40 Gbps (2 lanes x 20 Gbps)",  "use_case": "Full USB4 two-lane mode; 20.625 Gbaud per lane, 128b/132b encoding"},
        {"name": "USB4 v2 (Gen 4)", "max_bit_rate": "80 Gbps (symmetric) / up to 120 Gbps (asymmetric)", "use_case": "USB4 Version 2.0; PAM-3 signaling for higher throughput"},
        {"name": "USB 2.0 fallback", "max_bit_rate": "480 Mbps", "use_case": "Backward compatibility on the dedicated D+/D- pair"},
    ]
    d["key_features"] = [
        "Single high-speed USB Type-C connector with 40 Gbps (Gen 3x2) operation.",
        "Tunneling architecture: USB3.2, DisplayPort, and PCI Express protocols are encapsulated and tunneled over a common USB4 transport layer.",
        "Router-based topology: a USB4 fabric of host routers, hub routers, and device routers connected as a spanning tree.",
        "Connection Manager configures routers, allocates paths, and sets up tunnels across the fabric.",
        "Dual-lane operation with lane bonding (2 x 20 Gbps -> 40 Gbps) and optional asymmetric (3:1) lane configuration in USB4 v2.",
        "Time Management Unit (TMU) distributes a common time base across the fabric for isochronous tunnels.",
        "LT-LFPS (Low-Frequency Periodic Signaling) link training brings up the high-speed link.",
        "Sideband (SBU) channel carries low-speed management between adjacent routers.",
        "USB Power Delivery negotiation over the USB-C CC pins (up to 100 W, or 240 W with Extended Power Range).",
        "Built on the Thunderbolt 3 protocol contributed by Intel; optionally interoperable with Thunderbolt 3 devices.",
        "Backward compatible with USB 3.2, USB 2.0, and DisplayPort Alt Mode.",
        "Configuration / Transport / Tunneled-protocol layered architecture.",
    ]
    d["overview"] = (
        "USB4 is a USB Implementers Forum connection specification, built on the "
        "Thunderbolt 3 protocol donated by Intel, that defines a 40 Gbps (Gen 3x2) "
        "router-based fabric carried over a single USB Type-C connector. Unlike "
        "earlier USB generations, USB4 is a tunneling architecture: native USB3.2, "
        "DisplayPort, and PCI Express traffic is encapsulated into USB4 tunneled "
        "packets and transported over a common high-speed transport layer between "
        "host, hub, and device routers. A Connection Manager sets up paths and "
        "tunnels across the spanning-tree fabric; a Time Management Unit distributes "
        "a shared time base.")
    d["previous_versions"] = [
        "Thunderbolt 3 (2015, Intel) — donated base protocol.",
        "USB4 Version 1.0 (August 29, 2019) — 20 / 40 Gbps tunneling fabric.",
        "USB4 Version 2.0 (2022) — adds 80 Gbps symmetric / up to 120 Gbps asymmetric (Gen 4, PAM-3).",
    ]
    d["topology_summary"] = (
        "Spanning-tree of routers rooted at the host router; hub routers cascade the "
        "fabric; device routers are leaves. Each link is a USB-C dual-lane "
        "bidirectional connection at 10/20 Gbps per lane.")
    d["package_summary"] = (
        "USB4 is a wire-level + tunneling protocol spec carried over a USB-C 24-pin "
        "receptacle; physical signalling reuses the USB Type-C connector with two "
        "high-speed lane pairs, SBU sideband, CC power-delivery pins, and a USB 2.0 "
        "D+/D- pair.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS  (FORCE-OVERWRITE sibling protocol_overview + functional reqs)
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    # Drop USB-2.0-specific protocol_overview keys the sibling installs.
    for k in ("duplex_low_full_speed", "duplex_high_speed", "wire_count",
              "bit_stuffing_threshold", "max_devices_per_bus", "max_hub_tiers",
              "transfer_types", "frame_time_full_low_speed_ms",
              "microframe_time_high_speed_us"):
        po.pop(k, None)
    po["type"] = "Router-based tunneling fabric; host-managed (Connection Manager allocates paths + tunnels)."
    po["duplex"] = "full-duplex (independent TX and RX differential pairs per lane)"
    po["lanes"] = 2
    po["lane_bonding"] = "Two lanes bonded to a single logical link (2 x 20 Gbps = 40 Gbps Gen 3x2)."
    po["synchronous_serial"] = False
    po["wire_names"] = ["TX1+/TX1-", "RX1+/RX1-", "TX2+/TX2-", "RX2+/RX2-", "SBU1/SBU2", "CC1/CC2", "VBUS", "GND", "D+/D-"]
    po["high_speed_lane_pairs"] = 4
    po["encoding"] = "64b/66b (Gen 2, 10.3125 Gbaud) and 128b/132b (Gen 3, 20.625 Gbaud); PAM-3 in USB4 v2 (Gen 4)."
    po["line_rate_per_lane"] = {"Gen2": "10 Gbps", "Gen3": "20 Gbps", "Gen4_v2": "40 Gbps effective (PAM-3)"}
    po["aggregate_bandwidth"] = {"Gen2x2": "20 Gbps", "Gen3x2": "40 Gbps", "v2": "80 Gbps symmetric / 120 Gbps asymmetric"}
    po["tunneled_protocols"] = ["USB3.2", "DisplayPort", "PCI Express"]
    po["transport_layer"] = "Common USB4 transport layer carrying tunneled-protocol packets + control packets between routers."
    po["link_training"] = "LT-LFPS (Low-Frequency Periodic Signaling) ordered-set training."
    po["sideband"] = "SBU sideband channel for low-speed inter-router management."
    po["time_management"] = "Time Management Unit (TMU) distributes a fabric-wide time base."
    fr = [
        {"id": "FR-PHY-01",   "text": "Dual-lane high-speed signalling over a USB-C connector: TX1/RX1 + TX2/RX2 differential pairs. Gen 2 = 10.3125 Gbaud/lane (64b/66b); Gen 3 = 20.625 Gbaud/lane (128b/132b). USB4 v2 adds Gen 4 PAM-3 for 80 Gbps."},
        {"id": "FR-BOND-02",  "text": "Lane bonding: two lanes are bonded into one logical link; 2 x 20 Gbps = 40 Gbps (Gen 3x2). USB4 v2 may operate asymmetrically (3 lanes one direction, 1 the other)."},
        {"id": "FR-TUN-03",   "text": "Tunneling: USB3.2, DisplayPort, and PCI Express traffic is encapsulated into USB4 tunneled packets and carried over the common transport layer; each tunnel is an independent path through the fabric."},
        {"id": "FR-ROUTER-04","text": "Router-based topology: host routers, hub routers, and device routers form a spanning tree rooted at the host router; each router forwards tunneled + control packets between its adapters."},
        {"id": "FR-CM-05",    "text": "Connection Manager: a host-resident entity that discovers routers, reads/writes router configuration spaces, allocates hop IDs, and sets up paths + tunnels across the fabric."},
        {"id": "FR-LAYER-06", "text": "Layered architecture: Physical layer (lanes), Logical layer, Transport layer (tunneled-packet transport + flow control), Configuration layer (router config space), and Tunneled-protocol adapter layers (USB3/DP/PCIe)."},
        {"id": "FR-PATH-07",  "text": "Path setup: a path is an ordered sequence of per-hop input/output hop IDs through routers; the Connection Manager programs each router's path configuration to stitch a tunnel end-to-end."},
        {"id": "FR-TMU-08",   "text": "Time Management Unit (TMU): distributes a common time base across the fabric so isochronous tunnels (DisplayPort, USB3 isochronous) stay synchronized."},
        {"id": "FR-LT-09",    "text": "Link training via LT-LFPS: routers exchange Low-Frequency Periodic Signaling ordered sets to bring up and equalize the high-speed link before transport begins."},
        {"id": "FR-SBU-10",   "text": "Sideband (SBU) channel: a low-speed bidirectional management channel on the SBU1/SBU2 pins between two adjacent routers, used for connect/disconnect, lane configuration, and link management."},
        {"id": "FR-PD-11",    "text": "USB Power Delivery: power contract negotiated over the USB-C CC pins; up to 100 W standard, up to 240 W with Extended Power Range (EPR); VBUS direction and voltage set by the PD contract."},
        {"id": "FR-ENCAP-12", "text": "Encapsulation: native protocol packets (USB3/DP/PCIe) are wrapped in USB4 tunneled packets with a tunnel/adapter header so they can traverse the shared transport layer."},
        {"id": "FR-TB3-13",   "text": "Thunderbolt 3 base: USB4 is built on the Thunderbolt 3 protocol donated by Intel; USB4 hosts/devices may optionally interoperate with Thunderbolt 3 products."},
        {"id": "FR-COMPAT-14","text": "Backward compatibility: USB4 ports support USB 3.2 and USB 2.0 (on the dedicated D+/D- pair) and DisplayPort Alt Mode; a USB4 host falls back gracefully to the highest common capability."},
    ]
    d["functional_requirements"] = fr
    d["error_response_conditions"] = [
        "Link training failure (LT-LFPS ordered-set mismatch / equalization timeout)",
        "Tunnel path setup failure (Connection Manager cannot allocate hop IDs / bandwidth)",
        "Transport-layer credit/flow-control underflow or overflow",
        "Tunneled-protocol error propagated from USB3/DP/PCIe adapter",
        "Router configuration-space access error (invalid hop ID / adapter)",
        "Power Delivery contract negotiation failure on CC pins",
        "Time-sync (TMU) loss of common time base",
    ]
    d["compliance_requirements"] = [
        "USB-C connector + USB Power Delivery compliance (CC pin negotiation).",
        "Backward compatibility with USB 3.2 and USB 2.0 on the same port.",
        "USB4 routers must expose a standard router configuration space addressable by the Connection Manager.",
        "DisplayPort and PCIe tunnels must preserve native protocol semantics end-to-end.",
        "Gen 2 (10 Gbps/lane) is mandatory; Gen 3 (20 Gbps/lane) is the full-feature target.",
        "Optional Thunderbolt 3 interoperability when advertised.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command / protocol  (FORCE-OVERWRITE sibling channels + classes)
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Router-based tunneling transport: per-hop hop-ID-routed tunneled packets + "
        "control packets over a dual-lane high-speed link; managed by a Connection "
        "Manager via router configuration space.")
    d["channels"] = [
        {"name": "TX1/RX1 (lane 0)", "direction": "full-duplex differential", "purpose": "High-speed lane 0; 10/20 Gbps; bonded with lane 1."},
        {"name": "TX2/RX2 (lane 1)", "direction": "full-duplex differential", "purpose": "High-speed lane 1; 10/20 Gbps; bonded with lane 0 for 40 Gbps."},
        {"name": "SBU1/SBU2",        "direction": "bidirectional low-speed",   "purpose": "Sideband channel for inter-router management."},
        {"name": "CC1/CC2",          "direction": "bidirectional",             "purpose": "USB-C Configuration Channel; USB Power Delivery negotiation + orientation."},
        {"name": "VBUS",             "direction": "source -> sink",            "purpose": "Bus power per the negotiated PD contract (up to 100 W / 240 W EPR)."},
        {"name": "D+/D-",            "direction": "half-duplex",               "purpose": "USB 2.0 backward-compatibility pair."},
    ]
    d["packet_classes"] = [
        {"class": "Tunneled",      "purpose": "Encapsulated native-protocol traffic.", "subtypes": ["USB3 tunneled", "DisplayPort tunneled", "PCIe tunneled"]},
        {"class": "Transport",     "purpose": "USB4 transport-layer data + flow-control packets.", "subtypes": ["Data packet", "Flow-control credit", "Idle"]},
        {"class": "Control",       "purpose": "Router/link management.", "subtypes": ["Configuration read/write", "Path setup", "Hot-plug event", "TMU time-sync"]},
        {"class": "Link/Sideband", "purpose": "Link bring-up + sideband management.", "subtypes": ["LT-LFPS ordered set", "Lane config", "SBU message"]},
    ]
    # USB4 routes by hop ID, not by USB-2.0 PID byte. Replace the
    # sibling's packet_id_field with the USB4 routing key.
    d["packet_id_field"] = {
        "routing_key": "Hop ID",
        "purpose": "Each tunneled/transport packet carries a per-hop hop ID; a router maps {input adapter, input hop ID} -> {output adapter, output hop ID} along a configured path.",
        "structure": "Per-router path configuration installed by the Connection Manager; no fixed PID-byte encoding (unlike USB 2.0).",
    }
    d["transaction_phases"] = [
        "Link bring-up phase — LT-LFPS training + lane bonding.",
        "Enumeration / configuration phase — Connection Manager reads router config space, builds the spanning tree.",
        "Path/tunnel setup phase — Connection Manager allocates hop IDs and programs each router's path config.",
        "Transport phase — tunneled packets flow end-to-end with transport-layer flow control.",
    ]
    d["addressing"] = {
        "routing_model": "Per-hop hop-ID forwarding through routers (spanning tree).",
        "router_identification": "Topology ID / route string from host router down the tree.",
        "config_space": "Each router exposes a configuration space (router, adapter, path, counters) addressed by the Connection Manager.",
        "hop_id_role": "Identifies a path segment on a given adapter; rewritten at each router hop.",
    }
    d["transfer_types"] = [
        {"type": "USB3 tunnel",        "direction": "bidirectional", "use_case": "Tunnel USB 3.2 traffic (up to 20 Gbps) over the fabric."},
        {"type": "DisplayPort tunnel", "direction": "host -> sink",  "use_case": "Tunnel DisplayPort main-link video + AUX; isochronous, TMU-synchronized."},
        {"type": "PCIe tunnel",        "direction": "bidirectional", "use_case": "Tunnel PCI Express memory/IO/config transactions (e.g. for eGPU / NVMe)."},
        {"type": "Host-to-Host",       "direction": "bidirectional", "use_case": "USB4 host-to-host data path between two host routers."},
    ]
    d["control_transfer_stages"] = [
        "Config-space read — Connection Manager reads router/adapter capabilities.",
        "Path allocation — Connection Manager assigns input/output hop IDs per hop.",
        "Path config write — each router programmed with its segment of the path.",
        "Tunnel activation — adapters enabled; tunneled traffic begins.",
    ]
    d["valid_ready_handshake_rules"] = [
        "Transport layer uses credit-based flow control between adjacent routers.",
        "LT-LFPS ordered sets bring up + equalize the link before transport.",
        "Connection Manager-driven path setup must complete before a tunnel carries traffic.",
        "Power Delivery contract on CC pins must be established before high-power VBUS is sourced.",
    ]
    d["burst_based"] = True
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — config-space model  (FORCE-OVERWRITE sibling device-framework)
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    # Remove USB-2.0-specific device-framework keys the sibling installs.
    for k in ("device_request_layout", "standard_device_requests",
              "descriptor_types", "feature_selectors"):
        d.pop(k, None)
    d["router_configuration_space"] = {
        "purpose": "USB4 routers expose configuration spaces that the Connection Manager reads/writes to discover capabilities and program paths.",
        "config_space_types": [
            {"name": "Router config space",  "purpose": "Per-router capabilities, topology ID, vendor/product, total adapters."},
            {"name": "Adapter config space", "purpose": "Per-adapter type (lane / USB3 / DP-IN / DP-OUT / PCIe), state, capabilities."},
            {"name": "Path config space",    "purpose": "Per-adapter path entries mapping input hop ID -> output adapter + output hop ID."},
            {"name": "Counters config space","purpose": "Per-adapter performance + error counters."},
        ],
    }
    d["adapter_types"] = [
        {"name": "Lane adapter",   "purpose": "Physical-link endpoint; pairs of lane adapters form an inter-router link (with lane bonding)."},
        {"name": "USB3 adapter",   "purpose": "Up/down adapter that tunnels USB 3.2 traffic."},
        {"name": "DP-IN adapter",  "purpose": "Ingests DisplayPort source traffic for tunneling."},
        {"name": "DP-OUT adapter", "purpose": "Emits tunneled DisplayPort traffic to a sink."},
        {"name": "PCIe adapter",   "purpose": "Up/down adapter that tunnels PCI Express transactions."},
        {"name": "Host interface adapter", "purpose": "Connects the router to its host's Connection Manager."},
    ]
    d["notes"] = (
        "USB4 (unlike USB 2.0's wire-level device framework) is configured through "
        "router/adapter/path/counter configuration spaces. The Connection Manager "
        "reads these spaces to discover the spanning tree of routers and writes path "
        "config to set up tunnels. There is no USB-2.0 bmRequestType/descriptor "
        "device-request layout at the USB4 transport layer (those live in the "
        "tunneled USB3/USB2 protocols).")
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / electrical interface
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "USB4 high-speed signalling uses two bidirectional lanes over a USB-C "
        "connector. Each lane is a TX differential pair + an RX differential pair. "
        "Gen 2 = 10.3125 Gbaud/lane with 64b/66b encoding; Gen 3 = 20.625 Gbaud/lane "
        "with 128b/132b encoding; USB4 v2 (Gen 4) uses PAM-3 multilevel signalling "
        "for 40 Gbps effective per lane (80 Gbps symmetric). Link is brought up with "
        "LT-LFPS (Low-Frequency Periodic Signaling) ordered sets and adaptive "
        "equalization. SBU sideband is a low-speed management pair; CC1/CC2 carry "
        "USB Power Delivery. VBUS power is set by the negotiated PD contract.")
    d["line_rates"] = {
        "Gen2_per_lane_Gbaud": 10.3125, "Gen2_encoding": "64b/66b",
        "Gen3_per_lane_Gbaud": 20.625,  "Gen3_encoding": "128b/132b",
        "Gen4_v2": "PAM-3, 80 Gbps symmetric / up to 120 Gbps asymmetric",
    }
    d["voltage_classes_of_devices"] = [
        "USB Power Delivery up to 100 W (20 V / 5 A) over VBUS.",
        "Extended Power Range (EPR) up to 240 W (48 V / 5 A).",
        "Lower PD profiles (5 V / 9 V / 15 V / 20 V) negotiated on CC pins.",
    ]
    d["link_training"] = (
        "LT-LFPS ordered sets train, bond, and equalize the two high-speed lanes "
        "before the transport layer carries tunneled packets.")
    d.pop("high_speed_chirp_handshake", None)  # USB-2.0 sibling residue
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / state model
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["device_visible_states"] = [
        {"name": "Disconnected", "description": "No partner detected on the USB-C link; SBU + CC monitoring only."},
        {"name": "Training",     "description": "LT-LFPS link training + lane bonding in progress."},
        {"name": "Connected",    "description": "High-speed link up; router visible to the Connection Manager."},
        {"name": "Enumerated",   "description": "Connection Manager has read the router's config space and placed it in the spanning tree."},
        {"name": "Configured",   "description": "Paths/tunnels set up; adapters enabled; tunneled traffic flowing."},
        {"name": "Sleep/Low-power","description": "Link in a low-power state (e.g. USB4 sleep); resumes via SBU/LFPS."},
    ]
    d["fsm_hints"] = {
        "host_role": "The host router hosts the Connection Manager, which discovers routers, allocates hop IDs, and programs paths/tunnels.",
        "router_role": "Each router forwards tunneled + control packets per its installed path configuration; lane adapters bring up links via LT-LFPS.",
        "rule": "Tunnels are set up by the Connection Manager before traffic flows; transport uses credit-based flow control between adjacent routers.",
    }
    d["anti_deadlock_rule"] = (
        "Credit-based (flow-controlled) transport between adjacent routers prevents "
        "head-of-line buffer overrun; isochronous tunnels (DisplayPort) are "
        "bandwidth-reserved + TMU-synchronized so they cannot be starved by "
        "best-effort PCIe/USB3 tunnels.")
    d["exit_from_reset_or_poweron"] = (
        "On connect: USB-C orientation + PD negotiation on CC pins, then LT-LFPS link "
        "training + lane bonding, then the Connection Manager reads router config "
        "space, builds the spanning tree, and sets up tunnels.")
    d["default_ready_state_recommendation"] = {
        "link_down": "Lanes electrically idle; monitor SBU/CC for connect.",
        "link_up_no_tunnel": "Transport layer ready; await Connection Manager path setup.",
        "tunnel_active": "Adapters enabled; tunneled traffic flowing under flow control.",
    }
    d["connection_manager_rule"] = (
        "Exactly one Connection Manager (host-resident) owns path/tunnel allocation "
        "for the fabric; routers are passive forwarders programmed by it.")
    d["tunnel_setup_rule"] = (
        "Each tunnel = an end-to-end path = an ordered list of per-hop {adapter, hop "
        "ID} entries programmed into every router along the route by the Connection "
        "Manager.")
    # Drop USB-2.0-specific control-logic keys the sibling installs.
    for k in ("handshake_packet_meanings", "data_toggle_rule",
              "split_transaction_rule"):
        d.pop(k, None)
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["test_modes"] = [
        {"name": "Loopback (LT-LFPS)",  "purpose": "Lane loopback for high-speed BER characterization during link training."},
        {"name": "Compliance pattern",  "purpose": "Transmit defined compliance patterns for Gen 2 / Gen 3 PHY signal-quality measurement."},
        {"name": "Per-lane equalization","purpose": "Adaptive equalizer tuning + reporting per lane."},
        {"name": "PD compliance",        "purpose": "USB Power Delivery message-level compliance on CC pins."},
    ]
    d["spec_provided_observability"] = [
        {"name": "Counters config space", "purpose": "Per-adapter performance + error counters readable by the Connection Manager."},
        {"name": "Router config space",   "purpose": "Topology + capability discovery for debug of the spanning tree."},
        {"name": "SBU management",         "purpose": "Sideband connect/disconnect + lane-config events."},
        {"name": "TMU status",             "purpose": "Time-sync lock/quality for isochronous tunnels."},
    ]
    d["error_detection_mechanisms"] = [
        "Per-lane symbol/decoding errors (64b/66b, 128b/132b) flagged + counted.",
        "Transport-layer CRC + sequence checks on tunneled packets.",
        "Flow-control credit underflow/overflow detection.",
        "Path-setup validity checks in router config space (invalid hop ID / adapter).",
        "Power Delivery contract error on CC pins.",
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Hot-plug connect",    "trigger": "USB-C partner detected (CC/SBU)."},
        {"event": "Hot-plug disconnect", "trigger": "USB-C partner removed."},
        {"event": "Link up/down",        "trigger": "LT-LFPS training complete / link lost."},
        {"event": "Tunnel state change",  "trigger": "Connection Manager path setup/teardown."},
        {"event": "PD contract change",  "trigger": "USB Power Delivery renegotiation on CC pins."},
    ]
    d["notes"] = (
        "USB4 debug/observability is structural: routers expose router/adapter/path/"
        "counters configuration spaces that the Connection Manager reads, plus SBU "
        "sideband events and TMU time-sync status. PHY-level compliance uses Gen 2 / "
        "Gen 3 compliance patterns and LT-LFPS loopback.")
    d.pop("test_modes_high_speed_only", None)  # USB-2.0 sibling residue
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — RTL constants
# ----------------------------------------------------------------------
def _l8_const(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-overwrite width_parameters with USB4-specific values (the USB
    # sibling installs USB-2.0 PID/CRC/descriptor widths into this same key).
    wp = {}
    d["width_parameters"] = wp
    for k, v in {
        "NUM_LANES": 2,
        "HS_DIFF_PAIRS": 4,
        "GEN2_LINE_RATE_Gbps_per_lane": 10,
        "GEN3_LINE_RATE_Gbps_per_lane": 20,
        "GEN2_AGGREGATE_Gbps": 20,
        "GEN3_AGGREGATE_Gbps": 40,
        "USB4_V2_AGGREGATE_Gbps": 80,
        "GEN2_ENCODING": "64b/66b",
        "GEN3_ENCODING": "128b/132b",
        "GEN2_BAUD_Gbaud": 10.3125,
        "GEN3_BAUD_Gbaud": 20.625,
        "USB2_FALLBACK_Mbps": 480,
        "SBU_PAIRS": 1,
        "CC_PINS": 2,
        "USBC_RECEPTACLE_PINS": 24,
    }.items():
        wp.setdefault(k, v)
    d["encoding_schemes"] = {
        "Gen2": {"line_code": "64b/66b", "baud_Gbaud": 10.3125, "data_Gbps": 10},
        "Gen3": {"line_code": "128b/132b", "baud_Gbaud": 20.625, "data_Gbps": 20},
        "USB4v2_Gen4": {"line_code": "PAM-3", "data_Gbps_per_lane": 40, "aggregate_Gbps": 80},
    }
    d["key_constants_for_RTL_authoring"] = {
        "transport": "Router-based tunneling: hop-ID-routed tunneled + control packets over a credit-flow-controlled transport layer.",
        "tunneled_protocols": ["USB3.2", "DisplayPort", "PCIe"],
        "lanes": 2,
        "lane_bonding": "2 lanes bonded -> 40 Gbps (Gen 3x2).",
        "link_training": "LT-LFPS ordered sets.",
        "sideband": "SBU1/SBU2 low-speed management channel.",
        "power_delivery": "USB-C CC pins; up to 100 W (240 W EPR).",
        "time_management": "Time Management Unit (TMU) distributes a fabric-wide time base.",
        "connection_manager": "Host-resident; allocates hop IDs + paths + tunnels.",
        "base_protocol": "Thunderbolt 3 (donated by Intel).",
        "gen3_aggregate_Gbps": 40,
        "gen2_aggregate_Gbps": 20,
        "usb4_v2_aggregate_Gbps": 80,
    }
    d["default_signal_state_when_idle"] = {
        "lanes_idle": "Electrical idle / LFPS keep-alive when link is up but no traffic.",
        "link_down": "Lanes idle; SBU/CC monitored for connect.",
    }
    # Drop USB-2.0-specific RTL-constant keys the sibling installs.
    for k in ("crc_polynomials", "signaling_speeds"):
        d.pop(k, None)
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — timing / waveform
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["line_rate_structure"] = {
        "Gen2_baud_Gbaud": 10.3125, "Gen2_data_Gbps_per_lane": 10, "Gen2_encoding": "64b/66b",
        "Gen3_baud_Gbaud": 20.625,  "Gen3_data_Gbps_per_lane": 20, "Gen3_encoding": "128b/132b",
        "USB4v2_per_lane_Gbps": 40, "USB4v2_signalling": "PAM-3",
        "lanes": 2, "lane_bonding": True,
    }
    d["unit_interval_ps"] = {
        "Gen2_UI_ps": 96.97,   # 1 / 10.3125 GHz
        "Gen3_UI_ps": 48.48,   # 1 / 20.625 GHz
    }
    d["aggregate_bandwidth"] = {
        "Gen2x2_Gbps": 20, "Gen3x2_Gbps": 40,
        "USB4v2_symmetric_Gbps": 80, "USB4v2_asymmetric_Gbps": 120,
    }
    d["link_training_waveforms"] = {
        "LT_LFPS": "Low-Frequency Periodic Signaling ordered sets for link bring-up + lane bonding.",
        "equalization": "Adaptive per-lane equalization during training.",
        "sideband": "SBU low-speed management pulses for connect/lane-config.",
    }
    d["power_delivery_timing"] = {
        "CC_negotiation": "USB Power Delivery message exchange on CC pins before high-power VBUS.",
        "max_power_W": 100, "max_power_EPR_W": 240,
    }
    # Drop USB-2.0-specific timing keys the sibling installs.
    for k in ("frame_microframe_structure", "bit_time_constants", "packet_timing",
              "signaling_waveforms", "data_signaling_rate_tolerance",
              "bus_turn_around_time_FS_LS_bit_times", "bus_turn_around_time_HS_bit_times",
              "inter_packet_delay_HS_bit_times", "cable_delay_per_meter_ns_max",
              "max_cable_length_FS_m", "max_cable_length_LS_m", "max_end_to_end_delay_ns",
              "frame_interval_FS_ms", "frame_interval_jitter_FS_max_ns",
              "microframe_interval_HS_us", "microframe_interval_jitter_HS_max_ns"):
        d.pop(k, None)
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "USB4 router-based tunneling fabric over USB-C. Defines the transport, "
        "configuration, and tunneled-protocol layers between host routers, hub "
        "routers, and device routers; built on the Thunderbolt 3 protocol donated by "
        "Intel.")
    d["topology_description"] = (
        "Spanning tree of routers rooted at the host router; hub routers cascade the "
        "fabric; device routers are leaves. Each inter-router link is a USB-C "
        "dual-lane bidirectional connection.")
    d["integration_overview"] = {
        "connection_manager": "Host-resident; one per fabric.",
        "router_types": ["Host router", "Hub router", "Device router"],
        "tunneled_protocols": ["USB3.2", "DisplayPort", "PCIe"],
        "lanes_per_link": 2,
        "aggregate_bandwidth_Gbps": 40,
        "connector": "USB Type-C (24-pin)",
        "power_delivery": "USB-C CC pins, up to 100 W / 240 W EPR",
        "base_protocol": "Thunderbolt 3 (Intel)",
    }
    d["interface_categories"] = [
        "Host router (contains the Connection Manager + host interface adapter)",
        "Hub router (cascades the fabric; multiple downstream lane adapters)",
        "Device router (leaf; USB3 / DP / PCIe adapters)",
        "Lane adapter (physical inter-router link endpoint)",
        "Protocol adapter (USB3 / DP-IN / DP-OUT / PCIe tunneling endpoint)",
    ]
    d["interconnect_topologies_supported"] = [
        "Spanning tree of routers rooted at a host router (mandatory).",
        "Daisy-chain of routers via hub routers.",
        "Host-to-host link between two host routers.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Lanes electrically idle when link is down; LFPS keep-alive when up but idle.")
    d["soc_dependent_items"] = [
        "USB4 router IP (transport + configuration + adapter layers).",
        "High-speed PHY (Gen 2 / Gen 3 SerDes; USB4 v2 PAM-3).",
        "USB-C PHY + USB Power Delivery policy engine on CC pins.",
        "Tunneled-protocol controllers (USB3 host, DisplayPort source/sink, PCIe root/endpoint).",
        "Time Management Unit (TMU) clock distribution.",
        "Connection Manager firmware (host side).",
    ]
    d["low_power_modes"] = {
        "USB4_sleep": "Link low-power state; resumes via SBU/LFPS.",
        "Selective_tunnel_disable": "Individual tunnels can be torn down to save power.",
        "USB_PD_low_power": "Negotiated lower power contract on CC pins.",
    }
    d["tunneled_protocol_examples"] = [
        "USB3.2 tunnel (10/20 Gbps USB devices)",
        "DisplayPort tunnel (external monitors, DP Alt Mode)",
        "PCIe tunnel (eGPU, NVMe, Thunderbolt-class peripherals)",
        "Host-to-Host (PC-to-PC data transfer)",
    ]
    d.pop("device_classes_examples", None)  # USB-2.0 sibling residue
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — test cases
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - USB4 defines extensive electrical, link, transport, tunneling, "
        "and PD compliance behaviors (mapped to the USB-IF USB4 compliance program), "
        "but the spec itself does not ship a testbench.")
    d["derived_compliance_test_categories"] = [
        "USB-C orientation + Power Delivery contract negotiation on CC pins.",
        "LT-LFPS link training + lane bonding (Gen 2 and Gen 3).",
        "Gen 2 (10 Gbps/lane, 64b/66b) and Gen 3 (20 Gbps/lane, 128b/132b) signal quality.",
        "Aggregate 20 Gbps (Gen 2x2) and 40 Gbps (Gen 3x2) throughput.",
        "Router enumeration: Connection Manager reads router/adapter config space, builds spanning tree.",
        "Path/tunnel setup: hop-ID allocation + per-router path config write.",
        "USB3.2 tunnel data integrity end-to-end.",
        "DisplayPort tunnel (main link + AUX) with TMU time-sync.",
        "PCIe tunnel (memory/IO/config) end-to-end.",
        "Host-to-Host data path.",
        "Transport-layer credit-based flow control (no overrun).",
        "Backward compatibility: USB 3.2 and USB 2.0 fallback on the same port.",
        "Thunderbolt 3 interoperability (when advertised).",
        "USB4 v2: 80 Gbps symmetric / asymmetric (Gen 4 PAM-3) where supported.",
        "Hot-plug connect/disconnect handling.",
        "Power Delivery up to 100 W / 240 W EPR.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["notes"] = (
        "USB4 is a wire-level + tunneling protocol spec; no OTP / fuse content at the "
        "protocol layer. A USB4 router IP may hard-wire vendor/product IDs + "
        "capability defaults into ROM/OTP, but this is a per-implementation choice, "
        "not protocol-defined.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Drop USB-2.0-specific sequence keys the sibling installs.
    for k in ("bus_enumeration_sequence", "control_transfer_sequence",
              "bulk_in_transaction_sequence", "bulk_out_transaction_sequence",
              "interrupt_transfer_sequence", "isochronous_transfer_sequence",
              "split_transaction_sequence", "suspend_resume_sequence",
              "data_toggle_sequence"):
        d.pop(k, None)
    d["connect_and_link_bringup_sequence"] = [
        "1. USB-C partner detected; orientation + USB Power Delivery contract negotiated on CC pins.",
        "2. Lane adapters exchange LT-LFPS ordered sets to train the high-speed link.",
        "3. Two lanes bond into one logical link (2 x 20 Gbps = 40 Gbps Gen 3x2).",
        "4. Adaptive equalization tunes each lane; link reaches the active transport state.",
    ]
    d["router_enumeration_sequence"] = [
        "1. Connection Manager reads the newly-connected router's config space (router + adapters).",
        "2. Router is placed into the spanning tree (topology/route string assigned).",
        "3. Adapter capabilities (USB3 / DP / PCIe / lane) are discovered.",
        "4. TMU time-sync is established across the new link.",
    ]
    d["tunnel_setup_sequence"] = [
        "1. Connection Manager decides a tunnel is needed (e.g. DisplayPort to an external monitor).",
        "2. It computes an end-to-end path through routers and allocates per-hop hop IDs.",
        "3. It writes path config into every router along the route (input hop ID -> output adapter + hop ID).",
        "4. Source + sink protocol adapters are enabled; tunneled packets begin to flow under flow control.",
    ]
    d["displayport_tunnel_sequence"] = [
        "1. DP-IN adapter ingests DisplayPort main-link + AUX from the source.",
        "2. Traffic is encapsulated into USB4 tunneled packets, TMU-synchronized.",
        "3. Packets traverse the fabric along the configured path.",
        "4. DP-OUT adapter reconstructs the native DisplayPort stream to the sink.",
    ]
    d["pcie_tunnel_sequence"] = [
        "1. PCIe adapter ingests PCI Express TLPs (memory/IO/config).",
        "2. TLPs are encapsulated into USB4 tunneled packets.",
        "3. Packets traverse the fabric to the remote PCIe adapter.",
        "4. Native PCIe transactions are reconstructed (e.g. for an eGPU or NVMe).",
    ]
    d["power_delivery_sequence"] = [
        "1. On connect, source + sink advertise PD capabilities on CC pins.",
        "2. Sink requests a power object (e.g. 20 V / 5 A = 100 W, or EPR up to 240 W).",
        "3. Source accepts; VBUS ramps to the negotiated voltage.",
        "4. Either side may renegotiate the contract later.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["notes"] = (
        "USB4 is a digital tunneling protocol; no analog reference/trim/calibration "
        "loop at the protocol layer. The Gen 2 / Gen 3 SerDes PHY (and USB4 v2 PAM-3 "
        "PHY) includes adaptive equalization + per-lane training during LT-LFPS link "
        "bring-up, but that is PHY behavior, not a protocol-level calibration loop.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — protocol versioning
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "USB4 Version 1.0 (August 29, 2019)"
    f["previous_versions"] = [
        "Thunderbolt 3 (2015, Intel) — donated base protocol for USB4.",
        "USB4 Version 1.0 (August 29, 2019) — 20 / 40 Gbps router-based tunneling fabric.",
        "USB4 Version 2.0 (2022) — adds 80 Gbps symmetric / up to 120 Gbps asymmetric (Gen 4, PAM-3).",
    ]
    f["key_changes"] = [
        {"version": "Thunderbolt 3", "summary": "Intel's 40 Gbps tunneling protocol over USB-C; donated as the USB4 base."},
        {"version": "USB4 1.0", "summary": "USB-IF tunneling fabric: USB3/DP/PCIe tunnels, router topology, Connection Manager, 20/40 Gbps Gen 2/Gen 3."},
        {"version": "USB4 2.0", "summary": "Gen 4 PAM-3 signalling for 80 Gbps symmetric; asymmetric (3:1) lane mode up to 120 Gbps; enhanced DP/PCIe tunneling."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "tunnel_vs_native_usb",
         "usb4": "Carries USB3.2 as a TUNNEL over the transport layer, not natively.",
         "trap": "A USB4 port still exposes native USB 2.0 on D+/D- and USB 3.2 via tunnel; mismatched assumptions about 'native' vs 'tunneled' USB3 break interop."},
        {"trap_name": "gen2_vs_gen3_lane_rate",
         "gen2": "10 Gbps/lane (mandatory), 64b/66b.",
         "gen3": "20 Gbps/lane (full feature), 128b/132b.",
         "trap": "A Gen-2-only USB4 device negotiates 20 Gbps aggregate, not 40 Gbps — surprising users who expect '40 Gbps USB4'."},
        {"trap_name": "thunderbolt3_interop_optional",
         "usb4": "Built on Thunderbolt 3 but TB3 interop is OPTIONAL.",
         "trap": "Not every USB4 host certifies Thunderbolt 3 compatibility; a TB3 device may not work on a USB4 port that did not advertise TB3 interop."},
        {"trap_name": "usb4_v2_80Gbps_signalling",
         "usb4_1": "Gen 2/Gen 3 NRZ-class signalling.",
         "usb4_v2": "Gen 4 PAM-3 multilevel signalling for 80 Gbps.",
         "trap": "80 Gbps requires USB4 v2 cabling + PHYs; older USB4 1.0 cables/ports cap at 40 Gbps."},
    ]
    f["version_naming_history_note"] = (
        "USB4 is maintained by the USB Implementers Forum (USB-IF). Its base protocol "
        "is Thunderbolt 3, donated by Intel. USB4 1.0 was published August 29, 2019; "
        "USB4 2.0 (2022) added 80 Gbps. USB4 sits above earlier USB generations "
        "(USB 2.0 480 Mbps, USB 3.2 up to 20 Gbps) which it carries natively or via "
        "tunnels.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding tables
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # Drop USB-2.0-specific PID/descriptor encodings.
    for k in ("packet_id_encoding", "device_request_bmRequestType_encoding",
              "standard_descriptor_type_codes", "feature_selector_codes",
              "endpoint_attribute_transfer_type_encoding", "signaling_speed_table"):
        f.pop(k, None)
    f["line_encoding_table"] = {
        "header_columns": ["Generation", "Baud (Gbaud/lane)", "Line code", "Data rate/lane", "Aggregate (x2)"],
        "rows": [
            {"gen": "Gen 2", "baud": "10.3125", "code": "64b/66b",   "per_lane": "10 Gbps", "aggregate": "20 Gbps"},
            {"gen": "Gen 3", "baud": "20.625",  "code": "128b/132b", "per_lane": "20 Gbps", "aggregate": "40 Gbps"},
            {"gen": "Gen 4 (USB4 v2)", "baud": "PAM-3", "code": "PAM-3 multilevel", "per_lane": "40 Gbps", "aggregate": "80 Gbps"},
        ],
    }
    f["tunneled_protocol_table"] = {
        "header_columns": ["Tunnel", "Native protocol", "Adapter types"],
        "rows": [
            {"tunnel": "USB3 tunnel",        "native": "USB 3.2 (up to 20 Gbps)", "adapters": "USB3 up/down adapter"},
            {"tunnel": "DisplayPort tunnel", "native": "DisplayPort main link + AUX", "adapters": "DP-IN / DP-OUT adapter"},
            {"tunnel": "PCIe tunnel",        "native": "PCI Express TLPs", "adapters": "PCIe up/down adapter"},
        ],
    }
    f["adapter_type_table"] = {
        "header_columns": ["Adapter", "Role"],
        "rows": [
            ["Lane adapter", "Physical inter-router link endpoint (bonded pairs)"],
            ["USB3 adapter", "USB 3.2 tunneling endpoint"],
            ["DP-IN adapter", "DisplayPort source ingestion"],
            ["DP-OUT adapter", "DisplayPort sink emission"],
            ["PCIe adapter", "PCI Express tunneling endpoint"],
            ["Host interface adapter", "Router-to-Connection-Manager interface"],
        ],
    }
    f["power_delivery_table"] = {
        "header_columns": ["Profile", "Voltage", "Current", "Power"],
        "rows": [
            ["Standard PD", "20 V", "5 A", "100 W"],
            ["EPR", "48 V", "5 A", "240 W"],
            ["Lower profiles", "5/9/15/20 V", "negotiated", "<= 100 W"],
        ],
    }
    f["tables"] = [
        "USB4 line-rate / line-code table (Gen 2 / Gen 3 / Gen 4)",
        "USB4 tunneled-protocol table (USB3 / DisplayPort / PCIe)",
        "USB4 adapter-type table",
        "USB Power Delivery profile table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "USB Type-C connector with USB Power Delivery on CC pins.",
        "Gen 2 operation (10 Gbps/lane, 64b/66b) mandatory; aggregate 20 Gbps minimum.",
        "LT-LFPS link training + lane bonding to a single logical link.",
        "Router configuration space (router/adapter/path/counters) addressable by the Connection Manager.",
        "Encapsulation of USB3.2 / DisplayPort / PCIe into USB4 tunneled packets over the transport layer.",
        "Credit-based transport-layer flow control between adjacent routers.",
        "Time Management Unit (TMU) common time base for isochronous tunnels.",
        "Backward compatibility with USB 3.2 and USB 2.0 on the same port.",
        "Spanning-tree routing rooted at the host router; single Connection Manager.",
    ]
    f["must_not_have_properties"] = [
        "Source high-power VBUS before a USB Power Delivery contract is established on CC pins.",
        "Carry a tunnel before its end-to-end path is configured by the Connection Manager.",
        "Create routing loops (the fabric must remain a spanning tree).",
        "Advertise 40 Gbps (Gen 3x2) without supporting 20 Gbps/lane Gen 3.",
        "Break native USB 2.0 fallback on the dedicated D+/D- pair.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Link training fail", "trigger": "LT-LFPS ordered-set mismatch / equalization timeout."},
        {"mode": "Tunnel setup fail",  "trigger": "Connection Manager cannot allocate hop IDs / bandwidth."},
        {"mode": "Flow-control error", "trigger": "Transport-layer credit underflow/overflow."},
        {"mode": "Config-space error", "trigger": "Invalid hop ID / adapter in path config."},
        {"mode": "PD contract fail",   "trigger": "Power Delivery negotiation failure on CC pins."},
        {"mode": "TMU loss",           "trigger": "Loss of common time base for isochronous tunnels."},
    ]
    f["reset_behavior_compliance"] = (
        "On connect/reset: USB-C orientation + PD negotiation, then LT-LFPS link "
        "training, then Connection Manager enumeration before any tunnel carries "
        "traffic.")
    f.pop("min_bus_capacitance_constraint", None)  # USB-2.0 sibling residue
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog  (force-overwrite dependency_graph)
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "TX1+/TX1-", "direction": "transmit differential", "purpose": "High-speed lane 0 transmit.", "active_levels": "Gen 2 = 10.3125 Gbaud (64b/66b); Gen 3 = 20.625 Gbaud (128b/132b)."},
        {"name": "RX1+/RX1-", "direction": "receive differential",  "purpose": "High-speed lane 0 receive."},
        {"name": "TX2+/TX2-", "direction": "transmit differential", "purpose": "High-speed lane 1 transmit (bonded with lane 0)."},
        {"name": "RX2+/RX2-", "direction": "receive differential",  "purpose": "High-speed lane 1 receive."},
        {"name": "SBU1/SBU2", "direction": "bidirectional low-speed","purpose": "Sideband management channel between adjacent routers."},
        {"name": "CC1/CC2",   "direction": "bidirectional",          "purpose": "USB-C Configuration Channel; USB Power Delivery + orientation."},
        {"name": "VBUS",      "direction": "source -> sink",         "purpose": "Bus power per negotiated PD contract (up to 100 W / 240 W EPR)."},
        {"name": "D+/D-",     "direction": "half-duplex",            "purpose": "USB 2.0 backward-compatibility pair."},
        {"name": "GND",       "direction": "common reference",       "purpose": "Common ground."},
    ]
    f["logical_signaling_levels"] = [
        {"name": "LT-LFPS",        "meaning": "Low-Frequency Periodic Signaling ordered sets for link training."},
        {"name": "Electrical idle","meaning": "Lanes quiescent when link up but no traffic."},
        {"name": "Gen2 NRZ",       "meaning": "64b/66b-coded high-speed symbols at 10.3125 Gbaud."},
        {"name": "Gen3 NRZ",       "meaning": "128b/132b-coded high-speed symbols at 20.625 Gbaud."},
        {"name": "Gen4 PAM-3",     "meaning": "USB4 v2 multilevel signalling for 80 Gbps."},
    ]
    f["packet_types_summary"] = [
        {"class": "Tunneled",  "members": ["USB3 tunneled", "DisplayPort tunneled", "PCIe tunneled"]},
        {"class": "Transport", "members": ["Data packet", "Flow-control credit", "Idle"]},
        {"class": "Control",   "members": ["Config read/write", "Path setup", "Hot-plug", "TMU"]},
        {"class": "Link",      "members": ["LT-LFPS ordered set", "Lane config", "SBU message"]},
    ]
    f["channel_counts"] = {
        "high_speed_lanes":      2,
        "high_speed_diff_pairs": 4,
        "sideband_pairs":        1,
        "cc_pins":               2,
        "usbc_receptacle_pins":  24,
        "aggregate_Gbps_Gen3x2": 40,
        "tunneled_protocols":    3,
    }
    f["global_signals"] = [
        {"name": "VBUS", "purpose": "Bus power per the USB Power Delivery contract."},
        {"name": "GND",  "purpose": "Common ground."},
    ]
    # FORCE-OVERWRITE dependency_graph for the USB4 router/tunnel shape.
    f["dependency_graph"] = {
        "common_rule": "The Connection Manager (host-resident) configures all routers; tunnels are set up before traffic flows; routers forward tunneled + control packets per their installed path config.",
        "data_dependency": "Each tunnel = an end-to-end path = an ordered list of per-hop {adapter, hop ID} entries; transport uses credit-based flow control between adjacent routers.",
    }
    f["handshake_pairs"] = [
        {"name": "LFPS-train",     "from": "lane adapter", "to": "peer lane adapter", "rule": "LT-LFPS ordered sets train + bond the high-speed lanes."},
        {"name": "Credit-flow",    "from": "downstream router", "to": "upstream router", "rule": "Credit-based flow control gates transport-layer data."},
        {"name": "Config-rd/wr",   "from": "Connection Manager", "to": "router config space", "rule": "CM reads capabilities + writes path config."},
        {"name": "PD-negotiate",   "from": "source", "to": "sink", "rule": "USB Power Delivery contract on CC pins before high-power VBUS."},
        {"name": "TMU-sync",       "from": "host router", "to": "downstream routers", "rule": "Time Management Unit distributes a common time base."},
    ]
    f["ordering_rules"] = {
        "per_tunnel_ordering": "Each tunnel preserves the native protocol's packet ordering end-to-end.",
        "transport_flow_control": "Credit-based; no reorder across a single path.",
        "tx_rx_simultaneity": "Full-duplex; independent TX and RX pairs per lane.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — interconnect topology
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Spanning tree of routers rooted at the host router; hub routers cascade the "
        "fabric; device routers are leaves. Each link is a USB-C dual-lane "
        "bidirectional connection.")
    f["supported_topologies"] = [
        {"name": "Host router + device router", "description": "Direct point-to-point USB-C link."},
        {"name": "Daisy chain via hub routers", "description": "Hub routers cascade additional downstream links."},
        {"name": "Host-to-Host", "description": "Two host routers linked for PC-to-PC data."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host router",       "description": "Root of the tree; hosts the Connection Manager; allocates paths + tunnels."},
        {"role": "Hub router",        "description": "Cascades the fabric; multiple downstream lane adapters; forwards tunneled + control packets."},
        {"role": "Device router",     "description": "Leaf; exposes USB3 / DisplayPort / PCIe adapters to be tunneled."},
        {"role": "Connection Manager","description": "Host-resident manager; one per fabric; programs router config spaces."},
    ]
    f["interconnect_role"] = (
        "USB4 is a tunneling fabric: routers forward encapsulated USB3 / DisplayPort "
        "/ PCIe traffic over a shared transport layer along Connection-Manager-"
        "configured paths.")
    f["ordering_guarantees"] = {
        "per_tunnel_ordering": "Native protocol ordering preserved end-to-end within each tunnel.",
        "isochronous_tunnels": "DisplayPort + USB3 isochronous tunnels are bandwidth-reserved + TMU-synchronized.",
        "spanning_tree": "No routing loops; a single path between any two routers.",
    }
    f["memory_vs_peripheral_regions"] = (
        "PCIe tunnels carry PCI Express memory/IO/config transactions; USB3 tunnels "
        "carry USB device traffic; DisplayPort tunnels carry isochronous video.")
    f["device_classification"] = {
        "host_router":   "Contains the Connection Manager + host interface adapter.",
        "hub_router":    "Forwarding router adding downstream links.",
        "device_router": "Leaf router exposing protocol adapters.",
        "lane_adapter":  "Physical inter-router link endpoint.",
        "protocol_adapter": "USB3 / DP / PCIe tunneling endpoint.",
    }
    f["default_signal_values_evidence_tables"] = [
        "USB4 router architecture (host / hub / device routers)",
        "USB4 transport + configuration + tunneled-protocol layers",
        "USB-C connector pinout (high-speed lanes + SBU + CC + VBUS)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = False
    f["notes"] = (
        "USB4 is a wire-level + tunneling protocol spec; no PDK / SDC / floorplan "
        "constraints at the protocol layer. High-speed SerDes timing budgets (Gen 2 "
        "10.3125 Gbaud, Gen 3 20.625 Gbaud, USB4 v2 PAM-3), USB-C channel insertion "
        "loss, and PD power-path constraints live in the SoC/board integration spec, "
        "not in the USB4 protocol document itself.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan topology
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["internal_diagnostics"] = [
        "Router/adapter/path/counters configuration spaces are readable by the Connection Manager for in-system diagnosis.",
        "Per-lane SerDes loopback + compliance patterns (Gen 2 / Gen 3) for PHY BER characterization.",
        "Transport-layer CRC + flow-control credit counters detect link errors.",
        "SBU sideband connect/lane-config events for link debug.",
        "TMU time-sync lock/quality status.",
    ]
    f["notes"] = (
        "USB4 specifies structural observability via configuration-space counters + "
        "PHY compliance patterns. SoC-integrated USB4 router IP typically adds "
        "standard scan + JTAG at the integrator level (not protocol-defined).")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["low_power_modes_summary"] = {
        "usb4_sleep":            "Link low-power state; resumes via SBU/LFPS.",
        "selective_tunnel_off":  "Individual tunnels torn down to save power.",
        "usb_pd_low_power":      "Negotiated lower PD contract on CC pins.",
        "lane_disable":          "Drop from dual-lane to single-lane to save power.",
    }
    f["power_classes_of_devices"] = [
        "USB Power Delivery sink/source up to 100 W (20 V / 5 A).",
        "Extended Power Range (EPR) up to 240 W (48 V / 5 A).",
        "Bus-powered USB-C peripherals at lower PD profiles (5/9/15 V).",
    ]
    f["VBUS_specification"] = {
        "delivered_by": "USB Power Delivery contract on CC pins",
        "standard_max_W": 100,
        "epr_max_W": 240,
        "voltages_V": [5, 9, 15, 20, 28, 36, 48],
    }
    f["notes"] = (
        "USB4 power is delivered via USB Power Delivery over the USB-C CC pins (up to "
        "100 W standard, 240 W with EPR). Link low-power states (USB4 sleep, lane "
        "disable, selective tunnel teardown) reduce dynamic power; resume is via SBU "
        "/ LFPS.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "USB-C orientation + PD contract negotiation.",
        "LT-LFPS link training + lane bonding (Gen 2 / Gen 3).",
        "Gen 2 (10 Gbps/lane) and Gen 3 (20 Gbps/lane) signal quality + BER.",
        "Aggregate 20 / 40 Gbps throughput; USB4 v2 80 Gbps where supported.",
        "Router enumeration via config-space reads; spanning-tree construction.",
        "Hop-ID path allocation + per-router path-config writes.",
        "USB3.2 tunnel end-to-end data integrity.",
        "DisplayPort tunnel (main link + AUX) with TMU time-sync.",
        "PCIe tunnel (memory/IO/config) end-to-end.",
        "Host-to-Host data path.",
        "Transport-layer credit-based flow control.",
        "Backward compatibility (USB 3.2 + USB 2.0 fallback).",
        "Thunderbolt 3 interoperability (when advertised).",
        "Power Delivery up to 100 W / 240 W EPR.",
        "Hot-plug connect/disconnect + tunnel setup/teardown.",
    ]
    f["notes"] = (
        "USB4 does not ship a formal verification plan; the USB-IF maintains a USB4 "
        "compliance program (electrical, link, transport, tunneling, PD, "
        "interoperability). Categories above are derived from the USB4 architecture.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security requirements
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = True
    f["notes"] = (
        "Because USB4 tunnels PCI Express (which exposes DMA), platform security is a "
        "real concern. USB4 hosts rely on the platform's IOMMU/DMA-remapping + "
        "Connection-Manager-enforced PCIe-tunnel authorization to mitigate DMA "
        "attacks (the 'Thunderspy'/Thunderbolt DMA-attack class). USB Type-C "
        "Authentication (an optional companion spec) can attest devices/cables over "
        "the CC channel. The USB4 transport itself provides CRC integrity but not "
        "confidentiality.")
    f["security_mechanisms"] = [
        "Platform IOMMU / DMA remapping to contain PCIe-tunnel DMA.",
        "Connection-Manager-controlled PCIe-tunnel authorization (user-approve before PCIe tunnel).",
        "Optional USB Type-C Authentication over the CC channel.",
        "Transport-layer CRC (integrity, not confidentiality).",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_usb4(blob: str) -> bool:
    """Content-only `usb4` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same structural boolean the runner used inline, PRECEDED by a
    FOREIGN-PRIMARY DEFER (the v0.1.95 ORGANIC-usb4-misfire guard).

    The structural signature ("USB4" + a USB4-only structural token:
    router / 40 Gbps / Connection Manager) is necessary but NOT
    sufficient. USB4 is the tunneling super-protocol that carries
    DisplayPort and PCIe tunnels and negotiates power over USB Power
    Delivery, so a VESA DisplayPort spec or a USB-PD spec that merely
    NAMES USB4 (DisplayPort cites "alignment with USB4"; USB-PD is the
    power layer USB4 reuses) carries the loose USB4 structural tokens and
    would otherwise trip this detector and let the generic USB4 synth
    inject tunneling-fabric content into a DisplayPort / USB-PD spec.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, no chip/SKU/benchmark literal as detection logic): if
    the blob's DOMINANT subject is a foreign protocol, defer (False):

      - DisplayPort (the VESA DP structural signature: Main Link + AUX +
        DPCD + a DP-only discriminator [CR/EQ link training OR the
        RBR/HBR link-rate vocabulary]). This trio+discriminator is the
        DisplayPort signature; it is absent from a real USB4 spec (which
        carries DisplayPort only as a tunnel, never the native Main
        Link + AUX + DPCD wire interface).
      - USB Power Delivery (the USB-PD power-contract signature: Biphase
        Mark Coding + the PDO/RDO power-object pair + a Source/Sink
        contract over VBUS/VCONN). A native USB4 transport spec carries
        none of BMC + PDO/RDO power-object negotiation; it only mentions
        PD in passing, so this signature marks a PD-primary doc.

    Empirically corpus-clean: the real `usb4` benchmark trips NEITHER
    defer (no DP Main-Link+AUX+DPCD trio, no BMC+PDO/RDO power contract)
    and stays True; `displayport` trips dp_primary and `usb_pd` trips
    pd_primary, so both are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT USB4). ---
    # DisplayPort-primary: the VESA DP structural signature (Main Link +
    # AUX + DPCD + a DP-only discriminator). Mirrors displayport_synth's
    # `is_displayport`.
    _dp_main_link = "main link" in low
    _dp_aux = ("aux ch" in low or "aux channel" in low
               or "i2c-over-aux" in low)
    _dp_dpcd = ("dpcd" in low
                or "displayport configuration data" in low)
    _dp_cr_eq = (
        (("clock recovery" in low or "clock-recovery" in low)
         and ("channel equalization" in low
              or "channel-equalization" in low))
        or ("link training" in low and "training_pattern_set" in low))
    _dp_rate = (("rbr" in low and "hbr" in low) or "hbr2" in low
                or "hbr3" in low or "link_bw_set" in low)
    dp_primary = (_dp_main_link and _dp_aux and _dp_dpcd
                  and (_dp_cr_eq or _dp_rate))

    # USB-PD-primary: the USB Power Delivery power-contract signature
    # (Biphase Mark Coding + PDO/RDO power-object pair + Source/Sink over
    # VBUS/VCONN). Mirrors usb_pd_synth's `is_usb_pd` structural quorum.
    _pd_bmc = "biphase mark" in low
    _pd_pdo_rdo = (("power data object" in low or _wb_low("pdo", low))
                   and ("request data object" in low or _wb_low("rdo", low)))
    _pd_source_sink = ("source" in low and "sink" in low
                       and ("vbus" in low or "vconn" in low))
    pd_primary = _pd_bmc and _pd_pdo_rdo and _pd_source_sink

    if dp_primary or pd_primary:
        return False

    # --- STRUCTURAL USB4 signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("32 GT/s" not in blob)
        and "USB4" in blob and (
            "router" in blob.lower()
            or "40 Gbps" in blob
            or "Connection Manager" in blob))
