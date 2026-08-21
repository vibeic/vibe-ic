#!/usr/bin/env python3
"""serial_parallel_mul_synth.py — deterministic SOLVER for the SERIAL-PARALLEL
integer-multiplier subset of ``digital_arithmetic_primitive`` (spec -> RTL).

THE AUDITED GAP (capture, IC-expert recovery on the spm x sky130A cell):
``digital_arithmetic_primitive`` ships ``rtl_gen=null`` in ic_class_registry.json
and defers the ENTIRE family to ``fallback_skill=spec-to-rtl`` — i.e. a human/AI
hand-authors the RTL every blind run. But the SERIAL-PARALLEL MULTIPLIER shape
(one PARALLEL N-bit operand ``x`` + one 1-bit SERIAL operand ``y`` + one 1-bit
SERIAL result ``p`` + clk + rst, computing ``p = (x * y) mod 2^N``) is
CLOSED-FORM and its functional golden is ALREADY self-calibrated by
``arith_oracle_tb_gen`` (the serial-parallel declared-function oracle). A closed
function whose oracle the plugin can already CHECK is Bucket A: it can also be
GENERATED. This solver fills exactly that hole so the next blind run recovers the
RTL with NO agent.

FIRES only on the unambiguous serial-parallel MULTIPLIER shape:
  * L2/FRS states a MULTIPLY (``*`` / "multiplier" / "product" / "x × y").
  * top_ports resolve to EXACTLY: one clk, one rst, one input of width>1
    (the parallel multiplicand), one 1-bit input (the serial multiplier),
    one 1-bit output (the serial product).
On ANY ambiguity (operator not multiply, >1 wide operand, missing serial
in/out, missing clk/rst) it returns (None, reason) — a FAIL-CLOSED SKIP. A wrong
multiplier is far worse than an honest skip; the spec-to-rtl fallback still
stands for the shapes this solver declines.

Latency + bit-order are Plugin-chosen (the spec grants R3 freedom) and the
oracle self-calibrates them, so the emitted core uses a clean textbook
carry-save shift-add datapath (LSB-first y / LSB-first p, latency 1). Provenance:
authored from the public/textbook carry-save serial-parallel multiplier
algorithm — NOT copied from any benchmark reference RTL.

CLI:
    python3 serial_parallel_mul_synth.py <project_dir> [--emit]
      (default) prints a JSON verdict {emitted|deferred, reason, ...}
      --emit     writes phase2/stage1/rtl/<top>.v when the shape matches

Exit codes: 0 = emitted (or would emit); 2 = deferred (shape not matched);
            1 = error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CLK_NAMES = {"clk", "clock", "clk_i", "i_clk", "sysclk", "clk_in"}
_RST_NAMES = {"rst", "reset", "rst_n", "reset_n", "rstn", "i_rst",
              "rst_ni", "arst_n", "rst_in", "resetn"}
_MUL_TOKENS = ("multiplier", "multiply", "multiplic", "product", "* y",
               "x*y", "x * y", "x×y", "x × y", "乘法", "乘積", "乘積器",
               "序列乘", "mod 2^")


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_doc(gd: Path, *stems: str) -> Dict[str, Any]:
    for stem in stems:
        f = gd / stem
        if f.exists():
            return _load_json(f)
    return {}


def _is_active_low(rst_name: str, ports_blob: str) -> bool:
    if rst_name.lower().endswith("_n") or rst_name.lower().endswith("n") and \
       rst_name.lower() in {"rstn", "resetn"}:
        return True
    return bool(re.search(r"active[\s_-]*low", ports_blob, re.I))


def _port_width_is_wide(port: Dict[str, Any]) -> bool:
    """True when a port is a multi-bit bus (the parallel operand)."""
    w = port.get("width")
    if isinstance(w, int):
        return w > 1
    # symbolic widths like 'size-1:0', 'N-bit(...)', or an explicit msb symbol
    sym = str(port.get("width_symbolic") or "") + " " + str(w or "")
    if re.search(r"-\s*1\s*:\s*0", sym):
        return True
    msb = str(port.get("msb") or "")
    return bool(re.search(r"[A-Za-z]", msb))  # msb is a symbol (e.g. 'size-1')


def _size_param_from(port: Dict[str, Any], default_name: str = "size",
                     default_val: int = 32) -> Tuple[str, int]:
    """Resolve the parametric width name + default for the parallel operand."""
    for src in (port.get("width_symbolic"), port.get("width"), port.get("msb")):
        m = re.search(r"([A-Za-z_]\w*)\s*-\s*1", str(src or ""))
        if m:
            name = m.group(1)
            dv = default_val
            dm = re.search(r"預設\s*(\d+)|default\s*(\d+)|=\s*(\d+)",
                           str(src or ""))
            if dm:
                dv = int(next(g for g in dm.groups() if g))
            return name, dv
    return default_name, default_val


def extract_serial_parallel_mul_spec(
        project_dir: Path, ic_class: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (spec, reason). spec is None (FAIL-CLOSED) unless the design is an
    unambiguous serial-parallel multiplier."""
    gd = project_dir / "phase1" / "generated_docs"
    if not gd.exists():
        return None, f"no generated_docs at {gd}"

    l9 = _find_doc(gd, "L9_INTEGRATION_SPEC.json")
    ports: List[Dict[str, Any]] = l9.get("top_ports") or []
    top = l9.get("top_module") or l9.get("ic_name") or project_dir.name
    if not ports:
        return None, "L9 has no top_ports"

    # operator must be MULTIPLY, read from L2/FRS prose (token, never a SKU)
    blob = ""
    for stem in ("L2_FRS.json", "L2_ARCHITECTURE.json", "L1_DATASHEET.json"):
        blob += json.dumps(_find_doc(gd, stem), ensure_ascii=False)
    ports_blob = json.dumps(ports, ensure_ascii=False)
    hay = (blob + ports_blob).lower()
    if not any(tok.lower() in hay for tok in _MUL_TOKENS):
        return None, "no MULTIPLY operator token found in L2/FRS/ports"
    # a stated ADD/SUB/bitwise-only core is NOT this solver's shape
    if re.search(r"\b(adder|subtract|加法器|減法器)\b", hay) and \
       "multipl" not in hay and "乘" not in hay:
        return None, "operator resolves to add/sub, not multiply"

    clk = rst = par = ser_in = ser_out = None
    extra = []
    for p in ports:
        name = str(p.get("name", "")).strip()
        d = str(p.get("direction") or p.get("mode") or "").lower()
        lname = name.lower()
        if lname in _CLK_NAMES:
            clk = name
            continue
        if lname in _RST_NAMES:
            rst = name
            continue
        if d.startswith("in"):
            if _port_width_is_wide(p):
                if par is not None:
                    return None, f"more than one wide input operand ({par},{name})"
                par = (name, p)
            else:
                if ser_in is not None:
                    return None, f"more than one 1-bit serial input ({ser_in},{name})"
                ser_in = name
        elif d.startswith("out"):
            if _port_width_is_wide(p):
                return None, f"result port {name} is a bus; serial-parallel needs a 1-bit serial result"
            if ser_out is not None:
                return None, f"more than one 1-bit serial output ({ser_out},{name})"
            ser_out = name
        else:
            extra.append(name)

    miss = [n for n, v in (("clk", clk), ("rst", rst), ("parallel_operand", par),
                           ("serial_in", ser_in), ("serial_out", ser_out)) if not v]
    if miss:
        return None, f"missing required port role(s): {miss}"

    size_name, size_def = _size_param_from(par[1])
    active_low = _is_active_low(rst, ports_blob)
    spec = {
        "topology": "serial_parallel",
        "operator": "*",
        "top": top,
        "clk": clk,
        "rst": rst,
        "rst_active_low": active_low,
        "parallel": par[0],
        "serial_in": ser_in,
        "serial_out": ser_out,
        "size_param": size_name,
        "size_default": size_def,
    }
    return spec, "serial-parallel multiplier shape matched"


def emit_rtl(spec: Dict[str, Any]) -> str:
    top = spec["top"]
    sz = spec["size_param"]
    szd = spec["size_default"]
    clk, rst = spec["clk"], spec["rst"]
    x, y, p = spec["parallel"], spec["serial_in"], spec["serial_out"]
    rst_expr = f"!{rst}" if spec["rst_active_low"] else rst
    rst_word = "active-low" if spec["rst_active_low"] else "active-high"
    return f"""`default_nettype none
//============================================================================
// {top} — serial-parallel (carry-save) integer multiplier
//   AUTO-GENERATED by serial_parallel_mul_synth.py (deterministic, Bucket A).
//----------------------------------------------------------------------------
// Function : {p} = ({x} * {y}) mod 2^{sz}
//   {x} : parallel {sz}-bit multiplicand, held stable during a computation
//   {y} : serial multiplier, one bit per clock, LSB-first
//   {p} : serial product,   one bit per clock, LSB-first
// Reset    : synchronous, {rst_word}
// Algorithm: textbook carry-save shift-add serial-parallel multiplier. Latency
//   and bit-order are Plugin-chosen (spec R3 freedom); the flow's serial-
//   parallel oracle self-calibrates them, so any functionally-correct variant
//   verifies. Provenance: public/textbook algorithm, not any reference RTL.
//============================================================================
module {top} #(
    parameter {sz} = {szd}
) (
    input  wire            {clk},
    input  wire            {rst},
    input  wire [{sz}-1:0] {x},
    input  wire            {y},
    output wire            {p}
);
    reg  [{sz}-1:0] s;    // carry-save sum column
    reg  [{sz}-1:0] c;    // carry-save carry column
    reg             yr;   // registered serial multiplier bit
    reg             pr;   // registered serial product bit

    wire [{sz}-1:0] m  = {x} & {{{sz}{{yr}}}};               // gated partial product
    wire [{sz}-1:0] so = m ^ s ^ c;                    // carry-save sum
    wire [{sz}-1:0] co = (m & s) | (m & c) | (s & c);  // carry-save carry

    always @(posedge {clk}) begin
        if ({rst_expr}) begin
            s  <= {{{sz}{{1'b0}}}};
            c  <= {{{sz}{{1'b0}}}};
            yr <= 1'b0;
            pr <= 1'b0;
        end else begin
            yr <= {y};
            s  <= {{1'b0, so[{sz}-1:1]}};  // shift sum toward next (higher) weight
            c  <= co;                    // carry re-added at same column next cycle
            pr <= so[0];                 // stream settled LSB of this column
        end
    end

    assign {p} = pr;
endmodule
`default_nettype wire
"""


def plugin_declaration(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The L7-required ``plugin_output/declaration.json`` payload for *spec*.

    L7_verification_plan's own ``## 7.0 Plugin Declaration Requirements`` table
    states: "Plugin, before starting RTL design, MUST declare {bit_order,
    reset_polarity, latency_cycles, integer_encoding} in
    ``plugin_output/declaration.json``; the L7 comparison procedure reads this
    file to correctly pair reference outputs." This solver's own choices for
    all four are already FIXED and stated in its module docstring and in
    ``emit_rtl``'s comment block ("LSB-first y / LSB-first p, latency 1") — the
    values here are not derived or guessed, only restated in the schema the
    spec's own comparison procedure reads.

    ``bit_order``   : LSB_first — both the serial multiplier input and the
                     serial product output shift LSB-first (see ``emit_rtl``'s
                     header comment; not chosen here).
    ``reset_polarity``: read from ``spec["rst_active_low"]``, which
                     ``extract_serial_parallel_mul_spec`` already derived from
                     the design's own reset port name — never re-derived here.
    ``latency_cycles``: 1 — one register stage (``yr``) between a serial input
                     bit and the product bit it contributes to; stated, not
                     computed, because the datapath topology is fixed by
                     ``emit_rtl`` and this solver is the only writer of it.
    ``integer_encoding``: unsigned — the algorithm computes
                     ``p = (x * y) mod 2^N``; ``emit_rtl`` declares no signed
                     port and applies no two's-complement handling anywhere.
    """
    return {
        "bit_order": "LSB_first",
        "reset_polarity": "active_low" if spec["rst_active_low"] else "active_high",
        "latency_cycles": 1,
        "integer_encoding": "unsigned",
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--ic-class", default="digital_arithmetic_primitive")
    ap.add_argument("--emit", action="store_true",
                    help="write phase2/stage1/rtl/<top>.v when the shape matches")
    a = ap.parse_args(argv)
    proj = Path(a.project).resolve()
    spec, reason = extract_serial_parallel_mul_spec(proj, a.ic_class)
    if spec is None:
        print(json.dumps({"verdict": "DEFER", "reason": reason}))
        return 2
    rtl = emit_rtl(spec)
    out = {"verdict": "EMIT", "reason": reason, "top": spec["top"],
           "spec": spec}
    if a.emit:
        rtl_dir = proj / "phase2" / "stage1" / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        rtl_path = rtl_dir / f"{spec['top']}.v"
        rtl_path.write_text(rtl)
        out["written"] = str(rtl_path)
        # L7 ## 7.0 requires this declaration BEFORE RTL design starts; written
        # alongside the RTL here because this solver is a single atomic step,
        # not two — a run that crashed between them would leave the design in
        # a state the spec never describes (RTL present, declaration absent).
        decl_dir = proj / "plugin_output"
        decl_dir.mkdir(parents=True, exist_ok=True)
        decl_path = decl_dir / "declaration.json"
        decl_path.write_text(
            json.dumps(plugin_declaration(spec), indent=2, sort_keys=True) + "\n")
        out["declaration_written"] = str(decl_path)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
