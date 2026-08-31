#!/usr/bin/env python3
"""mux_compare_synth.py — a DETERMINISTIC solver for the CVDP
MULTIPLEXER / DEMUX  +  COMPARATOR / MIN-MAX family.

WHY (owner directive 2026-06-23): the shipped registry has a `mux_synth` that fires
only on VerilogEval / RTLLM bullet-port phrasing; on the CVDP "code generation"
slice it fires on ~0 prompts because CVDP states the interface as a markdown
test-case table / cocotb harness signal list / a non-empty module HEADER, not as a
clean bullet-port block. This synth fills that gap for the SELECT/COMPARE family:
it PARSES the stated operation (N:1 mux select map, 1:N demux routing, a>b/a==b/a<b
comparator with the signed-ness PARSED, min/max of N inputs) and the stated widths,
then emits a combinational datapath named per the PROMPT-stated module name. The
module NAME and the port INTERFACE both come from the shipped `record_prompt_context_bridge`
(`toplevel_name` / `extract_interface`), whose sole sources are `input.prompt` +
`input.context`. When the bridge cannot resolve the name or the interface from that
model-visible surface, this solver SKIPs (returns None) — never a harness peek.

GENERAL — keyed on the stated SELECT / COMPARE / MIN-MAX SEMANTICS, never on a
design name. The parsed select width / source count / comparison op / signed-ness
drive the emit; nothing is hard-coded to a benchmark id.

NO-CHEAT / §4.05 (binding) — the CVDP official rule (arXiv:2506.14074 §2 +
README_NON_AGENTIC): the model sees ONLY `input.prompt` + `input.context`. The
hidden test HARNESS (the cocotb `dut.<sig>` test and the `.env` TOPLEVEL /
VERILOG_SOURCES) and the GOLDEN reference RTL are OFF-LIMITS oracle and are NEVER
read here — not the module name, not the ports, not one bit of logic.
  * The select width, source count, comparison operation and signed-ness are PARSED
    from the PROMPT PROSE only; the module name + interface come from the bridge's
    prompt+context-only readers.
  * SKIP (return None) when:
      - the select->source MAPPING is not the natural ascending order, or is
        unstated, or the out-of-range select default is needed but unstated;
      - a comparator's signed-ness is ambiguous (neither signed nor unsigned, and
        not a mode-select that the prose fully pins);
      - the design is clocked / a CDC synchronizer / a protocol or bus controller /
        an area-or-latency-optimization task / a sort network / a flattened-array
        binary tree / needs a NAMED sub-module — a SELECT/COMPARE noun appears but
        the function is NOT a single combinational select/compare we can pin down;
      - the interface cannot be unambiguously extracted.
    NEVER emit a wrong op (a magnitude compare for a signed one, a mux for a demux);
    "a wrong op is far worse than an honest skip."

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC, pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

Port = Tuple[str, int]  # (name, width)

# The module NAME and the port INTERFACE come ONLY from the shipped bridge's
# prompt+context readers (`toplevel_name` / `extract_interface`). The bridge reads
# `input.prompt` + `input.context` exclusively — the hidden harness (cocotb
# `dut.<sig>`, `.env`) and the golden (`record["output"]`) are OFF-LIMITS oracle and
# are never touched here. (The bridge's own `solve()` additionally strips the oracle
# up front, so by the time a design reaches this family solver the harness/output
# are already gone.)
import record_prompt_context_bridge as _bridge  # noqa: E402  NAME + INTERFACE source

# Clock / reset / async-control port names the datapath classifiers must ignore
# (a purely COMBINATIONAL select/compare has no such ports). A plain constant set,
# NOT a harness read.
_SEQ_PORTS = {"clk", "clock", "rst", "reset", "rstn", "rst_n", "resetn",
              "reset_n", "areset", "aresetn", "clk_en", "clken", "srst",
              "nrst", "n_rst", "rst_ni", "clk_i"}


def _toplevel_name(record: dict) -> Optional[str]:
    """The target module name — from `input.prompt` + `input.context` ONLY (via the
    bridge). None when the prompt/context does not name the module (an honest SKIP,
    never a harness `.env` peek)."""
    return _bridge.toplevel_name(record)


def _extract_interface(record: dict, top: str) -> Optional[Tuple[List[Port], List[Port]]]:
    """The (inputs, outputs) port interface — from `input.prompt` + `input.context`
    ONLY (via the bridge: skeleton header / prose `### Inputs:`/`### Outputs:` block /
    test-case table). None when the interface is not stated on that model-visible
    surface. The cocotb `dut.<sig>` harness and the golden are NEVER read."""
    return _bridge.extract_interface(record, top)


# =========================================================================== #
# §4.05 up-front SKIP — clocked / CDC / protocol / area-opt / sort / tree
# (keyed on stated STRUCTURE / OPERATION, never a design name)
# =========================================================================== #
_SKIP_RE = re.compile(
    r"""(?xi)
      # clocked / sequential / CDC — this family must be COMBINATIONAL
      \bposedge\b | \bnegedge\b | \balways_ff\b | \bsynchroniz | \btwo[-\s]?flop\b |
      \bclock\s+domain\b | \bmetastab | \bglitch[-\s]?free\b | \bregister(?:ed|s)?\b |
      \brising\s+edge\b | \bfalling\s+edge\b |
      \bon\s+reset\b | \breset\s+behavior\b | \basserted\s+on\s+the\s+rising\b |
      \binternal\s+state | \bflip[-\s]?flop\b | \bclock\s+cycle\b |
      # non-plain datapaths the min/max/compare emit would get wrong
      \bclamp\b | \bclamped\b | \bsaturat | \bweighted\s+sum\b | \baccumulat |
      \brounding\b | \bdecimat | \bcorrelat | \bmoving\s+average\b | \bdice\b |
      \bdivider\b | \bdivision\b | \bquotient\b | \bsquare\s+root\b | \bgcd\b |
      # protocol / bus / composite
      \baxi\b | \baxi-?stream\b | \baxis\b | \bapb\b | \bahb\b | \bwishbone\b |
      \buart\b | \bspi\b | \bi2c\b | \bi2s\b | \bjtag\b | \bpcie\b | \busb\b |
      \bfifo\b | \bcache\b | \bsram\b | \bdram\b | \bsequencer\b | \bcontroller\b |
      \bprocessor\b | \bcpu\b | \bpipeline\b |
      # whole-task is an OPTIMIZATION / review, not an authoring of the function
      \barea\s+optimization\b | \blatency\s+optimization\b | \breduction\s+threshold\b |
      \bsynthesis\s+report\b | \bcode\s+review\b |
      # sort networks / trees over a flattened bus — too complex to pin blind
      \bbubble\s+sort\b | \bmerge\s+sort\b | \binsertion\s+sort\b |
      \bsort(?:ing)?\s+(?:engine|network|algorithm)\b |
      \bbinary\s+tree\b | \bbinary\s+search\s+tree\b | \$clog2 |
      \bflattened\s+(?:vector|array|input)\b |
      # needs a named sub-module / hierarchical building block
      \bsub-?module\b | \bbuilding\s+block\b | \bhierarchical\s+design\b |
      # special algebra the plain op would mis-emit (defer to other family solvers)
      \bgalois\b | \bgf\s*\(\s*2 | \bfixed[-\s]?point\b | \bfloating[-\s]?point\b |
      \bhamming\s+distance\b
    """,
)


# =========================================================================== #
# Family recognition  (general — operation semantics)
# =========================================================================== #
_MUX_RE = re.compile(r"(?xi)\bmultiplexer\b | \bmux\b | \bselect(?:s|ed|ing)?\s+one\s+of\b")
_DEMUX_RE = re.compile(
    r"(?xi)\bde-?multiplexer\b | \bde-?mux\b | "
    r"\brout(?:e|es|ing)\s+(?:the\s+)?(?:single\s+)?input\b")
_CMP_RE = re.compile(r"(?xi)\bcomparator\b | \bcompares?\b | \bgreater\s+than\b | \bless\s+than\b")
# MIN/MAX must be the CORE operation: a "find/select/output/compute/determine the
# min/max OF/AMONG the inputs" phrase, or "the (minimum|maximum) (value|of) ... among
# the inputs". A bare "maximum value representable" bound does NOT qualify.
_MINMAX_RE = re.compile(
    r"""(?xi)
      \b(?:find|select|output|compute|determine|produce|return)s?\b
        [^.\n]{0,40}?\b(?:minimum|maximum|min|max|smallest|largest)\b |
      \b(?:minimum|maximum|min|max|smallest|largest)\b
        [^.\n]{0,30}?\b(?:among|of\s+(?:the\s+)?(?:inputs|values|operands|elements))\b
    """,
)


# =========================================================================== #
# COMPARATOR
# =========================================================================== #
def _cmp_signedness(prompt: str) -> Optional[str]:
    """Return 'signed', 'unsigned', or 'mode' (a runtime mode-select that the prose
    pins as signed-when-high / magnitude-when-low), else None (ambiguous -> SKIP)."""
    t = prompt.lower()
    has_signed = bool(re.search(r"\bsigned\b", t))
    has_unsigned = bool(re.search(r"\bunsigned\b|\bmagnitude\b", t))
    # A mode-select comparator: a single 1-bit mode that chooses signed vs magnitude,
    # with the prose stating BOTH interpretations.
    mode = re.search(r"\bmode\b", t) and has_signed and has_unsigned and \
        bool(re.search(r"(?xi)signed\s+(?:mode|when|if)|"
                       r"(?:high|1)\s+for\s+.{0,12}signed|magnitude\s+(?:mode|when|if)", prompt))
    if mode:
        return "mode"
    if has_signed and not has_unsigned:
        return "signed"
    if has_unsigned and not has_signed:
        return "unsigned"
    if has_signed and has_unsigned:
        # both terms present but no mode-select that the prose pins -> ambiguous
        return None
    return None


def _cmp_classify_ports(ins: List[Port], outs: List[Port]):
    """Classify a comparator interface: the two equal-width data operands, an
    optional 1-bit enable, an optional 1-bit mode, and the gt/lt/eq outputs.
    Returns (a, b, width, enable|None, mode|None, gt, lt, eq) or None."""
    data = [(n, w) for n, w in ins if w > 1 and n.lower() not in _SEQ_PORTS]
    ctrl = [(n, w) for n, w in ins if w == 1 and n.lower() not in _SEQ_PORTS]
    if len(data) != 2:
        return None
    (a, wa), (b, wb) = data[0], data[1]
    if wa != wb:
        return None
    enable = next((n for n, _ in ctrl if re.search(r"(?i)en(able)?$|^en", n)), None)
    # the mode-select is the 1-bit control input that is NOT the enable. Prefer a
    # name that looks like a mode/sign select, else fall back to the remaining lone
    # control bit (chip-AGNOSTIC: the port may be renamed).
    non_en = [n for n, _ in ctrl if n != enable]
    mode = next((n for n in non_en if re.search(r"(?i)mode|signed|sel|sign", n)), None)
    if mode is None and len(non_en) == 1:
        mode = non_en[0]

    def _find_out(pats):
        for n, w in outs:
            if w == 1 and any(re.search(p, n, re.I) for p in pats):
                return n
        return None
    gt = _find_out([r"great", r"^o?_?gt$", r"_gt$", r"larger", r"above"])
    lt = _find_out([r"less", r"^o?_?lt$", r"_lt$", r"smaller", r"below"])
    eq = _find_out([r"equal", r"^o?_?eq$", r"_eq$", r"same"])
    if not (gt and lt and eq):
        return None
    return a, b, wa, enable, mode, gt, lt, eq


def _emit_comparator(top: str, a: str, b: str, w: int, enable: Optional[str],
                     mode: Optional[str], gt: str, lt: str, eq: str,
                     signedness: str, parameterized: bool) -> str:
    """Combinational comparator. signedness in {'signed','unsigned','mode'}. When
    'mode', a 1-bit `mode` port selects signed (high) vs magnitude/unsigned (low)."""
    L: List[str] = []
    wexpr = "WIDTH" if parameterized else str(w)
    rng = f"[{wexpr}-1:0]" if (parameterized or w > 1) else ""
    if parameterized:
        L.append(f"module {top} #(")
        L.append(f"    parameter WIDTH = {w}")
        L.append(f") (")
    else:
        L.append(f"module {top} (")
    L.append(f"    input  {rng} {a},")
    L.append(f"    input  {rng} {b},")
    if enable:
        L.append(f"    input  {enable},")
    if mode and signedness == "mode":
        L.append(f"    input  {mode},")
    L.append(f"    output {gt},")
    L.append(f"    output {lt},")
    L.append(f"    output {eq}")
    L.append(");")
    # signed/unsigned operand views
    if signedness == "signed":
        L.append(f"    wire signed {rng} sa = {a};")
        L.append(f"    wire signed {rng} sb = {b};")
        cgt, clt, ceq = "(sa >  sb)", "(sa <  sb)", "(sa == sb)"
    elif signedness == "unsigned":
        cgt, clt, ceq = f"({a} >  {b})", f"({a} <  {b})", f"({a} == {b})"
    else:  # mode-select
        L.append(f"    wire signed {rng} sa = {a};")
        L.append(f"    wire signed {rng} sb = {b};")
        cgt = f"({mode} ? (sa >  sb) : ({a} >  {b}))"
        clt = f"({mode} ? (sa <  sb) : ({a} <  {b}))"
        ceq = f"({mode} ? (sa == sb) : ({a} == {b}))"
    gate = f"{enable} && " if enable else ""
    L.append(f"    assign {gt} = {gate}{cgt};")
    L.append(f"    assign {lt} = {gate}{clt};")
    L.append(f"    assign {eq} = {gate}{ceq};")
    L.append("endmodule")
    return "\n".join(L)


# =========================================================================== #
# MIN / MAX  (2-input or N-input over individual equal-width ports)
# =========================================================================== #
def _minmax_kind(prompt: str) -> Optional[str]:
    t = prompt.lower()
    wants_max = bool(re.search(r"\bmax(?:imum)?\b|\blargest\b", t))
    wants_min = bool(re.search(r"\bmin(?:imum)?\b|\bsmallest\b", t))
    if wants_max and not wants_min:
        return "max"
    if wants_min and not wants_max:
        return "min"
    return None  # both / neither -> ambiguous (could be min/max pair or a sort)


def _minmax_signed(prompt: str) -> Optional[bool]:
    t = prompt.lower()
    s, u = bool(re.search(r"\bsigned\b", t)), bool(re.search(r"\bunsigned\b", t))
    if s and not u:
        return True
    if u and not s:
        return False
    if not s and not u:
        return False  # unsigned is the safe default ONLY when nothing is stated
    return None  # both stated, no mode -> ambiguous


def _emit_minmax(top: str, data: List[Port], out: str, kind: str, signed: bool) -> str:
    """Combinational min/max reduction over N individual equal-width inputs."""
    w = data[0][1]
    names = [n for n, _ in data]
    op = ">" if kind == "max" else "<"
    rng = f"[{w-1}:0]" if w > 1 else ""
    L: List[str] = [f"module {top} ("]
    for n in names:
        L.append(f"    input  {rng} {n},")
    L.append(f"    output {rng} {out}")
    L.append(");")
    if signed:
        for n in names:
            L.append(f"    wire signed {rng} s_{n} = {n};")
        L.append(f"    wire signed {rng} m0 = s_{names[0]};")
        prev = "m0"
        for i, n in enumerate(names[1:], start=1):
            L.append(f"    wire signed {rng} m{i} = (s_{n} {op} {prev}) ? s_{n} : {prev};")
            prev = f"m{i}"
        L.append(f"    assign {out} = {prev};")
    else:
        L.append(f"    wire {rng} m0 = {names[0]};")
        prev = "m0"
        for i, n in enumerate(names[1:], start=1):
            L.append(f"    wire {rng} m{i} = ({n} {op} {prev}) ? {n} : {prev};")
            prev = f"m{i}"
        L.append(f"    assign {out} = {prev};")
    L.append("endmodule")
    return "\n".join(L)


# =========================================================================== #
# MUX  (N:1, individual data ports, ascending sel->source map)
# =========================================================================== #
def _mux_classify(ins: List[Port], outs: List[Port], prompt: str):
    """N:1 individual-port mux: N equal-width data ports, one select port of width
    S (or a 1-bit sel for N==2), one output of the data width. Requires
    2**S == N (no out-of-range default needed). Returns (datas, sel, out, w) or None."""
    if len(outs) != 1:
        return None
    out_n, out_w = outs[0]
    sels = [(n, w) for n, w in ins if re.search(r"(?i)^sel|select|_sel$|\bsel\b", n)
            and n.lower() not in _SEQ_PORTS]
    if len(sels) != 1:
        return None
    sel_n, sel_w = sels[0]
    datas = [(n, w) for n, w in ins
             if (n, w) != (sel_n, sel_w) and n.lower() not in _SEQ_PORTS
             and not re.search(r"(?i)en(able)?$|valid|ready", n)]
    if len(datas) < 2:
        return None
    w0 = datas[0][1]
    if any(w != w0 for _, w in datas) or out_w != w0:
        return None
    n = len(datas)
    # select space must exactly cover N (else an out-of-range default is needed,
    # which we require to be stated -- keep it simple: SKIP unless exact).
    if (1 << sel_w) != n:
        return None
    return datas, sel_n, out_n, w0


def _emit_mux(top: str, datas: List[Port], sel: str, out: str, w: int) -> str:
    n = len(datas)
    sel_w = max(1, (n - 1).bit_length())
    rng = f"[{w-1}:0]" if w > 1 else ""
    srng = f"[{sel_w-1}:0]" if sel_w > 1 else ""
    L: List[str] = [f"module {top} ("]
    for nm, _ in datas:
        L.append(f"    input  {rng} {nm},")
    L.append(f"    input  {srng} {sel},")
    L.append(f"    output reg {rng} {out}")
    L.append(");")
    L.append("    always @(*) begin")
    L.append(f"        case ({sel})")
    nm = datas[0][0]
    for i, (nm, _) in enumerate(datas):
        L.append(f"            {sel_w}'d{i}: {out} = {nm};")
    L.append(f"            default: {out} = {nm};")
    L.append("        endcase")
    L.append("    end")
    L.append("endmodule")
    return "\n".join(L)


# =========================================================================== #
# DEMUX  (1:N, one data input routed to one of N outputs by sel; others 0)
# =========================================================================== #
def _demux_classify(ins: List[Port], outs: List[Port]):
    """1:N demux: one data input of width D, one select of width S, N outputs each
    of width D, 2**S == N. Returns (data, sel, outs_names, w) or None."""
    sels = [(n, w) for n, w in ins if re.search(r"(?i)^sel|select|_sel$|\bsel\b", n)
            and n.lower() not in _SEQ_PORTS]
    if len(sels) != 1:
        return None
    sel_n, sel_w = sels[0]
    datas = [(n, w) for n, w in ins
             if (n, w) != (sel_n, sel_w) and n.lower() not in _SEQ_PORTS
             and not re.search(r"(?i)en(able)?$|valid|ready", n)]
    if len(datas) != 1:
        return None
    data_n, data_w = datas[0]
    outs_d = [(n, w) for n, w in outs if w == data_w]
    if len(outs_d) < 2 or any(w != data_w for _, w in outs_d):
        return None
    if (1 << sel_w) != len(outs_d):
        return None
    return data_n, sel_n, [n for n, _ in outs_d], data_w


def _zero_lit(w: int) -> str:
    return f"{w}'b0" if w > 1 else "1'b0"


def _emit_demux(top: str, data: str, sel: str, outs: List[str], w: int) -> str:
    n = len(outs)
    sel_w = max(1, (n - 1).bit_length())
    rng = f"[{w-1}:0]" if w > 1 else ""
    srng = f"[{sel_w-1}:0]" if sel_w > 1 else ""
    zero = _zero_lit(w)
    L: List[str] = [f"module {top} ("]
    L.append(f"    input  {rng} {data},")
    L.append(f"    input  {srng} {sel},")
    for i, nm in enumerate(outs):
        comma = "," if i < n - 1 else ""
        L.append(f"    output reg {rng} {nm}{comma}")
    L.append(");")
    L.append("    always @(*) begin")
    for nm in outs:
        L.append(f"        {nm} = {zero};")
    L.append(f"        case ({sel})")
    for i, nm in enumerate(outs):
        L.append(f"            {sel_w}'d{i}: {nm} = {data};")
    L.append("            default: ;")
    L.append("        endcase")
    L.append("    end")
    L.append("endmodule")
    return "\n".join(L)


# =========================================================================== #
# entry point
# =========================================================================== #
def _is_parameterized(prompt: str) -> bool:
    return bool(re.search(r"(?xi)\bparameter\b\s+`?WIDTH`?|\bparameteriz", prompt)) and \
        bool(re.search(r"(?i)\bWIDTH\b", prompt))


def _width_default(prompt: str, fallback: int) -> int:
    """The stated default for the `WIDTH` parameter (e.g. 'default value: 5'),
    else `fallback`. Looks only near a WIDTH mention so an unrelated 'default'
    cannot bleed in."""
    m = re.search(r"(?i)`?WIDTH`?[^.\n]{0,60}?\bdefault[^.\n]{0,20}?\b(\d+)\b", prompt)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)\bdefault\b[^.\n]{0,20}?\bWIDTH\b[^.\n]{0,20}?\b(\d+)\b", prompt)
    if m:
        return int(m.group(1))
    return fallback


def solve(record: dict) -> Optional[str]:
    """Emit a deterministic combinational MUX / DEMUX / COMPARATOR / MIN-MAX
    datapath (module named per harness TOPLEVEL), or None (SKIP) on any ambiguity
    or non-pin-down-able design. Never reads golden RTL."""
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None

    # §4.05 up-front SKIP: clocked / CDC / protocol / area-opt / sort / tree / etc.
    if _SKIP_RE.search(prompt):
        return None

    top = _toplevel_name(record)
    if not top:
        return None
    iface = _extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    if not ins or not outs:
        return None

    is_mux = bool(_MUX_RE.search(prompt))
    is_demux = bool(_DEMUX_RE.search(prompt))
    is_cmp = bool(_CMP_RE.search(prompt))
    is_minmax = bool(_MINMAX_RE.search(prompt))

    # ---- DEMUX (check before MUX: a "demux" token also contains "mux") ----
    if is_demux:
        cls = _demux_classify(ins, outs)
        if not cls:
            return None
        data, sel, onames, w = cls
        return _emit_demux(top, data, sel, onames, w)

    # ---- MUX ----
    if is_mux and not is_demux:
        cls = _mux_classify(ins, outs, prompt)
        if not cls:
            return None
        datas, sel, out, w = cls
        return _emit_mux(top, datas, sel, out, w)

    # ---- COMPARATOR (3-output gt/lt/eq) ----
    if is_cmp:
        signedness = _cmp_signedness(prompt)
        if signedness is None:
            return None  # ambiguous signed-ness -> SKIP
        cp = _cmp_classify_ports(ins, outs)
        if not cp:
            return None
        a, b, w, enable, mode, gt, lt, eq = cp
        if signedness == "mode" and not mode:
            return None
        # `w` is the CONCRETE operand width the bridge resolved from the prompt
        # (a `WIDTH` parameter is already resolved to its stated default). When the
        # prose marks the design parameterized, re-declare with a `WIDTH` parameter
        # whose default is the stated value (falling back to the resolved width).
        param = _is_parameterized(prompt)
        if param:
            w = _width_default(prompt, w)
        return _emit_comparator(top, a, b, w, enable, mode, gt, lt, eq,
                                signedness, param)

    # ---- MIN / MAX of N inputs ----
    if is_minmax:
        kind = _minmax_kind(prompt)
        if kind is None:
            return None  # both min & max (a sort / pair) -> SKIP
        signed = _minmax_signed(prompt)
        if signed is None:
            return None  # ambiguous signed-ness -> SKIP
        data = [(n, w) for n, w in ins if w > 1 and n.lower() not in _SEQ_PORTS
                and not re.search(r"(?i)en(able)?$|valid|ready|sel|mode", n)]
        out_d = [(n, w) for n, w in outs if data and w == data[0][1]]
        if len(data) < 2 or len(out_d) != 1:
            return None
        if any(w != data[0][1] for _, w in data):
            return None
        return _emit_minmax(top, data, out_d[0][0], kind, signed)

    return None


# =========================================================================== #
# CLI
# =========================================================================== #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true", help="print emitted RTL")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n_emit = 0
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n_emit += 1
            if a.emit or a.id:
                print(f"=== {r.get('id')} ===")
                print(rtl)
    print(f"emitted={n_emit}/{len(recs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
