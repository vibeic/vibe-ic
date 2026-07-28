"""Automotive Audio Bus (A2B) protocol synth helper.

ic_class-gated overlay for the A2B structural signature: a high-bandwidth,
bidirectional, digital audio bus from Analog Devices (AD24xx family — AD2410 /
AD2420 / AD2425 / AD242x) that distributes multichannel digital audio, control
data, AND power over a SINGLE unshielded twisted pair (UTP) in a DAISY-CHAIN
(line) topology. One A2B main node (master), connected to a host SoC, drives a
daisy-chained line of up to ten A2B sub nodes (slaves). The bus is organized
into a periodic SUPERFRAME locked to the audio sample rate (e.g. 48 kHz),
divided into DOWNSTREAM and UPSTREAM portions, giving deterministic low latency
(~2 samples). A2B TUNNELS each node's local I2S/TDM audio + I2C control + GPIO +
interrupts over the bus, and delivers PHANTOM POWER (bus power) to downstream
nodes over the same twisted pair. Applies the Analog Devices A2B (AD24xx)
spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(single twisted-pair daisy chain + main/sub node discovery + sample-rate-locked
superframe with downstream/upstream + phantom power over bus + tunneled
I2S/TDM + I2C + AD24xx transceiver) read from the L-doc / input_doc CONTENT blob
only. It NEVER reads the input-document filename or the benchmark folder name,
and it does NOT fire on the bare token "a2b" alone — a structural quorum is
required.

Sibling disambiguation — A2B vs I2S, SoundWire, and S/PDIF (the audio family).
A2B, I2S, SoundWire and S/PDIF all move digital audio, but only A2B couples a
single-twisted-pair DAISY CHAIN + a MAIN/SUB node hierarchy with node DISCOVERY
and addressing + a sample-rate-locked SUPERFRAME (downstream + upstream) +
PHANTOM POWER over the bus + TUNNELED I2S/TDM and I2C + an AD24xx transceiver.
I2S is a direct 3-wire local link (SCK/WS/SD) between two chips with no daisy
chain, no discovery, no superframe, no power, no tunneling — I2S is what A2B
TUNNELS, it is not A2B. SoundWire is a multidrop MIPI bus with SoundWire-specific
framing / data ports and no twisted-pair-daisy-chain phantom-power AD24xx
transceiver. S/PDIF is a single biphase-mark coax/optical link with no node
discovery, no superframe regions, no phantom power, and no I2C/GPIO tunneling.
The detector DEFERS when the doc is I2S-primary, SoundWire-primary, or
S/PDIF-primary (the A2B-only structure absent), so it cannot false-fire on an
audio sibling.

Public entry: ``apply_a2b_synth(generated_docs_dir, is_a2b, a2b_ic_name)``.
Module-level ``is_a2b(blob)`` is the content-only detector.
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


# Sibling-specific keys that the audio-family synths (S/PDIF / I2S) and the
# I2C synth may have written into the base docs BEFORE the a2b synth runs.
# Because a2b runs last and FORCE-OVERWRITES, these orphan keys must be purged
# so the A2B gold does not carry S/PDIF / I2S content. Keyed by L-doc filename;
# values are (top_level_keys_to_delete, {parent_key: [nested_keys_to_delete]}).
_SIBLING_PURGE = {
    "L1_DATASHEET.json": (["original_release_date", "document_number",
                           "external_pin_count"], {}),
    "L2_FRS.json": (["iec_61937_encapsulation", "protocol_overview"], {}),
    "L3_CMD_PROTOCOL.json": (
        ["channel_status_word_layout_consumer", "iec_61937_encapsulation",
         "fis_format", "fis_types", "primitive_symbols",
         "oob_signaling_sequence", "command_header_format",
         "command_table_format", "prd_entry_format", "primitive_descriptions",
         "smp_functions", "transport_protocols", "ssp_frame_types",
         "connection_management", "primitives", "crc", "flow_control",
         "frame_format"], {},
    ),
    "L6_CONTROL_LOGIC.json": (
        ["biphase_mark_encoding_rule", "fsm_states_transmitter",
         "fsm_states_receiver", "default_ready_state_recommendation",
         "timing_dependency_rule", "configurations"], {}),
    "L8_RTL_CONSTANTS.json": (
        ["preamble_table_bmc_cells", "consumer_channel_status_byte_layout",
         "carrier_to_sample_rate_relationship", "voltage_levels",
         "key_constants_for_RTL_authoring", "supported_sample_rates_kHz",
         "default_signal_values_when_idle"],
        {"width_parameters": [
            "SPDIF_LINE_WIDTH", "SUBFRAME_BIT_WIDTH", "SUBFRAMES_PER_FRAME",
            "FRAMES_PER_BLOCK", "SUBFRAMES_PER_BLOCK", "PREAMBLE_BIT_FIELD_WIDTH",
            "PREAMBLE_BMC_CELL_WIDTH", "AUX_FIELD_BIT_WIDTH",
            "AUDIO_SAMPLE_BIT_WIDTH", "AUDIO_SAMPLE_BIT_WIDTH_24BIT_MODE",
            "V_BIT_WIDTH", "U_BIT_WIDTH", "C_BIT_WIDTH", "P_BIT_WIDTH",
            "CHANNEL_STATUS_WORD_BIT_WIDTH_PER_CHANNEL",
            "USER_DATA_WORD_BIT_WIDTH_PER_CHANNEL", "CHANNELS",
            "BMC_CELLS_PER_BIT", "BMC_CELLS_PER_SUBFRAME", "BMC_CELLS_PER_FRAME",
            "SPDIF_WIDTH", "LINE_WIDTH",
        ]},
    ),
    "L8_TIMING_WAVEFORM.json": (
        ["biphase_mark_code_waveform", "preamble_waveforms_bmc_cells",
         "subframe_timing", "frame_timing", "block_timing",
         "carrier_bit_rate_examples", "general_timing_rule",
         "electrical_levels"], {}),
    "L9_INTEGRATION_SPEC.json": (["default_signal_values_when_omitted"], {}),
    "L10_TEST_CASES.json": (["test_cases_present"], {}),
    "L12_BEHAVIORAL_SEQUENCES.json": (
        ["iec_61937_compressed_sequence", "channel_status_change_sequence",
         "typical_streaming_sequence", "lock_acquisition_sequence",
         "lock_loss_and_recovery_sequence"], {}),
    "L15_ENCODING_TABLES.json": ([], {"fields": [
        "biphase_mark_encoding_rule", "preamble_table",
        "subframe_field_layout_table", "channel_status_word_layout_consumer",
        "comparison_aes3_vs_spdif_table", "iec_61937_encapsulation_table",
        "frame_and_block_structure_table", "sample_frequency_code_table"]}),
    "L16_COMPLIANCE_PROPERTIES.json": ([], {"fields": ["min_clock_constraint"]}),
    "L17_CHANNEL_SIGNAL_CATALOG.json": ([], {"fields": [
        "channels", "global_signals", "channel_counts", "handshake_pairs",
        "dependency_graph", "ufm_channels", "ordering_rules"]}),
    "L18_INTERCONNECT_TOPOLOGY.json": ([], {"fields": [
        "ordering_guarantees", "axprot_polarity", "id_routing",
        "multi_copy_atomicity", "memory_vs_peripheral_regions",
        "slave_classification", "ultra_fast_mode_topology"]}),
    "L19_CONSTRAINTS_PDK.json": ([], {"fields": ["notes"]}),
    "L20_DFT_SCAN_TOPOLOGY.json": ([], {"fields": ["notes"]}),
    "L21_POWER_INTENT.json": ([], {"fields": ["low_power_modes_summary",
                                              "notes"]}),
    "L23_SECURITY_REQUIREMENTS.json": ([], {"fields": ["notes"]}),
}


def _purge_siblings(p: Path, d: dict) -> None:
    """Remove S/PDIF / I2S / I2C orphan keys an earlier sibling synth wrote."""
    spec = _SIBLING_PURGE.get(p.name)
    if not spec:
        return
    top_keys, nested = spec
    for k in top_keys:
        d.pop(k, None)
    for parent, subkeys in nested.items():
        node = d.get(parent)
        if isinstance(node, dict):
            for sk in subkeys:
                node.pop(sk, None)


def _has_word(low: str, *words: str) -> bool:
    """True if EVERY whitespace-delimited token/phrase appears as a word."""
    for w in words:
        if not re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
            return False
    return True


def _any_word(low: str, *words: str) -> bool:
    for w in words:
        if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
            return True
    return False


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

# Canonical A2B facts (Analog Devices A2B, AD24xx transceiver family).
_MAX_SUB_NODES = 10
_TYPICAL_SAMPLE_RATES_KHZ = [44.1, 48]
_MAX_AUDIO_CHANNELS_PER_DIRECTION = 32
_LATENCY_SAMPLES = 2
_TRANSCEIVERS = ["AD2410", "AD2420", "AD2425", "AD242x"]


def is_a2b(blob: str) -> bool:
    """Content-only A2B detector with an I2S / SoundWire / S/PDIF sibling MUTEX.

    Fire on the A2B structural signature: a single twisted-pair daisy-chain
    distributing audio + control + POWER, a main/sub (master/slave) node
    hierarchy with node discovery and addressing, a sample-rate-locked
    superframe with downstream + upstream portions, phantom power over the bus,
    tunneled I2S/TDM + I2C, and an AD24xx transceiver. DEFER when the doc is
    I2S-primary / SoundWire-primary / S/PDIF-primary with the A2B-only structure
    absent. Reads ONLY the spec text `blob` — never a filename or benchmark
    name, and never fires on the bare token "a2b" alone.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- A2B structural tokens (a quorum is required; no single token fires) ---
    name_token = _any_word(low, "a2b") or "automotive audio bus" in low
    twisted_pair = ("twisted pair" in low or "twisted-pair" in low
                    or _any_word(low, "utp")
                    or "unshielded twisted" in low)
    daisy_chain = ("daisy chain" in low or "daisy-chain" in low
                   or "daisy chained" in low or "daisy-chained" in low)
    # main/sub (master/slave) node hierarchy
    main_node = (("main node" in low or "master node" in low)
                 and ("sub node" in low or "sub nodes" in low
                      or "slave node" in low or "slave nodes" in low))
    discovery = ("node discovery" in low
                 or ("discovery" in low
                     and ("node address" in low or "sub node" in low)))
    # sample-rate-locked superframe with downstream + upstream regions
    superframe = "superframe" in low
    down_up = (("downstream" in low and "upstream" in low)
               and (superframe or "sample rate" in low or "sample period" in low))
    # phantom power / bus power over the same twisted pair
    phantom_power = ("phantom power" in low
                     or ("bus power" in low
                         and (twisted_pair or daisy_chain)))
    power_over_audio = (phantom_power
                        or (("power" in low)
                            and ("over the same" in low
                                 or "over the bus" in low)
                            and (twisted_pair or daisy_chain)))
    # tunneled local interfaces
    tunnels_i2s = (("i2s" in low or "tdm" in low)
                   and ("tunnel" in low or "tunnels" in low
                        or "tunneled" in low or "tunnelled" in low
                        or "tunneling" in low or "tunnelling" in low
                        or "over the bus" in low))
    tunnels_i2c = ("i2c" in low
                   and ("tunnel" in low or "tunnels" in low
                        or "tunneled" in low or "tunnelled" in low
                        or "tunneling" in low or "tunnelling" in low
                        or "over the bus" in low or "control" in low))
    transceiver = (_any_word(low, "ad2410", "ad2420", "ad2425")
                   or "ad242x" in low or "ad24xx" in low
                   or ("analog devices" in low and "transceiver" in low
                       and (daisy_chain or superframe)))

    # Structural quorum: A2B is uniquely the conjunction of a twisted-pair
    # daisy chain + main/sub node discovery + superframe-down/up + power over
    # the bus + tunneled I2S/I2C. Require the line-medium, the node hierarchy,
    # the superframe, and at least one of {phantom power, tunneled audio}.
    line_medium = twisted_pair and daisy_chain
    node_hierarchy = main_node and (discovery or "node address" in low)
    superframe_struct = superframe and down_up
    tunneling = tunnels_i2s or tunnels_i2c

    a2b_structure = (
        line_medium
        and node_hierarchy
        and superframe_struct
        and (power_over_audio or tunneling)
    )

    # --- Sibling MUTEX ----------------------------------------------------
    # I2S-primary: a direct 3-wire SCK/WS/SD link, no daisy chain / superframe /
    # node discovery / phantom power. If the doc reads as plain I2S and the
    # A2B-only structure is absent, defer.
    i2s_primary = (
        ("i2s" in low or "inter-ic sound" in low)
        and _any_word(low, "sck", "ws", "sd", "wclk", "lrck")
        and not (line_medium or superframe or main_node or phantom_power
                 or "automotive audio bus" in low
                 or _any_word(low, "ad2410", "ad2420", "ad2425")
                 or "ad242x" in low)
    )
    if i2s_primary:
        return False

    # SoundWire-primary: MIPI SoundWire bus with its own framing / data ports;
    # no twisted-pair daisy-chain phantom-power AD24xx transceiver.
    soundwire_primary = (
        ("soundwire" in low or "sound wire" in low)
        and ("data port" in low or "dataport" in low or "frame shape" in low
             or "mipi" in low)
        and not (line_medium and superframe and main_node
                 and (phantom_power or "automotive audio bus" in low))
    )
    if soundwire_primary:
        return False

    # S/PDIF-primary: biphase-mark coax/optical single audio link; no node
    # discovery, no superframe regions, no phantom power, no I2C tunneling.
    spdif_primary = (
        ("s/pdif" in low or "spdif" in low or "iec 60958" in low)
        and ("biphase" in low or "bi-phase" in low or "subframe" in low
             or "toslink" in low)
        and not (line_medium or main_node or phantom_power or superframe
                 or "automotive audio bus" in low)
    )
    if spdif_primary:
        return False

    return bool(
        a2b_structure
        or (name_token and line_medium and superframe_struct
            and (node_hierarchy or transceiver))
        or (("automotive audio bus" in low) and line_medium
            and (superframe or phantom_power) and node_hierarchy)
    )


def apply_a2b_synth(generated_docs_dir: Path, is_a2b_flag: bool,
                    a2b_ic_name: Optional[str]) -> None:
    """Apply Analog Devices A2B (AD24xx) synth when the A2B signature matched.

    Runs AFTER the audio siblings (i2s / soundwire / spdif) and the I2C synth,
    so it FORCE-ASSIGNS (not setdefault) every protocol-content key those
    siblings may have written, and force-overwrites L17.
    """
    if not is_a2b_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if a2b_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = a2b_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = a2b_ic_name
                d["ic_name"] = a2b_ic_name
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
# L1 — A2B datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["document_title"] = "Automotive Audio Bus (A2B) Transceiver Technical Specification"
    d["version"] = "Analog Devices A2B (AD24xx family: AD2410 / AD2420 / AD2425 / AD242x)"
    d["revised_date"] = "Reflects Analog Devices A2B AD24xx transceiver specification"
    d["manufacturer"] = "Analog Devices, Inc. (ADI)"
    d["copyright"] = "© Analog Devices, Inc. — A2B is a registered trademark of Analog Devices"
    d["abstract"] = (
        "The Automotive Audio Bus (A2B) is a high-bandwidth, bidirectional, "
        "digital audio bus from Analog Devices that distributes multichannel "
        "digital audio, control data, and power over a single unshielded "
        "twisted pair (UTP) cable in a daisy-chain (line) topology. A2B targets "
        "automotive infotainment and ADAS audio: microphone arrays, "
        "amplifiers, active and road-noise cancellation (ANC / RNC), and remote "
        "speaker / microphone nodes. One A2B main node (master), connected to a "
        "host processor / SoC through a local I2S/TDM audio port and a local "
        "I2C control port, drives a daisy-chained line of up to ten A2B sub "
        "nodes (slaves). Each node is an A2B transceiver (e.g. AD2410 / AD242x) "
        "that tunnels I2S/TDM audio together with I2C control, GPIO, and "
        "interrupts over the same twisted pair, and that delivers phantom power "
        "(bus power) to downstream nodes over the very same pair. Audio is "
        "organized into a periodic superframe locked to the audio sample rate "
        "(e.g. 48 kHz), divided into downstream and upstream portions, giving "
        "deterministic low and constant latency (approximately two samples).")
    d["keywords"] = [
        "A2B", "Automotive Audio Bus", "Analog Devices", "AD2410", "AD2420",
        "AD2425", "AD242x", "AD24xx", "transceiver", "main node", "sub node",
        "master", "slave", "daisy chain", "unshielded twisted pair", "UTP",
        "superframe", "downstream", "upstream", "phantom power", "bus power",
        "node discovery", "node address", "I2S", "TDM", "I2C", "GPIO over distance",
        "interrupt", "ANC", "RNC", "microphone array", "amplifier",
        "deterministic latency", "48 kHz", "infotainment", "ADAS",
    ]
    d["external_pins"] = [
        "AP / AN (A-side positive / negative): downstream twisted-pair "
        "connection toward the next sub node.",
        "BP / BN (B-side positive / negative): upstream twisted-pair connection "
        "toward the main node (absent on the main node's master side).",
        "BCLK, SYNC (FSYNC / WS), DTX0/DTX1, DRX0/DRX1: local I2S/TDM audio port.",
        "SDA, SCL: local I2C control port.",
        "IO0..IO7 / GPIO: general-purpose I/O and interrupt pins (GPIO over distance).",
        "IRQ / INT: interrupt output toward the host (main node) or local use.",
        "VIN / SWGND / phantom-power switch pins: bus-power input and downstream "
        "power-switch control.",
    ]
    d["max_sub_nodes"] = _MAX_SUB_NODES
    d["typical_sample_rates_kHz"] = list(_TYPICAL_SAMPLE_RATES_KHZ)
    d["max_audio_channels_per_direction"] = _MAX_AUDIO_CHANNELS_PER_DIRECTION
    d["end_to_end_latency_samples"] = _LATENCY_SAMPLES
    d["transceiver_family"] = list(_TRANSCEIVERS)
    d["modes_of_operation"] = [
        {"name": "A2B main node (master)",
         "role": "bus timing master + host bridge",
         "note": "Connected to the host SoC via a local I2S/TDM audio port and "
                 "a local I2C control port; generates the bus clock and "
                 "superframe sync; originates downstream and collects upstream; "
                 "the host configures the whole bus through the main node's I2C."},
        {"name": "A2B sub node (slave)",
         "role": "remote audio / control node",
         "note": "Recovers clock and data from its upstream (B-side) pair, "
                 "extracts the slots/control addressed to it, re-times and "
                 "forwards downstream; exposes a local I2S/TDM port, a local "
                 "I2C port, GPIO, and interrupt sources tunneled over the bus."},
    ]
    d["key_features"] = [
        "Single unshielded twisted pair (UTP) carries multichannel digital "
        "audio + control + power in a daisy-chain (line) topology.",
        "One A2B main node (master) plus up to ten A2B sub nodes (slaves) in a "
        "daisy chain; each segment is a point-to-point twisted-pair link.",
        "Node discovery enumerates sub nodes in order from the main node "
        "outward; each sub node gets a node address equal to its chain position.",
        "Periodic superframe synchronous to the audio sample rate (e.g. 48 kHz) "
        "with separate downstream and upstream portions; deterministic, low, "
        "constant latency of approximately two samples end to end.",
        "Phantom power (bus power) distributed to downstream nodes over the same "
        "twisted pair that carries the audio; switched segment-by-segment "
        "during discovery so a remote node needs no local supply.",
        "Tunnels each node's local I2S/TDM audio + I2C control + GPIO + "
        "interrupts transparently over the bus.",
        "Each node is an A2B transceiver (AD24xx family: AD2410 / AD2420 / "
        "AD2425 / AD242x); main and sub nodes typically share the same silicon.",
        "Node-by-node clock recovery and re-timing lets the chain span a long "
        "total cable length (order of tens of metres) without jitter buildup.",
        "Line diagnostics: cable open / short-to-ground / short-to-battery / "
        "short-across-pair / reversed-wiring detection and phantom-power faults, "
        "reported upstream via interrupts.",
    ]
    d["topology_summary"] = (
        "Daisy-chain (line) topology: the main node connects to sub node 0 over "
        "one twisted pair, sub node 0 to sub node 1 over the next segment, and "
        "so on up to sub node 9. Exactly one main node; up to ten sub nodes. "
        "Each transceiver has a B-side (upstream, toward the main node) and an "
        "A-side (downstream, toward the next sub node).")
    d["use_cases"] = [
        "Automotive microphone arrays (hands-free, voice recognition, ANC/RNC).",
        "Remote smart-amplifier / speaker nodes near the speakers.",
        "Distributed active / road-noise cancellation across nodes.",
        "Infotainment multichannel audio distribution from a head unit.",
        "Powering remote audio nodes over the bus with no local supply.",
    ]
    d["revision_history"] = [
        {"version": "A2B (AD2410)", "date": "First-generation",
         "description": "First A2B transceiver: single-twisted-pair daisy chain, "
                        "main/sub nodes, superframe, phantom power, I2S/TDM + I2C "
                        "tunneling."},
        {"version": "A2B AD242x", "date": "Second-generation",
         "description": "AD242x family transceivers with expanded channel counts, "
                        "diagnostics, and GPIO-over-distance capability."},
    ]
    d["overview"] = (
        "A2B replaces the heavy point-to-point analog and digital audio wiring "
        "of a vehicle with a single twisted-pair daisy chain carrying audio, "
        "control, interrupts, and power together. The bus is mastered by a "
        "single A2B main node connected to the host SoC via local I2S/TDM and "
        "I2C. The main node converts the host's local audio and register "
        "traffic into the A2B line protocol and transmits downstream; each sub "
        "node recovers clock and data, extracts the slots addressed to it, and "
        "re-times the signal to the next node. Upstream data (e.g. microphone "
        "audio) flows back to the main node in the same superframe. The "
        "superframe is locked to the sample rate, so latency is deterministic "
        "and low (~2 samples). Phantom power feeds downstream nodes over the "
        "same pair. Each node is an A2B transceiver such as the AD2410 or an "
        "AD242x device.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Single-twisted-pair daisy-chain digital audio bus distributing "
        "multichannel audio + I2C control + GPIO/interrupts + power; one main "
        "node (master) plus up to ten sub nodes (slaves); synchronous "
        "superframe locked to the audio sample rate.")
    po["duplex"] = ("bidirectional — each superframe carries a downstream "
                    "portion (main→subs) and an upstream portion (subs→main)")
    po["synchronous"] = True
    po["topology"] = "daisy chain (line) over a single unshielded twisted pair"
    po["timing_master"] = ("the A2B main node generates the bus clock and "
                           "superframe sync; every sub node phase-locks to it")
    po["medium"] = ("single unshielded twisted pair (UTP), ~100 Ω, point-to-"
                    "point per segment; ~15 m per segment, ~40 m total chain")
    po["max_sub_nodes"] = _MAX_SUB_NODES
    po["superframe_rate"] = ("equals the audio sample rate (SYNC rate), e.g. "
                             "44.1 kHz or 48 kHz; one superframe per sample period")
    po["latency"] = ("deterministic, low, constant — approximately two audio "
                     "samples end to end")
    po["power"] = ("phantom power (bus power) delivered to downstream nodes "
                   "over the same twisted pair that carries the audio")
    po["tunneled_interfaces"] = ["I2S/TDM audio", "I2C control", "GPIO over distance",
                                 "interrupts"]
    fr = [
        {"id": "FR-MEDIUM-UTP-01",
         "text": "A2B shall distribute multichannel digital audio, control "
                 "data, and power over a single unshielded twisted pair (UTP) "
                 "in a daisy-chain (line) topology."},
        {"id": "FR-NODES-02",
         "text": "An A2B bus shall consist of exactly one A2B main node "
                 "(master) plus up to ten A2B sub nodes (slaves) daisy-chained "
                 "in a line; each twisted-pair segment is point-to-point "
                 "between two adjacent transceivers."},
        {"id": "FR-MAIN-HOST-03",
         "text": "The A2B main node shall connect to the host SoC through a "
                 "local I2S/TDM audio port and a local I2C control port, and "
                 "shall act as the bus timing master generating the bus clock "
                 "and superframe sync."},
        {"id": "FR-DISCOVERY-04",
         "text": "The bus shall be brought up by a node-discovery process that "
                 "enumerates sub nodes one at a time, in order, from the node "
                 "nearest the main node outward, switching phantom power onto "
                 "each next segment as part of the sequence."},
        {"id": "FR-ADDRESS-05",
         "text": "Each sub node shall be identified by a node address equal to "
                 "its position in the daisy chain (0 nearest the main node, up "
                 "to 9); broadcast addressing to all nodes shall be supported."},
        {"id": "FR-SUPERFRAME-06",
         "text": "All bus traffic shall be organized into a periodic superframe "
                 "transmitted once per audio sample period (superframe rate = "
                 "sample rate, e.g. 48 kHz), containing a synchronization / "
                 "control region, a downstream portion, and an upstream "
                 "portion."},
        {"id": "FR-LATENCY-07",
         "text": "Because the superframe is locked to the sample rate and slot "
                 "positions are fixed by configuration, end-to-end audio "
                 "latency shall be deterministic, low, and constant — "
                 "approximately two audio samples."},
        {"id": "FR-PHANTOM-POWER-08",
         "text": "The main node (and configured intermediate sub nodes) shall "
                 "be able to supply DC phantom power (bus power) to downstream "
                 "nodes over the same twisted pair that carries the audio, "
                 "switched segment-by-segment during discovery."},
        {"id": "FR-TUNNEL-I2S-09",
         "text": "Each node shall tunnel its local I2S/TDM audio (BCLK, SYNC, "
                 "DTX/DRX, TDM slots) transparently over the bus, with all "
                 "nodes' local I2S/TDM clocks derived from the recovered bus "
                 "clock so audio is sample-aligned."},
        {"id": "FR-TUNNEL-I2C-10",
         "text": "The host's I2C bus (on the main node's local I2C port) shall "
                 "be tunneled over the A2B line so the host can read/write the "
                 "registers of any sub node transceiver and any sub-node-local "
                 "I2C peripheral; the sub node acts as an I2C controller on its "
                 "local I2C bus on behalf of the host."},
        {"id": "FR-GPIO-INT-11",
         "text": "Sub-node local GPIO pin states shall be transportable over "
                 "the bus (GPIO over distance), and sub-node interrupts shall "
                 "be tunneled upstream to the main node, which presents a "
                 "single interrupt to the host."},
        {"id": "FR-CLOCK-RETIME-12",
         "text": "Each sub node shall recover the bus clock from its upstream "
                 "twisted pair, phase-lock to it, and regenerate a re-timed "
                 "signal toward its downstream neighbor so the chain can span a "
                 "long total cable length without jitter buildup."},
        {"id": "FR-DIAGNOSTICS-13",
         "text": "A2B shall provide line diagnostics: detection of cable open, "
                 "short to ground, short to battery, short across the pair, and "
                 "reversed wiring per segment, plus phantom-power faults, "
                 "reported upstream to the main node via interrupt status."},
        {"id": "FR-TRANSCEIVER-14",
         "text": "Each A2B node shall be built around an A2B transceiver IC "
                 "(AD24xx family — AD2410 / AD2420 / AD2425 / AD242x); main and "
                 "sub nodes typically use the same silicon configured into main "
                 "or sub mode."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    else:
        d["functional_requirements"] = fr
    d["configurations"] = [
        {"name": "Main node (master) mode",
         "description": "Transceiver strapped/configured as the bus timing "
                        "master, bridging the host SoC's local I2S/TDM + I2C to "
                        "the A2B line; only an A-side (downstream)."},
        {"name": "Sub node (slave) mode",
         "description": "Transceiver configured as a sub node: B-side upstream "
                        "toward the main node, A-side downstream toward the next "
                        "sub node; exposes local I2S/TDM + I2C + GPIO."},
        {"name": "Bus-powered (phantom power) node",
         "description": "Sub node drawing all of its power from the A2B line; "
                        "no local supply."},
        {"name": "Local-powered node",
         "description": "Sub node with its own supply, used where the bus "
                        "cannot deliver enough power."},
    ]
    d["error_response_conditions"] = [
        "Loss of bus lock at a node — breaks the chain downstream of that node; "
        "reported upstream to the main node as an interrupt.",
        "Line fault on a segment (open / short to ground / short to battery / "
        "short across pair / reversed wiring) — detected and reported via "
        "interrupt status so the host can localize the fault to a segment.",
        "Phantom-power fault (over-current / under-voltage) on a segment — "
        "reported per segment; affected downstream nodes lose power.",
        "Data decoding / CRC error on the superframe control structure — "
        "reported via interrupt status.",
        "Discovery failure (next node fails to lock or respond after power is "
        "switched on) — discovery halts and is reported to the host.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — Command / protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["protocol_type"] = (
        "Synchronous, superframe-structured daisy-chain audio bus. The main "
        "node is the timing master; one superframe is transmitted per audio "
        "sample period and is divided into a synchronization/control region, a "
        "downstream portion, and an upstream portion. Control / register access "
        "(tunneled I2C), discovery, GPIO, and interrupts ride in the "
        "control region; audio rides in fixed slots. There is no general "
        "opcode/command set at the wire layer — control is register access "
        "tunneled over I2C.")
    d["opcodes"] = []
    d["no_opcodes_in_input"] = True
    d["channels"] = [
        {"name": "A-side twisted pair (downstream)",
         "direction": "main node → sub nodes",
         "description": "Differential twisted-pair link toward the next "
                        "downstream sub node; carries the downstream portion of "
                        "the superframe plus phantom power."},
        {"name": "B-side twisted pair (upstream)",
         "direction": "sub nodes → main node",
         "description": "Differential twisted-pair link toward the main node; "
                        "carries the upstream portion of the superframe."},
        {"name": "Local I2S/TDM audio port (per node)",
         "direction": "bidirectional (node-local)",
         "description": "BCLK, SYNC/FSYNC/WS, DTX/DRX TDM slots; tunneled over "
                        "the bus."},
        {"name": "Local I2C control port (per node)",
         "direction": "bidirectional (node-local)",
         "description": "SDA / SCL; tunneled over the bus for host register "
                        "access to sub nodes and their peripherals."},
    ]
    d["superframe_structure"] = {
        "rate": "equals the audio sample rate (SYNC rate), e.g. 48 kHz; one "
                "superframe per sample period",
        "regions": [
            {"name": "Synchronization / control region (SYNC)",
             "purpose": "Sub nodes lock to the bus on this preamble; carries "
                        "tunneled I2C register access, discovery, GPIO, and "
                        "interrupt traffic."},
            {"name": "Downstream portion",
             "purpose": "Audio slots flowing from the main node toward the sub "
                        "nodes (e.g. amplifier / playback channels)."},
            {"name": "Upstream portion",
             "purpose": "Audio slots and status flowing from the sub nodes back "
                        "toward the main node (e.g. microphone channels)."},
        ],
        "slot_mapping": "Each node consumes the downstream slots addressed to "
                        "it and inserts its data into the upstream slots "
                        "assigned to it as the superframe passes.",
        "latency": "Deterministic, ~2 samples end to end.",
    }
    d["discovery_protocol"] = {
        "summary": "Phantom-power-gated, ordered discovery from the main node "
                   "outward.",
        "steps": [
            "Host (via main node) initiates discovery of the next undiscovered "
            "node.",
            "Phantom power is switched onto the next downstream segment, "
            "powering up the next sub node transceiver.",
            "The newly powered sub node achieves bus lock and announces itself.",
            "The main node assigns the sub node a node address (its chain "
            "position 0..9) and reads its identification / vendor / product "
            "registers.",
            "The host configures the new node's audio slots, I2S/TDM format, "
            "I2C passthrough, GPIO, and interrupts via tunneled register writes.",
            "Discovery repeats for the next downstream node until the chain is "
            "enumerated.",
        ],
        "ordering_reason": "A downstream node cannot be discovered until its "
                           "upstream neighbor is discovered and instructed to "
                           "switch power to the next segment.",
    }
    d["addressing"] = {
        "scheme": "node address = position in the daisy chain (0 nearest the "
                  "main node, up to 9)",
        "broadcast": "broadcast addressing to all nodes supported for common "
                     "configuration",
        "register_access": "host reaches every node's registers over tunneled "
                           "I2C through the main node",
    }
    d["tunneled_protocols"] = ["I2S/TDM audio", "I2C control/register access",
                               "GPIO over distance", "interrupts"]
    d["burst_based"] = False
    d["byte_oriented"] = False
    d["frame_oriented"] = True
    d["connection_oriented"] = False
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — Register map (transceiver-level, not a wire protocol regmap).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["register_map_present"] = True
    d["notes"] = (
        "Each A2B transceiver exposes a register space reached over I2C "
        "(directly on the main node; tunneled over the bus for sub nodes). "
        "Representative register groups (concrete addresses are device-specific "
        "to the AD24xx part): node configuration / mode (main vs sub); node "
        "address; discovery control / status; audio slot control (downstream / "
        "upstream slot counts and offsets); I2S/TDM configuration (BCLK/SYNC "
        "rate, slot width, TDM mode); I2C passthrough control; GPIO direction / "
        "value / GPIO-over-distance mapping; interrupt mask / status / source; "
        "phantom-power switch control; line-diagnostic status; PLL / lock "
        "status; vendor / product / version identification.")
    d["register_groups"] = [
        {"group": "Node configuration", "fields": ["mode (main/sub)", "node address",
                                                   "PLL/lock status"]},
        {"group": "Discovery", "fields": ["discovery control", "discovery status",
                                          "node count"]},
        {"group": "Audio slots", "fields": ["downstream slot count/offset",
                                            "upstream slot count/offset",
                                            "slot format"]},
        {"group": "I2S/TDM", "fields": ["BCLK/SYNC rate", "slot width", "TDM mode",
                                        "DTX/DRX mapping"]},
        {"group": "I2C passthrough", "fields": ["passthrough enable",
                                                "local I2C controller config"]},
        {"group": "GPIO / interrupt", "fields": ["GPIO direction", "GPIO value",
                                                 "GPIO-over-distance map",
                                                 "interrupt mask", "interrupt status"]},
        {"group": "Power / diagnostics", "fields": ["phantom-power switch",
                                                    "power fault status",
                                                    "line-fault status"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — ADI / signaling.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "The A2B line is a differential signal over a single unshielded "
        "twisted pair (~100 Ω). The main node drives the bus clock and "
        "superframe; each sub node recovers the clock from the line and "
        "re-times the signal. DC phantom power (bus power) is delivered on the "
        "same conductors as the AC-coupled differential audio/control signal, "
        "so a remote node can be powered entirely from the line. A2B is "
        "designed for low electromagnetic emissions in the automotive "
        "environment. The local node interfaces (I2S/TDM digital audio, I2C "
        "control) connect to local codecs / ADC-DAC / amplifiers, whose analog "
        "characteristics are separate from the A2B line itself.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — Control logic / FSM.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["fsm_states_sub_node_lock"] = [
        {"name": "POWER_OFF", "description": "Sub node transceiver unpowered; "
                                            "awaits phantom power on its B-side segment."},
        {"name": "POWERED", "description": "Phantom power applied; transceiver "
                                          "boots and begins detecting activity "
                                          "on the B-side twisted pair."},
        {"name": "CLOCK_RECOVERY", "description": "Recover the bus clock from "
                                                 "the upstream line transitions."},
        {"name": "SUPERFRAME_LOCK", "description": "Align to the superframe SYNC; "
                                                  "achieve superframe (bus) lock."},
        {"name": "DISCOVERED", "description": "Respond to discovery; receive an "
                                             "assigned node address; report ID "
                                             "registers."},
        {"name": "CONFIGURED", "description": "Host has written audio slot, "
                                             "I2S/TDM, I2C, GPIO, interrupt "
                                             "configuration via tunneled registers."},
        {"name": "OPERATIONAL", "description": "Extract downstream slots, insert "
                                              "upstream slots, re-time and "
                                              "forward the superframe to the "
                                              "next node."},
        {"name": "LOSS_OF_LOCK", "description": "Bus lock lost; chain downstream "
                                              "of this node breaks; reported "
                                              "upstream via interrupt; retry "
                                              "from CLOCK_RECOVERY."},
    ]
    d["fsm_states_main_node"] = [
        {"name": "MAIN_INIT", "description": "Main node configured by host over "
                                            "local I2C; generates bus clock and "
                                            "superframe sync."},
        {"name": "DISCOVERING", "description": "Run the ordered discovery "
                                              "sequence, switching phantom power "
                                              "segment-by-segment and assigning "
                                              "node addresses."},
        {"name": "RUNNING", "description": "Transmit superframes downstream and "
                                          "collect the upstream portion; bridge "
                                          "host I2S/TDM + I2C to the bus."},
        {"name": "FAULT", "description": "A line or power fault or loss-of-lock "
                                        "was reported upstream; present a single "
                                        "interrupt to the host for triage."},
    ]
    d["fsm_hints"] = {
        "trigger": "Continuous superframe locked to the sample rate; the main "
                   "node is the timing master and the discovery sequence is "
                   "gated by segment-by-segment phantom-power switching.",
        "rule": "A sub node must achieve clock recovery then superframe lock "
                "before it can be discovered and addressed; a downstream node "
                "cannot be discovered before its upstream neighbor.",
        "abort": "Loss of bus lock at a node breaks the chain downstream of it "
                 "and is reported upstream to the main node.",
    }
    d["anti_deadlock_rule"] = (
        "There is a single timing master (the main node) and an ordered, "
        "power-gated discovery sequence, so there is no bus arbitration and no "
        "deadlock at the protocol layer. A node that loses lock simply re-runs "
        "clock recovery and superframe lock.")
    d["exit_from_reset_or_poweron"] = (
        "On power-on the main node is configured first; only the main node has "
        "power initially. The host then runs discovery, which switches phantom "
        "power onto each next segment in turn, powering and enumerating the sub "
        "nodes from the node nearest the main node outward.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — Test / debug.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Bus / superframe lock status (per node)",
         "purpose": "Indicates whether each sub node has achieved clock "
                    "recovery and superframe lock; loss of lock is reported "
                    "upstream."},
        {"name": "Line-fault diagnostics (per segment)",
         "purpose": "Detect and localize cable open, short to ground, short to "
                    "battery, short across the pair, and reversed wiring."},
        {"name": "Phantom-power fault status (per segment)",
         "purpose": "Over-current / under-voltage detection on each powered "
                    "segment."},
        {"name": "Interrupt status registers",
         "purpose": "Aggregate sub-node interrupts upstream so the host can "
                    "read the source and node of any fault over tunneled I2C."},
        {"name": "Discovery status / node count",
         "purpose": "Track how many nodes were discovered and where discovery "
                    "stopped if it failed."},
        {"name": "Data-decoding / CRC error indicators",
         "purpose": "Flag corruption of the superframe control structure."},
    ]
    d["notes"] = (
        "A2B diagnostics let the host localize a fault to a specific segment / "
        "node, which is essential for serviceability of a vehicle audio "
        "harness. Concrete AD24xx parts expose these as interrupt mask/status "
        "and diagnostic registers reached over (tunneled) I2C.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — RTL constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    wp = _ensure_dict(d, "width_parameters")
    for k, v in {
        "MAX_SUB_NODES": _MAX_SUB_NODES,
        "MAX_NODES_INCLUDING_MAIN": _MAX_SUB_NODES + 1,
        "NODE_ADDRESS_MIN": 0,
        "NODE_ADDRESS_MAX": _MAX_SUB_NODES - 1,
        "MAX_DOWNSTREAM_AUDIO_CHANNELS": _MAX_AUDIO_CHANNELS_PER_DIRECTION,
        "MAX_UPSTREAM_AUDIO_CHANNELS": _MAX_AUDIO_CHANNELS_PER_DIRECTION,
        "TWISTED_PAIR_CONDUCTORS_PER_SEGMENT": 2,
        "SUPERFRAMES_PER_SAMPLE_PERIOD": 1,
        "END_TO_END_LATENCY_SAMPLES": _LATENCY_SAMPLES,
        "LOCAL_I2S_TDM_PORT_PRESENT": 1,
        "LOCAL_I2C_PORT_PRESENT": 1,
    }.items():
        wp[k] = v
    d["electrical_levels"] = {
        "line_medium": "single unshielded twisted pair (UTP)",
        "line_impedance_ohm": 100,
        "signaling": "differential, AC-coupled audio/control + DC phantom power "
                     "on the same conductors",
        "max_distance_per_segment_m": 15,
        "max_total_chain_length_m": 40,
    }
    d["key_constants_for_RTL_authoring"] = {
        "topology": "daisy chain (line)",
        "node_roles": "one main node (master) + up to ten sub nodes (slaves)",
        "node_address_scheme": "chain position 0..9",
        "superframe_rate": "= audio sample rate (e.g. 48 kHz)",
        "superframe_regions": ["SYNC/control", "downstream", "upstream"],
        "latency_samples": _LATENCY_SAMPLES,
        "phantom_power": "switched segment-by-segment during discovery",
        "tunneled": ["I2S/TDM", "I2C", "GPIO", "interrupts"],
        "transceiver_family": list(_TRANSCEIVERS),
    }
    d["typical_sample_rates_kHz"] = list(_TYPICAL_SAMPLE_RATES_KHZ)
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — Timing / waveforms.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["superframe_timing"] = {
        "summary": "One superframe is transmitted per audio sample period; the "
                   "superframe rate equals the audio sample rate (SYNC rate).",
        "regions_in_order": ["SYNC / control preamble", "downstream portion",
                             "upstream portion"],
        "sync_role": "Sub nodes lock to the bus on the SYNC preamble; the SYNC "
                     "region also carries tunneled I2C, discovery, GPIO, and "
                     "interrupt traffic.",
        "latency": "Deterministic, low, constant — approximately two audio "
                   "samples end to end from the main node's local I2S input to "
                   "the farthest sub node's local I2S output.",
    }
    d["clocking"] = {
        "timing_master": "the A2B main node generates the bus clock and "
                         "superframe sync",
        "sub_node_clock": "each sub node recovers the bus clock from its "
                          "upstream twisted pair, phase-locks, and re-times the "
                          "signal toward its downstream neighbor",
        "local_clock_derivation": "all local I2S/TDM clocks (BCLK and SYNC/"
                                  "FSYNC) at every node are derived from the "
                                  "recovered bus clock, so the whole system "
                                  "shares one audio time base",
        "retiming": "node-by-node re-timing restores the signal at each node, "
                    "allowing a long total cable length without jitter buildup",
    }
    d["sample_rate_examples"] = [
        {"sample_rate_kHz": 44.1, "superframe_rate_kHz": 44.1,
         "use_case": "CD-derived audio"},
        {"sample_rate_kHz": 48, "superframe_rate_kHz": 48,
         "use_case": "automotive infotainment / ANC reference"},
    ]
    d["general_timing_rule"] = (
        "All timing is referenced to the audio sample rate. The superframe rate "
        "equals the sample rate; the main node is the rate master and every sub "
        "node phase-locks to the recovered bus clock. Slot positions within the "
        "superframe are fixed by configuration, which is what makes the "
        "end-to-end latency deterministic and constant (~2 samples).")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — Integration spec.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["module_role"] = (
        "An A2B transceiver node (main or sub) bridging a node-local I2S/TDM "
        "audio port and I2C control port to a single-twisted-pair A2B daisy "
        "chain. The main node connects to a host SoC; sub nodes connect to "
        "local codecs / amplifiers / microphones. The transceiver tunnels "
        "I2S/TDM + I2C + GPIO + interrupts over the bus and (where configured) "
        "supplies or consumes phantom power on the line.")
    d["integration_overview"] = {
        "topology": "daisy chain (line) over a single unshielded twisted pair",
        "node_roles": "one main node (master) + up to ten sub nodes (slaves)",
        "timing_master": "the main node generates bus clock + superframe sync",
        "a_side": "downstream twisted-pair toward the next sub node",
        "b_side": "upstream twisted-pair toward the main node (absent on main)",
        "local_audio_port": "I2S/TDM (BCLK, SYNC, DTX/DRX) per node",
        "local_control_port": "I2C (SDA/SCL) per node",
        "power": "phantom power (bus power) over the same twisted pair, switched "
                 "segment-by-segment during discovery",
        "tunneled": ["I2S/TDM audio", "I2C control", "GPIO over distance",
                     "interrupts"],
        "latency": "deterministic ~2 samples end to end",
    }
    d["interface_categories"] = [
        "A2B line interface (A-side / B-side twisted pair, differential + "
        "phantom power).",
        "Local I2S/TDM audio port (to host SoC on the main node; to codec / "
        "amplifier / microphone on a sub node).",
        "Local I2C control port (host register access on the main node; local "
        "peripherals on a sub node).",
        "GPIO / interrupt pins (GPIO over distance, interrupt aggregation).",
    ]
    d["interconnect_topologies_supported"] = [
        "Daisy chain (line) of one main node + up to ten sub nodes — the "
        "canonical A2B topology.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — Test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["test_cases"] = [
        {"id": "TC-DISCOVERY-01",
         "description": "Power up a main node with N sub nodes; run discovery; "
                        "verify all N sub nodes are enumerated in order with "
                        "node addresses 0..N-1 and that phantom power is "
                        "switched segment-by-segment."},
        {"id": "TC-SUPERFRAME-02",
         "description": "Verify exactly one superframe is transmitted per audio "
                        "sample period and that it contains a SYNC/control "
                        "region, a downstream portion, and an upstream "
                        "portion."},
        {"id": "TC-LATENCY-03",
         "description": "Inject a known sample at the main node's local I2S "
                        "input and verify it appears at the farthest sub node's "
                        "local I2S output with deterministic latency of about "
                        "two samples."},
        {"id": "TC-AUDIO-DOWNSTREAM-04",
         "description": "Map a downstream audio slot to a sub node and verify "
                        "the correct channel is delivered to that node's local "
                        "I2S/TDM output."},
        {"id": "TC-AUDIO-UPSTREAM-05",
         "description": "Map an upstream audio slot from a sub node (e.g. a "
                        "microphone) and verify it arrives sample-aligned at "
                        "the main node."},
        {"id": "TC-I2C-TUNNEL-06",
         "description": "From the host, read/write a sub node transceiver "
                        "register and a sub-node-local I2C peripheral over the "
                        "tunneled I2C path; verify correct access."},
        {"id": "TC-GPIO-DISTANCE-07",
         "description": "Toggle a sub node GPIO input and verify the state is "
                        "reproduced at the main node (GPIO over distance)."},
        {"id": "TC-PHANTOM-POWER-08",
         "description": "Verify a bus-powered sub node operates with no local "
                        "supply, drawing power from the line."},
        {"id": "TC-LINE-FAULT-09",
         "description": "Inject cable open / short-to-ground / short-to-battery "
                        "/ short-across-pair / reversed-wiring on a segment and "
                        "verify the fault is detected, localized, and reported "
                        "upstream via interrupt status."},
        {"id": "TC-LOSS-OF-LOCK-10",
         "description": "Force loss of bus lock at a mid-chain node and verify "
                        "the downstream chain breaks and the event is reported "
                        "upstream to the main node."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP content (genuine N/A).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["otp_present"] = False
    d["notes"] = (
        "The A2B protocol specification does not define one-time-programmable "
        "(OTP) content. Concrete AD24xx transceivers may hold vendor / product "
        "/ version identification readable over (tunneled) I2C, but that is a "
        "device register, not a protocol-defined OTP array.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — Behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["sequences"] = [
        {"name": "Bus bring-up and discovery",
         "steps": [
             "Host configures the main node over local I2C; main node starts "
             "the bus clock and superframe sync.",
             "Host initiates discovery of the next undiscovered node.",
             "Phantom power is switched onto the next downstream segment.",
             "The newly powered sub node recovers clock, achieves superframe "
             "lock, and announces itself.",
             "Main node assigns a node address (chain position) and reads ID "
             "registers.",
             "Host configures the node's slots, I2S/TDM, I2C, GPIO, interrupts "
             "via tunneled register writes.",
             "Repeat until the whole chain is enumerated.",
         ]},
        {"name": "Steady-state audio transport",
         "steps": [
             "Main node transmits a superframe per sample period: SYNC/control, "
             "then downstream, then upstream regions.",
             "Each sub node consumes its assigned downstream slots and inserts "
             "into its assigned upstream slots, re-timing and forwarding.",
             "Upstream audio (e.g. microphones) returns to the main node "
             "sample-aligned with deterministic ~2-sample latency.",
         ]},
        {"name": "Fault handling",
         "steps": [
             "A node detects loss of lock or a line/power fault.",
             "The condition is reported upstream toward the main node.",
             "The main node presents a single interrupt to the host.",
             "The host reads interrupt/diagnostic registers over tunneled I2C "
             "to localize the fault to a segment/node.",
         ]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — Lab calibration (genuine N/A).
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    d["lab_calibration_present"] = False
    d["notes"] = (
        "The A2B protocol does not define a lab-calibration procedure. Bus "
        "timing is locked to the audio sample rate and clock is recovered and "
        "re-timed at each node, so no per-unit analog calibration is part of "
        "the protocol. Physical-layer cable/connector characterization is an "
        "implementation / harness concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# Fields-style docs (L14-L23) — write into d["fields"].
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "Analog Devices A2B (AD24xx transceiver family)"
    f["versions"] = [
        {"name": "A2B (AD2410)", "note": "First-generation A2B transceiver."},
        {"name": "A2B AD242x", "note": "Second-generation AD242x family "
                                       "transceivers with expanded channels and "
                                       "diagnostics."},
    ]
    f["previous_versions"] = ["AD2410"]
    f["key_changes"] = [
        "AD242x expanded audio channel counts and diagnostics over AD2410.",
        "GPIO-over-distance and enhanced line diagnostics in later parts.",
    ]
    f["deprecated_features"] = []
    f["backward_compat_traps"] = [
        "Main and sub nodes must use a compatible A2B generation; mixing "
        "incompatible transceiver generations on one chain is not supported.",
    ]
    _write(p, d)


def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["node_addressing"] = {
        "scheme": "node address = daisy-chain position",
        "range": "0 (nearest main node) .. 9 (up to ten sub nodes)",
        "broadcast": "supported for common configuration",
    }
    f["superframe_regions"] = ["SYNC/control", "downstream", "upstream"]
    f["tunneled_protocols"] = ["I2S/TDM", "I2C", "GPIO", "interrupts"]
    _write(p, d)


def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["compliance_properties"] = [
        "There shall be exactly one main node (master) per A2B bus.",
        "There shall be at most ten sub nodes (slaves) in the daisy chain.",
        "The superframe rate shall equal the audio sample rate (one superframe "
        "per sample period).",
        "Each superframe shall contain a SYNC/control region, a downstream "
        "portion, and an upstream portion.",
        "Discovery shall enumerate sub nodes in order from the main node "
        "outward, gated by segment-by-segment phantom-power switching.",
        "All local I2S/TDM clocks shall be derived from the recovered bus clock "
        "so audio is sample-aligned across all nodes.",
        "End-to-end audio latency shall be deterministic and approximately two "
        "samples.",
    ]
    _write(p, d)


def _l17(gd: Path) -> None:
    """L17 — channel / signal catalog. FORCE-OVERWRITE (task requirement)."""
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "AP / AN", "direction": "downstream (A-side)",
         "description": "Differential twisted-pair toward the next sub node; "
                        "carries the downstream superframe + phantom power."},
        {"name": "BP / BN", "direction": "upstream (B-side)",
         "description": "Differential twisted-pair toward the main node; carries "
                        "the upstream superframe. Absent on the main node's "
                        "master side."},
        {"name": "BCLK", "direction": "local (per node)",
         "description": "Local I2S/TDM bit clock, derived from the recovered "
                        "bus clock."},
        {"name": "SYNC / FSYNC / WS", "direction": "local (per node)",
         "description": "Local I2S/TDM frame sync, derived from the bus clock."},
        {"name": "DTX0 / DTX1", "direction": "local out (per node)",
         "description": "Local I2S/TDM transmit data (TDM slots)."},
        {"name": "DRX0 / DRX1", "direction": "local in (per node)",
         "description": "Local I2S/TDM receive data (TDM slots)."},
        {"name": "SDA / SCL", "direction": "local bidirectional (per node)",
         "description": "Local I2C control port; tunneled over the bus for host "
                        "register access."},
        {"name": "IO0..IO7 / GPIO", "direction": "local bidirectional",
         "description": "General-purpose I/O; supports GPIO over distance."},
        {"name": "IRQ / INT", "direction": "out",
         "description": "Interrupt output toward the host (main node) / local."},
        {"name": "VIN / SWGND", "direction": "power",
         "description": "Bus-power input and downstream power-switch control "
                        "for phantom power."},
    ]
    f["global_signals"] = [
        {"name": "Bus clock", "description": "Generated by the main node; "
                                            "recovered and re-timed at each "
                                            "sub node."},
        {"name": "Superframe SYNC", "description": "Per-sample-period "
                                                  "synchronization preamble all "
                                                  "nodes lock to."},
    ]
    f["channel_counts"] = {
        "twisted_pair_segments": "one per node-to-node hop (up to 10)",
        "max_downstream_audio_channels": _MAX_AUDIO_CHANNELS_PER_DIRECTION,
        "max_upstream_audio_channels": _MAX_AUDIO_CHANNELS_PER_DIRECTION,
    }
    _write(p, d)


def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = "daisy chain (line)"
    f["supported_topologies"] = [
        "Daisy chain (line): one main node (master) + up to ten sub nodes "
        "(slaves), each segment a point-to-point twisted-pair link.",
    ]
    f["master_slave_role_summary"] = (
        "Exactly one main node (master) is the bus timing master and host "
        "bridge; sub nodes (slaves) phase-lock to the recovered bus clock, "
        "extract/insert audio slots, and re-time the superframe to the next "
        "node.")
    f["interconnect_rules"] = [
        "Each node has a B-side (upstream, toward the main node) and an A-side "
        "(downstream, toward the next sub node).",
        "The main node has only an A-side; the last sub node may have only a "
        "B-side.",
        "Phantom power flows from upstream to downstream, switched "
        "segment-by-segment during discovery.",
        "Discovery and node addressing proceed from the main node outward.",
    ]
    f["addressing_topology"] = {
        "scheme": "node address = chain position (0..9)",
        "broadcast": "supported",
    }
    f["device_classification"] = [
        {"class": "main node (master)", "note": "one per bus; host bridge + "
                                               "timing master"},
        {"class": "sub node (slave)", "note": "up to ten; remote audio/control "
                                             "node"},
    ]
    _write(p, d)


def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["physical_constraints"] = {
        "line_medium": "single unshielded twisted pair (UTP)",
        "line_impedance_ohm": 100,
        "max_distance_per_segment_m": 15,
        "max_total_chain_length_m": 40,
        "emissions": "designed for low electromagnetic emissions (automotive)",
    }
    _write(p, d)


def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["dft_notes"] = (
        "A2B is a protocol; scan/DFT topology is a property of a concrete "
        "AD24xx transceiver implementation, not of the A2B protocol itself. "
        "In-system diagnostics (line-fault, power-fault, lock-status, "
        "interrupt aggregation) provide field observability over (tunneled) "
        "I2C.")
    _write(p, d)


def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["power_intent"] = {
        "phantom_power": "DC bus power delivered to downstream nodes over the "
                         "same twisted pair that carries the audio/control "
                         "signal.",
        "switching": "switched segment-by-segment during discovery; a node "
                     "powers its downstream segment only when instructed, which "
                     "gates the discovery order.",
        "node_power_options": ["bus-powered (phantom power, no local supply)",
                               "local-powered (own supply where the bus cannot "
                               "deliver enough power)"],
        "fault_detection": "per-segment over-current / under-voltage detection, "
                           "reported upstream.",
    }
    _write(p, d)


def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["verification_plan"] = [
        "Discovery: enumerate N sub nodes in order with correct node "
        "addresses and segment-by-segment power switching.",
        "Superframe structure: one superframe per sample period with "
        "SYNC/control + downstream + upstream regions.",
        "Latency: deterministic ~2-sample end-to-end latency.",
        "Audio transport: downstream and upstream slots delivered "
        "sample-aligned to/from the correct nodes.",
        "Tunneling: I2C register access to sub nodes, GPIO over distance, and "
        "interrupt aggregation upstream.",
        "Power: bus-powered node operation; per-segment power-fault detection.",
        "Diagnostics: cable open / short / reversed-wiring detection and fault "
        "localization.",
        "Robustness: loss-of-lock at a mid-chain node breaks the chain "
        "downstream and is reported upstream.",
    ]
    _write(p, d)


def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    _purge_siblings(p, d)
    f = _ensure_dict(d, "fields")
    f["security_requirements"] = [
        "A2B is a wired in-vehicle bus; physical access to the harness is the "
        "primary threat surface.",
        "Node discovery and addressing are controlled by the host through the "
        "main node, limiting which nodes can be configured.",
        "Line and power-fault diagnostics support detection of tampering or "
        "miswiring of a segment.",
        "Confidentiality / authentication of the audio payload, if required, is "
        "an application-layer concern layered above A2B, not part of the "
        "transport itself.",
    ]
    _write(p, d)
