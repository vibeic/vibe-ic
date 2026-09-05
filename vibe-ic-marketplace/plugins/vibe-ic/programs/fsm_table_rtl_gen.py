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

  Multiple one-cycle protocol outputs owned by named states use the additive
  ``state_outputs`` map.  Each signal is a Moore decode of CURRENT state and is
  therefore deasserted outside its owner state(s):

    "state_outputs": {
      "return_change": ["RETURN_CHANGE"],
      "error": ["RETURN_MONEY"],
      "return_money": ["RETURN_MONEY"]
    }

  PULSED EVENTS that must survive until acknowledged use the additive ``events``
  map.  Each entry declares, in the INPUT, how the request signal BEHAVES — the
  one thing a generator must never infer:

    "events": {
      "irq_a": {"kind": "pulse", "ack": "ack_a",
                "deadline": 16, "starvation_out": "starved_a"},
      "irq_b": {"kind": "level"}
    }

  ``kind: "pulse"``  the source drives the request for a single cycle, so the
    request MUST be captured into a pending bit that sets on the pulse and clears
    only on its acknowledgment.  Set is dominant: a fresh request arriving in the
    same cycle as the previous acknowledgment is retained, never dropped.
  ``kind: "level"``  the source HOLDS the request until it is taken.  No pending
    storage is emitted — a held request needs none, and adding one would force a
    single topology onto a legitimate alternative architecture.
  ``deadline: N`` + ``starvation_out``  a bounded wait counter per pending event;
    the named output asserts once that event has waited N cycles without being
    acknowledged, so a starved contender REPORTS itself instead of waiting mutely.

  ``kind`` is REQUIRED and is never inferred.  A pulse with no ``ack``, a
  ``deadline`` with no ``starvation_out`` (or the reverse), or an ``events`` map on
  a clockless ``moore_comb`` spec are all REFUSED BY NAME so the unresolved
  interpretation is routed to AI rather than guessed.

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
import re
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


def _state_outputs(spec: dict) -> Dict[str, List[str]]:
    """Normalized ``signal -> [owner states]`` map, preserving input order."""
    raw = spec.get("state_outputs", {}) or {}
    if not isinstance(raw, dict):
        raise ValueError("state_outputs must be a signal-to-state-list mapping")
    out: Dict[str, List[str]] = {}
    for signal, owners in raw.items():
        if not isinstance(signal, str) or not re.fullmatch(r"[A-Za-z_]\w*", signal):
            raise ValueError(f"invalid state-output signal: {signal!r}")
        if isinstance(owners, str):
            owners = [owners]
        if not isinstance(owners, list) or not owners:
            raise ValueError(f"state_outputs[{signal!r}] must name at least one state")
        normalized: List[str] = []
        for owner in owners:
            if not isinstance(owner, str):
                raise ValueError(f"state_outputs[{signal!r}] has a non-string state")
            if owner not in normalized:
                normalized.append(owner)
        out[signal] = normalized
    return out


def _append_state_outputs(lines: List[str], spec: dict, state_expr: str,
                          enc: Dict[str, int]) -> None:
    """Emit one-hot current-state decodes for named-state protocol outputs.

    Equality is the default deassertion: once ``state_expr`` is not an owner,
    the output is zero without a stored pulse that can trail the state by an
    NBA phase.
    """
    for signal, owners in _state_outputs(spec).items():
        ordered = sorted(owners, key=lambda state: enc[state])
        cond = " || ".join(f"({state_expr} == {state})" for state in ordered)
        lines.append(f"  assign {signal} = {cond};")


_EVENT_KINDS = ("pulse", "level")

#: Largest wait bound that still sizes an implementable counter (32 bits).
_EVENT_DEADLINE_MAX = (1 << 32) - 1


def _events(spec: dict) -> Dict[str, dict]:
    """Normalized ``event -> contract`` map extracted from the INPUT ONLY.

    Every field that decides emitted structure is READ, never inferred.  Anything
    the spec leaves unresolved raises with the event named, so the caller routes
    that one interpretation to AI instead of receiving a guessed topology.
    """
    raw = spec.get("events", {}) or {}
    if not isinstance(raw, dict):
        raise ValueError("events must be an event-to-contract mapping")
    out: Dict[str, dict] = {}
    for name, contract in raw.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError(f"invalid event signal: {name!r}")
        if not isinstance(contract, dict):
            raise ValueError(f"events[{name!r}] must be a mapping")
        kind = contract.get("kind")
        if kind is None:
            raise ValueError(
                f"events[{name!r}] does not state 'kind'; pulse-vs-level is not "
                f"inferable from the input — route to AI, do not guess")
        if kind not in _EVENT_KINDS:
            raise ValueError(
                f"events[{name!r}] has unknown kind {kind!r}; "
                f"expected one of {list(_EVENT_KINDS)}")
        ack = contract.get("ack")
        if kind == "pulse" and not ack:
            raise ValueError(
                f"events[{name!r}] is pulsed but names no 'ack'; the clearing "
                f"event is not inferable from the input — route to AI")
        if ack is not None and (not isinstance(ack, str)
                                or not re.fullmatch(r"[A-Za-z_]\w*", ack)):
            raise ValueError(f"events[{name!r}] has an invalid 'ack' signal")
        deadline = contract.get("deadline")
        starve = contract.get("starvation_out")
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, int) \
                    or deadline < 1:
                raise ValueError(
                    f"events[{name!r}] 'deadline' must be a positive integer "
                    f"cycle count")
            # BOUNDED. The deadline is INPUT and sizes an emitted counter, so an
            # absurd value silently produces a several-hundred-bit register that
            # no synthesiser will take. Refuse it like any other unusable field
            # rather than emitting nonsense.
            if deadline > _EVENT_DEADLINE_MAX:
                raise ValueError(
                    f"events[{name!r}] 'deadline' of {deadline} exceeds "
                    f"{_EVENT_DEADLINE_MAX}; that is not a wait bound, and the "
                    f"counter it would size is not implementable")
            if not starve:
                raise ValueError(
                    f"events[{name!r}] sets a deadline but names no "
                    f"'starvation_out'; the report signal is not inferable")
        if starve:
            if not isinstance(starve, str) \
                    or not re.fullmatch(r"[A-Za-z_]\w*", starve):
                raise ValueError(
                    f"events[{name!r}] has an invalid 'starvation_out' signal")
            if deadline is None:
                raise ValueError(
                    f"events[{name!r}] names a starvation output but no "
                    f"'deadline'; the bound is not inferable — route to AI")
        out[name] = {"kind": kind, "ack": ack,
                     "deadline": deadline, "starvation_out": starve}
    # CROSS-EVENT CONFLICTS. Each starvation output is DRIVEN, so two events
    # naming the same one produce two continuous assignments on one wire. That
    # is legal Verilog — iverilog compiles it without a word — and it resolves to
    # X the moment the two disagree, so a genuinely starved event reports an
    # unusable value with no diagnostic anywhere. That is precisely the defect
    # class this contract exists to remove, so it is refused here.
    # An ACK may legitimately be shared: one acknowledgment clearing several
    # pending events is a real design, and nothing is driven by it.
    drivers: Dict[str, str] = {}
    for name, c in out.items():
        sig = c["starvation_out"]
        if not sig:
            continue
        if sig in drivers:
            raise ValueError(
                f"events[{name!r}] and events[{drivers[sig]!r}] both drive "
                f"starvation output '{sig}'; one wire cannot report two events")
        drivers[sig] = name
    for name, c in out.items():
        sig = c["starvation_out"]
        if not sig:
            continue
        if sig in out:
            raise ValueError(
                f"starvation output '{sig}' of events[{name!r}] is also an "
                f"event request input; it cannot be both driven and driving")
        for other, oc in out.items():
            if oc["ack"] == sig:
                raise ValueError(
                    f"starvation output '{sig}' of events[{name!r}] is also the "
                    f"acknowledgment of events[{other!r}]; it cannot be both an "
                    f"output and an input")
    return out


def _event_ports(spec: dict) -> List[str]:
    """Port declarations the event contract adds, in stable input order."""
    ports: List[str] = []
    seen = set()
    for name, c in _events(spec).items():
        for sig in (name, c["ack"]):
            if sig and sig not in seen:
                seen.add(sig)
                ports.append(f"  input        {sig}")
    for name, c in _events(spec).items():
        if c["starvation_out"] and c["starvation_out"] not in seen:
            seen.add(c["starvation_out"])
            ports.append(f"  output       {c['starvation_out']}")
    return ports


def _append_event_logic(lines: List[str], spec: dict, clk: str,
                        reset: dict) -> None:
    """Emit pending/ack storage and the bounded starvation report.

    A ``level`` event is HELD by its source and deliberately gets no storage:
    the rule fires on the declared behaviour, not on the word "interrupt".
    """
    evs = _events(spec)
    if not evs:
        return
    rst_test = _reset_test(reset) if reset else None
    for name, c in evs.items():
        if c["kind"] != "pulse":
            continue
        ack = c["ack"]
        pend = f"pending_{name}"
        lines.append("")
        lines.append(f"  // '{name}' is pulsed: hold it until '{ack}'. Set is")
        lines.append(f"  // dominant so a request coincident with an ack is kept.")
        lines.append(f"  reg {pend};")
        lines.append(f"  always @({_reset_sensitivity(reset, clk) if reset else 'posedge ' + clk}) begin")
        if rst_test:
            lines.append(f"    if ({rst_test}) {pend} <= 1'b0;")
            lines.append(f"    else {pend} <= {name} || ({pend} && !{ack});")
        else:
            lines.append(f"    {pend} <= {name} || ({pend} && !{ack});")
        lines.append("  end")
        if c["deadline"] is not None:
            dl = c["deadline"]
            cw = max(1, int(dl).bit_length())
            wait = f"wait_{name}"
            lines.append(f"  // bounded wait: report starvation after {dl} unacknowledged cycles")
            lines.append(f"  reg [{cw-1}:0] {wait};")
            lines.append(f"  always @({_reset_sensitivity(reset, clk) if reset else 'posedge ' + clk}) begin")
            if rst_test:
                lines.append(f"    if ({rst_test}) {wait} <= {cw}'d0;")
                lines.append(f"    else if (!{pend} || {ack}) {wait} <= {cw}'d0;")
            else:
                lines.append(f"    if (!{pend} || {ack}) {wait} <= {cw}'d0;")
            lines.append(f"    else if ({wait} != {cw}'d{dl}) {wait} <= {wait} + {cw}'d1;")
            lines.append("  end")
            lines.append(f"  assign {c['starvation_out']} = {pend} && ({wait} == {cw}'d{dl});")


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
    state_out = _state_outputs(spec)
    for signal, owners in state_out.items():
        for owner in owners:
            if owner not in enc:
                raise ValueError(
                    f"state-output '{signal}' owner '{owner}' not in encoding")
    if spec["kind"] in ("moore_comb", "moore_seq") \
            and "outputs" not in spec and not state_out:
        raise ValueError("Moore FSM requires per-state 'outputs' or 'state_outputs'")
    if spec["kind"] == "mealy_seq" and "outputs" not in spec:
        raise ValueError("Mealy FSM requires per-state/input 'outputs'")
    evs = _events(spec)
    if evs and spec["kind"] == "moore_comb":
        raise ValueError(
            "events require a clocked FSM; 'moore_comb' is combinational — "
            "state the sequential kind or drop the events contract")
    for _name, _c in evs.items():
        for _sig in (_name, _c["ack"], _c["starvation_out"]):
            if _sig and _sig in enc:
                raise ValueError(
                    f"event signal '{_sig}' collides with a state name")
        if _name in state_out or (_c["starvation_out"] or "") in state_out:
            raise ValueError(
                f"event '{_name}' collides with a state_outputs signal")
    legacy_out = spec.get("output", "out")
    if "outputs" in spec and legacy_out in state_out:
        raise ValueError(
            f"output '{legacy_out}' is declared by both outputs and state_outputs")


def _gen_moore_comb(spec: dict) -> str:
    enc = spec["encoding"]; trans = spec["transitions"]
    outs = spec.get("outputs")
    w = _state_width(enc)
    si = spec.get("state_in", "state")
    no = spec.get("next_state_out", "next_state")
    inp = spec.get("input", "in")
    out = spec.get("output", "out")
    ivals = _input_values(trans)

    ports = [f"  input        {inp}",
             f"  input  [{w-1}:0] {si}",
             f"  output reg [{w-1}:0] {no}"]
    if outs is not None:
        ports.append(f"  output       {out}")
    ports.extend(f"  output       {signal}" for signal in _state_outputs(spec))
    lines = [f"module {spec['module']} ("]
    lines.extend(p + ("," if i < len(ports) - 1 else "")
                 for i, p in enumerate(ports))
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
    if outs is not None:
        one_states = [s for s, o in outs.items() if int(o) == 1]
        if one_states:
            cond = " || ".join(f"({si} == {s})" for s in sorted(one_states, key=lambda s: enc[s]))
            lines.append(f"  assign {out} = {cond};")
        else:
            lines.append(f"  assign {out} = 1'b0;")
    _append_state_outputs(lines, spec, si, enc)
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

    ports = [f"  input        {clk}"]
    if reset:
        ports.append(f"  input        {reset['name']}")
    ports.append(f"  input        {inp}")
    if mealy or "outputs" in spec:
        ports.append(f"  output       {out}")
    ports.extend(f"  output       {signal}" for signal in _state_outputs(spec))
    ports.extend(_event_ports(spec))
    lines = [f"module {spec['module']} ("]
    lines.extend(p + ("," if i < len(ports) - 1 else "")
                 for i, p in enumerate(ports))
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
    elif "outputs" in spec:
        one_states = [s for s, o in outs.items() if int(o) == 1]
        if one_states:
            cond = " || ".join(f"(state == {s})" for s in sorted(one_states, key=lambda s: enc[s]))
            lines.append(f"  assign {out} = {cond};")
        else:
            lines.append(f"  assign {out} = 1'b0;")
    _append_state_outputs(lines, spec, "state", enc)
    _append_event_logic(lines, spec, clk, reset)
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
