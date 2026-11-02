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
import ast
import json
import math
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


# A CLOCK OR RESET IS NEVER AN ARITHMETIC OPERAND, whatever it is called.
# The exact-name sets above are an ALLOW-LIST, and a design that names its
# clocks by domain — `wclk`/`rclk`, `clk_a`/`clk_b` — or its resets `wrstn`/
# `rrstn`/`arstn` walks straight past them. MEASURED 2026-09-06 on the RTLLM
# asyn_fifo: with `wclk` and `rclk` left in the operand pool and every port
# resolving to 1 bit (the data buses are parameter-wide, so no numeric width
# survives), the generator emitted a "closed-form" XOR oracle asserting
# `wfull == wclk ^ rclk` and FAILED 2 of its 4 vectors against an async FIFO
# that passes its own dataset testbench. A false rejection is as expensive as a
# false certificate: the design was sent to repair, the repair was inert, and
# the emitter's output was waived to AI backup.
# chip-AGNOSTIC: clock/reset vocabulary by SHAPE, no design or vendor literal.
#: the bare clock/reset words, matched against a name's own TOKENS rather than
#: as a substring, so `clocks_per_bit` stays an operand while `wclk` does not.
_CLK_RST_TOKENS = frozenset({"clk", "clock", "rst", "reset", "rstn", "resetn",
                             "nrst", "nreset"})
#: single-letter domain prefixes a design puts on a clock or reset it owns:
#: w/r (write/read), a/b (two clock domains), i/o, n (active low), s (sync).
_DOMAIN_PREFIXES = "wrabions"


def is_clock_or_reset_port(name: str) -> bool:
    """True when a port NAME reads as a clock or a reset in any spelling.

    Used to keep such ports out of the arithmetic operand pool. The exact-name
    sets are an allow-list and a design that names its clocks by domain walks
    straight past them, so this matches the name's own TOKENS -- and a token
    that is a clock/reset word behind one domain letter (`wclk`, `arstn`)
    counts. The bias is deliberate: excluding one extra port costs a DEFER,
    which is the honest outcome when the oracle cannot be built, while
    admitting a clock as an operand produces a confident wrong verdict about a
    correct design.
    """
    low = (name or "").strip().lower()
    if not low:
        return False
    if low in _CLK_NAMES or low in _RST_NAMES:
        return True
    for tok in re.split(r'[^a-z0-9]+', low):
        if not tok:
            continue
        if tok in _CLK_RST_TOKENS:
            return True
        if (len(tok) > 3 and tok[0] in _DOMAIN_PREFIXES
                and tok[1:] in _CLK_RST_TOKENS):
            return True
        if (len(tok) > 3 and tok[-1] == "n"
                and tok[:-1] in _CLK_RST_TOKENS):
            return True
        if (len(tok) > 4 and tok[0] in _DOMAIN_PREFIXES and tok[-1] == "n"
                and tok[1:-1] in _CLK_RST_TOKENS):
            return True
    return False

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


def _extract_operator(text: str) -> Optional[Tuple[str, str, str, str]]:
    """Parse one complete affirmative function record, never an executable prefix.

    The supported domain remains one binary operation over two named operands.
    Unknown residual prose and larger ASTs require the expert reference hook.
    """
    text = text.strip().rstrip('.;').strip().replace('×', '*')
    if '#' in text:
        return None  # ast.parse discards comments, including functional caveats
    # These are descriptions of the supported arithmetic shape, not arbitrary
    # suffixes. Anything else (including overflow policy) remains unconsumed.
    descriptor = (r'(?:(?:unsigned|signed|parallel|serial|serial-parallel|binary)\s+)*'
                  r'(?:multiplier|multiply|adder|subtractor|bitwise arithmetic|arithmetic datapath)')
    if re.fullmatch(descriptor, text, re.I):
        for rx, op in _WORD_OPERATOR:
            if rx.search(text) and op in ('*', '+'):
                return (None, None, op, None)
    descriptions = []
    introduction = re.match(
        r'^Implement\s+(?:an?\s+)?(?:\d+-bit\s+)?(' + descriptor + r')\.\s+', text, re.I)
    if introduction:
        descriptions.append(introduction[1])
        text = text[introduction.end():]
    prefix = re.match(r'^(' + descriptor + r')(?:\s*:\s*|\s+)(?=[A-Za-z_]\w*\s*=)', text, re.I)
    if prefix:
        descriptions.append(prefix[1])
        text = text[prefix.end():]
    suffix = re.search(r'(?:[,;]\s*|\s+)(?:a\s+)?(?:\d+-bit\s+)?(' + descriptor + r')$', text, re.I)
    if suffix:
        descriptions.append(suffix[1])
        text = text[:suffix.start()]
    gloss = r'(?:\w+-bit\s+)?(?:modulo\s+)?(?:arithmetic\s+)?(?:multiplication|addition|subtraction)'
    suffix = re.search(r'\s*\(\s*(' + descriptor + '|' + gloss + r')\s*\)$', text, re.I)
    if suffix:
        descriptions.append(suffix[1])
        text = text[:suffix.start()]
    text = re.sub(r'\s+mod\s+2\s*\^\s*(?:\d+|[A-Za-z_]\w*)$', '', text)
    def compatible(description, op):
        if description.lower().endswith('bitwise arithmetic'):
            return op in ('&', '|', '^')
        if description.lower().endswith('arithmetic datapath'):
            return op in _OPERATORS
        return any(rx.search(description) and declared == op
                   for rx, declared in _WORD_OPERATOR)
    try:
        tree = ast.parse(text, mode='exec')
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None and len(tree.body) == 1:
        stmt = tree.body[0]
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.BinOp)
                and isinstance(stmt.value.left, ast.Name)
                and isinstance(stmt.value.right, ast.Name)):
            operators = {ast.Mult: '*', ast.Add: '+', ast.Sub: '-',
                         ast.BitAnd: '&', ast.BitOr: '|', ast.BitXor: '^',
                         ast.LShift: '<<', ast.RShift: '>>'}
            op = operators.get(type(stmt.value.op))
            if any(not compatible(desc, op) for desc in descriptions):
                return None
            if op and stmt.value.left.id != stmt.value.right.id:
                return (stmt.targets[0].id, stmt.value.left.id, op,
                        stmt.value.right.id)
    prose = re.fullmatch(
        r'(?:The\s+)?([A-Za-z_]\w*)\s+is\s+the\s+'
        r'(sum|product|difference|bitwise XOR|bitwise AND|bitwise OR)\s+of\s+'
        r'([A-Za-z_]\w*)\s+and\s+([A-Za-z_]\w*)', text, re.I)
    if prose and prose[3] != prose[4]:
        op = {'sum': '+', 'product': '*', 'difference': '-',
              'bitwise xor': '^', 'bitwise and': '&', 'bitwise or': '|'}[prose[2].lower()]
        if any(not compatible(desc, op) for desc in descriptions):
            return None
        return prose[1], prose[3], op, prose[4]
    return None


_FUNCTION_TITLES = frozenset({
    'function', 'functionality', 'functional description',
    'functional requirements', 'functional specification',
    'functional requirements specification', 'frs', 'l2_frs', 'l2 frs',
    'arithmetic function', 'arithmetic datapath',
    '功能', '功能定義', '功能定义', '功能描述', '功能需求', '功能規格', '功能规格',
})
_PROHIBITING_PROSE = (r"do not|don't|must not|not implement|forbidden|prohibit|disallow|negative|example"
                      r"|禁止|不得|不可|不要|不准|反例|範例|范例")
_ARITHMETIC_QUALIFIER = re.compile(
    r"saturat|clamp|overflow|underflow|\brounding\b|飽和|饱和|溢位|溢出|四捨五入", re.I)
_QUALIFYING_PROSE = re.compile(_PROHIBITING_PROSE + '|' + _ARITHMETIC_QUALIFIER.pattern, re.I)


def _title(record: dict) -> Optional[str]:
    title = record.get('title', '')
    return title.strip().rstrip(':').strip().casefold() if isinstance(title, str) else None


def _names_function(title: Optional[str]) -> bool:
    """A title names the function role only as a whole, gloss included.

    Every other title has another role, so ``Function (not applicable)`` does
    not name the function while ``功能定義 (Functional Specification)`` does.
    """
    if title is None:
        return False
    gloss = re.fullmatch(r'(.+?)\s*\((.+)\)', title)
    return all(part in _FUNCTION_TITLES for part in (gloss.groups() if gloss else (title,)))


def _affirmative_function_context(record: dict) -> bool:
    """A document wrapper may be untitled, name the function, or be an overview."""
    title = _title(record)
    return title in ('', 'overview') or _names_function(title)


_FUNCTION_RECORD_KEYS = frozenset({'title', 'content', 'section', 'evidence', 'heading_shape'})
_FUNCTION_WRAPPER_KEYS = frozenset({'title', 'function', 'content', 'fields'})


def _affirmative_function_record(row: dict) -> bool:
    """Is this record's structured role the function, with nothing qualifying it?

    Any other key can qualify a record as much as its title can.  ``section`` is
    the Phase-1 heading position (h2, 1.1, unheaded), never prose.
    """
    section = row.get('section', 'unheaded')
    return (row.keys() <= _FUNCTION_RECORD_KEYS
            and (_title(row) == '' or _names_function(_title(row)))
            and isinstance(section, str)
            and re.fullmatch(r'h\d+|unheaded|\d+(?:\.\d+)*', section) is not None)


def _fenced_function(content: str) -> str:
    """Phase 1 keeps a function as one fenced expression inside its own prose.

    The expression stands alone only when the prose around it is a lead-in, a
    note, or a definition of an operand, and qualifies nothing.  Otherwise the
    whole content goes to the complete-record parser, which refuses it.
    """
    fences = list(re.finditer(r'^```[^\n]*\n(.*?)^```[ \t]*$', content, re.M | re.S))
    lines = [line for line in fences[0][1].splitlines() if line.strip()] if len(fences) == 1 else []
    found = _extract_operator(lines[0]) if len(lines) == 1 else None
    if not found:
        return content
    prose = (content[:fences[0].start()] + content[fences[0].end():]).splitlines()
    operands = '|'.join(re.escape(name) for name in found if name and name.isidentifier())
    bullet = r'[-*]\s+[*`]*(?:' + operands + r')\b'
    closed = all(not line.strip() or line.rstrip().endswith((':', '：')) or line.startswith('>')
                 or (operands and re.match(bullet, line)) for line in prose)
    return lines[0] if closed and not _QUALIFYING_PROSE.search('\n'.join(prose)) else content


def _function_records(project: Path) -> List[str]:
    """Read affirmative function records, retaining their title's authority.

    An existing L2 is authoritative; incidental L1 descriptions or copied raw
    input must not override it. Do not concatenate separate records into code.
    """
    gd = _pl.generated_docs_dir(project)
    for name in ('L2_FRS.json', 'L2.json'):
        doc = _read_json(gd / name)
        if doc is not None:
            fields = doc.get('fields', doc)
            if (not isinstance(fields, dict) or not _affirmative_function_context(doc)
                    or not _affirmative_function_context(fields)):
                return []
            rows = fields.get('frs_sections') or []
            for key in ('function', 'content'):
                if not rows and isinstance(fields.get(key), str):
                    closed = doc.keys() <= _FUNCTION_WRAPPER_KEYS and fields.keys() <= _FUNCTION_WRAPPER_KEYS
                    return [fields[key]] if closed else []
            if not isinstance(rows, list) or any(
                    not isinstance(row, dict) or not isinstance(row.get('content'), str)
                    for row in rows):
                return []
            functions = [_fenced_function(row['content']) for row in rows
                         if _affirmative_function_record(row) and row['content'].strip()]
            # A record with another role is not read for the function, but one
            # stating a different function or an arithmetic rule such as overflow
            # handling leaves the source unresolved. A prohibiting title states neither.
            others = [row for row in rows if not _affirmative_function_record(row)
                      and not re.search(_PROHIBITING_PROSE, str(row.get('title', '')), re.I)]
            stated = {_extract_operator(record) for record in functions}
            unresolved = any(
                _extract_operator(row['content']) not in (None, *stated)
                or _ARITHMETIC_QUALIFIER.search(f"{row.get('title', '')}\n{row['content']}")
                for row in others)
            return [] if unresolved else functions
    doc = _read_json(gd / 'L1_DATASHEET.json') or {}
    fields = doc.get('fields', doc)
    overview = fields.get('overview') if isinstance(fields, dict) else None
    if (isinstance(overview, str) and overview.strip()
            and _affirmative_function_context(doc) and _affirmative_function_context(fields)):
        return [overview]
    return []


def _declared_size(project: Path) -> List[object]:
    """The declared datapath size: the N of ``mod 2^N`` when none is named N."""
    for name in ('plugin_output/declaration.json', 'declaration.json'):
        doc = _read_json(project / name) or {}
        for key in ('size_param', 'size', 'width', 'data_width', 'bit_width', 'word_width'):
            if key in doc:
                value = doc[key]
                return [int(value) if isinstance(value, str) and value.strip().isdigit() else value]
    return []


def _source_modulus(project: Path) -> Tuple[Optional[int], str]:
    """Bind source exponents to exact declared names; never to a width guess."""
    tokens = [m[1] for record in _function_records(project)
              for m in re.finditer(r'\bmod\s+2\s*\^\s*(\d+|[A-Za-z_]\w*)\b', record)]
    if not tokens:
        return None, ''
    values = []
    params = None
    top, _ = _load_top_ports(project)
    for token in tokens:
        declared = []
        if token.isdigit():
            declared = [int(token)]
        else:
            for name in ('plugin_output/declaration.json', 'declaration.json'):
                doc = _read_json(project / name) or {}
                if token in doc:
                    value = doc[token]
                    if isinstance(value, str) and value.strip().isdigit():
                        value = int(value.strip())
                    declared.append(value)
            if not declared and token == 'N':
                declared = _declared_size(project)
            if not declared:
                if params is None:
                    from _port_width import defaults_from_sources
                    sources = [(p, p.read_text(errors='replace'))
                               for p in sorted(_pl.rtl_dir(project).rglob('*'))
                               if p.is_file() and p.suffix in ('.v', '.sv')]
                    params = defaults_from_sources(sources, top)
                if token in params:
                    declared.append(params[token])
        if not declared:
            return None, f'source modulus exponent {token} is unbound — defer to testbench-gen'
        if any(type(v) is not int or v < 1 for v in declared):
            return None, f'source modulus exponent {token} has no positive integer declaration — defer'
        if len(set(declared)) != 1:
            return None, f'source modulus exponent {token} has conflicting declarations — defer'
        values.append((token, declared[0]))
    if len({value for _, value in values}) > 1:
        return None, f'conflicting source modulus exponents {values} — defer'
    return (values[0][1], ', '.join(f'{name}={value}' for name, value in values)) if values else (None, '')


def _supports_function_reset(project: Path, polarity: str) -> bool:
    """Consume a finite reset clause only through its structured L9 contract.

    Both serial consumers assert reset across complete clock cycles. An absent
    or conflicting reset domain cannot be discarded as arithmetic metadata.
    """
    _, ports = _load_top_ports(project)
    clocks = [p['name'] for p in ports if p['dir'] == 'input'
              and p['name'].lower() in _CLK_NAMES and p.get('numeric_width') == 1]
    resets = [p['name'] for p in ports if p['dir'] == 'input'
              and p['name'].lower() in _RST_NAMES and p.get('numeric_width') == 1]
    if len(clocks) != 1 or len(resets) != 1:
        return False
    l9 = _read_json(_pl.generated_docs_dir(project) / 'L9_INTEGRATION_SPEC.json') or {}
    fields = l9.get('fields', l9)
    if not isinstance(fields, dict):
        return False
    domains = fields.get('reset_domains') or []
    if not isinstance(domains, list):
        return False
    selected = [r for r in domains if isinstance(r, dict) and r.get('name') == resets[0]]
    if len(selected) != 1:
        return False
    domain = selected[0]
    if (domain.get('sync') not in ('sync', 'synchronous')
            or domain.get('polarity') != 'active_' + polarity):
        return False
    from _reset_input_semantics import admit_reset_phases
    try:
        phases = admit_reset_phases(project, [l9], {p['name'] for p in ports})
    except ValueError:
        return False
    if resets[0] in phases and not any(
            b['clock'] == clocks[0] and b['assertion'] == 'synchronous'
            and b['polarity'] == 'active_' + polarity for b in phases[resets[0]]):
        return False
    conventions = read_declared_conventions(project, ports)
    active_low = (conventions['reset_active_low'] if conventions is not None
                  else resets[0].lower().rstrip('i').endswith('n'))
    if active_low != (polarity == 'low'):
        return False
    return True


def _function_operator(project: Path) -> Optional[Tuple[str, str, str, str]]:
    records = _function_records(project)
    parsed = []
    for record in records:
        reset = re.search(r';\s*synchronous active-(high|low) reset[.;]?\s*$', record, re.I)
        if reset and _supports_function_reset(project, reset[1].lower()):
            record = record[:reset.start()]
        parsed.append(_extract_operator(record))
    if not parsed or any(item is None for item in parsed):
        return None
    first = parsed[0]
    return first if all(item == first for item in parsed) else None


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
        from _port_width import defaults_from_sources, resolve
        top, _ = _load_top_ports(project)
        sources = [(p, p.read_text(errors='replace'))
                   for p in sorted(_pl.rtl_dir(project).rglob('*'))
                   if p.is_file() and p.suffix in ('.v', '.sv')]
        params = defaults_from_sources(sources, top)
        resolved_widths = []
        for port in ports:
            raw = port.get('raw') or port
            cell = raw.get('width_decl') or raw.get('width_symbolic')
            if not cell and raw.get('msb') is not None and raw.get('lsb') is not None:
                cell = f"{raw['msb']}:{raw['lsb']}"
            if not cell:
                continue
            cell = cell if str(cell).strip().startswith('[') else f'[{cell}]'
            decl, _ = resolve(cell, params)
            value = _port_numeric_width({'width_decl': (decl or '').strip()})
            if value is not None and value > 1:
                resolved_widths.append(value)
        if resolved_widths:
            return max(resolved_widths)
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
    if type(w) is int and w >= 1:
        return w
    if isinstance(w, str) and w.strip().isdigit():
        numeric = int(w.strip())
        return numeric if numeric >= 1 else None
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
    """Resolve the named operand_a/operand_b/result and their exact widths, or
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
    found = _function_operator(project)
    if not found:
        topology = ', '.join(sorted({p['name'] for p in ports
            if is_clock_or_reset_port(p['name'])
            or p['name'].lower() in (_HANDSHAKE_NAMES | _STATUS_OUT_NAMES)}))
        data_inputs = [p for p in ports if p['dir'] == 'input'
                       and not is_clock_or_reset_port(p['name'])]
        extra = (len(data_inputs) != 2
                 or sum(p['dir'] == 'output' for p in ports) != 1)
        return None, ("no recognised closed-form operator (* + - & | ^ << >>) "
                      "in a complete affirmative L2 function record; unsupported "
                      "expression or residual semantics — defer to testbench-gen"
                      + (f"; clock/handshake/status ports: {topology}" if topology else "")
                      + ('; a clock input is present' if any(
                          p['dir'] == 'input' and is_clock_or_reset_port(p['name'])
                          for p in ports) else '')
                      + ('; additional input controls or output functions require a reference' if extra else ''))
    res_name, lhs_name, operator, rhs_name = found
    modulus, modulus_binding = _source_modulus(project)
    if modulus is None and modulus_binding:
        return None, modulus_binding

    width = _resolve_width(project, ports)
    text_l = '\n'.join(_function_records(project)).lower()
    source_l = _doc_text(project).lower()
    says_signed = bool(re.search(r"\bsigned\b|2'?s? ?complement|signed_2c", source_l))
    says_unsigned = bool(re.search(r"\bunsigned\b", source_l))
    encoding = None
    for cand in ("plugin_output/declaration.json", "declaration.json"):
        d = _read_json(project / cand)
        if d and isinstance(d.get("integer_encoding"), str):
            enc = d["integer_encoding"].lower()
            encoding = "signed" in enc and "unsigned" not in enc
            break
    signed = encoding if encoding is not None else says_signed and not says_unsigned

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
              and not is_clock_or_reset_port(p["name"])]
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
    if (lhs_name and op_a is None) or (rhs_name and op_b is None):
        return None, 'source expression operand is not a declared data input — defer'
    if op_a is None or op_b is None:
        ranked = sorted(inputs, key=_rank_key, reverse=True)
        op_a, op_b = ranked[0], ranked[1]
    result = _by_name(res_name, outputs) if res_name else None
    if res_name and result is None:
        return None, 'source expression result is not a declared output — defer'
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
            f"derivable; defer to #654 (testbench-gen)")

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
    # The clock is recognised by SHAPE, not by an exact-name allow-list. This
    # guard already said the right thing and `wclk`/`rclk` walked straight past
    # it, so an asynchronous FIFO was handed a closed-form combinational XOR
    # oracle over its own clocks and failed 2 of 4 vectors while passing its own
    # dataset testbench (MEASURED 2026-09-06, RTLLM asyn_fifo).
    if any(is_clock_or_reset_port(str(p.get("name", ""))) and p.get("dir") == "input"
           for p in ports):
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

    if len(inputs) != 2 or len(outputs) != 1:
        return None, (
            "closed-form binary oracle requires exactly two data inputs and "
            "one output; additional input controls or output functions are "
            "not verified by the selected binary expression — defer to "
            "testbench-gen instead of emitting an incomplete oracle")

    # Per-port resolved widths (folds FACET-2 #643): a parametric port whose
    # numeric width is unknown is bound to the datapath width N so the operand
    # gets a real [N-1:0] declaration rather than a phantom 1-bit. The GOLDEN
    # truncation width is the RESULT port's physical width — that is the bit
    # pattern the DUT output actually carries (e.g. a 16-bit product net for an
    # 8x8 multiplier), so the `===` compare is exact.
    for port, role in roles:
        if port.get('numeric_width') is None:
            # Symbolic parallel widths must resolve over the defaults of the
            # module the emitted bare instantiation will actually elaborate.
            # Reuse the existing resolver; the conventional 32-bit fallback is
            # not a declaration of a parameter's value.
            raw = port.get('raw') or {}
            cell = raw.get('width_decl') or raw.get('width_symbolic')
            if not cell:
                match = re.search(r'\[[^\]]+\]', str(raw.get('width') or ''))
                cell = match[0] if match else None
            if not cell:
                return None, f'{role} width is unresolved — defer to testbench-gen'
            from _port_width import defaults_from_sources, resolve
            sources = [(path, path.read_text(errors='replace'))
                       for path in sorted(_pl.rtl_dir(project).rglob('*'))
                       if path.suffix in ('.v', '.sv') and path.is_file()]
            params = defaults_from_sources(sources, top)
            cell = cell if cell.strip().startswith('[') else '[' + cell + ']'
            resolved, why = resolve(cell, params)
            numeric = _port_numeric_width({'width_decl': (resolved or '').strip()})
            if numeric is None:
                return None, f'{role} width is unresolved: {why} — defer to testbench-gen'
            port['numeric_width'] = numeric
    op_a_w, op_b_w, result_w = (port['numeric_width'] for port, _ in roles)
    operand_signs = [(p.get('raw') or {}).get('signed') for p in (op_a, op_b)]
    if any(value is not None for value in operand_signs):
        if any(type(value) is not bool for value in operand_signs) or len(set(operand_signs)) != 1:
            return None, 'mixed or unresolved operand signedness — defer to testbench-gen'
        signed = operand_signs[0]
        if encoding is not None and encoding != signed:
            return None, 'declared integer encoding conflicts with operand signedness — defer to testbench-gen'
    elif encoding is None and says_signed:
        return None, 'signed source without declared operand signedness — defer to testbench-gen'
    if signed and operator in ('<<', '>>'):
        return None, 'signed shift operator semantics are unresolved — defer'
    if modulus is not None and modulus != result_w:
        return None, (f'source modulus {modulus_binding} differs from declared '
                      f'result width {result_w} — defer to testbench-gen')

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


def parallel_golden(spec: dict, a: int, b: int) -> int:
    """Interpret each driven bit pattern at its own declared operand width."""
    values = []
    for value, key in ((a, 'operand_a_width'), (b, 'operand_b_width')):
        width = spec[key]
        value = _twos(value, width)
        if spec['signed'] and value & (1 << (width - 1)):
            value -= 1 << width
        values.append(value)
    if spec['operator'] == '<<' and values[1] >= spec['result_width']:
        return 0
    if spec['operator'] == '>>' and values[1] >= spec['operand_a_width']:
        return 0
    return compute_golden(spec['operator'], *values, spec['result_width'], spec['signed'])


def parallel_operand_pairs(spec: dict, count: int = 300,
                           exclude=()) -> List[Tuple[int, int]]:
    """Distinct deterministic pairs over the actual rectangular input domain.

    A full-period odd-stride permutation avoids duplicate pairs and reaches
    large shift amounts too. Output truncation never changes the input domain.
    """
    aw, bw = spec['operand_a_width'], spec['operand_b_width']
    mask = (1 << (aw + bw)) - 1
    bmask = (1 << bw) - 1
    seen = set(exclude)
    out = []
    index = 0
    while len(out) < count and index <= mask:
        value = (index * 0x9E3779B97F4A7C15 + 0xD1B54A32D192ED03) & mask
        pair = value >> bw, value & bmask
        index += 1
        if pair not in seen:
            out.append(pair)
            seen.add(pair)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# SERIAL-PARALLEL declared-function functional-golden oracle (general convention)
# ─────────────────────────────────────────────────────────────────────────────
# The IC-EXPERT CONVENTION for authoring a functional-TB golden on a SERIAL-
# PARALLEL arithmetic datapath — the shape the closed-form COMBINATIONAL oracle
# above legitimately DEFERS (a bit-serial operand/result whose latency + bit-
# order are Plugin-chosen). This is keyed on the INTERFACE SHAPE (one parallel
# operand + one bit-serial operand + one bit-serial result + clock), never on a
# chip/SKU literal, so a fresh design of the same shape (any serial-parallel
# multiplier/adder/…) gets the same golden-authoring convention automatically.
#
# The convention (what an IC expert knows):
#   1. The GOLDEN VALUE = (a OP b) mod 2^N is computed INDEPENDENTLY in Python
#      (compute_golden) and embedded as constants — it is NEVER read from the
#      DUT (§4.05: no golden/oracle-harness leak; the operator token + N + sign
#      come from the design's DECLARED L2/L7 function, a legitimate design INPUT).
#   2. The serial FRAMING conventions the datapath is FREE to choose — bit_order
#      (LSB/MSB-first) and output latency_cycles — are read from the Plugin's
#      DECLARED interface contract (plugin_output/declaration.json, or the RTL
#      header 'DECLARED CHOICES' block that L7 §7.0 mandates). These tell the
#      oracle HOW to frame/sample the serial stream, never WHAT the product is:
#      a DUT that computes the wrong product fails at ANY declared framing, so
#      the oracle stays sound. When the framing is NOT declared, DEFER
#      (fail-closed) rather than guess.
#   3. Choreography (validated against the reference serial-parallel multiplier
#      across N∈{8,16,32} and latency∈{2,3}): synchronous reset per declared
#      polarity for 2 cycles; drive the parallel operand held; stream the serial
#      operand one bit/cycle per bit_order; capture the serial result at each
#      posedge; the product occupies the window [latency, latency+N) — reassemble
#      per bit_order and compare `===` the embedded golden.
# ═════════════════════════════════════════════════════════════════════════════

_BIT_ORDER_LSB = {"lsb_first", "lsb-first", "lsb", "little", "little_endian",
                  "little-endian", "lsbfirst"}
_BIT_ORDER_MSB = {"msb_first", "msb-first", "msb", "big", "big_endian",
                  "big-endian", "msbfirst"}


def _serial_prose_port(p: dict) -> bool:
    """True when a port's width PROSE marks it bit-serial (mirrors the
    extract_arith_spec _is_literal_1bit prose test) — chip-AGNOSTIC serial
    vocabulary, no SKU."""
    if p.get("numeric_width") == 1:
        return True
    raw = p.get("raw") or {}
    wraw = str(raw.get("width") or raw.get("width_symbolic") or "").lower()
    return bool(re.search(r"\bserial\b|bit[- ]?serial|\[\s*0\s*:\s*0\s*\]", wraw))


SERIAL_LATENCY_ORIGIN = "settled_edge_offset"
LEGACY_SERIAL_LATENCY_ORIGIN = "pre_nba_sample_offset"


def settled_serial_latency(value: Any, origin: str) -> Optional[int]:
    """Normalize one stated clock convention; never try both integer windows."""
    if type(value) is bool:
        return None
    try:
        offset = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if origin == LEGACY_SERIAL_LATENCY_ORIGIN:
        offset -= 1
    elif origin != SERIAL_LATENCY_ORIGIN:
        return None
    return offset if offset >= 0 else None


def read_declared_conventions(project: Path,
                              ports: List[dict]) -> Optional[dict]:
    """Resolve the Plugin's DECLARED serial-interface conventions.

    Source priority (all are the Plugin's OWN declaration of FREE interface
    choices — never a golden value): plugin_output/declaration.json →
    declaration.json → the RTL header 'DECLARED CHOICES' block that L7 §7.0
    mandates the Plugin author (`bit_order = …`, `latency_cycles = …`,
    `integer_encoding = …`, `reset_polarity = …`).

    Returns {bit_order:'LSB'|'MSB', latency:int, signed:bool,
    reset_active_low:bool} or None when bit_order/latency cannot be resolved
    (→ the caller DEFERS, fail-closed)."""
    keys = ("bit_order", "latency_cycles", "integer_encoding", "reset_polarity",
            "latency_cycles_origin", "transaction_rearm", "rearm_reset_cycles",
            "parallel_hold")
    conv: Dict[str, Any] = {}
    for cand in ("plugin_output/declaration.json", "declaration.json"):
        d = _read_json(project / cand)
        if d:
            for k in keys:
                if d.get(k) is not None and k not in conv:
                    conv[k] = d[k]
    if not all(k in conv for k in ("bit_order", "latency_cycles")):
        rtl = _pl.rtl_dir(project)
        if rtl.is_dir():
            srcs = sorted(rtl.rglob("*.v")) + sorted(rtl.rglob("*.sv"))
            for f in srcs:
                try:
                    t = f.read_text(errors="replace")
                except OSError:
                    continue
                for k in keys:
                    if k in conv:
                        continue
                    # `bit_order = LSB_first`, `latency_cycles = 2`, …  in a
                    # comment or a declaration line — value is the first token.
                    m = re.search(rf"\b{k}\b\s*=\s*([A-Za-z0-9_]+)", t)
                    if m:
                        conv[k] = m.group(1)
                if all(k in conv for k in ("bit_order", "latency_cycles")):
                    break
    bo = str(conv.get("bit_order", "")).strip().lower()
    if bo in _BIT_ORDER_LSB:
        bit_order = "LSB"
    elif bo in _BIT_ORDER_MSB:
        bit_order = "MSB"
    else:
        return None
    try:
        latency = int(str(conv.get("latency_cycles")).strip())
    except (TypeError, ValueError):
        return None
    origin = conv.get("latency_cycles_origin", SERIAL_LATENCY_ORIGIN)
    settled = settled_serial_latency(latency, origin)
    if settled is None:
        return None
    enc = str(conv.get("integer_encoding", "")).strip().lower()
    signed = ("signed" in enc and "unsigned" not in enc)
    rp = str(conv.get("reset_polarity", "")).strip().lower()
    reset_active_low = ("active_low" in rp) or ("low" in rp and "high" not in rp)
    return {"bit_order": bit_order, "latency": latency, "signed": signed,
            "latency_origin": origin, "settled_latency": settled,
            "reset_active_low": reset_active_low,
            **{k: conv[k] for k in ("transaction_rearm", "rearm_reset_cycles",
                                    "parallel_hold") if k in conv}}


def extract_serial_arith_spec(
        project: Path,
        ic_class: Optional[str]) -> Tuple[Optional[dict], str]:
    """Resolve a SERIAL-PARALLEL arithmetic oracle spec, or (None, reason) to
    DEFER. Recognises the shape: exactly the arithmetic-primitive family, a
    recognised closed-form operator, a clock, ≥1 PARALLEL (wide/parametric)
    data operand, ≥1 bit-SERIAL data operand, ≥1 bit-SERIAL data result, and
    the Plugin's DECLARED bit_order+latency. Fail-closed on anything else."""
    if ic_class not in _ARITH_CLASSES:
        return None, (f"ic_class {ic_class!r} is not an arithmetic-primitive "
                      f"family class")
    top, ports = _load_top_ports(project)
    if not top or not ports:
        return None, "no usable L9 top ports"
    found = _function_operator(project)
    if not found:
        return None, "no recognised closed-form operator"
    res_name, lhs_name, operator, rhs_name = found
    modulus, modulus_binding = _source_modulus(project)
    if modulus is None and modulus_binding:
        return None, modulus_binding

    names_lc = {str(p.get("name", "")).lower() for p in ports}
    clk = next((p["name"] for p in ports if p["dir"] == "input"
                and p["name"].lower() in _CLK_NAMES), None)
    if not clk:
        return None, "serial-parallel oracle needs a clock input"
    rst = next((p["name"] for p in ports if p["dir"] == "input"
                and p["name"].lower() in _RST_NAMES), None)
    if names_lc & _HANDSHAKE_NAMES:
        return None, ("handshake input present — protocol-aware oracle needed, "
                      "not modelled by the serial-parallel convention")
    if any(str(p.get("name", "")).lower() in _STATUS_OUT_NAMES
           for p in ports if p["dir"] == "output"):
        return None, "control/status output present — not a pure serial datapath"

    data_in = [p for p in ports if p["dir"] == "input"
               and p["name"].lower() not in (_CLK_NAMES | _RST_NAMES)]
    outs = [p for p in ports if p["dir"] == "output"]

    def _is1(p):
        return _serial_prose_port(p)

    def _wide(p):
        nw = p.get("numeric_width")
        return (isinstance(nw, int) and nw > 1) or bool(p.get("is_parametric"))

    parallel_ins = [p for p in data_in if _wide(p) and not _is1(p)]
    serial_ins = [p for p in data_in if _is1(p)]
    serial_outs = [p for p in outs if _is1(p)]
    if not (parallel_ins and serial_ins and serial_outs):
        return None, ("not a serial-parallel shape (need ≥1 parallel operand + "
                      "≥1 bit-serial operand + ≥1 bit-serial result)")
    # A wide/parametric OUTPUT means the result is delivered in parallel — that
    # is the closed-form PARALLEL oracle's job, not this serial one.
    if any(_wide(p) and not _is1(p) for p in outs):
        return None, "result is a parallel bus — parallel oracle applies"

    # The Plugin's DECLARED conventions are read when present (informational —
    # they annotate the manifest), but they are NOT required: the emitted oracle
    # SELF-CALIBRATES the serial framing (bit-order + latency) from the DUT
    # stream vs the independent golden, so a missing / mislabelled declaration
    # (e.g. a `latency_cycles` label that does not match the actual register
    # depth) can neither block the oracle nor false-FAIL a correct DUT.
    conv = read_declared_conventions(project, ports) or {}
    width = _resolve_width(project, ports)
    if modulus is not None and modulus != width:
        return None, f'source modulus {modulus_binding} differs from serial word width {width} — defer'
    text_l = _doc_text(project).lower()
    signed = bool(conv.get("signed")) or bool(
        re.search(r"\bsigned\b|2'?s? ?complement|signed_2c", text_l)
        and not re.search(r"\bunsigned\b", text_l))

    parallel = max(parallel_ins,
                   key=lambda p: (p.get("numeric_width") or width))
    serial_in = serial_ins[0]
    serial_out = serial_outs[0]
    # Operand→role: golden = compute_golden(op, lhs_val, rhs_val). Map by the
    # spec-named operands when available so a NON-commutative op (- << >>) drives
    # the right side serially; commutative ops are order-invariant anyway.
    parallel_is_lhs = True
    if lhs_name and rhs_name:
        if serial_in["name"] == lhs_name and parallel["name"] == rhs_name:
            parallel_is_lhs = False
    other_inputs = [p["name"] for p in data_in
                    if p["name"] not in (parallel["name"], serial_in["name"])]
    # reset polarity: prefer the declared value, else infer from an active-low
    # port-name suffix (`_n`/`n`) — chip-AGNOSTIC.
    ral = bool(conv.get("reset_active_low")) if conv.get("reset_active_low") \
        is not None else (bool(rst) and str(rst).lower().rstrip("i").endswith("n"))
    return ({
        "topology": "serial_parallel",
        "top": top, "operator": operator, "width": width, "signed": signed,
        "parallel": parallel["name"], "serial_in": serial_in["name"],
        "serial_out": serial_out["name"], "clk": clk, "rst": rst,
        "reset_active_low": ral if rst else False,
        "declared_bit_order": conv.get("bit_order"),
        "declared_latency": conv.get("latency"),
        "parallel_is_lhs": parallel_is_lhs, "other_inputs": other_inputs,
        "ports": ports,
    }, "serial-parallel declared-function arithmetic oracle")


def _lcg_random_pairs(n: int, count: int, seed: int = 0x2545F491,
                      operator: str = "*") -> List[Tuple[int, int]]:
    """A deterministic (NO `random` import) pseudo-random operand-pair stream —
    fully reproducible, so the emitted TB is byte-stable. Shift RHS into
    [0, N) for shift operators."""
    out: List[Tuple[int, int]] = []
    state = seed & 0xFFFFFFFF
    span = 1 << n
    for _ in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        a = state % span
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        b = state % span
        if operator in ("<<", ">>"):
            b = b % n if n > 0 else 0
        out.append((a, b))
    return out


# ── what the CASE'S OWN TEXT states about its population ─────────────────────
# FULLSTACKTB (2026-09-29). An L10 row can state HOW MANY vectors it is about
# ("隨機 ≥ 10000 組 (x, y)"), WHICH operand corners it names ("x = MIN_NEG"),
# and that reset is asserted WHILE a computation is in progress. The per-case
# oracle used to ignore all three: it drove a fixed 28-pair sample and a corner
# set that, for an unsigned reading, never contains the MIN_NEG pattern the row
# names. A case executed that way is not the case the design stated. These
# readers are grammar over the case's own stimulus text -- no design literal --
# and each returns "nothing stated" rather than a guess.

#: A stated population is a count next to a population noun, or a count behind
#: a lower-bound word. A percentage is an ACCEPTANCE figure, never a population,
#: so a number followed by `%` is refused by construction.
_POPULATION_NOUN = (r"(?:組|组|筆|笔|個|个|pairs?|vectors?|sets?|samples?|"
                    r"operand\s+pairs?|input\s+pairs?|trials?|iterations?|"
                    r"transactions?)")
_POPULATION_RES = (
    re.compile(r"(?:≥|>=|>|至少|at\s+least|no\s+fewer\s+than|minimum(?:\s+of)?)"
               r"\s*([0-9][0-9,_]*)(?![0-9.,_]*\s*%)", re.IGNORECASE),
    re.compile(r"(?<![0-9.])([0-9][0-9,_]*)\s*" + _POPULATION_NOUN,
               re.IGNORECASE),
)
#: The most vectors one generated case module carries. A stated population
#: above it is NOT silently truncated to look satisfied: the caller compares
#: the executed count against the STATED one and reports the shortfall.
MAX_CASE_VECTORS = 20000


def declared_vector_population(case: dict) -> Optional[int]:
    """The vector population the case's OWN stimulus text states, or None.

    Read from `stimulus` and `coverage_scope` only -- `expected` carries the
    acceptance figure ("100% PASS", "≥ 95%"), and a percentage is never a
    population. Returns the LARGEST stated count (a row naming "≥ 10000 組"
    asks for at least that many)."""
    text = " ".join(str(case.get(k) or "") for k in ("stimulus",
                                                      "coverage_scope"))
    found: List[int] = []
    for rx in _POPULATION_RES:
        for m in rx.finditer(text):
            digits = re.sub(r"[,_]", "", m.group(1))
            if digits.isdigit() and int(digits) > 1:
                found.append(int(digits))
    return max(found) if found else None


_CORNER_NAMES = {
    # name -> function(width) giving the WIDTH-BIT PATTERN the name denotes
    "max_pos": lambda w: (1 << (w - 1)) - 1,
    "max_positive": lambda w: (1 << (w - 1)) - 1,
    "int_max": lambda w: (1 << (w - 1)) - 1,
    "min_neg": lambda w: 1 << (w - 1),
    "min_negative": lambda w: 1 << (w - 1),
    "int_min": lambda w: 1 << (w - 1),
    "all_ones": lambda w: (1 << w) - 1,
    "max_unsigned": lambda w: (1 << w) - 1,
    "umax": lambda w: (1 << w) - 1,
}
#: `<operand> = <value>` inside a corner enumeration. The value is a signed
#: decimal or one of the names above; anything else is not a corner the row
#: named and is ignored rather than guessed at.
_CORNER_ASSIGN_RE = re.compile(r"=\s*(-?\d+|[A-Za-z_][A-Za-z0-9_]*)")


def named_corner_values(case: dict, width: int) -> List[int]:
    """The operand corners the case's OWN text names, as width-bit patterns.

    `x = MIN_NEG` names the pattern 1<<(N-1); `y = -1` names all-ones. Two's
    complement is bit-identical mod 2^N for + - * & | ^, so a corner the row
    states in signed terms is the same drive pattern whatever signedness the
    oracle reads. Returns [] when the row names none."""
    if width < 1:
        return []
    text = " ".join(str(case.get(k) or "") for k in ("stimulus",
                                                      "coverage_scope"))
    mask = (1 << width) - 1
    out: List[int] = []
    for m in _CORNER_ASSIGN_RE.finditer(text):
        tok = m.group(1)
        if re.fullmatch(r"-?\d+", tok):
            val = int(tok) & mask
        else:
            fn = _CORNER_NAMES.get(tok.lower())
            if fn is None:
                continue
            val = fn(width) & mask
        if val not in out:
            out.append(val)
    return out


#: "reset asserted while a computation is in progress" -- the abort-and-restart
#: scenario. Grammar over the case's own text, either word order.
_RESET_MID_RE = re.compile(
    r"(?:reset|rst)[^/、,;。]{0,24}?(?:計算進行中|运算进行中|運算進行中|進行中|"
    r"during\s+(?:a\s+|the\s+)?(?:computation|operation|calculation|transfer)|"
    r"mid[- ]?(?:computation|operation|stream)|in[- ]progress|while\s+busy)"
    r"|(?:計算進行中|進行中|during\s+(?:a\s+|the\s+)?(?:computation|operation))"
    r"[^/、,;。]{0,24}?(?:reset|rst)\s*(?:assert|asserted)",
    re.IGNORECASE)


def reset_mid_computation_case(case: dict) -> bool:
    """True iff the case's own text asks for reset asserted mid-computation."""
    text = " ".join(str(case.get(k) or "") for k in ("stimulus", "expected",
                                                      "coverage_scope"))
    return bool(_RESET_MID_RE.search(text))


def _distinct_population_pairs(n: int, count: int, operator: str,
                               exclude: set) -> List[Tuple[int, int]]:
    """Up to `count` DISTINCT operand pairs not in `exclude`, deterministic.

    Not `_lcg_random_pairs`: that takes `state % 2**n`, the LOW bits of a
    power-of-two-modulus LCG, and bit k of such a generator has period 2**(k+1)
    -- MEASURED for n = 8: 500 draws gave 132 distinct pairs, so a stated
    population of 500 would have been "met" by repeating 132 vectors. This
    draws whole 64-bit SplitMix64 words (every bit full-period) and keeps only
    unseen pairs; it stops at the operand space's capacity rather than repeat,
    and the caller compares the result with the stated population."""
    mask = (1 << n) - 1
    words = max(1, (n + 63) // 64)
    state = 0x9E3779B97F4A7C15 ^ n

    def _next() -> int:
        nonlocal state
        state = (state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def _operand() -> int:
        v = 0
        for _ in range(words):
            v = (v << 64) | _next()
        return v & mask

    capacity = (1 << (2 * n)) if operator not in ("<<", ">>") \
        else (1 << n) * max(1, n)
    out: List[Tuple[int, int]] = []
    seen = set(exclude)
    budget = count * 8 + 1024
    while len(out) < count and len(seen) < capacity and budget > 0:
        budget -= 1
        a, b = _operand(), _operand()
        if operator in ("<<", ">>"):
            b = b % n if n > 0 else 0
        if (a, b) in seen:
            continue
        seen.add((a, b))
        out.append((a, b))
    return out


def select_operand_pairs(spec: dict, profile: str = "mixed",
                         cap: int = 28,
                         min_vectors: "int | None" = None,
                         extra_corners: "List[int] | Tuple[int, ...]" = ()
                         ) -> List[Tuple[int, int]]:
    """Deterministic operand pairs for a serial-parallel oracle, tuned to an
    L10 case PROFILE (chip-AGNOSTIC): 'corners' (the enumerated corner cross-
    product — for a corner-operand case), 'random' (a wide deterministic
    pseudo-random sample — for a random-equivalence / coverage case), or
    'mixed' (corners + a healthy random sample, the default). The random sample
    is deliberately generous so a data-dependent product defect is unlikely to
    escape (the L7 plan asks for a large random equivalence run).

    `extra_corners` (width-bit patterns the case's own text names) are crossed
    with each other FIRST, so every corner pair the row states is driven.
    `min_vectors` (the population the row states) grows the random tail until
    the sample holds at least that many distinct pairs, up to
    `MAX_CASE_VECTORS`; the caller compares the result with the stated count.
    With neither argument the output is exactly the historical sample."""
    n = spec["width"]
    op = spec["operator"]
    corners = enumerate_operand_pairs(n, spec.get("signed", True), op)
    # drop enumerate's small built-in random tail so we control the sample size
    corners = corners[:-6] if len(corners) > 6 else corners
    named: List[Tuple[int, int]] = []
    if extra_corners:
        vals = list(dict.fromkeys(int(v) for v in extra_corners))
        for a in vals:
            for b in vals:
                if op in ("<<", ">>"):
                    b = b % n if n > 0 else 0
                named.append((a, b))
    want = None
    if min_vectors:
        want = min(int(min_vectors), MAX_CASE_VECTORS)
    randoms = _lcg_random_pairs(n, 20, operator=op)
    if want is not None:
        # The historical 20 stay first; the population beyond them comes from
        # a stream whose every bit is usable (see `_distinct_population_pairs`).
        randoms = randoms + _distinct_population_pairs(
            n, want + len(named) + len(corners), op, set(randoms))
    if profile == "corners":
        sel = named + corners + randoms[:4]
    elif profile == "random":
        sel = named + randoms + corners[:4]
    else:
        sel = named + corners + randoms
    if want is not None and profile == "corners":
        # A stated population outranks the corner profile's short tail.
        sel = sel + randoms[4:]
    # de-dup preserving order
    seen: set = set()
    uniq: List[Tuple[int, int]] = []
    for p in sel:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    if want is not None:
        return uniq[:max(want, len(named))]
    if named:
        return uniq[:max(cap, len(named))] if cap else uniq
    return uniq[:cap] if cap else uniq


def emit_serial_oracle_module(module_name: str, spec: dict,
                              pairs: "List[Tuple[int, int]] | None" = None,
                              abort_before_each: bool = False
                              ) -> str:
    """Emit ONE self-checking SERIAL-PARALLEL oracle Verilog module.

    `module_name` lets a caller (the L10 per-case unit-TB producer) name the
    module after the L10 case so l10_tb_conformance credits it; the arith
    oracle path uses `tb_<top>_oracle`.

    SELF-CALIBRATING framing (§4.05-sound, robust across RTL variants). The
    GOLDEN VALUES are computed INDEPENDENTLY in Python (compute_golden) and
    embedded as constants — never read from the DUT. The three FRAMING facts a
    serial-parallel datapath is FREE to choose — the serial-input bit-order, the
    serial-output bit-order, and the output latency (offset) — are NOT trusted
    from a (loosely-labelled, often mismatched) declaration; instead the TB
    DISCOVERS the single (in_order, out_order, offset) framing under which the
    reassembled DUT stream equals the independent golden for ALL vectors, then
    reports pass=<matches at the best framing>/NV. This is exactly functional
    equivalence for a design whose framing is implementer's-choice (L2/L7): a
    DUT that computes the WRONG product matches NO consistent framing → it
    fails; a DUT that computes a·b under ANY self-consistent framing passes.
    The vector set carries several non-trivial, distinct goldens so a spurious
    framing cannot match all of them (no aliasing false-pass).

    `abort_before_each` (FULLSTACKTB) is the case whose own text asks for reset
    asserted WHILE a computation is in progress: before each vector a DIFFERENT
    operation (both operands inverted) is streamed for N/2 cycles and reset is
    then asserted in the middle of it. The vector that follows must still
    reassemble to its own golden, so a datapath that keeps state across a reset
    fails. It needs a reset port; without one the flag is refused (ValueError).

    A population larger than `_CAL_VECTORS` calibrates the framing on the first
    `_CAL_VECTORS` vectors (a single framing must reassemble EVERY one of them)
    and then scores EVERY vector at that framing. Same soundness -- one framing,
    all vectors -- without an O(framings x vectors) search: measured through a
    pad-ring chip top, the full search over 10 000 vectors took 2 min 27 s of
    vvp time. Populations at or below it emit exactly the historical module."""
    if abort_before_each and not spec.get("rst"):
        raise ValueError("abort_before_each needs a reset port to assert "
                         "mid-computation; this spec has none")
    top = spec["top"]
    op = spec["operator"]
    n = spec["width"]
    signed = bool(spec.get("signed", True))
    par, sin, sout = spec["parallel"], spec["serial_in"], spec["serial_out"]
    clk, rst = spec["clk"], spec["rst"]
    ral = bool(spec.get("reset_active_low"))
    par_lhs = bool(spec.get("parallel_is_lhs", True))
    ports = spec["ports"]
    if pairs is None:
        pairs = select_operand_pairs(spec, "mixed")
    if not pairs:
        pairs = [(1, 1)]

    def _rng(w):
        return f" [{w - 1}:0]" if w > 1 else ""

    L: List[str] = ["`timescale 1ns/1ps"]
    L.append("// Auto-generated by arith_oracle_tb_gen — SERIAL-PARALLEL "
             "declared-function functional-golden oracle (general IC-expert "
             "convention, interface-shape-keyed, chip-AGNOSTIC).")
    L.append(f"// operator '{op}'  N={n}  signed={str(signed).lower()}  "
             f"parallel={par} serial_in={sin} serial_out={sout}")
    L.append("// golden = (a %s b) mod 2^N computed INDEPENDENTLY (Python) and "
             "embedded; the serial framing (bit-order/latency) is DISCOVERED "
             "from the DUT stream vs the golden, never trusted from the DUT."
             % op)
    L.append(f"module {module_name};")
    L.append(f"  localparam integer N      = {n};")
    L.append("  localparam integer MAXOFF = 2*N;   // latency search window")
    L.append("  localparam integer CYC    = 3*N;   // capture cycles / vector")
    # port nets
    for p in ports:
        nm = p["name"]
        decl = "reg" if p["dir"] == "input" else "wire"
        if nm == par:
            rng = _rng(n)
        elif nm in (sin, sout, clk, rst):
            rng = ""
        else:
            pw = p.get("numeric_width")
            rng = f" [{pw - 1}:0]" if isinstance(pw, int) and pw > 1 else ""
        L.append(f"  {decl}{rng} {nm};")
    conns = ", ".join(f".{p['name']}({p['name']})" for p in ports)
    L.append(f"  {top} dut ({conns});")
    L.append(f"  initial {clk} = 1'b0;")
    L.append(f"  always #5 {clk} = ~{clk};")
    L.append(f"  localparam integer NV = {len(pairs)};")
    L.append("  reg [N-1:0] _av [0:NV-1];")
    L.append("  reg [N-1:0] _bv [0:NV-1];")
    L.append("  reg [N-1:0] _gv [0:NV-1];")
    L.append("  reg [CYC-1:0] _capL [0:NV-1];  // input streamed LSB-first")
    L.append("  reg [CYC-1:0] _capM [0:NV-1];  // input streamed MSB-first")
    L.append("  reg [CYC-1:0] _word;")
    L.append("  reg [N-1:0] _got;")
    L.append("  reg _b;")
    L.append("  integer _vi, _k, _bi, _io, _oo, _off, _m, _best;")
    # Winning framing triple. The search below already COMPUTES which
    # (in_order, out_order, offset) reassembles the DUT stream to the golden;
    # keeping it lets the run PERSIST the measured framing instead of
    # discarding it (see ORACLE_TB_FRAMING below).
    L.append("  integer _bio, _boo, _boff;")
    assert_v, deassert_v = ("0", "1") if ral else ("1", "0")

    # ── drive+capture one pass at a given serial-input bit-order ──────────────
    L.append("  task _drive_capture(input integer inorder); begin")
    L.append("    for (_vi = 0; _vi < NV; _vi = _vi + 1) begin")
    for nm in spec.get("other_inputs", []):
        L.append(f"      {nm} = 0;")
    if abort_before_each:
        # RESET MID-COMPUTATION, as the case's own text states it: a different
        # operation is in flight when reset asserts on the next line.
        L.append(f"      {rst} = 1'b{deassert_v}; {par} = ~_av[_vi];")
        L.append("      for (_k = 0; _k < N/2; _k = _k + 1) begin")
        L.append(f"        {sin} = ~((_bv[_vi] >> _k) & 1'b1);")
        L.append(f"        @(negedge {clk});")
        L.append("      end")
    if rst:
        L.append(f"      {rst} = 1'b{assert_v}; {sin} = 1'b0; "
                 f"{par} = _av[_vi];")
        L.append(f"      @(negedge {clk}); @(negedge {clk});")
        L.append(f"      {rst} = 1'b{deassert_v};")
    else:
        L.append(f"      {sin} = 1'b0; {par} = _av[_vi];")
        L.append(f"      @(negedge {clk}); @(negedge {clk});")
    L.append("      _word = 0;")
    L.append("      for (_k = 0; _k < CYC; _k = _k + 1) begin")
    L.append("        if (_k < N)")
    L.append(f"          {sin} = (inorder == 0) ? ((_bv[_vi] >> _k) & 1'b1)")
    L.append("                                  : ((_bv[_vi] >> (N-1-_k)) & 1'b1);")
    L.append(f"        else {sin} = 1'b0;")
    L.append(f"        @(posedge {clk});")
    L.append(f"        #1; _word[_k] = {sout};  // sample after this edge settles")
    L.append(f"        @(negedge {clk});")
    L.append("      end")
    L.append("      if (inorder == 0) _capL[_vi] = _word; else _capM[_vi] = _word;")
    L.append("    end")
    L.append("  end endtask")

    L.append("  initial begin")
    # vector table — golden precomputed in Python, embedded as constants
    for i, (a, b) in enumerate(pairs):
        lhs_v, rhs_v = (a, b) if par_lhs else (b, a)
        golden = compute_golden(op, lhs_v, rhs_v, n, signed)
        par_v = _twos(a, n)
        ser_v = _twos(b, n)
        L.append(f"    _av[{i}] = {n}'d{par_v}; _bv[{i}] = {n}'d{ser_v}; "
                 f"_gv[{i}] = {n}'d{golden};  // {par}={a} {op} {sin}={b}")
    L.append("    _drive_capture(0);   // serial input LSB-first")
    L.append("    _drive_capture(1);   // serial input MSB-first")
    if len(pairs) > _CAL_VECTORS:
        _emit_calibrated_framing_scoring(L, len(pairs))
        L.append("    $finish;")
        L.append("  end")
        L.append("endmodule")
        return "\n".join(L) + "\n"
    # search (in_order, out_order, offset) for the framing matching ALL vectors
    L.append("    _best = 0; _bio = -1; _boo = -1; _boff = -1;")
    L.append("    for (_io = 0; _io < 2; _io = _io + 1)")
    L.append("     for (_oo = 0; _oo < 2; _oo = _oo + 1)")
    L.append("      for (_off = 0; _off <= MAXOFF; _off = _off + 1) begin")
    L.append("        _m = 0;")
    L.append("        for (_vi = 0; _vi < NV; _vi = _vi + 1) begin")
    L.append("          _word = (_io == 0) ? _capL[_vi] : _capM[_vi];")
    L.append("          _got = 0;")
    L.append("          for (_bi = 0; _bi < N; _bi = _bi + 1) begin")
    L.append("            _b = _word[_off + _bi];")
    L.append("            if (_oo == 0) _got[_bi] = _b; else _got[N-1-_bi] = _b;")
    L.append("          end")
    L.append("          if (_got === _gv[_vi]) _m = _m + 1;")
    L.append("        end")
    L.append("        if (_m > _best) begin")
    L.append("          _best = _m; _bio = _io; _boo = _oo; _boff = _off;")
    L.append("        end")
    L.append("      end")
    L.append('    $display("ORACLE_TB_DONE pass=%0d/%0d", _best, NV);')
    # Persist the MEASURED framing. Emitted ONLY when a single framing
    # reassembles EVERY vector (_best == NV): a partial match means no
    # framing was established and publishing one would be a guess.
    # Encoding is numeric (0 = LSB_first, 1 = MSB_first) so the line carries
    # no locale/string-literal portability risk across simulators.
    L.append("    if (_best == NV) $display(\"ORACLE_TB_FRAMING in_order=%0d "
             "out_order=%0d latency_cycles=%0d latency_origin=settled_edge_offset\", _bio, _boo, _boff);")
    L.append("    if (_best != NV) $display(\"ORACLE_MISMATCH: no single serial "
             "framing reassembles the DUT stream to the golden for all vectors "
             "(possible functional defect)\");")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


#: The framing-calibration subset for a large population (see
#: `emit_serial_oracle_module`). Equal to the historical default sample size, so
#: every module emitted for a population that small is byte-identical to before.
_CAL_VECTORS = 28


def _emit_calibrated_framing_scoring(L: List[str], nv: int) -> None:
    """Framing search over the first `_CAL_VECTORS` vectors, then EVERY vector
    scored at the one framing found. Appends to `L` in place."""
    L.append(f"    // {nv} vectors: framing calibrated on the first "
             f"{_CAL_VECTORS}, then every vector scored at that one framing.")
    L.append("    _best = 0; _bio = -1; _boo = -1; _boff = -1;")
    L.append("    for (_io = 0; _io < 2; _io = _io + 1)")
    L.append("     for (_oo = 0; _oo < 2; _oo = _oo + 1)")
    L.append("      for (_off = 0; _off <= MAXOFF; _off = _off + 1) begin")
    L.append("        _m = 0;")
    L.append(f"        for (_vi = 0; _vi < {_CAL_VECTORS}; _vi = _vi + 1) begin")
    L.append("          _word = (_io == 0) ? _capL[_vi] : _capM[_vi];")
    L.append("          _got = 0;")
    L.append("          for (_bi = 0; _bi < N; _bi = _bi + 1) begin")
    L.append("            _b = _word[_off + _bi];")
    L.append("            if (_oo == 0) _got[_bi] = _b; else _got[N-1-_bi] = _b;")
    L.append("          end")
    L.append("          if (_got === _gv[_vi]) _m = _m + 1;")
    L.append("        end")
    L.append("        if (_m > _best) begin")
    L.append("          _best = _m; _bio = _io; _boo = _oo; _boff = _off;")
    L.append("        end")
    L.append("      end")
    L.append("    _m = 0;")
    L.append("    if (_bio >= 0) begin")
    L.append("      for (_vi = 0; _vi < NV; _vi = _vi + 1) begin")
    L.append("        _word = (_bio == 0) ? _capL[_vi] : _capM[_vi];")
    L.append("        _got = 0;")
    L.append("        for (_bi = 0; _bi < N; _bi = _bi + 1) begin")
    L.append("          _b = _word[_boff + _bi];")
    L.append("          if (_boo == 0) _got[_bi] = _b; else _got[N-1-_bi] = _b;")
    L.append("        end")
    L.append("        if (_got === _gv[_vi]) _m = _m + 1;")
    L.append("      end")
    L.append("    end")
    L.append('    $display("ORACLE_TB_DONE pass=%0d/%0d", _m, NV);')
    L.append(f"    if (_best == {_CAL_VECTORS} && _m == NV) $display("
             "\"ORACLE_TB_FRAMING in_order=%0d out_order=%0d "
             "latency_cycles=%0d latency_origin=settled_edge_offset\", _bio, _boo, _boff);")
    L.append(f"    if (_best != {_CAL_VECTORS} || _m != NV) $display("
             "\"ORACLE_MISMATCH: no single serial framing reassembles the DUT "
             "stream to the golden for all vectors (possible functional "
             "defect)\");")


ARITHMETIC_SCENARIO_HEADER = "// VIBEIC_ARITHMETIC_SCENARIO: "


def _arithmetic_scenario_intent(case: dict, operand_names: Tuple[str, ...]) -> dict:
    """Normalize only the row's declared intent, never its case/category name."""
    import unicodedata
    from _prose_polarity import is_denied, sentence_scope
    normalized = {k: unicodedata.normalize('NFKC', str(case.get(k) or '')).lower()
                  for k in ('stimulus', 'expected', 'coverage_scope', 'scope')}
    text = '; '.join(normalized.values())

    def stated(pattern: str, source: str = text) -> bool:
        for hit in re.finditer(pattern, source, re.IGNORECASE):
            lo, hi = sentence_scope(source, hit.start(), hit.end(),
                                   extra_breaks=(';', '；', '/', '、', '。', '\n'))
            # A denial of this subject governs it; a later "no X" or
            # "without extra idle cycles" is an acceptance qualifier.
            # Only a request predicate immediately following the subject can
            # deny it from the right; never scan a later expected-value clause.
            predicate = re.match(r'\s*(?:(?:is|are|was|were)\s+)?(?:[a-z]+\s+){0,2}'
                                 r'(?:required|requested|needed)\b', source[hit.end():hi])
            if (not is_denied(source[lo:hit.start()])
                    and not (predicate and is_denied(predicate.group(0)))):
                return True
        return False

    boundaries = stated(r'operand\s+(?:boundar\w*|extrem\w*|corners?)|(?:運算元|操作數|操作数)\s*(?:邊界|边界|極值|极值)')
    named_text = '; '.join(normalized[k] for k in ('stimulus', 'coverage_scope'))
    if operand_names:
        operand = '|'.join(re.escape(n) for n in operand_names)
        corner = '|'.join(re.escape(n) for n in _CORNER_NAMES)
        boundaries |= stated(rf'\b(?:{operand})\s*=\s*(?:{corner})\b', named_text)
    consecutive = stated(r'consecutive\s+(?:(?:(?:>=|≥|at\s+least)\s*)?[0-9][0-9,_]*\s+)?transactions?|back.to.back|(?:連續|连续)\s*(?:(?:至少\s*)?[0-9][0-9,_]*\s*)?(?:多筆|多笔|筆|笔|乘法|計算|计算|交易|運算|运算)')
    held = stated(r'held|hold|(?:reset|rst|重置|復位|复位)\s*(?:期間|期间)')
    # English reset-period wording denotes the held-reset situation too.
    # Keep explicitly undefined/denied scopes as an expert handoff.
    held |= stated(r'\bduring\s+(?:the\s+)?(?:reset|rst)\b'
                   r'(?!\s+(?:release\b|deassert(?:ion|ed)?\b|(?:(?:is|remains)\s+)?(?:unspecified|undefined|'
                   r'not\s+(?:required|specified|defined))))')
    released = stated(r'released|release|(?:reset|rst|重置|復位|复位)\s*(?:解除(?:瞬間|瞬间)?|釋放|释放)')
    mid = stated(_RESET_MID_RE.pattern) or stated(r'asserted\s+during\s+computation')
    reset = bool(stated(r'reset|rst|重置|復位|复位') and (mid or (held and released)))
    return {'case': {**case, **normalized}, 'text': text,
            'operand_boundaries': boundaries, 'consecutive_transactions': consecutive,
            'reset_situations': reset, 'reset_complete': held and released and mid,
            'random_transactions': stated(r'\brandom(?:ized)?\b|隨機|随机')}


def arithmetic_observation(project: Path, spec: dict, *, top: Optional[str] = None,
                           sources: Optional[dict] = None) -> Tuple[Optional[dict], str]:
    """Fixed within-cycle schedule from the selected INPUT interface.

    L9 owns the clock period. Optional observation choices live in the existing
    declaration verification_stimuli.arithmetic_observation, keyed by top.
    A changed surface requires an explicit clock/output, settling bound, sample
    and exact wrapper/model binding. No waveform or golden is consulted.
    The direct surface retains its 1 ns observation when no choice is supplied.
    """
    import hashlib
    selected = top or spec['top']
    l9_path = _pl.generated_docs_dir(project) / 'L9_INTEGRATION_SPEC.json'
    declaration_path = project / 'plugin_output/declaration.json'
    locus = f'{declaration_path}#/verification_stimuli/arithmetic_observation/{selected}'

    def refuse(reason, location=locus):
        return None, f'{location}: {reason}'

    l9 = _read_json(l9_path) or {}
    l9 = l9.get('fields') or l9
    clocks = l9.get('clocks') or l9.get('clock_domains') or []
    clocks = [c for c in clocks if isinstance(c, dict) and c.get('name') == spec['clk']]

    def ns(value):
        return (type(value) in (int, float) and math.isfinite(value)
                and value >= 0 and math.isclose(value * 1000, round(value * 1000), abs_tol=1e-6))

    if len(clocks) != 1 or not ns(clocks[0].get('period_ns')):
        return refuse('selected clock needs one finite period_ns at 1 ps resolution',
                      f'{l9_path}#/clocks or #/clock_domains (name={spec["clk"]})')
    period = clocks[0]['period_ns']
    if period <= 4 or not ns(period / 2) or clocks[0].get('duty_cycle', 0.5) != 0.5:
        return refuse('unsupported clock half-cycle or duty cycle for between-edge reset pulses',
                      f'{l9_path}#/clocks or #/clock_domains (name={spec["clk"]})')
    declaration = _read_json(declaration_path) or {}
    stimuli = declaration.get('verification_stimuli', {})
    choices = stimuli.get('arithmetic_observation', {}) if isinstance(stimuli, dict) else None
    if not isinstance(choices, dict):
        return refuse('arithmetic observation choices must be a mapping by selected top')
    choice = choices.get(selected)
    if choice is None and selected == spec['top'] and selected not in choices:
        return {'top': selected, 'clock': spec['clk'], 'output': spec['serial_out'],
                'clock_period_ns': period, 'sample_offset_ns': 1,
                'settle_ns': 0, 'binding': {}}, ''
    if not isinstance(choice, dict):
        return refuse('selected top has no declared arithmetic observation contract')
    if choice.get('clock') != spec['clk'] or choice.get('output') != spec['serial_out']:
        return refuse('observation clock/output does not match the selected arithmetic interface')
    sample, settle = choice.get('sample_offset_ns'), choice.get('settle_ns')
    if not ns(sample) or not ns(settle) or not 0 <= settle < sample < period / 2:
        return refuse('observation must be after declared settling and strictly inside the half-cycle')
    binding = choice.get('binding', {})
    if not isinstance(binding, dict):
        return refuse('observation source binding must be a mapping')
    try:
        binding = {str((project / p).resolve()): digest for p, digest in binding.items()}
        actual = {str((project / p).resolve()): digest for p, digest in (sources or {}).items()}
    except (TypeError, ValueError):
        return refuse('observation source binding contains an unsupported path')
    if len(binding) != len(choice.get('binding', {})) or len(actual) != len(sources or {}):
        return refuse('observation source binding contains duplicate source locators')
    if selected != spec['top'] and actual and binding != actual:
        # A retained author map may name the same canonical wrapper in its
        # previous carrier. Resolve that sole locator in memory; never edit it.
        pad = _read_json(project / 'reports/phase3/io_pad_chip_top.json') or {}
        wrapper_rel = Path(str(pad.get('chip_top_verilog', '')))
        wrapper = (project / wrapper_rel).resolve()
        stale = [p for p in binding if p not in actual]
        missing = [p for p in actual if p not in binding]
        if (pad.get('verdict') == 'WROTE' and pad.get('chip_top_module') == selected
                and pad.get('core_module') == spec['top']
                and not wrapper_rel.is_absolute() and '..' not in wrapper_rel.parts
                and wrapper.is_relative_to(project.resolve()) and wrapper.is_file()
                and len(stale) == len(missing) == 1 and missing[0] == str(wrapper)
                and any(Path(p).is_absolute() and str((project / p).resolve()) == stale[0]
                        for p in choice['binding'])
                and wrapper_rel.parts and Path(stale[0]).parts[-len(wrapper_rel.parts):] == wrapper_rel.parts
                and binding[stale[0]] == actual[str(wrapper)]
                and hashlib.sha256(wrapper.read_bytes()).hexdigest() == actual[str(wrapper)]
                and {p: d for p, d in binding.items() if p != stale[0]}
                == {p: d for p, d in actual.items() if p != str(wrapper)}):
            try:
                if Path(stale[0]).exists() and hashlib.sha256(Path(stale[0]).read_bytes()).hexdigest() != binding[stale[0]]:
                    return refuse('declared prior wrapper source bytes changed')
            except OSError:
                return refuse('declared prior wrapper source could not be read')
            binding = dict(actual)
    if selected != spec['top'] and (not actual or binding != actual):
        return refuse('observation binding does not match the selected wrapper and model bytes')
    if binding:
        import hashlib
        try:
            for p, digest in binding.items():
                path = Path(p)
                # Project-owned inputs must still exist with the declared
                # bytes. External model sources may be available only through
                # the existing resolver; their exact staged bytes are checked
                # against `sources` above and in the execution plan.
                if path.is_relative_to(project.resolve()) or path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        return refuse(f'observation source bytes changed: {path}')
        except OSError:
            return refuse(f'observation source could not be read: {path}')
    return {'top': selected, 'clock': spec['clk'], 'output': spec['serial_out'],
            'clock_period_ns': period, 'sample_offset_ns': sample,
            'settle_ns': settle, 'binding': binding}, ''


def _required_reset_observation(project: Path, case: dict, spec: dict) -> Tuple[Optional[dict], List[Path], str]:
    """Read the existing D13 source decision; never derive reset values from RTL."""
    import hashlib
    authority = project / 'input/flow109/D13/source.json'
    if not authority.is_file():
        return None, [], ''
    source = _read_json(authority)
    requirements = source.get('scenario_requirements') if isinstance(source, dict) else None
    row = requirements.get(case.get('name') or case.get('id')) if isinstance(requirements, dict) else None
    observation = row.get('reset_observation') if isinstance(row, dict) else None
    if not isinstance(observation, dict):
        return None, [], 'required reset observation is missing'
    if (observation.get('clock') != spec['clk'] or observation.get('edge') != 'rising'
            or observation.get('reset') != spec['rst']
            or type(observation.get('active_level')) is not int
            or observation['active_level'] != int(not spec['reset_active_low'])
            or not isinstance(observation.get('observation'), str) or not observation['observation'].strip()):
        return None, [], 'reset observation clock, polarity or sampling scope is unsupported'
    files = [authority]
    for key in ('source_reference', 'original_requirement_reference'):
        reference = observation.get(key)
        if (not isinstance(reference, dict) or not isinstance(reference.get('path'), str)
                or not reference['path']):
            return None, [], 'reset observation reference is missing'
        path = project / reference['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != reference.get('sha256'):
            return None, [], 'reset observation reference is stale or unavailable'
        files.append(path)
    rtl = {p.resolve() for ext in ('*.v', '*.sv') for p in _pl.rtl_dir(project).rglob(ext)}
    if files[1].resolve() not in rtl:
        return None, [], 'reset observation source is outside the compiled RTL population'
    required = observation.get('required_observations')
    if not isinstance(required, list) or not required:
        return None, [], 'required reset observation population is empty'
    names = set()
    for item in required:
        if (not isinstance(item, dict) or set(item) != {'state', 'width', 'expected_value'}
                or not isinstance(item.get('state'), str)
                or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', item['state']) is None
                or item['state'] in names or type(item.get('width')) is not int or item['width'] < 1
                or type(item.get('expected_value')) is not int or item['expected_value'] < 0
                or item['expected_value'].bit_length() > item['width']):
            return None, [], 'required reset observation population is malformed'
        names.add(item['state'])
    return observation, files, ''


def arithmetic_scenario_plan(project: Path, ic_class: Optional[str], case: dict,
                             *, request: Optional[dict] = None,
                             observation_top: Optional[str] = None,
                             observation_sources: Optional[dict] = None) -> Optional[dict]:
    """Supported L10 scope plus declared framing/rearm, without alignment search."""
    import hashlib
    spec, why = extract_serial_arith_spec(project, ic_class)
    intent = _arithmetic_scenario_intent(case, (spec['parallel'], spec['serial_in']) if spec else ())
    families = [k for k in ('operand_boundaries', 'consecutive_transactions', 'reset_situations') if intent[k]]
    # A random serial arithmetic row is the same fixed interface obligation;
    # its population is declared by that row, never found by framing search.
    random_vectors = bool(spec is not None and not families and intent['random_transactions'])
    if random_vectors:
        families = ['random_transactions']
    if not families:
        return None
    required_choices = {}; required_population = None

    def defer(reason: str) -> None:
        if request is not None:
            request.update(case=case.get('name') or case.get('id'), verdict='NOT_MEASURED',
                           fallback_skill='testbench-gen', scenario_families=families,
                           required_choices=required_choices, required_population=required_population,
                           unsupported_requirements=[reason] if reason else [],
                           authored_tb=f"phase2/stage1/sim/tb/{case.get('name') or case.get('id')}.v")

    if spec is None or spec.get('other_inputs'):
        defer(why if spec is None else 'unmodeled input roles')
        return None
    declared = _read_json(project / 'plugin_output/declaration.json') or {}
    if declared.get('integer_encoding') not in ('unsigned', 'signed', 'signed_2c'):
        defer('explicit integer encoding is required')
        return None
    conv = read_declared_conventions(project, spec['ports'])
    choices = conv or declared
    if choices.get('transaction_rearm') not in ('clocked_reset', 'continuous'):
        required_choices['transaction_rearm'] = {'type': 'string', 'allowed': ['clocked_reset', 'continuous']}
    if (type(choices.get('rearm_reset_cycles')) is not int
            or not 1 <= choices['rearm_reset_cycles'] <= 16):
        required_choices['rearm_reset_cycles'] = {'type': 'integer', 'minimum': 1, 'maximum': 16}
    if choices.get('parallel_hold') != 'through_final_product_bit':
        required_choices['parallel_hold'] = {'type': 'string', 'allowed': ['through_final_product_bit']}
    # Read a designer's explicit count, never turn a generic sample into it.
    count = declared_vector_population(intent['case']) if (intent['consecutive_transactions'] or random_vectors) else None
    if random_vectors and count is not None and count > MAX_CASE_VECTORS:
        defer('declared random population exceeds supported per-case vector capacity')
        return None
    minimum = max(2, count or 2)
    population_path = f"verification_stimuli.arithmetic_scenarios.{case.get('name') or case.get('id')}.transaction_count"
    stimuli = declared.get('verification_stimuli') or {}
    populations = stimuli.get('arithmetic_scenarios', {}) if isinstance(stimuli, dict) else None
    selected = populations.get(case.get('name') or case.get('id'), {}) if isinstance(populations, dict) else None
    malformed = selected is None or not isinstance(selected, dict)
    if isinstance(selected, dict) and 'transaction_count' in selected:
        chosen = selected['transaction_count']
        malformed = type(chosen) is not int or not minimum <= chosen <= MAX_CASE_VECTORS
        if not malformed:
            count = chosen
    if intent['consecutive_transactions'] and (malformed or count is None or not minimum <= count <= MAX_CASE_VECTORS):
        required_population = {'type': 'integer', 'minimum': minimum, 'maximum': MAX_CASE_VECTORS,
                               'declaration_path': population_path}
    if required_choices or required_population:
        defer('')
        return None
    if not conv or not spec.get('rst'):
        defer('declared framing and reset role are required')
        return None
    observation, why = arithmetic_observation(project, spec, top=observation_top,
                                              sources=observation_sources)
    if observation is None:
        defer('MISSING_OBSERVATION_CONTRACT: ' + why)
        if request is not None:
            request['reason_class'] = 'MISSING_OBSERVATION_CONTRACT'
        return None
    width = spec['width']; latency = conv['settled_latency']
    if not 4 <= width <= 64 or latency > 2 * width:
        defer('width or settled latency outside supported scenario range')
        return None
    # Continuous transactions can be generated without an unstated idle or
    # parallel-operand overlap only at zero settled latency.
    if conv['transaction_rearm'] == 'continuous' and latency != 0:
        defer('continuous rearm requires zero settled latency')
        return None
    l9 = _read_json(_pl.generated_docs_dir(project) / 'L9_INTEGRATION_SPEC.json') or {}
    l9 = l9.get('fields') or l9
    resets = l9.get('reset_domains') or l9.get('resets') or []
    if not any(r.get('name') == spec['rst'] and str(r.get('sync', '')).lower()
               in ('sync', 'synchronous') for r in resets if isinstance(r, dict)):
        defer('synchronous reset declaration is required')
        return None
    text = intent['text']
    # These scopes are exercised differently; unknown scope keeps the original
    # expert handoff. A generic arithmetic result is never renamed a scenario.
    populations = []
    if random_vectors:
        populations.append(('random_transactions',
                            select_operand_pairs(spec, 'random', min_vectors=count)))
    if intent['operand_boundaries']:
        corners = {0, 1, (1 << width) - 1}
        if spec['signed']:
            corners.update({(1 << (width - 1)) - 1, 1 << (width - 1)})
        corners.update(named_corner_values(intent['case'], width))
        populations.append(('operand_boundaries',
                            [(a, b) for a in sorted(corners) for b in sorted(corners)]))
    if intent['consecutive_transactions']:
        populations.append(('consecutive_transactions',
                            select_operand_pairs(spec, 'mixed', min_vectors=count)))
    if intent['reset_situations']:
        if not intent['reset_complete']:
            defer('reset scope must state held, released and asserted during computation')
            return None
        populations.append(('reset_situations', select_operand_pairs(spec, 'corners')))
    if not populations:
        return None
    if re.search(r'asynchronous|different\s+clock|power\s+(?:on|off)', text):
        defer('unmodeled asynchronous reset, clock or power scope')
        return None
    reset_observation = None
    reset_files = []
    if intent['reset_situations']:
        reset_observation, reset_files, reset_why = _required_reset_observation(project, case, spec)
        if reset_why or (reset_observation and observation.get('postlayout_deadline')):
            defer(reset_why or 'internal reset observation requires the declared RTL surface')
            return None
    files = [*reset_files, *_pl.generated_docs_dir(project).glob('L2*.json'),
             _pl.generated_docs_dir(project) / 'L9_INTEGRATION_SPEC.json',
             _pl.generated_docs_dir(project) / 'L10_TEST_CASES.json',
             project / 'plugin_output/declaration.json',
             *sorted(_pl.rtl_dir(project).rglob('*.v')),
             *sorted(_pl.rtl_dir(project).rglob('*.sv'))]
    if any(not p.is_file() for p in files):
        defer('current scenario input or DUT file is missing')
        return None
    binding = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    pairs = []; phases = []
    for kind, selected in populations:
        multiplier = 9 if kind == 'reset_situations' else 1
        phases.append({'scenario': kind, 'first_vector': len(pairs),
                       'vectors': len(selected), 'transactions': len(selected) * multiplier,
                       'comparisons': len(selected) * multiplier * width})
        pairs.extend(selected)
    kind = phases[0]['scenario'] if len(phases) == 1 else 'combined_scenarios'
    plan = {'schema': 'vibeic.arithmetic_scenario.v1', 'case': case.get('name') or case.get('id'),
            'scenario': kind, 'case_sha256': hashlib.sha256(json.dumps(
                case, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'binding': binding, 'spec': spec, 'pairs': pairs,
            'framing': conv, 'observation': observation, 'latency_origin': SERIAL_LATENCY_ORIGIN,
            'transactions': sum(p['transactions'] for p in phases),
            'comparisons': sum(p['comparisons'] for p in phases)}
    if len(phases) > 1:
        plan['populations'] = phases
    if reset_observation is not None:
        plan['reset_observation'] = reset_observation
    return plan


def mapped_reset_state_targets(plan: dict, netlist_text: str, core_instance: str,
                               *, synthesis: Optional[dict] = None,
                               source_text: str = '', liberty_text: str = '',
                               wrapper_text: str = '', pad_instances: Optional[dict] = None,
                               port_map: Optional[dict] = None) -> dict:
    """Bind retained state; refuse unproved constants or output-register aliases.

    A removed bit needs a constant D cone in the selected synthesis record.
    An output alias needs a direct source assignment and a unique mapped Q
    path through Liberty identity buffers and the declared output pad.
    Required widths, expected values and the port comparator remain intact.
    """
    from _hdl_code_text import strip_hdl_comments_and_strings
    required = (plan.get('reset_observation') or {}).get('required_observations', [])
    if not required:
        return {}
    code = strip_hdl_comments_and_strings(netlist_text)
    top = plan['observation']['top']
    body = re.search(r'\bmodule\s+' + re.escape(top) + r'\b(.*?)\bendmodule\b',
                     code, re.DOTALL)
    if body is None:
        raise ValueError('RESET_STATE_MAPPING_UNMEASURED: selected module absent')
    targets, gaps = {}, []
    module = (synthesis or {}).get('modules', {}).get(top, {})

    def constant(bit, seen=(), *, state_output=False):
        if bit in ('0', '1'):
            return bit
        if bit in seen:
            return None
        drivers = [(cell, pin, bits.index(bit))
                   for cell in module.get('cells', {}).values()
                   for pin, bits in cell.get('connections', {}).items()
                   if cell.get('port_directions', {}).get(pin) == 'output' and bit in bits]
        if len(drivers) != 1:
            return None
        cell, pin, index = drivers[0]
        conns = cell['connections']
        if cell['type'] == '$mux' and pin == 'Y':
            a, b = (constant(conns[p][index], (*seen, bit)) for p in ('A', 'B'))
            return a if a == b else None
        # Unconditional DFF, not an enable, latch or async-control inference.
        if state_output and cell['type'] == '$dff' and pin == 'Q':
            return constant(conns['D'][index], (*seen, bit))
        return None

    def output_register(state):
        import sdf_gate_sim as sgs
        from reset_sync_structural_exception import _balanced_block, _output_pins
        source = strip_hdl_comments_and_strings(source_text)
        selected = re.search(r'\bmodule\s+' + re.escape(plan['spec']['top'])
                             + r'\b(.*?)\bendmodule\b', source, re.DOTALL)
        if selected is None or re.search(r'\breg\s+' + re.escape(state) + r'\b', selected.group(1)) is None:
            return None
        source = selected.group(1)
        aliases = re.findall(r'\bassign\s+([A-Za-z_][\w$]*)\s*=\s*'
                             + re.escape(state) + r'\s*;', source)
        outputs = {p['name'] for p in plan['spec']['ports'] if p['dir'] == 'output'}
        aliases = [p for p in aliases if p in outputs and p in (port_map or {})]
        if len(aliases) != 1:
            return None
        # Read identity functions and driver directions from the actual library.
        roles, identities = {}, {}
        for cell in re.finditer(r'\bcell\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', liberty_text):
            block = _balanced_block(liberty_text, cell.end() - 1)
            pins, funcs = {}, {}
            for pin in re.finditer(r'\bpin\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', block):
                text = _balanced_block(block, pin.end() - 1)
                direction = re.search(r'\bdirection\s*:\s*"?(input|output|inout)\b', text)
                function = re.search(r'\bfunction\s*:\s*"\s*([A-Za-z_][\w$]*)\s*"', text)
                if direction:
                    pins[pin.group(1)] = direction.group(1)
                if function:
                    funcs[pin.group(1)] = function.group(1)
            roles[cell.group(1)] = pins
            if not re.search(r'\b(?:ff|latch|ff_bank|latch_bank)\s*\(', block):
                identities[cell.group(1)] = {p: f for p, f in funcs.items()
                    if pins.get(p) == 'output' and pins.get(f) == 'input'
                    and [n for n, d in pins.items() if d == 'input'] == [f]}
        q_pins = _output_pins(liberty_text)
        insts = sgs._instances(body.group(1))
        wrapper = sgs._instances(strip_hdl_comments_and_strings(wrapper_text))
        norm = lambda net: re.sub(r'\s+', '', net).lstrip('\\')
        drivers = {}
        for name, (master, conns) in insts.items():
            for pin, net in conns.items():
                if pin == (pad_instances or {}).get(name, {}).get('core_pin'):
                    continue  # the declared output pad consumes this core net
                if master not in roles or roles[master].get(pin) in ('output', 'inout'):
                    drivers.setdefault(norm(net), []).append((name, master, pin, conns))
        net = (port_map or {})[aliases[0]]
        visited, crossed_pad = set(), False
        while norm(net) not in visited:
            visited.add(norm(net))
            if any(norm(lhs) == norm(net) for lhs in re.findall(
                    r'\bassign\s+([^=;]+)=', body.group(1))):
                return None
            # The existing chip-top record declares the IO terminal and core pin.
            pads = [(n, p) for n, p in (pad_instances or {}).items()
                    if n in insts and n in wrapper and insts[n][0] == wrapper[n][0]
                    and norm(insts[n][1].get(p.get('terminal'), '')) == norm(net)]
            if pads and not crossed_pad and len(pads) == 1:
                name, pad = pads[0]
                if any(d[0] != name for d in drivers.get(norm(net), [])):
                    return None
                net = insts[name][1].get(pad.get('core_pin'), '')
                crossed_pad = True
                continue
            hits = drivers.get(norm(net), [])
            if len(hits) != 1:
                return None
            _, master, pin, conns = hits[0]
            if pin in q_pins.get(master, set()):
                return 'dut.' + net.strip() + ' '
            input_pin = identities.get(master, {}).get(pin)
            if input_pin is None:
                return None
            net = conns.get(input_pin, '')
        return None

    for row in required:
        name = core_instance + '/' + row['state']
        matches = re.findall(r'\b(?:wire|reg|logic)\s+(?:signed\s+)?'
                             r'(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?'
                             + re.escape('\\' + name) + r'\s+(?:=[^;]*)?;', body.group(1))
        widths = [abs(int(a) - int(b)) + 1 if a else 1 for a, b in matches]
        if widths == [row['width']]:
            targets[row['state']] = 'dut.\\' + name + ' '
            continue
        bits = module.get('netnames', {}).get(core_instance + '.' + row['state'], {}).get('bits', [])
        # Only missing high bits of an unambiguously retained [k:0] vector.
        if (len(matches) == 1 and matches[0][1] == '0' and len(bits) == row['width']
                and widths[0] < row['width']):
            removed = [constant(b, state_output=True) for b in bits[widths[0]:]]
            expected = format(row['expected_value'], f"0{row['width']}b")[:len(removed)]
            if all(b in ('0', '1') for b in removed) and ''.join(reversed(removed)) == expected:
                targets[row['state']] = ("{" + f"{len(removed)}'b{expected}, "
                                          + 'dut.\\' + name + ' }')
                continue
        if not widths and row['width'] == 1:
            alias = output_register(row['state'])
            if alias is not None:
                targets[row['state']] = alias
                continue
        gaps.append(f"{row['state']}: required width {row['width']}, retained {widths}; "
                    'constant or unique output-register proof unavailable')
    if gaps:
        raise ValueError('RESET_STATE_MAPPING_UNMEASURED: ' + '; '.join(gaps))
    return targets


def emit_arithmetic_scenario_module(module_name: str, plan: dict, *,
                                    dut_module: Optional[str] = None) -> str:
    """One fixed declared window; independent golden for every scenario bit."""
    spec = plan['spec']; framing = plan['framing']; n = spec['width']
    par, sin, sout, clk, rst = (spec[k] for k in
                               ('parallel', 'serial_in', 'serial_out', 'clk', 'rst'))
    latency = framing['settled_latency']; pairs = plan['pairs']
    random_vectors = plan['scenario'] == 'random_transactions'
    observation = plan['observation']
    deadline = bool(observation.get('postlayout_deadline'))
    half = format(observation['clock_period_ns'] / 2, '.12g')
    sample = format(observation['sample_offset_ns'], '.12g')
    on, off = (0, 1) if spec['reset_active_low'] else (1, 0)
    rearm = int(framing['transaction_rearm'] == 'clocked_reset')
    reset_cycles = framing['rearm_reset_cycles']
    lsb = framing['bit_order'] == 'LSB'
    # A 10000-pair plan exceeds native lexer comment-line limits. Keep the
    # exact JSON as short comment chunks; the same reader joins them losslessly.
    encoded_plan = json.dumps(plan, sort_keys=True)
    headers = ([ARITHMETIC_SCENARIO_HEADER + encoded_plan[i:i+2048]
                for i in range(0, len(encoded_plan), 2048)] if random_vectors or len(encoded_plan) > 2048
               else [ARITHMETIC_SCENARIO_HEADER + encoded_plan])
    lines = ['`timescale 1ns/1ps', *headers,
             f'module {module_name};', f'localparam integer N={n}, NV={len(pairs)}, L={latency};']
    for p in spec['ports']:
        width = n if p['name'] == par else int(p.get('numeric_width') or 1)
        lines.append(f"{'reg' if p['dir'] == 'input' else 'wire'} "
                     f"{'['+str(width-1)+':0] ' if width > 1 else ''}{p['name']};")
    # A gate-level adapter may retain the logical module as a temporary
    # placeholder for its declared pad-port binder. The observation/header
    # still identifies the physical surface whose schedule was validated.
    lines += [f"{dut_module or observation['top']} dut (" + ', '.join(f".{p['name']}({p['name']})" for p in spec['ports']) + ');',
              f'initial {clk}=0; always #{half} {clk}=~{clk};',
              'reg [N-1:0] av[0:NV-1], bv[0:NV-1], gv[0:NV-1];',
              'integer errors=0, comparisons=0, transactions=0, held_edges=0;',
              'integer vi,k,h,a; reg held_value;']
    if deadline:
        # The driver retains every original negedge. Automatic observer args
        # snapshot the expected bit/window before the driver advances. Required
        # time is a conformance deadline, not a promise that the model settles.
        lines += ['integer pending_observers=0;',
                  'integer passed_transactions=0, prior_errors;',
                  'task automatic begin_transaction; begin',
                  f' #{sample}; prior_errors=errors; pending_observers=pending_observers-1;',
                  'end endtask',
                  'task automatic observe_hold(input integer hold_index); begin',
                  f' #{sample};',
                  f" if ({sout} !== 1'b0 && {sout} !== 1'b1) errors=errors+1;",
                  f' if(hold_index>0 && {sout} !== held_value) errors=errors+1;',
                  f' held_value={sout}; held_edges=held_edges+1;',
                  ' pending_observers=pending_observers-1;', 'end endtask',
                  'task automatic observe_product(input integer bit_index,input expected_bit); begin',
                  f' #{sample};', ' if(bit_index>=L) begin',
                  f'  if({sout} !== expected_bit) begin', '   errors=errors+1;',
                  f'   $display("FAIL: {module_name} fixed-window bit=%0d",bit_index-L);',
                  '  end', '  comparisons=comparisons+1;', ' end',
                  ' if(bit_index==N+L-1) begin', '  transactions=transactions+1;',
                  '  if(errors==prior_errors) passed_transactions=passed_transactions+1;',
                  ' end', ' pending_observers=pending_observers-1;', 'end endtask',
                  'task clear_state(input integer holds); begin',
                  f" {rst}=1'b{on}; {sin}=0; {par}=0;",
                  ' for(h=0;h<holds;h=h+1) begin', f'  @(posedge {clk});',
                  '  pending_observers=pending_observers+1;',
                  '  fork observe_hold(h); join_none', f'  @(negedge {clk});',
                  ' end', f" {rst}=1'b{off};", 'end endtask',
                  'task compare_transaction(input integer v,input integer reset_first,input integer pulse); begin',
                  ' pending_observers=pending_observers+1;',
                  ' fork begin_transaction(); join_none',
                  f' if(reset_first) clear_state({reset_cycles});', f' {par}=av[v];',
                  ' for(k=0;k<N+L;k=k+1) begin',
                  f"  {sin}=(k<N) ? bv[v][{'k' if lsb else 'N-1-k'}] : 0;",
                  f"  if(pulse>0 && k==pulse) begin {rst}=1'b{on}; #1; {rst}=1'b{off}; #1; end",
                  f'  @(posedge {clk});', '  pending_observers=pending_observers+1;',
                  f"  fork observe_product(k,gv[v][{'k-L' if lsb else 'N-1-(k-L)'}]); join_none",
                  f'  @(negedge {clk});', ' end', 'end endtask',
                  'task interrupted(input integer v,input integer position,input integer holds); begin',
                  f' {par}=~av[v];', ' for(a=0;a<position;a=a+1) begin',
                  f"  {sin}=~bv[v][{'a' if lsb else 'N-1-a'}];",
                  f'  @(posedge {clk}); @(negedge {clk});', ' end',
                  ' clear_state(holds); compare_transaction(v,0,0);', 'end endtask',
                  'initial begin']
    else:
        lines += ['task clear_state(input integer holds); begin',
                  f" {rst}=1'b{on}; {sin}=0; {par}=0;",
                  ' for(h=0;h<holds;h=h+1) begin', f'  @(posedge {clk}); #{sample};',
                  f"  if ({sout} !== 1'b0 && {sout} !== 1'b1) errors=errors+1;",
                  f'  if(h>0 && {sout} !== held_value) errors=errors+1;',
                  f'  held_value={sout}; held_edges=held_edges+1; @(negedge {clk});',
                  ' end', f" {rst}=1'b{off};", 'end endtask',
                  'task compare_transaction(input integer v,input integer reset_first,input integer pulse); begin',
                  f' if(reset_first) clear_state({reset_cycles});', f' {par}=av[v];',
                  ' for(k=0;k<N+L;k=k+1) begin',
                  f"  {sin}=(k<N) ? bv[v][{'k' if lsb else 'N-1-k'}] : 0;",
                  f"  if(pulse>0 && k==pulse) begin {rst}=1'b{on}; #1; {rst}=1'b{off}; #1; end",
                  f'  @(posedge {clk}); #{sample};', '  if(k>=L) begin',
                  f"   if({sout} !== gv[v][{'k-L' if lsb else 'N-1-(k-L)'}]) begin",
                  '    errors=errors+1;', f'    $display("FAIL: {module_name} fixed-window bit=%0d",k-L);',
                  '   end', '   comparisons=comparisons+1;', '  end',
                  f'  @(negedge {clk});', ' end', ' transactions=transactions+1;', 'end endtask',
                  'task interrupted(input integer v,input integer position,input integer holds); begin',
                  f' {par}=~av[v];', ' for(a=0;a<position;a=a+1) begin',
                  f"  {sin}=~bv[v][{'a' if lsb else 'N-1-a'}];",
                  f'  @(posedge {clk}); #{sample}; @(negedge {clk});', ' end',
                  ' clear_state(holds); compare_transaction(v,0,0);', 'end endtask',
                  'initial begin']
    if random_vectors and not deadline:
        lines.insert(lines.index('task clear_state(input integer holds); begin'),
                     'integer passed_transactions=0, prior_errors;')
        task_start = lines.index('task compare_transaction(input integer v,input integer reset_first,input integer pulse); begin')
        lines.insert(task_start + 1, ' prior_errors=errors;')
        task_end = lines.index(' transactions=transactions+1;')
        lines.insert(task_end + 1, ' if(errors==prior_errors) passed_transactions=passed_transactions+1;')
    for p in spec['ports']:
        if p['dir'] == 'input' and p['name'] != clk:
            lines.append(f" {p['name']}=0;")
    lines.append(f" {rst}=1'b{on};")
    for i, (a, b) in enumerate(pairs):
        lhs, rhs = (a, b) if spec.get('parallel_is_lhs', True) else (b, a)
        golden = compute_golden(spec['operator'], lhs, rhs, n, spec['signed'])
        lines.append(f" av[{i}]={n}'d{_twos(a,n)}; bv[{i}]={n}'d{_twos(b,n)}; gv[{i}]={n}'d{golden};")
    phases = plan.get('populations') or [{'scenario': plan['scenario'],
                                       'first_vector': 0, 'vectors': len(pairs)}]
    if plan.get('populations'):
        # Same case and comparator tasks, with actual per-family populations.
        if deadline:
            count = len(phases)
            tasks = [f'integer phase_transactions[0:{count-1}],phase_comparisons[0:{count-1}],phase_errors[0:{count-1}];',
                     'task automatic phase_begin(input integer phase_id); begin',
                     f' #{sample}; phase_transactions[phase_id]=transactions;',
                     ' phase_comparisons[phase_id]=comparisons; phase_errors[phase_id]=errors;',
                     ' pending_observers=pending_observers-1;', 'end endtask',
                     'task automatic phase_end(input integer phase_id); begin', f' #{sample};',
                     ' case(phase_id)']
            for i, phase in enumerate(phases):
                tasks += [f'{i}: $display("ARITH_SCENARIO_POPULATION family={phase["scenario"]} transactions=%0d comparisons=%0d errors=%0d",',
                          ' transactions-phase_transactions[phase_id],comparisons-phase_comparisons[phase_id],errors-phase_errors[phase_id]);']
            tasks += [' endcase', ' pending_observers=pending_observers-1;', 'end endtask']
            lines[lines.index('initial begin'):lines.index('initial begin')] = tasks
        else:
            lines.insert(lines.index('initial begin'),
                         'integer phase_transactions,phase_comparisons,phase_errors;')
    lines.append(f' @(negedge {clk}); clear_state({reset_cycles});')
    for phase_index, phase in enumerate(phases):
        if deadline and plan.get('populations'):
            lines += [' pending_observers=pending_observers+1;',
                      f' fork phase_begin({phase_index}); join_none',
                      f' clear_state({reset_cycles});']
        elif plan.get('populations'):
            lines += [' phase_transactions=transactions; phase_comparisons=comparisons;',
                      f' phase_errors=errors; clear_state({reset_cycles});']
        first = phase['first_vector']; last = first + phase['vectors']
        lines.append(' for(vi=0;vi<NV;vi=vi+1) begin' if not plan.get('populations')
                     else f' for(vi={first};vi<{last};vi=vi+1) begin')
        if phase['scenario'] == 'reset_situations':
            for position in (1, n // 2, n - 1):
                for holds in (1, 3):
                    lines += [f' clear_state({reset_cycles}); interrupted(vi,{position},{holds});']
            for pulse in (1, n // 2, n - 1):
                lines += [f' clear_state({reset_cycles}); compare_transaction(vi,0,{pulse});']
        else:
            lines.append(f' compare_transaction(vi,{rearm},0);')
        lines.append(' end')
        if deadline and plan.get('populations'):
            lines += [' pending_observers=pending_observers+1;',
                      f' fork phase_end({phase_index}); join_none']
        elif plan.get('populations'):
            lines += [f'$display("ARITH_SCENARIO_POPULATION family={phase["scenario"]} transactions=%0d comparisons=%0d errors=%0d",',
                      ' transactions-phase_transactions,comparisons-phase_comparisons,errors-phase_errors);']
    if deadline:
        lines.append(' wait(pending_observers==0);')
    if random_vectors:
        order = 0 if lsb else 1
        lines += ['$display("ORACLE_TB_DONE pass=%0d/%0d", passed_transactions,transactions);',
                  f' if(!errors) $display("ORACLE_TB_FRAMING in_order={order} out_order={order} latency_cycles={latency} latency_origin={SERIAL_LATENCY_ORIGIN}");']
    lines += ['$display("ARITH_SCENARIO_DONE transactions=%0d comparisons=%0d errors=%0d held_edges=%0d",'
              ' transactions,comparisons,errors,held_edges);',
              f' if(errors) $fatal(1,"FAIL: {module_name} scenario comparator");',
              f' $display("[TB {module_name}] PASS: declared arithmetic scenario");', '$finish;', 'end endmodule']
    required_reset = (plan.get('reset_observation') or {}).get('required_observations', [])
    if required_reset:
        declarations, checks, summaries = [], [], []
        for index, required in enumerate(required_reset):
            state, width, expected = (required[k] for k in ('state', 'width', 'expected_value'))
            samples, mismatches = f'reset_samples_{index}', f'reset_mismatches_{index}'
            target = observation.get('reset_state_targets', {}).get(state, f'dut.{state}')
            declarations.append(f'integer {samples}=0, {mismatches}=0;')
            checks += [f'  {samples}={samples}+1;',
                       f"  if($bits({target})!={width} || {target} !== {width}'h{expected:x}) begin",
                       f'   {mismatches}={mismatches}+1; errors=errors+1;',
                       f'   $display("FAIL: reset expected state {state}");', '  end']
            summaries.append(f'$display("ARITH_RESET_OBSERVATION state={state} width={width} expected={expected} samples=%0d mismatches=%0d", {samples},{mismatches});')
        slot = next(i for i, line in enumerate(lines) if line.startswith('task '))
        lines[slot:slot] = declarations
        slot = next(i for i, line in enumerate(lines) if f'held_value={sout}; held_edges=' in line)
        lines[slot:slot] = checks
        slot = next(i for i, line in enumerate(lines) if 'ARITH_SCENARIO_DONE transactions=' in line)
        lines[slot:slot] = summaries
    return '\n'.join(lines) + '\n'


def _scenario_header(tb: Path) -> Optional[dict]:
    try:
        encoded = ''.join(l[len(ARITHMETIC_SCENARIO_HEADER):]
                          for l in tb.read_text().splitlines()
                          if l.startswith(ARITHMETIC_SCENARIO_HEADER))
        plan = json.loads(encoded)
        return plan if isinstance(plan, dict) and plan.get('schema') == 'vibeic.arithmetic_scenario.v1' else None
    except (OSError, ValueError, StopIteration):
        return None


def capture_arithmetic_scenario_execution(project: Path, tb: Path, transcript: Path,
                                           sources: dict) -> Tuple[Optional[dict], str]:
    """Capture actual comparisons; absence never creates scenario credit."""
    import hashlib
    plan = _scenario_header(tb)
    if not plan:
        return None, 'NOT_MEASURED: no supported arithmetic scenario plan'
    try:
        raw = transcript.read_bytes()
    except OSError:
        return None, 'NOT_MEASURED: no arithmetic scenario transcript'
    matches = re.findall(rb'^ARITH_SCENARIO_DONE transactions=(\d+) comparisons=(\d+) errors=(\d+) held_edges=(\d+)\r?$', raw, re.MULTILINE)
    if len(matches) != 1:
        return None, 'NOT_MEASURED: scenario comparison population incomplete or ambiguous'
    transactions, comparisons, errors, held = map(int, matches[0])
    populations = None; populations_complete = True
    if plan.get('populations'):
        populations = [{'scenario': family.decode(), 'transactions': int(tx),
                        'comparisons': int(cmp), 'errors': int(err)}
                       for family, tx, cmp, err in re.findall(
                           rb'^ARITH_SCENARIO_POPULATION family=(operand_boundaries|consecutive_transactions|reset_situations) transactions=(\d+) comparisons=(\d+) errors=(\d+)\r?$', raw, re.MULTILINE)]
        expected = [{k: p[k] for k in ('scenario', 'transactions', 'comparisons')}
                    for p in plan['populations']]
        observed = [{k: p[k] for k in ('scenario', 'transactions', 'comparisons')}
                    for p in populations]
        populations_complete = observed == expected
    framing = None; framing_complete = True
    if plan.get('scenario') == 'random_transactions':
        matches = re.findall(
            rb'^ORACLE_TB_FRAMING in_order=(\d+) out_order=(\d+) latency_cycles=(\d+) latency_origin=([a-z_]+)\r?$',
            raw, re.MULTILINE)
        declared = plan['framing']; order = 0 if declared['bit_order'] == 'LSB' else 1
        expected = (order, order, declared['settled_latency'], SERIAL_LATENCY_ORIGIN)
        observed = [(int(i), int(o), int(latency), origin.decode())
                    for i, o, latency, origin in matches]
        framing_complete = observed == [expected]
        if len(observed) == 1:
            framing = dict(zip(('in_order', 'out_order', 'latency_cycles', 'latency_origin'), observed[0]))
    measured = {'plan': plan, 'sources': sources, 'transcript': str(transcript),
                'transcript_sha256': hashlib.sha256(raw).hexdigest(),
                'transactions': transactions, 'comparisons': comparisons,
                'errors': errors, 'held_edges': held,
                'complete': transactions == plan['transactions'] and comparisons == plan['comparisons']
                            and populations_complete and framing_complete}
    if plan.get('scenario') == 'random_transactions':
        measured['framing'] = framing
    if populations is not None:
        measured['populations'] = populations
    if plan.get('reset_observation'):
        required = plan['reset_observation']['required_observations']
        rows = [{'state': state.decode(), 'width': int(width), 'expected_value': int(value),
                 'samples': int(samples), 'mismatches': int(mismatches)}
                for state, width, value, samples, mismatches in re.findall(
                    rb'^ARITH_RESET_OBSERVATION state=([A-Za-z_][A-Za-z0-9_$]*) width=(\d+) expected=(\d+) samples=(\d+) mismatches=(\d+)\r?$', raw, re.MULTILINE)]
        identities = [{k: row[k] for k in ('state', 'width', 'expected_value')} for row in rows]
        measured['reset_observations'] = rows
        measured['complete'] = (measured['complete'] and identities == required
                                and held > 0 and all(row['samples'] == held
                                    and 0 <= row['mismatches'] <= row['samples'] for row in rows)
                                and sum(row['mismatches'] for row in rows) <= errors)
    return measured, 'native declared scenario comparisons'


def arithmetic_scenario_case_state(row: dict) -> Tuple[str, str]:
    """Current generated scenario receipt, separate from generic TB provenance."""
    import hashlib
    measured = row.get('arithmetic_scenario')
    if not isinstance(measured, dict):
        return 'NOT_EXECUTED', 'generated generic oracle cannot measure a scenario'
    # A native comparator failure remains a measured failure.
    if type(measured.get('errors')) is int and measured['errors'] > 0:
        return 'FAIL', 'native arithmetic scenario comparator failed'
    plan = _scenario_header(Path(row.get('tb_file') or ''))
    if not plan or measured.get('plan') != plan or measured.get('complete') is not True:
        return 'NOT_EXECUTED', 'NOT_MEASURED: scenario plan/population incomplete'
    for path, digest in {**plan['binding'], **measured.get('sources', {})}.items():
        try:
            if not digest or hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                return 'NOT_EXECUTED', 'NOT_MEASURED: scenario input or DUT bytes changed'
        except OSError:
            return 'NOT_EXECUTED', 'NOT_MEASURED: scenario input or DUT missing'
    compiled = measured.get('sources') or {}
    rtl_paths = [p for p in plan['binding'] if Path(p).suffix in ('.v', '.sv')]
    if not rtl_paths or any(compiled.get(p) != plan['binding'][p] for p in rtl_paths):
        return 'NOT_EXECUTED', 'NOT_MEASURED: scenario DUT was not consumed by this compilation'
    try:
        raw = Path(measured['transcript']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != measured.get('transcript_sha256'):
            return 'NOT_EXECUTED', 'NOT_MEASURED: scenario transcript changed'
    except (OSError, KeyError):
        return 'NOT_EXECUTED', 'NOT_MEASURED: scenario transcript missing'
    observed, _ = capture_arithmetic_scenario_execution(
        Path(row['tb_file']).parent, Path(row['tb_file']), Path(measured['transcript']), compiled)
    if observed != measured:
        return 'NOT_EXECUTED', 'NOT_MEASURED: scenario observed population differs from receipt'
    return 'PASS', 'current native declared arithmetic scenario'


def case_oracle_options(spec: dict, case: "dict | None") -> Dict[str, Any]:
    """What the case's OWN text asks of its oracle: the pairs to drive and
    whether reset is asserted mid-computation. `{}` for no case (the historical
    sample)."""
    if not case:
        return {}
    width = int(spec.get("operand_a_width") or spec["width"])
    return {
        "min_vectors": declared_vector_population(case),
        "extra_corners": named_corner_values(case, width),
        "abort_before_each": (spec.get("topology") == "serial_parallel"
                              and bool(spec.get("rst"))
                              and reset_mid_computation_case(case)),
    }


def emit_case_oracle(project: Path, ic_class: Optional[str],
                     module_name: str, profile: str = "mixed",
                     case: "dict | None" = None) -> Optional[str]:
    """Emit ONE self-checking arithmetic oracle MODULE (serial-parallel or
    closed-form parallel) named `module_name`, or None when no closed-form
    oracle is derivable (fail-closed). The L10 per-case unit-TB producer
    (testbench_gen) calls this so each L10 `functional_vector` case gets genuine
    per-case golden evidence (a real drive+compare, NOT a substance-floor
    scaffold) that l10_tb_conformance can credit — the SAME chip-AGNOSTIC
    declared-function convention, keyed on interface shape."""
    sspec, _sr = extract_serial_arith_spec(project, ic_class)
    if sspec is not None:
        opts = case_oracle_options(sspec, case)
        return emit_serial_oracle_module(
            module_name, sspec,
            select_operand_pairs(sspec, profile,
                                 min_vectors=opts.get("min_vectors"),
                                 extra_corners=opts.get("extra_corners") or ()),
            abort_before_each=bool(opts.get("abort_before_each")))
    pspec, _pr = extract_arith_spec(project, ic_class)
    if pspec is not None:
        opts = case_oracle_options(pspec, case)
        pairs = None
        if opts.get("min_vectors") or opts.get("extra_corners"):
            pairs = select_operand_pairs(
                dict(pspec, width=int(pspec.get("operand_a_width")
                                      or pspec["width"])),
                profile, min_vectors=opts.get("min_vectors"),
                extra_corners=opts.get("extra_corners") or ())
        return _emit_tb(pspec, module_name=module_name, pairs=pairs)
    return None


def _emit_tb(spec: dict, module_name: "str | None" = None,
             pairs: "List[Tuple[int, int]] | None" = None) -> str:
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
    if pairs is None:
        pairs = (enumerate_operand_pairs(a_w, signed, operator) if a_w == b_w
                 else parallel_operand_pairs(spec, 64))
    role_w = {a_name: a_w, b_name: b_w, r_name: r_w}

    def _rng(w):
        return f" [{w - 1}:0]" if w > 1 else ""

    lines = ["`timescale 1ns/1ps",
             "// Auto-generated by arith_oracle_tb_gen (#745) — CLOSED-FORM "
             "arithmetic oracle TB",
             f"// operator '{operator}'  N={width}  "
             f"signed={str(signed).lower()}  operands [{a_w-1}:0]/[{b_w-1}:0] "
             f"result [{r_w-1}:0]  (FACET-2 #643: numeric-width operand decls)",
             f"module {module_name or ('tb_' + top + '_oracle')};"]
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
        golden = parallel_golden(spec, a, b)
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
    """Returns (verdict_dict, exit_code). 0 = TB emitted; 2 = DEFER.

    Tries the SERIAL-PARALLEL declared-function convention FIRST (the shape the
    closed-form combinational oracle DEFERS — a bit-serial operand/result with a
    DECLARED bit_order+latency), then the closed-form PARALLEL oracle, then
    DEFERs (fail-closed)."""
    serial_spec, serial_reason = extract_serial_arith_spec(project, ic_class)
    if serial_spec is not None:
        pairs = select_operand_pairs(serial_spec, "mixed")
        sim_dir = _pl.sim_full_stack_dir(project)
        sim_dir.mkdir(parents=True, exist_ok=True)
        tb_path = sim_dir / f"tb_{serial_spec['top']}_oracle.v"
        tb_path.write_text(emit_serial_oracle_module(
            f"tb_{serial_spec['top']}_oracle", serial_spec, pairs))
        manifest = {
            "program": "arith_oracle_tb_gen",
            "verdict": "TB_EMITTED",
            "topology": "serial_parallel",
            "tb": str(tb_path.relative_to(project)),
            "top": serial_spec["top"],
            "operator": serial_spec["operator"],
            "width": serial_spec["width"],
            "signed": serial_spec["signed"],
            "declared_bit_order": serial_spec.get("declared_bit_order"),
            "declared_latency": serial_spec.get("declared_latency"),
            "framing": "self-calibrated (in_order x out_order x offset search)",
            "parallel_operand": serial_spec["parallel"],
            "serial_operand": serial_spec["serial_in"],
            "serial_result": serial_spec["serial_out"],
            "vector_count": len(pairs),
            "source": ("serial-parallel declared-function convention: operator "
                       "from L2 function (golden computed independently); serial "
                       "framing self-calibrated from the DUT stream (#745 serial)"),
        }
        (sim_dir / "arith_oracle_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        return manifest, 0

    spec, reason = extract_arith_spec(project, ic_class)
    if spec is None:
        return ({
            "program": "arith_oracle_tb_gen",
            "verdict": "DEFER",
            "fallback_skill": "testbench-gen",
            "reason": reason,
            "serial_reason": serial_reason,
            "ic_class": ic_class,
            "capability_gap": "cap:cpu_functional_oracle",
        }, 2)

    tb_text = _emit_tb(spec)
    sim_dir = _pl.sim_full_stack_dir(project)
    sim_dir.mkdir(parents=True, exist_ok=True)
    tb_path = sim_dir / f"tb_{spec['top']}_oracle.v"
    tb_path.write_text(tb_text)
    n_vec = len(enumerate_operand_pairs(
        spec['operand_a_width'], spec['signed'], spec['operator'])) if (
        spec['operand_a_width'] == spec['operand_b_width']) else len(parallel_operand_pairs(spec, 64))
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
