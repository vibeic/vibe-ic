#!/usr/bin/env python3
"""vector_op_rtl_gen.py — deterministic vector-operation → RTL generator.

since v0.1.8.

Phase-2 "program writes the RTL" generator (with fsm_table / truth_table /
gate_netlist). Driven by the VerilogEval-v2 run: a family of problems are pure
bit-plumbing — reverse byte/bit order (Prob004 vector2, Prob006 vectorr,
Prob023 vector100r), split a wide bus into fields (Prob015 vector1), concatenate
fields (Prob064 vector3), sign-/zero-extend (Prob042 vector4) — for which the
RTL is a single mechanical `assign`. Given a structured vector-op contract it
emits that RTL DETERMINISTICALLY.

Ops:
  reverse      : out = in with `chunk`-bit groups reversed (chunk=1 → bit reverse,
                 chunk=8 → byte reverse). in/out widths equal, divisible by chunk.
  split        : one input → ordered MSB-first output slices (Σ out widths == in width).
  concat       : ordered MSB-first parts → one output (Σ part widths == out width).
                 parts are literal RTL expressions, e.g. "a", "b[3:0]", "2'b11".
  sign_extend  : out = {{(W-w){in[w-1]}}, in}            (W > w).
  zero_extend  : out = {{(W-w){1'b0}},  in}.

Input spec (JSON or YAML), e.g. (Prob004 byte-reverse):
    {"module":"TopModule","op":"reverse","chunk":8,
     "inputs":[{"name":"in","width":32}],"outputs":[{"name":"out","width":32}]}

chip-AGNOSTIC. Deterministic: same spec → byte-identical RTL.

CLI:
    python3 vector_op_rtl_gen.py <spec.json|spec.yaml> [-o out.sv]

Exit codes: 0 = wrote RTL   1 = invalid spec   2 = file/parse error
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import List


def _ports(spec, key):
    ps = spec.get(key) or []
    out = []
    for p in ps:
        if isinstance(p, str):
            p = {"name": p, "width": 1}
        out.append({"name": p["name"], "width": int(p.get("width", 1))})
    return out


def _decl(direction, p):
    w = p["width"]
    rng = f" [{w-1}:0]" if w > 1 else ""
    return f"  {direction}{rng} {p['name']}"


def _slice(name, hi, lo):
    return f"{name}[{hi}:{lo}]" if hi != lo else f"{name}[{lo}]"


def generate(spec: dict) -> str:
    if "module" not in spec or "op" not in spec:
        raise ValueError("spec needs 'module' and 'op'")
    op = spec["op"].lower()
    ins = _ports(spec, "inputs")
    outs = _ports(spec, "outputs")
    if not ins or not outs:
        raise ValueError("spec needs inputs and outputs")

    body: str
    if op == "reverse":
        if len(ins) != 1 or len(outs) != 1:
            raise ValueError("reverse needs exactly one input and one output")
        w = ins[0]["width"]
        if outs[0]["width"] != w:
            raise ValueError("reverse in/out widths must match")
        chunk = int(spec.get("chunk", 1))
        if w % chunk != 0:
            raise ValueError(f"width {w} not divisible by chunk {chunk}")
        n = w // chunk
        parts = [_slice(ins[0]["name"], j * chunk + chunk - 1, j * chunk) for j in range(n)]
        body = f"  assign {outs[0]['name']} = {{{', '.join(parts)}}};"

    elif op == "split":
        if len(ins) != 1:
            raise ValueError("split needs exactly one input")
        w = ins[0]["width"]
        if sum(o["width"] for o in outs) != w:
            raise ValueError("split: sum of output widths must equal input width")
        lines = []
        hi = w
        for o in outs:
            lo = hi - o["width"]
            lines.append(f"  assign {o['name']} = {_slice(ins[0]['name'], hi-1, lo)};")
            hi = lo
        body = "\n".join(lines)

    elif op == "concat":
        if len(outs) != 1:
            raise ValueError("concat needs exactly one output")
        parts = spec.get("parts")
        if not parts:
            raise ValueError("concat needs 'parts' (ordered MSB-first RTL expressions)")
        body = f"  assign {outs[0]['name']} = {{{', '.join(parts)}}};"

    elif op in ("sign_extend", "zero_extend"):
        if len(ins) != 1 or len(outs) != 1:
            raise ValueError(f"{op} needs one input and one output")
        w, W = ins[0]["width"], outs[0]["width"]
        if W <= w:
            raise ValueError(f"{op}: output width {W} must exceed input width {w}")
        fill = f"{ins[0]['name']}[{w-1}]" if op == "sign_extend" else "1'b0"
        body = f"  assign {outs[0]['name']} = {{{{{W-w}{{{fill}}}}}, {ins[0]['name']}}};"

    else:
        raise ValueError(f"unknown op: {op}")

    lines = [f"module {spec['module']} ("]
    lines.append(",\n".join([_decl("input", p) for p in ins] +
                            [_decl("output", p) for p in outs]))
    lines.append(");")
    lines.append(body)
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
        print(f"vector_op_rtl_gen: spec not found: {p}", file=sys.stderr)
        return 2
    try:
        text = p.read_text()
        spec = (__import__("yaml").safe_load(text) if p.suffix.lower() in (".yaml", ".yml")
                else json.loads(text))
        rtl = generate(spec)
    except (ValueError, KeyError) as e:
        print(f"vector_op_rtl_gen: invalid spec: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"vector_op_rtl_gen: {e}", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
        print(f"vector_op_rtl_gen: wrote {a.out} ({rtl.count(chr(10))} lines)")
    else:
        sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
