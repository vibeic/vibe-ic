#!/usr/bin/env python3
"""serdes_decode_synth.py — a DETERMINISTIC solver for two ATOMIC CVDP
"code generation" families the shipped solvers MISS:

  (1) SERIAL CONVERTER (PISO / SIPO) — a parallel<->serial shift-register
      serializer/deserializer with a STATED bit-order (MSB-first / LSB-first) and
      a simple load/shift(/valid) protocol. This is the bare shift-register
      converter, NOT a UART/SPI/RS-232 protocol controller.

  (2) ADDRESS / RANGE DECODER — a stated `address -> onehot/select` map or an
      `address range -> region` map. The combinational binary->one-hot decoder is
      ALREADY solved by the registry decoder path (cvdp_atomic_bridge), so this
      solver covers ONLY what that path MISSES: the SEQUENTIAL (clocked) binary->
      one-hot decoder, and the genuine address-RANGE -> region/select map (a set of
      stated `[base, limit]` ranges each driving a region/select output, with a
      stated default for an out-of-range address).

WHY a dedicated CVDP solver (and not the existing ones):
  * shift_counter_synth covers BARREL-shift / ROTATE / saturating-counter — NOT
    a serial<->parallel converter. memory_synth covers FIFO/LIFO/RAM/ROM/regfile
    storage — NOT a PISO/SIPO converter. So no shipped solver emits a serial
    converter.
  * table_lut_synth emits a COMBINATIONAL `case` over an ENUMERATED truth/LUT
    table; an address-RANGE decode is a set of `>=`/`<=` range COMPARISONS, not an
    enumerated case, so it is outside that solver. The registry decoder path emits
    the COMBINATIONAL binary->one-hot but has no CLOCKED variant.
  * cvdp_atomic_bridge's cocotb-driven port extraction mis-tokenizes these shift /
    decode designs (a bare SIPO has no enable/valid for the bridge to anchor on; the
    sequential decoder's registered output and reset confuse the registry op
    recognizer). So both families fall through to SKIP today.

This solver reuses the shipped `cvdp_atomic_bridge` ONLY for the module-name
resolver (`toplevel_name` — from input.prompt + input.context, never the hidden
harness). It does NOT edit the bridge; it is a standalone family solver exposing the same
`solve(record)->Optional[str]` contract as the other `cvdp_*_synth` modules (the
owner registers it in spec_artifact_registry._RECORD_SOLVER_NAMES separately).

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  * NEVER read the golden/reference RTL. Ports come from the PROMPT's own interface
    section (+ a worked-example; the module name from input.prompt/context via the
    bridge) — never from the OFF-LIMITS harness or output['context']/['response'].
  * NEVER guess a bit-order, a shift direction, a width, a map entry, a range bound,
    or an out-of-range default. ANY unstated governing fact -> return None (SKIP).
  * SKIP a full protocol FSM (UART framing / SPI mode / RS-232 / sync-serial
    handshake / baud generator), a CDC, a multi-module composite (SIPO+ECC,
    SIPO+CRC), an LFSR/PRBS/convolutional generator, a priority/first-set-bit
    encoder, a bus-peripheral (APB/AXI/AHB) register file, or a "modify the
    existing RTL" delta/debug/lint task (prior code in input['context']).
  A wrong shift order / wrong map silently passes lint+synth and only a testbench
  catches it, so a skip is always safer than a guess.

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

# Composite / protocol-FSM / non-member cues that must SKIP these two families up
# front. Keyed on OPERATION / INTERFACE vocabulary, never on a design name. A serial
# CONVERTER is the bare shift register — a UART/SPI/RS-232/sync-serial controller, a
# baud generator, an LFSR/PRBS/convolutional generator, or a multi-module composite
# is NOT a member.
_SKIP_RE = re.compile(
    r"""(?xi)
      \buart\b | \brs[-_ ]?232\b | \bspi\b | \bi2c\b | \bi2s\b | \bjtag\b |
      \baxi\b | \bapb\b | \bahb\b | \bwishbone\b | \bavalon\b |
      \bbaud\b | \bstart\s+bit\b | \bstop\s+bit\b | \bframing\b | \bparity\s+bit\b |
      \blfsr\b | \bprbs\b | \bconvolutional\b | \bscrambl | \bmanchester\b |
      \b8b/?10b\b | \b64b/?66b\b | \bcrc\b | \becc\b | \bhamming\b |
      \bcdc\b | \bclock[-\s]?domain\s+cross | \bgray[-\s]?code\s+pointer\b |
      \bstate\s+machine\b | \bsequence\s+detect
    """,
)


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
# CVDP-native interface reader: the `### Inputs` / `### Outputs` markdown list,
# AND a markdown port table (| Port | Direction | Width | ... |). Both forms appear
# in this dataset. Shared dialect with shift_counter_synth / memory_synth.
# --------------------------------------------------------------------------- #
def _param_defaults(prompt: str) -> Dict[str, int]:
    """STATED parameter defaults — `Default BINARY_WIDTH=5`, `Default value is 8`,
    `parameter X = 8`, `OUTPUT_WIDTH=32`."""
    out: Dict[str, int] = {}
    for m in re.finditer(
        r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?(?:\s+of)?\s*"
        r"(?:is\s+|=\s*|:\s*)?`?(\d+)`?", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in re.finditer(r"parameter\s+`?([A-Z][A-Z0-9_]+)`?\s*=\s*(\d+)", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    # `**`BINARY_WIDTH`**: ... Default: `BINARY_WIDTH=5`` / `BINARY_WIDTH=5`
    for m in re.finditer(r"`?([A-Z][A-Z0-9_]+)`?\s*=\s*`?(\d+)`?", prompt):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def _width_from_cell(cell: str, params: Dict[str, int]) -> Optional[int]:
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    m = re.search(r"\[\s*`?([A-Za-z_]\w*)`?\s*-\s*1\s*:\s*0\s*\]", cell)
    if m and m.group(1) in params:
        return params[m.group(1)]
    # a bare parameter token naming the width (`BINARY_WIDTH bits`, `(DATA_W)`)
    for tok in re.findall(r"`?([A-Za-z_][A-Za-z0-9_]*)`?", cell):
        if tok in params and re.search(r"\bbit", cell, re.I):
            return params[tok]
    m = re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*-?\s*bit\b", cell, re.I) or re.search(r"^\s*1\s*$", cell):
        return 1
    return None


_PORT_LINE_RE = re.compile(
    r"""^\s*[-*•]?\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*
        \(([^)]*)\)""",
    re.X)

_PORT_LINE_NOWIDTH_RE = re.compile(
    r"^\s*[-*•]\s*\*{0,2}`?([A-Za-z_]\w*)`?\*{0,2}\s*[:—\-]\s*(.+)$")


def _is_ctrl_name(name: str) -> bool:
    return bool(re.search(
        r"(?i)(^clk$|clock|^rst|reset|_n$|_en$|enable|valid|ready|done|"
        r"shift_?en|load|start|stop|^dir$|direction|mode|sel$|config|"
        r"serial_?in|serial_?out|sin$|sout$|^si$|^so$)", name))


# A direction sub-header: a markdown heading OR a bullet/bold label like
# `- **Inputs**:` / `**Input ports**` / `### Outputs`. Maps to 'in' / 'out' / None.
def _dir_header(ln: str) -> Optional[str]:
    h = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", ln) or \
        re.match(r"^\s*[-*•]?\s*\*\*(.+?)\*\*\s*:?\s*$", ln)
    if not h:
        return None
    label = h.group(1).strip().lower().rstrip(":").strip()
    # a combined header (handle FIRST so 'inputs and outputs' isn't read as 'input').
    if re.fullmatch(r"inputs?\s+and\s+outputs?|(input|output)s?\s+ports?\s+list|"
                    r"interface|ports?|port\s+list|signals?(\s+table)?", label):
        return "both"
    # a single-direction label, not a port bullet or prose heading.
    if re.fullmatch(r"(input|output)s?(\s+ports?)?", label):
        return "in" if label.startswith("input") else "out"
    return None


def _direction_split_ports(text: str, params: Dict[str, int]
                           ) -> Tuple[List[Port], List[Port]]:
    """Scan an interface region and assign each `**name** (width): ...` bullet to the
    direction of the nearest preceding direction sub-header (`**Inputs**` / `### Output`
    / ...). Handles both the SEPARATE-section dialect (`### Inputs:` ... `### Output:`)
    and the COMBINED dialect (`## Inputs and Outputs` with `- **Inputs**:` /
    `- **Output**:` sub-bullets). Direction is tracked, never inferred from the name."""
    lines = text.splitlines()
    cur: Optional[str] = None
    ins: List[Port] = []
    outs: List[Port] = []
    for ln in lines:
        d = _dir_header(ln)
        if d is not None:
            cur = None if d == "both" else d
            continue
        if cur is None:
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
            if _is_ctrl_name(name):
                w = 1
            else:
                continue
        (ins if cur == "in" else outs).append((name, w))
    return ins, outs


# --- markdown port TABLE reader: | `name` | Input/Output | width | desc | ------- #
def _table_ports(prompt: str, params: Dict[str, int]
                 ) -> Optional[Tuple[List[Port], List[Port]]]:
    lines = prompt.splitlines()
    for i, ln in enumerate(lines):
        if "|" not in ln:
            continue
        hdr = [c.strip().strip("`").lower() for c in ln.strip().strip("|").split("|")]
        if not any("port" in c or c == "name" or "signal" in c for c in hdr):
            continue
        if not any("direction" in c or "polarity" in c or "dir" == c for c in hdr):
            continue
        if i + 1 >= len(lines) or not re.match(
                r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            continue
        ni = next((j for j, c in enumerate(hdr)
                   if "port" in c or c == "name" or "signal" in c), None)
        di = next((j for j, c in enumerate(hdr)
                   if "direction" in c or "polarity" in c or c == "dir"), None)
        wi = next((j for j, c in enumerate(hdr) if "width" in c), None)
        if ni is None or di is None:
            return None
        ins: List[Port] = []
        outs: List[Port] = []
        for body in lines[i + 2:]:
            if "|" not in body or not body.strip().startswith("|"):
                break
            cells = [c.strip().strip("`") for c in body.strip().strip("|").split("|")]
            if len(cells) <= max(ni, di):
                continue
            nm = re.sub(r"\*", "", cells[ni]).strip().strip("`")
            nm = re.match(r"^([A-Za-z_]\w*)", nm)
            if not nm:
                continue
            name = nm.group(1)
            if name.lower() in _NOT_A_PORT_NAME:
                continue
            d = cells[di].lower()
            wcell = cells[wi] if (wi is not None and len(cells) > wi) else ""
            w = _width_from_cell(wcell, params)
            if w is None:
                w = _width_from_cell(cells[-1], params)
            if w is None:
                w = 1 if _is_ctrl_name(name) else None
            if w is None:
                continue
            if "out" in d:
                outs.append((name, w))
            elif "in" in d:
                ins.append((name, w))
        if ins and outs:
            return _dedup(ins), _dedup(outs)
    return None


def _dedup(ports: List[Port]) -> List[Port]:
    seen = set()
    out: List[Port] = []
    for n, w in ports:
        if n in seen:
            continue
        seen.add(n)
        out.append((n, w))
    return out


def _interface_from_text(text: str, params: Dict[str, int]
                         ) -> Optional[Tuple[List[Port], List[Port]]]:
    tbl = _table_ports(text, params)
    if tbl:
        return tbl
    ins, outs = _direction_split_ports(text, params)
    ins, outs = _dedup(ins), _dedup(outs)
    if ins and outs:
        return ins, outs
    return None


def _docs_context(record: dict) -> str:
    """Reference DOCUMENTATION shipped in input['context'] as docs/*.md (NOT prior
    RTL) — a legitimate interface source (the bridge similarly reads a header from
    output['context']). Only docs/markdown files; never an rtl/*.sv body."""
    ic = (record.get("input") or {}).get("context")
    if not isinstance(ic, dict):
        return ""
    parts = []
    for k, v in ic.items():
        if isinstance(v, str) and v.strip() and re.search(r"\.(md|txt|markdown)$", k, re.I):
            parts.append(v)
    return "\n".join(parts)


def _interface(prompt: str, params: Dict[str, int], record: Optional[dict] = None
               ) -> Optional[Tuple[List[Port], List[Port]]]:
    iface = _interface_from_text(prompt, params)
    if iface:
        return iface
    # fall back to a reference DOCS markdown shipped alongside (interface only).
    if record is not None:
        docs = _docs_context(record)
        if docs:
            dparams = dict(params)
            dparams.update(_param_defaults(docs))
            iface = _interface_from_text(docs, dparams)
            if iface:
                return iface
    return None


def _find_re(ports: List[Port], pattern: str) -> Optional[Port]:
    rx = re.compile(pattern, re.I)
    for n, w in ports:
        if rx.search(n):
            return (n, w)
    return None


def _clk(ports): return _find_re(ports, r"(^|_)(cl(?:k|ock))$")
def _rst(ports): return _find_re(ports, r"(rst|reset|areset)")


def _decl(direction, name, width, reg=False):
    kw = f"{direction} reg" if reg else direction
    return f"{kw} [{width-1}:0] {name}" if width > 1 else f"{kw} {name}"


def _param_block(params: Dict[str, int]) -> str:
    if not params:
        return ""
    decls = ",\n    ".join(f"parameter {p} = {v}" for p, v in params.items())
    return f" #(\n    {decls}\n)"


def _width_param_for(prompt: str, name: str, params: Dict[str, int]) -> Optional[str]:
    """If port `name`'s declared width is a parameter (e.g. `(DATA_WIDTH bits)` or
    `[DATA_WIDTH-1:0]`), return that parameter's name so the emit can re-parameterize."""
    for ln in prompt.splitlines():
        if re.search(rf"`?{re.escape(name)}`?", ln):
            m = re.search(r"\[\s*`?([A-Z][A-Z0-9_]+)`?\s*-\s*1\s*:\s*0\s*\]", ln)
            if m and m.group(1) in params:
                return m.group(1)
            for tok in re.findall(r"`([A-Z][A-Z0-9_]+)`", ln):
                if tok in params and re.search(r"\bbit", ln, re.I):
                    return tok
    return None


def _wexpr(prompt: str, name: str, width: int, params: Dict[str, int]) -> str:
    """A symbolic bus range `[PARAM-1:0]` when the width came from a declared
    parameter whose default equals `width`, else a literal `[width-1:0]`."""
    pn = _width_param_for(prompt, name, params)
    if pn and params.get(pn) == width:
        return f"[{pn}-1:0]"
    return f"[{width-1}:0]"


# =========================================================================== #
# FAMILY 1 — SERIAL CONVERTER (PISO / SIPO)
# =========================================================================== #
def _bit_order(prompt: str) -> Optional[str]:
    """STATED bit-order, or None. 'msb' / 'lsb'. Only a clearly-stated order
    counts; an unstated order returns None -> SKIP."""
    low = prompt.lower()
    msb = bool(re.search(r"msb[\s-]*first|most\s+significant\s+bit\s+first|"
                         r"msb\s+to\s+lsb|starting\s+from\s+the\s+most\s+significant",
                         low))
    lsb = bool(re.search(r"lsb[\s-]*first|least\s+significant\s+bit\s+first|"
                         r"lsb\s+to\s+msb|starting\s+from\s+the\s+least\s+significant",
                         low))
    if msb and not lsb:
        return "msb"
    if lsb and not msb:
        return "lsb"
    return None


def _shift_dir_from_example(prompt: str) -> Optional[str]:
    """For a SIPO, infer shift direction from a worked example that states
    'new data shifts in from the LSB' / 'MSB will be shifted out' (a left shift),
    or the converse (a right shift). 'left' / 'right' or None."""
    low = prompt.lower()
    left = bool(re.search(
        r"shift(?:s|ed|ing)?\s+(?:its\s+contents\s+)?left|shift[-\s]*left|"
        r"new\s+data\s+(?:will\s+)?shift(?:s|ed)?\s+in\s+from\s+the\s+lsb|"
        r"(?:the\s+)?(?:most\s+significant\s+bit|msb)\s+(?:will\s+be\s+)?shift(?:ed)?\s+out",
        low))
    right = bool(re.search(
        r"shift(?:s|ed|ing)?\s+(?:its\s+contents\s+)?right|shift[-\s]*right|"
        r"new\s+data\s+(?:will\s+)?shift(?:s|ed)?\s+in\s+from\s+the\s+msb|"
        r"(?:the\s+)?(?:least\s+significant\s+bit|lsb)\s+(?:will\s+be\s+)?shift(?:ed)?\s+out",
        low))
    if left and not right:
        return "left"
    if right and not left:
        return "right"
    return None


def _try_sipo(prompt: str, ins, outs, top, params) -> Optional[str]:
    """Serial In Parallel Out: a 1-bit serial_in shifted into an N-bit parallel_out
    on each clock. SKIP unless the shift direction is STATED/example-implied and the
    interface is exactly {clk(+optional rst/shift_en), serial_in} -> {parallel_out}."""
    low = prompt.lower()
    if not re.search(r"serial[\s-]*in[\s-]*parallel[\s-]*out|\bsipo\b", low):
        return None

    clk = _clk(ins)
    if clk is None:
        return None
    serial_in = _find_re(ins, r"(serial_?in|^sin$|^si$|s_?in$|data_?in_serial)")
    if serial_in is None:
        return None
    if serial_in[1] != 1:
        return None
    parallel_out = _find_re(outs, r"(parallel_?out|p_?out|data_?out|^pout$)")
    if parallel_out is None:
        wide = [(n, w) for n, w in outs if w > 1]
        parallel_out = wide[0] if len(wide) == 1 else None
    if parallel_out is None or parallel_out[1] < 2:
        return None
    pout_name, W = parallel_out

    # the shift direction (which end new data enters) MUST be resolvable.
    direction = _shift_dir_from_example(prompt)
    if direction is None:
        # fall back to a stated bit-order: feeding MSB-first into a left shift
        # rebuilds the word; a plain 'msb-first' SIPO is a left shift.
        bo = _bit_order(prompt)
        if bo == "msb":
            direction = "left"
        elif bo == "lsb":
            direction = "right"
    if direction is None:
        return None

    rst = _rst(ins)
    shift_en = _find_re(ins, r"(shift_?en|^en$|enable|^valid$|in_?valid)")
    done = _find_re(outs, r"(^done$|complete|out_?valid|^valid$)")

    # §4.05: a 'done' / counter-completion output is only honestly emittable when the
    # completion-count + a load/restart protocol is stated. The plain CVDP SIPO has no
    # done; if a 'done' port exists we SKIP (the completion protocol is not pinned by
    # the bare interface).
    if done is not None:
        return None

    # any OTHER unexplained input port -> SKIP (never invent its meaning).
    known = {clk[0], serial_in[0]}
    if rst:
        known.add(rst[0])
    if shift_en:
        known.add(shift_en[0])
    if any(n not in known for n, _ in ins):
        return None
    if any(n != pout_name for n, _ in outs):
        return None

    # shift expression: 'left' => new bit enters LSB, MSB drops off; 'right' => the
    # converse. Both are the standard SIPO; the stated direction picks one.
    if direction == "left":
        shift_expr = f"{{{pout_name}[{W-2}:0], {serial_in[0]}}}"
    else:
        shift_expr = f"{{{serial_in[0]}, {pout_name}[{W-1}:1]}}"

    clk_n, sin_n = clk[0], serial_in[0]
    pblock = _param_block(params)
    pw = _wexpr(prompt, pout_name, W, params)

    ports = [_decl("input", clk_n, 1)]
    sens = f"posedge {clk_n}"
    rst_test = None
    if rst:
        rst_n = rst[0]
        active_low = rst_n.lower().endswith("_n") or rst_n.lower() in (
            "rstn", "resetn") or bool(re.search(r"active[- ]low", low))
        async_rst = bool(re.search(r"asynchron|\basync\b|areset", low))
        rst_test = f"!{rst_n}" if active_low else rst_n
        ports.append(_decl("input", rst_n, 1))
        if async_rst:
            sens += f", {'negedge' if active_low else 'posedge'} {rst_n}"
    if shift_en:
        ports.append(_decl("input", shift_en[0], 1))
    ports.append(_decl("input", sin_n, 1))
    ports.append(f"output reg {pw} {pout_name}")

    guard = f"if ({shift_en[0]}) " if shift_en else ""
    lines = [
        "// program-SOLVED Serial-In Parallel-Out shift register "
        "(shift direction PARSED); deterministic, no AI.",
        f"module {top}{pblock} (",
        "    " + ",\n    ".join(ports),
        ");",
        f"    always @({sens}) begin",
    ]
    if rst_test is not None:
        lines += [
            f"        if ({rst_test})",
            f"            {pout_name} <= 0;",
            f"        else",
            f"            {guard}{pout_name} <= {shift_expr};",
        ]
    else:
        lines.append(f"        {guard}{pout_name} <= {shift_expr};")
    lines += ["    end", "endmodule", ""]
    return "\n".join(lines)


def _try_piso(prompt: str, ins, outs, top, params) -> Optional[str]:
    """Parallel In Serial Out: an N-bit parallel data input LOADED on a stated load
    signal, then shifted out 1 bit/clock in a STATED bit-order. SKIP unless there is
    an actual parallel DATA INPUT port + a stated LOAD signal + a stated bit-order.
    (A free-running pattern GENERATOR with no parallel data input is not a converter
    -> SKIP.)"""
    low = prompt.lower()
    if not re.search(r"parallel[\s-]*in[\s-]*serial[\s-]*out|\bpiso\b", low):
        return None

    clk = _clk(ins)
    if clk is None:
        return None
    data_in = _find_re(ins, r"(parallel_?in|p_?data|data_?in|^pin$|^din$|"
                            r"parallel_?data|load_?data)")
    if data_in is None or data_in[1] < 2:
        # no parallel DATA input bus => a generator, not a converter -> SKIP.
        return None
    din_name, W = data_in
    serial_out = _find_re(outs, r"(serial_?out|^sout$|^so$|s_?out$|data_?out_serial)")
    if serial_out is None or serial_out[1] != 1:
        return None
    sout_name = serial_out[0]

    # a STATED load control is required (when to capture the parallel word).
    load = _find_re(ins, r"(^load$|load_?en|^ld$|capture|parallel_?load|sample)")
    if load is None:
        return None
    load_n = load[0]

    bo = _bit_order(prompt)
    if bo is None:
        return None  # bit-order must be STATED

    rst = _rst(ins)
    if rst is None:
        return None
    shift_en = _find_re(ins, r"(shift_?en|^en$|enable|^valid$)")

    known = {clk[0], din_name, load_n, rst[0]}
    if shift_en:
        known.add(shift_en[0])
    if any(n not in known for n, _ in ins):
        return None
    if any(n != sout_name for n, _ in outs):
        return None

    rst_n = rst[0]
    active_low = rst_n.lower().endswith("_n") or rst_n.lower() in (
        "rstn", "resetn") or bool(re.search(r"active[- ]low", low))
    async_rst = bool(re.search(r"asynchron|\basync\b|areset", low))
    rst_test = f"!{rst_n}" if active_low else rst_n
    sens = f"posedge {clk[0]}"
    if async_rst:
        sens += f", {'negedge' if active_low else 'posedge'} {rst_n}"

    # MSB-first: serial_out is the top bit, shift left. LSB-first: bottom bit, right.
    if bo == "msb":
        out_bit = f"shift_reg[{W-1}]"
        shift_stmt = f"shift_reg <= {{shift_reg[{W-2}:0], 1'b0}};"
    else:
        out_bit = "shift_reg[0]"
        shift_stmt = f"shift_reg <= {{1'b0, shift_reg[{W-1}:1]}};"

    pblock = _param_block(params)
    dw = _wexpr(prompt, din_name, W, params)
    ports = [_decl("input", clk[0], 1), _decl("input", rst_n, 1),
             _decl("input", load_n, 1)]
    if shift_en:
        ports.append(_decl("input", shift_en[0], 1))
    ports.append(f"input {dw} {din_name}")
    ports.append(_decl("output", sout_name, 1))
    guard = f"else if ({shift_en[0]}) " if shift_en else "else "
    lines = [
        "// program-SOLVED Parallel-In Serial-Out shift register "
        "(load + bit-order PARSED); deterministic, no AI.",
        f"module {top}{pblock} (",
        "    " + ",\n    ".join(ports),
        ");",
        f"    reg {dw} shift_reg;",
        f"    always @({sens}) begin",
        f"        if ({rst_test})",
        f"            shift_reg <= 0;",
        f"        else if ({load_n})",
        f"            shift_reg <= {din_name};",
        f"        {guard}",
        f"            {shift_stmt}",
        "    end",
        f"    assign {sout_name} = {out_bit};",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# =========================================================================== #
# FAMILY 2 — ADDRESS / RANGE DECODER
# =========================================================================== #
def _try_seq_onehot_decoder(prompt: str, ins, outs, top, params) -> Optional[str]:
    """SEQUENTIAL (clocked) binary->one-hot decoder: on the clock edge,
    o_one_hot_out <= (1 << binary_in) within OUTPUT_WIDTH, else 0; reset clears it.
    (The COMBINATIONAL variant is already solved by the registry path; this covers
    only the clocked one.)"""
    low = prompt.lower()
    if not re.search(r"one[\s-]*hot", low):
        return None
    if not re.search(r"binary[\s-]*(?:to|-)[\s-]*one[\s-]*hot|"
                     r"binary[\s-]*encoded.*one[\s-]*hot|"
                     r"one[\s-]*hot.*binary[\s-]*encoded", low):
        return None
    clk = _clk(ins)
    if clk is None:
        return None  # combinational variant is solved elsewhere
    if not re.search(r"sequential|on\s+the\s+(?:next\s+)?rising\s+edge|"
                     r"registered|sampled\s+on\s+the\s+rising\s+edge|"
                     r"updated\s+on\s+the\s+(?:same\s+)?rising\s+edge|clocked",
                     low):
        return None

    bin_in = _find_re(ins, r"(binary_?in|^bin$|^b_?in$|encoded_?in|i_binary)")
    if bin_in is None:
        cands = [(n, w) for n, w in ins
                 if w > 1 and not re.search(r"(cl(k|ock)|rst|reset)", n, re.I)]
        bin_in = cands[0] if len(cands) == 1 else None
    if bin_in is None:
        return None
    bin_n, BW = bin_in
    oh = _find_re(outs, r"(one_?hot|^oh$|onehot|decoded|o_one_hot)")
    if oh is None:
        wide = [(n, w) for n, w in outs if w >= 2]
        oh = wide[0] if len(wide) == 1 else None
    if oh is None:
        return None
    oh_n, OW = oh
    if len(outs) != 1:
        return None

    rst = _rst(ins)
    known = {clk[0], bin_n}
    if rst:
        known.add(rst[0])
    if any(n not in known for n, _ in ins):
        return None

    # the stated out-of-range / default: out_of_range => 0. We range-guard against
    # OUTPUT_WIDTH so an index >= OW yields 0.
    bw_decl = _wexpr(prompt, bin_n, BW, params)
    ow_param = _width_param_for(prompt, oh_n, params)
    ow_name = ow_param if (ow_param and params.get(ow_param) == OW) else str(OW)
    ow_decl = f"[{ow_name}-1:0]" if not ow_name.isdigit() else f"[{OW-1}:0]"
    pblock = _param_block(params)

    rst_n = rst[0] if rst else None
    sens = f"posedge {clk[0]}"
    rst_test = None
    if rst_n:
        active_low = rst_n.lower().endswith("_n") or rst_n.lower() in (
            "rstn", "resetn", "rstb", "i_rstb") or rst_n.lower().endswith("b") \
            or bool(re.search(r"active[- ]low", low))
        async_rst = bool(re.search(r"asynchron|\basync\b|areset", low))
        rst_test = f"!{rst_n}" if active_low else rst_n
        if async_rst:
            sens += f", {'negedge' if active_low else 'posedge'} {rst_n}"

    ports = [_decl("input", clk[0], 1)]
    if rst_n:
        ports.append(_decl("input", rst_n, 1))
    ports.append(f"input {bw_decl} {bin_n}")
    ports.append(f"output reg {ow_decl} {oh_n}")
    body_assign = (
        f"            if ({bin_n} < {ow_name})\n"
        f"                {oh_n} <= ({{{{{ow_name}-1{{1'b0}}}}, 1'b1}} << {bin_n});\n"
        f"            else\n"
        f"                {oh_n} <= 0;")
    lines = [
        "// program-SOLVED sequential binary->one-hot decoder "
        "(clocked; out-of-range -> 0); deterministic, no AI.",
        f"module {top}{pblock} (",
        "    " + ",\n    ".join(ports),
        ");",
        f"    always @({sens}) begin",
    ]
    if rst_test is not None:
        lines += [
            f"        if ({rst_test})",
            f"            {oh_n} <= 0;",
            f"        else begin",
            body_assign,
            f"        end",
        ]
    else:
        lines += [body_assign.replace("            ", "        ")]
    lines += ["    end", "endmodule", ""]
    return "\n".join(lines)


# --- address RANGE -> region/select map ------------------------------------ #
_HEX = r"0[xX][0-9A-Fa-f]+|[0-9A-Fa-f]+'[hH][0-9A-Fa-f_]+|\d+"


def _num(tok: str) -> Optional[int]:
    tok = tok.strip().strip("`")
    m = re.match(r"0[xX]([0-9A-Fa-f]+)$", tok)
    if m:
        return int(m.group(1), 16)
    m = re.match(r"\d+'[hH]([0-9A-Fa-f_]+)$", tok)
    if m:
        return int(m.group(1).replace("_", ""), 16)
    if re.match(r"\d+$", tok):
        return int(tok)
    return None


def _parse_range_map(prompt: str) -> Optional[List[Tuple[int, int, int]]]:
    """Parse a STATED address-range -> region table: rows of `[base, limit] -> region`
    (or `base..limit : region N`). Returns [(base, limit, region_index), ...] sorted,
    or None. §4.05: every region index must be explicitly stated."""
    rows: List[Tuple[int, int, int]] = []
    for ln in prompt.splitlines():
        if "|" not in ln:
            continue
        cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
        nums: List[int] = []
        region = None
        for c in cells:
            rng = re.match(rf"\s*({_HEX})\s*(?:-|–|to|\.\.|:)\s*({_HEX})\s*$", c)
            if rng:
                lo, hi = _num(rng.group(1)), _num(rng.group(2))
                if lo is not None and hi is not None:
                    nums = [lo, hi]
                    continue
            rm = re.search(r"region\s*([0-9]+)|\bregion\s*([A-Za-z])\b", c, re.I)
            if rm:
                g = rm.group(1) or rm.group(2)
                region = int(g) if g.isdigit() else (ord(g.upper()) - ord("A"))
        if len(nums) == 2 and region is not None and nums[0] <= nums[1]:
            rows.append((nums[0], nums[1], region))
    if len(rows) >= 2:
        rows.sort()
        return rows
    return None


def _try_range_decoder(prompt: str, ins, outs, top, params) -> Optional[str]:
    """Address-RANGE -> region/select map: a STATED set of [base, limit] ranges, each
    mapping a region/select code, with a STATED default for an out-of-range address.
    Combinational. SKIP if the map is incomplete OR the default is unstated."""
    low = prompt.lower()
    if not re.search(r"address\s+range|range\s+of\s+address|memory\s+map|"
                     r"address\s+map|region", low):
        return None
    rmap = _parse_range_map(prompt)
    if rmap is None:
        return None
    # a default for out-of-range MUST be stated (a region value or 'select=0/none').
    dm = re.search(r"(?:default|out[\s-]*of[\s-]*range|otherwise|unmapped)\b[^.\n]{0,60}?"
                   r"region\s*([0-9]+)", low)
    default_region = int(dm.group(1)) if dm else None
    if default_region is None:
        if re.search(r"(?:default|out[\s-]*of[\s-]*range|otherwise|unmapped)\b"
                     r"[^.\n]{0,60}?(?:0\b|zero|none|no\s+region)", low):
            default_region = 0
    if default_region is None:
        return None

    addr = _find_re(ins, r"(addr|address)")
    if addr is None:
        return None
    addr_n, AW = addr
    region = _find_re(outs, r"(region|select|sel$|chip_?select|cs$|decode)")
    if region is None or len(outs) != 1:
        return None
    region_n, RW = region

    pblock = _param_block(params)
    aw = _wexpr(prompt, addr_n, AW, params)
    ports = [f"input {aw} {addr_n}", _decl("output reg", region_n, RW)]
    lines = [
        "// program-SOLVED address-range decoder "
        "(stated ranges + stated default; out-of-range -> default); "
        "deterministic, no AI.",
        f"module {top}{pblock} (",
        "    " + ",\n    ".join(ports),
        ");",
        "    always @(*) begin",
        f"        {region_n} = {RW}'d{default_region};",
    ]
    for lo, hi, reg in rmap:
        lines.append(
            f"        if ({addr_n} >= {AW}'h{lo:x} && {addr_n} <= {AW}'h{hi:x}) "
            f"{region_n} = {RW}'d{reg};")
    lines += ["    end", "endmodule", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
_SERIAL_BUILDERS = (_try_sipo, _try_piso)
_DECODER_BUILDERS = (_try_seq_onehot_decoder, _try_range_decoder)
_BUILDERS = _SERIAL_BUILDERS + _DECODER_BUILDERS
_FAMILY_NAMES = {
    "_try_sipo": "sipo_serial_converter",
    "_try_piso": "piso_serial_converter",
    "_try_seq_onehot_decoder": "sequential_onehot_decoder",
    "_try_range_decoder": "address_range_decoder",
}


def _delta_task(record: dict) -> bool:
    """A 'modify/debug/lint the existing RTL' task ships prior code in
    input['context'] (an rtl/*.sv body) — that is a delta task, not a single-function
    emit. A docs-only context (docs/*.md) is reference material, not prior code."""
    ic = (record.get("input") or {}).get("context")
    if not isinstance(ic, dict):
        return False
    for k, v in ic.items():
        if isinstance(v, str) and v.strip() and re.search(r"\.s?v$", k):
            return True
    return False


def solve(record: dict) -> Optional[str]:
    """Emit deterministic RTL (module named per the prompt/context) for a CVDP
    serial-converter (PISO/SIPO) or address/range-decoder design, or None (SKIP) on
    ANY ambiguity / unstated governing fact / non-member design / delta task."""
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
    docs = _docs_context(record)
    spec = prompt + ("\n" + docs if docs else "")
    # up-front protocol-FSM / composite / generator SKIP (prompt OR reference docs).
    if _SKIP_RE.search(spec):
        return None
    params = _param_defaults(prompt)
    iface = _interface(prompt, params, record)
    if not iface:
        return None
    ins, outs = iface
    for fn in _BUILDERS:
        try:
            rtl = fn(spec, ins, outs, top, params)
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
    docs = _docs_context(record)
    spec = prompt + ("\n" + docs if docs else "")
    if _delta_task(record) or not prompt.strip() or _SKIP_RE.search(spec):
        return None
    params = _param_defaults(prompt)
    iface = _interface(prompt, params, record)
    if not iface:
        return None
    ins, outs = iface
    for fn in _BUILDERS:
        try:
            if fn(spec, ins, outs, top, params):
                return _FAMILY_NAMES[fn.__name__]
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
