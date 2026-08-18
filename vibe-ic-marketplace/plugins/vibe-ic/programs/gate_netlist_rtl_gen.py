#!/usr/bin/env python3
"""gate_netlist_rtl_gen.py — deterministic gate-netlist → RTL generator.

since v0.1.8.

Phase-2 "program writes the RTL" generator (with fsm_table_rtl_gen +
truth_table_rtl_gen). Driven by the VerilogEval-v2 run: many problems are a plain
list of logic gates and wire connections (e.g. Prob065 7420 = two 4-input NAND,
Prob081 7458, Prob077/059 wire connections) for which the RTL is a mechanical
`assign` per gate — yet Phase 2 fell back to a blind LLM shot. Given a structured
gate netlist it emits the corresponding combinational RTL DETERMINISTICALLY.

Supported gate ops (each: output net + ordered input nets):
  and  or  nand  nor  xor  xnor  not  buf
A "net" is a module input/output port or an internal wire; a `not`/`buf` takes
exactly one input.

Input spec (JSON or YAML), e.g. (Prob065 7420):
    {
      "module": "TopModule",
      "inputs":  ["p1a","p1b","p1c","p1d","p2a","p2b","p2c","p2d"],
      "outputs": ["p1y","p2y"],
      "gates": [
        {"op": "nand", "out": "p1y", "in": ["p1a","p1b","p1c","p1d"]},
        {"op": "nand", "out": "p2y", "in": ["p2a","p2b","p2c","p2d"]}
      ]
    }
  Optional "wires": ["w1", ...] for internal nets (declared as `wire`).

chip-AGNOSTIC. Deterministic: same spec → byte-identical RTL.

CLI:
    python3 gate_netlist_rtl_gen.py <spec.json|spec.yaml> [-o out.sv]

Exit codes: 0 = wrote RTL   1 = invalid spec   2 = file/parse error
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

_BINARY = {"and": "&", "or": "|", "xor": "^"}
_INVERTED = {"nand": "&", "nor": "|", "xnor": "^"}


def _port_decl(direction: str, p) -> str:
    if isinstance(p, str):
        return f"  {direction} {p}"
    w = int(p.get("width", 1))
    rng = f" [{w-1}:0]" if w > 1 else ""
    return f"  {direction}{rng} {p['name']}"


def _name(p) -> str:
    return p if isinstance(p, str) else p["name"]


def _gate_expr(g: dict) -> str:
    op = g["op"].lower()
    ins = g["in"]
    if op in ("not", "buf"):
        if len(ins) != 1:
            raise ValueError(f"{op} gate '{g.get('out')}' needs exactly 1 input")
        return f"~{ins[0]}" if op == "not" else f"{ins[0]}"
    if not ins:
        raise ValueError(f"gate '{g.get('out')}' has no inputs")
    if op in _BINARY:
        return f" {_BINARY[op]} ".join(ins)
    if op in _INVERTED:
        return f"~({(' ' + _INVERTED[op] + ' ').join(ins)})"
    raise ValueError(f"unknown gate op: {op}")


def generate(spec: dict) -> str:
    if "module" not in spec or "gates" not in spec:
        raise ValueError("spec needs 'module' and 'gates'")
    ins = spec.get("inputs") or []
    outs = spec.get("outputs") or []
    if not outs:
        raise ValueError("spec needs at least one output")
    wires = spec.get("wires") or []
    out_names = {_name(o) for o in outs}

    lines = [f"module {spec['module']} ("]
    decls = [_port_decl("input", p) for p in ins] + [_port_decl("output", p) for p in outs]
    lines.append(",\n".join(decls))
    lines.append(");")
    for w in wires:
        lines.append(f"  wire {w};")
    driven = set()
    for g in spec["gates"]:
        out = g["out"]
        if out in driven:
            raise ValueError(f"net '{out}' driven by more than one gate")
        driven.add(out)
        expr = _gate_expr(g)
        lines.append(f"  assign {out} = {expr};")
    # every declared output must be driven
    missing = sorted(out_names - driven)
    if missing:
        raise ValueError(f"output(s) not driven by any gate: {missing}")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    p = Path(a.spec)
    if not p.is_file():
        print(f"gate_netlist_rtl_gen: spec not found: {p}", file=sys.stderr)
        return 2
    try:
        text = p.read_text()
        spec = (__import__("yaml").safe_load(text) if p.suffix.lower() in (".yaml", ".yml")
                else json.loads(text))
        rtl = generate(spec)
    except (ValueError, KeyError) as e:
        print(f"gate_netlist_rtl_gen: invalid spec: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"gate_netlist_rtl_gen: {e}", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
        print(f"gate_netlist_rtl_gen: wrote {a.out} ({rtl.count(chr(10))} lines)")
    else:
        sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
