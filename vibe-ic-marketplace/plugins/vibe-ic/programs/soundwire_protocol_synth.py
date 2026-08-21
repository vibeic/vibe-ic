"""MIPI SoundWire-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol` /
`bus_interconnect_protocol` specs that exhibit the MIPI SoundWire
structural signature:
    (`SoundWire` + `Master` + `Slave`)
        OR (`SoundWire` + `Stream` + `Data Port`)
        OR (`MIPI` + `SoundWire` + `Frame Shape`)
        OR (`SoundWire` + `Clock` + `Data line`)

Applies MIPI SoundWire v1.0-spec-universal facts (the public Overview
Webinar of 21 January 2015 by Pierre Bossart of Intel for the MIPI LML
Working Group, summarizing the V09r04 voting draft of SoundWire v1.0
that was ratified by MIPI mid-February 2015). Sits as a sibling to
the I2S synth (audio interface family); shares no electrical layer
with I2S but the same audio-payload framing concerns (sample rate,
bit depth, channel count, source vs sink port direction).

Key facts the synth bakes into the 24 L docs:
  * Two-pin DDR multi-drop bus: SoundWire_Clock + SoundWire_Data (Lane 0)
    plus optional Data Lanes 1..7.
  * Modified-NRZI encoding: Logic 1 = active level change; Logic 0 =
    passive unchanged level held by a mandatory bus-keeper.
  * Up to 11 Slaves per Master; up to 14 Data Ports per Slave; up to 8
    channels per Port; ~96 Slave-Ports system-wide.
  * Frame Shape configurable: Cols ∈ {2,4,6,8,10,12,14,16}; Rows ∈
    valid subset of [48, 256]; Control Word occupies the first 48 rows
    of Column 0 of every Frame.
  * 48-bit Control Word: PREQ + 8+1-bit Static Sync + 4-bit Dynamic
    Sync (CRC pattern, 15-frame period) + PING / READ / WRITE opcode
    + per-Slave status (Not Attached / Attached / Alert) + 16-bit
    register address + 8-bit payload + Command Status (ACK / NAK /
    Command_Ignored) + Parity bit.
  * Bulk Register Access (BRA / BTP) on DataPort 0 (~20 Mbit/s).
  * 48-bit hard-coded Slave enumeration value (spec version + UniqueID
    + MIPI ManufacturerID + PartID + Class) in 6 SCP_Device0..5
    registers; hardware arbitration at Device 0 favors highest value.
  * Max bus Clock 13 MHz typical; natural audio frequencies 9.6 / 12 /
    12.288 MHz.
  * Three device classes: Master, Slave, Monitor (test equipment with
    BREQ/BREL Command Word arbitration).
  * ClockStop Mode 0 mandatory (context retained); Mode 1 optional
    (context may be lost; re-enumeration on wake; e.g. jack detection).
  * Wake-Up High pulse on Data for ≥ 2× minimum BitSlot duration.
  * Channel Prepare CP_SM + ClockStopPrepare CSP_SM normative state
    machines for safe activation / deactivation.
  * Transport modes Isochronous (Normal) + Asynchronous (TX-controlled
    / RX-Controlled / Full-Async) with 2-bit RX-Ready/TX-Ready preamble.
  * Block-Per-Port vs Block-Per-Channel transport; Sub_Block_Offset
    enables 'holes' reclaimable by other streams.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI R46/R48/R50/R52, SPI R53/R54/R55, I2C R56/R57/R58,
UART, CAN, USB, I2S, I3C detectors). Any MIPI SoundWire variant
exhibits the same signature.

Public entry: `apply_soundwire_synth(generated_docs_dir, is_soundwire,
soundwire_ic_name)`.
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


def apply_soundwire_synth(generated_docs_dir: Path, is_soundwire: bool,
                          soundwire_ic_name: Optional[str]) -> None:
    """Apply MIPI SoundWire-specific synth when the structural signature matched."""
    if not is_soundwire:
        return
    gd = generated_docs_dir

    # ------------------------------------------------------------------
    # ic_name across the main 14 L docs (top-level for L1-L23 + L8_timing)
    # ------------------------------------------------------------------
    if soundwire_ic_name is not None:
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
                d["ic_name"] = soundwire_ic_name
                _write(q, d)
        # L14-L23 keep ic_name under fields
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
                f["ic_name"] = soundwire_ic_name
                d["fields"] = f
                _write(q, d)

    _apply_l1(gd)
    _apply_l2(gd)
    _apply_l3(gd)
    _apply_l4(gd)
    _apply_l5(gd)
    _apply_l6(gd)
    _apply_l7(gd)
    _apply_l8_rtl(gd)
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


# ----------------------------------------------------------------------
# L1 datasheet metadata
# ----------------------------------------------------------------------
def _apply_l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_number"] = (
        "MIPI SoundWire Overview Webinar (2015) — public summary of "
        "MIPI SoundWire v1.0")
    d["document_title"] = (
        "MIPI SoundWire Overview Webinar — A Comprehensive Audio "
        "Interface for Mobile and Mobile-Influenced Devices")
    d["version"] = (
        "Public Overview (V09r04 entered 30-day final Voting Draft "
        "review; V1.0 ratification planned for mid-February 2015)")
    d["revised_date"] = "21 January 2015 (webinar date)"
    d["manufacturer"] = (
        "MIPI Alliance, Inc. — Low Speed Multipoint Link (LML) "
        "Working Group")
    d["copyright"] = (
        "© 2014-2015 MIPI Alliance, Inc. All rights reserved.")
    d["presenter"] = (
        "Pierre Bossart (Intel Corporation), MIPI LML WG Chair")
    d["external_pins"] = [
        "SoundWire_Clock", "SoundWire_Data (Lane 0)",
        "(optional) SoundWire_Data Lane 1..7",
    ]
    d["total_external_pin_count"] = (
        "2 (mandatory single-lane bus: Clock + Data) up to 9 (Clock + "
        "Data Lane 0..7 in multi-lane configurations); typical 2-pin "
        "dual-data-rate multi-drop bus")
    d["wire_protocol"] = (
        "Two-pin dual-data-rate (DDR) multi-drop bus for audio "
        "applications; bidirectional SoundWire_Data; Modified-NRZI "
        "encoding so multiple devices can drive the same BitSlot "
        "without drive conflicts; Logic 1 = active SDA change, Logic "
        "0 = passive unchanged level maintained by a bus-keeper")
    d.setdefault("key_features", [
        "Two-pin dual-data-rate (DDR) multi-drop bus for audio applications — operates at 1.2 V or 1.8 V supply rails.",
        "Robustness and Scalability — single Clock + multiple optional Data Lanes (Lane 0 mandatory; Lanes 1..7 optional, shared or private among device groups).",
        "Low power, low latency, well-bounded PHY and transport: max bus clock 13 MHz typical (audio-friendly natural frequencies 9.6 / 12 / 12.288 MHz; can be faster in single-Slave-close-to-Master configurations).",
        "Support for multiple Streams, formats (PCM, PDM, raw DATA), and modes (Isochronous, Asynchronous, Block).",
        "Embedded commands / control words — removes need for sideband I2C or SPI for register access.",
        "In-band interrupts / wakes; support for low-power jack detection (PREQ pin in Control Word + ClockStop wake mechanism).",
        "Up to 11 Slave Devices per Master on a multi-drop bus; up to 14 Data Ports per Slave; PDM, PCM, and bulk data carried with bit-level interleaving for low latency.",
        "Isochronous and Asynchronous modes; dynamic changes in bandwidth allocation without audio glitches.",
        "Reconfigurations through synchronized bank switch (bank 0 / bank 1 shadow register pairs).",
        "Interrupt capabilities with 32-frame maximum latency.",
        "Bulk Register Access / Bulk Transport Protocol (BRA / BTP) on dedicated DataPort0 (DP0) — up to 20 Mbit/s for fast device configuration / firmware download.",
        "Plug-and-Play discovery — Master enumerates Slaves via Ping + 48-bit hard-coded enumeration value (SoundWire spec version + UniqueID + MIPI ManufacturerID + PartID + Class) stored as 6 SCP_Device0-5 registers.",
        "Standardized MIPI register space (0x0-0xFFF normative ~50% used; 0x1000-0x17FF Device-class reserved; 0x2000-0xFFFF implementation-defined; 0x10000-0x3FFFFFFF paged implementation space).",
        "Each frame has a parity bit for bit-level error detection; Command Failed conditions on Parity Error / Bus Clash; Command_Ignored on Non-existent device / Device not attached / Reserved or unimplemented register.",
        "Power management: ClockStop (Mode 0 mandatory = context retained, Mode 1 optional = very-low-power, context lost, re-enumeration required); Slaves can enter low-power state.",
        "Concurrent multi-stream support: each Stream has its own Port set; stream aggregation across Slaves possible (Source/Sink ports may have different parameters as long as they share the same SampleInterval and bank-switch event).",
        "Three device types: Master, Slave, Monitor (test-equipment, snooping/analyzer mode most of the time; can temporarily take-over bus and issue read/write commands via BREQ/BREL Monitor arbitration).",
    ])
    d["modes_of_operation"] = [
        {"name": "Isochronous (Isoc) / Normal",  "rate_limit": "audio sample rate locked to SoundWire frame rate", "typical_use": "regular audio playback (e.g. 48 kHz PCM phase-locked to bus)"},
        {"name": "Asynchronous (Async)",          "rate_limit": "two-bit preamble per sample (RX-Ready, TX-Ready); data only transmitted when both ready", "typical_use": "44.1 kHz playback over 48 kHz link, bursty voice-call traffic, always-listening micro-phone wake"},
        {"name": "TX-controlled",                 "rate_limit": "RX-Ready=1 always; Source defines when TX-Ready is set", "typical_use": "Source-paced async (e.g. always-listening mic streaming on demand)"},
        {"name": "RX-Controlled",                 "rate_limit": "TX-Ready=1 always; Sink defines when RX-Ready is set", "typical_use": "Sink-paced async (e.g. DAC pulling samples on its own audio clock)"},
        {"name": "Full-Async",                    "rate_limit": "Both Source and Sink control rate", "typical_use": "Bridged streams with independent clocks"},
        {"name": "Bulk Transport Protocol (BTP/BRA)", "rate_limit": "DataPort0 carries header + payload up to 20 Mbit/s", "typical_use": "fast register block access; firmware download; rapid reconfiguration"},
        {"name": "Block-Per-Port",                "rate_limit": "all channels of a Port packed as one data chunk per Sample Interval, lowest to highest channel", "typical_use": "Simple multi-channel ports"},
        {"name": "Block-Per-Channel",             "rate_limit": "Channels transmitted in individual chunks; initial Block_Offset + inter-sample Sub_Block_Offset",  "typical_use": "Create 'holes' in bit allocation reclaimable by other streams (e.g. 48 kHz stereo same pattern as 96 kHz mono)"},
        {"name": "Normal PHY",                     "rate_limit": "up to 13 MHz bus clock typical", "typical_use": "Default; meets mandatory PHY parameters for general inter-chip distances"},
        {"name": "High-PHY",                       "rate_limit": "Beyond mandatory PHY timings",   "typical_use": "Requires system-level knowledge of integrated components; mode identification via one bit of static sync word; defined hand-over sequence between Normal and High-PHY"},
        {"name": "PHY Test Modes (Master)",        "rate_limit": "Normal / M_DataOff / M_ClockDataOff / M_AllOff / M_KeeperOff / M_LowLow / M_LowHigh", "typical_use": "Master pin configuration so external Master or test equipment can drive Data/Clock instead of the Master; supports replacement of master bus-keeper"},
    ]
    d.setdefault("system_use_cases", [
        "Mobile audio peripheral interface — Application Processor (Host) ↔ Audio Codec / Microphones / Speakers / Smart-Amplifiers",
        "Replaces / unifies legacy I2S + I2C / SPI sideband control + PDM microphones + SLIMbus + HDAudio on mobile and mobile-influenced platforms",
        "AP direct-attach topology: Application Processor Master directly drives multiple ADC/DAC Slaves",
        "Bridges and inter-chip link: Application Processor Master ↔ Bridge Slave (Master on far end) ↔ ADC/DAC Slaves",
        "Inter-chip link with multi-lane support: e.g. AP Master ↔ Audio Codec Slave with Lane[0]..Lane[2] separate Data; BT/FM Radio + DSP on additional lanes",
        "Functional partitioning: Application Processor with two Master instances driving disjoint Slave groups (e.g. one for input ADCs, one for output DACs)",
        "Routing / use-case partitioning: independent Master pairs each owning a separate Clock + Data tree for different audio use cases",
        "Always-listening / voice-trigger microphones with in-band wake (ClockStopMode1 removes need for separate GPIO for jack detection)",
        "Smart Amplifier with I/V sensing (Class-D feedback), Bluetooth/FM-Radio audio interface, DSP-to-DSP digital audio link",
    ])
    d.setdefault("benefits_vs_predecessors", [
        "New use cases not possible with existing interfaces (I2S, SLIMbus, HDAudio)",
        "New system topologies across mobile and mobile-influenced industries",
        "Lower gate count allows for integration in cost-sensitive devices",
        "vs I2S/TDM: lower pin count, clock scaling, dynamic slot mapping, burst mode, command embedded with data (no I2C/SPI needed), in-band interrupt capability (no GPIO), PDM support — at cost of slight command overhead and inability to switch Master/Slave roles for clock",
        "vs PDM: clock scaling, embedded command/control, interrupt capability — at cost of ~70 % overhead for dual-mic but less than 5 % for single-mic; lower power than PDM in multi-lane mode",
        "vs HDAudio: clock scaling, lower pin count, PDM support, scales to simple devices — at cost of lower-bandwidth device-class functionality not yet standardized in v1.0",
        "vs SLIMbus: lower gate count for integration in cost-sensitive devices, simpler protocol, low-latency PDM support, lower power with adjustable Frame size and double-data rate — at cost of no clock and manager hand-over capabilities (only Master and Monitor can send messages)",
    ])
    d.setdefault("overview",
        "MIPI SoundWire is a digital-audio multi-drop interface defined "
        "by the MIPI Alliance Low Speed Multipoint Link (LML) Working "
        "Group. It uses a single Clock line and one (or more) "
        "bidirectional Data lines to carry multiple concurrent audio "
        "Streams (PCM and PDM) plus embedded command and control words "
        "on the same bus — eliminating the need for separate I2C/SPI "
        "sideband control. Frame Shape is configurable (Columns "
        "2/4/6/8/10/12/14/16 by Rows 48..256), supporting from "
        "low-latency PDM microphones up to high-channel-count PCM "
        "smart-amplifier links. Reconfiguration is performed atomically "
        "via bank switching, allowing dynamic bandwidth re-allocation "
        "without audio glitches. Up to 11 Slave Devices share the bus "
        "with a single Master, with optional Monitor (test/analyzer) "
        "devices arbitrating with BREQ/BREL.")
    d.setdefault("release_history_note",
        "Initial public discussions June 2012; contributions from ~16 "
        "MIPI member companies; V09r04 entered 30-day final Voting "
        "Draft review at time of webinar (21 January 2015); MIPI "
        "SoundWire V1.0 ratification planned for mid-February 2015. "
        "MIPI Alliance Press Release: 09 Oct 2014 — 'MIPI Alliance "
        "Introduces MIPI SoundWire, a Comprehensive Audio Interface "
        "for Mobile and Mobile-Influenced Devices'.")
    d.setdefault("scope_in", [
        "Two-pin SoundWire physical layer (Clock + Data) plus optional Data Lanes 1..7",
        "Frame structure (configurable rows × columns matrix), Control Word format, sync pattern, parity",
        "Embedded command protocol: PING / READ / WRITE / Bulk Register Access",
        "Slave enumeration via 48-bit hard-coded enumeration value (Manufacturer ID + Part ID + Class + UniqueID + spec version)",
        "Data transport modes: Isochronous, Asynchronous (TX-controlled / RX-controlled / Full-Async), Block-Per-Port, Block-Per-Channel",
        "Multi-lane support (Lane 0..7) and shared / virtual PHY topologies",
        "ClockStop modes 0 (mandatory, context retained) and 1 (optional, low-power, re-enumeration on wake)",
        "Bus arbitration with optional Monitor (BREQ / BREL)",
        "Standardized MIPI register layout (normative 0x0-0xFFF) including SCP_*, DP*_*, banked registers for atomic reconfiguration",
    ])
    d.setdefault("scope_out", [
        "Audio codec internals (filters, gain stages, DACs, ADCs)",
        "MIPI Device Class register definitions (separate MIPI specifications)",
        "Driver / firmware stack architecture (left to OS / SoC vendors)",
        "PCB layout, EMC, and ESD design rules (implementation-specific)",
        "Specific jitter requirements in ppm/ps (overview slide notes 'No requirements on jitter (ppm, ps) in SoundWire spec' — quality is system-design concern)",
        "Mechanical / connector specifications",
        "Implementation-defined registers (0x2000-0xFFFF and 0x10000-0x3FFFFFFF paged space)",
    ])
    _write(p, d)


# ----------------------------------------------------------------------
# L2 FRS
# ----------------------------------------------------------------------
def _apply_l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    # Handle pre-existing None — setdefault returns None and we'd skip
    # subkey synth otherwise. The phase1 runner emits protocol_overview=None
    # + no_protocol_overview_in_input=True when its universal detector cannot
    # find a protocol-overview signature. The Tier-2 SoundWire detector fired
    # because the structural signature did match, so override to dict.
    if d.get("protocol_overview") in (None, "", []):
        d["protocol_overview"] = {}
        d["no_protocol_overview_in_input"] = False
    po = d["protocol_overview"]
    if isinstance(po, dict):
        po["wires"] = 2
        po["wire_names"] = ["SoundWire_Clock", "SoundWire_Data"]
        po["bidirectional_data"] = True
        po["synchronous"] = True
        po["serial"] = True
        po["multi_drop"] = True
        po["ddr_transmission"] = True
        po["frame_based"] = True
        po["frame_shape_configurable"] = True
        po["rows_range"] = [48, 256]
        po["cols_set"] = [2, 4, 6, 8, 10, 12, 14, 16]
        po["max_slaves_per_master"] = 11
        po["max_data_ports_per_slave"] = 14
        po["max_channels_per_port"] = 8
        po["max_data_lanes"] = 8
        po["max_bus_clock_typ_MHz"] = 13
        po["natural_clock_MHz_set"] = [9.6, 12.0, 12.288]
        po["modified_nrzi_encoding"] = True
        po["bus_keeper_required"] = True
        po["supply_voltage_V_set"] = [1.2, 1.8]
    fr = [
        {"id": "FR-PHY-01",   "text": "SoundWire uses a dedicated SoundWire_Clock line driven Push-Pull by the Master and a bidirectional SoundWire_Data line shared among Master, Slaves and optional Monitor."},
        {"id": "FR-PHY-02",   "text": "Data is transmitted at dual-data-rate (DDR) — two BitSlots per Clock period — on falling and rising Clock edges."},
        {"id": "FR-PHY-03",   "text": "Bus levels are encoded using Modified-NRZI: Logic 1 = active change of the physical level; Logic 0 = passive unchanged level held by a bus-keeper. This removes drive conflicts when multiple devices may legally own the same BitSlot."},
        {"id": "FR-PHY-04",   "text": "Without a secondary clock edge to control handover between adjacent BitSlots, devices observe tDZ_Data_Max (worst-case latest time to become high-impedance) and tZD_Data_Min (worst-case earliest time to drive), with tDZ_Data_Max < tZD_Data_Min, and margin for devices detecting the clock edge at different times."},
        {"id": "FR-PHY-05",   "text": "Three data handover cases must be supported: (#1) high-Z → driving, (#2) driving → driving (different devices may legally drive two adjacent BitSlots), (#3) driving → high-Z."},
        {"id": "FR-PHY-06",   "text": "Even a device actively driving two adjacent BitSlots is required to momentarily tri-state between them; turn-off may be a self-timed event occurring before the clock edge that ends the BitSlot, governed by tOH_Data_Min."},
        {"id": "FR-PHY-07",   "text": "Maximum bus Clock frequency = 13 MHz for typical geometries; can be faster in specific settings (e.g. single Slave close to Master). Audio transport is most efficient with 'natural' clock frequencies — 9.6 MHz, 12 MHz, 12.288 MHz."},
        {"id": "FR-PHY-08",   "text": "Clock quality is constrained to meet PHY parameters; jitter is limited for best audio quality but the SoundWire spec sets no normative ppm or ps requirement on jitter — it is a system-design concern."},
        {"id": "FR-FRAME-09", "text": "Each Frame is a 2-D matrix with NumCols ∈ {2,4,6,8,10,12,14,16} and NumRows ∈ [48, 256] from a selected discrete set. Master defines the Frame Shape via the Control word; Slaves are required to handle pairwise combinations of Rows and Cols."},
        {"id": "FR-FRAME-10", "text": "Bits are transmitted serially in a fixed bitstream order traversing the 2-D frame; the bitstream view is column-major within each row, advancing row by row (figure of bitstream view in spec)."},
        {"id": "FR-FRAME-11", "text": "Control Word occupies the first 48 rows of Column 0 of each Frame. Remaining BitSlots carry payload (PCM, PDM, bulk, or raw data) and are partitioned into Transport Sub-Frames per Data Port."},
        {"id": "FR-CTRLWORD-12","text": "The 48-bit Control Word contains: PREQ (Interrupt/Wake signal), Synchronization (Static sync word = 8+1 bits to lock on frame boundaries + Dynamic sync = 4-bit CRC pattern with 15-frame period), PING command (Slave interrupt and status: Not Attached / Attached / Alert + multi-stream synchronization SSP bit + Bus arbitration with Monitor BREQ/BREL), Read/Write commands (16-bit address, 8-bit payload, addressable to single Slave / group of Slaves / broadcast), Command status, Parity check."},
        {"id": "FR-CTRLWORD-13","text": "Two-step synchronization: Static 8-bit sync word locks onto Frame boundaries; Dynamic 4-bit word (CRC pattern with 15-frame period) removes 'ghost' sync words."},
        {"id": "FR-PING-14",  "text": "PING command carries Slave status for up to 12 Slaves (Device 0-11): Not Attached (not present or operational), Attached (synchronized with Master and able to handle commands), Alert (synchronized and at least one Interrupt condition raised). It also carries the SSP (Synchronization Stream Position) bit for multi-stream synchronization and Monitor arbitration bits BREQ / BREL."},
        {"id": "FR-RW-15",    "text": "READ / WRITE commands have a 16-bit register address and an 8-bit payload. The Device field addresses a single Slave (Device 1..11), a group of Slaves (group address), or broadcast (Device 15 / 0xF). 8-bit payload per command limits per-command bandwidth and motivates Bulk Register Access (BRA) for longer transfers."},
        {"id": "FR-CMDSTAT-16","text": "Every command frame has a Command Status response from the addressed Slave(s): ACK (command executed), NAK (parity or bus clash detected — Command Failed), Command_Ignored (non-existent device, device not attached, reserved or not-implemented register)."},
        {"id": "FR-PARITY-17","text": "Each frame has a Parity bit set by Master or Monitor. Slaves shall set NAK bit and raise Interrupt condition on parity error. Parity is computed on the physical level read from the bus (not the value sent to the bus), so parity will also detect some bus conflicts. Parity calculation window: BitSlot0[44,1] in previous frame to BitSlot[44,0] in current frame; error may be reported with a 1-frame delay. Slaves do not compute parity until they have successfully synchronized to Master."},
        {"id": "FR-BRA-18",   "text": "Bulk Register Access (BRA) / Bulk Transport Protocol (BTP) uses a dedicated DataPort 0 (DP0) to access contiguous registers. Extends the command bandwidth limited by frame rate and 8-bit command payload; supports reconfigurations and firmware download up to ≈ 20 Mbit/s. Header defines command (e.g. block read / write / address); followed by raw data; CRC-protected. Notion of Initiator (typically Master, occasionally specialized Slave such as a debug tool) / Target(s) (Slaves). DP0 is bi-directional by nature, distinguishing it from DP1-DP14 which are single-direction."},
        {"id": "FR-ENUM-19",  "text": "Each Slave has a hard-coded 48-bit unique enumeration value comprising: SoundWire spec version (to handle future revisions), UniqueID (set by system integrator e.g. via pin-strapping, used when identical parts share the bus), MIPI ManufacturerID, PartID, and Class (not defined in v1.0). The 48 bits are stored as 6 SCP_Device0..SCP_Device5 registers, read by Master to identify Slave. Enumeration stops when a Slave has a non-zero Device Number."},
        {"id": "FR-STARTUP-20","text": "Slave startup sequence: (1) Slave determines Frame format without supervision; (2) verifies static and dynamic sync pattern for 16 frames; (3) drives PREQ and/or 'Attached' status bits for Device Number 0; (4) Master reads 48-bit enumeration value from Slave; (5) Master assigns a non-zero Device Number in [1, 11] to the Slave; (6) catch — multiple Slaves can report 'Attached' as Device 0 simultaneously, resolved by hardware arbitration (Slave with highest enumeration value wins; others back off); (7) Master must redo enumeration until no Slave reports Attached at Device 0."},
        {"id": "FR-RESET-21", "text": "Three reset levels: Hard-Reset (Power-on or implementation-defined reset; Bus Reset is Master driving 4096 Logic1 transitions; Device Reset is Master writing Reset bit in SCP_Ctrl); Soft Reset (Slave detects two sync errors, not necessarily successive). After reset: Interrupt masks disabled, Device Number lost, re-enumeration required. Hard/Soft Reset difference: Slave maintains Interrupt Status register to allow debug (sync-loss cause)."},
        {"id": "FR-REGSPACE-22","text": "Slave register space: normative 0x0000-0x0FFF (~50 % used); device-class reserved 0x1000-0x17FF; implementation-defined 0x2000-0xFFFF; additional 0x10000-0x3FFFFFFF accessible via paging registers. Register writes take effect at end of frame if command succeeded; no action if command failed."},
        {"id": "FR-BANKED-23","text": "Some registers are banked (bank 0 / bank 1 shadow). Software prepares next configuration in the 'shadow' bank; a software write to SCP_FrameCtrl0/1 switches the bank. All devices switch banks in a synchronized manner. Impact: Frame Shape changes, Channel activation/deactivation, BitSlot allocation changes."},
        {"id": "FR-INTRPT-24","text": "Interrupt Status stored in SCP_IntStat_1/2/3 registers (hierarchical representation with cascade), optimized for simple devices with up to 4 Ports. SCP_IntStat_1 covers Parity, Bus Clash, IntStat ImpDef1, Port 0-4 cascade, SCP2 cascade. SCP_IntStat_2 covers Ports 4-10 cascade + SCP3 cascade. SCP_IntStat_3 covers Ports 11-14 cascade. Each Port also has DPst_IntStat with Test Fail, Port Ready, ImpDef1..3."},
        {"id": "FR-TRANSPORT-25","text": "Sample Event = instant when data is captured/rendered — the word-clock / frame-sync periodic event per Slave-Port channel. Sample Interval = number of bits between successive Samples. Sample Interval value updates when Frame Shape or frequency changes; not necessarily a multiple of row size; not dependent on number of channels."},
        {"id": "FR-TRANSPORT-26","text": "Transport Sub-Frame is the vertical partition of the Frame allocated to a Data Port; defined by registers HStart, HStop, with notional HWidth = HStop - HStart. Audio data does not need to be placed in a specific location within Sample Interval; bit allocation can change dynamically without impact on capture/rendering."},
        {"id": "FR-TRANSPORT-27","text": "Payload Data Window = intersection between Transport Sub-Frame and Payload Data Windows (defined by Sample Interval and Transport Sub-Frame). Payload Data Windows may be shared between similar streams."},
        {"id": "FR-TRANSPORT-28","text": "Block-Per-Port mode: all channels packed as a single data chunk per Sample Interval, lowest to highest-numbered channel; BlockOffset from start of Payload Data Window."},
        {"id": "FR-TRANSPORT-29","text": "Block-Per-Channel mode: channels transmitted in individual chunks within the same Sample Interval; initial Block_Offset + inter-sample Sub_Block_Offset. Benefits: 'holes' in bit allocation reclaimable by other streams (e.g. 48 kHz stereo same pattern as 96 kHz mono). No impact on buffering or capture/rendering, only a transport-level capability."},
        {"id": "FR-TRANSPORT-30","text": "Simplifications: Full Data port implements Hstart, Hstop, SampleInterval, BlockOffset, SubBlockOffset; Simple Data port only needs SampleInterval and BlockOffset. Grouping: ability to group up to 4 successive samples to avoid 'vertical stripes' for PDM — required for PDM, optional for PCM."},
        {"id": "FR-MULTILANE-31","text": "Multi-lane support is completely optional. Lane 0 is shared between all devices (common control interface; Col 0 Rows 0..47 reserved for Command Word). Lanes 1..7 may be shared or private to a group of devices; for device-to-device lanes a bus-keeper must be enabled on one of the devices. No restrictions on Lane 1..7 — all bits including Col 0 can be used. Dynamic switching between lanes is possible for each Port."},
        {"id": "FR-SSP-32",   "text": "Transport Synchronization: SSP (Synchronization Stream Position) bit in PING frame driven at regular intervals — used to maintain alignment between multiple links with different frame rates and between Ports using different sampling rates on the same link. Typically large enough to be multiple of all sample intervals; driven at least once every 100 ms; linked with Sample Events. Used by Slaves to reset SampleInterval counters and resync transport if needed. Defines 'safe' time position for bus reconfiguration (Frame Shape changes, channel/port enablement) and can be used to maintain phase coherence between devices."},
        {"id": "FR-PORT-33",  "text": "Ports are defined as Source (generate data on bus) or Sink (retrieve data from bus). Isochronous 'Normal' mode for regular audio playback. Asynchronous modes use a two-bit preamble per sample (RX-Ready, TX-Ready); data only transmitted when both RX-Ready and TX-Ready are set."},
        {"id": "FR-PORTFSM-34","text": "Two concepts per Port: Prepare (make sure Slave is ready to render/capture) and Activate (transport data on bus). Prepare state machine CP_SM: Stopped (NF=0, P=0) → Preparing (NF=1, P=1) → Ready (NF=0, P=1) → De-preparing (NF=1, P=0) → Stopped. Software can unmask an interrupt to be notified when ready. Port can be ready immediately (simplified CP_SM = single Ready state) or require time to be ready. Activate might be configured at any time but audio might not be valid; activation typically done with bank switch to avoid bus conflicts between streams."},
        {"id": "FR-TESTMODES-35","text": "Transport test modes mandatory in each Port: Static0 (helps detect Bus Clash Errors when another port drives in same BitSlots), Static1 (helps generate Bus Clash Errors), PRBS (helps detect data integrity — 8-bit LFSR generates 255-bit maximal length sequence; different structure and init value for TX and RX; receiver synchronizes in up to 8 bits; interrupt can be generated on error)."},
        {"id": "FR-CLOCKSTOP-36","text": "Clock can be paused: 'ClockStopNow' Command followed by 'Stopping Frame' to let Master drive clock and data to Low. ClockStopMode0 (mandatory) — Slave keeps context and restarts immediately; ClockStopMode1 (optional) — Slave may lose context, enter very-low-power mode and require re-enumeration on startup (e.g. for jack detection). ClockStopMode1 removes need for extra GPIO."},
        {"id": "FR-CLOCKSTOP-37","text": "Wake-ups can be master- or Slave-initiated. Master can program which Slaves can wake-up the bus. Wake-Up High for ≥ 2× minimum BitSlot duration before resuming clock and payload."},
        {"id": "FR-CLOCKSTOPPREP-38","text": "ClockStopPrepare uses the same Prepare/Activate state machine concept as Channel Prepare/Activate. CSP_SM: NotReady → Preparing → Ready → De-preparing. Slave may need time to enable an alternate clock source or be ready immediately (simplified CSP_SM = single Ready state)."},
        {"id": "FR-MONITOR-39","text": "Monitor is test equipment, in snooping/analyzer mode most of the time. Can temporarily take over bus and issue read/write commands. Arbitration: BREQ=0 → Master owns Command Word; BREQ=1 → Monitor requests Command Word ownership; BREL=1 → Master will yield Command Word ownership at end of frame. Monitor will keep Command Word ownership as long as BREQ=1 AND BREL=1. Master can reclaim ownership by clearing BREL. Master always drives static and dynamic bits. Master does not drive parity bit when Monitor owns bus, but it shall set NAK on parity error. BREQ=0, BREL=1 is illegal. Master is permitted to never release bus ownership (e.g. in a shipping device). If Monitor loses sync, command will default to PING with BREQ cleared and Master will reclaim ownership."},
        {"id": "FR-AGG-40",   "text": "Stream aggregation: No notion of 'link' between Source and Sink. No requirement that Source and Sink port are programmed with same parameters. Examples: 4 microphones push data on bus and Master retrieves a single 4-ch input; Master writes 2-ch data on 4 ports and Slave reads 8-ch data. Requirements: channels enabled on all Devices with common bank switch; Source ports and Sink ports have same SampleInterval; 'smart' bit allocation with no spacing between ports. Limitation: aggregation is not possible with Async modes (RX/TX-ready are per port)."},
    ]
    if _empty(d.get("functional_requirements")) or len(d.get("functional_requirements", [])) < 10:
        d["functional_requirements"] = fr
    d["error_response_conditions"] = [
        "Command Failed — Parity Error in current frame",
        "Command Failed — Bus Clash detected (two drivers contended in the same BitSlot)",
        "Command_Ignored — Non-existent device (programming error)",
        "Command_Ignored — Device not attached (lost sync or power)",
        "Command_Ignored — Register reserved or not implemented",
        "PHY definition leads to infrequent single-bit errors → command retransmitted or bus reset on persistent errors; payload not suppressed or retransmitted by the bus",
        "No checks for programming errors",
        "No check if value written to a register makes sense",
    ]
    d["wire_count"] = (
        "2 (SoundWire_Clock + SoundWire_Data Lane 0); up to 9 (Clock + "
        "Data Lanes 0..7) in optional multi-lane mode")
    d["compliance_requirements"] = [
        "Every Slave shall implement a 48-bit hard-coded enumeration value (SoundWire spec version + UniqueID + MIPI ManufacturerID + PartID + Class) stored as 6 SCP_Device0..5 registers.",
        "Every Slave shall verify both static and dynamic sync patterns for 16 consecutive frames before reporting Attached.",
        "Every Slave shall raise the NAK bit and an Interrupt condition on parity error.",
        "Slaves shall not compute parity until they have successfully synchronized to Master.",
        "Every device shall implement HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset for full Data Ports (SampleInterval + BlockOffset only for Simple Data Ports).",
        "Each Port shall mandatorily support transport test modes Static0, Static1 and PRBS for compliance.",
        "Every Slave shall support ClockStopMode0 (context retained) as the mandatory low-power mode; ClockStopMode1 is optional.",
        "Multi-drop: up to 11 Slave Devices per Master; up to 14 Data Ports per Slave; up to 8 channels per Port.",
        "Frame Shape — Slaves are required to handle pairwise combinations of valid Rows and Cols (cols ∈ {2,4,6,8,10,12,14,16}; rows ∈ valid subset of [48, 256]). Master will typically only use a few combinations with rows and columns scaled by 2^N factors.",
        "Max bus Clock frequency 13 MHz typical; faster only in restricted geometries.",
        "Audio transport efficient at 'natural' clock frequencies 9.6 MHz / 12 MHz / 12.288 MHz.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 cmd protocol
# ----------------------------------------------------------------------
def _apply_l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Two-pin DDR multi-drop audio bus with Modified-NRZI encoding, "
        "configurable 2-D frame structure (rows × columns matrix) "
        "carrying both audio Payload and an embedded 48-bit Control "
        "Word in Column 0 Rows 0..47. Commands are embedded in the "
        "Control Word so no I2C/SPI sideband is required.")
    d["opcodes_summary"] = (
        "SoundWire's embedded command set is small: PING (Slave status "
        "/ multi-stream synchronization / Monitor arbitration), READ "
        "(16-bit address, 8-bit payload), WRITE (16-bit address, 8-bit "
        "payload), with Bulk Register Access (BRA / BTP) on DataPort 0 "
        "(DP0) for fast block transfers. Commands are address-able to "
        "a single Slave (Device 1..11), a group of Slaves (group "
        "address), or broadcast (Device 0xF).")
    d["channels"] = [
        {"name": "SoundWire_Clock", "direction": "master output (Push-Pull); shared across all Slaves on the bus", "description": "Provides the clock used by all Slaves and the Monitor (if any). Maximum frequency 13 MHz for typical geometries; can be faster in single-Slave-close-to-Master configurations; audio-friendly natural clock frequencies are 9.6 MHz, 12 MHz, 12.288 MHz. Clock can be paused via ClockStop command (Mode 0 mandatory, Mode 1 optional)."},
        {"name": "SoundWire_Data (Lane 0)", "direction": "bidirectional; multi-drop", "description": "DDR data line carrying two BitSlots per Clock period. Uses Modified-NRZI encoding so multiple devices can legally own the same BitSlot without drive conflicts. Logic 1 = active level change; Logic 0 = passive unchanged level held by a bus-keeper. Bus-keeper is mandatory; M_KeeperOff PHY Test Mode can switch it off."},
        {"name": "SoundWire_Data Lane 1..7 (optional)", "direction": "bidirectional; multi-drop or device-to-device", "description": "Optional additional data lanes for higher aggregate bandwidth. Lanes 1..7 may be shared among all devices or private to a group; for device-to-device lanes a bus-keeper must be enabled on one of the devices. No restriction on Col 0 — all BitSlots on Lanes 1..7 can carry payload."},
    ]
    d["valid_ready_handshake_rules"] = [
        "Isochronous (Normal) mode: data is transmitted every Sample Event without per-sample handshake; rate is fixed by Frame Shape + Frame Rate.",
        "Asynchronous mode: each sample is preceded by a 2-bit preamble RX-Ready, TX-Ready. Data is only transmitted when both RX-Ready = 1 AND TX-Ready = 1.",
        "TX-controlled mode: RX-Ready forced to 1; Source defines when TX-Ready is set (Source-paced).",
        "RX-Controlled mode: TX-Ready forced to 1; Sink defines when RX-Ready is set (Sink-paced).",
        "Full-Async: both Source and Sink independently control their Ready bits.",
        "At the command level the Master receives a per-frame ACK / NAK / Command_Ignored response from the addressed Slave in the next Control Word window.",
        "Bulk Register Access uses a header + CRC-protected payload on DP0, replacing the per-frame 8-bit payload limit of Read/Write commands.",
    ]
    d["burst_based"] = False
    d["frame_based"] = True
    d["byte_oriented_payload"] = (
        "8 bits per Read/Write payload; multi-byte transfers via "
        "consecutive frames or via BRA.")
    d["byte_order"] = (
        "MSb-first within the Control Word and BRA Header; payload "
        "byte ordering follows MIPI register-map definition.")
    d["transaction_framing"] = {
        "frame_unit":          "Configurable 2-D matrix NumCols × NumRows (Cols ∈ {2,4,6,8,10,12,14,16}; Rows ∈ [48, 256] from selected discrete set).",
        "frame_clock":         "Frame Rate (typical 48 kHz) = bus Clock frequency / (NumRows × NumCols / 2). For example 9.6 MHz Clock with 50 × 8 cols × 1 row = 48 kHz frame rate.",
        "control_word_position": "First 48 rows of Column 0 of each Frame; 48 bits total — PREQ + 8+1-bit static sync + 4-bit dynamic sync + PING / Read / Write opcode field + per-command fields (Device address, register address, payload) + Command Status (NAK/ACK) + Parity bit.",
        "static_sync_word":    "8 bits (plus 1 mode-identification bit used to indicate Normal vs High-PHY mode) — used by Slaves to lock onto Frame boundaries; verified for 16 consecutive frames before declaring Attached.",
        "dynamic_sync":        "4-bit CRC pattern with 15-frame period — removes 'ghost' sync word matches and increases robustness against false synchronization.",
        "parity":              "Single bit per frame; computed on the physical level read from the bus; window = BitSlot[44,1] of previous frame to BitSlot[44,0] of current frame; may be reported with a 1-frame delay.",
        "stopping_frame":      "Special frame after ClockStopNow command; Master owns all BitSlots and drives Clock and Data Low to enter ClockStop. Wake-Up High for ≥ 2× minimum BitSlot duration on Data line resumes the clock and payload.",
    }
    d["control_word_48bit_layout"] = {
        "ping_command_fields": [
            "PREQ — Interrupt / Wake signal (Slave indicates wake / interrupt condition).",
            "Static Sync Word (8 + 1 bits) — Frame boundary lock + Normal vs High-PHY mode bit.",
            "Status of Devices 0..11 — three-state per Slave: Not Attached, Attached, Alert (at least one Interrupt condition raised).",
            "SSP (Synchronization Stream Position) bit — multi-stream synchronization tick; driven at regular intervals; ≥ once every 100 ms.",
            "BREQ / BREL — Monitor arbitration bits (BREQ=1 → Monitor requests Command Word ownership; BREL=1 → Master will yield at end of frame).",
            "Dynamic Sync (4-bit) — CRC pattern with 15-frame period.",
            "Parity bit — single-bit error detection over Parity Calculation Window.",
        ],
        "read_command_fields": [
            "Static + Dynamic Sync (same as PING).",
            "Opcode = READ.",
            "Device address — Device 1..11 single Slave, group address, or 0xF broadcast.",
            "Register address — 16-bit (covers 0x0000-0xFFFF normative + implementation-defined; paging registers cover 0x10000-0x3FFFFFFF).",
            "Read Data payload — 8-bit register data returned by Slave on next frame.",
            "Command Status — ACK / NAK / Command_Ignored (NAK = Command Failed on parity error / bus clash; Command_Ignored = non-existent device / device not attached / reserved or not implemented).",
            "Parity bit.",
        ],
        "write_command_fields": [
            "Static + Dynamic Sync.",
            "Opcode = WRITE.",
            "Device address.",
            "Register address — 16-bit.",
            "Write Data payload — 8-bit register data driven by Master.",
            "Command Status — ACK / NAK / Command_Ignored.",
            "Parity bit. Register write takes effect at end of frame if command succeeded; no action if command failed.",
        ],
        "monitor_bus_arbitration": {
            "BREQ_0_BREL_X": "Master owns Command Word.",
            "BREQ_1_BREL_0": "Monitor requesting Command Word ownership; Master still owns.",
            "BREQ_1_BREL_1": "Monitor owns Command Word and may issue Read/Write commands; Master always drives static and dynamic bits; Master does not drive parity bit but sets NAK on parity error.",
            "BREQ_0_BREL_1": "Illegal sequence.",
        },
        "monitor_recovery": (
            "If Monitor loses sync, command will default to PING with "
            "BREQ cleared and Master will reclaim ownership."),
    }
    d["ping_status_per_slave"] = {
        "not_attached":  "Slave is not present or not operational on the bus.",
        "attached":      "Slave is synchronized with Master and able to handle commands; eligible to be addressed by Read/Write.",
        "alert":         "Slave is synchronized and at least one Interrupt condition is currently raised; Master must service via Read of SCP_IntStat_* registers.",
    }
    d["device_addressing"] = {
        "single_slave":  "Device 1..11 — addresses one specific Slave by its assigned Device Number.",
        "group":         "Group address — addresses a configured group of Slaves (group membership held in Slave registers).",
        "broadcast":     "Device 15 (0xF) — addresses all Slaves on the bus.",
        "device_0":      "Reserved for Slaves that have not yet been assigned a Device Number — used during enumeration.",
    }
    d["read_transaction_overview"] = [
        "1. Master drives Control Word in Column 0 Rows 0..47 of current Frame with Opcode = READ, Device address, 16-bit register address.",
        "2. Slave decodes Control Word during the same Frame; latches register address.",
        "3. In the next Frame, Slave returns 8-bit Read Data payload in the Control Word (in the assigned payload field) and sets Command Status = ACK (or Command_Ignored if register not implemented / device not attached).",
        "4. Parity bit covers the Parity Calculation Window (BitSlot[44,1] previous → BitSlot[44,0] current).",
        "5. If parity violated, Slave sets NAK and raises an Interrupt; Master may retransmit the command.",
    ]
    d["write_transaction_overview"] = [
        "1. Master drives Control Word with Opcode = WRITE, Device address, 16-bit register address, 8-bit write payload.",
        "2. Slave decodes Control Word; if command succeeded, register write takes effect at end of frame.",
        "3. Slave sets Command Status = ACK (or NAK on parity error / bus clash, Command_Ignored on non-existent device / device not attached / reserved or not implemented register) in the response field of next Frame.",
        "4. No action if Command Failed; payload not suppressed or retransmitted at bus level.",
    ]
    d["ping_transaction_overview"] = [
        "1. Master drives Control Word with Opcode = PING.",
        "2. Slaves drive their per-Slave status (Not Attached / Attached / Alert) into the assigned status bits of the same Frame.",
        "3. Master drives SSP at regular intervals (≥ once every 100 ms) for multi-stream synchronization and reconfiguration safe-point.",
        "4. Monitor (if present) drives BREQ / BREL to arbitrate Command Word ownership.",
    ]
    d["bra_transaction_overview"] = [
        "Bulk Register Access (BRA) / Bulk Transport Protocol (BTP) uses dedicated DataPort 0 (DP0) instead of the per-frame 8-bit Read/Write payload.",
        "Header defines command (block-read / block-write, base register address, count); payload is raw register data; CRC-protected.",
        "Notion of Initiator (typically Master, occasionally specialized Slave such as a debug tool acting as Initiator) and Target(s) (Slaves).",
        "DP0 is bi-directional by nature — unlike DP1-DP14 which are single-direction.",
        "Approximate bandwidth up to 20 Mbit/s; suitable for fast device configuration, firmware download, large reconfiguration.",
    ]
    d["audio_data_transport_overview"] = [
        "Audio payload (PCM, PDM, raw DATA) occupies the BitSlots not allocated to the Control Word, organized into per-Port Transport Sub-Frames (HStart, HStop) and per-stream Payload Data Windows (SampleInterval).",
        "Two transport block modes: Block-Per-Port (all channels packed lowest-to-highest into a single chunk per Sample Interval) and Block-Per-Channel (channels in individual chunks with Block_Offset / Sub_Block_Offset, enabling stream-aware packing such as 48 kHz stereo == 96 kHz mono).",
        "Grouping (up to 4 successive samples) is required for PDM to avoid 'vertical stripes'; optional for PCM.",
        "Stream aggregation: Source ports and Sink ports do not need to be programmed with the same parameters as long as they share the same SampleInterval and a common bank-switch event.",
    ]
    d["enumeration_sequence_overview"] = [
        "1. Master powers up the bus, programs Frame Shape, and starts the Clock.",
        "2. Slaves verify Static + Dynamic Sync patterns for 16 frames.",
        "3. Each Slave with Device Number 0 (un-enumerated) drives PREQ and/or its 'Attached' status bit for Device 0.",
        "4. Master reads the 6-byte 48-bit enumeration value from the Slave (SCP_Device0..SCP_Device5).",
        "5. Master assigns a non-zero Device Number in [1, 11] to that Slave.",
        "6. On bus conflict (multiple Slaves reporting Attached at Device 0 simultaneously), hardware arbitration: Slave with highest enumeration value wins; others back off.",
        "7. Master redoes enumeration until no Slave reports as Attached at Device 0.",
    ]
    d["reset_overview"] = [
        "Hard-Reset: Power-on or implementation-defined reset; Bus Reset = Master drives 4096 Logic1 transitions on Data line; Device Reset = Master writes Reset bit in SCP_Ctrl.",
        "Soft Reset: Slave detects two sync errors, not necessarily successive.",
        "Hard/Soft Reset difference: Slave maintains Interrupt Status register after Soft Reset to allow debug (look at sync-loss cause).",
        "After any reset: Interrupt masks disabled, Device Number lost (re-enumeration required).",
    ]
    d["clock_stop_overview"] = [
        "Master sends ClockStopNow command in the Control Word.",
        "Master then drives a Stopping Frame in which Master owns all BitSlots, ending the last bit of the Stopping Frame by parking Clock and Data Low.",
        "Slave enters ClockStopMode0 (context retained — mandatory) or ClockStopMode1 (context may be lost — optional; very-low-power, e.g. jack detection).",
        "Wake-up: master- or Slave-initiated; Slave drives Data line High for ≥ 2× minimum BitSlot duration to wake the bus; Master then resumes Clock and Frame N+1.",
        "Master can program which Slaves are allowed to wake-up the bus.",
        "ClockStopMode1 wake requires re-enumeration on startup.",
    ]
    d["phy_test_modes_master"] = {
        "header": ["Mode name", "Data bus-keeper", "Clock Output", "Data Output"],
        "rows": [
            ["Normal",         "x",          "x",         "x"],
            ["M_DataOff",      "x",          "x",         "Off/high-Z"],
            ["M_ClockDataOff", "x",          "Off/high-Z","Off/high-Z"],
            ["M_AllOff",       "Off/high-Z", "Off/high-Z","Off/high-Z"],
            ["M_KeeperOff",    "Off/high-Z", "x",         "x"],
            ["M_LowLow",       "x",          "Static Low","Static Low"],
            ["M_LowHigh",      "x",          "Static Low","Static High"],
        ],
        "note": (
            "'x' means functional in table. External master or test "
            "equipment can drive data and clock instead of master and "
            "replace the master bus-keeper."),
    }
    d["transport_test_modes_per_port"] = {
        "Static0": "Helps detect Bus Clash Errors — another port drives in the same BitSlots; mandatory in each Port.",
        "Static1": "Helps generate Bus Clash Errors deliberately; mandatory in each Port.",
        "PRBS":    "Helps detect data integrity. 8-bit LFSR generates a 255-bit maximal-length sequence. Different structure and init value for TX and RX. TX initial Q[8:1] = 0xFF. RX initial Q[8:1] = 0xD2. Receiver synchronizes in up to 8 bits. Interrupt can be generated on error.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 register map
# ----------------------------------------------------------------------
def _apply_l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = (
        "partial — public webinar describes the normative-register "
        "address ranges and the specific SCP_ / DPst_ register groups "
        "required for enumeration, control, and interrupt handling. "
        "Per-Slave bit-level field maps for every register are defined "
        "in the gated SoundWire v1.0 spec.")
    d["address_space_partitioning"] = [
        {"range_hex": "0x0000 - 0x0FFF", "type": "Normative",                 "usage": "MIPI-defined registers (~50 % used). Includes SCP_Device0..5 (enumeration), SCP_Ctrl, SCP_IntStat_1..3, SCP_IntClear_1, SCP_IntMask_1, SCP_FrameCtrl0/1 (bank switch), DPst_IntStat, DPst_IntClear, DPst_IntMask, per-Port HStart/HStop/SampleInterval/BlockOffset/SubBlockOffset, ClockStop control, ClockStopPrepare, etc."},
        {"range_hex": "0x1000 - 0x17FF", "type": "Device-class reserved",      "usage": "Reserved for MIPI Device Class definitions (e.g. audio codec class registers). Class definitions are 'not defined yet' at v1.0 release."},
        {"range_hex": "0x2000 - 0xFFFF", "type": "Implementation-defined",     "usage": "Vendor-specific registers (proprietary controls, vendor analog blocks, audio DSP coefficients, etc.)."},
        {"range_hex": "0x10000 - 0x3FFFFFFF", "type": "Implementation-defined (paged)", "usage": "Additional implementation-specific space accessible only via paging registers. Used by audio codecs with very large coefficient tables."},
    ]
    d["register_write_semantics"] = [
        "Register writes take effect at the end of the frame if the Read/Write command succeeded.",
        "No action is taken if the command failed (Parity / Bus Clash / Command_Ignored).",
        "Some registers are banked — software prepares next configuration in the 'shadow' bank; a software write to SCP_FrameCtrl0/1 switches banks; all devices switch banks in a synchronized manner. Impact: Frame Shape changes, channel activation/deactivation, BitSlot allocation changes.",
    ]
    d["named_register_groups_described_in_webinar"] = [
        {"group_name": "SCP_Device0 .. SCP_Device5",
         "purpose":    "6-byte storage of the 48-bit hard-coded Slave enumeration value (SoundWire spec version + UniqueID + MIPI ManufacturerID + PartID + Class). Read by Master to identify Slave during enumeration."},
        {"group_name": "SCP_Ctrl",
         "purpose":    "Slave Control Port primary control register; contains the Device Reset bit that the Master can write to perform a Device Reset (Hard-Reset level)."},
        {"group_name": "SCP_FrameCtrl0 / SCP_FrameCtrl1",
         "purpose":    "Banked Frame Control registers — Master writes to switch banks (next-configuration shadow bank becomes active). Drives synchronized bank switch across all devices."},
        {"group_name": "SCP_IntStat_1 (0x0040)",
         "purpose":    "Slave Control Port Interrupt Status register #1 — hierarchical with cascade. Bits cover Parity, Bus Clash, IntStat ImpDef1, Port 0 cascade, Port 1 cascade, Port 2 cascade, Port 3 cascade, SCP2 cascade."},
        {"group_name": "SCP_IntClear_1 (0x0040)",
         "purpose":    "Slave Control Port Interrupt Clear register #1 — clear-bits matching SCP_IntStat_1: IntClear Parity, IntClear Bus Clash, IntClear ImpDef1."},
        {"group_name": "SCP_IntMask_1 (0x0041)",
         "purpose":    "Slave Control Port Interrupt Mask register #1 — mask bits: IntMask Parity, IntMask Bus Clash, IntMask ImpDef1."},
        {"group_name": "SCP_IntStat_2 (0x0042)",
         "purpose":    "Slave Control Port Interrupt Status register #2 — Ports 4-10 cascade + SCP3 cascade."},
        {"group_name": "SCP_IntStat_3 (0x0043)",
         "purpose":    "Slave Control Port Interrupt Status register #3 — Ports 11-14 cascade."},
        {"group_name": "DPst_IntStat (+0x00 per Data Port)",
         "purpose":    "Per Data Port Interrupt Status register: Test Fail, Port Ready, IntStat ImpDef1, IntStat ImpDef2, IntStat ImpDef3."},
        {"group_name": "DPst_IntClear (+0x00 per Data Port)",
         "purpose":    "Per Data Port Interrupt Clear register: IntClear Test Fail, IntClear Port Ready, IntClear ImpDef1..3."},
        {"group_name": "DPst_IntMask (+0x01 per Data Port)",
         "purpose":    "Per Data Port Interrupt Mask register: IntMask Test Fail, IntMask Port Ready, IntMask ImpDef1..3."},
        {"group_name": "Per-Port Transport registers",
         "purpose":    "HStart, HStop (Transport Sub-Frame vertical bounds), SampleInterval, BlockOffset, SubBlockOffset, Block-Per-Port vs Block-Per-Channel mode, Source/Sink direction, channel count, sample bit-width."},
        {"group_name": "ClockStop control",
         "purpose":    "ClockStopNow command bit, ClockStopMode0 / ClockStopMode1 select, wake enable per-Slave bitmap."},
        {"group_name": "ClockStopPrepare (CSP_SM)",
         "purpose":    "ClockStopPrepare state-machine driver: NF (NotFinished), P (Prepare) bits; drive transition through NotReady → Preparing → Ready → De-preparing, supporting Slaves that need time to enable an alternate clock source."},
        {"group_name": "Channel Prepare (CP_SM)",
         "purpose":    "Per-channel Prepare state-machine: bits per channel c in DPX_PrepareCtrl (Prepare[c]) and DPX_PrepareStatus (NotFinished[c]); transition Stopped → Preparing → Ready → De-preparing → Stopped to gate channel activation."},
    ]
    d["interrupt_register_hierarchy_summary"] = {
        "level_1_scp_intstat_1": ["IntStat Parity", "IntStat Bus Clash", "IntStat ImpDef1", "Port 0 cascade", "Port 1 cascade", "Port 2 cascade", "Port 3 cascade", "SCP2 cascade"],
        "level_1_scp_intstat_2": ["Port 4 cascade", "Port 5 cascade", "Port 6 cascade", "Port 7 cascade", "Port 8 cascade", "Port 9 cascade", "Port 10 cascade", "SCP3 cascade"],
        "level_1_scp_intstat_3": ["Port 11 cascade", "Port 12 cascade", "Port 13 cascade", "Port 14 cascade", "—", "—", "—", "—"],
        "per_port_dpst_intstat": ["IntStat Test Fail", "IntStat Port Ready", "—", "—", "—", "IntStat ImpDef1", "IntStat ImpDef2", "IntStat ImpDef3"],
        "design_intent": "Optimized for simple devices with up to 4 ports — cascade scheme limits register count while supporting up to 14 ports.",
    }
    d["registers_left_to_implementation_or_class_spec"] = [
        "Per-codec analog block controls (PGA, microphone bias, DAC gain) → vendor implementation-defined 0x2000-0xFFFF or future MIPI Device Class.",
        "MIPI Device Class register definitions in 0x1000-0x17FF (not defined in SoundWire v1.0 spec base).",
        "Stream parameter detailed bit-level layout (sample rate, bit-depth, channel count, port direction) — visible only in full SoundWire v1.0 spec.",
        "Slave-specific identifiers in PartID and ManufacturerID — assigned per MIPI Manufacturer ID page.",
    ]
    d["soc_dependent_registers"] = (
        "Concrete SoundWire Master IP blocks expose their own register "
        "file (TX/RX FIFO, transport-layer DMA, status, interrupt "
        "enable, bus-management state, BRA engine, etc.) — these are "
        "defined by individual controller block guides, not by the "
        "SoundWire v1.0 spec.")
    _write(p, d)


# ----------------------------------------------------------------------
# L5 ADI / signaling
# ----------------------------------------------------------------------
def _apply_l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = False
    d["signaling_summary"] = (
        "Pure-digital two-pin DDR bus with carefully-specified analog "
        "DC and AC characteristics. Supply rails are 1.2 V or 1.8 V. "
        "The Modified-NRZI encoding requires a bus-keeper on "
        "SoundWire_Data — a weak active driver that maintains the "
        "last driven level when no device is actively driving — so "
        "Logic 0 (passive unchanged level) can be reliably "
        "distinguished from a floating bus. SoundWire_Clock is "
        "Push-Pull from the Master with no inversion; SoundWire_Data "
        "is bidirectional and dynamically shared. Maximum bus Clock "
        "13 MHz typical (faster in restricted geometries); "
        "audio-friendly natural Clock frequencies 9.6 MHz, 12 MHz, "
        "12.288 MHz. Clock quality is constrained to meet PHY "
        "parameters; jitter is limited for best audio quality but the "
        "SoundWire spec sets no normative ppm or ps requirement on "
        "jitter — it is a system-design and differentiating concern. "
        "Three data handover cases (high-Z→driving, driving→driving "
        "across two devices, driving→high-Z) are governed by "
        "tDZ_Data_Max < tZD_Data_Min with margin for devices "
        "detecting the clock edge at different times; even a device "
        "that drives two adjacent BitSlots is required to momentarily "
        "tri-state between them, with optional self-timed turn-off "
        "bounded by tOH_Data_Min.")
    d["key_analog_parameters"] = {
        "supply_V_set": [1.2, 1.8],
        "max_bus_clock_typ_MHz": 13.0,
        "natural_clock_MHz_set": [9.6, 12.0, 12.288],
        "encoding": "Modified-NRZI (Logic 1 = active change; Logic 0 = passive unchanged level, held by bus-keeper)",
        "bus_keeper_required": True,
        "ddr": True,
        "data_handover_cases": [
            "high-Z to driving",
            "driving to driving (different drivers)",
            "driving to high-Z",
        ],
        "key_phy_timing_params": [
            "tDZ_Data_Max (worst-case latest time to high-Z)",
            "tZD_Data_Min (worst-case earliest time to drive)",
            "tOH_Data_Min (self-timed turn-off; valid signal duration so bus-keeper snaps to new value)",
            "tOV_Data_Max",
            "V_OH_Data_Min",
            "V_OL_Data_Max",
            "V_TP_Clock_Min/Max",
            "V_TN_Clock_Min/Max",
        ],
        "voltage_thresholds": (
            "Implementation-specific — webinar only presents "
            "qualitative diagram (V_OH_Data_Min and V_OL_Data_Max "
            "thresholds; clock V_TP / V_TN thresholds); detailed "
            "numeric values pinned only in the gated SoundWire v1.0 "
            "spec."),
    }
    d["high_phy_mechanism"] = {
        "purpose":         "Mechanism to go beyond mandatory PHY timings.",
        "requires":        "System-level knowledge on integrated components — all components on the High-PHY link need to support the same requirements.",
        "handover":        "Defined hand-over sequence between 'normal' and 'high-PHY' mode.",
        "mode_identification": "Uses one bit of the static sync word to identify Normal vs High-PHY mode.",
    }
    d["shared_and_virtual_phy"] = {
        "shared_phy":  "Module-level integration where pins are shared — Master Digital Interface plus one or more Slave Digital Interfaces feed a single shared PHY block providing the external Clock/Data pads.",
        "virtual_phy": "Pins are NOT visible externally — SoundWire used inside a module; an OR-gate / clock-doubler virtual PHY provides the bus to internal digital interfaces. Used when SoundWire is purely intra-module signalling.",
    }
    d.setdefault("notes",
        "MIPI SoundWire is a digital interface, not an analog block; "
        "this layer documents the PHY-level signalling rules (DDR, "
        "Modified-NRZI, bus-keeper, data handover) that any compliant "
        "Master/Slave/Monitor must respect. Public webinar does not "
        "give numeric V_TP / V_TN thresholds — those live in the "
        "gated v1.0 specification.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 control logic FSM
# ----------------------------------------------------------------------
def _apply_l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_overview"] = (
        "SoundWire defines several normative state machines: (a) "
        "Master/Slave bus lifecycle (Power-up → Sync acquisition → "
        "Enumeration → Operating → ClockStop/Wake), (b) Channel "
        "Prepare CP_SM per channel per Port for safe "
        "activation/deactivation of data streams, (c) "
        "ClockStopPrepare CSP_SM for orderly entry into ClockStop "
        "modes 0 and 1, (d) Monitor arbitration over BREQ/BREL bits, "
        "and (e) Enumeration arbitration when multiple Slaves contend "
        "at Device 0.")
    d["fsm_states"] = [
        {"name": "POWER_OFF",          "description": "Bus and devices powered down. SoundWire_Clock and SoundWire_Data both Low (parked) or floating depending on PHY state."},
        {"name": "POWER_UP",           "description": "Master applies power, programs initial Frame Shape registers, and begins driving SoundWire_Clock at the selected natural clock frequency (9.6 / 12 / 12.288 MHz)."},
        {"name": "SYNC_ACQUIRE",       "description": "Slaves search for the 8+1-bit Static Sync Word in Column 0 of incoming Frames. Slave verifies both Static and Dynamic sync patterns for 16 consecutive frames before declaring sync."},
        {"name": "DEV0_REPORT",        "description": "Un-enumerated Slave (Device Number 0) drives PREQ and/or the 'Attached' status bit at the Device 0 position in the PING Control Word."},
        {"name": "ENUM_READ48",        "description": "Master reads the 6-byte 48-bit enumeration value (SCP_Device0..5) from the responding Slave via READ commands."},
        {"name": "ENUM_ASSIGN_DEVNUM", "description": "Master assigns a non-zero Device Number in [1, 11] via a WRITE command to the appropriate Slave register; Slave latches its new Device Number."},
        {"name": "ENUM_ARBITRATE",     "description": "If multiple Slaves report Attached at Device 0 simultaneously, hardware arbitration over the Modified-NRZI bus resolves: Slave with highest enumeration value wins; others back off. Master must redo enumeration until no Slave reports as Attached at Device 0."},
        {"name": "OPERATING",          "description": "Bus is in steady-state: Master issues PING / READ / WRITE Control Words every Frame; Slaves drive their per-Slave status; audio Payload flows in non-Control BitSlots according to programmed HStart/HStop/SampleInterval/BlockOffset/SubBlockOffset; Monitor (if present) may arbitrate via BREQ/BREL."},
        {"name": "BANK_SWITCH",        "description": "Master writes SCP_FrameCtrl0/1 to switch banks; all devices switch banks in a synchronized manner at the next SSP event for safe reconfiguration (Frame Shape changes, channel activation/deactivation, BitSlot allocation changes)."},
        {"name": "CLOCKSTOP_REQ",      "description": "Master issues a 'ClockStopNow' command in the Control Word, followed by a Stopping Frame in which Master owns all BitSlots and drives Clock and Data Low."},
        {"name": "CLOCKSTOP_MODE0",    "description": "Slave retains its context (registers, programmed transport, Device Number). Clock is paused. Slave can resume immediately when Master re-applies clock. Mandatory mode."},
        {"name": "CLOCKSTOP_MODE1",    "description": "Slave may lose context, enters very-low-power mode. Re-enumeration is required on wake. Optional mode; used for e.g. jack-detection with no extra GPIO."},
        {"name": "WAKE_SLAVE",         "description": "Slave drives SoundWire_Data High for ≥ 2× minimum BitSlot duration to request wake-up; Master detects and resumes clock."},
        {"name": "WAKE_MASTER",        "description": "Master autonomously resumes Clock and Frame N+1 to wake the bus."},
        {"name": "SOFT_RESET",         "description": "Slave detects two sync errors (not necessarily successive) → soft-reset: Device Number lost, Interrupt masks disabled, but Interrupt Status register maintained so debug can determine sync-loss cause."},
        {"name": "HARD_RESET",         "description": "Power-on or implementation-defined reset. Bus Reset = Master drives 4096 Logic1 transitions; Device Reset = Master writes Reset bit in SCP_Ctrl. Device Number lost, re-enumeration required."},
        {"name": "MONITOR_REQUEST",    "description": "Optional Monitor sets BREQ=1 in the Control Word; Master may yield by setting BREL=1; Monitor owns Command Word while BREQ=1 AND BREL=1; Master can reclaim by clearing BREL. Master always drives static and dynamic bits and parity (Master does not drive parity bit when Monitor owns bus, but sets NAK on parity error)."},
    ]
    d["channel_prepare_state_machine_cp_sm"] = {
        "purpose": "Make sure a Slave channel of a Port is ready to render/capture before audio data is transported.",
        "register_bits": {"P": "Value read from Prepare[c] in DPX_PrepareCtrl", "NF": "Value read from NotFinished[c] in DPX_PrepareStatus"},
        "states": [
            {"name": "Stopped",     "encoding": "NF=0, P=0", "outgoing": "Prepare1 ↔ Preparing"},
            {"name": "Preparing",   "encoding": "NF=1, P=1", "outgoing": "Prepare1 AND NOT PrepareFinished → Preparing; Prepare1 AND PrepareFinished → Ready; Prepare0 → De-preparing"},
            {"name": "Ready",       "encoding": "NF=0, P=1", "outgoing": "Prepare0 → De-preparing"},
            {"name": "De-preparing","encoding": "NF=1, P=0", "outgoing": "Prepare0 AND De-prepareFinished → Stopped; Prepare0 AND NOT De-prepareFinished → De-preparing; Prepare1 → Preparing"},
        ],
        "simplified_form": "Single 'Ready' state with NF=0, P=1; Prepare0 OR Prepare1 self-loop — for Ports that can be ready immediately.",
        "activation_rule": "Activate (data transport on bus) might be configured at any time but audio might not be valid. Activation typically done with bank switch to avoid bus conflicts between streams.",
        "software_assist": "Software can unmask an interrupt to be notified when the channel reaches Ready.",
    }
    d["clockstop_prepare_state_machine_csp_sm"] = {
        "purpose": "Support clean stopping of the bus clock for ClockStop entry; analogous to Channel Prepare/Activate.",
        "states": [
            {"name": "NotReady",    "encoding": "NF=0, P=0", "outgoing": "Prepare1 → Preparing"},
            {"name": "Preparing",   "encoding": "NF=1, P=1", "outgoing": "Prepare1 AND NOT PrepareFinished → Preparing; Prepare1 AND PrepareFinished → Ready; Prepare0 → De-preparing"},
            {"name": "Ready",       "encoding": "NF=0, P=1", "outgoing": "Prepare0 → De-preparing"},
            {"name": "De-preparing","encoding": "NF=1, P=0", "outgoing": "Prepare0 AND De-prepareFinished → NotReady; Prepare0 AND NOT De-prepareFinished → De-preparing; Prepare1 → Preparing"},
        ],
        "simplified_form": "Single 'Ready' state — for Slaves that can stop immediately without enabling an alternate clock source.",
        "rationale": "Slave may need time to enable an alternate clock source (so internal state can persist while SoundWire_Clock is off) or be ready immediately.",
    }
    d["fsm_hints"] = {
        "trigger":              "Master drives SoundWire_Clock and Control Word in Column 0 Rows 0..47. Slaves react to PING / READ / WRITE Control Words and to the synchronized bank switch via SCP_FrameCtrl0/1.",
        "rule":                 "All bus events are aligned to Frame boundaries and the periodic SSP event; safe reconfiguration windows are SSP ticks (driven ≥ once every 100 ms).",
        "no_slave_clock_drive": "Slaves NEVER drive SoundWire_Clock.",
    }
    d["anti_deadlock_rule"] = (
        "Modified-NRZI encoding allows multiple devices to legally "
        "own the same BitSlot without drive conflicts because Logic 0 "
        "is a passive unchanged level held by the bus-keeper. "
        "tDZ_Data_Max < tZD_Data_Min guarantees the previous driver "
        "releases before the next driver asserts. Monitor BREQ/BREL "
        "handshake guarantees that exactly one of Master/Monitor owns "
        "the Command Word at any moment (BREQ=0,BREL=1 is explicitly "
        "illegal).")
    d["exit_from_reset"] = (
        "After Hard-Reset (Power-On or Device Reset via SCP_Ctrl), "
        "every Slave is at Device Number 0 with Interrupt masks "
        "disabled. Slave must reacquire sync (16-frame static + "
        "dynamic verification) before reporting 'Attached'. Master "
        "then performs enumeration by reading 6-byte SCP_Device0..5 "
        "and assigning a Device Number 1..11.")
    d["default_ready_state_recommendation"] = {
        "clock_idle":            "Stopped (parked Low) during ClockStop; otherwise active at programmed natural Clock frequency.",
        "data_idle":             "Bus-keeper-held last value; never tri-stated for more than tDZ_Data_Max within an active BitSlot transition.",
        "frame_alignment":       "All Slaves and Monitor align to Frame N at the Static Sync Word boundary; SSP defines safe reconfiguration tick.",
    }
    d["channel_dependency_rules_master"] = {
        "note": "Master drives SoundWire_Clock continuously (except ClockStop), drives Control Word in Column 0 Rows 0..47 (PING / READ / WRITE), drives payload in BitSlots where the Master has been assigned a Source Port for that Frame, releases payload BitSlots assigned to Slave Source Ports, drives ClockStopNow + Stopping Frame for ClockStop entry.",
    }
    d["channel_dependency_rules_slave"] = {
        "note": "Slave samples SoundWire_Clock; decodes Control Word every Frame; drives its 'Attached'/'Alert' status bit in the PING response window; drives Read Data payload in next Frame after a READ command addressed to it; drives audio payload in its assigned Source Port BitSlots; never drives SoundWire_Clock; NF/P bits in DPX_PrepareCtrl/Status track channel readiness.",
    }
    d["arbitration_rule"] = (
        "Modified-NRZI on SoundWire_Data lets multiple devices share "
        "a BitSlot: Logic 1 wins (active edge) over Logic 0 (passive "
        "level held). Enumeration arbitration: Slave with the highest "
        "48-bit enumeration value wins when multiple un-enumerated "
        "Slaves contend at Device 0. Monitor arbitration via BREQ / "
        "BREL bits in the Control Word.")
    d["synchronization_rule"] = (
        "Single Master drives SoundWire_Clock — no clock-stretching "
        "or distributed clock generation. The Static 8+1-bit sync "
        "word + Dynamic 4-bit CRC sync (15-frame period) lock all "
        "Slaves to the Master's Frame boundary. The SSP bit driven in "
        "PING frames maintains alignment between multiple links with "
        "different frame rates and between Ports using different "
        "sampling rates on the same link, defines 'safe' time "
        "positions for bus reconfiguration, and can be used to "
        "maintain phase coherence between devices.")
    d["monitor_arbitration_rules"] = [
        "BREQ = 0 → Master owns Command Word.",
        "BREQ = 1 AND BREL = 0 → Monitor requests Command Word ownership; Master still owns.",
        "BREQ = 1 AND BREL = 1 → Monitor owns Command Word and may issue Read/Write commands.",
        "BREQ = 0 AND BREL = 1 → illegal sequence.",
        "Master always drives static and dynamic sync bits.",
        "Master does not drive parity bit when Monitor owns bus, but it shall set NAK on parity error.",
        "Master is permitted to never release bus ownership (e.g. in a shipping device).",
        "If Monitor loses sync, command will default to PING with BREQ cleared and Master will reclaim ownership.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L7 test/debug
# ----------------------------------------------------------------------
def _apply_l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = (
        "partial — the public webinar describes mandatory PHY Test "
        "Modes (Master pin configuration table), mandatory per-Port "
        "Transport Test Modes (Static0 / Static1 / PRBS), and the "
        "Monitor device class for snooping and bus injection. DFT "
        "scan / BIST / JTAG are not covered (they live at the SoC "
        "integration level).")
    d["spec_provided_observability"] = [
        {"name": "PING Slave Status",          "purpose": "Per-Slave three-state status (Not Attached / Attached / Alert) in every PING frame — coarse health check."},
        {"name": "Per-Slave Interrupt Status", "purpose": "Hierarchical SCP_IntStat_1/2/3 + per-Port DPst_IntStat capture Parity, Bus Clash, Port Ready, Test Fail, and ImpDef interrupt sources."},
        {"name": "Parity bit per Frame",       "purpose": "Single-bit error detection; computed on the physical level read from the bus; window = BitSlot[44,1] previous → BitSlot[44,0] current; reportable with a 1-frame delay."},
        {"name": "Command Status field",       "purpose": "Per-Read/Write response: ACK / NAK (Command Failed) / Command_Ignored (non-existent / not attached / reserved register)."},
        {"name": "SSP (Synchronization Stream Position)", "purpose": "Periodic synchronization tick in PING frames (≥ once every 100 ms) — observable safe-reconfig point and multi-stream alignment signal."},
        {"name": "Monitor BREQ / BREL",        "purpose": "Bus-arbitration state — observable Master vs Monitor ownership."},
        {"name": "PHY Test Modes (Master pin states)", "purpose": "Master-side pin configuration so external Master or test equipment can drive Data/Clock instead of the Master, including ability to disable the master bus-keeper (M_KeeperOff) and to park Data or both Clock and Data Off/high-Z."},
        {"name": "Transport Test Modes per Port",      "purpose": "Static0 (helps detect Bus Clash when another port drives same BitSlots), Static1 (helps generate Bus Clash deliberately), PRBS (255-bit maximal-length 8-bit LFSR sequence; receiver synchronizes in up to 8 bits; interrupt on error)."},
        {"name": "Monitor (test equipment)",     "purpose": "Optional device class that snoops the bus most of the time and may temporarily take over to issue Read/Write commands (BREQ/BREL arbitration)."},
    ]
    d["phy_test_modes_master_table"] = {
        "header": ["Mode name", "Data bus-keeper", "Clock Output", "Data Output"],
        "rows": [
            ["Normal",         "x",          "x",          "x"],
            ["M_DataOff",      "x",          "x",          "Off/high-Z"],
            ["M_ClockDataOff", "x",          "Off/high-Z", "Off/high-Z"],
            ["M_AllOff",       "Off/high-Z", "Off/high-Z", "Off/high-Z"],
            ["M_KeeperOff",    "Off/high-Z", "x",          "x"],
            ["M_LowLow",       "x",          "Static Low", "Static Low"],
            ["M_LowHigh",      "x",          "Static Low", "Static High"],
        ],
        "legend": "'x' means functional (driven normally) in that column.",
        "note":   "External master or test equipment can drive data and clock instead of master and replace the master bus-keeper.",
    }
    d["transport_test_modes_per_port_table"] = {
        "Static0": "Drives all-zeros on the port BitSlots; helps detect Bus Clash Errors caused by another port also driving the same BitSlots.",
        "Static1": "Drives all-ones on the port BitSlots; helps generate Bus Clash Errors deliberately for fault-injection testing.",
        "PRBS":    "8-bit LFSR — TX initial Q[8:1] = 0xFF; characteristic polynomial corresponds to the diagram in the webinar (taps in PRBS_out chain). Generates 255-bit maximal-length sequence. RX side initial Q[8:1] = 0xD2; receiver synchronizes in up to 8 bits. PRBS_error output toggles on mismatch and can raise an interrupt.",
    }
    d["interrupt_sources"] = [
        {"flag": "IntStat_Parity",      "trigger": "Parity bit mismatch over the Parity Calculation Window; Slave shall set NAK in current frame and raise this interrupt."},
        {"flag": "IntStat_Bus_Clash",   "trigger": "Two devices drove the same BitSlot with conflicting Logic 1 / Logic 1-from-different-source patterns — Modified-NRZI parity will detect some of these as well."},
        {"flag": "IntStat_Test_Fail",   "trigger": "PRBS test mode receiver detected a mismatch."},
        {"flag": "IntStat_Port_Ready",  "trigger": "Channel Prepare state machine reached Ready (NF=0, P=1)."},
        {"flag": "IntStat_ImpDef1..3",  "trigger": "Implementation-defined interrupt sources (vendor-specific)."},
        {"flag": "PING Alert",          "trigger": "At least one Interrupt condition raised on a Slave — Slave reports 'Alert' status (vs Attached) in PING. Master must Read SCP_IntStat_* to diagnose."},
        {"flag": "PREQ",                "trigger": "Slave-initiated Interrupt/Wake signal in Control Word; serves as in-band IRQ + wake for low-power jack detection in ClockStopMode1."},
        {"flag": "Command_Failed",      "trigger": "Per-frame Command Status = NAK; Parity Error or Bus Clash detected — Master may retransmit."},
        {"flag": "Command_Ignored",     "trigger": "Per-frame Command Status — Slave is non-existent, not attached (lost sync or power), or register is reserved / not implemented."},
    ]
    d["interrupt_latency_bound"] = (
        "32-frame max latency from interrupt generation in Slave to "
        "Slave reporting Alert in PING and Master servicing via Read "
        "of SCP_IntStat_* registers.")
    d["interrupt_request"] = (
        "SoundWire carries interrupts in-band — PREQ bit + per-Slave "
        "'Alert' three-state status in every PING frame + "
        "hierarchical SCP_IntStat_1/2/3 registers + per-Port "
        "DPst_IntStat. No separate IRQ pin required.")
    d["monitor_role"] = (
        "Test equipment in snooping/analyzer mode most of the time. "
        "Can temporarily take over the bus via BREQ/BREL arbitration "
        "to inject Read/Write commands. Receives sync from Master's "
        "static + dynamic sync words; if Monitor loses sync, the "
        "command defaults to PING with BREQ cleared and Master "
        "reclaims ownership.")
    d.setdefault("notes",
        "MIPI SoundWire defines protocol-level observability and "
        "bus-injection interfaces; DFT (scan, BIST, JTAG, MBIST) "
        "lives at SoC integration level and is left to the "
        "implementing controller / codec IP block.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants
# ----------------------------------------------------------------------
def _apply_l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    d["width_parameters"] = {
        "CLOCK_LINE_COUNT":        1,
        "DATA_LANE_COUNT_MANDATORY": 1,
        "DATA_LANE_COUNT_MAX":     8,
        "BITS_PER_CLOCK_PERIOD_DDR": 2,
        "CONTROL_WORD_WIDTH_bits": 48,
        "STATIC_SYNC_WIDTH_bits":  9,
        "DYNAMIC_SYNC_CRC_WIDTH_bits": 4,
        "DYNAMIC_SYNC_PERIOD_frames": 15,
        "FRAME_COLS_SET":          [2, 4, 6, 8, 10, 12, 14, 16],
        "FRAME_ROWS_MIN":          48,
        "FRAME_ROWS_MAX":          256,
        "CONTROL_WORD_ROWS":       48,
        "MAX_SLAVES_PER_MASTER":   11,
        "MAX_DATA_PORTS_PER_SLAVE": 14,
        "MAX_CHANNELS_PER_PORT":   8,
        "MAX_SLAVE_PORTS_SYSTEM_TYP": 96,
        "READ_WRITE_ADDR_WIDTH_bits": 16,
        "READ_WRITE_PAYLOAD_WIDTH_bits": 8,
        "DEVICE_ADDR_FIELD_WIDTH_bits": 4,
        "DEVICE_NUMBER_MIN_VALID": 1,
        "DEVICE_NUMBER_MAX_VALID": 11,
        "BROADCAST_DEVICE_NUMBER": 15,
        "DEVICE_0_FOR_UNENUMERATED": 0,
        "ENUMERATION_VALUE_WIDTH_bits": 48,
        "ENUMERATION_REGISTER_COUNT": 6,
        "INTERRUPT_LATENCY_MAX_frames": 32,
        "SYNC_VERIFY_FRAMES":      16,
        "BUS_RESET_LOGIC1_COUNT":  4096,
        "WAKE_HIGH_MIN_BITSLOTS":  2,
        "SSP_INTERVAL_MAX_ms":     100,
        "BRA_MAX_RATE_Mbps":       20,
        "BUS_CLOCK_MAX_TYP_MHz":   13.0,
        "PRBS_LFSR_WIDTH_bits":    8,
        "PRBS_SEQ_LENGTH_bits":    255,
        "PRBS_RX_SYNC_BITS_MAX":   8,
        "PRBS_TX_INIT_VALUE_hex":  "0xFF",
        "PRBS_RX_INIT_VALUE_hex":  "0xD2",
    }
    d["key_register_addresses_hex"] = {
        "SCP_Device0_5_range":   "implementation-defined within 0x0000-0x0FFF normative range; stores 48-bit enumeration value",
        "SCP_IntStat_1":         "0x0040",
        "SCP_IntClear_1":        "0x0040",
        "SCP_IntMask_1":         "0x0041",
        "SCP_IntStat_2":         "0x0042",
        "SCP_IntStat_3":         "0x0043",
        "DPst_IntStat":          "+0x00 per Data Port base",
        "DPst_IntClear":         "+0x00 per Data Port base",
        "DPst_IntMask":          "+0x01 per Data Port base",
    }
    d["address_space_partitioning_hex"] = {
        "normative":             "0x0000 - 0x0FFF (~50% used)",
        "device_class_reserved": "0x1000 - 0x17FF",
        "implementation_defined":"0x2000 - 0xFFFF",
        "paged_implementation":  "0x10000 - 0x3FFFFFFF (via paging registers)",
    }
    d["control_word_opcode_summary"] = {
        "PING":  "Slave status + multi-stream synchronization (SSP) + Monitor arbitration (BREQ/BREL)",
        "READ":  "16-bit address + 8-bit payload — addressed to single Slave (1..11) / group / broadcast (0xF)",
        "WRITE": "16-bit address + 8-bit payload",
        "BRA_BTP": "Bulk Register Access over DataPort 0 — Header + raw data + CRC; up to ~20 Mbit/s; bidirectional",
    }
    d["frame_shape_examples_from_webinar"] = [
        {"shape": "48x4",  "cols": 4,  "rows": 48,  "control_word_position": "Col 0 Rows 0..47", "payload_rows": "Rows 0..47 Cols 1..3"},
        {"shape": "64x4",  "cols": 4,  "rows": 64,  "control_word_position": "Col 0 Rows 0..47", "payload_rows": "Rows 0..47 Cols 1..3 plus Rows 48..63 Cols 0..3"},
        {"shape": "50x16", "cols": 16, "rows": 50,  "control_word_position": "Col 0 Rows 0..47", "payload_rows": "Rows 0..49 Cols 1..15 plus Rows 48..49 Col 0"},
    ]
    d["transport_examples_from_webinar"] = {
        "example_1": {"frame": "50 rows x 10 cols", "frame_rate_kHz": 48, "samples_per_frame": 2, "sample_events_at": ["Row 0 Col 0", "Row 25 Col 0"], "note": "Position of 3 streams is equivalent in terms of capture/rendering"},
        "example_2": {"frame": "50 rows x 8 cols",  "frame_rate_kHz": 48, "streams": ["192 kHz (4 samples/frame)", "96 kHz (2 samples/frame)"], "note": "Not enough space for 2nd channel at 192 kHz; 2nd channel of 96 kHz stream pushed after 2nd sample at 192 kHz — Block-Per-Channel mode required for 96 kHz stream"},
        "example_3": {"frame_rate_kHz": 48, "sample_rate_kHz": 32, "note": "2 sample intervals for 3 frames; samples may be spread across two frames; not illegal and even required for some combinations of frame/sample rate"},
        "example_4_pdm": {"frame": "50 rows x 10 cols", "oversampling_100x": "2 sample intervals/row", "oversampling_50x": "1 sample interval/row", "oversampling_25x": "1 sample for every other row"},
    }
    d["key_phy_timing_parameters_named"] = [
        "tDZ_Data_Max — worst-case latest time to become high-impedance",
        "tZD_Data_Min — worst-case earliest time to drive",
        "tDZ_Data_Max < tZD_Data_Min — strict ordering for inter-driver handover",
        "tOH_Data_Min — minimum valid signal duration so bus-keeper snaps to new value at far end of trace; permits self-timed turn-off that occurs before the clock edge ends the BitSlot",
        "tOV_Data_Max",
        "V_OH_Data_Min / V_OL_Data_Max — Data line voltage thresholds",
        "V_TP_Clock_Min/Max / V_TN_Clock_Min/Max — Clock positive- and negative-edge threshold envelopes",
    ]
    d["modes_named"] = [
        "Isochronous (Isoc) / Normal — regular audio playback",
        "Asynchronous (Async) — 2-bit preamble (RX-Ready, TX-Ready) per sample",
        "TX-controlled, RX-Controlled, Full-Async",
        "Block-Per-Port, Block-Per-Channel",
        "Normal PHY vs High-PHY",
        "ClockStopMode0 (mandatory, context retained), ClockStopMode1 (optional, context may be lost, re-enumerate on wake)",
    ]
    d["compliance_constants"] = {
        "mandatory_clockstop_modes":      ["ClockStopMode0"],
        "mandatory_transport_test_modes": ["Static0", "Static1", "PRBS"],
        "mandatory_sync_verify_frames":   16,
        "mandatory_dynamic_sync_period_frames": 15,
        "mandatory_ssp_interval_ms_max":  100,
        "mandatory_bus_reset_logic1_count": 4096,
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing waveform
# ----------------------------------------------------------------------
def _apply_l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["clock_and_reset_waveform"] = {
        "SoundWire_Clock_idle_during_clockstop": "Parked Low after a 'Stopping Frame' (Master drives all BitSlots of the Stopping Frame, ending with Clock + Data both Low).",
        "SoundWire_Clock_active":  "Square-wave at 9.6 MHz / 12 MHz / 12.288 MHz typical (13 MHz max for typical geometries; can be faster in single-Slave-close-to-Master configurations).",
        "SoundWire_Data_idle":     "Held by bus-keeper at last driven level; Modified-NRZI Logic 0 = no change.",
        "POR_release":             "Power-on reset releases Master to apply Clock and Frame; un-enumerated Slaves wait until 16 consecutive frames of valid static + dynamic sync before declaring 'Attached'.",
    }
    d["bit_transfer_waveform"] = {
        "rule":                "Two BitSlots per Clock period (DDR) — one on the rising edge and one on the falling edge of SoundWire_Clock.",
        "encoding":            "Modified-NRZI: Logic 1 = active level change on the BitSlot boundary; Logic 0 = passive (no change), level held by bus-keeper.",
        "data_handover_cases": ["Case #1: high-Z → driving (new driver starts; tZD_Data_Min minimum delay after clock edge)", "Case #2: driving → driving across two different devices (previous driver tri-states; next driver asserts; momentary tri-state required even if same physical device drives two adjacent BitSlots)", "Case #3: driving → high-Z (current driver releases; bus-keeper holds last level)"],
        "key_constraint":      "tDZ_Data_Max (worst-case latest time to high-Z) < tZD_Data_Min (worst-case earliest time to drive) so no two drivers fight on a transition.",
        "self_timed_turnoff":  "Permitted self-timed turn-off occurring before the clock edge that ends a given BitSlot; tOH_Data_Min ensures the valid signal is presented long enough for the bus-keeper at the far end of the PCB trace to snap to the new value.",
        "figure":              "Webinar slides 'Data handover (1)/(2)/(3)' and 'Modified NRZI encoding'.",
    }
    d["control_word_waveform"] = {
        "position_in_frame":  "First 48 rows of Column 0 of every Frame (Control Word occupies a 48-row × 1-col strip).",
        "static_sync_word":   "8 bits plus 1 mode-identification bit (Normal vs High-PHY) — fixed pattern Slaves use to lock onto Frame boundaries; verified for 16 consecutive frames before declaring 'Attached'.",
        "dynamic_sync":       "4-bit CRC pattern with 15-frame period — removes 'ghost' sync words.",
        "ping_status_bits":   "Three-state per Slave (Not Attached / Attached / Alert), positions for Devices 0..11.",
        "command_status":     "ACK / NAK / Command_Ignored per addressed Slave per Read/Write.",
        "parity_bit":         "Single bit per frame; covers Parity Calculation Window BitSlot[44,1] previous → BitSlot[44,0] current; error may be reported with a 1-frame delay; Slaves do not compute parity until they have successfully synchronized to Master.",
    }
    d["frame_shape_waveform"] = {
        "valid_cols":           [2, 4, 6, 8, 10, 12, 14, 16],
        "valid_rows_range":     [48, 256],
        "valid_rows_note":      "Only selected row values in [48, 256] are valid; Master typically uses combinations with rows and columns scaled by 2^N.",
        "control_word_position":"First 48 rows of Col 0 reserved for Control Word; remaining BitSlots carry payload (PCM, PDM, raw DATA).",
        "frame_examples":       ["48x4", "64x4", "50x16", "50x10", "50x8"],
    }
    d["transport_waveform"] = {
        "sample_event_definition": "Instant when data is captured/rendered — word-clock / frame-sync periodic event.",
        "sample_interval":         "Number of bits between successive Samples; updates when Frame Shape or sampling frequency changes; not necessarily a multiple of row size; not dependent on number of channels.",
        "transport_sub_frame":     "Vertical partition of Frame defined by HStart, HStop (with notional HWidth = HStop - HStart); can also be viewed as a temporal aperture per Data Port.",
        "payload_data_window":     "Intersection between Transport Sub-Frame and Payload Data Window (defined by Sample Interval). Can be shared between similar streams.",
        "block_per_port_mode":     "All channels of a port packed as a single data chunk per Sample Interval, lowest to highest channel; BlockOffset from start of Payload Data Window.",
        "block_per_channel_mode":  "Channels transmitted in individual chunks within same Sample Interval; initial Block_Offset + inter-sample Sub_Block_Offset; benefits: 'holes' in bit allocation reclaimable by other streams.",
        "grouping":                "Ability to group up to 4 successive samples to avoid 'vertical stripes' for PDM; required for PDM, optional for PCM.",
    }
    d["clockstop_wake_waveform"] = {
        "clockstopnow_then_stopping_frame": "Master issues 'ClockStopNow' command in the Control Word, then drives the Stopping Frame (Master owns all BitSlots in the Stopping Frame). Last bit of Stopping Frame parks Data Low; Clock is then held Low.",
        "wake_high_pulse":                  "Wake-Up High for ≥ 2× minimum BitSlot duration on Data; Master then resumes Clock — extended first bit of Frame N+1 followed by the second bit of Frame N+1.",
        "modes": {
            "ClockStopMode0": "Mandatory; Slave keeps context (registers, Device Number, programmed transport) and restarts immediately on wake.",
            "ClockStopMode1": "Optional; Slave may lose context, enters very-low-power mode; Slave needs to be re-enumerated on startup; removes need for extra GPIO for e.g. jack detection.",
        },
        "permission": "Master can program which Slaves are allowed to wake the bus.",
    }
    d["ssp_waveform"] = {
        "bit_position_in_ping": "SSP bit in PING frame; driven at regular intervals.",
        "min_period_ms":        100,
        "purpose":              "Maintain alignment between multiple links with different frame rates; between Ports using different sampling rates on the same link; define 'safe' time positions for bus reconfiguration; maintain phase coherence between devices; reset SampleInterval counters and resync transport.",
        "constraint":           "Typically large enough to be multiple of all sample intervals.",
    }
    d["monitor_arbitration_waveform"] = {
        "BREQ":  "Monitor request bit in Control Word; 0 = Master owns, 1 = Monitor requests.",
        "BREL":  "Master yield bit in Control Word; 0 = Master keeps, 1 = Master will yield at end of frame.",
        "ownership_truth_table": {
            "0_0": "Master owns",
            "0_1": "Illegal sequence",
            "1_0": "Monitor requesting; Master still owns",
            "1_1": "Monitor owns; may issue Read/Write commands",
        },
    }
    d["enumeration_waveform"] = {
        "step_1": "Master applies Clock; programmed Frame Shape is broadcast.",
        "step_2": "Slave verifies static + dynamic sync for 16 consecutive frames.",
        "step_3": "Slave drives PREQ and/or 'Attached' status bit at Device 0 position in next PING.",
        "step_4": "Master issues 6 consecutive READ commands to SCP_Device0..5 of the Slave (still Device Number 0) to read 48-bit enumeration value.",
        "step_5": "Master issues WRITE to assign new Device Number 1..11.",
        "step_6": "Bus contention: if multiple Slaves report Attached at Device 0, hardware arbitration favors the Slave with the highest 48-bit enumeration value (others back off); Master redoes enumeration until no Slave reports Attached at Device 0.",
    }
    d["reset_waveform"] = {
        "hard_reset_power_on":     "Power-On Reset; Master and Slaves come up at Device Number 0; Interrupt masks disabled; all registers at hardware defaults.",
        "hard_reset_bus_reset":    "Master drives 4096 Logic1 transitions on SoundWire_Data; all Slaves perform Hard-Reset.",
        "hard_reset_device_reset": "Master writes Reset bit in SCP_Ctrl of a specific Slave.",
        "soft_reset":              "Slave detects two sync errors (not necessarily successive); soft-resets itself; Device Number lost; Interrupt Status register maintained so debug can determine sync-loss cause.",
    }
    d["parity_waveform"] = {
        "parity_calculation_window": "BitSlot[44,1] of previous frame to BitSlot[44,0] of current frame.",
        "computation_basis":         "Physical level read on the bus (not the value sent), so parity detects some bus conflicts as well as bit errors.",
        "slave_response_on_error":   "Set NAK bit in current Read/Write Command Status; raise IntStat_Parity interrupt; reported with up to 1-frame delay.",
        "sync_dependency":           "Slaves do not compute parity until they have successfully synchronized to Master.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 integration spec
# ----------------------------------------------------------------------
def _apply_l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Wire-level audio interface specification for the MIPI "
        "Alliance SoundWire family. Defines the bus protocol between "
        "an Application-Processor-class Master and one or more "
        "audio-peripheral Slaves (microphones, codecs, smart "
        "amplifiers) plus optional Monitor (test equipment) sharing a "
        "single SoundWire_Clock + SoundWire_Data line pair (with "
        "optional additional Data Lanes 1..7). Concrete SoundWire "
        "Master / Slave / Monitor IP blocks implement this protocol "
        "behind an SoC bus interface (e.g. AHB / AXI / APB) and "
        "provide DMA, audio FIFOs, and per-Port transport-layer logic "
        "at the integration level.")
    d["integration_overview"] = {
        "physical_topology": "Multi-drop bus: a single SoundWire_Clock line driven by the Master + a single SoundWire_Data line (Lane 0) shared by Master, Slaves, and optional Monitor. Lanes 1..7 are optional and may be shared among all devices or private to a group of devices for higher aggregate bandwidth. For device-to-device lanes a bus-keeper must be enabled on one of the devices.",
        "drive_type":        "SoundWire_Clock: Push-Pull from Master. SoundWire_Data: Modified-NRZI DDR (two BitSlots per Clock period); Logic 1 = active level change; Logic 0 = passive unchanged level held by bus-keeper. Bus-keeper is required.",
        "voltage_domain":    "1.2 V or 1.8 V supplies; exact thresholds (V_OH_Data_Min / V_OL_Data_Max / V_TP_Clock / V_TN_Clock) are pinned in the gated v1.0 spec.",
        "max_devices":       "Up to 11 Slave Devices per Master per bus. Across the entire system, Slaves are limited to ~96 total Slave-Ports.",
        "max_data_ports":    "Up to 14 Data Ports per Slave; up to 8 channels per Port.",
        "address_space":     "Slave Device Numbers 1..11 (Device 0 = un-enumerated; Device 15 = broadcast; group addresses for multicast). 16-bit register address space subdivided into normative (0x0000-0x0FFF), device-class reserved (0x1000-0x17FF), implementation-defined (0x2000-0xFFFF), and paged implementation (0x10000-0x3FFFFFFF).",
        "no_chip_select":    "Addressing is software-based via the Device Number field in the Control Word — no per-device chip-select signal.",
    }
    d["interface_categories"] = [
        "Master (single per bus; provides Clock + sync pattern on Data; handles all bus management, bit allocation, Frame Shape, ClockStop)",
        "Slave (1..11 per Master; typically audio peripheral such as microphone, codec, amplifier; can signal Interrupt condition via PREQ / Alert / IntStat; can wake the system)",
        "Monitor (optional; test equipment in snooping/analyzer mode most of the time; may temporarily take over the bus via BREQ/BREL and issue Read/Write commands)",
        "Bridge Slave (Slave on one bus, Master on a downstream secondary bus — used in topologies where a single Master Application Processor wants to extend reach via a Bridge chip)",
    ]
    d["interconnect_topologies_supported"] = [
        "AP Direct-Attach — single Application Processor Master directly drives multiple ADC/DAC Slaves on a single Clock + Data tree.",
        "Bridges, Inter-chip Link — AP Master ↔ Bridge Slave (Master on the other side) ↔ downstream ADC/DAC Slaves; can include BT FM Radio chip with its own Slave + Data lanes.",
        "Inter-chip Link with Multi-Lane Support — AP Master ↔ Audio Codec Slave with Data[0]..Data[2] separate Data lanes for higher aggregate bandwidth; BT FM Radio + DSP on additional lanes.",
        "Functional Partitioning — Application Processor with two Master instances driving disjoint Slave groups (e.g. one for input ADCs, one for output DACs).",
        "Routing / Use-case Partitioning — independent Master pairs each owning a separate Clock + Data tree for different audio use cases.",
        "Shared PHY — module-level integration with one or more Slaves and a Master sharing a single PHY for external pads (pins shared).",
        "Virtual PHY — pins not visible externally; SoundWire used inside a module via an OR-gate / clock-doubler internal PHY.",
    ]
    d["default_signal_values_when_idle"] = (
        "SoundWire_Clock = held Low when ClockStop is active; "
        "otherwise running at configured natural-clock frequency. "
        "SoundWire_Data = held by bus-keeper at last driven level "
        "(Modified-NRZI Logic 0 = passive). On wake from ClockStop, "
        "Slave drives Data High for ≥ 2× minimum BitSlot duration; "
        "Master then resumes Clock.")
    d["soc_dependent_items"] = [
        "Pad type — Push-Pull driver for Clock; bidirectional Push-Pull / high-Z driver + bus-keeper for Data.",
        "Master Clock generation — typically natural-clock PLL output (9.6 / 12 / 12.288 MHz); may scale up to 13 MHz typical / faster in restricted geometries.",
        "Per-Slave bus-keeper enable (master M_KeeperOff PHY Test Mode).",
        "Multi-Lane mux logic (Lane 0..7 routing per Port).",
        "Frame Shape generator (Cols / Rows + Control Word generator).",
        "Static + Dynamic sync word generator / detector (4-bit CRC pattern with 15-frame period).",
        "Parity generator / checker (Parity Calculation Window logic).",
        "Per-Port transport-layer logic — HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset, Block-Per-Port vs Block-Per-Channel.",
        "Per-Port DMA / FIFO for audio data (PCM, PDM).",
        "BRA / BTP engine on DataPort 0 (Header + CRC payload up to 20 Mbit/s).",
        "Interrupt aggregation — SCP_IntStat_1/2/3 hierarchy + per-Port DPst_IntStat.",
        "ClockStop / wake control + ClockStopPrepare (CSP_SM).",
        "Channel Prepare / Activate (CP_SM) per channel per Port.",
        "Monitor BREQ/BREL arbitration logic (Master side).",
        "SoC bus interface (AHB / AXI / APB) wrapping the SoundWire Master IP.",
    ]
    d["low_power_modes"] = {
        "active_clock":         "Bus running at programmed natural-clock frequency.",
        "clockstop_mode0":      "Mandatory low-power mode. Slave retains all context (registers, Device Number, programmed transport). Slave is ready to resume immediately.",
        "clockstop_mode1":      "Optional very-low-power mode. Slave may lose context, requires re-enumeration on wake; suitable for e.g. headphone-jack-detection wake — eliminates need for extra GPIO.",
        "wake":                 "Wake-up may be master- or Slave-initiated. Master can program which Slaves are allowed to wake the bus. Slave wakes by driving Data High for ≥ 2× minimum BitSlot duration; Master resumes Clock and frames.",
    }
    d["bus_recovery_procedure"] = (
        "If a Slave detects two sync errors (not necessarily "
        "successive), it Soft-Resets — Device Number lost, Interrupt "
        "Status maintained for debug. If multiple parity / bus-clash "
        "errors persist, command is retransmitted or bus is reset "
        "(4096 Logic1 transitions on Data line for Hard Bus Reset). "
        "Master may also issue a Device Reset via SCP_Ctrl.")
    d["co_existence_with_other_audio_interfaces"] = {
        "replaces":             "I2S/TDM (lower pin count, clock scaling, dynamic slot mapping, burst mode, command embedded with data, in-band interrupt, PDM support), PDM (clock scaling, embedded command/control, interrupts), HDAudio (clock scaling, lower pin count, PDM, simpler devices), SLIMbus (lower gate count, simpler protocol, low-latency PDM, lower power with adjustable frame size + DDR).",
        "preserved_pros":       "I2S Master/Slave role-switching is not supported (slight con vs I2S); SLIMbus clock and manager hand-over capabilities are not supported (slight con vs SLIMbus — only Master and Monitor can send messages on SoundWire).",
        "overhead_notes":       "PDM-mode overhead is ≈ 70 % for dual-mic but less than 5 % for single-mic mode. Multi-lane SoundWire is lower power than equivalent PDM.",
    }
    d["engineering_notes"] = {
        "stream_aggregation":    "Source and Sink ports do not need to share parameters as long as they share SampleInterval and bank-switch event. Not possible in Async modes (RX/TX-ready are per port).",
        "bank_switch_safe_point":"All devices switch banks synchronously on the next SSP event after Master writes SCP_FrameCtrl0/1.",
        "ssp_interval":          "Driven at least once every 100 ms; defines safe time positions for bus reconfiguration.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L10 test cases
# ----------------------------------------------------------------------
def _apply_l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial — the public webinar describes mandatory features "
        "(PHY test modes per Master pin table, Transport Test Modes "
        "Static0/Static1/PRBS per Port, Monitor role, ClockStop "
        "modes) and normative state machines (CP_SM, CSP_SM, "
        "enumeration arbitration) that map directly to compliance "
        "test scenarios; the gated v1.0 spec defines the formal "
        "compliance test suite.")
    d["derived_compliance_test_categories"] = [
        "PHY-level — DDR sampling on both clock edges, Modified-NRZI encoding (Logic 1 = active change; Logic 0 = passive level held by bus-keeper) correctness verification.",
        "PHY-level — Data handover cases #1 (high-Z → driving), #2 (driving → driving across two devices), #3 (driving → high-Z) with tDZ_Data_Max < tZD_Data_Min timing margin verification.",
        "PHY-level — tOH_Data_Min self-timed turn-off verification ensuring far-end bus-keeper snaps to new value.",
        "PHY-level — Master PHY Test Modes coverage (Normal / M_DataOff / M_ClockDataOff / M_AllOff / M_KeeperOff / M_LowLow / M_LowHigh) — confirm each mode drives Clock/Data/Bus-keeper as tabled.",
        "PHY-level — High-PHY mode handover sequence; Mode identification via one bit of the static sync word.",
        "Frame structure — Frame Shape support for all valid Cols ∈ {2,4,6,8,10,12,14,16} × Rows ∈ valid subset of [48, 256]; pairwise combination handling by Slaves.",
        "Frame structure — Static 8+1-bit sync word lock acquisition; Dynamic 4-bit CRC pattern with 15-frame period verification.",
        "Frame structure — Slave declares 'Attached' only after 16 consecutive frames of valid Static + Dynamic sync.",
        "Control protocol — PING command: per-Slave three-state status (Not Attached / Attached / Alert); SSP bit driven ≥ once every 100 ms; Monitor BREQ/BREL arbitration.",
        "Control protocol — READ / WRITE command: 16-bit address + 8-bit payload; addressing Device 1..11 single Slave, group, and broadcast (0xF); ACK / NAK / Command_Ignored response coverage.",
        "Control protocol — Parity bit computation over Parity Calculation Window (BitSlot[44,1] previous → BitSlot[44,0] current); error reporting with 1-frame delay; bus-clash detection via parity on physical level.",
        "Control protocol — Bulk Register Access on DataPort 0: Header + payload + CRC; bidirectional; ≈ 20 Mbit/s.",
        "Enumeration — 48-bit hard-coded enumeration value (SoundWire spec version + UniqueID + ManufacturerID + PartID + Class) stored as 6 SCP_Device0..5 registers; Slave reports Attached at Device 0; Master reads 48-bit value; Master assigns Device Number 1..11.",
        "Enumeration — Hardware arbitration when multiple Slaves report Attached at Device 0 simultaneously: Slave with highest enumeration value wins; Master redoes enumeration until no Slave reports Attached at Device 0.",
        "Reset — Hard-Reset (Power-On, Bus Reset via 4096 Logic1 transitions, Device Reset via SCP_Ctrl); Soft Reset (two sync errors); post-reset state: Interrupt masks disabled, Device Number lost.",
        "Transport — Per-Port HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset programmability; Block-Per-Port and Block-Per-Channel mode verification.",
        "Transport — Sample Interval updates correctly when Frame Shape or sampling frequency changes; not necessarily multiple of row size; not dependent on number of channels.",
        "Transport — PDM grouping (up to 4 successive samples to avoid 'vertical stripes'); required for PDM, optional for PCM.",
        "Transport — Stream aggregation: Source and Sink ports with different parameters but shared SampleInterval and bank-switch event; not possible in Async modes.",
        "Transport — Async modes: 2-bit preamble (RX-Ready, TX-Ready) per sample; data only transmitted when both Ready; TX-controlled, RX-Controlled, Full-Async sub-modes.",
        "Transport — Per-Port Transport Test Modes Static0 / Static1 / PRBS — all 3 mandatory per Port; PRBS receiver synchronizes in ≤ 8 bits; PRBS error → interrupt.",
        "State machines — Channel Prepare CP_SM full 4-state and simplified single-Ready forms; software interrupt unmask for Ready notification.",
        "State machines — ClockStopPrepare CSP_SM full 4-state and simplified single-Ready forms.",
        "ClockStop — ClockStopNow command + Stopping Frame (Master owns all BitSlots; parks Clock and Data Low).",
        "ClockStop — ClockStopMode0 mandatory: context retained, immediate resume; ClockStopMode1 optional: context lost, re-enumeration on wake.",
        "ClockStop — Wake-Up High for ≥ 2× minimum BitSlot duration; Master programmable Slave-wake permission.",
        "Interrupt — Hierarchical SCP_IntStat_1/2/3 + per-Port DPst_IntStat; 32-frame maximum latency.",
        "Interrupt — Sources: Parity, Bus Clash, Test Fail, Port Ready, ImpDef1..3.",
        "Bank switching — Synchronized bank switch across all devices on SCP_FrameCtrl0/1 write; safe for Frame Shape changes, channel activation/deactivation, BitSlot allocation changes.",
        "Monitor — Snoop without disturbing bus; assert BREQ + BREL for Command Word ownership; transition back to Master ownership; BREQ=0, BREL=1 illegal.",
        "Monitor — Recovery: if Monitor loses sync, command defaults to PING with BREQ cleared and Master reclaims ownership.",
    ]
    d["spec_normative_fsms"] = [
        "Channel Prepare CP_SM (Stopped → Preparing → Ready → De-preparing → Stopped)",
        "ClockStopPrepare CSP_SM (NotReady → Preparing → Ready → De-preparing → NotReady)",
        "Enumeration arbitration (Slave with highest 48-bit enumeration value wins at Device 0)",
        "Monitor BREQ/BREL arbitration (truth table)",
    ]
    d["typical_communication_examples_from_webinar"] = [
        "Slide 'SoundWire frame overview' — Master Control Word column showing PING / READ / WRITE / TEST SUPPORT row groups; STATUS DEVICE 4-11 + STATUS DEVICE 0-3 rows; CONSTANT SYNC / DYNAMIC SYNC rows; PAR / NAK / ACK error-control rows.",
        "Slide 'Transport examples (1)' — Frame 50 rows × 10 cols at 48 kHz frame rate → 2 samples per frame; Sample Events at (Row 0, Col 0) and (Row 25, Col 0); position of 3 streams equivalent in terms of capture/rendering.",
        "Slide 'Transport examples (2)' — Frame 50 rows × 8 cols at 48 kHz; 192 kHz stream → 4 samples/frame; 96 kHz stream → 2 samples/frame; not enough space for 2nd channel → 2nd channel of 96 kHz stream pushed after 2nd sample at 192 kHz; Block-Per-Channel mode required for 96 kHz stream.",
        "Slide 'Transport examples (3)' (sample-rate mismatch) — Frame Rate 48 kHz, Sample Rate 32 kHz, 2 sample intervals for 3 frames; samples may be spread across two frames; not illegal and even required for some combinations of frame/sample rate.",
        "Slide 'Transport examples (3)' (PDM) — Frame size 50 rows × 10 cols; PDM 100× oversampling → 2 sample intervals/row; 50× → 1 sample interval/row; 25× → 1 sample for every other row.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 OTP / enumeration
# ----------------------------------------------------------------------
def _apply_l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = True
    d["notes"] = (
        "Every SoundWire Slave is required to expose a 48-bit "
        "hard-coded enumeration value composed of SoundWire spec "
        "version + UniqueID + MIPI ManufacturerID + PartID + Class. "
        "This value is intended to live in factory non-volatile "
        "memory (typically OTP / e-fuse / mask-ROM / hard-wired "
        "registers), exposed to the Master through 6 SCP_Device0..5 "
        "registers that the Master reads via consecutive READ "
        "commands during enumeration.")
    d["factory_burnt_protocol_level_state"] = [
        {"name":      "48-bit Slave Enumeration Value",
         "width_bits": 48,
         "field_breakdown": "SoundWire spec version (to handle future revisions, if any) || UniqueID (if there are identical parts on bus — value set by implementation-defined mechanism such as pin-strapping; set by system integrator, not manufacturer) || MIPI ManufacturerID || PartID || Class (not defined in v1.0)",
         "purpose": "Slave identity for Master enumeration. Stored as 6 SCP_Device0..SCP_Device5 registers; Master reads via consecutive READ commands; Slave reports 'Attached' at Device 0 until a non-zero Device Number is assigned via WRITE."},
        {"name":      "MIPI ManufacturerID",
         "width_bits": "implementation-defined within the 48-bit enumeration value",
         "field_breakdown": "Assigned per MIPI Manufacturer ID page (admin.mipi.org). Allocated per company.",
         "purpose": "Identifies the Slave manufacturer to the bus Master and to the system integrator's discovery flow."},
        {"name":      "PartID",
         "width_bits": "implementation-defined within the 48-bit enumeration value",
         "field_breakdown": "Vendor-defined Part identifier.",
         "purpose": "Distinguishes different Slave parts from the same manufacturer (e.g. different codec variants)."},
        {"name":      "UniqueID",
         "width_bits": "implementation-defined within the 48-bit enumeration value",
         "field_breakdown": "Set by system integrator via implementation-defined mechanism such as pin-strapping; used when identical parts share the bus to make their enumeration values unique.",
         "purpose": "Ensures arbitration succeeds when two or more identical Slaves are on the bus."},
        {"name":      "Class",
         "width_bits": "implementation-defined within the 48-bit enumeration value",
         "field_breakdown": "Reserved for MIPI Device Class identification. Public webinar notes this field is 'not defined yet' at SoundWire v1.0; class definitions live in separate MIPI Device Class specs.",
         "purpose": "Categorizes Slave device class (e.g. microphone, smart amplifier, codec)."},
        {"name":      "SoundWire spec version field",
         "width_bits": "implementation-defined within the 48-bit enumeration value",
         "field_breakdown": "Captures the SoundWire spec revision the Slave was designed against, so Master can handle future revisions if any.",
         "purpose": "Forward/backward compatibility hint."},
    ]
    d["scp_device_register_storage"] = (
        "The 48-bit enumeration value is exposed in SCP_Device0 "
        "through SCP_Device5 (6 bytes), read in sequence by the "
        "Master via Read commands during enumeration. These registers "
        "are read-only at runtime; the underlying values are "
        "factory-burnt via OTP / e-fuse / mask-ROM / hard-wired "
        "straps per vendor implementation.")
    d["fuse_otp_implementation_left_to_device"] = (
        "MIPI SoundWire does not mandate a particular OTP / fuse / "
        "mask-ROM technology — vendors may implement the 48-bit "
        "enumeration value storage in factory-trim, e-fuse, NVMEM, "
        "or hard-wired registers as appropriate for the device "
        "process. Pin-strapping is explicitly called out as one "
        "acceptable way to set the UniqueID portion at integration "
        "time.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 behavioral sequences
# ----------------------------------------------------------------------
def _apply_l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["typical_master_power_up_sequence"] = [
        "1. Master applies power to its SoundWire IP and to the Slaves (Slaves at Device Number 0 with Interrupt masks disabled).",
        "2. Master programs initial Frame Shape (NumCols ∈ {2,4,6,8,10,12,14,16}; NumRows ∈ valid subset of [48, 256]) into its Frame generator.",
        "3. Master starts driving SoundWire_Clock at the selected natural-clock frequency (typically 9.6 MHz, 12 MHz, or 12.288 MHz).",
        "4. Master begins emitting Frames with the Static 8+1-bit sync word and Dynamic 4-bit CRC sync (15-frame period) in Column 0 of each Frame.",
        "5. Slaves search Column 0 for valid sync, and only declare 'Attached' after verifying static + dynamic sync for 16 consecutive frames.",
    ]
    d["typical_slave_enumeration_sequence"] = [
        "1. After 16-frame sync verification, un-enumerated Slave drives PREQ and/or the 'Attached' status bit at the Device 0 position in the next PING Control Word.",
        "2. Master detects Attached at Device 0; issues 6 consecutive READ commands to SCP_Device0..SCP_Device5 of Device 0 to retrieve the 48-bit enumeration value (SoundWire spec version + UniqueID + ManufacturerID + PartID + Class).",
        "3. Master assigns a non-zero Device Number in [1, 11] by writing the chosen Device Number register on the Slave (Slave still addressed at Device 0).",
        "4. Slave latches its new Device Number and from the next Frame onward reports its status at the new Device Number position (Attached or Alert) instead of at Device 0.",
        "5. If multiple Slaves report Attached at Device 0 simultaneously, hardware arbitration over the Modified-NRZI bus resolves: Slave with the highest 48-bit enumeration value wins; the others back off.",
        "6. Master repeats steps 1-5 until no Slave reports Attached at Device 0.",
    ]
    d["typical_master_write_sequence"] = [
        "1. Master prepares Control Word with Opcode = WRITE, Device address (1..11 single Slave, group, or 0xF broadcast), 16-bit register address, 8-bit payload.",
        "2. Master emits the Control Word in Column 0 Rows 0..47 of the current Frame.",
        "3. Addressed Slave(s) decode the Control Word during the same Frame.",
        "4. If Parity bit is valid and Slave exists / is Attached / register is implemented: register write takes effect at end of frame; Slave responds with ACK in the Command Status field of the next Frame.",
        "5. Otherwise Slave responds with NAK (Command Failed) or Command_Ignored (non-existent / not attached / reserved register); Master may retransmit.",
    ]
    d["typical_master_read_sequence"] = [
        "1. Master prepares Control Word with Opcode = READ, Device address, 16-bit register address.",
        "2. Master emits the Control Word in Column 0 Rows 0..47 of the current Frame.",
        "3. Addressed Slave decodes the Control Word; latches the register address.",
        "4. In the next Frame, Slave drives the 8-bit Read Data payload into the assigned payload field of the Control Word and sets Command Status = ACK.",
        "5. On parity error (NAK) or non-existent / unimplemented register (Command_Ignored), Slave responds with the appropriate status; Master may retransmit.",
        "6. Master can chain consecutive READ commands to read multi-byte registers or use Bulk Register Access (BRA) on DataPort 0 for higher throughput.",
    ]
    d["bulk_register_access_sequence"] = [
        "1. Master (Initiator) writes the BRA Header (block-read / block-write opcode, base register address, byte count) into DataPort 0's transport window.",
        "2. The Header is followed by the raw payload (write data for block-write or empty for block-read).",
        "3. CRC is appended for protection.",
        "4. Slave(s) (Targets) decode the Header; for block-read, Slave drives the payload back on DataPort 0 in subsequent Frames; for block-write, Slave commits the data to its register file at end of frame on success.",
        "5. Throughput approximately 20 Mbit/s — replaces the 8-bit-per-frame Read/Write payload limit for fast device configuration / firmware download.",
        "6. DP0 is bi-directional by nature, unlike DP1-14 which are single-direction.",
    ]
    d["typical_stream_setup_sequence"] = [
        "1. Master writes Frame Shape (NumCols, NumRows) and Frame Rate into the shadow bank of SCP_FrameCtrl0/1.",
        "2. Master writes per-Slave per-Port HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset, channel count, sample bit-width into the shadow bank.",
        "3. Master writes channel enables into the shadow bank.",
        "4. Master writes Channel Prepare (Prepare[c] in DPX_PrepareCtrl) for each channel to be activated.",
        "5. Slaves transition channels through CP_SM: Stopped → Preparing → Ready (when ready, NF=0, P=1).",
        "6. Software may unmask DPst_IntStat Port Ready interrupt to be notified when ready.",
        "7. Master then performs synchronized bank switch via SCP_FrameCtrl0/1 toggle, taking effect at the next SSP event — all devices switch banks in a synchronized manner.",
        "8. Audio Payload starts flowing in the BitSlots assigned per Port; Source ports drive audio data, Sink ports receive it.",
    ]
    d["stream_aggregation_sequence"] = [
        "1. Master configures multiple Source ports across different Slaves with the same SampleInterval but possibly different HStart/HStop and channel counts.",
        "2. Master configures Sink port(s) (its own or on another Slave) to receive the aggregated stream — different parameters allowed.",
        "3. Master ensures channels are enabled on all Devices with a common bank switch.",
        "4. 'Smart' bit allocation places port BitSlots adjacently with no spacing between ports.",
        "5. Result: 4 microphones can push data on the bus and Master retrieves a single 4-channel input; or Master writes 2-channel data on 4 ports and Slave reads 8-channel data.",
        "6. Limitation: not possible with Async modes (RX/TX-ready are per port).",
    ]
    d["async_mode_sequence"] = [
        "1. Master configures both Source and Sink ports for Async mode (TX-controlled, RX-Controlled, or Full-Async).",
        "2. Each sample carries a 2-bit preamble: RX-Ready (Sink driven) + TX-Ready (Source driven).",
        "3. Data is transmitted on the bus only when both RX-Ready = 1 AND TX-Ready = 1.",
        "4. TX-controlled: RX-Ready forced 1; Source decides when to set TX-Ready (Source-paced; e.g. always-listening mic streaming only when audio event detected).",
        "5. RX-Controlled: TX-Ready forced 1; Sink decides when to set RX-Ready (Sink-paced; e.g. DAC pulling samples on its own audio clock).",
        "6. Full-Async: both Source and Sink independently control their Ready bits — used when neither side is bus-locked.",
        "7. Async mode is necessary for 44.1 kHz playback over 48 kHz link, bursty voice-call traffic, and to allow a Slave to generate a better audio clock than SoundWire's bus clock.",
    ]
    d["clockstop_entry_sequence"] = [
        "1. Master sends 'ClockStopNow' command in the Control Word (typically after stopping all active streams).",
        "2. Master drives a Stopping Frame in which Master owns all BitSlots.",
        "3. End of Stopping Frame: Master parks Data Low and then holds Clock Low.",
        "4. Slaves enter the previously-programmed ClockStop mode: Mode 0 (mandatory, context retained) or Mode 1 (optional, context may be lost; very-low-power; e.g. jack-detection wake).",
        "5. Before entering Mode 1 a Slave that needs time to enable an alternate clock source uses the ClockStopPrepare CSP_SM (NotReady → Preparing → Ready).",
    ]
    d["wake_from_clockstop_sequence"] = [
        "1. Wake initiator (Master or Slave) drives SoundWire_Data High for ≥ 2× minimum BitSlot duration.",
        "2. Master detects the wake pulse (or autonomously decides to wake), resumes SoundWire_Clock.",
        "3. The first bit of Frame N+1 is extended; Frame N+1 then proceeds normally.",
        "4. For ClockStopMode0: Slaves immediately resume with retained context — programmed transport, Device Number, Interrupt state.",
        "5. For ClockStopMode1: Slaves are at Device Number 0 with Interrupt masks disabled; Master re-runs enumeration before resuming any streams.",
        "6. Master can program which Slaves are allowed to wake the bus (others cannot initiate wake).",
    ]
    d["monitor_arbitration_sequence"] = [
        "1. Steady-state: Master owns Command Word (BREQ=0, BREL=X).",
        "2. Monitor sets BREQ=1 in the Control Word of the current Frame to request ownership.",
        "3. Master sets BREL=1 in the next Frame to indicate it will yield at end of frame.",
        "4. At the next Frame boundary, with BREQ=1 AND BREL=1, Monitor takes ownership of the Command Word and may issue PING / READ / WRITE commands.",
        "5. Master continues to drive static + dynamic sync bits in every Frame; Master does not drive the Parity bit while Monitor owns, but sets NAK on parity error.",
        "6. Master can reclaim ownership at any time by clearing BREL back to 0.",
        "7. BREQ=0 + BREL=1 combination is illegal and rejected.",
        "8. Recovery: if Monitor loses sync, command will default to PING with BREQ cleared and Master will reclaim ownership.",
    ]
    d["reset_sequences"] = {
        "hard_reset_power_on": "Power-On Reset releases all devices into Device Number 0 with Interrupt masks disabled. Slaves wait for 16 frames of valid sync before reporting Attached; Master then runs enumeration.",
        "hard_reset_bus_reset": "Master drives 4096 Logic1 transitions on SoundWire_Data; all Slaves perform Hard-Reset.",
        "hard_reset_device_reset": "Master writes Reset bit in SCP_Ctrl of a specific Slave; that Slave performs Hard-Reset; others continue.",
        "soft_reset": "Slave detects two sync errors (not necessarily successive); soft-resets itself; Device Number lost; Interrupt Status register MAINTAINED so debug can determine sync-loss cause; re-enumeration required.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L13 lab calibration
# ----------------------------------------------------------------------
def _apply_l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["notes"] = (
        "MIPI SoundWire is a digital-bus protocol specification; "
        "there is no analog reference / trim / calibration loop "
        "defined at the protocol layer. Codec-side analog calibration "
        "(microphone bias trim, DAC gain trim, ADC offset, headphone "
        "amplifier output trim, oscillator trim) is documented in "
        "individual codec / microphone / amplifier datasheets and "
        "exposed through implementation-defined registers "
        "(0x2000-0xFFFF) or future MIPI Device Class registers "
        "(0x1000-0x17FF). The only spec-level concession to analog "
        "quality is the qualitative statement that 'Jitter needs to "
        "be limited for best audio quality' with the explicit caveat "
        "'No requirements on jitter (ppm, ps) in SoundWire spec' — "
        "making jitter performance a differentiating system-design "
        "concern rather than a protocol-compliance gate.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 protocol versioning
# ----------------------------------------------------------------------
def _apply_l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["spec_version"] = (
        "Public webinar overview of MIPI SoundWire (21 January 2015); "
        "V09r04 entered 30-day final Voting Draft review at time of "
        "webinar; V1.0 ratification planned for mid-February 2015.")
    f["predecessor_protocols_replaced_or_unified"] = [
        "I2S — two-pin or three-pin audio bus (BCK + WS + Data) without inherent multi-drop, command channel, or interrupt path. SoundWire offers lower pin count, clock scaling, dynamic slot mapping, burst mode, command embedded with data (no I2C/SPI needed), in-band interrupt capability (no GPIO), and PDM support — at cost of slight command overhead and inability to switch Master/Slave roles for clock.",
        "PDM (Pulse Density Modulation) microphones — single-clock single-data stream with fixed oversampling. SoundWire adds clock scaling, embedded command/control, interrupt capability. PDM-mode overhead is ≈ 70% for dual-mic but less than 5% for single-mic; multi-lane SoundWire is lower power than equivalent PDM.",
        "HDAudio — Intel's PC audio link. SoundWire offers clock scaling, lower pin count, PDM support, and scales to simple devices. Con: lower-bandwidth device-class functionality not yet standardized.",
        "SLIMbus — earlier MIPI audio interface. SoundWire offers lower gate count for cost-sensitive devices, simpler protocol, low-latency PDM support, lower power with adjustable Frame size and DDR — at cost of no clock and manager hand-over capabilities (only Master and Monitor can send messages on SoundWire).",
    ]
    f["soundwire_release_history"] = [
        "June 2012 — Initial discussions in the MIPI LML Working Group.",
        "Contributions from approximately 16 MIPI member companies (Intel and others).",
        "V09r04 — Entered 30-day final Voting Draft review (around early 2015).",
        "Mid-February 2015 — Planned V1.0 ratification by MIPI Alliance.",
        "21 January 2015 — Public Overview Webinar (this PDF) presented by Pierre Bossart (Intel), MIPI LML WG Chair.",
        "9 October 2014 — MIPI press release: 'MIPI Alliance Introduces MIPI SoundWire, a Comprehensive Audio Interface for Mobile and Mobile-Influenced Devices'.",
    ]
    f["scope_relative_to_other_mipi_specs"] = [
        "MIPI Alliance — Working Groups include Analog Control Interface, Battery Interface, Camera, Debug, Display High Speed Synchronous Interface, Low Latency Interface, Low Speed Multipoint Link (LML — owns SoundWire), Marketing, PHY (C/D/M), Reduced Input Output (RIO), RF Front-End, Sensor/I3C, Software, Technical Steering Group, Test, UniPro.",
        "Within MIPI System Diagram: SoundWire is the interconnect between the Application Processor (Host) and Audio Codec / Microphones / Speakers; complementary to DSI (display), CSI (camera), I3C (sensors), UFS (storage), SLIMbus (legacy audio), GbT/SPP (debug), etc.",
    ]
    f["key_changes_vs_predecessors"] = [
        {"vs": "I2S/TDM",
         "summary": "DDR 2-pin multi-drop bus with up to 11 Slaves vs point-to-point or shared 3-pin; embedded commands eliminate I2C/SPI sideband; in-band interrupt and wake; PDM support; dynamic bit allocation via Frame Shape; ClockStop for power. Slight command overhead; no Master/Slave role switching for clock."},
        {"vs": "PDM (raw)",
         "summary": "Clock scaling, embedded command/control, interrupt capability. Multi-lane lower power than equivalent PDM. Overhead ≈ 70% for dual-mic and < 5% for single-mic mode."},
        {"vs": "HDAudio",
         "summary": "Clock scaling, lower pin count, PDM, scales to simple devices. Con: lower-bandwidth device-class functionality not yet standardized."},
        {"vs": "SLIMbus",
         "summary": "Lower gate count for cost-sensitive devices, simpler protocol, low-latency PDM, lower power with adjustable frame size and DDR. Con: no clock and manager hand-over (only Master and Monitor can send messages)."},
    ]
    f["backward_compat_traps"] = [
        {
            "trap_name": "soundwire_is_not_i2s_compatible",
            "i2s":  "Three-pin (BCK + WS + Data) point-to-point or shared TDM, no command channel.",
            "soundwire": "Two-pin DDR multi-drop with embedded commands + Modified-NRZI encoding + bus-keeper.",
            "trap": "Devices designed for I2S cannot be dropped onto a SoundWire bus — the wire-level protocol is completely different. SoundWire is a SoC-level replacement, not a backward-compatibility layer.",
        },
        {
            "trap_name": "soundwire_jitter_is_implementation_defined",
            "older_specs": "Some audio interfaces pin precise jitter (ppm, ps) requirements.",
            "soundwire": "No requirements on jitter (ppm, ps) in SoundWire spec — system-design concern only.",
            "trap": "Implementers cannot rely on spec-mandated jitter — must allocate their own jitter budget for best audio quality, especially in multi-lane / multi-Slave configurations.",
        },
        {
            "trap_name": "clockstopmode1_loses_context",
            "mode0": "Mandatory; context retained; immediate resume.",
            "mode1": "Optional; context may be lost; re-enumeration required on wake.",
            "trap": "Software wake-handler must check which mode the Slave was in before assuming Device Number, transport config, and interrupt masks are still valid; for Mode 1 the full enumeration + stream-setup must be repeated.",
        },
        {
            "trap_name": "high_phy_requires_full_link_support",
            "normal_phy": "Mandatory; meets default tDZ_Data_Max / tZD_Data_Min / tOH_Data_Min margins.",
            "high_phy":   "Beyond mandatory PHY timings; all components on the link must support the same requirements; mode identification via one bit of the static sync word; defined hand-over sequence.",
            "trap": "Mixing a High-PHY-capable Slave with a Normal-PHY-only Slave on the same bus forces operation at Normal-PHY only.",
        },
    ]
    f["ipr_status_note"] = (
        "The MIPI SoundWire Specification is a MIPI Alliance "
        "specification; access to the full v1.0 spec is gated to MIPI "
        "members. The 2015 public overview webinar is the "
        "publicly-distributed summary used here as substitute "
        "documentation.")
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L15 encoding tables
# ----------------------------------------------------------------------
def _apply_l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["device_number_encoding"] = {
        "header_columns": ["Device Number (4-bit)", "Decimal", "Restriction", "Description"],
        "rows": [
            {"value_binary": "0000", "decimal": 0,  "restriction": "Reserved for un-enumerated Slave", "purpose": "Slave reports 'Attached' here until Master assigns a non-zero Device Number 1..11; arbitration when multiple Slaves contend."},
            {"value_binary": "0001 .. 1011", "decimal": "1 .. 11", "restriction": "Valid Slave Device Numbers", "purpose": "Up to 11 Slaves per Master per bus."},
            {"value_binary": "1100", "decimal": 12, "restriction": "Reserved (implementation-defined or future)", "purpose": "Not described as a valid Slave or broadcast address in the overview."},
            {"value_binary": "1101", "decimal": 13, "restriction": "Reserved",                            "purpose": "Not described as a valid Slave or broadcast address in the overview."},
            {"value_binary": "1110", "decimal": 14, "restriction": "Reserved",                            "purpose": "Not described as a valid Slave or broadcast address in the overview."},
            {"value_binary": "1111", "decimal": 15, "restriction": "Broadcast",                            "purpose": "Addresses all Slaves on the bus."},
        ],
        "group_addresses_note": "In addition to single-Slave addressing (1..11) and broadcast (15), the Read/Write commands also support 'group of Slaves' addressing — group membership is held in Slave registers (specific layout in gated v1.0 spec).",
    }
    f["control_word_opcode_summary"] = {
        "header_columns": ["Opcode", "Direction", "Address Width", "Payload Width", "Purpose"],
        "rows": [
            ["PING",  "Master → Slaves", "Per-Slave status fields", "n/a (status bits)", "Three-state status per Slave (Not Attached / Attached / Alert) + SSP + BREQ/BREL Monitor arbitration."],
            ["READ",  "Master → Slave; Slave → Master (next frame)", "16-bit register address", "8-bit", "Read 8-bit register data."],
            ["WRITE", "Master → Slave",  "16-bit register address", "8-bit", "Write 8-bit register data; takes effect at end of frame if command succeeded."],
            ["BRA/BTP", "Initiator ↔ Target(s) on DataPort 0", "Block address in Header", "raw byte stream + CRC; up to ~20 Mbit/s", "Bulk Register Access for fast block read/write; firmware download; large reconfiguration."],
        ],
    }
    f["ping_status_encoding"] = {
        "header_columns": ["Encoding", "State name", "Meaning"],
        "rows": [
            ["Not Attached", "Not Attached", "Slave is not present on the bus or not operational."],
            ["Attached",     "Attached",     "Slave is synchronized with Master and able to handle commands; eligible to be addressed by READ/WRITE."],
            ["Alert",        "Alert",        "Slave is synchronized and at least one Interrupt condition is currently raised — Master must Read SCP_IntStat_* to diagnose."],
        ],
    }
    f["command_status_encoding"] = {
        "header_columns": ["Encoding", "State name", "Meaning"],
        "rows": [
            ["ACK",              "Command Succeeded",                 "Command was decoded and executed (register write committed / read data driven)."],
            ["NAK",              "Command Failed",                    "Parity Error or Bus Clash detected; Slave shall set NAK and raise IntStat_Parity / IntStat_Bus_Clash interrupt."],
            ["Command_Ignored",  "Non-existent / Not Attached / Reserved Register", "Slave does not exist at the addressed Device Number, or Slave is not in 'Attached' state (lost sync or power), or the register is reserved / not implemented."],
        ],
    }
    f["frame_shape_encoding"] = {
        "valid_cols": [2, 4, 6, 8, 10, 12, 14, 16],
        "valid_rows_range": [48, 256],
        "valid_rows_note": "Only selected row values in [48, 256] are valid; the discrete subset is defined in the gated v1.0 spec; Slaves are required to handle pairwise combinations of valid Rows × valid Cols; Master typically only uses combinations with rows and columns scaled by 2^N.",
        "control_word_position": "First 48 rows of Column 0 of every Frame.",
    }
    f["sync_word_encoding"] = {
        "static_sync": {"width_bits": "8 + 1", "purpose": "Frame-boundary lock + 1 mode-identification bit (Normal vs High-PHY)."},
        "dynamic_sync": {"width_bits": 4, "period_frames": 15, "purpose": "CRC pattern with 15-frame period — removes 'ghost' sync words and increases robustness."},
    }
    f["modified_nrzi_encoding"] = {
        "header_columns": ["Logical Data", "Physical Encoding"],
        "rows": [
            ["1", "Active change of the physical level on the BitSlot boundary."],
            ["0", "Passive — no change of the physical level; maintained by the bus-keeper."],
        ],
        "rationale": "One BitSlot can be legally owned by multiple devices; Modified-NRZI removes drive conflicts because Logic 0 does not require any driver to assert.",
    }
    f["phy_test_modes_master"] = {
        "header_columns": ["Mode name", "Data bus-keeper", "Clock Output", "Data Output"],
        "rows": [
            ["Normal",         "functional", "functional",  "functional"],
            ["M_DataOff",      "functional", "functional",  "Off/high-Z"],
            ["M_ClockDataOff", "functional", "Off/high-Z",  "Off/high-Z"],
            ["M_AllOff",       "Off/high-Z", "Off/high-Z",  "Off/high-Z"],
            ["M_KeeperOff",    "Off/high-Z", "functional",  "functional"],
            ["M_LowLow",       "functional", "Static Low",  "Static Low"],
            ["M_LowHigh",      "functional", "Static Low",  "Static High"],
        ],
    }
    f["transport_test_modes_per_port"] = {
        "header_columns": ["Mode", "Purpose"],
        "rows": [
            ["Static0", "Helps detect Bus Clash Errors when another port drives same BitSlots."],
            ["Static1", "Helps generate Bus Clash Errors deliberately."],
            ["PRBS",    "Helps detect data integrity — 8-bit LFSR generates 255-bit maximal-length sequence; TX init Q[8:1]=0xFF; RX init Q[8:1]=0xD2; receiver synchronizes in up to 8 bits; interrupt can be generated on error."],
        ],
    }
    f["scp_interrupt_status_layout_table"] = {
        "header_columns": ["Register addr (hex)", "Register", "Bit 7", "Bit 6", "Bit 5", "Bit 4", "Bit 3", "Bit 2", "Bit 1", "Bit 0"],
        "rows": [
            ["0x0040", "SCP_IntStat_1",  "SCP2 cascade", "Port 3 cascade", "Port 2 cascade", "Port 1 cascade", "Port 0 cascade", "IntStat ImpDef1", "IntStat Bus Clash", "IntStat Parity"],
            ["0x0040", "SCP_IntClear_1", "—",            "—",              "—",              "—",              "—",              "IntClear ImpDef1", "IntClear Bus Clash","IntClear Parity"],
            ["0x0041", "SCP_IntMask_1",  "—",            "—",              "—",              "—",              "—",              "IntMask ImpDef1",  "IntMask Bus Clash", "IntMask Parity"],
            ["0x0042", "SCP_IntStat_2",  "SCP3 cascade", "Port 10 cascade","Port 9 cascade", "Port 8 cascade", "Port 7 cascade", "Port 6 cascade",   "Port 5 cascade",    "Port 4 cascade"],
            ["0x0043", "SCP_IntStat_3",  "—",            "—",              "—",              "—",              "Port 14 cascade","Port 13 cascade",  "Port 12 cascade",   "Port 11 cascade"],
        ],
    }
    f["per_port_interrupt_layout_table"] = {
        "header_columns": ["Offset (hex)", "Register", "Bit 7", "Bit 6", "Bit 5", "Bit 4", "Bit 3", "Bit 2", "Bit 1", "Bit 0"],
        "rows": [
            ["+0x00", "DPst_IntStat",  "IntStat ImpDef3", "IntStat ImpDef2", "IntStat ImpDef1", "—", "—", "—", "IntStat Port Ready", "IntStat Test Fail"],
            ["+0x00", "DPst_IntClear", "IntClear ImpDef3","IntClear ImpDef2","IntClear ImpDef1","—", "—", "—", "IntClear Port Ready","IntClear Test Fail"],
            ["+0x01", "DPst_IntMask",  "IntMask ImpDef3", "IntMask ImpDef2", "IntMask ImpDef1", "—", "—", "—", "IntMask Port Ready", "IntMask Test Fail"],
        ],
    }
    f["register_address_space_partitioning_table"] = {
        "header_columns": ["Range (hex)", "Type", "Usage"],
        "rows": [
            ["0x0000 - 0x0FFF",       "Normative",                         "MIPI-defined registers (~50 % used); includes SCP_*, DPst_*, per-Port transport regs, banked Frame control."],
            ["0x1000 - 0x17FF",       "Device-class reserved",             "Reserved for MIPI Device Class definitions (e.g. audio codec class)."],
            ["0x2000 - 0xFFFF",       "Implementation-defined",            "Vendor-specific registers."],
            ["0x10000 - 0x3FFFFFFF",  "Implementation-defined (paged)",    "Additional space accessible only via paging registers."],
        ],
    }
    f["control_word_field_table"] = {
        "header_columns": ["Region", "Field", "Description"],
        "rows": [
            ["Header",       "PREQ",                "Interrupt / Wake signal — Slave indicates wake or interrupt condition."],
            ["Synchronization","Static Sync Word",  "8 + 1 bits — fixed Frame-boundary lock + 1-bit Normal vs High-PHY identification."],
            ["Synchronization","Dynamic Sync",      "4-bit CRC pattern with 15-frame period — removes ghost sync words."],
            ["Opcode",       "PING/READ/WRITE",     "Embedded command selector."],
            ["PING fields",  "Slave Status 0..11",  "Three-state per Slave (Not Attached / Attached / Alert)."],
            ["PING fields",  "SSP",                 "Synchronization Stream Position — driven at regular intervals, ≥ once every 100 ms."],
            ["PING fields",  "BREQ",                "Monitor request for Command Word ownership."],
            ["PING fields",  "BREL",                "Master will yield Command Word ownership at end of frame."],
            ["READ/WRITE",   "Device address",      "Single Slave (1..11), group, or broadcast (0xF)."],
            ["READ/WRITE",   "Register address",    "16-bit register address."],
            ["READ/WRITE",   "Payload",             "8-bit data (Master-write or Slave-read)."],
            ["Status",       "Command Status",      "ACK / NAK / Command_Ignored."],
            ["Error control","Parity bit",          "Single bit per Frame; window = BitSlot[44,1] previous → BitSlot[44,0] current."],
        ],
    }
    f["tables_referenced_in_overview"] = [
        "Frame Shape examples — 48x4, 64x4, 50x16 (Slide 'Frame shapes')",
        "Transport Sub-Frame parameters (HStart, HStop, HWidth = HStop - HStart) — Slide 'Transport (2): Sub-Frame definition'",
        "Payload Transport Window = Transport Sub-Frame ∩ Payload Data Window — Slide 'Transport (3): Payload Transport Window'",
        "Block-Per-Port — channels packed lowest-to-highest in single chunk per SampleInterval — Slide 'Transport (4): Block-Per-Port'",
        "Block-Per-Channel — individual chunks; Block_Offset + Sub_Block_Offset — Slide 'Transport (5): Block-Per-Channel'",
        "PRBS LFSR taps and init values — Slide 'Transport test modes'",
        "Multi-lane bit allocation — Slide 'Transport (7): multi-lane'",
        "PHY Test Modes table — Slide 'PHY Test modes'",
        "Interrupt registers — Slide 'Interrupt registers'",
        "Pro / Con table vs I2S/TDM, PDM, HDAudio, SLIMbus — Slide 'Comparison with other interfaces'",
        "Stream aggregation requirements — Slide 'Stream aggregation'",
        "Monitor arbitration BREQ/BREL truth table — Slide 'Monitor arbitration'",
        "SoundWire Frame Overview (PING / READ / WRITE columns of Control Word) — Slide 'SoundWire frame overview'",
    ]
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L16 compliance properties
# ----------------------------------------------------------------------
def _apply_l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["must_have_properties"] = [
        "SoundWire_Clock is driven Push-Pull by exactly one Master; Slaves never drive SoundWire_Clock.",
        "SoundWire_Data uses DDR — two BitSlots per Clock period.",
        "Data encoding is Modified-NRZI: Logic 1 = active level change; Logic 0 = passive unchanged level held by a mandatory bus-keeper.",
        "Bus-keeper is required (master-side bus-keeper exists; can be disabled only via M_KeeperOff PHY test mode).",
        "Frame Shape is configurable with Cols ∈ {2, 4, 6, 8, 10, 12, 14, 16} and Rows ∈ valid subset of [48, 256]; Slaves are required to handle pairwise combinations of valid Rows × valid Cols.",
        "Control Word occupies the first 48 rows of Column 0 of every Frame.",
        "Every Slave shall implement a 48-bit hard-coded enumeration value (SoundWire spec version + UniqueID + MIPI ManufacturerID + PartID + Class) stored as 6 SCP_Device0..5 registers.",
        "Every Slave shall verify both the Static 8+1-bit sync word and the Dynamic 4-bit CRC sync (15-frame period) for 16 consecutive frames before declaring 'Attached'.",
        "Every Slave shall implement the parity bit set by Master/Monitor in every frame; on parity error Slave shall set NAK in current frame and raise IntStat_Parity interrupt.",
        "Parity is computed on the physical level read on the bus (not the value sent) and may be reported with a 1-frame delay.",
        "Slaves do not compute parity until they have successfully synchronized to Master.",
        "Every Slave shall report three-state status in PING frames: Not Attached / Attached / Alert.",
        "Master shall drive the SSP (Synchronization Stream Position) bit at regular intervals in PING frames — at least once every 100 ms.",
        "Every Data Port shall mandatorily support the transport test modes Static0, Static1 and PRBS.",
        "Every Slave shall support ClockStopMode0 (context retained) as the mandatory low-power mode.",
        "Hard-Reset via Bus Reset = Master drives 4096 Logic1 transitions on SoundWire_Data; Hard-Reset via Device Reset = Master writes Reset bit in SCP_Ctrl.",
        "Wake-Up from ClockStop requires Slave to drive SoundWire_Data High for ≥ 2× minimum BitSlot duration.",
        "On power-up and after any reset, Slave starts at Device Number 0 with Interrupt masks disabled.",
        "On bus contention at Device 0, hardware arbitration favors the Slave with the highest 48-bit enumeration value; others back off; Master must redo enumeration until no Slave reports Attached at Device 0.",
        "Maximum 11 Slave Devices per Master per bus; up to 14 Data Ports per Slave; up to 8 channels per Port.",
        "Maximum bus Clock frequency 13 MHz typical for typical geometries; faster only in specific settings (e.g. single Slave close to Master).",
    ]
    f["must_not_have_properties"] = [
        "Slaves shall NOT drive SoundWire_Clock — there is no Slave clock-stretching.",
        "BREQ=0 AND BREL=1 combination — explicitly illegal Monitor arbitration state.",
        "Master shall NOT drive Parity bit while Monitor owns the bus (Master still sets NAK on parity error).",
        "Slaves shall NOT compute parity before they have successfully synchronized to Master.",
        "Devices shall NOT exceed tDZ_Data_Max before tZD_Data_Min has elapsed — drivers must not fight on a handover transition.",
        "Slaves shall NOT skip the momentary tri-state between adjacent BitSlots even when the same physical device drives both — Case #2 (driving → driving) is required to tri-state momentarily.",
        "An unenumerated Slave (Device Number 0) shall NOT respond to READ/WRITE commands addressed to Device 1..11.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Command Failed — Parity Error",       "trigger": "Parity bit mismatch over Parity Calculation Window (BitSlot[44,1] previous → BitSlot[44,0] current); reportable with up to 1-frame delay; Slave shall set NAK and raise IntStat_Parity."},
        {"mode": "Command Failed — Bus Clash",           "trigger": "Two devices drove the same BitSlot with conflicting Logic 1 patterns; partly detectable via parity on physical level; Slave shall set NAK and raise IntStat_Bus_Clash."},
        {"mode": "Command_Ignored — Non-existent device","trigger": "Programming error — addressed Device Number is not allocated to any Slave."},
        {"mode": "Command_Ignored — Device not attached","trigger": "Slave has lost sync or power; reports Not Attached."},
        {"mode": "Command_Ignored — Reserved / not implemented register","trigger": "Slave does not implement the addressed register; specified Slave shall reply Command_Ignored."},
        {"mode": "Sync loss",                            "trigger": "Slave detects two sync errors (not necessarily successive); soft-resets itself; Device Number lost; Interrupt Status maintained for debug."},
        {"mode": "DAA-style contention at Device 0",     "trigger": "Multiple Slaves report Attached at Device 0 simultaneously; hardware arbitration favors highest 48-bit enumeration value; Master must redo enumeration until no Device 0 reports Attached."},
        {"mode": "Frame Shape unsupported",              "trigger": "Slave does not handle the programmed (Rows, Cols) pair; bus reconfiguration must roll back."},
        {"mode": "Async port cannot be aggregated",      "trigger": "RX-Ready/TX-Ready handshake is per-port; stream aggregation is not possible with Async modes."},
    ]
    f["min_bus_clock_constraint"] = (
        "Minimum bus Clock frequency is implementation-defined; "
        "minimum is bounded by audio-clock requirements and the need "
        "to keep SSP within ≤ 100 ms intervals.")
    f["max_bus_clock_constraint"] = (
        "Maximum 13 MHz typical; can be faster in specific settings "
        "(e.g. single Slave close to Master).")
    f["interrupt_latency_constraint"] = (
        "Maximum 32 frames from interrupt generation in Slave to "
        "Slave reporting 'Alert' status in PING.")
    f["reset_behavior_compliance"] = (
        "After Hard-Reset / Soft-Reset every Slave drops Device "
        "Number to 0, disables Interrupt masks, and must re-acquire "
        "16 consecutive frames of valid sync before declaring "
        "'Attached'. After Soft-Reset only, Interrupt Status register "
        "is MAINTAINED so debug can determine sync-loss cause.")
    f["monitor_arbitration_compliance"] = [
        "BREQ = 0 → Master owns Command Word.",
        "BREQ = 1, BREL = 0 → Monitor requesting Command Word ownership; Master still owns.",
        "BREQ = 1, BREL = 1 → Monitor owns Command Word and may issue Read/Write commands.",
        "BREQ = 0, BREL = 1 → illegal sequence.",
        "Master always drives static and dynamic sync bits even when Monitor owns the bus.",
        "Master does not drive parity bit when Monitor owns bus, but it shall set NAK on parity error.",
        "Master is permitted to never release bus ownership (e.g. in a shipping device).",
        "If Monitor loses sync, command will default to PING with BREQ cleared and Master will reclaim ownership.",
    ]
    f["clockstop_compliance"] = [
        "ClockStopMode0 is mandatory — Slave keeps context and restarts immediately on wake.",
        "ClockStopMode1 is optional — Slave may lose context, requires re-enumeration on wake.",
        "Master can program which Slaves are allowed to wake the bus.",
        "Wake-Up High pulse on SoundWire_Data shall be ≥ 2× minimum BitSlot duration.",
    ]
    f["transport_compliance"] = [
        "Per-Port Transport Test Modes Static0, Static1, and PRBS are mandatory — Slave shall implement all three.",
        "PRBS receiver shall synchronize within ≤ 8 bits; PRBS_error shall raise IntStat_Test_Fail on mismatch.",
        "PCM and PDM payload modes shall be supported with the Block-Per-Port and Block-Per-Channel transport modes.",
        "Grouping up to 4 successive samples is required for PDM and optional for PCM.",
        "Stream aggregation: channels must be enabled on all Devices with a common bank switch; Source and Sink ports must share the same SampleInterval; 'smart' bit allocation with no spacing between ports.",
    ]
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L17 channel signal catalog
# ----------------------------------------------------------------------
def _apply_l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["channels"] = [
        {"name": "SoundWire_Clock",
         "direction_master": "output (Push-Pull); the single Master drives the Clock continuously while the bus is active.",
         "direction_slave":  "input only — Slaves never drive SoundWire_Clock; there is no Slave clock-stretching.",
         "purpose": "Provides the bus Clock used by all Slaves and optional Monitor. Maximum 13 MHz typical (can be faster in restricted geometries); audio-friendly natural frequencies are 9.6 MHz, 12 MHz, 12.288 MHz. Clock can be paused via ClockStop (Mode 0 mandatory, Mode 1 optional).",
         "active_levels": "Push-Pull 0/1 normally; held Low (parked) during ClockStop.",
         "idle_level": "Static Low during ClockStop; otherwise active square-wave at programmed natural-clock frequency."},
        {"name": "SoundWire_Data (Lane 0)",
         "direction_master": "bidirectional — Master drives Control Word in Column 0 Rows 0..47 and pulses for assigned Source-port BitSlots; Modified-NRZI encoded.",
         "direction_slave":  "bidirectional — Slaves drive their per-Slave status bits, Read Data responses, audio payload for assigned Source-port BitSlots, and PREQ.",
         "purpose": "Carries the embedded 48-bit Control Word + audio Payload (PCM, PDM, raw DATA, BRA blocks) + PHY arbitration. Modified-NRZI: Logic 1 = active level change, Logic 0 = passive unchanged level held by bus-keeper. DDR — two BitSlots per Clock period.",
         "active_levels": "Push-Pull when actively driven; otherwise bus-keeper-held last level.",
         "idle_level": "Whatever the bus-keeper last latched; explicitly Low during the Stopping Frame and ClockStop park."},
        {"name": "SoundWire_Data Lane 1..7 (optional)",
         "direction_master": "bidirectional — used when extra payload bandwidth is needed; routed per Port via dynamic switch.",
         "direction_slave":  "bidirectional — Slave may drive its assigned Source-port BitSlots on any allocated lane.",
         "purpose": "Optional additional Data lanes for higher aggregate bandwidth. Lane 0 is shared between all devices (Col 0 Rows 0..47 reserved for Command Word). Lanes 1..7 may be shared or private to a group of devices; for device-to-device lanes a bus-keeper must be enabled on one of the devices. No restrictions on Lane 1..7 — all bits including Col 0 can be used.",
         "active_levels": "Push-Pull when driven; bus-keeper-held otherwise.",
         "idle_level": "Bus-keeper-held last value."},
    ]
    f["global_signals"] = [
        {"name": "VDD",          "purpose": "Supply voltage (1.2 V or 1.8 V typical) for SoundWire I/O drivers."},
        {"name": "GND",          "purpose": "Common ground reference for all devices on the bus."},
        {"name": "Bus-Keeper",   "purpose": "Required active circuit (typically on Master) that weakly holds the last driven level on SoundWire_Data; can be disabled via M_KeeperOff PHY Test Mode for replacement by external test equipment."},
    ]
    f["channel_counts"] = {
        "data_lanes_min": 1,
        "data_lanes_max": 8,
        "clock_lines":    1,
        "external_pins_total_min": 2,
        "external_pins_total_max": 9,
        "supply_pins":    2,
        "device_address_field_width_bits": 4,
        "max_slaves":     11,
        "max_ports_per_slave": 14,
        "max_channels_per_port": 8,
        "control_word_width_bits": 48,
        "control_word_rows":      48,
    }
    f["ordering_rules"] = {
        "bit_ordering_in_frame":  "Bits are transmitted serially in a column-major-within-row bitstream traversing the 2-D Frame (each row's columns are traversed in order, then advance to next row).",
        "control_word_position":  "Always the first 48 rows of Column 0 of every Frame.",
        "ddr_rule":               "Two BitSlots per Clock period (rising + falling edge).",
        "block_per_port_ordering": "All channels of a port packed lowest-to-highest channel as a single data chunk per Sample Interval.",
        "block_per_channel_ordering": "Each channel in an individual chunk with Block_Offset + Sub_Block_Offset; allows 'holes' in bit allocation reclaimable by other streams (e.g. 48 kHz stereo same pattern as 96 kHz mono).",
    }
    f["dependency_graph"] = {
        "common_rule":     "Master drives SoundWire_Clock continuously (except ClockStop); Slaves sample SoundWire_Data on both Clock edges; all devices observe the 8+1-bit Static + 4-bit Dynamic CRC sync to lock Frame boundaries.",
        "data_dependency": "PING/READ/WRITE in Control Word → addressed Slave decodes during same Frame → Slave responds in next Frame's Command Status / Read Data payload field (1-frame round-trip for READ).",
        "no_slave_clock_drive": "Slaves cannot delay the bus via SoundWire_Clock; the only sequencing tools are the CP_SM / CSP_SM Prepare/Activate state machines, Channel Activation gating, and Bank Switch synchronized to the next SSP tick.",
    }
    f["handshake_pairs"] = [
        {"name": "ADDR_PING_STATUS", "from": "Each Slave",     "to": "Master", "rule": "Slave drives its three-state status (Not Attached / Attached / Alert) at its assigned Device Number position in every PING frame."},
        {"name": "READ_RESPONSE",    "from": "Addressed Slave","to": "Master", "rule": "In the Frame after a READ command, addressed Slave drives the 8-bit Read Data payload + Command Status ACK; on parity error → NAK; on non-existent / not-attached / reserved register → Command_Ignored."},
        {"name": "WRITE_RESPONSE",   "from": "Addressed Slave","to": "Master", "rule": "In the Frame after a WRITE command, addressed Slave drives Command Status ACK / NAK / Command_Ignored."},
        {"name": "ASYNC_READY_BITS", "from": "Source + Sink Ports", "to": "Bus", "rule": "Each sample carries 2-bit preamble (RX-Ready from Sink, TX-Ready from Source); data only transmitted when both Ready."},
        {"name": "BREQ_BREL",        "from": "Monitor (BREQ) + Master (BREL)", "to": "Bus", "rule": "Monitor Command Word ownership arbitration; BREQ=0 = Master owns; BREQ=1, BREL=1 = Monitor owns; BREQ=0, BREL=1 = illegal."},
        {"name": "WAKE_HIGH",        "from": "Slave (or Master)", "to": "Bus", "rule": "Wake-Up High on SoundWire_Data for ≥ 2× minimum BitSlot duration during ClockStop park; Master resumes Clock thereafter."},
    ]
    f["channel_protocol_layering"] = {
        "phy_layer":             "Modified-NRZI DDR with bus-keeper; tDZ_Data_Max < tZD_Data_Min; tOH_Data_Min ensures bus-keeper snaps to new value; PHY test modes (M_DataOff / M_ClockDataOff / M_AllOff / M_KeeperOff / M_LowLow / M_LowHigh) supported by Master.",
        "frame_layer":           "Configurable 2-D NumCols × NumRows Frame; first 48 rows of Col 0 = Control Word; remaining BitSlots carry payload partitioned into per-Port Transport Sub-Frames.",
        "transport_layer":       "Per-Port HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset; Block-Per-Port vs Block-Per-Channel; Isochronous vs Asynchronous (RX-Ready/TX-Ready handshake); per-Port Transport Test Modes Static0/Static1/PRBS mandatory.",
        "command_layer":         "Embedded in Control Word — PING, READ (16-bit addr, 8-bit payload), WRITE (16-bit addr, 8-bit payload), BRA on DP0 (~20 Mbit/s).",
        "management_layer":      "Enumeration via 48-bit SCP_Device0..5 + hardware arbitration at Device 0; banked SCP_FrameCtrl0/1 for synchronized reconfiguration; ClockStop / ClockStopPrepare; Channel Prepare; Monitor BREQ/BREL arbitration.",
    }
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L18 interconnect topology
# ----------------------------------------------------------------------
def _apply_l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["topology_type"] = (
        "Multi-drop 2-pin DDR bus (SoundWire_Clock + SoundWire_Data "
        "Lane 0) with optional Data Lanes 1..7 for higher aggregate "
        "bandwidth. Single Master per bus; up to 11 Slave Devices; "
        "optional Monitor (test equipment) snooping and occasionally "
        "taking over via BREQ/BREL.")
    f["supported_topologies"] = [
        {"name": "AP Direct-Attach",
         "description": "Application Processor Master drives multiple ADC / DAC Slaves directly on a single Clock + Data tree. Webinar slide 'Example topologies' top-left example."},
        {"name": "Bridges, Inter-Chip Link",
         "description": "Application Processor Master ↔ Bridge Slave (Master on the other side) ↔ downstream ADC/DAC Slaves; allows reach extension to BT FM Radio chip. Webinar slide 'Example topologies' bottom-left."},
        {"name": "Inter-Chip Link with Multi-Lane Support",
         "description": "Application Processor Master ↔ Audio Codec Slave with Data[0]..Data[2] separate Data lanes; BT FM Radio + DSP on additional lanes. Webinar slide 'Example topologies' right."},
        {"name": "Functional Partitioning",
         "description": "Application Processor with two Master instances driving disjoint Slave groups (e.g. one Master for input ADCs, one for output DACs). Webinar slide 'Example topologies (2)' left."},
        {"name": "Routing / Use-Case Partitioning",
         "description": "Independent Master pairs each owning a separate Clock + Data tree for different audio use cases. Webinar slide 'Example topologies (2)' right."},
        {"name": "Shared PHY",
         "description": "Module-level integration where pins are shared — Master Digital Interface plus Slave Digital Interfaces feed a single shared PHY block providing external Clock/Data pads. Webinar slide 'Shared and virtual PHY' left."},
        {"name": "Virtual PHY",
         "description": "Pins are NOT visible externally — SoundWire used inside a module; an OR-gate / clock-doubler virtual PHY provides the bus to internal digital interfaces. Webinar slide 'Shared and virtual PHY' right."},
        {"name": "Monitor-Augmented Bus",
         "description": "Any of the above plus a Monitor (test equipment) that snoops the bus and may temporarily take over via BREQ/BREL arbitration."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Master",
         "responsibilities": [
             "Provides Clock and sync pattern on Data line.",
             "Handles all bus management, bit allocation, Frame Shape, ClockStop.",
             "Drives Control Word in Col 0 Rows 0..47 of every Frame.",
             "Sends PING, READ, WRITE, BRA/BTP, ClockStopNow commands.",
             "Performs enumeration of Slaves by reading SCP_Device0..5 (48-bit value) and assigning Device Numbers 1..11.",
             "Performs synchronized bank switch (SCP_FrameCtrl0/1) for safe reconfiguration.",
             "Drives Parity bit (or sets NAK on parity error while Monitor owns bus).",
             "Configures per-Port HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset.",
             "Manages Wake-from-ClockStop permissions per-Slave.",
         ]},
        {"role": "Slave",
         "responsibilities": [
             "Typically audio peripheral (microphone, codec, smart amplifier, smart speaker).",
             "1..11 Slaves connected to Master over multi-drop bus.",
             "Verify Static + Dynamic sync for 16 consecutive frames before declaring Attached.",
             "Drive own three-state status (Not Attached / Attached / Alert) in PING frames.",
             "Respond ACK / NAK / Command_Ignored to READ / WRITE commands.",
             "Drive Read Data payload in next Frame after READ.",
             "Drive audio payload in assigned Source-Port BitSlots; receive payload in assigned Sink-Port BitSlots.",
             "Maintain hardware-mandatory 48-bit enumeration value in SCP_Device0..5.",
             "Ability to signal Interrupt condition via PREQ / Alert status / DPst_IntStat.",
             "Ability to wake-up the system (subject to Master's permission bitmap).",
             "Never drive SoundWire_Clock.",
         ]},
        {"role": "Monitor",
         "responsibilities": [
             "Test equipment, in snooping/analyzer mode most of the time.",
             "Can temporarily take over the bus via BREQ/BREL arbitration.",
             "Issue PING / READ / WRITE commands when owning the Command Word.",
             "If Monitor loses sync, command will default to PING with BREQ cleared and Master will reclaim ownership.",
             "Master always drives static and dynamic sync bits and may set NAK on parity error even when Monitor owns the Command Word.",
         ]},
        {"role": "Bridge Slave",
         "responsibilities": [
             "Acts as Slave on the upstream bus and as Master on a downstream secondary bus.",
             "Used for reach extension and topology hierarchy.",
         ]},
    ]
    f["interconnect_role"] = (
        "There is no central protocol-layer interconnect — the bus is "
        "a flat multi-drop shared medium with one Clock + one (or "
        "more) Data lanes. Bridge Slaves can extend reach by acting "
        "as Master of a downstream bus. From the application firmware "
        "perspective the bus behaves as a single shared 2-pin link "
        "with embedded command and data carrying both audio and "
        "control.")
    f["ordering_guarantees"] = {
        "within_a_frame":   "Bits are transmitted serially in column-major-within-row bitstream order across the 2-D Frame; the Control Word is always at Col 0 Rows 0..47.",
        "across_frames":   "Each Read/Write command has a 1-frame round-trip (response in next Frame's Command Status / Read Data field).",
        "across_ports":     "Stream aggregation requires same SampleInterval on all participating Ports + common bank-switch event; 'smart' bit allocation places port BitSlots adjacently with no spacing.",
        "across_buses":     "No fairness guarantee across multiple SoundWire buses; they are independent. SSP can be used to maintain alignment between multiple links with different frame rates.",
    }
    f["memory_vs_peripheral_regions"] = (
        "Not a memory bus. SoundWire's 16-bit register address space "
        "is per-Slave: normative 0x0000-0x0FFF, device-class reserved "
        "0x1000-0x17FF, implementation-defined 0x2000-0xFFFF, paged "
        "implementation 0x10000-0x3FFFFFFF.")
    f["slave_classification"] = {
        "audio_input_slave":   "Microphone / ADC peripheral driving Source Ports.",
        "audio_output_slave":  "Speaker / DAC / amplifier peripheral receiving Sink Ports.",
        "codec_slave":         "Combined ADC + DAC + audio DSP; mix of Source and Sink Ports.",
        "smart_amplifier":     "Class-D output stage with I/V sensing feedback Source Port + audio input Sink Port.",
        "bt_fm_radio":         "Bluetooth / FM Radio with audio streams (typically two Data lanes Data[0], Data[1]).",
        "dsp_slave":           "Audio DSP performing post-processing; both Source and Sink Ports.",
        "bridge_slave":        "Slave that further routes to a downstream sub-bus.",
        "monitor":             "Test equipment for development / debug / certification.",
        "wakeable_slave":      "Slave that may initiate wake-up from ClockStop; subject to Master's wake-permission bitmap.",
        "interrupt_capable":   "Every Slave can raise interrupts; reflected as Alert status in PING + SCP_IntStat_* / DPst_IntStat registers.",
    }
    f["default_signal_values_evidence_tables"] = [
        "PHY Test Modes table — Slide 'PHY Test modes' (Normal / M_DataOff / M_ClockDataOff / M_AllOff / M_KeeperOff / M_LowLow / M_LowHigh).",
        "Interrupt registers table — Slide 'Interrupt registers' (SCP_IntStat_1/2/3, DPst_IntStat).",
        "Frame Shapes — Slide 'Frame shapes' (48x4, 64x4, 50x16).",
        "Transport Sub-Frame, Payload Transport Window — Slides 'Transport (2)' and 'Transport (3)'.",
        "Block-Per-Port and Block-Per-Channel — Slides 'Transport (4)' and 'Transport (5)'.",
        "Multi-lane allocation — Slide 'Transport (7): multi-lane'.",
        "Monitor arbitration BREQ/BREL truth table — Slide 'Monitor arbitration'.",
        "Pro/Con vs other interfaces — Slide 'Comparison with other interfaces'.",
    ]
    f["addressing_topology"] = {
        "device_number_field_width_bits": 4,
        "device_0":            "Reserved for un-enumerated Slaves; used during enumeration handshake.",
        "device_1_to_11":      "Up to 11 single-Slave Device Numbers.",
        "group_addresses":     "Address one configured group of Slaves; group membership is held in Slave registers.",
        "broadcast_15":        "Addresses all Slaves on the bus.",
        "register_address_bits": 16,
    }
    f["bus_management_overview"] = {
        "current_master":      "Exactly one Master per bus.",
        "monitor_ownership":   "Optional Monitor may own the Command Word transiently via BREQ=1 AND BREL=1; Master can reclaim by clearing BREL.",
        "bank_switch":         "Atomic synchronized reconfiguration via SCP_FrameCtrl0/1 toggle at the next SSP tick.",
        "clockstop_modes":     "Mode 0 mandatory (context retained); Mode 1 optional (context may be lost).",
        "wake_permission":     "Master programs which Slaves are allowed to wake the bus.",
        "ssp_safe_reconfig":   "SSP tick (≥ once every 100 ms) defines safe time positions for bus reconfiguration.",
    }
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L19 constraints / PDK
# ----------------------------------------------------------------------
def _apply_l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["constraints_pdk_present"] = False
    f["notes"] = (
        "MIPI SoundWire is a wire-level audio bus specification — it "
        "does not mandate a PDK, process technology, cell library, or "
        "floorplan. Implementations are realized in concrete "
        "SoundWire Master / Slave / Monitor IP blocks targeting a "
        "wide variety of mobile and mobile-influenced CMOS processes. "
        "The specification only constrains the I/O electrical "
        "behavior at the supply rails 1.2 V or 1.8 V, the maximum bus "
        "Clock frequency of 13 MHz typical (faster in specific "
        "settings such as a single Slave close to the Master), and "
        "the PHY-level handover parameters (tDZ_Data_Max < "
        "tZD_Data_Min, tOH_Data_Min, V_OH_Data_Min / V_OL_Data_Max, "
        "V_TP_Clock / V_TN_Clock envelopes). Detailed numeric "
        "thresholds, jitter budgets, and rise/fall-time limits are "
        "pinned only in the gated v1.0 specification; the public "
        "webinar explicitly notes 'No requirements on jitter (ppm, "
        "ps) in SoundWire spec'. Bus-keeper drive strength, pad "
        "capacitance limits, and PCB trace impedance are "
        "implementation- and system-design concerns.")
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L20 DFT / scan topology
# ----------------------------------------------------------------------
def _apply_l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["dft_scan_topology_present"] = False
    f["notes"] = (
        "MIPI SoundWire is a wire-level audio bus protocol and does "
        "not specify SoC-level DFT (scan, BIST, JTAG, MBIST) "
        "topology. Protocol-level test infrastructure is limited to: "
        "(a) per-Port Transport Test Modes Static0 / Static1 / PRBS "
        "(8-bit LFSR, 255-bit maximal-length sequence, TX init "
        "Q[8:1]=0xFF, RX init Q[8:1]=0xD2, receiver synchronizes in "
        "≤ 8 bits, PRBS_error → IntStat_Test_Fail interrupt), (b) "
        "Master-side PHY Test Modes (Normal / M_DataOff / "
        "M_ClockDataOff / M_AllOff / M_KeeperOff / M_LowLow / "
        "M_LowHigh) for external master or test equipment to drive "
        "Data/Clock instead of the Master and to replace the master "
        "bus-keeper, and (c) the Monitor device class — test "
        "equipment that snoops the bus and may temporarily inject "
        "Read/Write commands via BREQ/BREL arbitration. Concrete "
        "SoundWire IP blocks implement their own DFT in the SoC "
        "integration; SoundWire merely provides the bus-side "
        "observability/injection hooks above.")
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L21 power intent
# ----------------------------------------------------------------------
def _apply_l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["power_intent_present"] = (
        "partial — the public webinar describes the spec-defined "
        "low-power mechanisms (ClockStop Mode 0 / Mode 1, Wake-Up "
        "High pulse, ClockStopPrepare CSP_SM, master-programmable "
        "Slave wake permission) and the supply rails (1.2 V / 1.8 V); "
        "UPF/CPF power-intent files are implementation-specific and "
        "not pinned by the SoundWire v1.0 spec.")
    f["supply_rails"] = [
        {"name": "VDD_IO", "voltage_V_set": [1.2, 1.8],
         "purpose": "Powers the SoundWire I/O drivers (Clock and Data lanes) and the bus-keeper. Bus is single-domain — all devices share the same VDD_IO."},
    ]
    f["low_power_modes_summary"] = [
        {"mode": "Active",            "description": "Bus running at programmed natural-clock frequency (9.6 / 12 / 12.288 MHz); Slaves driving status, audio payload, and Read responses."},
        {"mode": "ClockStop Mode 0",  "description": "Mandatory low-power mode. Master issues 'ClockStopNow' command + Stopping Frame; Master parks Clock and Data Low. Slave retains all context (registers, Device Number, programmed transport, Interrupt state). On wake, Slave resumes immediately."},
        {"mode": "ClockStop Mode 1",  "description": "Optional very-low-power mode. Slave may lose context, enters very-low-power state. On wake the Slave is at Device Number 0 with Interrupt masks disabled and Master must re-enumerate. Removes the need for an extra GPIO for e.g. headphone-jack-detection wake."},
        {"mode": "Wake-Up",           "description": "Wake-Up may be Master- or Slave-initiated. Slave wakes by driving SoundWire_Data High for ≥ 2× minimum BitSlot duration; Master detects and resumes Clock. Master can program which Slaves are allowed to wake the bus."},
    ]
    f["clockstop_prepare_csp_sm"] = {
        "purpose": "Support clean stopping of the Clock for ClockStop entry; analogous to Channel Prepare/Activate.",
        "states":  ["NotReady (NF=0, P=0)", "Preparing (NF=1, P=1)", "Ready (NF=0, P=1)", "De-preparing (NF=1, P=0)"],
        "simplified_form": "Single 'Ready' state — for Slaves that can stop immediately without enabling an alternate clock source.",
        "rationale": "Slave may need time to enable an alternate clock source (so internal state can persist while SoundWire_Clock is off) or be ready immediately.",
    }
    f["power_management_observations"] = [
        "Clock can be paused (ClockStop) — main lever for system-level audio sub-system power savings.",
        "ClockStop allows Slaves to enter low-power state.",
        "ClockStopMode1 removes the need for extra GPIO for jack detection and similar wake events.",
        "Wake permission per-Slave bitmap allows Master to gate which Slaves can wake the bus, preventing unwanted wakes from non-critical Slaves.",
        "Bank-switch reconfiguration (SCP_FrameCtrl0/1) is power-aware — channels not in use can be deactivated by toggling the appropriate Prepare bits in the shadow bank, then committing via bank switch.",
        "Sample Interval and Frame Shape can be dynamically reduced (smaller Frame Shape, fewer columns) to reduce average bus toggling and hence dynamic power.",
    ]
    f["soc_dependent_power_decisions"] = [
        "Power-domain partitioning between SoundWire IP, audio codec, microphones, smart amplifiers (UPF/CPF specifications are vendor-specific).",
        "DVFS / clock-gating of the Master controller and DMA when the bus is in ClockStop.",
        "Always-on / always-listening domain for microphones using ClockStopMode1 wake-on-voice-activity.",
        "Retention strategy across ClockStopMode0 (full retention) vs Mode 1 (power-off + re-enumeration on wake).",
    ]
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L22 verification plan
# ----------------------------------------------------------------------
def _apply_l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["verification_plan_present"] = (
        "partial — the public webinar enumerates the spec-mandated "
        "test surfaces (PHY Test Modes per Master pin table, "
        "Transport Test Modes Static0/Static1/PRBS per Port, "
        "normative CP_SM and CSP_SM state machines, enumeration "
        "arbitration, ClockStop modes, Monitor BREQ/BREL "
        "arbitration) that any compliant SoundWire IP must verify; "
        "the formal compliance test suite is defined in the gated "
        "v1.0 spec.")
    f["verification_categories"] = [
        {
            "name": "PHY-Layer Verification",
            "tests": [
                "DDR sampling on rising AND falling SoundWire_Clock edges.",
                "Modified-NRZI encoding correctness — Logic 1 = active change, Logic 0 = passive unchanged level held by bus-keeper.",
                "Bus-keeper presence and ability to hold the last driven level for the maximum specified duration.",
                "Three data handover cases: #1 high-Z → driving, #2 driving → driving (across two devices), #3 driving → high-Z; tDZ_Data_Max < tZD_Data_Min margin verification.",
                "tOH_Data_Min self-timed turn-off ensuring far-end bus-keeper snaps to new value.",
                "Master PHY Test Modes coverage: Normal / M_DataOff / M_ClockDataOff / M_AllOff / M_KeeperOff / M_LowLow / M_LowHigh.",
                "High-PHY mode handover sequence; mode identification via one bit of static sync word.",
                "Clock frequency sweep across natural-clock set {9.6, 12, 12.288 MHz} and up to 13 MHz typical.",
            ],
        },
        {
            "name": "Frame-Layer Verification",
            "tests": [
                "Frame Shape support — all valid Cols ∈ {2,4,6,8,10,12,14,16} × valid Rows subset of [48,256].",
                "Pairwise Frame Shape handling by Slaves (Slave is required to handle pairwise combinations).",
                "Static 8+1-bit sync word lock — 1-bit mode identification (Normal vs High-PHY).",
                "Dynamic 4-bit CRC pattern with 15-frame period verification.",
                "Slave declares 'Attached' only after 16 consecutive frames of valid Static + Dynamic sync.",
            ],
        },
        {
            "name": "Command-Layer Verification",
            "tests": [
                "PING command — per-Slave Not Attached / Attached / Alert status; SSP bit at ≥ 1 per 100 ms; Monitor BREQ/BREL arbitration.",
                "READ / WRITE command — 16-bit address + 8-bit payload; addressing Device 1..11, group, broadcast (0xF); response in next Frame.",
                "Command Status — ACK / NAK / Command_Ignored coverage.",
                "Parity computation over Parity Calculation Window (BitSlot[44,1] previous → BitSlot[44,0] current); 1-frame delay reporting.",
                "Bus-clash detection via parity on physical level.",
                "Bulk Register Access on DP0 — Header + payload + CRC; bidirectional; ≈ 20 Mbit/s.",
                "Register write semantics — takes effect at end of frame on success; no action on Command Failed.",
                "Banked register behavior — shadow bank prepared, atomic switch via SCP_FrameCtrl0/1 toggle at next SSP.",
            ],
        },
        {
            "name": "Enumeration & Reset Verification",
            "tests": [
                "48-bit enumeration value stored in SCP_Device0..5; Master reads via consecutive READs.",
                "Slave reports Attached at Device 0 until assigned a non-zero Device Number 1..11.",
                "Hardware arbitration when multiple Slaves contend at Device 0 — Slave with highest 48-bit enumeration value wins.",
                "Master redoes enumeration until no Slave reports Attached at Device 0.",
                "Hard-Reset by Power-On — Device Number lost, Interrupt masks disabled.",
                "Hard-Reset by Bus Reset (Master drives 4096 Logic1 transitions on Data) — global.",
                "Hard-Reset by Device Reset (Master writes Reset bit in SCP_Ctrl) — per-Slave.",
                "Soft Reset (Slave detects two sync errors) — Device Number lost, Interrupt Status MAINTAINED for debug.",
            ],
        },
        {
            "name": "Transport-Layer Verification",
            "tests": [
                "Per-Port HStart, HStop, SampleInterval, BlockOffset, SubBlockOffset programmability.",
                "Block-Per-Port (all channels packed lowest-to-highest in one chunk).",
                "Block-Per-Channel (individual chunks; Block_Offset + Sub_Block_Offset; 'holes' reclaimable).",
                "Sample Interval updates correctly when Frame Shape or sampling frequency changes; not multiple of row size; not dependent on channel count.",
                "PDM grouping (up to 4 successive samples) — mandatory for PDM, optional for PCM.",
                "Isochronous (Normal) mode at regular audio playback rates.",
                "Asynchronous modes — TX-controlled, RX-Controlled, Full-Async with 2-bit RX-Ready/TX-Ready preamble.",
                "Stream aggregation — Source and Sink Ports with different parameters but shared SampleInterval and bank-switch event; not possible in Async modes.",
                "Per-Port Transport Test Modes Static0 / Static1 / PRBS — all 3 mandatory per Port; PRBS receiver synchronizes in ≤ 8 bits; PRBS_error → interrupt.",
            ],
        },
        {
            "name": "State-Machine Verification",
            "tests": [
                "Channel Prepare CP_SM full 4-state form (Stopped → Preparing → Ready → De-preparing) with NF/P bit encoding.",
                "Channel Prepare CP_SM simplified single-Ready form for Ports that are ready immediately.",
                "ClockStopPrepare CSP_SM full 4-state form (NotReady → Preparing → Ready → De-preparing).",
                "ClockStopPrepare CSP_SM simplified single-Ready form.",
                "Software unmask of DPst_IntStat Port Ready interrupt for CP_SM Ready notification.",
            ],
        },
        {
            "name": "ClockStop & Wake Verification",
            "tests": [
                "ClockStopNow command + Stopping Frame (Master owns all BitSlots; parks Clock and Data Low).",
                "ClockStopMode0 mandatory: context retained, immediate resume.",
                "ClockStopMode1 optional: context may be lost, re-enumeration on wake.",
                "Wake-Up High pulse ≥ 2× minimum BitSlot duration on SoundWire_Data.",
                "Master-programmable Slave-wake permission bitmap.",
                "Re-enumeration on wake from Mode 1.",
            ],
        },
        {
            "name": "Interrupt & Status Verification",
            "tests": [
                "Hierarchical SCP_IntStat_1 / _2 / _3 cascade with Parity / Bus Clash / ImpDef + per-Port cascade bits.",
                "Per-Port DPst_IntStat — Test Fail / Port Ready / ImpDef1..3.",
                "32-frame maximum latency from interrupt generation to Slave reporting Alert in PING.",
                "PING Alert status triggers Master to Read SCP_IntStat_* for diagnosis.",
                "PREQ wake signal in Control Word.",
            ],
        },
        {
            "name": "Monitor Arbitration Verification",
            "tests": [
                "BREQ=0 → Master owns; BREQ=1, BREL=0 → Monitor requesting; BREQ=1, BREL=1 → Monitor owns; BREQ=0, BREL=1 → illegal.",
                "Master always drives static + dynamic sync; Master does not drive parity bit when Monitor owns the bus but sets NAK on parity error.",
                "Master can reclaim ownership by clearing BREL.",
                "Master is permitted to never release bus ownership.",
                "Recovery: if Monitor loses sync, command defaults to PING with BREQ cleared and Master reclaims ownership.",
            ],
        },
        {
            "name": "Multi-Lane Verification",
            "tests": [
                "Lane 0 shared between all devices; Col 0 Rows 0..47 reserved for Command Word.",
                "Lanes 1..7 may be shared or private; bus-keeper enabled on one device for device-to-device lanes.",
                "No restrictions on Lane 1..7 — Col 0 may be used.",
                "Dynamic switch between lanes per Port.",
            ],
        },
    ]
    d["fields"] = f
    _write(p, d)


# ----------------------------------------------------------------------
# L23 security requirements
# ----------------------------------------------------------------------
def _apply_l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["security_requirements_present"] = False
    f["notes"] = (
        "MIPI SoundWire v1.0 is a wire-level audio interface "
        "specification with no built-in confidentiality, integrity, "
        "or authentication requirements. SoundWire is a multi-drop "
        "broadcast medium — every device (Slaves and Monitor) on the "
        "bus can snoop SoundWire_Data and decode all Control Words, "
        "audio payload, and Read/Write traffic. The Parity bit per "
        "Frame and the Bulk Register Access CRC provide only error "
        "detection (single-bit and a short CRC respectively), not "
        "cryptographic integrity or authentication. The 48-bit "
        "hard-coded enumeration value (SoundWire spec version + "
        "UniqueID + MIPI ManufacturerID + PartID + Class) provides "
        "device identity but is not an anti-counterfeiting token — "
        "it can be cloned by any device that wishes to impersonate. "
        "Slaves that need to be authenticated to the system, or "
        "audio streams that must be encrypted, require higher-layer "
        "security mechanisms layered on top of SoundWire (e.g. "
        "DRM-protected audio streams over BRA payload).")
    f["no_built_in_authentication"]  = True
    f["no_built_in_confidentiality"] = True
    f["no_built_in_integrity_beyond_parity_and_bra_crc"] = True
    f["ipr_status_note"] = (
        "The MIPI SoundWire specification is gated to MIPI Alliance "
        "members; the public webinar used here as substitute "
        "documentation does not include IPR licensing terms. "
        "Implementers should consult MIPI directly for membership "
        "and licensing obligations.")
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
def is_soundwire(blob: str) -> bool:
    """Content-only `soundwire` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline, with a FOREIGN-PRIMARY DEFER
    bolted on top (mirrors `is_mipi`'s defer doctrine).

    The structural signature below (SoundWire + Master/Slave/Stream/Data
    Port) is necessary but NOT sufficient: the A2B (Automotive Audio Bus)
    spec is an audio-distribution bus that explicitly tunnels and compares
    itself to SoundWire / I2S, so its L-docs carry incidental "SoundWire"
    + "Master"/"Slave"/"Stream" tokens that trip the loose branches below
    and let the generic SoundWire synth fire on an A2B-primary spec.

    Guard (general, content-only, no chip/SKU/benchmark-name literal as
    detection logic): if the blob's DOMINANT subject is A2B, defer (False).
    A2B has a unique structural signature absent from every real SoundWire
    benchmark: a twisted-pair daisy-chain distributing audio+control+POWER,
    a main/sub node hierarchy with node discovery, a sample-rate-locked
    superframe with downstream+upstream regions, phantom power over the bus,
    and an AD24xx transceiver. Mirrors `is_a2b`'s own A2B-structure quorum.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is A2B, not SoundWire).
    # A2B-only structure: twisted-pair daisy chain + main/sub node hierarchy +
    # superframe-down/up + (phantom/bus power OR AD24xx transceiver). These
    # tokens are absent from every real SoundWire spec (count 0). ---
    _a2b_name = ("automotive audio bus" in low or "a2b" in low)
    _a2b_line = (("twisted pair" in low or "twisted-pair" in low)
                 and ("daisy chain" in low or "daisy-chain" in low
                      or "daisy chained" in low or "daisy-chained" in low))
    _a2b_nodes = (("main node" in low or "master node" in low)
                  and ("sub node" in low or "slave node" in low))
    _a2b_superframe = ("superframe" in low
                       and "downstream" in low and "upstream" in low)
    _a2b_power = ("phantom power" in low
                  or ("bus power" in low and _a2b_line))
    _a2b_xcvr = ("ad2410" in low or "ad2420" in low or "ad2425" in low
                 or "ad242x" in low or "ad24xx" in low)
    a2b_primary = (
        _a2b_line and _a2b_nodes and _a2b_superframe
        and (_a2b_power or _a2b_xcvr or _a2b_name))
    if a2b_primary:
        return False

    # --- STRUCTURAL SoundWire signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("SoundWire" in blob
            and ("MIPI" in blob
                 or "Slave" in blob
                 or "PHY" in blob))
        or ("SoundWire" in blob and "Master" in blob
            and "Slave" in blob)
        or ("SoundWire" in blob and "Stream" in blob
            and "Data Port" in blob))
