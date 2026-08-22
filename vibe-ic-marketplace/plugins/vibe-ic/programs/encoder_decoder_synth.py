#!/usr/bin/env python3
"""encoder_decoder_synth.py — deterministic SOLVER for the PRIORITY-ENCODER family.

A priority-encoder prompt that states its structure unambiguously is fully
determined, blind: the width N of the one input vector, the direction in which
priority is resolved (which set bit "wins"), and the value emitted when the
input vector is all-zero. This solver reads the stated interface (via the SHARED
port_parser) plus the prose that fixes those three facts, and EMITS correct
synthesizable RTL, or returns None (SKIP) on ANY ambiguity. It never guesses an
unstated direction or an unstated zero-input default.

The recognized STRUCTURE (keyed on stated behavior, NOT on port names):

  * exactly ONE multi-bit input vector `in` of width N, and exactly ONE output
    `pos` of width W; the output reports the bit POSITION of the winning set
    bit. W must be exactly the minimum width that holds the largest position
    index N-1 (i.e. W == ceil(log2(N))) — otherwise the stated interface and
    the stated behavior disagree and we SKIP.

  * DIRECTION must be unambiguously stated as LSB-first — the FIRST / LEAST
    SIGNIFICANT set bit wins (the dataset's two members, Prob071 casez and
    Prob112 dense-case, are both LSB-first). An MSB-first / "highest set bit"
    request, or an unstated direction, => SKIP (we do not guess).

  * ZERO-INPUT DEFAULT must be explicitly stated (e.g. "report zero if the
    input has no bits set", "if none of the input bits are high, output zero").
    Priority-encoder convention is NOT universal (some designs add a separate
    `valid` flag, some emit all-ones); an UNSTATED zero default => SKIP.

The emitted RTL is the canonical width-robust casez priority encoder:

    casez (in)
      default     : pos = 0;          // all-zero input -> stated default (0)
      N'b...zzz1  : pos = 0;          // LSB set         -> position 0
      N'b...zz1z  : pos = 1;
      ...
      N'b1zz...zz : pos = N-1;        // MSB set         -> position N-1
    endcase

The first matching casez arm wins in source order; listing low positions first
makes the lowest (least-significant) set bit win, which IS LSB-first priority.
This is functionally identical to Prob112's fully-enumerated dense `case` for an
LSB-first encoder, and identical to Prob071's casez, for any width N.

§4.05 NO-LEAK — SKIP (return None) unless EVERY one of these is unambiguous:
  * the prose actually describes a priority encoder / "position of the first
    set bit" (a bare "encoder"/"select"/"decoder" token does NOT qualify);
  * exactly one multi-bit input vector and exactly one output, no clock / reset
    / enable / valid / handshake ports (a pure combinational encoder has none);
  * a definite input width N >= 2 and an output width W == ceil(log2(N));
  * direction is stated AND is LSB-first (MSB-first or unstated => SKIP);
  * the all-zero-input default value is stated AND is zero (any other / unstated
    default => SKIP — including the "report a valid flag instead" variant).

API: synth(prompt_text, top="TopModule") -> str | None
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import port_parser as _pp  # noqa: E402  reuse the SHARED interface reader


# --------------------------------------------------------------------------- #
# prose helpers — all chip-AGNOSTIC, keyed on stated structure                #
# --------------------------------------------------------------------------- #
def _is_priority_encoder_prose(text: str) -> bool:
    """True iff the prose describes a priority encoder / first-set-bit position.

    Requires an explicit priority-encoder signature. We do NOT fire on a bare
    'encoder' / 'select' / 'position' token, which can describe other functions.
    """
    t = text.lower()
    if re.search(r"\bpriority\s+encoder\b", t):
        return True
    # "report/output the position of the first 1 bit" style, without the words
    # "priority encoder" — still a priority encoder if it asks for the position
    # of the first/first-set bit in a vector.
    if re.search(
        r"\bposition\s+of\s+the\s+(?:first|lowest|least[-\s]significant)\b.{0,40}\bbit\b",
        t,
    ) and re.search(r"\bbit\b.{0,30}\b(?:that\s+is\s+)?(?:1|one|high|set)\b", t):
        return True
    return False


def _has_disqualifying_function(text: str) -> bool:
    """True iff the prose is a DIFFERENT (non-priority-encoder) function => SKIP.

    Catches the near-miss families that also speak about bits/positions/select
    but are not an LSB-first priority encoder: multiplexers, decoders, demuxes,
    arbiters, barrel shifters, generic lookup tables, etc.
    """
    t = text.lower()
    return bool(
        re.search(
            r"\b(multiplexer|demultiplex|demux|arbiter|round[-\s]?robin|"
            r"barrel\s+shift|decoder|scancode|scan\s*code|shift\s+register|"
            r"state\s+machine|memory)\b",
            t,
        )
    )


def _direction_is_lsb_first(text: str):
    """Return True (LSB-first), False (MSB-first), or None (unstated/ambiguous).

    LSB-first: the FIRST / LEAST-SIGNIFICANT / LOWEST set bit wins.
    MSB-first: the HIGHEST / MOST-SIGNIFICANT set bit wins (we SKIP those — we
    do not author a direction the dataset members don't share, but we DETECT it
    so we never mis-emit an LSB encoder for an MSB request).
    """
    t = text.lower()
    lsb = bool(
        re.search(
            r"\b(?:first|lowest|least[-\s]significant)\b.{0,40}\bbit\b", t
        )
        or re.search(r"\bfirst\s+(?:1|one|high|set)\b", t)
        or re.search(r"\bleast[-\s]significant\b", t)
    )
    msb = bool(
        re.search(
            r"\b(?:last|highest|most[-\s]significant)\b.{0,40}\bbit\b", t
        )
        or re.search(r"\bmost[-\s]significant\b", t)
        or re.search(r"\bhighest\s+(?:set\s+)?bit\b", t)
    )
    if lsb and not msb:
        return True
    if msb and not lsb:
        return False
    return None  # neither stated, or BOTH appear (contradictory) -> ambiguous


def _zero_default_is_zero(text: str):
    """Return True iff the all-zero input default is unambiguously stated as 0.

    Returns True  : an explicit "if no bits set / input is zero -> output zero".
    Returns False : an explicit zero-input default that is NOT zero (e.g. a
                    separate valid flag is the actual signal, or all-ones).
    Returns None  : the zero-input behavior is not stated at all -> ambiguous.

    The output value ("zero") may appear EITHER BEFORE the condition ("report
    zero if the input has no bits high") OR AFTER it ("if none of the bits are
    high, output zero"), so we scan a window on BOTH sides of the matched
    all-zero condition rather than only the trailing sentence.
    """
    t = text.lower()
    # Find the all-zero / no-bits-set input condition (the trigger).
    zero_cond = re.search(
        r"(?:input\s+(?:vector\s+)?(?:is\s+)?(?:all\s+)?(?:zero|0)\b"
        r"|none\s+of\s+the\s+input\s+bits?\s+are\s+(?:high|1|set)"
        r"|no\s+bits?\s+(?:that\s+are\s+)?(?:high|set|1)"
        r"|(?:vector|input)\s+has\s+no\s+bits?\s+(?:that\s+are\s+)?(?:high|set|1))",
        t,
    )
    if not zero_cond:
        return None
    # Window spanning ~90 chars on each side of the condition — wide enough to
    # catch a "report zero ..." that precedes it or an "output zero" that
    # follows it, but narrow enough not to scoop in unrelated prose.
    lo = max(0, zero_cond.start() - 90)
    hi = min(len(t), zero_cond.end() + 90)
    window = t[lo:hi]
    # A competing NON-zero default explicitly stated for the all-zero input:
    #   - a separate validity flag is the real signal, or all-ones output.
    if re.search(r"\ball\s+(?:1s|ones)\b", window) and not re.search(
        r"\b(?:report|output|outputs?)\s+(?:0|zero)\b", window
    ):
        return False
    # Did the prose name "zero" / "0" as the OUTPUT for the all-zero input?
    says_zero = bool(
        re.search(r"\b(?:report|output|outputs?|return|set\s+.{0,20}?to)\s+"
                  r"(?:a\s+)?(?:0|zero)\b", window)
        or re.search(r"\b(?:0|zero)\b.{0,40}?\bif\b", window)  # "report zero if..."
    )
    if says_zero:
        return True
    return None


# --------------------------------------------------------------------------- #
# the solver                                                                  #
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule"):
    if not _is_priority_encoder_prose(prompt_text):
        return None
    if _has_disqualifying_function(prompt_text):
        return None

    ins, outs = _pp.parse_ports(prompt_text)
    if len(ins) != 1 or len(outs) != 1:
        return None

    in_name, n = ins[0]
    out_name, w = outs[0]

    # A pure combinational priority encoder has no sequential / handshake ports.
    seq = {"clk", "clock", "rst", "reset", "rstn", "rst_n", "en", "enable",
           "load", "valid", "ready", "ack"}
    if in_name.lower() in seq or out_name.lower() in seq:
        return None

    # Structural widths must be definite and consistent with the behavior.
    if n < 2:
        return None                       # not a vector -> not an encoder
    if w < 1:
        return None
    expected_w = max(1, math.ceil(math.log2(n)))
    if w != expected_w:
        return None                       # interface contradicts stated behavior

    # DIRECTION: must be stated AND LSB-first.
    direction = _direction_is_lsb_first(prompt_text)
    if direction is not True:
        return None                       # MSB-first or unstated -> SKIP

    # ZERO-INPUT DEFAULT: must be stated AND zero.
    if _zero_default_is_zero(prompt_text) is not True:
        return None                       # unstated / non-zero default -> SKIP

    return _emit_casez_priority_encoder(top, in_name, n, out_name, w)


# --------------------------------------------------------------------------- #
# emitter                                                                      #
# --------------------------------------------------------------------------- #
def _decl(name: str, width: int, direction: str, reg: bool = False) -> str:
    kw = f"{direction} reg" if reg else direction
    if width == 1:
        return f"    {kw} {name}"
    return f"    {kw} [{width-1}:0] {name}"


def _emit_casez_priority_encoder(top, in_name, n, out_name, w):
    """Emit a width-robust LSB-first casez priority encoder with zero default."""
    lines = [
        "// program-SOLVED priority encoder (LSB-first, zero default); deterministic.",
        f"module {top} (",
        _decl(in_name, n, "input") + ",",
        _decl(out_name, w, "output", reg=True),
        ");",
        "    always @(*) begin",
        f"        casez ({in_name})",
        f"            default    : {out_name} = {w}'h0;",
    ]
    # One arm per position 0..N-1: bit k is the explicit '1', EVERY other bit is
    # a casez don't-care ('z'). Priority comes purely from SOURCE ORDER — arms
    # are listed lowest-position-first, so for an input with several set bits the
    # FIRST matching arm is the lowest set bit (LSB-first priority). This is the
    # exact form the dataset reference uses (e.g. 8'bzzzzzzz1 -> 0, 8'bzzzzzz1z
    # -> 1, ...), generalized to any width N.
    for k in range(n):
        bits = ["z"] * n
        bits[n - 1 - k] = "1"           # index 0 == MSB in the string layout
        pattern = "".join(bits)
        lines.append(f"            {n}'b{pattern}: {out_name} = {w}'d{k};")
    lines += [
        "        endcase",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not an unambiguously-specified priority encoder",
              file=sys.stderr)
        sys.exit(1)
    print(rtl)
