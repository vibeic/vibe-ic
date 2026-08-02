#!/usr/bin/env python3
"""clock_domain_reg_crossing_check.py — RTL-level clock-domain-crossing screen.

Answers, from the RTL alone: *does this design carry a state bit from one
clock domain into another without re-synchronising it?* An unsynchronised
crossing is the classic silent-deadlock shape — the receiving domain samples a
value that is metastable or simply never coherent, so a status flag it computes
from that value never asserts and anything waiting on that flag waits forever.
A single-clock functional check cannot see this, and neither can equivalence
checking against a netlist built from the same RTL.

WHY THIS IS NOT ALREADY COVERED (the gap this closes)
  * `cdc_async_input_check.py` screens **top-level input ports** (and
    `*_pad/_async/_raw` names) for a 2-flop synchroniser. An internal register
    written under one clock and read under another is neither a port nor
    conventionally named, so it is invisible to that check.
  * `cdc_crossing_check.py` reads a CDC **report artifact**; for a multi-clock
    design it accepts `verdict=SKIPPED-CONDITION` as a disclosed capability gap
    (WAIVED-DEFERRED, exit 0). That is an honest waiver, but it means a
    multi-clock design can clear the CDC step with **no RTL ever analysed**.
  * `handshake_livelock_result_stability_check.py` only examines modules that
    expose an output whose name contains `valid` together with an input whose
    name contains `ready`; a design that signals through status flags of any
    other name is skipped by construction.

So this check reads the RTL, and only the RTL.

WHAT IT DOES, per module
  1. Extract every sequential `always` / `always_ff` block and attribute it to a
     clock domain (the edge signal in the sensitivity list that is not a reset).
  2. If the module has fewer than 2 clock domains, SKIP it. A single-clock
     module has no crossing to make, so this check can never fire on one.
  3. Per domain: `writes[d]` = identifiers assigned in that domain's blocks;
     `idents[d]` = every identifier appearing in that domain's blocks, expanded
     through continuous-assign (`assign`) aliases so a purely combinational path
     between two domains is seen too.
  4. A CROSSING is a register R with R in `writes[A]`, R in `idents[B]`, and R
     NOT in `writes[B]`, for domains A != B.
  5. For each crossing, look in the RECEIVING domain B for a synchroniser: a
     first stage `s1 <= R` (direct, bit-select, or concat/shift form) and a
     second stage `s2 <= s1` (or `s1` declared >= 2 bits and shifted).

FINDINGS
  ERROR  CDC_REG_NO_SYNC
      A register crosses domains with no synchroniser at all in the receiving
      domain. This is the unambiguous, deadlock-capable case.
  WARN   CDC_MULTIBIT_NO_GRAY
      A multi-bit register crosses domains through a per-bit synchroniser with
      no gray-encoding evidence. Independent bits settle on different cycles, so
      the receiving domain can observe a value the sender never held; a status
      flag compared against such a value can miss its condition. Reported, and
      fails only under `--strict`, because a multi-bit crossing can also be made
      safe by a stability qualifier this check does not model.

DELIBERATELY CONSERVATIVE — the ERROR tier stays silent when a synchroniser
chain exists at all, even if the raw register is also read directly elsewhere.
Under-reporting is preferred to firing on a design that is in fact correct.

chip-AGNOSTIC and design-AGNOSTIC: detection is structural (sensitivity lists,
assignment LHS sets, identifier sets). No design name, vendor, PDK, protocol or
signal-name literal decides any verdict; the only names consulted are the
generic reset/clock word-stems used to tell a clock apart from a reset inside a
sensitivity list.

CLI (matches the structural-gate convention):
    python3 clock_domain_reg_crossing_check.py <project_dir>
    python3 clock_domain_reg_crossing_check.py --rtl-dir <dir>
    python3 clock_domain_reg_crossing_check.py <project_dir> --json out.json
    python3 clock_domain_reg_crossing_check.py <project_dir> --strict

Exit codes:
    0 = PASS (no ERROR findings; no ERROR/WARN under --strict)
    1 = FAIL (ERROR findings, or any WARN under --strict)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import rtl_scan_scope as _scan_scope
except ImportError:  # pragma: no cover - packaged relative import
    from . import rtl_scan_scope as _scan_scope  # type: ignore


# --------------------------------------------------------------------------
# Generic word-stems. These do NOT select a design; they only let the parser
# tell a clock apart from a reset when both appear in one sensitivity list.
# --------------------------------------------------------------------------
_RESET_STEM = re.compile(r'(?:^|_)(?:a?rst|reset|clr|clear|nrst|resetn|rstn)(?:_|n?$)', re.I)

# Verilog/SystemVerilog keywords that must never be mistaken for a signal.
_KEYWORDS: Set[str] = {
    'always', 'always_ff', 'always_comb', 'always_latch', 'assign', 'begin',
    'end', 'if', 'else', 'case', 'casex', 'casez', 'endcase', 'default',
    'posedge', 'negedge', 'or', 'and', 'not', 'xor', 'nand', 'nor', 'xnor',
    'wire', 'reg', 'logic', 'bit', 'integer', 'genvar', 'parameter',
    'localparam', 'input', 'output', 'inout', 'module', 'endmodule',
    'function', 'endfunction', 'task', 'endtask', 'generate', 'endgenerate',
    'for', 'while', 'repeat', 'forever', 'initial', 'signed', 'unsigned',
    'automatic', 'static', 'typedef', 'enum', 'struct', 'packed', 'const',
    'return', 'break', 'continue', 'unique', 'priority', 'inside', 'void',
    'real', 'time', 'string', 'byte', 'shortint', 'int', 'longint',
}

_IDENT = re.compile(r'\b([A-Za-z_]\w*)\b')


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0
    evidence: dict = field(default_factory=dict)


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Lexical helpers
# --------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, preserving line count and offsets."""
    out: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        if src.startswith('/*', i):
            end = src.find('*/', i + 2)
            if end == -1:
                out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:]))
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end + 2]))
            i = end + 2
        elif src.startswith('//', i):
            end = src.find('\n', i)
            if end == -1:
                out.append(' ' * (n - i))
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def identifiers(text: str) -> Set[str]:
    """Every identifier in `text` that is not a language keyword.

    Sized/based literals (`4'd12`, `1'b0`) are removed first so their base
    letters never surface as identifiers.
    """
    text = re.sub(r"\b\d*'[sS]?[bodhBODH][0-9a-fA-FxXzZ_?]+", ' ', text)
    return {m.group(1) for m in _IDENT.finditer(text) if m.group(1) not in _KEYWORDS}


def _match_block(src: str, start: int) -> Tuple[str, int]:
    """Return (body, end_index) for the statement beginning at `start`.

    If the statement opens with `begin`, matches nested begin/end (word-bounded,
    so `endcase`/`endfunction` never close a `begin`). Otherwise returns the
    single statement up to its terminating `;`.
    """
    m = re.compile(r'\s*\bbegin\b').match(src, start)
    if not m:
        semi = src.find(';', start)
        return (src[start:semi + 1], semi + 1) if semi != -1 else (src[start:], len(src))
    depth = 0
    for tok in re.finditer(r'\b(begin|end)\b', src[start:]):
        if tok.group(1) == 'begin':
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                stop = start + tok.end()
                return src[start:stop], stop
    return src[start:], len(src)


# --------------------------------------------------------------------------
# Structure extraction
# --------------------------------------------------------------------------
@dataclass
class SeqBlock:
    clock: str
    body: str
    line: int
    sens: str = ""


def instantiation_operands(body: str) -> Set[str]:
    """Identifiers handed to a submodule through a named port connection.

    A `.port(net)` connection appears only in an instantiation. Whatever a
    module hands to a submodule may be synchronised INSIDE that submodule —
    which this checker cannot see — so such nets are excluded from the ERROR
    tier rather than declared unsynchronised. Name-independent: no
    `*sync*`-style instance-name heuristic is used, so it holds for a
    synchroniser cell whatever it is called.
    """
    ops: Set[str] = set()
    for m in re.finditer(r'\.\s*\w+\s*\(([^()]*)\)', body):
        ops |= identifiers(m.group(1))
    return ops


def bridging_clock_pairs(body: str, domains: List[str]) -> Set[frozenset]:
    """Clock-domain pairs joined by a submodule that is handed BOTH clocks.

    An instantiation receiving two of the module's clocks is a domain-bridging
    element (a synchroniser, a req/ack bridge, an async FIFO cell). Its internals
    are outside this file, so the checker must not assert that no synchronised
    control path exists between those two domains. Structural and
    name-independent — nothing keys on the instance or module name.

    Statements are split on `;`, so each instantiation's port connections group
    together and two unrelated single-clock instances are never merged.
    """
    pairs: Set[frozenset] = set()
    dom = set(domains)
    for stmt in body.split(';'):
        if '.' not in stmt:
            continue
        ops: Set[str] = set()
        for m in re.finditer(r'\.\s*\w+\s*\(([^()]*)\)', stmt):
            ops |= identifiers(m.group(1))
        hit = sorted(ops & dom)
        for i in range(len(hit)):
            for j in range(i + 1, len(hit)):
                pairs.add(frozenset((hit[i], hit[j])))
    return pairs


def memory_arrays(body: str) -> Set[str]:
    """Names declared as an unpacked array (`reg [W:0] mem [0:D];`).

    A memory written under one clock and read under another is a dual-port RAM:
    that IS the primitive, and a synchroniser on its storage array is
    meaningless. Such names are never a crossing for this gate.
    """
    names: Set[str] = set()
    for m in re.finditer(
        r'\b(?:reg|wire|logic|bit)\b[^;\n]*?\b([A-Za-z_]\w*)\s*\[[^\]]*\]\s*(?:\[[^\]]*\]\s*)*;',
        body
    ):
        # Require a range AFTER the identifier — that is the unpacked dimension.
        names.add(m.group(1))
    return names


def split_modules(src: str) -> List[Tuple[str, str, int]]:
    """Return [(module_name, module_body, start_line), ...]."""
    mods: List[Tuple[str, str, int]] = []
    for m in re.finditer(r'\bmodule\s+(\w+)', src):
        end = src.find('endmodule', m.end())
        body = src[m.end():end if end != -1 else len(src)]
        mods.append((m.group(1), body, src[:m.start()].count('\n') + 1))
    return mods


def sequential_blocks(body: str) -> List[SeqBlock]:
    """Extract clocked always blocks, attributing each to its clock signal."""
    blocks: List[SeqBlock] = []
    for m in re.finditer(r'\balways(?:_ff)?\s*@\s*\(', body):
        # Balanced-paren sensitivity list.
        i = m.end()
        depth = 1
        while i < len(body) and depth:
            if body[i] == '(':
                depth += 1
            elif body[i] == ')':
                depth -= 1
            i += 1
        sens = body[m.end():i - 1]
        edges = re.findall(r'\b(?:pos|neg)edge\s+([A-Za-z_]\w*)', sens)
        if not edges:
            continue  # combinational always @(*) — not a clock domain
        non_reset = [e for e in edges if not _RESET_STEM.search(e)]
        clock = non_reset[0] if non_reset else edges[0]
        blk, _ = _match_block(body, i)
        blocks.append(SeqBlock(clock=clock, body=blk, sens=sens,
                               line=body[:m.start()].count('\n') + 1))
    return blocks


def assigned_names(text: str) -> Set[str]:
    """Identifiers appearing as an assignment target inside `text`.

    Handles `x <= ...`, `x = ...`, `x[i] <= ...`, `{a,b} <= ...`. A `<=` used as
    a comparison lives inside an `if(...)`/`case(...)` head, which never begins a
    statement, so anchoring to a statement boundary keeps them apart.
    """
    names: Set[str] = set()
    for m in re.finditer(
        r'(?:^|[;)]|\bbegin\b|\belse\b|\bdo\b)\s*'          # statement boundary
        r'(\{[^{}]*\}|[A-Za-z_]\w*(?:\s*\[[^\]]*\])*)'      # target
        r'\s*(?:<=|=)(?!=)',
        text
    ):
        names |= identifiers(m.group(1))
    return names


def continuous_assigns(body: str) -> Dict[str, Set[str]]:
    """Map each continuously-driven net to the identifiers driving it.

    Covers both spellings of a continuous driver: an explicit `assign` statement
    and a net declaration carrying an initialiser (`wire x = a & b;`). Missing
    the second spelling hides any combinational path written that way.
    """
    amap: Dict[str, Set[str]] = {}

    def _record(lhs: str, rhs: str) -> None:
        for name in identifiers(lhs):
            amap.setdefault(name, set()).update(identifiers(rhs))

    for m in re.finditer(r'\bassign\b([^;]*);', body):
        stmt = m.group(1)
        eq = re.search(r'(?<![<>=!])=(?!=)', stmt)
        if eq:
            _record(stmt[:eq.start()], stmt[eq.end():])

    # `wire [3:0] x = expr;` / `logic y = expr;` — a declaration that is also a
    # continuous driver. `reg`/`logic` initialisers inside a procedural block are
    # not matched here because a declaration statement always starts with its
    # net type at a statement boundary.
    for m in re.finditer(
        r'(?:^|[;)]|\bbegin\b)\s*\b(?:wire|logic|bit)\b\s*'
        r'(?:signed\s+|unsigned\s+)?(?:\[[^\]]*\]\s*)?'
        r'([A-Za-z_]\w*)\s*=(?!=)([^;]*);',
        body
    ):
        _record(m.group(1), m.group(2))

    return amap


def expand_aliases(seed: Set[str], amap: Dict[str, Set[str]], limit: int = 8) -> Set[str]:
    """Close `seed` over continuous-assign sources (depth-limited, cycle-safe)."""
    out = set(seed)
    frontier = set(seed)
    for _ in range(limit):
        nxt: Set[str] = set()
        for name in frontier:
            for src_name in amap.get(name, ()):
                if src_name not in out:
                    nxt.add(src_name)
        if not nxt:
            break
        out |= nxt
        frontier = nxt
    return out


def declared_width(body: str, name: str) -> int:
    """Declared bit width of `name`.

    Returns 1 when unsized or undeclared, and -1 when the width is an
    expression this checker will not evaluate (a parameter). -1 means
    "multi-bit, exact width unknown" — callers must treat it as multi-bit and
    must NOT print it as a bit count, because reporting a guessed number as
    measured evidence is worse than reporting that it is parameterised.
    """
    m = re.search(
        r'\b(?:input|output|inout|reg|wire|logic|bit)\b[^;\n]*?'
        r'\[\s*([^\]:]+?)\s*:\s*([^\]]+?)\s*\][^;\n]*?\b' + re.escape(name) + r'\b',
        body
    )
    if not m:
        return 1
    try:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    except ValueError:
        return -1  # parameterised width — multi-bit, exact value not evaluated


def width_text(width: int) -> str:
    """Human-readable width for a finding message."""
    return "parameterised-width" if width < 0 else f"{width}-bit"


# --------------------------------------------------------------------------
# Synchroniser + gray-code recognition
# --------------------------------------------------------------------------
def _stage_targets(dom_text: str, source: str) -> Set[str]:
    """Names taking `source` directly as their next value (stage-1 candidates)."""
    src = re.escape(source)
    targets: Set[str] = set()
    # s1 <= source;  /  s1 <= source[3:0];
    for m in re.finditer(r'\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=\s*'
                         + src + r'\s*(?:\[[^\]]*\])?\s*;', dom_text):
        targets.add(m.group(1))
    # s1 <= {s1[n-2:0], source};  (compact shift-register synchroniser)
    for m in re.finditer(r'\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=\s*\{[^{}]*\b'
                         + src + r'\b[^{}]*\}\s*;', dom_text):
        targets.add(m.group(1))
    return targets


def is_synchronized(dom_text: str, mod_body: str, source: str) -> bool:
    """True when the receiving domain re-registers `source` at least twice."""
    stage1 = _stage_targets(dom_text, source)
    if not stage1:
        return False
    for s1 in stage1:
        # Explicit second flop: s2 <= s1;  (or s2 <= {..., s1})
        pat = (r'\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=\s*(?:'
               + re.escape(s1) + r'\s*(?:\[[^\]]*\])?|\{[^{}]*\b'
               + re.escape(s1) + r'\b[^{}]*\})\s*;')
        for m in re.finditer(pat, dom_text):
            if m.group(1) != s1:
                return True
        # Shift-register form: a >=2-bit stage-1 register is itself 2 flops.
        if declared_width(mod_body, s1) != 1 and re.search(
            r'\b' + re.escape(s1) + r'\s*(?:\[[^\]]*\])?\s*<=\s*\{[^{}]*\b'
            + re.escape(s1) + r'\b[^{}]*\}', dom_text
        ):
            return True
    return False


def has_gray_evidence(mod_body: str, source: str) -> bool:
    """True when `source` shows gray-encoding evidence.

    Recognises the canonical binary->gray form `x ^ (x >> 1)` and the equivalent
    concatenated-shift XOR, plus an explicit `gray` in the net's own name.
    """
    if re.search(r'gray', source, re.I):
        return True
    src = re.escape(source)
    # source <= bin ^ (bin >> 1)   /   source = {1'b0, bin[n:1]} ^ bin
    for m in re.finditer(r'\b' + src + r'\s*(?:\[[^\]]*\])?\s*(?:<=|=)(?!=)([^;]*);',
                         mod_body):
        rhs = m.group(1)
        if '^' in rhs and ('>>' in rhs or '{' in rhs):
            return True
        if re.search(r'gray', rhs, re.I):
            return True
    return False


# --------------------------------------------------------------------------
# Per-file audit
# --------------------------------------------------------------------------
def audit_text(src: str, rel: str) -> Tuple[List[Finding], int]:
    """Audit one already-comment-stripped source. Returns (findings, modules_examined)."""
    findings: List[Finding] = []
    examined = 0

    for mod_name, body, mod_line in split_modules(src):
        blocks = sequential_blocks(body)
        domains = sorted({b.clock for b in blocks})
        if len(domains) < 2:
            continue  # single-clock module: no crossing can exist
        examined += 1

        amap = continuous_assigns(body)
        inst_ops = instantiation_operands(body)
        mem_names = memory_arrays(body)
        bridges = bridging_clock_pairs(body, domains)
        writes: Dict[str, Set[str]] = {}
        idents: Dict[str, Set[str]] = {}
        dom_text: Dict[str, str] = {}
        dom_line: Dict[str, int] = {}
        for b in blocks:
            writes.setdefault(b.clock, set()).update(assigned_names(b.body))
            # A name in this block's OWN sensitivity list is a clock or an async
            # reset term, not data the block samples. Its re-test inside the
            # body (`if (!rst_n)`) is the reset branch. Counting it as a data
            # read makes every reset network look like a data crossing; reset
            # crossings are a reset-domain concern and belong to the RDC gate.
            sens_names = identifiers(b.sens)
            idents.setdefault(b.clock, set()).update(identifiers(b.body) - sens_names)
            dom_text[b.clock] = dom_text.get(b.clock, '') + '\n' + b.body
            dom_line.setdefault(b.clock, mod_line + b.line)

        # Reads reachable in each domain, including purely combinational paths.
        reach: Dict[str, Set[str]] = {
            d: expand_aliases(idents[d], amap) for d in domains
        }

        for recv in domains:
            for send in domains:
                if send == recv:
                    continue
                crossing = sorted(
                    (writes[send] - writes[recv]) & reach[recv]
                    - set(domains)          # a clock is not a crossing datum
                )
                # Is ANY register from this sending domain properly
                # synchronised into this receiving domain? If so the pair has a
                # working control path, and an unsynchronised multi-bit value
                # alongside it is the standard "data qualified by a synchronised
                # control signal" pattern — real, and not decidable as a defect
                # from structure alone. It is reported as WARN, not ERROR.
                has_control_sync = (
                    frozenset((send, recv)) in bridges
                    or any(is_synchronized(dom_text[recv], body, r)
                           for r in crossing if not _RESET_STEM.search(r))
                )
                for reg in crossing:
                    if _RESET_STEM.search(reg):
                        continue            # reset crossings are RDC, not this gate
                    if reg in mem_names:
                        continue            # dual-port memory array, not a flop crossing
                    if reg in inst_ops:
                        continue            # may be synchronised inside a submodule
                    if is_synchronized(dom_text[recv], body, reg):
                        width = declared_width(body, reg)
                        if width != 1 and not has_gray_evidence(body, reg):
                            findings.append(Finding(
                                rule='CDC_MULTIBIT_NO_GRAY',
                                severity='WARN',
                                message=(
                                    f"module '{mod_name}': {width_text(width)} '{reg}' is written in "
                                    f"clock domain '{send}' and synchronised bit-by-bit into "
                                    f"'{recv}' with no gray-encoding evidence; the receiving "
                                    f"domain can sample a value the sending domain never held"),
                                file=rel, line=dom_line[recv],
                                evidence={'module': mod_name, 'register': reg,
                                          'width': width, 'from_domain': send,
                                          'to_domain': recv, 'synchronised': True,
                                          'gray_evidence': False},
                            ))
                        continue
                    width = declared_width(body, reg)
                    qualified = has_control_sync and width != 1
                    findings.append(Finding(
                        rule=('CDC_UNSYNCED_DATA_QUALIFIED' if qualified
                              else 'CDC_REG_NO_SYNC'),
                        severity='WARN' if qualified else 'ERROR',
                        message=(
                            f"module '{mod_name}': {width_text(width)} '{reg}' crosses from clock "
                            f"domain '{send}' to '{recv}' unsynchronised, alongside a "
                            f"synchronised control path — safe only if the receiver samples "
                            f"it strictly while that control qualifies it"
                            if qualified else
                            f"module '{mod_name}': '{reg}' is written in clock domain "
                            f"'{send}' and read in clock domain '{recv}' with no "
                            f"synchroniser (>=2 flops) in '{recv}', and no synchronised "
                            f"control path exists between those domains; a status computed "
                            f"from it in '{recv}' can fail to assert"),
                        file=rel, line=dom_line[recv],
                        evidence={'module': mod_name, 'register': reg,
                                  'width': width,
                                  'from_domain': send, 'to_domain': recv,
                                  'synchronised': False,
                                  'control_path_synchronised': has_control_sync,
                                  'clock_domains': domains},
                    ))
    return findings, examined


def collect_files(project_dir: Optional[str], rtl_dir: Optional[str],
                  paths: List[str]) -> List[Path]:
    files: List[Path] = []
    if rtl_dir:
        root = Path(rtl_dir)
        if root.is_dir():
            for ext in ('*.v', '*.sv'):
                files.extend(sorted(root.rglob(ext)))
        elif root.is_file():
            files.append(root)
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            files.append(pp)
        elif pp.is_dir():
            for ext in ('*.v', '*.sv'):
                files.extend(sorted(pp.rglob(ext)))
    if not files and project_dir:
        files = list(_scan_scope.authoritative_rtl_files(Path(project_dir).resolve()))
    # dedup, preserve order
    seen: Set[Path] = set()
    out: List[Path] = []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            out.append(f)
    return out


def audit(project_dir: Optional[str] = None, rtl_dir: Optional[str] = None,
          paths: Optional[List[str]] = None, strict: bool = False) -> AuditResult:
    result = AuditResult(program='clock_domain_reg_crossing_check', passed=True)
    files = collect_files(project_dir, rtl_dir, paths or [])
    examined = 0
    for f in files:
        try:
            raw = f.read_text(errors='replace')
        except Exception:
            continue
        base = Path(project_dir).resolve() if project_dir else None
        rel = str(f)
        if base is not None:
            try:
                rel = str(f.resolve().relative_to(base))
            except ValueError:
                pass
        fnd, ex = audit_text(strip_comments(raw), rel)
        result.findings.extend(fnd)
        examined += ex

    errors = [f for f in result.findings if f.severity == 'ERROR']
    warns = [f for f in result.findings if f.severity == 'WARN']
    result.passed = not errors and not (strict and warns)
    result.summary = {
        'files_scanned': len(files),
        'multi_clock_modules_examined': examined,
        'errors': len(errors),
        'warnings': len(warns),
        'strict': strict,
        # No RTL at all is NOT a pass. The structural-gate dispatcher reads
        # exit 2 as input-missing/skip; reporting PASS on an empty scan would
        # let a project with no RTL collect a green CDC verdict it never earned.
        'no_input': len(files) == 0,
    }
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('project_dir', nargs='?', default=None)
    p.add_argument('paths', nargs='*', default=[])
    p.add_argument('--rtl-dir', dest='rtl_dir', default=None)
    p.add_argument('--strict', action='store_true',
                   help='treat WARN findings as failures')
    p.add_argument('--json', nargs='?', const='-', default=None,
                   help='Emit JSON. With no value → stdout. With a path → write file.')
    args = p.parse_args()

    project_dir = args.project_dir
    paths = list(args.paths)
    if project_dir and not Path(project_dir).is_dir():
        paths.insert(0, project_dir)
        project_dir = None
    if project_dir is None and not paths and not args.rtl_dir:
        project_dir = '.'

    result = audit(project_dir=project_dir, rtl_dir=args.rtl_dir,
                   paths=paths, strict=args.strict)

    if args.json is not None:
        payload = json.dumps(asdict(result), indent=2)
        if args.json == '-':
            print(payload)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload)
    else:
        for f in result.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity}] {f.rule} ({loc}): {f.message}")
        verdict = ('SKIP (no RTL found)' if result.summary.get('no_input')
                   else ('PASS' if result.passed else 'FAIL'))
        print(f"\n{verdict} — {result.summary}")
    if result.summary.get('no_input'):
        sys.exit(2)
    sys.exit(0 if result.passed else 1)


if __name__ == '__main__':
    main()
