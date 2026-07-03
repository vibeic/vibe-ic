#!/usr/bin/env python3
"""arith_oracle_tb_gen.py — deterministic CLOSED-FORM oracle TB generator for
arithmetic primitives (ORGANIC #745 [P2]).

The audited gap: an IC whose functional oracle is CLOSED-FORM
(``ic_class == digital_arithmetic_primitive``: ``p = x OP y`` truncated
``mod 2^N`` — a multiplier / adder / subtractor / bitwise / shift core)
shared ``verification_track='generic_full_stack'`` with no-oracle CPU/SoC
classes. With prose-only L10 vectors, ``oracle_tb_gen.py`` exits 2 (it only
REPLAYS enumerated golden vectors, it never COMPUTES a golden from a
recognised operator) → the run fell into the #654 connectivity-only cap
(``functional_verified=false``, ``capability_gap='cap:cpu_functional_oracle'``).
#654 is correct for a genuinely-no-oracle core, but an arithmetic primitive's
golden is a ONE-LINE Python computation — that over-broad deferral left the
EASIEST-oracle class with zero in-pipeline functional verification.

WHAT THIS DOES (chip-AGNOSTIC, Bucket A):
  * Recognise the closed-form operator + bit-width ``N`` + signedness from
    the design's own L2/declaration/L9 docs (the operator TOKEN, never a
    design SKU).
  * In a PURE Python function (testable WITHOUT iverilog) ENUMERATE corner
    operand pairs + a handful of deterministic pseudo-random pairs and
    COMPUTE the golden per recognised operator (``* + - & | ^ << >>``) with
    ``mod 2^N`` truncation + signedness.
  * Emit a self-checking Verilog TB that drives the operands at the resolved
    NUMERIC width (folding FACET-2 #643 — operand ports get a concrete
    ``[N-1:0]`` declaration, never a phantom 1-bit), waits, compares the DUT
    output ``===`` the computed golden, and prints the ``ORACLE_TB_DONE
    pass=<n>/<m>`` marker the runner greps (SAME marker contract as
    ``oracle_tb_gen``, so ``_run_oracle_tb`` consumes it unchanged).

§4.05 FAIL-CLOSED — this generator ONLY produces a TB when the oracle is
genuinely closed-form-derivable:
  * a NO-ORACLE class (``processor_cpu`` / ``crypto_accelerator`` / ``unknown``
    / anything but the arithmetic-primitive family) → DEFER (the #654
    connectivity cap stands; we never fabricate a golden we cannot derive).
  * an UNRECOGNISED operator → DEFER (don't guess).
  * a SERIAL / streaming datapath whose operand OR result is delivered
    bit-serially (the spm bit-serial multiplier: ``x`` parallel-N, ``y``/``p``
    1-bit serial) where the OUTPUT LATENCY + bit-order are Plugin-chosen and
    NOT closed-form-derivable from the spec → DEFER. The closed-form PARALLEL
    oracle fires ONLY when every operand input AND the result output resolve
    to the FULL numeric width ``N`` (an unambiguous parallel ``c = a OP b``).

Exit codes (CLI): 0 = TB emitted; 2 = deferred (a JSON ``verdict:DEFER``
direction is printed — the caller keeps the #654 cap); 1 = error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

# ── the arithmetic-primitive class family (registry name + synonyms) ──────────
_ARITH_CLASSES = {
    "digital_arithmetic_primitive",
    "digital_datapath",
    "arithmetic_primitive",
    "pure_datapath",
}

_CLK_NAMES = {"clk", "clock", "clk_i", "i_clk", "sysclk"}
_RST_NAMES = {"rst", "reset", "rst_n", "reset_n", "rstn", "i_rst",
              "rst_ni", "arst_n"}

# ORGANIC-20260703 — a start/valid/enable HANDSHAKE input or a control/STATUS
# output marks a SEQUENTIAL / protocol-driven datapath for which the closed-form
# combinational oracle is unsound. chip-AGNOSTIC: pure handshake vocabulary.
_HANDSHAKE_NAMES = {"start", "valid", "valid_in", "valid_i", "i_valid",
                    "in_valid", "din_valid", "en", "enable", "ena", "ready",
                    "req", "load", "go", "kick", "strobe"}
_STATUS_OUT_NAMES = {"valid_out", "valid_o", "o_valid", "out_valid", "done",
                     "busy", "ready", "finish", "finished", "ack", "req_out"}

# ── recognised CLOSED-FORM operators ─────────────────────────────────────────
# Each entry: token → (python golden, verilog op symbol). The python golden is
# the UNTRUNCATED integer result; truncation + signedness are applied uniformly
# by compute_golden() so the rule is the same for every operator.
_OPERATORS: Dict[str, Tuple[Any, str]] = {
    "*":  (lambda a, b: a * b,   "*"),
    "+":  (lambda a, b: a + b,   "+"),
    "-":  (lambda a, b: a - b,   "-"),
    "&":  (lambda a, b: a & b,   "&"),
    "|":  (lambda a, b: a | b,   "|"),
    "^":  (lambda a, b: a ^ b,   "^"),
    "<<": (lambda a, b: a << b,  "<<"),
    ">>": (lambda a, b: a >> b,  ">>"),
}

# Natural-language / algorithm-token → canonical operator. Keyed on GENERIC
# arithmetic vocabulary (no chip SKU); the explicit `p = x * y` symbol in the
# spec always wins over these when present.
_WORD_OPERATOR = [
    (re.compile(r"\bmultipl|\bproduct\b|\bmultiplier\b|\bmac\b", re.I), "*"),
    (re.compile(r"\bsubtract|\bdifference\b|\bsubtractor\b", re.I), "-"),
    (re.compile(r"\baddition\b|\badder\b|\bsum\b|\baccumulat", re.I), "+"),
    (re.compile(r"\bxor\b|\bexclusive[ -]or\b", re.I), "^"),
    (re.compile(r"\bbitwise and\b|\bAND gate\b", re.I), "&"),
    (re.compile(r"\bbitwise or\b|\bOR gate\b", re.I), "|"),
    (re.compile(r"\bleft shift\b|\bshift left\b", re.I), "<<"),
    (re.compile(r"\bright shift\b|\bshift right\b", re.I), ">>"),
]


# ── pure golden compute (testable WITHOUT iverilog) ──────────────────────────
def compute_golden(operator: str, a: int, b: int, width: int,
                   signed: bool) -> int:
    """Closed-form golden for ``a OP b`` truncated to ``width`` bits.

    Returns the *bit-pattern* value as an UNSIGNED ``width``-bit integer (the
    value the DUT's output net carries), so the emitted Verilog ``===`` compare
    matches directly. ``mod 2^width`` truncation is applied to every operator;
    signedness only changes how the INPUT operands are interpreted, never the
    output bit pattern (two's-complement arithmetic is bit-identical mod 2^N).
    PURE — no I/O, no globals; this is the single source of truth the emitted
    TB encodes and the unit test pins.
    """
    if operator not in _OPERATORS:
        raise ValueError(f"unrecognised operator {operator!r}")
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")
    mask = (1 << width) - 1
    fn = _OPERATORS[operator][0]
    raw = fn(int(a), int(b))
    return raw & mask


def _signed_range(width: int) -> Tuple[int, int]:
    return (-(1 << (width - 1)), (1 << (width - 1)) - 1)


def _unsigned_range(width: int) -> Tuple[int, int]:
    return (0, (1 << width) - 1)


def enumerate_operand_pairs(width: int, signed: bool,
                            operator: str = "*") -> List[Tuple[int, int]]:
    """Deterministic corner + a few pseudo-random operand pairs.

    Corner cases cover 0, 1, all-ones / MAX, MIN (signed), -1, and a couple of
    mid-range values; the pseudo-random pairs are a fixed LCG sequence (NO
    ``random`` import → fully reproducible). Values are returned as the LOGICAL
    operands (signed ints when ``signed``); the emitter converts each to the
    width-bit two's-complement bit pattern when driving the DUT. PURE.
    """
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")
    if signed:
        lo, hi = _signed_range(width)
    else:
        lo, hi = _unsigned_range(width)
    corners = {0, 1, hi, lo}
    if signed:
        corners.update({-1, hi, lo})
    if width >= 2:
        corners.add(hi // 2)
        corners.add(lo // 2 if signed else hi // 3)
    cvals = sorted(corners)
    pairs: List[Tuple[int, int]] = []
    seen = set()
    # For a shift operator the RHS is a shift AMOUNT and MUST be in [0, width)
    # for BOTH the corner cross-product AND the random tail — a negative corner
    # operand (e.g. -1 / MIN when signed) as a shift count would crash Python's
    # `<<`/`>>` (adversarial-review MEDIUM-1). Clamp here too, not only in the tail.
    def _clamp_rhs(bv: int) -> int:
        if operator in ("<<", ">>"):
            return abs(bv) % width if width > 0 else 0
        return bv
    for a in cvals:
        for b in cvals:
            key = (a, _clamp_rhs(b))
            if key not in seen:
                seen.add(key)
                pairs.append(key)
    # Cap the corner cross-product so the TB stays compact, then add a fixed
    # pseudo-random tail (LCG, deterministic). For shift operators the RHS is
    # bounded to [0, width) so the shift amount is meaningful.
    pairs = pairs[:16]
    span = hi - lo + 1
    state = 0x12345 & 0xFFFFFFFF
    for _ in range(6):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        a = lo + (state % span)
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        b = lo + (state % span)
        if operator in ("<<", ">>"):
            b = abs(b) % width if width > 0 else 0
        if (a, b) not in seen:
            seen.add((a, b))
            pairs.append((a, b))
    return pairs


# ── doc-driven spec extraction (operator / width / signedness / ports) ───────
def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(errors="replace"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _doc_text(project: Path) -> str:
    """Concatenate the closed-form-bearing L docs (L1/L2 FRS + input_doc) into
    one searchable blob — generic arithmetic vocabulary only."""
    blob: List[str] = []
    gd = _pl.generated_docs_dir(project)
    for cand in ("L2_FRS.json", "L1_DATASHEET.json", "L2.json"):
        d = _read_json(gd / cand)
        if d:
            blob.append(json.dumps(d, ensure_ascii=False))
    idoc = project / "phase1" / "input_doc"
    if idoc.is_dir():
        for f in sorted(idoc.glob("L*.txt")):
            try:
                blob.append(f.read_text(errors="replace"))
            except OSError:
                pass
    return "\n".join(blob)


# `p = x * y`, `c = a + b`, `result = op1 OP op2`, also unicode `×` for `*`.
_EXPR_RE = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*\(?\s*([A-Za-z_]\w*)\s*"
    r"(\*|×|\+|-|&|\||\^|<<|>>)\s*([A-Za-z_]\w*)",
    re.UNICODE)


def _extract_operator(text: str) -> Optional[Tuple[str, str, str, str]]:
    """Return (result_name, lhs_name, operator, rhs_name) from an explicit
    closed-form expression, else fall back to an arithmetic word-token. Returns
    None when no recognised operator is present (→ DEFER)."""
    for m in _EXPR_RE.finditer(text):
        res, lhs, op, rhs = m.group(1), m.group(2), m.group(3), m.group(4)
        op = "*" if op == "×" else op
        # distinct operand names so the corner-pair driver binds two real ports
        if op in _OPERATORS and lhs != rhs:
            return (res, lhs, op, rhs)
    for rx, op in _WORD_OPERATOR:
        if rx.search(text):
            # word-token: operand/result names unknown — resolved from ports
            return (None, None, op, None)  # type: ignore[return-value]
    return None


def _resolve_width(project: Path, ports: List[dict]) -> int:
    """Resolve the NUMERIC datapath width N. Priority: declaration.json
    size/width param → the widest numeric port width → L2 default. Returns a
    concrete int >= 1 (folds FACET-2 #643: a parametric `size`/`width` is
    resolved to its numeric default so operand ports get a real [N-1:0])."""
    for cand in ("plugin_output/declaration.json", "declaration.json"):
        d = _read_json(project / cand)
        if d:
            for k in ("size_param", "size", "width", "data_width", "N",
                      "bit_width", "word_width"):
                v = d.get(k)
                if isinstance(v, int) and v >= 1:
                    return v
                if isinstance(v, str) and v.strip().isdigit():
                    return int(v)
    widest = 0
    any_parametric = False
    for p in ports:
        # a normalized port already carries the computed `numeric_width`; fall
        # back to re-parsing the raw decl (adversarial-review LOW-3: reading only
        # width_decl on a normalized port always missed and defaulted to 32).
        w = p.get("numeric_width") or _port_numeric_width(p)
        if w and w > widest:
            widest = w
        if p.get("is_parametric") if "is_parametric" in p else _port_is_parametric(p):
            any_parametric = True
    # REOPEN #745: do NOT collapse to a 1-bit width when the ONLY numeric ports
    # are 1-bit serial control/data lines (clk/rst/y/p) while a real data bus is
    # PARAMETRIC. Returning 1 there silently disarmed the SERIAL-DEFER guard and
    # shipped a vacuous N=1 oracle as PASS for a 32-bit serial-parallel
    # multiplier. When the widest CONCRETE numeric width is 1 but a parametric
    # bus is present, the true datapath width is the parameter's value (not 1) —
    # return the conventional parametric datapath default so the mixed-topology
    # SERIAL-DEFER check fires (it judges parametric-vs-1-bit, not the number).
    if widest <= 1 and any_parametric:
        return 32  # parametric datapath default — keeps width != 1 for the guard
    if widest >= 1:
        return widest
    return 32  # conventional datapath default; only used if nothing numeric


def _port_numeric_width(p: dict) -> Optional[int]:
    """A CONSTANT numeric width for a port (None if parametric/unknown)."""
    wd = p.get("width_decl")
    if isinstance(wd, str):
        m = re.match(r"^\[\s*(\d+)\s*:\s*(\d+)\s*\]$", wd.strip())
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
    msb, lsb = p.get("msb"), p.get("lsb")
    if isinstance(msb, int) and isinstance(lsb, int):
        return abs(msb - lsb) + 1
    w = p.get("width")
    if isinstance(w, int) and w >= 1:
        return w
    if isinstance(w, str) and w.strip().isdigit():
        return int(w.strip())
    return None


# A symbol/expression token marking a PARAMETRIC width — any letter or `*`/`+`
# arithmetic in a width/span field that is NOT a plain literal number. Generic
# HDL/parameter vocabulary — no chip SKU. The signature is "a bus span that is a
# symbol or an expression of one" (e.g. `size`, `size-1`, `N-1:0`, `WIDTH-bit`,
# `2*WIDTH-1`), never any specific design's name.
_PARAM_WIDTH_RE = re.compile(r"[A-Za-z_]", re.I)


def _port_is_parametric(p: dict) -> bool:
    """True when the port's declared width is PARAMETRIC (a parameter symbol or
    an expression of one) and therefore has NO closed-form numeric width here.

    The production spec-to-rtl runner emits parametric data buses with a
    symbolic width string (e.g. ``'N-bit([size-1:0], parameter size 預設 32)'``,
    ``width_symbolic='size-1:0'``, or ``width='size'`` with ``msb='size-1'``)
    and NO numeric msb/lsb — so ``_port_numeric_width`` returns None for them. We
    must DISTINGUISH that 'parametric multi-bit bus' from a genuine literal 1-bit
    serial port, or the SERIAL-DEFER guard collapses (REOPEN #745: a 32-bit
    serial-parallel multiplier shipping a vacuous N=1 oracle as PASS).

    Signature (chip-AGNOSTIC): the port has no concrete numeric width, but one of
    its width/span fields is a SYMBOLIC string (contains a parameter name /
    arithmetic expression rather than a bare integer)."""
    if _port_numeric_width(p) is not None:
        return False
    for k in ("width", "width_decl", "width_symbolic", "msb", "lsb"):
        v = p.get(k)
        # a symbolic (non-numeric) string in a width/span field → parametric;
        # a bare 1-bit literal port has width==1 (numeric) and is NOT parametric.
        if isinstance(v, str) and v.strip() and not v.strip().isdigit() \
                and _PARAM_WIDTH_RE.search(v):
            return True
    return False


def _load_top_ports(project: Path) -> Tuple[Optional[str], List[dict]]:
    """(top, ports) from L9; reuses oracle_tb_gen's normalisation contract."""
    for cand in ("L9_INTEGRATION_SPEC.json", "L9.json"):
        p = _pl.generated_docs_dir(project) / cand
        d = _read_json(p)
        if not d:
            continue
        fields = d.get("fields", d)
        ports = fields.get("top_ports") or d.get("top_ports") or []
        top = (fields.get("top_module") or d.get("top_module") or "chip_top")
        norm = []
        for q in ports:
            if not isinstance(q, dict) or not q.get("name"):
                continue
            direction = str(q.get("dir") or q.get("direction")
                            or q.get("mode") or "").lower()
            norm.append({
                "name": q["name"],
                "dir": "output" if direction.startswith("o") else "input",
                "raw": q,
                "numeric_width": _port_numeric_width(q),
                "is_parametric": _port_is_parametric(q),
            })
        if norm:
            return top, norm
    return None, []


def extract_arith_spec(project: Path,
                       ic_class: Optional[str]) -> Tuple[Optional[dict], str]:
    """Resolve {operator, width, signed, operands, result_port, top}, or
    (None, reason) to DEFER.

    DEFER (§4.05 fail-closed) when: not the arithmetic-primitive family; no
    recognised closed-form operator; no usable top ports; OR the datapath is
    SERIAL (operand/result delivered bit-serially with Plugin-chosen latency —
    not closed-form-derivable). Only a fully PARALLEL ``c = a OP b`` with every
    operand input + result output at the resolved numeric width N is accepted.
    """
    if ic_class not in _ARITH_CLASSES:
        return None, (f"ic_class {ic_class!r} is not an arithmetic-primitive "
                      f"family class — no closed-form oracle (defer to #654)")
    top, ports = _load_top_ports(project)
    if not top or not ports:
        return None, "no usable L9 top ports — cannot bind operands"

    text = _doc_text(project)
    found = _extract_operator(text)
    if not found:
        return None, ("no recognised closed-form operator (* + - & | ^ << >>) "
                      "found in L1/L2 — defer (don't guess)")
    res_name, lhs_name, operator, rhs_name = found

    width = _resolve_width(project, ports)
    text_l = text.lower()
    signed = bool(re.search(r"\bsigned\b|2'?s? ?complement|signed_2c", text_l)) \
        and not re.search(r"\bunsigned\b|\"unsigned\"", text_l)
    # declaration.json integer_encoding wins when present.
    for cand in ("plugin_output/declaration.json", "declaration.json"):
        d = _read_json(project / cand)
        if d and isinstance(d.get("integer_encoding"), str):
            enc = d["integer_encoding"].lower()
            signed = "signed" in enc and "unsigned" not in enc
            break

    # §4.05 (adversarial-review): the emitted TB drives operands into UNSIGNED
    # reg nets and uses Verilog's plain `>>`/`<<` (LOGICAL shift). For a SIGNED
    # shift primitive the intended semantics may be ARITHMETIC (sign-extending,
    # `>>>`), which is NOT reliably derivable from the prose and would make a
    # logical-shift golden FALSE-FAIL a correct arithmetic-shift DUT. So DEFER on
    # a signed shift rather than ship a possibly-wrong oracle (unsigned shifts
    # are unambiguous and kept). Non-shift signed ops (+ - * & | ^) are
    # bit-identical mod 2^N and stay.
    if operator in ("<<", ">>") and signed:
        return None, ("signed shift operator: logical-vs-arithmetic shift "
                      "semantics are not closed-form-derivable from the spec — "
                      "defer to #654 rather than ship a possibly-wrong oracle")

    inputs = [p for p in ports if p["dir"] == "input"
              and p["name"].lower() not in (_CLK_NAMES | _RST_NAMES)]
    outputs = [p for p in ports if p["dir"] == "output"]
    if len(inputs) < 2 or len(outputs) < 1:
        return None, (f"need >=2 data inputs + 1 output for a binary "
                      f"closed-form op; got {len(inputs)} in / {len(outputs)} "
                      f"out — defer")

    # Prefer the spec-named operands/result; else take the two widest inputs
    # and the result output by name match or widest output.
    def _by_name(name, pool):
        return next((p for p in pool if p["name"] == name), None)

    # Rank candidate operands so a PARAMETRIC bus (numeric_width None but a real
    # multi-bit datapath) outranks a literal 1-bit serial line — otherwise the
    # `numeric_width or 1` key would pick the 1-bit serial port as an "operand".
    def _rank_key(p):
        return (1 if p.get("is_parametric") else 0, p.get("numeric_width") or 0)

    op_a = _by_name(lhs_name, inputs) if lhs_name else None
    op_b = _by_name(rhs_name, inputs) if rhs_name else None
    if op_a is None or op_b is None:
        ranked = sorted(inputs, key=_rank_key, reverse=True)
        op_a, op_b = ranked[0], ranked[1]
    result = _by_name(res_name, outputs) if res_name else None
    if result is None:
        result = max(outputs, key=_rank_key)

    # SERIAL-shape DEFER (§4.05) — REOPEN #745 HARDENED: the closed-form PARALLEL
    # oracle requires every operand input AND the result to be a FULL-WIDTH
    # PARALLEL bus of the SAME datapath. A bit-serial operand/result (spm:
    # parallel x, serial y/p — y and p are delivered one bit per cycle) needs the
    # Plugin-chosen output latency + bit-order to sample — NOT closed-form-
    # derivable from the spec, so defer to #654 honestly.
    #
    # The guard is now decided by TOPOLOGY MIX, NOT by the resolved `width`:
    #   * a port is "literal 1-bit" when its numeric_width == 1 (a real serial
    #     line: clk/rst-shaped or a 1-bit y/p),
    #   * a port is "wide" when numeric_width > 1 OR it is parametric (a true
    #     multi-bit data bus whose span is a parameter).
    # If ANY of {operand_a, operand_b, result} is literal-1-bit while ANOTHER is
    # wide/parametric, the datapath is serial-parallel → DEFER. (Crucially this
    # no longer hangs on `width > 1`: the round-13 collapse-to-N=1 made `width`
    # untrustworthy, so the topology mix is judged from the ports directly.)
    def _is_literal_1bit(p):
        # ORGANIC #745 r2 (Step-2.7): a port is serial when its numeric width is
        # 1 OR its width PROSE marks it serial — `_port_numeric_width` maps every
        # natural spelling of a serial line ('serial'/'bit-serial'/'1-bit serial')
        # to None, so a numeric-only test let a prose-serial operand escape the
        # guard and ship a vacuous N=1 oracle. A `[0:0]` range also reads serial.
        if p.get("numeric_width") == 1:
            return True
        wraw = str((p.get("raw") or {}).get("width")
                   or (p.get("raw") or {}).get("width_symbolic") or "").lower()
        return bool(re.search(r"\bserial\b|bit[- ]?serial|\[\s*0\s*:\s*0\s*\]",
                              wraw))
    def _is_wide(p):
        nw = p.get("numeric_width")
        return (isinstance(nw, int) and nw > 1) or bool(p.get("is_parametric"))

    roles = ((op_a, "operand_a"), (op_b, "operand_b"), (result, "result"))
    has_1bit = any(_is_literal_1bit(p) for p, _ in roles)
    has_wide = any(_is_wide(p) for p, _ in roles)
    # ORGANIC #745 r2 (Step-2.7) — FULLY-SERIAL COLLAPSE: a multiplier whose spec
    # declares an N>1-bit datapath (a parametric/N-bit operator expression) yet
    # ALL operand+result ports resolve to 1-bit serial is NOT a closed-form
    # parallel oracle either — emitting a 1-bit oracle there is the same vacuous
    # false-PASS. DEFER when every data role is 1-bit/serial but the spec datapath
    # is wider than 1.
    all_serial = all(_is_literal_1bit(p) for p, _ in roles)
    spec_width_gt1 = bool(
        re.search(r"\bmod\s*2\s*\^\s*[a-zA-Z]", text)        # p = x*y mod 2^N
        or re.search(r"\b(\d{2,})\s*[- ]?bit\b", text_l)     # "32-bit"
        or re.search(r"\bparameter\b[^\n]*\b(width|size|n)\b", text_l))
    if all_serial and spec_width_gt1:
        return None, (
            "fully bit-serial datapath: the spec declares an N>1-bit "
            "multiplier but every operand/result port is 1-bit/serial — the "
            "bit-serial latency + order are Plugin-chosen, not closed-form-"
            "derivable; defer to #654 rather than ship a vacuous N=1 oracle")
    if has_1bit and has_wide:
        bad = next((r for p, r in roles if _is_literal_1bit(p)), "port")
        return None, (
            f"SERIAL/streaming datapath: {bad} is a literal 1-bit serial port "
            f"while another operand/result is a wide/parametric bus — bit-serial "
            f"delivery with Plugin-chosen latency/bit-order is NOT closed-form-"
            f"derivable; defer to #654 (testbench-author)")

    # ORGANIC-20260703 — SEQUENTIAL / HANDSHAKE / STATUS-OUTPUT DEFER. The oracle
    # emitted here is COMBINATIONAL: it drives operands and compares
    # `result == a OP b` with NO clock driven and no start/valid asserted. That is
    # sound ONLY for a purely-combinational arithmetic primitive (a single data
    # output that is a pure function of the data inputs). A design with a CLOCK
    # input (registered / pipelined / FSM datapath), a start/valid/enable
    # HANDSHAKE, or a control/STATUS output (valid_out/done/busy/…) needs a
    # latency- and protocol-aware oracle — the combinational golden would
    # false-FAIL a correct sequential DUT (measured misfires: dot_product FSM,
    # modified_booth_mul, cont_adder). DEFER (the runner then WAIVEs reference_tb)
    # rather than ship a bogus oracle. Runs AFTER the serial guards so a serial
    # datapath keeps its more-specific reason. chip-AGNOSTIC: clock/handshake/
    # status port-name grammar.
    _names_lc = {str(p.get("name", "")).lower() for p in ports}
    if _names_lc & _CLK_NAMES:
        return None, (
            "sequential/clocked datapath (a clock input is present): the "
            "closed-form COMBINATIONAL oracle drives no clock and asserts no "
            "start/valid, so it cannot soundly check a registered/pipelined/FSM "
            "arithmetic datapath — defer (WAIVE reference_tb) to #654")
    if _names_lc & _HANDSHAKE_NAMES:
        return None, (
            "handshake-driven datapath (a start/valid/enable input is present): "
            "the closed-form combinational oracle asserts no handshake, so it "
            "cannot drive this protocol — defer (WAIVE reference_tb) to #654")
    _status_outs = sorted(
        str(p.get("name")) for p in ports
        if p.get("dir") == "output"
        and str(p.get("name", "")).lower() in _STATUS_OUT_NAMES)
    if _status_outs:
        return None, (
            f"control/status output(s) present ({', '.join(_status_outs)}): a "
            f"closed-form combinational oracle checks only the single data "
            f"result and cannot model a status/handshake output — defer to #654")

    # Per-port resolved widths (folds FACET-2 #643): a parametric port whose
    # numeric width is unknown is bound to the datapath width N so the operand
    # gets a real [N-1:0] declaration rather than a phantom 1-bit. The GOLDEN
    # truncation width is the RESULT port's physical width — that is the bit
    # pattern the DUT output actually carries (e.g. a 16-bit product net for an
    # 8x8 multiplier), so the `===` compare is exact.
    op_a_w = op_a.get("numeric_width") or width
    op_b_w = op_b.get("numeric_width") or width
    result_w = result.get("numeric_width") or width

    spec = {
        "top": top,
        "operator": operator,
        "width": width,
        "signed": signed,
        "operand_a": op_a["name"],
        "operand_b": op_b["name"],
        "result": result["name"],
        "operand_a_width": op_a_w,
        "operand_b_width": op_b_w,
        "result_width": result_w,
        "ports": ports,
    }
    return spec, "closed-form parallel arithmetic oracle"


# ── Verilog TB emit ──────────────────────────────────────────────────────────
def _twos(val: int, width: int) -> int:
    """Logical int → unsigned width-bit two's-complement bit pattern."""
    return val & ((1 << width) - 1)


def _emit_tb(spec: dict) -> str:
    top = spec["top"]
    operator = spec["operator"]
    width = spec["width"]
    signed = spec["signed"]
    a_name, b_name, r_name = (spec["operand_a"], spec["operand_b"],
                              spec["result"])
    a_w = spec.get("operand_a_width") or width
    b_w = spec.get("operand_b_width") or width
    r_w = spec.get("result_width") or width
    ports = spec["ports"]

    clk = next((p["name"] for p in ports
                if p["dir"] == "input" and p["name"].lower() in _CLK_NAMES),
               None)
    rst = next((p["name"] for p in ports
                if p["dir"] == "input" and p["name"].lower() in _RST_NAMES),
               None)
    rst_active_low = bool(rst) and rst.lower().rstrip("i").endswith("n")

    # Enumerate operand pairs over operand_a's width (the corner space); each
    # operand is two's-complement-truncated to ITS OWN port width when driven.
    pairs = enumerate_operand_pairs(a_w, signed, operator)
    role_w = {a_name: a_w, b_name: b_w, r_name: r_w}

    def _rng(w):
        return f" [{w - 1}:0]" if w > 1 else ""

    lines = ["`timescale 1ns/1ps",
             "// Auto-generated by arith_oracle_tb_gen (#745) — CLOSED-FORM "
             "arithmetic oracle TB",
             f"// operator '{operator}'  N={width}  "
             f"signed={str(signed).lower()}  operands [{a_w-1}:0]/[{b_w-1}:0] "
             f"result [{r_w-1}:0]  (FACET-2 #643: numeric-width operand decls)",
             f"module tb_{top}_oracle;"]
    # Port nets: operands + result at the resolved NUMERIC width (#643).
    for p in ports:
        nm = p["name"]
        decl = "reg" if p["dir"] == "input" else "wire"
        if nm in role_w:
            prng = _rng(role_w[nm])
        else:
            pw = p.get("numeric_width")
            prng = f" [{pw - 1}:0]" if isinstance(pw, int) and pw > 1 else ""
        lines.append(f"  {decl}{prng} {nm};")
    conns = ", ".join(f".{p['name']}({p['name']})" for p in ports)
    lines.append(f"  {top} dut ({conns});")
    if clk:
        lines.append(f"  initial {clk} = 1'b0;")
        lines.append(f"  always #5 {clk} = ~{clk};")
    lines.append(f"  reg{_rng(r_w)} _golden;")
    lines.append("  integer _pass; integer _total;")
    lines.append("  initial begin")
    lines.append("    _pass = 0; _total = 0;")
    # zero non-driven non-clk/rst inputs
    for p in ports:
        nm = p["name"]
        if p["dir"] == "input" and nm not in (a_name, b_name) \
                and nm != clk and nm != rst:
            lines.append(f"    {nm} = 0;")
    if rst:
        lines.append(f"    {rst} = 1'b{'0' if rst_active_low else '1'};")
        lines.append("    #20;")
        lines.append(f"    {rst} = 1'b{'1' if rst_active_low else '0'};")
        lines.append("    #20;")
    for idx, (a, b) in enumerate(pairs):
        au = _twos(a, a_w)
        bu = _twos(b, b_w)
        # The DUT output bit pattern is (a OP b) truncated to the RESULT port
        # width; signedness only re-interprets the operand inputs.
        golden = compute_golden(operator, a, b, r_w, signed)
        lines.append(f"    // vector {idx}: {a_name}={a} {operator} "
                     f"{b_name}={b} => golden={golden} (mod 2^{r_w})")
        lines.append(f"    {a_name} = {a_w}'d{au};")
        lines.append(f"    {b_name} = {b_w}'d{bu};")
        lines.append(f"    _golden = {r_w}'d{golden};")
        lines.append("    #20;")
        lines.append("    _total = _total + 1;")
        lines.append(f"    if ({r_name} === _golden) begin")
        lines.append("      _pass = _pass + 1;")
        lines.append(f"      $display(\"ORACLE_VECTOR vec{idx} PASS\");")
        lines.append("    end else begin")
        lines.append(f"      $display(\"ORACLE_VECTOR vec{idx} FAIL "
                     f"(expected %0d got %0d)\", _golden, {r_name});")
        lines.append("    end")
    lines.append("    $display(\"ORACLE_TB_DONE pass=%0d/%0d\", _pass, _total);")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def generate(project: Path,
             ic_class: Optional[str] = None) -> Tuple[dict, int]:
    """Returns (verdict_dict, exit_code). 0 = TB emitted; 2 = DEFER."""
    spec, reason = extract_arith_spec(project, ic_class)
    if spec is None:
        return ({
            "program": "arith_oracle_tb_gen",
            "verdict": "DEFER",
            "fallback_skill": "testbench-author",
            "reason": reason,
            "ic_class": ic_class,
            "capability_gap": "cap:cpu_functional_oracle",
        }, 2)

    tb_text = _emit_tb(spec)
    sim_dir = _pl.sim_full_stack_dir(project)
    sim_dir.mkdir(parents=True, exist_ok=True)
    tb_path = sim_dir / f"tb_{spec['top']}_oracle.v"
    tb_path.write_text(tb_text)
    n_vec = len(enumerate_operand_pairs(
        spec.get("operand_a_width") or spec["width"], spec["signed"],
        spec["operator"]))
    manifest = {
        "program": "arith_oracle_tb_gen",
        "verdict": "TB_EMITTED",
        "tb": str(tb_path.relative_to(project)),
        "top": spec["top"],
        "operator": spec["operator"],
        "width": spec["width"],
        "signed": spec["signed"],
        "operand_a": spec["operand_a"],
        "operand_b": spec["operand_b"],
        "result": spec["result"],
        "vector_count": n_vec,
        "source": "closed-form operator from L1/L2 + L9 top_ports (#745)",
    }
    (sim_dir / "arith_oracle_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--ic-class", default=None,
                    help="IC class (defaults to detect from project)")
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    ic_class = args.ic_class
    if ic_class is None:
        # Best-effort self-detect so the CLI is usable standalone.
        try:
            from ic_class_profile import detect_ic_class as _d  # type: ignore
            prof = _d(args.project.resolve())
            ic_class = (prof.get("ic_class")
                        if isinstance(prof, dict) else None)
        except Exception:
            ic_class = None
    rep, rc = generate(args.project.resolve(), ic_class)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
