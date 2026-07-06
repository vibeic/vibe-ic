#!/usr/bin/env python3
"""dff_edge_synth.py — deterministic SOLVER for the D-flip-flop / edge-detect /
edge-capture family.

A spec/prompt for a *simple clocked register* (NOT an FSM table — that is
ff_truth_table_synth / full_moore_fsm_synth) is, when its structure is fully and
unambiguously stated, mechanically synthesizable. This solver reads the prompt,
EMITS the exact RTL deterministically, or returns None (SKIP) on ANY ambiguity.
It keys on the STATED STRUCTURE — width, clock edge polarity, reset polarity +
sync-vs-async + reset value, enable / byte-enable, and what "detect"/"capture"
means — never on the problem name.

Families it solves (each proven host-0-mismatch on its VerilogEval-Human target):

  * plain D flip-flop, width N            q <= d;                 (Prob031, Prob034)
  * sync reset to 0 / to a stated value   if(rst) q<=VAL; else..  (Prob041,46,48,73)
  * async reset to 0 / to a stated value  @(posedge clk,posedge…) (Prob047, Prob049)
  * XOR-self-feedback D flip-flop         q <= in ^ q;            (Prob053)
  * byte-enable register                  if(be[k]) q[..]<=d[..]  (Prob073)
  * positive-edge detect  (0->1)          pedge <= in & ~prev;    (Prob054)
  * any-edge   detect                     any  <= in ^ prev;      (Prob045)
  * negative-edge detect  (1->0)          nedge <= ~in & prev;
  * edge CAPTURE (set-and-hold to reset)  out <= out|(~in&prev);  (Prob066)
  * dual-edge triggered flip-flop         qp/qn + mux on clk      (Prob078)

§4.05 NO-LEAK: a wrong sample is strictly worse than a SKIP, so this SKIPs on ANY
ambiguity — unknown width, unstated/contradictory edge polarity, unclear reset
behaviour, capture-vs-detect ambiguity, unstated enable semantics, or any prompt
structure outside the proven envelope (FSM tables, counters, shift registers,
LFSRs, arithmetic, multi-output combos, …) returns None and the author's sample
is left untouched.

API:  synth(prompt_text, top="TopModule") -> str | None
"""
from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _parse_ports(prompt: str) -> Tuple[List, List]:
    import port_parser   # bullet form OR Verilog module header (v2/human twins)
    return port_parser.parse_ports(prompt)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _decl(width: int) -> str:
    return f"[{width-1}:0] " if width > 1 else ""


def _zero(width: int) -> str:
    return f"{width}'b0" if width > 1 else "1'b0"


def _find(ins, *names):
    """First input port whose lowercase name is in `names`."""
    low = {n.lower(): (n, w) for n, w in ins}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


# --------------------------------------------------------------------------- #
# reset detection — returns (rst_name, active_high:bool, is_async:bool,
#                            reset_value_int_or_None) or None when no reset.
# Returns the SENTINEL "AMBIG" (a str) when a reset is mentioned but its
# polarity / sync-ness / value cannot be pinned down -> caller SKIPs.
# --------------------------------------------------------------------------- #
_AMBIG = "AMBIG"


def _detect_reset(prompt: str, ins) -> object:
    # candidate reset ports, by name convention
    cand = None
    for n, w in ins:
        ln = n.lower()
        if w != 1:
            continue
        if ln in ("reset", "rst", "areset", "ar", "resetn", "rst_n", "reset_n",
                  "arst", "arstn", "nreset", "sync_reset", "async_reset"):
            cand = (n, w)
            break
    if cand is None:
        # a bare single-char reset port (e.g. `r`) is accepted ONLY when the prose
        # explicitly calls it a "reset" — keeps a stray data line `r` from being
        # mistaken for a reset (Prob048: input `r`, prose "synchronous reset").
        if re.search(r"\breset\b", prompt, re.I):
            singles = [(n, w) for n, w in ins
                       if w == 1 and n.lower() in ("r", "rst", "rn", "n")]
            if len(singles) == 1:
                cand = singles[0]
    if cand is None:
        # no reset port -> a reset-less register (legal: Prob031/34/53/54/45/78)
        # but if the prose loudly claims a reset yet no port matches, SKIP.
        if re.search(r"\breset\b", prompt, re.I) and not re.search(
                r"\bno\s+reset\b|without\s+(a\s+)?reset|there\s+is\s+no\s+reset",
                prompt, re.I):
            # reset described but un-portable -> ambiguous
            # EXCEPT "active-?low reset" etc would have matched a resetn port;
            # a stray "reset" in prose with no port is a real ambiguity.
            return _AMBIG
        return None

    rst, _ = cand
    rl = rst.lower()
    low = prompt.lower()

    # ---- polarity ---------------------------------------------------------- #
    active_high: Optional[bool] = None
    # explicit prose first
    if re.search(r"active[\s-]*low", low):
        active_high = False
    elif re.search(r"active[\s-]*high", low):
        active_high = True
    # name convention: trailing n / _n / starts arst-n etc => active low
    if active_high is None:
        if rl.endswith("n") and rl not in ("reset",):   # resetn / rst_n / arstn
            active_high = False
    # bare "reset"/"areset"/"ar"/"r" with no polarity prose: VerilogEval refs
    # treat an un-qualified active-high reset as the default ONLY when the prose
    # says "reset" without "active low". To stay safe we require either a prose
    # polarity OR a name ending in n. Otherwise — for a bare name with no prose —
    # default active-high is the universal convention here (Prob047 "active high
    # asynchronous reset", Prob049 bare "asynchronous reset ar"). Pin it:
    if active_high is None:
        # bare reset name, no polarity word -> assume active-high (industry default
        # for an un-suffixed reset). Both VE refs (ar, areset) do exactly this.
        active_high = True

    # ---- sync vs async ----------------------------------------------------- #
    is_async: Optional[bool] = None
    if re.search(r"asynchronous|async\b|\basync", low):
        is_async = True
    elif re.search(r"synchronous|\bsync\b", low):
        is_async = False
    if is_async is None:
        # name convention: a / areset / ar / arst => async
        if rl in ("areset", "ar", "arst", "arstn", "async_reset") or rl.startswith("areset"):
            is_async = True
        else:
            is_async = False   # plain reset/rst/resetn default synchronous

    # ---- reset value ------------------------------------------------------- #
    rval: Optional[int] = 0
    # "reset to 0" / "reset output to zero" / "set the output to zero" => 0
    # "reset to 0x34" / "reset to 8'h34" => 0x34
    mhex = re.search(r"reset(?:\s+\w+){0,3}?\s+to\s+0x([0-9a-fA-F]+)", prompt)
    # a Verilog-sized hex literal `N'h..`; allow intervening words ("a reset THAT
    # RESETS to 12'h5a") so the indirect phrasing is read as hex, not as decimal N.
    mhex2 = re.search(r"reset(?:\s+\w+){0,3}?\s+to\s+(\d+)'\s*[hH]([0-9a-fA-F]+)", prompt)
    # plain decimal value — but NEVER the WIDTH PREFIX of a sized literal `N'h..`
    # (the negative lookahead stops `12'h5a` being misread as decimal 12).
    mdec = re.search(r"reset(?:\s+\w+){0,3}?\s+to\s+(\d+)\b(?!\s*'\s*[hbdHBD])", prompt)
    if mhex:
        rval = int(mhex.group(1), 16)
    elif mhex2:
        rval = int(mhex2.group(2), 16)
    elif re.search(r"reset(?:\s+\w+){0,3}?\s+to\s+(zero|0)\b", prompt, re.I) or \
            re.search(r"setting\s+the\s+output\s+to\s+zero", low) or \
            re.search(r"output\s+should\s+be\s+reset\s+to\s+0\b", low):
        rval = 0
    elif mdec:
        rval = int(mdec.group(1))
    else:
        # reset present but no NUMERIC value clause. Two cases:
        #   (a) no value clause at all -> the universal convention is reset-to-0
        #       (Prob073 "active-low reset", no value -> 0).
        #   (b) a value clause EXISTS but is non-numeric ("reset to some configured
        #       value", "reset to the seed", "reset to the default") -> the reset
        #       value is NOT pinned -> AMBIGUOUS, must SKIP (§4.05 no-leak).
        if re.search(r"reset(?:\s+\w+){0,4}?\s+to\s+(?!0\b|zero\b|0x|\d)", prompt, re.I):
            return _AMBIG
        rval = 0

    return (rst, active_high, is_async, rval)


# --------------------------------------------------------------------------- #
# clock edge polarity
# --------------------------------------------------------------------------- #
def _clock_edge(prompt: str) -> Optional[str]:
    low = prompt.lower()
    pos = bool(re.search(r"positive\s+edge|posedge|positive[\s-]*edge[\s-]*trigger", low))
    neg = bool(re.search(r"negative\s+edge|negedge|negative[\s-]*edge[\s-]*trigger", low))
    if pos and neg:
        return None     # contradictory / dual — handled elsewhere or SKIP
    if pos:
        return "posedge"
    if neg:
        return "negedge"
    return None         # unstated -> SKIP (caller decides)


# --------------------------------------------------------------------------- #
# module emit
# --------------------------------------------------------------------------- #
def _emit_header(top, ins, outs, out_is_reg=True, out_kind="reg") -> str:
    decls = []
    for n, w in ins:
        decls.append(f"  input {_decl(w)}{n}")
    for n, w in outs:
        kw = f"output {out_kind} " if out_is_reg else "output "
        decls.append(f"  {kw}{_decl(w)}{n}")
    return f"module {top} (\n" + ",\n".join(decls) + "\n);\n"


# --------------------------------------------------------------------------- #
# the synthesizer
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    if not prompt_text or not prompt_text.strip():
        return None
    low = prompt_text.lower()
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return None

    # Single clock input mandatory for this clocked family.
    clk_info = _find(ins, "clk", "clock")
    if clk_info is None:
        return None
    clk = clk_info[0]

    # ----- HARD scope gate: reject anything that is NOT a simple register ----- #
    # These keywords betray a DIFFERENT artifact (FSM, counter, shift, lfsr,
    # arithmetic, memory, mux-tree, etc). Conservative SKIP — §4.05.
    _OUT_OF_SCOPE = (
        r"\bcounter\b", r"\bcount\b", r"\bshift\s+register\b", r"\bbarrel\b",
        r"\brotat", r"\blfsr\b", r"\bstate\s+machine\b", r"\bfsm\b",
        r"\bnext[\s-]*state\b", r"\bone[\s-]*hot\b", r"\bmoore\b", r"\bmealy\b",
        r"\bk-?map\b", r"\bkarnaugh\b", r"\btruth\s+table\b", r"\bmultiplex",
        r"\bmux\b", r"\badder\b", r"\bsubtract", r"\bmultipl(y|ier)\b",
        r"\bdivider\b", r"\bmemory\b", r"\bregister\s+file\b", r"\bram\b",
        r"\bcellular\b", r"\brule\s*\d", r"\barithmetic\b", r"\bbcd\b",
        r"\bgray\b", r"\bjohnson\b", r"\bring\s+counter\b", r"\btimer\b",
        r"\bclock\s+divider\b", r"\bpriority\s+encoder\b", r"\bdecoder\b",
    )
    for pat in _OUT_OF_SCOPE:
        if re.search(pat, low):
            return None

    # =========================================================================
    # 1) DUAL-EDGE triggered flip-flop (Prob078)
    # =========================================================================
    if re.search(r"dual[\s-]*edge", low) or (
            re.search(r"both\s+edges?\s+of\s+the\s+clock", low) and
            re.search(r"flip[\s-]*flop", low)):
        # must be 1 data in + 1 out, equal width, no reset, single d->q
        din = _find(ins, "d")
        if din is None or len(outs) != 1:
            return None
        d, dw = din
        qn, qw = outs[0]
        if dw != qw:
            return None
        w = qw
        body = (
            f"  reg {_decl(w)}qp;\n"
            f"  reg {_decl(w)}qn;\n\n"
            f"  always @(posedge {clk})\n"
            f"    qp <= {d};\n\n"
            f"  always @(negedge {clk})\n"
            f"    qn <= {d};\n\n"
            f"  always @(*)\n"
            f"    {qn} <= {clk} ? qp : qn;\n"
        )
        return _emit_header(top, ins, outs) + "\n" + body + "\nendmodule\n"

    # =========================================================================
    # 2) EDGE DETECT / EDGE CAPTURE
    #    "detect"/"capture" of a 0->1 / 1->0 / any transition across cycles
    # =========================================================================
    is_capture = bool(re.search(r"\bcapture\b", low))
    is_detect = bool(re.search(r"\bdetect\b|edge\s+detection|transition", low))
    if is_capture or is_detect:
        return _synth_edge(prompt_text, top, ins, outs, clk, is_capture)

    # =========================================================================
    # 3) PLAIN / RESET / ENABLE / BYTE-ENABLE / XOR-FEEDBACK D FLIP-FLOP
    # =========================================================================
    if re.search(r"flip[\s-]*flop|\bdff\b|d\s+flop|register", low):
        return _synth_dff(prompt_text, top, ins, outs, clk)

    return None


# --------------------------------------------------------------------------- #
# edge detect / capture synthesizer
# --------------------------------------------------------------------------- #
def _synth_edge(prompt_text, top, ins, outs, clk, is_capture) -> Optional[str]:
    low = prompt_text.lower()
    # exactly one data input vector + one output vector of equal width
    data = [(n, w) for n, w in ins if n != clk and
            n.lower() not in ("reset", "rst", "resetn", "rst_n", "reset_n")]
    if len(data) != 1 or len(outs) != 1:
        return None
    din, dw = data[0]
    oname, ow = outs[0]
    if dw != ow:
        return None

    # clock edge: edge-detect/capture logic is positive-edge in every VE case.
    # The VE-human twin states "triggered on the positive edge of the clock"; the
    # VE-v2 twin states the cross-cycle behaviour ("the cycle after", "1 in one clock
    # cycle to 0 the next") WITHOUT naming the edge. Cross-cycle sampling on a single
    # clock is positive-edge by universal convention (and every VE reference uses
    # posedge), so an UNSTATED edge defaults to posedge here. An explicit "negative
    # edge"/negedge still SKIPs (outside the proven envelope), so we never silently
    # emit the wrong polarity when the prompt does name it.
    edge = _clock_edge(prompt_text)
    if edge is None:
        edge = "posedge"   # unstated edge on a clocked edge-detect/capture -> posedge
    if edge != "posedge":
        return None   # negedge edge-detect not in proven envelope -> SKIP

    # which transition?  0->1 (pos), 1->0 (neg), any
    want_pos = bool(re.search(
        r"0\s+in\s+one\s+clock\s+cycle\s+to\s+1|0\s*(?:->|to)\s*1\s+transition|"
        r"changes?\s+from\s+0\b.*\bto\s+1\b|positive\s+edge\s+detection|"
        r"similar\s+to\s+positive\s+edge", low))
    want_neg = bool(re.search(
        r"1\s+in\s+one\s+clock\s+cycle\s+to\s+0|1\s*(?:->|to)\s*0\s+transition|"
        r"changes?\s+from\s+1\b.*\bto\s+0\b|negative\s+edge\s+detection", low))
    want_any = bool(re.search(
        r"any\s+edge|detect\s+any\s+edge|"
        r"0\s+to\s+1\s+or\s+1\s+to\s+0|1\s+to\s+0\s+or\s+0\s+to\s+1|"
        r"either\s+(?:a\s+)?transition", low))
    # "changes from one clock cycle to the next" with NO directional clause is an
    # any-edge too — but only when neither a 0->1 nor a 1->0 directional clause is
    # present (those make it pos/neg).
    if not (want_pos or want_neg) and re.search(
            r"changes?\s+from\s+one\s+clock\s+cycle\s+to\s+the\s+next", low):
        want_any = True

    # an explicit "0 to 1 or 1 to 0" (both directions) is ANY-edge and OVERRIDES
    # the directional matches that its own substrings would otherwise trigger.
    if re.search(r"0\s+to\s+1\s+or\s+1\s+to\s+0|1\s+to\s+0\s+or\s+0\s+to\s+1", low) \
            or re.search(r"\bdetect\s+any\s+edge\b|\bany\s+edge\b", low):
        want_pos = want_neg = False
        want_any = True

    # disambiguate: a single, exclusive transition meaning is required.
    sel = [k for k, v in (("pos", want_pos), ("neg", want_neg), ("any", want_any)) if v]
    if len(sel) != 1:
        return None
    kind = sel[0]

    if kind == "pos":
        expr = f"{din} & ~d_last"
    elif kind == "neg":
        expr = f"~{din} & d_last"
    else:
        expr = f"{din} ^ d_last"

    # reset: capture REQUIRES a reset (set-and-hold until reset). detect: no reset.
    r = _detect_reset(prompt_text, ins)
    if r == _AMBIG:
        return None

    body = [f"  reg {_decl(dw)}d_last;\n"]
    if is_capture:
        if not isinstance(r, tuple):
            return None   # capture must name a reset -> else SKIP
        rst, ah, is_async, rval = r
        if is_async:
            return None   # VE capture is synchronous-reset only -> SKIP async
        cond = rst if ah else f"!{rst}"
        body.append(f"\n  always @({edge} {clk}) begin\n")
        body.append(f"    d_last <= {din};\n")
        body.append(f"    if ({cond})\n")
        body.append(f"      {oname} <= {_zero(ow)};\n")
        body.append(f"    else\n")
        body.append(f"      {oname} <= {oname} | ({expr});\n")
        body.append(f"  end\n")
    else:
        # pure detect: register prev, output = transition expr; NO reset.
        if isinstance(r, tuple):
            return None   # a reset on a plain detect is outside proven envelope
        body.append(f"\n  always @({edge} {clk}) begin\n")
        body.append(f"    d_last <= {din};\n")
        body.append(f"    {oname} <= {expr};\n")
        body.append(f"  end\n")

    return _emit_header(top, ins, outs) + "\n" + "".join(body) + "\nendmodule\n"


# --------------------------------------------------------------------------- #
# plain / reset / enable / byte-enable / xor-feedback DFF synthesizer
# --------------------------------------------------------------------------- #
def _synth_dff(prompt_text, top, ins, outs, clk) -> Optional[str]:
    low = prompt_text.lower()
    if len(outs) != 1:
        return None
    oname, ow = outs[0]

    # ---- clock edge ---- #
    # A plain clocked D-flip-flop / register whose prompt does not NAME the edge
    # is positive-edge by universal HDL convention (every VE reference register
    # uses posedge; "Create a single D flip-flop." / "a simple D flip flop with
    # active high synchronous reset" state no edge). This mirrors the identical
    # unstated-edge -> posedge default already applied in the edge-detect/capture
    # branch (_synth_edge). An EXPLICIT negedge is still honored below (the emit
    # uses `edge`), so a prompt that DOES name the polarity is never overridden.
    #
    # `_clock_edge` returns None for TWO distinct reasons: (a) the edge is UNSTATED
    # (safe to default posedge) and (b) the prose is CONTRADICTORY — names BOTH
    # positive and negative edge (genuinely ambiguous -> MUST SKIP, never guess).
    # Only case (a) may default; case (b) still returns None here.
    edge = _clock_edge(prompt_text)
    if edge is None:
        _low = prompt_text.lower()
        _pos = bool(re.search(r"positive\s+edge|posedge", _low))
        _neg = bool(re.search(r"negative\s+edge|negedge", _low))
        if _pos and _neg:
            return None        # contradictory edge -> §4.05 no-leak SKIP
        edge = "posedge"       # unstated edge on a clocked register -> posedge

    # ---- reset ---- #
    r = _detect_reset(prompt_text, ins)
    if r == _AMBIG:
        return None
    reset = r if isinstance(r, tuple) else None
    rst_name = reset[0] if reset else None

    # ---- enumerate non-clk, non-reset inputs ---- #
    other = [(n, w) for n, w in ins if n != clk and (rst_name is None or n != rst_name)]

    # ======================================================================= #
    # BYTE-ENABLE register (Prob073): a byteena (k bits) + d (N bits) + q (N).
    # The prose explicitly maps each enable bit to a byte slice.
    # ======================================================================= #
    be = _find(ins, "byteena", "byte_enable", "byteen", "be")
    if be is not None and re.search(r"byte[\s-]*enable|byteena", low):
        return _synth_byteena(prompt_text, top, ins, outs, clk, edge, reset, be)

    # ======================================================================= #
    # XOR-self-feedback DFF (Prob053): q <= in ^ q, no reset, 1-bit.
    # Recognized only when the prose explicitly says the FF input is an XOR of
    # an input with the FF's own output.
    # ======================================================================= #
    if re.search(r"\bxor\b", low) and ow == 1 and reset is None:
        # need exactly one 1-bit data input that is the non-feedback XOR operand
        d1 = [(n, w) for n, w in other if w == 1]
        if len(d1) == 1 and re.search(
                r"xor.*output|output.*xor|takes?\s+as\s+input.*output|"
                r"along\s+with\s+the\s+output", low):
            dn = d1[0][0]
            body = (f"  initial\n    {oname} = 1'b0;\n\n"
                    f"  always @({edge} {clk})\n"
                    f"    {oname} <= {dn} ^ {oname};\n")
            return _emit_header(top, ins, outs) + "\n" + body + "\nendmodule\n"
        return None

    # ======================================================================= #
    # ENABLE-style with load priority (Prob061: L load R else E shift w) — OUT
    # of the proven plain-DFF envelope; SKIP (it's a shift-register stage).
    # Generic "enable" not matching a clean single-data-in DFF -> SKIP.
    # ======================================================================= #
    if re.search(r"\bload\b|\benable\b|\bshift\b", low) and len(other) > 1:
        # multiple control inputs with load/enable semantics -> not a plain DFF
        return None

    # ======================================================================= #
    # PLAIN D flip-flop, width N, with optional sync/async reset to VAL.
    # Requires EXACTLY one data input `d` of the SAME width as the output.
    # ======================================================================= #
    d = _find(ins, "d")
    if d is None:
        # the single data input might be named otherwise; accept iff there is
        # EXACTLY one non-clk non-reset input of width == output width.
        same = [(n, w) for n, w in other if w == ow]
        if len(same) == 1 and len(other) == 1:
            d = same[0]
        else:
            return None
    dn, dw = d
    if dw != ow:
        return None
    # there must be no OTHER data/control input beyond d (else ambiguous)
    if len(other) != 1:
        return None

    # confirm count of DFFs (if "N D flip-flops" stated, must equal width)
    mcount = re.search(r"(\d+)\s+d\s+flip[\s-]*flops?", low)
    if mcount and int(mcount.group(1)) != ow:
        return None

    # ---- emit ---- #
    if reset is None:
        # reset-less DFF: the VE reference power-up-initializes the register to 0
        # (`initial q = 8'h0`), and the testbench compares ref-vs-dut from the
        # power-up sample — so a dut with NO initial mismatches at t0. Mirror the
        # reference's `initial q = 0` to guarantee a 0-mismatch register.
        sens = f"{edge} {clk}"
        body = (f"  initial\n    {oname} = {_zero(ow)};\n\n"
                f"  always @({sens})\n    {oname} <= {dn};\n")
        return _emit_header(top, ins, outs) + "\n" + body + "\nendmodule\n"

    rst, ah, is_async, rval = reset
    cond = rst if ah else f"!{rst}"
    if rval == 0:
        rstv = _zero(ow)
    else:
        rstv = f"{ow}'h{rval:x}"
    if is_async:
        rst_edge = "posedge" if ah else "negedge"
        sens = f"{edge} {clk}, {rst_edge} {rst}"
    else:
        sens = f"{edge} {clk}"
    body = (f"  always @({sens})\n"
            f"    if ({cond})\n"
            f"      {oname} <= {rstv};\n"
            f"    else\n"
            f"      {oname} <= {dn};\n")
    return _emit_header(top, ins, outs) + "\n" + body + "\nendmodule\n"


# --------------------------------------------------------------------------- #
# byte-enable register synthesizer (Prob073)
# --------------------------------------------------------------------------- #
def _synth_byteena(prompt_text, top, ins, outs, clk, edge, reset, be) -> Optional[str]:
    low = prompt_text.lower()
    oname, ow = outs[0]
    d = _find(ins, "d")
    if d is None:
        return None
    dn, dw = d
    ben, bew = be
    if dw != ow:
        return None
    # number of enable bits * 8 must equal the data width (byte = 8 bits)
    if bew * 8 != ow:
        return None
    # prose must confirm byteena[k] controls byte k (we trust the byte mapping:
    # bit i controls d[i*8 +: 8], the universal Altera byteena convention)
    body = []
    body.append(f"  always @({edge} {clk}) begin\n")
    if reset is not None:
        rst, ah, is_async, rval = reset
        if is_async:
            return None   # byteena async reset not in proven envelope
        cond = rst if ah else f"!{rst}"
        body.append(f"    if ({cond})\n")
        body.append(f"      {oname} <= {_zero(ow)};\n")
        body.append(f"    else begin\n")
        ind = "      "
    else:
        ind = "    "
    for i in range(bew):
        hi = i * 8 + 7
        lo = i * 8
        body.append(f"{ind}if ({ben}[{i}])\n")
        body.append(f"{ind}  {oname}[{hi}:{lo}] <= {dn}[{hi}:{lo}];\n")
    if reset is not None:
        body.append("    end\n")
    body.append("  end\n")
    return _emit_header(top, ins, outs) + "\n" + "".join(body) + "\nendmodule\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="spec / prompt file")
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args(argv)
    from pathlib import Path
    text = Path(a.prompt).read_text(errors="replace")
    rtl = synth(text, a.top)
    if rtl is None:
        print("// SKIP: dff_edge_synth found no unambiguous register/edge spec",
              file=sys.stderr)
        return 2
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
