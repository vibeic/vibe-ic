#!/usr/bin/env python3
"""mbist_wrapper_gen.py — Memory-BIST (MBIST) March C- wrapper GENERATOR + GATE.

TAPEOUT-SIGNOFF P0 (MBIST half). A foundry tapeout with on-chip RAM needs a
memory built-in self-test wrapper per RAM so the memories are testable on ATE.
The tapeout checklist LISTS MBIST as required, but until this program there was
no insertion and no simulation — any design containing a RAM (the plugin's own
`memory_array_synth.py` / `memory_synth.py` can generate one) taped out with
UNTESTABLE memories. This program closes that hole with two responsibilities in
one file (the house pattern: a deterministic generator with a runnable
self-check, plus an argparse verdict gate).

(a) DETECT — scan the netlist / RTL / a memory-macro LEF for RAMs:
      * an inferred behavioral memory  `reg [W-1:0] mem [0:D-1];` (the canonical
        on-chip RAM shape emitted by memory_synth) — the ONLY array flagged is
        one that is actually WRITTEN in an always block (a writable RAM). A pure
        read-only initialized LUT/ROM is NOT a March-testable RAM and is left
        alone, so a RAM-less design never trips a spurious FAIL (see §4.05);
      * an SRAM/DPRAM/SPRAM macro-cell INSTANCE (an instantiation of an
        undefined module whose name carries a `sram`/`dpram`/`spram`/`openram`
        token);
      * a memory-macro `MACRO` block in a `.lef`.
    Each detected RAM's geometry — DATA_WIDTH x DEPTH (and the derived
    ADDR_WIDTH = clog2(DEPTH)) — is derived FROM THE DESIGN (the array packed /
    unpacked dimensions, resolved through the design's own `parameter`
    defaults), never from a chip literal (chip-AGNOSTIC).

(b) EMIT — a synthesizable March C- MBIST wrapper parameterized to each RAM's
    geometry. The controller runs the standard six-element March C- sequence
        {  (w0);  ^(r0,w1);  ^(r1,w0);  v(r0,w1);  v(r1,w0);  v(r0)  }
    (address ascending `^` then descending `v`), with a `bist_start` /
    `bist_done` / `bist_fail` interface. The FSM issues each read one cycle
    ahead of its compare, so it is correct for a registered-read (1-cycle) RAM
    and also tolerant of a combinational-read RAM. A companion self-check
    (`build_selfcheck`) emits a good RAM, a stuck-at-0 broken RAM, and an
    iverilog/cocotb-runnable testbench proving a correct RAM ends bist_fail=0
    and a broken RAM ends bist_fail=1. The March C- controller is REAL
    synthesizable Verilog (single synchronous reset, no `!==`, no `initial`),
    not a stub.

THE GATE (argparse + verdict JSON + exit code):
    PASS  — every detected RAM has an emitted MBIST wrapper covering it (a
            wrapper module that carries the bist interface AND instantiates the
            RAM, or a RAM that has the bist interface built in). exit 0.
    FAIL  — one or more detected RAMs have NO wrapper. The verdict lists them.
            exit 1.
    N/A   — the design has NO RAM: a RAM-less design legitimately needs no
            MBIST. This is NOT a PASS (nothing was verified) and NOT a FAIL
            (nothing is wrong). exit 0, verdict "N/A".

§4.05 BOUNDARY (both directions, and both proven by the tests):
    * no-RAM  -> N/A          (never a spurious FAIL, never a spurious PASS);
    * RAM present + NO wrapper -> FAIL (an untestable memory must not slip
      through as PASS). The FAIL half is what makes the gate load-bearing.

CLI:
    mbist_wrapper_gen.py detect <sources...>
    mbist_wrapper_gen.py emit   <sources...> --out DIR [--selfcheck]
    mbist_wrapper_gen.py gate   <sources...> [--json OUT]
  <sources...> may be Verilog (.v/.sv/.vh) or LEF (.lef) files, or directories.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from _specrtl_common import Port, parse_verilog_ports, strip_comments
    try:
        from _specrtl_common import _strip_subprograms  # type: ignore
    except Exception:  # pragma: no cover
        def _strip_subprograms(t):  # type: ignore
            return t
except Exception:  # pragma: no cover - defensive standalone fallback
    @dataclass
    class Port:  # type: ignore
        name: str
        direction: str
        width: int

    def strip_comments(src: str) -> str:  # type: ignore
        src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
        src = re.sub(r"//[^\n]*", " ", src)
        return src

    def _strip_subprograms(t):  # type: ignore
        return t

    _PDECL = re.compile(
        r"\b(input|output|inout)\b\s*(?:reg|wire|logic|signed|unsigned|\s)*"
        r"(?:(\[[^\]]*\])\s*)?"
        r"([A-Za-z_]\w*(?:\s*,\s*(?!(?:input|output|inout)\b)[A-Za-z_]\w*)*)")
    _LIT = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")

    def parse_verilog_ports(text: str) -> List[Port]:  # type: ignore
        out: List[Port] = []
        for m in _PDECL.finditer(text):
            w = 1
            if m.group(2):
                lit = _LIT.fullmatch(m.group(2).strip())
                if lit:
                    w = abs(int(lit.group(1)) - int(lit.group(2))) + 1
            for nm in re.split(r"\s*,\s*", m.group(3)):
                nm = nm.strip()
                if nm:
                    out.append(Port(nm, m.group(1), w))
        return out


# =========================================================================== #
# RAM model
# =========================================================================== #
@dataclass
class RamSpec:
    """A detected RAM + its resolved interface roles (chip-AGNOSTIC)."""
    module: str
    data_width: int
    depth: int
    addr_width: int
    clk: Optional[str]
    we: Optional[str]
    addr: Optional[str]       # shared single-port address
    waddr: Optional[str]      # dual-port write address
    raddr: Optional[str]      # dual-port read address
    din: Optional[str]
    dout: Optional[str]
    ren: Optional[str]
    reset: Optional[str]
    reset_active_low: bool
    source: str
    kind: str                 # "behavioral" | "macro" | "lef"
    complete: bool            # roles fully resolved -> auto-wrappable


_VERILOG_KW = {
    "module", "endmodule", "input", "output", "inout", "reg", "wire", "logic",
    "always", "assign", "if", "else", "begin", "end", "case", "endcase",
    "for", "while", "initial", "posedge", "negedge", "parameter", "localparam",
    "generate", "endgenerate", "function", "task", "signed", "unsigned",
    "genvar", "integer", "real", "wait", "repeat", "forever", "casez", "casex",
}


# =========================================================================== #
# small expression / range helpers
# =========================================================================== #
def _clog2(n: int) -> int:
    if n <= 1:
        return 1
    return (n - 1).bit_length()


def _eval_atom(tok: str, params: Dict[str, int]) -> Optional[int]:
    tok = tok.strip().strip("()").strip()
    if re.fullmatch(r"\d+", tok):
        return int(tok)
    m = re.fullmatch(r"(\d+)'[sS]?[bB]([01_]+)", tok)
    if m:
        return int(m.group(2).replace("_", ""), 2)
    m = re.fullmatch(r"(\d+)'[sS]?[hH]([0-9a-fA-F_]+)", tok)
    if m:
        return int(m.group(2).replace("_", ""), 16)
    m = re.fullmatch(r"(\d+)'[sS]?[dD](\d+)", tok)
    if m:
        return int(m.group(2))
    return params.get(tok)


def _eval_expr(expr: str, params: Dict[str, int]) -> Optional[int]:
    """Resolve the small class of width/depth expressions this dataset uses:
    an int, a parameter id, `NAME +/- k`, or `2**NAME` / `2^NAME`."""
    expr = expr.strip()
    m = re.fullmatch(r"2\s*(?:\*\*|\^)\s*([A-Za-z_]\w*|\d+)", expr)
    if m:
        b = _eval_atom(m.group(1), params)
        return None if b is None else (1 << b)
    m = re.fullmatch(r"([A-Za-z_]\w*|\d+)\s*([+\-])\s*(\d+)", expr)
    if m:
        a = _eval_atom(m.group(1), params)
        if a is None:
            return None
        k = int(m.group(3))
        return a - k if m.group(2) == "-" else a + k
    return _eval_atom(expr, params)


def _range_size(bracket: str, params: Dict[str, int]) -> Optional[int]:
    """Size implied by a `[hi:lo]` packed/unpacked range, a `[N]` C-style
    unpacked size, resolving parameter ids through `params`."""
    s = bracket.strip()
    s = s[1:-1].strip() if s.startswith("[") and s.endswith("]") else s
    if ":" in s:
        hi, lo = s.split(":", 1)
        hv = _eval_expr(hi, params)
        lv = _eval_expr(lo, params)
        if hv is None or lv is None:
            return None
        return abs(hv - lv) + 1
    return _eval_expr(s, params)


_PARAM_RE = re.compile(
    r"\b(?:parameter|localparam)\b\s*(?:\[[^\]]*\]\s*)?"
    r"(?:integer\s+|signed\s+|unsigned\s+)?"
    r"([A-Za-z_]\w*)\s*=\s*([^,;)\n]+)")


def _param_map(text: str) -> Dict[str, int]:
    params: Dict[str, int] = {}
    for m in _PARAM_RE.finditer(text):
        val = _eval_expr(m.group(2).strip(), params)
        if val is not None:
            params.setdefault(m.group(1), val)
    return params


# =========================================================================== #
# Verilog module iteration + memory detection
# =========================================================================== #
def _iter_modules(clean_text: str) -> List[Tuple[str, str]]:
    """(name, region) for each module. `region` spans from just after the
    `module NAME` tokens to the matching `endmodule` (header + body)."""
    out: List[Tuple[str, str]] = []
    for m in re.finditer(r"\bmodule\s+([A-Za-z_]\w*)", clean_text):
        em = re.search(r"\bendmodule\b", clean_text[m.end():])
        end = m.end() + (em.start() if em else len(clean_text))
        out.append((m.group(1), clean_text[m.end():end]))
    return out


# A memory is a reg/logic with an UNPACKED dimension after the name.
_MEM_RE = re.compile(
    r"\b(?:reg|logic|bit)\b\s*"
    r"(?:signed\s+|unsigned\s+)?"
    r"(\[[^\]]*\])?\s*"                 # 1: packed width (optional)
    r"([A-Za-z_]\w*)\s*"                # 2: array name
    r"(\[[^\]]*\])\s*;")               # 3: unpacked depth (required)


def _is_written(region: str, name: str) -> bool:
    """True if `name` is a WRITABLE memory: an indexed write governed by an
    `always` block (a non-blocking clocked write, or a blocking write in a
    combinational/clocked always). A ROM preloaded only in an `initial` block
    (or `$readmem`) is NOT flagged — a read-only LUT is not a March-testable
    RAM, so a RAM-less-plus-LUT design still resolves to N/A (§4.05)."""
    esc = re.escape(name)
    for m in re.finditer(rf"\b{esc}\s*\[[^\]]*\]\s*(<=|=(?!=))", region):
        pre = region[:m.start()]
        k_always = pre.rfind("always")
        k_initial = pre.rfind("initial")
        if m.group(1) == "<=":
            # non-blocking write: a clocked RAM write unless it sits inside an
            # initial preload (unusual) whose keyword is nearer.
            if k_always >= k_initial:
                return True
        else:
            # blocking write: count only when an `always` governs it, never an
            # `initial` preload.
            if k_always > k_initial:
                return True
    return False


def _first_written_memory(region: str,
                          params: Dict[str, int]) -> Optional[Tuple[int, int]]:
    for m in _MEM_RE.finditer(region):
        name = m.group(2)
        if name in _VERILOG_KW:
            continue
        if not _is_written(region, name):
            continue
        width = _range_size(m.group(1), params) if m.group(1) else 1
        depth = _range_size(m.group(3), params)
        if width is None or depth is None or width < 1 or depth < 1:
            continue
        return width, depth
    return None


def _module_ports(region: str) -> List[Port]:
    reg = _strip_subprograms(region)
    return parse_verilog_ports(reg)


_W1 = (lambda w: w == 1)


def _role(ports: List[Port], *pats: str, width=None) -> Optional[Port]:
    rx = [re.compile(p, re.I) for p in pats]
    for p in ports:
        if width is not None and not width(p.width):
            continue
        if any(r.search(p.name) for r in rx):
            return p
    return None


def _build_spec(module: str, dw: int, depth: int, ports: List[Port],
                source: str) -> RamSpec:
    ins = [p for p in ports if p.direction == "input"]
    outs = [p for p in ports if p.direction in ("output", "inout")]
    clk = _role(ins, r"^(i_|w_|r_)?cl(?:k|ock)(_in|_i)?$", r"^clk", r"clock")
    reset = _role(ins, r"(rst|reset|areset|clr|clear)")
    we = _role(ins, r"(write_?en|wr_?en|^wen$|^w_en$|^we$|^wr$|^write$|"
               r"write_enable|wr_enable)", width=_W1)
    ren = _role(ins, r"(read_?en|rd_?en|^ren$|^r_en$|^re$|^rd$|read_enable)",
                width=_W1)
    waddr = _role(ins, r"(write_?addr|wr_?addr|w_?addr|^waddr$)")
    raddr = _role(ins, r"(read_?addr|rd_?addr|r_?addr|^raddr$)")
    din = _role(ins, r"(write_?data|wr_?data|w_?data|data_?in|^din$|^wdata$)")
    dout = _role(outs, r"(read_?data|rd_?data|r_?data|data_?out|^dout$|"
                 r"^rdata$|^q$)")
    dual = waddr is not None and raddr is not None and waddr.name != raddr.name
    addr = None if dual else _role(ins, r"^addr$", r"^address$", r"^a$",
                                   r"_addr$", r"addr")
    # ADDR_WIDTH: prefer the RAM's own address-port width; else clog2(depth).
    aw = None
    for p in ins:
        if addr is not None and p.name == addr.name and p.width > 1:
            aw = p.width
        if waddr is not None and p.name == waddr.name and p.width > 1:
            aw = p.width
    need = _clog2(depth)
    if aw is None or aw < need:
        aw = need
    rlow = bool(reset) and (reset.name.lower().endswith("_n")
                            or reset.name.lower() in ("rstn", "resetn"))
    complete = bool(clk and we and din and dout and (addr is not None or dual))
    return RamSpec(
        module=module, data_width=dw, depth=depth, addr_width=aw,
        clk=clk.name if clk else None, we=we.name if we else None,
        addr=addr.name if addr else None,
        waddr=waddr.name if dual else None,
        raddr=raddr.name if dual else None,
        din=din.name if din else None, dout=dout.name if dout else None,
        ren=ren.name if ren else None, reset=reset.name if reset else None,
        reset_active_low=rlow, source=source, kind="behavioral",
        complete=complete)


def detect_text(text: str, source: str = "inline") -> List[RamSpec]:
    """Behavioral-memory RAMs declared in Verilog `text`."""
    clean = strip_comments(text)
    fparams = _param_map(clean)
    specs: List[RamSpec] = []
    for name, region in _iter_modules(clean):
        params = dict(fparams)
        params.update(_param_map(region))
        mem = _first_written_memory(region, params)
        if mem is None:
            continue
        dw, depth = mem
        specs.append(_build_spec(name, dw, depth, _module_ports(region), source))
    return specs


# --------------------------------------------------------------------------- #
# SRAM/DPRAM/SPRAM macro-cell instances + LEF memory macros (geometry-lean)
# --------------------------------------------------------------------------- #
_MACRO_NAME_RE = re.compile(r"(?i)(sram|dpram|spram|openram)")
_INST_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s+(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*\(")


def _geom_from_name(name: str) -> Tuple[Optional[int], Optional[int]]:
    m = re.search(r"(\d+)x(\d+)", name, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _macro_spec(mod: str, source: str, kind: str) -> RamSpec:
    dw, depth = _geom_from_name(mod)
    return RamSpec(
        module=mod, data_width=dw or 0, depth=depth or 0,
        addr_width=_clog2(depth) if depth else 0,
        clk=None, we=None, addr=None, waddr=None, raddr=None, din=None,
        dout=None, ren=None, reset=None, reset_active_low=True,
        source=source, kind=kind, complete=False)


def _detect_macro_instances(text: str, defined: set,
                            source: str) -> List[RamSpec]:
    clean = strip_comments(text)
    out: List[RamSpec] = []
    for _name, region in _iter_modules(clean):
        for im in _INST_RE.finditer(region):
            mod = im.group(1)
            if mod in defined or mod in _VERILOG_KW:
                continue
            if not _MACRO_NAME_RE.search(mod):
                continue
            out.append(_macro_spec(mod, source, "macro"))
    return out


def _looks_lef(label: str, text: str) -> bool:
    return label.lower().endswith(".lef") or bool(
        re.search(r"^\s*MACRO\b", text, re.M))


def _parse_lef(text: str, source: str) -> List[RamSpec]:
    out: List[RamSpec] = []
    for m in re.finditer(r"^\s*MACRO\s+([A-Za-z_]\w*)", text, re.M):
        name = m.group(1)
        if _MACRO_NAME_RE.search(name) or re.search(r"(?i)\b(ram|rom|mem)\b",
                                                     name):
            out.append(_macro_spec(name, source, "lef"))
    return out


def detect(items: List[Tuple[str, str]]) -> List[RamSpec]:
    """Detect every RAM (behavioral array + macro instance + LEF macro) across
    a list of (label, text) sources. De-duplicated by module name."""
    verilog: List[Tuple[str, str]] = []
    lefs: List[Tuple[str, str]] = []
    for label, text in items:
        (lefs if _looks_lef(label, text) else verilog).append((label, text))

    specs: List[RamSpec] = []
    defined: set = set()
    for label, text in verilog:
        specs.extend(detect_text(text, source=label))
        for name, _region in _iter_modules(strip_comments(text)):
            defined.add(name)

    seen = {s.module for s in specs}
    for label, text in verilog:
        for ms in _detect_macro_instances(text, defined, label):
            if ms.module not in seen:
                specs.append(ms)
                seen.add(ms.module)
    for label, text in lefs:
        for ms in _parse_lef(text, label):
            if ms.module not in seen:
                specs.append(ms)
                seen.add(ms.module)

    out: List[RamSpec] = []
    dedup: set = set()
    for s in specs:
        if s.module in dedup:
            continue
        dedup.add(s.module)
        out.append(s)
    return out


# =========================================================================== #
# EMIT — the March C- MBIST wrapper
# =========================================================================== #
# The controller core is geometry-parameterized (DATA_WIDTH / DEPTH /
# ADDR_WIDTH are the module parameters, referenced symbolically) and its logic
# is a fixed constant — only the module header and the RAM-under-test
# instantiation depend on the detected RAM, so this block carries no Python
# str.format braces to collide with Verilog concatenation `{W{1'b0}}`.
_FSM_CORE = r"""
    // ---- backgrounds ----
    localparam [DATA_WIDTH-1:0] BG0 = {DATA_WIDTH{1'b0}};
    localparam [DATA_WIDTH-1:0] BG1 = {DATA_WIDTH{1'b1}};

    // ---- controller state ----
    localparam S_IDLE = 2'd0, S_RUN = 2'd1, S_DONE = 2'd2;
    reg  [1:0]            state;
    reg  [2:0]            elem;    // March C- element index 0..5
    reg                   opix;    // operation index within element (0/1)
    reg                   rphase;  // read phase: 0=issue address, 1=compare

    // element decode: direction + number of operations
    //   0: ^ (w0)     1: ^ (r0,w1)   2: ^ (r1,w0)
    //   3: v (r0,w1)  4: v (r1,w0)   5: v (r0)
    reg                   dir_down;
    reg  [1:0]            nops;
    always @(*) begin
        case (elem)
            3'd0:    begin dir_down = 1'b0; nops = 2'd1; end
            3'd1:    begin dir_down = 1'b0; nops = 2'd2; end
            3'd2:    begin dir_down = 1'b0; nops = 2'd2; end
            3'd3:    begin dir_down = 1'b1; nops = 2'd2; end
            3'd4:    begin dir_down = 1'b1; nops = 2'd2; end
            default: begin dir_down = 1'b1; nops = 2'd1; end
        endcase
    end

    // current-operation decode: read/write + expected/written background
    reg cur_read, cur_write, cur_expv, cur_wrv;
    always @(*) begin
        cur_read  = 1'b0; cur_write = 1'b0; cur_expv = 1'b0; cur_wrv = 1'b0;
        case (elem)
            3'd0:            begin cur_write = 1'b1; cur_wrv  = 1'b0; end
            3'd1: if (!opix) begin cur_read  = 1'b1; cur_expv = 1'b0; end
                  else       begin cur_write = 1'b1; cur_wrv  = 1'b1; end
            3'd2: if (!opix) begin cur_read  = 1'b1; cur_expv = 1'b1; end
                  else       begin cur_write = 1'b1; cur_wrv  = 1'b0; end
            3'd3: if (!opix) begin cur_read  = 1'b1; cur_expv = 1'b0; end
                  else       begin cur_write = 1'b1; cur_wrv  = 1'b1; end
            3'd4: if (!opix) begin cur_read  = 1'b1; cur_expv = 1'b1; end
                  else       begin cur_write = 1'b1; cur_wrv  = 1'b0; end
            default:         begin cur_read  = 1'b1; cur_expv = 1'b0; end
        endcase
    end

    // ---- RAM input drive (combinational) ----
    always @(*) begin
        mb_we  = (state == S_RUN) && cur_write && (rphase == 1'b0);
        mb_re  = (state == S_RUN) && cur_read;
        mb_din = cur_wrv ? BG1 : BG0;
    end

    wire                 last_op   = (opix == (nops - 2'd1));
    wire                 at_end    = dir_down ? (mb_addr == {ADDR_WIDTH{1'b0}})
                                              : (mb_addr == (DEPTH - 1));
    wire                 last_elem = (elem == 3'd5);
    wire [ADDR_WIDTH-1:0] top_addr = (DEPTH - 1);

    // ---- sequencer (single synchronous active-low reset) ----
    always @(posedge clk) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            elem      <= 3'd0;
            opix      <= 1'b0;
            rphase    <= 1'b0;
            mb_addr   <= {ADDR_WIDTH{1'b0}};
            bist_done <= 1'b0;
            bist_fail <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    bist_done <= 1'b0;
                    if (bist_start) begin
                        state     <= S_RUN;
                        elem      <= 3'd0;
                        opix      <= 1'b0;
                        rphase    <= 1'b0;
                        mb_addr   <= {ADDR_WIDTH{1'b0}};
                        bist_fail <= 1'b0;
                    end
                end
                S_RUN: begin
                    if (cur_read && (rphase == 1'b0)) begin
                        rphase <= 1'b1;              // wait 1 cycle for read data
                    end else begin
                        if (cur_read) begin          // rphase==1: data valid
                            if (mb_dout != (cur_expv ? BG1 : BG0))
                                bist_fail <= 1'b1;
                        end
                        rphase <= 1'b0;
                        if (!last_op) begin
                            opix <= opix + 1'b1;     // next op, same cell
                        end else begin
                            opix <= 1'b0;
                            if (at_end) begin
                                if (last_elem) begin
                                    state     <= S_DONE;
                                    bist_done <= 1'b1;
                                end else begin
                                    elem    <= elem + 3'd1;
                                    mb_addr <= ((elem + 3'd1) >= 3'd3)
                                               ? top_addr : {ADDR_WIDTH{1'b0}};
                                end
                            end else begin
                                mb_addr <= dir_down ? (mb_addr - 1'b1)
                                                    : (mb_addr + 1'b1);
                            end
                        end
                    end
                end
                default: begin // S_DONE
                    bist_done <= 1'b1;
                    if (!bist_start) state <= S_IDLE;
                end
            endcase
        end
    end
endmodule
"""


def _instance_lines(spec: RamSpec) -> List[str]:
    conns = [f".{spec.clk}(clk)"]
    if spec.reset:
        conns.append(f".{spec.reset}(" +
                     ("rst_n" if spec.reset_active_low else "~rst_n") + ")")
    conns.append(f".{spec.we}(mb_we)")
    if spec.ren:
        conns.append(f".{spec.ren}(mb_re)")
    if spec.addr:
        conns.append(f".{spec.addr}(mb_addr)")
    else:
        conns.append(f".{spec.waddr}(mb_addr)")
        conns.append(f".{spec.raddr}(mb_addr)")
    conns.append(f".{spec.din}(mb_din)")
    conns.append(f".{spec.dout}(mb_dout)")
    body = ",\n        ".join(conns)
    return [f"    {spec.module} dut (", f"        {body}", "    );"]


def emit_wrapper(spec: RamSpec, wrapper_name: Optional[str] = None) -> str:
    """Emit the synthesizable March C- MBIST wrapper for `spec`.

    Requires a fully-resolved interface (spec.complete). The wrapper
    instantiates the RAM under test and drives the six-element March C-
    sequence, asserting bist_fail on any read mismatch."""
    if not spec.complete:
        raise ValueError(
            f"cannot auto-emit MBIST wrapper for {spec.module}: interface "
            f"roles (clk/we/addr/din/dout) not fully resolved")
    wrapper = wrapper_name or f"{spec.module}_mbist"
    lines = [
        "// ---------------------------------------------------------------",
        f"// MBIST March C- wrapper for RAM `{spec.module}` "
        f"({spec.data_width} x {spec.depth}, ADDR_WIDTH={spec.addr_width}).",
        "// Auto-generated by mbist_wrapper_gen.py — deterministic, no AI.",
        "// Algorithm: March C-  { (w0); ^(r0,w1); ^(r1,w0); v(r0,w1); "
        "v(r1,w0); v(r0) }",
        "// Reads are issued one cycle ahead of compare (correct for a "
        "registered-read RAM).",
        "// ---------------------------------------------------------------",
        f"module {wrapper} #(",
        f"    parameter DATA_WIDTH = {spec.data_width},",
        f"    parameter DEPTH      = {spec.depth},",
        f"    parameter ADDR_WIDTH = {spec.addr_width}",
        ") (",
        "    input                   clk,",
        "    input                   rst_n,        // synchronous, active-low",
        "    input                   bist_start,",
        "    output reg              bist_done,",
        "    output reg              bist_fail",
        ");",
        "    // ---- RAM interface driven by the controller ----",
        "    reg  [ADDR_WIDTH-1:0]   mb_addr;",
        "    reg                     mb_we;",
        "    reg                     mb_re;",
        "    reg  [DATA_WIDTH-1:0]   mb_din;",
        "    wire [DATA_WIDTH-1:0]   mb_dout;",
        "",
        "    // ---- RAM under test ----",
    ]
    lines.extend(_instance_lines(spec))
    return "\n".join(lines) + "\n" + _FSM_CORE.lstrip("\n")


# =========================================================================== #
# SELF-CHECK — good RAM, stuck-at broken RAM, and a runnable testbench
# =========================================================================== #
def emit_reference_ram(spec: RamSpec, broken: bool = False) -> str:
    """A canonical single-port synchronous-read RAM with `spec`'s port names and
    geometry. `broken=True` forces address 0 stuck-at-0 (a fault March C-
    detects on the first r1 of address 0)."""
    a = spec.addr or spec.waddr or "addr"
    clk, we, din, dout = spec.clk or "clk", spec.we or "we", \
        spec.din or "din", spec.dout or "dout"
    lines = [
        f"// reference RAM for `{spec.module}` self-check "
        f"({'STUCK-AT-0 @addr0 (broken)' if broken else 'good'}).",
        f"module {spec.module} #(",
        f"    parameter DATA_WIDTH = {spec.data_width},",
        f"    parameter DEPTH      = {spec.depth},",
        f"    parameter ADDR_WIDTH = {spec.addr_width}",
        ") (",
        f"    input                    {clk},",
        f"    input                    {we},",
        f"    input  [ADDR_WIDTH-1:0]  {a},",
        f"    input  [DATA_WIDTH-1:0]  {din},",
        f"    output reg [DATA_WIDTH-1:0] {dout}",
        ");",
        "    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];",
        f"    always @(posedge {clk}) begin",
    ]
    if broken:
        lines.append(
            f"        if ({we}) mem[{a}] <= ({a} == {{ADDR_WIDTH{{1'b0}}}}) ? "
            f"{{DATA_WIDTH{{1'b0}}}} : {din};")
    else:
        lines.append(f"        if ({we}) mem[{a}] <= {din};")
    lines.append(f"        {dout} <= mem[{a}];")
    lines += ["    end", "endmodule", ""]
    return "\n".join(lines)


def emit_selfcheck_tb(spec: RamSpec, wrapper_name: str) -> str:
    """A testbench that pulses bist_start, waits for bist_done, and prints
    `MBIST_RESULT PASS|FAIL|TIMEOUT`."""
    timeout = spec.depth * 16 + 2000
    lines = [
        "`timescale 1ns/1ps",
        "module tb_mbist;",
        "    reg  clk = 1'b0;",
        "    reg  rst_n = 1'b0;",
        "    reg  bist_start = 1'b0;",
        "    wire bist_done;",
        "    wire bist_fail;",
        "    integer cyc;",
        f"    {wrapper_name} dut (",
        "        .clk(clk), .rst_n(rst_n), .bist_start(bist_start),",
        "        .bist_done(bist_done), .bist_fail(bist_fail)",
        "    );",
        "    always #5 clk = ~clk;",
        "    initial begin",
        "        rst_n = 1'b0; bist_start = 1'b0;",
        "        repeat (4) @(negedge clk);",
        "        rst_n = 1'b1;",
        "        @(negedge clk);",
        "        bist_start = 1'b1;",
        "        @(negedge clk);",
        "        bist_start = 1'b0;",
        "        cyc = 0;",
        f"        while (!bist_done && cyc < {timeout}) begin",
        "            @(negedge clk); cyc = cyc + 1;",
        "        end",
        "        if (!bist_done)      $display(\"MBIST_RESULT TIMEOUT\");",
        "        else if (bist_fail)  $display(\"MBIST_RESULT FAIL\");",
        "        else                 $display(\"MBIST_RESULT PASS\");",
        "        $finish;",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def build_selfcheck(data_width: int, depth: int,
                    module: str = "mbist_ram") -> Dict[str, str]:
    """A fully self-contained MBIST self-check bundle for a `data_width` x
    `depth` single-port RAM: {spec, wrapper_name, wrapper, ram_good,
    ram_broken, tb}."""
    spec = RamSpec(
        module=module, data_width=data_width, depth=depth,
        addr_width=_clog2(depth), clk="clk", we="we", addr="addr",
        waddr=None, raddr=None, din="din", dout="dout", ren=None, reset=None,
        reset_active_low=True, source="selfcheck", kind="behavioral",
        complete=True)
    wname = f"{module}_mbist"
    return {
        "spec": spec,
        "wrapper_name": wname,
        "wrapper": emit_wrapper(spec, wname),
        "ram_good": emit_reference_ram(spec, broken=False),
        "ram_broken": emit_reference_ram(spec, broken=True),
        "tb": emit_selfcheck_tb(spec, wname),
    }


# =========================================================================== #
# GATE — verdict PASS / FAIL / N/A
# =========================================================================== #
def _is_mbist_wrapper(ports: List[Port]) -> bool:
    def has(pat: str) -> bool:
        return any(re.search(pat, p.name, re.I) for p in ports)
    return has(r"bist.*start") and has(r"bist.*done") and has(r"bist.*fail")


def _module_instantiates(region: str, target: str) -> bool:
    return re.search(
        r"\b" + re.escape(target) +
        r"\b\s*(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*\(", region) is not None


def _module_recs(items: List[Tuple[str, str]]) -> List[Dict]:
    recs: List[Dict] = []
    for label, text in items:
        if _looks_lef(label, text):
            continue
        clean = strip_comments(text)
        for name, region in _iter_modules(clean):
            recs.append({"name": name, "ports": _module_ports(region),
                         "region": region, "source": label})
    return recs


def _verdict_message(verdict: str, rams: List[RamSpec],
                     uncovered: List[RamSpec]) -> str:
    if verdict == "N/A":
        return ("no writable RAM / SRAM macro detected — a RAM-less design "
                "needs no MBIST (§4.05: N/A, not a failure and not a pass)")
    if verdict == "PASS":
        return (f"all {len(rams)} detected RAM(s) have an MBIST wrapper "
                "(March C- coverage present)")
    names = ", ".join(f"{r.module}({r.data_width}x{r.depth})"
                      for r in uncovered)
    return (f"{len(uncovered)} RAM(s) with NO MBIST wrapper: {names} — insert "
            "a March-test MBIST wrapper (mbist_wrapper_gen emit) before tapeout")


def gate(items: List[Tuple[str, str]]) -> Tuple[Dict, int]:
    """Return (verdict_report, exit_code). exit 0 = PASS or N/A, 1 = FAIL."""
    rams = detect(items)
    recs = _module_recs(items)
    by_name = {r["name"]: r for r in recs}
    wrappers = [r for r in recs if _is_mbist_wrapper(r["ports"])]

    results: List[Tuple[RamSpec, Optional[str]]] = []
    for ram in rams:
        cov: Optional[str] = None
        self_rec = by_name.get(ram.module)
        if self_rec and _is_mbist_wrapper(self_rec["ports"]):
            cov = ram.module           # RAM has BIST built in
        else:
            for w in wrappers:
                if w["name"] == ram.module:
                    continue
                if _module_instantiates(w["region"], ram.module):
                    cov = w["name"]
                    break
        results.append((ram, cov))

    uncovered = [ram for ram, cov in results if not cov]
    if not rams:
        verdict, rc = "N/A", 0
    elif uncovered:
        verdict, rc = "FAIL", 1
    else:
        verdict, rc = "PASS", 0

    report = {
        "program": "mbist_wrapper_gen",
        "check": "mbist_coverage",
        "verdict": verdict,
        "ram_count": len(rams),
        "rams": [{
            "module": r.module, "data_width": r.data_width, "depth": r.depth,
            "addr_width": r.addr_width, "kind": r.kind, "source": r.source,
            "auto_wrappable": r.complete, "covered_by": cov,
        } for r, cov in results],
        "uncovered": [r.module for r in uncovered],
        "wrappers": [w["name"] for w in wrappers],
        "message": _verdict_message(verdict, rams, uncovered),
    }
    return report, rc


# =========================================================================== #
# emit driver + CLI
# =========================================================================== #
def emit(items: List[Tuple[str, str]], out_dir: Path,
         selfcheck: bool = False) -> Dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rams = detect(items)
    emitted: List[Dict] = []
    skipped: List[Dict] = []
    for spec in rams:
        if not spec.complete:
            skipped.append({
                "module": spec.module, "kind": spec.kind,
                "reason": ("interface roles (clk/we/addr/din/dout) not fully "
                           "resolved — a hand-authored MBIST wrapper is "
                           "needed for this macro/embedded RAM")})
            continue
        wname = f"{spec.module}_mbist"
        (out / f"{wname}.v").write_text(emit_wrapper(spec, wname))
        emitted.append({"module": spec.module, "wrapper": wname,
                        "file": f"{wname}.v", "data_width": spec.data_width,
                        "depth": spec.depth, "addr_width": spec.addr_width})
        if selfcheck:
            sc = build_selfcheck(spec.data_width, spec.depth,
                                 module=f"{spec.module}_ref")
            scdir = out / f"selfcheck_{spec.module}"
            scdir.mkdir(exist_ok=True)
            (scdir / f"{sc['wrapper_name']}.v").write_text(sc["wrapper"])
            (scdir / "ram_good.v").write_text(sc["ram_good"])
            (scdir / "ram_broken.v").write_text(sc["ram_broken"])
            (scdir / "tb_mbist.v").write_text(sc["tb"])
    manifest = {"program": "mbist_wrapper_gen", "out": str(out),
                "emitted": emitted, "skipped": skipped}
    (out / "mbist_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    return manifest


def _load_items(paths: List[str]) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    exts = (".v", ".sv", ".vh", ".lef")
    for pth in paths:
        p = Path(pth)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in exts:
                    items.append((str(f), f.read_text(errors="replace")))
        elif p.is_file():
            items.append((str(p), p.read_text(errors="replace")))
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect", help="list detected RAMs (JSON)")
    d.add_argument("paths", nargs="+")
    e = sub.add_parser("emit", help="emit MBIST wrapper(s) to --out")
    e.add_argument("paths", nargs="+")
    e.add_argument("--out", required=True)
    e.add_argument("--selfcheck", action="store_true",
                   help="also emit a good/broken RAM + testbench bundle")
    g = sub.add_parser("gate", help="MBIST coverage verdict (PASS/FAIL/N/A)")
    g.add_argument("paths", nargs="+")
    g.add_argument("--json", help="write the verdict report to this path")
    a = ap.parse_args(argv)

    if a.cmd == "detect":
        items = _load_items(a.paths)
        specs = detect(items)
        print(json.dumps([asdict(s) for s in specs], indent=2))
        return 0
    if a.cmd == "emit":
        items = _load_items(a.paths)
        man = emit(items, Path(a.out), selfcheck=a.selfcheck)
        print(json.dumps(man, indent=2))
        return 0
    # gate
    items = _load_items(a.paths)
    if not items:
        print("mbist_wrapper_gen: FAIL — no source files found", file=sys.stderr)
        return 2
    report, rc = gate(items)
    print(f"mbist_wrapper_gen: {report['verdict']} — {report['message']}")
    for r in report["rams"]:
        cov = r["covered_by"] or "(none)"
        print(f"  RAM {r['module']} {r['data_width']}x{r['depth']} "
              f"[{r['kind']}] covered_by={cov}")
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
