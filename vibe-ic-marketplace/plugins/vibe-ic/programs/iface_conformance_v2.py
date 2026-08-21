#!/usr/bin/env python3
"""iface_conformance_v2.py — prompt→interface conformance gate (ORGANIC #695).

PROBLEM (Oracle-RCA on the CVDP cvdp-open residual): a recurring class of
blind-author miss is PROMPT-DERIVABLE and PROGRAM-CHECKABLE, yet no gate
catches it before the completion is emitted. The hidden cocotb harness binds
to the DUT by EXACT signal names + directions and derives its TOPLEVEL from
the canonical problem / file name, so any of:

  (1) MODULE-NAME-CASE — the RTL module name differs (often only in CASE)
      from the canonical id stem the harness uses as TOPLEVEL
      (RTL `FindFasterClock` vs harness top `findfasterclock`) → the harness
      `-s findfasterclock` finds no such module → elaboration fail;
  (2) MISSING-PORT — an interface port NAMED in the prompt (a markdown table
      row, a backtick signal name with a nearby direction word, a given-code
      module header, a wavedrom `{"name":…}` entry) is ABSENT from the RTL
      port list (AXI master omitting `ar*`/`aw*`; `s_ready`; a
      `register_addr_i` named only in a wavedrom) → the harness drive/read of
      that net does not bind → elab / functional fail;
  (3) PORT-DIRECTION — a port whose DIRECTION disagrees with the prompt's
      signal table (the harness DRIVES `sram_valid` as a DUT input but the
      RTL declares it `output`) → functional fail.

All three are derivable from the PROMPT ALONE (table rows / backtick signal
names / a given-code module header / wavedrom name entries / the canonical
id), so a DETERMINISTIC gate reading ONLY the prompt + the authored RTL can
flag them at emit time. Run-time stays BLIND: this gate NEVER opens the
oracle / hidden testbench / reference RTL — only the two files it is handed.

ADVISORY by default (prompt extraction is heuristic — a prompt mentions
internal signals that are legitimately NOT ports, so a false positive must
NOT hard-block an otherwise-correct emit). `--strict` exits 1 on any finding.

SCOPING (ORGANIC #726): the gate scopes prompt-named identifiers to their
OWNING module so it does not false-fire. A prompt token is SATISFIED if it is a
declared port of ANY module in the completion (top OR sub-module) or of a
harness-supplied context module; a token equal to a declared MODULE name (a
markdown `### Module: Foo` heading, a backtick wrapping a sub-module name) is
EXCLUDED from the signal/direction comparison; and MODULE-NAME-CASE is
SUPPRESSED when the prompt's RTL skeleton declares the module name verbatim
(the harness instantiates that exact name).

CLI:
    python3 iface_conformance_v2.py --id <problem_id> \
        --prompt <prompt.txt> --rtl <design.sv> \
        [--context <ctx.sv> ...] [--strict] [--json OUT]

  --id      the canonical problem id; the harness TOPLEVEL stem is derived
            from it (`cvdp_copilot_findfasterclock_0001` → `findfasterclock`).
            Optional — when absent only port name/direction checks run.
  --prompt  the prompt / spec text the author was given (the ONLY interface
            source other than the id).
  --rtl     the authored RTL the author is about to emit.
  --context a harness-supplied context RTL file (`input.context` rtl/*.sv); the
            ports and module names it declares count as SATISFIED, not
            author-missing (the #715 family). Repeatable.
  --strict  exit 1 on any finding (default: advisory, always exit 0).

Exit codes:
    0  no finding, OR findings in advisory (default) mode
    1  ≥1 finding AND --strict
    2  bad input (missing/empty file)

Stdout: one line per finding (`MODULE-NAME-CASE: …`, `MISSING-PORT: …`,
`PORT-DIRECTION: …`); `interface-conformance ok` when conformant.

chip-AGNOSTIC: pure prompt-prose + RTL structure; no chip / vendor / SKU
literal, no dataset / oracle access.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import _provenance as _prov  # noqa: E402  (ORGANIC #770)

# ORGANIC #770 — a prompt interface signal whose ONLY evidence is a free-prose
# direction-proximity scrape (`_DIR_NEAR_*`, wavedrom name) is a PROSE_HEURISTIC
# source; a real markdown signal table or the prompt's given-code module header
# is a STRUCTURAL source. A finding sourced ONLY from prose/wavedrom is
# provenance-gated against the RTL; a finding with ANY structural source keeps
# its historical blocking power.
#
# ORGANIC #809 (R12C3) — a bold-label structured port declaration is ALSO a
# STRUCTURAL source: a markdown bullet `- **<Name>:** ...` under a
# direction-asserting section heading (`### New Input:` / `### Inputs`), OR a
# bullet `- **<name> (input, wire)**: ...` carrying the direction inside the
# bold label, declares an interface port as authoritatively as a port table
# row. (CVDP cvdp_copilot_moving_average_0005 declares its sole new port `enable`
# ONLY in this form — `## New Input` + `- **enable:** 1-bit` — which the prose /
# table / given-code extractors never see, so an RTL OMITTING `enable` slipped
# through `interface-conformance ok`.) chip-AGNOSTIC: pure markdown structure.
_STRUCTURAL_IFACE_SOURCES = frozenset({"table", "given_code", "bold_label"})


def _iface_provenance(sources: Set[str]) -> str:
    """STRUCTURAL when any source is a real table / given-code header; else
    PROSE_HEURISTIC (prose-direction proximity, wavedrom). chip-AGNOSTIC."""
    if sources & _STRUCTURAL_IFACE_SOURCES:
        return _prov.STRUCTURAL
    return _prov.PROSE_HEURISTIC


# ── id → canonical harness TOPLEVEL stem ────────────────────────────────────
# Mirrors cvdp_gate.required_top_from_id but kept self-contained so this gate
# has no import-time dependency on the benchmark harness. The CVDP id follows
# `cvdp_copilot_<stem>[_NNNN]`; the harness TOPLEVEL stem is `<stem>` (the id
# minus the `cvdp_copilot_` prefix and any trailing `_NNNN` variant suffix).
# For a non-CVDP id we fall back to the id minus a trailing `_NNNN`.
_CVDP_VARIANT_RE = re.compile(r"^cvdp_copilot_(.+?)_\d{3,}$")
_CVDP_PLAIN_RE = re.compile(r"^cvdp_copilot_(.+)$")
_TRAILING_NUM_RE = re.compile(r"^(.+?)_\d{3,}$")


def harness_top_from_id(rid: Optional[str]) -> Optional[str]:
    """The canonical harness TOPLEVEL stem derived from the problem id, or
    None when no id is given. The harness derives its cocotb TOPLEVEL from
    this canonical name, so the RTL module must match it CASE-EXACTLY."""
    rid = (rid or "").strip()
    if not rid:
        return None
    m = _CVDP_VARIANT_RE.match(rid)
    if m:
        return m.group(1)
    m = _CVDP_PLAIN_RE.match(rid)
    if m:
        return m.group(1)
    m = _TRAILING_NUM_RE.match(rid)
    if m:
        return m.group(1)
    return rid


# ── RTL parsing (case-PRESERVING) ───────────────────────────────────────────
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def _strip_comments(text: str) -> str:
    t = _BLOCK_COMMENT_RE.sub(" ", text)
    t = _LINE_COMMENT_RE.sub(" ", t)
    return _STRING_LIT_RE.sub('""', t)


_MODULE_HDR_RE = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\s*"
    r"(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"   # optional #(params)
    r"(?:\((?P<ports>(?:[^()]|\([^()]*\))*)\))?\s*;",
    re.DOTALL)

# Canonical SystemVerilog DIRECTION + TYPE/SIGN keywords. These are the tokens
# the header-port parsers (`_ANSI_PORT_RE` / `_NONANSI_PORT_RE`) consume as
# direction / net-type / sign qualifiers and that `_parse_module_match` already
# excludes from its bare-name harvest (the inline tuple it used). Promoted to a
# single named frozenset so every prompt-side extractor that harvests candidate
# port NAMES filters them through the SAME set rather than re-inventing a
# divergent list. A SystemVerilog reserved TYPE/DIRECTION keyword is NEVER a
# legal port identifier, so excluding it as a candidate name can only remove a
# phantom — it can never mask a genuine port. chip-AGNOSTIC.
_SV_PORT_KEYWORDS = frozenset({
    "input", "output", "inout",
    "wire", "reg", "logic", "bit", "signed", "unsigned",
})

# ANSI port declaration inside the header port list, e.g.
# `input wire [3:0] foo`, `output reg bar`, `inout baz`.
_ANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned))*"
    r"(?:\s*\[[^\]]*\])?\s*"
    r"([A-Za-z_]\w*)")

# non-ANSI body declaration: `input [3:0] foo, bar;` / `output reg q;`
_NONANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned))*"
    r"(?:\s*\[[^\]]*\])?\s*"
    r"((?:[A-Za-z_]\w*\s*,\s*)*[A-Za-z_]\w*)\s*;")


# A `module <name>` keyword followed by an identifier — the anchor for the
# depth-aware header scan below. (The full `#(...)` / `(...)` blocks are then
# extracted by walking paren depth, NOT by a fixed-nesting regex, so a param
# default with a nested-paren expression — `$clog2(W)`, `(A + $clog2(B))`,
# nested ternary — no longer makes the whole header un-matchable.)
_MODULE_KW_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")


@dataclass
class _HdrMatch:
    """A depth-scanned module-header match, duck-typed to the subset of the
    re.Match interface `_parse_module_match` uses: `.group(1)` (module name),
    `.group('ports')` (the port-list blob, or None), and `.end()` (the index
    just past the closing `;` of the header — where the body begins)."""
    name: str
    ports: Optional[str]
    end_idx: int

    def group(self, key):
        if key == 1:
            return self.name
        if key == "ports":
            return self.ports
        raise KeyError(key)

    def end(self) -> int:
        return self.end_idx


def _scan_balanced(src: str, open_idx: int) -> int:
    """Given `src[open_idx] == '('`, return the index just past the matching
    ')' to ARBITRARY nesting depth, or -1 if unbalanced. Walks paren depth so
    nested-paren param defaults / port-type expressions are spanned correctly."""
    depth = 0
    i = open_idx
    n = len(src)
    while i < n:
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _find_module_headers(src: str) -> List[_HdrMatch]:
    """Locate every `module <name> [#(...)] [(...)] ;` header in (comment-
    stripped) `src` using a paren-depth-aware scan instead of a single-level
    regex. Returns headers in source order; each carries the module name, the
    raw port-list blob (or None for a non-ANSI bare-name-less header), and the
    body-start index. A header that does not terminate in a `;` (e.g. a stray
    `module` keyword in prose) is skipped."""
    out: List[_HdrMatch] = []
    for km in _MODULE_KW_RE.finditer(src):
        name = km.group(1)
        i = km.end()
        n = len(src)
        # skip whitespace
        while i < n and src[i].isspace():
            i += 1
        # optional #(...) parameter block
        if i < n and src[i] == "#":
            j = i + 1
            while j < n and src[j].isspace():
                j += 1
            if j < n and src[j] == "(":
                close = _scan_balanced(src, j)
                if close == -1:
                    continue
                i = close
                while i < n and src[i].isspace():
                    i += 1
        # optional (ports...) block
        ports_blob: Optional[str] = None
        if i < n and src[i] == "(":
            close = _scan_balanced(src, i)
            if close == -1:
                continue
            ports_blob = src[i + 1:close - 1]
            i = close
            while i < n and src[i].isspace():
                i += 1
        # header must terminate in `;`
        if i < n and src[i] == ";":
            out.append(_HdrMatch(name=name, ports=ports_blob, end_idx=i + 1))
    return out


@dataclass
class RtlIface:
    module_name: Optional[str] = None
    # direction by ORIGINAL-CASE port name
    ports: Dict[str, str] = field(default_factory=dict)

    @property
    def port_names_lower(self) -> Dict[str, str]:
        """lower(name) → original-case name (for case-insensitive lookup)."""
        return {k.lower(): k for k in self.ports}


def _parse_module_match(src: str, m: "re.Match") -> RtlIface:
    """Build an RtlIface from a single _MODULE_HDR_RE match `m` over `src`."""
    iface = RtlIface(module_name=m.group(1))
    ports_blob = m.group("ports") or ""
    # ANSI directions in the header
    for pm in _ANSI_PORT_RE.finditer(ports_blob):
        iface.ports[pm.group(2)] = pm.group(1).lower()
    # bare names in the header (non-ANSI: directions are in the body)
    header_names: List[str] = []
    if ports_blob.strip():
        # tokens that look like identifiers not already captured as ANSI ports
        for nm in re.findall(r"[A-Za-z_]\w*", ports_blob):
            if nm in _SV_PORT_KEYWORDS:
                continue
            header_names.append(nm)
    # non-ANSI body declarations — scan ONLY this module's body (header → its
    # matching endmodule), so a sub-module's body decls aren't attributed here.
    body = src[m.end():]
    em = re.search(r"\bendmodule\b", body)
    if em:
        body = body[:em.start()]
    for pm in _NONANSI_PORT_RE.finditer(body):
        direction = pm.group(1).lower()
        for nm in re.split(r"\s*,\s*", pm.group(2).strip()):
            nm = nm.strip()
            if nm and nm not in iface.ports:
                iface.ports[nm] = direction
    # any header bare-name with no direction found → record as unknown so it's
    # still counted as a declared port (prevents false MISSING-PORT)
    for nm in header_names:
        iface.ports.setdefault(nm, "unknown")
    return iface


def parse_rtl(text: str) -> RtlIface:
    """Parse the FIRST module declaration: name (case-preserved) + ports with
    directions. Handles ANSI (directions in the header) and non-ANSI
    (directions in the body) port styles. This is the TOP the harness binds.

    Uses a paren-depth-aware header scan (`_find_module_headers`) so a module
    whose `#(params)` default contains a nested-paren expression (`$clog2(W)`,
    `(A + $clog2(B))`, nested ternary) is matched correctly instead of being
    silently skipped — which previously made the parser fall through to a later
    sub-module and report every real top port as MISSING (ORGANIC #753)."""
    src = _strip_comments(text)
    hdrs = _find_module_headers(src)
    if not hdrs:
        return RtlIface()
    return _parse_module_match(src, hdrs[0])


def parse_all_rtl(text: str) -> List[RtlIface]:
    """Parse EVERY module declaration in `text`. The first is the TOP; the rest
    are sub-modules. Used so a port declared on ANY module (top OR sub-module)
    counts as SATISFIED — the prompt's given-code may name a sub-module's ports
    that are legitimately declared on that sub-module, not the top (#726)."""
    src = _strip_comments(text)
    return [_parse_module_match(src, m) for m in _find_module_headers(src)]


# ── prompt interface extraction ─────────────────────────────────────────────
# A markdown table row whose first backtick-quoted cell is a signal name and a
# later cell is a direction word: `| `clk_A` | input | ... |`.
_DIR_WORD_RE = re.compile(r"\b(input|output|inout)\b", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([A-Za-z_]\w*)`")

# A backtick signal name followed (within a short window) by a direction word,
# or preceded by one — covers prose like "`s_ready` is an output" and
# "input `register_addr_i`". The window is intentionally tight so unrelated
# prose mentions don't fabricate ports (advisory anyway).
_DIR_NEAR_BEFORE_RE = re.compile(
    r"\b(input|output|inout)\b([^\n`]{0,40}?)`([A-Za-z_]\w*)`",
    re.IGNORECASE)
_DIR_NEAR_AFTER_RE = re.compile(
    r"`([A-Za-z_]\w*)`([^\n`]{0,40}?)\b(?:is\s+(?:an?\s+)?)?(input|output|inout)\b",
    re.IGNORECASE)

# (#753) COPULAR / VALUE-ASSIGNMENT guard for the direction-word-BEFORE rule:
# in mux/selector specs a sentence like "the output clock should be `clk2`" /
# "the output is `clkN`" / "output = `clkN`" describes which INPUT source an
# output EQUALS, not the backticked net's OWN direction. When the gap between
# the direction word and the backtick contains a copular / value verb, the
# backtick is the VALUE, not a port of that direction — skip the record.
_COPULAR_GAP_RE = re.compile(
    r"(?:\bshould\s+be\b|\bis\b|\bare\b|\bequals?\b|\bbecomes?\b|\bdrives?\b|=)",
    re.IGNORECASE)

# (#753) NOUN guard for the direction-word-AFTER rule: "the input"/"the output"
# where the direction word is the trailing NOUN ("the input word"/"the input")
# is a reference to the data word, NOT a port-direction tag (e.g.
# "`sync_header` is the first 2 bits of the input", "`Dx` ... from the input").
# Reject when the direction word is immediately preceded by the bare article
# "the" (the indefinite "is an output" port phrasing is already consumed by the
# rule's optional `is\s+an?\s+` prefix, so it is NOT caught by this guard).
_NOUN_THE_TAIL_RE = re.compile(r"\bthe\s*$", re.IGNORECASE)

# (#762) ATTRIBUTIVE-NOUN guard for the direction-word-BEFORE rule: in CSR /
# peripheral specs a phrase like "driven by the output data register (`reg_out`)"
# or "loaded from the input control register (`reg_in`)" uses the direction word
# as an ATTRIBUTIVE ADJECTIVE modifying a noun (the GPIO *output-data register*),
# NOT a port-direction tag for the parenthetically-named INTERNAL net. When the
# gap between the direction word and the backtick ends in such a head noun
# (register / signal / data / bus / port / counter / flag / line / wire / net /
# pin / value / word / field / latch / buffer), the direction word modifies that
# noun-phrase and the backtick is the internal net's name, not a port of that
# direction — skip the record. chip-AGNOSTIC: pure English noun-phrase grammar,
# no design/vendor literal. Mirrors _COPULAR_GAP_RE.
#
# The guard is a MULTI-WORD attributive phrase that ALSO opens the parenthetical
# wrapping the name: `… <mod> <head-noun> (`$ — "output data register (`reg_out`)",
# "input control register (`reg_in`)". The leading `<mod>` (a modifier word before
# the head noun) is what distinguishes this from the LEGITIMATE single-noun
# role-label forms — both the paren form "input data (`x`)" / "output bus (`y`)"
# (gap " data ("/" bus (") AND the bare appositive "output signal `done_o`" /
# "input clock `clk_i`" (gap "signal "/"clock ", where the backtick IS that noun).
# (#763r2) the prior bare-trailing-head-noun arm was REMOVED: it over-fired on the
# dominant legitimate role-label "output signal `x`" / "input data `x`", silently
# dropping a real port's direction (an §4.05 leak). reg_out is caught by the
# multi-word+paren arm; a real bare-noun internal net stays masked by the
# given-code-internal-net mask, not by prose grammar.
_HEAD_NOUN = (r"(?:register|signal|data|bus|port|counter|flag|line|wire|net|"
              r"pin|value|word|field|latch|buffer)s?")
_ATTRIBUTIVE_NOUN_GAP_RE = re.compile(
    r"\b\w+\s+" + _HEAD_NOUN + r"\s*\(\s*$",  # multi-word attributive phrase + open paren
    re.IGNORECASE)

# (#762) NEW-SUBJECT guard for the direction-word-AFTER rule: a genuine prose port
# predication binds the direction word DIRECTLY to the named net ("`s_ready` is an
# output", "`data_valid` is an input", "`s_ready` (active high) is an output",
# "`done`, when asserted, is an output") — the gap between the backtick name and
# the direction word carries at most a parenthetical annotation or an adverbial
# subordinate clause, but the SUBJECT of the copula is still the named net. A
# COINCIDENTAL match instead scrapes a direction word whose clause predicates a
# DIFFERENT subject ("the pointer (`r_ptr`) decrements, and the data is output" —
# 'output' predicates "the data", not r_ptr). The discriminating signature is a
# NEW SUBJECT noun-phrase — a determiner + noun immediately followed by a
# copula/auxiliary — inside the gap. When present, the direction word belongs to
# that new subject, not to the backtick name — skip the record. chip-AGNOSTIC:
# pure clause grammar, no literal.
# (#762r2) the prior broad clause-break form ([,;)] / and|or|but|…) was REPLACED:
# it over-fired on a parenthetical annotation ")" or an appositive comma that does
# NOT detach the copula's subject ("`s_ready` (active high) is an output"),
# silently dropping a real port direction (an §4.05 leak).
# The `_DIR_NEAR_AFTER_RE` capture consumes the copula ("is an") itself, so a new
# subject surfaces as the gap ENDING in a determiner + noun ("…and the data " then
# the consumed "is output"). An appositive annotation ("(active high) ") or an
# adverbial subordinate ("when asserted, ") does NOT end in a determiner+noun, so
# the genuine "`name` (active high) is an output" is preserved.
_AFTER_NEW_SUBJECT_RE = re.compile(
    r"\b(?:the|a|an|its|this|that|each|every)\s+\w+\s*$",
    re.IGNORECASE)

# (#763) VERB / ATTRIBUTIVE-MODIFIER guard for the direction-word-BEFORE rule.
# The BEFORE rule (`(input|output) <gap> `name``) was written for the role-label
# form "input `foo`" / "output `bar`" — the direction word labels the immediately-
# following backtick port. But the word "input"/"output" is also an ordinary
# English VERB / GERUND ("Output the signal", "output by XORing"), an ATTRIBUTIVE
# NOUN-MODIFIER of a following common noun ("output encoding", "output signal",
# "GPIO Output Data"), and can sit in a PRIOR clause whose period/colon the 40-char
# gap window straddles ("Encoded output signal. The encoding applied to `serial_in`").
# In every such case the direction word is NOT a role-label for the trailing
# backtick name, so attributing its direction to that name is a false positive
# (Serial_Line_Converter: `clk_pulse`/`mode`/`serial_in` wrongly tagged output).
# A genuine role-label has a THIN gap: pure whitespace/punctuation straight to the
# name, OR a short noun-phrase that PARENTHESIZES the name ("input data (`x`)",
# "output data register (`y`)"). Everything else is rejected. chip-AGNOSTIC: pure
# English-grammar structure over the gap, no design / vendor / SKU literal.
#
# (1) the gap crosses a sentence / clause boundary (a `.`/`;`/`:` then space, or a
#     markdown bold close `**` then `.`/`:`): the direction word is in a prior clause.
_BEFORE_SENT_BOUNDARY_RE = re.compile(r"[.;:]\s|\*\*\s*[.;:]")
# (2) the direction word governs a DIFFERENT entity than the trailing backtick
#     name: a RE-TARGETING marker mid-gap — a verb object ("output by XORing"), an
#     adjunct ("Output the signal only during the"), or a prepositional re-aim
#     ("select the output encoding based on the") — moves the direction word's
#     reference away from the name. A genuine appositive role-label gap ("signal ",
#     "data ", "clock ", "of the module ") carries none of these markers, so it is
#     preserved. chip-AGNOSTIC English-grammar tokens, no design / vendor literal.
#     (#763r2) REPLACES the prior lead-noun / lead-verb blanket rejection, which
#     over-fired on the dominant legitimate forms "output signal `x`" / "input
#     clock `x`" / "output of the module `x`" — silently dropping a real port's
#     direction (an §4.05 leak).
_BEFORE_RETARGET_RE = re.compile(
    r"\b(?:by|based\s+on|only|during|applied\s+to|via|using|when|if|"
    r"according\s+to|derived\s+from|depending\s+on)\b",
    re.IGNORECASE)
# role-label paren form: the gap is a short noun-phrase ending in an open paren
# that wraps the name ("input data (`x`)", "input parameters (`y`)"), no sentence
# break inside — this is a LEGITIMATE role-label, keep it.
_BEFORE_NOUN_PAREN_RE = re.compile(r"^[^.;:]*\(\s*$")


def _before_dir_is_role_label(gap: str) -> bool:
    """True when the direction-word-BEFORE gap `gap` (the text between the
    direction word and the backtick name) is a genuine port role-label — i.e.
    the direction word labels THIS backtick name — and not a verb / gerund /
    re-targeted modifier / prior-clause leak. chip-AGNOSTIC."""
    if _BEFORE_SENT_BOUNDARY_RE.search(gap):
        return False
    if _BEFORE_NOUN_PAREN_RE.match(gap):
        return True
    if _BEFORE_RETARGET_RE.search(gap):
        return False
    return True


# (#763) DATA-NOUN guard for the direction-word-AFTER rule, complementing the
# #753 `_NOUN_THE_TAIL_RE` article-prefixed guard. When the direction word is
# IMMEDIATELY FOLLOWED by a common data-noun ("output data", "input value") it is
# an attributive modifier of that noun, NOT a role-label for the preceding backtick
# name — but ONLY when the gap is a VERBAL / CONDITIONAL clause (it carries a finite
# verb / participle / subordinator), so the direction word sits in a separate
# predicate from the name ("if `dfmt_enable` is disabled output data will be ...").
# The dominant LEGITIMATE descriptive form ("`serial_in`: Input signal carrying ...",
# "`serial_out`: Encoded output signal", "16-bit output signal") has only a copular
# `is`/label gap and is NOT a verbal clause, so it is preserved. chip-AGNOSTIC.
_AFTER_DATA_NOUN_RE = re.compile(
    r"^\s*(?:data|word|words|value|values|signal|signals|payload|stream|"
    r"sample|samples|bus|bit|bits|register|line|channel|encoding)\b",
    re.IGNORECASE)
_AFTER_GAP_CLAUSE_RE = re.compile(
    r"\b(?:disabled|enabled|asserted|deasserted|low|high|active|inactive|valid|"
    r"invalid|set|cleared|selects?|controls?|drives?|reaches?|toggled?|"
    r"configures?|indicates?|when|if|while|then|will|carries|carrying|holds?|"
    r"stores?|reflects?|provides?)\b",
    re.IGNORECASE)

# A given-code module header inside the prompt (e.g. a fenced template the
# author must complete) — its ports are the authoritative interface.
_WAVEDROM_NAME_RE = re.compile(r'["\']name["\']\s*:\s*["\']([A-Za-z_]\w*)["\']')


# ── (#809 / R12C3) bold-label structured port declaration ───────────────────
# Some CVDP specs declare ports NOT in a markdown table and NOT in a given-code
# header, but as bold-label markdown bullets. TWO precise forms are recognized:
#
#   FORM-A — direction EXPLICIT in the bullet's bold-label parenthetical:
#       - **clk (input, wire)**: Clock signal ...
#       - **data_out (output, wire[11:0])**: 12-bit output ...
#     the `(input|output|inout, ...)` clause inside the `**...**` label gives
#     BOTH the name and its direction with NO ambiguity, so it is harvested
#     regardless of the heading. HIGH PRECISION — a real port is the only thing
#     that carries an inline direction in its bold label.
#
#   FORM-B — direction carried by a PORT-SECTION heading, bare-name bullet:
#       ## New Input
#       - **enable:** 1-bit
#     the bullet is a bare bold-label name (`**enable:**`); the DIRECTION comes
#     from a heading that is a PORT-SECTION declaration ("New Input", "Inputs",
#     "Output Ports"). FORM-B is DELIBERATELY NARROW (it fires on bare prose-ish
#     bold labels, so it must not fabricate phantoms): it requires (1) the heading
#     to be a SHORT port-section heading asserting ONE unambiguous direction, AND
#     (2) the bullet body to look like a port type spec (`1-bit`, `[7:0]`, `wire`,
#     a width/`bit` token) — NOT a prose sentence, AND (3) the name to not be a
#     reserved direction / generic-prose-label word. A bullet under a descriptive
#     heading ("Behavior", "Example Operations", "Interface Signals",
#     "Specifications", "Edge Cases") or whose body is a prose sentence is NOT a
#     port and is skipped — so prose labels (`**Input**:`, `**Note**:`,
#     `**Behavior**:`, `**Parameters**:`, `**Purpose**:`) and internal-net /
#     param / FSM-state bold bullets are never fabricated as ports.
#
# chip-AGNOSTIC: pure markdown bullet + heading grammar, no design/vendor literal.
_BOLDLABEL_FORMA_RE = re.compile(
    r"^\s*[-*+]\s+\*\*\s*([A-Za-z_]\w*)\s*"          # 1: port name
    r"\(\s*(input|output|inout)\b[^)]*\)\s*"          # 2: inline direction (req)
    r":?\s*\*\*",                                      # close the bold label
    re.IGNORECASE)
# FORM-B candidate: a bare-name bold-label bullet `- **<name>:** <body>`
# (no inline direction paren). Captures name (1) and the bullet body (2) so the
# body can be required to be a port type-spec, not a prose sentence.
_BOLDLABEL_FORMB_RE = re.compile(
    r"^\s*[-*+]\s+\*\*\s*([A-Za-z_]\w*)\s*:?\s*\*\*\s*:?\s*(.*)$",
    re.IGNORECASE)
# A markdown heading line (`#`/`##`/`###` ...) — capture its text so a
# PORT-SECTION heading ("New Input", "Inputs", "Output Ports") can give the
# direction to FORM-B bare-name bullets that follow it.
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
# A heading that is a SHORT PORT-SECTION declaration asserting ONE direction:
# an optional leading qualifier (New / Additional / Module) then Input(s) /
# Output(s) optionally followed by Port(s) / Signal(s) / Pin(s). The `$` anchor
# keeps it SHORT — "Inputs and Outputs" (mixed), "Interface Signals" (no
# direction word), "Example Operations", "Behavior" do NOT match, so FORM-B
# never fires under them. chip-AGNOSTIC.
_PORT_SECTION_HDR_RE = re.compile(
    r"^\s*(?:new\s+|additional\s+|module\s+)?"
    r"(input|output)s?"
    r"(?:\s+(?:port|signal|pin)s?)?\s*$",
    re.IGNORECASE)
# A FORM-B bullet BODY that looks like a port TYPE SPEC (a width / bit-count /
# net-type token) rather than a prose sentence. `1-bit`, `[7:0]`, `12-bit wire`,
# `wire`, `logic [3:0]`, `8 bits`. A prose body ("Clock signal that drives ...")
# does NOT match, so a descriptive bullet is not harvested as a port. The body
# may be empty (the name + a following table/desc). chip-AGNOSTIC.
_PORTSPEC_BODY_RE = re.compile(
    r"^\s*(?:"
    r"\d+\s*[-\s]?\s*bits?\b"          # 1-bit, 12 bit, 8 bits
    r"|\[[^\]]*\]"                       # [7:0]
    r"|(?:wire|reg|logic|bit|signed|unsigned)\b"  # net type
    r")",
    re.IGNORECASE)
# Reserved direction / generic-prose-label words that are NEVER a port name even
# under a port-section heading (a bullet `- **Input:** ...` / `- **Note:** ...`
# is a prose label, not a port). chip-AGNOSTIC English nouns + dir words.
_NONPORT_LABEL_WORDS = frozenset({
    "input", "output", "inout", "inputs", "outputs",
    "note", "notes", "behavior", "behaviour", "parameters", "parameter",
    "purpose", "computation", "example", "examples", "description",
    "overview", "summary", "specification", "specifications", "interface",
    "clock", "reset", "latency",  # role NOUNS used as section labels here
})
# A markdown bullet line. Used for FORM-B CONTIGUITY: FORM-B harvests ONLY the
# immediate contiguous bullet list directly under a port-section heading; a
# non-blank NON-bullet line (intervening prose / table / a paragraph that
# introduces a CSR bit-field list) ENDS that port list. (Step-2.7 §4.05: CSR
# bit-fields listed as bold bullets AFTER a prose sentence under `## Inputs`
# were wrongly fabricated as input ports.)
_BULLET_LINE_RE = re.compile(r"^\s*[-*+]\s+")
# A FORM-B bullet BODY that describes an INTERNAL STORAGE element (an FSM/state
# register, a counter, a flip-flop, an internal signal) — NOT an interface port,
# even under a port-section heading. NB: bare "register" is deliberately NOT
# matched (a real port body like "8-bit register address" must stay a port);
# only the storage-element phrasings are denied. (Step-2.7 §4.05: an FSM-state
# register described in a bullet under `## Outputs` was wrongly fabricated as an
# output port.) chip-AGNOSTIC English storage vocabulary.
_INTERNAL_SIGNAL_BODY_RE = re.compile(
    r"\b(?:fsm|finite\s+state|state\s+machine|state\s+register|"
    r"internal(?:\s+(?:register|signal|net|state|reg|wire))?|"
    r"counter|accumulator|shift\s+register|flip[-\s]?flop|flop)\b"
    r"|hold(?:s|ing)\s+the\s+current",
    re.IGNORECASE)


def _heading_direction(heading_text: str) -> str:
    """The single port direction asserted by a SHORT port-section heading
    ("New Input" → input, "Output Ports" → output), or '' when the heading is
    not a short single-direction port-section heading ("Inputs and Outputs",
    "Interface Signals", "Behavior" → ''). chip-AGNOSTIC."""
    m = _PORT_SECTION_HDR_RE.match(heading_text or "")
    if not m:
        return ""
    return m.group(1).lower()


def bold_label_ports(prompt: str) -> Dict[str, str]:
    """Extract ports declared as bold-label markdown bullets (#809 / R12C3).

    FORM-A (inline direction `- **name (input, ...)**:`) is harvested
    unconditionally — its direction is explicit and unambiguous. FORM-B
    (`- **name:** <type-spec>` under a SHORT single-direction port-section
    heading) is harvested ONLY when ALL of: the heading is a port-section
    heading, the bullet is in the IMMEDIATE contiguous bullet list under it
    (intervening prose / a table ends the list), the bullet body is a port
    type-spec, the body does NOT describe an internal storage element
    (FSM/state register / counter / flip-flop), and the name is not a reserved
    prose-label word — so prose labels, CSR bit-fields introduced by a
    paragraph, internal nets and FSM-state bold bullets are never fabricated as
    ports. Returns name→direction (lower). chip-AGNOSTIC."""
    out: Dict[str, str] = {}
    cur_dir = ""
    for line in prompt.splitlines():
        hm = _MD_HEADING_RE.match(line)
        if hm:
            cur_dir = _heading_direction(hm.group(1))
            continue
        # FORM-A — inline direction, always trustworthy (heading-independent).
        am = _BOLDLABEL_FORMA_RE.match(line)
        if am:
            out[am.group(1)] = am.group(2).lower()
            continue
        # FORM-B — bare name under a port-section heading, narrow guards.
        if not cur_dir:
            continue
        # CONTIGUITY: a blank line stays inside the list; a non-blank NON-bullet
        # line (prose/table) ENDS the immediate port list under the heading, so
        # later bullets (e.g. a CSR bit-field list introduced by a sentence) are
        # NOT ports. §4.05 no-false-block.
        if not line.strip():
            continue
        if not _BULLET_LINE_RE.match(line):
            cur_dir = ""
            continue
        bm = _BOLDLABEL_FORMB_RE.match(line)
        if not bm:
            continue
        name = bm.group(1)
        body = bm.group(2) or ""
        if name.lower() in _NONPORT_LABEL_WORDS:
            continue
        if not _PORTSPEC_BODY_RE.match(body):
            continue
        # INTERNAL-STORAGE body: a bullet describing an FSM/state register,
        # counter, flip-flop or internal signal is NOT an interface port even
        # under a port-section heading. §4.05 no-false-block.
        if _INTERNAL_SIGNAL_BODY_RE.search(body):
            continue
        # a concrete inline-direction (FORM-A) already recorded wins; otherwise
        # take the heading direction.
        out.setdefault(name, cur_dir)
    return out


# ── register-map / CSR name exclusion (ORGANIC #738 secondary) ───────────────
# A name that appears ONLY in a register-map 'Register Name' / 'Field Name'
# column (a table that ALSO has an Offset/Address column) and is prose-tagged as
# an internal CSR — accessed via the bus, NOT a top-level port — must NOT be
# charged as a MISSING-PORT. The harness binds to top-level PORTS, never to an
# internal CSR accessed through an offset, so flagging these is pure advisory
# noise on exactly the register-map prompts. Structural rule (chip-AGNOSTIC):
# the table header names a register/field column AND an offset/address column,
# and the prompt prose marks them internal ("internal", "CSR", "register map",
# "accessed via/through the bus", "not ... ports").
_REGMAP_NAME_HDR = re.compile(
    r'^\s*(register\s*name|field\s*name|reg\s*name|register|field)\s*$', re.I)
_REGMAP_OFFSET_HDR = re.compile(
    r'^\s*(offset|address|addr|reg\s*offset)\s*$', re.I)
# (#844 issue #24) A GENERIC name-column header — a plain `Name` / `Register` /
# `Reg` / `Field` / `CSR` — is, on its own, too ambiguous to mark a name column
# (a port table can also have a `Name` column). It names the register column ONLY
# when the SAME table also has an offset/address column AND no Direction column
# (so it is a register map, not a port table). Names recognised THIS way are
# masked at the consumer ONLY under a structural PROVENANCE guard (direction-less
# + sole evidence is a table), so a genuine top-level port is never absorbed.
_REGMAP_GENERIC_NAME_HDR = re.compile(
    r'^\s*(name|register|reg|field|csr)\s*$', re.I)
_DIR_COL_HDR = re.compile(
    r'^\s*(direction|dir\.?|i\s*/?\s*o|inout|mode|type|r\s*/?\s*w)\s*$', re.I)
# (#844 issue #24, Step-2.7 round-2/3) The generic-`Name`-header mask is the
# §4.05-RISKY path (it REMOVES a MISSING-PORT block), so it fires ONLY for a table
# under a STRICT register-MAP / CSR heading — restricted to the UNAMBIGUOUS
# address-map terms (`register map` / `csr map` / `csr` / `csrs`). apb_dsp's
# `## Register Map (CSR)` matches. Deliberately EXCLUDED (round-3 — they hold
# genuine memory-mapped/exposed top-level ports just as often as internal CSRs,
# so masking under them is a §4.05 false-skip): `control and status registers`,
# `register file` (CPU GP regs), `memory-mapped registers`, `register
# block/bank/set`, and any `register layout`/`pin …` heading. A "register MAP" is
# specifically a bus address→register map — internal CSRs, not ports.
_REGMAP_STRICT_HEADING_RE = re.compile(
    r'^\s{0,3}#{1,6}\s+.*\b(?:register\s*map|csr\s*map|csrs?)\b',
    re.I)
_REGMAP_INTERNAL_PROSE = re.compile(
    r'\b(?:internal\s+(?:csr|register)|'
    r'csr(?:s)?\b|'
    r'register\s*map|'
    r'accessed\s+(?:via|through)\s+the\s+bus|'
    r'not\s+(?:a\s+)?top[\s-]*level\s+ports?|'
    r'not\s+(?:top[\s-]*level\s+)?ports?\s+of\s+the\s+module)\b',
    re.I)


def _split_md_row_local(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_md_delim_local(cells: List[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{2,}:?", (c or "").replace(" ", "")) for c in cells
        if c != "")


def regmap_csr_names(prompt: str) -> Set[str]:
    """Lower-cased names that occur ONLY in a register-map 'Register/Field Name'
    column of a table that ALSO carries an Offset/Address column, AND whose
    prompt prose tags the map as internal CSRs. These are bus-accessed CSRs, not
    top-level ports, so they are excluded from MISSING-PORT. Conservative: an
    empty set unless BOTH the table shape AND the internal-prose tag are present
    (a genuine port table never matches — it has a Direction column, not an
    Offset column, and no internal-CSR prose)."""
    if not _REGMAP_INTERNAL_PROSE.search(prompt):
        return set()
    names: Set[str] = set()
    lines = prompt.splitlines()
    n = len(lines)
    i = 0
    while i < n - 1:
        line = lines[i]
        if line.count("|") < 2:
            i += 1
            continue
        header = _split_md_row_local(line)
        delim = _split_md_row_local(lines[i + 1]) if i + 1 < n else []
        if not _is_md_delim_local(delim) or len(delim) != len(header):
            i += 1
            continue
        name_col = next(
            (k for k, h in enumerate(header) if _REGMAP_NAME_HDR.match(h)), None)
        off_col = next(
            (k for k, h in enumerate(header) if _REGMAP_OFFSET_HDR.match(h)), None)
        # A register-map table needs BOTH a register/field name column AND an
        # offset/address column (this is what distinguishes it from a port
        # interface table, which has a Direction column instead).
        if name_col is None or off_col is None:
            i += 1
            continue
        j = i + 2
        while j < n:
            row = lines[j]
            if row.count("|") < 1:
                break
            cells = _split_md_row_local(row)
            if _is_md_delim_local(cells):
                j += 1
                continue
            if all(c == "" for c in cells):
                break
            if len(cells) > name_col:
                cell = cells[name_col].strip().strip("`*_ ")
                m = re.fullmatch(r"[A-Za-z_]\w*", cell)
                if m:
                    names.add(cell.lower())
            j += 1
        i = j if j > i else i + 1
    return names


_PORTS_SECTION_HDR = re.compile(
    r'^\s{0,3}#{1,6}\s+.*\b(?:ports?|port\s+list|interface|signals?|'
    r'i\s*/?\s*o|pin\s*out|pinout|pin\s+(?:description|map|assignment|list)|'
    r'connections?|top[\s-]*level\s+(?:ports?|signals?|interface|i\s*/?\s*o)|'
    r'external\s+(?:ports?|signals?|interface))\b',
    re.I)
_ANY_HEADING_LINE_RE = re.compile(r'^\s{0,3}#{1,6}\s+')


def _names_under_ports_section(prompt: str) -> Set[str]:
    """Lower-cased backtick identifiers that appear under a markdown PORTS /
    INTERFACE / SIGNALS section heading (until the next heading). A name declared
    in such a section is an author-asserted top-level port even if its direction
    prose is unrecognised by the extractor — so it must NEVER be masked by the
    generic-regmap relaxation. (#844 issue #24, the round-4 `status` leak: a
    genuine output declared under `## Ports` with prose direction the extractor
    misses, ALSO listed in a generic-`Name` regmap table, would otherwise read
    identically to an internal CSR.) chip-AGNOSTIC: pure markdown structure."""
    names: Set[str] = set()
    lines = prompt.splitlines()
    in_ports = False
    for line in lines:
        if _ANY_HEADING_LINE_RE.match(line):
            in_ports = bool(_PORTS_SECTION_HDR.match(line))
            continue
        if in_ports:
            for m in re.finditer(r'`([A-Za-z_]\w*)`', line):
                names.add(m.group(1).lower())
    return names


def regmap_generic_csr_names(prompt: str) -> Set[str]:
    """Lower-cased names from an internal-CSR register-map table whose name column
    uses a GENERIC header (a bare `Name`/`Register`/`Reg`/`Field`/`CSR`) rather
    than the STRICT `Register Name`/`Field Name` header that `regmap_csr_names`
    requires. The table must ALSO carry an offset/address column and NO Direction
    column (a port table has a Direction column, not an offset). (#844 issue #24:
    the apb_dsp_unit FP — 4 APB CSRs under a `| Addr | Name | Function | Reset |`
    table were false-flagged MISSING-PORT because the bare `Name` header was not
    recognised.) These names are masked at the consumer ONLY under a structural
    PROVENANCE guard (direction-less + sole evidence is a table), so a genuine
    direction-ful or Ports-section port is never absorbed. chip-AGNOSTIC."""
    if not _REGMAP_INTERNAL_PROSE.search(prompt):
        return set()
    strict = regmap_csr_names(prompt)
    names: Set[str] = set()
    lines = prompt.splitlines()
    n = len(lines)
    i = 0
    # the generic mask fires ONLY for a table under a STRICT register-map/CSR
    # heading (#844 issue #24 Step-2.7 round-2 — kills the `## Pin Description` /
    # `## Connections` / `## Register Layout` false-skips: those headings are not
    # register MAPS, so their offset-bearing port tables are never absorbed).
    under_regmap_heading = False
    while i < n - 1:
        line = lines[i]
        if _ANY_HEADING_LINE_RE.match(line):
            under_regmap_heading = bool(_REGMAP_STRICT_HEADING_RE.match(line))
            i += 1
            continue
        if line.count("|") < 2 or not under_regmap_heading:
            i += 1
            continue
        header = _split_md_row_local(line)
        delim = _split_md_row_local(lines[i + 1]) if i + 1 < n else []
        if not _is_md_delim_local(delim) or len(delim) != len(header):
            i += 1
            continue
        hdr_clean = [h.strip().strip("`*_ ") for h in header]
        has_dir = any(_DIR_COL_HDR.match(h) for h in hdr_clean)
        off_col = next(
            (k for k, h in enumerate(header) if _REGMAP_OFFSET_HDR.match(h)), None)
        # generic name column, NOT also a strict-name column; offset present; no
        # direction column → an internal register map with a bare `Name` header.
        strict_col = next(
            (k for k, h in enumerate(header) if _REGMAP_NAME_HDR.match(h)), None)
        gen_col = next(
            (k for k, h in enumerate(header)
             if _REGMAP_GENERIC_NAME_HDR.match(h)), None)
        if strict_col is not None or gen_col is None or off_col is None \
                or has_dir:
            i += 1
            continue
        j = i + 2
        while j < n:
            row = lines[j]
            if row.count("|") < 1:
                break
            cells = _split_md_row_local(row)
            if _is_md_delim_local(cells):
                j += 1
                continue
            if all(c == "" for c in cells):
                break
            if len(cells) > gen_col:
                cell = cells[gen_col].strip().strip("`*_ ")
                if re.fullmatch(r"[A-Za-z_]\w*", cell):
                    names.add(cell.lower())
            j += 1
        i = j if j > i else i + 1
    return names - strict


# (#753) A markdown table HEADER that is a DESCRIPTION / FSM-state / metadata
# table — its first column names a concept (State / Field / Signal description),
# NOT a port direction. Such a table has NO Direction column (and no Offset
# column, which would make it a register map). Its first-column backtick names
# are state labels / internal entry fields, never top-level ports, so they must
# not be harvested as port names from the bare-`name | word` inline scan.
_DESC_FIRSTCOL_HDR = re.compile(
    r"^\s*(state|field|register\s*field|entry|signal|name|parameter|param)\s*$",
    re.I)
_DIR_HDR_RE = re.compile(r"^\s*direction\s*$", re.I)


def _desc_table_firstcol_names(prompt: str) -> Set[str]:
    """First-column backtick names of any markdown table whose header first cell
    is a concept column (State / Field / Entry / Signal) AND which has NO
    Direction column. These are FSM-state labels / internal-entry-metadata field
    names (`IDLE`/`LOAD`/`SHIFT`/`LATCH`; `valid`/`cache_line_addr`/`write`/
    `next`/`next_index`), never top-level ports. Structural + chip-AGNOSTIC: a
    genuine port table is excluded because it carries a Direction column."""
    names: Set[str] = set()
    lines = prompt.splitlines()
    n = len(lines)
    i = 0
    while i < n - 1:
        line = lines[i]
        if line.count("|") < 2:
            i += 1
            continue
        header = _split_md_row_local(line)
        delim = _split_md_row_local(lines[i + 1]) if i + 1 < n else []
        if not _is_md_delim_local(delim) or len(delim) != len(header):
            i += 1
            continue
        hdr_clean = [h.strip().strip("*_ ") for h in header]
        has_dir = any(_DIR_HDR_RE.match(h) for h in hdr_clean)
        first_is_desc = bool(hdr_clean) and bool(_DESC_FIRSTCOL_HDR.match(hdr_clean[0]))
        if has_dir or not first_is_desc:
            i += 1
            continue
        j = i + 2
        while j < n:
            row = lines[j]
            if row.count("|") < 1:
                break
            cells = _split_md_row_local(row)
            if _is_md_delim_local(cells):
                j += 1
                continue
            if all(c == "" for c in cells):
                break
            if cells:
                cell = cells[0].strip().strip("`*_ ")
                if re.fullmatch(r"[A-Za-z_]\w*", cell):
                    names.add(cell)
            j += 1
        i = j if j > i else i + 1
    return names


# ORGANIC-20260618 (square_root_0003) — a TEST-VECTOR RESULTS table names its
# data columns in the HEADER row (`| WIDTH | Test ID | `num` | `final_root` |
# `expected_root` | Latency | Explanation |`) and carries numeric VALUES in the
# body rows. Those header-cell backtick names are column labels, NOT ports — yet
# the iface scraper's directionless `setdefault(name, "")` branch fabricated them
# as ports (source=table → STRUCTURAL → block-eligible → spurious rc=1). This
# excludes backtick names that occur ONLY in the HEADER cells of such a
# directionless (no-Direction-column) table AND nowhere else in the prompt.
# Restricting to HEADER cells (a results-table signature) — never body-row Name
# cells — means a `## Pin Description` / register-map table that lists port/CSR
# names in a BODY `Name` column (req/gnt; irq/status) is untouched, so a real
# MISSING-PORT is never masked (§4.05 no-leak — issue#24 negatives). The
# canonical shared parser already requires a Direction column for a port table.
# chip-AGNOSTIC: pure markdown table grammar.
# (Step-2.7 #27) Unambiguous TEST-VECTOR / RESULTS-table column headers. At least
# one must be present for a no-Direction table's backtick header names to be
# excluded as non-ports — this separates a results table (square_root) from a
# port-listing table whose ports happen to be column headers (the `overflow`
# leak). Deliberately EXCLUDES generic words a port table may carry (Notes /
# Description / Comment / Width / Function).
# A cell whose whole content is a port DIRECTION word (incl. the `in`/`out`
# shorthand used in body rows of a port-listing table). Step-2.7 #27 round-2.
_DIR_WORD_RE = re.compile(r"^(?:input|output|inout|in|out|i/o)$", re.I)
_RESULTS_META_HDR = re.compile(
    r"^\s*(?:test(?:\s*(?:id|case|vector|no\.?|#|num\w*))?|vectors?|"
    r"latency|cycles?|clk\s*cycles?|expected(?:\s+\w+)?|golden|reference|"
    r"case\s*\d*|example|iteration|scenario|stimulus|input\s+vector|"
    r"output\s+vector|explanation|step\s*\d*|#)\s*$",
    re.I)


def _directionless_table_names(prompt: str) -> Set[str]:
    """Backtick identifiers that appear ONLY in the HEADER row of a proper
    header+delimiter markdown table with NO Direction column (a results /
    test-vector table whose columns are quoted), and nowhere else in the prompt.
    Such header labels are not ports. A name that also appears outside the header
    (a body Name cell, a `## Ports` section, prose) is NOT returned, so a real
    MISSING-PORT is never masked. chip-AGNOSTIC: pure markdown table grammar."""
    lines = prompt.splitlines()
    n = len(lines)
    header_lines: Set[int] = set()              # directionless-table HEADER rows
    candidates: Set[str] = set()
    i = 0
    while i < n - 1:
        line = lines[i]
        if line.count("|") < 2:
            i += 1
            continue
        header = _split_md_row_local(line)
        delim = _split_md_row_local(lines[i + 1]) if i + 1 < n else []
        if not _is_md_delim_local(delim) or len(delim) != len(header):
            i += 1
            continue
        hdr_clean = [h.strip().strip("*_` ") for h in header]
        has_dir = any(_DIR_HDR_RE.match(h) for h in hdr_clean)
        if has_dir:
            i += 2
            continue
        # (Step-2.7 #27) Absence of a Direction column is NOT enough — a port
        # table that lists its ports as backtick COLUMN HEADERS (no Direction
        # col) looks identical, and excluding its header names would mask a real
        # MISSING-PORT (the `overflow` leak). Require POSITIVE test-vector /
        # results-table evidence: at least one column header is unambiguous
        # test-vector metadata (Test ID / Vector / Latency / Cycle / Expected /
        # Case / Iteration / #). A pure port-listing table has none, so its
        # header names stay block-eligible. chip-AGNOSTIC: markdown grammar.
        if not any(_RESULTS_META_HDR.match(h) for h in hdr_clean):
            i += 2
            continue
        # (Step-2.7 #27 round-2) A genuine results / test-vector table holds DATA
        # VALUES in its body; a PORT-listing table (ports as headers) holds
        # DIRECTION WORDS (`in`/`out`/`input`/`output`/`inout`) in its body rows —
        # even when there is no Direction header COLUMN. `_DIR_HDR_RE` only checks
        # header cells, so a port table with body direction words + a coincidental
        # `Expected`/`Test ID` meta column would be mis-excluded, re-masking a real
        # MISSING-PORT (`overflow`). Scan this table's BODY rows: any direction
        # word means it is a port table, NOT a results table — do not exclude.
        body_has_dir = False
        b = i + 2
        while b < n:
            row = lines[b]
            if row.count("|") < 1:
                break
            cells = _split_md_row_local(row)
            if _is_md_delim_local(cells):
                b += 1
                continue
            if all(c == "" for c in cells):
                break
            if any(_DIR_WORD_RE.match(c.strip().strip("*_` "))
                   for c in cells):
                body_has_dir = True
                break
            b += 1
        if body_has_dir:
            i += 2
            continue
        # collect backtick names from the HEADER row only (results-table columns)
        header_lines.add(i)
        for cell in header:
            for mm in re.finditer(r"`([A-Za-z_]\w*)`", cell):
                candidates.add(mm.group(1))
        i += 2
    # keep only candidates whose EVERY backtick occurrence is in a directionless
    # header row — a name also seen elsewhere (body Name cell, prose, ## Ports)
    # is a real port mention and must not be masked.
    elsewhere: Set[str] = set()
    for k, line in enumerate(lines):
        if k in header_lines:
            continue
        for mm in re.finditer(r"`([A-Za-z_]\w*)`", line):
            elsewhere.add(mm.group(1))
    names = candidates - elsewhere
    return names


def _table_ports(prompt: str) -> Dict[str, str]:
    """Markdown table rows: first backtick cell = name, a later cell carrying
    a direction word = direction. Returns name→direction (lower, '' if no
    direction word in the row).

    (#753) A first-column backtick name from a DESCRIPTION / FSM-state / metadata
    table (a 2-column `State|Description` / `Field|Description` table with NO
    Direction column) is NOT a port — exclude it from the no-direction
    (`setdefault(name, "")`) branch so FSM-state labels and internal entry
    fields are not fabricated as ports. A row that DOES carry a direction word is
    still harvested unconditionally (a genuine port table).

    (ORGANIC FIR_0001) A backtick cell that is a SystemVerilog reserved
    TYPE/DIRECTION keyword (`logic`/`wire`/`reg`/`bit`/`signed`/`unsigned`/
    `input`/`output`/`inout`) is NEVER a legal port identifier — it is the
    contents of a TYPE column in a `| `name` | `type` | desc |` port table.
    The pipe-window scan can straddle a cell boundary and match ``logic` |
    System` (the type cell of one row + the first word of the description cell),
    fabricating a phantom port named `logic` (source=table → STRUCTURAL →
    block-eligible → spurious rc=1). Candidate NAMES are therefore filtered
    through the SAME `_SV_PORT_KEYWORDS` set the header-port parsers already use
    (whole-token, case-SENSITIVE — the phantom is always the literal lowercase keyword). This can only DROP a phantom keyword name;
    a real port whose identifier merely CONTAINS such a keyword as a substring
    (`logic_en`, `reg_file_addr`, `wire_sel`) is a distinct whole token and is
    still harvested — so the relaxation never masks a genuine MISSING-PORT.
    chip-AGNOSTIC: pure SV-keyword set + markdown grammar."""
    out: Dict[str, str] = {}
    desc_only = _desc_table_firstcol_names(prompt)
    # (ORGANIC-20260618) names that occur ONLY inside a directionless table (no
    # Direction column) — a results / metadata table, never a port table. Mirrors
    # the shared `_parse_md_table_ports` Direction-column discipline.
    directionless = _directionless_table_names(prompt)
    # Split on the pipe so an inline single-line table (the acceptance shape)
    # and a true multi-row markdown table both work: scan windows of
    # ``name` | dir` regardless of line boundaries.
    for cell_m in re.finditer(r"`([A-Za-z_]\w*)`\s*\|\s*([A-Za-z]+)", prompt):
        name = cell_m.group(1)
        word = cell_m.group(2).lower()
        # (FIR_0001) a candidate name equal (whole-token) to a reserved SV
        # type/direction keyword is a Type-column cell, not a port — skip it.
        # CASE-SENSITIVE (Step-2.7): the phantom is always the literal lowercase
        # keyword (`logic`/`reg`/…); a CAPITALIZED identifier (`Reg`, `Logic`,
        # `Wire`) is a LEGAL distinct SV port name, NOT a reserved keyword, so it
        # must NOT be excluded — matching the header parser's case-sensitive
        # lowercase membership keeps the no-leak invariant the docstring asserts.
        if name in _SV_PORT_KEYWORDS:
            continue
        if word in ("input", "output", "inout"):
            out[name] = word
        elif name not in desc_only and name not in directionless:
            out.setdefault(name, "")
    return out


def _given_code_ports(prompt: str) -> Tuple[Optional[str], Dict[str, str]]:
    """A module header given INSIDE the prompt (a code template). Returns the
    template module name (if any) and its ports."""
    iface = parse_rtl(prompt)
    if iface.module_name is None and not iface.ports:
        return None, {}
    return iface.module_name, dict(iface.ports)


# Internal-net declaration inside a given-code block: `logic [1:0] sync_header;`,
# `reg [7:0] type_field;`, `wire a, b;`. These are body decls (no input/output
# keyword), so the named identifiers are authoritatively INTERNAL, never ports.
#
# (R13C4) UNPACKED-ARRAY tolerance: an unpacked-array internal reg
# (`reg [3:0] wait_counters [0:9];`, `reg [4:0] effective_priority [0:9];`)
# carries one-or-more trailing unpacked dimensions BETWEEN the name and the `;`/`=`
# terminator. The original tail `(<names>)\s*[;=]` required the terminator to
# IMMEDIATELY follow the name, so it harvested the packed/scalar skeleton regs
# (`pending_interrupts`, `active_mask`, `service_timer`) but SILENTLY MISSED the
# unpacked-array ones — leaving them out of `given_code_internal_names()`, so the
# never-mask guard did not suppress them and a "Register Summary Table" row naming
# such a skeleton-internal reg false-fired as a block-eligible MISSING-PORT on the
# author's correct, skeleton-conforming RTL. The tail now tolerates zero-or-more
# trailing unpacked dimensions `[...]` before the terminator. chip-AGNOSTIC: pure
# Verilog unpacked-array declaration grammar, no design/vendor literal.
_GIVEN_INTERNAL_RE = re.compile(
    r"(?<![A-Za-z_.])(?:logic|wire|reg)\b"
    r"(?:\s+(?:signed|unsigned))?"
    r"(?:\s*\[[^\]]*\])?\s*"
    r"((?:[A-Za-z_]\w*\s*,\s*)*[A-Za-z_]\w*)"
    r"(?:\s*\[[^\]]*\])*"   # trailing unpacked dimension(s): `name [0:9]`
    r"\s*[;=]")


def given_code_internal_names(prompt: str) -> Set[str]:
    """Lower-cased identifiers that the prompt's OWN given code declares as
    INTERNAL nets (`logic`/`wire`/`reg` body decls, NOT ports) or as
    `localparam`/`parameter` constants. These are authoritatively non-ports —
    the prompt's skeleton itself fixes them internal — so a prose / table
    mention of such a name must NOT be charged as a MISSING-PORT. Mirrors the
    existing module-name (#726b) and regmap-CSR (#738) exclusions; chip-AGNOSTIC
    (pure structure over the prompt's given code, no design literal).

    Scoped to a fenced/given code region: only `input`/`output`-free body
    declarations and parameter declarations are collected, so a genuine ANSI
    port (`input logic [1:0] foo`) is never harvested as internal. The caller
    still applies a never-mask guard (only suppress a name the RTL does NOT
    declare as a real port), so this can never hide an actually-missing port."""
    names: Set[str] = set()
    # comments stripped so a `// comment` does not bleed into a decl span.
    text = _strip_comments(prompt)
    # body internal-net declarations (logic/wire/reg WITHOUT a direction kw):
    # we exclude any decl whose line carries input/output/inout (that is a port,
    # handled by the ANSI parser, not an internal net).
    for m in _GIVEN_INTERNAL_RE.finditer(prompt):
        # guard: the matched decl must not be an ANSI port decl
        start = prompt.rfind("\n", 0, m.start()) + 1
        line = prompt[start:m.start()]
        if _DIR_WORD_RE.search(line):
            continue
        for nm in re.split(r"\s*,\s*", m.group(1).strip()):
            nm = nm.strip()
            if nm:
                names.add(nm.lower())
    # localparam / parameter constants. Each `parameter`/`localparam` keyword is
    # followed by `<NAME> = <value>`; subsequent NAMEs may be comma-continued
    # under ONE keyword (`localparam IDLE=.., LOAD=.., SHIFT=.., LATCH=..;`) or
    # each carry its own keyword inside an ANSI `#( parameter X=.., parameter
    # Y=.. )` header. Capture the keyword's own NAME, then any comma-continued
    # `<NAME> =` that follows up to the next keyword / `;` / `)`.
    for km in re.finditer(r"\b(localparam|parameter)\b", text):
        seg = text[km.end():]
        # stop at the next param keyword, a `;`, or the closing `)` of #(...)
        stop = re.search(r"\b(?:localparam|parameter)\b|;|\)", seg)
        seg = seg[:stop.start()] if stop else seg
        for assign in seg.split(","):
            nm = assign.split("=")[0]
            nm = re.sub(r"^\s*(?:int|integer|logic|bit|signed|unsigned|"
                        r"\[[^\]]*\])\s*", "", nm).strip().strip("`*_ ")
            if re.fullmatch(r"[A-Za-z_]\w*", nm):
                names.add(nm.lower())
    # never-mask: if the given-code's OWN module header declares a name as a
    # PORT, it is authoritatively a port — drop it from the internal set even if
    # a (contradictory) body decl also names it. The harness binds it as a port.
    gm_name, gm_ports = _given_code_ports(prompt)
    for pn in gm_ports:
        names.discard(pn.lower())
    return names


def given_code_param_names(prompt: str) -> Set[str]:
    """Lower-cased identifiers the prompt's OWN given code declares as
    `localparam` / `parameter` constants. A parameter is AUTHORITATIVELY never a
    port — so unlike an internal NET (which a real required port could
    coincidentally share a name with), a skeleton-declared parameter must
    override even an explicit prose-DIRECTION attribution (#753 reopen: the prose
    "the pipeline takes `PIPE_DEPTH` cycles to propagate input signals" wrongly
    tagged the parameter `PIPE_DEPTH` an `input` port, defeating the direction-
    aware never-mask guard). chip-AGNOSTIC: pure given-code parameter grammar. A
    name the given-code module HEADER declares a real port still wins (it is
    discarded below), so a genuine port is never masked."""
    names: Set[str] = set()
    text = _strip_comments(prompt)
    for km in re.finditer(r"\b(localparam|parameter)\b", text):
        seg = text[km.end():]
        stop = re.search(r"\b(?:localparam|parameter)\b|;|\)", seg)
        seg = seg[:stop.start()] if stop else seg
        for assign in seg.split(","):
            nm = assign.split("=")[0]
            nm = re.sub(r"^\s*(?:int|integer|logic|bit|signed|unsigned|"
                        r"\[[^\]]*\])\s*", "", nm).strip().strip("`*_ ")
            if re.fullmatch(r"[A-Za-z_]\w*", nm):
                names.add(nm.lower())
    # a name the given-code header declares a real PORT is authoritatively a
    # port — but ONLY when it carries a REAL direction (input/output/inout). The
    # header parser can scrape a bare identifier out of a width expression
    # (`input [W-1:0] din` yields a spurious `W` with direction 'unknown'); such
    # a mis-parse must NOT evict the genuinely-declared `parameter W` from the
    # param set (else W would never be masked and would false-fire as a phantom
    # MISSING-PORT). A real ANSI port always declares a direction.
    _gm_name, gm_ports = _given_code_ports(prompt)
    for pn, pdir in gm_ports.items():
        if (pdir or "").lower() in ("input", "output", "inout"):
            names.discard(pn.lower())
    return names


@dataclass
class PromptIface:
    # port name → direction ('' / 'input' / 'output' / 'inout')
    ports: Dict[str, str] = field(default_factory=dict)
    given_module: Optional[str] = None
    sources: Dict[str, Set[str]] = field(default_factory=dict)
    # ORGANIC #806 (#770) — source(s) that supplied the NON-EMPTY direction now
    # stored in `ports[name]`. A source that names a port in a DIRECTION-LESS
    # context (a markdown table with NO Direction column; a given-code bare-name
    # whose 'unknown' direction normalised to '') contributes to `sources` (it
    # proves the NAME exists) but NOT to `dir_sources` (it did not assert the
    # DIRECTION). The PORT-DIRECTION provenance is computed from `dir_sources`,
    # so a direction whose ONLY evidence is a free-prose scrape stays
    # PROSE_HEURISTIC even when a direction-LESS table ALSO named the port —
    # collapsing the "Data output from FIFO" prose-noun leak into the #770
    # advisory class. chip-AGNOSTIC.
    dir_sources: Dict[str, Set[str]] = field(default_factory=dict)

    def add(self, name: str, direction: str, source: str) -> None:
        cur = self.ports.get(name, "")
        # a concrete direction wins over an empty one; conflicting concrete
        # directions are left as the first-seen (table is most authoritative)
        if not cur and direction:
            self.ports[name] = direction
            # this source ESTABLISHED the stored direction → owns its provenance.
            self.dir_sources.setdefault(name, set()).add(source)
        elif name not in self.ports:
            self.ports[name] = direction
        elif cur and direction == cur:
            # a later source that AGREES with the stored direction corroborates
            # it STRUCTURALLY → also owns the direction provenance.
            self.dir_sources.setdefault(name, set()).add(source)
        self.sources.setdefault(name, set()).add(source)


def extract_prompt_iface(prompt: str) -> PromptIface:
    """Extract the named interface from the PROMPT alone. Sources, in order of
    authority for direction: markdown table rows, a given-code module header,
    backtick-name-with-nearby-direction prose, wavedrom name entries (names
    only — no direction)."""
    pif = PromptIface()
    # (a) markdown table rows — most authoritative for direction
    for name, direction in _table_ports(prompt).items():
        pif.add(name, direction, "table")
    # (b) given-code module header (a template the author completes)
    gm_name, gm_ports = _given_code_ports(prompt)
    if gm_name is not None:
        pif.given_module = gm_name
    for name, direction in gm_ports.items():
        pif.add(name, "" if direction == "unknown" else direction,
                "given_code")
    # (b2) (#809 / R12C3) bold-label structured port declarations — a STRUCTURAL
    # source equal in authority to a port table. `- **<name> (input, ...)**:`
    # (inline direction) or `- **<name>:**` under a direction-asserting heading
    # (`## New Input`). chip-AGNOSTIC markdown grammar.
    for name, direction in bold_label_ports(prompt).items():
        pif.add(name, direction, "bold_label")
    # (c) backtick name + nearby direction word (prose)
    for m in _DIR_NEAR_BEFORE_RE.finditer(prompt):
        gap = m.group(2) or ""
        # (#753) skip copular/value-assignment spans ("the output ... should be
        # `clk2`") — the backtick is the VALUE the (output) signal equals (the
        # source it selects), not the port's own direction.
        if _COPULAR_GAP_RE.search(gap):
            continue
        # (#762) skip attributive-noun phrases ("the output data register
        # (`reg_out`)") — the direction word modifies the head noun (register),
        # so the backticked name is that INTERNAL register's name, not a port.
        if _ATTRIBUTIVE_NOUN_GAP_RE.search(gap):
            continue
        # (#763) skip when the direction word is NOT a role-label for THIS name —
        # a verb/gerund ("Output the signal", "output by XORing"), an attributive
        # noun-modifier ("output encoding", "output signal"), or a prior-clause
        # leak across a sentence boundary ("Encoded output signal. The encoding
        # applied to `serial_in`"). These wrongly invert a correct input→output.
        if not _before_dir_is_role_label(gap):
            continue
        pif.add(m.group(3), m.group(1).lower(), "prose")
    for m in _DIR_NEAR_AFTER_RE.finditer(prompt):
        gap = m.group(2) or ""
        # (#753) skip "the input"/"the output" trailing-NOUN references ("`Dx` ...
        # from the input", "`sync_header` is the first 2 bits of the input") —
        # here the direction word is the data-word noun, not a port-direction.
        if _NOUN_THE_TAIL_RE.search(gap):
            continue
        # (#762) skip coincidental cross-clause matches ("the pointer (`r_ptr`)
        # decrements, and the data is output") — the gap introduces a NEW SUBJECT
        # (determiner + noun + copula) that the direction word predicates, so it
        # belongs to a different clause, not to the named (internal) net. A genuine
        # "`name` is an input" / "`name` (active high) is an output" has no new
        # subject before the copula and is preserved.
        if _AFTER_NEW_SUBJECT_RE.search(gap):
            continue
        # (#763) skip when the direction word is an attributive modifier of a
        # following data-noun ("output data", "input value") AND the gap is a
        # verbal/conditional clause ("if `dfmt_enable` is disabled output data
        # will be ...") — the direction word belongs to that noun phrase, not to
        # the backtick name (which is the clause's subject), so attributing the
        # direction to the name inverts a correct input→output. The descriptive
        # "`x`: Output signal" / "16-bit output signal" forms (no clause verb in
        # the gap) are preserved.
        if (_AFTER_DATA_NOUN_RE.match(prompt[m.end():])
                and _AFTER_GAP_CLAUSE_RE.search(gap)):
            continue
        pif.add(m.group(1), m.group(3).lower(), "prose")
    # (d) wavedrom signal names (names only, no direction)
    for m in _WAVEDROM_NAME_RE.finditer(prompt):
        pif.add(m.group(1), "", "wavedrom")
    return pif


# ── conformance ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    kind: str       # MODULE-NAME-CASE | MISSING-PORT | PORT-DIRECTION
    message: str
    # ORGANIC #770 — provenance/confidence gate. A finding may HARD-BLOCK under
    # --strict only when block_eligible (STRUCTURAL source, or a PROSE_HEURISTIC
    # source the RTL corroborates). A PROSE_HEURISTIC finding the RTL contradicts
    # / does not back is ADVISORY (reported, never a veto). Default True
    # (fail-closed: MODULE-NAME-CASE and any un-tagged finding keep blocking).
    block_eligible: bool = True
    advisory_note: str = ""


def check_conformance(rid: Optional[str], prompt: str, rtl_text: str,
                      context_rtl: Optional[List[str]] = None) -> List[Finding]:
    findings: List[Finding] = []
    # The TOP is the first module the author emitted; the harness binds to it.
    modules = parse_all_rtl(rtl_text)
    rtl = modules[0] if modules else RtlIface()
    pif = extract_prompt_iface(prompt)
    rtl_lower = rtl.port_names_lower

    # (#726a/#726d) A port name is SATISFIED if it is declared on ANY module in
    # the completion (top OR sub-module) OR on any CONTEXT module the harness
    # provides via input.context rtl/*.sv — not only the top. The prompt's
    # given-code may name a sub-module's ports, and context-RTL ports are
    # harness-supplied, not author-missing (the #715 family). Union over all.
    context_modules: List[RtlIface] = []
    for ctx in (context_rtl or []):
        context_modules.extend(parse_all_rtl(ctx))
    all_port_names_lower: Set[str] = set()
    for mod in modules + context_modules:
        all_port_names_lower.update(mod.port_names_lower.keys())

    # (#726b/#726c) The set of declared MODULE names — across the completion AND
    # the prompt's given-code AND context RTL. A prompt token equal to a module
    # name (a markdown heading like `### Module: Foo`, or a backtick wrapping a
    # sub-module name) is NOT an interface signal and must be EXCLUDED from the
    # missing-port / direction comparison entirely.
    module_names_lower: Set[str] = set()
    for mod in modules + context_modules:
        if mod.module_name:
            module_names_lower.add(mod.module_name.lower())
    if pif.given_module:
        module_names_lower.add(pif.given_module.lower())

    # (#738 secondary) Names that occur ONLY in a register-map 'Register/Field
    # Name' column (with an Offset/Address column) and are prose-tagged as
    # internal CSRs are bus-accessed registers, NOT top-level ports — the
    # harness never binds to them, so they must not be charged as MISSING-PORT.
    regmap_csrs = regmap_csr_names(prompt)
    # (#844 issue #24) generic-`Name`-header internal-CSR names. Masked ONLY under
    # a structural PROVENANCE guard below — never the prose port-detection that
    # leaked across PR #23's Step-2.7 rounds.
    regmap_generic_csrs = regmap_generic_csr_names(prompt)
    ports_section_names = _names_under_ports_section(prompt)

    # (#753) Names the prompt's OWN given code declares as INTERNAL nets
    # (`logic`/`wire`/`reg` body decls) or `localparam`/`parameter` constants are
    # authoritatively non-ports — the skeleton itself fixes them internal. A
    # prose / FSM-state-table / parameter mention of such a name (`sync_header`,
    # `type_field`, `IDLE`/`LOAD`/`SHIFT`/`LATCH`, `PIPE_DEPTH`) must NOT be
    # charged as MISSING-PORT. Same never-mask guard as the regmap rule below.
    given_internal = given_code_internal_names(prompt)
    # (#753 reopen) parameter names are AUTHORITATIVELY never ports — they
    # override even a spurious prose-DIRECTION attribution, unlike an internal
    # net which a real port could coincidentally share a name with.
    given_params = given_code_param_names(prompt)

    # (1) MODULE-NAME-CASE: harness top from id must match the RTL module name
    # CASE-EXACTLY. Only flag when the names match case-INSENSITIVELY but
    # differ in case (a genuinely different name is the author's design freedom
    # / the prompt's `Module Name:` may legitimately rename — that is NOT this
    # gate's concern, and flagging it would false-fire constantly).
    #
    # (#726c) SUPPRESS when the prompt's RTL block LITERALLY declares the module
    # name verbatim (case-exact): a code-completion skeleton instantiates that
    # exact name, so the harness uses it as-is — the lowercase id stem is then
    # NOT the elaboration top, and flagging a "case mismatch" pushes a WRONG
    # rename that breaks the harness.
    top = harness_top_from_id(rid)
    prompt_declares_verbatim = (
        pif.given_module is not None and rtl.module_name is not None
        and pif.given_module == rtl.module_name)
    if top and rtl.module_name and rtl.module_name != top \
            and rtl.module_name.lower() == top.lower() \
            and not prompt_declares_verbatim:
        findings.append(Finding(
            "MODULE-NAME-CASE",
            f"MODULE-NAME-CASE: harness top is '{top}' (derived from the "
            f"canonical id) but the RTL declares '{rtl.module_name}' — the "
            f"hidden harness elaborates `-s {top}` CASE-EXACTLY, so this "
            f"ELAB_ERRORs at scoring"))

    # (2) MISSING-PORT: a prompt-named port absent from EVERY module's port list
    # (case-insensitive — the harness binds by name; case is checked only for
    # the module-top above). Internal-signal false positives are why this is
    # ADVISORY by default.
    for name in sorted(pif.ports):
        if name.lower() in module_names_lower:
            continue  # (#726b) a module name, not an interface signal
        # (#738 secondary) an internal CSR named only in a register-map column —
        # bus-accessed, not a top-level port — is NOT author-missing. But never
        # suppress a name that the RTL DOES declare as a port (no masking of a
        # genuine signal): only skip when it is also absent from every module.
        if (name.lower() in regmap_csrs
                and name.lower() not in all_port_names_lower):
            continue
        # (#844 issue #24) a generic-`Name`-header regmap CSR is masked ONLY under
        # a STRUCTURAL PROVENANCE guard: it must be DIRECTION-LESS *and* its sole
        # interface evidence must be a TABLE (`sources == {'table'}`). A genuine
        # top-level port always carries either a direction (PORT-DIRECTION
        # provenance) or a Ports-section/bullet source ('prose'/'bold_label'), so
        # the PR #23 Step-2.7 leak cases never match: a direction-ful `irq`
        # (dir!=''), or a `status` also named in a Ports section (sources ⊇
        # {'prose','table'}). apb_dsp's CSRs (dir='', sources={'table'}) DO match
        # → the false MISSING-PORT is removed. No prose port-detection.
        # DOCUMENTED LOW RESIDUAL (Step-2.7 round-3, accepted): a spec that lists
        # GENUINE top-level ports under a `## Register Map`/`## CSR` heading in a
        # generic-Name offset table with NO direction anywhere (no Direction/R-W
        # column, no direction prose, not under `## Ports`) is masked. This is
        # structurally identical to an internal CSR map and contrived for CVDP-
        # class specs — a port genuinely bound by the hidden TB must state its
        # direction (drive vs sample), and every realistic direction expression
        # defuses this mask (adds a non-table source or a Direction column).
        if (name.lower() in regmap_generic_csrs
                and name.lower() not in all_port_names_lower
                and name.lower() not in ports_section_names
                and not (pif.ports.get(name) or "").strip()
                and pif.sources.get(name, set()) == {"table"}):
            continue
        # (#753 reopen) a name the given-code skeleton declares as a `parameter`
        # is AUTHORITATIVELY never a port — mask it even if a (spurious) prose
        # direction was attributed ("the pipeline takes `PIPE_DEPTH` cycles to
        # propagate input signals" wrongly tagged PIPE_DEPTH an input). A
        # parameter cannot be a port, so there is no real-port to protect here.
        if (name.lower() in given_params
                and name.lower() not in all_port_names_lower):
            continue
        # (#753) a name the prompt's given code declares an internal NET (logic/
        # wire/reg) is not a port — but never mask a name the RTL actually
        # declares as a port, NOR a name the prompt PROSE/table declares with an
        # EXPLICIT DIRECTION (#753 adversarial-review: an unrelated helper block's
        # internal `reg data_valid;` must not mask a genuinely-required top port
        # the prompt declares as `an input data_valid`). Only a NET name whose
        # sole prompt evidence is direction-LESS is masked.
        if (name.lower() in given_internal
                and name.lower() not in all_port_names_lower
                and not (pif.ports.get(name) or "").strip()):
            continue
        if name.lower() not in all_port_names_lower:
            name_sources = pif.sources.get(name, set())
            srcs = ",".join(sorted(name_sources))
            # ORGANIC #770 — provenance gate. A name from a real signal table /
            # given-code header (STRUCTURAL) that the RTL omits is a genuine
            # missing port → BLOCK-eligible. A name whose ONLY evidence is a
            # free-prose scrape (PROSE_HEURISTIC) and which is ABSENT from the
            # RTL has NO structural corroboration (a phantom port: `'and'`
            # scraped from "Input and output ...", an FSM-state name) → ADVISORY.
            prov = _iface_provenance(name_sources)
            corr = _prov.corroborate_port_presence(name, all_port_names_lower)
            block = _prov.is_block_eligible(prov, corr)
            findings.append(Finding(
                "MISSING-PORT",
                f"MISSING-PORT: prompt names interface signal '{name}' "
                f"(source: {srcs}) but the RTL port list does not declare it "
                f"— the harness binds to this net by name (advisory: confirm "
                f"it is a port, not an internal signal)",
                block_eligible=block,
                advisory_note=("" if block
                               else _prov.advisory_reason(prov, corr))))

    # (3) PORT-DIRECTION: a TOP port the RTL declares with a direction that
    # disagrees with the prompt's signal table. The harness binds the top, so
    # direction is checked against the top only.
    for name, want in sorted(pif.ports.items()):
        if not want or want == "unknown":
            continue
        if name.lower() in module_names_lower:
            continue  # (#726b) a module name, not an interface signal
        rtl_orig = rtl_lower.get(name.lower())
        if rtl_orig is None:
            continue  # not a top port (satisfied elsewhere or reported missing)
        have = rtl.ports.get(rtl_orig, "unknown")
        if have in ("unknown", ""):
            continue
        if have != want:
            # ORGANIC #770 — provenance gate. A direction from a real signal
            # table / given-code header (STRUCTURAL) that the RTL contradicts is
            # a genuine direction conflict → BLOCK-eligible. A direction whose
            # ONLY evidence is a free-prose `_DIR_NEAR_*` scrape
            # (PROSE_HEURISTIC) that the RTL's OWN structural declaration refutes
            # (have != want) is the author's RTL winning over a low-confidence
            # prose guess → ADVISORY (the RTL's explicit declaration is stronger
            # evidence than a prose-proximity heuristic).
            # ORGANIC #806 — provenance from the DIRECTION sources only (not the
            # NAME sources union): a directionless-table name no longer confers
            # STRUCTURAL on a prose-only direction, so a CONTRADICTED RTL
            # declaration correctly downgrades it to advisory.
            dir_srcs = pif.dir_sources.get(name, set())
            prov = _iface_provenance(dir_srcs)
            corr = _prov.corroborate_direction(want, have)
            block = _prov.is_block_eligible(prov, corr)
            findings.append(Finding(
                "PORT-DIRECTION",
                f"PORT-DIRECTION: prompt declares '{name}' as {want} but the "
                f"RTL declares it {have} — the harness drives/reads it as "
                f"{want}, so the opposite direction FAILs functionally",
                block_eligible=block,
                advisory_note=("" if block
                               else _prov.advisory_reason(prov, corr))))
    return findings


def run(rid: Optional[str], prompt_path: Path, rtl_path: Path,
        context_paths: Optional[List[Path]] = None
        ) -> Tuple[List[Finding], Dict]:
    prompt = prompt_path.read_text(errors="replace")
    rtl_text = rtl_path.read_text(errors="replace")
    context_paths = context_paths or []
    context_rtl = [p.read_text(errors="replace") for p in context_paths]
    findings = check_conformance(rid, prompt, rtl_text, context_rtl)
    rtl = parse_rtl(rtl_text)
    report = {
        "program": "iface_conformance_v2",
        "version": "1.0.1",
        "id": rid,
        "harness_top": harness_top_from_id(rid),
        "rtl_module": rtl.module_name,
        "rtl_ports": rtl.ports,
        "findings": [{"kind": f.kind, "message": f.message,
                      "block_eligible": f.block_eligible,
                      "advisory_note": f.advisory_note} for f in findings],
        "conformant": not findings,
        # ORGANIC #770 — a finding that is reported but not BLOCK-eligible
        # (a prose-heuristic finding the RTL contradicts) does not hard-block.
        "blocking_findings": sum(1 for f in findings if f.block_eligible),
        # provenance: prove the gate only read the handed-in files (blind) —
        # the prompt, the authored RTL, and any harness-supplied context RTL.
        "files_read": [str(prompt_path), str(rtl_path)]
        + [str(p) for p in context_paths],
    }
    return findings, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="prompt→interface conformance gate (#695): module-name "
                    "case + missing-port + port-direction, all "
                    "prompt-derivable, BLIND (no oracle read).")
    ap.add_argument("--id", default=None,
                    help="canonical problem id; the harness TOPLEVEL stem is "
                         "derived from it")
    ap.add_argument("--prompt", required=True,
                    help="prompt / spec text the author was given")
    ap.add_argument("--rtl", required=True, help="the authored RTL")
    ap.add_argument("--context", action="append", default=None,
                    help="a harness-supplied context RTL file "
                         "(input.context rtl/*.sv); ports/modules it declares "
                         "count as SATISFIED, not author-missing. Repeatable.")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any finding (default: advisory, exit 0)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    pp = Path(args.prompt)
    rp = Path(args.rtl)
    for label, p in (("--prompt", pp), ("--rtl", rp)):
        if not p.is_file():
            print(f"ERROR: {label} file not found: {p}", file=sys.stderr)
            return 2
    ctx_paths: List[Path] = []
    for c in (args.context or []):
        cp = Path(c)
        if not cp.is_file():
            print(f"ERROR: --context file not found: {cp}", file=sys.stderr)
            return 2
        ctx_paths.append(cp)
    if not rp.read_text(errors="replace").strip():
        print(f"ERROR: --rtl file is empty: {rp}", file=sys.stderr)
        return 2

    findings, report = run(args.id, pp, rp, ctx_paths)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    if not findings:
        print("interface-conformance ok")
        return 0
    for f in findings:
        suffix = "" if f.block_eligible else f"  [ADVISORY — {f.advisory_note}]"
        print(f.message + suffix)
    mode = "strict" if args.strict else "advisory"
    # ORGANIC #770 — under --strict, only a BLOCK-eligible finding (STRUCTURAL,
    # or a prose-heuristic finding the RTL corroborates) hard-blocks. A
    # prose-heuristic finding the RTL contradicts / does not back is reported but
    # does NOT veto a correct emit.
    blocking = [f for f in findings if f.block_eligible]
    print(f"interface-conformance: {len(findings)} finding(s) "
          f"({len(blocking)} block-eligible) [{mode}]", file=sys.stderr)
    return 1 if (args.strict and blocking) else 0


if __name__ == "__main__":
    sys.exit(main())
