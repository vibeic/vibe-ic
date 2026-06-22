#!/usr/bin/env python3
"""spec_artifact_catalog.py — the MASTER CATALOG of structured ELEMENT TYPES that
appear in IC design documents / specs / prompts. The single vocabulary the
recognizer + extractor layer targets, merging:
  * the 20 "primitive" structural types from the ESA/Synopsys/UVM doc survey,
  * the vibe-ic l_doc_taxonomy (L1-L23) homes,
  * the extractability tier (which decides program-vs-AI division of labour), and
  * the existing program extractor/generator hooks (where one already exists).

DOCTRINE (owner 2026-06-22/23) — the UNDERSTANDING layer is DUAL-PASS:
  AI INTERPRETS the spec (strongest, improves with LLM upgrades) and the PROGRAM
  extracts a deterministic BASELINE; the two are reconciled (see
  spec_artifact_dual_pass.py). So each element type records BOTH how the program
  reads it (a deterministic baseline, possibly None) AND its extractability tier
  (which tells the dual-pass engine whether AI leads or merely cross-checks):

    tier = "table"  -> a regular table/grid; PROGRAM is authoritative baseline,
                       AI cross-checks (catches a parser miss / format variant).
    tier = "prose"  -> natural-language / parametric spec; AI LEADS, the program
                       baseline (if any) is partial; reconcile flags AI-only finds
                       as new-extractor candidates.
    tier = "vision" -> a diagram/image; needs eda_doc_extract + vision, not regex;
                       AI/vision leads, no text baseline.

`data_schema` is the shape the element's `data` field carries (the structured JSON
the IC Expert Agent emits per element). `program` names the module.function that
produces the deterministic baseline (None = not built yet -> AI-only baseline).
Pure data module; no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ElementType:
    key: str                          # canonical element_type id
    title: str
    category: str                     # combinational | sequential | timing | interface | ...
    l_docs: Tuple[str, ...]           # l_doc_taxonomy homes
    tier: str                         # table | prose | vision | hybrid
    data_schema: str                  # one-line shape of the `data` field
    program: Optional[str] = None     # "module.fn" deterministic baseline extractor, or None
    generator: Optional[str] = None   # "module.fn" RTL generator, or None
    status: str = "to_build"          # live | extractor_exists | to_build | vision_pending


# Canonical element-type catalog (the recognizer/extractor targets).
CATALOG: Tuple[ElementType, ...] = (
    # ---- A. Combinational ----
    ElementType("truth_table", "Truth Table", "combinational", ("L15", "L4"), "table",
                "{inputs[], output, rows{combo->bit}}",
                "kmap_truth_table_oracle_check.parse_truth_table",
                "oracle_table_synth.synth", "live"),
    ElementType("karnaugh_map", "Karnaugh Map", "combinational", ("L15",), "table",
                "{inputs[], output, grid}",
                "kmap_truth_table_oracle_check.parse_kmap",
                "kmap_grid_synth.synth", "live"),
    ElementType("boolean_expression", "Boolean Expression", "combinational", ("L6", "L15"), "prose",
                "{output, expr_ast, inputs[]}", "parametric_spec_extractor.extract_boolean_expression", None, "live"),
    ElementType("gate_level_schematic", "Gate-Level Netlist", "combinational", ("L18",), "hybrid",
                "{gates[{type,inputs,out}], nets[]}", None,
                "gate_netlist_rtl_gen.generate", "extractor_exists"),
    ElementType("lookup_rom_table", "Lookup / ROM Table", "combinational", ("L15", "L11"), "table",
                "{addr_bits, data{addr->val}}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("function_op_table", "Function / ALU Op Table", "combinational", ("L3", "L15"), "table",
                "{select, ops{code->op}}", "structured_table_extractor.extract_tables", None, "live"),

    # ---- B. Sequential / FSM ----
    ElementType("fsm_transition_table", "State Transition Table", "sequential", ("L6", "L3"), "table",
                "{states[], transitions{}, moore_output{}, reset}",
                "full_moore_fsm_synth._parse_fsm_table",
                "full_moore_fsm_synth.synth", "live"),
    ElementType("fsm_next_state_bit", "FSM Next-State Bit", "sequential", ("L6",), "table",
                "{state_bus, input, bit, table}",
                "kmap_truth_table_oracle_check.parse_fsm_next_state_bit",
                "oracle_table_synth.synth", "live"),
    ElementType("onehot_fsm", "One-Hot FSM", "sequential", ("L6",), "table",
                "{encoding, transitions, output}", None, "onehot_fsm_synth.synth", "live"),
    ElementType("comb_state_table", "Combinational State Table", "sequential", ("L6",), "table",
                "{encoding, transitions, output}", None, "comb_state_table_synth.synth", "live"),
    ElementType("ff_truth_table", "Flip-Flop Truth Table", "sequential", ("L6", "L15"), "table",
                "{ctrl[], cells{Qold/~Qold/0/1}}", None, "ff_truth_table_synth.synth", "live"),
    ElementType("state_encoding", "State Encoding", "sequential", ("L6", "L8C"), "table",
                "{state->code}", "kmap_truth_table_oracle_check._parse_state_encoding", None, "live"),
    ElementType("state_diagram", "State Diagram (bubble)", "sequential", ("L6",), "vision",
                "{states[], edges[{from,to,cond,out}]}", "figure_extractor.extract_figures", None, "live"),
    ElementType("sequence_detector", "Sequence Detector Spec", "sequential", ("L6",), "prose",
                "{pattern, overlap, moore_mealy, on_detect}", "parametric_spec_extractor.extract_sequence_detector", None, "live"),
    ElementType("protocol_state_machine", "Protocol State Machine", "sequential", ("L3", "L16"), "prose",
                "{states[], transitions, protocol}", "residual_recognizer.recognize_all", None, "live"),
    ElementType("behavioral_sequence", "Behavioral Sequence / Trace", "sequential", ("L12",), "table",
                "{cycle->{signals}}", "structured_table_extractor.extract_tables", None, "live"),

    # ---- C. Timing ----
    ElementType("timing_waveform", "Timing / Waveform Table", "timing", ("L8T",), "table",
                "{time, inputs, outputs}", None,
                "waveform_truth_table_synth.synth", "live"),
    ElementType("timing_parameter_table", "Timing Parameter Table", "timing", ("L8T",), "table",
                "{setup, hold, tco, tpd, ...}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("timing_diagram", "Timing Diagram (waveform)", "timing", ("L8T",), "vision",
                "{signals[], edges[]}", "figure_extractor.extract_figures", None, "live"),
    ElementType("timing_constraints", "Timing Constraints (SDC)", "timing", ("L19",), "prose",
                "{clk_period, io_delay, false/multicycle}", "parametric_spec_extractor.extract_timing_constraints", None, "live"),
    ElementType("clock_domain_table", "Clock Domain Table", "timing", ("L19", "L6"), "table",
                "{domains[], crossings[]}", "structured_table_extractor.extract_tables", None, "live"),

    # ---- D. Interface / Register ----
    ElementType("pinout_table", "Pinout / Port Table", "interface", ("L1",), "table",
                "{pins[{name,dir,width,type,desc}]}",
                "pinout_table_extractor.extract_pinout", None, "live"),
    ElementType("bit_field_table", "Register Bit-Field Table", "interface", ("L4",), "table",
                "{rows[{bit,name,function}]}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("register_map", "Register Map", "interface", ("L4",), "table",
                "{regs[{addr,offset,access,reset,fields[]}]}",
                "regmap_table_extractor.extract_regmap_table", None, "live"),
    ElementType("memory_map", "Memory Map", "interface", ("L4",), "table",
                "{ranges[{start,end,block}]}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("channel_signal_catalog", "Channel Signal Catalog", "interface", ("L17",), "table",
                "{channel->signals[]}", "structured_table_extractor.extract_tables", None, "live"),

    # ---- E. Protocol / Command ----
    ElementType("command_opcode_table", "Command / Opcode Table", "protocol", ("L3",), "table",
                "{opcode->{op,operands}}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("encoding_table", "Encoding Table", "protocol", ("L15",), "table",
                "{field->{code->meaning}}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("packet_frame_format", "Packet / Frame Format", "protocol", ("L3", "L15"), "hybrid",
                "{fields[{name,bits,byteorder}]}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("crc_checksum_spec", "CRC / Checksum Spec", "protocol", ("L8C",), "prose",
                "{poly, init, width, refin, refout, xorout}", "parametric_spec_extractor.extract_crc", None, "live"),

    # ---- F. Arithmetic / Data ----
    ElementType("arithmetic_spec", "Arithmetic Primitive Spec", "arithmetic", ("L2", "L8C"), "prose",
                "{op, width, signed, overflow}", "parametric_spec_extractor.extract_arithmetic", None, "live"),
    ElementType("counter_spec", "Counter Spec", "arithmetic", ("L2", "L6"), "prose",
                "{width, direction, modulo}", "parametric_spec_extractor.extract_counter", None, "live"),
    ElementType("shift_register_spec", "Shift Register Spec", "arithmetic", ("L2", "L6"), "prose",
                "{width, direction, lfsr, load}", "parametric_spec_extractor.extract_shift_register", None, "live"),
    ElementType("edge_detector", "Edge Detector", "sequential", ("L6",), "prose",
                "{detect, edge}", "parametric_spec_extractor.extract_edge_detector", None, "live"),
    ElementType("pulse_detector", "Pulse Detector", "sequential", ("L6",), "prose",
                "{detect}", "parametric_spec_extractor.extract_pulse_detector", None, "live"),
    ElementType("clock_generator", "Clock Generator / Divider", "timing", ("L8T",), "prose",
                "{kind, divisor}", "parametric_spec_extractor.extract_clock_generator", None, "live"),
    ElementType("signal_generator", "Signal / Waveform Generator", "analog", ("L5",), "prose",
                "{kind, wave, width}", "parametric_spec_extractor.extract_signal_generator", None, "live"),
    ElementType("timekeeping", "Timekeeping / Calendar", "sequential", ("L6",), "prose",
                "{kind, fields}", "parametric_spec_extractor.extract_timekeeping", None, "live"),
    ElementType("number_format", "Number Format", "arithmetic", ("L8C",), "prose",
                "{fixed_q | float | bcd}", "parametric_spec_extractor.extract_number_format", None, "live"),
    ElementType("data_conversion_table", "Data Conversion Table", "arithmetic", ("L15",), "table",
                "{in->out}", "structured_table_extractor.extract_tables", None, "live"),

    # ---- G. Memory ----
    ElementType("memory_spec", "Memory Spec", "memory", ("L4", "L8C"), "prose",
                "{kind, depth, width, ports, latency}", "parametric_spec_extractor.extract_memory", None, "live"),
    ElementType("otp_fuse_content", "OTP / Fuse Content", "memory", ("L11",), "table",
                "{addr->bits, layout}", "residual_recognizer.recognize_all", None, "live"),

    # ---- H. Analog / Mixed-Signal ----
    ElementType("analog_electrical_spec", "Analog Electrical Spec", "analog", ("L5",), "prose",
                "{gain, bw, noise, psrr, v/i_range}", "residual_recognizer.recognize_all", None, "live"),
    ElementType("pvt_corner_table", "PVT Corner Table", "analog", ("L19",), "table",
                "{corner->{p,v,t}}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("circuit_schematic", "Circuit Schematic", "analog", ("L5", "L18"), "vision",
                "{devices[], nets[]}", "figure_extractor.extract_figures", None, "live"),

    # ---- I. Physical / Backend ----
    ElementType("power_domain_table", "Power Domain Table (UPF)", "physical", ("L21",), "table",
                "{domains[], isolation, level_shift, retention}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("dft_scan_spec", "DFT / Scan Spec", "physical", ("L20",), "prose",
                "{chains, bist, jtag_tap}", "residual_recognizer.recognize_all", None, "live"),
    ElementType("floorplan_spec", "Floorplan / Placement", "physical", ("L19",), "vision",
                "{die, regions, io_ring, macros}", "figure_extractor.extract_figures", None, "live"),
    ElementType("pdk_target", "PDK / Technology Target", "physical", ("L19",), "prose",
                "{pdk, metal_stack, vt}", "parametric_spec_extractor.extract_pdk_target", None, "live"),

    # ---- J. Verification ----
    ElementType("test_vector_table", "Test Vector / Worked Example", "verification", ("L10",), "table",
                "{in->expected_out}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("coverage_matrix", "Coverage Matrix", "verification", ("L22",), "table",
                "{feature x test -> covered}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("traceability_matrix", "Traceability Matrix", "verification", ("L22",), "table",
                "{requirement -> design/verif refs}", "structured_table_extractor.extract_tables", None, "live"),
    ElementType("assertion_property", "Assertion / Property", "verification", ("L16", "L22"), "prose",
                "{properties[], assume, assert, cover}", "residual_recognizer.recognize_all", None, "live"),

    # ---- K. Architecture / Reference ----
    ElementType("block_diagram", "Block Diagram / Hierarchy", "architecture", ("L9",), "vision",
                "{modules[], dataflow_edges[]}", "figure_extractor.extract_figures", None, "live"),
    ElementType("reference_design", "Reference Design / IP", "architecture", ("L9", "L18"), "hybrid",
                "{block->{ports,params,rtl_ref}}", "residual_recognizer.recognize_all", None, "live"),
    ElementType("functional_requirements", "Functional Requirements", "system", ("L2",), "prose",
                "{requirements[{id,text,priority}]}", "residual_recognizer.recognize_all", None, "live"),
    ElementType("figure", "Figure (untyped diagram)", "architecture", ("L9",), "vision",
                "{lead:vision, caption, figure, ref}", "figure_extractor.extract_figures", None, "live"),
)

_BY_KEY: Dict[str, ElementType] = {e.key: e for e in CATALOG}


def keys() -> List[str]:
    return [e.key for e in CATALOG]


def get(key: str) -> Optional[ElementType]:
    return _BY_KEY.get(key)


def by_tier(tier: str) -> List[ElementType]:
    return [e for e in CATALOG if e.tier == tier]


def by_status(status: str) -> List[ElementType]:
    return [e for e in CATALOG if e.status == status]


def coverage_summary() -> Dict[str, int]:
    from collections import Counter
    tiers = Counter(e.tier for e in CATALOG)
    stat = Counter(e.status for e in CATALOG)
    return {"total": len(CATALOG), "by_tier": dict(tiers), "by_status": dict(stat)}


if __name__ == "__main__":
    import json
    print(json.dumps({
        "summary": coverage_summary(),
        "catalog": [{"type": e.key, "category": e.category, "tier": e.tier,
                     "l_docs": list(e.l_docs), "status": e.status,
                     "program": e.program, "generator": e.generator} for e in CATALOG],
    }, indent=2))
