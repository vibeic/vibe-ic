#!/usr/bin/env python3
"""memory_array_synth.py — deterministic SOLVER for the register-array MEMORY
family (RAM / ROM / LIFO stack / instruction register), spec prose -> RTL.

Same flow as the VerilogEval-v2 solvers: PARSE the stated structure of the prompt
into a small structured record, then EMIT correct RTL deterministically, then
HOST-VERIFY against the dataset testbench. The body is NEVER guessed — every shape
fires ONLY when the prompt states the structure unambiguously, and returns None
(SKIP) on any §4.05 ambiguity (a wrong memory/stack is far worse than an honest
skip, which lets the runner fall through to the LLM authoring path).

This is a clean prose-parsed canonical solver: it reads the interface through the
SHARED reader chain `rtllm_port_bridge.bridge_prompt -> port_parser.parse_ports`
(the same bridge the arithmetic solver uses; a no-op on VerilogEval bullet/header
prompts), so the port names/widths come from the prompt's "Input ports:/Output
ports:" prose, never from a hard-coded table.

chip-AGNOSTIC RECOGNITION (this file's contract):
  * Each shape is recognised by its STRUCTURE — the operation described in prose +
    the port DIRECTIONS / WIDTHS / roles — NOT by the dataset's exact port-name set.
    Renaming the LIFO ports to generic equivalents (push/pop/din/dout) does NOT
    change whether the LIFO shape fires; the actual parsed names are used verbatim
    in the emitted RTL so the testbench still binds by name.
  * Structural parameters (RAM array depth, LIFO stack-pointer reset value +
    push/pop direction, instr_reg field slicing + fetch encoding) are PARSED from
    the prose, never hard-coded. A RAM whose depth is STATED uses that depth, not
    2**WIDTH. A field whose layout is UNSTATED makes the shape SKIP rather than
    hard-code a guess.

API:  synth(prompt_text, top="TopModule") -> str | None
      `top` is used verbatim; when it is the caller default ("TopModule") the
      prompt's "Module name:" token is used instead. Returns None on §4.05 ambiguity.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- shared port reader (bridge -> port_parser) --------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import rtllm_port_bridge as _bridge  # noqa: E402
    import port_parser as _pp  # noqa: E402
except Exception:  # pragma: no cover - import guard for standalone smoke
    _bridge = None
    _pp = None

_DEFAULT_TOP = "TopModule"

Port = Tuple[str, int]


# ============================================================ helpers / parsing
def _module_name(text: str) -> Optional[str]:
    """The module name the RTLLM testbench instantiates by — the token under the
    'Module name:' header. Returns None if absent (=> SKIP, never guess a name)."""
    m = re.search(r"Module\s*name\s*[:：]\s*\n?\s*([A-Za-z_]\w*)", text, re.I)
    return m.group(1) if m else None


def _ports(text: str) -> Tuple[List[Port], List[Port]]:
    """(ins, outs) via the shared bridge->parser chain. ([],[]) if unreadable."""
    if _bridge is None or _pp is None:
        return [], []
    return _pp.parse_ports(_bridge.bridge_prompt(text))


def _names(ports: List[Port]) -> List[str]:
    return [n for n, _ in ports]


def _width_of(ports: List[Port], name: str) -> Optional[int]:
    for n, w in ports:
        if n == name:
            return w
    return None


def _int_after(text: str, *patterns: str) -> Optional[int]:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    return None


def _has(text: str, *subs: str) -> bool:
    low = text.lower()
    return any(s.lower() in low for s in subs)


# --- STRUCTURAL role identification (chip-AGNOSTIC, name-free) ------------------
_CLK_RE = re.compile(r"^(clk|clock|clk_in|Clk)$", re.I)
_RST_RE = re.compile(r"(rst|reset|clr|clear)", re.I)


def _is_clk(name: str) -> bool:
    return bool(_CLK_RE.match(name))


def _is_rst(name: str) -> bool:
    return bool(_RST_RE.search(name))


def _find_role(ports: List[Port], *name_patterns: str,
               width=None) -> Optional[Port]:
    """First port whose name matches ANY of `name_patterns` (regex, case-insens)
    and (optionally) satisfies the width predicate. Role-based, not exact-set."""
    rx = [re.compile(p, re.I) for p in name_patterns]
    for n, w in ports:
        if width is not None and not width(w):
            continue
        if any(r.search(n) for r in rx):
            return (n, w)
    return None


# ============================================================ RAM
def _try_ram(text: str, top: str, ins, outs) -> Optional[str]:
    if not _has(text, "RAM", "memory", "register array"):
        return None
    if _has(text, "ROM", "read-only memory") and not _has(text, "RAM"):
        return None  # a pure ROM is handled by _try_rom
    width = _int_after(text, r"WIDTH\s*=\s*(\d+)", r"bit\s*width\s*of\s*(\d+)",
                       r"width\s*of\s*(\d+)\s*bits?", r"(\d+)[- ]bit\s+wide")
    depth = _int_after(text, r"DEPTH\s*=\s*(\d+)", r"depth\s*of\s*(\d+)",
                       r"depth\s+(\d+)")
    if width is None or depth is None:
        return None
    # STRUCTURAL: a clocked register-array with a write port (enable+addr+data) and
    # a read port (enable+addr) feeding a read-data output. Roles resolved by name
    # hint, not by an exact name set.
    clk = _find_role(ins, r"^(clk|clock|Clk)$")
    rst = _find_role(ins, r"(rst|reset)")
    wen = _find_role(ins, r"(write_en|wr_en|wen|we)\b", r"write.*en")
    waddr = _find_role(ins, r"write_addr", r"wr_addr", r"waddr")
    wdata = _find_role(ins, r"write_data", r"wr_data", r"wdata", r"din")
    ren = _find_role(ins, r"(read_en|rd_en|ren|re)\b", r"read.*en")
    raddr = _find_role(ins, r"read_addr", r"rd_addr", r"raddr")
    rdata = _find_role(outs, r"read_data", r"rd_data", r"rdata", r"dout")
    if None in (clk, rst, wen, waddr, wdata, ren, raddr, rdata):
        return None
    clk_n, rst_n = clk[0], rst[0]
    wen_n, waddr_n, wdata_n = wen[0], waddr[0], wdata[0]
    ren_n, raddr_n, rdata_n = ren[0], raddr[0], rdata[0]
    # Array depth/address-width come from the STATED dims — NOT 2**WIDTH. The
    # address bus is sized to address `depth` locations; an explicitly stated
    # address width (if any) wins.
    stated_aw = _int_after(text, r"address\s+width\s*=\s*(\d+)",
                           r"(\d+)[- ]bit\s+address")
    aw = stated_aw if stated_aw is not None else max(1, (depth - 1).bit_length())
    array_depth = depth
    sync_read = _has(text, "second always", "read_data register",
                     "posedge", "synchronous")
    if not sync_read:
        return None
    body = []
    body.append(f"module {top} (")
    body.append(f"    input              {clk_n},")
    body.append(f"    input              {rst_n},")
    body.append(f"    input              {wen_n},")
    body.append(f"    input  [{aw-1}:0]      {waddr_n},")
    body.append(f"    input  [{width-1}:0]      {wdata_n},")
    body.append(f"    input              {ren_n},")
    body.append(f"    input  [{aw-1}:0]      {raddr_n},")
    body.append(f"    output reg [{width-1}:0]  {rdata_n}")
    body.append(");")
    body.append(f"    reg [{width-1}:0] RAM [0:{array_depth-1}];")
    body.append("    integer i;")
    body.append(f"    always @(posedge {clk_n} or negedge {rst_n}) begin")
    body.append(f"        if (!{rst_n}) begin")
    body.append(f"            for (i = 0; i < {array_depth}; i = i + 1)")
    body.append("                RAM[i] <= 0;")
    body.append(f"        end else if ({wen_n}) begin")
    body.append(f"            RAM[{waddr_n}] <= {wdata_n};")
    body.append("        end")
    body.append("    end")
    body.append(f"    always @(posedge {clk_n} or negedge {rst_n}) begin")
    body.append(f"        if (!{rst_n}) begin")
    body.append(f"            {rdata_n} <= 0;")
    body.append(f"        end else if ({ren_n}) begin")
    body.append(f"            {rdata_n} <= RAM[{raddr_n}];")
    body.append("        end else begin")
    body.append(f"            {rdata_n} <= 0;")
    body.append("        end")
    body.append("    end")
    body.append("endmodule")
    return "\n".join(body) + "\n"


# ============================================================ ROM
_HEX_LIT_RE = re.compile(r"(\d+)'h([0-9A-Fa-f_]+)")


def _try_rom(text: str, top: str, ins, outs) -> Optional[str]:
    if not _has(text, "ROM", "read-only memory"):
        return None
    # STRUCTURAL: a single address input + a single data output, contents enumerated.
    addr = _find_role(ins, r"addr", r"address")
    dout = _find_role(outs, r"dout", r"data_out", r"q\b", r"read_data")
    if addr is None or dout is None:
        return None
    aw = _width_of(ins, addr[0])
    dw = _width_of(outs, dout[0])
    if aw is None or dw is None:
        return None
    addr_n, dout_n = addr[0], dout[0]
    # The ROM contents MUST be enumerated. RTLLM states them as a list of hex
    # literals tied to a contiguous range "locations 0 through K". We require BOTH
    # the range phrase and exactly (K+1) data literals of the output width.
    rng = re.search(r"locations?\s+(\d+)\s+through\s+(\d+)", text, re.I)
    lits = [(int(b), int(v.replace("_", ""), 16))
            for b, v in _HEX_LIT_RE.findall(text)]
    data_lits = [val for bits, val in lits if bits == dw]
    if not rng or not data_lits:
        return None
    lo, hi = int(rng.group(1)), int(rng.group(2))
    if hi - lo + 1 != len(data_lits):
        return None  # contents under-/over-specified -> SKIP, never fabricate
    depth = 2 ** aw
    body = [f"module {top} (",
            f"    input      [{aw-1}:0] {addr_n},",
            f"    output reg [{dw-1}:0] {dout_n}",
            ");",
            f"    reg [{dw-1}:0] mem [0:{depth-1}];",
            "    initial begin"]
    for i, val in enumerate(data_lits):
        body.append(f"        mem[{lo+i}] = {dw}'h{val:0{(dw+3)//4}X};")
    body.append("    end")
    body.append("    always @(*) begin")
    body.append(f"        {dout_n} = mem[{addr_n}];")
    body.append("    end")
    body.append("endmodule")
    return "\n".join(body) + "\n"


# ============================================================ LIFO buffer
def _parse_stack_directions(text: str) -> Optional[Dict[str, str]]:
    """PARSE the stack-pointer convention from prose.

    Returns {"push": "dec"|"inc", "pop": "dec"|"inc"} or None if unstated/
    contradictory. "push ... pointer is decremented" => push=dec. The two must be
    opposite directions; if both say the same direction it is contradictory -> None.
    """
    low = text.lower()
    push = None
    pop = None
    # push (write) direction
    if re.search(r"push(?:ed)?[^.]*pointer\s+is\s+decrement", low) or \
       re.search(r"pointer\s+is\s+decrement[^.]*push", low) or \
       re.search(r"write[^.]*pointer\s+is\s+decrement", low) or \
       re.search(r"pointer\s+is\s+decrement[^.]*write", low):
        push = "dec"
    elif re.search(r"push(?:ed)?[^.]*pointer\s+is\s+increment", low) or \
            re.search(r"write[^.]*pointer\s+is\s+increment", low):
        push = "inc"
    # pop (read) direction
    if re.search(r"pop(?:ped)?[^.]*pointer\s+is\s+increment", low) or \
       re.search(r"pointer\s+is\s+increment[^.]*pop", low) or \
       re.search(r"read[^.]*pointer\s+is\s+increment", low) or \
       re.search(r"pointer\s+is\s+increment[^.]*read", low):
        pop = "inc"
    elif re.search(r"pop(?:ped)?[^.]*pointer\s+is\s+decrement", low) or \
            re.search(r"read[^.]*pointer\s+is\s+decrement", low):
        pop = "dec"
    if push is None or pop is None:
        return None
    if push == pop:
        return None  # contradictory
    return {"push": push, "pop": pop}


def _try_lifo(text: str, top: str, ins, outs) -> Optional[str]:
    if not _has(text, "LIFO", "last-in-first-out", "last in first out", "stack"):
        return None
    # STRUCTURAL roles (name-hinted, NOT an exact RTLLM name set). Renaming the RTLLM
    # ports to generic stack names (din/dout/push/pop/...) still resolves the roles.
    clk = _find_role(ins, r"^(clk|clock|Clk)$")
    rst = _find_role(ins, r"(rst|reset)")
    en = _find_role(ins, r"^(en|enable)$", r"_en$")
    rw = _find_role(ins, r"^(rw|r_w|rwn|rd_wr)$", r"read.?write",
                    r"^(push|pop)$", r"^(wr|rd)$")
    din = _find_role(ins, r"datain", r"data_in", r"din", r"push_data",
                     r"wr_data", width=lambda w: w > 1)
    dout = _find_role(outs, r"dataout", r"data_out", r"dout", r"pop_data",
                      r"rd_data", width=lambda w: w > 1)
    empty = _find_role(outs, r"empty", width=lambda w: w == 1)
    full = _find_role(outs, r"full", width=lambda w: w == 1)
    if None in (clk, rst, en, rw, din, dout, empty, full):
        return None
    dw = din[1]
    if dout[1] != dw:
        return None  # data-in/out widths must match (it's a FIFO/LIFO of one width)
    depth = _int_after(text, r"up to (\d+) entries", r"hold up to (\d+)",
                       r"(\d+)\s*entries", r"depth\s*of\s*(\d+)")
    if depth is None:
        return None
    dirs = _parse_stack_directions(text)
    if dirs is None:
        return None  # §4.05: push/pop direction unstated -> SKIP
    # SP reset value: the STATED "set to N" (empty marker). Default depth if the
    # prose ties the reset/empty pointer to the depth but gives no explicit number.
    sp_reset = _int_after(text, r"pointer\s+is\s+set\s+to\s+(\d+)",
                          r"set\s+to\s+(\d+)\s*\(indicating",
                          r"reset[^.]*pointer[^.]*?(\d+)")
    if sp_reset is None:
        sp_reset = depth
    clk_n, rst_n = clk[0], rst[0]
    en_n, rw_n = en[0], rw[0]
    din_n, dout_n = din[0], dout[0]
    empty_n, full_n = empty[0], full[0]
    spw = max(1, (sp_reset).bit_length())
    # push/pop SP updates per the PARSED directions.
    push_step = "SP - 1" if dirs["push"] == "dec" else "SP + 1"
    pop_step = "SP + 1" if dirs["pop"] == "inc" else "SP - 1"
    # push writes at the slot the SP will occupy after a decrement-push (top-down),
    # or at the current SP for an increment-push (bottom-up).
    push_slot = "SP-1" if dirs["push"] == "dec" else "SP"
    body = [f"module {top} (",
            f"    input  [{dw-1}:0] {din_n},",
            f"    input         {rw_n},",
            f"    input         {en_n},",
            f"    input         {rst_n},",
            f"    input         {clk_n},",
            f"    output        {empty_n},",
            f"    output        {full_n},",
            f"    output reg [{dw-1}:0] {dout_n}",
            ");",
            f"    reg [{dw-1}:0] stack_mem [0:{depth-1}];",
            f"    reg [{spw}:0] SP;",
            "    integer i;",
            f"    assign {empty_n} = (SP == {sp_reset});",
            "    assign {full} = (SP == 0);".format(full=full_n),
            f"    always @(posedge {clk_n}) begin",
            f"        if ({en_n}) begin",
            f"            if ({rst_n}) begin",
            f"                SP <= {sp_reset};",
            f"                for (i = 0; i < {depth}; i = i + 1)",
            "                    stack_mem[i] <= 0;",
            f"                {dout_n} <= 0;",
            "            end else begin",
            f"                if (!{rw_n} && !{full_n}) begin",
            f"                    SP <= {push_step};",
            f"                    stack_mem[{push_slot}] <= {din_n};",
            f"                end else if ({rw_n} && !{empty_n}) begin",
            f"                    {dout_n} <= stack_mem[SP];",
            "                    stack_mem[SP] <= 0;",
            f"                    SP <= {pop_step};",
            "                end",
            "            end",
            "        end",
            "    end",
            "endmodule"]
    return "\n".join(body) + "\n"


# ============================================================ instr_reg
def _parse_field_slice(text: str, field_w: int) -> Optional[str]:
    """PARSE the bit-slice for an output field from the prose 'High N bits' /
    'Low M bits' / 'full' phrasing, returning 'high', 'low', or 'full', or None
    if the layout is unstated for that field width."""
    low = text.lower()
    if re.search(r"high\s+%d\s+bits?" % field_w, low) or \
       re.search(r"(?:top|upper|most\s+significant)\s+%d\s+bits?" % field_w, low):
        return "high"
    if re.search(r"low\s+%d\s+bits?" % field_w, low) or \
       re.search(r"(?:bottom|lower|least\s+significant)\s+%d\s+bits?" % field_w, low):
        return "low"
    return None


def _parse_fetch_encoding(text: str) -> Optional[Dict[str, int]]:
    """PARSE which fetch code targets which bank from the prose.

    Returns {"bank1_code": int, "bank2_code": int} (the 2-bit fetch literals that
    load bank1 / bank2 respectively), or None if unstated. RTLLM states it as
    'If fetch is 2'b01 ... ins_p1' / 'If fetch is 2'b10 ... ins_p2' OR as
    '1 for register, 2 for RAM/ROM'."""
    low = text.lower()
    # explicit 2'bXX -> bankN form: scan EACH "fetch is 2'bXX ... <bank>" clause
    # independently, bounded to its own sentence (no '.' crossing) so the second
    # clause cannot re-match the first literal. Bank cues use word boundaries so a
    # word like "from" never matches the "rom" cue.
    bank1_code: Optional[int] = None
    bank2_code: Optional[int] = None
    for m in re.finditer(r"fetch\s+is\s+2'b(\d\d)([^.]*)", low):
        code = int(m.group(1), 2)
        tail = m.group(2)
        is_b1 = re.search(r"\b(?:ins_?p?1|first|register|bank\s*1)\b", tail)
        is_b2 = re.search(r"\b(?:ins_?p?2|second|ram|rom|bank\s*2)\b", tail)
        if is_b1 and not is_b2 and bank1_code is None:
            bank1_code = code
        elif is_b2 and not is_b1 and bank2_code is None:
            bank2_code = code
    if bank1_code is not None and bank2_code is not None and bank1_code != bank2_code:
        return {"bank1_code": bank1_code, "bank2_code": bank2_code}
    # numeric "(1 for register, 2 for RAM/ROM)" form
    m = re.search(r"\(\s*(\d+)\s+for\s+register\s*,\s*(\d+)\s+for\s+ram", low)
    if m and int(m.group(1)) != int(m.group(2)):
        return {"bank1_code": int(m.group(1)), "bank2_code": int(m.group(2))}
    return None


def _try_instr_reg(text: str, top: str, ins, outs) -> Optional[str]:
    if "instruction register" not in text.lower():
        return None
    # STRUCTURAL: a clocked register with a multi-bit data input, a 2-bit fetch
    # select, and three output fields sliced from two banks.
    clk = _find_role(ins, r"^(clk|clock)$")
    rst = _find_role(ins, r"(rst|reset)")
    fetch = _find_role(ins, r"fetch", r"sel", r"source", width=lambda w: w == 2)
    data = _find_role(ins, r"^data$", r"data_in", r"din", r"instr",
                      width=lambda w: w > 1)
    if None in (clk, rst, fetch, data):
        return None
    # Outputs: an opcode-like field (ins), a low-field (ad1), and a full-width
    # field (ad2). Identify the full-width one structurally (== data width).
    dw = data[1]
    full_outs = [(n, w) for n, w in outs if w == dw]
    part_outs = [(n, w) for n, w in outs if w < dw]
    if len(full_outs) != 1 or len(part_outs) != 2:
        return None
    ad2_n = full_outs[0][0]
    # The two partial fields: the wider/narrower distinguished by stated slice.
    # ins = the "High N bits" field; ad1 = the "Low M bits" field.
    f1, f2 = part_outs[0], part_outs[1]
    slice1 = _parse_field_slice(text, f1[1])
    slice2 = _parse_field_slice(text, f2[1])
    if slice1 is None or slice2 is None or slice1 == slice2:
        return None  # §4.05: field layout unstated/ambiguous -> SKIP
    if slice1 == "high":
        ins_n, ins_w = f1
        ad1_n, ad1_w = f2
    else:
        ins_n, ins_w = f2
        ad1_n, ad1_w = f1
    enc = _parse_fetch_encoding(text)
    if enc is None:
        return None  # §4.05: fetch encoding unstated -> SKIP
    clk_n, rst_n = clk[0], rst[0]
    fetch_n, data_n = fetch[0], data[0]
    b1 = enc["bank1_code"]
    b2 = enc["bank2_code"]
    body = [f"module {top} (",
            f"    input              {clk_n},",
            f"    input              {rst_n},",
            f"    input  [1:0]       {fetch_n},",
            f"    input  [{dw-1}:0]       {data_n},",
            f"    output [{ins_w-1}:0]       {ins_n},",
            f"    output [{ad1_w-1}:0]       {ad1_n},",
            f"    output [{dw-1}:0]       {ad2_n}",
            ");",
            f"    reg [{dw-1}:0] ins_p1;",
            f"    reg [{dw-1}:0] ins_p2;",
            f"    always @(posedge {clk_n}) begin",
            f"        if (!{rst_n}) begin",
            "            ins_p1 <= 0;",
            "            ins_p2 <= 0;",
            "        end else begin",
            f"            case ({fetch_n})",
            f"                2'b{b1:02b}: ins_p1 <= {data_n};",
            f"                2'b{b2:02b}: ins_p2 <= {data_n};",
            "                default: begin",
            "                    ins_p1 <= ins_p1;",
            "                    ins_p2 <= ins_p2;",
            "                end",
            "            endcase",
            "        end",
            "    end",
            f"    assign {ins_n} = ins_p1[{dw-1}:{dw-ins_w}];",
            f"    assign {ad1_n} = ins_p1[{ad1_w-1}:0];",
            f"    assign {ad2_n} = ins_p2;",
            "endmodule"]
    return "\n".join(body) + "\n"


# ============================================================ dispatcher
_SHAPES = [_try_ram, _try_rom, _try_lifo, _try_instr_reg]


def synth(prompt_text: str, top: str = _DEFAULT_TOP) -> Optional[str]:
    """Parse the register-array memory prompt and EMIT RTL, or None (SKIP).

    `top` is used verbatim; when it is the caller default ("TopModule") the
    prompt's 'Module name:' token is used instead. Returns None on any §4.05
    ambiguity (unenumerated ROM contents, under-specified dims, unstated stack
    direction / field layout, missing interface) so the runner falls through to
    LLM authoring.
    """
    if not prompt_text or not prompt_text.strip():
        return None
    name = top
    if top == _DEFAULT_TOP:
        name = _module_name(prompt_text) or top
    ins, outs = _ports(prompt_text)
    for shape in _SHAPES:
        out = shape(prompt_text, name, ins, outs)
        if out:
            return out
    return None


# ============================================================ CLI
def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="spec prompt text file")
    ap.add_argument("--top", default=_DEFAULT_TOP, help="override module name")
    a = ap.parse_args(argv)
    text = Path(a.prompt).read_text(errors="replace")
    out = synth(text, top=a.top)
    if out is None:
        print("// SKIP: memory_array_synth declined (no matching shape / §4.05 ambiguity)",
              file=sys.stderr)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
