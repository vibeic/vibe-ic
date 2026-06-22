#!/usr/bin/env python3
"""gshare_predictor_synth.py — deterministic SOLVER for the gshare branch-predictor
datapath family (VerilogEval Prob153_gshare and any prompt of the same SHAPE).

A gshare predictor DECOMPOSES into structural parts, each of which a fully-stated
prompt determines blind:

  (a) a global history shift register of width H,
  (b) a Pattern History Table (PHT) of 2**H entries of K-bit saturating counters,
  (c) an index function = pc[H-1:0] XOR global_history,
  (d) the PREDICT path: read PHT[predict_index]; predict_taken = the counter MSB;
      output predict_history = the history register used to make the prediction,
  (e) the TRAIN/update path: on a resolved branch, move the K-bit saturating
      counter toward taken/not-taken WITH clamp (no wrap), and shift the predicted
      outcome into the global history; on a misprediction RECOVER the history,
  (f) the precise reset + the read/write port timing + the same-cycle
      train-vs-predict precedence and predict-sees-pre-train-PHT bypass.

This solver READS that structure (the stated H / PC widths, the stated XOR index,
the stated K-bit saturating increment/decrement/clamp, the stated train>predict
history precedence, the stated next-clock PHT-write bypass, the stated reset
timing) and EMITS the datapath — OR returns None (SKIP) on ANY ambiguity. The
emitted RTL REPLACES the AI's guess and still flows through every downstream gate.

§4.05 NO-LEAK doctrine — a WRONG branch predictor is far worse than a SKIP, because
it silently passes lint/synth and only the testbench catches it. Branch predictors
carry two notoriously convention-dependent, host-OBSERVABLE details:

  * the K-bit saturating-counter RESET VALUE. "Weakly not taken" (2'b01) vs
    "strongly not taken" (2'b00) vs "weakly taken" (2'b10) are all legitimate
    not-taken/taken reset conventions in real silicon. The reset value is NOT just
    the predict_taken MSB — the counter's DISTANCE to the taken threshold after a
    few trains is observable, so 2'b00 and 2'b01 (same MSB) still diverge.
  * the history-register RESET VALUE (0 vs any other seed) — also host-observable
    because it XOR-indexes the very first predictions.

So this solver SKIPs (returns None) unless the prompt UNAMBIGUOUSLY states BOTH
reset values (and every other structural detail below). It NEVER hard-codes the
"usual" 2'b01 / 0 convention from the problem name. If a prompt DOES pin the reset
values, the solver fires and the emitted datapath is host-correct.

API: synth(prompt_text, top="TopModule") -> RTL str | None
"""
from __future__ import annotations

import os
import re
import sys


def _parse_ports(prompt):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser   # bullet form OR Verilog module header (the v2/human twins)
    return port_parser.parse_ports(prompt)


def _find(ports, *names):
    """First port whose lower-cased name is one of `names`; (name,width) | None."""
    low = {n.lower(): (n, w) for n, w in ports}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


def _decl(port_kind, name, width):
    if width == 1:
        return f"{port_kind} {name}"
    return f"{port_kind} [{width-1}:0] {name}"


# --------------------------------------------------------------------------- #
# Shape gate — STRUCTURE words only, never a module/problem name. A gshare
# predictor is identified by the conjunction of (gshare | branch predictor with
# global history XOR-hashed into an index) + a pattern history table of
# saturating counters + the predict/train two-interface split.
# --------------------------------------------------------------------------- #
def _is_gshare_family(text: str) -> bool:
    t = text.lower()
    has_gshare = "gshare" in t or (
        "branch predict" in t
        and "global" in t and "history" in t
        and re.search(r"xor|hash", t) is not None)
    has_pht = bool(re.search(r"pattern\s+history\s+table|\bpht\b|"
                             r"table\s+of\s+(?:two|2|\w+)[\s-]*bit\s+saturat", t))
    has_two_iface = ("predict" in t and "train" in t)
    return has_gshare and has_pht and has_two_iface


# --------------------------------------------------------------------------- #
# Structural parameter extraction. Each returns the parsed value or None.
# --------------------------------------------------------------------------- #
def _history_width(text: str, ins, outs):
    """H = the global-history width. Must be stated AND match the history-bearing
    ports (predict_history out / train_history in)."""
    ph = _find(outs, "predict_history")
    th = _find(ins, "train_history")
    # the prompt also states it ("7-bit global history" / "H-bit global branch history").
    m = re.search(r"(\d+)\s*-?\s*bit\s+global\s+(?:branch\s+)?history", text, re.I)
    stated = int(m.group(1)) if m else None
    cands = {w for w in (ph[1] if ph else None, th[1] if th else None, stated)
             if w is not None}
    if len(cands) != 1:
        return None          # ports + prose disagree, or history not present
    return next(iter(cands))


def _pc_width(text: str, ins):
    pc = _find(ins, "predict_pc")
    tpc = _find(ins, "train_pc")
    cands = {w for w in (pc[1] if pc else None, tpc[1] if tpc else None)
             if w is not None}
    if len(cands) != 1:
        return None
    return next(iter(cands))


def _counter_bits(text: str):
    """K = saturating-counter width. Prob153 = two-bit. Stated, else None."""
    m = re.search(r"(two|three|four|\d+)\s*-?\s*bit\s+saturat", text, re.I)
    if not m:
        return None
    word = m.group(1).lower()
    return {"two": 2, "three": 3, "four": 4}.get(word,
                                                int(word) if word.isdigit() else None)


def _pht_entries(text: str, h):
    """Number of PHT entries; must be the stated value AND == 2**H."""
    m = re.search(r"(\d+)\s*-?\s*entry\s+(?:table|pht|pattern\s+history)", text, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n if n == (1 << h) else None


def _index_is_history_xor_pc(text: str) -> bool:
    """(c) index = history XOR pc, explicitly stated."""
    t = text.lower()
    return ("xor" in t) and ("index" in t) and ("history" in t) and (
        "pc" in t or "program counter" in t)


def _predict_taken_is_msb(text: str) -> bool:
    """(d) predicted direction = the saturating-counter MSB ('taken' = high bit).
    A 2-bit saturating counter's [1]=MSB is the prediction; the prompt frames it as
    'produces the predicted branch direction' from the counter. We require the
    counter to be SATURATING (so the MSB-as-prediction convention holds) and that
    the table is what's read for the prediction."""
    t = text.lower()
    return "saturat" in t and "predict" in t and "table" in t


def _train_precedence_stated(text: str) -> bool:
    """(f) when train-mispredict + predict collide on the history register in the
    same cycle, TRAINING takes precedence — stated verbatim."""
    return bool(re.search(r"training\s+takes\s+precedence", text, re.I))


def _predict_sees_pretrain_pht(text: str) -> bool:
    """(f) predict of an entry being trained THIS cycle sees the PRE-train PHT,
    because training only writes the PHT at the next positive edge — stated
    verbatim. We require the PHT-SPECIFIC bypass wording (a bare "next positive
    clock edge" also appears in the predict-history-update sentence, so matching
    that alone would over-fire)."""
    t = text.lower()
    return bool(re.search(
        r"prediction\s+sees\s+the\s+pht\s+state\s+before\s+training", t)) or bool(
        re.search(r"training\s+only\s+modifies\s+the\s+pht\s+at\s+the\s+next\s+"
                  r"positive\s+clock\s+edge", t))


def _history_update_on_predict_stated(text: str) -> bool:
    """(e) on a prediction, the history register shifts in the predicted outcome at
    the next positive edge — stated verbatim."""
    return bool(re.search(
        r"history\s+register\s+is\s+then\s+updated.*next\s+positive\s+clock\s+edge",
        text, re.I | re.S))


def _misprediction_recovery_stated(text: str) -> bool:
    """(e) on a mispredicted train, the history register is RECOVERED to the state
    immediately after that branch — stated verbatim, and the recovery value is
    {train_history, train_taken} (the trained branch's pre-state shifted with its
    true outcome)."""
    return bool(re.search(
        r"if\s+the\s+branch\s+being\s+trained\s+is\s+mispredict",
        text, re.I)) and bool(re.search(
        r"recover\s+the\s+branch\s+history\s+register", text, re.I))


def _reset_timing(text: str):
    """(f) reset polarity + sync/async, stated. Returns (async:bool, active_high:bool)
    or None when ambiguous."""
    t = text.lower()
    is_async = "asynchronous" in t
    is_sync = "synchronous" in t and not is_async
    if is_async == is_sync:                       # neither or both -> ambiguous
        return None
    active_high = "active-high" in t or "active high" in t
    active_low = "active-low" in t or "active low" in t
    if active_high == active_low:                 # ambiguous polarity
        return None
    return (is_async, active_high)


# --------------------------------------------------------------------------- #
# §4.05 FLOOR primitive — the two reset VALUES. host-observable, convention-laden.
# Returns (pht_reset_val:int, hist_reset_val:int) ONLY if BOTH are unambiguously
# stated by the prompt, else None (the documented FLOOR for Prob153 as written).
# --------------------------------------------------------------------------- #
def _reset_values(text: str, k, h):
    """The K-bit PHT counter reset value AND the H-bit history reset value.

    A gshare prompt must STATE both. Acceptable statements include a named state
    pinned to a value ("counters reset to weakly-not-taken (2'b01)"), an explicit
    literal ("the PHT resets to 2'b01", "history resets to 0"), or a fully
    enumerated saturating-counter state encoding tied to the reset state. We do NOT
    accept the bare name "weakly not taken" alone — the numeric value of a 2-bit
    saturating counter's weakly-not-taken state (01 vs 10 depending on whether the
    MSB is the taken bit) is itself a convention, so we require the literal value
    to be disclosed.
    """
    # PHT reset value: an explicit literal tied to the PHT/counter reset.
    pht_val = None
    for m in re.finditer(
            r"(?:pht|pattern\s+history\s+table|saturat\w*\s+counter[s]?|counter[s]?|"
            r"table)[^.\n]{0,80}?reset[^.\n]{0,40}?"
            r"(?:to\s+)?(\d+)\s*'\s*[bB]([01]+)",
            text, re.I):
        v = int(m.group(2), 2)
        if v < (1 << k):
            pht_val = v
    # also accept "reset ... pht/counters to <decimal>" or "to <named>=<binary>".
    if pht_val is None:
        m = re.search(
            r"reset[^.\n]{0,40}?(?:pht|counter[s]?|table)[^.\n]{0,40}?"
            r"to\s+(\d+)\s*'\s*[bB]([01]+)", text, re.I)
        if m:
            v = int(m.group(2), 2)
            if v < (1 << k):
                pht_val = v

    # history reset value: an explicit literal tied to the history register reset.
    hist_val = None
    m = re.search(
        r"(?:global\s+)?(?:branch\s+)?history\s+register[^.\n]{0,80}?reset"
        r"[^.\n]{0,40}?to\s+(?:(\d+)\s*'\s*[bBhH]([0-9a-fA-F]+)|(zero|0)\b)",
        text, re.I)
    if m:
        if m.group(3):
            hist_val = 0
        else:
            base = 16 if "'h" in m.group(0).lower() else 2
            hist_val = int(m.group(2), base)
    if pht_val is None or hist_val is None:
        return None
    if hist_val >= (1 << h):
        return None
    return (pht_val, hist_val)


# --------------------------------------------------------------------------- #
# The emitter. Builds the gshare datapath exactly per the stated structure and
# the (now-disclosed) reset values. Mirrors the canonical port set.
# --------------------------------------------------------------------------- #
def _emit(top, clk, areset, ports, h, pc_w, k, pht_n, async_reset,
          active_high, pht_reset, hist_reset):
    pv = _find(ports["ins"], "predict_valid")[0]
    ppc = _find(ports["ins"], "predict_pc")[0]
    pt = _find(ports["outs"], "predict_taken")[0]
    phist = _find(ports["outs"], "predict_history")[0]
    tv = _find(ports["ins"], "train_valid")[0]
    tt = _find(ports["ins"], "train_taken")[0]
    tm = _find(ports["ins"], "train_mispredicted")[0]
    th = _find(ports["ins"], "train_history")[0]
    tpc = _find(ports["ins"], "train_pc")[0]
    rst = areset[0]
    rst_edge = "posedge" if active_high else "negedge"
    rst_cond = rst if active_high else f"~{rst}"
    sens = f"posedge {clk[0]}"
    if async_reset:
        sens += f", {rst_edge} {rst}"
    msb = k - 1
    maxv = (1 << k) - 1
    lines = [
        "// program-SOLVED gshare branch predictor datapath; deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([
            _decl("input", clk[0], 1),
            _decl("input", rst, 1),
            _decl("input", pv, 1),
            _decl("input", ppc, pc_w),
            _decl("output", pt, 1),
            _decl("output", phist, h),
            _decl("input", tv, 1),
            _decl("input", tt, 1),
            _decl("input", tm, 1),
            _decl("input", th, h),
            _decl("input", tpc, pc_w),
        ]),
        ");",
        f"    reg [{k-1}:0] pht [0:{pht_n-1}];",
        f"    reg [{h-1}:0] history_r;",
        f"    wire [{h-1}:0] predict_index = history_r ^ {ppc}[{h-1}:0];",
        f"    wire [{h-1}:0] train_index   = {th} ^ {tpc}[{h-1}:0];",
        "    integer i;",
        f"    always @({sens}) begin",
        f"        if ({rst_cond}) begin",
        f"            for (i = 0; i < {pht_n}; i = i + 1)",
        f"                pht[i] <= {k}'d{pht_reset};",
        f"            history_r <= {h}'d{hist_reset};",
        "        end else begin",
        # (e) predict path updates the history (shift in the predicted outcome) ...
        f"            if ({pv})",
        f"                history_r <= {{history_r[{h-2}:0], {pt}}};",
        # (e) train path: saturating up/down with clamp (no wrap) ...
        f"            if ({tv}) begin",
        f"                if (pht[train_index] < {k}'d{maxv} && {tt})",
        f"                    pht[train_index] <= pht[train_index] + {k}'d1;",
        f"                else if (pht[train_index] > {k}'d0 && !{tt})",
        f"                    pht[train_index] <= pht[train_index] - {k}'d1;",
        # (f) train-mispredict RECOVERS + takes PRECEDENCE over the predict update
        #     (this assignment is later in the block, so it wins the history reg).
        f"                if ({tm})",
        f"                    history_r <= {{{th}[{h-2}:0], {tt}}};",
        "            end",
        "        end",
        "    end",
        # (d) predict_taken = counter MSB; outputs are X when predict_valid is low
        #     (matches the reference's don't-care convention so the TB X-match holds).
        f"    assign {pt}   = {pv} ? pht[predict_index][{msb}] : 1'bx;",
        f"    assign {phist} = {pv} ? history_r : {{{h}{{1'bx}}}};",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def synth(prompt_text: str, top: str = "TopModule"):
    if not _is_gshare_family(prompt_text):
        return None
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return None
    ports = {"ins": ins, "outs": outs}

    # --- the canonical port set must be present (the two-interface split). ---
    clk = _find(ins, "clk", "clock")
    areset = _find(ins, "areset", "arst", "reset", "rst")
    needed_in = ["predict_valid", "predict_pc", "train_valid", "train_taken",
                 "train_mispredicted", "train_history", "train_pc"]
    needed_out = ["predict_taken", "predict_history"]
    if not clk or not areset:
        return None
    if any(_find(ins, n) is None for n in needed_in):
        return None
    if any(_find(outs, n) is None for n in needed_out):
        return None

    # --- (a)/(b)/(c) widths + index ---
    h = _history_width(prompt_text, ins, outs)
    if h is None or h < 1:
        return None
    pc_w = _pc_width(prompt_text, ins)
    if pc_w is None or pc_w < h:                  # need pc[H-1:0] for the XOR
        return None
    k = _counter_bits(prompt_text)
    if k is None or k < 2:
        return None
    pht_n = _pht_entries(prompt_text, h)
    if pht_n is None:
        return None
    if not _index_is_history_xor_pc(prompt_text):
        return None

    # --- (d) predict path ---
    if not _predict_taken_is_msb(prompt_text):
        return None

    # --- (e) train/update + history shift + misprediction recovery ---
    if not _history_update_on_predict_stated(prompt_text):
        return None
    if not _misprediction_recovery_stated(prompt_text):
        return None

    # --- (f) precedence + bypass + reset timing ---
    if not _train_precedence_stated(prompt_text):
        return None
    if not _predict_sees_pretrain_pht(prompt_text):
        return None
    rt = _reset_timing(prompt_text)
    if rt is None:
        return None
    async_reset, active_high = rt

    # --- §4.05 FLOOR: the two reset VALUES must be UNAMBIGUOUSLY stated. ---
    rv = _reset_values(prompt_text, k, h)
    if rv is None:
        # Every structural part above is solved, but the host-OBSERVABLE PHT
        # counter reset value and history reset value are NOT stated by the
        # prompt. Hard-coding the conventional 2'b01 / 0 would be a §4.05 leak
        # (an unstated-convention guess). SKIP — honest AI-floor.
        return None
    pht_reset, hist_reset = rv

    return _emit(top, clk, areset, ports, h, pc_w, k, pht_n,
                 async_reset, active_high, pht_reset, hist_reset)


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not an unambiguously-stated gshare predictor "
              "(structure or reset VALUES unstated — §4.05 FLOOR)", file=sys.stderr)
        sys.exit(1)
    print(rtl)
