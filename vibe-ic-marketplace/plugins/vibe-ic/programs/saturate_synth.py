#!/usr/bin/env python3
"""saturate_synth.py — deterministic SOLVER for the CVDP SATURATE / CLAMP /
THRESHOLD + SIGN-DATAPATH family the existing solvers miss.

WHY a dedicated CVDP solver (and not the bridge / arith_variants):
  KEY INSIGHT (owner directive 2026-06-23): a whole shape of CVDP "code generation"
  problems is a SINGLE purely-combinational data-mapping function over one or two
  operands — NOT an `a+b`/`a*b` arithmetic op and NOT a registry shape:
    * CLAMP / SATURATE an operand to a STATED [lo, hi] range (out = clip(x,lo,hi));
    * THRESHOLD / comparator-to-FLAG (out = (x >/>=/</<= T) ? .. : ..);
    * ABSOLUTE VALUE of a signed operand (out = |x|);
    * SIGN-EXTEND / ZERO-EXTEND an operand from W to M bits;
    * NEGATE / two's-complement (out = -x = ~x + 1);
    * SIGNED <-> UNSIGNED reinterpret / conditional-select / conditional-clip.

  These are MISSED by the existing solvers:
    * arith_variants_synth only emits when it finds an `a`/`b` operand PAIR and
      an add/sub/mul VERB; a single-operand abs / sign-extend / negate, or a
      clamp-to-explicit-[lo,hi] (not the add-then-saturate it handles), has no `a+b`
      verb and so it returns None.
    * cvdp_atomic_bridge SHORT-CIRCUITS `\\bsaturat`/`\\bclamp` to SKIP outright, and
      its registry path has no canonical for "clamp x to [lo,hi]" / "abs(x)" /
      "sign-extend W->M" / "x > T ? p : q", so it emits nothing (or, worse, a
      registry shape that does not match the function).

  This solver fills exactly that gap. It reads the interface from the CVDP harness
  (the cocotb test's `dut.<sig>` signals + the .env TOPLEVEL + prose/table widths),
  recognizes the FUNCTION, parses the STATED bound / threshold / from-to widths /
  signed-ness, and emits a functionally-correct COMBINATIONAL datapath.

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding) — return None (SKIP) whenever:
  * the clamp/saturate BOUND ([lo,hi]) is not stated (literal or named param);
  * the THRESHOLD value, the comparison sense (>, >=, <, <=), or the two select
    results are not stated;
  * the operation's SIGNED-NESS is needed (abs / signed clamp / signed compare /
    sign-extend) but not stated (signed vs unsigned semantics differ);
  * the sign-extend / zero-extend FROM-width or TO-width is not stated;
  * the design is composite / sequential / a protocol / memory / a multi-op ALU /
    an FSM-pinned or latency-pinned wrapper / a LINT-or-edit task — i.e. not a
    single recognizable combinational mapping function;
  * the interface cannot be unambiguously extracted (never guess a width, a port, a
    direction, or a polarity);
  * the golden/reference RTL is NEVER read (output['context'] is empty in v1.1.0;
    even if present, only a module HEADER would be a hint, never its body).

A wrong clamp / threshold / sign datapath is far worse than an honest skip.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC (no design-name keys), pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

Port = Tuple[str, int]  # (name, width)

_NOT_A_PORT_NAME = {
    "signed", "unsigned", "wire", "reg", "logic", "input", "output", "inout",
    "module", "endmodule", "parameter", "localparam", "for", "if", "begin", "end",
}

# Clock / reset / handshake / control names that are never a DATA operand.
_SEQ_PORTS = {"clk", "clock", "i_clk", "i_clock", "rst", "reset", "rstn", "rst_n",
              "i_rst_n", "i_rst_b", "resetn", "reset_n", "areset", "aresetn",
              "arst_n", "clk_en", "clken", "srst", "enable", "en", "i_enable"}


# --------------------------------------------------------------------------- #
# §4.05 SKIP cues (keyed on SEMANTICS / INTERFACE vocabulary, never a design name).
# A composite / protocol / memory / multi-op design is not a single mapping fn.
# --------------------------------------------------------------------------- #
_COMPOSITE_RE = re.compile(
    r"""(?xi)
      \baxi\b | \baxi-?lite\b | \baxi-?stream\b | \baxis\b | \bapb\b | \bahb\b |
      \bwishbone\b | \bavalon\b | \btilelink\b | \buart\b | \bspi\b | \bi2c\b |
      \bi2s\b | \bjtag\b | \bpcie\b | \busb\b |
      \bfifo\b | \blifo\b | \bfilo\b | \bcache\b | \bsram\b | \bdram\b |
      \bregister\s+file\b | \bregfile\b | \bmemory\b | \bram\b | \brom\b |
      \bprocessor\b | \bcpu\b | \balu\b | \bopcode\b | \binstruction\b |
      \bsequencer\b | \bcontroller\b | \bstate\s+machine\b | \bfsm\b |
      \bperceptron\b | \bneuron\b | \bsobel\b | \bgaussian\b | \bconvolution\b |
      \bfir\b | \biir\b | \bfft\b | \bdft\b | \bfilter\b | \bcorrelat |
      \baccumulat | \bmoving\s+average\b | \bwindow\b | \bmatrix\b |
      \bcrc\b | \bscrambl | \bencoder\b | \bdecoder\b | \bmapper\b |
      \belevator\b | \bfan\b | \binterrupt\b | \bsorter\b | \bcounter\b |
      \bdivider\b | \bdivision\b | \bgcd\b | \bjitter\b
    """,
)

# Function-changing special algebra — a plain compare/clamp would be WRONG.
_SPECIAL_ALGEBRA_RE = re.compile(
    r"""(?xi)
      \bgalois\b | \bgf\s*\(\s*2 | \bfinite\s+field\b | \bcarry[-\s]?less\b |
      \bmodular\s+(?:arithmetic|reduction)\b | \bmontgomery\b |
      \bbcd\b | \bbinary[-\s]coded[-\s]decimal\b |
      \bfixed[-\s]?point\b | \bfloating[-\s]?point\b | \bIEEE[-\s]?754\b |
      \bqam\b
    """,
)

# A LINT / debug / "fix the bug" / "complete the partial module" edit-task is NOT a
# clean function emit — we cannot reproduce an unknown partial body. SKIP.
_EDIT_TASK_RE = re.compile(
    r"""(?xi)
      \blint\s+(?:code\s+)?review\b | \bresolve\s+all\s+lint\b |
      \bfix\s+the\s+bug | \bdebug\s+the\b | \bincorrect\s+behavior\b |
      \bexhibits\s+(?:incorrect|wrong)\b | \bedge\s+cases?\b.{0,40}\bbug
    """,
)


# --------------------------------------------------------------------------- #
# Harness access (.env TOPLEVEL + cocotb test text)
# --------------------------------------------------------------------------- #
def _harness_files(record: dict) -> Dict[str, str]:
    h = record.get("harness") or {}
    files = h.get("files") or {}
    return {k: v for k, v in files.items() if isinstance(v, str)}


def _toplevel(record: dict) -> Optional[str]:
    for k, v in _harness_files(record).items():
        if k.endswith(".env"):
            m = re.search(r"^\s*TOPLEVEL\s*=\s*(\S+)", v, re.M)
            if m:
                return m.group(1)
    return None


def _cocotb_test_text(record: dict) -> str:
    for k, v in _harness_files(record).items():
        if re.search(r"test_.*\.py$", k) and "runner" not in k:
            return v
    return ""


# --------------------------------------------------------------------------- #
# Latency / FSM-state PROTOCOL-PIN detection — a combinational mapping cannot
# match a cycle-pinned protocol or a pinned FSM state encoding -> SKIP.
# --------------------------------------------------------------------------- #
_LATENCY_PIN_RE = re.compile(
    r"(?xi) assert\s+\w*latency\w*\s*== | \blatency\s*==\s*\w+")
_FSM_STATE_PIN_RE = re.compile(
    r"(?i)assert\s+dut\.\w*(?:status|state)\w*\.value\s*==")


def _has_protocol_pin(tb: str) -> bool:
    return bool(_LATENCY_PIN_RE.search(tb) or _FSM_STATE_PIN_RE.search(tb))


# --------------------------------------------------------------------------- #
# cocotb dut.<signal> direction inference + PARAMETER filtering.
# A cocotb PARAMETER is read with `int(dut.NAME.value)` to CONFIGURE the run (a
# python int used as a width / loop bound), not asserted as a DUT output. They are
# ALL-CAPS snake (DATA_WIDTH, WIDTH, MAX_VAL, …); we drop them so they never become
# phantom ports.
# --------------------------------------------------------------------------- #
_PARAM_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$|^[A-Z]{3,}$")


def _cocotb_params(tb: str) -> set:
    params = set()
    for m in re.finditer(r"\b\w+\s*=\s*int\(\s*dut\.(\w+)\.value\s*\)", tb):
        if _PARAM_NAME_RE.match(m.group(1)):
            params.add(m.group(1))
    for m in re.finditer(r"dut\.([A-Z][A-Z0-9_]+)\.value", tb):
        if _PARAM_NAME_RE.match(m.group(1)):
            params.add(m.group(1))
    return params


def _cocotb_clocks(tb: str) -> List[str]:
    clks = list(dict.fromkeys(re.findall(r"Clock\(\s*dut\.(\w+)\b", tb)))
    if not clks:
        edges = list(dict.fromkeys(
            re.findall(r"(?:Rising|Falling)Edge\(\s*dut\.(\w+)", tb)))
        driven = set(re.findall(r"dut\.(\w+)\.value\s*=(?!=)", tb))
        edges = [e for e in edges if e not in driven
                 and re.search(r"(?i)cl(?:k|ock)", e)]
        clks = edges
    return clks


def _cocotb_io(tb: str) -> Tuple[List[str], List[str], bool]:
    """(inputs, outputs, sequential?) from the cocotb test. A signal ASSIGNED
    (`dut.X.value = ...`, not `==`) is an INPUT; a signal only READ is an OUTPUT.
    Parameters and clocks are removed from data ports; `sequential` is True if a
    Clock()/clock-edge is driven (the design is clocked -> not pure combinational)."""
    driven = list(dict.fromkeys(re.findall(r"dut\.(\w+)\.value\s*=(?!=)", tb)))
    read = list(dict.fromkeys(
        re.findall(r"=\s*dut\.(\w+)\.value\b", tb)
        + re.findall(r"int\(\s*dut\.(\w+)\.value", tb)
        + re.findall(r"dut\.(\w+)\.value\.(?:integer|signed_integer)", tb)
        + re.findall(r"dut\.(\w+)\.value\s*[=!]=", tb)
        + re.findall(r"while\s+(?:\(\s*)?dut\.(\w+)\.value", tb)))
    params = _cocotb_params(tb)
    clks = _cocotb_clocks(tb)
    driven_set = set(driven)
    seq = bool(clks)
    ins = [s for s in driven if s not in params and s not in clks]
    outs = [s for s in read if s not in driven_set and s not in params
            and s not in clks]
    return ins, outs, seq


# --------------------------------------------------------------------------- #
# CVDP-native `### Inputs/Outputs` markdown port reader (+ table form).
# --------------------------------------------------------------------------- #
def _param_defaults(prompt: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    # `WIDTH ... default value of 5` / `... default is 5` / `... default = 5`.
    for m in re.finditer(
            r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?(?:\s+of)?\s*"
            r"(?:is\s+|=\s*)?`?(\d+)`?", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    # `WIDTH ... (default value: 5)` / `(default: 5)` (parenthesized colon form).
    for m in re.finditer(
            r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?\s*:\s*`?(\d+)`?",
            prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in re.finditer(r"parameter\s+(?:int\s+)?([A-Z][A-Z0-9_]+)\s*=\s*(\d+)",
                         prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def _width_from_cell(cell: str, params: Dict[str, int]) -> Optional[int]:
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    m = re.search(r"\[\s*`?([A-Za-z_]\w*)`?\s*-\s*1\s*:\s*0\s*\]", cell)
    if m and m.group(1) in params:
        return params[m.group(1)]
    # a bare named width-token cell: `WIDTH` -> the parameter's default value.
    m = re.fullmatch(r"\s*`?([A-Za-z_]\w*)`?\s*", cell)
    if m and m.group(1) in params:
        return params[m.group(1)]
    m = re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*-?\s*bit\b", cell, re.I) or re.search(r"\(\s*1\s*\)", cell):
        return 1
    return None


_PORT_LINE_RE = re.compile(
    r"""^\s*[-*]?\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*\(([^)]*)\)""", re.X)
# a markdown port TABLE row: | `name` | dir | width | ... |
_TABLE_ROW_RE = re.compile(r"^\s*\|\s*`?([A-Za-z_]\w*)`?\s*\|(.*)\|\s*$")


def _section_ports(prompt: str, header_words, params) -> List[Port]:
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
        if not m:
            continue
        name, cell = m.group(1), m.group(2)
        if name.lower() in _NOT_A_PORT_NAME:
            continue
        w = _width_from_cell(cell, params)
        if w is None:
            if re.search(r"(?i)(clk|clock|rst|reset|_n$|en$|enable|valid|ready|"
                         r"mode|sel|start|stop|load|done|flag|greater|less|equal|"
                         r"overflow|underflow|zero|sign|gt|lt|eq)", name):
                w = 1
            else:
                continue
        ports.append((name, w))
    return ports


def _table_ports(prompt: str, params) -> Tuple[List[Port], List[Port]]:
    """Parse a markdown port TABLE: | Signal | Direction | Bit Width | ... |.
    Direction column distinguishes input vs output; width column gives the width
    (literal, `WIDTH` param, or `1`). Used when ports are stated as a table."""
    lines = prompt.splitlines()
    ins: List[Port] = []
    outs: List[Port] = []
    # find the header row that has both a "direction" and a "width"/"bit" column.
    hdr_idx = None
    cols = None
    for i, ln in enumerate(lines):
        if "|" not in ln:
            continue
        cells = [c.strip().lower() for c in ln.strip().strip("|").split("|")]
        if any("direction" in c for c in cells) and any(
                ("width" in c or "bit" in c) for c in cells):
            if i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$",
                                               lines[i + 1]):
                hdr_idx = i
                cols = cells
                break
    if hdr_idx is None:
        return [], []
    di = next((j for j, c in enumerate(cols) if "direction" in c), None)
    wi = next((j for j, c in enumerate(cols) if "width" in c or "bit" in c), None)
    ni = 0  # the signal/name column is conventionally first
    for ln in lines[hdr_idx + 2:]:
        if "|" not in ln or not ln.strip().startswith("|"):
            break
        cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
        if len(cells) <= max(di or 0, wi or 0, ni):
            continue
        name = cells[ni]
        if not re.fullmatch(r"[A-Za-z_]\w*", name) or name.lower() in _NOT_A_PORT_NAME:
            continue
        direction = cells[di].lower() if di is not None else ""
        w = _width_from_cell(cells[wi], params) if wi is not None else None
        if w is None:
            # An unparseable width cell: a control/flag-named port is 1-bit by
            # convention; otherwise the width is genuinely UNRESOLVED — emit
            # width 0 as a sentinel so the interface resolver SKIPs (§4.05: never
            # guess a data-path width, e.g. a named `WIDTH` param with no default).
            if re.search(r"(?i)(clk|clock|rst|reset|_n$|^en$|enable|valid|ready|"
                         r"mode|sel|start|stop|load|done|flag|greater|less|equal|"
                         r"^gt$|^lt$|^eq$|overflow|underflow|zero$|sign$)", name):
                w = 1
            else:
                w = 0  # UNRESOLVED data width sentinel
        if "out" in direction:
            outs.append((name, w))
        elif "in" in direction:
            ins.append((name, w))
    return ins, outs


# --------------------------------------------------------------------------- #
# Width resolution from PROSE (used for cocotb-derived port names).
# --------------------------------------------------------------------------- #
def _prose_width(prompt: str, name: str) -> Optional[int]:
    # (1) explicit bus range tied directly to the name: `name [hi:lo]`.
    m = re.search(rf"\b{re.escape(name)}\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", prompt)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    # (2) the CVDP parenthetical convention: `name (8-bits, [7:0])` / `name (8-bit)`
    #     — the width parenthetical immediately follows the name token. This is the
    #     authoritative per-port width and must win over a stray same-line token.
    m = re.search(
        rf"\b{re.escape(name)}\b[`*]*\s*\(([^)]*)\)", prompt)
    if m:
        cell = m.group(1)
        rm = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
        if rm:
            return abs(int(rm.group(1)) - int(rm.group(2))) + 1
        rm = re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
        if rm:
            return int(rm.group(1))
    # (3) a same-line "N-bit name" / "name ... N-bit" — only when N is ADJACENT
    #     (no other "M-bit" token intervening) to avoid grabbing a neighbour width.
    m = re.search(rf"\b(\d+)\s*-?\s*bits?\s+(?:\w+\s+){{0,3}}{re.escape(name)}\b",
                  prompt, re.I)
    if m:
        return int(m.group(1))
    return None


def _dedup(ports: List[Port]) -> List[Port]:
    seen = set()
    out: List[Port] = []
    for n, w in ports:
        if n in seen or n.lower() in _NOT_A_PORT_NAME:
            continue
        seen.add(n)
        out.append((n, w))
    return out


# --------------------------------------------------------------------------- #
# interface resolution: prefer the cocotb test signals (CVDP's real interface),
# fall back to the markdown `### Inputs/Outputs` section / port table. Widths
# cross-checked from prose / section / table.
# --------------------------------------------------------------------------- #
def _resolve_interface(record: dict, prompt: str, tb: str
                       ) -> Optional[Tuple[List[Port], List[Port], Dict[str, int]]]:
    params = _param_defaults(prompt)

    sec_in = _dedup(_section_ports(prompt, ("inputs", "input ports", "input"),
                                   params))
    sec_out = _dedup(_section_ports(prompt, ("outputs", "output ports", "output"),
                                    params))
    if not (sec_in and sec_out):
        t_in, t_out = _table_ports(prompt, params)
        sec_in = sec_in or _dedup(t_in)
        sec_out = sec_out or _dedup(t_out)

    c_ins, c_outs, _seq = _cocotb_io(tb)
    sec_w = {n.lower(): w for n, w in sec_in + sec_out}

    def _ctrl_w(name: str) -> Optional[int]:
        low = name.lower()
        if low in _SEQ_PORTS or re.search(
                r"(?i)(_n$|^en$|enable|valid|ready|start|stop|mode|sel|load|done|"
                r"clear|flag|greater|less|equal|^gt$|^lt$|^eq$|sign$|overflow|"
                r"underflow|zero$)", name):
            return 1
        return None

    ins: List[Port] = []
    outs: List[Port] = []
    unresolved = False
    if c_ins and c_outs:
        for name in c_ins:
            w = _prose_width(prompt, name)
            if w is None:
                w = sec_w.get(name.lower())
            if w is None:
                w = _ctrl_w(name)
            if not w:  # None or the width-0 UNRESOLVED sentinel -> §4.05 SKIP
                unresolved = True
                continue
            ins.append((name, w))
        for name in c_outs:
            w = _prose_width(prompt, name)
            if w is None:
                w = sec_w.get(name.lower())
            if w is None:
                w = _ctrl_w(name)
            if not w:
                unresolved = True
                continue
            outs.append((name, w))
        ins, outs = _dedup(ins), _dedup(outs)
        if ins and outs and not unresolved:
            return ins, outs, params

    # section/table fallback — reject if ANY port width is the UNRESOLVED sentinel.
    if sec_in and sec_out and all(w for _n, w in sec_in + sec_out):
        return sec_in, sec_out, params
    return None


# --------------------------------------------------------------------------- #
# port classification helpers
# --------------------------------------------------------------------------- #
def _find(ports: List[Port], names) -> Optional[Port]:
    low = {n.lower(): (n, w) for n, w in ports}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


def _clk_port(ports):
    return _find(ports, ("clk", "clock", "i_clk", "i_clock"))


def _rst_port(ports):
    for n, w in ports:
        if re.search(r"(?i)(rst|reset|areset)", n):
            return (n, w)
    return None


_X_NAMES = ("x", "in", "a", "i_a", "data", "data_in", "din", "i_data", "in_data",
            "operand", "i_operand", "value", "i_value", "input_value", "i_in",
            "in_value", "d", "i_d")
_Y_NAMES = ("y", "out", "result", "o_result", "o_out", "data_out", "dout",
            "o_data", "out_data", "o_value", "output_value", "o", "q", "o_q",
            "clamped", "saturated", "abs_out", "o_abs", "neg_out", "o_neg",
            "extended", "o_ext", "y_out")


def _signed(name: str, signed: bool) -> str:
    return f"$signed({name})" if signed else name


# --------------------------------------------------------------------------- #
# bound / threshold / width parsing (LITERAL or named-param)
# --------------------------------------------------------------------------- #
def _num(tok: str) -> Optional[int]:
    tok = tok.strip().strip("`")
    neg = False
    if tok.startswith("-"):
        neg = True
        tok = tok[1:].strip()
    m = re.fullmatch(r"(?:0x([0-9a-fA-F]+)|(\d+)\s*'\s*[hH]([0-9a-fA-F]+)|(\d+))", tok)
    if not m:
        # 2^k form
        mm = re.fullmatch(r"2\s*\^\s*(\d+)\s*-\s*1", tok)
        if mm:
            v = (1 << int(mm.group(1))) - 1
            return -v if neg else v
        mm = re.fullmatch(r"2\s*\^\s*(\d+)", tok)
        if mm:
            v = 1 << int(mm.group(1))
            return -v if neg else v
        return None
    if m.group(1) is not None:
        v = int(m.group(1), 16)
    elif m.group(3) is not None:
        v = int(m.group(3), 16)
    else:
        v = int(m.group(4))
    return -v if neg else v


def _parse_value(prompt: str, params: Dict[str, int], frag: str) -> Optional[int]:
    """Resolve a value token to an int: a literal (dec/hex/2^k) or a named
    parameter present in `params`. None if unresolved."""
    frag = frag.strip().strip("`")
    v = _num(frag)
    if v is not None:
        return v
    if frag in params:
        return params[frag]
    return None


_VAL_TOK = r"(-?(?:0x[0-9a-fA-F]+|\d+\s*'\s*[hH][0-9a-fA-F]+|2\s*\^\s*\d+(?:\s*-\s*1)?|\d+)|[A-Z][A-Z0-9_]*)"
_RANGE_RE = re.compile(
    r"(?xi)"
    r"(?:clamp|saturat\w*|clip|bound|limit|constrain)\w*"
    r"[^.\n]{0,40}?"
    r"(?:to\s+(?:the\s+)?(?:range\s+)?|within\s+(?:the\s+)?(?:range\s+)?|between\s+)"
    r"\[?\s*`?" + _VAL_TOK + r"`?\s*"
    r"(?:,|\s+to\s+|\s+and\s+|\s*:\s*)\s*"
    r"`?" + _VAL_TOK + r"`?\s*\]?",
)


def _parse_range(prompt: str, params: Dict[str, int]
                 ) -> Optional[Tuple[int, int]]:
    """Parse a STATED [lo, hi] clamp range. Returns (lo, hi) or None."""
    for m in _RANGE_RE.finditer(prompt):
        lo = _parse_value(prompt, params, m.group(1))
        hi = _parse_value(prompt, params, m.group(2))
        if lo is not None and hi is not None and hi > lo:
            return lo, hi
    # an explicit "(0-15)" / "range 0 to 15" form near a clamp/saturat word.
    for m in re.finditer(
            r"(?i)(?:clamp|saturat\w*|clip|range|valid)[^.\n]{0,30}?"
            r"\(?\s*(\d+)\s*(?:-|to|,)\s*(\d+)\s*\)?", prompt):
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi > lo:
            return lo, hi
    return None


_THRESH_RE = re.compile(
    r"""(?xi)
      (?:if|when|where)?\s*
      `?(\w+)`?\s*
      (>=|<=|>|<)\s*
      `?([0-9][0-9a-fx'^A-F]*|[A-Z][A-Z0-9_]*)`?
    """,
)


# --------------------------------------------------------------------------- #
# RTL emit helpers
# --------------------------------------------------------------------------- #
def _decl(direction: str, name: str, w: int, reg: bool = False) -> str:
    kw = f"{direction} reg" if reg else direction
    return f"    {kw} [{w-1}:0] {name}" if w > 1 else f"    {kw} {name}"


def _module(top: str, in_decls: List[str], out_decls: List[str], body: List[str],
            comment: str) -> str:
    return "\n".join(
        [comment, f"module {top} ("]
        + [",\n".join(in_decls + out_decls), ");"]
        + body + ["endmodule", ""])


def _stated_signed(low: str) -> Optional[bool]:
    """True/False if signed-ness is STATED, else None (unstated)."""
    has_signed = bool(re.search(r"(?<!un)\bsigned\b|two'?s\s+complement|"
                                r"sign\s+bit|signed\s+(?:integer|operand|value|mode)",
                                low))
    has_unsigned = bool(re.search(r"\bunsigned\b|magnitude", low))
    if has_signed and not has_unsigned:
        return True
    if has_unsigned and not has_signed:
        return False
    if has_signed and has_unsigned:
        return None  # both mentioned (dual-mode) — signed-ness is mode-selected
    return None


# =========================================================================== #
# FUNCTION recognition + emit
# =========================================================================== #
def _recognize_and_emit(record: dict, top: str, prompt: str, tb: str,
                        ins: List[Port], outs: List[Port],
                        params: Dict[str, int]) -> Optional[str]:
    low = prompt.lower()

    # purely combinational only: a clock among the ports defeats every shape here.
    if _clk_port(ins) or _rst_port(ins):
        return None

    x = _find(ins, _X_NAMES)
    y = _find(outs, _Y_NAMES)

    # Each detector is SPECIFIC (verb-precise) so at most one fires; "negative"
    # (a sign DESCRIPTION) must NOT trigger negate, "magnitude" alone must NOT
    # trigger abs, etc. Detectors are evaluated in structural-specificity order;
    # crucially, dispatch FALLS THROUGH to the next family when an emitter SKIPs,
    # so a keyword that incidentally matches one family but whose interface fits
    # another is still solved (and an unsolvable record SKIPs at the end).
    has_cmp_flags = bool(
        _find(outs, ("o_greater", "greater", "gt", "o_gt", "a_gt_b", "o_a_gt_b"))
        or _find(outs, ("o_less", "less", "lt", "o_lt", "a_lt_b", "o_a_lt_b"))
        or _find(outs, ("o_equal", "equal", "eq", "o_eq", "a_eq_b", "o_a_eq_b")))
    is_clamp = bool(re.search(r"\bclamp\w*|\bsaturat\w*|\bclip\w*|"
                              r"constrain\w*\s+to|bound\w*\s+to", low))
    is_abs = bool(re.search(r"\babsolute\s+value\b|\babs\s*\(|magnitude\s+of\s+"
                            r"(?:the\s+)?(?:signed\s+)?(?:input|operand|value)", low))
    is_neg = bool(re.search(
        r"\bnegate\b|\bnegation\b|two'?s[-\s]complement\s+negat|"
        r"additive\s+inverse|compute\s+the\s+negative\s+of", low))
    is_ext = bool(re.search(r"sign[-\s]?extend\w*|zero[-\s]?extend\w*|"
                            r"sign[-\s]?extension|zero[-\s]?extension", low))
    is_thresh = has_cmp_flags or bool(re.search(
        r"\bthreshold\w*|\bcomparator\w*|\bcompare\w*|greater\s+than|less\s+than|"
        r"\bexceed\w*|\bflag\b[^.\n]{0,40}(?:>=|<=|>|<)|"
        r"(?:>=|<=|>|<)[^.\n]{0,40}\bflag\b", low))

    # structural comparator (gt/lt/eq flag outputs) is the least-ambiguous shape:
    # try it FIRST when those flag ports exist.
    if has_cmp_flags:
        r = _emit_threshold(top, prompt, low, params, ins, outs)
        if r:
            return r
    # dispatch the single-operand mappings; FALL THROUGH on a SKIP.
    if is_ext:
        r = _emit_extend(top, prompt, low, params, ins, outs, x, y)
        if r:
            return r
    if is_clamp:
        r = _emit_clamp(top, prompt, low, params, ins, outs, x, y)
        if r:
            return r
    if is_abs:
        r = _emit_abs(top, prompt, low, ins, outs, x, y)
        if r:
            return r
    if is_neg:
        r = _emit_negate(top, prompt, low, ins, outs, x, y)
        if r:
            return r
    if is_thresh:
        return _emit_threshold(top, prompt, low, params, ins, outs)
    return None


# --------------------------------------------------------------------------- #
# CLAMP / SATURATE x to a STATED [lo, hi].
# --------------------------------------------------------------------------- #
def _emit_clamp(top, prompt, low, params, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    rng = _parse_range(prompt, params)
    if rng is None:
        return None  # §4.05: unstated bound -> SKIP
    lo, hi = rng
    signed = _stated_signed(low)
    # signed-ness only matters when lo can be negative; if lo >= 0 and the whole
    # range is non-negative, unsigned compare is correct regardless.
    if lo < 0 and signed is None:
        return None  # §4.05: negative bound but signed-ness unstated -> SKIP
    if lo < 0 and signed is False:
        return None  # contradiction: unsigned port cannot hold a negative bound
    xn, xw = x
    yn, yw = y
    use_signed = bool(signed) or lo < 0
    cmp_x = _signed(xn, use_signed) if use_signed else xn
    lo_lit = str(lo) if lo >= 0 else f"-{abs(lo)}"
    hi_lit = str(hi)
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w, reg=(n == yn)) for n, w in outs]
    body = [
        "    always @(*) begin",
        f"        if ({cmp_x} < {_signed(lo_lit, use_signed) if use_signed else lo_lit})",
        f"            {yn} = {lo_lit};",
        f"        else if ({cmp_x} > {_signed(hi_lit, use_signed) if use_signed else hi_lit})",
        f"            {yn} = {hi_lit};",
        "        else",
        f"            {yn} = {xn};",
        "    end",
    ]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational clamp/saturate to "
                   f"[{lo_lit},{hi_lit}] ({'signed' if use_signed else 'unsigned'}); "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# SIGN-EXTEND / ZERO-EXTEND x from W to M.
# --------------------------------------------------------------------------- #
def _emit_extend(top, prompt, low, params, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    is_sign = bool(re.search(r"sign[-\s]?extend|sign[-\s]?extension", low))
    is_zero = bool(re.search(r"zero[-\s]?extend|zero[-\s]?extension", low))
    if is_sign == is_zero:
        return None  # neither or BOTH mentioned ambiguously -> SKIP
    xn, fw = x   # from-width = the input port width
    yn, mw = y   # to-width   = the output port width
    if mw <= fw or fw < 1:
        return None  # §4.05: widths must be stated and M > W
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w) for n, w in outs]
    pad = mw - fw
    if is_sign:
        rhs = f"{{{{{pad}{{{xn}[{fw-1}]}}}}, {xn}}}"
        kind = "sign-extend"
    else:
        rhs = f"{{{{{pad}{{1'b0}}}}, {xn}}}"
        kind = "zero-extend"
    body = [f"    assign {yn} = {rhs};"]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational {kind} {fw}->{mw}; "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# ABSOLUTE VALUE of a signed operand.
# --------------------------------------------------------------------------- #
def _emit_abs(top, prompt, low, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    signed = _stated_signed(low)
    if signed is not True:
        return None  # §4.05: abs is only defined on a SIGNED operand
    xn, xw = x
    yn, yw = y
    if yw < xw:
        return None
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w) for n, w in outs]
    body = [f"    assign {yn} = {xn}[{xw-1}] ? (~{xn} + 1'b1) : {xn};"]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational absolute value (signed); "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# NEGATE / two's-complement.
# --------------------------------------------------------------------------- #
def _emit_negate(top, prompt, low, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    xn, xw = x
    yn, yw = y
    if yw < xw:
        return None
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w) for n, w in outs]
    body = [f"    assign {yn} = (~{xn} + 1'b1);"]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational negate (two's complement); "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# THRESHOLD / comparator-to-flag.
#   * a dual-mode (signed/magnitude) gt/lt/eq comparator with enable; or
#   * a single (x </>/>=/<= T) ? p : q select with a STATED threshold.
# --------------------------------------------------------------------------- #
def _emit_threshold(top, prompt, low, params, ins, outs) -> Optional[str]:
    gt = _find(outs, ("o_greater", "greater", "gt", "o_gt", "a_gt_b", "o_a_gt_b"))
    lt = _find(outs, ("o_less", "less", "lt", "o_lt", "a_lt_b", "o_a_lt_b"))
    eq = _find(outs, ("o_equal", "equal", "eq", "o_eq", "a_eq_b", "o_a_eq_b"))
    a = _find(ins, ("i_a", "a", "in_a", "x", "i_x", "data", "i_data", "in0", "i_in0"))
    b = _find(ins, ("i_b", "b", "in_b", "y", "i_y", "ref", "i_ref", "in1", "i_in1"))
    en = _find(ins, ("i_enable", "enable", "en", "i_en"))
    mode = _find(ins, ("i_mode", "mode", "sel", "i_sel", "signed_mode"))

    # ---- gt/lt/eq comparator-to-flag (the dominant CVDP comparator shape) ----#
    if (gt or lt or eq) and a and b:
        # need at least two of the three flags to be a real comparator.
        if sum(bool(f) for f in (gt, lt, eq)) < 2:
            return None
        if a[1] != b[1] or a[1] < 1:
            return None
        signed = _stated_signed(low)
        has_dual = mode is not None and bool(
            re.search(r"(?i)(signed|magnitude|unsigned)\s+mode", low)) \
            and re.search(r"(?i)magnitude", low) and re.search(r"(?i)signed", low)
        if not has_dual and signed is None:
            return None  # §4.05: single-mode compare but signed-ness unstated
        in_decls = [_decl("input", n, w) for n, w in ins]
        out_decls = [_decl("output", n, w) for n, w in outs]
        an, bn = a[0], b[0]
        if has_dual:
            # mode high => signed compare; low => unsigned magnitude compare.
            # parse which polarity is signed (default: high=signed per CVDP norm).
            high_signed = not bool(re.search(
                r"(?i)(low|0)\D{0,20}signed\s+mode", low))
            sa, sb = f"$signed({an})", f"$signed({bn})"
            sig_cmp = "(%s {op} %s)"
            usig_cmp = "(%s {op} %s)" % (an, bn)
            mn = mode[0]
            sel = mn if high_signed else f"!{mn}"

            def _expr(op):
                return (f"({sel} ? ($signed({an}) {op} $signed({bn})) "
                        f": ({an} {op} {bn}))")
        else:
            su = bool(signed)
            ca, cb = _signed(an, su), _signed(bn, su)

            def _expr(op):
                return f"({ca} {op} {cb})"
        guard = (f"{en[0]} && " if en else "")
        body = []
        if gt:
            body.append(f"    assign {gt[0]} = {guard}{_expr('>')};")
        if lt:
            body.append(f"    assign {lt[0]} = {guard}{_expr('<')};")
        if eq:
            body.append(f"    assign {eq[0]} = {guard}({an} == {bn});")
        return _module(top, in_decls, out_decls, body,
                       "// program-SOLVED combinational comparator-to-flag "
                       + ("(dual signed/magnitude mode)" if has_dual
                          else ("signed" if signed else "unsigned"))
                       + (" with enable" if en else "") + "; deterministic.")

    # ---- single threshold select: out = (x <op> T) ? p : q -------------------#
    x = _find(ins, _X_NAMES)
    y = _find(outs, _Y_NAMES)
    flag = _find(outs, ("flag", "o_flag", "above", "o_above", "exceeded",
                        "o_exceeded", "trigger", "o_trigger"))
    out_t = y or flag
    if not (x and out_t):
        return None
    # need a STATED threshold tied to the operand with an explicit comparison.
    best = None
    for m in _THRESH_RE.finditer(prompt):
        lhs, op, rhs = m.group(1), m.group(2), m.group(3)
        if lhs.lower() != x[0].lower():
            continue
        tv = _parse_value(prompt, params, rhs)
        if tv is None:
            continue
        best = (op, tv)
        break
    if best is None:
        return None  # §4.05: no parseable threshold tied to the operand -> SKIP
    op, tv = best
    signed = _stated_signed(low)
    if (tv < 0) and signed is not True:
        return None
    xn = _signed(x[0], bool(signed)) if signed else x[0]
    # a 1-bit flag output: out = (x <op> T).
    if flag and out_t == flag and flag[1] == 1:
        in_decls = [_decl("input", n, w) for n, w in ins]
        out_decls = [_decl("output", n, w) for n, w in outs]
        body = [f"    assign {flag[0]} = ({xn} {op} {tv});"]
        return _module(top, in_decls, out_decls, body,
                       f"// program-SOLVED combinational threshold flag "
                       f"(x {op} {tv}); deterministic.")
    return None  # a value-select needs both stated results; SKIP if not pinned


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    top = _toplevel(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    tb = _cocotb_test_text(record)

    # §4.05 up-front SKIPs (composite / special-algebra / edit-task).
    if _COMPOSITE_RE.search(prompt) or _SPECIAL_ALGEBRA_RE.search(prompt) \
            or _EDIT_TASK_RE.search(prompt):
        return None
    # a clocked test => sequential design => not a pure combinational mapping.
    _ci, _co, seq = _cocotb_io(tb)
    if seq or _has_protocol_pin(tb):
        return None

    iface = _resolve_interface(record, prompt, tb)
    if not iface:
        return None
    ins, outs, params = iface
    try:
        return _recognize_and_emit(record, top, prompt, tb, ins, outs, params)
    except Exception:
        return None


def family_of(record: dict) -> Optional[str]:
    """Reporting helper: the family this solver emitted, or None."""
    rtl = solve(record)
    if not rtl:
        return None
    c = rtl.splitlines()[0]
    for key in ("clamp/saturate", "sign-extend", "zero-extend", "absolute value",
                "negate", "comparator-to-flag", "threshold flag"):
        if key in c:
            return key
    return "saturate-family"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
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
    print(f"emitted={n}/{len(recs)}  families={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
