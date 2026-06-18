#!/usr/bin/env python3
"""latency_conformance_check.py — v1.0 plugin gate (ORGANIC #705).

DETERMINISTIC latency-conformance gate: MEASURE the RTL's REAL event→output
latency the way a hidden scorer counts it, and BLOCK on any mismatch versus the
spec literal.

THE FAILURE THIS CLOSES
-----------------------
When a spec states an EXACT latency ("output asserts WIDTH+2 cycles after the
start event", "N+1-cycle delay"), the agent's SELF-testbench is untrustworthy:
across four blind authoring strategies agents scored 0/8 on off-by-one latency
failures because each improvised a counting convention that happened to match
its OWN (wrong) RTL — the self-TB confirmed the wrong behaviour. There is no
independent yard-stick.

This program IS that yard-stick. It does NOT ask the RTL's self-TB anything; it
generates ITS OWN canonical measurement testbench, drives the DUT with a fixed
deterministic convention (the way a scorer counts), reads back the measured
latency, RESOLVES the spec literal against the module's real parameter values,
and compares. A mismatch is a hard BLOCK.

CANONICAL MEASUREMENT CONVENTION (what a scorer counts)
-------------------------------------------------------
The generated testbench:
  * instantiates the DUT and drives a free-running ``clk`` (10 ns period);
  * applies reset — active-LOW auto-detected from a ``rst_n``/``resetn``/
    ``arst_n``-style port name (or forced via ``--reset-active-low|high`` /
    ``--reset``), else active-HIGH — holds it a few cycles, then deasserts;
  * drives every OTHER data input to a deterministic constant (all-ones by
    default; ``--input-const`` overrides) so the design actually progresses;
  * measures latency relative to the EVENT-LATCH POSEDGE E (the posedge where
    the DUT samples ``--event`` HIGH), POSEDGE-CONSISTENTLY (no negedge
    sampling — the negedge mis-reads a registered output as latency-0):
      - PRECONDITION: ``--output`` MUST be LOW before the event; if it is
        already HIGH the measurement is meaningless (an out-of-reset always-HIGH
        ``valid``) → ``LATENCY_PRECONDITION_HIGH`` → rc 2;
      - COMBINATIONAL latency 0: assert ``event`` in the clk LOW phase and let
        purely-combinational logic settle WITHOUT crossing a posedge; if
        ``--output`` goes HIGH with no clock edge → measured 0;
      - REGISTERED latency >= 1: advance to E (deassert ``event`` with an NBA so
        it is a clean one-edge pulse), then COUNT full posedges reading
        ``--output`` AT each posedge (so it reflects the PREVIOUS edge's
        registered value): posedge E+1 reflects E ⇒ ``out <= start`` reads HIGH
        at E+1 ⇒ measured 1; a 2-stage ``r<=start; out<=r`` reads HIGH at E+2 ⇒
        measured 2;
  * prints ``MEASURED_LATENCY=<n>`` (or ``LATENCY_TIMEOUT`` if the output never
    asserts within the bounded window). An N-stage shift register measures
    EXACTLY N for N=0,1,2,3,…

COUNTING ORIGIN (``--latency-origin``, ORGANIC #744 round-17)
------------------------------------------------------------
The gate MEASURES with a fixed EXCLUSIVE origin: it counts the posedges STRICTLY
AFTER the event-latch edge E (E itself is cycle 0). A spec may enumerate the SAME
timing INCLUSIVELY — counting the event-latch cycle itself as cycle 1 (the
canonical "1 cycle registering inputs + N cycles compute + 1 cycle asserting the
output = N+2" decomposition). An author who transcribes that inclusive literal
verbatim into ``--expect`` would see a false off-by-one MISMATCH on CORRECT RTL
(``measured`` reads one lower than the inclusive literal).

``--latency-origin inclusive`` lets the author DECLARE that ``--expect`` is stated
in the inclusive convention; the gate then compares ``measured + 1`` (the
exclusive measurement plus the event-latch cycle) against ``--expect``. The
default ``exclusive`` is the original behaviour, byte-for-byte.

This is a DECLARED CONVENTION, NOT a ``+-1`` TOLERANCE: under a FIXED origin the
comparison stays EXACT, so a real one-cycle latency bug still MISMATCHes — a
design one cycle EARLY measures exclusive E-1 (inclusive E ≠ the declared E+1) and
one cycle LATE measures exclusive E+1 (inclusive E+2 ≠ E+1). A blanket "accept
measured+1==expected" WOULD leak (it would silently pass an exclusive-spec design
whose RTL asserts one cycle early), which is precisely why the resolution is an
author-declared origin rather than a tolerance band.

--expect RESOLUTION
-------------------
``--expect`` is a literal arithmetic expression over the module's parameters
(``WIDTH+2``, ``N+1``, ``8``). It is resolved by substituting the DUT's
parameter values: ``--param NAME=VAL`` overrides first, else the module's own
default ``#(...)`` values. The arithmetic is evaluated by a TINY SAFE evaluator
(digits, parameter names, ``+ - * // ( )`` only — NEVER ``eval`` of arbitrary
code). A resolved value above a sane ceiling (or negative) is REJECTED (rc 2)
so a pathological ``--expect`` cannot stall the sim; the measurement window is
hard-clamped regardless of ``--max-cycles`` (MED DoS guard).

HONESTY
-------
  * iverilog/vvp ABSENT → ``SKIP — iverilog unavailable`` and rc 0 (a distinct
    SKIP; NEVER a fabricated measurement or PASS).
  * output never asserts within the bounded window → ``LATENCY-TIMEOUT`` rc 1.
  * a missing event/output port → clear error + rc 2.
  * ``--output`` already HIGH before the event → ``LATENCY-ERROR`` rc 2 (a
    meaningless measurement is refused, NEVER reported as a bogus latency 0).

NO-HANDSHAKE STREAMING DESIGNS (ORGANIC #729)
---------------------------------------------
A pure STREAMING design (continuous data/valid, no discrete pulse->done
handshake) has no ``--event``-triggers->``--output`` relationship to measure: the
output never makes a one-shot assertion after a one-cycle event pulse, so the
TB simply TIMES OUT. A bare TIMEOUT is the wrong signal there — it is neither a
real timing BLOCK (the design has no such timing contract) nor a PASS (nothing
was measured). With ``--allow-no-handshake`` such a TIMEOUT is reclassified to a
DISTINCT ``NOT_APPLICABLE`` verdict on a DISTINCT exit code (3), so it can never
be misread as a real PASS (rc 0) or as a real latency BLOCK (rc 1). WITHOUT the
flag the default behaviour is UNCHANGED: a TIMEOUT stays ``LATENCY-TIMEOUT`` rc
1 (a design that DOES have a handshake but mis-latches must still hard-block).

PER-OUTPUT (SECOND-OUTPUT) LATENCY INFERENCE (ORGANIC #740 G3)
-------------------------------------------------------------
A design may carry a SECOND output that has no event->output handshake to
MEASURE (the canonical TB measures ONE event->output relationship), yet whose
intended latency is IMPLIED by the partial-code intermediate pipeline registers
feeding it. ``--second-output PORT`` INFERS that output's per-output latency
from the declared intermediate registers (the registered-chain depth from the
output back to its first combinational/input source) — a PURE structural parse,
no simulation. It is ADVISORY ONLY (never changes the exit code): it reports the
inferred latency, and when ``--expect-second`` is also given it notes whether the
inference matches the spec literal. When the chain is AMBIGUOUS (branch depths
disagree, combinational/register feedback, or the output is not registered) it
emits an ADVISORY "not inferred" note rather than guessing.

chip-AGNOSTIC: pure measurement + comparison; no design/chip/vendor/SKU literal.

Usage:
    python3 latency_conformance_check.py --rtl <design>.sv --top <module>
        --event <start_port> --output <valid_port> --expect "WIDTH+2"
        [--param NAME=VAL ...] [--reset PORT] [--reset-active-low|high]
        [--input-const N] [--max-cycles N] [--mode latency]
        [--allow-no-handshake] [--json OUT]

Exit codes:
    0  latency-conformance ok (measured == resolved spec)  OR  SKIP (no iverilog)
    1  LATENCY-MISMATCH  or  LATENCY-TIMEOUT
    2  setup / parse error (missing port, bad --expect, bad --param, …)
    3  NOT-APPLICABLE — no pulse->done handshake to measure on a streaming
       design (only with --allow-no-handshake; never a silent PASS)
"""
from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# SHARED port/param parser — never hand-roll a port regex (#705 requirement).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reset_clock_variant_alias import (  # noqa: E402
    parse_module_ports,
    parse_module_params,
    _module_body,
)

# The timing-conformance family. Only `latency` is fully implemented; the
# others are reserved extensibility hooks (pulse-one-cycle-after,
# registered-vs-comb, handshake-phase) toward the same canonical-measurement
# discipline. `--mode latency` is the default and the only one wired today.
_MODES = ("latency",)

# Canonical free-running clock spellings (input clk auto-bind for the TB). Kept
# as the FAST-PATH exact set; `_is_clock` below ALSO accepts the universal clock
# family by a NARROW, token-anchored `clk`/`clock` match (ORGANIC #805/#807).
_CLK_NAMES = frozenset({"clk", "clock", "clk_i", "clock_i", "clk_in", "clk_in1"})
# ORGANIC #805/#807 — well-known SINGLE-TOKEN glued clock spellings (no '_' to
# split on): AMBA bus clocks + common glued forms. A CLOSED allow-list (not a
# fuzzy match) so it cannot swallow data ports like `block`/`lock`/`tick`.
_CLK_GLUED_NAMES = frozenset({
    "aclk", "bclk", "pclk", "hclk", "mclk", "gclk", "refclk", "sclk", "fclk",
    "wclk", "rclk", "txclk", "rxclk", "sysclk", "coreclk", "busclk"})  # ORGANIC #844: bclk is aclk B-side CDC pair
_CLK_STEMS = frozenset({"clk", "clock"})
# Qualifier tokens that, when paired with a `clk`/`clock` stem, mark a
# clock-DERIVED CONTROL/DATA port (clock-enable / gate / divider / select / …)
# — held at the data constant, NOT bound as the free-running clock.
_CLK_QUALIFIER_DENY = frozenset({
    "en", "ena", "enable", "enabled", "gate", "gated", "gating", "div",
    "divider", "divided", "ratio", "sel", "select", "mux", "cnt", "count",
    "counter", "data", "valid", "ready", "req", "ack", "rst", "reset", "n",
    "b", "pol", "edge", "mask", "freq", "period", "phase", "src", "source",
    "out",
    # ORGANIC #805/#807 Step-2.7 §4.05 — the clock-STATUS / HEALTH / MONITOR /
    # TEST family: a `clk_<word>` INPUT carrying clock STATUS (PLL lock, stable,
    # ok, error) or a test/debug/monitor tap is NOT the free-running clock and
    # must NOT inflate the multi-clock CDC count (which would false-screen a
    # genuine single-clock measurable design to rc=3 NOT_APPLICABLE, hiding a
    # real timing bug).
    # (unambiguous status/health/error words only — ambiguous clock qualifiers
    # like `sync`/`active` are deliberately NOT denied; the edge-aware CDC count
    # below is the decisive backstop, so a real `clk_sync` clock is never
    # over-rejected.)
    "lock", "locked", "lol", "status", "stat", "stable", "vld", "ok", "good",
    "mon", "monitor", "test", "tst", "dbg", "debug", "err", "error", "loss",
    "lost", "present", "skew", "jitter", "fault", "fail", "detect", "detected",
    "rdy", "alarm", "warn", "miss"})

# Active-low reset spelling fragments (name-based auto-detect of polarity).
_ACTIVE_LOW_RST = ("rst_n", "rstn", "reset_n", "resetn", "arst_n", "arstn",
                   "nrst", "nreset", "n_rst", "n_reset", "rst_b", "resetb",
                   "reset_b", "rst_ni", "resetb_n")
_RST_NAME_HINT = ("rst", "reset")

# CLEAR-class controls (C5). A synchronous CLEAR/FLUSH input (`clr`, `clear`,
# `flush`) is reset-EQUIVALENT for measurement: held ACTIVE it permanently
# flushes the pipeline so the output can NEVER assert. The canonical TB must
# therefore hold it in its INACTIVE state during measurement (like a reset),
# NOT pin it to the all-ones data constant. They are active-HIGH by the usual
# convention (asserted HIGH clears), with the same `_n`/`_b` low-suffix override
# as resets. This is a NARROW, name-anchored set — it does NOT capture ordinary
# data inputs.
_CLEAR_NAME_EXACT = frozenset({"clr", "clear", "clrn", "clr_n", "clear_n",
                               "flush", "aclr", "sclr", "clra", "clrb"})

# ORGANIC #810 r2 (Step-2.7 §4.05) — CLEAR/FLUSH/COMPLETION semantic vocabulary
# for the structural clear-equivalent detector. A purely STRUCTURAL `if(ctrl)
# reg<=const-zero` branch is NOT sufficient to hold `ctrl` inactive during the
# canonical measurement: a load-bearing functional control (capture / mode /
# hold / enable) buggy at its canonical (active) value produces the SAME shape
# and the SAME timeout, so structurally relaxing it MASKS a real latency bug
# (the exact failure class PR #3 removed for set/reset bits). The relaxation
# therefore fires ONLY when `ctrl`'s NAME also carries clear/flush/completion
# semantics — the motivating `Present_Processing_Completed` (a done/flush
# control) matches via `complete`, while `capture`/`mode`/`hold` do not. Long,
# unambiguous words match as a substring; short fragments only as a whole
# underscore/camelCase segment (so `done` does not fire inside `abandoned`).
_CLEAR_EQUIV_LONG = ("clear", "flush", "complete", "finish", "abort", "cancel",
                     "purge", "drain", "discard", "invalidate", "reset")
_CLEAR_EQUIV_SEG = frozenset({"clr", "rst", "done", "init", "eot", "eof"})
# ORGANIC #811 r2 (Step-2.7 §4.05) — LOAD-BEARING-CONTROL deny override. A name
# can carry a clear-vocab substring yet denote a load-bearing FUNCTIONAL control
# (`finish_mode` = a MODE select; `drain_sel` = a path SELECT) — held inactive,
# such a control changes WHICH functional path is measured and masks a real
# latency bug (Step-2.7 reproduced this on the localparam-resolved path). When a
# name carries BOTH a clear token AND a functional-control SEGMENT below, the
# functional reading wins and the name is NOT a clear-equivalent: §4.05 biases to
# NOT relaxing (a false-timeout on a genuine clear is a missed FP-fix, far safer
# than masking a bug). chip-AGNOSTIC: generic control-role English segments.
_LOADBEARING_CTRL_SEG = frozenset({
    "mode", "sel", "select", "mux", "load", "capture", "hold", "en", "enable",
    "phase", "cfg", "config", "ctrl", "op", "opcode", "cmd", "func", "fn",
    "stage", "step", "addr", "index", "idx", "way", "bank", "channel", "chan"})


def _clear_equiv_segments(name: str) -> List[str]:
    segs: List[str] = []
    for chunk in re.split(r"[_\W]+", name):
        if not chunk:
            continue
        sub = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", chunk)
        segs.extend(sub if sub else [chunk])
    return [s.lower() for s in segs]


def _looks_like_clear_equiv_name(name: str) -> bool:
    """True iff `name` carries clear / flush / completion semantics — the NAME
    gate the structural clear-equivalent relaxation requires so a load-bearing
    functional control (capture/mode/hold/enable) is never held inactive (§4.05
    no-leak). Long unambiguous words match anywhere; short fragments only as a
    whole segment.

    ORGANIC #811 r2: a name with a load-bearing-control SEGMENT
    (`_LOADBEARING_CTRL_SEG` — mode/sel/select/load/...) is NOT a clear even when
    it ALSO carries a clear token (`finish_mode`, `drain_sel`), because such a
    control held inactive masks a real latency bug. The functional reading wins."""
    segs = _clear_equiv_segments(name)
    if any(seg in _LOADBEARING_CTRL_SEG for seg in segs):
        return False
    low = name.lower()
    if any(w in low for w in _CLEAR_EQUIV_LONG):
        return True
    return any(seg in _CLEAR_EQUIV_SEG for seg in segs)

# SET/RESET SCALAR MUTEX CONTROL class (ORGANIC #809 round-12, C1). A sequential
# primitive (SR / JK flip-flop, gated latch) carries a pair of MUTUALLY-EXCLUSIVE
# 1-bit SET and RESET controls (`i_S`/`i_R`, `S`/`R`, `set`/`reset`, `sd`/`rd`,
# `preset`/`clr`). The canonical TB pins EVERY non-event input to the all-ones
# data constant — which pins the SET/RESET MUTEX PARTNER of the measured event
# ACTIVE. With the pulsed measured control AND its partner both held active the
# DUT enters its spec INVALID state (`{i_S,i_R}=2'b11 -> o_Q<=0` per the SR truth
# table), so the measured output can NEVER assert -> a FALSE LATENCY-TIMEOUT on
# CORRECT RTL (`cvdp_copilot_flop_0001`). These scalar mutex controls are NOT
# resets/clears (held ACTIVE they do not flush the pipeline — they DRIVE a
# specific value), but for MEASUREMENT they must likewise be held INACTIVE so the
# measured event reaches the output. This is a NARROW, name-anchored EXACT set of
# the conventional SET/RESET bit spellings — `reset`/`rst`/`clr`/`clear`/`preset`
# are already caught by `_looks_like_reset`/`_looks_like_clear`, so this set
# captures only the BARE S/R/SET/SD/RD-style scalar spellings they miss. It does
# NOT capture multi-bit data buses (it is applied only to 1-bit scalar inputs in
# `classify_ports`). chip-AGNOSTIC: a generic sequential-primitive control shape.
_SETRESET_BIT_NAME_EXACT = frozenset({
    "s", "r", "set", "reset_bit",
    "sd", "rd",            # set-direct / reset-direct (FPGA primitive style)
    "i_s", "i_r", "o_s", "o_r",
    "s_i", "r_i",
    "set_i", "reset_i", "sd_i", "rd_i"})

# ARBITRATION / MUTUAL-EXCLUSION stimulus class (ORGANIC #770 round-2, Part C).
# A bus arbiter is a MUTEX design: a set of competing REQUEST inputs map to a set
# of GRANT outputs, and at most one master is granted per arbitration. The
# canonical TB drives EVERY non-event data input to the same all-active constant
# — which, for an arbiter, pins the COMPETING requests ACTIVE *and* (depending on
# the priority/select wiring) pins the SELECT so a spec-correct arbiter grants a
# DIFFERENT master than the one being measured. The measured grant is then
# structurally UNREACHABLE → a false LATENCY-TIMEOUT on correct RTL
# (`bus_arbiter_0004`). The fix: detect the multi-request / multi-grant
# structural signature and, when the all-active stimulus makes the measured grant
# unreachable (a TIMEOUT), RETRY with a ONE-HOT request stimulus — drive ONLY the
# measured request active (the event), hold the COMPETING request inputs INACTIVE
# — so the measured grant is reachable and the genuine per-master latency is read.
#
# These are name-anchored *request*/*grant* fragments — a NARROW signature, not a
# data-input net. chip-AGNOSTIC: a structural multi-request/multi-grant shape, no
# chip / vendor / SKU literal.
_REQUEST_NAME_FRAGS = ("req", "request")
_GRANT_NAME_FRAGS = ("grant", "gnt", "gr_")


def _looks_like_request(name: str) -> bool:
    """A bus-arbitration REQUEST input (`req`, `req0`, `m0_request`, `request_i`).
    NARROW, fragment-anchored on the `req`/`request` token boundary so an
    ordinary data input (`frequency`, `prequel`) is NOT captured: the fragment
    must start at a word boundary or be the whole token's prefix segment."""
    lo = name.lower()
    for frag in _REQUEST_NAME_FRAGS:
        # word-anchored: `req`/`request` at the start, or after a `_`/digit
        # boundary (m0_req, bus_request_2) — never embedded mid-word (frequency).
        if re.search(r"(?:^|_)" + frag + r"(?:$|_|\d)", lo):
            return True
    return False


def _looks_like_grant(name: str) -> bool:
    """A bus-arbitration GRANT output (`grant`, `grant0`, `m1_gnt`, `gnt_o`).
    Same NARROW word-anchored fragment match as `_looks_like_request`."""
    lo = name.lower()
    for frag in _GRANT_NAME_FRAGS:
        if re.search(r"(?:^|_)" + frag.rstrip("_") + r"(?:$|_|\d)", lo):
            return True
    return False


# DoS guards (MED). A real event->output latency is small; a huge resolved
# `--expect` (e.g. `8*1000000`) emitted into the TB loop bound + `#delay`
# cutoff would stall each record ~120 s. Reject an out-of-range resolved expect
# outright, and HARD-CLAMP the measurement window regardless of how it is
# derived so a pathological `--max-cycles` cannot wedge the sim either.
_MAX_EXPECT = 100000
_MAX_CYCLES_CEILING = 200000


# ─── safe arithmetic evaluation of the --expect literal ──────────────────────
# ONLY integer +, -, *, // (and unary +/-) over digit literals and the
# substituted parameter names. ast with a node whitelist — NEVER eval().
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


class ExpectError(ValueError):
    """Raised when --expect cannot be safely evaluated to an integer."""


# ─── Verilog literal / $clog2 normalisation (C5 — param-default parse) ────────
# A module's #(...) defaults are HDL, not Python: a sized/based literal
# (`'d128`, `8'hFF`, `4'b1010`, `'sd1`) and the elaboration-time function
# `$clog2(N)` are perfectly legal default RHS values, yet Python's ast.parse
# chokes on the leading apostrophe and on `$`. Before walking the AST we
# CANONICALISE the HDL literal forms to plain decimal so a faithful, very common
# parameterised design can have its #(...) defaults resolved (else the params
# are silently dropped and the generated TB's port widths stay unresolved →
# `Unable to bind parameter` compile crash). PURE deterministic text rewrite —
# still no eval(); the result is re-validated by the strict AST whitelist below.
import re as _re_lit  # noqa: E402 (literal-normaliser only; main `re` below)

# Verilog based literal:  [size] ' [s] base digits[_digits]
#   'd128  8'hFF  4'b1010  16'sd1  'b10_10  'hDEAD_BEEF
_VLOG_BASED_LIT_RE = _re_lit.compile(
    r"(?<![\w'])(\d+)?\s*'\s*[sS]?\s*([dDbBoOhH])\s*([0-9a-fA-FxXzZ_]+)")
_VBASE = {"b": 2, "o": 8, "d": 10, "h": 16}


def _vlog_literal_to_int(size: Optional[str], base_ch: str, digits: str
                         ) -> Optional[int]:
    """Convert one Verilog based literal's (base, digits) to a Python int, or
    None if it is not a clean integer (e.g. contains x/z don't-cares)."""
    base = _VBASE[base_ch.lower()]
    clean = digits.replace("_", "")
    if not clean or any(c in "xXzZ?" for c in clean):
        return None  # don't-care literal — not a resolvable constant
    try:
        return int(clean, base)
    except ValueError:
        return None


def _normalise_hdl_literals(expr: str) -> str:
    """Rewrite Verilog based literals in `expr` to plain decimal so the strict
    arithmetic AST can parse them. `$clog2(` is mapped to a sentinel call name
    `clog2(` that the whitelisted evaluator recognises. Unresolvable literals
    (x/z) are left verbatim so the AST step rejects them honestly."""
    # $clog2(...) → clog2(...) (a recognised, side-effect-free integer fn)
    out = expr.replace("$clog2", "clog2")

    def _sub(m: "object") -> str:
        v = _vlog_literal_to_int(m.group(1), m.group(2), m.group(3))
        return str(v) if v is not None else m.group(0)

    return _VLOG_BASED_LIT_RE.sub(_sub, out)


def _clog2(n: int) -> int:
    """Verilog $clog2: ceil(log2(n)) — bits needed to index n values.
    $clog2(0)=$clog2(1)=0; $clog2(2)=1; $clog2(32)=5; $clog2(33)=6."""
    if n <= 1:
        return 0
    return (n - 1).bit_length()


# Whitelisted side-effect-free integer functions usable in a param default /
# --expect (mirroring the HDL elaboration-time functions). NEVER arbitrary code.
_ALLOWED_CALLS = {"clog2": _clog2}


def safe_eval_arith(expr: str, params: Dict[str, int]) -> int:
    """Evaluate a parameter arithmetic expression SAFELY.

    Permitted: integer literals (incl. Verilog based literals `'d128`/`8'hFF`,
    canonicalised to decimal first), the parameter NAMEs in `params`, the binary
    operators ``+ - * //`` and unary ``+ -``, parentheses, and the whitelisted
    side-effect-free integer functions ``$clog2(...)``. ANYTHING else (other
    function calls, attribute access, names not in `params`, ``/`` true-div,
    ``**`` power, bit ops, …) RAISES ExpectError. Never executes arbitrary
    code — the AST is walked node-by-node against a strict whitelist.
    """
    if not expr or not expr.strip():
        raise ExpectError("empty --expect expression")
    expr = _normalise_hdl_literals(expr)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExpectError(f"--expect is not a valid expression: {e}") from e

    def _ev(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINOPS):
                raise ExpectError(
                    f"operator {type(node.op).__name__} not allowed in --expect "
                    f"(only + - * //)")
            left = _ev(node.left)
            right = _ev(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            # FloorDiv
            if right == 0:
                raise ExpectError("division by zero in --expect")
            return left // right
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARYOPS):
                raise ExpectError(
                    f"unary {type(node.op).__name__} not allowed in --expect")
            v = _ev(node.operand)
            return +v if isinstance(node.op, ast.UAdd) else -v
        # integer constant
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, int):
                raise ExpectError(
                    f"--expect may only use integer literals, got "
                    f"{node.value!r}")
            return node.value
        # a whitelisted side-effect-free integer function call, e.g. $clog2(N)
        if isinstance(node, ast.Call):
            fn = node.func
            if (not isinstance(fn, ast.Name) or fn.id not in _ALLOWED_CALLS
                    or node.keywords):
                raise ExpectError(
                    f"only the whitelisted integer functions "
                    f"{sorted(_ALLOWED_CALLS)} (e.g. $clog2) are allowed in "
                    f"--expect / param defaults")
            argv = [_ev(a) for a in node.args]
            if len(argv) != 1:
                raise ExpectError(
                    f"{fn.id} expects exactly one integer argument")
            return int(_ALLOWED_CALLS[fn.id](argv[0]))
        # a parameter name
        if isinstance(node, ast.Name):
            if node.id not in params:
                raise ExpectError(
                    f"--expect references unknown parameter {node.id!r}; "
                    f"known params: {sorted(params) or 'none'} (use --param "
                    f"{node.id}=VAL or declare it in the module #(...) block)")
            return int(params[node.id])
        raise ExpectError(
            f"disallowed expression element {type(node).__name__} in --expect")

    return int(_ev(tree))


# ─── parameter resolution (module defaults + --param overrides) ──────────────
def resolve_params(rtl_text: str, module: str,
                   overrides: Dict[str, int]) -> Dict[str, int]:
    """Build the parameter->int map for `module`.

    Starts from the module's own ``#(...)`` default values (parsed with the
    SHARED parser), then applies ``--param NAME=VAL`` overrides on top. A
    default whose RHS is itself a simple integer (or a tiny arithmetic of
    EARLIER params) is evaluated; a default that cannot be reduced to an int
    is dropped from the map (it can still be supplied via --param).
    """
    raw_block, names = parse_module_params(rtl_text, module)
    params: Dict[str, int] = {}
    if raw_block:
        # Parse each `NAME = RHS` in source order so a later default may use an
        # earlier one. The shared parser already gave us the NAME order; pull
        # each RHS up to the next top-level comma.
        for nm, rhs in _iter_param_defaults(raw_block):
            try:
                params[nm] = safe_eval_arith(rhs, params)
            except ExpectError:
                # non-integer / non-arithmetic default (e.g. a string param) —
                # leave unresolved; --param can still set it.
                continue
    # overrides win
    for nm, val in overrides.items():
        params[nm] = val
    return params


def _iter_param_defaults(param_block: str):
    """Yield (name, rhs_text) for each `NAME = RHS` in a #(...) param block,
    splitting on TOP-LEVEL commas only (a comma inside [..]/(..) is not a
    separator). Leading `parameter`/`localparam`/type/width keywords on the
    NAME side are stripped."""
    for seg in _split_top_level_commas(param_block):
        if "=" not in seg:
            continue
        lhs, rhs = seg.split("=", 1)
        # the parameter name is the LAST identifier on the lhs (after any
        # `parameter`/`localparam`/`int`/`[..]` width tokens)
        toks = [t for t in _IDENT_RE.findall(lhs)]
        if not toks:
            continue
        name = toks[-1]
        yield name, rhs.strip()


def _split_top_level_commas(block: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    buf: List[str] = []
    for ch in block:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


import re  # noqa: E402  (kept local-late to keep the header import block clean)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


# ─── ORGANIC #793 — localparam-in-#() exclusion from the DUT override list ────
def _localparam_names(param_block: "Optional[str]") -> "set":
    """Return the set of names whose `#(...)` segment leads with the `localparam`
    keyword (a DERIVED constant the instance inherits, NOT an overridable
    parameter). A `parameter`-led or keyword-less segment is a real overridable
    parameter and is NOT included (§4.05 no-leak: a header with no localparams
    returns an empty set, so the override list is unchanged)."""
    out: set = set()
    if not param_block:
        return out
    for seg in _split_top_level_commas(param_block):
        if "=" not in seg:
            continue
        lhs, _rhs = seg.split("=", 1)
        toks = _IDENT_RE.findall(lhs)
        if not toks:
            continue
        # the name is the LAST identifier on the lhs (after parameter/localparam/
        # type/width tokens); a localparam segment leads with `localparam`.
        if "localparam" in toks[:-1]:
            out.add(toks[-1])
    return out


def module_localparam_names(rtl_text: str, module: str) -> "set":
    """ORGANIC #793 — set of names declared `localparam` INSIDE `module`'s
    `#(...)` block. Their resolved integer values stay in the `resolve_params`
    map (the instance inherits them; they are needed for net widths + --expect
    arithmetic) but they MUST NOT appear in the DUT `#(.NAME(VAL))` override list
    — overriding a localparam is an iverilog elaboration error ("Cannot override
    localparam"). Kept as a SEPARATE query so `resolve_params`'s `Dict` return
    type is unchanged (§4.05 no-leak for every existing caller)."""
    raw_block, _names = parse_module_params(rtl_text, module)
    return _localparam_names(raw_block)


def _rtl_event_value_candidates(rtl_text: str, ev_width: "Optional[int]") -> List[int]:
    """ORGANIC #795 — extract candidate EVENT values from the RTL's OWN sized
    literals whose width matches the event port (e.g. the `case (decoder_in)`
    labels / comparison constants of a decoder/LUT/ROM).

    A decoder/LUT/ROM responds only to a TINY subset of its input space (its
    valid codewords); a blind all-ones constant almost never hits one, so the
    change-detect TIMEs out falsely. The design ITSELF enumerates the meaningful
    inputs as sized literals exactly `ev_width` bits wide — those are precisely
    the values guaranteed to move the bus. Reads ONLY the RTL the gate already
    has (no oracle / hidden TB) and is fully chip-agnostic: any width-matched
    literal is a candidate; a design with none yields an empty list and falls
    back to the generic probes (no leak)."""
    if ev_width is None or ev_width <= 1:
        return []
    out: List[int] = []
    all_ones = (1 << ev_width) - 1
    for m in re.finditer(r"(\d+)'([bBhHdDoO])([0-9a-fA-F_xXzZ]+)", rtl_text):
        try:
            w = int(m.group(1))
        except ValueError:
            continue
        if w != ev_width:
            continue
        base = m.group(2).lower()
        digits = m.group(3).replace("_", "")
        if any(c in "xXzZ" for c in digits):
            continue  # an x/z literal cannot be a concrete stimulus
        try:
            if base == "b":
                val = int(digits, 2)
            elif base == "h":
                val = int(digits, 16)
            elif base == "o":
                val = int(digits, 8)
            else:
                val = int(digits, 10)
        except ValueError:
            continue
        val &= all_ones
        # all-ones is the stimulus that already TIMED OUT; all-zeros is the most
        # common reset baseline — skip both (they cannot relax the timeout).
        if val in (0, all_ones) or val in out:
            continue
        out.append(val)
    return out


# ─── port classification ─────────────────────────────────────────────────────
def _is_clock(name: str) -> bool:
    """ORGANIC #805/#807 — recognise the clock family beyond the fixed
    `_CLK_NAMES` set. The exact whitelist mis-classified every conventional but
    non-listed clock spelling (`i_clk`, async-FIFO `w_clk`/`r_clk`, `sys_clk`,
    AMBA `aclk`/`pclk`/`hclk`, `clk0`, `core_clk`) as an ordinary data input held
    to the all-ones constant — so the generated TB drove a free-running `clk` net
    wired to NOTHING in the DUT, the design never saw a clock edge, and CORRECT
    RTL hard-blocked with a false LATENCY-TIMEOUT. Recognise the clock by a
    NARROW token-anchored `clk`/`clock` match: strip a directional `i_`/`o_`/`io_`
    prefix and trailing index digits, require a `clk`/`clock` WHOLE TOKEN, and a
    clock-control deny-list rejects derived control/data ports (`clk_en`,
    `clk_div`, `clk_sel`, `clk_gate`, `en_clk_dsp`, …). chip-AGNOSTIC."""
    n = name.lower()
    if n in _CLK_NAMES or n in _CLK_GLUED_NAMES:
        return True
    core = re.sub(r"^(?:i|o|io)_", "", n)   # directional prefix
    core = re.sub(r"\d+$", "", core)         # trailing index digits (clk0, clk1)
    toks = [t for t in core.split("_") if t]
    if not toks or not any(t in _CLK_STEMS for t in toks):
        return False
    # a clk/clock stem paired with a control/data qualifier is NOT the clock.
    if any(t in _CLK_QUALIFIER_DENY for t in toks):
        return False
    return True


# ORGANIC #811 round-16 — generic DIRECTIONAL prefix strip (`i_`/`o_`/`io_`/
# `in_`/`out_`). The exact-token name recognisers (`_looks_like_clear`,
# `_looks_like_setreset_bit`) matched only the BARE token, UNLIKE `_is_clock`
# which strips a directional prefix — so a port `i_clear`/`o_clr`/`i_flush` was
# NOT recognised as a clear (it fell into the all-ones-pinned `others` and was
# pinned ACTIVE → permanent flush → false LATENCY-TIMEOUT on correct RTL,
# `cvdp_copilot_signed_adder_0001`). This helper MIRRORS `_is_clock`'s prefix
# handling but covers the full generic directional family. chip-AGNOSTIC: only
# universal port-direction prefixes, no chip / vendor / signal-name literal.
_DIR_PREFIX_RE = re.compile(r"^(?:i|o|io|in|out)_")


def _strip_dir_prefix(name: str) -> str:
    """Strip ONE leading generic directional prefix (`i_`/`o_`/`io_`/`in_`/
    `out_`) from `name`. Returns the lowered core token. A name with no such
    prefix is returned unchanged (lowered), so an exact match on the bare token
    still works."""
    return _DIR_PREFIX_RE.sub("", name.lower())


def _looks_like_clear(name: str) -> bool:
    """A synchronous CLEAR/FLUSH control — reset-equivalent for MEASUREMENT
    (held active it permanently flushes the pipeline). NARROW, name-anchored
    (an exact name in `_CLEAR_NAME_EXACT`); does NOT capture data inputs.

    ORGANIC #811 — the match is tried on BOTH the bare lowered name AND the name
    with a leading directional prefix stripped (`i_clear`/`o_clr`/`i_flush` →
    `clear`/`clr`/`flush`), MIRRORING `_is_clock`'s prefix handling. The set
    itself is unchanged, so an ordinary data input (`i_enable`→`enable`,
    `i_data`→`data`) is still NOT in the clear allowlist (§4.05 no-leak)."""
    lo = name.lower()
    return lo in _CLEAR_NAME_EXACT or _strip_dir_prefix(lo) in _CLEAR_NAME_EXACT


def _looks_like_setreset_bit(name: str) -> bool:
    """A SCALAR SET/RESET mutex control of a sequential primitive (ORGANIC #809).
    NARROW, name-anchored EXACT match of the BARE S/R/SET/SD/RD-style scalar
    spellings the reset/clear recognisers miss (`i_S`/`i_R`, `S`/`R`, `sd`/`rd`,
    `set_i`/`reset_i`). Held inactive during MEASUREMENT so the pulsed measured
    event is not fought by its all-ones-pinned mutex partner. Caller applies this
    ONLY to 1-bit scalar inputs, so it can never capture a multi-bit data bus.

    ORGANIC #811 — like `_looks_like_clear`, the EXACT match is tried on BOTH the
    bare name and the directional-prefix-stripped core, so `i_set`/`o_set`/`i_sd`
    are recognised. The EXACT set already enumerates the `i_`/`o_` forms it cares
    about; the strip only adds the generic `in_`/`out_` family and is harmless
    for the rest (the bare core must still be one of the bare spellings)."""
    lo = name.lower()
    return (lo in _SETRESET_BIT_NAME_EXACT
            or _strip_dir_prefix(lo) in _SETRESET_BIT_NAME_EXACT)


def _reset_is_active_low(name: str) -> bool:
    lo = name.lower()
    if lo in _ACTIVE_LOW_RST:
        return True
    # generic low-asserted marker on a reset- OR clear-named port.
    if any(h in lo for h in _RST_NAME_HINT) or _looks_like_clear(lo):
        # An UNDERSCORE-separated polarity suffix (`_n`/`_b`) or an `n`-prefix
        # (`nrst`) is unambiguous.
        if lo.endswith("_n") or lo.endswith("_b") or lo.startswith("n"):
            return True
        # ORGANIC #795 — a BARE trailing `n`/`b` (no separator) is a polarity
        # marker ONLY when attached DIRECTLY to a reset/clear stem (`rstn`,
        # `resetn`, `rstb`, `clrn`). It must NOT fire on a trailing DIRECTION
        # word like `reset_in`/`rst_in` where the final `n` belongs to `_in`,
        # not the reset stem — those ports are active-HIGH. Strip the candidate
        # marker and require the remainder to END with a reset/clear stem.
        if lo.endswith("n") or lo.endswith("b"):
            stem = lo[:-1]
            if (any(stem.endswith(h) for h in _RST_NAME_HINT)
                    or _looks_like_clear(stem)
                    or stem.endswith("clr") or stem.endswith("clear")):
                return True
        return False
    return False


def _looks_like_reset(name: str) -> bool:
    """A reset-CLASS control to HOLD INACTIVE during measurement — a reset
    proper OR a synchronous clear/flush (C5). Holding either ACTIVE would keep
    the design permanently quiescent so the output could never assert."""
    lo = name.lower()
    return any(h in lo for h in _RST_NAME_HINT) or _looks_like_clear(lo)


# ─── STRUCTURAL synchronous-CLEAR-equivalent detection (ORGANIC #810) ─────────
# The name allowlist `_CLEAR_NAME_EXACT` ({clr,clear,flush,aclr,sclr,...}) is
# the ONLY way the gate recognises a clear/flush control today. A design may
# carry a 1-bit input that is a synchronous-CLEAR / FLUSH-equivalent under a
# DIFFERENT spelling the allowlist misses (e.g. `Present_Processing_Completed`,
# `abort`, `kill`, `halt_clr`): when ASSERTED it DOMINATINGLY forces the
# state/output register(s) to their reset/zero constant EVERY clock, exactly
# like `if (clear) State <= '0;`. Pinned to the all-ones data constant by the
# canonical TB, such a control is held ACTIVE — permanently flushing the FSM so
# the measured output (`State != 0`) can NEVER assert → a FALSE LATENCY-TIMEOUT
# on CORRECT RTL (`cvdp_copilot_rs_232_0001`). This is the SAME false-TIMEOUT
# family the gate documents (C1 SR-mutex, C5 clear/flush) — only the spelling
# escapes the name anchor.
#
# `detect_structural_clear_equiv` is a PURE structural parse (no simulation):
# for each 1-bit input it scans the module's sequential always-blocks for a
# DOMINATING guarded branch `(else) if (<sig at one polarity>) <reg> <= <const>`
# whose body assigns ONLY constants (no datapath signal RHS) and drives at
# least one register to a ZERO constant — the unmistakable synchronous-clear
# signature. It returns {name: active_low} so the caller can HOLD the control
# in its NON-clearing (INACTIVE) value during measurement, the same way an
# explicit clear is held inactive. The ACTIVE polarity is INFERRED from the
# branch condition (`if(S)`/`S==HIGH`/`S==1'b1` → active-HIGH; `if(!S)`/`if(~S)`
# /`S==LOW`/`S==1'b0` → active-LOW) so "hold inactive" pins the control to the
# value that does NOT clear, NOT blindly to all-ones.
#
# §4.05 NO-LEAK — this detector is NARROW by construction AND its USE is
# TIMEOUT-GATED + ONE-AT-A-TIME (the caller holds each candidate inactive only
# after a plain TIMEOUT and adopts the FIRST clean measurement), so it can
# only RELAX a structural permanent-flush timeout, never mask a real bug:
#   * the branch body must assign ONLY constant literals — an ordinary
#     data/enable input whose branch loads a SIGNAL (`if (load) r <= data_in`)
#     or increments (`if (en) cnt <= cnt + 1`) is NOT a constant assignment and
#     is NEVER flagged, so a genuine data/enable dependency is preserved;
#   * at least one register must be driven to ZERO — a SET-to-all-ones control
#     (not a clear) does not match;
#   * applied ONLY to 1-bit scalar inputs, so it can never capture a data bus;
#   * because adoption is TIMEOUT-gated, a measured-but-WRONG latency (MISMATCH)
#     is NEVER retried — a genuine off-by-N still hard-blocks;
#   * if holding the candidate inactive does NOT make the output assert, the
#     original TIMEOUT stands.
# chip-AGNOSTIC: pure Verilog grammar (guarded const-zero register branch); no
# chip / vendor / SKU / signal-name literal.
def _bool_param_map(rtl_text: str) -> Dict[str, int]:
    """Map each `parameter`/`localparam` whose default is a 1-bit boolean
    constant (`1'b1`, `1`, `1'b0`, `0`) to that 0/1 value — so a clear branch
    written `if (S == HIGH)` (HIGH a parameter = 1'b1) resolves its polarity."""
    bm: Dict[str, int] = {}
    for nm, val in re.findall(
            r"\b(?:parameter|localparam)\s+(?:\[[^\]]*\]\s*)?"
            r"([A-Za-z_]\w*)\s*=\s*([^,;\n)]+)", rtl_text):
        mm = re.match(r"^\s*(?:\d+)?'[bB]([01])\s*$|^\s*([01])\s*$", val)
        if mm:
            bm[nm] = int(mm.group(1) if mm.group(1) is not None else mm.group(2))
    return bm


def _is_const_expr(rhs: str, bool_params: Dict[str, int]) -> bool:
    """True iff `rhs` is a pure CONSTANT (sized/unsized literal, replication of a
    1-bit literal, or a boolean parameter) — i.e. carries NO datapath signal. A
    branch body that assigns a constant to every register it touches is a CLEAR
    /SET, never a data load or an arithmetic update."""
    s = rhs.strip()
    if s in bool_params:
        return True
    return bool(re.fullmatch(
        r"(?:\d+)?'[hbdoHBDO][0-9a-fA-FxXzZ_]+"     # sized literal  4'b0000 8'hFF
        r"|\d+"                                       # plain decimal  0  255
        r"|'[01]"                                     # '0  '1
        r"|\{\s*\d*\s*\{\s*1'b[01]\s*\}\s*\}", s))    # {N{1'b0}}  {1'b0}


def _is_zero_const(rhs: str) -> bool:
    """True iff `rhs` is a constant ZERO literal (the reset/clear value).

    ORGANIC #811 — the zero-replication count may be a PARAMETER expression, not
    a digit (`{DATA_WIDTH{1'b0}}` — the canonical parameterised reset value), so
    the replication-count slot accepts any non-`{` token, and the replicated bit
    may be `1'b0` or `0`. Still ZERO-only (a `1'b1` replication never matches)."""
    s = rhs.strip()
    return bool(re.fullmatch(
        r"(?:\d+)?'[hbdoHBDO]0+"                      # 4'b0000  8'h00  'd0
        r"|'0"                                        # '0
        r"|0+"                                        # 0  00
        # {N{1'b0}} / {DATA_WIDTH{1'b0}} — replication of a single ZERO bit.
        r"|\{\s*[^{}]*\s*\{\s*1'b0\s*\}\s*\}", s))


# ─── ORGANIC #811 round-16 — localparam-RESOLVED constant value map ───────────
# An FSM clear branch writes its state/status register to a SYMBOLIC reset/idle
# state — `state <= IDLE;` where `localparam [1:0] IDLE = 2'b00;` — NOT to a bare
# literal. `_is_const_expr` (literal-only) rejects `IDLE`, so the round-15
# structural clear detector returns {} for the entire FSM family and the clear
# escapes recognition (`cvdp_copilot_signed_adder_0001`). This map resolves a
# localparam/parameter whose default is a CONSTANT integer (literal or a chain of
# already-resolved constants) to its integer VALUE, so `state <= IDLE` can be
# compared against the register's ASYNC-RESET value: the genuine "this control
# forces the FSM to its reset/idle state" signature. PURE deterministic text
# parse; chip-AGNOSTIC (Verilog localparam grammar, no signal-name literal).
def _const_value_map(rtl_text: str) -> Dict[str, int]:
    """Map each `parameter`/`localparam` whose default resolves to a CONSTANT
    integer to that value. Handles sized/unsized literals (`2'b00`, `8'hFF`,
    `'d4`, plain decimal) directly, and resolves a name-RHS (`localparam X = Y;`)
    against earlier entries via a bounded fixpoint so a chain of symbolic
    constants resolves. A non-constant / datapath RHS is simply omitted (so a
    register write to a non-constant name is later treated as NOT a clear).
    A comma-separated multi-name declaration (`localparam [1:0] IDLE = 2'b00,
    LOAD = 2'b01, ...;` — the canonical FSM state encoding) yields ALL its
    name=value pairs, not just the first."""
    raw: List[Tuple[str, str]] = []
    # Strip comments FIRST so a `parameter`/`localparam` word inside a comment
    # cannot make the `[^;]*` declaration capture span into real RTL (which would
    # pollute the map with a register-assignment LHS=RHS pair).
    clean = re.sub(r"//[^\n]*", " ", rtl_text)
    clean = re.sub(r"/\*.*?\*/", " ", clean, flags=re.S)
    # Each `parameter`/`localparam` declaration up to its terminating `;`; the
    # leading `[w:l]` width applies to the whole comma list.
    for decl in re.finditer(
            r"\b(?:parameter|localparam)\b\s*(?:\[[^\]]*\]\s*)?([^;]*);",
            clean):
        for seg in _split_top_level_commas(decl.group(1)):
            if "=" not in seg:
                continue
            lhs, rhs = seg.split("=", 1)
            nm = _IDENT_RE.findall(lhs)
            if nm:
                raw.append((nm[-1], rhs.strip()))
    vm: Dict[str, int] = {}

    def _lit(val: str) -> Optional[int]:
        s = val.strip()
        m = re.fullmatch(
            r"(?:(\d+)\s*)?'[sS]?([hbdoHBDO])([0-9a-fA-F_]+)", s)
        if m:
            return _vlog_literal_to_int(m.group(1), m.group(2), m.group(3))
        if re.fullmatch(r"\d+", s):
            return int(s)
        return None

    # up to a few passes so `localparam B = A;` resolves after `A`.
    for _ in range(8):
        progressed = False
        for nm, val in raw:
            if nm in vm:
                continue
            v = _lit(val)
            if v is None:
                s = val.strip()
                if s in vm:                  # name-RHS resolved earlier
                    v = vm[s]
            if v is not None:
                vm[nm] = v
                progressed = True
        if not progressed:
            break
    return vm


def _resolve_const_token(rhs: str, const_vals: Dict[str, int]) -> Optional[int]:
    """Resolve `rhs` (a register-assignment RHS) to its integer constant value
    via a literal parse OR a localparam/parameter lookup; None if it carries any
    datapath signal (so it is NOT a constant clear/reset write)."""
    s = rhs.strip()
    if s in const_vals:
        return const_vals[s]
    m = re.fullmatch(r"(?:(\d+)\s*)?'[sS]?([hbdoHBDO])([0-9a-fA-F_]+)", s)
    if m:
        return _vlog_literal_to_int(m.group(1), m.group(2), m.group(3))
    if re.fullmatch(r"\d+", s):
        return int(s)
    # `{N{1'b0}}` / `'0` replication of zero — a concrete zero constant.
    if _is_zero_const(s):
        return 0
    return None


def _async_reset_values(blk: str, const_vals: Dict[str, int]) -> Dict[str, int]:
    """ORGANIC #811 — for ONE sequential always-block `blk`, find the
    ASYNCHRONOUS-reset branch (`if (!rst_n)` / `if (rst)` etc., the guarded
    branch a `posedge clk or negedge rst` block opens with) and return
    {reg_name: resolved_const_value} for every register it drives to a CONSTANT.
    The reset branch is identified as the FIRST top-level `if (<bare/neg sig>)`
    whose body assigns ONLY constants and drives ≥1 register to ZERO — the
    unmistakable reset signature. Returns {} when no such branch is found (so a
    register whose reset value is UNKNOWN is never used to relax — bias to NOT
    classifying, per the no-leak requirement)."""
    for m in re.finditer(
            r"\b(?:else\s+)?if\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*", blk):
        cond = m.group(1).strip()
        if not (re.fullmatch(r"\s*[!~]?\s*[A-Za-z_]\w*\s*", cond)
                or re.fullmatch(
                    r"\s*[A-Za-z_]\w*\s*==\s*[A-Za-z_0-9']+\s*", cond)):
            continue
        body = _branch_body_text(blk[m.end():])
        assigns = re.findall(
            r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*<=\s*([^;]+);", body)
        vals: Dict[str, int] = {}
        all_const = bool(assigns)
        saw_zero = False
        for lhs, rhs in assigns:
            v = _resolve_const_token(rhs, const_vals)
            if v is None:
                all_const = False
                break
            vals[lhs] = v
            if v == 0:
                saw_zero = True
        if all_const and saw_zero:
            return vals
    return {}


def _branch_body_text(tail: str) -> str:
    """The body of a guarded branch starting at `tail`: a balanced `begin..end`
    block or a single statement up to the next `;`. Shared by the reset-value
    extractor and the clear-branch scan."""
    if tail.lstrip().startswith("begin"):
        i = tail.find("begin")
        depth = 0
        j = i
        while j < len(tail):
            if tail[j:j + 5] == "begin":
                depth += 1
                j += 5
                continue
            if (tail[j:j + 3] == "end"
                    and (j + 3 >= len(tail)
                         or not (tail[j + 3].isalnum() or tail[j + 3] == "_"))):
                depth -= 1
                if depth == 0:
                    break
                j += 3
                continue
            j += 1
        return tail[i + 5:j]
    semi = tail.find(";")
    return tail[:semi + 1] if semi >= 0 else ""


def detect_structural_clear_equiv(
        rtl_text: str, top: str,
        scalar_input_names: "set") -> Dict[str, bool]:
    """Return {input_name: active_low} for each 1-bit input that is a
    clear-equivalent control: it has the STRUCTURAL `if(ctrl) reg<=const-zero`
    signature AND a NAME carrying clear/flush/completion semantics
    (`_looks_like_clear_equiv_name`). The name gate is REQUIRED (§4.05 no-leak):
    a structural-only match also captures a load-bearing functional control
    buggy at its canonical value, masking a real latency bug. PURE structural +
    name; no simulation. `scalar_input_names` restricts the scan to 1-bit inputs
    so a multi-bit data bus is never captured.

    ORGANIC #811 round-16 — a clear branch that assigns the state/status register
    to a LOCALPARAM/parameter idle state (`if (i_clear) state <= IDLE;` where
    `localparam IDLE = 2'b00;`) is ALSO recognised, iff the localparam's RESOLVED
    constant value equals the value that register takes in the design's
    ASYNCHRONOUS-RESET branch — the genuine "this control forces the FSM to its
    reset/idle state" signature. A branch that assigns the register to a
    NON-reset state localparam (`if (S) state <= RUN`) does NOT match (no-leak):
    `RUN`'s value differs from the async-reset value. If the register's reset
    value is UNKNOWN (no async-reset branch parsed), the localparam path does NOT
    fire — bias to keeping the input pinned."""
    body = _module_body(rtl_text, top)
    # strip comments so a commented-out assignment inside a branch body is never
    # parsed as a real assign (false clear-signature) — and vice versa.
    body = re.sub(r"//[^\n]*", " ", body)
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    bool_params = _bool_param_map(rtl_text)
    # ORGANIC #811 r2 (Step-2.7 §4.05) — resolve localparam values from the DUT
    # MODULE BODY, not the whole file: a SIBLING module's `localparam RUN = 0`
    # would otherwise first-decl-win and poison the DUT's `RUN = 2'b01`, making a
    # jam-to-RUN (non-reset) branch falsely resolve to the reset value and mis-
    # classify a load-bearing control as a clear. `body` is already
    # `_module_body(rtl_text, top)`, so this scopes the const map to the DUT.
    const_vals = _const_value_map(body)            # ORGANIC #811 localparam values
    found: Dict[str, bool] = {}
    # Walk sequential always-blocks only (an edge-sensitive sensitivity list).
    for am in re.finditer(r"always\s*@\s*\(([^)]*)\)", body):
        if "edge" not in am.group(1):
            continue
        blk = body[am.end():]
        nxt = re.search(r"\balways\b", blk)
        if nxt:
            blk = blk[:nxt.start()]
        # ORGANIC #811 — the per-block ASYNC-RESET register values (the FSM's
        # reset/idle state) so a `state <= IDLE` clear can be compared against
        # the register's genuine reset value. {} when no reset branch is parsed.
        reset_vals = _async_reset_values(blk, const_vals)
        # every guarded branch `(else )?if ( COND )` inside the block
        for im in re.finditer(
                r"\b(?:else\s+)?if\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*", blk):
            cond = im.group(1).strip()
            sig: Optional[str] = None
            active_low: Optional[bool] = None
            m_bare = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*", cond)
            m_neg = re.fullmatch(r"\s*[!~]\s*([A-Za-z_]\w*)\s*", cond)
            m_cmp = re.fullmatch(
                r"\s*([A-Za-z_]\w*)\s*==\s*([A-Za-z_0-9']+)\s*", cond)
            if m_bare:
                sig, active_low = m_bare.group(1), False
            elif m_neg:
                sig, active_low = m_neg.group(1), True
            elif m_cmp:
                sig = m_cmp.group(1)
                rhs = m_cmp.group(2)
                rv = bool_params.get(rhs)
                if rv is None:
                    mm = re.fullmatch(r"(?:\d+)?'[bB]([01])|([01])", rhs)
                    if mm:
                        rv = int(mm.group(1) if mm.group(1) is not None
                                 else mm.group(2))
                if rv is None:
                    continue
                active_low = (rv == 0)
            else:
                continue
            if sig not in scalar_input_names:
                continue
            # the branch body: a `begin ... end` block (balanced) or a single
            # statement up to the next `;`.
            bodytxt = _branch_body_text(blk[im.end():])
            assigns = re.findall(
                r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*<=\s*([^;]+);", bodytxt)
            if not assigns:
                continue
            if not _looks_like_clear_equiv_name(sig):
                # the NAME gate is REQUIRED for BOTH structural paths (§4.05
                # no-leak): a structural-only match would also hold a
                # load-bearing functional control inactive and mask a real bug.
                continue
            # PATH 1 (round-15) — every assigned RHS is a pure literal constant
            # AND at least one is a ZERO literal (the unmistakable `<=const-zero`
            # clear signature).
            literal_clear = (
                all(_is_const_expr(rhs, bool_params) for _, rhs in assigns)
                and any(_is_zero_const(rhs) for _, rhs in assigns))
            # PATH 2 (ORGANIC #811) — the LOCALPARAM-RESOLVED clear: this control
            # forces the FSM to its RESET/IDLE state. The branch qualifies iff
            #   * every assigned RHS resolves to a CONSTANT (literal OR
            #     localparam/parameter — no datapath signal); AND
            #   * every assigned register that HAS a known async-reset value goes
            #     to EXACTLY that reset value (so `state <= RUN` — RUN != the
            #     IDLE reset value — DISQUALIFIES the whole branch, even if the
            #     branch incidentally zeroes another output); AND
            #   * every assigned register WITHOUT a known reset value is a ZERO
            #     constant (conservative: an unknown-reset register may only be
            #     cleared to zero, never set to an arbitrary non-zero constant);
            #   * AND at least one register actually matches a known reset value
            #     (the branch genuinely drives a reset-tracked register home).
            # §4.05 no-leak: a control that jams the FSM into a NON-reset state
            # (the exact (d) negative) is REJECTED — its value differs from the
            # reset value — so a real "stuck in a wrong state" timeout still
            # hard-blocks. An unknown reset value (empty reset_vals) never fires.
            localparam_clear = False
            if reset_vals:
                resolved = [(lhs, _resolve_const_token(rhs, const_vals))
                            for lhs, rhs in assigns]
                if all(v is not None for _, v in resolved):
                    matched_reset = False
                    ok = True
                    for lhs, v in resolved:
                        if lhs in reset_vals:
                            if v != reset_vals[lhs]:
                                ok = False
                                break
                            matched_reset = True
                        elif v != 0:
                            ok = False
                            break
                    localparam_clear = ok and matched_reset
            # ORGANIC #811 r2 (Step-2.7 §4.05) — RESET-CONSISTENCY guard binding
            # BOTH paths: when the async-reset values are known, a branch that
            # drives ANY reset-tracked register to a NON-reset constant
            # (`state <= RUN` while the reset state is IDLE) is NOT a clear —
            # it jams the FSM into a wrong state, the exact (d) negative. PATH 1
            # (`literal_clear`) alone only required "all const + ≥1 zero", so a
            # `state<=RUN(nonzero); cnt<=0; o_ready<=0;` branch slipped through on
            # the zeroed siblings and masked a real permanent-jam timeout. Reject
            # the whole branch when any reset-tracked reg goes to a non-reset
            # value (a load-bearing control that forces a wrong state must still
            # hard-block).
            violates_reset = False
            if reset_vals:
                for lhs, rhs in assigns:
                    v = _resolve_const_token(rhs, const_vals)
                    if (v is not None and lhs in reset_vals
                            and v != reset_vals[lhs]):
                        violates_reset = True
                        break
            if (literal_clear or localparam_clear) and not violates_reset:
                found.setdefault(sig, active_low)
    return found


# ─── per-output latency inference from intermediate registers (#740 G3) ───────
# A SECOND output port often has NO event->output handshake to MEASURE (the
# canonical TB measures ONE event->output relationship), yet its intended
# latency is IMPLIED by the partial-code intermediate pipeline registers that
# feed it: `out2 <= stage1; stage1 <= stageN; ... <= <comb of inputs>`. The
# inferred latency is the DEPTH of that registered chain from the output back to
# the first purely-combinational / input source. This is a PURE structural
# function (no iverilog) so it is unit-testable on the parse alone; it is
# ADVISORY (returns a reason string) whenever the chain is AMBIGUOUS (branching
# depths, combinational feedback, or the output is not registered at all).
def _module_body(rtl_text: str, top: str) -> str:
    """The text between `module <top> ... ;` head and its matching endmodule
    (best-effort; the same head-of-module bounding the rest of the file uses)."""
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\b", rtl_text)
    if not m:
        return rtl_text
    nxt = re.search(r"\bendmodule\b", rtl_text[m.end():])
    return rtl_text[m.end(): m.end() + (nxt.start() if nxt else len(rtl_text))]


def _nba_sources(body: str) -> Dict[str, List[str]]:
    """Map each non-blocking-assigned signal to the list of RHS identifier
    SOURCES of its assignment(s). `out <= a;` → {'out': ['a']}. Multiple
    assignments to the same LHS union their source lists (so a reset-clear
    `out <= 0;` contributes no source and a datapath `out <= s1;` contributes
    `s1`). Constants / numeric literals contribute nothing."""
    srcs: Dict[str, List[str]] = {}
    for m in re.finditer(
            r"(?<![<>!=])\b([A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*<=\s*([^;]+);",
            body):
        lhs = m.group(1)
        rhs = m.group(2)
        ids = [t for t in _IDENT_RE.findall(rhs)
               if not re.match(r"^\d", t)]
        srcs.setdefault(lhs, [])
        srcs[lhs].extend(ids)
    return srcs


def infer_output_latency_from_registers(
        rtl_text: str, top: str, output: str,
        max_depth: int = 64) -> Tuple[Optional[int], str]:
    """Infer the intended event->output latency of `output` from the declared
    intermediate pipeline registers feeding it. Returns (latency, reason).

    latency is an int when a single unambiguous registered chain depth is found
    (the number of register hops from `output` back to the first non-registered
    /input/combinational source); None when ambiguous (with a reason that says
    why — branch-depth disagreement, combinational/feedback, or not registered).
    PURE structural — no simulation. ADVISORY by construction.
    """
    body = _module_body(rtl_text, top)
    nba = _nba_sources(body)
    registered = set(nba.keys())
    if output not in registered:
        return None, (f"output '{output}' is not a registered (non-blocking) "
                      f"signal in module '{top}' — per-output latency cannot be "
                      f"inferred from a register chain (advisory)")

    # BFS the longest/shortest registered chain depth from `output` back to the
    # first non-registered source. Track every distinct terminal depth; if more
    # than one distinct depth is reachable the pipeline is ambiguous.
    terminal_depths: Set[int] = set()

    def _walk(sig: str, depth: int, seen: Set[str]) -> None:
        if depth > max_depth:
            terminal_depths.add(-1)        # runaway / feedback → ambiguous
            return
        sources = nba.get(sig)
        if not sources:
            # `sig` is not registered → it is a combinational / input source.
            # The number of register hops taken to get here IS the latency.
            terminal_depths.add(depth)
            return
        if sig in seen:
            terminal_depths.add(-1)        # combinational/register feedback loop
            return
        seen = seen | {sig}
        # Only registered sources extend the chain by one hop; a
        # non-registered source terminates at this hop's depth+1 (the source is
        # combinational/input one register before this stage).
        reg_sources = [s for s in sources if s in registered and s != sig]
        comb_sources = [s for s in sources if s not in registered]
        if comb_sources:
            terminal_depths.add(depth + 1)
        for s in reg_sources:
            _walk(s, depth + 1, seen)

    _walk(output, 0, set())
    clean = {d for d in terminal_depths if d >= 0}
    if -1 in terminal_depths:
        return None, (f"output '{output}' has a combinational/register feedback "
                      f"or runaway chain — per-output latency is ambiguous "
                      f"(advisory; not inferred)")
    if not clean:
        return None, (f"output '{output}' register chain reached no "
                      f"combinational/input source — ambiguous (advisory)")
    if len(clean) > 1:
        return None, (f"output '{output}' is fed by register chains of "
                      f"DIFFERENT depths {sorted(clean)} — per-output latency "
                      f"is ambiguous (advisory; not inferred)")
    depth = next(iter(clean))
    return depth, (f"output '{output}' is registered through a {depth}-stage "
                   f"pipeline (inferred per-output latency {depth} from declared "
                   f"intermediate registers; advisory)")


def _width_of(width_str: str) -> int:
    """Best-effort bit-width from a `[MSB:LSB]` width token; 1 if scalar or
    parameterised (we only need a width for the TB reg declaration — a
    parameterised width is rendered symbolically, see _build_tb)."""
    m = re.match(r"\s*\[\s*([^:\]]+)\s*:\s*([^:\]]+)\s*\]", width_str or "")
    if not m:
        return 1
    try:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    except ValueError:
        return 1  # symbolic width — handled in _build_tb


# ─── ORGANIC #787 — multi-bit DATAPATH output width + handshake detection ─────
# The measurement TB models the --output as a 1-BIT done/valid PULSE: it counts
# posedges from the event to the first `out === 1'b1`. That convention is only
# meaningful for a 1-bit handshake flag. A MULTI-BIT DATAPATH result bus (e.g.
# `result_real[31:0]`) is NOT a 1-bit pulse: `out === 1'b1` matches ONLY when the
# WHOLE bus equals exactly 1, so a correct registered datapath never "asserts"
# (→ false TIMEOUT rc=1) — or worse, its quiescent value happens to equal 1 and
# the PRECONDITION fires (→ false rc=2). For such a bus the latency is the first
# cycle the bus CHANGES away from its settled post-reset value (`out !== baseline`)
# — a faithful SIMULATION, not a pulse that will never come. These two helpers
# decide when to switch the measurement TB to that change-detect assertion.
def _resolved_output_width(width_str: str, params: Dict[str, int]) -> Optional[int]:
    """The CONCRETE numeric bit-width of a `[MSB:LSB]` packed width, evaluating
    arithmetic / parameterised bounds via the SAME safe arithmetic evaluator used
    for --expect (so `[OUT_WIDTH-1:0]` with OUT_WIDTH=32 → 32, `[31:0]` → 32,
    a scalar → 1). Returns None when a bound is non-constant / unresolved — the
    caller then conservatively keeps the unchanged simulation path (no leak)."""
    ws = _concretise_width(width_str or "", params)
    if not ws:
        return 1  # scalar port (no packed width) is 1 bit
    m = re.match(r"\s*\[\s*([^:\]]+?)\s*:\s*([^:\]]+?)\s*\]\s*$", ws)
    if not m:
        return None
    try:
        msb = safe_eval_arith(m.group(1), {})
        lsb = safe_eval_arith(m.group(2), {})
    except ExpectError:
        return None
    return abs(msb - lsb) + 1


# A 1-bit OUTPUT named like a handshake/status flag (done/valid/ready/ack/grant/
# busy/error/...) genuinely uses the pulse->assert model, so even when (rare) it
# is declared as a >1-bit vector we keep the pulse TB. This is NARROW + word-
# anchored so a DATAPATH bus (`result_real`, `sum`, `q`, `data_out`) is NOT
# matched — those are measured by change-detection. §4.05: a real 1-bit done/valid
# still flows through the unchanged pulse model.
_PULSE_NAME_FRAGS = ("done", "valid", "vld", "ready", "rdy", "ack", "grant",
                     "gnt", "busy", "error", "err", "irq", "intr", "complete",
                     "finish", "eop", "sop", "empty", "full", "overflow",
                     "underflow", "match", "hit", "flag")


def _looks_like_pulse_output(name: str) -> bool:
    """True when `name` reads like a 1-bit handshake/status PULSE output (done /
    valid / ready / ack / ...), so the event->`out===1` pulse model applies even
    on a wide declaration. Word-anchored fragment match (start, or after a `_` /
    digit boundary) so a datapath name (`result_real`, `data_out`, `sum`) — whose
    latency is measured by change-detection — is never captured."""
    lo = name.lower()
    for frag in _PULSE_NAME_FRAGS:
        if re.search(r"(?:^|_)" + re.escape(frag) + r"(?:$|_|\d)", lo):
            return True
    return False


class PortInfo:
    __slots__ = ("name", "direction", "width_str", "unpacked_dims")

    def __init__(self, name: str, direction: str, width_str: str,
                 unpacked_dims: str = ""):
        self.name = name
        self.direction = direction
        self.width_str = (width_str or "").strip()
        # ORGANIC #767 — the trailing UNPACKED array dimension(s) declared
        # AFTER the port name (`input wire [7:0] lane [7:0]` /
        # `... mem [0:3][7:0]`). The shared parser's 3-tuple keeps only the
        # PACKED width + name; this carries the post-name dimension string
        # (e.g. "[7:0]" or "[0:3][7:0]") so the measurement TB can model the
        # port as an array (per-element decl + drive) instead of wiring a
        # scalar reg to a DUT array port (an iverilog elaboration ERROR).
        # Empty string for an ordinary scalar/packed-only port (no leak).
        self.unpacked_dims = (unpacked_dims or "").strip()

    @property
    def is_array(self) -> bool:
        return bool(self.unpacked_dims)


# ─── unpacked-array dimension recovery (ORGANIC #767) ────────────────────────
# The shared `parse_module_ports` returns 3-tuples (dir, packed-width, name) and
# DROPS any trailing UNPACKED array dimension declared AFTER the port name
# (`input wire [7:0] lane [7:0]`). Widening that shared contract to a 4-tuple
# would break every 3-tuple caller (l9/shape_b/phase2/leaf_typo all unpack
# `for d, _w, n in ports`), so we recover the post-name dimension LOCALLY from
# the same RTL text instead — a pure, additive, name-anchored scan that touches
# nothing the shared parser already produces.
#
# Grammar of an ANSI port-list entry with an unpacked array:
#   <dir> [net-type]* [packed-width] <NAME> <UNPACKED-DIMS>
# where UNPACKED-DIMS is one or more `[..]` groups that follow the NAME (and only
# the name) before the comma / closing paren. A SCALAR or packed-only port has
# nothing between its name and the separator, so this returns "" for it (no leak:
# a non-array port's TB modelling is byte-for-byte unchanged).
_UNPACKED_PORT_RE = re.compile(
    r"\b(?:input|output|inout)\b"          # direction-led ANSI entry
    r"(?:\s*(?:wire|reg|logic|signed|unsigned)\b)*"
    r"(?:\s*[A-Za-z_]\w*::\s*[A-Za-z_]\w*)?"   # optional pkg::type_t
    r"\s*(?:\[[^\]]+\])?"                   # optional packed width
    # (1) the port NAME — never a net-type/sign keyword. Without this guard the
    # engine backtracks on a scalar packed port (`input wire [7:0] data_in`):
    # it consumes nothing as the net-type, captures `wire` as the NAME, and the
    # packed `[7:0]` as a phantom trailing UNPACKED dim. The negative lookahead
    # forbids that — a net-type/sign token can only be the leading qualifier,
    # never the port name. (chip-AGNOSTIC: pure SV port grammar.)
    r"\s*(?!(?:wire|reg|logic|signed|unsigned)\b)(\w+)"
    r"\s*((?:\[[^\]]+\]\s*)+)")             # (2) one+ trailing UNPACKED dims


def parse_unpacked_dims(rtl_text: str, module: str) -> Dict[str, str]:
    """name -> concatenated trailing unpacked-dimension string for every ANSI
    port of `module` that declares one (e.g. {"lane": "[7:0]"}). Ports with no
    post-name dimension are simply absent from the map. Best-effort, pure text —
    never raises; an unparsed module yields {}."""
    out: Dict[str, str] = {}
    # (1) ANSI header port-list block.
    block = _module_portlist_block(rtl_text, module)
    # (2) (#766r2) NON-ANSI body direction declarations carry their unpacked dims
    # in the body (`input [7:0] mem [3:0];`), not the header. Scan the body too so
    # a non-ANSI unpacked-array port recovers its dim and the TB builds a proper
    # array net — reaching the SAME #767 element-wise / NOT_APPLICABLE path the
    # ANSI class does (rc=3 parity), instead of building a scalar net that fails to
    # compile (a hard rc=2) — and never the dropped/floating scalar that silently
    # PASSed before the #766 port-recovery fix.
    body = _module_body(rtl_text, module) or ""
    for src in (block, body):
        if not src:
            continue
        for m in _UNPACKED_PORT_RE.finditer(src):
            name, dims = m.group(1), m.group(2)
            dims = re.sub(r"\s+", "", dims)  # collapse "[0:3] [7:0]" -> "[0:3][7:0]"
            if dims and name not in out:
                out[name] = dims
    return out


def _module_portlist_block(rtl_text: str, module: str) -> str:
    """The raw text inside `module <module> ( ... )` (ANSI header). Empty if not
    found. Local, minimal counterpart of the shared parser's block extractor —
    only used to recover post-name unpacked dims, so it does not need the shared
    parser's full define/ifdef machinery."""
    mm = re.search(r"\bmodule\s+" + re.escape(module) + r"\b", rtl_text)
    if not mm:
        return ""
    i = rtl_text.find("(", mm.end())
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(rtl_text)):
        c = rtl_text[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return rtl_text[i + 1:j]
    return ""


def classify_ports(ports: List[Tuple[str, str, str]],
                   event_name: str, output_name: str,
                   reset_override: Optional[str],
                   unpacked_map: Optional[Dict[str, str]] = None
                   ) -> Tuple[Optional[PortInfo], List[PortInfo],
                              Optional[PortInfo], Optional[PortInfo],
                              List[PortInfo]]:
    """Return (clk, resets, event_port, output_port, other_inputs).

    `ports` is the shared parser's [(dir, width, name), ...].
    `unpacked_map` (ORGANIC #767) maps a port name to its trailing UNPACKED
    array-dimension string (from `parse_unpacked_dims`); a name not in the map is
    a scalar/packed-only port (unpacked_dims="").
    """
    unpacked_map = unpacked_map or {}
    clk: Optional[PortInfo] = None
    resets: List[PortInfo] = []
    event_port: Optional[PortInfo] = None
    output_port: Optional[PortInfo] = None
    others: List[PortInfo] = []
    for direction, width, name in ports:
        pi = PortInfo(name, direction, width, unpacked_map.get(name, ""))
        if name == output_name and direction == "output":
            output_port = pi
            continue
        if name == event_name:
            event_port = pi
            # the event is ALSO a driven input; it is pulsed, not held — so it
            # is excluded from `others` (constant-driven) below.
            continue
        if direction == "input":
            if clk is None and _is_clock(name):
                clk = pi
                continue
            # A reset-CLASS control (reset proper OR a synchronous clear/flush,
            # C5) is held INACTIVE during measurement. A clear/flush is held
            # inactive EVEN when an explicit --reset names a different port:
            # leaving it pinned to the all-ones data constant would permanently
            # flush the pipeline so the output could never assert.
            is_rst = (reset_override is not None
                      and (name == reset_override or _looks_like_clear(name))) \
                or (reset_override is None and _looks_like_reset(name))
            # ORGANIC #809 (C1) — a SCALAR (1-bit) SET/RESET MUTEX control of a
            # sequential primitive (`i_S`/`i_R`, `S`/`R`, `sd`/`rd`, `set_i`/
            # `reset_i`) CAN, when pinned to the all-ones data constant, hold the
            # measured event's mutex partner ACTIVE and drive the DUT into its
            # spec INVALID state (a FALSE TIMEOUT on correct RTL,
            # `cvdp_copilot_flop_0001`).
            #
            # §4.05 CRITICAL — this MUST NOT be handled by UNCONDITIONALLY
            # reclassifying the bit as a reset (held inactive for the canonical
            # measurement): a name like `set` is ALSO a legitimate FUNCTIONAL
            # control, and holding it inactive would MASK a genuine off-by-N
            # latency bug that only manifests at its canonical (all-ones) value.
            # The discriminator is TIMEOUT: an SR-flop's invalid-state partner
            # makes the output NEVER assert (timeout) — safe to retry inactive;
            # a functional-control bug produces a WRONG-but-present latency
            # (MISMATCH, not timeout) which must hard-block. So the set/reset-bit
            # handling lives ONLY in the TIMEOUT-gated mutex-bit retry below, NOT
            # here. (Was: an unconditional `is_rst = True` here — a §4.05 leak.)
            if is_rst:
                resets.append(pi)
                continue
            others.append(pi)
    return clk, resets, event_port, output_port, others


# ─── measurement testbench generation ────────────────────────────────────────
def _concretise_width(width_str: str, params: Dict[str, int]) -> str:
    """Substitute resolved param VALUES into a `[MSB:LSB]` width string so the
    TB reg/wire declaration is fully numeric (TB scope has no module params).
    `[WIDTH-1:0]` with WIDTH=8 → `[8-1:0]` (iverilog folds the constant). A
    width referencing a param NOT in `params` is left verbatim (the instance
    #(...) carries the value into the DUT; the TB net then mirrors via the
    same substitution where it can)."""
    if not width_str:
        return ""

    def _sub(m: "re.Match") -> str:
        nm = m.group(0)
        return str(params[nm]) if nm in params else nm

    return _IDENT_RE.sub(_sub, width_str)


def _decl_width(pi: PortInfo, params: Dict[str, int]) -> str:
    """The `[w]` declaration fragment for a TB reg/wire mirroring this port,
    with module parameters substituted to concrete integers (TB scope cannot
    see the DUT's #(...) params)."""
    w = _concretise_width(pi.width_str, params)
    return f" {w}" if w else ""


# ─── unpacked-array TB modelling helpers (ORGANIC #767) ──────────────────────
def _decl_unpacked(pi: PortInfo, params: Dict[str, int]) -> str:
    """The trailing UNPACKED dimension fragment for a TB net mirroring this
    port (rendered AFTER the net name: `reg [7:0] lane [7:0];`). Empty for a
    scalar/packed-only port. Parameterised bounds are param-substituted, like
    the packed width, so a parameterised array port elaborates."""
    if not pi.unpacked_dims:
        return ""
    return " " + _concretise_width(pi.unpacked_dims, params)


def _unpacked_indices(pi: PortInfo, params: Dict[str, int]) -> Optional[List[int]]:
    """The concrete list of element indices for a SINGLE-dimension unpacked
    array port (e.g. "[7:0]" -> [7,6,..,0], "[0:3]" -> [0,1,2,3]). Returns None
    when the port is not an array, has a non-constant bound, or has MORE than one
    unpacked dimension (multi-dim is conservatively left to the rc=3 fallback —
    we never fabricate a drive we can't model exactly)."""
    if not pi.unpacked_dims:
        return None
    dims = _concretise_width(pi.unpacked_dims, params)
    groups = re.findall(r"\[([^\]]+)\]", dims)
    if len(groups) != 1:
        return None  # multi-dim — not modelled element-wise
    g = groups[0].strip()
    # `[N]` short-form unpacked dimension == `[0:N-1]` (indices 0..N-1).
    if ":" not in g:
        try:
            n = int(g)
        except ValueError:
            return None
        if n <= 0:
            return None
        return list(range(n))
    m = re.match(r"\s*([^:]+?)\s*:\s*([^:]+?)\s*$", g)
    if not m:
        return None
    try:
        a, b = int(m.group(1)), int(m.group(2))
    except ValueError:
        return None
    # Inclusive index set in DECLARATION order (handles both `[7:0]` descending
    # and `[0:3]` ascending unpacked ranges — the order only affects emission,
    # every element is driven the same constant).
    step = 1 if b >= a else -1
    return list(range(a, b + step, step))


def build_measurement_tb(top: str, clk: Optional[PortInfo],
                         resets: List[PortInfo], event_port: PortInfo,
                         output_port: PortInfo, others: List[PortInfo],
                         reset_active_low_map: Dict[str, bool],
                         input_const: int, max_cycles: int,
                         params: Optional[Dict[str, int]] = None,
                         reset_hold: int = 5,
                         inactive_inputs: Optional[set] = None,
                         datapath_mode: bool = False,
                         localparams: Optional[set] = None,
                         event_value: Optional[str] = None) -> str:
    """Emit the self-contained canonical-latency measurement TB.

    Convention:
      reset asserted `reset_hold` cycles → deasserted → quiescent settle →
      `event` pulsed HIGH for EXACTLY ONE clock (one posedge latch edge) →
      from THAT latch edge, count posedges of clk until `output` first == 1.

    `params` (resolved module #(...) values + --param overrides) is forwarded
    to the DUT instance as `#(.NAME(VAL))` AND substituted into every TB net
    width so a parameterised design elaborates with no out-of-scope param.

    `inactive_inputs` (ORGANIC #770 round-2, Part C) is the set of `others` port
    NAMES to drive to their INACTIVE value instead of the all-active data
    constant. It is the ONE-HOT arbiter retry mechanism: the COMPETING request
    inputs of a bus arbiter are held inactive so the measured request (the
    event) wins arbitration and the measured grant is reachable. An empty /
    None set is the byte-for-byte unchanged default stimulus (§4.05 no-leak: a
    non-arbiter design never populates this set, so its TB is identical).

    ORGANIC #810 — `inactive_inputs` may instead be a DICT {name: bit} where
    `bit` is the per-port INACTIVE single-bit value ("1'b0" or "1'b1"). A
    STRUCTURAL synchronous-clear-equivalent control (see
    `detect_structural_clear_equiv`) is held in its NON-clearing value, whose
    polarity is INFERRED — an active-HIGH clear is held LOW ("1'b0"), an
    active-LOW clear held HIGH ("1'b1"). A plain `set` keeps the legacy
    all-ZEROS drive (the arbiter / mutex-bit retries), so those paths are
    byte-for-byte unchanged.
    """
    params = params or {}
    # `inactive_inputs` accepts a set (legacy all-zeros) or a dict
    # {name: inactive_bit}. Normalise to {name: bit}; a set maps every name to
    # the all-zeros bit "1'b0" (the unchanged arbiter / mutex-bit behaviour).
    if isinstance(inactive_inputs, dict):
        inactive_map: Dict[str, str] = dict(inactive_inputs)
    else:
        inactive_map = {nm: "1'b0" for nm in (inactive_inputs or set())}
    localparams = localparams or set()
    L: List[str] = []
    L.append("`timescale 1ns/1ps")
    L.append("module latency_tb;")
    L.append("  reg clk = 0;")
    for r in resets:
        L.append(f"  reg{_decl_width(r, params)} {r.name}"
                 f"{_decl_unpacked(r, params)};")
    L.append(f"  reg{_decl_width(event_port, params)} {event_port.name}"
             f"{_decl_unpacked(event_port, params)};")
    for o in others:
        L.append(f"  reg{_decl_width(o, params)} {o.name}"
                 f"{_decl_unpacked(o, params)};")
    L.append(f"  wire{_decl_width(output_port, params)} {output_port.name}"
             f"{_decl_unpacked(output_port, params)};")
    # ORGANIC #787 — in DATAPATH mode the output is a multi-bit result bus, not a
    # 1-bit pulse: latency is the first cycle the bus CHANGES from its settled
    # post-reset value. Capture that baseline so the assert predicate can be
    # `out !== out_rstval` instead of `out === 1'b1`.
    if datapath_mode:
        L.append(f"  reg{_decl_width(output_port, params)} out_rstval;")
        # ORGANIC #787 r2 (Step-2.7 §4.05) — measure the SETTLE cycle (the LAST
        # change), not the FIRST change: a staged-partial / glitch bus moves
        # before it commits, so first-change under-measures the latency. Track
        # the previous bus value, the last cycle it changed, and how many times
        # it changed (>1 ⇒ the committed-result cycle is ambiguous ⇒ ADVISORY,
        # never a hard PASS).
        L.append(f"  reg{_decl_width(output_port, params)} out_prev;")
        L.append("  integer last_change;")
        L.append("  integer change_count;")
    L.append("  integer cyc;")
    L.append("  integer measured;")
    # DUT instance (named connections; only declared TB nets are wired). The
    # resolved params are passed through #(.NAME(VAL)) so the design's own
    # internal `WIDTH`-typed signals + the --expect resolution agree.
    # ORGANIC #793 — the override list is built from REAL PARAMETER names ONLY.
    # Names declared `localparam` inside the `#(...)` block are derived constants
    # the instance inherits from its own defaults; their VALUES are still used for
    # the TB net widths above, but emitting them here ("Cannot override
    # localparam") is an iverilog elaboration error on otherwise-correct RTL.
    inst_params = ""
    override_params = {nm: val for nm, val in params.items()
                       if nm not in localparams}
    if override_params:
        inst_params = " #(" + ", ".join(
            f".{nm}({val})" for nm, val in sorted(override_params.items())) + ")"
    conns: List[str] = []
    if clk is not None:
        conns.append(f".{clk.name}(clk)")
    for r in resets:
        conns.append(f".{r.name}({r.name})")
    conns.append(f".{event_port.name}({event_port.name})")
    for o in others:
        conns.append(f".{o.name}({o.name})")
    conns.append(f".{output_port.name}({output_port.name})")
    L.append(f"  {top}{inst_params} dut({', '.join(conns)});")
    L.append("  always #5 clk = ~clk;")
    ev = event_port.name
    out = output_port.name
    L.append("  initial begin")
    L.append("    measured = -1;")
    # assert reset (each per its polarity), drive constant inputs + event low
    for r in resets:
        asserted = "1'b0" if reset_active_low_map.get(r.name, False) else "1'b1"
        L.append(f"    {r.name} = {asserted};")
    L.append(f"    {ev} = 1'b0;")
    for o in others:
        # all-ones (or the const) constant so the design progresses. The
        # replication count is the port's concrete width; a fixed small const
        # is rendered as a plain decimal.
        # ORGANIC #770 round-2 (Part C) — a COMPETING request held INACTIVE for
        # the one-hot arbiter retry is driven to all-ZEROS regardless of the
        # data constant (so the measured request wins arbitration). Only the
        # ports the caller named in `inactive_inputs` are affected; every other
        # `other` keeps its byte-for-byte unchanged data-constant drive.
        # ORGANIC #810 — a STRUCTURAL clear-equivalent is held in its inferred
        # NON-clearing value (`inactive_map[o.name]` = "1'b0" for an active-HIGH
        # clear, "1'b1" for an active-LOW clear), replicated across the port
        # width; the arbiter / mutex-bit set path maps to the unchanged all-zeros.
        if o.name in inactive_map:
            val = f"{{{_width_token(o, params)}{{{inactive_map[o.name]}}}}}"
        elif input_const < 0:
            val = f"{{{_width_token(o, params)}{{1'b1}}}}"
        else:
            val = str(input_const)
        # ORGANIC #767 — an UNPACKED-ARRAY input cannot take a single flat
        # assignment (`bus = {8{1'b1}}` is illegal on `reg [7:0] bus [7:0]`).
        # Drive it ELEMENT-WISE with the SAME per-element constant so each lane
        # carries the data the design expects. Single-dim concrete arrays only;
        # a non-modellable shape is screened to rc=3 before the TB is built.
        idxs = _unpacked_indices(o, params)
        if idxs is not None:
            for k in idxs:
                L.append(f"    {o.name}[{k}] = {val};")
        else:
            L.append(f"    {o.name} = {val};")
    # hold reset for `reset_hold` posedges
    L.append(f"    repeat ({reset_hold}) @(posedge clk);")
    # deassert reset
    for r in resets:
        deasserted = "1'b1" if reset_active_low_map.get(r.name, False) else "1'b0"
        L.append(f"    {r.name} = {deasserted};")
    # quiescent settle (let the design reach a known idle before the event)
    L.append("    repeat (2) @(posedge clk);")
    #
    # CANONICAL latency convention — posedge-CONSISTENT, NO negedge sampling.
    # Latency is measured relative to the event-latch posedge E (where the DUT
    # samples `event` HIGH).
    #
    # (1) PRECONDITION — `out` MUST be LOW before the event. If it is already
    #     HIGH the measurement is meaningless (an out-of-reset `valid`); emit a
    #     distinct error sentinel and stop (→ rc 2). Sampled in the clk LOW
    #     phase (after a negedge), so it reflects the settled steady state.
    L.append("    @(negedge clk);")
    if datapath_mode:
        # ORGANIC #787 — a multi-bit datapath bus has an ARBITRARY settled
        # post-reset value (often non-zero); `out === 1'b1` is not a meaningful
        # precondition. Capture the settled baseline and detect the first CHANGE
        # away from it as the assertion — never flag "already HIGH".
        L.append(f"    out_rstval = {out};")
        assert_pred = f"({out} !== out_rstval)"
    else:
        L.append(f"    if ({out} === 1'b1) begin")
        L.append('      $display("LATENCY_PRECONDITION_HIGH");')
        L.append("      $finish;")
        L.append("    end")
        assert_pred = f"({out} === 1'b1)"
    # (2) COMBINATIONAL latency 0 — assert event HIGH in the SAME clk LOW phase
    #     (we are just after a negedge) and let purely-combinational logic
    #     settle WITHOUT crossing a posedge (a small in-phase delay). If `out`
    #     goes HIGH with no clock edge → measured = 0.
    #     C5: a MULTI-BIT event (e.g. a consensus/AND-reduction `inp[N-1:0]`)
    #     must be asserted ALL-ONES, not the scalar `1'b1` (which sets only the
    #     LSB ⇒ a consensus output never asserts). The width is the port's
    #     concrete (param-substituted) width; a scalar renders as plain `1'b1`.
    ev_w = _width_token(event_port, params)
    ev_assert = "1'b1" if ev_w == "1" else f"{{{ev_w}{{1'b1}}}}"
    ev_deassert = "1'b0" if ev_w == "1" else f"{{{ev_w}{{1'b0}}}}"
    # ORGANIC #795 — a multi-bit datapath EVENT-VALUE retry overrides the blind
    # all-ones assert with a concrete distinct codeword so a decoder/LUT/ROM whose
    # all-ones input is an invalid/no-op symbol (mapping to the reset baseline) is
    # actually driven to a value that moves the bus. The scalar (1-bit pulse) path
    # is never touched: a 1-bit event keeps the `1'b1` pulse.
    if event_value is not None and ev_w != "1":
        ev_assert = event_value
    L.append(f"    {ev} = {ev_assert};")
    L.append("    #1;   // settle combinational paths, still inside the low phase")
    if datapath_mode:
        # ORGANIC #787 r2 — SETTLE measurement: latency = the LAST cycle the bus
        # changes (its committed/held value), not the first transient move. A bus
        # that changes more than once after the event (staged partial, glitch) is
        # AMBIGUOUS → emit DATAPATH_MULTI_CHANGE (advisory), never a hard PASS.
        L.append("    out_prev = out_rstval;")
        L.append("    last_change = -1;")
        L.append("    change_count = 0;")
        L.append(f"    if {assert_pred} begin   // combinational (latency-0) change")
        L.append(f"      last_change = 0; change_count = 1; out_prev = {out};")
        L.append("    end")
        L.append("    @(posedge clk);          // event-latch posedge E (t=0)")
        # ORGANIC #795 — for a multi-bit datapath CODE input the event is a LEVEL
        # codeword, not a pulse: HOLD it steady after the latch. Yanking it back
        # to all-zeros (the pulse convention) would make the decoded bus change a
        # SECOND time (codeword→decoded, then →baseline) and be falsely flagged
        # DATAPATH_MULTI_CHANGE. Holding the codeword yields a single change to
        # its committed value ⇒ a clean first-change latency. The all-ones /
        # default path still pulse-deasserts (byte-for-byte unchanged).
        if event_value is None:
            L.append(f"    {ev} <= {ev_deassert};   // one-edge event pulse")
        L.append(f"    for (cyc = 1; cyc <= {max_cycles}; cyc = cyc + 1) begin")
        L.append("      @(posedge clk);        // posedge E+cyc")
        L.append(f"      if ({out} !== out_prev) begin")
        L.append(f"        last_change = cyc; change_count = change_count + 1; out_prev = {out};")
        L.append("      end")
        L.append("    end")
        L.append("    if (last_change < 0) begin")
        L.append(f'      $display("LATENCY_TIMEOUT %0d", {max_cycles});')
        L.append("    end else if (change_count > 1) begin")
        L.append('      $display("DATAPATH_MULTI_CHANGE=%0d", last_change);')
        L.append("    end else begin")
        L.append('      $display("MEASURED_LATENCY=%0d", last_change);')
        L.append("    end")
        L.append("    $finish;")
        L.append("  end")
        # shared tail: global hard cutoff + endmodule (identical to the pulse path)
        L.append("  initial begin")
        L.append(f"    #{(max_cycles + reset_hold + 32) * 10 * 4};")
        L.append('    $display("LATENCY_TIMEOUT %0d", ' + str(max_cycles) + ");")
        L.append("    $finish;")
        L.append("  end")
        L.append("endmodule")
        return "\n".join(L) + "\n"
    L.append(f"    if {assert_pred} begin")
    L.append("      measured = 0;")
    L.append("    end else begin")
    # (3) REGISTERED latency >= 1 — `out` is still LOW after the comb settle.
    #     Advance to the event-latch posedge E (the DUT samples event HIGH
    #     here). Deassert event with an NBA right after E so it is a clean
    #     ONE-edge pulse. Then COUNT full posedges, reading `out` AT each
    #     posedge (in-process, AFTER this step's NBAs settle) so it reflects
    #     the value registered by the PREVIOUS edge:
    #       posedge E+1 reflects E's update — `out <= start` reads HIGH ⇒ 1;
    #       a 2-stage `r<=start; out<=r` reads 0 at E+1, HIGH at E+2 ⇒ 2.
    L.append("      @(posedge clk);          // event-latch posedge E (t=0)")
    L.append(f"      {ev} <= {ev_deassert};   // one-edge event pulse")
    L.append(f"      for (cyc = 1; cyc <= {max_cycles}; cyc = cyc + 1) begin")
    L.append("        @(posedge clk);        // posedge E+cyc")
    L.append(f"        if {assert_pred} begin")
    L.append("          measured = cyc;")
    L.append(f"          cyc = {max_cycles} + 1;   // break")
    L.append("        end")
    L.append("      end")
    L.append("    end")
    L.append("    if (measured >= 0) begin")
    L.append('      $display("MEASURED_LATENCY=%0d", measured);')
    L.append("    end else begin")
    L.append(f'      $display("LATENCY_TIMEOUT %0d", {max_cycles});')
    L.append("    end")
    L.append("    $finish;")
    L.append("  end")
    # global hard cutoff so a hung DUT cannot wedge the sim
    L.append("  initial begin")
    L.append(f"    #{(max_cycles + reset_hold + 32) * 10 * 4};")
    L.append('    $display("LATENCY_TIMEOUT %0d", ' + str(max_cycles) + ");")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def _width_token(pi: PortInfo, params: Optional[Dict[str, int]] = None) -> str:
    """A Verilog replication-count token for an all-ones constant of this
    port's width: the numeric width if known, else the symbolic `(MSB-LSB+1)`
    from the (param-substituted) width string. Falls back to 1 for a scalar."""
    ws = _concretise_width(pi.width_str, params or {})
    m = re.match(r"\s*\[\s*([^:\]]+)\s*:\s*([^:\]]+)\s*\]", ws or "")
    if not m:
        return "1"
    msb, lsb = m.group(1).strip(), m.group(2).strip()
    # numeric → plain width; symbolic → ((msb)-(lsb)+1)
    try:
        return str(abs(int(msb) - int(lsb)) + 1)
    except ValueError:
        return f"(({msb})-({lsb})+1)"


# ─── iverilog/vvp drive ──────────────────────────────────────────────────────
def _run(cmd: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out or "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


_MEAS_RE = re.compile(r"^MEASURED_LATENCY=(\d+)\s*$", re.MULTILINE)
_TIMEOUT_RE = re.compile(r"^LATENCY_TIMEOUT\s+(\d+)\s*$", re.MULTILINE)
_PRECOND_RE = re.compile(r"^LATENCY_PRECONDITION_HIGH\s*$", re.MULTILINE)
# ORGANIC #787 r2 (Step-2.7 §4.05) — a datapath bus that changed MORE THAN ONCE
# after the event: the committed-result cycle cannot be inferred from latency
# alone (staged partial / glitch), so the measurement is ADVISORY, never a hard
# PASS that could mask a genuine multi-cycle latency.
_DP_MULTI_RE = re.compile(r"^DATAPATH_MULTI_CHANGE=(\d+)\s*$", re.MULTILINE)
# ORGANIC #795 — bound the datapath EVENT-VALUE retry probe count (RTL-own
# codewords + a small generic spread) so a wide event input cannot explode the
# sim count on a genuinely-stuck bus (which still TIMEs out after all probes).
_DP_MAX_EVENT_PROBES = 8


def measure_latency(rtl_path: Path, tb_text: str, workdir: Path,
                    context_files: Optional[List[Path]] = None
                    ) -> Tuple[Optional[int], str, str]:
    """Compile + run the measurement TB; return (measured, status, err).

    `status` is one of:
      * "ok"               — `measured` is the integer latency.
      * "timeout"          — output never asserted in the window.
      * "precondition_high"— `output` was already HIGH before the event (the
                             measurement is meaningless).
    `err` is non-empty only on a compile/run failure (status "" then).
    The caller has already confirmed iverilog/vvp are present.

    `context_files` (C5) are EXTRA RTL sources compiled alongside `--rtl` so a
    DUT that instantiates a prompt-provided submodule (e.g. a leading-zero
    counter, an sbox) resolves all module references. They are pure context —
    `-s latency_tb` keeps the top fixed.
    """
    tb_path = workdir / "latency_tb.sv"
    tb_path.write_text(tb_text)
    binp = workdir / "latency_sim.vvp"
    extra = [str(p) for p in (context_files or [])]
    rc, out, err = _run(["iverilog", "-g2012", "-o", str(binp),
                         "-s", "latency_tb", str(rtl_path), *extra,
                         str(tb_path)])
    if rc != 0:
        blob = ((out or "") + "\n" + (err or "")).strip()
        return None, "", ("RTL + measurement-TB did not compile: "
                          + "; ".join(blob.splitlines()[:5]))
    rc2, out2, err2 = _run(["vvp", str(binp)])
    sim = out2 or ""
    # precondition-high takes priority — it is emitted before any measurement.
    if _PRECOND_RE.search(sim):
        return None, "precondition_high", ""
    mm = _MEAS_RE.search(sim)
    if mm:
        return int(mm.group(1)), "ok", ""
    dpm = _DP_MULTI_RE.search(sim)
    if dpm:
        # the bus settled at this cycle but moved more than once getting there →
        # ambiguous; report the settle cycle but mark the status advisory.
        return int(dpm.group(1)), "datapath_ambiguous", ""
    if _TIMEOUT_RE.search(sim):
        return None, "timeout", ""
    return None, "", ("measurement TB produced no MEASURED_LATENCY line "
                      "(vvp stderr: "
                      + "; ".join((err2 or "").splitlines()[:3]) + ")")


# ─── orchestration ───────────────────────────────────────────────────────────
def run_latency_conformance(
    rtl_path: Path, top: Optional[str], event: str, output: str,
    expect: str, params_override: Dict[str, int],
    reset_override: Optional[str], reset_active_low_flag: Optional[bool],
    input_const: int, max_cycles_override: Optional[int],
    mode: str = "latency", allow_no_handshake: bool = False,
    context_files: Optional[List[Path]] = None,
    latency_origin: str = "exclusive",
) -> Tuple[int, Dict]:
    """Run the gate; return (rc, report). rc is the program exit code.

    rc 0  = ok / SKIP, rc 1 = MISMATCH / TIMEOUT, rc 2 = setup error,
    rc 3  = NOT_APPLICABLE (no-handshake streaming, only with
    `allow_no_handshake`).
    """
    report: Dict = {
        "program": "latency_conformance_check",
        "mode": mode,
        "rtl": str(rtl_path),
        "event": event,
        "output": output,
        "expect_expr": expect,
        "methodology": ("canonical event->output latency MEASUREMENT (TB counts "
                        "posedges from the one-cycle event pulse to the output "
                        "assertion) vs the resolved spec literal — independent "
                        "of the design's self-TB"),
        "reads_only": "rtl + generated measurement TB (no oracle / hidden TB)",
    }
    if mode not in _MODES:
        report["verdict"] = "ERROR"
        report["reason"] = (f"--mode {mode!r} not implemented; only "
                            f"{sorted(_MODES)} (latency) is wired today")
        return 2, report

    rtl_text = rtl_path.read_text(errors="replace")

    # resolve top
    if top is None:
        names = re.findall(r"\bmodule\s+([A-Za-z_]\w*)", rtl_text)
        if not names:
            report["verdict"] = "ERROR"
            report["reason"] = "no module declaration found in RTL"
            return 2, report
        top = names[0]
    report["top"] = top

    ports = parse_module_ports(rtl_text, top)
    if not ports:
        report["verdict"] = "ERROR"
        report["reason"] = (f"no ports parsed for module {top!r} (does the "
                            f"module exist and use an ANSI port list?)")
        return 2, report

    # ORGANIC #767 — recover any trailing UNPACKED array dimensions the shared
    # 3-tuple parser drops, so an `input wire [7:0] lane [7:0]` array port is
    # modelled as an array in the measurement TB (per-element decl + drive)
    # rather than wired scalar-to-array (an iverilog elaboration ERROR → a false
    # rc=2 BLOCK on correct RTL). Empty map for a design with no array ports.
    unpacked_map = parse_unpacked_dims(rtl_text, top)
    report["array_ports"] = unpacked_map
    clk, resets, event_port, output_port, others = classify_ports(
        ports, event, output, reset_override, unpacked_map)

    if event_port is None:
        report["verdict"] = "ERROR"
        report["reason"] = (f"--event port {event!r} not found in module "
                            f"{top!r} (declared ports: "
                            f"{[n for _d, _w, n in ports]})")
        return 2, report
    if output_port is None:
        report["verdict"] = "ERROR"
        report["reason"] = (f"--output port {output!r} not found as an OUTPUT "
                            f"in module {top!r} (declared ports: "
                            f"{[(d, n) for d, _w, n in ports]})")
        return 2, report
    report["clk"] = clk.name if clk else None
    report["resets"] = [r.name for r in resets]
    report["other_inputs_held_constant"] = [o.name for o in others]

    # ORGANIC #807 — MULTI-CLOCK (CDC) guard. A single free-running-clock
    # event→output LATENCY is UNDEFINED across asynchronous clock domains: an
    # async-FIFO (`w_clk`/`r_clk`) or any ≥2-clock-input design cannot be measured
    # by the single-clock convention. Screen it to the DISTINCT rc=3
    # NOT_APPLICABLE verdict (never a false rc=1 TIMEOUT, never a fake rc=0 PASS).
    # The robust `_is_clock` (#805/#807) now recognises the non-standard spellings
    # so this count is accurate. A single-clock design (n==1) measures as before.
    # Step-2.7 §4.05 — count ONLY a clock-named input that is actually EDGE-SENSED
    # (`posedge <n>` / `negedge <n>`) in the RTL. A clock-STATUS/HEALTH input
    # (clk_lock / clk_mon / clk_stable — a PLL-lock or monitor tap) is read
    # combinationally, never in a clock-edge sensitivity, so it can never inflate
    # the CDC count and false-screen a genuine single-clock design to rc=3.
    def _is_edge_sensed(nm: str) -> bool:
        return re.search(r"\b(?:pos|neg)edge\s+" + re.escape(nm) + r"\b",
                         rtl_text) is not None
    clock_inputs = [n for d, _w, n in ports
                    if d == "input" and n != event and _is_clock(n)
                    and _is_edge_sensed(n)]
    if len(clock_inputs) >= 2:
        report["verdict"] = "NOT_APPLICABLE"
        report["clock_inputs"] = clock_inputs
        report["measured_latency"] = None
        report["reason"] = (
            f"design has {len(clock_inputs)} clock inputs {clock_inputs} "
            f"(multi-clock / CDC) — a single free-running-clock event->output "
            f"latency is undefined across asynchronous domains; NOT-APPLICABLE "
            f"(rc=3, NOT a false TIMEOUT or a fake PASS)")
        return 3, report

    # ORGANIC #770 round-2 (Part C) — ARBITER / MUTUAL-EXCLUSION stimulus class.
    # Detect the structural bus-arbiter signature: the MEASURED request (event)
    # plus other COMPETING request inputs, against multiple grant outputs. The
    # signature is name-anchored (request*/grant*), NARROW (≥1 competing request
    # AND a grant-named output) — a non-arbiter design populates an EMPTY
    # competing-request set so the one-hot retry below is structurally dead for
    # it (§4.05 no-leak). The all-output port name set lets us recognise a
    # multi-grant design even when only one grant is the measured output.
    all_output_names = [n for d, _w, n in ports if d == "output"]
    measured_is_request = _looks_like_request(event)
    competing_requests = [o.name for o in others if _looks_like_request(o.name)]
    output_is_grant = _looks_like_grant(output)
    any_grant_output = any(_looks_like_grant(n) for n in all_output_names)
    # Arbiter-class iff the measured event is a request, the MEASURED OUTPUT is a
    # grant, AND at least one OTHER competing request exists to hold inactive.
    # ORGANIC #770 r2 Step-2.7: the measured output MUST itself be a grant
    # (`output_is_grant`) — the one-hot retry's stimulus surgery (holding req
    # inputs inactive) is only semantically justified when the thing we measure is
    # the grant for the measured request. The earlier `any_grant_output` disjunct
    # let the retry fire while measuring a NON-grant output (e.g. a status/done
    # line), where suppressing requests can hide a real timing miss. The design
    # must ALSO expose ≥2 grant outputs (a genuine multi-master arbiter) for the
    # mutex semantics to apply.
    grant_outputs = [n for n in all_output_names if _looks_like_grant(n)]
    is_arbiter_class = bool(
        measured_is_request and output_is_grant and len(grant_outputs) >= 2
        and competing_requests)
    report["arbiter_class"] = is_arbiter_class
    if is_arbiter_class:
        report["competing_requests_held_inactive_on_retry"] = competing_requests

    # resolve --expect against the module params (+ overrides)
    try:
        params = resolve_params(rtl_text, top, params_override)
        # ORGANIC #793 — names declared `localparam` inside the `#(...)` block are
        # derived constants the instance inherits; their VALUES live in `params`
        # (for widths + --expect) but they are NEVER overridden in the DUT
        # instantiation below ("Cannot override localparam" elaboration error).
        localparams = module_localparam_names(rtl_text, top)
        report["resolved_params"] = params
        if localparams:
            report["localparams"] = sorted(localparams)
        expected = safe_eval_arith(expect, params)
    except ExpectError as e:
        report["verdict"] = "ERROR"
        report["reason"] = f"--expect resolution failed: {e}"
        return 2, report
    # DoS guard — a huge resolved expect (e.g. `8*1000000`) would be emitted
    # verbatim into the TB loop bound + `#delay` cutoff, stalling each record
    # ~120 s. A real event->output latency is small; reject anything above a
    # sane ceiling FAST, before any sim is built.
    if expected < 0:
        report["verdict"] = "ERROR"
        report["reason"] = (f"resolved --expect {expect}={expected} is negative; "
                            f"a latency must be >= 0")
        return 2, report
    if expected > _MAX_EXPECT:
        report["verdict"] = "ERROR"
        report["reason"] = (f"resolved --expect {expect}={expected} exceeds the "
                            f"sane latency ceiling {_MAX_EXPECT}; refusing (a "
                            f"real event->output latency is small — this would "
                            f"only stall the sim)")
        return 2, report
    report["expected_latency"] = expected

    # ORGANIC #767 — UNPACKED-ARRAY port modelling guard.
    # A single-dimension, constant-bound array INPUT (e.g. `lane [7:0]`) is
    # fully modelled by the TB (per-element decl + element-wise drive), so it
    # proceeds normally. But two shapes the latency convention cannot model
    # FAITHFULLY are reclassified to a DISTINCT NOT_APPLICABLE (rc 3) rather than
    # left to crash the compile with a misleading hard rc=2 BLOCK on correct RTL:
    #   (a) the measured EVENT or the measured OUTPUT port is itself an array —
    #       the convention pulses a single event bit and reads a single output-
    #       assertion bit; an array event/output has no single-bit semantics here.
    #   (b) any held input is a MULTI-DIMENSION or NON-CONSTANT-bound array — we
    #       refuse to fabricate a drive we cannot enumerate exactly.
    # A scalar/packed-only design hits NONE of these (unpacked_dims=="") so its
    # behaviour is byte-for-byte unchanged (§4.05 no-leak).
    na_reason = None
    if event_port.is_array:
        na_reason = (f"--event port {event!r} is an UNPACKED-ARRAY "
                     f"({event_port.unpacked_dims}); the event->output latency "
                     f"convention pulses a single event bit and has no single-"
                     f"bit semantics for an array event")
    elif output_port.is_array:
        na_reason = (f"--output port {output!r} is an UNPACKED-ARRAY "
                     f"({output_port.unpacked_dims}); the latency convention "
                     f"counts cycles to a single output-assertion bit and has "
                     f"no single-bit semantics for an array output")
    else:
        for o in (others + resets):
            if o.is_array and _unpacked_indices(o, params) is None:
                na_reason = (f"input port {o.name!r} is a MULTI-DIMENSION or "
                             f"NON-CONSTANT-bound unpacked array "
                             f"({o.unpacked_dims}); refusing to fabricate an "
                             f"un-enumerable element-wise drive")
                break
    if na_reason is not None:
        report["verdict"] = "NOT_APPLICABLE"
        report["measured_latency"] = None
        report["reason"] = (na_reason + "; NOT-APPLICABLE (NOT a silent PASS, "
                            "NOT a real timing block)")
        return 3, report

    # ─── ORGANIC #787 — MULTI-BIT DATAPATH OUTPUT change-detect measurement ────
    # The measurement TB below models the --output as a 1-BIT done/valid PULSE
    # (`out === 1'b1`). That convention is meaningless for a MULTI-BIT DATAPATH
    # result bus: the bus only `=== 1'b1` when ALL bits happen to equal exactly
    # 1, so a correct registered datapath either never "asserts" (false TIMEOUT
    # rc=1) or its quiescent value coincidentally equals 1 and the PRECONDITION
    # fires (false rc=2) — both HARD-BLOCK correct RTL. When the PRIMARY --output
    # is a resolved width>1 bus that is NOT named like a handshake flag, MEASURE
    # the latency the faithful way: the same posedge-counting TB, but the
    # assertion is the FIRST CHANGE of the output away from its settled
    # post-reset value (`out !== <captured baseline>`) instead of `out === 1'b1`.
    # This is a real SIMULATION (not a structural guess), so the verdict reflects
    # the design's ACTUAL cycle-accurate latency — including FSM/enable-gated
    # multi-cycle datapaths a naive register-chain walk would mis-count.
    #
    # §4.05 no-leak — this only changes the ASSERT predicate for a genuine
    # multi-bit datapath bus:
    #   * a 1-bit output (width==1) keeps the unchanged `out===1'b1` pulse TB;
    #   * a wide output named done/valid/ready/ack/... (a real handshake declared
    #     as a vector) keeps the pulse TB (`_looks_like_pulse_output`);
    #   * a non-constant / unresolved width (None) keeps the pulse TB;
    #   * an UNPACKED-ARRAY output is screened to rc=3 above (never reaches here);
    #   * the latency is STILL MEASURED by simulation, so a GENUINE datapath
    #     latency mismatch (measured != --expect) still MISMATCHes (rc 1) and a
    #     bus that never changes still TIMEs out (rc 1). It can only convert a
    #     false `out===1`-model TIMEOUT/PRECONDITION on a CORRECT datapath bus
    #     into the faithful measured latency.
    out_width = _resolved_output_width(output_port.width_str, params)
    report["output_width"] = out_width
    datapath_mode = bool(out_width is not None and out_width > 1
                         and not output_port.is_array
                         and not _looks_like_pulse_output(output))
    report["datapath_output"] = datapath_mode
    if datapath_mode:
        report["measurement_method"] = (
            "first-change-from-reset-value (multi-bit datapath output; the 1-bit "
            "pulse `out===1` model does not apply to a result bus)")

    # reset polarity map
    #
    # ORGANIC #811 round-16 — the `--reset-active-low`/`--reset-active-high`
    # flag forces the polarity of the RESET the user named, NOT of every
    # reset-EQUIVALENT control held inactive alongside it. A synchronous
    # CLEAR/FLUSH (`i_clear`, `clr`, `flush`) has its OWN active-HIGH-by-default
    # convention (with the usual `_n`/`_b` low-suffix override) — applying the
    # reset's `--reset-active-low` to it would hold an active-HIGH clear HIGH
    # (== its CLEARING value) for the whole measurement, permanently flushing the
    # FSM → the SAME false LATENCY-TIMEOUT the name-strip fix was meant to cure
    # (`cvdp_copilot_signed_adder_0001`). So the explicit flag governs ONLY the
    # true reset port(s); a clear-class port always uses its own name-inferred
    # polarity. §4.05 no-leak: this only changes the held value of a clear that
    # the canonical TB would otherwise hold ACTIVE (a guaranteed timeout), never
    # a true reset's polarity.
    reset_active_low_map: Dict[str, bool] = {}
    for r in resets:
        is_clear_class = _looks_like_clear(r.name) and r.name != reset_override
        if reset_active_low_flag is not None and not is_clear_class:
            reset_active_low_map[r.name] = reset_active_low_flag
        else:
            reset_active_low_map[r.name] = _reset_is_active_low(r.name)
    report["reset_active_low"] = reset_active_low_map

    # The measurement window. Default scales with the expected latency; an
    # explicit --max-cycles overrides. EITHER way it is hard-clamped to a
    # ceiling so a pathological value can never wedge the sim (MED DoS).
    if max_cycles_override is not None:
        max_cycles = max_cycles_override
    else:
        max_cycles = max(64, 4 * expected + 16)
    max_cycles = max(1, min(max_cycles, _MAX_CYCLES_CEILING))
    report["max_cycles"] = max_cycles

    # iverilog/vvp gate — refuse-don't-fake.
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        report["verdict"] = "SKIP"
        report["tool_available"] = False
        report["reason"] = ("iverilog/vvp absent — cannot MEASURE the RTL's "
                            "latency; reporting SKIP (NOT a fabricated "
                            "measurement or PASS)")
        return 0, report
    report["tool_available"] = True

    tb = build_measurement_tb(top, clk, resets, event_port, output_port,
                              others, reset_active_low_map, input_const,
                              max_cycles, params=params,
                              datapath_mode=datapath_mode,
                              localparams=localparams)
    report["measurement_tb_lines"] = tb.count("\n")

    report["context_files"] = [str(p) for p in (context_files or [])]
    workdir = Path(tempfile.mkdtemp(prefix="latconf_"))
    try:
        measured, status, err = measure_latency(rtl_path, tb, workdir,
                                                context_files=context_files)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # ORGANIC #770 round-2 (Part C) — ARBITER ONE-HOT RETRY.
    # The all-active stimulus pins EVERY competing request ACTIVE, so a
    # spec-correct arbiter may grant a DIFFERENT master and leave the measured
    # grant structurally UNREACHABLE → a false TIMEOUT on correct RTL. When (and
    # ONLY when) the design carries the arbiter signature AND the first
    # measurement TIMED OUT (the measured grant never asserted under contention),
    # retry with a ONE-HOT request stimulus: drive ONLY the measured request (the
    # event) active and hold the COMPETING requests INACTIVE. The measured grant
    # is then reachable and its genuine per-master latency is read.
    #
    # §4.05 no-leak — this retry can ONLY relax a TIMEOUT to a measurement; it can
    # never mask a real timing miss:
    #   * it fires ONLY on a TIMEOUT (status == "timeout"); a measured-but-wrong
    #     latency (MISMATCH) is NEVER retried — a genuine 2-cycle grant vs spec=1
    #     measures 2 and still hard-blocks.
    #   * a non-arbiter design has an EMPTY competing-request set (is_arbiter_class
    #     is False), so the retry is structurally dead for it.
    #   * if the one-hot retry STILL times out (the grant is genuinely
    #     unreachable for the measured master), the original TIMEOUT stands.
    if (status == "timeout" and is_arbiter_class and err == ""):
        # ORGANIC #770 r2 Step-2.7 — MUTEX-ARTIFACT PROOF before adopting the
        # one-hot result. The measured grant timing out under all-active stimulus
        # is a legitimate arbiter MUTEX artifact ONLY if the arbiter DID grant
        # SOMEONE ELSE under that same stimulus (the measured master simply lost
        # arbitration). If NO other grant asserted either, the design is genuinely
        # not granting — a real bug — and the one-hot retry's PASS would MASK it.
        # Probe each OTHER grant output under the ORIGINAL all-active stimulus; the
        # mutex artifact is confirmed iff at least one other grant DID assert.
        other_grants = [n for n in grant_outputs if n.lower() != output.lower()]
        # widths for the grant outputs, to build a probe PortInfo for each.
        _width_by_name = {nm: w for d, w, nm in ports if d == "output"}
        mutex_confirmed = False
        for og in other_grants:
            og_port = PortInfo(og, "output", _width_by_name.get(og, ""),
                               unpacked_map.get(og, ""))
            pwork = Path(tempfile.mkdtemp(prefix="latconf_probe_"))
            try:
                probe_tb = build_measurement_tb(
                    top, clk, resets, event_port, og_port,
                    others, reset_active_low_map, input_const, max_cycles,
                    params=params, localparams=localparams)
                _p_measured, p_status, _p_err = measure_latency(
                    rtl_path, probe_tb, pwork, context_files=context_files)
            except Exception:
                p_status = "error"
            finally:
                shutil.rmtree(pwork, ignore_errors=True)
            # BOTH a measured assertion ("ok") AND "precondition_high" (the other
            # grant is already/independently HIGH under the all-active stimulus)
            # prove the arbiter DID grant another master — the mutex artifact.
            if p_status in ("ok", "precondition_high"):
                mutex_confirmed = True
                break
        report["arbiter_mutex_artifact_confirmed"] = mutex_confirmed
        if mutex_confirmed:
            retry_tb = build_measurement_tb(
                top, clk, resets, event_port, output_port, others,
                reset_active_low_map, input_const, max_cycles, params=params,
                inactive_inputs=set(competing_requests),
                localparams=localparams)
            rwork = Path(tempfile.mkdtemp(prefix="latconf_onehot_"))
            try:
                r_measured, r_status, r_err = measure_latency(
                    rtl_path, retry_tb, rwork, context_files=context_files)
            finally:
                shutil.rmtree(rwork, ignore_errors=True)
            report["arbiter_onehot_retry"] = {
                "competing_requests_held_inactive": competing_requests,
                "retry_status": r_status,
                "retry_measured_latency": r_measured,
            }
            # Adopt the retry result ONLY if it MEASURED a latency (clean ok). A
            # retry that still times out / errors leaves the original TIMEOUT
            # untouched (no-leak: a genuinely unreachable grant still blocks).
            if r_status == "ok" and r_err == "":
                measured, status, err = r_measured, r_status, r_err
                report["measured_under_one_hot_arbitration"] = True

    # ORGANIC #795 — DATAPATH EVENT-VALUE RETRY. In datapath_mode a multi-bit
    # --event DATA/CODE input is driven blind ALL-ONES; for a decoder/LUT/ROM
    # that is commonly an INVALID/no-op codeword mapping to the reset baseline,
    # so the `out !== out_rstval` change-detect never fires → a FALSE TIMEOUT on
    # correct 1-cycle RTL. Retry with distinct codewords — the RTL's OWN
    # width-matched sized literals (its valid codewords, via
    # _rtl_event_value_candidates) first, then generic spread probes — each
    # driven HELD STEADY (event_value path, not pulse-deasserted, to avoid a
    # false DATAPATH_MULTI_CHANGE). Adopt the first that cleanly measures.
    # §4.05 no-leak: fires ONLY on a TIMEOUT (never on a MISMATCH); a bus that
    # does not change under ANY probed value still TIMEs out.
    if status == "timeout" and datapath_mode and err == "":
        try:
            _ev_w_int = int(_width_token(event_port, params))
        except (ValueError, TypeError):
            _ev_w_int = 0
        if _ev_w_int > 1:
            _all_ones = (1 << _ev_w_int) - 1
            _rtl_cands = _rtl_event_value_candidates(rtl_text, _ev_w_int)
            _generic = [1, 2, 1 << (_ev_w_int - 1), _all_ones >> 1]
            _probes: List[int] = []
            for _v in _rtl_cands + _generic:
                if 0 < _v < _all_ones and _v not in _probes:
                    _probes.append(_v)
            _probes = _probes[:_DP_MAX_EVENT_PROBES]
            report["datapath_event_value_probes"] = _probes
            # ORGANIC #795 Step-2.7 §4.05 — probe EVERY candidate and collect ALL
            # clean measurements; do NOT hard-PASS off the FIRST clean probe. A
            # spuriously-correct latency on one incidental codeword would MASK a
            # genuine multi-cycle bug on a DIFFERENT codeword (an incidental
            # self-test path at 2 cycles hiding a primary path at 4). Adopt the
            # WORST (MAX) latency across all cleanly-measured codewords so a
            # slow/buggy codeword is ALWAYS surfaced; a uniform-latency decoder
            # (all codewords agree) is unaffected. A genuinely stuck bus measures
            # nothing clean → the original TIMEOUT stands.
            _clean: List[Tuple[int, int]] = []   # (event_value, measured_latency)
            for _v in _probes:
                ev_tb = build_measurement_tb(
                    top, clk, resets, event_port, output_port, others,
                    reset_active_low_map, input_const, max_cycles,
                    params=params, datapath_mode=datapath_mode,
                    localparams=localparams,
                    event_value=f"{_ev_w_int}'d{_v}")
                ework = Path(tempfile.mkdtemp(prefix="latconf_dpev_"))
                try:
                    e_measured, e_status, e_err = measure_latency(
                        rtl_path, ev_tb, ework, context_files=context_files)
                finally:
                    shutil.rmtree(ework, ignore_errors=True)
                if e_status == "ok" and e_err == "" and e_measured is not None:
                    _clean.append((_v, e_measured))
            if _clean:
                _v_adopt, _m_adopt = max(_clean, key=lambda t: t[1])
                measured, status, err = _m_adopt, "ok", ""
                report["measured_under_datapath_event_value"] = _v_adopt
                report["datapath_event_value_measurements"] = {
                    str(v): m for v, m in _clean}

    # ORGANIC #809 round-12 (C1) — SET/RESET MUTEX-BIT on-timeout retry.
    # On a plain (non-arbiter, non-datapath) TIMEOUT, the all-ones data constant
    # may be pinning the measured event's MUTEX PARTNER ACTIVE — a SET/RESET bit
    # of a sequential primitive whose HIGH state structurally prevents the
    # measured output from asserting (e.g. SR-FF invalid state {S,R}=11 -> Q=0).
    # RETRY driving each such bit INACTIVE (0) ONE AT A TIME and adopt the FIRST
    # clean measurement.
    #
    # §4.05 NO-LEAK — the retry is NARROWLY name-anchored and TIMEOUT-gated so it
    # can ONLY relax a structural invalid-state timeout, never mask a real bug:
    #   * fires ONLY on status=="timeout" (a measured-but-wrong MISMATCH is NEVER
    #     retried — a genuine off-by-N still hard-blocks);
    #   * the probe set is ONLY the conventional SET/RESET mutex-bit spellings
    #     (`_looks_like_setreset_bit`: S/R/SD/RD/set/i_s/i_r…) — a GENERIC 1-bit
    #     functional control (`en`, `cfg`, `mode`, a select) is NEVER deactivated,
    #     so a design whose output is legitimately gated by such a control and is
    #     BUGGY at its canonical (all-ones) value still TIMES OUT and hard-blocks.
    #     (An earlier form probed EVERY 1-bit input and adopted any clean result —
    #     that masked real `en`/`cfg`-gated bugs; §4.05 leak, removed.)
    #   * excluded for arbiter-class (its own one-hot retry owns that) and for
    #     datapath_mode (its own event-value retry owns that);
    #   * if NO single set/reset-bit deactivation makes the output assert, the
    #     original TIMEOUT stands (a genuinely mis-latching design still blocks).
    if (status == "timeout" and err == "" and not is_arbiter_class
            and not datapath_mode):
        _scalar_others = [o for o in others
                          if not o.is_array and _width_of(o.width_str) == 1
                          and _looks_like_setreset_bit(o.name)]
        report["mutex_bit_retry_candidates"] = [o.name for o in _scalar_others]
        for _o in _scalar_others:
            rtb = build_measurement_tb(
                top, clk, resets, event_port, output_port, others,
                reset_active_low_map, input_const, max_cycles, params=params,
                inactive_inputs={_o.name}, localparams=localparams)
            rwork = Path(tempfile.mkdtemp(prefix="latconf_mutexbit_"))
            try:
                r_measured, r_status, r_err = measure_latency(
                    rtl_path, rtb, rwork, context_files=context_files)
            finally:
                shutil.rmtree(rwork, ignore_errors=True)
            if r_status == "ok" and r_err == "" and r_measured is not None:
                measured, status, err = r_measured, "ok", ""
                report["measured_with_inactive_bit"] = _o.name
                break

    # ORGANIC #810 — STRUCTURAL synchronous-CLEAR-EQUIVALENT on-timeout retry.
    # On a plain (non-arbiter, non-datapath) TIMEOUT that the name-based clear
    # allowlist did NOT catch, a 1-bit input that the canonical all-ones constant
    # pins ACTIVE may be a synchronous-CLEAR / FLUSH-equivalent — when asserted it
    # DOMINATINGLY forces the state/output register(s) to ZERO every clock (the
    # `if (S) State <= '0;` signature), so the measured output can NEVER assert
    # (`cvdp_copilot_rs_232_0001` / `Present_Processing_Completed`). RETRY holding
    # each STRUCTURALLY-detected clear-equivalent in its inferred NON-clearing
    # (INACTIVE) value ONE AT A TIME and adopt the FIRST clean measurement.
    #
    # §4.05 NO-LEAK — the detector is structurally NARROW (a guarded branch that
    # assigns ONLY constants and drives a register to ZERO; never a data load or
    # arithmetic update) AND the retry is TIMEOUT-gated + one-at-a-time, so it can
    # ONLY relax a structural permanent-flush timeout, never mask a real bug:
    #   * fires ONLY on status=="timeout" (a measured-but-wrong MISMATCH is NEVER
    #     retried — a genuine off-by-N still hard-blocks);
    #   * an ordinary data/enable input is NOT a constant-only zeroing branch, so
    #     it is NEVER flagged → its real latency dependency is preserved;
    #   * the inferred ACTIVE polarity makes "hold inactive" pin the control to
    #     the NON-clearing value (LOW for an active-HIGH clear), not all-ones;
    #   * excluded for arbiter-class / datapath_mode (their own retries own those);
    #   * if NO clear-equivalent deactivation makes the output assert, the
    #     original TIMEOUT stands (a genuinely mis-latching design still blocks).
    if (status == "timeout" and err == "" and not is_arbiter_class
            and not datapath_mode):
        _scalar_in_names = {n for d, w, n in ports
                            if d == "input" and n != event
                            and _width_of(w) == 1}
        _clear_equiv = detect_structural_clear_equiv(rtl_text, top,
                                                     _scalar_in_names)
        # only `others` (constant-driven) ports matter — a reset already held
        # inactive needs no retry; the event is excluded above.
        _other_names = {o.name for o in others}
        _clear_cands = {nm: al for nm, al in _clear_equiv.items()
                        if nm in _other_names}
        report["structural_clear_equiv_candidates"] = {
            nm: ("active_low" if al else "active_high")
            for nm, al in _clear_cands.items()}
        for _nm, _active_low in _clear_cands.items():
            # hold the clear-equivalent at its NON-clearing value: an active-HIGH
            # clear is held LOW ("1'b0"), an active-LOW clear held HIGH ("1'b1").
            _inactive_bit = "1'b1" if _active_low else "1'b0"
            ctb = build_measurement_tb(
                top, clk, resets, event_port, output_port, others,
                reset_active_low_map, input_const, max_cycles, params=params,
                inactive_inputs={_nm: _inactive_bit}, localparams=localparams)
            cwork = Path(tempfile.mkdtemp(prefix="latconf_clearequiv_"))
            try:
                c_measured, c_status, c_err = measure_latency(
                    rtl_path, ctb, cwork, context_files=context_files)
            finally:
                shutil.rmtree(cwork, ignore_errors=True)
            if c_status == "ok" and c_err == "" and c_measured is not None:
                measured, status, err = c_measured, "ok", ""
                report["measured_with_inactive_clear_equiv"] = _nm
                report["inactive_clear_equiv_polarity"] = (
                    "active_low" if _active_low else "active_high")
                break

    if err:
        report["verdict"] = "ERROR"
        report["reason"] = err
        return 2, report
    if status == "precondition_high":
        report["verdict"] = "PRECONDITION_HIGH"
        report["measured_latency"] = None
        report["reason"] = (f"output {output!r} already asserted (HIGH) before "
                            f"the {event!r} event — the latency measurement is "
                            f"meaningless (e.g. an out-of-reset always-HIGH "
                            f"signal)")
        return 2, report
    if status == "timeout":
        # ORGANIC #729 — a TIMEOUT on a STREAMING design with no pulse->done
        # handshake is NOT a real timing BLOCK and is NOT a PASS: there is no
        # event->output assertion to measure. Only with --allow-no-handshake do
        # we reclassify it to a DISTINCT NOT_APPLICABLE verdict on a DISTINCT
        # exit code (3) so it can never be misread as a real PASS or a real
        # block. WITHOUT the flag the default behaviour is unchanged (a design
        # that SHOULD pulse but mis-latches must still hard-block, rc 1).
        if allow_no_handshake:
            report["verdict"] = "NOT_APPLICABLE"
            report["measured_latency"] = None
            report["reason"] = (
                f"output {output!r} never asserted within {max_cycles} cycles "
                f"after the {event!r} pulse — this design has no pulse->done "
                f"handshake (streaming / continuously-valid), so the "
                f"event->output latency convention does not apply; "
                f"NOT-APPLICABLE (NOT a silent PASS, NOT a real timing block)")
            return 3, report
        report["verdict"] = "TIMEOUT"
        report["measured_latency"] = None
        report["reason"] = (f"output {output!r} never asserted within "
                            f"{max_cycles} cycles")
        return 1, report
    if status == "datapath_ambiguous":
        # ORGANIC #787 r2 (Step-2.7 §4.05) — the datapath bus changed MORE THAN
        # ONCE after the event (staged partial / glitch before commit), so the
        # committed-result cycle cannot be inferred from latency alone. Do NOT
        # certify it as a PASS (that would mask a genuine multi-cycle latency, the
        # reproduced leak); do NOT hard-block it either (a legitimately staged
        # datapath is not a timing bug). Emit a DISTINCT advisory verdict on the
        # NOT-APPLICABLE exit code (3): the measured settle cycle is reported but
        # the latency convention does not reliably apply.
        report["verdict"] = "DATAPATH_AMBIGUOUS"
        report["measured_latency"] = measured
        report["advisory"] = True
        report["reason"] = (
            f"datapath output {output!r} settled at cycle {measured} but its bus "
            f"changed more than once after the {event!r} event (staged/transient "
            f"value before commit), so an event->output latency cannot be reliably "
            f"measured — ADVISORY (NOT a PASS that could mask a multi-cycle "
            f"latency, NOT a hard timing block)")
        return 3, report

    report["measured_latency"] = measured
    # ORGANIC #744 round-17 — AUTHOR-DECLARED counting-origin convention.
    #
    # The gate MEASURES latency with a fixed EXCLUSIVE origin: it counts the
    # posedges STRICTLY AFTER the event-latch edge E (E itself is cycle 0). A spec
    # may instead enumerate the SAME timing INCLUSIVELY — counting the event-latch
    # cycle itself as cycle 1 (the canonical "1 cycle IDLE->BUSY + N cycles BUSY +
    # 1 cycle DONE = N+2" decomposition). An author who faithfully transcribes the
    # inclusive spec literal into --expect then sees an off-by-one that the #744
    # hint already explains but the gate could not RESOLVE — a false MISMATCH on
    # CORRECT RTL.
    #
    # `--latency-origin inclusive` lets the author DECLARE that --expect is stated
    # in the inclusive convention; the gate then compares the inclusive latency
    # (measured + 1, i.e. the exclusive measurement plus the event-latch cycle)
    # against --expect. Default `exclusive` => measured == expected, the v1.1.17
    # behaviour byte-for-byte (§4.05 no-leak for every existing invocation).
    #
    # §4.05 NO-LEAK — this is a DECLARED CONVENTION, not a +-1 TOLERANCE. Under a
    # FIXED origin the comparison stays EXACT, so a real +-1 latency bug still
    # MISMATCHes: a design 1 cycle EARLY measures exclusive E-1 (inclusive E), a
    # design 1 cycle LATE measures exclusive E+1 (inclusive E+2) — neither equals
    # the declared inclusive --expect=E+1. A blanket "accept measured+1==expected"
    # WOULD leak (it accepts an exclusive-spec design whose RTL is 1 cycle early),
    # which is exactly why the resolution is an author-declared origin, NOT a
    # tolerance: the +1 is applied to ONE side under the author's explicit
    # declaration, the gate never widens the accepted band to +-1.
    origin = (latency_origin or "exclusive").lower()
    report["latency_origin"] = origin
    if origin == "inclusive":
        # The latency the author declared is the inclusive count = exclusive
        # measurement + the event-latch cycle.
        measured_in_convention = measured + 1
    else:
        measured_in_convention = measured
    report["measured_latency_in_convention"] = measured_in_convention
    if measured_in_convention != expected:
        report["verdict"] = "MISMATCH"
        if origin == "inclusive":
            report["reason"] = (
                f"inclusive latency {measured_in_convention} (exclusive measured "
                f"{measured} + the event-latch cycle) != resolved spec "
                f"{expect}={expected}")
        else:
            report["reason"] = (f"measured latency {measured} != resolved spec "
                                f"{expect}={expected}")
        return 1, report

    report["verdict"] = "PASS"
    if origin == "inclusive":
        report["reason"] = (
            f"inclusive latency {measured_in_convention} (exclusive measured "
            f"{measured} + the event-latch cycle) == resolved spec "
            f"{expect}={expected}")
    else:
        report["reason"] = (f"measured latency {measured} == resolved spec "
                            f"{expect}={expected}")
    return 0, report


def _parse_param_override(items: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items or []:
        if "=" not in it:
            raise ExpectError(f"--param must be NAME=VAL, got {it!r}")
        nm, val = it.split("=", 1)
        nm = nm.strip()
        try:
            out[nm] = int(val.strip(), 0)
        except ValueError as e:
            raise ExpectError(
                f"--param {nm} value must be an integer, got {val!r}") from e
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("DETERMINISTIC latency-conformance gate (#705): MEASURE "
                     "the RTL's real event->output latency canonically and "
                     "BLOCK on mismatch vs the spec literal. The self-TB is "
                     "untrustworthy for timing; this program is the independent "
                     "yard-stick."))
    ap.add_argument("--rtl", required=True, help="the RTL file (.v/.sv)")
    ap.add_argument("--top", default=None,
                    help="DUT module name (default: the first module)")
    ap.add_argument("--event", required=True,
                    help="the start/trigger input port (pulsed HIGH one cycle)")
    ap.add_argument("--output", required=True,
                    help="the output port whose first 1-assertion ends the count")
    ap.add_argument("--expect", required=True,
                    help="spec latency literal: arithmetic over module params "
                         "(e.g. 'WIDTH+2', 'N+1', '8')")
    ap.add_argument("--param", action="append", default=[],
                    help="parameter override NAME=VAL (repeatable); overrides "
                         "the module's #(...) default")
    ap.add_argument("--reset", default=None,
                    help="force a specific reset port name (else auto-detect "
                         "from reset-style port names)")
    pol = ap.add_mutually_exclusive_group()
    pol.add_argument("--reset-active-low", dest="reset_active_low",
                     action="store_true", default=None,
                     help="force ALL detected resets active-LOW")
    pol.add_argument("--reset-active-high", dest="reset_active_low",
                     action="store_false", default=None,
                     help="force ALL detected resets active-HIGH")
    ap.add_argument("--input-const", type=int, default=-1,
                    help="constant driven on all other data inputs; -1 (default)"
                         " = all-ones, else a fixed decimal value")
    ap.add_argument("--max-cycles", type=int, default=None,
                    help="bounded measurement window (default max(64, "
                         "4*expected+16))")
    ap.add_argument("--mode", default="latency", choices=_MODES,
                    help="timing-conformance mode (only 'latency' is wired)")
    ap.add_argument("--latency-origin", dest="latency_origin",
                    choices=("exclusive", "inclusive"), default="exclusive",
                    help="AUTHOR-DECLARED counting origin for --expect (#744 "
                         "round-17). 'exclusive' (default, unchanged): --expect "
                         "counts posedges AFTER the event-latch edge (that edge "
                         "is cycle 0). 'inclusive': --expect counts the "
                         "event-latch cycle itself as cycle 1 (the canonical "
                         "'1 cycle in + N cycles compute + 1 cycle out = N+2' "
                         "spec decomposition); the gate then compares measured+1 "
                         "against --expect. This is a DECLARED convention, NOT a "
                         "+-1 tolerance: a real 1-cycle-early/late latency bug "
                         "still MISMATCHes under the fixed declared origin.")
    ap.add_argument("--allow-no-handshake", dest="allow_no_handshake",
                    action="store_true", default=False,
                    help="on a STREAMING design with no pulse->done handshake, "
                         "report a DISTINCT NOT-APPLICABLE (rc 3) instead of a "
                         "TIMEOUT — the event->output latency convention does "
                         "not apply (#729). Default OFF: a TIMEOUT stays rc 1.")
    ap.add_argument("--second-output", default=None,
                    help="(#740 G3) a SECOND output port whose latency has no "
                         "event->output handshake to MEASURE; its intended "
                         "per-output latency is INFERRED from the declared "
                         "intermediate pipeline registers feeding it. ADVISORY "
                         "only — reported, never blocks. Optionally compared "
                         "against --expect-second.")
    ap.add_argument("--expect-second", default=None,
                    help="(#740 G3) optional spec latency literal for "
                         "--second-output (arithmetic over module params); when "
                         "given AND the inference is unambiguous, an ADVISORY "
                         "note states whether the inferred latency matches.")
    ap.add_argument("--context", action="append", default=[],
                    help="(C5) extra RTL source file(s) to compile alongside "
                         "--rtl so a DUT that instantiates a prompt-provided "
                         "submodule (leading-zero counter, sbox, …) resolves "
                         "all module references. Repeatable; -s keeps the top "
                         "fixed. A directory expands to its *.v/*.sv files.")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    rtl_path = Path(args.rtl)
    if not rtl_path.is_file():
        print(f"ERROR: --rtl not found: {rtl_path}", file=sys.stderr)
        return 2

    # Resolve --context into a concrete file list (a directory expands to its
    # HDL sources; the --rtl file itself is never duplicated).
    context_files: List[Path] = []
    for c in args.context or []:
        cp = Path(c)
        if cp.is_dir():
            for f in sorted(cp.iterdir()):
                if f.suffix in (".v", ".sv") and f.resolve() != rtl_path.resolve():
                    context_files.append(f)
        elif cp.is_file():
            if cp.resolve() != rtl_path.resolve():
                context_files.append(cp)
        else:
            print(f"ERROR: --context not found: {cp}", file=sys.stderr)
            return 2

    try:
        overrides = _parse_param_override(args.param)
    except ExpectError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    rc, report = run_latency_conformance(
        rtl_path=rtl_path, top=args.top, event=args.event, output=args.output,
        expect=args.expect, params_override=overrides,
        reset_override=args.reset, reset_active_low_flag=args.reset_active_low,
        input_const=args.input_const, max_cycles_override=args.max_cycles,
        mode=args.mode, allow_no_handshake=args.allow_no_handshake,
        context_files=context_files, latency_origin=args.latency_origin)

    # ORGANIC #740 (G3) — SECOND-output per-output latency inference (ADVISORY).
    # Never changes rc: it only annotates the report + prints an advisory note.
    if args.second_output:
        _rtl_text = rtl_path.read_text(errors="replace")
        _top2 = report.get("top") or args.top
        if _top2 is None:
            _names = re.findall(r"\bmodule\s+([A-Za-z_]\w*)", _rtl_text)
            _top2 = _names[0] if _names else None
        _inf, _reason = (infer_output_latency_from_registers(
            _rtl_text, _top2, args.second_output) if _top2 else
            (None, "no module to scope the second output"))
        _sec = {"output": args.second_output, "inferred_latency": _inf,
                "reason": _reason, "advisory": True}
        if args.expect_second is not None and _inf is not None:
            try:
                _exp2 = safe_eval_arith(args.expect_second,
                                        report.get("resolved_params", {}) or {})
                _sec["expected_latency"] = _exp2
                _sec["matches_spec"] = (_inf == _exp2)
            except ExpectError as e:
                _sec["expect_second_error"] = str(e)
        report["second_output"] = _sec

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))

    verdict = report.get("verdict")
    expr = args.expect
    if verdict == "SKIP":
        print(f"SKIP — iverilog unavailable: {report['reason']}")
    elif verdict == "PRECONDITION_HIGH":
        print(f"LATENCY-ERROR: output {args.output} already asserted before "
              f"event {args.event}", file=sys.stderr)
    elif verdict == "ERROR":
        print(f"ERROR: {report['reason']}", file=sys.stderr)
    elif verdict == "NOT_APPLICABLE":
        print(f"LATENCY-NOT-APPLICABLE: output {args.output} never asserted "
              f"after the {args.event} pulse — no pulse->done handshake "
              f"(streaming design); the latency convention does not apply")
    elif verdict == "TIMEOUT":
        print(f"LATENCY-TIMEOUT: output {args.output} never asserted within "
              f"{report['max_cycles']} cycles")
    elif verdict == "MISMATCH":
        _conv = report.get("measured_latency_in_convention",
                           report['measured_latency'])
        if report.get("latency_origin") == "inclusive":
            print(f"LATENCY-MISMATCH: inclusive latency {_conv} (exclusive "
                  f"measured={report['measured_latency']} + the event-latch "
                  f"cycle) but spec {expr}={report['expected_latency']}")
        else:
            print(f"LATENCY-MISMATCH: measured={report['measured_latency']} but "
                  f"spec {expr}={report['expected_latency']}")
        # ORGANIC #744 (R3-2 author-UX hint) — counting-origin disambiguation.
        # `measured` counts posedges AFTER the event-latch edge (that edge is
        # t=0). A spec phrasing the SAME timing INCLUSIVELY (counting the latch
        # edge itself) reads one higher, so an author who transcribed the
        # inclusive literal into --expect sees an off-by-one that LOOKS like an
        # RTL bug but is a counting-origin convention difference. Round-17: the
        # hint now names the deterministic resolution — `--latency-origin
        # inclusive` — so the author can DECLARE the convention instead of being
        # told only to re-check. (The default origin stays exclusive, so the hint
        # only ever fires when the author has NOT yet declared inclusive.)
        if report.get("latency_origin") != "inclusive":
            print("  hint (#744): `measured` counts posedges AFTER the "
                  "event-latch edge (that edge is t=0); a spec that counts "
                  "INCLUSIVELY expects measured+1. If your --expect is stated in "
                  "the inclusive convention (e.g. a 'WIDTH+2 = 1 cycle in + WIDTH "
                  "compute + 1 cycle out' spec), re-run with `--latency-origin "
                  "inclusive` to declare it — that is an EXACT comparison under "
                  "the declared origin, NOT a +-1 tolerance, so a real 1-cycle "
                  "latency bug still blocks. Otherwise treat this as a real RTL "
                  "off-by-one.")
    elif verdict == "PASS":
        print(f"latency-conformance ok: measured={report['measured_latency']} "
              f"== spec {expr}")
    # ORGANIC #740 (G3) — ADVISORY second-output inference note (never blocks).
    _sec = report.get("second_output")
    if _sec is not None:
        if _sec.get("inferred_latency") is not None:
            _line = (f"SECOND-OUTPUT-LATENCY (advisory): {_sec['reason']}")
            if "matches_spec" in _sec:
                _verb = "MATCHES" if _sec["matches_spec"] else "DIFFERS from"
                _line += (f"; inferred {_sec['inferred_latency']} {_verb} spec "
                          f"--expect-second={_sec['expected_latency']}")
            print(_line)
        else:
            print(f"SECOND-OUTPUT-LATENCY (advisory, not inferred): "
                  f"{_sec['reason']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
