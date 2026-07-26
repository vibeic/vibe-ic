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
  * the parallel operand's WIDTH is resolvable from the spec (see
    ``resolve_parallel_width``) and the spec's own fields agree on it.
On ANY ambiguity (operator not multiply, >1 wide operand, missing serial
in/out, missing clk/rst, unresolvable or self-contradictory width) it returns
(None, reason) — a FAIL-CLOSED SKIP. A wrong multiplier is far worse than an
honest skip; the spec-to-rtl fallback still stands for the shapes this solver
declines.

WIDTH IS NEVER DEFAULTED. An earlier revision resolved the width from the FIRST
L9 field that carried the parameter NAME and therefore never read the declared
default in the sibling field — every emission was 32 bits regardless of what the
spec said, and nothing downstream notices (``l9_rtl_pin_consistency_check``
compares pin names + directions and DISCARDS widths). The resolver now reads
every field and DEFERs rather than invent a width.

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


_PARAM_NAME_RE = re.compile(r"([A-Za-z_]\w*)\s*-\s*1")
# A declared default, written the way real L9 docs write it. The BARE ``= N``
# form is deliberately NOT accepted on its own: prose like "x = 0 at reset"
# would silently become a width. It is accepted only ANCHORED to the parameter
# name (``parameter `size` = 32``).
_DEFAULT_GENERIC_RE = re.compile(
    r"預設\s*(\d+)|\bdefaults?\s*(?:to\s*)?[:=]?\s*(\d+)", re.I)


def _width_sources(port: Dict[str, Any]) -> List[str]:
    """Every L9 field the parallel operand's width may be declared in.

    ALL of them are scanned. The pre-repair code returned on the FIRST field
    that merely carried the parameter NAME (``width_symbolic``), so the declared
    default living in the SIBLING ``width`` field was never read and every
    emission silently used a hardcoded 32.
    """
    return [str(port.get(k) or "") for k in
            ("width_symbolic", "width", "msb", "description")]


def _declared_defaults(port: Dict[str, Any], param: Optional[str]) -> List[int]:
    """Every width VALUE this port declares, from every field, de-duplicated in
    first-seen order. More than one distinct value = the spec contradicts
    itself and the caller must FAIL-CLOSED rather than pick one."""
    vals: List[int] = []

    def _add(v: int) -> None:
        if v > 0 and v not in vals:
            vals.append(v)

    srcs = _width_sources(port)
    if param:
        anchored = re.compile(
            re.escape(param) + r"\W{0,12}?(?:預設|default(?:s\s+to)?|[:=])\s*(\d+)",
            re.I)
        for s in srcs:
            for m in anchored.finditer(s):
                _add(int(m.group(1)))
    for s in srcs:
        for m in _DEFAULT_GENERIC_RE.finditer(s):
            _add(int(next(g for g in m.groups() if g)))
    # Literal bit ranges and integer fields are declarations too.
    for s in srcs:
        for m in re.finditer(r"\[\s*(\d+)\s*:\s*0\s*\]", s):
            _add(int(m.group(1)) + 1)
    w = port.get("width")
    if isinstance(w, int) and not isinstance(w, bool):
        _add(w)
    msb = port.get("msb")
    if isinstance(msb, int) and not isinstance(msb, bool):
        _add(msb + 1)
    return vals


def resolve_parallel_width(
        port: Dict[str, Any]) -> Tuple[Optional[str], Optional[int], str]:
    """Resolve the parallel operand's ``(param_name, width, reason)``.

    FAIL-CLOSED. Returns ``(None, None, reason)`` — which the caller turns into
    a DEFER — whenever the declared width cannot be resolved or the spec's own
    fields disagree. This function NEVER invents a width: emitting a 32-bit
    datapath for a spec that declared 16 (or 64) is a silently wrong chip, and
    no downstream gate catches it (``l9_rtl_pin_consistency_check`` compares pin
    NAMES and DIRECTIONS only — it discards widths).

    ``param_name`` is None when the spec declares a plain integer width; the
    emitter then writes a fixed-width port instead of inventing a parameter.
    """
    param: Optional[str] = None
    for src in _width_sources(port)[:3]:   # name comes from a width field
        m = _PARAM_NAME_RE.search(src)
        if m:
            param = m.group(1)
            break
    vals = _declared_defaults(port, param)
    if len(vals) > 1:
        return None, None, (
            f"parallel operand declares CONFLICTING widths {vals} across "
            f"width/width_symbolic/msb/description — refusing to guess")
    if not vals:
        if param:
            return None, None, (
                f"parallel operand width is parametric (`{param}`) but the "
                f"spec declares no default for it in width/width_symbolic/"
                f"msb/description — refusing to invent one")
        return None, None, (
            "parallel operand declares no resolvable width")
    if vals[0] < 2:
        return None, None, (
            f"parallel operand resolves to width {vals[0]} — not a multi-bit "
            f"operand")
    if param:
        return param, vals[0], f"parametric width `{param}` default {vals[0]}"
    return None, vals[0], f"fixed width {vals[0]}"


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
        # ``inout`` starts with "in" — classifying it as an input would emit a
        # module whose port list silently disagrees with L9.
        if d.startswith("inout") or d in ("bidir", "bidirectional") or \
                str(p.get("io") or "").lower().startswith("inout"):
            return None, (f"port {name!r} is bidirectional — a serial-parallel "
                          f"multiplier has no inout port")
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
            extra.append(f"{name}({d or 'no direction'})")

    if extra:
        # An unclassifiable port used to be collected and IGNORED, so the
        # emitted module would simply not declare it. Silently dropping a
        # declared top port is the same class of fabrication as inventing a
        # width: FAIL-CLOSED instead.
        return None, (f"top port(s) with an unrecognised direction: {extra} — "
                      f"refusing to emit a module that omits a declared port")

    miss = [n for n, v in (("clk", clk), ("rst", rst), ("parallel_operand", par),
                           ("serial_in", ser_in), ("serial_out", ser_out)) if not v]
    if miss:
        return None, f"missing required port role(s): {miss}"

    size_name, size_def, width_why = resolve_parallel_width(par[1])
    if size_def is None:
        # FAIL-CLOSED on the width exactly as on the shape. A multiplier of the
        # wrong width is a wrong chip, and it is invisible downstream.
        return None, f"width unresolved on `{par[0]}`: {width_why}"
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
        "width_resolution": width_why,
    }
    return spec, f"serial-parallel multiplier shape matched ({width_why})"


def emit_rtl(spec: Dict[str, Any]) -> str:
    top = spec["top"]
    sz = spec["size_param"]          # None when the spec declares a fixed width
    szd = spec["size_default"]       # ALWAYS the spec's declared width
    clk, rst = spec["clk"], spec["rst"]
    x, y, p = spec["parallel"], spec["serial_in"], spec["serial_out"]
    rst_expr = f"!{rst}" if spec["rst_active_low"] else rst
    rst_word = "active-low" if spec["rst_active_low"] else "active-high"
    # A parameter is emitted ONLY when the spec declares one. A spec that states
    # a plain integer width gets that integer — inventing a parameter name would
    # put a symbol in the RTL that the spec never declared.
    if sz:
        param_block = f" #(\n    parameter {sz} = {szd}\n)"
        w = sz               # width expression used inside the body
        wname = sz
    else:
        param_block = ""
        w = str(szd)
        wname = str(szd)
    return f"""`default_nettype none
//============================================================================
// {top} — serial-parallel (carry-save) integer multiplier
//   AUTO-GENERATED by serial_parallel_mul_synth.py (deterministic, Bucket A).
//----------------------------------------------------------------------------
// Function : {p} = ({x} * {y}) mod 2^{wname}
//   {x} : parallel {wname}-bit multiplicand, held stable during a computation
//   {y} : serial multiplier, one bit per clock, LSB-first
//   {p} : serial product,   one bit per clock, LSB-first
// Width    : {spec["width_resolution"]} — READ FROM THE SPEC, never defaulted.
// Reset    : synchronous, {rst_word}
// Algorithm: textbook carry-save shift-add serial-parallel multiplier. Latency
//   and bit-order are Plugin-chosen (spec R3 freedom); the flow's serial-
//   parallel oracle self-calibrates them, so any functionally-correct variant
//   verifies. Provenance: public/textbook algorithm, not any reference RTL.
//============================================================================
module {top}{param_block} (
    input  wire            {clk},
    input  wire            {rst},
    input  wire [{w}-1:0] {x},
    input  wire            {y},
    output wire            {p}
);
    reg  [{w}-1:0] s;    // carry-save sum column
    reg  [{w}-1:0] c;    // carry-save carry column
    reg             yr;   // registered serial multiplier bit
    reg             pr;   // registered serial product bit

    wire [{w}-1:0] m  = {x} & {{{w}{{yr}}}};               // gated partial product
    wire [{w}-1:0] so = m ^ s ^ c;                    // carry-save sum
    wire [{w}-1:0] co = (m & s) | (m & c) | (s & c);  // carry-save carry

    always @(posedge {clk}) begin
        if ({rst_expr}) begin
            s  <= {{{w}{{1'b0}}}};
            c  <= {{{w}{{1'b0}}}};
            yr <= 1'b0;
            pr <= 1'b0;
        end else begin
            yr <= {y};
            s  <= {{1'b0, so[{w}-1:1]}};  // shift sum toward next (higher) weight
            c  <= co;                    // carry re-added at same column next cycle
            pr <= so[0];                 // stream settled LSB of this column
        end
    end

    assign {p} = pr;
endmodule
`default_nettype wire
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--ic-class", default="digital_arithmetic_primitive")
    ap.add_argument("--emit", action="store_true",
                    help="write phase2/stage1/rtl/<top>.v when the shape matches")
    a = ap.parse_args()
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
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
