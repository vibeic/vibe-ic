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
