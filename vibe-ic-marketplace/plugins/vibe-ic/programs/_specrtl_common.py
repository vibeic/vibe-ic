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
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


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
# Ports
# ---------------------------------------------------------------------------
@dataclass
class Port:
    name: str
    direction: str   # input / output / inout
    width: int       # 1 for scalar


_PORT_DECL = re.compile(
    r'\b(input|output|inout)\b\s*(?:reg|wire|logic|signed|unsigned|\s)*'
    r'(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?'
    r'([A-Za-z_]\w*(?:\s*,\s*(?!(?:input|output|inout)\b)[A-Za-z_]\w*)*)')


# function/task argument declarations use the same input/output keywords as module
# ports but are lexically scoped to the subprogram — blank their bodies (preserving
# newlines) before port extraction so they are not mistaken for module ports.
_SUBPROGRAM = re.compile(
    r'\bfunction\b.*?\bendfunction\b|\btask\b.*?\bendtask\b', re.S | re.I)


def _strip_subprograms(text: str) -> str:
    return _SUBPROGRAM.sub(
        lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group(0)), text)


def parse_verilog_ports(text: str) -> List[Port]:
    """Parse Verilog `input/output/inout [msb:lsb] a, b` declarations."""
    ports: List[Port] = []
    for m in _PORT_DECL.finditer(text):
        direction = m.group(1)
        if m.group(2) is not None:
            width = abs(int(m.group(2)) - int(m.group(3))) + 1
        else:
            width = 1
        for nm in re.split(r'\s*,\s*', m.group(4)):
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
# Copular / auxiliary verbs that mark the bullet as a SENTENCE, not a port decl.
_NL_PORT_COPULA_RE = re.compile(
    r'^[ \t]*(?:is|are|was|were|will|shall|should|must|can|may|has|have|'
    r'represents?|denotes?|indicates?|holds?|carries|specif\w+)\b', re.I)


def _nl_port_is_prose(name: str, tail: str) -> bool:
    """True when an `- input <name> <tail>` bullet is ordinary PROSE rather than
    a port declaration: the name is a known non-port word, the bullet is a
    heading (`name:`), or the tail is a copular sentence (`name is …`)."""
    if name.lower() in _NL_PORT_PROSE_NAMES:
        return True
    t = tail or ""
    if t.lstrip().startswith(":"):
        return True                       # "- Input ports:" heading
    if _NL_PORT_COPULA_RE.match(t):
        return True                       # "- Output latency is 1 cycle"
    return False


def _parse_nl_ports(text: str) -> List[Port]:
    ports: List[Port] = []
    for m in _NL_PORT.finditer(text):
        direction = m.group(1).lower()
        name = m.group(2)
        if _nl_port_is_prose(name, m.group("tail") or ""):
            continue
        width = int(m.group(3)) if m.group(3) else 1
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
_DIR_HDR = re.compile(r'^\s*(dir|direction|i\s*/\s*o|i/o|io|mode|type)\s*$', re.I)
_WIDTH_HDR = re.compile(r'^\s*(width|bits?|size|\[?\s*msb\s*:\s*lsb\s*\]?|range)\s*$', re.I)


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


def _parse_md_table_ports(text: str) -> Tuple[List[Port], List[str]]:
    """Parse a markdown PIN/interface table into ports.

    Returns (ports, notes). `notes` carries an advisory string when a qualifying
    table header was found but some body rows could not be parsed into ports, so
    the caller can surface it (a partial parse must never be a silent 0-port skip).
    """
    lines = text.splitlines()
    best_ports: List[Port] = []
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
            if len(ports) >= len(best_ports):
                best_ports = ports
                notes = []
                if len(ports) < dir_valued_rows or unparsed:
                    notes = [
                        f"spec interface present as a table but only {len(ports)} "
                        f"port(s) parsed from {body_rows} row(s) — verify the "
                        f"interface table is fully captured."]
        i = j if j > i else i + 1
    return best_ports, notes


def _module_port_region(text: str, prefer: str = "TopModule") -> Optional[str]:
    """Return the ANSI port-list inside `module name ( ... )`, or None.

    Lets a markdown spec carry a fenced ```verilog module(...)``` header without
    prose ("...provides valid outputs...") leaking false ports.

    When the spec embeds MULTIPLE module declarations (e.g. a reference or buggy
    module shown before the real target header — common in code-completion and
    bug-fix prompts), prefer the one named `prefer` (default TopModule, the target)
    so the contract is taken from the target header, not the embedded example."""
    headers = list(re.finditer(r'\bmodule\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\(', text))
    if not headers:
        return None
    m = next((h for h in headers if h.group(1) == prefer), headers[0])
    i = text.index('(', m.start())
    depth, n = 0, len(text)
    while i < n:
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[m.start():i]
        i += 1
    return None


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
            mod = data.get('module')
            lat = data.get('latency_registered')
        ports = [Port(d['name'], d.get('direction', 'input'), int(d.get('width', 1)))
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
