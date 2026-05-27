#!/usr/bin/env python3
"""truth_table_rtl_gen.py — deterministic truth-table → combinational RTL generator.

since v0.1.7.

Phase-2 "program writes the RTL" generator, companion to fsm_table_rtl_gen.py.
Driven by the VerilogEval-v2 run: many problems hand the design a FULLY-SPECIFIED
truth table (e.g. Prob069 truthtable1) or K-map for which the combinational logic
is mechanically derivable — yet Phase 2 had no deterministic generator and fell
back to a blind LLM shot. Given a structured truth-table contract it emits a
correct, synthesizable `case`-based combinational module DETERMINISTICALLY — no
LLM. For a fully-specified table the result is exactly correct (no don't-care
ambiguity); for a partial table, unlisted input combinations take an explicit
`default` (canonical don't-care assignment), which is deterministic and valid.

Input spec (JSON or YAML), e.g. (Prob069):
    {
      "module": "TopModule",
      "inputs":  [{"name": "x3"}, {"name": "x2"}, {"name": "x1"}],
      "outputs": [{"name": "f"}],
      "rows": [ {"in": "000", "out": "0"}, {"in": "001", "out": "0"},
                {"in": "010", "out": "1"}, {"in": "011", "out": "1"},
                {"in": "100", "out": "0"}, {"in": "101", "out": "1"},
                {"in": "110", "out": "0"}, {"in": "111", "out": "1"} ],
      "default": "0"
    }
  - `in`  : binary string, MSB = FIRST declared input (widths summed, MSB-first).
  - `out` : binary string, MSB = FIRST declared output.
  - widths default to 1; multi-bit ports supported via {"name":..,"width":N}.
  - `default` (optional) : output bit-string for input combos not listed
    (default = all zeros). Use it for don't-care / partial tables.

chip-AGNOSTIC. Deterministic: same spec → byte-identical RTL.

CLI:
    python3 truth_table_rtl_gen.py <spec.json|spec.yaml> [-o out.sv]

Exit codes: 0 = wrote RTL   1 = invalid spec   2 = file/parse error
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List


def _load(path: Path) -> dict:
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def _ports(spec: dict, key: str) -> List[dict]:
    ports = spec.get(key) or []
    if not ports:
        raise ValueError(f"spec needs at least one {key[:-1]}")
    norm = []
    for p in ports:
        if isinstance(p, str):
            p = {"name": p, "width": 1}
        norm.append({"name": p["name"], "width": int(p.get("width", 1))})
    return norm


def _decl(direction: str, p: dict, reg: bool = False) -> str:
    w = p["width"]
    kw = f"{direction} reg" if reg else direction
    rng = f" [{w-1}:0]" if w > 1 else ""
    pad = "" if w > 1 else " " * 0
    return f"  {kw}{rng} {p['name']}"


def generate(spec: dict) -> str:
    if "module" not in spec or "rows" not in spec:
        raise ValueError("spec needs 'module' and 'rows'")
    ins = _ports(spec, "inputs")
    outs = _ports(spec, "outputs")
    in_w = sum(p["width"] for p in ins)
    out_w = sum(p["width"] for p in outs)
    rows = spec["rows"]
    default = spec.get("default", "0" * out_w)
    if len(default) != out_w:
        raise ValueError(f"default '{default}' width != total output width {out_w}")

    # validate rows
    seen = set()
    for r in rows:
        bi, bo = str(r["in"]), str(r["out"])
        if len(bi) != in_w:
            raise ValueError(f"row in '{bi}' width != total input width {in_w}")
        if len(bo) != out_w:
            raise ValueError(f"row out '{bo}' width != total output width {out_w}")
        if set(bi) - set("01"):
            raise ValueError(f"row in '{bi}' must be binary (0/1)")
        if bi in seen:
            raise ValueError(f"duplicate input row '{bi}'")
        seen.add(bi)

    in_concat = "{" + ", ".join(p["name"] for p in ins) + "}" if len(ins) > 1 else ins[0]["name"]
    single_out = len(outs) == 1
    out_reg = outs[0]["name"] if single_out else "_tt_o"

    lines = [f"module {spec['module']} ("]
    decls = [_decl("input", p) for p in ins]
    if single_out:
        decls.append(_decl("output", outs[0], reg=True))
    else:
        decls += [_decl("output", p) for p in outs]
    lines.append(",\n".join(decls))
    lines.append(");")
    if not single_out:
        lines.append(f"  reg [{out_w-1}:0] {out_reg};")
    lines.append(f"  always @(*) begin")
    lines.append(f"    case ({in_concat})")
    for r in rows:
        lines.append(f"      {in_w}'b{r['in']}: {out_reg} = {out_w}'b{r['out']};")
    lines.append(f"      default: {out_reg} = {out_w}'b{default};")
    lines.append(f"    endcase")
    lines.append(f"  end")
    if not single_out:
        # split the concatenated reg back onto the declared output ports (MSB-first)
        hi = out_w
        for p in outs:
            lo = hi - p["width"]
            sl = f"[{hi-1}:{lo}]" if p["width"] > 1 else f"[{lo}]"
            lines.append(f"  assign {p['name']} = {out_reg}{sl};")
            hi = lo
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="truth-table spec JSON or YAML")
    ap.add_argument("-o", "--out", help="output .sv path (default: stdout)")
    a = ap.parse_args()
    p = Path(a.spec)
    if not p.is_file():
        print(f"truth_table_rtl_gen: spec not found: {p}", file=sys.stderr)
        return 2
    try:
        rtl = generate(_load(p))
    except (ValueError, KeyError) as e:
        print(f"truth_table_rtl_gen: invalid spec: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"truth_table_rtl_gen: {e}", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
        print(f"truth_table_rtl_gen: wrote {a.out} ({rtl.count(chr(10))} lines)")
    else:
        sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
