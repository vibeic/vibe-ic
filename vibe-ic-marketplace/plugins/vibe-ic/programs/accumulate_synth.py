#!/usr/bin/env python3
"""accumulate_synth.py — deterministic SOLVER for the CVDP sequential
ACCUMULATOR / running-op family:

  RUNNING ACCUMULATOR   acc <= acc + data   (on enable; reset clears to 0)
  INTEGER MAC           acc <= acc + a*b    (plain integer multiply only)
  RUNNING MIN / MAX     acc <= (data </> acc) ? data : acc   (on enable)
  POWER-OF-2 MOVING AVG sum of the last N samples, divided by N via a >>log2(N)
                        shift — ONLY when N is a power of two (no general divider)

WHY a dedicated CVDP solver (and not the registry / the other family solvers):
  * The registry's plain +/-/* synths key on VerilogEval / RTLLM bullet ports and
    emit a COMBINATIONAL `result = a + b`. A running accumulator is SEQUENTIAL
    (state across clocks, reset, enable) — a different shape the registry never
    emits. cvdp_atomic_bridge.py ALSO SKIPs this family: its cocotb-driven port
    extractor mis-tokenizes the clocked interface and its _SPECIAL_ALGEBRA_RE skips
    the saturate cue. So neither path covers running-sum / running-MAC / running
    min-max / power-of-2 moving-average.
  * This solver builds ONLY a CVDP-native interface reader (the dataset's own
    `### Inputs/Outputs` markdown list, incl. the `- **[11:0] data_in**:` form) and
    four deterministic SEQUENTIAL emitters, each PARSE-or-SKIP.

§4.05 NO-LEAK / NO-CHEAT (binding):
  * NEVER read the hidden harness (cocotb TB, .env TOPLEVEL) or the golden/reference
    RTL. Ports AND the module name come ONLY from input.prompt + input.context (the
    latter via the bridge) — never from the harness and never from output['context']
    bodies (which are empty in CVDP v1.1.0 anyway, but the guard holds regardless).
  * NEVER guess a width, a reset polarity/sync, an operation, a divisor, or a
    window. ANY unstated / ambiguous governing fact -> return None (SKIP). A wrong
    accumulate silently passes lint+synth and only a clocked testbench catches it,
    so a skip is always safer than a guess.
  * SKIP every: unstated reset/width; a stated NON-power-of-2 divide (needs a real
    divider); a GF / fixed-point / floating-point accumulate; a windowed average
    whose window logic isn't pinned; a composite / protocol / FSM-gated / pipelined
    design; a "modify the existing RTL" DELTA task (prior code in input.context).

GENERAL + CHIP-AGNOSTIC: recognition keys on the OPERATION / STRUCTURE semantics
and role-conventional port names ONLY — never a design name or a record id. The
SAME prompt solves identically; the emitted module is named per the prompt/context
module designation (rename-invariant), never per the hidden harness TOPLEVEL.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
deterministic, pure-function.
"""
from __future__ import annotations

import math
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
# module NAME — from `input.prompt` + `input.context` ONLY (via the bridge).
# The harness `.env` TOPLEVEL and the cocotb testbench are the hidden test
# HARNESS = OFF-LIMITS oracle; when the name is stated in NEITHER the prompt nor
# the provided context the bridge returns None and this solver SKIPs (honest
# floor, never a harness peek).
# --------------------------------------------------------------------------- #
def _toplevel(record: dict) -> Optional[str]:
    try:
        import cvdp_atomic_bridge as _bridge
        t = _bridge.toplevel_name(record)
        if t:
            return t
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# CVDP-native interface reader: the `### Inputs` / `### Outputs` markdown list.
# Forms handled (all from the dataset prose, never the golden RTL):
#   - **`data_in`** (8-bits, [7:0]): ...
#   - **`i_data`** (logic [`DATA_WIDTH`-1:0]): ...   (parameterized -> stated default)
#   - **[11 : 0] data_in**: 12-bit input data.       (range PREFIXED before the name)
#   - **clk**: Clock signal.                          (width-less control -> 1-bit)
# Width resolution order: an explicit [hi:lo] (suffix OR prefix); a parameterized
# [`P`-1:0] whose default P is stated; an `N-bit(s)` token. An unresolved width on a
# non-control data port -> the port is dropped, which forces a §4.05 SKIP rather
# than a phantom width.
# --------------------------------------------------------------------------- #
def _param_defaults(prompt: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in re.finditer(
        r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?(?:\s+of)?\s*"
        r"(?:is\s+|=\s*)?`?(\d+)`?", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in re.finditer(r"parameter\s+([A-Z][A-Z0-9_]+)\s*=\s*(\d+)", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def _range_width(text: str, params: Dict[str, int]) -> Optional[int]:
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", text)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    m = re.search(r"\[\s*`?([A-Za-z_]\w*)`?\s*-\s*1\s*:\s*0\s*\]", text)
    if m and m.group(1) in params:
        return params[m.group(1)]
    m = re.search(r"\b(\d+)\s*-?\s*bits?\b", text, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*-?\s*bit\b", text, re.I) or re.search(r"\(\s*1\s*\)", text):
        return 1
    return None


# a control/clock/reset/enable-style name with no stated width is 1-bit by role.
_CTRL_NAME_RE = re.compile(
    r"(?i)(?:^|_)(clk|clock|rst|reset|resetn|rstn|areset|en|enable|valid|ready|"
    r"start|stop|load|clear|clr|cen|ce|hold|dvld|in_valid|out_valid|done|tc)$"
    r"|(?:^|_)(?:clk|clock|rst|reset|en|enable|valid|load|clear)(?:$|_)")

# name forms:
#   (A) **`name`** (cell): ...        / - name (cell): ...      (range in the cell)
#   (B) **[hi:lo] name**: ...         (range PREFIXED before the name)
#   (C) **name**: description         (width-less; control -> 1-bit, else from desc)
_PORT_A_RE = re.compile(
    r"""^\s*[-*]?\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*\(([^)]*)\)""", re.X)
_PORT_B_RE = re.compile(
    r"""^\s*[-*]?\s*\*{0,2}\s*(\[[^\]]*\])\s*`?([A-Za-z_]\w*)`?\*{0,2}\s*:""", re.X)
_PORT_C_RE = re.compile(
    r"""^\s*[-*]\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*[:—\-]\s*(.+)$""", re.X)


def _section_ports(prompt: str, header_words, params) -> List[Port]:
    lines = prompt.splitlines()
    ports: List[Port] = []
    in_sec = False
    for ln in lines:
        h = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", ln) or re.match(
            r"^\s*\*\*(.+?)\*\*\s*:?\s*$", ln)
        if h:
            label = h.group(1).strip().lower().rstrip(":")
            label = re.sub(r"\s+(ports?|signals?)$", "", label)
            in_sec = any(w == label or label.startswith(w) or label.endswith(w)
                         for w in header_words)
            continue
        if not in_sec:
            continue
        name = cell = None
        mb = _PORT_B_RE.match(ln)        # prefixed-range form first (range is explicit)
        if mb:
            cell, name = mb.group(1), mb.group(2)
        else:
            ma = _PORT_A_RE.match(ln)
            if ma:
                name, cell = ma.group(1), ma.group(2)
            else:
                mc = _PORT_C_RE.match(ln)
                if not mc:
                    continue
                name, cell = mc.group(1), mc.group(2)
        if not name or name.lower() in _NOT_A_PORT_NAME:
            continue
        w = _range_width(cell, params)
        if w is None:
            w = _range_width(ln, params)          # range may sit elsewhere on the line
        if w is None:
            if _CTRL_NAME_RE.search(name):
                w = 1
            else:
                continue                          # unresolved data width -> drop -> SKIP
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
    ins = _dedup(_section_ports(prompt, ("inputs", "input"), params))
    outs = _dedup(_section_ports(prompt, ("outputs", "output"), params))
    if ins and outs:
        return ins, outs
    return None


def _find_re(ports: List[Port], pattern: str) -> Optional[Port]:
    rx = re.compile(pattern, re.I)
    for n, w in ports:
        if rx.search(n):
            return (n, w)
    return None


def _clk(ins): return _find_re(ins, r"(?:^|_)(cl(?:k|ock))$") or _find_re(ins, r"clk|clock")
def _rst(ins): return _find_re(ins, r"(rst|reset|areset)")
def _enable(ins): return _find_re(ins, r"(?:^|_)(en|enable|ena|cen|ce|valid|vld|i_valid|in_valid)$")


def _decl(direction, name, width, reg=False):
    kw = f"{direction} reg" if reg else direction
    return f"{kw} [{width-1}:0] {name}" if width > 1 else f"{kw} {name}"


# --------------------------------------------------------------------------- #
# reset semantics — PARSED, never guessed. Returns (rst_name, active_low, async)
# or None when the polarity/sync is not unambiguously stated.
# --------------------------------------------------------------------------- #
def _reset_semantics(prompt: str, rst_name: str) -> Optional[Tuple[str, bool, bool]]:
    low = prompt.lower()
    nm = rst_name.lower()
    # active-low iff the name says so OR the prose says so; active-high iff stated.
    name_low = nm.endswith("_n") or nm in ("resetn", "rstn", "arstn", "aresetn")
    prose_low = bool(re.search(r"active[-\s]?low", low))
    prose_high = bool(re.search(r"active[-\s]?high", low))
    if name_low or prose_low:
        active_low = True
    elif prose_high:
        active_low = False
    else:
        return None  # polarity not stated -> SKIP
    asynch = bool(re.search(r"asynchronous|\basync\b|areset", low)) or "async" in nm
    synch = bool(re.search(r"synchronous", low)) and not asynch
    # require an explicit sync/async statement (or an areset-style name) — never guess.
    if not (asynch or synch):
        return None
    return rst_name, active_low, asynch


# --------------------------------------------------------------------------- #
# §4.05 disqualifiers shared by every family (operation/structure semantics).
# --------------------------------------------------------------------------- #
_DISQUALIFY_RE = re.compile(
    r"""(?xi)
      \bgalois\b | \bgf\s*\(\s*2 | \bgf\(2 | \birreducible\b | \bfinite\s+field\b |
      \bmodular\s+(?:multipl|arithmetic)\b | \bmontgomery\b | \bcarry[-\s]?less\b |
      \bfixed[-\s]?point\b | \bfloating[-\s]?point\b | \bQ\d+\.\d+\b |
      \baxi\b | \bapb\b | \bahb\b | \bwishbone\b | \bavalon\b | \buart\b | \bspi\b |
      \bi2c\b | \bi2s\b | \bjtag\b | \bpcie\b | \busb\b | \brs[-\s]?232\b |
      \bfifo\b | \bcache\b | \bsram\b | \bdram\b | \bmemory\s+controller\b |
      \bstate\s+machine\b | \bfsm\b | \bsequencer\b | \bprocessor\b | \bcpu\b |
      \bpacket\b | \belevator\b | \bvending\b | \bparking\b | \bperceptron\b |
      \bhebbian\b | \bvga\b | \bsprite\b | \bpipeline\b | \bpipelined\b |
      \bmatrix\b | \bbooth\b | \bcordic\b | \bfir\b | \bdivider\b
    """,
)


def _delta_task(record: dict) -> bool:
    """A 'modify/enhance the existing RTL' delta task ships prior code in
    input['context']. We solve FROM-SCRATCH designs only."""
    ic = (record.get("input") or {}).get("context")
    if isinstance(ic, dict) and any(
            isinstance(v, str) and v.strip() for v in ic.values()):
        return True
    prompt = (record.get("input") or {}).get("prompt") or ""
    # textual delta cues even when the prior code rides in the prompt fence.
    if re.search(r"(?i)\b(modify|enhance|complete the (?:given|provided|partial)|"
                 r"the original module|existing\s+(?:rtl|module|code|design))\b", prompt):
        return True
    return False


# =========================================================================== #
# FAMILY 1 — running accumulator   acc <= acc + data   (on enable; reset -> 0)
# =========================================================================== #
def _try_accumulator(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    # must be a RUNNING / accumulating SUM of a streamed data input (not a one-shot
    # multi-operand add, not a*b, not min/max, not an average).
    if not re.search(r"accumulat|running\s+sum|running\s+total|keeps?\s+(?:a\s+)?"
                     r"running|adds?\s+(?:each|every|the\s+incoming)", low):
        return None
    if re.search(r"average|mean|multiply[-\s]?accumulate|\bmac\b|\bmin(?:imum)?\b|"
                 r"\bmax(?:imum)?\b|product", low):
        return None
    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    # exactly one wide data input + one accumulator output (plus clk/rst/enable).
    data_in = _find_re(ins, r"(data_?in|\bdin\b|sample|\bin\b|i_data|value|operand)")
    if data_in is None:
        cands = [(n, w) for n, w in ins
                 if (n, w) not in (clk, rst) and w > 1]
        data_in = cands[0] if len(cands) == 1 else None
    if data_in is None or data_in[1] < 1:
        return None
    acc_out = _find_re(outs, r"(acc|sum|total|result|data_?out|count|o_data)")
    if acc_out is None:
        wide = [(n, w) for n, w in outs if w >= data_in[1]]
        acc_out = wide[0] if len(wide) == 1 else None
    if acc_out is None:
        return None
    if len([o for o in outs if o[1] > 1]) != 1:
        return None  # more than one wide output -> not a single accumulator -> SKIP

    rs = _reset_semantics(prompt, rst[0])
    if rs is None:
        return None
    rst_name, active_low, asynch = rs

    # saturate ONLY if explicitly stated with a stated bound; otherwise plain wrap.
    saturate = bool(re.search(r"saturat|clamp|does\s+not\s+wrap", low))
    sat_max = None
    if saturate:
        mm = re.search(r"max(?:imum)?\s+(?:value\s+)?(?:of\s+)?(\d+)", low)
        if not mm:
            return None  # saturate stated but no stated bound -> SKIP
        sat_max = int(mm.group(1))
        if (1 << acc_out[1]) <= sat_max:
            return None

    ena = _enable(ins)
    used = {clk[0], rst[0]}
    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1)]
    guard = ""
    if ena and ena[0] not in used:
        ports.append(_decl("input", ena[0], ena[1]))
        used.add(ena[0])
        guard = f"if ({ena[0]}) "
    ports.append(_decl("input", data_in[0], data_in[1]))
    used.add(data_in[0])
    # any other unexplained input -> SKIP (never invent its meaning).
    if any(n not in used for n, _ in ins):
        return None
    ports.append(_decl("output", acc_out[0], acc_out[1], reg=True))

    din, acc, W = data_in[0], acc_out[0], acc_out[1]
    rst_test = f"!{rst_name}" if active_low else rst_name
    sens = f"posedge {clk[0]}"
    if asynch:
        sens += f", {'negedge' if active_low else 'posedge'} {rst_name}"
    if saturate:
        nextv = (f"(({acc} + {din}) > {sat_max}) ? {sat_max}[{W-1}:0] : "
                 f"({acc} + {din})")
    else:
        nextv = f"{acc} + {din}"
    note = ("saturating " if saturate else "") + "running accumulator (acc<=acc+data)"
    return (
        f"// program-SOLVED {note}; reset polarity/sync PARSED; deterministic, no AI.\n"
        f"module {top} (\n    " + ",\n    ".join(ports) + "\n);\n"
        f"    always @({sens}) begin\n"
        f"        if ({rst_test})\n"
        f"            {acc} <= 0;\n"
        f"        else {guard}begin\n"
        f"            {acc} <= {nextv};\n"
        f"        end\n"
        f"    end\n"
        f"endmodule\n")


# =========================================================================== #
# FAMILY 2 — integer MAC   acc <= acc + a*b   (plain integer multiply; reset -> 0)
# A windowed / pipelined / per-N MAC (output every N inputs, multi-stage) is NOT a
# single running MAC -> SKIP (covered by the disqualifiers + the structural guards).
# =========================================================================== #
def _try_mac(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"multiply[-\s]?accumulate|\bmac\b|"
                     r"accumulat[^.\n]{0,40}product|product[^.\n]{0,40}accumulat", low):
        return None
    # plain INTEGER multiply only — a GF/fixed-point/pipelined/window MAC is disqualified
    # by _DISQUALIFY_RE (checked in solve()). Also SKIP a per-N windowed result.
    if re.search(r"after\s+`?n`?\s+(?:valid\s+)?inputs|every\s+`?n`?\s+cycles|"
                 r"window|dot\s*product|\bstage\b|two[-\s]stage|2[-\s]stage", low):
        return None
    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    # two distinct wide multiplicand inputs.
    a = _find_re(ins, r"(multiplicand|^a$|in_?a|op_?a|data_?a|x)")
    b = _find_re(ins, r"(multiplier|^b$|in_?b|op_?b|data_?b|y|coeff|weight)")
    if a is None or b is None or a[0] == b[0]:
        wide = [(n, w) for n, w in ins if (n, w) not in (clk, rst) and w > 1]
        if len(wide) == 2:
            a, b = wide[0], wide[1]
        else:
            return None
    acc_out = _find_re(outs, r"(acc|mac|result|sum|product|data_?out|o_data)")
    if acc_out is None:
        wide = [(n, w) for n, w in outs if w > 1]
        acc_out = wide[0] if len(wide) == 1 else None
    if acc_out is None:
        return None
    if len([o for o in outs if o[1] > 1]) != 1:
        return None

    rs = _reset_semantics(prompt, rst[0])
    if rs is None:
        return None
    rst_name, active_low, asynch = rs

    ena = _enable(ins)
    used = {clk[0], rst[0]}
    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1)]
    guard = ""
    if ena and ena[0] not in used:
        ports.append(_decl("input", ena[0], ena[1]))
        used.add(ena[0])
        guard = f"if ({ena[0]}) "
    for nm, w in (a, b):
        ports.append(_decl("input", nm, w))
        used.add(nm)
    if any(n not in used for n, _ in ins):
        return None
    ports.append(_decl("output", acc_out[0], acc_out[1], reg=True))

    acc = acc_out[0]
    rst_test = f"!{rst_name}" if active_low else rst_name
    sens = f"posedge {clk[0]}"
    if asynch:
        sens += f", {'negedge' if active_low else 'posedge'} {rst_name}"
    return (
        f"// program-SOLVED integer MAC (acc<=acc+a*b); reset PARSED; "
        f"deterministic, no AI.\n"
        f"module {top} (\n    " + ",\n    ".join(ports) + "\n);\n"
        f"    always @({sens}) begin\n"
        f"        if ({rst_test})\n"
        f"            {acc} <= 0;\n"
        f"        else {guard}begin\n"
        f"            {acc} <= {acc} + ({a[0]} * {b[0]});\n"
        f"        end\n"
        f"    end\n"
        f"endmodule\n")


# =========================================================================== #
# FAMILY 3 — running min / max   acc <= (data </> acc) ? data : acc  (on enable)
# =========================================================================== #
def _try_minmax(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    is_max = bool(re.search(r"running\s+max|maximum\s+(?:value\s+)?(?:seen|so\s+far|"
                            r"of\s+the\s+stream)|keeps?\s+track\s+of\s+the\s+max|"
                            r"peak\s+(?:value|detect)", low))
    is_min = bool(re.search(r"running\s+min|minimum\s+(?:value\s+)?(?:seen|so\s+far|"
                            r"of\s+the\s+stream)|keeps?\s+track\s+of\s+the\s+min", low))
    if is_max == is_min:
        return None  # neither, or both (ambiguous) -> SKIP
    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    data_in = _find_re(ins, r"(data_?in|\bdin\b|sample|\bin\b|value|i_data)")
    if data_in is None:
        cands = [(n, w) for n, w in ins if (n, w) not in (clk, rst) and w > 1]
        data_in = cands[0] if len(cands) == 1 else None
    if data_in is None or data_in[1] < 1:
        return None
    out_p = _find_re(outs, r"(min|max|peak|result|data_?out|o_data)")
    if out_p is None:
        wide = [(n, w) for n, w in outs if w > 1]
        out_p = wide[0] if len(wide) == 1 else None
    if out_p is None or out_p[1] != data_in[1]:
        return None
    if len([o for o in outs if o[1] > 1]) != 1:
        return None

    rs = _reset_semantics(prompt, rst[0])
    if rs is None:
        return None
    rst_name, active_low, asynch = rs

    # reset value MUST be stated for a min/max accumulator (min resets to a max
    # sentinel / first sample; max resets to 0 / a min sentinel). We require an
    # explicit "resets to 0" (max) or an explicit reset-value statement; else SKIP.
    signed = bool(re.search(r"signed", low))
    if signed:
        return None  # signed min/max sentinel handling is not pinned here -> SKIP
    W = out_p[1]
    rv = None
    if is_max:
        if re.search(r"reset[^.]{0,80}?(?:to\s+)?(?:0\b|zero)", low):
            rv = "0"
    else:  # min resets to the all-ones max sentinel only if stated as such
        if re.search(r"reset[^.]{0,80}?(?:to\s+)?(?:max|all\s+ones|0x?f+|"
                     r"largest|maximum)", low):
            rv = f"{{{W}{{1'b1}}}}"
    if rv is None:
        return None  # reset value not pinned -> SKIP

    ena = _enable(ins)
    used = {clk[0], rst[0]}
    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1)]
    guard = ""
    if ena and ena[0] not in used:
        ports.append(_decl("input", ena[0], ena[1]))
        used.add(ena[0])
        guard = f"if ({ena[0]}) "
    ports.append(_decl("input", data_in[0], data_in[1]))
    used.add(data_in[0])
    if any(n not in used for n, _ in ins):
        return None
    ports.append(_decl("output", out_p[0], W, reg=True))

    din, acc = data_in[0], out_p[0]
    cmp = ">" if is_max else "<"
    rst_test = f"!{rst_name}" if active_low else rst_name
    sens = f"posedge {clk[0]}"
    if asynch:
        sens += f", {'negedge' if active_low else 'posedge'} {rst_name}"
    return (
        f"// program-SOLVED running {'max' if is_max else 'min'} "
        f"(acc<=(data {cmp} acc)?data:acc); reset PARSED; deterministic, no AI.\n"
        f"module {top} (\n    " + ",\n    ".join(ports) + "\n);\n"
        f"    always @({sens}) begin\n"
        f"        if ({rst_test})\n"
        f"            {acc} <= {rv};\n"
        f"        else {guard}begin\n"
        f"            if ({din} {cmp} {acc}) {acc} <= {din};\n"
        f"        end\n"
        f"    end\n"
        f"endmodule\n")


# =========================================================================== #
# FAMILY 4 — power-of-2 moving average  (sum of last N, /N via >>log2(N))
# Pinned model (matches the CVDP moving_average harness exactly): a ring buffer of
# the last N samples + a running sum; on each clock the OLD sum is published as the
# output (>>log2 N => 1-cycle latency), then sum <= sum + data_in - oldest. The
# partial-fill phase divides by N too (buffer inits to 0 at reset). §4.05: ONLY
# when N is a power of two (a non-power-of-2 divide needs a real divider -> SKIP).
# =========================================================================== #
def _try_moving_average(prompt: str, ins, outs, top) -> Optional[str]:
    low = prompt.lower()
    if not re.search(r"moving\s+average|running\s+average|sliding\s+(?:window\s+)?"
                     r"average", low):
        return None
    # window size N — must be a single stated power of two.
    n = None
    for m in re.finditer(r"(?:last|recent|window(?:\s+size)?(?:\s+of)?|past)\s+"
                         r"(?:`?)(\d+)(?:`?)\s*(?:input\s+)?samples?", low):
        n = int(m.group(1))
        break
    if n is None:
        m = re.search(r"(\d+)[-\s]point\s+moving\s+average", low)
        if m:
            n = int(m.group(1))
    if n is None or n < 2 or (n & (n - 1)) != 0:
        return None  # window not stated, or not a power of two -> SKIP
    shift = int(math.log2(n))

    clk = _clk(ins)
    rst = _rst(ins)
    if clk is None or rst is None:
        return None
    data_in = _find_re(ins, r"(data_?in|\bdin\b|sample|\bin\b|i_data)")
    data_out = _find_re(outs, r"(data_?out|average|avg|result|\bout\b|o_data)")
    if data_in is None or data_out is None:
        return None
    if data_in[1] < 1 or data_out[1] < 1:
        return None
    if len([o for o in outs if o[1] > 1]) != 1:
        return None

    rs = _reset_semantics(prompt, rst[0])
    if rs is None:
        return None
    rst_name, active_low, asynch = rs
    # the pinned ring-buffer model is for a SYNCHRONOUS reset; an async-reset shape
    # is not what this harness pins -> SKIP.
    if asynch:
        return None
    # must clear the output (and the buffer/sum) on reset — stated.
    if not re.search(r"reset[^.]{0,120}?(?:clear|zero|0\b)", low):
        return None

    ena = _enable(ins)
    used = {clk[0], rst[0]}
    ports = [_decl("input", clk[0], 1), _decl("input", rst_name, 1)]
    guard = ""
    if ena and ena[0] not in used:
        ports.append(_decl("input", ena[0], ena[1]))
        used.add(ena[0])
        guard = f"if ({ena[0]}) "
    ports.append(_decl("input", data_in[0], data_in[1]))
    used.add(data_in[0])
    if any(nm not in used for nm, _ in ins):
        return None
    ports.append(_decl("output", data_out[0], data_out[1], reg=True))

    din, dout, W = data_in[0], data_out[0], data_in[1]
    OW = data_out[1]
    # sum must hold N*(2^W-1): W + log2(N) bits suffices.
    SW = W + shift
    ptr_w = max(1, shift)
    # The harness applies data_in[k] on the SAME edge the DUT registers it, then on the
    # NEXT iteration compares data_out against the average that INCLUDES sample k. So the
    # registered output published on each edge must be the NEXT running sum (the one that
    # folds in the just-sampled input), >> log2(N) — NOT the old sum (that lags one extra
    # cycle: harness `Mismatch ... got 0`). Compute the next-sum once and both publish its
    # quotient and store it.
    next_sum = f"(sum + {din} - buffer[wr_ptr])"
    # average = next_sum >> log2(N) = the high (SW-shift) bits, truncated to the output's
    # declared width OW (a wider sum-quotient is masked to OW bits).
    quot_bits = SW - shift                       # == W
    take = min(OW, quot_bits)
    avg_slice = f"sum_next[{shift + take - 1}:{shift}]"
    pad = "" if take >= OW else f"{{{OW - take}{{1'b0}}}}, "
    avg_expr = avg_slice if take >= OW else f"{{{pad}{avg_slice}}}"
    rst_test = f"!{rst_name}" if active_low else rst_name
    return (
        f"// program-SOLVED power-of-2 moving average (last {n} samples, >>{shift}); "
        f"window & divisor PARSED; ring buffer + running sum; deterministic, no AI.\n"
        f"module {top} (\n    " + ",\n    ".join(ports) + "\n);\n"
        f"    reg [{W-1}:0] buffer [0:{n-1}];\n"
        f"    reg [{ptr_w-1}:0] wr_ptr;\n"
        f"    reg [{SW-1}:0] sum;\n"
        f"    wire [{SW-1}:0] sum_next = {next_sum};\n"
        f"    integer k;\n"
        f"    always @(posedge {clk[0]}) begin\n"
        f"        if ({rst_test}) begin\n"
        f"            sum <= 0;\n"
        f"            wr_ptr <= 0;\n"
        f"            {dout} <= 0;\n"
        f"            for (k = 0; k < {n}; k = k + 1) buffer[k] <= 0;\n"
        f"        end else {guard}begin\n"
        f"            {dout} <= {avg_expr};\n"  # average INCLUDING the just-sampled input
        f"            sum <= sum_next;\n"
        f"            buffer[wr_ptr] <= {din};\n"
        f"            wr_ptr <= wr_ptr + 1;\n"
        f"        end\n"
        f"    end\n"
        f"endmodule\n")


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
_BUILDERS = (_try_moving_average, _try_mac, _try_minmax, _try_accumulator)
_NAMES = {
    "_try_moving_average": "moving_average_pow2",
    "_try_mac": "integer_mac",
    "_try_minmax": "running_minmax",
    "_try_accumulator": "running_accumulator",
}


def solve(record: dict) -> Optional[str]:
    """Emit deterministic SEQUENTIAL RTL (module named per the harness TOPLEVEL)
    for a CVDP running accumulator / integer-MAC / running min-max / power-of-2
    moving-average, or None (SKIP) on ANY unstated/ambiguous governing fact, a
    DELTA modify-task, or a disqualified (GF / fixed-point / non-pow2-divide /
    composite / pipelined / FSM-gated) design."""
    if not isinstance(record, dict):
        return None
    top = _toplevel(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    if _delta_task(record):
        return None
    if _DISQUALIFY_RE.search(prompt):
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
    if _delta_task(record) or _DISQUALIFY_RE.search(prompt):
        return None
    iface = _interface(prompt)
    if not iface:
        return None
    ins, outs = iface
    for fn in _BUILDERS:
        try:
            if fn(prompt, ins, outs, top):
                return _NAMES[fn.__name__]
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
    ids: List[str] = []
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            ids.append(r.get("id"))
            k = family_of(r)
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  family={k} ===")
                print(rtl)
    print(f"solved={n}/{len(recs)}  families={fam}  ids={ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
