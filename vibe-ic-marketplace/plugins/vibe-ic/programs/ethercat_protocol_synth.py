"""EtherCAT-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `industrial_field_protocol` /
`bus_interconnect_protocol`-shaped specs that exhibit the EtherCAT
structural signature. EtherCAT (Ethernet for Control Automation
Technology, IEC 61158 Type 12) sits on top of standard IEEE 802.3
Ethernet — therefore the Ethernet structural synth (ethernet_protocol_synth)
may fire first on any EtherCAT spec. This overlay runs AFTER the Ethernet
synth and FORCE-OVERWRITES Ethernet-leaning generic content with the
EtherCAT-specific layer (EtherType 0x88A4, datagram + on-the-fly engine,
ESC + FMMU + SyncManager + Distributed Clocks, ESM state machine, mailbox
protocols CoE/SoE/EoE/FoE/AoE).

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / Modbus synth).
Any EtherCAT specification variant — ETG Brochure, ETG.1000 series, IEC
61158-3-12/-4-12/-5-12/-6-12, ETG.1500 conformance, ESI XML reference,
vendor ESC ASIC datasheets — exhibits the same EtherCAT signature:
ESC + 0x88A4 + FMMU + SyncManager + Distributed Clocks.

Detection (must satisfy AT LEAST ONE of):
  - (EtherCAT + ESC + slave/SubDevice)
  - (EtherCAT + FMMU + SyncManager + Distributed Clocks)
  - (0x88A4 + EtherCAT + datagram)

Public entry: `apply_ethercat_synth(generated_docs_dir, is_ethercat,
                                    ethercat_ic_name)`.
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


def _force_ic_name(gd: Path, ic_name: str) -> None:
    """Force ic_name across all 24 L docs. EtherCAT overlay must
    overwrite even non-empty values left by the Ethernet synth."""
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
            d["ic_name"] = ic_name
            _write(q, d)
    for n in [
        "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
        "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
        "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
        "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
        "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
    ]:
        q = gd / n
        if q.is_file():
            d = _read(q)
            f = d.get("fields") or {}
            f["ic_name"] = ic_name
            d["fields"] = f
            _write(q, d)


def _apply_l1(gd: Path) -> None:
    """L1 DATASHEET — force-overwrite Ethernet-leaning fields with
    EtherCAT identity. EtherCAT is layered on Ethernet, so the Ethernet
    synth's L1 (IEEE 802.3 title / 1985 lineage / MII/GMII pin set) must
    be replaced wholesale."""
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "EtherCAT — The Ethernet Fieldbus — EtherCAT Technology Group Brochure"
    d["version"] = "ETG Brochure — Introduction to EtherCAT and the EtherCAT Technology Group"
    d["revised_date"] = "March 6, 2024"
    d["manufacturer"] = (
        "EtherCAT Technology Group (ETG) — Beckhoff Automation (originator). "
        "EtherCAT was introduced by Beckhoff in 2003 and is administered by the ETG, "
        "the world's largest fieldbus organization.")
    d["copyright"] = (
        "© EtherCAT Technology Group. EtherCAT® is a registered trademark and "
        "patented technology licensed by Beckhoff Automation GmbH, Germany.")
    d["abstract"] = (
        "EtherCAT (Ethernet for Control Automation Technology) is a high-performance, "
        "low-cost, deterministic Industrial Ethernet fieldbus standardized as IEC 61158 "
        "Type 12, IEC 61784, ISO 15745-4 and SEMI E54.20. A single EtherCAT MainDevice "
        "(Master) drives a daisy-chained or branched network of up to 65,535 SubDevices "
        "(Slaves) over standard 100BASE-TX / 100BASE-FX cabling. The defining "
        "characteristic is on-the-fly processing — each EtherCAT Slave Controller (ESC) "
        "reads its input data and writes its output data into the Ethernet frame while "
        "the frame is still passing through the device's interface logic, at the wire "
        "speed of 100 Mb/s or 1 Gb/s (EtherCAT G). EtherCAT carries its datagrams as "
        "the payload of an Ethernet frame with EtherType 0x88A4, or alternatively "
        "encapsulated inside a UDP/IP packet on port 0x88A4. Each EtherCAT datagram has "
        "a 10-byte header (Cmd + Idx + Address + Length + IRQ) and selects one of 13 "
        "addressing commands: NOP, APRD/APWR/APRW, FPRD/FPWR/FPRW, BRD/BWR/BRW, "
        "LRD/LWR/LRW, ARMW, FRMW.")
    d["keywords"] = [
        "EtherCAT", "ETG", "EtherCAT Technology Group",
        "Industrial Ethernet", "Fieldbus",
        "IEC 61158 Type 12", "IEC 61784", "ISO 15745-4", "SEMI E54.20",
        "MainDevice", "Master", "SubDevice", "Slave",
        "ESC", "EtherCAT Slave Controller",
        "0x88A4 EtherType", "EtherCAT datagram",
        "on-the-fly processing", "processing on the fly",
        "FMMU", "Fieldbus Memory Management Unit",
        "SyncManager", "SM", "mailbox", "process data buffer",
        "Distributed Clocks", "DC", "System Time",
        "ESM", "EtherCAT State Machine",
        "Init", "PreOp", "SafeOp", "Op", "Boot",
        "AL Control", "AL Status",
        "CoE", "CANopen over EtherCAT",
        "SoE", "Sercos over EtherCAT",
        "EoE", "Ethernet over EtherCAT",
        "FoE", "File access over EtherCAT",
        "AoE", "ADS over EtherCAT",
        "Safety over EtherCAT", "FSoE", "Black Channel",
        "EtherCAT G", "EtherCAT P",
        "Hot Connect", "Hot Swap", "Cable Redundancy",
        "NOP", "APRD", "APWR", "APRW",
        "FPRD", "FPWR", "FPRW",
        "BRD", "BWR", "BRW",
        "LRD", "LWR", "LRW",
        "ARMW", "FRMW",
        "Auto-Increment Address", "Fixed Address",
        "Broadcast Address", "Logical Address",
        "EAP", "EtherCAT Automation Protocol",
    ]
    d["external_pins"] = [
        "MII / RMII / RGMII to two integrated Ethernet PHYs per ESC "
        "(Port 0 = upstream toward MainDevice; Port 1/2/3 = downstream). "
        "Standard Fast Ethernet 100BASE-TX over Cat 5 with 8P8C / RJ-45 connectors, "
        "or 100BASE-FX over multimode fiber for long-distance segments.",
        "PDI (Process Data Interface) on the application side of the ESC: "
        "one of (a) 8/16-bit asynchronous µC parallel bus, "
        "(b) 8/16-bit synchronous µC parallel bus, "
        "(c) SPI slave, "
        "(d) Digital I/O (up to 32-bit) with optional WD-strobe, "
        "(e) On-chip CPU bus. Includes IRQ output, INT/ECAT_DONE, "
        "and SYNC0/SYNC1 DC interrupt outputs.",
        "EEPROM Interface (SII): 2-wire I²C-compatible (SCL, SDA) to an external "
        "1-Kbit to 4-Mbit serial EEPROM holding the ESI (EtherCAT Slave Information) "
        "descriptor: Vendor ID, Product Code, Revision, Configured Station Alias, "
        "default SM/FMMU configuration, mailbox protocol bitmask.",
        "RUN / ERR / LINK / ACT LED outputs per IEC 61784-2 "
        "(RUN = ESM state, ERR = AL error, LINK = PHY link, ACT = Rx/Tx activity).",
        "EtherCAT P (single-cable variant): SE_VCC + SP_VCC dual 24 V US/UP power "
        "rails superimposed on the 100BASE-TX data pairs through ETG-defined "
        "coupling magnetics; 3 A per rail.",
    ]
    # Remove Ethernet-specific pin counts that don't apply
    for k in ("external_pin_count_mii", "external_pin_count_gmii",
              "external_pin_count_rgmii"):
        d.pop(k, None)
    d["external_pin_count_typical_esc"] = 128
    d["supported_speeds_Mbps"] = [100, 1000]
    d["supported_topologies"] = [
        "Line / Daisy-Chain", "Tree (branching)",
        "Star (via branch SubDevices)", "Ring (with cable redundancy)",
        "Drop Line", "Hot Connect / Hot Swap groups",
        "Mixed combinations of all the above",
    ]
    d["modes_of_operation"] = [
        {"name": "Cyclic process-data exchange (Op state)",
         "description": "MainDevice cyclically circulates one or more frames carrying "
                        "LRD/LWR/LRW datagrams that touch the entire process-image of "
                        "all SubDevices; cycle times typically 1 ms down to <100 µs."},
        {"name": "Mailbox communication (acyclic)",
         "description": "MainDevice/SubDevice exchange variable-length messages through "
                        "mailbox SyncManager channels (SM0 = MBox-Out, SM1 = MBox-In) "
                        "carrying CoE / SoE / EoE / FoE / AoE protocols."},
        {"name": "Distributed Clocks synchronization",
         "description": "ARMW datagram propagates the reference clock to all DC-capable "
                        "SubDevices; offset + drift compensation yields <100 ns jitter."},
        {"name": "Cable Redundancy (Ring + dual NIC)",
         "description": "MainDevice with two Ethernet ports drives the network as a ring; "
                        "on cable break the segment auto-divides into two healthy line "
                        "segments, no SubDevice loss."},
        {"name": "Hot Connect / Hot Swap",
         "description": "Defined groups of SubDevices may be added or removed from the "
                        "network during operation without disturbing the cyclic exchange."},
    ]
    d["key_features"] = [
        "On-the-fly frame processing: every ESC reads its inputs and writes its outputs "
        "into the Ethernet frame as it passes through the device's MAC, with only ~1 µs "
        "of forwarding delay per node. One frame can service thousands of nodes in one trip.",
        "Up to 65,535 SubDevices per network (16-bit Configured Station Address space); "
        "4 GB total Logical Address space (32-bit) shared by all SubDevices via FMMU.",
        "Performance: 1000 distributed digital I/O processed in 30 µs; 100 axes with 8 "
        "bytes each in 100 µs; bandwidth utilization typically >90 % on the wire.",
        "Distributed Clocks (DC): nanosecond-class synchronization across the whole network; "
        "SYNC0 / SYNC1 output pulses per SubDevice are aligned to a common System Time; "
        "jitter <100 ns measured between SubDevices several hops apart.",
        "Flexible topology: line, tree, star, ring, drop line, and mixtures.",
        "13 addressing commands via Cmd field: NOP (0x00), APRD (0x01), APWR (0x02), "
        "APRW (0x03), FPRD (0x04), FPWR (0x05), FPRW (0x06), BRD (0x07), BWR (0x08), "
        "BRW (0x09), LRD (0x0A), LWR (0x0B), LRW (0x0C), ARMW (0x0D), FRMW (0x0E).",
        "Working Counter (WKC): each datagram has a 16-bit WKC field that every addressed "
        "SubDevice increments by a deterministic amount (+1 on successful read, +2 on "
        "successful write, +3 on successful read-write).",
        "EtherCAT State Machine (ESM): six states — Init → PreOp → SafeOp → Op (+ Boot "
        "for firmware update). AL Control (0x0120) requests, AL Status (0x0130) confirms.",
        "FMMU: up to 8 per SubDevice; each maps a region of the network-wide Logical "
        "Address space (32-bit) onto a region of the local 64-KByte ESC memory at bit "
        "granularity.",
        "SyncManager: up to 8 channels per SubDevice; each is configured as either a "
        "mailbox channel (handshake, atomic write-then-read) or a process data buffer "
        "(1/2/3-buffer with hardware overrun protection).",
        "Application protocols on mailbox: CoE (CANopen over EtherCAT), SoE (Sercos), "
        "EoE (Ethernet tunneled), FoE (File access for firmware update), AoE (ADS).",
        "Safety over EtherCAT (FSoE — IEC 61784-3-12): black-channel safety frame on "
        "the mailbox transport; SIL 3 / Cat 4 / PL e capable.",
        "EtherCAT G (gigabit) and EtherCAT P (power + data on a single cable) are "
        "upward-compatible extensions.",
    ]
    d["topology_summary"] = (
        "Daisy-chain (line) is the dominant topology; the MainDevice's frame enters Port 0 "
        "of the first SubDevice, passes through every ESC, reaches the last SubDevice, and "
        "is automatically looped back upstream because each ESC closes the loop on any port "
        "that has no active link partner. Tree / star variants are formed by SubDevices "
        "that integrate 3 or 4 ports. Ring topology is used for cable redundancy. Up to "
        "65,535 SubDevices per logical bus.")
    d["package_summary"] = (
        "EtherCAT is a wire-level + frame-level + register-level specification. "
        "Connector / cabling mechanicals follow IEEE 802.3 100BASE-TX (Cat 5/5e UTP, "
        "RJ-45, or M8/M12/M23 industrial connectors) or 100BASE-FX (SC/LC/MTRJ fiber). "
        "EtherCAT P adds ETG-specified coupling magnetics and an M8 4-pin connector.")
    d["package"] = (
        "EtherCAT Slave Controllers are typically delivered as ASIC (e.g. Beckhoff "
        "ET1100 in QFN56 / BGA128, ET1200 in QFN48, ET1815/ET1816 BGA), FPGA IP "
        "cores (Intel, Xilinx, Altera, Lattice), or integrated into automation "
        "SoCs (TI Sitara, Renesas RZ/N, Infineon XMC4800, Microchip LAN9252, etc.). "
        "MainDevice implementations run on standard PCs / industrial PCs / embedded "
        "controllers with any standard Ethernet MAC + PHY (no special hardware required).")
    d["use_cases"] = [
        "Industrial machine control (CNC, robotics, packaging, semiconductor wafer handling)",
        "Multi-axis motion control (servo drive networks, EtherCAT CoE DS402 drive profile)",
        "High-density distributed I/O across hundreds of nodes",
        "Measurement systems (nanosecond-aligned distributed sampling)",
        "Functional-safety I/O networks (FSoE, SIL 3 / Cat 4 / PL e)",
        "Test and measurement (semiconductor ATE, end-of-line test cells)",
        "Medical devices and laboratory automation",
        "Automotive test rigs and HiL simulators",
        "Wind / hydro / process automation",
        "EtherCAT Automation Protocol (EAP) — plant-floor MainDevice-to-MainDevice",
    ]
    d["revision_history"] = [
        {"version": "EtherCAT introduced (Beckhoff)",
         "date": "April 2003 (Hannover Fair)",
         "description": "Public introduction of EtherCAT by Beckhoff Automation."},
        {"version": "EtherCAT Technology Group founded",
         "date": "November 2003",
         "description": "ETG founded to promote and standardize EtherCAT."},
        {"version": "IEC 61158 / IEC 61784 standardization",
         "date": "2007",
         "description": "EtherCAT becomes IEC standard (IEC 61158 Type 12 + IEC 61784 CPF 12)."},
        {"version": "Safety over EtherCAT",
         "date": "2010",
         "description": "FSoE standardized as IEC 61784-3-12."},
        {"version": "EtherCAT P", "date": "2015",
         "description": "Single-cable variant — 24 V US + 24 V UP superimposed on data."},
        {"version": "EtherCAT G", "date": "2018",
         "description": "1 Gb/s and 10 Gb/s variants."},
        {"version": "ETG Brochure (this document)",
         "date": "March 2024",
         "description": "Updated technical + marketing overview brochure."},
    ]
    d["overview"] = (
        "EtherCAT extends the Ethernet standard so that a single Ethernet frame can be "
        "used as a periodically circulated 'process data train' that visits every SubDevice "
        "on the network. The frames are forwarded through each SubDevice's two-port ESC at "
        "full 100 Mb/s wire speed; while passing through, the ESC's hardware-implemented "
        "FMMU + SyncManager + DPRAM logic reads the bits addressed to this SubDevice and "
        "writes the bits the SubDevice has produced directly into the frame. The on-the-fly "
        "mechanism removes both the per-node store-and-forward latency of switched Ethernet "
        "and the per-frame framing overhead of one-frame-per-device protocols. The MainDevice "
        "runs on any standard Ethernet NIC; no special hardware is required on the controller "
        "side. The SubDevice side is a dedicated ESC ASIC or FPGA IP (Beckhoff ET1100/ET1200/"
        "ET1815, Microchip LAN9252, Renesas RZ/N, TI Sitara, etc.).")
    d["block_diagram_components"] = [
        "MainDevice software stack running on a standard PC / embedded controller; "
        "uses any standard Ethernet NIC.",
        "Standard Ethernet PHY + MAC (no EtherCAT-specific silicon on MainDevice side).",
        "EtherCAT cable (Cat 5 or better, up to 100 m between nodes, 100 km+ with fiber).",
        "EtherCAT Slave Controller (ESC) ASIC or FPGA, with 2-4 integrated Ethernet ports, "
        "FMMU array (8), SyncManager array (8), Distributed Clock unit, EEPROM interface, "
        "PDI to local µC.",
        "Per-SubDevice local microcontroller running the application firmware and the slave "
        "stack (ESM handler, mailbox protocol handlers — CoE/SoE/EoE/FoE/AoE).",
        "External SII EEPROM (1 Kbit to 4 Mbit) holding the ESI descriptor.",
        "Optional Safety SubDevice running an FSoE stack on top of the standard slave stack.",
        "Optional EtherCAT P coupling magnetics for single-cable power+data installations.",
    ]
    d["process_technology"] = (
        "Implementation-defined: ESC ASICs are typically 90/65/55/40 nm CMOS. "
        "FPGA IP cores target any modern fabric. Brochure-level spec does not pin process.")
    d["transaction_summary"] = (
        "EtherCAT communication consists of (a) cyclic process-data exchange in state Op, "
        "driven by LRD/LWR/LRW datagrams targeting the network-wide Logical Address space, "
        "and (b) acyclic mailbox communication in states PreOp/SafeOp/Op driven by FPRD/FPWR "
        "targeting fixed SubDevice mailbox SyncManager regions.")
    d["data_model_summary"] = (
        "Each SubDevice exposes a 64-KByte local ESC memory containing: "
        "(1) hardwired ESC control/status registers at 0x000-0x0FFF, "
        "(2) DPRAM for process data + mailbox at 0x1000-0xFFFF. "
        "MainDevice configures: SM0/SM1 = mailbox, SM2/SM3 = process data, "
        "FMMU0..FMMU2 = logical→physical mapping.")
    _write(p, d)


def _apply_l2(gd: Path) -> None:
    """L2 FRS — replace Ethernet protocol_overview and functional_requirements
    with the EtherCAT layer (datagrams + ESM + FMMU + SM + DC)."""
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_overview"] = {
        "type": (
            "Industrial Ethernet fieldbus with on-the-fly frame processing. The MainDevice "
            "circulates Ethernet frames carrying one or more EtherCAT datagrams; SubDevices "
            "implemented as EtherCAT Slave Controllers (ESC) read/modify/forward the frame "
            "while it is passing through their MAC. Layered above the wire: 13-command "
            "addressing scheme, 6-state EtherCAT State Machine (ESM), SyncManager + FMMU "
            "memory model, optional Distributed Clocks, and mailbox-resident application "
            "protocols (CoE / SoE / EoE / FoE / AoE)."),
        "transport": (
            "Standard 100BASE-TX (100 Mb/s) or 100BASE-FX Ethernet; EtherCAT G extends to "
            "1 Gb/s. Two carrier modes: (a) raw Ethernet frames with EtherType 0x88A4 "
            "(default), (b) UDP/IP encapsulation on port 0x88A4."),
        "duplex": "Full duplex (100BASE-TX always full duplex).",
        "topology_supported": (
            "Line (daisy-chain — dominant), tree, star, ring with redundancy, drop line, "
            "mixed; up to 65,535 SubDevices per logical bus."),
        "master_count": (
            "Single MainDevice per logical bus in the cyclic phase. EAP enables "
            "MainDevice-to-MainDevice exchange at the plant level."),
        "slave_count_max": 65535,
        "synchronization": (
            "Distributed Clocks (DC) sub-protocol: ARMW (Cmd 0x0D) datagrams propagate the "
            "reference clock; hardware offset + drift compensation yields <100 ns jitter."),
        "cycle_time_typical_us": [100, 250, 500, 1000, 2000, 4000],
        "process_data_per_frame_max_B": 1486,
        "interfaces_in_scope": [
            "ESC IO (two or more Fast/Gigabit Ethernet ports + on-the-fly forwarding logic)",
            "PDI (Process Data Interface): async µC bus, sync µC bus, SPI, DIO, on-chip CPU bus",
            "EEPROM SII interface (I²C-compatible 2-wire) carrying the ESI descriptor",
            "MainDevice = standard Ethernet NIC; no EtherCAT-specific hardware required",
        ],
    }
    d["functional_requirements"] = [
        {"id": "FR-FRAME-01", "text":
         "Every EtherCAT frame on the wire shall be a standard Ethernet frame with "
         "EtherType = 0x88A4 (Raw-Ethernet) or shall be encapsulated inside a UDP/IP "
         "packet with destination UDP port 0x88A4 (UDP/IP mode)."},
        {"id": "FR-ECATHDR-02", "text":
         "The EtherCAT header is exactly 16 bits: Length[10:0], Reserved[12]=0, "
         "Type[15:12] = 0x1 for ESC datagrams (Type 0x4 reserved for Network Variables / EAP)."},
        {"id": "FR-DGHDR-03", "text":
         "Each EtherCAT datagram begins with a 10-byte header: Cmd[7:0], Idx[7:0], "
         "Address[31:0], Length[10:0], Reserved[2:0], Circulating[14], Next[15], IRQ[15:0]. "
         "The datagram ends with the Data field followed by a 16-bit Working Counter."},
        {"id": "FR-CMD-04", "text":
         "The Cmd field takes one of 15 values: 0x00 NOP, 0x01 APRD, 0x02 APWR, 0x03 APRW, "
         "0x04 FPRD, 0x05 FPWR, 0x06 FPRW, 0x07 BRD, 0x08 BWR, 0x09 BRW, 0x0A LRD, 0x0B LWR, "
         "0x0C LRW, 0x0D ARMW, 0x0E FRMW. All other values are reserved."},
        {"id": "FR-AP-05", "text":
         "Auto-Increment addressing (APRD/APWR/APRW/ARMW): Address high half is signed 16-bit "
         "Position incremented by every SubDevice; SubDevice executes when its incremented "
         "Position becomes 0x0000."},
        {"id": "FR-FP-06", "text":
         "Fixed Physical addressing (FPRD/FPWR/FPRW/FRMW): Address high half is the 16-bit "
         "Configured Station Address from ESC register 0x0010-0x0011."},
        {"id": "FR-BC-07", "text":
         "Broadcast addressing (BRD/BWR/BRW): Address high half ignored; every SubDevice executes."},
        {"id": "FR-LOG-08", "text":
         "Logical addressing (LRD/LWR/LRW): Address is the full 32-bit Logical Address; "
         "every SubDevice's FMMUs map a region of this onto local ESC memory."},
        {"id": "FR-WKC-09", "text":
         "Working Counter (WKC) appended after data field. SubDevices increment by +1 on "
         "successful read, +2 on successful write, +3 on successful read-write."},
        {"id": "FR-DC-10", "text":
         "Distributed Clocks: first DC-capable SubDevice's ESC time is the System Time "
         "reference; MainDevice issues ARMW to propagate; SubDevices close the loop via "
         "System Time Offset (0x0920) writes, achieving <100 ns jitter."},
        {"id": "FR-FMMU-11", "text":
         "FMMU: up to 8 per SubDevice at registers 0x0600-0x06FF; each entry maps a slice of "
         "network-wide 32-bit Logical Address space onto a slice of local ESC memory at bit "
         "granularity."},
        {"id": "FR-SM-12", "text":
         "SyncManager: up to 8 channels per SubDevice at 0x0800-0x08FF; configured as "
         "Mailbox mode (atomic handshake) or Buffered process-data mode (1/2/3-buffer ring "
         "with overrun protection)."},
        {"id": "FR-ESM-13", "text":
         "EtherCAT State Machine has six states: Init (0x01), PreOp (0x02), Boot (0x03), "
         "SafeOp (0x04), Op (0x08), and implicit Off. MainDevice requests next state via "
         "AL Control (0x0120); SubDevice confirms via AL Status (0x0130); errors in AL "
         "Status Code (0x0134)."},
        {"id": "FR-ESC-14", "text":
         "Each SubDevice contains an EtherCAT Slave Controller (ESC) with: 64 KByte memory "
         "space at 0x0000-0xFFFF; 2-4 Ethernet ports with on-the-fly processing engine, "
         "port loop-back, auto-forwarding, per-port CRC error counters; SII state machine; "
         "FMMU array; SyncManager array; optional Distributed Clock unit."},
        {"id": "FR-PDI-15", "text":
         "Each ESC exposes one Process Data Interface (PDI) to the application µC. PDI type "
         "selected in 0x0140 PDI Control: asynchronous/synchronous µC bus, SPI, DIO, or "
         "on-chip CPU bus."},
        {"id": "FR-SII-16", "text":
         "Each SubDevice has an external serial EEPROM (1 Kbit-4 Mbit, I²C-compatible 2-wire) "
         "holding ESI: Vendor ID, Product Code, Revision, Serial, SM/FMMU defaults, mailbox "
         "protocol bitmask, PDI configuration."},
        {"id": "FR-COE-17", "text":
         "CoE (CANopen over EtherCAT): re-uses CiA 301/4xx Object Dictionary. SDO Read/Write, "
         "SDO Information, PDO. DS-402 is the canonical drive profile."},
        {"id": "FR-SOE-18", "text":
         "SoE (Sercos over EtherCAT): IEC 61800-7 / Sercos III IDN-addressed parameter access."},
        {"id": "FR-EOE-19", "text":
         "EoE (Ethernet over EtherCAT): tunnels arbitrary 802.3 Ethernet frames inside mailbox."},
        {"id": "FR-FOE-20", "text":
         "FoE (File access over EtherCAT): TFTP-like firmware update in Boot state."},
        {"id": "FR-AOE-21", "text":
         "AoE (ADS over EtherCAT): Beckhoff TwinCAT routed messaging (AMS Net Id + Port)."},
        {"id": "FR-FSOE-22", "text":
         "Safety over EtherCAT (FSoE, IEC 61784-3-12): black-channel safety frame on mailbox; "
         "SIL 3 / Cat 4 / PL e capable."},
        {"id": "FR-ESC-PORT-23", "text":
         "Each ESC port (Port 0/1/2/3) has hardware-implemented automatic loopback: if no "
         "active link partner is present the ESC closes the loop internally and forwards "
         "back upstream."},
        {"id": "FR-LATENCY-24", "text":
         "Forwarding latency through one ESC is ~1 µs at 100 Mb/s (300 ns - 1.5 µs vendor-dependent)."},
        {"id": "FR-HOTCON-25", "text":
         "Hot Connect / Hot Swap defines groups of SubDevices that may join/leave during "
         "operation. MainDevice tolerates absence."},
    ]
    d["error_response_conditions"] = [
        {"id": "ER-CRC", "text":
         "FCS error on receive (per-port hardware-counted in ESC registers 0x0300-0x030F): "
         "forwarded frames continue, Frame Error Counter increments."},
        {"id": "ER-WKC", "text":
         "Working Counter mismatch: MainDevice compares returned WKC against expected; "
         "mismatch escalates to application layer."},
        {"id": "ER-AL", "text":
         "AL Status mismatch (0x0130): if SubDevice cannot satisfy MainDevice-requested ESM "
         "transition, AL Status holds previous state OR'ed with Error bit (bit 4); AL Status "
         "Code (0x0134) carries IEC 61158-defined error number."},
        {"id": "ER-PDI", "text":
         "PDI watchdog (0x0410-0x041F): missing PDI write within timeout asserts PDI WD pin, "
         "optionally resets process-data outputs to Safe state."},
        {"id": "ER-SM", "text":
         "SyncManager error (0x0805 SM Status): mailbox buffer-full/buffer-empty; buffered-mode "
         "overrun; mailbox watchdog timeout."},
        {"id": "ER-LINK", "text":
         "Link loss on any port (0x0110 DL Status): affected port Loop-State changes "
         "open→closed; ESC auto-forwards on loop-back path."},
    ]
    d["compliance_requirements"] = [
        "EtherCAT Conformance Test (ETG.1500 / ETG.1500.1) — mandatory before commercial "
        "release of any EtherCAT SubDevice.",
        "EtherCAT MainDevice Classification (ETG.1500.2): Class A (full feature set) vs "
        "Class B (basic feature set).",
        "Vendor ID assignment by ETG (32-bit identifier).",
        "ESI XML file per ETG.2000 schema, published by vendor.",
        "Safety over EtherCAT (FSoE) certification per IEC 61784-3-12 for SIL 3 / Cat 4 / PL e.",
        "IEC 61158 Type 12 + IEC 61784 CPF 12 international standardization; SEMI E54.20.",
    ]
    _write(p, d)


def _apply_l3(gd: Path) -> None:
    """L3 CMD_PROTOCOL — replace Ethernet's MII/MDIO frame catalog with
    EtherCAT datagram + Cmd table + addressing modes."""
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "EtherCAT runs three nested protocols in one packet: (a) outer Ethernet frame "
        "(DA + SA + EtherType 0x88A4 + Payload + FCS), (b) EtherCAT header (Length + "
        "Reserved + Type=0x1), (c) one or more EtherCAT datagrams chained by the Next bit, "
        "each carrying its own Cmd / Idx / Address / Length / IRQ / Data / WKC.")
    d["channels"] = [
        {"name": "Ethernet wire — Port 0 (Upstream)",
         "direction": "MainDevice ↔ first SubDevice",
         "description": "Standard 100BASE-TX or 100BASE-FX. EtherType 0x88A4 frames."},
        {"name": "Ethernet wire — Port 1/2/3 (Downstream)",
         "direction": "SubDevice ↔ next SubDevice",
         "description": "On-the-fly forwarding to next SubDevice. Last port loops back."},
        {"name": "PDI (Process Data Interface)",
         "direction": "ESC ↔ local µC",
         "description": "Async/sync µC bus, SPI, DIO, or on-chip CPU bus. Plus IRQ, "
                        "SYNC0/SYNC1 DC outputs, LATCH0/LATCH1 DC inputs."},
        {"name": "SII (EEPROM Slave Information Interface)",
         "direction": "ESC ↔ external EEPROM",
         "description": "I²C-compatible 2-wire to serial EEPROM (1 Kbit-4 Mbit)."},
    ]
    d["packet_classes"] = [
        {"class": "EtherCAT frame (raw Ethernet, EtherType 0x88A4)",
         "purpose": "Default low-latency on-segment transport. DA unconstrained.",
         "format": "Preamble(7B) + SFD(1B) + DA(6B) + SA(6B) + EtherType=0x88A4(2B) + "
                   "EtherCAT_Header(2B) + Datagram_block(60-1500B) + FCS(4B)"},
        {"class": "EtherCAT frame (UDP/IP, dst port 0x88A4)",
         "purpose": "Cross-network routing through standard IP infrastructure.",
         "format": "Eth(EtherType=0x0800) + IP + UDP(dst=0x88A4) + EtherCAT_Header + "
                   "Datagram_block + Eth_FCS"},
        {"class": "EtherCAT datagram",
         "purpose": "One unit of read/modify/write addressing inside the frame.",
         "format": "Cmd(1B) + Idx(1B) + Address(4B) + Length+Next(2B) + IRQ(2B) + "
                   "Data(Length B) + Working_Counter(2B)"},
        {"class": "Mailbox transport frame (SM0+SM1)",
         "purpose": "Carries CoE/SoE/EoE/FoE/AoE/VoE messages.",
         "format": "Mbx_Header(6B) + Mbx_Data(per protocol)"},
    ]
    d["ethercat_header_format"] = {
        "size_bytes": 2,
        "fields": [
            {"name": "Length",   "bits": "10:0",  "description": "Total length of following datagrams in bytes."},
            {"name": "Reserved", "bits": "11",    "description": "0"},
            {"name": "Type",     "bits": "15:12", "description": "0x1=ESC datagram, 0x4=Network Variables, 0x5=Mailbox-only"},
        ],
    }
    d["datagram_header_format"] = {
        "size_bytes": 10,
        "fields": [
            {"offset": 0, "name": "Cmd",         "size_bits": 8,  "description": "Command code (see commands_table)."},
            {"offset": 1, "name": "Idx",         "size_bits": 8,  "description": "MainDevice-local opaque index."},
            {"offset": 2, "name": "Address",     "size_bits": 32, "description": "Cmd-dependent: AP→Position+Offset, FP→ConfigStaAddr+Offset, BC→0+Offset, LOG→32-bit Logical."},
            {"offset": 6, "name": "Length",      "size_bits": 11, "description": "Data length 1..1486 in bytes."},
            {"offset": 6, "name": "Reserved",    "size_bits": 3,  "description": "0"},
            {"offset": 6, "name": "Circulating", "size_bits": 1,  "description": "Already gone around once."},
            {"offset": 6, "name": "Next",        "size_bits": 1,  "description": "1 = another datagram follows."},
            {"offset": 8, "name": "IRQ",         "size_bits": 16, "description": "AL Status interrupt aggregate."},
        ],
        "datagram_tail": {
            "data_offset": 10,
            "data_length": "Length bytes",
            "wkc_offset": "10 + Length",
            "wkc_size_bytes": 2,
            "description": "After the Data field, every datagram ends with a 16-bit "
                           "Working Counter (WKC) updated by each addressed SubDevice.",
        },
    }
    d["commands_table"] = [
        {"cmd_hex": "0x00", "name": "NOP",  "long_name": "No Operation",                      "addressing": "—",            "wkc_increment_rule": "0",                                                        "typical_use": "Padding / frame timing."},
        {"cmd_hex": "0x01", "name": "APRD", "long_name": "Auto-Increment Read",               "addressing": "AP",            "wkc_increment_rule": "+1 by SubDevice whose Position == 0 after increment.",     "typical_use": "Start-up sweep before Configured Station Address."},
        {"cmd_hex": "0x02", "name": "APWR", "long_name": "Auto-Increment Write",              "addressing": "AP",            "wkc_increment_rule": "+1 by SubDevice whose Position == 0 after increment.",     "typical_use": "Initial register write during start-up."},
        {"cmd_hex": "0x03", "name": "APRW", "long_name": "Auto-Increment ReadWrite",          "addressing": "AP",            "wkc_increment_rule": "+3 (= +1 read + +2 write).",                               "typical_use": "Atomic register read-then-write during start-up."},
        {"cmd_hex": "0x04", "name": "FPRD", "long_name": "Configured Address Read",           "addressing": "FP",            "wkc_increment_rule": "+1 by SubDevice whose Configured Station Address matches.","typical_use": "Targeted read of one specific SubDevice."},
        {"cmd_hex": "0x05", "name": "FPWR", "long_name": "Configured Address Write",          "addressing": "FP",            "wkc_increment_rule": "+1 by matching SubDevice.",                                "typical_use": "Targeted register write — AL Control, SM, FMMU."},
        {"cmd_hex": "0x06", "name": "FPRW", "long_name": "Configured Address RW",             "addressing": "FP",            "wkc_increment_rule": "+3 by matching SubDevice.",                                "typical_use": "Targeted atomic read-then-write."},
        {"cmd_hex": "0x07", "name": "BRD",  "long_name": "Broadcast Read",                    "addressing": "BC",            "wkc_increment_rule": "+1 by every SubDevice.",                                   "typical_use": "Cyclic status sweep (e.g. AL Status of every SubDevice)."},
        {"cmd_hex": "0x08", "name": "BWR",  "long_name": "Broadcast Write",                   "addressing": "BC",            "wkc_increment_rule": "+1 by every SubDevice.",                                   "typical_use": "Network-wide configuration."},
        {"cmd_hex": "0x09", "name": "BRW",  "long_name": "Broadcast ReadWrite",               "addressing": "BC",            "wkc_increment_rule": "+3 by every SubDevice.",                                   "typical_use": "Broadcast atomic read-then-write."},
        {"cmd_hex": "0x0A", "name": "LRD",  "long_name": "Logical Read",                      "addressing": "LOG",           "wkc_increment_rule": "+1 by every SubDevice whose Read-Type FMMU maps the bits.","typical_use": "Cyclic process-data INPUT."},
        {"cmd_hex": "0x0B", "name": "LWR",  "long_name": "Logical Write",                     "addressing": "LOG",           "wkc_increment_rule": "+1 by every SubDevice whose Write-Type FMMU maps.",        "typical_use": "Cyclic process-data OUTPUT."},
        {"cmd_hex": "0x0C", "name": "LRW",  "long_name": "Logical ReadWrite",                 "addressing": "LOG",           "wkc_increment_rule": "+1 read + +2 write per successful SubDevice.",             "typical_use": "Combined process-data IO (most common cyclic command)."},
        {"cmd_hex": "0x0D", "name": "ARMW", "long_name": "Auto-Increment Read, Multiple Write","addressing": "AP+MultiWrite", "wkc_increment_rule": "+1 by first matching SubDevice; downstream SubDevices read.","typical_use": "Distributed Clock System Time propagation."},
        {"cmd_hex": "0x0E", "name": "FRMW", "long_name": "Fixed Read, Multiple Write",        "addressing": "FP+MultiWrite", "wkc_increment_rule": "+1 by FP-matching SubDevice; downstream SubDevices copy.",  "typical_use": "Re-distribute value from one FP-addressed SubDevice."},
    ]
    d["addressing_modes"] = [
        {"name": "Position (AP)",   "cmd_codes": ["APRD","APWR","APRW","ARMW"], "address_high_word_meaning": "Signed 16-bit position; incremented at each SubDevice; match @ 0x0000.", "low_word_meaning": "16-bit local ESC offset."},
        {"name": "Configured (FP)", "cmd_codes": ["FPRD","FPWR","FPRW","FRMW"], "address_high_word_meaning": "16-bit Configured Station Address (0x0010-0x0011).",                    "low_word_meaning": "16-bit local ESC offset."},
        {"name": "Broadcast (BC)",  "cmd_codes": ["BRD","BWR","BRW"],            "address_high_word_meaning": "Ignored; every SubDevice matches.",                                    "low_word_meaning": "16-bit local ESC offset."},
        {"name": "Logical (LOG)",   "cmd_codes": ["LRD","LWR","LRW"],            "address_high_word_meaning": "Part of 32-bit network-wide Logical Address space.",                   "low_word_meaning": "Part of 32-bit Logical Address."},
    ]
    d["esm_state_transitions"] = [
        {"from": "Init",   "to": "PreOp",  "trigger": "AL Control = 0x02"},
        {"from": "Init",   "to": "Boot",   "trigger": "AL Control = 0x03"},
        {"from": "PreOp",  "to": "SafeOp", "trigger": "AL Control = 0x04"},
        {"from": "SafeOp", "to": "Op",     "trigger": "AL Control = 0x08"},
        {"from": "Op",     "to": "SafeOp", "trigger": "AL Control = 0x04 OR PD WD expiry"},
        {"from": "*",      "to": "Init",   "trigger": "AL Control = 0x01"},
        {"from": "Boot",   "to": "Init",   "trigger": "AL Control = 0x01"},
    ]
    d["mailbox_protocols_on_sm"] = [
        {"name": "CoE",  "long_name": "CANopen over EtherCAT",     "mbx_type": "0x03", "description": "SDO Read/Write, SDO Info, PDO. DS-402 drive profile most common."},
        {"name": "EoE",  "long_name": "Ethernet over EtherCAT",    "mbx_type": "0x02", "description": "Tunnels 802.3 frames for IP apps on SubDevice."},
        {"name": "FoE",  "long_name": "File access over EtherCAT", "mbx_type": "0x04", "description": "TFTP-like firmware download in Boot state."},
        {"name": "SoE",  "long_name": "Servo Profile (Sercos)",    "mbx_type": "0x05", "description": "IEC 61800-7 IDN parameter access."},
        {"name": "VoE",  "long_name": "Vendor-specific",           "mbx_type": "0x0F", "description": "Vendor-defined mailbox protocol."},
        {"name": "AoE",  "long_name": "ADS over EtherCAT",         "mbx_type": "0x01", "description": "Beckhoff routed messaging (AMS Net Id + Port)."},
    ]
    d["transaction_classes_split"] = {
        "cyclic": ["LRD", "LWR", "LRW", "BRD"],
        "acyclic_register": ["APRD", "APWR", "APRW", "FPRD", "FPWR", "FPRW"],
        "broadcast_config": ["BWR", "BRW"],
        "distributed_clocks": ["ARMW", "FRMW"],
    }
    # Strip Ethernet-leaning sub-keys that the Ethernet synth may have left
    for k in ("mac_frame_format", "mdio_clause22_frame", "mdio_clause45_frame",
              "auto_negotiation_format"):
        d.pop(k, None)
    _write(p, d)


def _apply_l4(gd: Path) -> None:
    """L4 REGMAP — replace IEEE Clause-22 PHY register map with the
    ESC 0x000-0xFFF register region (DL Control, AL Control/Status, FMMU,
    SyncManager, Distributed Clocks, SII, MII Management)."""
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_address_scheme"] = (
        "Every EtherCAT Slave Controller (ESC) exposes a single, flat 64-KByte memory map "
        "at offsets 0x0000-0xFFFF. The map is divided into a hardware-fixed Register Region "
        "at 0x0000-0x0FFF and a configurable DPRAM Region at 0x1000-0xFFFF used for "
        "Process-Data and Mailbox SyncManager buffers. Access from the wire uses Cmd-dependent "
        "addressing (AP/FP/BC/LOG); access from the local µC uses the PDI (byte-level R/W).")
    d["esc_register_region_summary"] = [
        {"range": "0x0000-0x000F", "name": "ESC Information",            "purpose": "Type, Revision, Build, Number of FMMUs/SMs, RAM size, Port descriptor, ESC features."},
        {"range": "0x0010-0x001F", "name": "Station Address",            "purpose": "Configured Station Address + Configured Station Alias."},
        {"range": "0x0020-0x002F", "name": "Write Protection",           "purpose": "Register Write Enable / Protection."},
        {"range": "0x0040-0x004F", "name": "ESC Reset",                  "purpose": "ESC reset request from PDI and ECAT bus."},
        {"range": "0x0100-0x010F", "name": "ESC DL Control",             "purpose": "Forwarding mode, Loop Control per port, Station Alias enable."},
        {"range": "0x0110-0x011F", "name": "ESC DL Status",              "purpose": "Per-port link state, loop state, signal-detect, PDI operational."},
        {"range": "0x0120-0x013F", "name": "AL Control + Status",        "purpose": "AL Control (0x0120), AL Status (0x0130), AL Status Code (0x0134)."},
        {"range": "0x0140-0x014F", "name": "PDI Control",                "purpose": "PDI type selector (async µC, sync µC, SPI, DIO, on-chip CPU)."},
        {"range": "0x0150-0x015F", "name": "PDI Configuration",          "purpose": "PDI-specific (SPI mode, data hold time)."},
        {"range": "0x0200-0x020F", "name": "Interrupt Mask + Request",   "purpose": "ECAT Event Mask, PDI Interrupt Config, IRQ enable."},
        {"range": "0x0220-0x022F", "name": "Interrupt Status",           "purpose": "Per-event status latching."},
        {"range": "0x0300-0x030F", "name": "RX Error Counters",          "purpose": "Per-port Frame/Physical/Forwarded RX Error counters."},
        {"range": "0x0310-0x031F", "name": "Lost Link Counters",         "purpose": "Per-port lost-link counter."},
        {"range": "0x0400-0x040F", "name": "Watchdog Divider",           "purpose": "Watchdog time base."},
        {"range": "0x0410-0x042F", "name": "Process-Data WD + PDI WD",   "purpose": "Process-data + PDI watchdog timeouts."},
        {"range": "0x0500-0x050F", "name": "EEPROM Interface (SII)",     "purpose": "EEPROM Config (0x0500), PDI Access (0x0501), Control/Status (0x0502), Address (0x0504), Data (0x0508)."},
        {"range": "0x0510-0x05FF", "name": "MII Management Interface",   "purpose": "MII PHY register access — Control/Status (0x0510), PHY Address (0x0512), PHY Reg Addr (0x0513), Data (0x0514)."},
        {"range": "0x0600-0x06FF", "name": "FMMU (8 entries × 16 bytes)", "purpose": "Per-FMMU: Logical Start Addr, Length, Logical Start/Stop Bit, Physical Start Addr, Physical Start Bit, Type R/W, Active."},
        {"range": "0x0800-0x087F", "name": "SyncManager (8 × 8 bytes)",  "purpose": "Per-SM: Physical Start Addr, Length, Control, Status, Activate, PDI Control."},
        {"range": "0x0900-0x09FF", "name": "Distributed Clocks",         "purpose": "Receive Time per port, System Time (0x0910), System Time Offset (0x0920), System Time Delay (0x0928), SYNC0/SYNC1 Cycle Time (0x0990/0x0994)."},
        {"range": "0x0F00-0x0F0F", "name": "ESC Specific Registers",     "purpose": "ESC-vendor-specific."},
        {"range": "0x1000-0xFFFF", "name": "DPRAM (Process Data + Mailbox)", "purpose": "Configurable user space. Typical: SM0 MBox-Out @ 0x1000, SM1 MBox-In @ 0x1400, SM2 Outputs, SM3 Inputs."},
    ]
    d["station_address_registers"] = [
        {"offset_hex": "0x0010", "name": "Configured Station Address", "width_bits": 16, "access": "R/W"},
        {"offset_hex": "0x0012", "name": "Configured Station Alias",   "width_bits": 16, "access": "R/W"},
    ]
    d["al_control_status_registers"] = [
        {"offset_hex": "0x0120", "name": "AL Control",  "width_bits": 16, "access": "R/W",
         "field_layout": [
             {"bits": "3:0",  "name": "State",                  "values": "1=Init, 2=PreOp, 3=Boot, 4=SafeOp, 8=Op"},
             {"bits": "4",    "name": "Acknowledge",             "values": "1 = ack AL Status Code"},
             {"bits": "5",    "name": "Device Identification",   "values": "1 = request Device Identification"},
             {"bits": "15:6", "name": "Reserved",                "values": "0"},
         ]},
        {"offset_hex": "0x0130", "name": "AL Status",   "width_bits": 16, "access": "RO",
         "field_layout": [
             {"bits": "3:0",  "name": "State",        "values": "Current ESM state"},
             {"bits": "4",    "name": "Error Ind.",   "values": "1 = transition failed"},
             {"bits": "5",    "name": "DevID Valid",  "values": "1 = Dev Identification valid"},
             {"bits": "15:6", "name": "Reserved",     "values": "0"},
         ]},
        {"offset_hex": "0x0134", "name": "AL Status Code", "width_bits": 16, "access": "RO",
         "description": "IEC 61158 error code (e.g. 0x0011 'Invalid requested state change', 0x001E 'Invalid Input Configuration', 0x0030 'DC Invalid Sync Configuration')."},
    ]
    d["fmmu_entry_layout"] = {
        "size_bytes": 16, "base_addr_hex": "0x0600", "stride_bytes": 16, "count": 8,
        "fields": [
            {"offset": 0,  "name": "Logical Start Address",  "size_bytes": 4},
            {"offset": 4,  "name": "Length",                 "size_bytes": 2},
            {"offset": 6,  "name": "Logical Start Bit",      "size_bits": 3},
            {"offset": 7,  "name": "Logical Stop Bit",       "size_bits": 3},
            {"offset": 8,  "name": "Physical Start Address", "size_bytes": 2},
            {"offset": 10, "name": "Physical Start Bit",     "size_bits": 3},
            {"offset": 11, "name": "Type — Read",            "size_bits": 1},
            {"offset": 11, "name": "Type — Write",           "size_bits": 1},
            {"offset": 12, "name": "Activate",               "size_bytes": 1},
            {"offset": 13, "name": "Reserved",               "size_bytes": 3},
        ],
    }
    d["sm_entry_layout"] = {
        "size_bytes": 8, "base_addr_hex": "0x0800", "stride_bytes": 8, "count": 8,
        "fields": [
            {"offset": 0, "name": "Physical Start Address", "size_bytes": 2},
            {"offset": 2, "name": "Length",                 "size_bytes": 2},
            {"offset": 4, "name": "Control",                "size_bytes": 1,
             "field_layout": [
                 {"bits": "1:0", "name": "Operation Mode", "values": "00=3-buffer, 01=Reserved, 10=Mailbox, 11=Reserved"},
                 {"bits": "3:2", "name": "Direction",       "values": "00=Read (Outputs), 01=Write (Inputs)"},
                 {"bits": "4",   "name": "ECAT Event En",   "values": "1 = IRQ to MainDevice"},
                 {"bits": "5",   "name": "PDI Event En",    "values": "1 = IRQ to PDI"},
                 {"bits": "6",   "name": "Watchdog En",     "values": "1 = trigger Process-Data WD"},
                 {"bits": "7",   "name": "Reserved",        "values": "0"},
             ]},
            {"offset": 5, "name": "Status",      "size_bytes": 1, "description": "Buffer state / mailbox state / IRQ pending."},
            {"offset": 6, "name": "Activate",    "size_bytes": 1},
            {"offset": 7, "name": "PDI Control", "size_bytes": 1},
        ],
        "canonical_assignment": [
            {"sm": "SM0", "purpose": "MBox-Out",  "direction": "MainDevice → SubDevice", "mode": "Mailbox"},
            {"sm": "SM1", "purpose": "MBox-In",   "direction": "SubDevice → MainDevice", "mode": "Mailbox"},
            {"sm": "SM2", "purpose": "Outputs",   "direction": "MainDevice → SubDevice", "mode": "Buffered 3-buffer"},
            {"sm": "SM3", "purpose": "Inputs",    "direction": "SubDevice → MainDevice", "mode": "Buffered 3-buffer"},
        ],
    }
    d["distributed_clocks_registers"] = [
        {"offset_hex": "0x0900", "name": "Receive Time Port 0", "width_bits": 32, "access": "RO"},
        {"offset_hex": "0x0904", "name": "Receive Time Port 1", "width_bits": 32, "access": "RO"},
        {"offset_hex": "0x0908", "name": "Receive Time Port 2", "width_bits": 32, "access": "RO"},
        {"offset_hex": "0x090C", "name": "Receive Time Port 3", "width_bits": 32, "access": "RO"},
        {"offset_hex": "0x0910", "name": "System Time",         "width_bits": 64, "access": "R/W (ARMW)"},
        {"offset_hex": "0x0918", "name": "Receive Time PDI",    "width_bits": 64, "access": "RO"},
        {"offset_hex": "0x0920", "name": "System Time Offset",  "width_bits": 64, "access": "R/W"},
        {"offset_hex": "0x0928", "name": "System Time Delay",   "width_bits": 32, "access": "R/W"},
        {"offset_hex": "0x092C", "name": "System Time Diff",    "width_bits": 32, "access": "RO"},
        {"offset_hex": "0x0980", "name": "Cyclic Unit Control", "width_bits": 8,  "access": "R/W"},
        {"offset_hex": "0x0981", "name": "Activation",          "width_bits": 8,  "access": "R/W"},
        {"offset_hex": "0x0990", "name": "Sync0 Cycle Time",    "width_bits": 32, "access": "R/W"},
        {"offset_hex": "0x0994", "name": "Sync1 Cycle Time",    "width_bits": 32, "access": "R/W"},
        {"offset_hex": "0x09A0", "name": "Sync Start Time",     "width_bits": 64, "access": "R/W"},
    ]
    d["eeprom_sii_registers"] = [
        {"offset_hex": "0x0500", "name": "EEPROM Configuration", "width_bits": 8,  "access": "R/W"},
        {"offset_hex": "0x0501", "name": "EEPROM PDI Access",    "width_bits": 8,  "access": "R/W"},
        {"offset_hex": "0x0502", "name": "EEPROM Control/Status","width_bits": 16, "access": "R/W"},
        {"offset_hex": "0x0504", "name": "EEPROM Address",       "width_bits": 32, "access": "R/W"},
        {"offset_hex": "0x0508", "name": "EEPROM Data",          "width_bits": 64, "access": "R/W"},
    ]
    d["mii_management_registers"] = [
        {"offset_hex": "0x0510", "name": "MII Control/Status",       "width_bits": 16, "access": "R/W"},
        {"offset_hex": "0x0512", "name": "PHY Address",              "width_bits": 5,  "access": "R/W"},
        {"offset_hex": "0x0513", "name": "PHY Register Address",     "width_bits": 5,  "access": "R/W"},
        {"offset_hex": "0x0514", "name": "PHY Data",                 "width_bits": 16, "access": "R/W"},
        {"offset_hex": "0x0516", "name": "MII ECAT-Access Enable",   "width_bits": 8,  "access": "R/W"},
    ]
    d["esc_information_registers"] = [
        {"offset_hex": "0x0000", "name": "Type",            "width_bits": 8,
         "access": "RO", "description": "ESC type identifier (e.g. ET1100=0x11, ET1200=0x12)."},
        {"offset_hex": "0x0001", "name": "Revision",        "width_bits": 8,
         "access": "RO", "description": "ESC revision."},
        {"offset_hex": "0x0002", "name": "Build",           "width_bits": 16,
         "access": "RO", "description": "ESC build / version."},
        {"offset_hex": "0x0004", "name": "FMMU Count",      "width_bits": 8,
         "access": "RO", "description": "Number of FMMU entries supported (typically 8)."},
        {"offset_hex": "0x0005", "name": "SyncManager Count", "width_bits": 8,
         "access": "RO", "description": "Number of SyncManagers (typically 8)."},
        {"offset_hex": "0x0006", "name": "RAM Size",        "width_bits": 8,
         "access": "RO",
         "description": "RAM size in KByte (typically 8 KByte for ET1100; 60 KByte for larger ESCs)."},
        {"offset_hex": "0x0007", "name": "Port Descriptor", "width_bits": 8,
         "access": "RO",
         "description": "Per-port descriptor: not-implemented / MII / EBUS — 2 bits per port × 4 ports."},
        {"offset_hex": "0x0008", "name": "ESC Features Supported", "width_bits": 16,
         "access": "RO",
         "description": "Bit-mask of supported features: FMMU-bit-operation, DC, DC-64bit, low-jitter EBUS, extended ALsync, etc."},
    ]
    d["rx_error_counter_registers_per_port"] = [
        {"offset_hex": "0x0300", "name": "Frame Error Counter Port 0", "width_bits": 8,
         "access": "RO",
         "description": "Increment on receive frame error (FCS, length, etc.)."},
        {"offset_hex": "0x0301", "name": "Physical RX Error Port 0",   "width_bits": 8,
         "access": "RO",
         "description": "Increment on PHY-level errors (symbol error, signal-lost)."},
        {"offset_hex": "0x0302", "name": "Forwarded RX Error Port 0",  "width_bits": 8,
         "access": "RO",
         "description": "Forwarded RX errors (errors carried in from upstream)."},
        {"offset_hex": "0x0308", "name": "Lost Link Counter Port 0",   "width_bits": 8,
         "access": "RO",
         "description": "Lost-link event counter."},
        {"comment": "Ports 1-3 use the same layout offset by +1 / +2 / +3 within each byte group."},
    ]
    # Remove Ethernet-Clause-22 register catalog left by the Ethernet synth
    for k in ("phy_clause22_register_map", "bmcr_bit_definitions",
              "bmsr_bit_definitions", "anar_field_layout",
              "anlpar_field_layout", "phy_clause45_register_map"):
        d.pop(k, None)
    _write(p, d)


def _apply_l5(gd: Path) -> None:
    """L5 ADI_SPEC — replace MII/GMII/RGMII AC tables with the ESC PDI
    + Ethernet-PHY interface model."""
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["signaling_summary"] = (
        "EtherCAT uses standard IEEE 802.3 100BASE-TX (MLT-3, 4B5B, transformer-coupled "
        "to 100 Ω twisted pair) or 100BASE-FX (NRZI on multimode fiber) on the wire. "
        "EtherCAT G extends to 1000BASE-T (PAM-5) or 1000BASE-X (8B/10B). The ESC-side "
        "MII / RMII / RGMII signaling is conventional LVTTL/LVCMOS Ethernet PHY interface. "
        "EtherCAT P adds 24 V DC US + UP power rails superimposed on the 100BASE-TX data "
        "pairs via ETG-specified coupling magnetics. The PDI signaling between ESC and "
        "the application µC is configurable across five families: 8/16-bit async parallel, "
        "8/16-bit sync parallel, SPI slave, DIO, and on-chip CPU bus.")
    d["100base_tx_signaling"] = {
        "encoding": "4B/5B then MLT-3 on one twisted pair per direction",
        "line_rate_Mbaud": 25,
        "data_rate_Mb_s": 100,
        "differential_amplitude_mV_pp": "950 mV ± 15% per IEEE 802.3 Clause 25",
        "transformer_coupling": "1:1 transformer required",
        "cable": "Cat 5/5e UTP, 100 Ω, max segment 100 m",
        "connector": "RJ-45, or M8/M12/M23 industrial",
    }
    d["ethercat_g_signaling"] = {
        "rates_supported": [1000, 10000],
        "1000BASE_T": "PAM-5 across 4 pairs Cat 5e at 125 Mbaud per pair, 1 Gb/s",
        "1000BASE_X": "8B/10B at 1.25 GBaud per direction, 1 Gb/s",
    }
    d["ethercat_p_signaling"] = {
        "data_signaling": "100BASE-TX over twisted pair (unchanged from IEEE 802.3)",
        "power_rails": [
            {"name": "US (System Power)",     "voltage_V": 24, "current_A_max": 3, "purpose": "Logic + I/O electronics"},
            {"name": "UP (Peripheral Power)", "voltage_V": 24, "current_A_max": 3, "purpose": "Sensor / actuator load"},
        ],
        "coupling": "ETG-specified magnetics combine the 24 V rails with 100BASE-TX differential signal on same 4-conductor cable",
        "connector": "M8 P-coded 4-pin",
    }
    d["esc_pdi_signaling"] = [
        {"pdi_type": "Asynchronous 8/16-bit µC bus", "voh_v": 2.40, "vol_v": 0.40,
         "cycle_time_ns": "≥ 40 (configurable in 0x0140)"},
        {"pdi_type": "Synchronous 8/16-bit µC bus",  "voh_v": 2.40, "vol_v": 0.40,
         "clock_MHz_max": 30},
        {"pdi_type": "SPI slave",                    "voh_v": 2.40, "vol_v": 0.40,
         "modes_supported": "Mode 3 default; Mode 0 selectable",
         "clock_MHz_max": "20-25 (vendor-dependent)"},
        {"pdi_type": "Digital I/O (DIO)",            "voh_v": 2.40, "vol_v": 0.40,
         "note": "Up to 32 out + 32 in; no µC needed"},
        {"pdi_type": "On-chip CPU bus",              "voh_v": 2.40, "vol_v": 0.40,
         "note": "AMBA AHB/AXI/Avalon-MM, vendor-dependent"},
    ]
    d["esc_distributed_clock_io"] = [
        {"signal": "SYNC0", "direction": "ESC → µC", "voh_v": 2.40, "vol_v": 0.40,
         "description": "First DC pulse output; period in 0x0990."},
        {"signal": "SYNC1", "direction": "ESC → µC", "voh_v": 2.40, "vol_v": 0.40,
         "description": "Second DC pulse output; period in 0x0994."},
        {"signal": "LATCH0", "direction": "µC → ESC", "voh_v": 2.40, "vol_v": 0.40,
         "description": "External event latch — captures System Time."},
        {"signal": "LATCH1", "direction": "µC → ESC", "voh_v": 2.40, "vol_v": 0.40,
         "description": "Second latch input."},
    ]
    d["esc_sii_eeprom_io"] = [
        {"signal": "EEPROM_SCL", "direction": "open-drain output",       "voh_v": "Hi-Z", "vol_v": 0.40, "description": "I²C-compatible 2-wire clock to SII EEPROM, 100/400 kHz."},
        {"signal": "EEPROM_SDA", "direction": "open-drain bidirectional","voh_v": "Hi-Z", "vol_v": 0.40, "description": "I²C-compatible 2-wire data."},
    ]
    d["supply_rails_typical_esc"] = [
        {"name": "VCC_CORE", "nominal_V": 1.2, "tolerance_pct": 5, "purpose": "ESC core logic"},
        {"name": "VCC_IO",   "nominal_V": 3.3, "tolerance_pct": 5, "purpose": "PDI + MII + LED I/O"},
    ]
    d["operating_temperature_range_C"] = [-40, 85]
    d["100base_fx_signaling"] = {
        "encoding": "4B/5B then NRZI on one fiber strand per direction",
        "line_rate_Mbaud": 125,
        "data_rate_Mb_s": 100,
        "wavelength_nm": 1300,
        "cable": "62.5/125 µm or 50/125 µm multimode fiber; max segment 2 km",
        "connector": "SC / LC / MTRJ",
    }
    d["esc_phy_management_io"] = [
        {"signal": "MDC",  "direction": "ESC → PHY",     "voh_v": 2.4, "vol_v": 0.4,
         "description": "MII Management clock, ≤ 2.5 MHz."},
        {"signal": "MDIO", "direction": "bidirectional", "voh_v": 2.4, "vol_v": 0.4,
         "description": "MII Management data (three-state, 1.5 kΩ pull-up at PHY)."},
    ]
    d["esd_protection_class"] = (
        "Compliant with IEC 61000-4-2 ± 4 kV contact discharge on Ethernet ports "
        "(transformer-protected)")
    # Strip MII/GMII/RGMII tables that the Ethernet synth populated
    for k in ("mii_dc_characteristics", "mii_ac_characteristics",
              "gmii_ac_characteristics", "rgmii_ac_characteristics",
              "phy_mdi_signaling"):
        d.pop(k, None)
    _write(p, d)


def _apply_l6(gd: Path) -> None:
    """L6 CONTROL_LOGIC — replace CSMA/CD + AutoNeg FSMs with the ESM,
    on-the-fly engine, mailbox handshake, and DC propagation FSMs."""
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_esm"] = [
        {"state": "Init",   "code": "0x01", "description": "Initial state after power-up; no mailbox, no process-data."},
        {"state": "PreOp",  "code": "0x02", "description": "Pre-Operational — mailbox SMs (SM0/SM1) active; CoE/SoE/EoE/FoE/AoE exchangeable."},
        {"state": "SafeOp", "code": "0x04", "description": "Safe-Operational — process-data SMs and FMMUs active; Inputs valid; Outputs in Safe state."},
        {"state": "Op",     "code": "0x08", "description": "Operational — full bidirectional cyclic process-data; PD WD armed."},
        {"state": "Boot",   "code": "0x03", "description": "Bootstrap — firmware update via FoE; only from Init."},
    ]
    d["fsm_transitions_esm"] = [
        {"from": "Init",   "to": "PreOp",  "trigger": "MainDevice FPWR 0x0120 = 0x02"},
        {"from": "PreOp",  "to": "SafeOp", "trigger": "FPWR 0x0120 = 0x04; SubDevice validates SM2/SM3/FMMU"},
        {"from": "SafeOp", "to": "Op",     "trigger": "FPWR 0x0120 = 0x08; SubDevice arms PD WD"},
        {"from": "Op",     "to": "SafeOp", "trigger": "FPWR 0x0120 = 0x04 OR PD WD expiry"},
        {"from": "SafeOp", "to": "PreOp",  "trigger": "FPWR 0x0120 = 0x02"},
        {"from": "PreOp",  "to": "Init",   "trigger": "FPWR 0x0120 = 0x01"},
        {"from": "Init",   "to": "Boot",   "trigger": "FPWR 0x0120 = 0x03"},
        {"from": "Boot",   "to": "Init",   "trigger": "FPWR 0x0120 = 0x01"},
    ]
    d["fsm_states_esc_on_the_fly_engine"] = [
        {"state": "IDLE",             "description": "No frame on any port; ESC waits."},
        {"state": "RECEIVE",          "description": "SOF detected; receive into shift register."},
        {"state": "DECODE_DATAGRAM",  "description": "Parse Cmd/Addr/Length/Next; determine AP/FP/BC/LOG match."},
        {"state": "MATCH_OR_FORWARD", "description": "If addressed: read+modify+write on in-flight bytes."},
        {"state": "UPDATE_WKC",       "description": "If successful: increment WKC (+1 read, +2 write, +3 RW)."},
        {"state": "FORWARD",          "description": "Transmit modified frame on next active port (or loop back)."},
        {"state": "DONE",             "description": "Frame transmitted; back to IDLE."},
    ]
    d["fsm_states_mainDevice_cyclic_engine"] = [
        {"state": "INIT_SWEEP",          "description": "BRD AL Status sweep + APRD enumeration (Position)."},
        {"state": "ASSIGN_ADDRESS",      "description": "APWR Configured Station Address on each SubDevice."},
        {"state": "READ_SII",            "description": "Read each SubDevice's ESI EEPROM."},
        {"state": "CONFIG_PHASE1",       "description": "FPWR DL Control, SM0/SM1 (mailbox), DC RX-Latch enable."},
        {"state": "ESM_INIT_TO_PREOP",   "description": "FPWR 0x0120 = 0x02; verify via BRD 0x0130."},
        {"state": "CONFIG_PHASE2",       "description": "FPWR SM2/SM3, FMMU0..2, DC SYNC config."},
        {"state": "ESM_PREOP_TO_SAFEOP", "description": "FPWR 0x0120 = 0x04."},
        {"state": "ESM_SAFEOP_TO_OP",    "description": "FPWR 0x0120 = 0x08."},
        {"state": "CYCLIC_RUN",          "description": "Cyclic LRD/LWR/LRW + ARMW (DC) + BRD AL Status."},
        {"state": "ERROR_HANDLING",      "description": "WKC drop / AL Status error / link loss → diagnose + recover."},
    ]
    d["fsm_states_mailbox_handshake"] = [
        {"state": "MBX_IDLE",    "description": "SM0 buffer empty."},
        {"state": "MBX_WRITE",   "description": "MainDevice FPWR into SM0; hardware sets Mbx_Out Empty=1."},
        {"state": "MBX_PROCESS", "description": "SubDevice CPU reads SM0, processes, writes SM1."},
        {"state": "MBX_READ",    "description": "Hardware sets Mbx_In Full=1; MainDevice FPRD reads SM1."},
        {"state": "MBX_RETRY",   "description": "On timeout MainDevice resends with incremented Counter."},
    ]
    d["fsm_states_distributed_clocks"] = [
        {"state": "DC_OFF",        "description": "DC unit inactive."},
        {"state": "DC_MEASURE",    "description": "BWR 0x0900 latches RX timestamps; FPRD sweeps."},
        {"state": "DC_COMPENSATE", "description": "MainDevice writes System Time Offset (0x0920) + Delay (0x0928)."},
        {"state": "DC_PROPAGATE",  "description": "Cyclic ARMW; SubDevices close PI loop on local System Time."},
        {"state": "DC_SYNC_ARMED", "description": "Activation 0x0981 set; SYNC0/SYNC1 outputs active."},
    ]
    d["anti_deadlock_rule"] = (
        "ESM transitions only on MainDevice request via AL Control 0x0120 with one exception: "
        "PD Watchdog expiry forces Op → SafeOp. SubDevice never escalates state autonomously "
        "beyond the safe direction. Mailbox handshake on SM0/SM1 is atomic on the wire; a "
        "half-completed mailbox write cannot be observed by the SubDevice CPU. The on-the-fly "
        "engine has no internal queues; one frame in, one frame out, deterministic latency.")
    d["fsm_hints"] = (
        "ESM and on-the-fly engine are implementable as small synchronous state machines "
        "clocked at the wire rate. FMMU lookup is a sorted-window compare against the 8 "
        "entries; SyncManager arbitration is single-buffer per channel. DC PI loop converges "
        "within 100-1000 cycles.")
    # Strip Ethernet FSMs left by the Ethernet synth
    for k in ("fsm_states_mac_tx", "fsm_states_mac_rx",
              "fsm_states_csma_cd_half_duplex",
              "fsm_states_mdio_master_clause22",
              "fsm_states_auto_negotiation_clause28"):
        d.pop(k, None)
    _write(p, d)


def _apply_l7(gd: Path) -> None:
    """L7 TEST_DEBUG — replace IEEE-LB / PHY-loopback tests with the
    ETG.1500 CTT + ESC error counters + Independent Diagnostic Interface."""
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        "Per-port RX Error Counters (ESC 0x0300-0x030F): Frame Error, Physical RX Error, Forwarded RX Error.",
        "Per-port Lost Link Counter (0x0308-0x030F).",
        "ESC DL Status (0x0110): per-port Link status, Loop state, Signal Detect, PDI operational.",
        "AL Status (0x0130) + AL Status Code (0x0134) — IEC 61158-defined ESM error numbers.",
        "Working Counter (WKC) per datagram — in-band integrity check.",
        "Distributed Clock System Time Difference (0x092C) — drift / sync quality.",
        "Process-Data Watchdog Status (0x0440).",
        "Mailbox handshake state bits in SM0/SM1 Status (0x0805 / 0x080D).",
    ]
    d["error_detection_mechanisms"] = [
        "Ethernet FCS (CRC-32); corrupted frames forwarded but counted.",
        "Working Counter check per datagram.",
        "ESM cross-check via BRD 0x0130 (one frame snapshots whole network).",
        "DC System Time Difference monitor (continuous drift).",
        "PD Watchdog auto-transitions Op → SafeOp.",
        "PDI Watchdog drives outputs to Safe state.",
        "Mailbox handshake timeout + MainDevice retry on Counter mismatch.",
        "SII checksum (bit 8 of 0x0502).",
    ]
    d["test_modes"] = [
        {"name": "Independent Diagnostic Interface",
         "description": "Read-only FPRD command set lets any external diagnostic tool walk "
                        "the network and snapshot CRC counters + link state + ESM state "
                        "without disturbing the cyclic exchange."},
        {"name": "EtherCAT Conformance Test Tool (CTT)",
         "description": "ETG-provided official tool that drives a SubDevice through every "
                        "mandatory + optional protocol path. Pass is a precondition for ETG "
                        "certification."},
        {"name": "Cable Loopback / Hardware Loopback",
         "description": "Each ESC port has hardware auto-loopback when link partner absent."},
        {"name": "PHY Loopback (MII master loopback)",
         "description": "Command via MII Management (0x0510-0x0516) to put PHY into internal "
                        "loopback for at-speed BIST."},
        {"name": "Process-Data Watchdog test mode",
         "description": "PD WD can be intentionally disabled via SM Control bit 6."},
        {"name": "EEPROM emulation mode",
         "description": "Bit 8 of 0x0500 enables PDI-emulated SII; µC supplies SII content."},
    ]
    d["interrupt_or_event_sources"] = [
        {"name": "ECAT Interrupt", "description": "ESC interrupt via AL Status interrupt OR'ed into IRQ field of next datagram."},
        {"name": "PDI Interrupt",  "description": "ESC interrupt output pin to local µC."},
        {"name": "SYNC0 / SYNC1",  "description": "DC output pulses for cycle synchronization."},
        {"name": "LATCH0 / LATCH1","description": "External edge → System Time capture."},
        {"name": "SM Event",       "description": "SM buffer empty/full/written interrupt."},
        {"name": "Mailbox Event",  "description": "SM0 written / SM1 read interrupt."},
        {"name": "PD WD Event",    "description": "Process-Data Watchdog expiry."},
        {"name": "PDI WD Event",   "description": "PDI Watchdog expiry."},
    ]
    d["loopback_modes_summary"] = (
        "Three loopback paths: (1) Per-port hardware auto-loopback when link partner absent — "
        "foundation of daisy-chain auto-return. (2) Manual port loopback via DL Control "
        "0x0100-0x010F. (3) PHY internal loopback via MII management.")
    d["diagnostic_tools_external"] = [
        "ETG Conformance Test Tool (CTT) — official compliance suite",
        "Beckhoff TwinCAT System Manager — graphical configurator + on-line diagnostic",
        "Wireshark with EtherCAT dissector — frame-level capture (EtherType 0x88A4)",
        "EtherCAT Explorer / acontis EC-Inspector / KPA EtherCAT Studio",
        "ETG.1500 Conformance Mark — visible badge on certified products",
    ]
    d["notes"] = (
        "Diagnostic data is collected non-intrusively: a periodic BRD to 0x0130 (AL Status) + "
        "a periodic BRD to 0x0300 (Frame Error Counter) costs one datagram each per cycle "
        "and snapshots the whole network.")
    _write(p, d)


def _apply_l8_consts(gd: Path) -> None:
    """L8 RTL_CONSTANTS — replace Ethernet width-parameters (preamble,
    SFD, MII, GMII, MDIO) with EtherCAT-specific constants (EtherType
    0x88A4, datagram header, WKC, ESC memory map, FMMU, SM, DC, ESM)."""
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    # Replace width_parameters wholesale — Ethernet synth populated
    # MII/GMII/MDIO things that don't apply to EtherCAT
    d["width_parameters"] = {
        "ETHERTYPE_ETHERCAT_HEX": "0x88A4",
        "UDP_PORT_ETHERCAT_HEX": "0x88A4",
        "ETHERCAT_HEADER_WIDTH_BITS": 16,
        "ETHERCAT_HEADER_LENGTH_BITS": 11,
        "ETHERCAT_HEADER_TYPE_BITS": 4,
        "ETHERCAT_HEADER_TYPE_ESC_DATAGRAM_HEX": "0x1",
        "ETHERCAT_HEADER_TYPE_NETWORK_VAR_HEX": "0x4",
        "DATAGRAM_HEADER_WIDTH_BYTES": 10,
        "DATAGRAM_CMD_WIDTH_BITS": 8,
        "DATAGRAM_IDX_WIDTH_BITS": 8,
        "DATAGRAM_ADDRESS_WIDTH_BITS": 32,
        "DATAGRAM_LENGTH_WIDTH_BITS": 11,
        "DATAGRAM_LENGTH_MAX_BYTES": 1486,
        "DATAGRAM_RESERVED_BITS": 3,
        "DATAGRAM_CIRCULATING_BIT": 14,
        "DATAGRAM_NEXT_BIT": 15,
        "DATAGRAM_IRQ_WIDTH_BITS": 16,
        "WKC_WIDTH_BITS": 16,
        "WKC_INCREMENT_READ": 1,
        "WKC_INCREMENT_WRITE": 2,
        "WKC_INCREMENT_READ_WRITE": 3,
        "ESC_MEMORY_TOTAL_BYTES": 65536,
        "ESC_REGISTER_REGION_BYTES": 4096,
        "ESC_DPRAM_REGION_BYTES": 61440,
        "FMMU_COUNT_MAX": 8,
        "FMMU_ENTRY_SIZE_BYTES": 16,
        "FMMU_BASE_ADDR_HEX": "0x0600",
        "SM_COUNT_MAX": 8,
        "SM_ENTRY_SIZE_BYTES": 8,
        "SM_BASE_ADDR_HEX": "0x0800",
        "STATION_ADDRESS_REG_HEX": "0x0010",
        "STATION_ADDRESS_WIDTH_BITS": 16,
        "STATION_ALIAS_REG_HEX": "0x0012",
        "STATION_ALIAS_WIDTH_BITS": 16,
        "AL_CONTROL_REG_HEX": "0x0120",
        "AL_STATUS_REG_HEX": "0x0130",
        "AL_STATUS_CODE_REG_HEX": "0x0134",
        "DL_CONTROL_REG_HEX": "0x0100",
        "DL_STATUS_REG_HEX": "0x0110",
        "DC_SYSTEM_TIME_REG_HEX": "0x0910",
        "DC_SYSTEM_TIME_WIDTH_BITS": 64,
        "DC_TIME_OFFSET_REG_HEX": "0x0920",
        "DC_TIME_OFFSET_WIDTH_BITS": 64,
        "DC_TIME_DELAY_REG_HEX": "0x0928",
        "DC_TIME_DELAY_WIDTH_BITS": 32,
        "DC_SYNC0_CYCLE_REG_HEX": "0x0990",
        "DC_SYNC1_CYCLE_REG_HEX": "0x0994",
        "SII_CONTROL_STATUS_REG_HEX": "0x0502",
        "SII_ADDRESS_REG_HEX": "0x0504",
        "SII_DATA_REG_HEX": "0x0508",
        "MII_CONTROL_STATUS_REG_HEX": "0x0510",
        "ESM_STATE_INIT_HEX": "0x01",
        "ESM_STATE_PREOP_HEX": "0x02",
        "ESM_STATE_BOOT_HEX": "0x03",
        "ESM_STATE_SAFEOP_HEX": "0x04",
        "ESM_STATE_OP_HEX": "0x08",
        "ESM_STATE_ERROR_BIT": 4,
        "MAX_SUBDEVICES_PER_BUS": 65535,
        "LOGICAL_ADDRESS_SPACE_BYTES": 4294967296,
        "WIRE_RATE_MBPS_FAST": 100,
        "WIRE_RATE_MBPS_GIGABIT": 1000,
        "ESC_FORWARDING_DELAY_NS_TYP": 1000,
        "ESC_FORWARDING_DELAY_NS_MIN": 300,
        "ESC_FORWARDING_DELAY_NS_MAX": 1500,
        "DC_JITTER_NS_TYP": 100,
    }
    d["commands_table_hex"] = {
        "NOP":  "0x00", "APRD": "0x01", "APWR": "0x02", "APRW": "0x03",
        "FPRD": "0x04", "FPWR": "0x05", "FPRW": "0x06", "BRD":  "0x07",
        "BWR":  "0x08", "BRW":  "0x09", "LRD":  "0x0A", "LWR":  "0x0B",
        "LRW":  "0x0C", "ARMW": "0x0D", "FRMW": "0x0E",
    }
    d["ethercat_frame_field_offsets_bytes_from_da_byte0"] = {
        "DA": 0, "SA": 6, "EtherType": 12, "EtherCAT_Header": 14,
        "First_Datagram_Header": 16,
        "First_Datagram_Cmd": 16, "First_Datagram_Idx": 17,
        "First_Datagram_Address": 18,
        "First_Datagram_Length_NextBit_etc": 22,
        "First_Datagram_IRQ": 24, "First_Datagram_Data_Start": 26,
        "comment": "FCS appears 4 bytes from end of payload.",
    }
    d["fmmu_entry_field_offsets_bytes"] = {
        "Logical_Start_Address": 0, "Length": 4,
        "Logical_Start_Bit": 6, "Logical_Stop_Bit": 7,
        "Physical_Start_Address": 8, "Physical_Start_Bit": 10,
        "Type_Read_Write_Bits": 11, "Activate": 12,
    }
    d["sm_entry_field_offsets_bytes"] = {
        "Physical_Start_Address": 0, "Length": 2,
        "Control": 4, "Status": 5, "Activate": 6, "PDI_Control": 7,
    }
    d["fcs_polynomial"] = {
        "polynomial_hex": "0x04C11DB7",
        "reflected_representation_hex": "0xEDB88320",
        "init_hex": "0xFFFFFFFF",
        "final_xor_hex": "0xFFFFFFFF",
        "bit_order": "LSB-first within each byte",
        "comment": "Inherited from IEEE 802.3 Ethernet.",
    }
    d["mbx_header_layout"] = {
        "size_bytes": 6,
        "fields": [
            {"offset": 0, "name": "Length",           "size_bytes": 2},
            {"offset": 2, "name": "Address",          "size_bytes": 2},
            {"offset": 4, "name": "Channel+Priority", "size_bytes": 1},
            {"offset": 5, "name": "Type+Counter",     "size_bytes": 1},
        ],
    }
    d["key_constants_for_RTL_authoring"] = {
        "ETHERCAT_ETHERTYPE": "0x88A4",
        "DEFAULT_CYCLE_TIME_NS": 1000000,
        "MIN_CYCLE_TIME_NS": 100000,
        "PROCESS_DATA_WATCHDOG_DEFAULT_NS": 100000000,
        "PDI_WATCHDOG_DEFAULT_NS": 100000000,
        "MAX_FRAME_BYTES_UNTAGGED": 1518,
        "MAX_FRAME_BYTES_VLAN": 1522,
        "MIN_FRAME_BYTES": 64,
        "IFG_BIT_TIMES": 96,
        "SII_EEPROM_MAX_BITS": 4194304,
    }
    # Strip Ethernet-specific structures
    for k in ("mac_frame_field_offsets_bytes_from_da_byte0",
              "vlan_tagged_field_offsets_bytes_from_da_byte0",
              "mdio_clause22_frame_bit_order",
              "mdio_clause45_frame_bit_order"):
        d.pop(k, None)
    _write(p, d)


def _apply_l8_timing(gd: Path) -> None:
    """L8 TIMING_WAVEFORM — replace IEEE Ethernet MII / Auto-Neg / CSMA-CD
    waveforms with EtherCAT cyclic + DC + ESC-forwarding timing."""
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["data_rate_waveforms"] = {
        "100BASE-TX": {"line_rate_Mb_s": 100, "MII_TX_CLK_MHz": 25,
                       "nibble_clock_period_ns": 40, "bit_time_ns": 10,
                       "encoding": "4B/5B + MLT-3"},
        "100BASE-FX": {"line_rate_Mb_s": 100, "encoding": "4B/5B + NRZI",
                       "bit_time_ns": 10},
        "EtherCAT G 1000BASE-T": {"line_rate_Mb_s": 1000,
                                  "GMII_GTX_CLK_MHz": 125,
                                  "byte_clock_period_ns": 8,
                                  "bit_time_ns": 1},
        "EtherCAT G 1000BASE-X": {"line_rate_Mb_s": 1000,
                                  "encoding": "8B/10B at 1.25 GBaud",
                                  "bit_time_ns": 1},
    }
    d["frame_timing_at_100mbps"] = {
        "preamble_duration_ns": 560,
        "sfd_duration_ns": 80,
        "min_frame_64B_payload_duration_ns": 5120,
        "max_frame_1518B_duration_ns": 121440,
        "ifg_duration_ns": 960,
        "max_frame_rate_PPS_min_frame": 148809,
        "comment": "Frame transmission at 100 Mb/s carries one wire-bit every 10 ns.",
    }
    d["ethercat_datagram_timing"] = {
        "header_10_bytes_ns_at_100Mbps": 800,
        "data_byte_ns_at_100Mbps": 80,
        "wkc_2_bytes_ns_at_100Mbps": 160,
        "comment": "Throughput: 1 datagram with N data bytes = (12+N)*80 ns on wire at 100 Mb/s.",
    }
    d["esc_forwarding_latency_ns"] = {
        "typical_at_100Mbps": 1000,
        "min_at_100Mbps": 300,
        "max_at_100Mbps": 1500,
        "typical_at_1Gbps": 350,
        "comment": "ESC forwards the in-flight frame in cut-through mode; per-hop "
                   "delay is dominated by the on-the-fly engine pipeline depth, "
                   "NOT by store-and-forward.",
    }
    d["distributed_clocks_timing"] = {
        "system_time_resolution_ns": 1,
        "system_time_width_bits": 64,
        "jitter_typical_ns": 100,
        "max_jitter_after_drift_compensation_ns": 1000,
        "sync0_pulse_period_ns_min": 1000,
        "sync0_pulse_period_ns_max_typical": 1000000000,
        "comment": "DC field engineering target: <100 ns network-wide jitter. "
                   "Verified by network analyzer comparing SYNC0 rising edges "
                   "across hops.",
    }
    d["cyclic_exchange_timing"] = {
        "cycle_time_ns_min": 100000,
        "cycle_time_ns_typical": 1000000,
        "cycle_time_ns_long": 4000000,
        "process_data_watchdog_default_ns": 100000000,
        "comment": "Cycle time is bounded below by ((frame transmission time) + "
                   "Σ ESC forwarding delays + cable propagation + MainDevice "
                   "software jitter). For 100 SubDevices on 100 Mb/s with 16 B "
                   "I/O each, the wire time is ~140 µs.",
    }
    d["pdi_timing"] = {
        "spi_max_clock_MHz": 25,
        "spi_min_chip_select_setup_ns": 10,
        "spi_max_data_hold_ns": 20,
        "async_micro_bus_min_cycle_ns": 40,
        "sync_micro_bus_max_clock_MHz": 30,
        "comment": "PDI is the application-side bus to local µC; choice is "
                   "configured in 0x0140 PDI Control.",
    }
    d["ethernet_signal_timing_reference_IEEE_802_3"] = {
        "mii_tx_clk_period_at_100Mb_s_ns": 40,
        "mii_tx_clk_duty_cycle_pct": "35-65",
        "mii_tx_clk_tolerance_ppm": 100,
        "mdc_max_freq_MHz": 2.5,
        "mdc_min_period_ns": 400,
        "mdc_min_high_low_time_ns": 160,
    }
    # Strip Ethernet-specific waveforms
    for k in ("mii_signal_timing", "mdio_signal_timing", "frame_waveform",
              "auto_negotiation_waveform", "csma_cd_timing",
              "pause_frame_timing"):
        d.pop(k, None)
    _write(p, d)


def _apply_l9(gd: Path) -> None:
    """L9 INTEGRATION_SPEC — replace MAC + PHY block-diagram with ESC +
    PDI + SII + Distributed-Clock integration model."""
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "EtherCAT defines two distinct silicon roles. (1) The EtherCAT SubDevice (Slave) "
        "integrates an EtherCAT Slave Controller (ESC) — 2-4 Ethernet ports + on-the-fly "
        "engine + FMMU + SyncManager + DPRAM + DC + SII + PDI — alongside a local "
        "application µC. (2) The MainDevice (Master) uses a standard PC + commodity "
        "Ethernet NIC; no EtherCAT-specific silicon on the controller side.")
    d["topology_description"] = (
        "Daisy-chain (line) is canonical. Each SubDevice ESC has hardware auto-loopback on "
        "any port without an active link partner, so the frame physically traverses every "
        "device twice on the same cable (outbound + return), creating one logical bus. "
        "Tree topologies use 3- or 4-port SubDevices. Ring topology with cable redundancy "
        "uses two MainDevice NICs.")
    d["integration_overview"] = (
        "Typical SubDevice integration: ESC IP (Beckhoff ET1100/ET1200/ET1815, Microchip "
        "LAN9252, or FPGA IP) is placed between Ethernet PHYs and application µC. The ESC's "
        "Ethernet ports connect via MII/RMII/RGMII to two integrated 10/100 Ethernet PHYs. "
        "The PDI connects to the application µC's external bus / SPI. An external SII EEPROM "
        "holds the ESI XML descriptor. SYNC0/SYNC1 outputs drive the µC's cycle interrupt.")
    d["interface_categories"] = [
        {"category": "Ethernet wire (network side)",
         "interfaces": ["100BASE-TX over Cat 5/5e UTP with RJ-45 or M8/M12",
                        "100BASE-FX over multimode fiber",
                        "EtherCAT G: 1000BASE-T or 1000BASE-X",
                        "EtherCAT P: 100BASE-TX + 2×24 V power"]},
        {"category": "PDI (application side, ESC → local µC)",
         "interfaces": ["Async 8/16-bit µC parallel bus",
                        "Sync 8/16-bit µC parallel bus",
                        "SPI slave (Mode 0 or Mode 3, ≤25 MHz)",
                        "Digital I/O (32 in + 32 out, no µC needed)",
                        "On-chip CPU bus (AMBA AHB / AXI / Avalon-MM)"]},
        {"category": "SII (EEPROM side)",
         "interfaces": ["I²C-compatible 2-wire to serial EEPROM",
                        "PDI emulation (µC supplies SII content)"]},
        {"category": "Distributed Clock outputs",
         "interfaces": ["SYNC0 / SYNC1 output pulses to µC",
                        "LATCH0 / LATCH1 external event inputs"]},
        {"category": "Diagnostic LEDs",
         "interfaces": ["RUN, ERR, LINK, ACT per IEC 61784-2"]},
    ]
    d["interconnect_topologies_supported"] = [
        {"name": "Line / Daisy-chain",       "description": "Most common; min cabling cost.", "max_nodes": 65535, "redundancy": False},
        {"name": "Tree",                     "description": "3+ port SubDevice junctions.",   "max_nodes": 65535, "redundancy": False},
        {"name": "Star",                     "description": "Branches off central multi-port SubDevice.", "max_nodes": 65535, "redundancy": False},
        {"name": "Ring",                     "description": "Dual NIC MainDevice; cable-break recovery.", "max_nodes": 65535, "redundancy": True},
        {"name": "Drop line",                "description": "Tree branches terminating in stub.", "max_nodes": 65535, "redundancy": False},
        {"name": "Hot Connect / Hot Swap",   "description": "Groups join/leave during operation.", "max_nodes": 65535, "redundancy": "partial"},
    ]
    d["default_signal_values_when_omitted"] = [
        {"signal": "PDI READY",          "default_when_unused": "Tied high (no wait)"},
        {"signal": "PDI IRQ output",     "default_when_unused": "Disabled (mask in 0x0200)"},
        {"signal": "SYNC0 / SYNC1",      "default_when_unused": "Inactive (Activation 0x0981 = 0)"},
        {"signal": "EEPROM_SDA / SCL",   "default_when_unused": "Open-drain Hi-Z + 4.7 kΩ pull-ups"},
        {"signal": "MII PHY pins",       "default_when_unused": "Port loops back internally via DL Control 0x0100"},
    ]
    d["soc_dependent_items"] = [
        "PHY choice (Microchip LAN8710 / TI DP83822 / Marvell 88E1111) — MDIO register quirks",
        "Magnetics + connector mechanicals (RJ-45 / M8 / M12 / M23)",
        "PDI bus electrical levels (3.3 V vs 5 V µC interfacing)",
        "External SII EEPROM choice + capacity (1 Kbit / 4 Kbit / 32 Kbit / 1 Mbit)",
        "Application µC class (8-bit / 16-bit / 32-bit Cortex-M / FPGA NIOS / RISC-V)",
    ]
    d["esi_xml_descriptor_required"] = {
        "filename_pattern": "<VendorName>_<Profile>_<RevisionDate>.xml",
        "schema": "ETG.2000 EtherCAT Slave Information",
        "key_elements": [
            "Vendor ID (32-bit, ETG-assigned)",
            "Product Code (vendor-defined 32-bit)",
            "Revision Number (32-bit)",
            "Serial Number (32-bit, optional)",
            "Mailbox SM0/SM1 configuration",
            "Process Data SM2/SM3 configuration",
            "Default FMMU mappings",
            "Mailbox protocols bitmask (CoE/SoE/EoE/FoE/AoE/VoE)",
            "Boot mailbox configuration",
            "CoE Object Dictionary skeleton",
        ],
    }
    d["operating_temperature_range_C"] = [-40, 85]
    d["power_consumption_typical_esc_W"] = [0.3, 1.5]
    _write(p, d)


def _apply_l10(gd: Path) -> None:
    """L10 TEST_CASES — replace IEEE Ethernet conformance cases with the
    ETG.1500 EtherCAT compliance test categories."""
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = True
    d["derived_compliance_test_categories"] = [
        {"category": "Frame structure and EtherType",
         "tests": [
             "Frame with EtherType=0x88A4 + EtherCAT header Type=0x1 + valid datagrams is processed.",
             "Frame with wrong EtherType is forwarded transparently; no datagram processing.",
             "Frame with EtherCAT header Type=0x4 is forwarded but not processed by ESC.",
             "Frame with Length exceeding 1486 B is rejected.",
             "Frame shorter than 60 B is padded; ESC operates correctly.",
             "Frame with FCS error: ESC increments Frame Error Counter (0x0300); still forwarded.",
         ]},
        {"category": "Command-code addressing",
         "tests": [
             "NOP: no SubDevice modifies frame; WKC unchanged.",
             "APRD with Position == 0: SubDevice reads, +1 WKC.",
             "APRW: atomic read-then-write, +3 WKC.",
             "FPRD targeting matching Configured Station Address: +1 WKC.",
             "FPRD targeting non-matching address: +0 WKC, forwarded unchanged.",
             "BRD: every SubDevice +1 WKC; total WKC == count.",
             "BWR: every counter cleared.",
             "LRD with FMMU mapping: addressed SubDevices read; WKC matches.",
             "LWR with overlapping FMMUs: deterministic union by bit position.",
             "LRW: +3 WKC per successful SubDevice.",
             "ARMW: first matching SubDevice writes; subsequent SubDevices read (DC propagation).",
         ]},
        {"category": "EtherCAT State Machine (ESM)",
         "tests": [
             "Power-up: Init; AL Status = 0x01.",
             "Init → PreOp: AL Status = 0x02 after AL Control = 0x02.",
             "PreOp → SafeOp: AL Status = 0x04 OR 0x14 + AL Status Code 0x001E on invalid config.",
             "SafeOp → Op: AL Status = 0x08; PD WD armed.",
             "Op → SafeOp on PD WD expiry: AL Status = 0x14.",
             "Init → Boot: AL Status = 0x03; FoE only.",
             "Illegal Init → Op direct: rejected with AL Status Code 0x0011.",
         ]},
        {"category": "FMMU and SyncManager",
         "tests": [
             "FMMU Active=0 ignored.",
             "FMMU bit-granular: only mapped sub-byte slice modified.",
             "Two FMMUs (read + write) on same region → LRW one-datagram I/O.",
             "SM0 Mailbox-Out handshake; SubDevice CPU signals ready after read.",
             "SM2/SM3 3-buffer mode: PDI never reads half-written buffer.",
             "SM Watchdog Trigger bit 6 triggers PD WD.",
         ]},
        {"category": "Distributed Clocks",
         "tests": [
             "BWR to 0x0900 latches RX timestamps on every DC SubDevice.",
             "Propagation delay measurement equals cable + ESC forwarding.",
             "System Time Offset written; local System Time within drift of reference.",
             "ARMW cyclic propagation maintains ±100 ns alignment.",
             "SYNC0 generation with <100 ns jitter across hops.",
         ]},
        {"category": "Mailbox protocols",
         "tests": [
             "CoE SDO Upload of 0x1018:1 (Vendor ID) returns 4-byte value.",
             "CoE SDO Download of 0x1C12:1 returns success.",
             "CoE Emergency posting on SM1.",
             "FoE WRQ/DATA/ACK firmware download in Boot.",
             "EoE: ICMP Echo tunneled through mailbox.",
         ]},
        {"category": "Working Counter validation",
         "tests": [
             "Datagram targeting N SubDevices returns WKC = expected total.",
             "Cable break: WKC drops by missing-SubDevice count; MainDevice diagnoses.",
         ]},
        {"category": "Independent diagnostic interface",
         "tests": [
             "External tool reads AL Status of every SubDevice via FPRD without disturbing cyclic exchange.",
             "External tool reads RX Error Counters; cyclic frame error rate quantified.",
         ]},
    ]
    d["conformance_test_tool_categories"] = (
        "ETG.1500 Conformance Test (CT) suite from the EtherCAT Technology Group covers all "
        "of the above. Pass is required before commercial release of a certified EtherCAT "
        "product.")
    d["notes"] = (
        "Wireshark + EtherCAT dissector + passive Ethernet tap is the standard hand-debug "
        "setup. Frame-level capture verifies Cmd / Address / Length / IRQ / WKC byte-by-byte.")
    _write(p, d)


def _apply_l11(gd: Path) -> None:
    """L11 OTP_CONTENT — replace Ethernet-OUI / MAC-address OTP with
    EtherCAT SII EEPROM (ESI descriptor)."""
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = {
        "spec_provides_via": (
            "External SII EEPROM (1 Kbit-4 Mbit, I²C-compatible 2-wire), NOT on-chip OTP. "
            "The SII EEPROM holds the ESI (EtherCAT Slave Information) descriptor that the "
            "ESC reads at power-up. Some ESCs offer optional PDI-emulated SII."),
        "factory_burned_typical_fields": [
            {"name": "Vendor ID",                       "width_bits": 32, "description": "ETG-assigned; mirrored at CoE OD 0x1018:1."},
            {"name": "Product Code",                    "width_bits": 32, "description": "Vendor-defined; mirrored at CoE OD 0x1018:2."},
            {"name": "Revision Number",                 "width_bits": 32, "description": "Hardware/firmware revision; CoE OD 0x1018:3."},
            {"name": "Serial Number",                   "width_bits": 32, "description": "Per-device; optional; CoE OD 0x1018:4."},
            {"name": "Bootstrap Mailbox Configuration", "width_bits": 64, "description": "Boot-state SM0/SM1 defaults."},
            {"name": "Standard Mailbox Configuration",  "width_bits": 64, "description": "PreOp/SafeOp/Op SM0/SM1 defaults."},
            {"name": "Mailbox Protocols Supported",     "width_bits": 16, "description": "Bitmask: AoE/EoE/CoE/FoE/SoE/VoE."},
            {"name": "EEPROM Size Indicator",           "width_bits": 16, "description": "SII EEPROM capacity (Kbit-1)."},
            {"name": "Configured Station Alias",        "width_bits": 16, "description": "Persistent secondary station address."},
            {"name": "PDI Control",                     "width_bits": 16, "description": "Selects PDI type and configuration."},
        ],
    }
    d["esi_xml_descriptor_required"] = {
        "schema": "ETG.2000 EtherCAT Slave Information XML schema",
        "purpose": (
            "Machine-readable representation of SII contents + richer meta-data (per-device "
            "PDO mapping, CoE Object Dictionary skeleton). MainDevice configuration tools "
            "consume the ESI XML."),
    }
    d["notes"] = (
        "Some ESCs (e.g. Beckhoff ET1100) treat SII as the canonical OTP-equivalent: loaded "
        "into hardware Vendor-ID/Product-Code/Revision/Serial registers (mirrored at 0x0008-"
        "0x000F) when the ESC supports SII auto-load.")
    _write(p, d)


def _apply_l12(gd: Path) -> None:
    """L12 BEHAVIORAL_SEQUENCES — replace Ethernet link-up + MAC TX/RX
    sequences with EtherCAT network-bring-up + cyclic + mailbox + DC."""
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["network_bring_up_sequence"] = [
        {"step": 1,  "action": "Power-up", "actor": "SubDevice",
         "description": "ESC enters Init; reads SII into internal registers."},
        {"step": 2,  "action": "MainDevice broadcast sweep", "actor": "MainDevice",
         "description": "BRD to 0x0130 + 0x0010 returns total SubDevice count via WKC."},
        {"step": 3,  "action": "Position enumeration", "actor": "MainDevice",
         "description": "APRD to 0x0000 reads Type/Revision/Build per Position."},
        {"step": 4,  "action": "Assign Configured Station Address", "actor": "MainDevice",
         "description": "APWR to 0x0010 sets unique 16-bit FP address per SubDevice."},
        {"step": 5,  "action": "Read SII EEPROM", "actor": "MainDevice",
         "description": "FPWR 0x0501 + sequence of FPWR/FPRD 0x0502/0x0504/0x0508."},
        {"step": 6,  "action": "Configure mailbox SMs", "actor": "MainDevice",
         "description": "FPWR 0x0800 (SM0) + 0x0808 (SM1) with ESI defaults."},
        {"step": 7,  "action": "DC measurement", "actor": "MainDevice",
         "description": "Optional: BWR 0x0900 latches RX timestamps; FPRD sweeps; compute delays."},
        {"step": 8,  "action": "ESM Init → PreOp", "actor": "MainDevice",
         "description": "FPWR 0x0120 = 0x02; verify via BRD 0x0130."},
        {"step": 9,  "action": "Configure process-data SMs + FMMUs", "actor": "MainDevice",
         "description": "FPWR 0x0810/0x0818, 0x0600+, DC SYNC0/1 cycle + start time."},
        {"step": 10, "action": "ESM PreOp → SafeOp", "actor": "MainDevice",
         "description": "FPWR 0x0120 = 0x04; SubDevice validates SM2/SM3/FMMU."},
        {"step": 11, "action": "Test cyclic in SafeOp", "actor": "MainDevice",
         "description": "Start cyclic LRD/LWR/LRW; Inputs valid; Outputs in Safe state."},
        {"step": 12, "action": "ESM SafeOp → Op", "actor": "MainDevice",
         "description": "FPWR 0x0120 = 0x08; arms PD WD; drives application outputs."},
        {"step": 13, "action": "Cyclic run", "actor": "MainDevice",
         "description": "Cyclic LRD/LWR/LRW + ARMW (DC) + BRD 0x0130. On WKC drop → ERROR_HANDLING."},
    ]
    d["cyclic_frame_transmission_sequence"] = [
        {"step": 1, "actor": "MainDevice MAC",
         "description": "Construct frame: DA + SA + 0x88A4 + EtherCAT_Header + chained datagrams + FCS."},
        {"step": 2, "actor": "MainDevice MAC", "description": "Transmit onto Port 0."},
        {"step": 3, "actor": "ESC SubDevice 1 Port 0",
         "description": "Decode datagram; if addressed, on-the-fly read/modify/write + WKC update; forward on Port 1."},
        {"step": 4, "actor": "ESC SubDevice 2..N", "description": "Same as step 3."},
        {"step": 5, "actor": "ESC SubDevice N", "description": "Auto-loopback on unused Port 1."},
        {"step": 6, "actor": "Return path",  "description": "Transparent pass-through; modified bytes stable."},
        {"step": 7, "actor": "MainDevice MAC",
         "description": "Receive returning frame; verify WKC; extract Inputs."},
    ]
    d["mailbox_communication_sequence_coe_sdo_read"] = [
        {"step": 1, "actor": "MainDevice",
         "description": "Construct CoE SDO Read Request: Mbx_Header + CoE Header + SDO Command."},
        {"step": 2, "actor": "MainDevice",
         "description": "FPWR 0x1000 (SM0 base); hardware sets Mbx_Out Empty=1."},
        {"step": 3, "actor": "SubDevice CPU",
         "description": "Read SM0 via PDI; parse; look up Object Dictionary; construct response."},
        {"step": 4, "actor": "SubDevice CPU",
         "description": "Write response into SM1; hardware sets Mbx_In Full=1."},
        {"step": 5, "actor": "MainDevice",
         "description": "FPRD 0x080D polls; FPRD 0x1400 reads response."},
    ]
    d["distributed_clock_propagation_sequence"] = [
        {"step": 1, "actor": "MainDevice", "description": "Configure DC: BWR 0x0980 + 0x0981; per-SubDevice FPWR 0x0990/0x0994/0x09A0."},
        {"step": 2, "actor": "MainDevice", "description": "Per cycle: ARMW (Cmd 0x0D) with Position=0, Address=0x0910, Length=8."},
        {"step": 3, "actor": "Reference SubDevice", "description": "ESC writes local System Time into Data field; WKC += 1."},
        {"step": 4, "actor": "Downstream SubDevices", "description": "Read Data field; update System Time Offset via PI loop."},
        {"step": 5, "actor": "All DC SubDevices", "description": "SYNC0/SYNC1 align to local System Time; <100 ns jitter."},
    ]
    d["hot_connect_join_sequence"] = [
        {"step": 1, "actor": "Hot-Connect SubDevice", "description": "Power on; link-up; AL Status = 0x01."},
        {"step": 2, "actor": "Adjacent SubDevice",    "description": "Auto-loopback opens; frame now passes through new device."},
        {"step": 3, "actor": "MainDevice",            "description": "Next BRD sweep shows extra SubDevice."},
        {"step": 4, "actor": "MainDevice",            "description": "APWR Configured Station Address; FPWR config; ESM walk to Op."},
        {"step": 5, "actor": "Cyclic engine",         "description": "Hot Connect group's process data joins cyclic exchange."},
    ]
    d["cable_break_recovery_sequence_ring"] = [
        {"step": 1, "actor": "Both MainDevice NICs",
         "description": "MainDevice runs ring topology with two NICs. Both NICs "
                        "send cyclic frames in opposite directions."},
        {"step": 2, "actor": "ESC",
         "description": "Cable break detected by ESC on affected port; auto-loopback "
                        "closes the port."},
        {"step": 3, "actor": "Network",
         "description": "Ring now splits into two healthy line segments; each "
                        "MainDevice NIC reaches half the SubDevices via its primary direction."},
        {"step": 4, "actor": "MainDevice",
         "description": "Detects topology change via DL Status read; cyclic exchange "
                        "continues without SubDevice loss."},
    ]
    # Strip Ethernet-leaning sequences populated by the Ethernet synth
    for k in ("link_bring_up_sequence",
              "tx_frame_sequence_full_duplex",
              "tx_frame_sequence_half_duplex_csma_cd",
              "rx_frame_sequence",
              "mdio_clause22_write_sequence",
              "mdio_clause22_read_sequence",
              "mdio_clause45_read_sequence"):
        d.pop(k, None)
    _write(p, d)


def _apply_l13(gd: Path) -> None:
    """L13 LAB_CALIBRATION — replace Ethernet PMD calibration targets
    with ESC forwarding-latency + DC jitter + WKC consistency targets."""
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"target": "ESC forwarding latency per hop", "typical_value_ns": [300, 1500],
         "method": "Cut-through latency: TX/RX timestamp at PHY pins.",
         "criticality": "DC jitter budget"},
        {"target": "Distributed Clock jitter end-to-end", "typical_target_ns": 100,
         "method": "Oscilloscope triggers on SYNC0 of two SubDevices several hops apart.",
         "criticality": "Motion-control synchronization"},
        {"target": "Cycle time", "typical_target_us": 1000,
         "method": "MainDevice TX-to-TX interval on outgoing NIC.",
         "criticality": "Hard-real-time deadline"},
        {"target": "Frame error rate", "acceptable_threshold_per_minute": 0,
         "method": "ESC Frame Error Counters (0x0300-0x030F) periodic read.",
         "criticality": "Cable integrity"},
        {"target": "Working Counter consistency", "acceptable_consistency_pct": 100,
         "method": "MainDevice software verifies WKC == expected per cycle.",
         "criticality": "Cyclic data integrity"},
        {"target": "PD Watchdog timeout", "configured_window_ms_default": 100,
         "method": "Intentionally stall cyclic exchange; measure Op→SafeOp.",
         "criticality": "Fail-safe"},
        {"target": "Mailbox round-trip latency", "typical_value_us": [100, 1000],
         "method": "Time CoE SDO Upload request → response.",
         "criticality": "Configuration speed"},
    ]
    d["calibration_artifacts_per_subdevice"] = [
        {"artifact": "System Time Delay (0x0928)", "captured_during": "Bring-up DC measurement",
         "writable": True, "description": "Propagation delay from reference."},
        {"artifact": "System Time Offset (0x0920)", "captured_during": "Continuous DC PI loop",
         "writable": True, "description": "Local time minus System Time."},
    ]
    d["calibration_artifacts_per_network"] = [
        {"artifact": "Configured Station Address", "captured_during": "Bring-up",
         "persistent_in_subdevice_eeprom": False,
         "description": "MainDevice re-assigns at every power-up."},
        {"artifact": "Configured Station Alias (0x0012)",
         "captured_during": "ESI-defined, loaded from SII",
         "persistent_in_subdevice_eeprom": True,
         "description": "Persistent secondary address survives power-cycle."},
    ]
    d["notes"] = (
        "EtherCAT does not require analog calibration. The 'calibration' content is the DC "
        "propagation-delay measurement during start-up, captured into System Time Delay per "
        "SubDevice. Once captured, runs deterministically forever (PI-loop drift only).")
    _write(p, d)


def _apply_l14(gd: Path) -> None:
    """L14 PROTOCOL_VERSIONING — replace IEEE 802.3 version lineage with
    EtherCAT (Beckhoff 2003 → ETG → IEC 61158 → FSoE → P → G)."""
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["spec_version"] = (
        "ETG Brochure — EtherCAT and ETG Introduction (March 6, 2024) referencing IEC 61158 "
        "Type 12 + IEC 61784 CPF 12 + ISO 15745-4 + SEMI E54.20 base spec")
    f["previous_versions"] = [
        "EtherCAT introduced by Beckhoff Automation at the Hannover Fair, April 2003",
        "EtherCAT Technology Group founded November 2003",
        "IEC 61158-3-12 + -4-12 + -5-12 + -6-12 published 2007",
        "IEC 61784-1 CPF 12 + IEC 61784-2 CPF 12",
        "Safety over EtherCAT standardized as IEC 61784-3-12 (2010)",
        "ETG.1500 Conformance Test specification",
        "ETG.2000 ESI XML schema",
        "ETG.5003 Modular Device Profile (MDP)",
        "ETG.1020 EtherCAT Protocol Enhancements",
    ]
    f["key_changes"] = [
        {"version": "EtherCAT base (2003-2007)",
         "summary": "100 Mb/s Industrial Ethernet with on-the-fly processing; 13 commands; ESM; FMMU + SM; DC."},
        {"version": "FSoE (2010)",                  "summary": "Layered safety frame on mailbox; SIL 3."},
        {"version": "EtherCAT P (2015)",            "summary": "Single-cable variant with 24 V US + UP rails."},
        {"version": "EtherCAT G (2018)",            "summary": "1 Gb/s and 10 Gb/s; protocol unchanged above PHY."},
        {"version": "ETG Brochure (2024)",          "summary": "Updated technical + marketing overview."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "EtherCAT G+", "summary": "Further deployment of gigabit + 10G."},
        {"version": "TSN compatibility", "summary": "Coexistence with IEEE 802.1 TSN domains."},
        {"version": "OPC-UA over EtherCAT", "summary": "Plant-floor integration (EAP + CSP+)."},
        {"version": "Industry 4.0 / IoT", "summary": "MainDevices as edge gateways."},
    ]
    f["trademark_and_licensing"] = (
        "EtherCAT® is a registered trademark and a patented technology licensed by Beckhoff "
        "Automation GmbH, Germany. Free, royalty-free use is permitted for ETG members.")
    f["standardization_bodies"] = [
        "EtherCAT Technology Group (ETG)",
        "IEC (IEC 61158 / IEC 61784 / IEC 61918)",
        "ISO (ISO 15745-4)",
        "SEMI (SEMI E54.20)",
        "AIDA (automotive line standardization)",
    ]
    f["iec_standard_breakdown"] = {
        "IEC 61158-3-12": "Data Link Layer service definition for Type 12 (EtherCAT)",
        "IEC 61158-4-12": "Data Link Layer protocol specification for Type 12",
        "IEC 61158-5-12": "Application Layer service definition for Type 12",
        "IEC 61158-6-12": "Application Layer protocol specification for Type 12",
        "IEC 61784-1 CPF 12": "EtherCAT Communication Profile Family",
        "IEC 61784-2 CPF 12": "EtherCAT Real-Time Communication Profile",
        "IEC 61784-3-12": "FSoE (Safety over EtherCAT)",
        "IEC 61784-5-12": "EtherCAT installation profile",
    }
    d["fields"] = f
    _write(p, d)


def _apply_l15(gd: Path) -> None:
    """L15 ENCODING_TABLES — replace MII / MDIO / EtherType encoding
    tables with EtherCAT frame + datagram + command + state + AL Status
    Code tables."""
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["ethercat_frame_table"] = [
        {"offset_bytes": 0,  "field": "Destination MAC", "size_bytes": 6, "notes": "Unconstrained."},
        {"offset_bytes": 6,  "field": "Source MAC",      "size_bytes": 6, "notes": "MainDevice NIC MAC."},
        {"offset_bytes": 12, "field": "EtherType",       "size_bytes": 2, "notes": "0x88A4 (EtherCAT) or 0x0800 (UDP/IP)."},
        {"offset_bytes": 14, "field": "EtherCAT Header", "size_bytes": 2, "notes": "Length[10:0] + Reserved[11] + Type[15:12]=0x1."},
        {"offset_bytes": 16, "field": "Datagram Block",  "size_bytes": "1-1486", "notes": "One or more chained datagrams."},
        {"offset_bytes": "end-4", "field": "FCS",        "size_bytes": 4, "notes": "Standard Ethernet CRC-32."},
    ]
    f["ethercat_header_bit_table"] = [
        {"bit_field": "Length",   "bits": "10:0",  "purpose": "Total length of following datagrams."},
        {"bit_field": "Reserved", "bits": "11",    "purpose": "0"},
        {"bit_field": "Type",     "bits": "15:12", "purpose": "0x1=ESC, 0x4=Network Variables, 0x5=Mailbox-only"},
    ]
    f["datagram_header_bit_table"] = [
        {"offset_bytes": 0, "field": "Cmd",         "size_bits": 8,  "purpose": "Command code 0x00-0x0E."},
        {"offset_bytes": 1, "field": "Idx",         "size_bits": 8,  "purpose": "MainDevice index."},
        {"offset_bytes": 2, "field": "Address",     "size_bits": 32, "purpose": "Cmd-dependent."},
        {"offset_bytes": 6, "field": "Length",      "size_bits": 11, "purpose": "Data length 1-1486."},
        {"offset_bytes": 6, "field": "Reserved",    "size_bits": 3,  "purpose": "0"},
        {"offset_bytes": 6, "field": "Circulating", "size_bits": 1,  "purpose": "Already gone around once."},
        {"offset_bytes": 6, "field": "Next",        "size_bits": 1,  "purpose": "1 = next datagram follows."},
        {"offset_bytes": 8, "field": "IRQ",         "size_bits": 16, "purpose": "AL Status interrupt aggregate."},
    ]
    f["command_code_table"] = [
        {"cmd_hex": "0x00", "name": "NOP",  "addressing": "—",         "wkc_inc": 0, "use": "No-op"},
        {"cmd_hex": "0x01", "name": "APRD", "addressing": "Position",  "wkc_inc": 1, "use": "Start-up enumeration"},
        {"cmd_hex": "0x02", "name": "APWR", "addressing": "Position",  "wkc_inc": 1, "use": "Start-up register write"},
        {"cmd_hex": "0x03", "name": "APRW", "addressing": "Position",  "wkc_inc": 3, "use": "Atomic start-up RW"},
        {"cmd_hex": "0x04", "name": "FPRD", "addressing": "Configured","wkc_inc": 1, "use": "Targeted read"},
        {"cmd_hex": "0x05", "name": "FPWR", "addressing": "Configured","wkc_inc": 1, "use": "Targeted write"},
        {"cmd_hex": "0x06", "name": "FPRW", "addressing": "Configured","wkc_inc": 3, "use": "Targeted atomic RW"},
        {"cmd_hex": "0x07", "name": "BRD",  "addressing": "Broadcast", "wkc_inc": 1, "use": "Network-wide status sweep"},
        {"cmd_hex": "0x08", "name": "BWR",  "addressing": "Broadcast", "wkc_inc": 1, "use": "Network-wide config"},
        {"cmd_hex": "0x09", "name": "BRW",  "addressing": "Broadcast", "wkc_inc": 3, "use": "Network-wide atomic RW"},
        {"cmd_hex": "0x0A", "name": "LRD",  "addressing": "Logical",   "wkc_inc": 1, "use": "Cyclic Inputs"},
        {"cmd_hex": "0x0B", "name": "LWR",  "addressing": "Logical",   "wkc_inc": 1, "use": "Cyclic Outputs"},
        {"cmd_hex": "0x0C", "name": "LRW",  "addressing": "Logical",   "wkc_inc": 3, "use": "Combined cyclic IO"},
        {"cmd_hex": "0x0D", "name": "ARMW", "addressing": "Pos+MW",    "wkc_inc": 1, "use": "DC time propagation"},
        {"cmd_hex": "0x0E", "name": "FRMW", "addressing": "FP+MW",     "wkc_inc": 1, "use": "Re-distribute from FP SubDevice"},
    ]
    f["esm_state_table"] = [
        {"state": "Init",   "code_hex": "0x01", "description": "Initial after power-up."},
        {"state": "PreOp",  "code_hex": "0x02", "description": "Mailbox only."},
        {"state": "Boot",   "code_hex": "0x03", "description": "Firmware-update via FoE."},
        {"state": "SafeOp", "code_hex": "0x04", "description": "Process-data; Outputs in Safe state."},
        {"state": "Op",     "code_hex": "0x08", "description": "Full cyclic; Outputs drive hardware."},
        {"state": "Error",  "code_hex": "+0x10", "description": "OR'ed into previous-state code in AL Status."},
    ]
    f["mailbox_protocol_type_table"] = [
        {"mbx_type_hex": "0x01", "name": "AoE",  "long_name": "ADS over EtherCAT"},
        {"mbx_type_hex": "0x02", "name": "EoE",  "long_name": "Ethernet over EtherCAT"},
        {"mbx_type_hex": "0x03", "name": "CoE",  "long_name": "CANopen over EtherCAT"},
        {"mbx_type_hex": "0x04", "name": "FoE",  "long_name": "File access over EtherCAT"},
        {"mbx_type_hex": "0x05", "name": "SoE",  "long_name": "Servo Profile over EtherCAT"},
        {"mbx_type_hex": "0x0F", "name": "VoE",  "long_name": "Vendor-specific"},
    ]
    f["addressing_mode_summary_table"] = [
        {"mode": "Auto-Increment (AP)", "cmd_codes": ["APRD","APWR","APRW","ARMW"]},
        {"mode": "Configured (FP)",     "cmd_codes": ["FPRD","FPWR","FPRW","FRMW"]},
        {"mode": "Broadcast (BC)",      "cmd_codes": ["BRD","BWR","BRW"]},
        {"mode": "Logical (LOG)",       "cmd_codes": ["LRD","LWR","LRW"]},
    ]
    f["al_status_code_table"] = [
        {"code_hex": "0x0000", "description": "No error"},
        {"code_hex": "0x0011", "description": "Invalid requested state change"},
        {"code_hex": "0x0012", "description": "Unknown requested state"},
        {"code_hex": "0x0013", "description": "Bootstrap not supported"},
        {"code_hex": "0x0014", "description": "No valid firmware"},
        {"code_hex": "0x0015", "description": "Invalid mailbox config (Bootstrap)"},
        {"code_hex": "0x0016", "description": "Invalid mailbox config (PreOp)"},
        {"code_hex": "0x0017", "description": "Invalid SyncManager configuration"},
        {"code_hex": "0x0018", "description": "No valid inputs available"},
        {"code_hex": "0x0019", "description": "No valid outputs"},
        {"code_hex": "0x001A", "description": "Synchronization error"},
        {"code_hex": "0x001B", "description": "SyncManager watchdog"},
        {"code_hex": "0x001D", "description": "Invalid Output Configuration"},
        {"code_hex": "0x001E", "description": "Invalid Input Configuration"},
        {"code_hex": "0x001F", "description": "Invalid Watchdog Configuration"},
        {"code_hex": "0x0020", "description": "SubDevice needs cold start"},
        {"code_hex": "0x002C", "description": "Fatal sync error"},
        {"code_hex": "0x002D", "description": "No Sync Error"},
        {"code_hex": "0x0030", "description": "DC Invalid Sync Configuration"},
        {"code_hex": "0x0031", "description": "DC Invalid Latch Configuration"},
        {"code_hex": "0x0032", "description": "DC PLL Sync Error"},
        {"code_hex": "0x0033", "description": "DC Sync IO Error"},
        {"code_hex": "0x0034", "description": "DC Sync Timeout"},
        {"code_hex": "0x0035", "description": "DC Invalid Sync Cycle Time"},
        {"code_hex": "0x0042", "description": "MBX_EOE"},
        {"code_hex": "0x0043", "description": "MBX_COE"},
        {"code_hex": "0x0044", "description": "MBX_FOE"},
        {"code_hex": "0x0045", "description": "MBX_SOE"},
        {"code_hex": "0x004F", "description": "MBX_VOE"},
        {"code_hex": "0x0050", "description": "EEPROM no access"},
    ]
    f["mbx_header_table"] = [
        {"offset_bytes": 0, "field": "Length",            "size_bytes": 2, "purpose": "Mailbox data length"},
        {"offset_bytes": 2, "field": "Address",           "size_bytes": 2, "purpose": "Routing station address"},
        {"offset_bytes": 4, "field": "Channel+Priority",  "size_bytes": 1, "purpose": "Channel[5:0] + Priority[7:6]"},
        {"offset_bytes": 5, "field": "Type+Counter",      "size_bytes": 1, "purpose": "Type[3:0] + Counter[6:4]"},
    ]
    f["fcs_polynomial_table"] = {
        "polynomial_hex": "0x04C11DB7",
        "reflected_hex": "0xEDB88320",
        "init_hex": "0xFFFFFFFF",
        "final_xor_hex": "0xFFFFFFFF",
        "bit_order": "LSB-first within each byte",
        "comment": "Identical to IEEE 802.3 Ethernet CRC-32.",
    }
    f["sm_mode_encoding_table"] = [
        {"control_byte_bits": "1:0", "value": "00", "meaning": "3-buffer (process data)"},
        {"control_byte_bits": "1:0", "value": "10", "meaning": "Mailbox mode"},
        {"control_byte_bits": "3:2", "value": "00", "meaning": "Read (Outputs)"},
        {"control_byte_bits": "3:2", "value": "01", "meaning": "Write (Inputs)"},
    ]
    # Strip Ethernet-specific encoding tables left by the Ethernet synth
    for k in ("mac_frame_table", "ethertype_table",
              "mii_txd_encoding_table", "mii_rxd_encoding_table",
              "mdio_c22_frame_table", "mdio_c45_frame_table",
              "clause22_register_summary_table", "clause45_devad_table",
              "auto_neg_base_page_table", "tables"):
        f.pop(k, None)
    d["fields"] = f
    _write(p, d)


def _apply_l16(gd: Path) -> None:
    """L16 COMPLIANCE_PROPERTIES — replace Ethernet (preamble + FCS +
    minimum-frame) compliance with EtherCAT must-have / must-not-have."""
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["must_have_properties"] = [
        "Every wire-side Ethernet frame is a valid IEEE 802.3 frame.",
        "EtherType field equals 0x88A4 (or UDP/IP encapsulation on port 0x88A4).",
        "EtherCAT header Type=0x1 (or 0x4 for EAP) and Length consistent.",
        "Each datagram has valid 10-byte header + Data + 2-byte WKC at correct offsets.",
        "SubDevices forward frames on-the-fly with per-hop latency within ESC datasheet spec.",
        "WKC incremented per spec rules (+1 read, +2 write, +3 RW) by every addressed SubDevice.",
        "ESM follows 6-state model with only legal transitions; AL Status honest.",
        "Process-Data Watchdog forces Op → SafeOp on cyclic frame loss.",
        "Each ESC has hardware auto-loopback on any port without active link partner.",
        "SII EEPROM has valid ESI per ETG.2000; SII checksum correct.",
        "Mailbox SM channels enforce atomic write-then-read.",
        "Process-data SM 3-buffer mode prevents PDI from reading half-written buffer.",
        "DC-capable SubDevices honor System Time Offset + Delay; SYNC0/SYNC1 per cycle time.",
    ]
    f["must_not_have_properties"] = [
        "MUST NOT emit wire-side Ethernet frames with malformed FCS.",
        "MUST NOT silently drop addressed datagrams.",
        "MUST NOT autonomously transition out of Op except via PD WD or MainDevice request.",
        "MUST NOT modify bytes outside addressed FMMU regions during LRD/LWR/LRW.",
        "MUST NOT respond to mailbox protocols not declared in SII bitmask.",
        "MUST NOT allow MainDevice to enter Op without traversing PreOp + SafeOp.",
        "MUST NOT discard frames with unknown EtherCAT header Type — forward transparently.",
        "MUST NOT reuse a Configured Station Address conflicting with another SubDevice.",
    ]
    f["compliance_failure_modes"] = [
        "Illegal ESM transition not rejected with AL Status Code 0x0011.",
        "Working Counter miscount.",
        "Mailbox response when protocol not declared in SII bitmask.",
        "PD WD not expiring within configured window.",
        "DC SYNC0 jitter exceeding spec.",
        "SII checksum mismatch on reload.",
        "Frame forwarding corrupting bytes outside addressed region.",
    ]
    f["frame_boundary_compliance"] = [
        "ESC forwards every Ethernet frame on Port 0 to next open port without altering "
        "bytes outside addressed-FMMU / addressed-register regions.",
        "Frames with corrupted FCS still forwarded (FCS preserved) and counted in 0x0300.",
        "Frames shorter than 60 B are not generated by SubDevices.",
    ]
    f["address_filter_compliance"] = [
        "Destination MAC NOT used to filter EtherCAT frames.",
        "AP/FP/BC/LOG applied at datagram level.",
        "Multiple datagrams in one frame can address same SubDevice with different Cmds.",
    ]
    f["reset_behavior_compliance"] = [
        "Hard reset → Init; ESC re-reads SII.",
        "Soft reset (0x0040) → Init; SII reload optional.",
        "Hot reset → AL Status visible via next BRD.",
    ]
    f["min_link_constraint"] = (
        "Active link required on Port 0 for SubDevice to participate. Without link, the ESC "
        "is inaccessible from the wire; PDI access by local µC still works.")
    f["etg_certification_path"] = [
        "Apply for ETG membership",
        "Register Vendor ID with ETG",
        "Develop ESI XML per ETG.2000",
        "Run ETG Conformance Test Tool (CTT)",
        "Submit conformance report to ETG Test Center",
        "Receive ETG.1500 Conformance Mark",
    ]
    f["safety_certification"] = (
        "FSoE products require additional certification per IEC 61784-3-12 + IEC 61508 SIL 3 "
        "by accredited safety body.")
    d["fields"] = f
    _write(p, d)


def _apply_l17(gd: Path) -> None:
    """L17 CHANNEL_SIGNAL_CATALOG — replace MII / GMII / RGMII pin
    catalog with EtherCAT Port 0/1/2/3, PDI, SII, DC, LED catalog."""
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["channels"] = [
        {"name": "ECAT_P0_TXP / TXN",  "interface": "Ethernet Port 0", "direction": "ESC → wire",   "purpose": "100BASE-TX / 1000BASE-T differential TX to upstream.", "active_levels": "MLT-3/PAM-5 differential",        "idle_level": "Link-pulse"},
        {"name": "ECAT_P0_RXP / RXN",  "interface": "Ethernet Port 0", "direction": "wire → ESC",   "purpose": "100BASE-TX / 1000BASE-T differential RX from upstream.","active_levels": "MLT-3/PAM-5 differential",        "idle_level": "Link-pulse"},
        {"name": "ECAT_P1_TXP / TXN",  "interface": "Ethernet Port 1", "direction": "ESC → wire",   "purpose": "Forward to downstream SubDevice; loop back on link-down.","active_levels": "MLT-3/PAM-5 differential",       "idle_level": "Link-pulse"},
        {"name": "ECAT_P1_RXP / RXN",  "interface": "Ethernet Port 1", "direction": "wire → ESC",   "purpose": "Receive returning frame.",                              "active_levels": "MLT-3/PAM-5 differential",        "idle_level": "Link-pulse"},
        {"name": "ECAT_P2 / P3 (opt)", "interface": "Ethernet Port 2/3","direction": "bidirectional","purpose": "Optional 3rd/4th ports for tree/star topologies.",     "active_levels": "MLT-3/PAM-5 differential",        "idle_level": "Link-pulse"},
        {"name": "MDC",                "interface": "MII Management",   "direction": "ESC → PHY",   "purpose": "MII Management clock, ≤ 2.5 MHz.",                       "active_levels": "LVTTL/LVCMOS",                    "idle_level": "0"},
        {"name": "MDIO",               "interface": "MII Management",   "direction": "bidirectional","purpose": "MII Management data (three-state, 1.5 kΩ pull-up).",   "active_levels": "LVTTL/LVCMOS three-state",         "idle_level": "Hi-Z"},
        {"name": "EEPROM_SCL",         "interface": "SII (EEPROM)",     "direction": "ESC → EEPROM","purpose": "I²C-compatible clock to SII EEPROM.",                   "active_levels": "Open-drain, 4.7 kΩ pull-up",      "idle_level": "Hi-Z"},
        {"name": "EEPROM_SDA",         "interface": "SII (EEPROM)",     "direction": "bidirectional","purpose": "I²C-compatible data.",                                   "active_levels": "Open-drain, 4.7 kΩ pull-up",      "idle_level": "Hi-Z"},
        {"name": "SYNC0",              "interface": "Distributed Clocks","direction": "ESC → µC",   "purpose": "First DC pulse output; period in 0x0990.",              "active_levels": "LVTTL/LVCMOS",                    "idle_level": "0"},
        {"name": "SYNC1",              "interface": "Distributed Clocks","direction": "ESC → µC",   "purpose": "Second DC pulse output; period in 0x0994.",             "active_levels": "LVTTL/LVCMOS",                    "idle_level": "0"},
        {"name": "LATCH0",             "interface": "Distributed Clocks","direction": "µC → ESC",   "purpose": "External event input — capture System Time.",           "active_levels": "LVTTL/LVCMOS, edge-sensitive",    "idle_level": "0"},
        {"name": "LATCH1",             "interface": "Distributed Clocks","direction": "µC → ESC",   "purpose": "Second latch input.",                                   "active_levels": "LVTTL/LVCMOS, edge-sensitive",    "idle_level": "0"},
        {"name": "PDI_CS_n",           "interface": "PDI",              "direction": "µC → ESC",    "purpose": "Chip select for PDI bus / SPI slave.",                   "active_levels": "Active LOW",                      "idle_level": "1"},
        {"name": "PDI_ADDR[15:0]",     "interface": "PDI",              "direction": "µC → ESC",    "purpose": "PDI address bus.",                                       "active_levels": "LVTTL/LVCMOS",                    "idle_level": "Don't care"},
        {"name": "PDI_DATA[7:0/15:0]", "interface": "PDI",              "direction": "bidirectional","purpose": "PDI data bus 8/16-bit.",                                 "active_levels": "LVTTL/LVCMOS",                    "idle_level": "Hi-Z"},
        {"name": "PDI_WR_n / RD_n",    "interface": "PDI",              "direction": "µC → ESC",    "purpose": "Write / Read strobe.",                                   "active_levels": "Active LOW",                      "idle_level": "1"},
        {"name": "PDI_READY",          "interface": "PDI",              "direction": "ESC → µC",    "purpose": "Wait-state signal.",                                     "active_levels": "Active HIGH = ready",             "idle_level": "1"},
        {"name": "PDI_IRQ",            "interface": "PDI",              "direction": "ESC → µC",    "purpose": "Interrupt output; mask in 0x0200.",                      "active_levels": "Configurable polarity",            "idle_level": "Inactive"},
        {"name": "SPI_SCK / MOSI / MISO", "interface": "PDI (SPI)",     "direction": "various",     "purpose": "SPI clock + MOSI + MISO.",                               "active_levels": "LVTTL/LVCMOS",                    "idle_level": "SCK per CPOL"},
        {"name": "PDI_DIO_OUT[31:0]",  "interface": "PDI (DIO)",        "direction": "ESC → ext",   "purpose": "Up to 32 output pins; no µC required.",                  "active_levels": "LVTTL/LVCMOS",                    "idle_level": "Last value"},
        {"name": "PDI_DIO_IN[31:0]",   "interface": "PDI (DIO)",        "direction": "ext → ESC",   "purpose": "Up to 32 input pins sampled into DPRAM.",                "active_levels": "LVTTL/LVCMOS",                    "idle_level": "Sampled"},
        {"name": "LED_RUN",            "interface": "Diagnostic",       "direction": "ESC → LED",   "purpose": "ESM state per IEC 61784-2.",                             "active_levels": "Active HIGH",                     "idle_level": "Pattern-coded"},
        {"name": "LED_ERR",            "interface": "Diagnostic",       "direction": "ESC → LED",   "purpose": "AL Status error.",                                       "active_levels": "Active HIGH",                     "idle_level": "Off"},
        {"name": "LED_LINK_P0 / P1",   "interface": "Diagnostic",       "direction": "PHY → LED",   "purpose": "Per-port link state.",                                   "active_levels": "Active HIGH",                     "idle_level": "Off"},
        {"name": "LED_ACT_P0 / P1",    "interface": "Diagnostic",       "direction": "PHY → LED",   "purpose": "Per-port TX/RX activity.",                               "active_levels": "Blinking",                        "idle_level": "Off"},
        {"name": "RESET_n",            "interface": "Reset",            "direction": "ext → ESC",   "purpose": "Hard reset; asynchronous.",                              "active_levels": "Active LOW",                      "idle_level": "1"},
        {"name": "CLK25",              "interface": "Clock",            "direction": "ext → ESC",   "purpose": "25 MHz crystal/oscillator (some ESCs 50 MHz).",          "active_levels": "Square wave 25 MHz",              "idle_level": "Running"},
    ]
    f["esc_typical_pin_count_by_role"] = {
        "Ethernet ports (2-port)": 12,
        "Ethernet ports (3-port)": 18,
        "Ethernet ports (4-port)": 24,
        "MII Management (MDC + MDIO)": 2,
        "SII EEPROM (SCL + SDA)": 2,
        "PDI µC bus (16-bit async)": 38,
        "PDI SPI slave": 5,
        "PDI DIO (32 out + 32 in)": 64,
        "DC signals (SYNC0/1 + LATCH0/1)": 4,
        "Diagnostic LEDs": 8,
        "Power + Ground (typical)": "16-24",
    }
    d["fields"] = f
    _write(p, d)


def _apply_l18(gd: Path) -> None:
    """L18 INTERCONNECT_TOPOLOGY — replace IEEE star / hub topology
    with EtherCAT line / tree / ring / hot-connect."""
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["topology_type"] = (
        "Daisy-chained (line) single-MainDevice multi-SubDevice fieldbus on standard Ethernet "
        "wire, with on-the-fly frame processing replacing classical store-and-forward. "
        "Auto-loopback at the last SubDevice reflects the frame back upstream.")
    f["supported_topologies"] = [
        {"name": "Line / Daisy-Chain",      "description": "Most common; min cabling cost.",                                      "max_nodes": 65535, "redundancy": False},
        {"name": "Tree",                    "description": "3- or 4-port SubDevice junctions.",                                   "max_nodes": 65535, "redundancy": False},
        {"name": "Star",                    "description": "All branches off one central multi-port SubDevice.",                  "max_nodes": 65535, "redundancy": False},
        {"name": "Ring (cable redundancy)", "description": "Dual NIC MainDevice; auto-divides on cable break.",                    "max_nodes": 65535, "redundancy": True},
        {"name": "Drop line",               "description": "Stub branch terminating at a single device.",                         "max_nodes": 65535, "redundancy": False},
        {"name": "Hot Connect / Hot Swap",  "description": "Groups of SubDevices may join/leave during operation.",               "max_nodes": 65535, "redundancy": "Group-level"},
        {"name": "Mixed",                   "description": "Arbitrary combination of line+tree+star+ring+drop+hot-connect.",     "max_nodes": 65535, "redundancy": "Per-segment"},
    ]
    f["master_slave_role_summary"] = {
        "MainDevice (Master)": "Single per logical bus during cyclic phase. Originates every frame. No EtherCAT-specific hardware.",
        "SubDevice (Slave)":   "Up to 65,535 per logical bus. Each contains an ESC ASIC or FPGA IP. On-the-fly processing only.",
    }
    f["interconnect_role"] = (
        "Each ESC integrates 2-4 Ethernet ports + on-the-fly engine + FMMU + SyncManager + "
        "DPRAM + DC + SII + PDI. Port 0 = upstream, Port 1/2/3 = downstream. Hardware "
        "auto-loopback on any port without an active link partner enables daisy-chain "
        "auto-return without explicit configuration.")
    f["frame_traversal_pattern"] = (
        "Frame originated by MainDevice → SubDevice₁ Port 0 → forwarded Port 1 → SubDevice₂ "
        "Port 0 → ... → last SubDevice → auto-loopback → returns to MainDevice. Total wire "
        "traversal = 2 × cable length + Σ (2 × ESC forwarding delay).")
    f["addressing_in_the_topology"] = [
        "Position (AP) — physical sequence; used at start-up only.",
        "Configured (FP) — 16-bit Configured Station Address assigned by MainDevice.",
        "Broadcast (BC) — every SubDevice.",
        "Logical (LOG) — 32-bit Logical Address space mapped via FMMUs.",
    ]
    f["device_classification"] = {
        "MainDevice classes": ["Class A (full)", "Class B (basic)"],
        "SubDevice classes":  ["Standard", "FSoE (functional safety)", "MainDevice-side gateway (EAP bridge)"],
    }
    f["redundancy_modes"] = [
        {"name": "Cable Redundancy (ring + dual NIC)", "level": "Wire", "recovery_time_typical_us": 15},
        {"name": "Hot Connect / Hot Swap",             "level": "Device", "recovery_time_typical_ms": "Group-dependent"},
        {"name": "FSoE end-point redundancy",          "level": "Safety", "recovery_time_typical_ms": "Watchdog-dependent"},
    ]
    f["ordering_guarantees"] = (
        "On-the-fly processing is strictly in-order within one frame. Per-cycle ordering "
        "enforced by MainDevice cyclic engine. Mailbox messages point-to-point and in-order.")
    f["memory_vs_peripheral_regions"] = (
        "ESC's 64-KByte address space is uniformly memory-mapped from both ECAT wire side "
        "and PDI side. 0x0000-0x0FFF = hardware registers; 0x1000-0xFFFF = configurable DPRAM.")
    f["performance_summary"] = {
        "1000 distributed digital I/O processed": "30 µs (per ETG brochure)",
        "100 axes with 8 bytes process data each": "100 µs",
        "Bandwidth utilization on wire": ">90% typical",
        "DC synchronization jitter": "<100 ns end-to-end",
        "Cycle time floor": "<100 µs",
    }
    d["fields"] = f
    _write(p, d)


def _apply_l19(gd: Path) -> None:
    """L19 CONSTRAINTS_PDK — replace IEEE 802.3 cable constraints with
    EtherCAT-specific channel + ESC supply constraints."""
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = [
        {"channel": "Ethernet wire (100BASE-TX)", "max_segment_length_m": 100,  "cable_type": "Cat 5/5e UTP, 100 Ω", "connector": "RJ-45 or M8/M12/M23"},
        {"channel": "Ethernet wire (100BASE-FX)", "max_segment_length_m": 2000, "cable_type": "62.5/125 or 50/125 µm multimode fiber", "connector": "SC/LC/MTRJ"},
        {"channel": "EtherCAT G (1000BASE-T)",     "max_segment_length_m": 100,  "cable_type": "Cat 5e UTP or better"},
        {"channel": "EtherCAT P",                  "max_segment_length_m": 50,   "cable_type": "ETG-specified power+data hybrid", "current_limit_A_per_rail": 3},
    ]
    f["esc_clocking_constraints"] = [
        {"signal": "External crystal/oscillator", "frequency_MHz": 25, "tolerance_ppm": 100,
         "note": "Some ESCs accept 50 MHz."},
    ]
    f["esc_pdi_constraints"] = [
        {"interface": "Async µC bus",    "min_cycle_time_ns": 40},
        {"interface": "Sync µC bus",     "max_clock_MHz": 30},
        {"interface": "SPI",             "max_clock_MHz": 25},
    ]
    f["esc_power_constraints"] = [
        {"rail": "VCC_CORE", "voltage_V": [1.0, 1.2, 1.5], "tolerance_pct": 5},
        {"rail": "VCC_IO",   "voltage_V": [1.8, 2.5, 3.3], "tolerance_pct": 5},
        {"power_W_typical": 0.5, "power_W_max": 1.5},
    ]
    f["environmental_constraints"] = [
        {"parameter": "Operating temperature", "range_C": [-40, 85]},
        {"parameter": "Storage temperature",   "range_C": [-65, 150]},
        {"parameter": "Humidity",              "range_pct": [5, 95]},
        {"parameter": "ESD",                   "spec": "IEC 61000-4-2 ±4 kV contact"},
        {"parameter": "EMC",                   "spec": "IEC 61000-6-2 industrial"},
    ]
    f["pdk_pdf_note"] = (
        "ETG Brochure is a system + protocol-level document. Silicon-level constraints are "
        "defined by the ESC ASIC vendor or FPGA fabric.")
    f["notes"] = (
        "EtherCAT MainDevice has no special silicon constraints. EtherCAT G adds 1000BASE-T "
        "/ 1000BASE-X envelope.")
    d["fields"] = f
    _write(p, d)


def _apply_l20(gd: Path) -> None:
    """L20 DFT_SCAN_TOPOLOGY — replace IEEE BSCAN / PHY-loopback DFT with
    EtherCAT in-band diagnostic (RX error counters + AL Status) + ESC DFT."""
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["dft_present"] = False
    f["in_band_test_facilities"] = [
        "Per-port RX Error Counter (0x0300-0x030F).",
        "Per-port Lost Link Counter (0x0308-0x030F).",
        "Working Counter (WKC) per datagram.",
        "AL Status (0x0130) + AL Status Code (0x0134).",
        "DC System Time Difference (0x092C).",
        "Process-Data Watchdog Status (0x0440).",
    ]
    f["internal_diagnostics_observability"] = [
        "DL Status (0x0110) per-port.",
        "BRD 0x0130 sweep snapshots ESM state of every SubDevice.",
        "BRD 0x0300 sweep snapshots frame-error rate.",
        "Independent Diagnostic Interface — external tool read-only via MainDevice pass-through.",
    ]
    f["out_of_band_test_facilities"] = [
        "External crystal/oscillator replaceable for compliance characterization.",
        "RESET_n external pin.",
        "RUN/ERR/LINK/ACT LEDs for visual diagnostic.",
        "Conformance Test Tool (CTT) — ETG-provided official suite.",
    ]
    f["esc_silicon_dft"] = (
        "Implementation-specific to ESC ASIC vendor. Beckhoff ET1100 includes full JTAG "
        "boundary scan (IEEE 1149.1), at-speed BIST of on-the-fly engine memory, scan chains. "
        "FPGA-based ESC IP cores rely on FPGA fabric's native DFT.")
    f["notes"] = (
        "ETG Brochure is a protocol-level document; silicon DFT is vendor-specific. The "
        "diagnostic facilities listed above are wire-protocol-visible and the primary "
        "observability mechanism in deployed systems.")
    d["fields"] = f
    _write(p, d)


def _apply_l21(gd: Path) -> None:
    """L21 POWER_INTENT — replace IEEE PAUSE / EEE LPI / Wake-on-LAN with
    EtherCAT power model (no PAUSE, no LPI, optional EtherCAT P)."""
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["power_intent_present"] = True
    f["link_power_management_states"] = [
        {"state": "Full operation",  "description": "PHY active, ESM in Op, cyclic exchange. PHY ~250 mW per 100BASE-TX port; ESC ~300-1500 mW."},
        {"state": "Link-down idle",  "description": "Port without link partner auto-loops; PHY backs off to low-power link-pulse."},
        {"state": "Initialization",  "description": "Power-up — PHY auto-neg, ESC SII load, AL Status = Init."},
    ]
    f["low_power_modes_summary"] = (
        "EtherCAT does not define PHY low-power states beyond IEEE 802.3. IEEE 802.3az LPI "
        "is generally NOT used because LPI wake delay is incompatible with sub-millisecond "
        "cycle times. EtherCAT P delivers 24 V US + UP power alongside data on the same cable.")
    f["device_states_d0_d3_analog"] = (
        "Not applicable — EtherCAT is a network protocol, not a PCI Express endpoint.")
    f["auxiliary_power_for_wake_on_lan"] = (
        "Not specified — EtherCAT does not define a Wake-on-LAN mechanism.")
    f["pause_flow_control_summary"] = (
        "EtherCAT does NOT use IEEE 802.3x PAUSE frames. Flow control is implicit: MainDevice "
        "originates frames at deterministic cycle rate; SubDevices process on-the-fly without "
        "buffering; no link congestion can occur.")
    f["ethercat_p_power_summary"] = {
        "spec": "EtherCAT P (ETG-released)",
        "rails": [
            {"name": "US (System/Sensor/Electronics)", "voltage_V": 24, "current_A_max": 3, "purpose": "Logic + sensor power"},
            {"name": "UP (Peripheral/Actuator)",        "voltage_V": 24, "current_A_max": 3, "purpose": "Actuator drive power"},
        ],
        "max_segment_length_m": 50,
        "coupling": "ETG-specified magnetics combine 24 V DC with 100BASE-TX on same cable.",
        "connector": "M8 P-coded 4-pin",
    }
    f["notes"] = (
        "EtherCAT MainDevice power consumption is a property of the host PC/controller. "
        "SubDevice ESC consumption typically 0.3-1.5 W; PHYs add ~250 mW per active port.")
    d["fields"] = f
    _write(p, d)


def _apply_l22(gd: Path) -> None:
    """L22 VERIFICATION_PLAN — replace IEEE Ethernet verification with
    ETG.1500 + interoperability + ETG CTT plan."""
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["verification_plan_present"] = True
    f["verification_categories_derived_from_spec"] = [
        {"category": "Frame structure", "checks": [
            "EtherType=0x88A4 raw-Ethernet processed.",
            "UDP/IP encapsulated (dst port 0x88A4) processed.",
            "EtherCAT header Length consistent.",
            "EtherCAT header Type=0x1 selects ESC datagram processing.",
            "FCS correct; Frame Error Counter increments on receive errors.",
        ]},
        {"category": "Command-code processing", "checks": [
            "All 15 Cmd values processed per spec.",
            "AP / FP / BC / LOG addressing.",
            "WKC: +1 read, +2 write, +3 RW.",
        ]},
        {"category": "ESM", "checks": [
            "All 6 states reachable via legal transitions only.",
            "Illegal transitions rejected with AL Status Code 0x0011.",
            "PD WD forces Op → SafeOp.",
            "AL Status Error bit set correctly.",
        ]},
        {"category": "FMMU and SyncManager", "checks": [
            "FMMU bit-granular mapping.",
            "SM Mailbox atomic handshake.",
            "SM Buffered 3-buffer overrun protection.",
            "SM WD Trigger bit 6.",
        ]},
        {"category": "Distributed Clocks", "checks": [
            "Propagation delay measurement.",
            "System Time Offset; <100 ns of reference.",
            "ARMW cyclic propagation.",
            "SYNC0/SYNC1 jitter <100 ns across hops.",
        ]},
        {"category": "Mailbox protocols", "checks": [
            "CoE SDO Upload / Download / Emergency.",
            "FoE firmware download in Boot.",
            "EoE ICMP tunneling.",
            "AoE routed request/response.",
        ]},
        {"category": "Diagnostic and error counters", "checks": [
            "Frame Error Counter increments on FCS error.",
            "Lost Link Counter on cable disconnect.",
            "DL Status reflects port states.",
            "WKC mismatch on cable break.",
        ]},
        {"category": "Conformance", "checks": [
            "ETG.1500 CTT pass.",
            "ETG.2000 ESI XML validates.",
            "Vendor ID + Product Code + Revision readable via CoE OD 0x1018.",
        ]},
        {"category": "Topology and redundancy", "checks": [
            "Daisy-chain; auto-loopback at last SubDevice.",
            "Tree: 3+ port branches independently reachable.",
            "Ring redundancy recovery within ~15 µs.",
            "Hot Connect group join/leave during cyclic exchange.",
        ]},
    ]
    f["verification_tools"] = [
        "ETG Conformance Test Tool (CTT)",
        "Wireshark + EtherCAT dissector",
        "Beckhoff TwinCAT / acontis EC-Inspector / KPA EtherCAT Studio",
        "Oscilloscope for DC SYNC0/1 jitter",
        "FSoE certification suite (TÜV / exida)",
    ]
    f["notes"] = (
        "Verification flow: (1) APRD bring-up enumeration, (2) ESM walk Init→PreOp→SafeOp→Op, "
        "(3) cyclic exchange with WKC monitoring, (4) ETG CTT, (5) interoperability against "
        "reference MainDevice, (6) DC jitter characterization, (7) optional FSoE certification.")
    d["fields"] = f
    _write(p, d)


def _apply_l23(gd: Path) -> None:
    """L23 SECURITY_REQUIREMENTS — replace Ethernet MACsec / PAUSE-frame
    integrity model with the EtherCAT FSoE + black-channel safety model."""
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "Ethernet FCS (CRC-32) — link-layer bit-error detection.",
        "Working Counter (WKC) per datagram — application-layer integrity check.",
        "Mailbox handshake atomic; partially-written messages never observed.",
        "Process-data SM 3-buffer mode — overrun-protected.",
        "Process-Data Watchdog — silent-fail protection.",
        "PDI Watchdog — local µC stall detection.",
        "SII checksum on EEPROM load.",
    ]
    f["anti_tampering_features"] = [
        "Register Write Enable / Write Protection (0x0020-0x002F).",
        "PDI Access bit (0x0501) — explicit SII ownership transfer.",
        "ESM state machine rejects illegal Op-state entry.",
    ]
    f["confidentiality_features"] = [
        "Not specified — EtherCAT does NOT define wire encryption.",
        "Air-gapped from corporate IP networks via Industrial DMZ pattern; cross-network via EAP.",
    ]
    f["authentication_features"] = [
        "Not specified — no MainDevice authentication.",
        "Hot Connect groups: MainDevice rejects unexpected Vendor ID / Product Code via ESI cross-check.",
    ]
    f["integrity_features_beyond_crc"] = [
        "Working Counter (WKC).",
        "Process-Data Watchdog.",
        "Distributed Clock continuous drift monitoring (0x092C).",
    ]
    f["safety_features_fsoe"] = (
        "Safety over EtherCAT (FSoE, IEC 61784-3-12) is an optional black-channel-principle "
        "safety frame layered on mailbox transport. Adds: end-to-end CRC + sequence number, "
        "watchdog timeout per safety connection, FSoE Connection ID, dual-channel architecture. "
        "Underlying EtherCAT network is NOT safety-rated; only FSoE end-points are. SIL 3 / "
        "Cat 4 / PL e.")
    f["future_security_pointers"] = [
        "Possible cryptographic message integrity at EtherCAT layer (under ETG discussion).",
        "TSN coexistence may pull in IEEE 802.1AE (MACsec) for shared segments.",
        "OPC UA Secure Channel above EAP for cross-plant authentication.",
    ]
    f["notes"] = (
        "EtherCAT's threat model assumes physically protected industrial environment. "
        "Wire-level encryption / authentication is NOT in scope of base spec. For applications "
        "that require it, FSoE provides safety integrity; external IPsec / OPC UA / MACsec at "
        "the network boundary.")
    d["fields"] = f
    _write(p, d)


def apply_ethercat_synth(generated_docs_dir: Path, is_ethercat: bool,
                         ethercat_ic_name: Optional[str]) -> None:
    """Apply EtherCAT-specific synth when the structural signature matched.

    IMPORTANT: This overlay must run AFTER ethernet_protocol_synth on any
    spec that triggers BOTH signatures (every EtherCAT document does,
    because EtherCAT is layered on Ethernet). All field updates here use
    direct assignment (NOT setdefault) to force-overwrite any Ethernet-
    leaning content the prior overlay populated.
    """
    if not is_ethercat:
        return
    gd = Path(generated_docs_dir)
    if ethercat_ic_name is not None:
        _force_ic_name(gd, ethercat_ic_name)
    _apply_l1(gd)
    _apply_l2(gd)
    _apply_l3(gd)
    _apply_l4(gd)
    _apply_l5(gd)
    _apply_l6(gd)
    _apply_l7(gd)
    _apply_l8_consts(gd)
    _apply_l8_timing(gd)
    _apply_l9(gd)
    _apply_l10(gd)
    _apply_l11(gd)
    _apply_l12(gd)
    _apply_l13(gd)
    _apply_l14(gd)
    _apply_l15(gd)
    _apply_l16(gd)
    _apply_l17(gd)
    _apply_l18(gd)
    _apply_l19(gd)
    _apply_l20(gd)
    _apply_l21(gd)
    _apply_l22(gd)
    _apply_l23(gd)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_ethercat(blob: str) -> bool:
    """Content-only `ethercat` detector with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text).

    The original structural signature below (EtherCAT + ESC + slave, or
    EtherCAT + FMMU + SyncManager, or 0x88A4 + EtherCAT, or EtherCAT +
    datagram) is necessary but NOT sufficient: every neighbour in the
    Industrial-Ethernet family cites EtherCAT in a comparison section
    (datagram / 0x88A4 / FMMU / SyncManager / ESC tokens leak in), and the
    base IEEE-802.3 docs share EtherCAT's MII/MDIO/802.3 substrate, so the
    loose branches below would otherwise fire on a doc whose DOMINANT
    subject is a foreign protocol — and the generic EtherCAT synth would
    then FORCE-OVERWRITE that foreign spec's L-docs with EtherCAT identity.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, density/structural signatures only, NO benchmark-name /
    chip / SKU literal as detection logic): if the blob's DOMINANT subject
    is one of the foreign protocols, defer (return False) so the generic
    EtherCAT synth never runs on it:
      - 800G Ethernet (the IEEE 802.3df / 800GBASE / PAM4 PHY signature) —
        EtherCAT runs at 100 Mb/s or 1 Gb/s and carries NONE of the 800G
        PHY-family tokens.
      - Base IEEE 802.3 Ethernet (overwhelming MII/MDIO/802.3 PHY-MAC
        density with only incidental EtherCAT mentions) — an EtherCAT-
        PRIMARY doc names "EtherCAT" hundreds of times, not a handful.
      - PROFIBUS (the PROFIBUS-DP signature: dense PROFIBUS naming + the
        SD1-SD4 telegram delimiters / DPVx service levels / GSD device
        description / token-passing hybrid MAC). EtherCAT carries none of
        these RS-485 fieldbus structures.
      - PROFINET (the PROFINET-IO signature: dense PROFINET naming +
        IO-Controller/IO-Device roles / GSDML / DCP / RT EtherType 0x8892).

    The real `ethercat` benchmark trips NONE of these defers (it has 0
    800GBASE/PROFIBUS-DP tokens, near-zero PROFINET tokens, and is not
    802.3-PHY-dominated) and stays True; the four foreign benchmarks each
    trip their own foreign-primary defer and are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT EtherCAT). ---
    # 800G Ethernet: the IEEE 802.3df / 800GBASE PAM4 PHY-family signature.
    ethernet_800g_primary = (
        blob.count("800GBASE") >= 5
        or blob.count("802.3df") >= 5
        or ("800 Gigabit Ethernet" in blob and "PAM4" in blob)
        or (low.count("pam4") >= 20 and "802.3" in blob))
    # PROFIBUS-DP: dense PROFIBUS naming + at least one PROFIBUS-only
    # structural feature (SD1-SD4 telegram delimiters / DPVx service levels /
    # GSD device description / token-passing hybrid MAC).
    _sd_delims = sum(blob.count(t) for t in ("SD1", "SD2", "SD3", "SD4"))
    _dpv = sum(blob.count(t) for t in ("DPV0", "DPV1", "DPV2"))
    _token_passing = (low.count("token passing") + low.count("token-passing"))
    profibus_primary = (
        low.count("profibus") >= 20
        and (_sd_delims >= 4 or _dpv >= 2 or low.count("gsd") >= 5
             or _token_passing >= 3))
    # PROFINET-IO: dense PROFINET naming + an IO-role / engineering / RT
    # EtherType signature unique to PROFINET.
    _pn_roles = (
        ("io-controller" in low or "io controller" in low)
        and ("io-device" in low or "io device" in low))
    profinet_primary = (
        low.count("profinet") >= 20
        and (_pn_roles or "gsdml" in low or low.count("dcp") >= 5
             or "0x8892" in low))
    # Base IEEE 802.3 Ethernet: overwhelming MII/MDIO/802.3 PHY-MAC density
    # with only incidental EtherCAT mentions (an EtherCAT-PRIMARY doc names
    # EtherCAT hundreds of times — not a handful).
    # Keyed on the ratio, not absolute magnitude: an ETHERNET-primary doc is
    # dense in the MII/MDIO/802.3 PHY-MAC signature while EtherCAT stays
    # INCIDENTAL (a handful of comparison mentions), whereas an EtherCAT-primary
    # doc names EtherCAT hundreds of times (447 in the real benchmark) and is far
    # LESS 802.3-PHY-dense (18) — so the incidental-EtherCAT clause is the load-
    # bearing discriminator and the PHY-density thresholds only need to establish
    # a genuine PHY-MAC doc, not a specific magnitude (a real ethernet spec runs
    # MII≈400 / MDIO≈145 / 802.3≈119 — the old 200/200 gate missed it).
    ethernet_base_primary = (
        blob.count("EtherCAT") < 20
        and blob.count("MII") >= 100
        and blob.count("MDIO") >= 20
        and blob.count("802.3") >= 50)
    if (ethernet_800g_primary or profibus_primary or profinet_primary
            or ethernet_base_primary):
        return False

    # --- STRUCTURAL EtherCAT signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("EtherCAT" in blob and "ESC" in blob
         and "slave" in blob.lower())
        or ("EtherCAT" in blob and "FMMU" in blob
            and "SyncManager" in blob)
        or ("0x88A4" in blob and "EtherCAT" in blob)
        or ("EtherCAT" in blob and "datagram" in blob.lower()))
