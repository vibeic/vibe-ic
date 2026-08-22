#!/usr/bin/env python3
"""spec_enumset_extract.py — PROGRAM-FIRST structural extractor for CVDP
enumerated-mode (control-map) specs. [chip-AGNOSTIC, §4.05 no-leak]

WHY
  §3.9 of the spec-coverage doctrine names the MOST-MISSED checklist item: an
  enumerated set's OUTSIDE-THE-SET / default boundary. CVDP "enumerated mode"
  prompts (a rounding-mode map, an opcode->operation map, a coin-value->action
  map, a control-character table, a state-encoding `parameter` block, ...) state
  a discrete CODE -> NAMED-MODE control map AND, almost always, a single
  "invalid / otherwise / default / reserved" behavior for codes OUTSIDE the
  enumerated set. The canonical `spec_coverage_check.py` enum_set/enum_boundary
  extractor keys ONLY on a brace-list `{a, b, c}`, so the list-of-bullets /
  pipe-table / `parameter NAME = N'b...` / case-label shapes that DOMINATE the
  CVDP control-map prompts slip through and the boundary item is never charged.

WHAT
  `extract(prompt_text)` parses an enumerated CONTROL MAP — >=3 entries of the
  form `N'bXXX` / `N'hXX` / `N'dX` / `3'd2` (or a `| code | meaning |` markdown
  table row, or a `parameter NAME = N'b...` / `localparam NAME = N'b...`
  declaration) each mapped to a named mode / operation — and emits:
    * ONE `enum_set` item per (code, meaning) pair, evidence = the EXACT literal
      row / line it came from (a real `N'bxxx`/`N'hxx` literal map, so — per the
      contract — it carries the literal as `evidence` even though `enum_set` is a
      prose-heuristic kind in spec_coverage_check);
    * PLUS ONE `enum_boundary` item capturing the STATED outside-the-set/default
      behavior, evidence = the exact default/otherwise/invalid/reserved clause —
      emitted ONLY when such a behavior is stated in the prose (the load-bearing
      §3.9 recovery).

  Each emitted dict mirrors the `ChecklistItem` shape consumed by
  spec_coverage_check.py: kind / requirement / evidence / coverage_tokens
  (+ provenance/block_eligible defaults), so the list can be merged straight
  into that program's checklist (see `as_checklist_items`).

§4.05 NO-LEAK
  * require >=3 REAL literal entries — a single value or pure prose returns [];
  * every emitted item is anchored to a concrete structural feature (a sized
    literal, a pipe-table row, a parameter/localparam decl, or a case label) —
    NEVER fabricated from free prose;
  * the boundary item is emitted ONLY when the prose actually states an
    outside-the-set behavior (otherwise/invalid/default/reserved/...), so a map
    with no stated default does not invent a phantom boundary requirement.

chip-AGNOSTIC: keyed on the literal-map STRUCTURE (sized literals, pipe tables,
parameter decls, case labels) — NO chip / vendor / SKU / problem-id literal.

CLI
    python3 spec_enumset_extract.py --prompt FILE   # -> JSON list to stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Literal grammars (chip-AGNOSTIC, pure Verilog/SystemVerilog literal shapes)
# ---------------------------------------------------------------------------
# A SIZED literal: 3'b000 / 8'hFB / 3'd2 / 2'b01 (width ' base digits).
_SIZED_LIT = r"\d+'[bBdDhHoO][0-9A-Fa-fxXzZ_]+"
# A hex literal in 0x form (control-character tables: 0x07, 0xFB).
_HEX0X_LIT = r"0[xX][0-9A-Fa-f]+"
# A Verilog-style `0b...` selector literal (axi_alu op_select: 0b00 / 0b11).
_BIN0B_LIT = r"0[bB][01]+"

_SIZED_RE = re.compile(_SIZED_LIT)
_HEX0X_RE = re.compile(_HEX0X_LIT)
_BIN0B_RE = re.compile(_BIN0B_LIT)

# An outside-the-set / default boundary clause. The presence of ANY of these
# tokens AND a stated resulting behavior makes the boundary item testable.
# (Re-uses the same family as spec_coverage_check._DEFAULT_CLAUSE_RE but does NOT
# require a `{...}` brace anchor — the CVDP maps are bullet/table/param shaped.)
# NOTE: a BARE `default` is too weak (it matches "the key has a default value of
# 0xAA", which is NOT an outside-the-set behavior). It is admitted ONLY in its
# FALLBACK-VERB / case-path forms ("defaults to ...", "default case/path/
# behavior") that genuinely denote the out-of-set path. chip-AGNOSTIC.
_BOUNDARY_TOKEN_RE = re.compile(
    r"\b(any\s+other|all\s+other|otherwise|unsupported|unrecognized|"
    r"unrecognised|unlisted|invalid|reserved|illegal|not\s+(?:in|listed|"
    r"valid|recognized|recognised|defined|supported)|outside\s+the\s+set|"
    r"out[- ]of[- ]range|defaults?\s+to|default\s+(?:case|path|behaviou?r|"
    r"value\s+is\s+(?:invalid|reserved|illegal))|else)\b",
    re.I)
# A stated RESULT after the boundary token, on the same sentence/clause: an
# arrow / "defaults to" / "triggers" / "results in" / "should" / "=" verb plus
# some text. Used to confirm the boundary actually states a BEHAVIOR.
_BOUNDARY_RESULT_RE = re.compile(
    r"(?:->|→|=>|"
    r"\bdefaults?\s+to\b|\btriggers?\b|\bresults?\s+in\b|\bgives?\b|"
    r"\byields?\b|\bproduces?\b|\bmaps?\s+to\b|\bsets?\b|\bcauses?\b|"
    r"\bshould\b|\bmust\b|\bwill\b|\bis\s+(?:reserved|illegal|invalid)\b|"
    r"\btrigger\w*\b|\bremain\w*\b|\breturn\w*\b|\bmoves?\s+to\b|"
    r"\boccur\w*\b|\bdefault\b)",
    re.I)
# The SELECTOR noun the boundary must be ABOUT — a value/code/mode/input of the
# enumerated map (not, e.g., a "default key VALUE" that merely contains the word
# "default"). The outside-the-set clause is testable only when it governs codes
# of the map. chip-AGNOSTIC: generic selector vocabulary, no design literal.
_SELECTOR_NOUN_RE = re.compile(
    r"\b(mode|modes|code|codes|opcode|opcodes|value|values|input|inputs|"
    r"header|headers|field|fields|type|state|states|select\w*|coin|coins|"
    r"item|items|operation|operations|command|commands|encoding|symbol|"
    r"option|options|entry|entries|character|characters)\b",
    re.I)
# A clause that is HDL CODE (a case-label / assignment line / inline `//`
# comment), never an English boundary sentence. We require the boundary to be
# PROSE so a `default: sig <= data;` code label or a `// Fan off by default`
# comment is not mistaken for a stated outside-the-set behavior. A bare sized
# literal (`3'b000`) is NOT a code marker — prose routinely cites the set bounds
# ("values other than 3'b000 to 3'b100, ... should default to ...") — so the
# literal arm is deliberately absent. chip-AGNOSTIC: code-structure markers only.
_CODE_CLAUSE_RE = re.compile(
    r"(?://|<=|\bbegin\b\s*$|^\s*end\b|\bendcase\b|\bassign\s+\w+\s*=|"
    r"^\s*case\s*\(|<<|>>)")

# A bare-binary opcode literal in an explicit opcode/code/select context (the
# secure_ALU `i_opcode = 000 .. 111` shape — no width prefix). Only honored when
# the surrounding line names an opcode/code/select/mode token, so a plain "000"
# elsewhere is NOT a code. chip-AGNOSTIC: opcode-context grammar.
_OPCODE_CTX_RE = re.compile(
    r"\b(opcode|op[\s_-]?code|op[\s_-]?sel\w*|op[\s_-]?select|i_opcode|"
    r"mode|select|sel\b|encoding|state|cmd|command|action)\b", re.I)
_BARE_BIN_RE = re.compile(r"\b([01]{2,8})\b")

# Markdown pipe-table row: `| key | val |` (>=2 cells). Reused minimal parser so
# this program stays self-contained (no import of spec_coverage_check internals).
_MD_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_MD_DELIM_RE = re.compile(r"^[\s:|-]+$")

# `parameter NAME = N'b...` / `localparam NAME = N'b...,` state-encoding decls.
# Captures NAME and the literal. chip-AGNOSTIC pure HDL grammar.
_PARAM_DECL_RE = re.compile(
    r"\b(?:parameter|localparam)\b[^=;]*?"
    r"\b([A-Za-z_]\w*)\s*=\s*(" + _SIZED_LIT + r")",
    re.I)
# Chained `localparam A = x, B = y, C = z;` continuation members:
# `NAME = N'b...` not preceded by the keyword (the keyword arm above caught the
# first). chip-AGNOSTIC.
_PARAM_CHAIN_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*=\s*(" + _SIZED_LIT + r")")

# A case label `N'b... :` / `N'd... :` inside a case statement (fan_controller
# `3'd1 : ...`, gate_target `2'b00 : ...`). chip-AGNOSTIC.
_CASE_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(" + _SIZED_LIT + r")\s*:")

# An EXAMPLE / SCENARIO / TEST-CASE section heading. The bullets under such a
# heading list CONCRETE input/output VALUES of one stimulus (`rm = 3'b101`,
# `in_data = 24'b...`), NOT the enumerated MAP definition — so charging them as
# map members both inflates the member count and admits an invalid example code
# (`3'b101`) as if it were a defined mode. We strip example sections before
# extracting the map (the boundary scan still runs on the FULL text, since a
# default behavior may be stated in an example). chip-AGNOSTIC: pure heading
# grammar (markdown heading / bold heading), no design literal.
_EXAMPLE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*\s*|\d+\.\s*)*"
    r"(?:example|scenario|test\s*case|test\s*inputs|sample)\b",
    re.I)
_ANY_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$)")


# ---------------------------------------------------------------------------
# Meaning extraction (best-effort, structural)
# ---------------------------------------------------------------------------
def _clean_meaning(text: str) -> str:
    """Trim a captured meaning fragment to a short human label: strip markdown
    emphasis / code ticks / trailing punctuation; collapse whitespace."""
    t = text.strip()
    t = re.sub(r"`+", "", t)
    t = re.sub(r"\*+", "", t)
    t = t.strip(" \t-:|.,;")
    t = re.sub(r"\s+", " ", t)
    return t


def _meaning_near(line: str, lit: str) -> str:
    """Best-effort named meaning for a code literal on its own line / bullet.

    Picks the FIRST non-literal informative token group on the line — the named
    mode / operation. Prefers the SHORT name (a back-ticked / bold identifier)
    over a long parenthetical gloss: a bold+ticked `RNE (Round to Nearest...)`
    yields "RNE". Empty string when none (the entry still counts: a code with no
    inline name is still a valid enumerated member structurally)."""
    # Remove the literal itself and common decoration, then take a short label.
    without = line.replace(lit, " ")
    # Prefer a bold name `**RNE** (...)` or `**\`RNE\` (...)**`; inside it prefer
    # a back-ticked short identifier (the symbolic mode name) over the gloss.
    m = re.search(r"\*\*([^*]+)\*\*", without)
    if m:
        inner = m.group(1)
        tick = re.search(r"`([^`]+)`", inner)
        return _clean_meaning(tick.group(1) if tick else inner)
    m = re.search(r"`([^`]+)`", without)
    if m:
        return _clean_meaning(m.group(1))
    # Else first identifier-ish run.
    m = re.search(r"[A-Za-z][\w /+().-]{0,60}", without)
    return _clean_meaning(m.group(0)) if m else ""


# ---------------------------------------------------------------------------
# Structural map extractors — each returns a list of (code, meaning, evidence)
# ---------------------------------------------------------------------------
# An ENTRY is (code, meaning, evidence, form). `form` records HOW the code was
# anchored (pipe-table row / parameter decl / case label / bullet-mapping), used
# only for debugging — the cohort selector keys on the code's (width, base).

# A bullet / sentence that MAPS a selector value to a named mode: the code sits
# in a selector/label position, NOT on the RHS of a data/reset assignment. The
# disqualifying shape is `<signal> <= <literal>` / `<signal> = <literal>` where
# the literal is a DATA/RESET value being written to a signal (grant1 <= 1'b0,
# prdata <= 8'b0, TEMP_LOW <= 8'd30). The qualifying shapes put the code as the
# OBJECT of selection: `NAME (...) : code`, `selector = code -> behavior`,
# `code :` (case), `| code | meaning |` (table). chip-AGNOSTIC.
_RHS_DATA_ASSIGN_RE = re.compile(
    r"[A-Za-z_]\w*(?:\s*\[[^\]]*\])?\s*(?:<=|=)\s*[^=<>]*$")


def _strip_example_sections(text: str) -> str:
    """Blank out lines belonging to an EXAMPLE / SCENARIO / TEST-CASE section so
    the MAP extraction does not treat concrete example stimulus values as map
    members. A section runs from an example heading to the next heading of the
    SAME-or-shallower level (or EOF). Lines are blanked (not removed) so byte
    offsets / line counts are preserved for evidence fidelity. chip-AGNOSTIC."""
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    in_example = False
    for ln in lines:
        if _EXAMPLE_HEADING_RE.match(ln):
            in_example = True
            out.append("\n" if ln.endswith("\n") else "")
            continue
        if in_example and _ANY_HEADING_RE.match(ln) \
                and not _EXAMPLE_HEADING_RE.match(ln):
            in_example = False
        out.append(("\n" if ln.endswith("\n") else "") if in_example else ln)
    return "".join(out)


# A REGISTER-MAP table header (Offset/Address + Access/Width) — its rows map an
# OFFSET to a register NAME, NOT a code to a meaning, so it is owned by
# spec_regmap_extract and must NOT be read as an enum set (the SPI-datasheet
# precision leak: `| 0x00 | CTRL | RW | 32 |` was minting an enum member).
_REGMAP_HDR_OFFSET_RE = re.compile(r"\b(offset|address|addr)\b", re.I)
_REGMAP_HDR_ACCESS_RE = re.compile(r"\b(access|width|r/?w|rw|ro|wo)\b", re.I)
# A SELECTOR/ENCODING column name in the FIRST header cell — a table whose first
# column enumerates a mode / select / encoding / type field MAY use small DECIMAL
# codes (0,1,2,3) that the sized/hex/bin literal matchers do not catch.
_SELECTOR_HDR_RE = re.compile(
    r"\b(mode|sel|select|selector|encoding|enc|state|type|code|field|opcode|"
    r"cmd|command|setting|option|config)\b", re.I)
_SMALL_DEC_RE = re.compile(r"^\d{1,3}$")


def _from_pipe_tables(text: str) -> List[tuple]:
    """Each `| code | meaning |` row whose FIRST cell holds a code literal.

    Table-aware: a REGISTER-MAP table (Offset/Address + Access/Width header) is
    skipped (it is a register map, not an enum), and a SELECTOR table (first
    header column = mode/sel/encoding/…) additionally accepts a small DECIMAL code
    so a `| MODE | … |` / `0 | … | meaning` mode table is recovered."""
    out: List[tuple] = []
    lines = text.splitlines()
    is_regmap = False
    is_selector = False
    for i, raw in enumerate(lines):
        m = _MD_ROW_RE.match(raw)
        if not m:
            is_regmap = is_selector = False   # left the table
            continue
        if _MD_DELIM_RE.match(raw.strip().strip("|")):
            continue  # header delimiter row (state already set from the header)
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 2:
            continue
        # A header row is one IMMEDIATELY FOLLOWED BY a `|---|` delimiter — classify
        # the table from it and consume no data from it.
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _MD_DELIM_RE.match(nxt.strip().strip("|")):
            hdr = " ".join(cells).lower()
            is_regmap = bool(_REGMAP_HDR_OFFSET_RE.search(hdr)
                             and _REGMAP_HDR_ACCESS_RE.search(hdr))
            is_selector = bool(_SELECTOR_HDR_RE.search(cells[0]))
            continue
        if is_regmap:
            continue  # a register map is NOT an enum set (owned by spec_regmap_extract)
        # find the code cell (the first cell containing a code literal)
        code_cell = None
        code_lit = None
        for c in cells:
            lit = (_SIZED_RE.search(c) or _HEX0X_RE.search(c)
                   or _BIN0B_RE.search(c))
            if lit:
                code_cell = c
                code_lit = lit.group(0)
                break
        # a SELECTOR table may encode with a small decimal in the first cell
        if code_lit is None and is_selector and _SMALL_DEC_RE.match(cells[0]):
            code_cell = cells[0]
            code_lit = cells[0]
        if code_lit is None:
            continue
        # meaning = the concatenation of the OTHER cells (the value/description)
        meaning_cells = [c for c in cells if c is not code_cell and c]
        meaning = _clean_meaning(" -> ".join(meaning_cells)) if meaning_cells \
            else _clean_meaning(code_cell.replace(code_lit, ""))
        out.append((code_lit, meaning, raw.strip(), "pipe"))
    return out


def _from_parameters(text: str) -> List[tuple]:
    """`parameter/localparam NAME = N'b...` state-encoding members, including
    comma-chained continuations of one declaration statement."""
    out: List[tuple] = []
    seen_spans: set = set()
    # Walk each parameter/localparam STATEMENT (up to its `;`) so a chained
    # `localparam A=.., B=.., C=..;` yields every member.
    for sm in re.finditer(r"\b(?:parameter|localparam)\b", text, re.I):
        start = sm.start()
        semi = text.find(";", start)
        stmt = text[start: semi if semi != -1 else min(len(text), start + 400)]
        for cm in _PARAM_CHAIN_RE.finditer(stmt):
            name, lit = cm.group(1), cm.group(2)
            key = (name, lit)
            if key in seen_spans:
                continue
            seen_spans.add(key)
            out.append((lit, _clean_meaning(name),
                        _clean_meaning(f"{name} = {lit}"), "param"))
    return out


def _from_case_labels(text: str) -> List[tuple]:
    """`N'b... :` / `N'd... :` case labels with the inline comment / RHS as the
    meaning (fan_controller `3'd1 : pwm_duty_cycle <= 8'd64; // Low speed`)."""
    out: List[tuple] = []
    for m in _CASE_LABEL_RE.finditer(text):
        lit = m.group(1)
        # take the rest of that line as the meaning hint
        line_end = text.find("\n", m.end())
        rest = text[m.end(): line_end if line_end != -1 else len(text)]
        comment = ""
        cmt = re.search(r"//\s*(.+)$", rest)
        if cmt:
            comment = _clean_meaning(cmt.group(1))
        meaning = comment or _clean_meaning(rest)
        out.append((lit, meaning, _clean_meaning(m.group(0).strip()), "case"))
    return out


def _from_bullets(text: str) -> List[tuple]:
    """List-of-bullets / inline `NAME (...): N'b...` map (rounding_0001's 5-mode
    table) and bare-binary opcode maps in an opcode context (secure_ALU).

    §4.05: a code on the RHS of a DATA/RESET assignment (`grant1 <= 1'b0`,
    `prdata <= 8'b0`, `TEMP_LOW <= 8'd30`) is NOT a selector value being mapped —
    it is a data value WRITTEN to a signal — so it is excluded. A code in a
    selector/named-mode position (`**RNE** (...): 3'b000`, `i_opcode = 000:
    Addition`) is kept. The literal must be the SELECTED value, not the assigned
    data. chip-AGNOSTIC: assignment-shape grammar, no design/vendor literal."""
    out: List[tuple] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # A markdown TABLE ROW is owned by `_from_pipe_tables` (which applies the
        # register-map / selector classification). Skipping it here prevents a
        # register-map row (`| 0x00 | CTRL | RW | … |`) the table pass deliberately
        # dropped from being re-minted as a bare-literal bullet enum. chip-AGNOSTIC.
        if _MD_ROW_RE.match(raw):
            continue
        lit = (_SIZED_RE.search(line) or _HEX0X_RE.search(line)
               or _BIN0B_RE.search(line))
        if lit:
            litstr = lit.group(0)
            # Drop a literal that is the RHS DATA of an assignment whose LHS is a
            # signal — unless the line ALSO carries a case-label `code :` form (a
            # `code : sig <= data` keeps the code; the data RHS is filtered by
            # de-dup against the case extractor). Use the text BEFORE the literal
            # to see whether `signal <= ... ` / `signal = ...` opens to its left.
            before = line[:lit.start()]
            if _RHS_DATA_ASSIGN_RE.search(before) and ":" not in before:
                continue
            out.append((litstr, _meaning_near(line, litstr), line, "bullet"))
            continue
        # bare-binary opcode in opcode context (`i_opcode = 000` -> Addition)
        if _OPCODE_CTX_RE.search(line):
            bm = _BARE_BIN_RE.search(line)
            if bm:
                out.append((bm.group(1), _meaning_near(line, bm.group(1)),
                            line, "bullet-bin"))
    return out


def _lit_cohort(code: str) -> tuple:
    """The (width, base) cohort key of a code literal, for grouping members of
    ONE enumerated map. A sized literal `3'b000` -> (3, 'b'); a `0x07` -> a hex
    cohort keyed by hex-DIGIT-COUNT; a `0b00` -> a binary cohort by bit-count; a
    bare binary `000` -> a binary cohort by bit-count. chip-AGNOSTIC."""
    m = re.fullmatch(r"(\d+)'([bBdDhHoO])[0-9A-Fa-fxXzZ_]+", code)
    if m:
        return (int(m.group(1)), m.group(2).lower())
    if re.fullmatch(_HEX0X_LIT, code):
        return (len(re.sub(r"^0[xX]", "", code)) * 4, "h0x")
    if re.fullmatch(_BIN0B_LIT, code):
        return (len(re.sub(r"^0[bB]", "", code)), "b0b")
    if re.fullmatch(r"[01]{2,8}", code):
        return (len(code), "bare")
    # A bare small DECIMAL selector code (`MODE` table 0/1/2/3). These reach the
    # cohorter ONLY from `_from_pipe_tables`' SELECTOR-table path (no other source
    # emits a bare decimal — table rows are skipped by `_from_bullets`), so a fixed
    # survivable cohort groups the mode values without admitting incidental
    # decimals. chip-AGNOSTIC.
    if re.fullmatch(r"\d{1,3}", code):
        return (2, "dec")
    return (0, "?")


def _select_dominant_cohort(entries: List[tuple]) -> List[tuple]:
    """Group entries by (width, base) cohort and return the members of the
    DOMINANT enumerated map: the cohort with the most DISTINCT code values
    (>=3 required; ties broken by earliest first appearance).

    This is the §4.05 anchor that separates the real enumerated control map from
    incidental same-shaped literals: a 5-mode 3-bit selector map dominates the
    handful of stray 24-bit data vectors / 1-bit reset flags that share no
    cohort with it. Width-1 literals (`1'b0` flags) never form a map and are
    dropped. chip-AGNOSTIC: pure literal-shape cohorting, no design literal."""
    cohorts: Dict[tuple, List[tuple]] = {}
    order: Dict[tuple, int] = {}
    for idx, e in enumerate(entries):
        coh = _lit_cohort(e[0])
        if coh[0] <= 1:
            continue  # a 1-bit / unparsable literal is never an enumerated map
        cohorts.setdefault(coh, []).append(e)
        order.setdefault(coh, idx)
    best_coh = None
    best_n = 0
    for coh, members in cohorts.items():
        distinct = len({m[0].lower().replace("_", "") for m in members})
        if distinct < 3:
            continue
        if distinct > best_n or (distinct == best_n and best_coh is not None
                                 and order[coh] < order[best_coh]):
            best_coh = coh
            best_n = distinct
    if best_coh is None:
        return []
    return cohorts[best_coh]


def _dedup_entries(entries: List[tuple]) -> List[tuple]:
    """Stable de-dup by code literal (a code may appear in both a bullet AND its
    code block — keep the first / most-descriptive). chip-AGNOSTIC."""
    seen: set = set()
    out: List[tuple] = []
    for code, meaning, ev, form in entries:
        norm = code.lower().replace("_", "")
        if norm in seen:
            # prefer the entry that carries a non-empty meaning
            for i, (c, mn, e, f) in enumerate(out):
                if c.lower().replace("_", "") == norm and not mn and meaning:
                    out[i] = (c, meaning, e, f)
                    break
            continue
        seen.add(norm)
        out.append((code, meaning, ev, form))
    return out


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------
def _find_boundary(text: str) -> Optional[str]:
    """Return the exact stated outside-the-set / default PROSE clause when the
    spec states a behavior for codes OUTSIDE the enumerated set; else None.

    A clause qualifies when ALL hold (§4.05 — the boundary is the load-bearing
    recovery, so the bar is deliberately strict):
      * it is PROSE, not HDL code (no `//` comment / `<=` / case-label / brace);
      * it carries a boundary token (otherwise / invalid / unsupported / any
        other / not in the set / reserved / out-of-range / default / else);
      * the boundary token is ABOUT a selector noun of the map (mode / code /
        value / input / header / field / coin / item / ...), so a "default KEY
        VALUE" that merely contains the word "default" does not qualify;
      * it states a RESULT (-> / triggers / should / is reserved / defaults to /
        moves to / error / ...).
    With no such stated PROSE behavior -> None (emit NO boundary item).

    Scanning is TOKEN-ANCHORED rather than hard sentence-split so a soft-wrapped
    prose sentence ("...values other than 3'b000 to\\n3'b100), ... should default
    to ...") is judged as ONE clause — the bound between the boundary token and
    its stated result is robust to mid-sentence line wraps."""
    best: Optional[str] = None
    for tok in _BOUNDARY_TOKEN_RE.finditer(text):
        # the clause = the surrounding sentence, bounded by sentence terminators
        # (`.`/`\n\n`) but NOT a single soft `\n`. Walk left/right to the nearest
        # sentence boundary; collapse internal soft newlines.
        lo = max((text.rfind(".", 0, tok.start()),
                  text.rfind("\n\n", 0, tok.start())))
        if lo < 0:
            lo = 0
        hi_dot = text.find(".", tok.end())
        hi_par = text.find("\n\n", tok.end())
        cands = [h for h in (hi_dot, hi_par) if h != -1]
        hi = min(cands) if cands else len(text)
        clause = text[lo:hi]
        flat = re.sub(r"\s+", " ", clause).strip(" .\n")
        if not flat:
            continue
        # PROSE only — reject HDL code lines / inline comments.
        if _CODE_CLAUSE_RE.search(flat):
            continue
        # the boundary must be ABOUT a selector noun of the map.
        if not _SELECTOR_NOUN_RE.search(flat):
            continue
        # require a stated RESULT somewhere in the clause.
        if not _BOUNDARY_RESULT_RE.search(flat):
            continue
        cl = _clean_meaning(flat)
        # prefer the SHORTEST qualifying clause (the crisp default statement).
        if cl and (best is None or len(cl) < len(best)):
            best = cl
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[dict]:
    """Extract enumerated-set + outside-the-set boundary checklist items from a
    CVDP enumerated-mode prompt.

    Returns a list of dicts mirroring spec_coverage_check.ChecklistItem (kind /
    requirement / evidence / coverage_tokens + provenance defaults):
      * one kind='enum_set' per (code, meaning) entry (evidence = the exact
        literal row / line);
      * one kind='enum_boundary' (evidence = the exact default/otherwise clause)
        WHEN the prose states an outside-the-set behavior.

    §4.05 no-leak: returns [] unless >=3 real literal entries are recovered
    (a single value or pure prose -> []). chip-AGNOSTIC."""
    if not prompt_text or not prompt_text.strip():
        return []

    # Map members are extracted from the DEFINITION text (example/scenario/test
    # sections stripped) so concrete example stimulus values are not mistaken for
    # map members; the boundary scan below runs on the FULL prompt.
    def_text = _strip_example_sections(prompt_text)
    entries = _dedup_entries(
        _from_pipe_tables(def_text)
        + _from_parameters(def_text)
        + _from_case_labels(def_text)
        + _from_bullets(def_text)
    )

    # Reduce the raw candidates to the DOMINANT enumerated map (the largest
    # same-(width,base) cohort, >=3 distinct codes) so a 5-mode 3-bit selector
    # map is not diluted by stray data vectors / reset flags of other widths.
    entries = _select_dominant_cohort(entries)

    # §4.05: require >=3 REAL literal entries. A single value / pure prose -> [].
    if len(entries) < 3:
        return []

    items: List[dict] = []
    for code, meaning, evidence, _form in entries:
        label = f"{code} -> {meaning}" if meaning else code
        items.append({
            "kind": "enum_set",
            "requirement": f"enumerated mode: {label} handled",
            "evidence": evidence,            # the EXACT literal/row (contract)
            "coverage_tokens": [code] + ([meaning] if meaning else []),
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    # The load-bearing §3.9 recovery: the outside-the-set / default boundary.
    boundary = _find_boundary(prompt_text)
    if boundary is not None:
        items.append({
            "kind": "enum_boundary",
            "requirement": ("outside-the-set / default boundary: "
                            + boundary),
            "evidence": boundary,            # the EXACT default/otherwise clause
            # an outside-the-set value is, by definition, none of the members
            "coverage_tokens": ["__OUTSIDE_SET__"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    return items


def as_checklist_items(prompt_text: str):
    """Convenience: return extract() results as spec_coverage_check.ChecklistItem
    instances when that module is importable (so the structurally-anchored items
    merge straight into its checklist). Falls back to the raw dicts otherwise.
    chip-AGNOSTIC, import-optional (no hard dependency)."""
    raw = extract(prompt_text)
    try:
        from spec_coverage_check import ChecklistItem  # type: ignore
    except Exception:
        try:
            from .spec_coverage_check import ChecklistItem  # type: ignore
        except Exception:
            return raw
    out = []
    for d in raw:
        out.append(ChecklistItem(
            kind=d["kind"],
            requirement=d["requirement"],
            evidence=d["evidence"],
            coverage_tokens=list(d.get("coverage_tokens", [])),
            provenance=d.get("provenance", "STRUCTURAL"),
            block_eligible=d.get("block_eligible", True),
        ))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Structural extractor for CVDP enumerated-mode control "
                    "maps (enum_set + outside-the-set boundary).")
    ap.add_argument("--prompt", required=True,
                    help="path to the prompt/spec text file")
    args = ap.parse_args(argv)
    try:
        text = open(args.prompt, "r", encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"error: cannot read --prompt: {e}", file=sys.stderr)
        return 2
    items = extract(text)
    print(json.dumps(items, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
