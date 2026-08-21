#!/usr/bin/env python3
"""memory_synth.py — a DETERMINISTIC solver for the CVDP parameterized MEMORY
family of "code generation" problems: synchronous FIFO, LIFO / stack, single- and
dual-port RAM, ROM (stated contents), and the register file.

WHY a dedicated CVDP memory solver (and not memory_array_synth):
  * programs/memory_array_synth.py is the RTLLM/VerilogEval-phrased memory solver:
    it reads ports through `rtllm_port_bridge.bridge_prompt -> port_parser`, keys on
    RTLLM phrasings ("register array", "locations 0 through K", "up to N entries",
    "instruction register"), and notably has NO synchronous-FIFO shape at all.
  * A CVDP "code generation" memory prompt instead states its interface as a clean
    `### Input Ports` / `### Output Ports` markdown list (`**data_in** (DATA_WIDTH
    bits)`, `**`empty`** (1 bit)`) with `ADDR_WIDTH`/`DEPTH` parameter defaults, and
    its protocol as prose + an example-vector table — none of which the RTLLM reader
    fires on. So memory_array_synth fires on 0 CVDP memory records.

This solver builds ONLY what those do not cover: a CVDP-native interface reader (the
`### Inputs/Outputs` markdown list, shared with shift_counter_synth's dialect)
plus five deterministic emitters, each gated by its STATED structure:

  SYNC FIFO   — a single-clock circular-buffer FIFO with write/read pointers, full /
                empty flags (and an optional element count), depth + width PARSED.
                §4.05: SKIP an ASYNC / dual-clock / gray-pointer-CDC FIFO unless the
                gray-code pointer-synchronizer CDC is FULLY stated (in practice this
                always SKIPs — a wrong CDC is a silicon hazard, never a guess).
  LIFO/STACK  — push/pop stack with a stack pointer, full / empty, depth + width
                PARSED; combinational top-of-stack read (data_out = last pushed).
  RAM         — single- or dual-port register-array RAM, depth + width PARSED, sync
                or async read PARSED. Write on enable+addr+data; read by addr.
  ROM         — a stated-contents read-only memory: address in, data out, the
                contents table ENUMERATED in the prompt (one literal per location).
  REGISTER    — a register file: #regs (depth) + #read ports + #write ports PARSED,
  FILE          with per-port addr/data/enable. Combinational read.

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  * NEVER read the golden/reference RTL. Ports come from the PROMPT's own interface
    section (and the module name from input.prompt/context via the bridge) — never
    from the OFF-LIMITS harness (.env TOPLEVEL, cocotb TB) or output bodies.
  * SKIP (return None) on ANY unstated/ambiguous governing fact: unstated depth or
    width, an unstated/ambiguous read/write protocol, an async-CDC FIFO whose
    gray-pointer synchronizer is not fully pinned, OR a composite design (the memory
    is one block inside a cache/AXI/APB/SoC) / an extra-feature variant (BIST,
    clock-gating, collision side-outputs, ping-pong, error codes) the bare primitive
    cannot honestly cover. A wrong memory/stack silently passes lint+synth and only a
    testbench catches it, so a skip is always safer than a guess.
  * A "modify the existing RTL" delta task (prior code in input['context']) is not a
    single-function emit -> SKIP.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC (keys on STATED structure only, never on a design name), deterministic.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

Port = Tuple[str, int]  # (name, width)

_NOT_A_PORT_NAME = {
    "signed", "unsigned", "wire", "reg", "logic", "input", "output", "inout",
    "module", "endmodule", "parameter", "localparam",
}


# --------------------------------------------------------------------------- #
# module name — from input.prompt + input.context ONLY (via the bridge). The
# harness `.env` TOPLEVEL is OFF-LIMITS oracle, so there is NO harness fallback:
# when the name is stated in neither the prompt nor the context, return None
# (honest SKIP), never a peek at the hidden testbench.
# --------------------------------------------------------------------------- #
def _toplevel(record: dict) -> Optional[str]:
    try:
        import cvdp_atomic_bridge as _bridge
        return _bridge.toplevel_name(record)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# CVDP-native interface reader: the `### Inputs` / `### Outputs` markdown list.
# Forms (all from the dataset prose, never the golden RTL):
#   - **`data_in`** (DATA_WIDTH bits): ...
#   - **`data_in`** (8-bits, [7:0]): ...
#   - **`full`** (1 bit): ...
#   - `clock` (1 bit): ...
#   - **`din`** (`DATA_WIDTH` bits, [DATA_WIDTH - 1:0]): ...
# A parameterized width (`DATA_WIDTH bits` / `[DATA_WIDTH-1:0]`) resolves to the
# STATED parameter default. A data port whose width is unresolved is DROPPED, which
# forces a §4.05 SKIP upstream rather than a phantom width.
# --------------------------------------------------------------------------- #
def _param_defaults(prompt: str) -> Dict[str, int]:
    """STATED parameter defaults: `DATA_WIDTH` (default = 8) / `Default value is 8
    bits.`. A definition line `- **`NAME`**: <desc>. Default value is N` ties NAME to
    N even across a sentence break, so the `default` scan is anchored per-LINE on the
    bullet that introduces NAME (the desc may contain a sentence period)."""
    out: Dict[str, int] = {}
    # per-line: a bullet introducing a parameter NAME whose SAME line states a default.
    for ln in prompt.splitlines():
        m = re.match(r"\s*[-*]\s*\*{0,2}`?([A-Za-z_][A-Za-z0-9_]*)`?\*{0,2}\b", ln)
        if not m:
            continue
        name = m.group(1)
        if name.lower() in _NOT_A_PORT_NAME:
            continue
        dm = re.search(r"default(?:\s+value)?(?:\s+of)?\s*(?:is\s+|=\s*)?`?(\d+)`?",
                       ln, re.I)
        if dm:
            out.setdefault(name, int(dm.group(1)))
    # inline `NAME (default = 8)` / `NAME, with a default value of 8`.
    for m in re.finditer(
        r"`?([A-Za-z_][A-Za-z0-9_]*)`?[^.\n]{0,60}?default(?:\s+value)?(?:\s+of)?\s*"
        r"(?:is\s+|=\s*)?`?(\d+)`?", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in re.finditer(r"`?([A-Za-z_][A-Za-z0-9_]*)`?\s*\(\s*default\s*=\s*(\d+)\s*\)",
                         prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in re.finditer(r"parameter\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def _width_from_cell(cell: str, params: Dict[str, int]) -> Optional[int]:
    """Resolve a declared width from a `(...)` interface cell."""
    # explicit [hi:lo]
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    # parameterized [`P`-1:0] / [P-1:0]
    m = re.search(r"\[\s*`?([A-Za-z_]\w*)`?\s*-\s*1\s*:\s*0\s*\]", cell)
    if m and m.group(1) in params:
        return params[m.group(1)]
    # a parameter token used as the width itself: `DATA_WIDTH bits`
    m = re.search(r"`?([A-Za-z_][A-Za-z0-9_]*)`?\s*-?\s*bits?\b", cell, re.I)
    if m and m.group(1) in params:
        return params[m.group(1)]
    # an `N-bit(s)` literal token
    m = re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*-?\s*bit\b", cell, re.I) or re.search(r"\(\s*1\s*\)", cell):
        return 1
    return None


_PORT_LINE_RE = re.compile(
    r"""^\s*(?:\d+\.\s*)?[-*]?\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*   # **`name`**
        \(([^)]*)\)""",                                              # (...)
    re.X)

_PORT_LINE_NOWIDTH_RE = re.compile(
    r"^\s*(?:\d+\.\s*)?[-*]\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*[:—\-]\s*(.+)$")


def _section_ports(prompt: str, header_words, params) -> List[Port]:
    """Ports listed under an `### Inputs`/`### Outputs`-style heading."""
    lines = prompt.splitlines()
    ports: List[Port] = []
    in_sec = False
    for ln in lines:
        h = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", ln) or re.match(
            r"^\s*\d*\.?\s*\*\*(.+?)\*\*\s*:?\s*$", ln)
        if h:
            label = h.group(1).strip().lower().rstrip(":")
            label = re.sub(r"[`*]", "", label)
            in_sec = any(w == label or label.startswith(w) or label.endswith(w)
                         for w in header_words)
            continue
        if not in_sec:
            continue
        m = _PORT_LINE_RE.match(ln)
        if m:
            name, cell = m.group(1), m.group(2)
        else:
            m2 = _PORT_LINE_NOWIDTH_RE.match(ln)
            if not m2:
                continue
            name, cell = m2.group(1), m2.group(2)
        if name.lower() in _NOT_A_PORT_NAME:
            continue
        w = _width_from_cell(cell, params)
        if w is None:
            if re.search(r"(?i)(clk|clock|rst|reset|_n$|_en$|enable|valid|ready|"
                         r"full|empty|push|pop|write|read|wen|ren|inc|overflow|"
                         r"underflow|count_?en|stop|start|load)", name):
                w = 1
            else:
                continue
        ports.append((name, w))
    return ports


def _dedup(ports: List[Port]) -> List[Port]:
    seen = set()
    out: List[Port] = []
    for n, w in ports:
        if n in seen:
            continue
        seen.add(n)
        out.append((n, w))
    return out


def _interface(prompt: str) -> Optional[Tuple[List[Port], List[Port], Dict[str, int]]]:
    params = _param_defaults(prompt)
    ins = _dedup(_section_ports(
        prompt, ("inputs", "input ports", "input port", "input"), params))
    outs = _dedup(_section_ports(
        prompt, ("outputs", "output ports", "output port", "output"), params))
    if ins and outs:
        return ins, outs, params
    return None


# --------------------------------------------------------------------------- #
# role resolution helpers (chip-AGNOSTIC: by name CONVENTION, never a design name)
# --------------------------------------------------------------------------- #
def _find(ports: List[Port], *names) -> Optional[Port]:
    low = {n.lower(): (n, w) for n, w in ports}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


def _find_re(ports: List[Port], pattern: str,
             width=None) -> Optional[Port]:
    rx = re.compile(pattern, re.I)
    for n, w in ports:
        if width is not None and not width(w):
            continue
        if rx.search(n):
            return (n, w)
    return None


def _clk(ins):
    return _find_re(ins, r"^(i_|w_|r_)?cl(?:k|ock)(_in)?$") or _find(ins, "clk", "clock")


def _rst(ins):
    return _find_re(ins, r"(rst|reset|areset|clr|clear)")


def _depth(prompt: str, params: Dict[str, int]) -> Optional[int]:
    """Resolve the array DEPTH (number of entries). Either a STATED literal DEPTH /
    FILO_DEPTH / 'depth of N' / '2^ADDR_WIDTH', or None (=> SKIP)."""
    # the *_DEPTH parameter default already resolved by _param_defaults wins first.
    for pkey in ("DEPTH", "FILO_DEPTH", "FIFO_DEPTH", "LIFO_DEPTH", "STACK_DEPTH",
                 "MEM_DEPTH", "RAM_DEPTH", "BUFFER_DEPTH", "NUM_ENTRIES", "ENTRIES"):
        if pkey in params:
            return params[pkey]
    low = prompt.lower()
    # `2^{ADDR_WIDTH}` / `2**ADDR_WIDTH` / "depth is 2^ADDR_WIDTH"
    m = re.search(r"2\s*[\^*]{1,2}\s*\{?\s*`?([A-Za-z_]\w*)`?\s*\}?", prompt)
    if m and m.group(1) in params:
        return 1 << params[m.group(1)]
    # an inline literal: `depth of N` / `DEPTH = N`
    m = re.search(r"\b(?:filo_|lifo_|fifo_|stack_|mem_|ram_|buffer_)?depth\b\s*"
                  r"(?:\([^)]*\)\s*)?(?:default\s*(?:value)?\s*(?:is|=|of)?\s*)?"
                  r"(?:of\s+|=\s*)?`?(\d+)`?", low)
    if m and m.group(1):
        return int(m.group(1))
    # an explicit "hold up to N entries" / "store up to N words" phrasing
    m = re.search(r"(?:hold\s+up\s+to|up\s+to|store\s+up\s+to)\s+(\d+)\s*"
                  r"(?:entries|elements|words|locations|data)", low)
    if m:
        return int(m.group(1))
    return None


def _addr_width(depth: int) -> int:
    return max(1, (depth - 1).bit_length()) if depth > 1 else 1


def _active_low(rst_name: str, prompt: str) -> bool:
    low = prompt.lower()
    return (rst_name.lower().endswith("_n") or rst_name.lower() in ("resetn", "rstn")
            or bool(re.search(r"active[- ]low\s+(?:asynchronous\s+)?reset", low))
            or bool(re.search(rf"{re.escape(rst_name)}[^.\n]{{0,40}}active[- ]low",
                              low)))


def _async_reset(rst_name: str, prompt: str) -> bool:
    low = prompt.lower()
    return (bool(re.search(r"areset", rst_name, re.I))
            or bool(re.search(
                r"asynchronous(?:\s+active[- ]\w+)?\s+reset|async\s+reset|"
                r"reset[^.\n]{0,40}asynchronous", low)))


def _decl(direction: str, name: str, width: int, reg=False) -> str:
    kw = f"{direction} reg" if reg else direction
    return f"{kw} [{width-1}:0] {name}" if width > 1 else f"{kw} {name}"


def _w_hi(wexpr) -> str:
    """High bit of a width that may be an int (literal) or a `NAME` parameter id."""
    return f"{wexpr}-1" if isinstance(wexpr, str) else str(int(wexpr) - 1)


def _decl_sym(direction: str, name: str, wexpr, reg=False) -> str:
    """Like _decl but the width may be a PARAMETER identifier (symbolic), so the
    emitted port is `[DATA_WIDTH-1:0]` (overridable) rather than a baked literal."""
    if isinstance(wexpr, str):
        kw = f"{direction} reg" if reg else direction
        return f"{kw} [{wexpr}-1:0] {name}"
    return _decl(direction, name, int(wexpr), reg=reg)


# Width parameter names this dataset uses (NOT the address/depth params).
_WIDTH_PARAM_RE = re.compile(r"(?:^|_)(?:DATA_)?WIDTH$|^WIDTH$|DWIDTH$|_DW$", re.I)
# Depth-by-entries vs depth-by-address-bits parameter names.
_DEPTH_PARAM_NAMES = ("DEPTH", "FILO_DEPTH", "FIFO_DEPTH", "LIFO_DEPTH",
                      "STACK_DEPTH", "MEM_DEPTH", "RAM_DEPTH", "BUFFER_DEPTH",
                      "NUM_ENTRIES", "ENTRIES")


def _lifo_param_decls(prompt: str, params: Dict[str, int], W: int,
                      depth: int):
    """Resolve the SPEC'S OWN parameter names so the emit is a genuinely
    parameterized module the harness can `-P<top>.NAME=...` override.

    Returns (param_decl_lines, width_expr, depth_expr):
      * param_decl_lines : ["parameter DATA_WIDTH = 8", "parameter FILO_DEPTH = 16"]
      * width_expr       : "DATA_WIDTH" (str, symbolic) or W (int, when no width param)
      * depth_expr       : "FILO_DEPTH" / "(1 << ADDR_WIDTH)" / str(depth)
    GENERAL — every value read from the parsed param defaults; never invented."""
    decls: List[str] = []

    # --- width parameter: a *WIDTH param whose default == the resolved data width.
    width_name = None
    for nm, val in params.items():
        if _WIDTH_PARAM_RE.search(nm) and val == W:
            width_name = nm
            break
    if width_name is None:  # accept any param named exactly DATA_WIDTH even if W parse differs
        for nm in ("DATA_WIDTH", "WIDTH", "DWIDTH"):
            if nm in params:
                width_name = nm
                break
    if width_name is not None:
        decls.append(f"parameter {width_name} = {params[width_name]}")
        width_expr = width_name
    else:
        width_expr = W

    # --- depth: prefer an explicit *_DEPTH entry-count param; else 2**ADDR_WIDTH.
    #     Exclude the already-chosen width_name from address candidacy so a single
    #     param that matched BOTH (e.g. a spec that names only `ADDR_WIDTH` and whose
    #     default happens to equal W) is never declared twice (a duplicate `parameter`
    #     is an iverilog error). The width binding wins; depth then falls back to the
    #     literal. The final dedupe below is the airtight backstop.
    depth_param = next((nm for nm in _DEPTH_PARAM_NAMES
                        if nm in params and nm != width_name), None)
    addr_param = None
    if depth_param is None:
        # 2^{ADDR_WIDTH} form — declare ADDR_WIDTH, depth = (1 << ADDR_WIDTH)
        m = re.search(r"2\s*[\^*]{1,2}\s*\{?\s*`?([A-Za-z_]\w*)`?\s*\}?", prompt)
        if m and m.group(1) in params and m.group(1) != width_name:
            addr_param = m.group(1)
    if depth_param is not None:
        decls.append(f"parameter {depth_param} = {params[depth_param]}")
        depth_expr = depth_param
    elif addr_param is not None:
        decls.append(f"parameter {addr_param} = {params[addr_param]}")
        depth_expr = f"(1 << {addr_param})"
    else:
        depth_expr = str(depth)  # literal-only depth (no param stated) — still valid

    # Backstop: never emit the same `parameter NAME` twice (a duplicate decl is an
    # iverilog compile error), preserving first-seen order.
    seen, deduped = set(), []
    for d in decls:
        key = d.split("=", 1)[0].strip()
        if key not in seen:
            seen.add(key)
            deduped.append(d)
    decls = deduped
    return decls, width_expr, depth_expr


# --------------------------------------------------------------------------- #
# §4.05 up-front SKIP cues (composite / extra-feature / async-CDC).
# --------------------------------------------------------------------------- #
# A memory that is one block inside a larger composite controller.
_COMPOSITE_RE = re.compile(
    r"""(?xi)
      \baxi\b | \baxi-?lite\b | \baxi-?stream\b | \baxis\b | \bapb\b | \bahb\b |
      \bwishbone\b | \bavalon\b | \btilelink\b | \buart\b | \bspi\b | \bi2c\b |
      \bjtag\b | \bpcie\b | \busb\b | \bsdram\b | \bddr\b |
      \bcache\b | \bmshr\b | \btlb\b | \bsequencer\b | \bmicrocode\b |
      \bprocessor\b | \bcpu\b | \bpipeline\s+stage | \bload[-\s]?store\b |
      \bping[-\s]?pong\b | \bskid\b | \bhuffman\b | \bperceptron\b | \bhebbian\b |
      \bsprite\b | \bvga\b | \brgb2ycbcr\b | \bbranch\s+predict
    """,
)
# Extra-feature variants the bare primitive does not cover.
_EXTRA_FEATURE_RE = re.compile(
    r"""(?xi)
      \bbist\b | \bbuilt[-\s]?in\s+self[-\s]?test\b |
      \bclock[-\s]?gat | \bgated[-\s]?clock\b | \bgated_clk\b |
      \bcollision\s+detect | \berror[-\s]?code\b | \bparity\b
    """,
)
# Async / dual-clock / gray-pointer FIFO cues — SKIP unless the gray-pointer CDC is
# explicitly + fully stated (gray-code conversion AND a multi-flop synchronizer).
# NOTE: a bare "asynchronous reset" is a single-clock design detail, NOT a dual-clock
# FIFO — the async cue must be tied to the CLOCK / domain / operation, never to the
# RESET. So `async(hronous)` only fires when it modifies clock/operation/read/write/
# FIFO/buffer, and an explicit asynchronous-RESET phrase is excluded.
_ASYNC_FIFO_RE = re.compile(
    r"""(?xi)
      dual[-\s]?clock | two\s+clock\s+domain | \bcdc\b |
      clock\s+domain\s+crossing |
      \basync(?:hronous)?\s+(?:fifo|filo|buffer|clock|operation|write|read|
        and\s+simultaneous|domain) |
      (?:fifo|filo|buffer)[^.\n]{0,30}\basync(?:hronous)? |
      (?:w_?clk|wr_?clk|wclk)\b[^.\n]{0,40}\b(?:r_?clk|rd_?clk|rclk)\b |
      (?:r_?clk|rd_?clk|rclk)\b[^.\n]{0,40}\b(?:w_?clk|wr_?clk|wclk)\b
    """,
)
# An asynchronous *reset* phrase that must NOT be read as an async-CDC FIFO cue.
_ASYNC_RESET_PHRASE_RE = re.compile(
    r"(?i)asynchronous(?:\s+active[-\s]?\w+)?\s+reset")


def _async_fifo_cue(prompt: str) -> bool:
    """True only for a genuine dual-clock / async-CDC FIFO cue — NOT for a plain
    asynchronous-reset single-clock design."""
    # strip async-reset phrases first so 'Asynchronous ... reset' never fires.
    scrubbed = _ASYNC_RESET_PHRASE_RE.sub(" ", prompt)
    return bool(_ASYNC_FIFO_RE.search(scrubbed))


def _gray_cdc_fully_stated(prompt: str) -> bool:
    """An async FIFO is solvable ONLY if BOTH the gray-code pointer encoding AND a
    multi-flop pointer synchronizer are explicitly stated. Anything less -> not
    fully pinned -> SKIP (return False)."""
    low = prompt.lower()
    has_gray = bool(re.search(r"gray[-\s]?code|gray\s+pointer|binary[-\s]?to[-\s]?gray",
                              low))
    has_sync = bool(re.search(
        r"(?:two|2|double|multi)[-\s]?(?:flop|stage|ff)\s+synchroniz|"
        r"pointer\s+synchroniz|synchroniz[^.\n]{0,30}pointer", low))
    return has_gray and has_sync


def _is_modify_task(record: dict) -> bool:
    ic = (record.get("input") or {}).get("context")
    return isinstance(ic, dict) and any(
        isinstance(v, str) and v.strip() for v in ic.values())


# =========================================================================== #
# FAMILY 1 — synchronous FIFO (single-clock circular buffer, full/empty)
# =========================================================================== #
def _try_sync_fifo(prompt: str, ins, outs, params, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"\bfifo\b|first[-\s]?in[-\s]?first[-\s]?out|circular\s+buffer", low):
        return None
    # §4.05: an ASYNC / dual-clock / gray-pointer FIFO must be FULLY pinned; else SKIP.
    if _async_fifo_cue(prompt) and not _gray_cdc_fully_stated(prompt):
        return None

    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    # A truly async FIFO has two distinct clocks — never single-emit here.
    clks = [p for p in ins if re.search(r"cl(?:k|ock)", p[0], re.I)]
    if len(clks) > 1:
        return None

    # write-side: enable + data-in; read-side: enable; data-out + full + empty.
    # Anchored so a write-side name (wr_en) can NEVER be mis-claimed by the read
    # regex (a bare `ren` would substring-match `wr_en`); each role is word-bounded.
    wen = _find_re(ins, r"^(wr_?en|write_?en|w_?inc|wen|w_en|push|we)$|^wr$",
                   width=lambda w: w == 1)
    ren = _find_re(ins, r"^(rd_?en|read_?en|r_?inc|ren|r_en|pop|re)$|^rd$",
                   width=lambda w: w == 1)
    if wen is not None and ren is not None and wen[0] == ren[0]:
        return None
    din = _find_re(ins, r"(w_?data|wr_?data|write_?data|data_?in|din|push_?data)",
                   width=lambda w: w > 1)
    dout = _find_re(outs, r"(r_?data|rd_?data|read_?data|data_?out|dout|pop_?data)",
                    width=lambda w: w > 1)
    full = _find_re(outs, r"full", width=lambda w: w == 1)
    empty = _find_re(outs, r"empty", width=lambda w: w == 1)
    if None in (wen, ren, din, dout, full, empty):
        return None
    if din[1] != dout[1]:
        return None
    W = din[1]
    depth = _depth(prompt, params)
    if depth is None or depth < 2:
        return None

    clk_n, rst_n = clk[0], rst[0]
    wen_n, ren_n = wen[0], ren[0]
    din_n, dout_n = din[0], dout[0]
    full_n, empty_n = full[0], empty[0]
    # an optional element-count output (data-count), sized to count 0..depth.
    cnt = _find_re(outs, r"(count|data_?count|fill|occupancy|num_?entries|level)",
                   width=lambda w: w > 1)
    cw = max(1, depth.bit_length())  # bits to represent 0..depth inclusive
    aw = _addr_width(depth)

    active_low = _active_low(rst_n, prompt)
    async_rst = _async_reset(rst_n, prompt)
    rst_test = f"!{rst_n}" if active_low else rst_n
    sens = f"posedge {clk_n}"
    if async_rst:
        sens += f", {'negedge' if active_low else 'posedge'} {rst_n}"

    ports = [_decl("input", clk_n, 1), _decl("input", rst_n, 1),
             _decl("input", wen_n, 1), _decl("input", ren_n, 1),
             _decl("input", din_n, W),
             _decl("output", dout_n, W, reg=True),
             _decl("output", full_n, 1), _decl("output", empty_n, 1)]
    if cnt:
        ports.append(_decl("output", cnt[0], cnt[1], reg=True))

    lines = [
        "// program-SOLVED synchronous circular-buffer FIFO "
        "(stated depth/width, full/empty flags); deterministic, no AI.",
        f"module {top} (",
        "    " + ",\n    ".join(ports),
        ");",
        f"    localparam DEPTH = {depth};",
        f"    reg [{W-1}:0] mem [0:DEPTH-1];",
        f"    reg [{aw}:0] wr_ptr;",
        f"    reg [{aw}:0] rd_ptr;",
        f"    reg [{cw}:0] count;",
        f"    wire do_wr = {wen_n} && !{full_n};",
        f"    wire do_rd = {ren_n} && !{empty_n};",
        f"    assign {full_n}  = (count == DEPTH);",
        f"    assign {empty_n} = (count == 0);",
        f"    always @({sens}) begin",
        f"        if ({rst_test}) begin",
        "            wr_ptr <= 0;",
        "            rd_ptr <= 0;",
        "            count  <= 0;",
        f"            {dout_n} <= 0;",
    ]
    if cnt:
        lines.append(f"            {cnt[0]} <= 0;")
    lines += [
        "        end else begin",
        "            if (do_wr) begin",
        f"                mem[wr_ptr[{aw-1}:0]] <= {din_n};",
        "                wr_ptr <= (wr_ptr == DEPTH-1) ? 0 : wr_ptr + 1;",
        "            end",
        "            if (do_rd) begin",
        f"                {dout_n} <= mem[rd_ptr[{aw-1}:0]];",
        "                rd_ptr <= (rd_ptr == DEPTH-1) ? 0 : rd_ptr + 1;",
        "            end",
        "            case ({do_wr, do_rd})",
        "                2'b10: count <= count + 1;",
        "                2'b01: count <= count - 1;",
        "                default: count <= count;",
        "            endcase",
    ]
    if cnt:
        lines.append(f"            {cnt[0]} <= count + (do_wr ? 1 : 0) - (do_rd ? 1 : 0);")
    lines += ["        end", "    end", "endmodule", ""]
    return "\n".join(lines)


# =========================================================================== #
# FAMILY 2 — LIFO / stack (push/pop, full/empty, combinational top read)
# =========================================================================== #
def _try_lifo(prompt: str, ins, outs, params, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"\blifo\b|\bfilo\b|\bstack\b|last[-\s]?in[-\s]?first[-\s]?out|"
                     r"first[-\s]?in[-\s]?last[-\s]?out", low):
        return None
    # §4.05: an ASYNC / dual-clock stack must be fully pinned (it never is) -> SKIP.
    if _async_fifo_cue(prompt):
        return None

    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    clks = [p for p in ins if re.search(r"cl(?:k|ock)", p[0], re.I)]
    if len(clks) > 1:
        return None

    # Anchored so write-side (wr_en) and read-side (rd_en) names can't cross-claim.
    push = _find_re(ins, r"^(push|wr_?en|write_?en|wen|w_en|we|w_inc)$",
                    width=lambda w: w == 1)
    pop = _find_re(ins, r"^(pop|rd_?en|read_?en|ren|r_en|re|r_inc)$",
                   width=lambda w: w == 1)
    if push is not None and pop is not None and push[0] == pop[0]:
        return None
    din = _find_re(ins, r"(data_?in|din|push_?data|w_?data|wr_?data)",
                   width=lambda w: w > 1)
    dout = _find_re(outs, r"(data_?out|dout|pop_?data|r_?data|rd_?data)",
                    width=lambda w: w > 1)
    full = _find_re(outs, r"full", width=lambda w: w == 1)
    empty = _find_re(outs, r"empty", width=lambda w: w == 1)
    if None in (push, pop, din, dout, full, empty):
        return None
    if din[1] != dout[1]:
        return None
    W = din[1]
    depth = _depth(prompt, params)
    if depth is None or depth < 2:
        return None

    clk_n, rst_n = clk[0], rst[0]
    push_n, pop_n = push[0], pop[0]
    din_n, dout_n = din[0], dout[0]
    full_n, empty_n = full[0], empty[0]

    active_low = _active_low(rst_n, prompt)
    async_rst = _async_reset(rst_n, prompt)
    rst_test = f"!{rst_n}" if active_low else rst_n
    sens = f"posedge {clk_n}"
    if async_rst:
        sens += f", {'negedge' if active_low else 'posedge'} {rst_n}"
    # feedthrough: push+pop simultaneously on an empty stack passes data straight
    # through (stated for the CVDP FILO). Only emitted when explicitly stated.
    feedthrough = bool(re.search(r"feed[-\s]?through", low))

    # GENERAL parameterization (§9 GENERAL-not-OVERFIT): the cocotb harness drives
    # this module with `-P<top>.DATA_WIDTH=...` / `-P<top>.FILO_DEPTH=...` /
    # `-P<top>.ADDR_WIDTH=...` overrides, so the emit MUST declare those parameters
    # (a literal-baked width/depth has nothing to override -> iverilog compile fail).
    # Resolve the spec's OWN parameter NAMES; never invent a width/depth constant.
    pblock, wexpr, depth_expr = _lifo_param_decls(prompt, params, W, depth)

    ports = [_decl_sym("input", din_n, wexpr), _decl("input", push_n, 1),
             _decl("input", pop_n, 1), _decl("input", rst_n, 1),
             _decl("input", clk_n, 1),
             _decl_sym("output", dout_n, wexpr, reg=True),
             _decl("output", full_n, 1, reg=True),
             _decl("output", empty_n, 1, reg=True)]
    head = f"module {top} (" if not pblock else (
        f"module {top} #(\n    " + ",\n    ".join(pblock) + "\n) (")
    lines = [
        "// program-SOLVED synchronous LIFO/stack "
        "(stated depth/width, push/pop, full/empty); deterministic, no AI.",
        head,
        "    " + ",\n    ".join(ports),
        ");",
        # When the spec ALREADY declares a `DEPTH` parameter, depth_expr is the
        # bare name "DEPTH"; re-declaring `localparam DEPTH = DEPTH` collides with
        # that parameter (iverilog: "DEPTH has already been declared") — use the
        # parameter directly. Only alias to a local `DEPTH` for a differently
        # named / derived depth (e.g. FILO_DEPTH, `(1 << ADDR_WIDTH)`).
        (f"    localparam DEPTH = {depth_expr};" if depth_expr != "DEPTH"
         else "    // DEPTH is a module parameter (declared above), used directly"),
        "    localparam AW = $clog2(DEPTH);",
        f"    reg [{_w_hi(wexpr)}:0] mem [0:DEPTH-1];",
        "    reg [AW:0] sp;",  # stack pointer / count = number of valid entries (0..DEPTH)
        # DECREMENT THEN TRUNCATE. `sp` is [AW:0] — one bit wider than the
        # address — so it can represent the full count DEPTH. Writing
        # `sp[AW-1:0] - 1'b1` truncates FIRST, and on a FULL stack
        # (sp == DEPTH, e.g. 4'b1000) that leaves 3'b000 and then subtracts 1,
        # which only reaches the top entry if the subtraction wraps inside AW
        # bits. Whether it does is NOT ours to decide: an array index is a
        # SELF-DETERMINED expression, so its evaluation width is the simulator's
        # call. Icarus 11 evaluates it wider, `0 - 1` is -1, and mem[-1] reads X
        # (#1415); Icarus 13/14 wrap and read the right entry. Computing
        # `sp - 1'b1` in an assignment whose context width spans sp's own [AW:0]
        # gives 8 - 1 = 7 BEFORE the narrowing — one value, every simulator, and
        # right for every sp in 1..DEPTH.
        "    wire [AW-1:0] top_idx = sp - 1'b1;",
        f"    wire do_push = {push_n} && !{full_n};",
        f"    wire do_pop  = {pop_n} && !{empty_n};",
        f"    always @({sens}) begin",
        f"        if ({rst_test}) begin",
        "            sp <= 0;",
        f"            {dout_n} <= 0;",
        f"            {full_n} <= 1'b0;",
        f"            {empty_n} <= 1'b1;",
        "        end else begin",
    ]
    if feedthrough:
        lines += [
            f"            if (({push_n} && {pop_n}) && ({empty_n} == 1'b1)) begin",
            f"                {dout_n} <= {din_n};",  # feedthrough: pass straight out
            "            end else if (do_push && !do_pop) begin",
        ]
    else:
        lines += [
            "            if (do_push && !do_pop) begin",
        ]
    lines += [
        f"                mem[sp[AW-1:0]] <= {din_n};",
        "                sp <= sp + 1;",
        "            end else if (do_pop && !do_push) begin",
        f"                {dout_n} <= mem[top_idx];",
        "                sp <= sp - 1;",
        "            end else if (do_push && do_pop) begin",
        # simultaneous push+pop on a non-empty stack: replace the top element.
        f"                mem[top_idx] <= {din_n};",
        f"                {dout_n} <= mem[top_idx];",
        "            end",
        "            // flags reflect the post-update occupancy",
        f"            {empty_n} <= ((sp + (do_push && !do_pop ? 1 : 0)"
        f" - (do_pop && !do_push ? 1 : 0)) == 0);",
        f"            {full_n}  <= ((sp + (do_push && !do_pop ? 1 : 0)"
        f" - (do_pop && !do_push ? 1 : 0)) == DEPTH);",
        "        end",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# =========================================================================== #
# FAMILY 3 — single- / dual-port RAM (depth/width parsed, sync or async read)
# =========================================================================== #
def _try_ram(prompt: str, ins, outs, params, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"\bram\b|random[-\s]access\s+memory|register\s+array|"
                     r"\bmemory\s+array\b", low):
        return None
    if re.search(r"read[-\s]?only|\brom\b", low) and not re.search(r"\bram\b", low):
        return None  # a pure ROM -> _try_rom
    # exclude register file (handled separately by name + multi-read-port shape)
    if re.search(r"register\s+file|regfile", low):
        return None

    clk = _clk(ins)
    if clk is None:
        return None
    W = None
    for pkey in ("DATA_WIDTH", "WIDTH", "DWIDTH"):
        if pkey in params:
            W = params[pkey]
            break
    depth = _depth(prompt, params)
    wdata = _find_re(ins, r"(write_?data|wr_?data|w_?data|data_?in|din|wdata)",
                     width=lambda w: w > 1)
    rdata = _find_re(outs, r"(read_?data|rd_?data|r_?data|data_?out|dout|rdata|q)",
                     width=lambda w: w > 1)
    if wdata is None or rdata is None:
        return None
    if W is None:
        W = wdata[1]
    if wdata[1] != W or rdata[1] != W:
        return None
    if depth is None or depth < 2:
        return None
    aw = _addr_width(depth)

    wen = _find_re(ins, r"(write_?en|wr_?en|wen|w_en|^we$|write$)",
                   width=lambda w: w == 1)
    waddr = _find_re(ins, r"(write_?addr|wr_?addr|w_?addr|waddr)")
    raddr = _find_re(ins, r"(read_?addr|rd_?addr|r_?addr|raddr)")
    addr = _find_re(ins, r"(^addr$|^address$|^a$)")
    ren = _find_re(ins, r"(read_?en|rd_?en|ren|r_en|^re$|read$)",
                   width=lambda w: w == 1)
    rst = _rst(ins)

    # dual-port: distinct write_addr + read_addr; single-port: one shared addr.
    dual = waddr is not None and raddr is not None
    single = not dual and addr is not None
    if not (dual or single):
        return None
    if wen is None:
        return None

    sync_read = bool(re.search(
        r"synchronous\s+read|registered\s+read|read\s+is\s+synchronous|"
        r"read\s+data\s+is\s+registered|on\s+(?:the\s+)?(?:rising|clock)\s+edge"
        r"[^.\n]{0,60}read", low))
    async_read = bool(re.search(
        r"asynchronous\s+read|combinational\s+read|read\s+is\s+(?:asynchronous|"
        r"combinational)|read\s+data\s+is\s+available\s+(?:immediately|"
        r"combinational)", low))
    if sync_read == async_read:
        # neither (or both) clearly stated -> SKIP (never guess read timing).
        return None

    clk_n = clk[0]
    wdata_n, rdata_n = wdata[0], rdata[0]
    waddr_n = (waddr or addr)[0]
    raddr_n = (raddr or addr)[0]
    wen_n = wen[0]

    decls = [_decl("input", clk_n, 1)]
    if rst:
        decls.append(_decl("input", rst[0], 1))
    decls.append(_decl("input", wen_n, 1))
    if dual:
        decls.append(_decl("input", waddr_n, aw))
        decls.append(_decl("input", raddr_n, aw))
    else:
        decls.append(_decl("input", addr[0], aw))
    decls.append(_decl("input", wdata_n, W))
    if ren:
        decls.append(_decl("input", ren[0], 1))
    decls.append(_decl("output", rdata_n, W, reg=sync_read))

    lines = [
        f"// program-SOLVED {'dual' if dual else 'single'}-port RAM "
        f"({'sync' if sync_read else 'async'} read, stated depth/width); "
        "deterministic, no AI.",
        f"module {top} (",
        "    " + ",\n    ".join(decls),
        ");",
        f"    localparam DEPTH = {depth};",
        f"    reg [{W-1}:0] mem [0:DEPTH-1];",
        f"    always @(posedge {clk_n}) begin",
        f"        if ({wen_n}) mem[{waddr_n}] <= {wdata_n};",
        "    end",
    ]
    rd_guard = f"if ({ren[0]}) " if ren else ""
    if sync_read:
        lines += [
            f"    always @(posedge {clk_n}) begin",
            f"        {rd_guard}{rdata_n} <= mem[{raddr_n}];",
            "    end",
        ]
    else:
        lines += [f"    assign {rdata_n} = mem[{raddr_n}];"]
    lines += ["endmodule", ""]
    return "\n".join(lines)


# =========================================================================== #
# FAMILY 4 — ROM (stated contents table, address in, data out)
# =========================================================================== #
_HEX_LIT_RE = re.compile(r"(\d+)'h([0-9A-Fa-f_]+)")


def _try_rom(prompt: str, ins, outs, params, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"\brom\b|read[-\s]?only\s+memory", low):
        return None
    addr = _find_re(ins, r"(addr|address)")
    dout = _find_re(outs, r"(data_?out|dout|^q$|read_?data|rdata|data)",
                    width=lambda w: w > 1)
    if addr is None or dout is None:
        return None
    aw = addr[1]
    dw = dout[1]
    addr_n, dout_n = addr[0], dout[0]

    # Contents MUST be ENUMERATED. Two stated forms:
    #  (a) a "locations 0 through K" range + (K+1) hex literals of the data width;
    #  (b) an explicit "address A : value V" / "mem[A] = V" table.
    contents: Dict[int, int] = {}
    for m in re.finditer(r"(?:mem|rom|data)?\s*\[\s*(\d+)\s*\]\s*[:=]\s*"
                         r"(?:\d+'h)?([0-9A-Fa-f]+)", prompt):
        contents[int(m.group(1))] = int(m.group(2), 16)
    if not contents:
        for m in re.finditer(r"(?:address|addr|location)\s*`?(\d+)`?\s*[:=\-]\s*"
                             r"(?:\d+'h)?`?([0-9A-Fa-f]+)`?", prompt, re.I):
            contents[int(m.group(1))] = int(m.group(2), 16)
    if not contents:
        rng = re.search(r"locations?\s+(\d+)\s+through\s+(\d+)", prompt, re.I)
        lits = [(int(b), int(v.replace("_", ""), 16))
                for b, v in _HEX_LIT_RE.findall(prompt)]
        data_lits = [val for bits, val in lits if bits == dw]
        if rng and data_lits:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if hi - lo + 1 == len(data_lits):
                for i, val in enumerate(data_lits):
                    contents[lo + i] = val
    if not contents:
        return None  # §4.05: contents not enumerated -> never fabricate
    depth = 1 << aw
    if max(contents) >= depth:
        return None

    sync = bool(re.search(r"synchronous|registered|clocked|on\s+(?:the\s+)?"
                          r"(?:rising|clock)\s+edge", low))
    clk = _clk(ins)
    body = [f"// program-SOLVED ROM (stated contents table); deterministic, no AI.",
            f"module {top} ("]
    decls = []
    if sync and clk:
        decls.append(_decl("input", clk[0], 1))
    decls.append(_decl("input", addr_n, aw))
    decls.append(_decl("output", dout_n, dw, reg=True))
    body.append("    " + ",\n    ".join(decls))
    body.append(");")
    body.append(f"    reg [{dw-1}:0] mem [0:{depth-1}];")
    body.append("    integer i;")
    body.append("    initial begin")
    body.append(f"        for (i = 0; i < {depth}; i = i + 1) mem[i] = 0;")
    for a in sorted(contents):
        body.append(f"        mem[{a}] = {dw}'h{contents[a]:0{(dw+3)//4}X};")
    body.append("    end")
    if sync and clk:
        body.append(f"    always @(posedge {clk[0]}) {dout_n} <= mem[{addr_n}];")
    else:
        body.append(f"    always @(*) {dout_n} = mem[{addr_n}];")
    body.append("endmodule")
    body.append("")
    return "\n".join(body)


# =========================================================================== #
# FAMILY 5 — register file (#regs + #read/#write ports parsed, combinational read)
# =========================================================================== #
def _try_regfile(prompt: str, ins, outs, params, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"register\s+file|regfile", low):
        return None

    clk = _clk(ins)
    if clk is None:
        return None
    rst = _rst(ins)

    # number of registers (depth) + register width.
    nregs = _depth(prompt, params)
    if nregs is None:
        m = re.search(r"(\d+)\s*(?:general[-\s]?purpose\s+)?registers?\b", low)
        if m:
            nregs = int(m.group(1))
    if nregs is None or nregs < 2:
        return None
    aw = _addr_width(nregs)
    W = None
    for pkey in ("DATA_WIDTH", "WIDTH", "REG_WIDTH", "DWIDTH"):
        if pkey in params:
            W = params[pkey]
            break

    # write ports: (wen, waddr, wdata) triples. read ports: (raddr -> rdata) pairs.
    waddrs = [(n, w) for n, w in ins if re.search(r"(write_?addr|wr_?addr|w_?addr|"
                                                  r"waddr|wad)\d*", n, re.I)]
    wdatas = [(n, w) for n, w in ins if re.search(r"(write_?data|wr_?data|w_?data|"
                                                  r"wdata|din)\d*", n, re.I)]
    wens = [(n, w) for n, w in ins if re.search(r"(write_?en|wr_?en|wen|w_en)\d*",
                                                n, re.I)]
    raddrs = [(n, w) for n, w in ins if re.search(r"(read_?addr|rd_?addr|r_?addr|"
                                                 r"raddr|rad)\d*", n, re.I)]
    rdatas = [(n, w) for n, w in outs if re.search(r"(read_?data|rd_?data|r_?data|"
                                                  r"rdata|dout|q)\d*", n, re.I)]
    if not (waddrs and wdatas and raddrs and rdatas):
        return None
    # one write port and >=1 read port (the canonical NR-read / 1-write file).
    if len(waddrs) != 1 or len(wdatas) != 1 or len(wens) != 1:
        return None
    if len(raddrs) != len(rdatas):
        return None
    if W is None:
        W = wdatas[0][1]
    if wdatas[0][1] != W or any(w != W for _, w in rdatas):
        return None

    clk_n = clk[0]
    waddr_n, wdata_n, wen_n = waddrs[0][0], wdatas[0][0], wens[0][0]

    active_low = _active_low(rst[0], prompt) if rst else True
    async_rst = _async_reset(rst[0], prompt) if rst else False

    decls = [_decl("input", clk_n, 1)]
    if rst:
        decls.append(_decl("input", rst[0], 1))
    decls.append(_decl("input", wen_n, 1))
    decls.append(_decl("input", waddr_n, aw))
    decls.append(_decl("input", wdata_n, W))
    # pair read addr/data by their trailing index when present, else by order.
    def _idx(nm):
        m = re.search(r"(\d+)$", nm)
        return int(m.group(1)) if m else 0
    raddrs_s = sorted(raddrs, key=lambda p: _idx(p[0]))
    rdatas_s = sorted(rdatas, key=lambda p: _idx(p[0]))
    for (rn, _), (dn, _) in zip(raddrs_s, rdatas_s):
        decls.append(_decl("input", rn, aw))
    for (dn, _) in rdatas_s:
        decls.append(_decl("output", dn, W))

    lines = [
        f"// program-SOLVED register file ({len(rdatas)}-read/1-write, "
        f"{nregs} regs); deterministic, no AI.",
        f"module {top} (",
        "    " + ",\n    ".join(decls),
        ");",
        f"    reg [{W-1}:0] rf [0:{nregs-1}];",
        "    integer i;",
    ]
    if rst:
        rst_test = f"!{rst[0]}" if active_low else rst[0]
        sens = f"posedge {clk_n}"
        if async_rst:
            sens += f", {'negedge' if active_low else 'posedge'} {rst[0]}"
        lines += [
            f"    always @({sens}) begin",
            f"        if ({rst_test}) begin",
            f"            for (i = 0; i < {nregs}; i = i + 1) rf[i] <= 0;",
            f"        end else if ({wen_n}) begin",
            f"            rf[{waddr_n}] <= {wdata_n};",
            "        end",
            "    end",
        ]
    else:
        lines += [
            f"    always @(posedge {clk_n}) begin",
            f"        if ({wen_n}) rf[{waddr_n}] <= {wdata_n};",
            "    end",
        ]
    # combinational read ports.
    for (rn, _), (dn, _) in zip(raddrs_s, rdatas_s):
        lines.append(f"    assign {dn} = rf[{rn}];")
    lines += ["endmodule", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
_BUILDERS = (_try_sync_fifo, _try_lifo, _try_ram, _try_rom, _try_regfile)
_BUILDER_FAMILY = {
    "_try_sync_fifo": "sync_fifo",
    "_try_lifo": "lifo_stack",
    "_try_ram": "ram",
    "_try_rom": "rom",
    "_try_regfile": "register_file",
}


def solve(record: dict) -> Optional[str]:
    """Emit deterministic RTL (module named per the prompt/context) for a CVDP
    sync-FIFO / LIFO / RAM / ROM / register-file design, or None (SKIP) on ANY
    ambiguity / unstated governing fact / non-member / composite design."""
    if not isinstance(record, dict):
        return None
    top = _toplevel(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    # a "modify the existing RTL" task ships prior code in input['context'] -> SKIP.
    if _is_modify_task(record):
        return None
    # §4.05 up-front composite / extra-feature SKIP.
    if _COMPOSITE_RE.search(prompt) or _EXTRA_FEATURE_RE.search(prompt):
        return None

    iface = _interface(prompt)
    if not iface:
        return None
    ins, outs, params = iface
    for fn in _BUILDERS:
        try:
            rtl = fn(prompt, ins, outs, params, top)
        except Exception:
            rtl = None
        if rtl:
            return rtl
    return None


def family_of(record: dict) -> Optional[str]:
    """Reporting helper: the family name this record solves under, or None."""
    if not isinstance(record, dict):
        return None
    top = _toplevel(record) or "top"
    prompt = (record.get("input") or {}).get("prompt") or ""
    if _is_modify_task(record):
        return None
    if _COMPOSITE_RE.search(prompt) or _EXTRA_FEATURE_RE.search(prompt):
        return None
    iface = _interface(prompt)
    if not iface:
        return None
    ins, outs, params = iface
    for fn in _BUILDERS:
        try:
            if fn(prompt, ins, outs, params, top):
                return _BUILDER_FAMILY[fn.__name__]
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true", help="print emitted RTL")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n = 0
    fam: Dict[str, int] = {}
    ids: List[str] = []
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            k = family_of(r)
            fam[k] = fam.get(k, 0) + 1
            ids.append(f"{r.get('id')}[{k}]")
            if a.emit or a.id:
                print(f"=== {r.get('id')}  family={k} ===")
                print(rtl)
    print(f"solved={n}/{len(recs)}  families={fam}")
    for i in ids:
        print("  ", i)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
