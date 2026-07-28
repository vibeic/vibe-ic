"""PCI Express-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol`-shaped
specs that exhibit the PCI Express structural signature (TLP + DLLP +
LTSSM + PCI Express terminology, OR 8b/10b + Transaction Layer + Data
Link Layer + Physical Layer + PCI Express base spec mention). Applies
PCI-SIG PCI Express Base Specification Rev 1.0 (April 2002) spec-
canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any PCIe-family variant (PCIe 1.0 / 1.1 / 2.x / 3.x / 4.x base spec,
PCI Express endpoint IPs, Root-Complex IPs) exhibits the same
structural TL+DLL+PHY+LTSSM signature.

Public entry: `apply_pcie_synth(generated_docs_dir, is_pcie, pcie_ic_name)`.
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


def apply_pcie_synth(generated_docs_dir: Path, is_pcie: bool,
                     pcie_ic_name: Optional[str]) -> None:
    """Apply PCI Express-specific synth when the structural signature matched."""
    if not is_pcie:
        return
    gd = Path(generated_docs_dir)

    # Force ic_name across the 14 main L docs.
    if pcie_ic_name is not None:
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
                d["ic_name"] = pcie_ic_name
                _write(q, d)

    # L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "PCI Express Base Specification")
        d.setdefault("version", "Revision 1.0")
        d.setdefault("revised_date", "April 29, 2002")
        d.setdefault("manufacturer", "PCI-SIG (PCI Special Interest Group)")
        d.setdefault("copyright", "© 2002 PCI-SIG")
        d.setdefault("abstract",
            "PCI Express is a third-generation, layered, point-to-point, dual-simplex, differentially-signaled serial I/O interconnect with embedded clocking via 8b/10b encoding and credit-based flow control. The Base Specification covers the Transaction Layer, Data Link Layer, and Physical Layer plus software configuration, power management, and system architecture.")
        d.setdefault("keywords", [
            "PCI Express", "PCIe", "TLP", "DLLP", "LTSSM", "8b/10b",
            "Transaction Layer", "Data Link Layer", "Physical Layer",
            "Root Complex", "Endpoint", "Switch", "Virtual Channel",
        ])
        d.setdefault("external_pins", [
            "TXp / TXn (differential transmit pair, per Lane)",
            "RXp / RXn (differential receive pair, per Lane)",
            "REFCLK+ / REFCLK- (100 MHz reference clock, optional spread-spectrum)",
            "PERST# (Fundamental Reset, active LOW)",
            "WAKE# (open-drain wakeup, system-level)",
        ])
        d.setdefault("external_pin_count_per_lane", 4)
        d.setdefault("supported_link_widths_lanes", [1, 2, 4, 8, 12, 16, 32])
        d.setdefault("modes_of_operation", [
            {"name": "Gen 1 (this spec)", "line_rate_GT_s": 2.5,
             "encoding": "8b/10b",
             "per_lane_raw_bandwidth_Gbps": 2.5,
             "per_lane_effective_bandwidth_Gbps": 2.0},
        ])
        d.setdefault("key_features", [
            "Continuation of the PCI Software Model — backward binary compatible with PCI 2.3 configuration access.",
            "Serial, differential, low-voltage signaling at 2.5 GT/s per Lane per direction (Gen 1).",
            "Layered architecture: Transaction Layer (TL) + Data Link Layer (DLL) + Physical Layer (PHY).",
            "Predictable, low latency suitable for isochronous data delivery.",
            "Robust data integrity: 16-bit LCRC on TLP at Data Link Layer + optional 32-bit ECRC end-to-end at Transaction Layer.",
            "Embedded clocking via 8b/10b encoding — no separate clock line.",
            "Bandwidth scalability through Lane aggregation (x1, x2, x4, x8, x12, x16, x32) and frequency.",
            "Hot attach and detach capability — link training auto-detects connected partners.",
            "Aggressive Active-State and software-driven power management (L0 / L0s / L1 / L2 / L3).",
            "Credit-based flow control eliminates retries due to receive-buffer overflow.",
            "Split-transaction protocol — Requests and Completions are decoupled (Posted + Non-Posted + Completion classes).",
            "Up to 8 Traffic Classes (TC) mapped onto up to 8 Virtual Channels (VC) per Link.",
            "Message Space replaces sideband signals (interrupts via MSI; PME via PM Messages; legacy INTx emulation via Messages).",
            "Process-technology independent — supports different DC common-mode voltages at TX and RX (AC-coupled).",
            "Maximum payload size (Max_Payload_Size) negotiated per device: 128 / 256 / 512 / 1024 / 2048 / 4096 bytes.",
            "Native hot-plug, error reporting, and slot-power-limit infrastructure.",
        ])
        d.setdefault("topology_summary",
            "Tree-shaped fabric (called a 'hierarchy') rooted at a Root Complex (RC). RC connects CPU/memory to the I/O. Below the RC: optional Switches that aggregate multiple Endpoints, plus optional PCI Express-to-PCI/PCI-X Bridges for legacy PCI access. Endpoints are either 'PCI Express Endpoints' or 'Legacy Endpoints'. Each Link is point-to-point and dual-simplex (independent TX + RX pairs).")
        d.setdefault("package_summary",
            "PCI Express Base Specification is a wire-level + transaction-level + software-interface specification. Mechanical / connector specifications (card edge, mini-card, ExpressCard, etc.) are in the companion PCI Express Card Electromechanical Specification.")
        d.setdefault("use_cases", [
            "Client PCs (desktop + mobile) — graphics, storage, networking interconnect",
            "Standard + Enterprise servers — multi-Endpoint, multi-hierarchy fabrics",
            "Embedded and communication platforms",
            "Streaming media applications via isochronous Virtual Channels",
            "Backward-compatible replacement for the parallel PCI / PCI-X bus",
        ])
        d.setdefault("revision_history", [
            {"version": "1.0", "date": "April 29, 2002",
             "description": "Initial release by PCI-SIG."},
        ])
        d.setdefault("overview",
            "PCI Express is a third-generation I/O interconnect targeted at re-engineering the PCI/PCI-X parallel bus into a high-bandwidth, low-pin-count point-to-point serial fabric. It preserves the PCI software model (configuration cycles, device hierarchy, plug-and-play) while delivering scalable bandwidth (2.5 GT/s per Lane per direction Gen 1, aggregated across x1..x32 Lanes) over differential signaling with embedded clocking via 8b/10b encoding. The architecture is layered: Transaction Layer produces and consumes Transaction Layer Packets (TLPs); Data Link Layer adds Sequence Numbers + LCRC + ACK/NAK replay; Physical Layer performs 8b/10b encoding + framing + Link Training (LTSSM). Together these layers deliver split-transaction, credit-based-flow-controlled, error-protected, hot-pluggable I/O for clients, servers, and embedded systems.")
        _write(p, d)

    # L2
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        if d.get("protocol_overview") in (None, "", []):
            d["protocol_overview"] = {}
        po = d["protocol_overview"]
        if isinstance(po, dict):
            po.setdefault("type",
                "Layered, point-to-point, dual-simplex, differentially-signaled, packet-based serial I/O interconnect.")
            po.setdefault("duplex",
                "dual-simplex (independent TX + RX differential pairs per Lane; both directions transmit simultaneously)")
            po.setdefault("synchronous_serial", False)
            po.setdefault("embedded_clock", True)
            po.setdefault("encoding",
                "8b/10b (per byte → 10 bits on the wire); embedded clock + DC balance + special K-codes for framing and link management")
            po.setdefault("line_rate_GT_s", 2.5)
            po.setdefault("lane_widths_supported", [1, 2, 4, 8, 12, 16, 32])
            po.setdefault("layers", [
                "Transaction Layer (TL)", "Data Link Layer (DLL)",
                "Physical Layer (PHY) = Logical Sub-block + Electrical Sub-block",
            ])
            po.setdefault("packet_classes_per_layer", {
                "Transaction_Layer": "TLP (Transaction Layer Packet)",
                "Data_Link_Layer":   "DLLP (Data Link Layer Packet) — link-management only, e.g. ACK / NAK / FC / PM",
            })
            po.setdefault("flow_control",
                "Credit-based per Virtual Channel; receiver advertises credits to transmitter; no retries due to receiver buffer overflow.")
            po.setdefault("split_transaction", True)
            po.setdefault("address_spaces",
                ["Memory", "I/O", "Configuration", "Message"])
            po.setdefault("max_payload_sizes_bytes_negotiated",
                [128, 256, 512, 1024, 2048, 4096])
            po.setdefault("virtual_channels_max", 8)
            po.setdefault("traffic_classes_max", 8)
        fr = [
            {"id": "FR-LINK-01",   "text": "A PCI Express Link is a dual-simplex communications channel between two components, consisting of a transmit differential pair and a receive differential pair (per Lane), with an embedded clock recovered via 8b/10b encoding."},
            {"id": "FR-LANES-02",  "text": "A Link must support at least one Lane (x1). Bandwidth may be scaled by aggregating multiple Lanes — supported widths are x1, x2, x4, x8, x12, x16, x32. The Link must be symmetric (same number of Lanes in each direction)."},
            {"id": "FR-RATE-03",   "text": "Gen 1 signaling rate is 2.5 GT/s per Lane per direction; the data rate is expected to increase in future generations."},
            {"id": "FR-LAYERS-04", "text": "The architecture has three discrete logical layers — Transaction Layer, Data Link Layer, and Physical Layer — each split into outbound (TX) and inbound (RX) sections."},
            {"id": "FR-TL-05",     "text": "The Transaction Layer assembles and disassembles Transaction Layer Packets (TLPs), tracks credit-based Flow Control, supports four address spaces (Memory / I/O / Configuration / Message), enforces ordering rules, and optionally generates/checks end-to-end ECRC."},
            {"id": "FR-DLL-06",    "text": "The Data Link Layer adds a 12-bit Sequence Number and a 16-bit LCRC to each outgoing TLP, runs the ACK/NAK replay protocol, manages Data Link Layer Packets (DLLPs) for ACK/NAK/FC/PM, and runs the Data Link Control and Management State Machine."},
            {"id": "FR-PHY-07",    "text": "The Physical Layer converts byte-level data from the DLL into 8b/10b-encoded symbols, frames TLPs with STP...END (or EDB for nullified) and DLLPs with SDP...END, performs Lane-to-Lane skew compensation (de-skew), and runs the Link Training and Status State Machine (LTSSM)."},
            {"id": "FR-LTSSM-08",  "text": "Link bring-up follows the LTSSM: Detect → Polling → Configuration → L0 (active). Low-power transitions go to L0s / L1 / L2 / L3. Failure / re-training goes to Recovery. Disable / Hot Reset are explicit terminating states."},
            {"id": "FR-TLP-09",    "text": "TLPs carry Memory / I/O / Configuration / Message transactions. Each TLP has a header (3 or 4 DWords depending on addressing mode and presence of data payload) and an optional data payload of up to Max_Payload_Size bytes."},
            {"id": "FR-CLASS-10",  "text": "Transaction classes: Posted (Memory Write, Message), Non-Posted (Memory Read, I/O Read/Write, Configuration Read/Write), Completion (response to a Non-Posted Request, with or without data)."},
            {"id": "FR-LCRC-11",   "text": "Every TLP at the Data Link Layer is protected by a 16-bit LCRC computed over Sequence Number + TLP body. Bit errors trigger NAK + replay from the retry buffer at the transmitter."},
            {"id": "FR-ECRC-12",   "text": "End-to-end CRC (ECRC) is a 32-bit CRC, optional, appended as the TLP Digest. It catches errors that LCRC cannot (e.g. corruption inside an intermediate Switch)."},
            {"id": "FR-FC-13",     "text": "Flow control is credit-based per Virtual Channel. Six credit types: PH (Posted Header), PD (Posted Data), NPH (Non-Posted Header), NPD (Non-Posted Data), CplH (Completion Header), CplD (Completion Data)."},
            {"id": "FR-VC-14",     "text": "Up to 8 Virtual Channels (VC0..VC7) and up to 8 Traffic Classes (TC0..TC7) per Link, with TC-to-VC mapping configured by software. VC0 is mandatory and always carries TC0."},
            {"id": "FR-MSI-15",    "text": "Interrupts use Message Signaled Interrupts (MSI) — a Memory Write transaction to a designated address. Legacy INTx semantics are emulated via in-band Messages."},
            {"id": "FR-PM-16",     "text": "Link power management states: L0 (active) / L0s (transmit-side standby, fast resume) / L1 (link inactive but trained, slower resume) / L2 (deep sleep, REFCLK off; Beacon required to wake) / L3 (main power off)."},
            {"id": "FR-HOTPLUG-17","text": "PCI Express supports native hot-plug — insertion and removal of devices while the rest of the system is operating — via Slot Capabilities/Control/Status registers and in-band Hot-Plug Messages."},
            {"id": "FR-CFGSPACE-18","text": "Each device exposes 256 bytes of PCI-compatible Configuration Space plus up to 4096 bytes of PCI Express Extended Configuration Space. Type 0 header is for non-bridges; Type 1 header is for bridges/switch ports."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Receiver Error (Physical Layer) — 8b/10b decode error, framing error (STP/SDP/END missing), or bit-stream loss; logged + reported.",
            "LCRC error (Data Link Layer) — TLP fails 16-bit LCRC check; receiver sends NAK; transmitter replays from retry buffer.",
            "Sequence Number error (Data Link Layer) — out-of-order or duplicate Sequence Number; receiver discards or NAKs.",
            "Replay Number rollover — transmitter exceeds REPLAY_NUM threshold without ACK; Link is declared down → LTSSM Recovery.",
            "Completion Timeout (Transaction Layer) — Non-Posted Request did not receive a Completion within the timeout window.",
            "Unsupported Request (UR) — Completer cannot service the Request; returns Completion with status UR.",
            "Completer Abort (CA) / Configuration Request Retry Status (CRS) — Completer-level abnormal conditions, reported in Completion Status.",
            "ECRC mismatch (optional) — Transaction Layer Digest does not match recomputed CRC; reported via Advanced Error Reporting.",
            "Flow control credit underflow — Transmitter must NOT send a packet without sufficient credit; underflow is a fatal protocol error.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "8b/10b encoding with running-disparity tracking and the canonical K28.5 COM symbol for ordered-set framing.",
                "TLP framing: STP (K27.7) at start, END (K29.7) at end (or EDB K30.7 for nullified TLPs).",
                "DLLP framing: SDP (K28.2) at start, END (K29.7) at end.",
                "Mandatory support for Virtual Channel 0 (VC0) carrying Traffic Class 0 (TC0).",
                "Mandatory PCI Express Capability Structure in Configuration Space (offsets defined by the PCI Express Capability List Register).",
                "Mandatory Configuration Request support: every device responds to Type 0 (own device) or Type 1 (bridge to a deeper bus) Configuration cycles correctly.",
                "Mandatory ACK/NAK replay protocol with a Retry Buffer at the transmitter.",
                "LTSSM compliance — Link must be able to train from Detect to L0 through Polling and Configuration without firmware intervention.",
                "Switches must forward all TLP types between any set of ports (with the noted Locked-Request and peer-to-peer caveats).",
            ]
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Split-transaction packet protocol with three nested packet classes: TLPs (Transaction Layer) carried inside Data Link Layer wrappers (Sequence Number + LCRC + framing), each framed at the Physical Layer with STP/END (TLP) or SDP/END (DLLP) special K-codes on top of 8b/10b-encoded byte streams.")
        d.setdefault("channels", [
            {"name": "TXp/TXn", "direction": "transmit (per Lane, per direction)",
             "description": "Differential transmit pair. AC-coupled, 8b/10b-encoded, 2.5 Gb/s per Lane at Gen 1."},
            {"name": "RXp/RXn", "direction": "receive (per Lane, per direction)",
             "description": "Differential receive pair, symmetric counterpart of TXp/TXn."},
            {"name": "REFCLK+/REFCLK-", "direction": "common reference clock",
             "description": "100 MHz reference; spread-spectrum-clocking (SSC) tolerant. May be shared (Common Clock) or independent (Separate Clock)."},
            {"name": "PERST#", "direction": "system → device",
             "description": "Fundamental Reset. Active LOW. Asserted while main power is unstable; deasserted to start link training."},
            {"name": "WAKE#",  "direction": "device → system (open-drain)",
             "description": "Open-drain WAKE signal. Pulled LOW by any device that wants to resume from L2 / L3."},
        ])
        d.setdefault("packet_classes", [
            {"class": "TLP (Transaction Layer Packet)",
             "purpose": "Carries Memory / I/O / Configuration / Message transactions end-to-end across the fabric.",
             "subtypes": ["Memory Read Request (MRd)", "Memory Read Lock Request (MRdLk)",
                          "Memory Write Request (MWr)", "I/O Read Request (IORd)",
                          "I/O Write Request (IOWr)", "Configuration Read Type 0 (CfgRd0)",
                          "Configuration Write Type 0 (CfgWr0)", "Configuration Read Type 1 (CfgRd1)",
                          "Configuration Write Type 1 (CfgWr1)", "Message Request (Msg)",
                          "Message Request with Data (MsgD)", "Completion (Cpl)",
                          "Completion with Data (CplD)", "Completion Locked (CplLk)",
                          "Completion with Data Locked (CplDLk)"]},
            {"class": "DLLP (Data Link Layer Packet)",
             "purpose": "Link management only; never propagated past the Link.",
             "subtypes": ["Ack", "Nak", "InitFC1 (Flow Control Initialization phase 1)",
                          "InitFC2 (phase 2)", "UpdateFC (running credit update)",
                          "PM (Power Management — PM_Enter_L1 / PM_Enter_L23 / PM_Active_State_Request_L1 / PM_Request_Ack)",
                          "Vendor Specific"]},
        ])
        d.setdefault("tlp_header_format", {
            "fmt_field_width_bits": 2,
            "type_field_width_bits": 5,
            "Fmt_encoding": {
                "00": "3 DW header, no data",
                "01": "4 DW header, no data",
                "10": "3 DW header, with data",
                "11": "4 DW header, with data",
            },
            "common_first_DW_fields": [
                "Fmt[1:0]", "Type[4:0]", "TC[2:0] (Traffic Class)",
                "TD (TLP Digest present)", "EP (Error / Poisoned)",
                "Attr[1:0] (Relaxed Ordering, No Snoop)",
                "Length[9:0] (DW count of data payload, max 1024 DW = 4 KB)",
            ],
            "memory_request_addressing": "Bit 29 of the Type/Fmt encoding distinguishes 32-bit (3 DW header) from 64-bit (4 DW header) addressing for Memory Requests.",
            "completion_header": "Always 3 DW header; includes Completer ID (Bus/Device/Function), Completion Status, Byte Count, Requester ID, Tag, Lower Address.",
        })
        d.setdefault("transaction_classes_split", [
            {"class": "Posted",
             "transactions": ["Memory Write", "Message", "Message with Data"],
             "completion": "no Completion expected"},
            {"class": "Non-Posted",
             "transactions": ["Memory Read", "I/O Read", "I/O Write",
                              "Configuration Read", "Configuration Write",
                              "Memory Read Lock"],
             "completion": "single or multiple Completions returned"},
            {"class": "Completion",
             "transactions": ["Cpl", "CplD", "CplLk", "CplDLk"],
             "completion": "response to a Non-Posted Request"},
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "Flow control is credit-based per Virtual Channel — transmitter must have sufficient credits (6 credit types: PH, PD, NPH, NPD, CplH, CplD) before sending a TLP.",
            "Data Link Layer guarantees TLP delivery via ACK/NAK + replay: receiver sends Ack DLLP (sequence number n) on successful LCRC; transmitter retires TLPs with sequence ≤ n from the Retry Buffer.",
            "On LCRC or framing error, receiver sends Nak DLLP (last good sequence number); transmitter replays all TLPs after that sequence from the Retry Buffer.",
            "REPLAY_TIMER and ACK_TIMER bound the worst-case wait before forcing replay; REPLAY_NUM rollover declares Link failure → LTSSM Recovery.",
            "Update Flow Control (UpdateFC) DLLPs are emitted periodically by the receiver to advertise running credits as buffer space is freed.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented", False)
        d.setdefault("addressing", {
            "memory_address_width_bits_32DW_header": 32,
            "memory_address_width_bits_64DW_header": 64,
            "configuration_address_format":
                "Bus(8) + Device(5) + Function(3) + Extended Register Number(4) + Register Number(6) — selects within 4 KB extended Config Space",
            "io_address_width_bits": 32,
            "requester_id_width_bits": 16,
            "completer_id_width_bits": 16,
            "tag_width_bits": 8,
            "sequence_number_width_bits": 12,
        })
        d.setdefault("frame_format", {
            "tlp_framing":
                "STP (K27.7) + Sequence Number (12b) + 2 Reserved + TLP header + optional data payload + 16-bit LCRC + END (K29.7) — or EDB (K30.7) for nullified TLP.",
            "dllp_framing":
                "SDP (K28.2) + DLLP type + DLLP-specific fields + 16-bit CRC + END (K29.7).",
            "ordered_sets":
                "Special non-DLLP/non-TLP symbol sequences started by COM (K28.5): TS1 / TS2 for Link Training, SKP for clock-tolerance compensation, EIOS / EIEOS / FTS for electrical idle and exit.",
        })
        _write(p, d)

    # L4 — wire-level Config Space (not a flat register file)
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d.setdefault("configuration_space_overview", {
            "pci_compatible_size_bytes":  256,
            "pcie_extended_size_bytes":  4096,
            "header_types": [
                {"type": "Type 0", "purpose": "Non-bridge devices (Endpoints, including Legacy + PCI Express Endpoints)."},
                {"type": "Type 1", "purpose": "Bridges and Switch Ports (virtual PCI-to-PCI bridges)."},
            ],
            "common_header_fields_first_4DW": [
                "Vendor ID (16b)", "Device ID (16b)", "Command (16b)", "Status (16b)",
                "Revision ID (8b)", "Class Code (24b)", "Cache Line Size (8b)",
                "Latency Timer (8b)", "Header Type (8b)", "BIST (8b)",
            ],
        })
        d.setdefault("type0_header_significant_fields", [
            "BAR0..BAR5 — Base Address Registers (memory or I/O)",
            "CardBus CIS Pointer",
            "Subsystem Vendor ID + Subsystem ID",
            "Expansion ROM Base Address",
            "Capabilities Pointer (offset of first Capability Structure)",
            "Interrupt Line + Interrupt Pin",
            "Min_Gnt + Max_Lat (legacy)",
        ])
        d.setdefault("type1_header_significant_fields", [
            "Primary Bus Number / Secondary Bus Number / Subordinate Bus Number",
            "I/O Base + I/O Limit",
            "Memory Base + Memory Limit",
            "Prefetchable Memory Base + Limit (32/64-bit)",
            "Bridge Control",
            "Capabilities Pointer",
        ])
        d.setdefault("pcie_capability_structure_offsets_relative", [
            {"offset_h": "00", "name": "PCI Express Capability List Register",  "width_bits": 32},
            {"offset_h": "02", "name": "PCI Express Capabilities Register",      "width_bits": 16},
            {"offset_h": "04", "name": "Device Capabilities Register",           "width_bits": 32},
            {"offset_h": "08", "name": "Device Control Register",                "width_bits": 16},
            {"offset_h": "0A", "name": "Device Status Register",                 "width_bits": 16},
            {"offset_h": "0C", "name": "Link Capabilities Register",             "width_bits": 32},
            {"offset_h": "10", "name": "Link Control Register",                  "width_bits": 16},
            {"offset_h": "12", "name": "Link Status Register",                   "width_bits": 16},
            {"offset_h": "14", "name": "Slot Capabilities Register",             "width_bits": 32},
            {"offset_h": "18", "name": "Slot Control Register",                  "width_bits": 16},
            {"offset_h": "1A", "name": "Slot Status Register",                   "width_bits": 16},
            {"offset_h": "1C", "name": "Root Control Register",                  "width_bits": 16},
            {"offset_h": "20", "name": "Root Status Register",                   "width_bits": 32},
        ])
        d.setdefault("pcie_extended_capability_structures", [
            "Advanced Error Reporting (AER) Capability",
            "Virtual Channel (VC) Capability",
            "Device Serial Number Capability",
            "Power Budgeting Capability",
        ])
        d.setdefault("data_link_layer_protocol_fields", {
            "sequence_number_width_bits": 12,
            "lcrc_width_bits": 16,
            "lcrc_polynomial":     "x^16 + x^12 + x^5 + 1 (CCITT CRC-16)",
            "dllp_crc_width_bits": 16,
        })
        d.setdefault("transaction_layer_protocol_fields", {
            "ecrc_width_bits": 32,
            "ecrc_polynomial":
                "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1 (IEEE 802.3 / Ethernet CRC32, polynomial 0x04C11DB7)",
            "max_payload_size_negotiated_bytes": [128, 256, 512, 1024, 2048, 4096],
        })
        d["notes"] = (
            "PCI Express does not have a flat protocol-level register map. "
            "Instead, each PCI Express device exposes a per-device "
            "Configuration Space — 256 bytes of PCI 2.3-compatible "
            "Configuration Space PLUS up to 4096 bytes of PCI Express "
            "Extended Configuration Space. Standard register layouts (Type "
            "0 header, Type 1 header, Capability Structures including PCI "
            "Express Capability, Power Management, MSI, Virtual Channel, "
            "Advanced Error Reporting, Device Serial Number, Power "
            "Budgeting) are defined in chapter 5 of the spec.")
        _write(p, d)

    # L5
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d["analog_digital_interface_present"] = True
        d["signaling_summary"] = (
            "Per-Lane low-voltage differential signaling on TXp/TXn "
            "(transmit) and RXp/RXn (receive) pairs. Both ends are "
            "AC-coupled — DC common-mode voltages at TX and RX can be "
            "different (process-technology independent). The Physical "
            "Layer Electrical Sub-Block specifies the differential "
            "transmitter (Section 4.3.3) and receiver (Section 4.3.4) "
            "characteristics. Gen 1 line rate is 2.5 Gb/s per Lane per "
            "direction. Embedded clock is recovered by the receiver from "
            "the 8b/10b-encoded stream (no separate clock line on the "
            "Link).")
        d.setdefault("transmitter_specs_minimum_canonical", {
            "unit_interval_ns_nominal":    0.4,
            "line_rate_GT_s":              2.5,
            "differential_pp_voltage_V":   {
                "typical": 0.8, "nominal_low": 0.4, "nominal_high": 1.2,
                "note": "specified as differential peak-to-peak; ≈ 800 mV typical",
            },
            "common_mode_voltage_V":       0.5,
            "ac_coupling_required":        True,
            "de_emphasis_dB":              -3.5,
            "output_impedance_ohm":        {"differential": 100, "single_ended": 50},
            "transmitter_disabled_state":
                "Electrical Idle — differential output transitions to undriven, common-mode held.",
        })
        d.setdefault("receiver_specs_minimum_canonical", {
            "differential_pp_voltage_V_min":  0.175,
            "differential_pp_voltage_V_max":  1.2,
            "input_impedance_ohm":            {"differential": 100, "single_ended": 50},
            "ac_coupled_input":               True,
            "electrical_idle_detect_required": True,
            "elastic_buffer_required":        True,
            "rx_eye_height_V_min":            0.175,
            "rx_eye_width_UI_min":            0.4,
        })
        d.setdefault("beacon_signaling", {
            "purpose":          "Wake the Link from L2 (deep sleep) when REFCLK is OFF.",
            "frequency_range":  "30 kHz to 500 MHz (modulated pulses)",
            "coupling":         "AC-coupled through ~75 nF capacitor",
            "example":
                "A 30 kHz BEACON signal includes 2 ns pulses through a 75 nF capacitor (per Figure 4-31).",
        })
        d.setdefault("electrical_idle", {
            "definition":
                "Differential transmitter output is undriven (high impedance or driven to common mode); no symbol stream produced.",
            "indicated_by":
                "EIOS (Electrical Idle Ordered Set) before the transmitter enters Electrical Idle.",
            "exit_indication":
                "EIEOS or FTS Ordered Sets, depending on the LTSSM exit state.",
        })
        d.setdefault("voltage_classes", [
            "Differential pp ≥ 0.8 V at TX nominal Gen 1",
            "Differential pp ≥ 0.175 V at RX minimum (after channel loss)",
            "DC common mode 0.5 V nominal at TX",
            "Receiver tolerates different DC common mode than TX due to AC coupling",
        ])
        d.setdefault("8b_10b_role_in_analog",
            "The 8b/10b code provides DC balance and guaranteed transition density so the receiver's clock-data-recovery (CDR) loop can lock; the special K-codes (notably COM K28.5) provide the symbol-alignment marker.")
        _write(p, d)

    # L6
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_ltssm", [
            {"name": "Detect",        "description": "Initial state after PERST# deassertion or unrecoverable Link error. Detect.Quiet → Detect.Active sub-states. Transmitter looks for a far-end receiver via differential detect circuitry."},
            {"name": "Polling",       "description": "Bit-lock + symbol-lock + Lane polarity inversion + Link / Lane number exchange. Sub-states: Polling.Active, Polling.Configuration, Polling.Compliance, Polling.Speed (Gen 1 stays at 2.5 GT/s)."},
            {"name": "Configuration", "description": "Link Width and Lane Number negotiation. Sub-states: Configuration.Linkwidth.Start, Configuration.Linkwidth.Accept, Configuration.Lanenum.Wait, Configuration.Lanenum.Accept, Configuration.Complete, Configuration.Idle."},
            {"name": "L0",            "description": "Normal operational state. TLPs and DLLPs flow in both directions; SKP ordered sets inserted every 1180-1538 symbols for clock-tolerance compensation."},
            {"name": "L0s",           "description": "Low-power state that can be entered + exited individually on TX or RX direction. Fast exit via FTS (Fast Training Sequence) ordered sets."},
            {"name": "L1",            "description": "Lower-power state requiring both directions in agreement. Slower exit than L0s; goes through Recovery.RcvrLock then Recovery.RcvrCfg then L0."},
            {"name": "L2",            "description": "Deep sleep; REFCLK may be off; main-power may remain. Re-entry requires Beacon (or WAKE# at system level) and a full LTSSM restart from Detect."},
            {"name": "Recovery",      "description": "Re-train an already-trained Link without going through full Detect/Polling/Configuration. Used to clear errors and to enter L0s/L1. Sub-states: Recovery.RcvrLock, Recovery.RcvrCfg, Recovery.Idle, Recovery.Speed (future)."},
            {"name": "Loopback",      "description": "Test mode; Loopback Master transmits patterns to Loopback Slave, which retransmits them back. Used for production test and debug."},
            {"name": "Disabled",      "description": "Transmitter outputs Electrical Idle on all Lanes; Link is electrically off. Re-entry to active state requires a state-machine reset or PERST# cycle."},
            {"name": "Hot Reset",     "description": "Software-initiated reset; goes from L0/Recovery to Detect after transmitting TS1 with Hot Reset bit set."},
        ])
        d.setdefault("fsm_states_data_link_layer", [
            {"name": "DL_Inactive", "description": "Reported when LTSSM is not in L0 / L0s / L1 / Recovery; Transaction Layer sees the Link as unusable."},
            {"name": "DL_Init",     "description": "Flow Control initialization phase (InitFC1 → InitFC2 DLLP exchange) on VC0."},
            {"name": "DL_Active",   "description": "Normal operation; TLP send/receive + ACK/NAK + UpdateFC."},
        ])
        d.setdefault("fsm_states_tlp_transmitter", [
            {"name": "TX_FORM",     "description": "Transaction Layer assembles the TLP header + payload + (optional) ECRC."},
            {"name": "TX_SEQ",      "description": "Data Link Layer attaches the next Sequence Number and computes the 16-bit LCRC."},
            {"name": "TX_FRAME",    "description": "Physical Layer 8b/10b-encodes the bytes, prepends STP, appends END (or EDB for nullified)."},
            {"name": "TX_RETRY",    "description": "Retry Buffer holds every transmitted TLP until acked. On NAK or REPLAY_TIMER expiration, replay starting from the first un-acked sequence number."},
        ])
        d.setdefault("fsm_states_tlp_receiver", [
            {"name": "RX_DECODE",   "description": "Physical Layer detects STP, captures the TLP bytes between STP and END, 8b/10b-decodes them."},
            {"name": "RX_LCRC",     "description": "Data Link Layer recomputes the 16-bit LCRC + verifies Sequence Number monotonicity."},
            {"name": "RX_ACKNAK",   "description": "If LCRC + Sequence are good, schedule an Ack DLLP; else NAK with the last good Sequence Number."},
            {"name": "RX_TL",       "description": "Hand the TLP to Transaction Layer for type-specific processing (Memory / I/O / Configuration / Message)."},
        ])
        d.setdefault("fsm_hints", {
            "trigger": "PERST# deassertion triggers Detect; receiver-detect circuit success transitions to Polling; symbol lock + TS exchange transitions to Configuration; Lane/width agreement transitions to L0.",
            "rule":    "Each transmitted TLP is added to the Retry Buffer with its assigned Sequence Number; the buffer entry is freed when an Ack DLLP for that (or a later) Sequence Number arrives. NAK or REPLAY_TIMER triggers replay.",
            "abort":   "REPLAY_NUM (replay-attempt counter) exceeding its threshold declares the Link as unrecoverable → LTSSM Recovery (or, if Recovery fails, Detect).",
        })
        d.setdefault("anti_deadlock_rule",
            "Credit-based flow control eliminates retries due to receiver buffer overflow. Six credit types (PH/PD/NPH/NPD/CplH/CplD) prevent a slow Completion class from blocking Posted or Non-Posted traffic. Completion credits are infinite at the Root Complex side to avoid deadlock with Non-Posted Requests.")
        d.setdefault("exit_from_reset_or_poweron",
            "PERST# deassertion → LTSSM enters Detect → Polling → Configuration → L0. During Configuration, both ends negotiate Link Width (by exchanging TS1/TS2 ordered sets) and assign Lane numbers. Flow Control initialization (InitFC1 → InitFC2 on VC0) runs as soon as L0 is reached; then the Data Link Layer transitions to DL_Active and the Transaction Layer is unblocked.")
        d.setdefault("default_ready_state_recommendation", {
            "TX_idle": "Electrical Idle (output undriven at common mode) when no symbols to send and not in L0.",
            "TX_L0":   "Continuously transmits IDL data symbol (00h scrambled + 8b/10b encoded) when in L0 with no TLP/DLLP pending.",
            "RX_idle": "Receiver decoders idle (or in low-power) when in L0s/L1/L2; must wake on FTS (L0s) or Recovery training (L1) or Beacon (L2).",
        })
        d.setdefault("configurations", [
            {"name": "x1 Link",   "description": "1 Lane per direction; simplest, lowest-bandwidth (2.5 GT/s = ~2 Gb/s effective per direction)."},
            {"name": "x2 / x4 / x8 / x12 / x16 / x32 Link",
             "description": "Aggregated Lanes; data bytes striped Lane-by-Lane starting at Lane 0. STP / SDP must be placed on Lane 0."},
        ])
        d.setdefault("timing_dependency_rule",
            "Each Lane runs its own 2.5 GHz symbol clock recovered locally; multi-Lane Links require a de-skew elastic buffer at the receiver to align Lane skew (up to several UI). The Physical Layer inserts SKP ordered sets every 1180-1538 symbols to allow elastic buffers to absorb ±300 ppm clock-tolerance drift.")
        _write(p, d)

    # L7
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d["test_debug_architecture_present"] = True
        d.setdefault("spec_provided_observability", [
            {"name": "LTSSM state probe",      "purpose": "Each Link's current LTSSM state (Detect / Polling / Configuration / L0 / L0s / L1 / L2 / Recovery / Disabled / Hot Reset / Loopback) is observable via Link Status Register + Link Capabilities Register + vendor-specific probe ports."},
            {"name": "TLP / DLLP capture",     "purpose": "Protocol analyzers tap into the Link via electrical interposers or via vendor-side mirrored ports."},
            {"name": "Retry Buffer monitor",   "purpose": "Per-Link retry-attempt counter (REPLAY_NUM) exposed as a status bit; retry-buffer occupancy is implementation-defined."},
            {"name": "Credit accounting",      "purpose": "Per-VC running credits for each of 6 credit types (PH/PD/NPH/NPD/CplH/CplD) — observable via VC Resource Status Register + UpdateFC traffic."},
            {"name": "8b/10b symbol stream",   "purpose": "Lane-by-Lane symbol stream is the lowest-level observable; bit/symbol/Lane-decoding errors are reported via Receiver Error in Link Status + AER Uncorrectable Error Status."},
            {"name": "Lane skew status",       "purpose": "Multi-Lane elastic-buffer occupancy; SKP-set insertion + extraction rate is observable in the Physical Layer."},
            {"name": "Link Width + Speed",     "purpose": "Negotiated width and current speed observable in Link Status Register."},
            {"name": "Slot Status + Slot Capabilities", "purpose": "Hot-plug event observability (Card Present, Power Indicator, Attention Indicator, MRL Sensor)."},
        ])
        d.setdefault("error_detection_mechanisms", [
            "8b/10b decode errors — invalid 10-bit symbol or running-disparity violation; reported as Receiver Error.",
            "TLP LCRC error (16-bit) — Data Link Layer triggers NAK + replay.",
            "TLP ECRC error (32-bit, optional) — Transaction Layer logs in AER Uncorrectable Error Status.",
            "DLLP CRC error (16-bit) — DLLP discarded.",
            "Sequence Number error — TLP arriving out of expected sequence; receiver NAKs.",
            "REPLAY_NUM rollover — repeated NAK / timeout; declares Link as failed → LTSSM Recovery / Detect.",
            "Completion Timeout — Non-Posted Request did not get a Completion within the timeout window.",
            "Unsupported Request (UR), Completer Abort (CA), Configuration Retry Status (CRS) — abnormal Completion Status codes.",
        ])
        if _empty(d.get("test_modes")):  # force when upstream emits None/[]/empty
            d["test_modes"] = [
                {"name": "Compliance Pattern",  "purpose": "LTSSM Polling.Compliance sub-state transmits a defined compliance pattern for electrical characterization."},
                {"name": "Loopback",            "purpose": "Loopback Master transmits a known pattern; Loopback Slave retransmits it back. Used for receiver-eye testing."},
                {"name": "Hot Reset",           "purpose": "Triggers Link re-training via a TS1 with the Hot Reset bit set."},
                {"name": "Disable Link",        "purpose": "Force the Link into Electrical Idle for power / characterization."},
            ]
        d.setdefault("interrupt_or_event_sources", [
            {"event": "Hot-plug Card-Present change",   "trigger": "Card insertion / removal sensed by slot circuitry."},
            {"event": "Link Up / Link Down",            "trigger": "LTSSM enters / exits L0."},
            {"event": "Correctable Error",              "trigger": "Per AER capability; e.g. Receiver Error, Bad TLP, Bad DLLP, REPLAY_NUM rollover."},
            {"event": "Uncorrectable Error (Fatal/Non-Fatal)", "trigger": "Per AER capability; e.g. Poisoned TLP Received, Flow Control Protocol Error, Completion Timeout, Completer Abort."},
            {"event": "Root Error reporting",           "trigger": "RC aggregates First / Next Uncorrectable Error sources via Root Error Status."},
            {"event": "Power Management Event (PME)",   "trigger": "Endpoint generates PM_PME Message; routed up to RC."},
        ])
        d.setdefault("notes",
            "PCI Express Rev 1.0 specifies a comprehensive in-band error-detection framework (CRC + Sequence Number + replay) and explicit AER (Advanced Error Reporting) extended capability for fine-grained error logging + signaling. JTAG / scan / BIST are NOT specified at the protocol level — those are integrator-side concerns at the SoC.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "SYMBOL_WIDTH_raw_bits": 8,
                "SYMBOL_WIDTH_encoded_bits": 10,
                "ENCODING": "8b/10b",
                "LANE_WIDTH_PER_DIRECTION_DIFF_PAIRS": 1,
                "SUPPORTED_LINK_WIDTHS_LANES": [1, 2, 4, 8, 12, 16, 32],
                "GEN1_LINE_RATE_GT_S": 2.5,
                "UNIT_INTERVAL_NS": 0.4,
                "GEN1_PER_LANE_RAW_BW_Gbps": 2.5,
                "GEN1_PER_LANE_EFFECTIVE_BW_Gbps": 2.0,
                "TLP_SEQUENCE_NUMBER_WIDTH_BITS": 12,
                "TLP_LCRC_WIDTH_BITS": 16,
                "DLLP_CRC_WIDTH_BITS": 16,
                "ECRC_WIDTH_BITS_OPTIONAL": 32,
                "TLP_HEADER_DW_OPTIONS": [3, 4],
                "TLP_HEADER_BYTES_3DW": 12,
                "TLP_HEADER_BYTES_4DW": 16,
                "TLP_DATA_PAYLOAD_LENGTH_FIELD_WIDTH_BITS": 10,
                "TLP_MAX_PAYLOAD_DW": 1024,
                "TLP_MAX_PAYLOAD_BYTES": 4096,
                "MAX_PAYLOAD_SIZE_NEGOTIATED_BYTES": [128, 256, 512, 1024, 2048, 4096],
                "FMT_FIELD_WIDTH_BITS": 2,
                "TYPE_FIELD_WIDTH_BITS": 5,
                "TC_FIELD_WIDTH_BITS": 3,
                "ATTR_FIELD_WIDTH_BITS": 2,
                "REQUESTER_ID_WIDTH_BITS": 16,
                "COMPLETER_ID_WIDTH_BITS": 16,
                "TAG_WIDTH_BITS": 8,
                "BUS_NUMBER_WIDTH_BITS": 8,
                "DEVICE_NUMBER_WIDTH_BITS": 5,
                "FUNCTION_NUMBER_WIDTH_BITS": 3,
                "EXT_REGISTER_NUMBER_WIDTH_BITS": 4,
                "REGISTER_NUMBER_WIDTH_BITS": 6,
                "MAX_VIRTUAL_CHANNELS": 8,
                "MAX_TRAFFIC_CLASSES": 8,
                "FLOW_CONTROL_CREDIT_TYPES": 6,
                "PCI_CFG_SPACE_BYTES": 256,
                "PCIE_EXT_CFG_SPACE_BYTES": 4096,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("special_symbols_8b10b", {
            "COM": {"encoding": "K28.5", "name": "Comma",            "purpose": "Lane and Link initialization and management; symbol alignment marker."},
            "STP": {"encoding": "K27.7", "name": "Start TLP",        "purpose": "Marks the start of a Transaction Layer Packet."},
            "SDP": {"encoding": "K28.2", "name": "Start DLLP",       "purpose": "Marks the start of a Data Link Layer Packet."},
            "END": {"encoding": "K29.7", "name": "End",              "purpose": "Marks the end of a TLP or DLLP."},
            "EDB": {"encoding": "K30.7", "name": "End Bad",          "purpose": "Marks the end of a nullified TLP."},
            "PAD": {"encoding": "K23.7", "name": "Pad",              "purpose": "Used in Framing and Link Width and Lane ordering negotiations."},
            "SKP": {"encoding": "K28.0", "name": "Skip",             "purpose": "Compensates for different bit rates between two communicating ports (clock-tolerance)."},
            "FTS": {"encoding": "K28.1", "name": "Fast Training Sequence", "purpose": "Used within an ordered-set to exit from L0s to L0."},
            "IDL": {"encoding": "K28.3", "name": "Idle",             "purpose": "Electrical Idle symbol used in the Electrical Idle Ordered Set."},
        })
        d.setdefault("lcrc_polynomial", {
            "name":          "CRC-16-CCITT (TLP LCRC + DLLP CRC)",
            "polynomial":    "x^16 + x^12 + x^5 + 1",
            "hex":           "0x1021",
            "covers":        "TLP: Sequence Number + TLP body. DLLP: DLLP type + DLLP-specific fields.",
            "initial_value": "0xFFFF",
            "width_bits":    16,
        })
        d.setdefault("ecrc_polynomial", {
            "name":          "CRC-32 (IEEE 802.3 / Ethernet)",
            "polynomial":    "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1",
            "hex":           "0x04C11DB7",
            "covers":        "End-to-end TLP integrity (optional, when TD = 1 in the TLP header).",
            "initial_value": "0xFFFFFFFF",
            "width_bits":    32,
        })
        d.setdefault("fmt_type_canonical_encodings", {
            "fmt_encoding": {
                "00": "3 DW header, no data",
                "01": "4 DW header, no data",
                "10": "3 DW header, with data",
                "11": "4 DW header, with data",
            },
            "type_encoding_examples": {
                "MRd_32b_addr":   "Fmt=00, Type=00000",
                "MRd_64b_addr":   "Fmt=01, Type=00000",
                "MWr_32b_addr":   "Fmt=10, Type=00000",
                "MWr_64b_addr":   "Fmt=11, Type=00000",
                "IORd":           "Fmt=00, Type=00010",
                "IOWr":           "Fmt=10, Type=00010",
                "CfgRd0":         "Fmt=00, Type=00100",
                "CfgWr0":         "Fmt=10, Type=00100",
                "CfgRd1":         "Fmt=00, Type=00101",
                "CfgWr1":         "Fmt=10, Type=00101",
                "Cpl":            "Fmt=00, Type=01010",
                "CplD":           "Fmt=10, Type=01010",
            },
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "is_serial":                True,
            "is_differential":          True,
            "is_dual_simplex":          True,
            "embedded_clock":           True,
            "encoding":                 "8b/10b",
            "lane_data_striping":       "Lane 0 carries the first byte of any TLP/DLLP; STP/SDP must be placed on Lane 0.",
            "framing_tlp_start":        "K27.7 (STP)",
            "framing_tlp_end_good":     "K29.7 (END)",
            "framing_tlp_end_bad":      "K30.7 (EDB)",
            "framing_dllp_start":       "K28.2 (SDP)",
            "framing_dllp_end":         "K29.7 (END)",
            "scrambling_polynomial":    "x^16 + x^5 + x^4 + x^3 + 1 (data is scrambled before 8b/10b encoding; SKP/COM/training-set symbols are NOT scrambled)",
            "refclk_freq_MHz_nominal":  100,
            "ssc_tolerance_percent":    0.5,
            "clock_tolerance_ppm":      300,
            "skp_insertion_interval_symbols": [1180, 1538],
        })
        d.setdefault("default_signal_values_when_idle", {
            "TX_in_Electrical_Idle": "Output driven to common-mode; no symbol stream; receiver detects via low-pass differential threshold.",
            "TX_in_L0_no_packet":    "Continuously transmit 00h (Logical Idle) on all Lanes, scrambled and 8b/10b-encoded; SKP ordered set inserted every 1180-1538 symbols.",
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("line_rate_waveform", {
            "Gen1_line_rate_GT_s":   2.5,
            "unit_interval_ns":      0.4,
            "symbol_period_ns":      4.0,
            "encoding":              "8b/10b — 8 source bits become 10 wire bits; embedded clock + DC balance.",
            "raw_per_lane_bps":      "2.5 Gb/s",
            "effective_per_lane_bps": "2.0 Gb/s (after 8b/10b 20% overhead)",
            "aggregate_x16_per_direction_Gbps": "40 Gb/s effective",
        })
        d.setdefault("packet_framing_waveform", {
            "tlp_framing":
                "STP (K27.7) → 12-bit Sequence Number → TLP header (3 or 4 DW) → optional data payload → 16-bit LCRC → END (K29.7), or EDB (K30.7) for nullified TLP.",
            "dllp_framing":
                "SDP (K28.2) → DLLP type byte + DLLP-specific fields → 16-bit CRC → END (K29.7).",
            "lane_placement":
                "STP / SDP MUST be placed on Lane 0 when the Link is wider than x1.",
            "logical_idle":
                "When no TLP / DLLP / ordered-set is being transmitted, IDL data character (00h) is sent on all Lanes, scrambled and 8b/10b-encoded.",
        })
        d.setdefault("ordered_sets", {
            "TS1":  {"length_symbols": 16, "purpose": "Polling and Configuration training; carries Link Number, Lane Number, N_FTS count, Data Rate field, training control bits.", "lead_symbol": "COM (K28.5)"},
            "TS2":  {"length_symbols": 16, "purpose": "Final-handshake training set — confirms Lane / Link agreement before transitioning to L0.", "lead_symbol": "COM (K28.5)"},
            "SKP":  {"length_symbols": 4,  "purpose": "Skip ordered set; receiver elastic buffer adds/removes one SKP symbol to absorb ±300 ppm clock-tolerance.", "lead_symbol": "COM (K28.5)"},
            "FTS":  {"length_symbols": "configurable (N_FTS)", "purpose": "Fast Training Sequence — used to exit L0s to L0.", "lead_symbol": "COM (K28.5)"},
            "EIOS": {"length_symbols": 4,  "purpose": "Electrical Idle Ordered Set — transmitted just before TX enters Electrical Idle.", "lead_symbol": "COM (K28.5)"},
            "EIEOS":{"length_symbols": 16, "purpose": "Electrical Idle Exit Ordered Set — used on exit from Electrical Idle to re-acquire symbol lock.", "lead_symbol": "COM (K28.5)"},
        })
        d.setdefault("ltssm_transition_trigger_waveform", {
            "Detect_to_Polling":        "Receiver-detect circuit senses far-end termination on the differential pair.",
            "Polling_to_Configuration": "Both ends have observed sufficient consecutive TS1 / TS2 ordered sets with valid Lane/Link numbers.",
            "Configuration_to_L0":      "Lane width + Lane number agreement complete; both ends have sent N consecutive TS2 with no further training mods.",
            "L0_to_L0s":                "Either end transmits EIOS then enters Electrical Idle on its TX direction. Independent per direction.",
            "L0s_to_L0":                "Transmitter sends N_FTS Fast Training Sequences + SKP → both ends in symbol lock → return to L0.",
            "L0_to_L1":                 "Both ends agree via PM_Enter_L1 DLLPs; LTSSM transitions through Recovery briefly.",
            "L1_to_L0":                 "Upstream component initiates Recovery; Link re-trains then returns to L0.",
            "L0_to_L2":                 "Software-driven via PM_Enter_L23 DLLPs; TX enters Electrical Idle; REFCLK may stop.",
            "L2_to_Detect":             "Beacon (or WAKE# at system level) brings PERST# de-assertion or LTSSM reset; full re-train from Detect.",
        })
        d.setdefault("clock_tolerance_compensation", {
            "skp_insertion_interval_symbols_min": 1180,
            "skp_insertion_interval_symbols_max": 1538,
            "purpose": "Allows the receive elastic buffer to absorb or generate one SKP symbol per interval, compensating for up to ±300 ppm clock-rate mismatch between TX and RX.",
        })
        d.setdefault("general_timing_rule",
            "PCI Express is fundamentally character-timed at 4 ns per 10b symbol on each Lane (Gen 1). All higher-level state machines (LTSSM sub-states, FC initialization, Replay) are specified in 'Symbol Times' to allow scaling to future generations where the symbol period changes.")
        d.setdefault("transmitter_eye_diagram_reference",
            "Figure 4-32 — Minimum Transmitter Timing and Voltage Output Compliance Specification.")
        d.setdefault("receiver_eye_diagram_reference",
            "Figure 4-34 — Minimum Receiver Eye Timing and Voltage Compliance Specification.")
        d.setdefault("voltage_levels", {
            "TX_diff_pp_V_typical":  0.8,
            "RX_diff_pp_V_min":      0.175,
            "RX_eye_width_UI_min":   0.4,
            "TX_common_mode_V":      0.5,
            "ac_coupling":           "Required at both ends; common-mode at TX and RX can differ.",
        })
        _write(p, d)

    # L9
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level + transaction-level + software-interface specification for a third-generation, point-to-point, layered, differential serial I/O interconnect. Defines the protocol between any pair of PCI Express components (Root Complex / Switch / Endpoint / PCI Express-to-PCI Bridge) connected through a tree-shaped hierarchy of point-to-point Links. Card-edge connectors, slot mechanicals, and add-in card power delivery are NOT in the Base Spec — covered by the companion PCI Express Card Electromechanical Specification.")
        d.setdefault("topology_description",
            "Hierarchy (tree) rooted at a Root Complex (RC). Below the RC: any combination of Switches and PCI Express-to-PCI/PCI-X Bridges. Leaf nodes are Endpoints (either Legacy or PCI Express Endpoints). Each Link is a point-to-point dual-simplex connection between exactly two components. There is no shared-medium 'bus' — every PCIe Link is a private wire pair.")
        d.setdefault("integration_overview", {
            "host_count_per_hierarchy":         1,
            "max_lane_width":                   32,
            "lane_widths_supported":            [1, 2, 4, 8, 12, 16, 32],
            "gen1_line_rate_GT_s":              2.5,
            "host_side_register_spec":          "PCI Configuration Space (256 B) + PCI Express Extended Configuration Space (up to 4096 B per device); Type 0 for non-bridges, Type 1 for bridges/switch ports.",
            "device_side_interface":            "Each device exposes its Configuration Space via Configuration Read/Write TLPs routed by Bus/Device/Function number.",
            "wire_count_per_lane_per_dir":      2,
            "lanes_are_lock-step":              "All Lanes of a Link run at the same line rate; data is striped Lane-by-Lane starting at Lane 0.",
            "ac_coupling_required":             True,
            "refclk_freq_MHz":                  100,
            "refclk_sharing":                   "Common Clock (shared REFCLK) OR Separate Clock (independent crystals + 8b/10b clock recovery).",
        })
        d.setdefault("interface_categories", [
            "Root Complex (RC) — top of the hierarchy; connects CPU + memory subsystem to PCIe fabric; one or more Root Ports.",
            "Switch — logical assembly of virtual PCI-to-PCI bridges; aggregates multiple downstream Endpoints under one upstream port.",
            "PCI Express Endpoint — modern PCIe-only Endpoint; Type 0 header; must not generate I/O Requests or support Lock semantics.",
            "Legacy Endpoint — PCIe Endpoint with PCI-style behaviors permitted (may support I/O space + Lock semantics for legacy software).",
            "PCI Express-to-PCI/PCI-X Bridge — translates between PCIe protocol and legacy PCI / PCI-X bus.",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Point-to-point Link between RC and a single Endpoint.",
            "Tree via Switch — one upstream port + N downstream ports.",
            "Cascaded Switches — multi-level hierarchy.",
            "PCI Express-to-PCI Bridge for legacy peripherals.",
            "Optional: Advanced Peer-to-Peer Communication (Cross-Link) between two RCs (separate spec).",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "TX defaults to Electrical Idle outside of L0 / L0s; in L0 with no TLP/DLLP queued, TX continuously emits IDL (00h scrambled + 8b/10b encoded). PERST# is asserted (LOW) while system power is unstable.")
        d.setdefault("soc_dependent_items", [
            "Choice of integrated Root Complex vs external bridge.",
            "PCIe PHY transceiver implementation (analog: TX driver + RX equalizer + CDR + de-emphasis driver).",
            "REFCLK source (crystal + PLL; SSC-tolerant for Common Clock topology).",
            "PERST# generation (typically derived from Power Good).",
            "WAKE# routing (open-drain wired-OR across slots).",
            "Hot-plug slot control (Power Indicator + Attention Indicator + MRL Sensor + Card Present).",
            "Interrupt controller routing for MSI / MSI-X / INTx-Message emulation.",
            "DMA engine wiring for Memory Read / Write TLPs.",
            "Power-management policy state (D0..D3 device states) mapped to L0..L2 link states.",
        ])
        d.setdefault("low_power_modes", {
            "L0":  "Active — full operation.",
            "L0s": "Standby per direction; sub-µs exit via FTS.",
            "L1":  "Link inactive but trained; slower exit through Recovery; sub-millisecond.",
            "L2":  "Deep sleep; REFCLK off; Beacon required to wake.",
            "L3":  "Main power off.",
        })
        d.setdefault("device_classes_examples", [
            "Graphics Accelerator (PCIe Endpoint, typically x16)",
            "Network Interface Controller (PCIe Endpoint, x1 / x4 / x8)",
            "Storage Controller / RAID (PCIe Endpoint, x4 / x8)",
            "PCIe-to-USB Bridge",
            "PCIe-to-PCI/PCI-X Bridge for legacy add-ins",
            "Switch fabric for multi-Endpoint backplanes",
        ])
        _write(p, d)

    # L10
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - the spec defines detailed compliance behaviors "
            "(Chapter 4 electrical + LTSSM, Chapter 2 Transaction Layer, "
            "Chapter 3 Data Link Layer, Chapter 5 software / Configuration "
            "Space, Chapter 6 power management) that map to a formal "
            "PCI-SIG Compliance Program, but the spec itself does not "
            "include a testbench.")
        # v0.1.90 — FORCE-clear hallucinated per-opcode `test_cases` +
        # `extraction_evidence`, mirroring jtag_protocol_synth (which carries
        # the same fix). The upstream `gen_l10_test_cases` in
        # phase1_doc_one_shot_runner.py scans L3.opcodes and stamps a
        # happy-path + pre-wake-false case per opcode with an `opcode_hex`
        # field. PCIe is a LAYERED PACKET protocol (TLP / DLLP / LTSSM ordered
        # sets), NOT byte-opcode-driven — those auto-stamped `opcode_hex: 0x11`
        # entries are hallucinations flagged by l_doc_parity_diff's
        # HALLUCINATION_HEURISTICS. They were previously masked because a PCIe
        # card carries a JTAG TAP and the (now primary-subject-gated) JTAG
        # synth happened to clear L10 first; the v0.1.90 primary-subject guard
        # correctly stops JTAG firing on a PCIe doc, exposing this latent gap.
        # Chip-AGNOSTIC doctrine (per jtag_protocol_synth): every
        # protocol-specific synth that is NOT byte-opcode-driven must clear
        # gen_l10_test_cases output.
        d["test_cases"] = []
        d["extraction_evidence"] = {}
        d.setdefault("derived_compliance_test_categories", [
            "LTSSM bring-up: Detect → Polling (TS1 exchange) → Configuration (Link width + Lane number negotiation) → L0.",
            "Receiver detection on TX termination via differential-detect circuit.",
            "Polling.Compliance pattern at 2.5 GT/s (for electrical eye-diagram tests).",
            "Polling.Configuration TS1 / TS2 ordered set exchange and N_FTS field negotiation.",
            "Configuration: Link Width negotiation for x1 / x2 / x4 / x8 / x12 / x16 / x32.",
            "Configuration: Lane reversal (Lane 0 ↔ Lane N-1) and polarity inversion handling.",
            "L0: TLP roundtrip — Memory Write (Posted) end-to-end with no Completion.",
            "L0: TLP roundtrip — Memory Read (Non-Posted) + Completion with data.",
            "L0: Configuration Read / Write Type 0 + Type 1 routing.",
            "L0: I/O Read / Write (Legacy Endpoints only).",
            "L0: Message Request and Message Request with Data routing (INTx emulation, PM, Error, Vendor-defined).",
            "Data Link Layer: 16-bit LCRC error injection — receiver must NAK + transmitter must replay from Retry Buffer.",
            "Data Link Layer: Sequence-Number mismatch — receiver discards / NAKs.",
            "Data Link Layer: REPLAY_TIMER expiration triggers automatic replay.",
            "Data Link Layer: REPLAY_NUM rollover declares Link as failed → LTSSM Recovery.",
            "Flow Control: InitFC1 / InitFC2 / UpdateFC DLLP exchange; six credit types (PH/PD/NPH/NPD/CplH/CplD).",
            "Flow Control: Transmitter must NOT send a TLP without sufficient credits.",
            "Virtual Channel: VC0 mandatory presence; additional VC1..VC7 configured via VC Capability.",
            "Traffic Class to VC Mapping: software-configurable via VC Resource Control Register.",
            "Max_Payload_Size negotiation: 128 / 256 / 512 / 1024 / 2048 / 4096 bytes.",
            "ECRC (optional): TD = 1 in header; 32-bit Digest; receiver verifies.",
            "Completion Timeout: Non-Posted Request without Completion triggers timer.",
            "Unsupported Request, Completer Abort, Configuration Retry Status Completion encoding.",
            "L0 → L0s transition + exit via FTS within N_FTS Symbol Times.",
            "L0 → L1 transition via PM_Enter_L1 DLLP + Recovery + return to L0.",
            "L1 → L0 exit via Recovery sequence.",
            "L2 entry via PM_Enter_L23 DLLP; REFCLK may stop.",
            "L2 → Detect re-entry via Beacon (or WAKE# at system level).",
            "Hot Reset: TS1 with Hot Reset bit set; downstream device returns to Detect.",
            "Native Hot-Plug: card-insertion / removal handled via Slot Capability + Slot Status registers.",
            "MSI generation: posted Memory Write to designated address triggers host interrupt.",
            "Error reporting via Advanced Error Reporting (AER) capability — Correctable / Uncorrectable Non-Fatal / Uncorrectable Fatal classes.",
            "Switch behavior: forward TLPs unmodified between any two ports; do not split packets.",
            "Loopback test mode: master → slave → master pattern echo for eye / electrical characterization.",
        ])
        _write(p, d)

    # L11
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d.setdefault("otp_equivalent_factory_burned_fields", [
            {"field": "Vendor ID",      "width_bits": 16, "location": "Type 0/1 Config Space Header offset 00h", "note": "Assigned by PCI-SIG to the silicon vendor."},
            {"field": "Device ID",      "width_bits": 16, "location": "Type 0/1 Config Space Header offset 02h", "note": "Per-product identifier chosen by the vendor."},
            {"field": "Revision ID",    "width_bits": 8,  "location": "Type 0/1 Config Space Header offset 08h", "note": "Vendor's silicon revision."},
            {"field": "Class Code",     "width_bits": 24, "location": "Type 0/1 Config Space Header offset 09h", "note": "Base Class + Sub-Class + Programming Interface; identifies the device category."},
            {"field": "Subsystem Vendor ID + Subsystem ID", "width_bits": 32, "location": "Type 0 Config Space Header offset 2Ch", "note": "Per-board subsystem identification (typically the integrator's IDs)."},
            {"field": "Device Serial Number Capability",    "width_bits": 64, "location": "PCI Express Extended Capability (chapter 5.12)", "note": "Optional, unique 64-bit IEEE EUI-64 identifier."},
            {"field": "MSI / MSI-X Address + Data templates","width_bits": 32, "location": "MSI / MSI-X Capability Structures", "note": "Some templates may be silicon-fixed; address/data values themselves are programmed at runtime."},
        ])
        d["notes"] = (
            "PCI Express Rev 1.0 does not specify OTP / fuse content as a "
            "protocol concept. Practically, every PCIe silicon device must "
            "burn Vendor ID + Device ID + Revision ID + Class Code into "
            "ROM / OTP / metal-mask so that Configuration Reads to offsets "
            "00h-0Bh return the correct identifiers immediately after "
            "PERST# deassertion (before any software-programmed register "
            "has been written). The optional Device Serial Number "
            "Capability (Section 5.12) is also typically OTP-equivalent.")
        _write(p, d)

    # L12
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("link_bring_up_sequence_ltssm", [
            "1. PERST# deassertion. LTSSM enters Detect.Quiet.",
            "2. Detect.Active — each Lane's transmitter probes the differential pair; receiver-detect circuit senses far-end termination.",
            "3. Transition to Polling.Active — transmitter sends continuous TS1 ordered sets with Link Number = PAD, Lane Number = PAD.",
            "4. Polling.Configuration — both ends have observed N consecutive TS1 ordered sets; bit + symbol lock acquired; polarity inversion (if any) detected and corrected.",
            "5. Transition to Configuration.Linkwidth.Start — upstream port proposes a Link Number; downstream accepts via TS2.",
            "6. Configuration.Lanenum.Wait / .Accept — Lane numbers assigned starting at Lane 0; Lane reversal handled if upstream Lane 0 maps to downstream Lane N-1.",
            "7. Configuration.Complete — N consecutive TS2 ordered sets sent with the agreed Link / Lane numbers.",
            "8. Configuration.Idle — both ends transmit Logical Idle data; transition to L0 once both ends see Idle.",
            "9. L0 — Link is now in normal operation; Data Link Layer can begin Flow Control initialization.",
        ])
        d.setdefault("flow_control_initialization_sequence", [
            "1. Data Link Layer transitions to DL_Init upon LTSSM L0.",
            "2. Both ends exchange InitFC1 DLLPs on VC0 advertising initial credits for PH / PD / NPH / NPD / CplH / CplD.",
            "3. After receiving InitFC1 from the far end, each side transmits InitFC2 DLLPs confirming credits.",
            "4. Once both InitFC2 phases complete, Data Link Layer transitions to DL_Active.",
            "5. Transaction Layer is unblocked; TLPs may begin to flow on VC0.",
        ])
        d.setdefault("tlp_transmission_sequence", [
            "1. Transaction Layer assembles a TLP: header (Fmt / Type / TC / Attr / Length / Requester ID / Tag / Address) + optional data payload + optional 32-bit ECRC (when TD = 1).",
            "2. Transaction Layer confirms sufficient Flow Control credits for the relevant VC + credit type.",
            "3. Data Link Layer assigns the next 12-bit Sequence Number; computes 16-bit LCRC over Sequence Number + TLP body.",
            "4. Copy of the TLP is stored in the Retry Buffer with its Sequence Number.",
            "5. Physical Layer 8b/10b-encodes the bytes; frames the TLP with STP (start) and END (end); inserts on Lane 0 for the first byte; stripes across Lanes for wider Links.",
            "6. Far end Physical Layer decodes the symbols; Data Link Layer verifies LCRC + Sequence Number monotonicity.",
            "7. Receiver schedules an Ack DLLP carrying the latest good Sequence Number.",
            "8. Ack arrives at transmitter; transmitter retires TLPs with Sequence ≤ acked from the Retry Buffer; updates Flow Control credits.",
        ])
        d.setdefault("nak_replay_sequence", [
            "1. Receiver detects an LCRC error (or framing error) on TLP with Sequence n.",
            "2. Receiver sends Nak DLLP carrying the last good Sequence Number (n - 1).",
            "3. Transmitter receives Nak; sets the Retry Buffer read pointer to the first TLP after the acked sequence.",
            "4. Transmitter retransmits every TLP in the Retry Buffer from that point onward, in original order, with the original Sequence Numbers.",
            "5. REPLAY_NUM counter increments; if it crosses the per-spec threshold, the Link is declared as failed and LTSSM transitions to Recovery.",
        ])
        d.setdefault("configuration_enumeration_sequence", [
            "1. After L0 + Data Link Layer DL_Active, host firmware (BIOS / UEFI / OS) issues Configuration Read Type 0 to Bus = 0, Device = 0, Function = 0, looking for the Root Complex's own Type 1 header.",
            "2. Host walks the hierarchy by probing each downstream Bus / Device / Function. A Vendor ID of FFFFh indicates 'no device present'.",
            "3. For each discovered device, host reads the Type 0 (Endpoint) or Type 1 (Bridge / Switch Port) header, BAR sizes, and Capability List.",
            "4. Host assigns Bus Number ranges to each Switch Port / Bridge (Primary / Secondary / Subordinate).",
            "5. Host programs BARs with non-overlapping address ranges in Memory and I/O space.",
            "6. Host writes Command register Memory Space Enable / Bus Master Enable / I/O Space Enable as appropriate.",
            "7. Host examines PCI Express Capability Structure to learn Link Capabilities + Device Capabilities + Slot Capabilities; configures Max_Payload_Size + Max_Read_Request_Size + ASPM.",
        ])
        d.setdefault("low_power_l0s_entry_exit_sequence", [
            "1. Transmitter side of the Link has nothing to send for a programmable idle period.",
            "2. Transmitter sends EIOS (Electrical Idle Ordered Set), then enters Electrical Idle on its TX direction.",
            "3. Far-end receiver detects Electrical Idle; its LTSSM enters L0s.",
            "4. When TX has a new packet to send, it transmits N_FTS Fast Training Sequences + SKP to re-acquire bit / symbol lock at the far end.",
            "5. Both ends return to L0 within a few hundred ns.",
        ])
        d.setdefault("low_power_l1_entry_exit_sequence", [
            "1. Either Data Link Layer (via PM_Active_State_Request_L1) or software (via Link Control Register) requests L1 entry.",
            "2. Both ends agree by exchanging PM_Active_State_NAK or PM_Request_Ack DLLPs.",
            "3. LTSSM transitions through Recovery briefly, then to L1; both TX directions enter Electrical Idle.",
            "4. Exit: upstream initiates Recovery training; LTSSM transitions back to L0 via Recovery.RcvrLock → Recovery.RcvrCfg → Recovery.Idle → L0.",
        ])
        d.setdefault("hot_reset_sequence", [
            "1. Software sets the Secondary Bus Reset bit in a Switch Port / Root Port Bridge Control Register.",
            "2. The Port transmits TS1 ordered sets with the Hot Reset bit (TS1[6]) asserted.",
            "3. Downstream device's LTSSM transitions to Detect.",
            "4. Software clears the bit; LTSSM re-trains through Polling / Configuration back to L0.",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d.setdefault("lab_measurement_targets_from_spec", [
            {"name": "Eye diagram per Lane",       "purpose": "Verify transmitter output meets Figure 4-32 minimum eye-height/width; verify receiver input meets Figure 4-34 minimum eye."},
            {"name": "Jitter budget",              "purpose": "Random jitter + deterministic jitter must be within the Gen 1 budget so the BER stays below 10^-12 after CDR."},
            {"name": "De-emphasis level",          "purpose": "≈ -3.5 dB de-emphasis on the first symbol after a transition; verifies the transmitter's high-frequency boost."},
            {"name": "Common-mode voltage",        "purpose": "≈ 0.5 V at TX; AC coupling means RX can have a different common mode."},
            {"name": "Electrical Idle detect threshold", "purpose": "RX must distinguish Electrical Idle from active signaling reliably."},
            {"name": "REFCLK jitter + frequency",  "purpose": "100 MHz nominal; SSC modulation ≤ 0.5%; jitter budget split between transmitter PLL and reference."},
            {"name": "LTSSM oscilloscope decode",  "purpose": "Capture TS1 / TS2 / SKP / FTS / EIOS ordered sets to debug Link Training failures."},
            {"name": "Protocol analyzer (TLP/DLLP)", "purpose": "Off-the-shelf PCIe protocol analyzers (LeCroy, Keysight) tap the Link via interposers and decode all packet classes for compliance testing."},
        ])
        d["notes"] = (
            "PCI Express Rev 1.0 itself does NOT specify an on-chip "
            "calibration loop. Compliance testing is done with external "
            "equipment (oscilloscope, BERT, protocol analyzer, vector "
            "signal generator) per PCI-SIG Compliance Program procedures. "
            "PHY transceivers in modern silicon implement closed-loop "
            "adaptive equalization + clock recovery + impedance trim — "
            "those are per-implementation, not protocol-defined.")
        _write(p, d)

    # L14
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "PCI Express Base Specification Revision 1.0 (April 29, 2002)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "PCI Local Bus Specification 2.3 (predecessor parallel-bus standard; PCIe inherits its software model)",
                "PCI-X 1.0 / 2.0 (predecessor parallel-bus standard)",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "1.0",
                 "summary":
                    "First production PCI Express base specification. Introduces serial differential 2.5 GT/s point-to-point Links, 8b/10b encoding, layered Transaction/DataLink/Physical architecture, TLP + DLLP packetization, credit-based flow control, Virtual Channels (1-8) + Traffic Classes (8), Switch + Endpoint + Root Complex device classes, LTSSM, ASPM (L0s + L1) + software-controlled link PM (L2/L3), native hot-plug, Advanced Error Reporting (AER), and PCI-compatible Configuration Space + 4 KB Extended Configuration Space."},
            ]
        if _empty(f.get("future_versions_industry_outline")):
            f["future_versions_industry_outline"] = [
                {"version": "PCIe 2.0 (2007)",  "line_rate_GT_s": 5,   "encoding": "8b/10b",
                 "summary": "Doubles per-Lane raw bandwidth to 5 GT/s; same 8b/10b encoding (20% overhead); backward-compatible with 1.0/1.1 devices via auto-negotiation."},
                {"version": "PCIe 2.1 (2009)",  "line_rate_GT_s": 5,   "encoding": "8b/10b",
                 "summary": "Errata + management infrastructure improvements."},
                {"version": "PCIe 3.0 (2010)",  "line_rate_GT_s": 8,   "encoding": "128b/130b",
                 "summary": "Switches encoding to 128b/130b (much lower 1.5% overhead); raw 8 GT/s gives ~7.88 Gb/s effective per Lane."},
                {"version": "PCIe 4.0 (2017)",  "line_rate_GT_s": 16,  "encoding": "128b/130b",
                 "summary": "Doubles to 16 GT/s; same 128b/130b encoding; tighter channel-loss budget."},
                {"version": "PCIe 5.0 (2019)",  "line_rate_GT_s": 32,  "encoding": "128b/130b",
                 "summary": "Doubles to 32 GT/s; NRZ; introduces precoding option for SerDes."},
                {"version": "PCIe 6.0 (2022)",  "line_rate_GT_s": 64,  "encoding": "PAM4 + FEC",
                 "summary": "Switches NRZ to PAM4 (4 levels per UI); adds Forward Error Correction (FEC); FLIT-based packet flow."},
                {"version": "PCIe 7.0 (2025+)", "line_rate_GT_s": 128, "encoding": "PAM4 + FEC",
                 "summary": "Doubles to 128 GT/s; new channel-loss budget; FLIT-based mandatory."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "Speed_auto_negotiation_at_attach",
                 "Gen1_device":   "Trains at 2.5 GT/s only; Polling.Speed sub-state stays at 2.5 GT/s.",
                 "Gen2plus_device":"Trains at 2.5 GT/s first; then negotiates Recovery.Speed up to its maximum.",
                 "trap": "Gen 2+ device on a Gen 1 Link will silently fall back to 2.5 GT/s — bandwidth surprise for users."},
                {"trap_name": "Lane_width_downshift",
                 "rule": "Both ends advertise their max lane width via TS1/TS2; agreement is the minimum.",
                 "trap": "x16 device on a x4 Link silently trains as x4 — performance surprise."},
                {"trap_name": "Encoding_change_at_Gen3",
                 "Gen1_2_encoding": "8b/10b (20% overhead)",
                 "Gen3plus_encoding": "128b/130b (1.5% overhead)",
                 "trap": "Gen 3+ silicon must implement BOTH encoders to remain backward-compatible; a Gen 3 PHY only running 128b/130b will not train against a Gen 1 partner."},
                {"trap_name": "Max_Payload_Size_must_be_minimum_of_path",
                 "rule": "Max_Payload_Size_Supported is advertised; runtime Max_Payload_Size is set to the minimum across the path from Requester to Completer.",
                 "trap": "Endpoint advertises 4096 B, but a Switch in the path only supports 128 B → the path must run at 128 B; misconfiguration causes Malformed TLP errors."},
                {"trap_name": "Optional_features_must_be_independently_negotiated",
                 "rule": "ASPM, ECRC, Vendor-Specific Messages, Hot-Plug, MSI vs MSI-X — each must be discovered via Capability Structures and explicitly enabled.",
                 "trap": "Assuming a peer supports ASPM L1 without checking Link Capabilities will cause traffic to stall or hang."},
            ]
        f.setdefault("version_naming_history_note",
            "PCI-SIG (PCI Special Interest Group) maintains the spec. PCI Express Rev 1.0 was finalized April 29, 2002 by the Promoter Group. Subsequent revisions retain '8b/10b' through Gen 2, then switch to 128b/130b at Gen 3 and PAM4 + FEC at Gen 6. The PCI Express Card Electromechanical Specification is a separate companion document covering connectors and add-in cards.")
        d["fields"] = f
        _write(p, d)

    # L15
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("special_symbols_table", {
            "header_columns": ["Encoding", "Symbol", "Name", "Description"],
            "rows": [
                ["K28.5", "COM", "Comma",                  "Used for Lane and Link initialization and management"],
                ["K27.7", "STP", "Start TLP",              "Marks the start of a Transaction Layer Packet"],
                ["K28.2", "SDP", "Start DLLP",             "Marks the start of a Data Link Layer Packet"],
                ["K29.7", "END", "End",                    "Marks the end of a Transaction Layer Packet or a Data Link Layer Packet"],
                ["K30.7", "EDB", "EnD Bad",                "Marks the end of a nullified TLP"],
                ["K23.7", "PAD", "Pad",                    "Used in Framing and Link Width and Lane ordering negotiations"],
                ["K28.0", "SKP", "Skip",                   "Used for compensating for different bit rates for two communicating ports"],
                ["K28.1", "FTS", "Fast Training Sequence", "Used within an ordered-set to exit from L0s to L0"],
                ["K28.7", "",    "",                       "Reserved"],
                ["K28.3", "IDL", "Idle",                   "Electrical Idle symbol used in the electrical idle ordered-set"],
                ["K28.4", "",    "",                       "Reserved"],
                ["K28.6", "",    "",                       "Reserved"],
            ],
        })
        f.setdefault("fmt_field_encoding_table", {
            "header_columns": ["Fmt[1:0]", "Meaning"],
            "rows": [
                ["00", "3 DW header, no data"],
                ["01", "4 DW header, no data"],
                ["10", "3 DW header, with data"],
                ["11", "4 DW header, with data"],
            ],
        })
        f.setdefault("transaction_type_encoding_examples_table", {
            "header_columns": ["Type Name", "Fmt[1:0]", "Type[4:0]", "Header DW", "Has Data"],
            "rows": [
                ["MRd  (Memory Read 32b addr)",          "00", "00000", 3, False],
                ["MRd  (Memory Read 64b addr)",          "01", "00000", 4, False],
                ["MWr  (Memory Write 32b addr)",         "10", "00000", 3, True],
                ["MWr  (Memory Write 64b addr)",         "11", "00000", 4, True],
                ["IORd (I/O Read)",                       "00", "00010", 3, False],
                ["IOWr (I/O Write)",                      "10", "00010", 3, True],
                ["CfgRd0 (Config Read Type 0)",          "00", "00100", 3, False],
                ["CfgWr0 (Config Write Type 0)",         "10", "00100", 3, True],
                ["CfgRd1 (Config Read Type 1)",          "00", "00101", 3, False],
                ["CfgWr1 (Config Write Type 1)",         "10", "00101", 3, True],
                ["Cpl  (Completion)",                     "00", "01010", 3, False],
                ["CplD (Completion with data)",          "10", "01010", 3, True],
                ["Msg  (Message)",                        "01", "10rrr", 4, False],
                ["MsgD (Message with data)",             "11", "10rrr", 4, True],
            ],
        })
        f.setdefault("dllp_type_encoding_table", {
            "header_columns": ["DLLP Type", "Purpose"],
            "rows": [
                ["Ack",          "Acknowledge a TLP up to a given Sequence Number"],
                ["Nak",          "Negative acknowledge — request replay from last good Sequence Number"],
                ["InitFC1",      "Flow Control initialization, phase 1; per VC, per credit type"],
                ["InitFC2",      "Flow Control initialization, phase 2; confirms phase 1 receipt"],
                ["UpdateFC",     "Running Flow Control credit update"],
                ["PM_Enter_L1",  "Power Management — request L1 entry"],
                ["PM_Enter_L23", "Power Management — request L2 / L3 entry"],
                ["PM_Active_State_Request_L1", "Active State Power Management L1 request"],
                ["PM_Request_Ack", "Acknowledge a PM request"],
                ["Vendor Specific", "Vendor-defined DLLP"],
            ],
        })
        f.setdefault("lcrc_polynomial_table", {
            "header_columns": ["Field", "Value"],
            "rows": [
                ["Polynomial",    "x^16 + x^12 + x^5 + 1 (CRC-16-CCITT)"],
                ["Hex",           "0x1021"],
                ["Initial value", "0xFFFF"],
                ["Width",         "16 bits"],
                ["Covers",        "TLP: Sequence Number + TLP body. DLLP: DLLP type + DLLP-specific fields."],
            ],
        })
        f.setdefault("ecrc_polynomial_table", {
            "header_columns": ["Field", "Value"],
            "rows": [
                ["Polynomial",    "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1 (IEEE 802.3 CRC-32)"],
                ["Hex",           "0x04C11DB7"],
                ["Initial value", "0xFFFFFFFF"],
                ["Width",         "32 bits"],
                ["Covers",        "TLP end-to-end (optional; signaled via TD = 1 in header)"],
            ],
        })
        f.setdefault("8b_10b_encoding_note",
            "The PCI Express Physical Layer uses the IBM 8b/10b code published by Widmer + Franaszek in IBM J. Res. Dev. Vol 27 #5 (Sept 1983) — same code as Fibre Channel, Gigabit Ethernet 1000BASE-X, Serial ATA, and InfiniBand 1x. Provides DC balance + ≤ 5-bit run length + 12 unique 'comma' K-codes used by PCI Express as Special Symbols.")
        if _empty(f.get("tables")):
            f["tables"] = [
                "Table 2-1 — Transaction Types for Different Address Spaces",
                "Table 2-8 — Fmt[1:0] and Type[4:0] Field Encodings",
                "Table 2-16 — Flow Control Credit Types",
                "Table 3-1 — DLLP Type Encodings",
                "Table 3-2 — Mapping of Bits into CRC Field",
                "Table 3-3 — Mapping of Bits into LCRC Field",
                "Table 4-1 — Special Symbols",
                "Table 4-2 — TS1 Ordered-Set",
                "Table 4-3 — TS2 Ordered-Set",
                "Table 4-4 — Differential Transmitter (Tx) Output Specifications",
                "Table 4-5 — Differential Receiver (Rx) Input Specifications",
                "Table B-1 — 8b/10b Data Symbol Codes",
                "Table B-2 — 8b/10b Special Character Symbol Codes",
            ]
        d["fields"] = f
        _write(p, d)

    # L16
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Layered architecture: Transaction Layer + Data Link Layer + Physical Layer.",
            "Point-to-point Link: each Link connects exactly two components via dual-simplex differential pairs.",
            "Per-Lane 2.5 GT/s line rate (Gen 1) with 8b/10b encoding.",
            "Lane widths x1, x2, x4, x8, x12, x16, x32 — symmetric in both directions on a given Link.",
            "TLP framing: STP (K27.7) at start, END (K29.7) at end (or EDB K30.7 for nullified TLP).",
            "DLLP framing: SDP (K28.2) at start, END (K29.7) at end.",
            "TLPs carry a 12-bit Sequence Number + 16-bit LCRC at the Data Link Layer.",
            "DLLPs carry a 16-bit CRC.",
            "ACK / NAK replay protocol guarantees TLP delivery; receiver NAKs on LCRC/Sequence error; transmitter replays from Retry Buffer.",
            "Credit-based flow control per Virtual Channel with six credit types (PH / PD / NPH / NPD / CplH / CplD).",
            "Mandatory Virtual Channel VC0 carrying Traffic Class TC0.",
            "PCI 2.3-compatible Configuration Space (256 B) + PCI Express Extended Configuration Space (up to 4096 B per device).",
            "LTSSM bring-up from PERST# through Detect → Polling → Configuration → L0 without firmware intervention.",
            "Configuration Read Type 0 / Type 1 routing per spec rules; Vendor ID = FFFFh indicates 'no device'.",
            "Max_Payload_Size negotiated to the minimum across the path; values 128 / 256 / 512 / 1024 / 2048 / 4096 B.",
            "Switches must forward all TLP types between any set of ports; must not split a TLP into smaller TLPs.",
            "AC coupling on both ends of every differential pair.",
        ])
        f.setdefault("must_not_have_properties", [
            "Sending a TLP without sufficient Flow Control credits (would be a fatal protocol error).",
            "Splitting a single TLP into multiple smaller TLPs at a Switch.",
            "Generating I/O Requests from a PCI Express Endpoint (Legacy Endpoints may; modern PCI Express Endpoints may not).",
            "Generating Locked Requests from a PCI Express Endpoint (Legacy Endpoints + Root Complex requesters only).",
            "Forwarding peer-to-peer transactions through a Root Complex unless explicitly supported (RC is permitted but not required to support peer-to-peer).",
            "Reusing a Sequence Number before its TLP has been acked.",
            "Placing STP / SDP on any Lane other than Lane 0 in a multi-Lane Link.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Replay failure",                "trigger": "REPLAY_NUM rollover after repeated NAKs / REPLAY_TIMER expirations; Link declared as failed."},
            {"mode": "LCRC error",                    "trigger": "16-bit CRC mismatch on a received TLP; receiver NAKs."},
            {"mode": "Sequence Number error",         "trigger": "Out-of-order or duplicate Sequence Number; receiver NAKs or drops."},
            {"mode": "8b/10b decode error",           "trigger": "Invalid 10-bit symbol or running-disparity violation; logged as Receiver Error."},
            {"mode": "Framing error",                 "trigger": "Missing STP / SDP / END / EDB; logged as Receiver Error."},
            {"mode": "Flow Control protocol error",   "trigger": "Transmitter sent a TLP without sufficient credits, or receiver advertised more credits than buffer size."},
            {"mode": "Completion Timeout",            "trigger": "Non-Posted Request without Completion within the timeout window."},
            {"mode": "Unsupported Request",           "trigger": "Completer cannot service a Request type (e.g. I/O Request to a PCIe Endpoint)."},
            {"mode": "Completer Abort",               "trigger": "Completer encounters an abnormal condition while processing a Request."},
            {"mode": "Malformed TLP",                 "trigger": "Header fields violate spec rules (e.g. Length > Max_Payload_Size; reserved field non-zero)."},
            {"mode": "Poisoned TLP Received",         "trigger": "TLP with EP (Error / Poisoned) bit set was received; data should be marked invalid."},
        ])
        f.setdefault("min_link_constraint",
            "Every Link must support at least x1 width at Gen 1 (2.5 GT/s) and must successfully train from Detect to L0 within the LTSSM-defined symbol time budgets.")
        f.setdefault("reset_behavior_compliance",
            "PERST# deassertion triggers LTSSM entry to Detect; all per-Link state machines (DLL, TL) wait for L0 + Flow Control init. Hot Reset (TS1 with Hot Reset bit) returns the downstream device to Detect without de-asserting PERST#.")
        f.setdefault("8b10b_running_disparity_rule",
            "Each transmitted symbol must obey the IBM 8b/10b running-disparity rule. Receivers must validate running disparity and flag violations as Receiver Errors.")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {"name": "TXp",     "direction": "output (per Lane, per direction)", "purpose": "Positive line of the differential transmit pair.",                      "active_levels": "AC-coupled, 0.8 V differential pp typical, 0.5 V common mode, 8b/10b encoded at 2.5 Gb/s Gen 1", "idle_level": "Electrical Idle when LTSSM not in L0 or L0s"},
            {"name": "TXn",     "direction": "output (per Lane, per direction)", "purpose": "Negative line of the differential transmit pair.",                      "active_levels": "AC-coupled, 0.8 V differential pp typical", "idle_level": "Electrical Idle"},
            {"name": "RXp",     "direction": "input  (per Lane, per direction)", "purpose": "Positive line of the differential receive pair.",                       "active_levels": "AC-coupled, 0.175 V differential pp min after channel loss", "idle_level": "Electrical Idle detect"},
            {"name": "RXn",     "direction": "input  (per Lane, per direction)", "purpose": "Negative line of the differential receive pair.",                       "active_levels": "AC-coupled, 0.175 V differential pp min", "idle_level": "Electrical Idle detect"},
            {"name": "REFCLK+", "direction": "input (per component)",            "purpose": "Positive line of 100 MHz reference clock differential pair; SSC-tolerant; common or separate clock topology.",  "active_levels": "100 MHz HCSL or similar differential", "idle_level": "n/a; always driven"},
            {"name": "REFCLK-", "direction": "input (per component)",            "purpose": "Negative line of 100 MHz reference clock differential pair.",            "active_levels": "100 MHz",                              "idle_level": "n/a; always driven"},
            {"name": "PERST#",  "direction": "input (per component)",            "purpose": "Fundamental Reset; active LOW; asserted while main power is unstable.",  "active_levels": "Single-ended LVTTL / LVCMOS, active LOW", "idle_level": "Deasserted HIGH for normal operation"},
            {"name": "WAKE#",   "direction": "open-drain (system-level)",         "purpose": "Pulled LOW by any device that wants to resume from L2 / L3.",            "active_levels": "Open-drain, active LOW", "idle_level": "Released (pulled HIGH by system pull-up)"},
        ]
        f["logical_signaling_levels"] = [
            {"name": "Active TX symbol stream", "meaning": "Continuously driven differential signaling carrying 8b/10b-encoded TLP / DLLP / Idle / Ordered-Set data."},
            {"name": "Electrical Idle",         "meaning": "Transmitter outputs no symbol stream; differential output is undriven (or held at common mode)."},
            {"name": "Beacon",                  "meaning": "30 kHz to 500 MHz modulated pulses on the differential pair used to wake the Link from L2 when REFCLK is off."},
        ]
        f["packet_types_summary"] = [
            {"class": "TLP",  "members": ["MRd", "MRdLk", "MWr", "IORd", "IOWr", "CfgRd0", "CfgWr0", "CfgRd1", "CfgWr1", "Msg", "MsgD", "Cpl", "CplD", "CplLk", "CplDLk"], "count": 15},
            {"class": "DLLP", "members": ["Ack", "Nak", "InitFC1", "InitFC2", "UpdateFC", "PM_Enter_L1", "PM_Enter_L23", "PM_Active_State_Request_L1", "PM_Request_Ack", "Vendor Specific"], "count": 10},
        ]
        f["channel_counts"] = {
            "lanes_per_link_min":           1,
            "lanes_per_link_max":          32,
            "differential_pairs_per_lane":  2,
            "wires_per_lane":               4,
            "shared_signals_per_link":      ["REFCLK pair", "PERST#", "WAKE#"],
            "max_vc_per_link":              8,
            "max_tc_per_link":              8,
            "flow_control_credit_types":    6,
            "tlp_packet_class_count":      15,
            "dllp_packet_class_count":     10,
        }
        f["global_signals"] = [
            {"name": "REFCLK", "purpose": "100 MHz reference clock for all components in a Common Clock domain."},
            {"name": "PERST#", "purpose": "Fundamental reset distributed to every component."},
            {"name": "WAKE#",  "purpose": "Open-drain wakeup signal; any device can assert to wake the system from L2/L3."},
        ]
        # Force-overwrite dependency_graph for PCIe shape.
        f["dependency_graph"] = {
            "common_rule":
                "Each Lane is fully autonomous at the bit level (independent CDR + 8b/10b decoder + elastic buffer). Lanes of a wider Link cooperate only at de-skew + striping. The TX direction of a Link is independent of the RX direction (dual-simplex). LTSSM coordinates both directions for state transitions.",
            "data_dependency":
                "TLP transmission requires: (1) sufficient Flow Control credits on the relevant VC + credit type, (2) DL_Active state, (3) LTSSM L0. Replay requires: prior un-acked TLP in Retry Buffer + Nak DLLP or REPLAY_TIMER expiration.",
        }
        f["handshake_pairs"] = [
            {"name": "TLP-ACK",      "from": "receiver", "to": "transmitter", "rule": "Receiver sends Ack DLLP for the highest Sequence Number whose TLP passed LCRC + ordering check; transmitter retires acked TLPs from the Retry Buffer."},
            {"name": "TLP-NAK",      "from": "receiver", "to": "transmitter", "rule": "Receiver sends Nak DLLP carrying the last good Sequence Number; transmitter replays all later TLPs from the Retry Buffer."},
            {"name": "Init-FC-1",    "from": "either",   "to": "either",      "rule": "InitFC1 DLLP advertises initial credits per (VC, credit-type)."},
            {"name": "Init-FC-2",    "from": "either",   "to": "either",      "rule": "InitFC2 DLLP confirms InitFC1 receipt."},
            {"name": "Update-FC",    "from": "receiver", "to": "transmitter", "rule": "UpdateFC DLLP advertises additional credits as receiver buffer fills are freed."},
            {"name": "PM_Enter_L1",  "from": "either",   "to": "either",      "rule": "Both ends must agree before LTSSM transitions to L1."},
            {"name": "PM_Enter_L23", "from": "either",   "to": "either",      "rule": "Both ends agree to enter L2 / L3; TX enters Electrical Idle."},
            {"name": "TS1-TS2",      "from": "either",   "to": "either",      "rule": "Polling + Configuration LTSSM training-set exchange; carries Link / Lane Number + N_FTS + data-rate."},
        ]
        f.setdefault("ordering_rules", {
            "bit_order_within_byte":   "Byte is 8b/10b-encoded then transmitted LSB of the 10-bit symbol first on the wire (per Figure 4-3, Bit Transmission Order on Physical Lanes).",
            "byte_order_within_field": "Little-endian for multi-byte fields within TLP headers (matches PCI convention).",
            "lane_striping":           "Multi-Lane Links stripe successive bytes round-robin starting at Lane 0; STP/SDP MUST land on Lane 0.",
            "tx_rx_simultaneity":      "Dual-simplex: TX and RX directions transmit independently and simultaneously.",
        })
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Tree-shaped 'hierarchy' rooted at a Root Complex (RC). "
            "Below the RC: optional Switches that aggregate multiple "
            "Endpoints, plus optional PCI Express-to-PCI/PCI-X Bridges. "
            "Every PCIe Link is point-to-point and dual-simplex; there "
            "is no shared-medium 'bus' anywhere in the fabric. Optional "
            "Cross-Link interconnect (Advanced Peer-to-Peer "
            "Communication) allows two separate hierarchies to "
            "interoperate.")
        f["supported_topologies"] = [
            {"name": "Single RC + single Endpoint",      "description": "Simplest case: one Link between RC and one Endpoint."},
            {"name": "RC + Switch + N Endpoints",        "description": "Switch upstream port connects to RC; downstream ports each connect to one Endpoint."},
            {"name": "Cascaded Switches",                 "description": "Multi-level tree; each Switch hides its Endpoints behind virtual PCI-to-PCI bridges."},
            {"name": "RC + PCI Express-to-PCI/PCI-X Bridge", "description": "Allows legacy parallel-PCI / PCI-X devices to attach to a PCIe RC."},
            {"name": "Advanced Peer-to-Peer (Cross-Link)", "description": "Optional. Two RCs / hierarchies connect via Cross-Link Switches; details in a separate Advanced PCI Express Packet Switching Specification."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Root Complex (RC)",     "description": "Top of one hierarchy; connects CPU/memory to PCIe fabric; must generate Configuration Requests as Requester; may generate I/O Requests; must not support Lock semantics as Completer."},
            {"role": "Switch",                "description": "Logical assembly of virtual PCI-to-PCI bridges; forwards TLPs unmodified; must not split a TLP into smaller TLPs; arbitrates between ingress ports on per-VC basis (round-robin or weighted round-robin)."},
            {"role": "PCI Express Endpoint",  "description": "Type 0 Configuration Space header; must support Configuration Requests as Completer; must NOT generate I/O Requests; must NOT support Lock semantics."},
            {"role": "Legacy Endpoint",       "description": "Type 0 header; may support I/O space + Lock semantics for legacy software compatibility; must not issue Locked Requests."},
            {"role": "PCI Express-to-PCI Bridge", "description": "One PCIe Port + one or more PCI/PCI-X bus interfaces; supports Lock semantics from PCIe→PCI direction (for deadlock prevention)."},
        ]
        f["interconnect_role"] = (
            "PCI Express is a tree of point-to-point Links. There is no "
            "protocol-layer router; Switches act as fan-out and address-"
            "based forwarders, but they cannot drop, split, or reorder "
            "TLPs (except within ordering rules). Each PCIe Link is "
            "independent — TLP delivery is guaranteed at the Link layer "
            "by ACK/NAK + replay, and at the end-to-end layer optionally "
            "by ECRC.")
        f["ordering_guarantees"] = {
            "producer_consumer":      "PCI / PCI-X compliant producer-consumer ordering model preserved end-to-end through Switches.",
            "relaxed_ordering_optin": "TLPs may set the Relaxed Ordering attribute to opt out of certain strict ordering rules for performance.",
            "virtual_channel_isolation": "Traffic on different VCs has no ordering relationship to traffic on other VCs; this enables traffic-class differentiation and prevents head-of-line blocking.",
            "completion_ordering":    "Completions returned to a Requester are NOT ordered against new Requests, allowing pipelining; ordering within a sequence of split-Completion fragments IS preserved.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "PCI Express defines four address spaces: Memory, I/O, Configuration, Message. Memory space is the primary data path (DMA + memory-mapped registers). I/O space is legacy (Legacy Endpoints only). Configuration space is the per-device control plane (256 B + 4 KB extended). Message space replaces sideband signals (INTx, PME, error, vendor-defined).")
        f.setdefault("device_classification", {
            "root_complex":               "Connects CPU + memory to PCIe; one per hierarchy.",
            "switch":                     "Aggregates N downstream ports into one upstream port; appears as multiple virtual PCI-to-PCI bridges.",
            "pci_express_endpoint":       "Modern Endpoint; no I/O space; no Lock semantics.",
            "legacy_endpoint":            "PCI-compatible Endpoint; may use I/O space + Lock.",
            "pci_express_to_pci_bridge":  "PCIe ↔ PCI / PCI-X protocol translator.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Figure 1-2 Example Topology",
            "Figure 1-3 Logical Block Diagram of a Switch",
            "Figure 1-6 Advanced Peer-to-Peer Communication",
            "Section 1.3 PCI Express Fabric Topology",
        ])
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f.setdefault("electrical_channel_constraints", {
            "differential_impedance_ohm":     100,
            "single_ended_impedance_ohm":      50,
            "ac_coupling_required":           True,
            "ac_coupling_cap_typical_nF":     {"low": 75, "high": 200},
            "tx_de_emphasis_dB":              -3.5,
            "tx_common_mode_V":               0.5,
            "max_intra_pair_skew_mils_gen1":  5,
            "max_inter_pair_skew_mils_gen1": 25,
            "refclk_freq_MHz":               100,
            "refclk_ssc_max_percent":         0.5,
            "clock_tolerance_ppm":            300,
            "esd_class_recommended":          "≥ Class 2 on TX / RX pads (per industry practice; not specified in Rev 1.0)",
        })
        f["notes"] = (
            "PCI Express Rev 1.0 is a wire-level + transaction-level + "
            "software-interface protocol spec; it does not impose PDK-"
            "specific SDC / floorplan constraints. The Base Spec DOES "
            "specify analog compliance windows (Tables 4-4 + 4-5; Figures "
            "4-32, 4-33, 4-34) and PCB-level guidance on differential "
            "impedance, AC coupling, and channel-loss budgets. SoC "
            "integration constraints (clock-tree budget, PHY "
            "characterization, pad type selection) live in the SoC "
            "integration spec, not in the Base Spec. Companion "
            "mechanical/connector constraints live in the PCI Express "
            "Card Electromechanical Specification.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = "partial"
        f.setdefault("in_band_test_facilities", [
            {"name": "Polling.Compliance pattern", "purpose": "LTSSM sub-state that transmits a defined compliance pattern at 2.5 GT/s for electrical eye / BER characterization."},
            {"name": "Loopback test mode",          "purpose": "Loopback Master transmits a known pattern; Loopback Slave retransmits it back; allows receiver-eye and serializer/deserializer testing without a full link partner."},
            {"name": "Hot Reset",                    "purpose": "TS1 with Hot Reset bit set forces downstream device to Detect; testable via Bridge Control Secondary Bus Reset."},
            {"name": "Disable Link",                "purpose": "Forces TX into Electrical Idle for power-consumption and OFF-state characterization."},
            {"name": "Compliance Pattern (Section 4.2.8)", "purpose": "Spec-defined repeating pattern of K28.5 + D21.5 + K28.5 + D10.2 for electrical eye / jitter measurement."},
            {"name": "Advanced Error Reporting (AER)",     "purpose": "Provides in-protocol observability of correctable / uncorrectable / fatal errors."},
        ])
        f.setdefault("internal_diagnostics_observability", [
            "Link Status Register — current LTSSM state, negotiated Link Speed + Link Width.",
            "Slot Status Register — Card Present, Power Indicator, Attention Indicator, MRL Sensor, Power Fault.",
            "Device Status Register — Correctable / Non-Fatal / Fatal Error Detected, Unsupported Request Detected, AUX Power Detected, Transactions Pending.",
            "Root Status Register — PME Status, PME Pending, PME Requester ID.",
            "AER Uncorrectable Error Status / Mask / Severity Registers — fine-grained protocol-error observability.",
            "AER Header Log Register — first 4 DW of the offending TLP header preserved for postmortem.",
            "VC Resource Status Register — per-VC negotiation status.",
        ])
        f.setdefault("out_of_band_test_facilities", [
            "PROBE-via-protocol-analyzer (LeCroy / Keysight / vendor-specific) — interposer or mid-board tap to capture TLPs / DLLPs / Ordered Sets.",
            "PROBE-via-vendor-PHY-debug-port — implementation-defined (PIPE-style PHY interface specs add scan + debug; not in Base Spec).",
        ])
        f["notes"] = (
            "PCI Express Rev 1.0 does NOT specify JTAG / scan-chain / "
            "BIST at the protocol level. Compliance testing is performed "
            "via in-protocol Loopback + Polling.Compliance modes plus "
            "external instruments per the PCI-SIG Compliance Program. "
            "SoC-integrated PCIe controllers typically add standard scan "
            "+ JTAG at the integrator level.")
        d["fields"] = f
        _write(p, d)

    # L21 power
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["power_intent_present"] = True
        f.setdefault("link_power_management_states", [
            {"state": "L0",   "name": "Active",                  "description": "Normal operation. TX + RX both active; TLPs / DLLPs / Ordered Sets flow freely.", "exit_latency_estimate": "n/a (already active)"},
            {"state": "L0s",  "name": "Standby per direction",  "description": "Either TX or RX direction enters Electrical Idle independently. Entry preceded by EIOS. Exit by transmitting N_FTS Fast Training Sequences. Per-direction independent.", "exit_latency_estimate": "sub-microsecond"},
            {"state": "L1",   "name": "Lower-power link standby","description": "Both directions in Electrical Idle. Link state preserved; no full re-training. Exit via Recovery (Recovery.RcvrLock → Recovery.RcvrCfg → Recovery.Idle → L0).", "exit_latency_estimate": "single-digit microseconds (depends on Common Clock vs Separate Clock)"},
            {"state": "L2",   "name": "Deep sleep",              "description": "Both directions in Electrical Idle. Main power may remain; REFCLK may be off. Wake via Beacon (or WAKE# at system level). LTSSM restarts from Detect.", "exit_latency_estimate": "millisecond (full re-train)"},
            {"state": "L3",   "name": "Off",                     "description": "Main power removed. Re-entry requires full PERST# cycle.", "exit_latency_estimate": "system-wide power-up"},
        ])
        f["low_power_modes_summary"] = {
            "L0_active":   "Full operational power.",
            "L0s_standby": "Per-direction Electrical Idle; sub-µs FTS-based exit.",
            "L1_low":      "Bi-directional Electrical Idle; Link state preserved; few-µs Recovery-based exit.",
            "L2_sleep":    "Deep sleep; REFCLK off; Beacon wakeup; ms-scale re-train.",
            "L3_off":      "Main power off.",
        }
        f.setdefault("device_states_d0_d3", [
            {"state": "D0",     "description": "Fully operational; corresponds to L0 link state."},
            {"state": "D1",     "description": "Optional intermediate low-power; vendor-defined; functional but reduced."},
            {"state": "D2",     "description": "Optional deeper low-power; vendor-defined."},
            {"state": "D3hot",  "description": "Configuration Space still accessible; aux power only; corresponds to L1 or L2."},
            {"state": "D3cold", "description": "Main power removed; only Vaux available; corresponds to L2 / L3."},
        ])
        f.setdefault("active_state_power_management_aspm", {
            "ASPM_L0s_support": "Optional but commonly implemented; per-direction TX entry decision based on configurable idle threshold.",
            "ASPM_L1_support":  "Optional; bi-directional agreement required via PM_Active_State_Request_L1 DLLP.",
            "ASPM_disable":     "Default; can be enabled per-direction via Link Control Register.",
        })
        f.setdefault("pm_messages_summary", [
            {"name": "PM_Active_State_Request_L1",   "purpose": "DLLP requesting ASPM L1 entry."},
            {"name": "PM_Request_Ack",               "purpose": "DLLP acknowledging a PM_Enter_L1 / PM_Enter_L23 request."},
            {"name": "PM_Enter_L1",                   "purpose": "DLLP requesting software-driven L1 entry."},
            {"name": "PM_Enter_L23",                  "purpose": "DLLP requesting L2 / L3 entry."},
            {"name": "PM_PME (TLP Message)",         "purpose": "Power Management Event message; routed upstream to the Root Complex."},
            {"name": "PME_Turn_Off / PME_TO_Ack (TLP Messages)", "purpose": "Root informs downstream devices of imminent main-power removal; devices acknowledge."},
        ])
        f.setdefault("auxiliary_power", {
            "Vaux_support":    "Optional auxiliary power rail supplied to devices for PME / WAKE# generation while main power is off (L2/L3, D3cold).",
            "Vaux_usage_hint": "Required for any device that must generate a wake event from D3cold.",
        })
        f["notes"] = (
            "PCI Express explicitly specifies a comprehensive Link Power "
            "Management framework: ASPM (HW-driven L0s + L1) for "
            "autonomous power saving during idle, plus software-driven "
            "L1/L2/L3 transitions for OS / firmware control. Coordination "
            "with the legacy PCI Power Management Capability (D0..D3) is "
            "mandatory — see Section 6.3 PCI-PM Software Compatible "
            "Mechanisms.")
        d["fields"] = f
        _write(p, d)

    # L23 security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f.setdefault("anti_corruption_features", [
            "16-bit LCRC at the Data Link Layer protects each TLP across the Link (catches all 1-bit + 2-bit errors and most burst errors).",
            "16-bit CRC at the Data Link Layer protects each DLLP.",
            "32-bit ECRC (optional) at the Transaction Layer provides end-to-end TLP integrity (detects corruption at intermediate Switches that the per-Link LCRC cannot).",
            "8b/10b running-disparity rule + invalid-symbol detection catches PHY-level bit errors before the DLL layer sees them.",
            "ACK / NAK + Retry Buffer guarantees in-order delivery despite single-bit transient errors.",
            "Sequence Number monotonicity detection rejects duplicate or out-of-order packets.",
        ])
        f.setdefault("anti_tampering_features",   [])
        f.setdefault("confidentiality_features",  [])
        f.setdefault("authentication_features",   [])
        f.setdefault("future_security_pointers", [
            "PCI Express 5.0+ Integrity & Data Encryption (IDE) extension adds AES-GCM link encryption + integrity protection (defined in a separate ECN).",
            "Compute Express Link (CXL) builds on PCIe 5.0+ and adds CXL.io / CXL.cache / CXL.mem; security is layered above the base PCIe protocol.",
            "Single Root I/O Virtualization (SR-IOV) — added in PCIe 2.0 ECN — provides VM isolation but is NOT cryptographic.",
            "Access Control Services (ACS) — added in PCIe 2.0 ECN — restricts peer-to-peer routing at Switches for VM isolation but is NOT cryptographic.",
        ])
        f["notes"] = (
            "PCI Express Rev 1.0 (2002) is a wire-level + transaction-"
            "level + software-interface specification with NO native "
            "confidentiality / integrity / authentication features. CRC + "
            "ECRC provide anti-corruption protection only. TLP payloads "
            "are in plaintext on the Link. Modern PCIe security "
            "extensions (IDE, CMA/SPDM, ACS, SR-IOV) are layered above "
            "the Base Spec and were added in much later revisions; they "
            "are NOT part of Rev 1.0.")
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
def is_pcie(blob: str) -> bool:
    """Content-only `pcie` detector (importable) with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text).

    The base PCIe structural signature (TLP+DLLP+LTSSM, or PCI Express +
    Transaction Layer + Data Link Layer, or 8b/10b + PCI Express) is necessary
    but NOT sufficient: every protocol layered on or compared against PCIe
    incidentally carries the PCIe Base-Spec vocabulary in its spec text and
    would otherwise trip these loose branches. The base-PCIe synth must NOT
    fire on a spec whose DOMINANT subject is one of those foreign protocols.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine and the SAS
    sibling-MUTEX doctrine — every condition is a GENERAL protocol-semantic
    signature: distinctive structural tokens, layer/transport names, frame-field
    names, density counts; NO benchmark-directory / chip / SKU literal as
    detection logic). If the blob's DOMINANT subject is a foreign protocol,
    defer (return False) so the generic PCIe synth never fires on a foreign
    spec that only cites PCIe incidentally as its transport or as a comparison:

      - CXL (Compute Express Link): a cache-coherent interconnect that RUNS its
        CXL.io / CXL.cache / CXL.mem protocols on the PCIe PHY. Its base-PCIe
        vocabulary (TLP/DLLP/LTSSM, Transaction/Data-Link layers) is incidental
        transport, not subject. Defer on dense CXL.io / CXL.mem / CXL.cache /
        "Compute Express Link" density (a real PCIe spec mentions CXL only in
        passing — ~1 hit — while a CXL spec carries 100+).
      - PCIe 5.0 (the derived CHILD): extends base PCIe with the Gen5 PHY
        (retimers + lane margining at 32 GT/s). Defer via the CHILD's
        distinctive PHY discriminator (a sibling-MUTEX): retimer + lane
        margining + dense "32 GT/s". Base PCIe (Gen1, 2.5 GT/s) carries none.
      - NVMe: a storage command set whose transport is PCIe. Defer on the dense
        NVMe queueing model (Submission/Completion Queue + doorbell, or NVM
        Express + dense Admin Command) — absent from a pure PCIe Base Spec.
      - UFS: built on MIPI UniPro + M-PHY. Defer on UPIU density / UniPro+M-PHY
        / "Universal Flash Storage" — none of which appear in a PCIe spec.
      - USB4: a tunneling fabric that can carry PCIe; defer on dense USB4 +
        router / Connection Manager / 40 Gbps and the absence of 32 GT/s
        (mirrors `is_usb4`'s own 32-GT/s sibling-MUTEX vs PCIe5).
      - DisplayPort: a VESA display interface that cites PCIe/USB4; defer on the
        DP structural trio (Main Link + AUX + DPCD), absent from PCIe.
      - SAS: Serial Attached SCSI; defer on the SSP+STP+SMP transport triple +
        expander + SAS-address/wide-port structure, absent from PCIe.

    Empirically corpus-clean: the real `pcie` benchmark trips NONE of these
    defers (its CXL/NVLink/USB4/queue tokens are all single incidental
    mentions), while cxl / displayport / nvlink / nvme / pcie_gen5 / sas / ufs
    / usb4 each trip their own foreign-primary discriminator and are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT base PCIe). ---
    cxl_primary = (
        low.count("compute express link") >= 10
        or low.count("cxl.io") >= 10
        or low.count("cxl.mem") >= 10
        or low.count("cxl.cache") >= 10)
    # NVLink: NVIDIA's high-speed link; dense "nvlink" / its NVHS sublayer.
    nvlink_primary = (low.count("nvlink") >= 10 or "nvhs" in low)
    # PCIe 5.0 derived-CHILD sibling-MUTEX: Gen5 PHY = retimer + lane margining
    # + dense 32 GT/s (the Gen5 line rate). Base PCIe Gen1 carries none.
    pcie5_primary = (
        ("retimer" in low and "lane margining" in low)
        and low.count("32 gt/s") >= 20)
    # NVMe: dense host/controller queueing model on top of PCIe.
    nvme_primary = (
        (low.count("submission queue") >= 10
         and low.count("completion queue") >= 10
         and low.count("doorbell") >= 10)
        or (("nvm express" in low or "nvme" in low)
            and low.count("admin command") >= 10))
    # UFS: MIPI UniPro + M-PHY transport with the UPIU information-unit model.
    ufs_primary = (
        low.count("upiu") >= 10
        or ("unipro" in low and ("m-phy" in low or "mphy" in low))
        or low.count("universal flash storage") >= 10)
    # USB4: a tunneling router fabric; 32-GT/s absent distinguishes it from PCIe5.
    usb4_primary = (
        "32 gt/s" not in low
        and low.count("usb4") >= 10
        and ("router" in low or "connection manager" in low
             or "40 gbps" in low))
    # DisplayPort: the VESA Main-Link + AUX + DPCD display-interface trio.
    dp_primary = (
        "main link" in low
        and ("aux ch" in low or "aux channel" in low or "i2c-over-aux" in low)
        and ("dpcd" in low or "displayport configuration data" in low))
    # SAS: the SSP+STP+SMP transport triple + expander + SAS-address/wide-port.
    sas_primary = (
        ("ssp" in low or "serial scsi protocol" in low)
        and ("stp" in low or "sata tunnel" in low)
        and ("smp" in low or "serial management protocol" in low)
        and "expander" in low
        and ("sas address" in low or "wide port" in low))
    if (cxl_primary or nvlink_primary or pcie5_primary or nvme_primary
            or ufs_primary or usb4_primary or dp_primary or sas_primary):
        return False

    # --- STRUCTURAL base-PCIe signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("TLP" in blob and "DLLP" in blob
            and "LTSSM" in blob)
        or ("PCI Express" in blob
            and "Transaction Layer" in blob
            and "Data Link Layer" in blob)
        or ("8b/10b" in blob and "PCI Express" in blob))
