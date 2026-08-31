#!/usr/bin/env python3
"""encoder_synth.py — deterministic SOLVER for the CVDP PRIORITY-ENCODER /
BINARY-DECODER / ONE-HOT family, covering the cases the already-shipped registry
solvers (`encoder_decoder_synth` / `mux_synth`) do NOT.

WHY a NEW solver (what the shipped ones leave on the floor):
  * `encoder_decoder_synth.synth` emits ONLY an **LSB-first** priority encoder
    that reports a **position** and has **no valid flag**, and it requires the
    output width to be EXACTLY ceil(log2(N)). It SKIPs every MSB-first ("highest
    set bit wins") encoder — which is the dominant CVDP shape (e.g. an 8-input
    3-bit priority encoder whose prose says "priority decreases from bit 7 to
    bit 0").
  * Neither shipped solver emits a **binary decoder** (index -> one-hot), nor the
    **parameterized** one-hot decoder with a stated out-of-range -> 0 rule.
  * `mux_synth` is a multiplexer (select-one-of-N data sources) — a different
    function; it explicitly SKIPs encoder/decoder prose.

This solver therefore adds exactly the uncovered atomic functions:
  (E) PRIORITY ENCODER, either direction — N-bit input vector -> log2(N)-bit
      index of the highest (MSB-first) OR lowest (LSB-first) set bit, with the
      priority DIRECTION PARSED FROM PROSE (MSB-vs-LSB), an optional valid flag
      (emitted only when the prose states one), and a stated all-zero default.
  (D) BINARY DECODER — a log2(M)-bit (or parameterized) index -> M-bit one-hot,
      `out = (1 << index)`, with a stated out-of-range -> all-zeros rule. Handles
      the parameterized form (`BINARY_WIDTH` / `OUTPUT_WIDTH`) the CVDP harness
      instantiates at DEFAULTS (the runner passes NO parameters).

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  * NEVER guess the priority DIRECTION. If MSB-vs-LSB is not unambiguously stated
    (or both/neither appear), return None.
  * NEVER guess a mapping. A decoder whose index->output mapping is not the plain
    `out[index]=1` one-hot (e.g. a stated address map, a granularity table, a
    gray code) returns None.
  * NEVER guess a width or an out-of-range default. Emit the out-of-range guard
    ONLY when it is stated; if the select space can exceed the output width and
    no default is stated, SKIP.
  * The golden / reference RTL is NEVER read. We work from the prompt prose, the
    SHARED `port_parser`-derived interface, and (for the parameterized decoder)
    the stated parameter defaults — never any reference body.
  * Sequential / pipelined / handshake variants (clk/rst/valid pipeline,
    registered output) are out of scope here -> SKIP (a clocked first-bit decoder
    with PlRegs pipeline stages is NOT this combinational function).

API (mirrors the sibling solvers):
    synth(prompt_text, top="TopModule") -> str | None    # raw prose+top
    solve(record) -> Optional[str]                        # CVDP record (uses the
                                                           # bridge for interface)
chip-AGNOSTIC, pure-function, deterministic.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import port_parser as _pp  # noqa: E402  the SHARED interface reader

Port = Tuple[str, int]

# Sequential / handshake ports a pure combinational encoder/decoder never has.
_SEQ_PORTS = {
    "clk", "clock", "i_clk", "clk_i", "rst", "reset", "rstn", "rst_n", "resetn",
    "reset_n", "i_rstb", "rstb", "areset", "aresetn", "rst_async_n", "en",
    "enable", "load", "ready", "ack", "in_valid", "out_valid",
}

# Prose that marks a DIFFERENT (non-atomic / non-plain) decoder or encoder whose
# mapping is NOT the plain index<->one-hot one — SKIP these (NO-CHEAT). Keyed on
# stated semantics, never a design name.
_OTHER_MAPPING_RE = re.compile(
    r"""(?xi)
      \bgray\b | \bbcd\b | \bone[-\s]?hot\s+to\b | \bgranularit | \bunpack |
      \bsigned\b | \bsign[-\s]?extend | \baddress\s+map | \bchip\s+select\b |
      \b8b/?10b\b | \b64b/?66b\b | \bmanchester\b | \bconvolutional\b |
      \breed[-\s]?solomon\b | \bhamming\b | \bsequencer\b | \bscancode\b |
      \bscan\s*code\b | \bpipeline | \bpipelined\b | \bstack\b
    """,
)


# --------------------------------------------------------------------------- #
# direction parse — the load-bearing §4.05 decision for the encoder            #
# --------------------------------------------------------------------------- #
def parse_priority_direction(text: str) -> Optional[bool]:
    """Return True = MSB-first (highest set bit wins), False = LSB-first (lowest
    set bit wins), or None = unstated / contradictory (=> SKIP). NEVER guesses.

    MSB-first cues: "highest"/"most-significant"/"high(est) bit", or an explicit
    "priority decreases from bit N down to bit 0" / "bit 7 ... to ... bit 0".
    LSB-first cues: "lowest"/"least-significant"/"first set bit", or "priority
    decreases from bit 0 up to bit N".
    If BOTH or NEITHER are found -> None. A directional flow phrase
    ("from the highest ... to the lowest", "from bit 7 ... to bit 0") is read as
    the WINNER being the START of the flow, so it does NOT count as both.
    """
    t = text.lower()
    # (1) directional FLOW phrase: "<from> X <to> Y" — the winner is the START.
    flow = re.search(
        r"priorit[^.\n]*?\bfrom\b[^.\n]*?\b(highest|lowest|bit\s+\d+)\b"
        r"[^.\n]*?\bto\b[^.\n]*?\b(highest|lowest|bit\s+\d+)\b", t)
    if flow:
        a, b = flow.group(1), flow.group(2)
        ai = int(re.search(r"\d+", a).group()) if a.startswith("bit") else None
        bi = int(re.search(r"\d+", b).group()) if b.startswith("bit") else None
        if a == "highest" or b == "lowest" or (ai is not None and bi is not None and ai > bi):
            return True        # MSB-first (flow starts at the highest)
        if a == "lowest" or b == "highest" or (ai is not None and bi is not None and bi > ai):
            return False       # LSB-first (flow starts at the lowest)

    msb = bool(
        re.search(r"\bhighest[-\s](?:priority\s+)?(?:active\s+)?(?:set\s+)?(?:input|bit|line|index)\b", t)
        or re.search(r"\bhighest\s+(?:active\s+)?(?:set\s+)?bit\b", t)
        or re.search(r"\bmost[-\s]significant\b", t)
        or re.search(r"\bhighest\s+(?:order\s+)?(?:active\s+)?(?:input|bit|index)\b", t)
    )
    lsb = bool(
        re.search(r"\blowest[-\s](?:priority\s+)?(?:active\s+)?(?:set\s+)?(?:input|bit|line|index)\b", t)
        or re.search(r"\blowest\s+(?:active\s+)?(?:set\s+)?bit\b", t)
        or re.search(r"\bleast[-\s]significant\b", t)
        or re.search(r"\bfirst\s+(?:set\s+)?bit\b", t)
        or re.search(r"\bfirst\s+(?:1|one|high|set)\b", t)
    )
    if msb and not lsb:
        return True
    if lsb and not msb:
        return False
    return None


def _is_priority_encoder_prose(text: str) -> bool:
    t = text.lower()
    if re.search(r"\bpriority\s+encoder\b", t):
        return True
    if re.search(r"\bencoder\b", t) and re.search(r"\bpriorit", t):
        return True
    # "index/position of the highest/lowest active input/bit"
    if re.search(r"\b(?:index|position|code)\b.{0,40}\b(?:highest|lowest|first)\b", t) \
       and re.search(r"\b(?:active|set|high)\b.{0,20}\b(?:input|bit|line)\b", t):
        return True
    return False


def _is_binary_decoder_prose(text: str) -> bool:
    """True iff the prose describes a binary-index -> one-hot decoder."""
    t = text.lower()
    if re.search(r"\bbinary[-\s]to[-\s]one[-\s]?hot\b", t):
        return True
    if re.search(r"\bone[-\s]?hot\b", t) and re.search(r"\bdecoder?\b", t) \
       and re.search(r"\bbinary\b", t):
        return True
    # "only the bit at index <name> is set to 1, all others 0"
    if re.search(r"\bbit\s+at\s+index\b", t) and re.search(r"\bone[-\s]?hot\b", t):
        return True
    return False


# --------------------------------------------------------------------------- #
# zero-default parse (shared idea with the sibling solver, kept self-contained) #
# --------------------------------------------------------------------------- #
def _zero_default_is_zero(text: str) -> Optional[bool]:
    """True iff an explicit all-zero-input -> output 0 default is stated; False if
    a non-zero default is stated; None if unstated."""
    t = text.lower()
    cond = re.search(
        r"(?:input(?:\s+lines?)?\s+(?:is|are)\s+(?:all\s+)?(?:zero|0)\b"
        r"|all\s+zeros?\b"
        r"|none\s+of\s+the\s+input\s+(?:lines?|bits?)\s+are\s+(?:active|high|1|set)"
        r"|no\s+(?:input\s+)?bits?\s+(?:that\s+are\s+)?(?:high|set|active|1))",
        t,
    )
    if not cond:
        return None
    lo = max(0, cond.start() - 90)
    hi = min(len(t), cond.end() + 90)
    w = t[lo:hi]
    if re.search(r"\ball\s+(?:1s|ones)\b", w) and not re.search(
        r"\b(?:report|output|default|set)\b[^.\n]{0,25}\b(?:0|zero)\b", w
    ):
        return False
    if re.search(r"\b(?:report|output|outputs?|default(?:s+to)?|set\s+.{0,20}?to|return)\b"
                 r"[^.\n]{0,25}\b(?:0|zero|3'b000|all\s+zeros?)\b", w) \
       or re.search(r"\b(?:0|zero)\b[^.\n]{0,30}?\b(?:if|when)\b", w):
        return True
    return None


# --------------------------------------------------------------------------- #
# parameter defaults (the CVDP harness instantiates the DUT at its DEFAULTS)    #
# --------------------------------------------------------------------------- #
def _param_default(text: str, pname: str) -> Optional[int]:
    """Parse `Default <PNAME>=<int>` / `<PNAME>=<int>` / `Default: <int>` for a
    named parameter, as stated in prose. None if not stated."""
    for pat in (
        rf"\b{re.escape(pname)}\s*=\s*(\d+)",
        rf"`{re.escape(pname)}`[^.\n]{{0,60}}?default[^.\n]{{0,20}}?(\d+)",
        rf"default[^.\n]{{0,8}}?`?{re.escape(pname)}`?\s*=?\s*(\d+)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    return None


# --------------------------------------------------------------------------- #
# CVDP-prose interface reader — the shared port_parser reads the bullet /      #
# header / RTLLM forms, but CVDP states the interface in TWO more forms the     #
# shared reader returns ([],[]) on:                                            #
#   (1) range-BEFORE-name bullet:  `- [7:0] in: An 8-bit input vector.`        #
#       under an `Inputs:` / `Output:` section header.                          #
#   (2) labelled bullet with a PARAMETER-named width:                          #
#       `**Input**: \`binary_in\` (\`BINARY_WIDTH\` bits) — ...`               #
#       whose width is the stated default of that parameter.                   #
# Both are GENERAL CVDP-format forms, keyed on the literal Input/Output cue,    #
# never on a design name. A width we cannot reduce to a single integer drops    #
# that port (=> downstream SKIP), never a guessed width.                        #
# --------------------------------------------------------------------------- #
def _cvdp_prose_ports(text: str) -> Tuple[List[Port], List[Port]]:
    ins: List[Port] = []
    outs: List[Port] = []
    section = None  # 'in' | 'out' | None  (for the range-before-name bullets)

    def _wtok(s: str) -> Optional[int]:
        m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", s)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
        m = re.search(r"\b(\d+)\s*-?\s*bits?\b", s, re.I)
        if m:
            return int(m.group(1))
        if re.search(r"\b(?:one|single|1)[-\s]?bit\b", s, re.I):
            return 1
        # parameter-named width: `(`PARAM` bits)` -> the param's stated default.
        m = re.search(r"\(\s*`?([A-Z][A-Z0-9_]+)`?\s*bits?\s*\)", s)
        if m:
            return _param_default(text, m.group(1))
        return None

    for ln in text.splitlines():
        low = ln.lower()
        # section header lines
        if re.match(r"\s*[-*]?\s*\**\s*inputs?\s*[:：]\s*$", low) or \
           re.match(r"\s*#+\s*inputs?\b", low):
            section = "in"
            continue
        if re.match(r"\s*[-*]?\s*\**\s*outputs?\s*[:：]\s*$", low) or \
           re.match(r"\s*#+\s*outputs?\b", low):
            section = "out"
            continue
        # (1) range-before-name bullet:  - [7:0] in: ...
        m = re.match(r"\s*[-*]\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+)\s*[:：]", ln)
        if m and section in ("in", "out"):
            w = abs(int(m.group(1)) - int(m.group(2))) + 1
            (ins if section == "in" else outs).append((m.group(3), w))
            continue
        # (1b) range-before-name bullet with an inline Input/Output label.
        m = re.match(r"\s*[-*]\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+)\b", ln)
        if m and section in ("in", "out"):
            w = abs(int(m.group(1)) - int(m.group(2))) + 1
            (ins if section == "in" else outs).append((m.group(3), w))
            continue
        # (2) labelled bullet:  **Input**: `name` (`PARAM` bits) / (N bits)
        m = re.match(r"\s*[-*]?\s*\**\s*(input|output)s?\**\s*[:：]\s*`?(\w+)`?\s*(.*)$",
                     ln, re.I)
        if m:
            d, name, rest = m.group(1).lower(), m.group(2), m.group(3)
            w = _wtok(rest) or _wtok(ln)
            if w:
                (ins if d == "input" else outs).append((name, w))
            section = "in" if d == "input" else "out"
            continue
    return ins, outs


# --------------------------------------------------------------------------- #
# the solver (prose + interface -> RTL)                                        #
# --------------------------------------------------------------------------- #
# Positive sequential cues (a clocked / pipelined / registered datapath).
_SEQ_PROSE_RE = re.compile(
    r"(?xi)"
    r"\bsequential\b | \bsynchroniz | \bregistered\s+(?:before|output|on)\b |"
    r"\brising\s+(?:clock\s+)?edge\b | \bon\s+the\s+(?:next\s+|same\s+)?(?:rising|clock)\b |"
    r"\bpipelin | \bflip[-\s]?flop | \bsampled\s+on\b | \bhold\s+state\b |"
    r"\bnext\s+rising\s+edge\b")
# Explicit COMBINATIONAL declaration — overrides an incidental "clock" mention
# (e.g. "purely combinational module without a clock or reset").
_COMB_PROSE_RE = re.compile(
    r"(?xi)"
    r"\bpurely\s+combinational\b | \bcombinational\s+(?:logic|module|circuit)\b |"
    r"\bwithout\s+a\s+clock\b | \bno\s+clock\s+(?:or|nor|and)\s+reset\b |"
    r"\bcombinational\b[^.\n]{0,40}\bwithout\b")


def _classify_and_emit(prompt: str, top: str,
                       ins: List[Port], outs: List[Port]) -> Optional[str]:
    # No sequential / handshake ports — these are pure combinational functions.
    # Check BOTH the surviving port list AND the prose (the raw-prose path filters
    # clk/rst out of `ins` before we get here, so a clocked variant must also be
    # caught from the prose, never mis-emitted as combinational). An explicit
    # "purely combinational / without a clock" declaration wins over an incidental
    # clock mention.
    seq_port = any(n.lower() in _SEQ_PORTS for n, _ in ins + outs)
    seq_prose = bool(_SEQ_PROSE_RE.search(prompt))
    comb_decl = bool(_COMB_PROSE_RE.search(prompt))
    # A present clock/reset port is decisive — always SKIP, even if the prose
    # also (contradictorily) says "combinational".
    if seq_port:
        return None
    if seq_prose and not comb_decl:
        return None
    if _OTHER_MAPPING_RE.search(prompt):
        return None

    # Data ports only (control/handshake removed) for the emit helpers; the
    # presence of any control port was already decisive above.
    d_ins = [(n, w) for n, w in ins if n.lower() not in _SEQ_PORTS]
    d_outs = [(n, w) for n, w in outs if n.lower() not in _SEQ_PORTS]
    if not d_ins or not d_outs:
        return None

    # ----- (E) PRIORITY ENCODER ------------------------------------------- #
    if _is_priority_encoder_prose(prompt):
        return _emit_priority_encoder(prompt, top, d_ins, d_outs)

    # ----- (D) BINARY DECODER (index -> one-hot) -------------------------- #
    if _is_binary_decoder_prose(prompt):
        return _emit_binary_decoder(prompt, top, d_ins, d_outs)

    return None


def _emit_priority_encoder(prompt: str, top: str,
                           ins: List[Port], outs: List[Port]) -> Optional[str]:
    if len(ins) != 1:
        return None
    in_name, n = ins[0]
    if n < 2:
        return None

    # Direction MUST be unambiguously stated.
    direction_msb = parse_priority_direction(prompt)
    if direction_msb is None:
        return None
    # Zero-input default MUST be stated (and zero) — unless a valid flag carries it.
    zdef = _zero_default_is_zero(prompt)

    # Outputs: exactly one index output, plus optionally a 1-bit valid flag.
    valid_name = None
    idx_outs = []
    for nm, w in outs:
        if w == 1 and re.search(r"(?i)(valid|found|active|any)", nm):
            valid_name = nm
        else:
            idx_outs.append((nm, w))
    if len(idx_outs) != 1:
        return None
    out_name, w = idx_outs[0]
    expected_w = max(1, math.ceil(math.log2(n)))
    if w != expected_w:
        return None
    # If there is no valid flag, the all-zero default must be a stated 0.
    if valid_name is None and zdef is not True:
        return None
    if zdef is False:
        return None

    return _build_priority_encoder(top, in_name, n, out_name, w,
                                   direction_msb, valid_name)


def _emit_binary_decoder(prompt: str, top: str,
                         ins: List[Port], outs: List[Port]) -> Optional[str]:
    if len(ins) != 1 or len(outs) != 1:
        return None
    in_name, iw = ins[0]
    out_name, ow = outs[0]
    if iw < 1 or ow < 2:
        return None

    # Parameterized form: prose names BINARY_WIDTH / OUTPUT_WIDTH with defaults,
    # and the port_parser gave us the DEFAULT-instantiated widths. We re-emit a
    # PARAMETERIZED module (the harness builds at defaults, passing no params).
    bw = _param_default(prompt, "BINARY_WIDTH")
    ohw = _param_default(prompt, "OUTPUT_WIDTH")
    # The out-of-range guard is stated when the prose pairs an out-of-range /
    # "greater than or equal to OUTPUT_WIDTH" / "exceeds the range" condition
    # with an all-zeros output. Tolerate markdown backticks around the literal 0.
    _z = r"`?(?:0|zero|all\s+zeros?)`?"
    out_of_range_zero = bool(
        re.search(r"(?i)out[-\s]?of[-\s]?range", prompt)
        and re.search(rf"(?i)(?:output|outputs?|set)s?\s+{_z}", prompt)
    ) or bool(
        re.search(rf"(?i)\b(?:greater\s+than\s+or\s+equal\s+to|>=|exceeds?(?:\s+the\s+range\s+of)?)"
                  rf"\b[^.\n]{{0,60}}?\b(?:output|outputs?)\b[^.\n]{{0,20}}?{_z}", prompt)
    )

    if bw is not None and ohw is not None:
        # Parameterized decoder. Defaults must agree with the parsed interface.
        if iw != bw or ow != ohw:
            # interface width disagrees with the stated default -> SKIP
            return None
        return _build_param_decoder(top, in_name, out_name, bw, ohw,
                                    out_of_range_zero)

    # Fixed-width form: out width must be exactly 2**in_width (full decode) OR a
    # stated out-of-range guard must protect the partial decode.
    if ow == (1 << iw):
        return _build_fixed_decoder(top, in_name, iw, out_name, ow, False)
    if ow < (1 << iw):
        if not out_of_range_zero:
            return None                    # partial decode without a stated guard
        return _build_fixed_decoder(top, in_name, iw, out_name, ow, True)
    # ow > 2**iw : extra unreachable bits are fine (always 0); still one-hot.
    return _build_fixed_decoder(top, in_name, iw, out_name, ow, out_of_range_zero)


# --------------------------------------------------------------------------- #
# emitters                                                                     #
# --------------------------------------------------------------------------- #
def _decl(name: str, w: int, direction: str, reg: bool = False) -> str:
    kw = f"{direction} reg" if reg else direction
    return f"    {kw} {name}" if w == 1 else f"    {kw} [{w-1}:0] {name}"


def _build_priority_encoder(top, in_name, n, out_name, w, msb_first, valid_name):
    """Width-robust casez priority encoder. Arm ORDER encodes the direction:
    the FIRST matching casez arm wins, so listing high positions first makes the
    HIGHEST set bit win (MSB-first); listing low positions first makes the LOWEST
    win (LSB-first)."""
    note = "MSB-first (highest set bit)" if msb_first else "LSB-first (lowest set bit)"
    lines = [
        f"// program-SOLVED priority encoder ({note}); deterministic.",
        f"module {top} (",
    ]
    port_lines = [_decl(in_name, n, "input"),
                  _decl(out_name, w, "output", reg=True)]
    if valid_name:
        port_lines.append(_decl(valid_name, 1, "output", reg=True))
    lines.append(",\n".join(port_lines))
    lines.append(");")
    lines.append("    always @(*) begin")
    # default arm = all-zero input -> index 0 (+ valid=0 if present).
    if valid_name:
        lines.append(f"        {valid_name} = 1'b1;")
    lines.append(f"        casez ({in_name})")
    order = range(n - 1, -1, -1) if msb_first else range(n)
    for k in order:
        bits = ["z"] * n
        bits[n - 1 - k] = "1"              # string index 0 == MSB
        pattern = "".join(bits)
        lines.append(f"            {n}'b{pattern}: {out_name} = {w}'d{k};")
    # all-zero input falls through to default.
    if valid_name:
        lines.append(f"            default   : begin {out_name} = {w}'d0; "
                     f"{valid_name} = 1'b0; end")
    else:
        lines.append(f"            default   : {out_name} = {w}'d0;")
    lines += ["        endcase", "    end", "endmodule", ""]
    return "\n".join(lines)


def _build_param_decoder(top, in_name, out_name, bw, ohw, oor_zero):
    """Parameterized binary -> one-hot decoder, instantiated at the stated
    defaults (the harness passes no overrides). out = (1 << in), guarded so an
    in >= OUTPUT_WIDTH yields all-zeros when the prose states it."""
    body = (f"    assign {out_name} = ({in_name} < OUTPUT_WIDTH) ? "
            f"({{{{(OUTPUT_WIDTH-1){{1'b0}}}}, 1'b1}} << {in_name}) "
            f": {{OUTPUT_WIDTH{{1'b0}}}};") if oor_zero else \
           (f"    assign {out_name} = "
            f"{{{{(OUTPUT_WIDTH-1){{1'b0}}}}, 1'b1}} << {in_name};")
    return "\n".join([
        "// program-SOLVED parameterized binary->one-hot decoder; deterministic.",
        f"module {top} #(",
        f"    parameter BINARY_WIDTH = {bw},",
        f"    parameter OUTPUT_WIDTH = {ohw}",
        ") (",
        f"    input  [BINARY_WIDTH-1:0] {in_name},",
        f"    output [OUTPUT_WIDTH-1:0] {out_name}",
        ");",
        body,
        "endmodule",
        "",
    ])


def _build_fixed_decoder(top, in_name, iw, out_name, ow, oor_zero):
    """Fixed-width binary -> one-hot decoder, out = (1 << in)."""
    if oor_zero and ow < (1 << iw):
        body = (f"    assign {out_name} = ({in_name} < {ow}) ? "
                f"({{{{({ow}-1){{1'b0}}}}, 1'b1}} << {in_name}) : {ow}'b0;")
    else:
        body = (f"    assign {out_name} = "
                f"{{{{({ow}-1){{1'b0}}}}, 1'b1}} << {in_name};")
    return "\n".join([
        "// program-SOLVED binary->one-hot decoder; deterministic.",
        f"module {top} (",
        _decl(in_name, iw, "input") + ",",
        _decl(out_name, ow, "output"),
        ");",
        body,
        "endmodule",
        "",
    ])


# --------------------------------------------------------------------------- #
# public API                                                                   #
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    """Solve from raw prose + a stated/parseable interface. None on SKIP."""
    if not prompt_text or not prompt_text.strip():
        return None
    ins, outs = _pp.parse_ports(prompt_text)
    if not ins or not outs:
        ins, outs = _cvdp_prose_ports(prompt_text)
    if not ins or not outs:
        return None
    return _classify_and_emit(prompt_text, top, ins, outs)


def solve(record: dict) -> Optional[str]:
    """CVDP-record entry: pull the interface via the shipped atomic bridge (which
    reads the harness/skeleton/prose interface), then classify+emit. None=SKIP."""
    if not isinstance(record, dict):
        return None
    try:
        import record_prompt_context_bridge as _bridge
    except Exception:
        return None
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    if _OTHER_MAPPING_RE.search(prompt):
        # still allow the param-decoder path's own narrow OTHER cues to gate;
        # but a global non-plain mapping cue is a hard SKIP.
        if not (_is_binary_decoder_prose(prompt) and not re.search(
                r"(?xi)\bgray\b|\bbcd\b|\bone[-\s]?hot\s+to\b|\bgranularit|"
                r"\bunpack|\bsigned\b|\bsign[-\s]?extend|\baddress\s+map|"
                r"\bpipeline|\bsequencer\b|\bscancode\b|\bstack\b", prompt)):
            return None

    # Interface resolution, best source first:
    #   (a) the shipped bridge (skeleton header / cocotb / table / prose);
    #   (b) the shared port_parser bullet/header form;
    #   (c) the CVDP-prose forms (range-before-name / parameter-named width).
    iface = _bridge.extract_interface(record, top)
    if iface:
        ins, outs = iface
    else:
        ins, outs = _pp.parse_ports(prompt)
        if not ins or not outs:
            ins, outs = _cvdp_prose_ports(prompt)
    if not ins or not outs:
        return None
    return _classify_and_emit(prompt, top, ins, outs)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", help="CVDP code-generation jsonl (sweep all)")
    ap.add_argument("--prompt", help="a prose file to solve directly")
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args(argv)
    if a.prompt:
        rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
        if rtl is None:
            print("SKIP", file=sys.stderr)
            return 1
        print(rtl)
        return 0
    if a.jsonl:
        recs = [json.loads(l) for l in open(a.jsonl)]
        n = 0
        for r in recs:
            if a.id and r.get("id") != a.id:
                continue
            rtl = solve(r)
            if rtl:
                n += 1
                if a.emit or a.id:
                    print(f"=== {r.get('id')} ===")
                    print(rtl)
        print(f"emitted={n}/{len(recs)}")
        return 0
    ap.error("need --jsonl or --prompt")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
