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
)

# The timing-conformance family. Only `latency` is fully implemented; the
# others are reserved extensibility hooks (pulse-one-cycle-after,
# registered-vs-comb, handshake-phase) toward the same canonical-measurement
# discipline. `--mode latency` is the default and the only one wired today.
_MODES = ("latency",)

# Canonical free-running clock spellings (input clk auto-bind for the TB).
_CLK_NAMES = frozenset({"clk", "clock", "clk_i", "clock_i", "clk_in", "clk_in1"})

# Active-low reset spelling fragments (name-based auto-detect of polarity).
_ACTIVE_LOW_RST = ("rst_n", "rstn", "reset_n", "resetn", "arst_n", "arstn",
                   "nrst", "nreset", "n_rst", "n_reset", "rst_b", "resetb",
                   "reset_b", "rst_ni", "resetb_n")
_RST_NAME_HINT = ("rst", "reset")

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


def safe_eval_arith(expr: str, params: Dict[str, int]) -> int:
    """Evaluate a parameter arithmetic expression SAFELY.

    Permitted: integer literals, the parameter NAMEs in `params`, the binary
    operators ``+ - * //`` and unary ``+ -``, and parentheses. ANYTHING else
    (function calls, attribute access, names not in `params`, ``/`` true-div,
    ``**`` power, bit ops, …) RAISES ExpectError. Never executes arbitrary
    code — the AST is walked node-by-node against a strict whitelist.
    """
    if not expr or not expr.strip():
        raise ExpectError("empty --expect expression")
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


# ─── port classification ─────────────────────────────────────────────────────
def _is_clock(name: str) -> bool:
    return name.lower() in _CLK_NAMES


def _reset_is_active_low(name: str) -> bool:
    lo = name.lower()
    if lo in _ACTIVE_LOW_RST:
        return True
    # generic low-asserted suffix on a reset-named port
    if any(h in lo for h in _RST_NAME_HINT):
        return (lo.endswith("_n") or lo.endswith("n") or lo.endswith("_b")
                or lo.endswith("b") or lo.startswith("n"))
    return False


def _looks_like_reset(name: str) -> bool:
    lo = name.lower()
    return any(h in lo for h in _RST_NAME_HINT)


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


class PortInfo:
    __slots__ = ("name", "direction", "width_str")

    def __init__(self, name: str, direction: str, width_str: str):
        self.name = name
        self.direction = direction
        self.width_str = (width_str or "").strip()


def classify_ports(ports: List[Tuple[str, str, str]],
                   event_name: str, output_name: str,
                   reset_override: Optional[str]
                   ) -> Tuple[Optional[PortInfo], List[PortInfo],
                              Optional[PortInfo], Optional[PortInfo],
                              List[PortInfo]]:
    """Return (clk, resets, event_port, output_port, other_inputs).

    `ports` is the shared parser's [(dir, width, name), ...].
    """
    clk: Optional[PortInfo] = None
    resets: List[PortInfo] = []
    event_port: Optional[PortInfo] = None
    output_port: Optional[PortInfo] = None
    others: List[PortInfo] = []
    for direction, width, name in ports:
        pi = PortInfo(name, direction, width)
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
            is_rst = (reset_override is not None and name == reset_override) or \
                     (reset_override is None and _looks_like_reset(name))
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


def build_measurement_tb(top: str, clk: Optional[PortInfo],
                         resets: List[PortInfo], event_port: PortInfo,
                         output_port: PortInfo, others: List[PortInfo],
                         reset_active_low_map: Dict[str, bool],
                         input_const: int, max_cycles: int,
                         params: Optional[Dict[str, int]] = None,
                         reset_hold: int = 5) -> str:
    """Emit the self-contained canonical-latency measurement TB.

    Convention:
      reset asserted `reset_hold` cycles → deasserted → quiescent settle →
      `event` pulsed HIGH for EXACTLY ONE clock (one posedge latch edge) →
      from THAT latch edge, count posedges of clk until `output` first == 1.

    `params` (resolved module #(...) values + --param overrides) is forwarded
    to the DUT instance as `#(.NAME(VAL))` AND substituted into every TB net
    width so a parameterised design elaborates with no out-of-scope param.
    """
    params = params or {}
    L: List[str] = []
    L.append("`timescale 1ns/1ps")
    L.append("module latency_tb;")
    L.append("  reg clk = 0;")
    for r in resets:
        L.append(f"  reg{_decl_width(r, params)} {r.name};")
    L.append(f"  reg{_decl_width(event_port, params)} {event_port.name};")
    for o in others:
        L.append(f"  reg{_decl_width(o, params)} {o.name};")
    L.append(f"  wire{_decl_width(output_port, params)} {output_port.name};")
    L.append("  integer cyc;")
    L.append("  integer measured;")
    # DUT instance (named connections; only declared TB nets are wired). The
    # resolved params are passed through #(.NAME(VAL)) so the design's own
    # internal `WIDTH`-typed signals + the --expect resolution agree.
    inst_params = ""
    if params:
        inst_params = " #(" + ", ".join(
            f".{nm}({val})" for nm, val in sorted(params.items())) + ")"
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
        if input_const < 0:
            L.append(f"    {o.name} = {{{_width_token(o, params)}{{1'b1}}}};")
        else:
            L.append(f"    {o.name} = {input_const};")
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
    L.append(f"    if ({out} === 1'b1) begin")
    L.append('      $display("LATENCY_PRECONDITION_HIGH");')
    L.append("      $finish;")
    L.append("    end")
    # (2) COMBINATIONAL latency 0 — assert event HIGH in the SAME clk LOW phase
    #     (we are just after a negedge) and let purely-combinational logic
    #     settle WITHOUT crossing a posedge (a small in-phase delay). If `out`
    #     goes HIGH with no clock edge → measured = 0.
    L.append(f"    {ev} = 1'b1;")
    L.append("    #1;   // settle combinational paths, still inside the low phase")
    L.append(f"    if ({out} === 1'b1) begin")
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
    L.append(f"      {ev} <= 1'b0;            // one-edge event pulse")
    L.append(f"      for (cyc = 1; cyc <= {max_cycles}; cyc = cyc + 1) begin")
    L.append("        @(posedge clk);        // posedge E+cyc")
    L.append(f"        if ({out} === 1'b1) begin")
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


def measure_latency(rtl_path: Path, tb_text: str, workdir: Path
                    ) -> Tuple[Optional[int], str, str]:
    """Compile + run the measurement TB; return (measured, status, err).

    `status` is one of:
      * "ok"               — `measured` is the integer latency.
      * "timeout"          — output never asserted in the window.
      * "precondition_high"— `output` was already HIGH before the event (the
                             measurement is meaningless).
    `err` is non-empty only on a compile/run failure (status "" then).
    The caller has already confirmed iverilog/vvp are present.
    """
    tb_path = workdir / "latency_tb.sv"
    tb_path.write_text(tb_text)
    binp = workdir / "latency_sim.vvp"
    rc, out, err = _run(["iverilog", "-g2012", "-o", str(binp),
                         "-s", "latency_tb", str(rtl_path), str(tb_path)])
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

    clk, resets, event_port, output_port, others = classify_ports(
        ports, event, output, reset_override)

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

    # resolve --expect against the module params (+ overrides)
    try:
        params = resolve_params(rtl_text, top, params_override)
        report["resolved_params"] = params
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

    # reset polarity map
    reset_active_low_map: Dict[str, bool] = {}
    for r in resets:
        if reset_active_low_flag is not None:
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
                              max_cycles, params=params)
    report["measurement_tb_lines"] = tb.count("\n")

    workdir = Path(tempfile.mkdtemp(prefix="latconf_"))
    try:
        measured, status, err = measure_latency(rtl_path, tb, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

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

    report["measured_latency"] = measured
    if measured != expected:
        report["verdict"] = "MISMATCH"
        report["reason"] = (f"measured latency {measured} != resolved spec "
                            f"{expect}={expected}")
        return 1, report

    report["verdict"] = "PASS"
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
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    rtl_path = Path(args.rtl)
    if not rtl_path.is_file():
        print(f"ERROR: --rtl not found: {rtl_path}", file=sys.stderr)
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
        mode=args.mode, allow_no_handshake=args.allow_no_handshake)

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
        print(f"LATENCY-MISMATCH: measured={report['measured_latency']} but "
              f"spec {expr}={report['expected_latency']}")
        # ORGANIC #744 (R3-2 author-UX hint) — counting-origin disambiguation.
        # `measured` counts posedges AFTER the event-latch edge (that edge is
        # t=0). A spec phrasing the SAME timing INCLUSIVELY (counting the latch
        # edge itself) reads one higher, so an author who transcribed the
        # inclusive literal into --expect sees an off-by-one that LOOKS like an
        # RTL bug but is a counting-origin convention difference.
        print("  hint (#744): `measured` counts posedges AFTER the event-latch "
              "edge (that edge is t=0); a spec that counts INCLUSIVELY expects "
              "measured+1 — re-check whether --expect uses the inclusive origin "
              "before treating this as an RTL off-by-one.")
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
