#!/usr/bin/env python3
"""spec_artifact_registry.py — SINGLE SOURCE OF TRUTH for the canonical STRUCTURED
ARTIFACT TYPES that appear in IC specs / design documents / benchmark prompts.

WHY (owner directive 2026-06-22): an IC spec/prompt carries a FINITE set of
structured artifact types — truth table, Karnaugh map, FSM transition table +
state encoding, timing/waveform table, register/pin map, reference netlist, … —
each with a semi-regular but recognizable format. Historically each type's
recognizer/parser was re-implemented ad-hoc: prompt-parsers inside the §4.2
benchmark synth modules (kmap_grid_synth / waveform_truth_table_synth /
oracle_table_synth / full_moore_fsm_synth / onehot_fsm_synth) AND JSON-spec
parsers inside the Phase-2 RTL generators (fsm_table_rtl_gen / truth_table_rtl_gen
/ gate_netlist_rtl_gen). The same FSM/truth-table format was parsed in three
places. This registry collapses that: ONE catalog maps

    artifact_type -> {recognize(text)->structured, generate(text)->RTL,
                      l_docs (l_doc_taxonomy home), title}

so BOTH the Phase-1 doc-ingestion (the IC Expert Agent, which now KNOWS the
catalog of artifact types and how to extract each) AND the benchmark
deterministic-solve layer consume the same extraction knowledge. New artifact
types are added HERE, once.

Pure-function module (recognizers/generators are deterministic, SKIP=None on any
ambiguity — they inherit each underlying parser's §4.05 conservative envelope).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import kmap_truth_table_oracle_check as _ott   # noqa: E402  parse_truth_table/kmap/fsm/state_enc
import oracle_table_synth as _ots              # noqa: E402  truth/kmap/fsm-bit -> RTL
import kmap_grid_synth as _kg                  # noqa: E402  K-map -> SOP RTL
import waveform_truth_table_synth as _wf       # noqa: E402  waveform table -> RTL
import onehot_fsm_synth as _oh                 # noqa: E402  one-hot FSM -> RTL
import full_moore_fsm_synth as _fm             # noqa: E402  Moore FSM table -> RTL
import ff_truth_table_synth as _ff             # noqa: E402  flip-flop truth table -> RTL
import comb_state_table_synth as _cs           # noqa: E402  combinational state table -> RTL
import mux_synth as _mux                        # noqa: E402  N:1 multiplexer -> RTL
import shift_register_synth as _sr              # noqa: E402  shift/rotate/barrel -> RTL
import cellular_automaton_synth as _ca          # noqa: E402  1-D Wolfram Rule-N CA -> RTL
import lfsr_synth as _lf                        # noqa: E402  Galois LFSR -> RTL
import kmap_sop_synth as _ksop                  # noqa: E402  K-map incl. don't-care (host-verified) -> RTL
# --- v1.1.76 extraction-completeness families (wave-2) ---
import mealy_sequence_synth as _mealy           # noqa: E402  Mealy FSM table / sequence detector -> RTL
import fsm_prose_synth as _fp                    # noqa: E402  combinational one-hot FSM decode -> RTL
import dff_edge_synth as _dffedge               # noqa: E402  DFF / edge-detect / edge-capture -> RTL
import counter_popcount_synth as _cp            # noqa: E402  counter / popcount / parity -> RTL
import encoder_decoder_synth as _enc            # noqa: E402  priority encoder -> RTL
import vector_ops_synth as _vec                 # noqa: E402  bit/byte reverse / extend / split / concat -> RTL
import waveform_ext_synth as _wfx               # noqa: E402  waveform-table envelope extension -> RTL
import comb_gate_synth as _cg                   # noqa: E402  single gate / wire / boolean equation -> RTL
import residual_combinational_synth as _rc      # noqa: E402  constant output / equality comparator -> RTL
# --- v1.1.76 extraction-completeness families (wave-3: aggressive remainder) ---
import arithmetic_synth as _arith               # noqa: E402  half/full/N-bit/2's-comp adder + add-sub -> RTL
import counter_advanced_synth as _cadv          # noqa: E402  BCD/saturating/down/clock counter -> RTL
import serial_protocol_fsm_synth as _spf        # noqa: E402  serial/HDLC/protocol receiver FSM -> RTL
import nextstate_misc_synth as _nsm             # noqa: E402  named one-hot next-state-bit / decode / QM SOP-POS -> RTL
import behavioral_fsm_synth as _bfsm            # noqa: E402  latched seq-detector / reset-pulse counter -> RTL
import comb_advanced_synth as _cadvc            # noqa: E402  advanced combinational catch-all (dedup'd) -> RTL
# --- v1.1.77 wave-4 (multi-part decomposition of the hardest clusters) ---
import sequential_waveform_synth as _seqwf       # noqa: E402  multi-bit/sequential waveform -> RTL
import conway_2d_synth as _c2d                   # noqa: E402  2-D Game-of-Life-class CA -> RTL
import gshare_predictor_synth as _gsh            # noqa: E402  gshare predictor (gate-ready; SKIPs till spec complete) -> RTL
# --- v1.1.83 RTLLM-prose NEW canonicals (general, §4.05 parse-or-SKIP; audit-clean,
#     remediated: parse stated facts, never hardcode/copy-golden) ---
import calendar_counter_synth as _cal             # noqa: E402  cascaded modulo (sec/min/hour) counters -> RTL
import memory_array_synth as _mem                 # noqa: E402  RAM / ROM / LIFO / instruction register -> RTL
import serdes_width_synth as _serdes              # noqa: E402  parallel<->serial / width converter -> RTL
import signal_gen_synth as _siggen                # noqa: E402  signal/square/triangle generator + CDC synchronizer -> RTL


# --------------------------------------------------------------------------- #
# Canonical recognizers — reuse the ONE underlying parser, normalize to a clean
# structured dict. Each returns None (SKIP) when the artifact is absent/ambiguous.
# --------------------------------------------------------------------------- #
def _rec_truth_table(text: str):
    ins, outs = _ott.parse_ports(text)
    if not ins or not outs:
        return None
    r = _ott.parse_truth_table(text, ins, outs)
    if not r:
        return None
    _k, names, out_name, table = r
    return {"inputs": names, "output": out_name,
            "rows": {"".join(str(b) for b in k): v for k, v in sorted(table.items())}}


def _rec_kmap(text: str):
    ins, outs = _ott.parse_ports(text)
    if not ins or not outs:
        return None
    r = _ott.parse_kmap(text, ins, outs)
    if not r:
        return None
    _k, names, out_name, table = r
    return {"inputs": names, "output": out_name, "cells": len(table)}


def _rec_fsm_next_state_bit(text: str):
    ins, outs = _ott.parse_ports(text)
    if not ins or not outs:
        return None
    r = _ott.parse_fsm_next_state_bit(text, ins, outs)
    if not r:
        return None
    _k, in_specs, out_name, table = r
    return {"inputs": [{"name": n, "width": w} for n, w in in_specs],
            "output": out_name, "care_cells": len(table)}


def _rec_fsm_transition_table(text: str):
    r = _fm._parse_fsm_table(text)
    if not r:
        return None
    states, trans, mout, gov = r
    rp = _fm._parse_reset(text, set(states))
    reset = None
    if rp:
        reset = {"state": rp[0], "async": rp[1], "active_high": rp[2]}
    # governing_input: per-state input name (a 2-input arrow FSM gates each state
    # on its own named input); None-valued for the single-implicit-input forms.
    return {"states": states, "transitions": trans, "moore_output": mout,
            "reset": reset, "governing_input": gov}


def _rec_waveform(text: str):
    # the waveform synth fires only on a complete combinational/seq-1FF waveform table
    return {"present": True} if _wf.synth(text, "TopModule") else None


def _rec_onehot_fsm(text: str):
    return {"present": True} if _oh.synth(text, "TopModule") else None


def _rec_ff_truth_table(text: str):
    return {"present": True} if _ff.synth(text, "TopModule") else None


def _rec_comb_state_table(text: str):
    return {"present": True} if _cs.synth(text, "TopModule") else None


def _rec_multiplexer(text: str):
    return {"present": True} if _mux.synth(text, "TopModule") else None


def _rec_shift_register(text: str):
    return {"present": True} if _sr.synth(text, "TopModule") else None


def _rec_cellular_automaton(text: str):
    return {"present": True} if _ca.synth(text, "TopModule") else None


def _rec_galois_lfsr(text: str):
    return {"present": True} if _lf.synth(text, "TopModule") else None


def _rec_kmap_sop(text: str):
    return {"present": True} if _ksop.synth(text, "TopModule") else None


def _rec_mealy_sequence(text: str):
    return {"present": True} if _mealy.synth(text, "TopModule") else None


def _rec_fsm_prose(text: str):
    return {"present": True} if _fp.synth(text, "TopModule") else None


def _rec_dff_edge(text: str):
    return {"present": True} if _dffedge.synth(text, "TopModule") else None


def _rec_counter_popcount(text: str):
    return {"present": True} if _cp.synth(text, "TopModule") else None


def _rec_priority_encoder(text: str):
    return {"present": True} if _enc.synth(text, "TopModule") else None


def _rec_vector_ops(text: str):
    return {"present": True} if _vec.synth(text, "TopModule") else None


def _rec_waveform_ext(text: str):
    return {"present": True} if _wfx.synth(text, "TopModule") else None


def _rec_comb_gate(text: str):
    return {"present": True} if _cg.synth(text, "TopModule") else None


def _rec_residual_combinational(text: str):
    return {"present": True} if _rc.synth(text, "TopModule") else None


def _rec_arithmetic(text: str):
    return {"present": True} if _arith.synth(text, "TopModule") else None


def _rec_counter_advanced(text: str):
    return {"present": True} if _cadv.synth(text, "TopModule") else None


def _rec_serial_protocol_fsm(text: str):
    return {"present": True} if _spf.synth(text, "TopModule") else None


def _rec_nextstate_misc(text: str):
    return {"present": True} if _nsm.synth(text, "TopModule") else None


def _rec_behavioral_fsm(text: str):
    return {"present": True} if _bfsm.synth(text, "TopModule") else None


def _rec_comb_advanced(text: str):
    return {"present": True} if _cadvc.synth(text, "TopModule") else None


def _rec_sequential_waveform(text: str):
    return {"present": True} if _seqwf.synth(text, "TopModule") else None


def _rec_conway_2d(text: str):
    return {"present": True} if _c2d.synth(text, "TopModule") else None


def _rec_gshare_predictor(text: str):
    return {"present": True} if _gsh.synth(text, "TopModule") else None


def _rec_calendar_counter(text: str):
    return {"present": True} if _cal.synth(text, "TopModule") else None


def _rec_memory_array(text: str):
    return {"present": True} if _mem.synth(text, "TopModule") else None


def _rec_serdes_width(text: str):
    return {"present": True} if _serdes.synth(text, "TopModule") else None


def _rec_signal_gen(text: str):
    return {"present": True} if _siggen.synth(text, "TopModule") else None


# --------------------------------------------------------------------------- #
# The catalog
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ArtifactType:
    key: str
    title: str
    l_docs: Tuple[str, ...]                       # home(s) in l_doc_taxonomy
    recognize: Callable[[str], Optional[dict]]    # text -> structured | None
    generate: Optional[Callable[[str, str], Optional[str]]]  # (text, top) -> RTL | None
    desc: str


REGISTRY: Tuple[ArtifactType, ...] = (
    ArtifactType("truth_table", "Truth Table", ("L15", "L4"),
                 _rec_truth_table, _ots.synth,
                 "Column truth table: every input combination's output disclosed."),
    ArtifactType("karnaugh_map", "Karnaugh Map", ("L15",),
                 _rec_kmap, _kg.synth,
                 "Gray-code K-map grid (don't-care-free) for a single 1-bit output."),
    ArtifactType("fsm_transition_table", "FSM Transition Table", ("L6", "L3"),
                 _rec_fsm_transition_table, _fm.synth,
                 "Complete Moore FSM table (arrow or tabular) + state encoding + reset."),
    ArtifactType("fsm_next_state_bit", "FSM Next-State Bit", ("L6",),
                 _rec_fsm_next_state_bit, _ots.synth,
                 "Combinational next-state bit y[N] from a transition table + encoding."),
    ArtifactType("timing_waveform", "Timing / Waveform Table", ("L8T",),
                 _rec_waveform, _wf.synth,
                 "Combinational (or 1-FF) time/input/output waveform table."),
    ArtifactType("onehot_fsm", "One-Hot FSM", ("L6",),
                 _rec_onehot_fsm, _oh.synth,
                 "One-hot encoded FSM next-state/output by inspection."),
    ArtifactType("ff_truth_table", "Flip-Flop Truth Table", ("L6", "L15"),
                 _rec_ff_truth_table, _ff.synth,
                 "Clocked flip-flop truth table with Qold/~Qold next-state cells (JK/D/T/SR)."),
    ArtifactType("comb_state_table", "Combinational State Table", ("L6",),
                 _rec_comb_state_table, _cs.synth,
                 "Combinational next_state+output logic from a table + GIVEN state encoding."),
    # --- v1.1.75 extraction-completeness families (append-only: every entry above
    #     keeps its generate() first-fire; these catch previously-unsolved prompts).
    ArtifactType("multiplexer", "Multiplexer", ("L4", "L15"),
                 _rec_multiplexer, _mux.synth,
                 "N:1 multiplexer (individual ports or packed bus) with stated data/"
                 "select widths and, when the select space exceeds N, a stated default."),
    ArtifactType("shift_register", "Shift / Rotate / Barrel Register", ("L6", "L8T"),
                 _rec_shift_register, _sr.synth,
                 "Clocked shift/rotate/barrel register: width+direction+arith/logical+"
                 "control-priority fully stated."),
    ArtifactType("cellular_automaton", "Cellular Automaton", ("L6", "L4"),
                 _rec_cellular_automaton, _ca.synth,
                 "1-D Wolfram Rule-N CA: stated rule + 3-cell neighbourhood + 0-boundaries."),
    ArtifactType("galois_lfsr", "Galois LFSR", ("L6", "L3"),
                 _rec_galois_lfsr, _lf.synth,
                 "Galois-right LFSR fully stated by width + tap positions + sync reset/seed."),
    ArtifactType("karnaugh_map_sop", "Karnaugh Map (SOP, don't-care-tolerant)", ("L15",),
                 _rec_kmap_sop, _ksop.synth,
                 "K-map grid incl. don't-cares (assigned 0, host-verified), reordered "
                 "headers, 1-var/bus-indexed axes; single 1-bit output. Superset of "
                 "karnaugh_map (which stays the don't-care-free fast path above)."),
    # --- v1.1.76 extraction-completeness families (wave-2). Ordered specific-first,
    #     conservative catch-alls (comb_gate / residual) LAST. The whole REGISTRY is
    #     mutual-exclusion-checked (test_v1_1_76_registry_integration): at most one
    #     generator fires per benchmark prompt, so ordering is a documented tie-break,
    #     not a correctness crutch.
    ArtifactType("mealy_fsm_sequence", "Mealy FSM / Sequence Detector", ("L6", "L3"),
                 _rec_mealy_sequence, _mealy.synth,
                 "Mealy transition+output table, or a stated bit-sequence detector "
                 "(KMP prefix FSM, overlap stated). Output depends on (state,input)."),
    ArtifactType("fsm_prose", "Combinational One-Hot FSM Decode", ("L6", "L8T"),
                 _rec_fsm_prose, _fp.synth,
                 "Pure combinational state[N]->next_state[N] one-hot decode + Moore "
                 "outputs with the encoding pinned by the prompt (next_state is a port)."),
    ArtifactType("dff_edge", "D-Flip-Flop / Edge Detect / Edge Capture", ("L6", "L8T"),
                 _rec_dff_edge, _dffedge.synth,
                 "Simple clocked register: plain/reset(sync|async,polarity,value)/"
                 "byte-enable/feedback DFF, edge-detect (0->1 / 1->0 / any), "
                 "edge-capture (set-and-hold to reset), dual-edge FF."),
    ArtifactType("counter_popcount", "Counter / Popcount / Parity", ("L6", "L4", "L15"),
                 _rec_counter_popcount, _cp.synth,
                 "Population count, parity/reduction-XOR (even ^ / odd ~^), or "
                 "modulo-N up counter (sync active-high reset + optional enable)."),
    ArtifactType("priority_encoder", "Priority Encoder", ("L4", "L15"),
                 _rec_priority_encoder, _enc.synth,
                 "LSB-first priority encoder: input width N + stated direction + "
                 "stated zero-input default; output width ceil(log2(N))."),
    ArtifactType("vector_ops", "Vector Manipulation", ("L4", "L15"),
                 _rec_vector_ops, _vec.synth,
                 "Pure bit-wiring op (bit/byte reverse, sign/zero-extend, hi/lo "
                 "split, passthrough+position bits, concat-then-split), fully stated."),
    ArtifactType("timing_waveform_ext", "Timing/Waveform Table (ext envelope)", ("L8T",),
                 _rec_waveform_ext, _wfx.synth,
                 "Waveform variants the base timing_waveform skips: combinational-by-"
                 "consistency (no clock col) and general posedge-1FF; host-verified."),
    ArtifactType("comb_gate", "Combinational Gate / Wire / Boolean Equation", ("L4", "L15"),
                 _rec_comb_gate, _cg.synth,
                 "Single named logic gate, wire pass-through, per-output reduction/"
                 "2-input gate bank, or an explicit boolean equation (no table)."),
    ArtifactType("residual_combinational", "Residual Combinational (constant / equality)",
                 ("L4", "L15"), _rec_residual_combinational, _rc.synth,
                 "Tiny stateless circuit stated directly: constant output or an "
                 "equality comparator (boolean equations are owned by comb_gate)."),
    # --- v1.1.76 wave-3 (aggressive remainder). Dedicated solvers before the
    #     comb_advanced catch-all (which had its adder/one-hot shapes removed so
    #     arithmetic / nextstate_misc own them — exactly one generator per prompt).
    ArtifactType("arithmetic", "Integer Arithmetic Datapath", ("L4", "L15"),
                 _rec_arithmetic, _arith.synth,
                 "Half/full adder, N-bit ripple adder (overflow MSB), signed "
                 "two's-complement adder + signed-overflow flag, or add/subtract by "
                 "a stated control bit (optional zero flag). SKIPs unstated signedness."),
    ArtifactType("counter_advanced", "Advanced Counter / Timer / Clock", ("L6", "L4", "L15"),
                 _rec_counter_advanced, _cadv.synth,
                 "Multi-digit BCD counter, saturating up/down counter (clamp), "
                 "down-counter timer (load+terminal-count), 12-hour BCD clock, or "
                 "shift-or-decrement/rollback dual register — each fully stated."),
    ArtifactType("serial_protocol_fsm", "Serial / Protocol Receiver FSM", ("L6", "L3"),
                 _rec_serial_protocol_fsm, _spf.synth,
                 "Prose serial/protocol receiver FSM (start/N-data/stop framing "
                 "[+byte capture], HDLC consecutive-1s, serial 2's complementer, "
                 "pattern-detect+delay timer), built from stated parameters."),
    ArtifactType("nextstate_misc", "Named Next-State Bit / Decode / Don't-Care SOP-POS",
                 ("L6", "L4", "L15"), _rec_nextstate_misc, _nsm.synth,
                 "Named one-hot next-state bits (Y<k>=y[k]), binary present-state "
                 "combinational decode + Moore output, or prose don't-care minimum "
                 "SOP/POS (Quine-McCluskey, host-verified)."),
    ArtifactType("behavioral_fsm", "Behavioral-Prose Moore FSM", ("L6", "L3"),
                 _rec_behavioral_fsm, _bfsm.synth,
                 "Mechanically-complete behavioral-prose Moore FSM: latched sequence "
                 "detector (KMP, asserts forever until reset) or reset-pulse counter. "
                 "Narrative FSMs (Lemmings, PS/2) stay an honest AI-floor SKIP."),
    ArtifactType("comb_advanced", "Advanced Combinational (catch-all)", ("L4", "L15", "L6"),
                 _rec_comb_advanced, _cadvc.synth,
                 "case-map / min-max / neighbour-vector / dual-impl / OR-of-ANDs / "
                 "wire-list / pairwise-equality / D-latch (adders + one-hot FSM are "
                 "deduped out — owned by arithmetic / nextstate_misc)."),
    # --- v1.1.77 wave-4: multi-part decomposition of the hardest clusters. Each is
    #     §4.05 SKIP-safe + host-verified; mutually exclusive with all entries above.
    ArtifactType("sequential_waveform_multibit", "Sequential / Multi-bit Waveform Table", ("L8T",),
                 _rec_sequential_waveform, _seqwf.synth,
                 "Multi-bit/sequential waveform variants the binary solvers skip: "
                 "counter-by-delta, multi-bit LUT, symbolic mux, negedge-FF+transparent-"
                 "latch, submodule composition; host-verified."),
    ArtifactType("conway_2d", "2-D Cellular Automaton (Game of Life-class)", ("L6", "L4"),
                 _rec_conway_2d, _c2d.synth,
                 "2-D toroidal Moore (8-neighbour) CA: stated HxW grid + row-major packed "
                 "vector + B.../S... birth/survival rule. Orthogonal to the 1-D Rule-N CA."),
    ArtifactType("gshare_predictor", "gshare Branch Predictor (gate-ready)", ("L6", "L4"),
                 _rec_gshare_predictor, _gsh.synth,
                 "Full gshare datapath (history reg + 2-bit-saturating PHT + PC^history "
                 "index + predict/train bypass). SKIPs unless the reset VALUES are stated "
                 "(spec-absent in Prob153 -> honest floor); fires once a complete spec appears."),
    # --- v1.1.83 RTLLM-prose NEW canonicals. General parse-or-SKIP (audit-clean,
    #     remediated): every emitted fact is parsed from the prose, never hardcoded /
    #     golden-copied; an unstated fact SKIPs. Each fires on the structured prose
    #     form and is verified to fire 0 times on every VE-phrasing prompt.
    ArtifactType("calendar_counter", "Cascaded Modulo Calendar/Clock Counters", ("L6", "L4"),
                 _rec_calendar_counter, _cal.synth,
                 "Cascaded modulo counters (sec/min/hour rollover with stated ranges + "
                 "cascade order). SKIPs an unresolvable cascade / unstated range."),
    ArtifactType("memory_array", "Memory Array (RAM / ROM / LIFO / instr-reg)", ("L4", "L15"),
                 _rec_memory_array, _mem.synth,
                 "Addressable memory array: RAM (stated depth/protocol), ROM (stated "
                 "contents), LIFO stack, instruction register (parsed field layout). "
                 "SKIPs unstated init/protocol/layout."),
    ArtifactType("serdes_width", "Serial<->Parallel / Width Converter", ("L6", "L8T"),
                 _rec_serdes_width, _serdes.synth,
                 "parallel-to-serial / serial-to-parallel / N-to-M width converter with a "
                 "PARSED load/shift protocol + bit-order + packing order. SKIPs unstated "
                 "direction/order."),
    ArtifactType("signal_gen", "Signal / Square / Triangle Generator + Synchronizer", ("L6", "L8T"),
                 _rec_signal_gen, _siggen.synth,
                 "Periodic signal/square/triangle generator (stated period/bound) + a "
                 "multi-FF CDC synchronizer (structural detect). SKIPs an unstated "
                 "bound/period."),
)

_BY_KEY: Dict[str, ArtifactType] = {a.key: a for a in REGISTRY}


def types() -> List[str]:
    return [a.key for a in REGISTRY]


def detect(text: str) -> List[dict]:
    """Every artifact type recognized in `text`, with its extracted structured form
    and its l_doc_taxonomy home. This is the IC-Expert-Agent's "what structured
    information is in this spec, and what is it" primitive."""
    found = []
    for a in REGISTRY:
        try:
            s = a.recognize(text) if a.recognize else None
        except Exception:
            s = None
        if s is not None:
            found.append({"type": a.key, "title": a.title,
                          "l_docs": list(a.l_docs), "structured": s})
    return found


def generate(text: str, top: str = "TopModule") -> Tuple[Optional[str], Optional[str]]:
    """Deterministic RTL from the first artifact type whose generator fires.
    Returns (artifact_type, rtl) or (None, None). The benchmark §4.2 absorption
    chain and Phase-2 short-circuit both route through here."""
    for a in REGISTRY:
        if not a.generate:
            continue
        try:
            rtl = a.generate(text, top)
        except Exception:
            rtl = None
        if rtl:
            return a.key, rtl
    return None, None


# --------------------------------------------------------------------------- #
# Record-level operation solvers — the UNIFIED dispatch.
#
# These operation-named solvers (gf / bcd / crc / hamming / encoder / memory /
# shift_counter / …) take a full benchmark RECORD and do their OWN interface
# extraction (via the record-adapter helpers in `cvdp_atomic_bridge`, which is the
# thin record→ports adapter, NOT a dispatcher). They program-SOLVE special-algebra
# / structural datapaths the text-level REGISTRY above SKIPs. They run FIRST (their
# declared order is the precedence — first non-None wins), then `generate()` is the
# text-level fall-through. This is the SINGLE deterministic-solver dispatch: the
# bridge is now a thin driver that calls ONLY `generate_from_record()`.
#
# DEFERRED import (the solvers `import cvdp_atomic_bridge` for the record-adapter
# helpers; importing them at registry module-load time, while the bridge is still
# importing the registry's own helpers, would race a half-initialized module). The
# load runs lazily on the first `generate_from_record()` call, by which time every
# module is fully defined — GENERAL for every present + future record solver.
_RECORD_SOLVER_NAMES = (
    "gf_synth", "bcd_synth", "crc_synth",
    "conv_encoder_synth", "sort_synth", "dice_roller_synth",
    "firstbit_synth", "fibonacci_synth",
    "encoder_synth", "graycode_parity_synth",
    "shift_counter_synth", "compose_synth", "hamming_synth",
    "mux_compare_synth", "accumulate_synth", "memory_synth",
    "arith_variants_synth", "table_lut_synth", "saturate_synth",
    "bitmanip_synth", "serdes_decode_synth", "modify_complete_synth",
)
_RECORD_SOLVERS: List = []
_RECORD_SOLVER_IMPORT_ERRORS: List[Tuple[str, str]] = []


def _load_record_solvers() -> List:
    """Import the record solvers in `_RECORD_SOLVER_NAMES` order (declared
    precedence) and populate `_RECORD_SOLVERS`. Idempotent. A solver missing a
    callable `solve` is skipped (recorded in `_RECORD_SOLVER_IMPORT_ERRORS`)."""
    if _RECORD_SOLVERS:
        return _RECORD_SOLVERS
    _RECORD_SOLVER_IMPORT_ERRORS.clear()
    for _name in _RECORD_SOLVER_NAMES:
        try:
            _mod = __import__(_name)
        except Exception as _e:               # absent / broken solver — record, skip
            _RECORD_SOLVER_IMPORT_ERRORS.append((_name, repr(_e)))
            continue
        if not callable(getattr(_mod, "solve", None)):
            _RECORD_SOLVER_IMPORT_ERRORS.append((_name, "no callable solve()"))
            continue
        _RECORD_SOLVERS.append(_mod)
    return _RECORD_SOLVERS


def generate_from_record(record: dict, text_fallthrough=None) -> Optional[str]:
    """The UNIFIED deterministic-solver dispatch for a benchmark RECORD.
    Runs every record-level operation solver in declared precedence (first
    non-None wins); returns its RTL, or None. The text-level `generate()`
    fall-through is the caller's responsibility (the bridge supplies the
    record→ports adaptation it needs first), passed as `text_fallthrough` —
    a `() -> Optional[str]` thunk — and invoked only when no record solver fires."""
    import copy as _copy
    if not isinstance(record, dict):
        return None
    for _solver in _load_record_solvers():
        try:
            _rtl = _solver.solve(_copy.deepcopy(record))
        except Exception:
            _rtl = None
        if _rtl:
            return _rtl
    if text_fallthrough is not None:
        try:
            return text_fallthrough()
        except Exception:
            return None
    return None


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="spec / prompt / extracted doc text")
    ap.add_argument("--generate", action="store_true", help="also emit RTL if synthesizable")
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args(argv)
    text = Path(a.prompt).read_text(errors="replace")
    out = {"artifacts": detect(text)}
    if a.generate:
        k, rtl = generate(text, a.top)
        out["generated"] = {"type": k, "rtl_present": bool(rtl)}
        if rtl:
            out["rtl"] = rtl
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
