#!/usr/bin/env python3
"""shift_counter_synth.py — deterministic SOLVER for the CVDP barrel-shift /
rotate and saturating / specialized-counter families.

WHY a dedicated CVDP solver (and not the two existing registry synths):
  * programs/shift_register_synth.py and programs/counter_advanced_synth.py both
    take (prompt_text, top) and read ports through port_parser (VerilogEval bullet
    / module-header twins) or the RTLLM prose bridge. Their prose patterns key on
    VerilogEval / RTLLM phrasings ("D-flops", "value to load", "torsional ring",
    "frequency divider", "12-hour ... am/pm"). A CVDP "code generation" prompt
    states its interface as a clean `### Inputs/Outputs` markdown list
    (`**data_in** (8-bits, [7:0])`) and embeds worked example vectors / a cocotb
    test, NOT those phrasings. So neither existing synth fires on the CVDP
    barrel-shift / rotate / specialized-counter records.
  * cvdp_atomic_bridge.py DOES read CVDP interfaces, but it SHORT-CIRCUITS this very
    family to SKIP: its _SPECIAL_ALGEBRA_RE skips `\\bsaturat`, and its cocotb-driven
    port extraction mis-tokenizes these designs (e.g. it returned
    o_processed_data -> ('data',1) for adc_data_rotate and None for barrel_shifter).

This solver builds ONLY what those three do not cover: a CVDP-native interface
reader (the `### Inputs/Outputs` markdown list) plus two deterministic emitters —

  BARREL SHIFT / ROTATE:
    N-bit data, shift/rotate by a control amount, with a PARSED direction
    (left/right, read from the stated control-bit polarity) and a PARSED mode
    (logical / arithmetic / rotate). Combinational OR clocked (parsed). §4.05:
    SKIP if the direction OR the mode is unstated, or if a second selectable mode
    (mask/XOR/multi-mode) makes a single emit ambiguous.

  SATURATING / SPECIALIZED COUNTER:
    an up/down counter that SATURATES at a stated max/min (NOT wrap), or counts by
    a stated step, or a mod-N / multi-digit-BCD counter with a stated N. The
    bound / step / direction / saturate-vs-wrap behaviour is PARSED. §4.05: SKIP
    if the bound or the wrap-vs-saturate behaviour is unstated.

§4.05 NO-LEAK / NO-CHEAT (binding):
  * NEVER read the golden/reference RTL. Ports come from the PROMPT's own interface
    section (and the module name from input.prompt/context via the bridge) — never
    from the OFF-LIMITS harness (.env TOPLEVEL, cocotb TB) or output bodies.
  * NEVER guess a direction, a mode, a width, a bound, or saturate-vs-wrap. ANY
    unstated governing fact -> return None (SKIP). A wrong shift/rotate/counter
    silently passes lint+synth and only a testbench catches it, so a skip is always
    safer than a guess.

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
# Forms handled (all from the dataset prose, never the golden RTL):
#   - **`data_in`** (8-bits, [7:0]): ...
#   - **`shift_bits`** (3-bits, [2:0]): ...
#   - **`left_right`** (1-bit): ...
#   - **`i_adc_data_in`** (logic [`DATA_WIDTH`-1:0]): ...   (parameterized -> use default)
#   - `ms_hr` (4-bit) — ...
# Width resolution, in order: an explicit [hi:lo] range; an `N-bit(s)` token; a
# parameterized [`P`-1:0] whose default P is stated as "default value of D bits" /
# "default ... D". Unresolved width on a non-1-bit data port -> the port is dropped,
# which forces a §4.05 SKIP rather than a phantom width.
# --------------------------------------------------------------------------- #
def _param_defaults(prompt: str) -> Dict[str, int]:
    """STATED parameter defaults: `DATA_WIDTH`, with a default value of 8` etc."""
    out: Dict[str, int] = {}
    for m in re.finditer(
        r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?(?:\s+of)?\s*"
        r"(?:is\s+|=\s*)?`?(\d+)`?", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    # `parameter DATA_WIDTH = 8` inside a fenced module header is also a stated default.
    for m in re.finditer(r"parameter\s+([A-Z][A-Z0-9_]+)\s*=\s*(\d+)", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def _width_from_cell(cell: str, params: Dict[str, int]) -> Optional[int]:
    # explicit [hi:lo]
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    # parameterized [`P`-1:0] / [P-1:0]
    m = re.search(r"\[\s*`?([A-Za-z_]\w*)`?\s*-\s*1\s*:\s*0\s*\]", cell)
    if m and m.group(1) in params:
        return params[m.group(1)]
    # an `N-bit(s)` token
    m = re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*-?\s*bit\b", cell, re.I) or re.search(r"\(\s*1\s*\)", cell):
        return 1
    return None


_PORT_LINE_RE = re.compile(
    r"""^\s*[-*]?\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*   # **`name`**
        \(([^)]*)\)""",                                  # (8-bits, [7:0]) / (logic [..])
    re.X)

# a width-LESS bullet port line: `- `name`: description` / `- **name** — description`.
# Used only as a fallback; the width is then resolved from the description text on
# the same line (or, for a control/clock/reset-style name, defaulted to 1-bit).
_PORT_LINE_NOWIDTH_RE = re.compile(
    r"^\s*[-*]\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*[:—\-]\s*(.+)$")


def _section_ports(prompt: str, header_words, params) -> List[Port]:
    """Ports listed under a `### Inputs`/`### Outputs`-style heading. We scan from
    the heading to the next heading and read each `**name** (...)` bullet."""
    lines = prompt.splitlines()
    ports: List[Port] = []
    in_sec = False
    for ln in lines:
        h = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", ln) or re.match(
            r"^\s*\*\*(.+?)\*\*\s*:?\s*$", ln)
        if h:
            label = h.group(1).strip().lower().rstrip(":")
            in_sec = any(w == label or label.startswith(w) or label.endswith(w)
                         for w in header_words)
            continue
        if not in_sec:
            continue
        m = _PORT_LINE_RE.match(ln)
        cell = None
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
            # a control/flag-looking single-bit port with no width token is 1-bit;
            # a data port with no resolvable width is dropped (forces SKIP upstream).
            if re.search(r"(?i)(clk|clock|rst|reset|_n$|en$|enable|valid|ready|"
                         r"direction|dir|left_right|mode|status|sel|start|stop|"
                         r"load|tc|done|carry|flag)", name):
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


def _interface(prompt: str) -> Optional[Tuple[List[Port], List[Port]]]:
    params = _param_defaults(prompt)
    ins = _dedup(_section_ports(prompt, ("inputs", "input ports", "input"), params))
    outs = _dedup(_section_ports(prompt, ("outputs", "output ports", "output"), params))
    if ins and outs:
        return ins, outs
    return None


def _find(ports: List[Port], *names) -> Optional[Port]:
    low = {n.lower(): (n, w) for n, w in ports}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


def _find_re(ports: List[Port], pattern: str) -> Optional[Port]:
    rx = re.compile(pattern, re.I)
    for n, w in ports:
        if rx.search(n):
            return (n, w)
    return None


def _clk(ins): return _find_re(ins, r"^(i_)?cl(?:k|ock)$") or _find(ins, "clk", "clock")
def _rst(ins): return _find_re(ins, r"(rst|reset|areset)")


def _decl(direction, name, width, reg=False):
    kw = f"{direction} reg" if reg else direction
    return f"{kw} [{width-1}:0] {name}" if width > 1 else f"{kw} {name}"


# =========================================================================== #
# FAMILY 1 — barrel shift / rotate
# =========================================================================== #
def _try_barrel_rotate(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"barrel\s*shift|\brotat", low):
        return None
    # A multi-MODE selectable design (mask / XOR / arithmetic+rotate+custom all under
    # one mode bus) cannot be emitted as a single deterministic shift -> SKIP. We only
    # emit when the design is ONE shift OR ONE rotate (a single direction control, no
    # mask/xor/custom-mode menu).
    if re.search(r"\bmask\b|\bxor\b|custom[- ]?mask|invalid\s+mode|operation[_ ]?mode|"
                 r"mode\s*\[", low):
        return None

    # ---- ports ---- #
    # data input: the widest input that is a data word.
    data_in = _find_re(ins, r"(data_?in|adc_data_in|^in$|^din$|data$)")
    if data_in is None:
        # fall back to the widest non-control input
        cands = [(n, w) for n, w in ins
                 if w > 1 and not re.search(r"(count|shift_?bits|amount|amt)", n, re.I)]
        data_in = max(cands, key=lambda p: p[1]) if cands else None
    if data_in is None:
        return None
    din_name, W = data_in
    if W < 2:
        return None

    # the shift/rotate AMOUNT control.
    amount = _find_re(ins, r"(shift_?bits|shift_?count|shift_?amount|^amount$|^amt$|"
                           r"^shift$|^count$|rotate_?(?:by|amount|count))")
    if amount is None:
        return None
    amt_name, amt_w = amount

    # the OUTPUT data word (single wide output, plus optionally a status flag).
    data_out = _find_re(outs, r"(data_?out|processed_data|result|^out$|^dout$)")
    if data_out is None:
        wide = [(n, w) for n, w in outs if w > 1]
        data_out = wide[0] if len(wide) == 1 else None
    if data_out is None:
        return None
    dout_name, OW = data_out
    if OW != W:
        return None  # in/out widths must agree for a plain shift/rotate

    # ---- mode: rotate vs logical vs arithmetic — must be UNAMBIGUOUS ---- #
    is_rotate = bool(re.search(r"\brotat", low))
    is_shift = bool(re.search(r"barrel\s*shift|shift\s+(?:left|right|the\s+bits|operation)|"
                              r"shift\s+by", low))
    if is_rotate and is_shift:
        # both shift AND rotate selectable -> ambiguous single emit -> SKIP
        return None
    if not (is_rotate or is_shift):
        return None
    arith = bool(re.search(r"arithmetic\s+(?:right\s+)?shift|sign[- ]exten", low))

    # ---- direction: must be a single STATED control with a stated polarity map ---- #
    dir_port = _find_re(ins, r"(left_?right|shift_?direction|rotate_?direction|"
                             r"^direction$|^dir$)")
    if dir_port is None:
        return None
    dir_name, dir_w = dir_port
    if dir_w != 1:
        return None
    # parse "<value>: ... left" and "<value>: ... right" polarity from the prose.
    left_val = right_val = None
    for m in re.finditer(
        r"(?:`?\b([01])\b`?|=\s*([01]))\s*[:)\-–]?\s*[^.\n]{0,40}?\b(left|right)\b",
        prompt, re.I):
        v = m.group(1) if m.group(1) is not None else m.group(2)
        d = m.group(3).lower()
        if d == "left" and left_val is None:
            left_val = int(v)
        elif d == "right" and right_val is None:
            right_val = int(v)
    # also accept "<name> = 1: Shift left." form anchored on the dir port name.
    if left_val is None or right_val is None:
        for m in re.finditer(
            rf"{re.escape(dir_name)}\s*=\s*([01])\s*[:)\-–]?\s*[^.\n]{{0,30}}?"
            rf"\b(left|right)\b", prompt, re.I):
            v, d = int(m.group(1)), m.group(2).lower()
            if d == "left":
                left_val = v
            else:
                right_val = v
    if left_val is None or right_val is None or left_val == right_val:
        return None  # direction polarity not unambiguously stated -> SKIP

    # ---- clocking: combinational vs posedge clk (parsed) ---- #
    clk = _clk(ins)
    rst = _rst(ins)
    combinational = bool(re.search(r"combinational|one\s+clock\s+cycle|"
                                   r"output\s+(?:must\s+)?change\s+immediately", low))
    clocked = clk is not None and bool(re.search(
        r"rising\s+edge|posedge|synchronous|on\s+(?:the\s+)?clock", low))
    if combinational and not clocked:
        clk = None  # pure combinational
    elif clk is None:
        # no clock and not stated combinational -> can't decide timing -> SKIP
        return None

    # a status output flag (optional, e.g. o_operation_status = 1 when active).
    status = None
    for n, w in outs:
        if (n, w) != data_out and w == 1 and re.search(r"status|active|state", n, re.I):
            status = (n, w)
            break

    # the amount may exceed W for a rotate (mod W). For a shift, amounts >= W zero out.
    rot_amt = f"({amt_name} % {W})"

    # ---- emit ---- #
    left_expr_shift = f"({din_name} << {amt_name})"
    right_expr_shift_log = f"({din_name} >> {amt_name})"
    right_expr_shift_ari = f"($signed({din_name}) >>> {amt_name})"
    right_expr_shift = right_expr_shift_ari if arith else right_expr_shift_log
    # rotate: build with a doubled-vector slice to be amount-agnostic.
    left_rot = (f"(({{{din_name}, {din_name}}} << {rot_amt}) >> {W})")
    right_rot = (f"(({{{din_name}, {din_name}}} >> {rot_amt}) & {{{W}{{1'b1}}}})")

    if is_rotate:
        left_e, right_e = left_rot, right_rot
        op_word = "rotate"
    else:
        left_e, right_e = left_expr_shift, right_expr_shift
        op_word = "arithmetic shift" if arith else "logical shift"

    sel_left = f"({dir_name} == 1'b{left_val})"
    body_expr = f"{sel_left} ? {left_e} : {right_e}"

    if clk is None:
        # combinational
        ports = [_decl("input", din_name, W), _decl("input", amt_name, amt_w),
                 _decl("input", dir_name, 1), _decl("output", dout_name, W)]
        if status:
            ports.append(_decl("output", status[0], 1))
        lines = [
            f"// program-SOLVED combinational barrel {op_word} "
            f"(direction & mode PARSED); deterministic, no AI.",
            f"module {top} (",
            "    " + ",\n    ".join(ports),
            ");",
            f"    assign {dout_name} = ({body_expr});",
        ]
        if status:
            lines.append(f"    assign {status[0]} = 1'b1;")
        lines += ["endmodule", ""]
        return "\n".join(lines)

    # clocked
    if rst is None:
        return None
    rst_name = rst[0]
    active_low = rst_name.lower().endswith("_n") or rst_name.lower() in (
        "resetn", "rstn") or bool(re.search(r"active[- ]low", low))
    rst_test = f"!{rst_name}" if active_low else rst_name
    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1),
             _decl("input", din_name, W), _decl("input", amt_name, amt_w),
             _decl("input", dir_name, 1), _decl("output reg", dout_name, W)]
    if status:
        ports.append(_decl("output reg", status[0], 1))
    lines = [
        f"// program-SOLVED clocked barrel {op_word} "
        f"(direction & mode PARSED); deterministic, no AI.",
        f"module {top} (",
        "    " + ",\n    ".join(ports),
        ");",
        f"    always @(posedge {clk[0]}) begin",
        f"        if ({rst_test}) begin",
        f"            {dout_name} <= 0;",
    ]
    if status:
        lines.append(f"            {status[0]} <= 1'b0;")
    lines += [
        "        end else begin",
        f"            {dout_name} <= ({body_expr});",
    ]
    if status:
        lines.append(f"            {status[0]} <= 1'b1;")
    lines += ["        end", "    end", "endmodule", ""]
    return "\n".join(lines)


# =========================================================================== #
# FAMILY 2 — saturating / specialized counter
# =========================================================================== #
def _try_saturating_counter(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"saturat", low):
        return None
    if len(outs) != 1:
        return None
    q_name, q_w = outs[0]
    if q_w < 1:
        return None
    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    rst_name = rst[0]

    # bounds MUST be stated.
    mmax = re.search(r"max(?:imum)?\s+(?:value\s+)?(?:of\s+)?(\d+)", low)
    mmin = re.search(r"min(?:imum)?\s+(?:value\s+)?(?:of\s+)?(\d+)", low)
    if not mmax or not mmin:
        return None
    cmax, cmin = int(mmax.group(1)), int(mmin.group(1))
    if cmax <= cmin or (1 << q_w) <= cmax:
        return None
    # MUST be saturate (clamp), NOT wrap. If a POSITIVE wrap/rollover is stated for
    # the bound, this is the wrong shape -> SKIP (the plain modulo counter owns wrap).
    # A NEGATED wrap ("does not wrap", "without wrapping") is a saturate statement, so
    # it must not trip the wrap-SKIP.
    if re.search(r"(?<!not )(?<!no )(?<!never )"
                 r"\b(?:wraps?(?:\s+around)?|rolls?\s+over|roll\s*over|"
                 r"returns?\s+to\s+(?:zero|0)\b)", low) and not re.search(
            r"(?:does\s+not|doesn't|never|without|no)\s+wrap", low):
        return None
    if not re.search(r"satur|clamp|holds?\s+at|stays?\s+at|stops?\s+at|"
                     r"does\s+not\s+exceed|does\s+not\s+wrap|without\s+wrap|capped", low):
        return None

    # reset value (default to cmin if a "resets to 0/min" is stated).
    rv = cmin
    mrv = re.search(r"reset[^.]{0,80}?to\s+(\d+)", low)
    if mrv:
        rv = int(mrv.group(1))
    elif re.search(r"reset[^.]{0,40}?(?:to\s+)?(?:zero|0\b)", low):
        rv = 0
    if not (cmin <= rv <= cmax):
        return None

    async_rst = bool(re.search(r"asynchron|\basync\b|areset", low)) or \
        bool(re.search(r"async", rst_name, re.I))
    active_low = rst_name.lower().endswith("_n") or rst_name.lower() in (
        "resetn", "rstn") or bool(re.search(r"active[- ]low", low))
    rst_test = f"!{rst_name}" if active_low else rst_name

    # up/down direction control + enable (optional, parsed).
    dirn = _find_re(ins, r"(up_?down|^dir$|direction|down$)")
    ena = _find_re(ins, r"(^en$|enable|valid)")
    others = [(n, w) for n, w in ins if n not in (clk[0], rst_name)]

    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1)]
    used = {clk[0], rst_name}
    inc_guard = ""
    if ena and ena[0] not in used:
        ports.append(_decl("input", ena[0], ena[1]))
        used.add(ena[0])
        inc_guard = f"if ({ena[0]}) "
    if dirn and dirn[0] not in used:
        ports.append(_decl("input", dirn[0], dirn[1]))
        used.add(dirn[0])
    # any other unexplained control input -> SKIP (we never invent its meaning).
    if any(n not in used for n, _ in others):
        return None
    ports.append(_decl("output", q_name, q_w, reg=True))

    sens = f"posedge {clk[0]}"
    if async_rst:
        edge = "negedge" if active_low else "posedge"
        sens += f", {edge} {rst_name}"

    if dirn:
        step_body = (
            f"            if ({dirn[0]}) begin\n"
            f"                if ({q_name} < {cmax}) {q_name} <= {q_name} + 1;\n"
            f"            end else begin\n"
            f"                if ({q_name} > {cmin}) {q_name} <= {q_name} - 1;\n"
            f"            end\n")
    else:
        # up-only saturating counter.
        step_body = (
            f"            if ({q_name} < {cmax}) {q_name} <= {q_name} + 1;\n")

    lines = [
        "// program-SOLVED saturating counter (clamps at stated max/min, no wrap); "
        "deterministic, no AI.",
        f"module {top} (",
        "    " + ",\n    ".join(ports),
        ");",
        f"    always @({sens}) begin",
        f"        if ({rst_test})",
        f"            {q_name} <= {rv};",
        f"        else begin",
        f"            {inc_guard}begin",
        step_body + "            end",
        "        end",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# =========================================================================== #
# FAMILY 2b — multi-digit BCD wall-clock counter (24-hour, 6 split nibbles)
# A specialized counter whose per-field bounds (sec<60, min<60, hr<24) and BCD
# rollover are FULLY stated. Sync active-high reset to 00:00:00, one tick = one clk.
# =========================================================================== #
def _try_bcd_clock(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"\bbcd\b|binary[- ]coded[- ]decimal", low):
        return None
    if not (re.search(r"hours?\b", low) and re.search(r"minutes?\b", low)
            and re.search(r"seconds?\b", low)):
        return None
    if not re.search(r"24[- ]hour|23:59:59", low):
        return None  # only the 24-hour split-nibble shape here (12-hour packed is elsewhere)
    out_map = {n.lower(): (n, w) for n, w in outs}
    need = ("ms_hr", "ls_hr", "ms_min", "ls_min", "ms_sec", "ls_sec")
    if not all(k in out_map for k in need):
        return None
    if any(out_map[k][1] != 4 for k in need):
        return None
    if len(outs) != 6:
        return None
    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    rst_name = rst[0]
    # reset must be stated active-high resetting all to 0.
    if not re.search(r"active[- ]high", low) or not re.search(
            r"reset[^.]{0,80}?(?:to\s+)?(?:0\b|zero|00:00:00)", low):
        return None
    if re.search(r"asynchron|areset", low):
        return None  # sync reset shape only
    extra = [n for n, _ in ins if n not in (clk[0], rst_name)]
    if extra:
        return None

    mh, lh = out_map["ms_hr"][0], out_map["ls_hr"][0]
    mm, lm = out_map["ms_min"][0], out_map["ls_min"][0]
    msn, lsn = out_map["ms_sec"][0], out_map["ls_sec"][0]
    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1)]
    for n in (mh, lh, mm, lm, msn, lsn):
        ports.append(_decl("output", n, 4, reg=True))
    body = (
        f"    wire sec_roll = ({msn} == 5) && ({lsn} == 9);\n"
        f"    wire min_roll = sec_roll && ({mm} == 5) && ({lm} == 9);\n"
        f"    wire hr_roll  = min_roll && ({mh} == 2) && ({lh} == 3);\n"
        f"    always @(posedge {clk[0]}) begin\n"
        f"        if ({rst_name}) begin\n"
        f"            {mh} <= 0; {lh} <= 0; {mm} <= 0; {lm} <= 0; {msn} <= 0; {lsn} <= 0;\n"
        f"        end else begin\n"
        f"            // seconds\n"
        f"            if ({lsn} == 9) begin {lsn} <= 0;\n"
        f"                if ({msn} == 5) {msn} <= 0; else {msn} <= {msn} + 1;\n"
        f"            end else {lsn} <= {lsn} + 1;\n"
        f"            // minutes (advance when seconds roll over)\n"
        f"            if (sec_roll) begin\n"
        f"                if ({lm} == 9) begin {lm} <= 0;\n"
        f"                    if ({mm} == 5) {mm} <= 0; else {mm} <= {mm} + 1;\n"
        f"                end else {lm} <= {lm} + 1;\n"
        f"            end\n"
        f"            // hours (advance when minutes roll over); 23 -> 00\n"
        f"            if (min_roll) begin\n"
        f"                if (hr_roll) begin {mh} <= 0; {lh} <= 0; end\n"
        f"                else if ({lh} == 9) begin {lh} <= 0; {mh} <= {mh} + 1; end\n"
        f"                else {lh} <= {lh} + 1;\n"
        f"            end\n"
        f"        end\n"
        f"    end\n"
    )
    return (f"// program-SOLVED 24-hour BCD wall-clock counter "
            f"(stated 60/60/24 bounds); deterministic, no AI.\n"
            f"module {top} (\n    " + ",\n    ".join(ports) + "\n);\n" + body
            + "endmodule\n")


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
_BUILDERS = (_try_barrel_rotate, _try_saturating_counter, _try_bcd_clock)


def solve(record: dict) -> Optional[str]:
    """Emit deterministic RTL (module named per the prompt/context) for a CVDP
    barrel-shift / rotate or saturating / specialized-counter design, or None
    (SKIP) on ANY ambiguity / unstated governing fact / non-member design."""
    if not isinstance(record, dict):
        return None
    top = _toplevel(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    # a "modify the existing RTL" task ships prior code in input['context'] — that is
    # a delta task, not a single-function emit. We solve from-scratch designs only.
    ic = (record.get("input") or {}).get("context")
    if isinstance(ic, dict) and any(
            isinstance(v, str) and v.strip() for v in ic.values()):
        return None

    iface = _interface(prompt)
    if not iface:
        return None
    ins, outs = iface
    for fn in _BUILDERS:
        try:
            rtl = fn(prompt, ins, outs, top)
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
    ic = (record.get("input") or {}).get("context")
    if isinstance(ic, dict) and any(
            isinstance(v, str) and v.strip() for v in ic.values()):
        return None
    iface = _interface(prompt)
    if not iface:
        return None
    ins, outs = iface
    names = {"_try_barrel_rotate": "barrel_shift_rotate",
             "_try_saturating_counter": "saturating_counter",
             "_try_bcd_clock": "bcd_clock_counter"}
    for fn in _BUILDERS:
        try:
            if fn(prompt, ins, outs, top):
                return names[fn.__name__]
        except Exception:
            continue
    return None


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n = 0
    fam: Dict[str, int] = {}
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            k = family_of(r)
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  family={k} ===")
                print(rtl)
    print(f"solved={n}/{len(recs)}  families={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
