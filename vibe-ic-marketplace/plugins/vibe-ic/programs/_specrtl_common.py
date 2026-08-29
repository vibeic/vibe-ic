#!/usr/bin/env python3
"""_specrtl_common.py — shared Spec↔RTL parsing primitives.

Single source of truth for the Spec↔RTL *contract conformance* family
(`spec_conformance_check.py`, `spec_rtl_port_fidelity_check.py`). A "spec
contract" is what the datasheet / L-docs / natural-language prompt *declares*
the design must be; the RTL must *conform* to it. This module extracts that
contract from prose/markdown/JSON and parses the matching facts out of RTL.

It is deliberately dependency-free (stdlib only) and chip-AGNOSTIC: every
matcher is structural (sensitivity lists, `if`-polarity, port declarations,
reset-mode keywords). No vendor / IC / SKU / signal-name literals.

Exposed:
  strip_comments(src)                      -> str
  Port(name, direction, width)             dataclass
  parse_rtl_ports(src, top)                -> (module_name, [Port])
  classify_rtl_resets(module_body)         -> {signal: {"mode":set,"polarity":set}}
  SpecContract(module, ports, reset, latency_registered)  dataclass
  extract_spec_contract(text)              -> SpecContract
  rtl_source_files(project_dir)            -> [Path]  (authored-RTL collector)
"""
from __future__ import annotations

import ast
import json
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# A port whose width could not be resolved to a concrete literal bit-count
# (a parameterized / symbolic bound like `[WB_AW-1:0]` that no in-module
# parameter resolves). It is UNKNOWN — NOT a literal 1 — so a width-equality
# check must SKIP it rather than assert a false mismatch. chip-AGNOSTIC.
WIDTH_UNKNOWN = 0


# ---------------------------------------------------------------------------
# Comment stripping (preserves newlines for line tracking)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        if src[i:i + 2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end + 2]))
            i = end + 2
        elif src[i:i + 2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


# ---------------------------------------------------------------------------
# AUTHORED-RTL source collection (shared by the strict-structural gate family)
# ---------------------------------------------------------------------------
# SCALE RATIONALE (first Kimi-scale run, 2026-07): the RTL-SOURCE structural
# gates (self_rx_mask_check, host_soft_reset_unwake_path_check,
# crc_completeness_check, crc_residual_check, handshake_check,
# bitwidth_consistency_check, rx_byte_valid_requires_ibt_gate_check) each
# collected Verilog by rglobbing the WHOLE project for *.v/*.sv (they run with
# cwd=<project>, arg "."). On a 3.1M-cell design the emitted GENERIC NETLISTS
# phase2/stage2/synth/netlist_yosys.v and netlist.v are 342 MB EACH; the
# gates' char-level comment strippers and regex passes then take >30 min per
# gate, and all 7 parallel gates were killed at the #525 900 s per-gate
# budget — an INCONCLUSIVE audit purely from pathological ingestion. These
# gates audit AUTHORED RTL SOURCE; an emitted netlist / sim build / verify
# tree is NEVER a legitimate input to them, so excluding those outputs
# narrows nothing they legitimately scan (§4.05-safe: on a small project the
# canonical rtl dir is what they effectively audited anyway).
#
# chip-AGNOSTIC + dependency-free: pathlib only, flow-stage directory names
# from the canonical runner layout (_path_layout), no chip/vendor/SKU literal.

# Verilog source suffixes the gate family collects (kept in lock-step with the
# per-gate `rglob("*.v") + rglob("*.sv")` calls this helper replaces).
RTL_SOURCE_EXTS: Tuple[str, ...] = ("*.v", "*.sv")

# Generated-output directory names (any path component below the project root)
# that hold EMITTED artefacts, never authored RTL source:
#   stage2/stage3/stage4/phase3 — synth / PnR / tapeout stage outputs
#   synth                       — netlist.v / netlist_yosys.v home
#   sim / sim_full_stack / sim_professional / verify — sim builds + benches
#   reports / _logs             — reports and logs (stray .v copies)
RTL_SOURCE_EXCLUDED_DIR_PARTS = frozenset({
    "stage2", "stage3", "stage4", "phase3",
    "sim", "sim_full_stack", "sim_professional", "verify",
    "reports", "_logs", "synth",
})

# Sanity cap for the FALLBACK (no canonical rtl dir) scan: no authored RTL
# source file is 342 MB — only flat machine-emitted netlists reach that size.
# 8 MB is far above any hand/LLM-authored module yet far below the smallest
# netlist that ever hurt (the #615 precedent used a 2 MB floor for the same
# distinction inside reset_dependency_check).
RTL_SOURCE_MAX_BYTES = 8 * 1024 * 1024


def rtl_source_files(project_dir,
                     exts: Tuple[str, ...] = RTL_SOURCE_EXTS) -> List[Path]:
    """Collect a project's AUTHORED RTL source files (*.v / *.sv).

    Contract:
      1. If ``<project>/phase2/stage1/rtl/`` — the canonical authored-RTL home
         (runner layout ``_path_layout.rtl_dir``) — exists and holds at least
         one *.v/*.sv file, ONLY that tree is scanned.
      2. Otherwise (legacy layouts, or the caller passed a bare RTL dir
         directly), rglob ``project_dir`` but EXCLUDE any file that sits under
         a generated-output directory (RTL_SOURCE_EXCLUDED_DIR_PARTS matched
         against the path components below ``project_dir``, filename itself
         excluded from the match) AND any file larger than
         RTL_SOURCE_MAX_BYTES.

    ``exts`` (Kimi-scale round 2): the glob patterns collected, default
    RTL_SOURCE_EXTS. Some family gates have always ALSO scanned header files
    (*.vh / *.svh — `define / parameter timing constants live there); they
    pass a widened tuple so adopting the shared collector never narrows the
    suffix set they legitimately audit (§4.05: dropping a `.vh` declaration
    could false-SKIP a real dead-constant / undocumented-latency finding).
    The canonical-dir preference, generated-dir exclusion, and size-cap
    contract are identical for every suffix.

    ``project_dir`` must be a directory; anything else returns []. Returned
    paths are descendants of ``project_dir`` exactly as the caller passed it
    (never resolve()d — gates run with cwd=<project> and report relative
    paths), sorted and de-duplicated. Single-FILE arguments stay the calling
    gate's own business — this helper is only the directory collector.
    """
    root = Path(project_dir)
    if not root.is_dir():
        return []
    canonical = root / "phase2" / "stage1" / "rtl"
    if canonical.is_dir():
        files = [p for ext in exts for p in canonical.rglob(ext)
                 if p.is_file()]
        if files:
            return sorted(set(files))
    out: List[Path] = []
    for ext in exts:
        for p in root.rglob(ext):
            if not p.is_file():
                continue
            try:
                rel_parts = p.relative_to(root).parts
            except ValueError:
                # e.g. root == Path('.'): rglob already yields bare relative
                # paths that do not textually start with '.', so the parts ARE
                # the relative parts.
                rel_parts = p.parts
            # Only DIRECTORY components below the root are matched ([:-1]) —
            # a design file merely NAMED `synth.v`/`verify.sv` is kept.
            if RTL_SOURCE_EXCLUDED_DIR_PARTS.intersection(rel_parts[:-1]):
                continue
            try:
                if p.stat().st_size > RTL_SOURCE_MAX_BYTES:
                    continue
            except OSError:
                continue
            out.append(p)
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
@dataclass
class Port:
    name: str
    direction: str   # input / output / inout
    width: int       # 1 for scalar
    # A spec port the INPUT DOCUMENT marks as optional (L9 emits `optional: true`
    # for a pin the datasheet offers rather than requires). Its absence from the
    # RTL is a design CHOICE, not a conformance defect — the same flag
    # l9_rtl_pin_consistency_check already honours. Defaults False so every
    # positional Port(...) construction keeps its current meaning.
    optional: bool = False


# The width bracket tolerates ANY range expression, not only a `\d+:\d+` literal
# range. A parameterized bus (`[INPUT_ADDR_WIDTH-1:0]`, `[(IN_ROW*IN_COL*W)-1:0]`,
# `[IN_DATA_WIDTH*IN_DATA_NS-1:0]`) failed the old digits-only bracket; the regex
# then backtracked, the type-keyword run (`logic`/`reg`/…) matched ZERO reps, and
# the NAME group captured the type keyword `logic` as a phantom port WHILE DROPPING
# the real parameterized port (ORGANIC-20260618 — exposed once the balanced
# `_module_port_region` reaches these ANSI headers). The bracket now matches
# `[ ... ]` (no inner `]`); the numeric WIDTH is extracted only when the range is a
# pure `<int>:<int>` literal, else width defaults to 1 (unknown). chip-AGNOSTIC.
_PORT_DECL = re.compile(
    r'\b(input|output|inout)\b\s*(?:reg|wire|logic|signed|unsigned|\s)*'
    r'(?:(\[[^\]]*\])\s*)?'
    r'([A-Za-z_]\w*(?:\s*,\s*(?!(?:input|output|inout)\b)[A-Za-z_]\w*)*)')
_LITERAL_RANGE = re.compile(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]')


# ---------------------------------------------------------------------------
# Parameter-aware width resolution
# ---------------------------------------------------------------------------
# A parameterized port bound (`[WB_AW-1:0]`, `[DATA_WIDTH*2-1:0]`,
# `[$clog2(DEPTH)-1:0]`) must NOT be parsed as width 1: that manufactures a
# false width-mismatch against a spec that states the resolved literal. Where
# the referenced parameter is declared in the SAME module we resolve it to the
# concrete bit-count; where it cannot be resolved the width is UNKNOWN
# (WIDTH_UNKNOWN), never a literal 1. chip-AGNOSTIC: pure Verilog param grammar
# + a whitelisted-operator arithmetic evaluator (no eval()).
_PARAM_ASSIGN = re.compile(
    r'\b(?:parameter|localparam)\b\s*'
    r'(?:\b(?:signed|unsigned|integer|int|time|logic|reg|bit|byte)\b\s*)*'
    r'(?:\[[^\]]*\]\s*)?'
    r'([A-Za-z_]\w*)\s*=\s*([^,;)\n]+)')

_SAFE_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.floordiv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.LShift: operator.lshift, ast.RShift: operator.rshift,
    ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.BitXor: operator.xor,
}
_SAFE_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg,
                  ast.Invert: operator.invert}


def _clog2(v: int) -> int:
    """Verilog $clog2 — ceil(log2(v)); $clog2(0)=$clog2(1)=0."""
    return (v - 1).bit_length() if v > 1 else 0


def _eval_ast_int(node, env: Dict[str, int]) -> Optional[int]:
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, int) and not isinstance(node.value, bool) else None
    if isinstance(node, ast.Name):
        v = env.get(node.id)
        return v if isinstance(v, int) else None
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
        l = _eval_ast_int(node.left, env)
        r = _eval_ast_int(node.right, env)
        if l is None or r is None:
            return None
        try:
            return int(_SAFE_BINOPS[type(node.op)](l, r))
        except (ZeroDivisionError, ValueError):
            return None
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARYOPS:
        v = _eval_ast_int(node.operand, env)
        return None if v is None else int(_SAFE_UNARYOPS[type(node.op)](v))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'clog2' and len(node.args) == 1):
        a = _eval_ast_int(node.args[0], env)
        return None if a is None else _clog2(a)
    return None


def _safe_eval_int(expr: str, env: Dict[str, int]) -> Optional[int]:
    """Evaluate a simple Verilog integer expression against a param env, using a
    whitelisted-operator AST walk (never eval()). Returns None if it references
    an unresolved name, uses an unsupported construct, or is a sized literal."""
    expr = re.sub(r'\$clog2', 'clog2', expr.strip())
    if not expr:
        return None
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return None
    return _eval_ast_int(tree.body, env)


def _parse_module_params(text: str) -> Dict[str, int]:
    """Resolve `parameter`/`localparam NAME = <expr>` to concrete ints, to a
    fixpoint so a later param can reference an earlier one. Sized-literal /
    unresolvable params are simply left out."""
    raw: Dict[str, str] = {}
    for m in _PARAM_ASSIGN.finditer(text):
        raw.setdefault(m.group(1), m.group(2).strip())
    resolved: Dict[str, int] = {}
    for _ in range(len(raw) + 1):
        progressed = False
        for name, expr in raw.items():
            if name in resolved:
                continue
            v = _safe_eval_int(expr, resolved)
            if v is not None:
                resolved[name] = v
                progressed = True
        if not progressed:
            break
    return resolved


def _resolve_bracket_width(bracket: str, params: Dict[str, int]) -> int:
    """Width of a `[hi:lo]` packed dimension, resolving parameter names via
    ``params``. Returns WIDTH_UNKNOWN when either bound cannot be resolved to a
    concrete int (e.g. an unresolved parameter, or a ternary/complex bound)."""
    inner = bracket.strip()
    if inner.startswith('['):
        inner = inner[1:]
    if inner.endswith(']'):
        inner = inner[:-1]
    # Exactly one colon separates msb:lsb; a ternary (`?:`) or multi-colon bound
    # is too complex to resolve statically → UNKNOWN (safe).
    if inner.count(':') != 1:
        return WIDTH_UNKNOWN
    hi_s, lo_s = inner.split(':', 1)
    hi = _safe_eval_int(hi_s, params)
    lo = _safe_eval_int(lo_s, params)
    if hi is None or lo is None:
        return WIDTH_UNKNOWN
    return abs(hi - lo) + 1


# function/task argument declarations use the same input/output keywords as module
# ports but are lexically scoped to the subprogram — blank their bodies (preserving
# newlines) before port extraction so they are not mistaken for module ports.
_SUBPROGRAM = re.compile(
    r'\bfunction\b.*?\bendfunction\b|\btask\b.*?\bendtask\b', re.S | re.I)


def _strip_subprograms(text: str) -> str:
    return _SUBPROGRAM.sub(
        lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group(0)), text)


def parse_verilog_ports(text: str,
                        params: Optional[Dict[str, int]] = None) -> List[Port]:
    """Parse Verilog `input/output/inout [msb:lsb] a, b` declarations.

    A NON-literal packed dimension (`[WB_AW-1:0]`) is resolved against ``params``
    (the module's own parameters) where possible; if it cannot be resolved the
    width is WIDTH_UNKNOWN, NEVER a literal 1. ``params`` defaults to the
    parameters parsed from ``text`` itself, so any caller that passes a full
    module / region gets parameter-aware widths with no signature change."""
    if params is None:
        params = _parse_module_params(text)
    ports: List[Port] = []
    for m in _PORT_DECL.finditer(text):
        direction = m.group(1)
        if m.group(2) is None:
            width = 1  # no packed dimension → genuine 1-bit scalar
        else:
            bracket = m.group(2).strip()
            lit = _LITERAL_RANGE.fullmatch(bracket)
            if lit:
                width = abs(int(lit.group(1)) - int(lit.group(2))) + 1
            else:
                # Parameterized / symbolic bound: resolve via params, else UNKNOWN.
                width = _resolve_bracket_width(bracket, params)
        for nm in re.split(r'\s*,\s*', m.group(3)):
            nm = nm.strip()
            if nm:
                ports.append(Port(nm, direction, width))
    return ports


def parse_rtl_ports(src: str, top: Optional[str]) -> Tuple[str, List[Port]]:
    """Return (module_name, ports) for the chosen/first module in RTL `src`."""
    mods = list(re.finditer(r'\bmodule\s+(\w+)\b', src))
    if not mods:
        return '', []
    chosen = None
    if top:
        for m in mods:
            if m.group(1) == top:
                chosen = m
                break
    chosen = chosen or mods[0]
    name = chosen.group(1)
    nxt = re.search(r'\bendmodule\b', src[chosen.end():])
    region = src[chosen.end():chosen.end() + (nxt.start() if nxt else len(src))]
    # Strip Verilog comments BEFORE the port-declaration scan: an ANSI header with
    # inline port comments (`// Clock input`, `// J input of the flip-flop`) makes
    # the _PORT_DECL regex match the comment word `input`/`output` and harvest the
    # following comment token as a phantom port, while consuming the next REAL
    # `input`/`output` keyword into the name group — injecting phantom ports and
    # DROPPING real ports (e.g. a dropped reset port collapses reset coverage to a
    # fixed fallback list that never matches the TB). chip-AGNOSTIC: Verilog comment
    # grammar only. Done first so _strip_subprograms then sees comment-free text.
    region = strip_comments(region)
    # Ignore input/output declarations inside function/task bodies (not module ports).
    region = _strip_subprograms(region)
    return name, parse_verilog_ports(region)


# ---------------------------------------------------------------------------
# Reset classification in RTL (per sequential always block)
# ---------------------------------------------------------------------------
_OPENERS = re.compile(r'\b(begin|case[zx]?|fork)\b')
_CLOSERS = re.compile(r'\b(end|endcase|join(?:_any|_none)?)\b')
_ALWAYS = re.compile(r'\balways(?:_ff)?\b')
_SENS = re.compile(r'@\s*\(([^)]*)\)', re.S)
_RST_EDGE = re.compile(r'\b(?:pos|neg)edge\s+(\w+)')
# Generic (chip-AGNOSTIC) reset-name shapes used only to gate SYNC-reset
# classification so an enable (`if(en)`) is never mistaken for a reset.
_RESET_NAME = re.compile(r'rst|reset|clr|clear|\bpor\b', re.I)


def _extract_block(src: str, after: int) -> Tuple[str, int]:
    m = re.compile(r'\S').search(src, after)
    if not m:
        return '', len(src)
    if not re.match(r'begin\b', src[m.start():]):
        semi = src.find(';', m.start())
        end = semi if semi != -1 else len(src)
        return src[m.start():end + 1], end + 1
    depth, pos, tok, last = 0, m.start(), re.compile(r'\b\w+\b'), len(src)
    while pos < last:
        t = tok.search(src, pos)
        if not t:
            break
        w = t.group(0)
        if _OPENERS.fullmatch(w):
            depth += 1
        elif _CLOSERS.fullmatch(w):
            depth -= 1
            if depth == 0:
                return src[m.start():t.end()], t.end()
        pos = t.end()
    return src[m.start():], len(src)


def _classify_polarity(cond: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse (reset_signal, polarity) from a reset `if` condition."""
    cond = cond.strip()
    m = re.match(r'^[!~]\s*(\w+)\s*$', cond)
    if m:
        return m.group(1), 'active-low'
    m = re.match(r'^(\w+)\s*==\s*1?\'?[bdh]?0+\s*$', cond) or \
        re.match(r"^(\w+)\s*==\s*0\s*$", cond)
    if m:
        return m.group(1), 'active-low'
    m = re.match(r'^(\w+)\s*==\s*1?\'?[bdh]?0*1\s*$', cond) or \
        re.match(r"^(\w+)\s*==\s*1\s*$", cond)
    if m:
        return m.group(1), 'active-high'
    m = re.match(r'^(\w+)\s*$', cond)
    if m:
        return m.group(1), 'active-high'
    return None, None


def classify_rtl_resets(body: str) -> Dict[str, Dict[str, Set[str]]]:
    """Per reset signal, the set of modes ('synchronous'/'asynchronous') and
    polarities ('active-high'/'active-low') it is used with across the module's
    sequential blocks."""
    out: Dict[str, Dict[str, Set[str]]] = {}
    pos = 0
    while True:
        am = _ALWAYS.search(body, pos)
        if not am:
            break
        sm = _SENS.search(body, am.end())
        if not sm or sm.start() > am.end() + 8:
            pos = am.end()
            continue
        edges = _RST_EDGE.findall(sm.group(1))
        if not edges:                       # not sequential
            pos = sm.end()
            continue
        block, end_pos = _extract_block(body, sm.end())
        ifm = re.search(r'\bif\s*\(([^)]*)\)', block)
        rst_sig, pol = (None, None)
        if ifm:
            rst_sig, pol = _classify_polarity(ifm.group(1))
        mode = None
        if rst_sig and rst_sig in edges:
            mode = 'asynchronous'
        elif (rst_sig and rst_sig not in edges and pol is not None and ifm
              and ifm.start() < 60 and _RESET_NAME.search(rst_sig)):
            mode = 'synchronous'
        if rst_sig and mode:
            rec = out.setdefault(rst_sig, {'mode': set(), 'polarity': set()})
            rec['mode'].add(mode)
            if pol:
                rec['polarity'].add(pol)
        pos = end_pos
    return out


# ---------------------------------------------------------------------------
# Spec contract extraction (prose / markdown / JSON  ->  declared intent)
# ---------------------------------------------------------------------------
@dataclass
class SpecContract:
    module: Optional[str] = None
    ports: List[Port] = field(default_factory=list)
    reset_mode: Optional[str] = None        # synchronous / asynchronous
    reset_polarity: Optional[str] = None    # active-high / active-low
    reset_signal: Optional[str] = None      # if the spec names it
    latency_registered: Optional[bool] = None
    fsm_output_style: Optional[str] = None  # 'moore'/'mealy' if the spec declares one
    source: str = ''                        # how ports were parsed: nl/verilog/json/md-table
    # LLM double-confirm records for the prose-inferred SEMANTIC fields above
    # (asdict of llm_semantic_confirm.Confirmation). Empty when no semantic field
    # was declared or no LLM backend was reachable to confirm.
    semantic_confirmations: List[dict] = field(default_factory=list)
    # Advisory notes the extractor surfaces to the caller (e.g. a datasheet
    # interface TABLE was detected but only partially parsed). These never fail a
    # gate on their own; spec_conformance_check re-emits them as INFO findings so a
    # silent 0-port skip on a table-only interface spec is visible.
    notes: List[str] = field(default_factory=list)


# Natural-language interface bullet:  " - input  d   (8 bits)"  /  " - output q"
# Line-anchored with [ \t] (never \s) so a greedy match cannot swallow the next
# bullet's newline and skip ports.
#
# END-anchored (ORGANIC-20260614 C1, #751): a TRUE interface bullet is
# `- input <name>` optionally followed by an `(N bits)` width annotation and then
# the END of the line — nothing else. Without the trailing `[ \t]*$` anchor this
# regex harvested ordinary PROSE bullets as phantom ports: `- Input ports:` ->
# 'ports', `- Output all zeros (...)` -> 'all', `- Output latency is 1 clock
# cycle.` -> 'latency', `- Input coefficients [..]` -> 'coefficients'. Each
# carries trailing prose after the captured word, so the end-anchor rejects them
# while every legitimate `- input clk` / `- input d (8 bits)` bullet still matches.
# Natural-language interface bullet:  " - input  d   (8 bits)  data bus"
# Line-anchored with [ \t] (never \s). The NAME + optional `(N bits)` width is
# captured; a TRAILING DESCRIPTION (the common datasheet shape `- input clk
# system clock`) is allowed (group 4) — an earlier end-anchored version dropped
# every described bullet, collapsing the whole port set (#751 adversarial-review
# HIGH). To still reject ordinary PROSE bullets ("- Input ports:", "- Output
# latency is 1 clock cycle.", "- Output all zeros"), the captured name is
# post-filtered by `_nl_port_is_prose` below — a heading (`name:`), a copular
# sentence (`name is/are/…`), or a closed set of non-port plural/abstract nouns.
_NL_PORT = re.compile(
    r'^[ \t]*[-*][ \t]*(input|output|inout)\b[ \t]+'
    r'([A-Za-z_]\w*)[ \t]*(?:\([ \t]*(\d+)[ \t]*bits?[ \t]*\))?'
    r'(?P<tail>[ \t]*[:]?[^\n]*)?$',
    re.I | re.M)

# ORGANIC #772 — DIRECTION-LABEL-COLON bullet form. Many datasheets declare a
# port as `- **Input**: \`binary_in\` (\`BINARY_WIDTH\` bits) ...` / `- Output:
# valid (1 bit)` — the direction word is a LABEL (optionally markdown-emphasised
# **/__/*/_), followed by a colon, then the (optionally-backticked) name, then a
# width annotation. The canonical `_NL_PORT` requires the direction word to be
# immediately followed by the bare name (no colon, no emphasis), so this common
# style returned ZERO ports → a vacuous `spec-coverage ok` on a spec that clearly
# declares ports. To avoid re-introducing a phantom-port leak from ordinary prose
# bullets (`- **Note**: the output is ...`), the label-colon form REQUIRES a
# structural WIDTH ANCHOR — `(N bits)` or `(\`WIDTH\` bits)` — right after the
# name. A genuine port declaration in this style always carries that width
# annotation; a prose sentence does not. chip-AGNOSTIC: pure markdown/English
# grammar, no chip / vendor / SKU literal.
_NL_PORT_LABEL = re.compile(
    r'^[ \t]*[-*][ \t]*'
    r'(?:\*\*|__|\*|_)?(input|output|inout)(?:\*\*|__|\*|_)?'  # (1) emphasised dir
    r'[ \t]*:[ \t]*'                                            # (2) colon label
    r'`?([A-Za-z_]\w*)`?[ \t]*'                                 # (3) (backtick) name
    r'\([ \t]*(?:`?\w+`?[ \t]+)?(\d+|`\w+`)[ \t]*bits?[ \t]*\)',  # (4) width anchor
    re.I | re.M)

# Non-port English words that recur as the "name" of a PROSE bullet (`- Input
# ports:`, `- Input coefficients [...]`, `- Output all zeros`). chip-AGNOSTIC:
# generic English, never a chip/SKU literal. 'data'/'addr'/'valid' are NOT here
# (they are common real port names).
_NL_PORT_PROSE_NAMES = frozenset({
    "ports", "port", "signals", "signal", "coefficients", "latency",
    "all", "none", "both", "zeros", "ones", "value", "values", "list",
    "bits", "bit", "width", "widths", "behavior", "behaviour", "outputs",
    "inputs", "interface", "interfaces", "description", "note", "notes",
})
# ORGANIC #770 — coordinating conjunctions / articles that, when captured as the
# "name" by `_NL_PORT`, mark the bullet as a prose SENTENCE rather than a port
# declaration ("- Input and output AXI Stream signals adhere to ..." → phantom
# name "and"). These are NOT in `_NL_PORT_PROSE_NAMES` because a single-letter or
# short token CAN be a real port name (`- input a (8 bits)`); they are rejected
# ONLY when NOT immediately followed by a structural width anchor `(N bits)`
# (#770 Step-2.7 blast-radius finding: a blanket prose-name set dropped the
# legitimate ports `a` / `an`). chip-AGNOSTIC: pure English function-word grammar.
_NL_PORT_FUNCTION_WORDS = frozenset({
    "and", "or", "nor", "but", "plus", "with", "the", "a", "an",
})
# a width annotation `(N bits)` / `(`WIDTH` bits)` immediately after the name is
# the structural anchor that proves a function-word token is actually a port name.
_NL_PORT_WIDTH_ANCHOR_RE = re.compile(
    r"^[ \t]*\([ \t]*(?:`?\w+`?[ \t]+)?(?:\d+|`\w+`)[ \t]*bits?[ \t]*\)",
    re.IGNORECASE)
# Copular / auxiliary verbs that mark the bullet as a SENTENCE, not a port decl.
_NL_PORT_COPULA_RE = re.compile(
    r'^[ \t]*(?:is|are|was|were|will|shall|should|must|can|may|has|have|'
    r'represents?|denotes?|indicates?|holds?|carries|specif\w+)\b', re.I)
# The same copula/auxiliary set, but matched ANYWHERE in the tail (not anchored).
# Used by the descriptive-noun-tail guard below to catch the "name-before-copula
# with an intervening noun" prose shape ("- Input data elements ARE divided into
# pairs …" → `_NL_PORT_COPULA_RE` misses it because the NOUN `elements` sits
# between the captured name `data` and the copula `are`). chip-AGNOSTIC: pure
# English grammar, no chip/SKU literal.
_NL_PORT_COPULA_ANYWHERE_RE = re.compile(
    r'\b(?:is|are|was|were|will|shall|should|must|can|may|has|have|'
    r'represents?|denotes?|indicates?|holds?|carries|specif\w+)\b', re.I)
# A leading optional packed-dimension `[range]` (literal or parameterized) that a
# genuine described-port tail may carry before the real port name
# (`- input logic [N-1:0] o_count : Output count`). Stripped before inspecting the
# first descriptive token so a ranged-but-genuine port tail is not misread.
_NL_PORT_TAIL_LEADING_RANGE_RE = re.compile(r'^[ \t]*\[[^\]]*\][ \t]*')
# ORGANIC #785 r2 (Step-2.7 §4.05) — CANONICAL control/clock/reset/handshake
# signal names. A bullet whose port NAME is one of these is a genuine port even
# when it carries only a short descriptive tail (`- input load enable.`,
# `- input reset active high.`), so the descriptive-noun-tail guard must NOT drop
# it. Deliberately EXCLUDES generic datapath nouns (data/average/sum/result/…),
# which remain phantom-prone so the #785 positive (drop `- Input data stream.`)
# still holds. chip-AGNOSTIC: a general digital-hardware signal vocabulary, no
# chip/vendor/SKU literal.
_NL_PORT_CANONICAL_NAMES = frozenset({
    'clk', 'clock', 'rst', 'reset', 'resetn', 'rstn', 'nreset', 'clr', 'clear',
    'load', 'en', 'enable', 'start', 'stop', 'go', 'run', 'valid', 'ready',
    'done', 'ack', 'req', 'busy', 'cs', 'we', 're', 'oe', 'ce', 'wr', 'rd',
    'sel', 'flush', 'stall', 'hold', 'pause', 'irq', 'int', 'err', 'error',
    'fault', 'overflow', 'underflow', 'carry', 'borrow', 'zero', 'sign'})


def _nl_port_is_prose(name: str, tail: str, has_width: bool = False) -> bool:
    """True when an `- input <name> <tail>` bullet is ordinary PROSE rather than
    a port declaration: the name is a known non-port word, a function word with
    NO width anchor (a conjunction/article scraped from a sentence), the bullet
    is a heading (`name:`), or the tail is a copular sentence (`name is …`).

    `has_width` is True when the caller's port regex already consumed a `(N bits)`
    width group for this bullet (the structural anchor the function-word check
    looks for, but eaten before the tail)."""
    if name.lower() in _NL_PORT_PROSE_NAMES:
        return True
    t = tail or ""
    # ORGANIC #770 — a function word (and/or/the/a/an/…) is a phantom port ONLY
    # when it is NOT immediately followed by a structural width anchor. A real
    # short/single-letter port (`- input a (8 bits)`) carries the anchor and is
    # kept; a conjunction in a sentence (`- Input and output signals …`) does not.
    # 2026-06-20 (v1.1.34 clean-room, VerilogEval Prob145_circuit8) — a function
    # word with an EMPTY tail (`- input a` / `- output q`, the lone token on the
    # bullet) is a genuine 1-bit port under the prompt's "all ports are one bit
    # unless otherwise specified" convention, NOT a conjunction scraped from a
    # sentence. The original #770 SENTENCE shape carries a prose TAIL after the
    # function word (`- Input and output signals adhere to …`), so a NON-EMPTY
    # same-line tail still drops.
    #
    # 2026-06-20 (PR #31 Step-2.7 §4.05) — the original bare `t.strip()` test
    # was line-anchored and admitted a line-WRAPPED prose sentence whose first
    # physical line ends ON a function word (`- Input and⏎  output ports adhere …`
    # → phantom `and`; `- Input a⏎  stream of 8-bit samples …` → phantom `a`),
    # emitting a false `ERROR port-missing` against conformant RTL. The
    # STRUCTURAL discriminator is `len(name) > 1`: of the function-word set, only
    # the single-CHARACTER article `a` is a plausible 1-bit port name; the
    # multi-letter conjunctions/articles (and/or/nor/but/plus/with/the/an) are
    # never genuine ports (and/or/nor are reserved keywords), so they are dropped
    # whether bare (`- input or`) or as a wrapped sentence (`- Input and⏎ …`).
    #
    # The single-char `a` is IRREDUCIBLE: `- Input a⏎  stream of samples` (prose)
    # and `- input a⏎  the primary data input` (a genuine port `a` with a wrapped
    # description) are STRUCTURALLY IDENTICAL — same name, empty same-line tail,
    # bare indented continuation — so any rule that drops one drops the other. A
    # first attempt (a `followed_by_prose` next-line probe) dropped BOTH, which a
    # Step-2.7 re-review proved is a §4.05 FALSE-SKIP: a genuine lone `- input a`
    # followed by its own description / a sibling `Outputs:` heading vanished from
    # the spec contract, so RTL that truly OMITS port `a` would pass unflagged.
    # §4.05 ranks a false-SKIP (mask a real defect) STRICTLY WORSE than a
    # false-FIRE (spurious port-missing a human dismisses), so this suppressor
    # resolves the single-char `a` ambiguity toward RESCUE: `a` is kept whenever
    # its same-line tail is empty, closing the original lone-port false-SKIP the
    # PR targets; the residual `- Input a⏎ …`-sentence phantom is an accepted SAFE
    # false-fire. chip-AGNOSTIC: pure English function-word grammar + identifier
    # plausibility (no chip / vendor / SKU literal, no next-line heuristic).
    if (name.lower() in _NL_PORT_FUNCTION_WORDS
            and not has_width
            and not _NL_PORT_WIDTH_ANCHOR_RE.match(t)
            and (t.strip() or len(name) > 1)):
        return True
    if t.lstrip().startswith(":"):
        return True                       # "- Input ports:" heading
    if _NL_PORT_COPULA_RE.match(t):
        return True                       # "- Output latency is 1 cycle"
    # ORGANIC-20260617 R9C1 (#785) — DESCRIPTIVE-NOUN-TAIL / NOUN-BEFORE-COPULA
    # prose. A datasheet prose bullet under a port HEADING ("- Input data
    # stream.", "- Output average over the window.", "- Input data elements are
    # divided into pairs …") is mis-harvested as a phantom port whose NAME is a
    # common noun (`data`/`average`) that is deliberately NOT in
    # `_NL_PORT_PROSE_NAMES` (they are legitimate real port names elsewhere). The
    # two prior guards miss it: there is no leading colon (not a heading) and the
    # copula either is absent ("stream.") or is preceded by an intervening noun
    # ("data ELEMENTS are …") so the anchored `_NL_PORT_COPULA_RE` does not fire.
    # Distinguish prose from a genuine described port by the structural anchors a
    # real port carries and prose does not:
    #   • a width anchor `(N bits)`  (then `has_width` / `_NL_PORT_WIDTH_ANCHOR_RE`)
    #   • a `name : description` colon mid-tail (kept by the existing flow)
    #   • a bare/identifier tail with NO terminal sentence period
    #     ("- input clk system clock", "- input clk_in : Clock input").
    # Reject ONLY when the bullet carries NO width anchor AND the tail, after an
    # optional leading packed range, begins with a lowercase descriptive English
    # word (not an `_`/digit identifier, not a kept function word) AND EITHER it
    # ends in a sentence period `.` OR a copula appears later (noun-before-copula).
    # chip-AGNOSTIC: pure English grammar, no chip/vendor/SKU literal.
    if not has_width and not _NL_PORT_WIDTH_ANCHOR_RE.match(t):
        # ORGANIC #785 r2 (Step-2.7 §4.05): NEVER drop a bullet whose NAME is a
        # genuine port. The descriptive-tail heuristic keys on the TAIL only, so
        # `- input load enable.` / `- input reset active high.` (real control
        # ports `load`/`reset` + a short description) were wrongly dropped — a
        # missing such port then leaks past spec_conformance. A name is a real
        # port (not a phantom) when it is a CANONICAL control/clock/reset/
        # handshake signal name OR is IDENTIFIER-shaped (carries `_` or a digit:
        # rst_n, data_valid, clk_in). Only a BARE GENERIC datapath noun
        # (data/average/stream/…) — never a canonical signal — stays
        # phantom-prone, so the #785 positive (drop `- Input data stream.`) holds.
        nlow = name.lower()
        name_is_real_port = (
            nlow in _NL_PORT_CANONICAL_NAMES
            or "_" in name
            or any(c.isdigit() for c in name))
        core = _NL_PORT_TAIL_LEADING_RANGE_RE.sub("", t).strip()
        if not name_is_real_port and core and ":" not in core:
            mtok = re.match(r"([A-Za-z_]\w*)", core)
            first = mtok.group(1) if mtok else ""
            descriptive = (
                bool(first)
                and first.islower()
                and "_" not in first
                and not any(c.isdigit() for c in first)
                and first not in _NL_PORT_FUNCTION_WORDS)
            if descriptive and (
                    core.rstrip().endswith(".")
                    or _NL_PORT_COPULA_ANYWHERE_RE.search(core)):
                return True
    return False


def _parse_nl_ports(text: str) -> List[Port]:
    ports: List[Port] = []
    canonical_lines: set = set()   # source lines the canonical pass already used
    for m in _NL_PORT.finditer(text):
        direction = m.group(1).lower()
        name = m.group(2)
        if _nl_port_is_prose(name, m.group("tail") or "",
                             has_width=bool(m.group(3))):
            continue
        # NOTE: NO name-dedup here — `spec_self_consistency_check` relies on
        # `_parse_nl_ports` returning EVERY bullet (including a duplicate port
        # name) so it can detect the duplicate-port error. (#770 Step-2.7
        # blast-radius finding: a `seen`-set dedup here silently hid duplicates.)
        canonical_lines.add(text[:m.start()].count("\n"))
        width = int(m.group(3)) if m.group(3) else 1
        ports.append(Port(name, direction, width))
    # ORGANIC #772 — the direction-label-colon datasheet form (`- **Input**:
    # `name` (N bits)`). The width anchor in the regex already gates out prose
    # bullets, so no `_nl_port_is_prose` post-filter is needed here. A symbolic
    # width (`(`WIDTH` bits)`) is not a concrete bit-count, so default to 1 (the
    # port's PRESENCE + direction is the structural fact spec-coverage needs; the
    # exact width is corroborated against the RTL elsewhere). Only skip a label
    # match on a line the CANONICAL pass already consumed (some bullets match
    # both regexes) — never a same-NAME dedup (duplicates on distinct lines are
    # preserved for the duplicate-port detector).
    for m in _NL_PORT_LABEL.finditer(text):
        if text[:m.start()].count("\n") in canonical_lines:
            continue
        direction = m.group(1).lower()
        name = m.group(2)
        w = m.group(3) or ""
        width = int(w) if w.isdigit() else 1
        ports.append(Port(name, direction, width))
    return ports


# ---------------------------------------------------------------------------
# Markdown PIN-CONFIGURATION / interface TABLE port parser
# ---------------------------------------------------------------------------
# Most *datasheets* declare the interface only as a markdown table:
#     | Signal | Dir   | Width | Description |
#     |--------|-------|-------|-------------|
#     | clk    | input | 1     | clock       |
#     | d      | in    | [7:0] | data        |
# extract_spec_contract previously returned 0 ports for that shape (port
# conformance silently skipped). This parser detects such a table and emits
# Port(name, direction, width) rows.
#
# chip-AGNOSTIC + corpus-clean by construction: a table is accepted ONLY when
# it has BOTH a name-shaped header column (Signal/Pin/Port/Name) AND a direction
# header column, AND that direction column's DATA cells actually hold direction
# tokens (input/output/inout or in/out/io). Generic report tables in the corpus
# (e.g. "| Protocol | Authored RTL | ... |", "| L1_DATASHEET | 102407 | ... |")
# have no direction column with direction-valued cells, so they never match.
# Only table CELLS — never sentence words — drive ports (the "no raw prose scan"
# rule is preserved).

# A normalised direction value -> canonical direction.
_DIR_TOKEN = {
    'input': 'input', 'in': 'input', 'i': 'input',
    'output': 'output', 'out': 'output', 'o': 'output',
    'inout': 'inout', 'io': 'inout', 'bidir': 'inout',
    'bidirectional': 'inout', 'in/out': 'inout',
}

# Header-cell predicates (column-role detection by header text).
_NAME_HDR = re.compile(r'^\s*(signal|pin|port|name|signal\s*name|port\s*name)\s*$', re.I)
# Direction-column header vocabulary. `in\s*/\s*out` matches the common
# `In/Out` interface-table header (the dominant CVDP form); the existing `i/o`
# only matched the abbreviated `I/O`. `direction` covers `Direction`.
_DIR_HDR = re.compile(
    r'^\s*(dir|direction|in\s*/\s*out|in\s*-\s*out|i\s*/\s*o|i/o|io|mode|type)\s*$',
    re.I)
# Width-column header vocabulary. `length`/`len` matches the common `Length`
# interface-table column (CVDP form); the existing set had width/bits/size/range.
_WIDTH_HDR = re.compile(
    r'^\s*(width|bits?|size|len(?:gth)?|\[?\s*msb\s*:\s*lsb\s*\]?|range)\s*$',
    re.I)


def _split_md_row(line: str) -> List[str]:
    """Split a markdown table row `| a | b | c |` into trimmed cells."""
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [c.strip() for c in s.split('|')]


def _is_md_delim_row(cells: List[str]) -> bool:
    """A markdown header/body delimiter row: every cell is dashes (with optional
    leading/trailing colons for alignment): `---`, `:--`, `--:`, `:-:`."""
    if not cells:
        return False
    return all(re.fullmatch(r':?-{2,}:?', c.replace(' ', '')) for c in cells if c != '')


def _strip_md_emphasis(cell: str) -> str:
    """Remove markdown decoration WITHOUT corrupting identifiers.

    Backticks are code-span markers (never inside an identifier) so strip them
    anywhere; `*`/`_` are emphasis markers only when they WRAP the token, so
    strip them only at the cell's leading/trailing edge. This preserves an
    internal underscore (`data_in`, `rst_n`) that a naive `[`*_]→''` would eat."""
    c = cell.replace('`', '').strip()
    c = re.sub(r'^[*_]+', '', c)
    c = re.sub(r'[*_]+$', '', c)
    return c.strip()


def _norm_dir(cell: str) -> Optional[str]:
    """Map a direction data-cell to canonical direction, else None.

    Strips markdown emphasis/backticks so `` `input` `` / `**in**` still match.
    Rejects anything that is not a pure direction token (so a Description cell
    that merely *contains* the word 'input' does not count as a direction)."""
    c = _strip_md_emphasis(cell).lower()
    return _DIR_TOKEN.get(c)


def _parse_width_cell(cell: str) -> Optional[int]:
    """Parse a width data-cell to an int bit count, else None.

    Accepts `8`, `[7:0]`, `7:0`, `8 bits`, `1` (scalar). Backtick/emphasis
    tolerant. Returns None for unparseable / empty cells (caller defaults to 1)."""
    c = _strip_md_emphasis(cell).lower()
    if not c or c in ('-', '--', 'n/a', 'na'):
        return None
    m = re.fullmatch(r'\[?\s*(\d+)\s*:\s*(\d+)\s*\]?', c)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    m = re.fullmatch(r'(\d+)\s*(?:bits?)?', c)
    if m:
        v = int(m.group(1))
        return v if v >= 1 else None
    return None


def _parse_md_table_ports(text: str, union: bool = False) -> Tuple[List[Port], List[str]]:
    """Parse a markdown PIN/interface table into ports.

    Returns (ports, notes). `notes` carries an advisory string when a qualifying
    table header was found but some body rows could not be parsed into ports, so
    the caller can surface it (a partial parse must never be a silent 0-port skip).

    `union` (default False — preserves the single-best contract the conformance
    gates rely on): when True, UNION the ports of EVERY qualifying interface table
    (deduped by name, first-seen wins) instead of returning only the largest one.
    A spec often splits its interface across separate clock/reset, input, and
    output tables; the Phase-1 ingester needs all of them.
    """
    lines = text.splitlines()
    best_ports: List[Port] = []
    union_ports: List[Port] = []
    _seen_union = set()
    notes: List[str] = []
    i = 0
    n = len(lines)
    while i < n - 1:
        line = lines[i]
        if line.count('|') < 2:
            i += 1
            continue
        header = _split_md_row(line)
        # need a header followed by a markdown delimiter row to be a real table
        delim = _split_md_row(lines[i + 1]) if i + 1 < n else []
        if not _is_md_delim_row(delim) or len(delim) != len(header):
            i += 1
            continue
        name_col = next((k for k, h in enumerate(header) if _NAME_HDR.match(h)), None)
        dir_col = next((k for k, h in enumerate(header) if _DIR_HDR.match(h)), None)
        width_col = next((k for k, h in enumerate(header) if _WIDTH_HDR.match(h)), None)
        if name_col is None or dir_col is None:
            i += 1
            continue
        # walk body rows
        j = i + 2
        ports: List[Port] = []
        body_rows = 0
        dir_valued_rows = 0
        unparsed = 0
        while j < n:
            row = lines[j]
            if row.count('|') < 2 and not row.strip().startswith('|'):
                break
            if row.count('|') < 1:
                break
            cells = _split_md_row(row)
            if _is_md_delim_row(cells):     # closing/interior delimiter — skip
                j += 1
                continue
            if all(c == '' for c in cells):
                break
            body_rows += 1
            if len(cells) <= max(name_col, dir_col):
                unparsed += 1
                j += 1
                continue
            direction = _norm_dir(cells[dir_col])
            if direction is None:
                unparsed += 1
                j += 1
                continue
            dir_valued_rows += 1
            name = _strip_md_emphasis(cells[name_col])
            # a bare identifier name only (no spaces / link markup / prose)
            m = re.fullmatch(r'[A-Za-z_]\w*', name)
            if not m:
                unparsed += 1
                j += 1
                continue
            width = 1
            if width_col is not None and len(cells) > width_col:
                w = _parse_width_cell(cells[width_col])
                if w is not None:
                    width = w
            ports.append(Port(name, direction, width))
            j += 1
        # Accept this table ONLY if its direction column truly holds direction
        # tokens (≥2 direction-valued body rows, and the majority of body rows are
        # direction-valued) — this is what distinguishes an interface table from a
        # generic report/regmap table that happens to share a header word.
        if (ports and dir_valued_rows >= 2
                and dir_valued_rows * 2 >= body_rows):
            for p in ports:                       # accumulate for the union mode
                if p.name not in _seen_union:
                    _seen_union.add(p.name)
                    union_ports.append(p)
            if len(ports) >= len(best_ports):
                best_ports = ports
                notes = []
                if len(ports) < dir_valued_rows or unparsed:
                    notes = [
                        f"spec interface present as a table but only {len(ports)} "
                        f"port(s) parsed from {body_rows} row(s) — verify the "
                        f"interface table is fully captured."]
        i = j if j > i else i + 1
    return (union_ports if union else best_ports), notes


def _skip_balanced_parens(text: str, i: int) -> Optional[int]:
    """`text[i]` must be `(`. Return the index JUST PAST the matching `)`, or
    None if unbalanced. Balances nested parens so a `#( ... )` parameter block
    containing inner parens (`$clog2(BUFFER_DEPTH)`, `(IN_ROW > IN_COL) ? ..`,
    `{N{1'b1}}`) is consumed whole."""
    if i >= len(text) or text[i] != '(':
        return None
    depth, n = 0, len(text)
    while i < n:
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


# One ANSI port-list segment: an OPTIONAL direction (a continuation segment
# inherits the previous one), optional net/sign kinds, an optional packed
# dimension, the port name, an optional unpacked dimension. The TRAILING run is
# same-line whitespace ONLY (`[ \t]*`, not `\s*`) so the char right after a port
# name reveals whether the port ended its line (`,`/`)`/newline) or is trailed by
# a same-line prose word. Used ONLY to bound a TRUNCATED (unbalanced-`(`) header —
# see the S4-OVM1 fallback in `_module_port_region`.
_PORTLIST_SEG = re.compile(
    r'\s*(?P<dir>input|output|inout)?\s*'
    r'(?:(?:wire|reg|logic|signed|unsigned)\b\s*)*'
    r'(?:\[[^\]]*\]\s*)?'
    r'(?P<name>[A-Za-z_]\w*)'
    r'(?:[ \t]*\[[^\]]*\])?[ \t]*')
# A direction keyword at a genuine PORT POSITION — immediately preceded (modulo
# same-line whitespace) by a port-list separator `,` / newline. `_portlist_prefix_len`
# RESYNCS to it past a prose interruption, so a described / prose-named segment never
# cascade-drops the real ports after it. Keying on a SEPARATOR-anchored keyword (not a
# bare `\binput\b`) is what distinguishes a real later port (`…, output valid`) from a
# keyword merely MENTIONED inside a description (`… the input stream is latched`), so
# the resync cannot scrape a prose word as a phantom.
_RESYNC_KW_RE = re.compile(r'[,\r\n][ \t]*(input|output|inout)\b')


def _mask_comments_len(s: str) -> str:
    """Length-PRESERVING comment blanking — the non-truncating sibling of
    `strip_comments()`. `strip_comments` returns early on an UNTERMINATED `//`/`/*`
    (changing the string length); `_portlist_prefix_len` walks a TRUNCATED header
    where an unterminated comment is plausible AND maps masked-string indices back
    onto the RAW region, so length MUST be preserved. Mirrors `strip_comments`'
    token rules (`//` to end-of-line, `/* … */` block) but always emits spaces
    (newlines kept) and runs an unterminated comment to EOF. Aligning the bound's
    tokenization with the consumer's (`parse_verilog_ports` strip_comments BEFORE
    its port scan) stops an inline `// …` / `/* … */` in a truncated port list from
    cutting the region mid-list and dropping a real port. chip-AGNOSTIC."""
    out, i, n = [], 0, len(s)
    while i < n:
        two = s[i:i + 2]
        if two == '/*':
            end = s.find('*/', i + 2)
            stop = end + 2 if end != -1 else n
            out.append(''.join('\n' if c == '\n' else ' ' for c in s[i:stop]))
            i = stop
        elif two == '//':
            end = s.find('\n', i)
            stop = end if end != -1 else n
            out.append(' ' * (stop - i))
            i = stop
        else:
            out.append(s[i]); i += 1
    return ''.join(out)


def _portlist_prefix_len(region: str) -> int:
    """Length, measured from the opening `(`, of the well-formed ANSI port-list
    PREFIX of `region` (which must start with `(`).

    Bounds a TRUNCATED module header whose port list has no closing `);` AND is
    not followed by a body-boundary keyword. Without this bound the region runs to
    EOF and `parse_verilog_ports` harvests any PROSE word that merely follows the
    literal token `input`/`output`/`inout` as a phantom port. This walk recognises
    ports off the SAME structural anchor the consumer uses — the DIRECTION keyword
    `input`/`output`/`inout` — and keeps EVERY direction-anchored port, so it never
    DROPS a real declared port (a drop would §4.05-LEAK: the downstream conformance
    gate would false-SKIP a genuinely-missing RTL port). Rules:
      * a segment carrying a DIRECTION keyword is a real port (the keyword anchors
        it exactly as `parse_verilog_ports` keys on it), recorded EVEN when a
        same-line description trails its name (`input clk the system clock`,
        `output reg dout the input stream …`). The prose-NOUN blacklist does NOT
        gate a direction-anchored name (`input value` / `input signals` are
        legitimate ports — consistent with how the BALANCED header is parsed).
      * a bare identifier continues a list ONLY across a COMMA with an inherited
        direction (`input a, b, c`).
      * a PROSE segment — a copula sentence (`input is computed …`), a comma-
        continuation prose noun (`…, signals …`), or any name trailed by a same-
        line prose word — does NOT terminate the walk. It RESYNCS to the next
        DIRECTION keyword and continues, so a real later port (`… input rst the
        reset, output valid`, `input clk active, gated by enable, output done`) is
        NEVER cascade-dropped. The resync keys ONLY on the direction keyword — an
        intervening comma/newline INSIDE a description is prose punctuation, not a
        port-list separator (round-2 §4.05 review: a min(keyword, separator) resync
        landed on an in-prose comma and re-introduced the cascade-drop, and the
        per-port separator search was O(n²) on a long single-line prose tail).
    The walk ends at a STRUCTURAL boundary — `)`/`;`/fence/comment/EOF, a bare word
    that is neither a port nor a comma-continuation, or no further PORT-POSITION
    direction keyword. This bounds the trailing-prose run after a clean port list
    (#28's intent) WITHOUT the false-SKIP of dropping a real direction-declared
    port. The IRREDUCIBLE residual is a token lexically identical to a real port
    declaration (`input stream` inside the prose `… the input stream`); that is
    indistinguishable from a genuine header, the prior fallback harvested it too,
    and keeping it is the §4.05-SAFE direction (a bounded false-FIRE over-flag, not
    a false-SKIP defect-mask). chip-AGNOSTIC."""
    masked = _mask_comments_len(region)   # align tokenization with parse_verilog_ports
    n = len(masked)

    def _resync(p: int) -> int:
        """Index of the next PORT-POSITION direction keyword (>= p) on which real
        ports resume — a keyword anchored to a `,`/newline separator, so a keyword
        merely MENTIONED in the skipped prose (`… the input stream …`) is not a
        resync target. Returns -1 if none. Crosses a blank line: a blank line is a
        legitimate visual grouping of a newline-separated port list, so a real port
        after it (`input clk …`<blank>`input rst_n …`) must NOT be abandoned (round-3
        §4.05 review: a paragraph-break bound here false-SKIPped grouped reset/output
        ports). The residual — a PROSE line that starts, after a separator, with a
        lowercase `input`/`output` token — yields one bounded false-FIRE phantom, the
        §4.05-SAFE direction. O(distance): the scanned span is then consumed (i jumps
        to it), so the whole walk stays linear (no per-port scan-to-EOF)."""
        m2 = _RESYNC_KW_RE.search(masked, p)
        return m2.start(1) if m2 is not None else -1

    i = 1 if masked[:1] == '(' else 0
    last = i
    have_dir = False
    prev_comma = False
    while i < n:
        # Skip inter-token whitespace MANUALLY before matching, so `_PORTLIST_SEG`
        # is never applied to a long whitespace run that then fails the required
        # name (its two `\s*` groups would backtrack O(n²) on, e.g., a truncated
        # `(` followed by thousands of blank lines).
        while i < n and masked[i] in ' \t\r\n':
            i += 1
        if i >= n:
            break
        m = _PORTLIST_SEG.match(masked, i)
        if not m or m.end() == i:
            break                       # STRUCTURAL end: `)`, fence, `;`, a non-port char
        seg_dir = bool(m.group('dir'))
        is_cont = (not seg_dir) and have_dir and prev_comma
        if not (seg_dir or is_cont):
            break                       # STRUCTURAL: a bare word, not a port/continuation
        nm = m.group('name').lower()
        # --- PROSE segments: skip (resync), do NOT terminate the walk ----------- #
        # A copula/auxiliary verb as the "name" marks a SENTENCE (`input is computed
        # …`) — never a legal port name. (Gate copula verbs ONLY, NOT coordinating
        # function words like `a`/`an`: a single-letter `a` is a common real port.)
        if seg_dir and _NL_PORT_COPULA_RE.match(nm):
            r = _resync(m.end())
            if r < 0:
                break
            i = r; prev_comma = False; continue
        # A bare comma-continuation whose name is a known prose noun (`…, signals …`)
        # is a sentence continuation, not a port.
        if is_cont and nm in _NL_PORT_PROSE_NAMES:
            r = _resync(m.end())
            if r < 0:
                break
            i = r; prev_comma = False; continue
        # --- a real port (direction-anchored, or a clean comma-continuation) ----- #
        if seg_dir:
            have_dir = True
        j = m.end()
        ch = masked[j] if j < n else ''
        if ch == ',':
            last = j; i = j + 1; prev_comma = True; continue
        if ch in '\r\n':
            last = j; i = j; prev_comma = False; continue   # last port on its line
        if ch == '' or not (ch.isalpha() or ch == '_'):
            last = j; break             # `)`, EOR, code-fence, `;`, comment-now-space …
        # A same-line bare word trails the name.
        if not seg_dir:
            # a comma-continuation trailed by prose (`…, computed by …`) is prose
            r = _resync(j)
            if r < 0:
                break
            i = r; prev_comma = False; continue
        # A direction-anchored REAL port with a trailing same-line description:
        # RECORD it (never drop a direction-declared port), then resync to the next
        # real port so a clean later port is not cascade-dropped.
        last = j
        r = _resync(j)
        if r < 0:
            break
        i = r; prev_comma = False
    return last


def _module_port_region(text: str, prefer: str = "TopModule") -> Optional[str]:
    """Return the ANSI port-list inside `module name ( ... )`, or None.

    Lets a markdown spec carry a fenced ```verilog module(...)``` header without
    prose ("...provides valid outputs...") leaking false ports.

    When the spec embeds MULTIPLE module declarations (e.g. a reference or buggy
    module shown before the real target header — common in code-completion and
    bug-fix prompts), prefer the one named `prefer` (default TopModule, the target)
    so the contract is taken from the target header, not the embedded example.

    ORGANIC-20260618 (cascaded_adder_0025 / image_rotate_0001 /
    write_buffer_merge_0001): the optional parameter block `#( ... )` is BALANCE-
    matched, not regex-`[^)]*`-matched. A real ANSI header whose param list
    embeds nested parens (`#( parameter X = $clog2(N) )`, `( (A>B)?A:B )`,
    `{N{1'b1}}`) was MISSED by the old `#\\s*\\([^)]*\\)` regex (it cannot span an
    inner `)`), so the contract extractor fell through to the prose-scan fallback
    and harvested English words as phantom ports. Balancing the param block reaches
    the real port-list `( ... )` and the phantom-port class disappears at source."""
    n = len(text)
    headers: List[Tuple[str, int, int]] = []   # (name, header_start, portlist_open)
    for m in re.finditer(r'\bmodule\s+(\w+)\s*', text):
        j = m.end()
        # optional `#( ... )` parameter block, balance-matched
        if j < n and text[j] == '#':
            k = j + 1
            while k < n and text[k] in ' \t\r\n':
                k += 1
            if k < n and text[k] == '(':
                end = _skip_balanced_parens(text, k)
                if end is None:
                    continue
                j = end
                while j < n and text[j] in ' \t\r\n':
                    j += 1
        if j < n and text[j] == '(':
            headers.append((m.group(1), m.start(), j))
    if not headers:
        return None
    name, start, open_i = next((h for h in headers if h[0] == prefer), headers[0])
    end = _skip_balanced_parens(text, open_i)
    if end is not None:
        return text[start:end - 1]      # exclude the closing ')'
    # ORGANIC-20260618 (gray_to_binary_0001) — a PARTIAL / truncated code template
    # may show the ANSI port list with NO closing `);` (the body decls start right
    # after the last port). The unbalanced `(` made this header un-matchable, so
    # the contract extractor fell through to the prose-scan fallback and scraped
    # English words ('Gray Input'->'Gray', '... is ...'->'is', 'by inverting'->'by',
    # 'upon changes'->'upon') as phantom ports. Bound the port-list region at the
    # first BODY boundary instead — the first line that begins a non-port body
    # declaration (`logic`/`wire`/`reg` WITHOUT input/output, `always`/`assign`/
    # `genvar`/`generate`/`localparam`/`function`/`task`) or `endmodule`. Within
    # this bounded region, parse_verilog_ports only harvests `input/output/inout`
    # declarations, so NO prose word can leak as a port. chip-AGNOSTIC.
    region = text[open_i:]
    boundary = re.search(
        r'(?m)^[ \t]*(?:'
        r'(?:logic|wire|reg|integer|genvar)\b'   # body net/var decl …
        r'|always\b|assign\b|generate\b|localparam\b|parameter\b'
        r'|function\b|task\b|initial\b|endmodule\b)',
        region)
    if boundary is not None:
        region = region[:boundary.start()]
    else:
        # S4-OVM1 — no body-boundary keyword follows the unbalanced `(`, so the
        # region above runs to EOF and parse_verilog_ports could harvest any PROSE
        # word that merely follows the literal token `input`/`output`/`inout`
        # (e.g. a single-line template `... output reg dout the input stream
        # carries result data` -> phantom ports `result`/`data`/…). Bound the
        # region to the well-formed comma-separated ANSI port-list PREFIX instead.
        # §4.05-safe: in this degraded truncated-header path this can only DROP a
        # real port, never ADD a phantom. chip-AGNOSTIC.
        region = region[:_portlist_prefix_len(region)]
    return text[start:open_i] + region


# An active-low-shaped reset name: trailing `_n`/`n`, or a leading `n` on a
# reset root (nrst / nreset). Used to INFER active-low polarity from the signal
# name when the prose gives no explicit "active-low" word. Conservative — only
# names that are unambiguously a reset.
_ACTIVE_LOW_RST_NAME = re.compile(
    r'^(?:'
    r'rst_?n|reset_?n|resetn'        # rst_n / rstn / reset_n / resetn
    r'|n_?rst|n_?reset|nrst|nreset'  # nrst / n_rst / nreset
    r'|[a-z]+_rst_n|[a-z]+_reset_n'  # <prefix>_rst_n / <prefix>_reset_n
    r')$', re.I)


# Clause-bound reset qualifier extraction
# (ORGANIC-20260606-reset-mode-dual-keyword-false-positive). A spec sentence
# can qualify SEVERAL signals at once — "asynchronous positive edge triggered
# areset, synchronous active high signals load, and enable" declares an ASYNC
# reset plus SYNC non-reset controls in ONE sentence. Sentence-scoped keyword
# presence then lets the OTHER signals' qualifier win; worse, the legacy
# splitter treated every newline as a sentence boundary, so a hard line-wrap
# falling between "asynchronous" and its reset token divorced the qualifier
# from the very line that carried "reset". Fix: soft-unwrap line-wraps (a
# single newline inside a paragraph is a wrap, not a boundary), split REAL
# sentences, and bind the mode/polarity keyword to the clause (comma/semicolon
# segment) that contains the reset token itself. Clause-bound evidence wins;
# the legacy sentence-scope logic stays as the fallback so single-qualifier
# specs ("Asynchronous, active-high reset") keep resolving exactly as before.
_RESET_TOKEN_RE = re.compile(r'\b\w*(?:rst|reset)\w*\b|\bpor\b')
_MODE_KW_RE = re.compile(r'\b(a)?synchronous(?:ly)?\b')
_POLARITY_KW_RE = re.compile(r'\bactive[\s-]*(high|low)\b')


def _soft_unwrap_sentences(text: str) -> List[str]:
    """Lower-cased REAL sentences: single newlines (hard wraps) become spaces,
    blank lines stay paragraph boundaries, then split on ./!/?"""
    low = text.lower()
    unwrapped = re.sub(r'[ \t]*\n(?![ \t]*\n)[ \t]*', ' ', low)
    return [s for s in re.split(r'(?<=[.!?\n])', unwrapped) if s.strip()]


def _clause_bound_reset_kw(text: str, kw_re: re.Pattern) -> Optional[str]:
    """Scan clause-by-clause: in every clause that contains a reset token, look
    for the qualifier keyword. Returns the qualifier when all reset-bearing
    clauses agree (nearest-to-token wins inside a clause carrying both), else
    None (no clause-bound evidence, or conflicting clauses)."""
    found: List[str] = []
    for sent in _soft_unwrap_sentences(text):
        toks = [m.start() for m in _RESET_TOKEN_RE.finditer(sent)]
        if not toks:
            continue
        start = 0
        for cb in list(re.finditer(r'[,;:]', sent)) + [None]:
            end = cb.start() if cb else len(sent)
            clause_toks = [p for p in toks if start <= p < end]
            if clause_toks:
                kws = [(m.start() + start, m.group(1)) for m in
                       kw_re.finditer(sent[start:end])]
                if kws:
                    if len({g for _, g in kws}) == 1:
                        found.append(kws[0][1])
                    else:  # both qualifiers inside one clause: nearest wins
                        t = clause_toks[0]
                        found.append(min(kws, key=lambda kv: abs(kv[0] - t))[1])
            start = cb.end() if cb else end
    return found[0] if len(set(found)) == 1 else None


def _detect_reset(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (mode, polarity, signal) the spec declares for reset, if any."""
    low = text.lower()
    mode = None
    # Look only in sentences that mention reset, to avoid false matches.  POR
    # (power-on reset) is a reset even when the literal word "reset" is absent
    # from its sentence, so admit POR-bearing sentences too.
    reset_ctx = ' '.join(
        s for s in re.split(r'(?<=[.\n])', low)
        if 'reset' in s or re.search(r'\bpor\b|power[\s-]*on[\s-]*reset', s)) or low
    # Clause-bound evidence first (see the rule comment above): the qualifier
    # sharing a clause with the reset token beats any sentence-scope keyword.
    cb_mode = _clause_bound_reset_kw(text, _MODE_KW_RE)
    if cb_mode is not None:
        mode = 'asynchronous' if cb_mode == 'a' else 'synchronous'
    # Token-bound async phrases next — each names the reset token DIRECTLY
    # ("rising edge OF <rst>", "edge triggered <rst>", power-on reset), so they
    # out-rank a floating sentence-scope keyword that may qualify other signals.
    if mode is None:
        if (re.search(r'power[\s-]*on[\s-]*reset', reset_ctx)
                or re.search(r'\bpor\b\s+holds?\b', reset_ctx)
                or re.search(r'(?:rising|falling)\s+edge\s+of\s+'
                             r'`?\b\w*(?:rst|reset|nrst|por)\w*\b`?', reset_ctx)
                or re.search(r'(?:positive|negative|rising|falling)[\s-]+edge[\s-]*'
                             r'triggered\s+`?\b\w*(?:rst|reset)\w*\b`?', reset_ctx)):
            mode = 'asynchronous'
    # Legacy sentence-scope keyword fallback (unchanged semantics).
    if mode is None:
        if re.search(r'asynchronous(?:ly)?', reset_ctx):
            mode = 'asynchronous'
        elif re.search(r'synchronous(?:ly)?', reset_ctx):
            mode = 'synchronous'
    # Conservative loose-phrase inference, only when nothing above fixed the
    # mode. A reset "registered to the clock" / "sampled on the clock" is sync.
    if mode is None:
        if (re.search(r'reset\s+is\s+registered', reset_ctx)
                or re.search(r'registered\s+(?:to|on|by|against)\s+the\s+clock', reset_ctx)
                or re.search(r'reset\s+is\s+sampled\s+(?:on|by|at)\s+the\s+clock', reset_ctx)
                or re.search(r'synchronized\s+to\s+the\s+clock', reset_ctx)):
            mode = 'synchronous'
    polarity = None
    cb_pol = _clause_bound_reset_kw(text, _POLARITY_KW_RE)
    if cb_pol is not None:
        polarity = 'active-' + cb_pol
    elif re.search(r'active[\s-]*high', reset_ctx) or re.search(r'\bactive\s+high\b', reset_ctx):
        polarity = 'active-high'
    elif re.search(r'active[\s-]*low', reset_ctx) or re.search(r'\bactive\s+low\b', reset_ctx):
        polarity = 'active-low'
    # named reset signal (best-effort): a reset-shaped token near "reset"
    signal = None
    m = re.search(r'`?\b(\w*rst_n|resetn|reset_n|nrst|nreset|arst|areset|srst|rst_n|rst|reset|por)\b`?',
                  reset_ctx)
    if m:
        signal = m.group(1)
    # Polarity inference from an active-low-shaped reset NAME, only when no
    # explicit polarity word was found. `nrst`/`rst_n`/`reset_n` are asserted low
    # by convention. Kept conservative: never overrides an explicit word.
    if polarity is None and signal and _ACTIVE_LOW_RST_NAME.match(signal):
        polarity = 'active-low'
    return mode, polarity, signal


def _detect_fsm_output_style(text: str) -> Optional[str]:
    """Return 'moore'/'mealy' iff the spec clearly DECLARES that FSM output style
    as a requirement, else None.

    This is a declared spec property — the sibling of reset-mode — NOT a bare
    keyword grep. To avoid the false triggers that make a naive substring match
    invalid (e.g. "Moore's law", "not a Moore machine"), it requires the term to
    be used as an FSM descriptor (machine/FSM/state-machine in the local window),
    is possessive-aware ("Moore's"), is negation-aware ("not a Moore ..."), and
    bails to None when both styles appear (ambiguous). Mealy-vs-Moore is a valid
    design choice, so this only fires when the spec itself picks one."""
    low = text.lower()

    def declares(word: str) -> bool:
        for m in re.finditer(r'\b' + word + r'\b', low):
            pre = low[max(0, m.start() - 18):m.start()]
            post = low[m.end():m.end() + 3]
            if word == 'moore' and post.startswith("'s"):            # "Moore's law"
                continue
            if re.search(r"\b(not|non|isn'?t|aren'?t|rather than|instead of)\s*(a|an)?\s*$", pre):
                continue
            window = low[max(0, m.start() - 24):m.end() + 32]
            if re.search(r'\b(machine|fsm|finite[\s-]*state|automat|state[\s-]*machine)\b', window):
                return True
        return False

    moore, mealy = declares('moore'), declares('mealy')
    if moore and not mealy:
        return 'moore'
    if mealy and not moore:
        return 'mealy'
    return None


# A spec that DECLARES combinational / zero-latency / unregistered behaviour
# overrides any positive single-cycle latency phrasing: for a combinational
# block "completes in one clock cycle" means the result is available WITHIN one
# cycle (zero registered latency), NOT a registered 1-cycle pipeline delay. This
# suppressor is checked BEFORE the ambiguous single-cycle branch so it can
# override it, and it is broadened well past the literal "combinational output"
# substring (which alone misses the far more common "combinational logic" /
# "changes immediately" / "unregistered" / "no clock" wordings).
# chip-AGNOSTIC: matches design-intent phrasing, never a benchmark-specific
# literal.
_COMBINATIONAL_DECL_RE = re.compile(
    r'\bpurely\s+combinational\b'
    r'|\bfully\s+combinational\b'
    r'|\bcombinational\s+(?:logic|output|circuit|block|design|module|'
    r'function|path|implementation)\b'
    r'|\bis\s+combinational\b'
    r'|\b(?:un|non[- ]?)registered\s+output'
    r'|\boutput\s+(?:is\s+)?(?:un|non[- ]?)registered'
    r'|\boutput\s+changes?\s+immediately'
    r'|\bchanges?\s+immediately\s+(?:based\s+on|with|when|on)'
    r'|\bzero[- ]?(?:cycle\s+)?latency'
    r'|\bno\s+(?:clock|register|registers|sequential|state\s+element)',
    re.I)


def _detect_latency(text: str) -> Optional[bool]:
    """Tri-state output-latency detector.

    True  = the output is registered (a real N>=1-cycle output latency);
    False = the spec EXPLICITLY declares combinational / zero-latency /
            unregistered behaviour (no registered output latency);
    None  = unknown (the spec says nothing about output timing).

    The False verdict is AUTHORITATIVE — the caller must honor it instead of
    falling through to a keyword-grep that would re-derive a phantom latency
    item from incidental wording (#758)."""
    low = text.lower()
    # An EXPLICIT registered-OUTPUT declaration is an unambiguous output-timing
    # statement ("registered output" / "output is registered"); it wins even if
    # a combinational note about INTERNAL logic is also present, so a real
    # registered design can never be silently relaxed (no leak). The leading
    # `\b` word-boundary keeps the glued NEGATED form ("unregistered output")
    # out of this branch (in "unregistered" the `r` is preceded by a word char,
    # so `\bregistered` does not match), and the negative lookbehind `(?<!non-)`
    # / `(?<!non )` keeps the hyphen/space-separated negated form
    # ("non-registered output") out too. Both fall through to the combinational
    # suppressor below (#758).
    if re.search(r'(?<!non-)(?<!non )\bregistered\s+output', low) or \
       re.search(r'output\s+is\s+(?<!non-)(?<!non )\bregistered', low):
        return True
    # Otherwise a combinational / zero-latency / unregistered DECLARATION
    # suppresses (and overrides) the AMBIGUOUS single-cycle phrasing below: for
    # a clockless block "completes in one clock cycle" means WITHIN one cycle
    # (zero registered latency), not a 1-cycle pipeline delay.
    if _COMBINATIONAL_DECL_RE.search(low):
        return False
    if re.search(r'one\s+clock\s+cycle', low) or \
       re.search(r'\b1\s*[- ]?clock[- ]?cycle', low) or \
       re.search(r'single[- ]cycle', low):
        return True
    if re.search(r'combinational\s+output', low):
        return False
    return None


def _json_port_direction(d: dict) -> str:
    """Read a port dict's direction, accepting BOTH the `dir` key (the shape the
    canonical Phase-1 extractor `phase1_port_extract` and the L9/L17 L-docs emit)
    AND the `direction` key. Normalises `in`/`out`/`io` abbreviations to
    canonical `input`/`output`/`inout` via _DIR_TOKEN so a spec written either
    way matches the RTL-parsed direction. Defaults to `input` only when neither
    key is present. chip-AGNOSTIC."""
    raw = d.get('dir', d.get('direction'))
    if raw is None:
        return 'input'
    return _DIR_TOKEN.get(str(raw).strip().lower(), str(raw).strip().lower())


def _json_port_width(d: dict) -> int:
    """Read a port dict's width as an int bit-count. A symbolic/parameterized
    width (a non-integer string like `WB_AW` / `DATA_WIDTH-1:0`) is UNKNOWN, not
    a literal 1 — return 0 (the width-UNKNOWN sentinel) so the width-mismatch
    check skips it rather than asserting a false literal width."""
    w = d.get('width', 1)
    try:
        return int(w)
    except (TypeError, ValueError):
        return 0  # symbolic/parameterized width — unknown, do not assert


def extract_spec_contract(text: str, is_json: bool = False,
                          confirm: bool = True, client_factory=None) -> SpecContract:
    """Extract a declared contract from spec text.

    SEMANTIC double-confirm: prose-inferred fields (reset mode/polarity, output latency,
    FSM output style) are only deterministic CANDIDATES. When `confirm` is set (default)
    each is re-judged by an LLM via llm_semantic_confirm before it is trusted — the
    program's parse of meaning is inferior to the model's. On a host with no LLM backend
    this is a no-op that records the candidate as `unconfirmed-no-backend` (for agent-layer
    confirmation). JSON contracts are authoritative and skip confirmation.

    JSON form: {"module":..,"ports":[{"name","direction","width"}],
                "reset":{"mode","polarity","signal"},"latency_registered":bool}
    Else: natural-language bullets first; if none, Verilog port declarations
    (covers a markdown ```verilog module(...)``` block). Reset mode/polarity and
    output-latency are read from the prose either way.
    """
    if is_json:
        data = json.loads(text)
        if isinstance(data, list):          # bare port list [{...}, ...]
            port_dicts, rst, mod, lat = data, {}, None, None
        else:                               # {"ports":[...],"reset":{...},...}
            port_dicts = data.get('ports', [])
            rst = data.get('reset', {}) or {}
            # A JSON spec contract names its top under `module` OR `top_module`
            # — L9_INTEGRATION_SPEC.json emits the latter. Reading only `module`
            # left mod=None, and the caller's `args.top or spec.module` then fell
            # back to "the first module found" in the RTL directory: on any
            # multi-module design that is a SUBMODULE, and the whole port
            # conformance verdict was rendered against the wrong module.
            mod = data.get('module') or data.get('top_module')
            lat = data.get('latency_registered')
        ports = [Port(d['name'], _json_port_direction(d), _json_port_width(d),
                      bool(d.get('optional')) if isinstance(d, dict) else False)
                 for d in port_dicts]
        return SpecContract(module=mod, ports=ports,
                            reset_mode=rst.get('mode'),
                            reset_polarity=rst.get('polarity'),
                            reset_signal=rst.get('signal'),
                            latency_registered=lat,
                            fsm_output_style=(data.get('fsm_output_style')
                                              if isinstance(data, dict) else None),
                            source='json')

    clean = strip_comments(text)
    ports = _parse_nl_ports(clean)
    source = 'nl'
    table_notes: List[str] = []
    if not ports:
        region = _module_port_region(clean)
        if region is not None:                      # ANSI markdown module header
            ports = parse_verilog_ports(region)
            source = 'verilog'
        else:
            # Datasheet PIN-CONFIGURATION / interface TABLE (parsed from the raw
            # text — markdown cells are not Verilog, so they pre-empt comment
            # stripping). Tried after NL bullets + the ANSI header, before a
            # non-ANSI module decl / prose, per the contract-extractor coverage plan.
            tbl_ports, table_notes = _parse_md_table_ports(text)
            if tbl_ports:
                ports = tbl_ports
                source = 'md-table'
            elif re.search(r'\bmodule\s+\w+[\s\S]*?\bendmodule\b', clean):
                # A genuine non-ANSI Verilog module FENCE (`module <name> ... ;
                # input/output decls ... endmodule`). ORGANIC-20260614 C1 (#751):
                # the old guard fired on the bare WORD 'module' anywhere in prose
                # ("Design a GP module", "Modify the existing module"), so the
                # ENTIRE natural-language spec was scanned as Verilog and the
                # _PORT_DECL regex harvested English phrases as phantom ports
                # ('1-bit input signal'->'signal', 'output of that'->'of',
                # 'output every clock'->'every'). Requiring a real
                # `module ... endmodule` fence — which prose never has — keeps
                # the legitimate non-ANSI module path while restoring the
                # documented invariant: never scan raw prose for input/output
                # words. (Real ANSI/non-ANSI headers in the corpus are already
                # caught by _module_port_region above; this branch only covers a
                # truly fenced non-ANSI declaration.)
                # Prefer the TopModule target if the spec embeds several module decls.
                _, ports = parse_rtl_ports(clean, "TopModule")
                source = 'verilog'
            else:                                   # pure prose: no interface
                ports = []                           # declared — never scan raw
                source = 'none'                      # prose for "input/output" words
    # Module name: prefer the target `TopModule` when a spec embeds several module
    # headers (a reference/buggy example before the real target), else the first.
    mod = None
    names = re.findall(r'\bmodule\s+(\w+)', clean)
    if "TopModule" in names:
        mod = "TopModule"
    elif names:
        mod = names[0]
    else:
        mm = re.search(r'module\s+named\s+`?(\w+)`?', text, re.I)
        if mm:
            mod = mm.group(1)
    mode, polarity, signal = _detect_reset(text)
    contract = SpecContract(module=mod, ports=ports, reset_mode=mode,
                            reset_polarity=polarity, reset_signal=signal,
                            latency_registered=_detect_latency(text),
                            fsm_output_style=_detect_fsm_output_style(text), source=source,
                            notes=table_notes)
    if confirm:
        # program PROPOSES (above) -> LLM CONFIRMS/CORRECTS the semantic candidates.
        try:
            from llm_semantic_confirm import confirm_contract, manifest
        except ImportError:
            from .llm_semantic_confirm import confirm_contract, manifest  # packaged
        contract.semantic_confirmations = manifest(
            confirm_contract(contract, text, client_factory=client_factory))
    return contract
