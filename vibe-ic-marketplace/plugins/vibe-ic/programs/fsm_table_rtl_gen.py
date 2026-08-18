#!/usr/bin/env python3
"""fsm_table_rtl_gen.py — deterministic FSM-table → synthesizable RTL generator.

since v0.1.6.

Phase-2 "program writes the RTL" enhancement, driven by the VerilogEval-v2 run:
many problems hand the design an EXPLICIT state-transition table (e.g. Prob100
fsm3comb: "A | A,B | 0 / B | C,B | 0 / ..."), for which the RTL is mechanically
derivable — yet Phase 2 had no deterministic generator and fell back to a blind
LLM shot. This closes that gap: given a structured FSM contract (states, encoding,
transition table, per-state/Mealy outputs), it emits correct, synthesizable
Verilog deterministically — no LLM, no don't-care guessing.

Three kinds:
  - moore_comb : combinational next-state + Moore output logic only (the
    "implement the combinational portion" problems). Ports: current-state input,
    next-state output, input(s), output(s).
  - moore_seq  : registered state (clk + reset), Moore output = f(state).
  - mealy_seq  : registered state (clk + reset), Mealy output = f(state, input).

Input spec (JSON or YAML), e.g.:
    {
      "module": "TopModule", "kind": "moore_comb",
      "input": "in", "state_in": "state", "next_state_out": "next_state",
      "output": "out",
      "encoding": {"A": 0, "B": 1, "C": 2, "D": 3},
      "transitions": {"A": {"0": "A", "1": "B"}, "B": {"0": "C", "1": "B"},
                      "C": {"0": "A", "1": "D"}, "D": {"0": "C", "1": "B"}},
      "outputs": {"A": 0, "B": 0, "C": 0, "D": 1}
    }
  For *_seq add: "clk": "clk", "reset": {"name":"reset","mode":"sync","polarity":"high","to":"A"}.

chip-AGNOSTIC: pure table→logic transform; no IC-, bus-, or protocol-specific
knowledge. Deterministic: same spec → byte-identical RTL.

CLI:
    python3 fsm_table_rtl_gen.py <spec.json|spec.yaml> [-o out.sv]

Exit codes: 0 = wrote RTL   1 = invalid spec   2 = file/parse error
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List


def _load(path: Path) -> dict:
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def _state_width(encoding: Dict[str, int]) -> int:
    if not encoding:
        raise ValueError("encoding is empty")
    hi = max(encoding.values())
    return max(1, hi.bit_length())


def _enc_lit(width: int, value: int) -> str:
    return f"{width}'d{value}"


def _input_values(transitions: Dict[str, dict]) -> List[str]:
    vals = set()
    for tbl in transitions.values():
        vals.update(str(k) for k in tbl.keys())
    # numeric input values, sorted ascending
    return sorted(vals, key=lambda v: int(v))


def _validate(spec: dict) -> None:
    for req in ("module", "kind", "encoding", "transitions"):
        if req not in spec:
            raise ValueError(f"spec missing required key: {req}")
    if spec["kind"] not in ("moore_comb", "moore_seq", "mealy_seq"):
        raise ValueError(f"unknown kind: {spec['kind']}")
    enc, trans = spec["encoding"], spec["transitions"]
    for s in trans:
        if s not in enc:
            raise ValueError(f"transition state '{s}' not in encoding")
        for nxt in trans[s].values():
            if nxt not in enc:
                raise ValueError(f"next-state '{nxt}' (from '{s}') not in encoding")
    if spec["kind"].startswith("moore") and spec["kind"] != "moore_comb":
        pass
    if spec["kind"] in ("moore_comb", "moore_seq") and "outputs" not in spec:
        raise ValueError("Moore FSM requires per-state 'outputs'")


def _gen_moore_comb(spec: dict) -> str:
    enc = spec["encoding"]; trans = spec["transitions"]; outs = spec["outputs"]
    w = _state_width(enc)
    si = spec.get("state_in", "state")
    no = spec.get("next_state_out", "next_state")
    inp = spec.get("input", "in")
    out = spec.get("output", "out")
    ivals = _input_values(trans)

    lines = [f"module {spec['module']} ("]
    lines.append(f"  input        {inp},")
    lines.append(f"  input  [{w-1}:0] {si},")
    lines.append(f"  output reg [{w-1}:0] {no},")
    lines.append(f"  output       {out}")
    lines.append(");")
    # state localparams
    for s, v in sorted(enc.items(), key=lambda kv: kv[1]):
        lines.append(f"  localparam {s} = {_enc_lit(w, v)};")
    lines.append("")
    # next-state combinational
    lines.append(f"  always @(*) begin")
    lines.append(f"    case ({si})")
    for s, v in sorted(enc.items(), key=lambda kv: kv[1]):
        tbl = trans.get(s, {})
        if set(tbl.keys()) == set(ivals) and len(ivals) == 2 and "0" in tbl and "1" in tbl:
            expr = f"{inp} ? {tbl['1']} : {tbl['0']}"
            lines.append(f"      {s}: {no} = {expr};")
        else:
            # general: nested case on input
            lines.append(f"      {s}: case ({inp})")
            for iv in ivals:
                lines.append(f"               {len(ivals).bit_length() if False else 1}'d{iv}: {no} = {tbl[iv]};")
            lines.append(f"               default: {no} = {s};")
            lines.append(f"             endcase")
    lines.append(f"      default: {no} = {si};")
    lines.append(f"    endcase")
    lines.append(f"  end")
    lines.append("")
    # Moore output
    one_states = [s for s, o in outs.items() if int(o) == 1]
    if one_states:
        cond = " || ".join(f"({si} == {s})" for s in sorted(one_states, key=lambda s: enc[s]))
        lines.append(f"  assign {out} = {cond};")
    else:
        lines.append(f"  assign {out} = 1'b0;")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def _reset_sensitivity(reset: dict, clk: str) -> str:
    if reset and reset.get("mode") == "async":
        edge = "negedge" if reset.get("polarity") == "low" else "posedge"
        return f"posedge {clk} or {edge} {reset['name']}"
    return f"posedge {clk}"


def _reset_test(reset: dict) -> str:
    if reset.get("polarity") == "low":
        return f"!{reset['name']}"
    return f"{reset['name']}"


def _gen_seq(spec: dict) -> str:
    enc = spec["encoding"]; trans = spec["transitions"]
    w = _state_width(enc)
    clk = spec.get("clk", "clk")
    inp = spec.get("input", "in")
    out = spec.get("output", "out")
    reset = spec.get("reset", {})
    mealy = spec["kind"] == "mealy_seq"
    outs = spec.get("outputs", {})
    ivals = _input_values(trans)

    lines = [f"module {spec['module']} ("]
    lines.append(f"  input        {clk},")
    if reset:
        lines.append(f"  input        {reset['name']},")
    lines.append(f"  input        {inp},")
    lines.append(f"  output       {out}")
    lines.append(");")
    for s, v in sorted(enc.items(), key=lambda kv: kv[1]):
        lines.append(f"  localparam {s} = {_enc_lit(w, v)};")
    lines.append(f"  reg [{w-1}:0] state, next_state;")
    lines.append("")
    # next-state comb
    lines.append(f"  always @(*) begin")
    lines.append(f"    case (state)")
    for s, v in sorted(enc.items(), key=lambda kv: kv[1]):
        tbl = trans.get(s, {})
        if len(ivals) == 2 and "0" in tbl and "1" in tbl:
            lines.append(f"      {s}: next_state = {inp} ? {tbl['1']} : {tbl['0']};")
        else:
            lines.append(f"      {s}: case ({inp})")
            for iv in ivals:
                lines.append(f"               1'd{iv}: next_state = {tbl[iv]};")
            lines.append(f"               default: next_state = {s};")
            lines.append(f"             endcase")
    lines.append(f"      default: next_state = state;")
    lines.append(f"    endcase")
    lines.append(f"  end")
    lines.append("")
    # state register
    sens = _reset_sensitivity(reset, clk) if reset else f"posedge {clk}"
    lines.append(f"  always @({sens}) begin")
    if reset:
        to = reset.get("to")
        lines.append(f"    if ({_reset_test(reset)}) state <= {to};")
        lines.append(f"    else state <= next_state;")
    else:
        lines.append(f"    state <= next_state;")
    lines.append(f"  end")
    lines.append("")
    # output
    if mealy:
        # outputs keyed "state,input" → value
        lines.append(f"  reg {out}_r;")
        lines.append(f"  always @(*) begin")
        lines.append(f"    case (state)")
        mo = spec["outputs"]
        for s, v in sorted(enc.items(), key=lambda kv: kv[1]):
            lines.append(f"      {s}: {out}_r = {inp} ? 1'b{int(mo.get(f'{s},1', 0))} : 1'b{int(mo.get(f'{s},0', 0))};")
        lines.append(f"      default: {out}_r = 1'b0;")
        lines.append(f"    endcase")
        lines.append(f"  end")
        lines.append(f"  assign {out} = {out}_r;")
    else:
        one_states = [s for s, o in outs.items() if int(o) == 1]
        if one_states:
            cond = " || ".join(f"(state == {s})" for s in sorted(one_states, key=lambda s: enc[s]))
            lines.append(f"  assign {out} = {cond};")
        else:
            lines.append(f"  assign {out} = 1'b0;")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def generate(spec: dict) -> str:
    _validate(spec)
    if spec["kind"] == "moore_comb":
        return _gen_moore_comb(spec)
    return _gen_seq(spec)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="FSM spec JSON or YAML")
    ap.add_argument("-o", "--out", help="output .sv path (default: stdout)")
    a = ap.parse_args()
    p = Path(a.spec)
    if not p.is_file():
        print(f"fsm_table_rtl_gen: spec not found: {p}", file=sys.stderr)
        return 2
    try:
        spec = _load(p)
        rtl = generate(spec)
    except (ValueError, KeyError) as e:
        print(f"fsm_table_rtl_gen: invalid spec: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # parse error
        print(f"fsm_table_rtl_gen: {e}", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
        print(f"fsm_table_rtl_gen: wrote {a.out} ({rtl.count(chr(10))} lines)")
    else:
        sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
