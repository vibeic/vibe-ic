#!/usr/bin/env python3
"""constraint_prose_tokens.py — the ONE reader for constraint declarations
that a design states in PROSE rather than in a machine-readable deck.

Why this is a module and not a private emitter helper
------------------------------------------------------------------
Constraint prose has more than one consumer shape, but it needs one parsing
primitive: "walk a design's own input documents and return markdown bindings
and SDC directives with their source lines".  Keeping that primitive separate
from `l19_constraint_token_emit` makes the language parser independently
testable and prevents future consumers from growing a second table walker that
answers "what does the document say" differently.

Two vocabularies live here, and only two, because both are properties of a
LANGUAGE rather than of a design:

  * `SDC_DIRECTIVES` — the command names of the SDC constraint language.
    A document that writes `create_clock` is stating a timing constraint no
    matter what chip it describes.
  * `is_flow_setting_token` — the SHAPE of a flow/tool configuration key
    (UPPER_SNAKE, two or more segments). Deliberately a shape and NOT a
    whitelist of OpenLane variable names: a whitelist is a maintenance
    surface that silently mis-reports every key nobody thought to add, and
    the value binding beside the token is what makes it a declaration.

chip-AGNOSTIC: nothing here names a design, a PDK, a vendor or a cell
library. The only literals are SDC command names and markdown syntax.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────
# Vocabulary A — the SDC constraint language's own command names
# ─────────────────────────────────────────────────────────────────────
# These are the constraint language, not a tool's configuration. A design
# that quotes one has stated a constraint; a design that quotes none has
# not. Ordered longest-first so `create_generated_clock` is never reported
# as `create_clock`.
SDC_DIRECTIVES: Tuple[str, ...] = (
    "create_generated_clock",
    "set_clock_uncertainty",
    "set_clock_transition",
    "set_max_capacitance",
    "set_propagated_clock",
    "set_input_transition",
    "set_disable_timing",
    "set_multicycle_path",
    "set_max_transition",
    "set_timing_derate",
    "set_case_analysis",
    "set_driving_cell",
    "set_output_delay",
    "set_clock_groups",
    "set_clock_latency",
    "set_input_delay",
    "set_max_fanout",
    "set_false_path",
    "set_max_delay",
    "set_min_delay",
    "create_clock",
    "set_max_area",
    "set_load",
    "set_units",
)

SDC_DIRECTIVE_RE = re.compile(
    r"\b(" + "|".join(SDC_DIRECTIVES) + r")\b")

# ─────────────────────────────────────────────────────────────────────
# Vocabulary B — the SHAPE of a flow configuration key
# ─────────────────────────────────────────────────────────────────────
# UPPER_SNAKE with at least two segments. The single-segment form is
# excluded because it collides with ordinary emphasis in prose ("PASS",
# "CLEAN", "TODO", "SKY130") and a false key is worse than a missed one:
# it lands in a published L document as a constraint the design never set.
_FLOW_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

# Markdown emphasis is stripped ONLY WHEN IT IS SYMMETRIC, and that is the
# whole design of this function rather than a detail of it. The obvious
# `^[\s`*_~]+|[\s`*_~]+$` turns the scope cell ``family_a_*`` into
# ``family_a`` — it eats a trailing `_*` that is not emphasis at all but the
# design's own GLOB, so a setting scoped to a whole library family is
# recorded against a library that does not exist. Emphasis comes in pairs;
# an identifier's punctuation does not.
_EMPHASIS_PAIRS = ("**", "__", "~~", "*", "_")


def strip_ornament(cell: str) -> str:
    """A markdown cell's text with code ticks and PAIRED emphasis removed."""
    s = str(cell).strip()
    s = s.strip("`").strip()
    changed = True
    while changed and s:
        changed = False
        for mark in _EMPHASIS_PAIRS:
            if len(s) > 2 * len(mark) and s.startswith(mark) \
                    and s.endswith(mark):
                s = s[len(mark):-len(mark)].strip()
                changed = True
                break
    return s


def is_flow_setting_token(text: str) -> bool:
    """Does this cell hold a flow/tool configuration KEY?

    Shape only. Whether it is a *declaration* is decided by the caller,
    which requires a value bound to it — see `table_bindings`. A key with
    no value beside it is a mention, and this module never turns a mention
    into a setting.
    """
    tok = strip_ornament(text)
    return bool(_FLOW_TOKEN_RE.match(tok))


# A bound value is anything that is not itself a key and not empty. It is
# NOT required to be numeric: a design writes `FP_PDN_SKIPTRIM | true`,
# `PL_TARGET_DENSITY | 工具預設` (tool default) and `CORE_RING | auto` in
# the same table, and refusing the non-numeric ones would drop the
# design's own answer for two of the three while claiming coverage of the
# table.
def is_bound_value(text: str) -> bool:
    """Is this cell a VALUE bound to a key, rather than another key?"""
    val = strip_ornament(text)
    if not val:
        return False
    if _FLOW_TOKEN_RE.match(val):
        return False       # a second key, not this key's value
    return not set(val) <= set("-:| ")   # a markdown rule row, not a value


# ─────────────────────────────────────────────────────────────────────
# Markdown table reader
# ─────────────────────────────────────────────────────────────────────
_RULE_RE = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")


def heading_path_map(text: str) -> Dict[int, str]:
    """`{line_number: "H1 > H2 > H3"}` for every line of the document.

    Every consumer here needs to know WHERE in a document a fact was
    stated, and the enclosing heading PATH is the answer — not the nearest
    heading, which for a subsection called "Core Utilization" says nothing
    about it being part of a floorplan section. Lines above the first
    heading map to the empty string.
    """
    out: Dict[int, str] = {}
    stack: List[Tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
        out[i] = " > ".join(t for _, t in stack)
    return out


def _split_row(line: str) -> Optional[List[str]]:
    """Cells of a pipe-table row, or None if the line is not one."""
    s = line.strip()
    if "|" not in s:
        return None
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = [c.strip() for c in s.split("|")]
    return cells if len(cells) >= 2 else None


class Table:
    """One markdown pipe table, with the source line of every row.

    `header` / `rows` hold RAW cell text — ornament stripping is the
    caller's call, because a caller matching a key wants it stripped and a
    caller quoting evidence wants the document's own bytes.
    """

    def __init__(self, header: List[str], header_line: int) -> None:
        self.header = header
        self.header_line = header_line
        self.rows: List[Tuple[int, List[str]]] = []


def iter_tables(text: str) -> List[Table]:
    """Every pipe table in the document, in order.

    A table is a header row, a `---` rule row, then data rows until the
    first line that is not a row. That is the GitHub-flavoured shape every
    design document in this corpus uses; a table without the rule row is
    not recognised, which is the conservative direction (a false table
    would bind keys to whatever prose happened to contain a pipe).
    """
    lines = text.splitlines()
    out: List[Table] = []
    i = 0
    while i < len(lines) - 1:
        head = _split_row(lines[i])
        if head is None or not _RULE_RE.match(lines[i + 1]):
            i += 1
            continue
        tbl = Table(head, i + 1)
        j = i + 2
        while j < len(lines):
            row = _split_row(lines[j])
            if row is None:
                break
            tbl.rows.append((j + 1, row))
            j += 1
        out.append(tbl)
        i = j
    return out


# ─────────────────────────────────────────────────────────────────────
# Key → value bindings, in the two orientations designs actually use
# ─────────────────────────────────────────────────────────────────────
# BOTH ORIENTATIONS ARE REQUIRED, and this was measured rather than
# assumed. One real design states its PDN settings row-oriented
#
#     | `FP_PDN_SKIPTRIM` | true (skip the PDN trimming pass) |
#
# and its floorplan settings column-oriented, in the SAME document
#
#     | PDK family | `FP_CORE_UTIL` | `PL_TARGET_DENSITY` |
#     | SKY130     | 45%            | tool default        |
#     | GF180MCU   | 40%            | 0.5                 |
#
# A reader that knows only the row form returns the PDN keys and reports
# the floorplan keys as absent — which is a partial extraction that reads
# exactly like a complete one, because nothing counts what it did not
# look for. The column form also carries the SCOPE (the row's first cell)
# that makes a per-library setting mean what the design meant: dropping it
# would collapse two different targets into one and the last one written
# would win.


def table_bindings(text: str, source: str = "") -> List[Dict[str, object]]:
    """Every ``key -> value`` a document's tables bind, both orientations.

    Each record:

        token    str        the configuration key, ornament-stripped
        value    str        the bound value, ornament-stripped
        scope    str|None   the row key, for a column-oriented table
        line     int        1-based line in `text` the VALUE sits on
        evidence str        the raw row, so a reader can audit the parse
        source   str        passed through verbatim
        orientation  "row" | "column"
    """
    out: List[Dict[str, object]] = []
    heads = heading_path_map(text)
    for tbl in iter_tables(text):
        # column-oriented: keys in the header, values in each data row
        key_cols = [c for c, cell in enumerate(tbl.header)
                    if is_flow_setting_token(cell)]
        for col in key_cols:
            token = strip_ornament(tbl.header[col])
            for line_no, row in tbl.rows:
                if col >= len(row) or not is_bound_value(row[col]):
                    continue
                scope = strip_ornament(row[0]) if row else ""
                out.append({
                    "token": token,
                    "value": strip_ornament(row[col]),
                    "scope": scope or None,
                    "line": line_no,
                    "evidence": " | ".join(row)[:220],
                    "source": source,
                    "section": heads.get(line_no, ""),
                    "orientation": "column",
                })
        # row-oriented: key in the first cell, value in the second
        for line_no, row in tbl.rows:
            if not row or not is_flow_setting_token(row[0]):
                continue
            if len(row) < 2 or not is_bound_value(row[1]):
                continue
            out.append({
                "token": strip_ornament(row[0]),
                "value": strip_ornament(row[1]),
                "scope": None,
                "line": line_no,
                "evidence": " | ".join(row)[:220],
                "source": source,
                "section": heads.get(line_no, ""),
                "orientation": "row",
            })
    return out


# `KEY = value` / `KEY: value` outside a table. The value must start on the
# same line: a key at the end of a sentence is a mention, and the whole
# point of requiring a binding is to keep mentions out.
#
# THE VALUE STOPS AT THE PUNCTUATION THAT WRAPS IT, not only at whitespace.
# Measured on real prose: `met(MAX_FANOUT_CONSTRAINT = 5)` yielded the value
# `5)` and ``…`FP_PDN_SKIPTRIM` = `true`(略過…)`` yielded ``true`(略過`` —
# both then landed in a published L document as the design's declared
# setting. A closing bracket or code tick belongs to the sentence, never to
# the value.
_INLINE_BIND_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\s*[=:]\s*"
    r"([^\s|,;。、`()（）\[\]<>]+)")


# A CODE BLOCK IS CODE, AND THE INLINE PATH MAY NOT READ IT.
#
# MEASURED, and this is the sweep finding that produced the rule. Across
# 105 published run dirs the inline path was the ONLY over-collector, and
# on one CPU-class design it returned 224 "settings" — every one of them
# from a literal block: a shell environment setup
#
#     ::
#
#         export RISCV_TOOLCHAIN=/path/to/riscv
#         export PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/path/to/spike/lib/pkgconfig
#
# and an ISA constant listing (`OPCODE_LOAD`, `PRIV_LVL_M`, `XDEBUGVER_STD`).
# None is a flow constraint; all of them have the SHAPE of one. Filling the
# constraints layer with a toolchain path and an opcode table is the same
# "a roster somebody wrote" failure this module refuses everywhere else.
#
# Both block idioms in this corpus are covered: a fenced block (``` / ~~~,
# markdown) and an INDENTED block (four spaces, which is how markdown and
# reStructuredText `::` both mark one). The measured design used the second.
#
# THE FENCE RULE IS FOR THE INLINE PATH ONLY. An SDC directive inside a
# fence is precisely the design QUOTING its constraint — the measured
# design's `create_clock` lives in a ```sdc block — so `sdc_directive_hits`
# deliberately reads fences, and `table_bindings` is unaffected because a
# pipe table is not a code block.
_FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")
_INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")


def _code_block_lines(text: str) -> set:
    """1-based line numbers that are CODE rather than prose."""
    out: set = set()
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.add(i)
            continue
        if in_fence or (line.strip() and _INDENTED_CODE_RE.match(line)):
            out.add(i)
    return out


def inline_bindings(text: str, source: str = "") -> List[Dict[str, object]]:
    """Every ``KEY = value`` binding stated in PROSE, outside a table."""
    code = _code_block_lines(text)
    heads = heading_path_map(text)
    out: List[Dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line_no in code:
            continue
        for m in _INLINE_BIND_RE.finditer(line):
            val = strip_ornament(m.group(2))
            if not is_bound_value(val):
                continue
            out.append({
                "token": m.group(1),
                "value": val,
                "scope": None,
                "line": line_no,
                "evidence": line.strip()[:220],
                "source": source,
                "section": heads.get(line_no, ""),
                "orientation": "inline",
            })
    return out


def sdc_directive_hits(text: str, source: str = "") -> List[Dict[str, object]]:
    """Every SDC command name the document quotes, with its line.

    Deduplicated by (directive, line): a document that writes
    ``set_input_delay / set_output_delay`` on one line has stated two
    constraints, and one that repeats a directive on the same line has
    stated one.
    """
    out: List[Dict[str, object]] = []
    seen = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        for m in SDC_DIRECTIVE_RE.finditer(line):
            key = (m.group(1), line_no)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "directive": m.group(1),
                "line": line_no,
                "evidence": line.strip()[:220],
                "source": source,
            })
    return out


def scan_inputs(texts: Iterable[Tuple[object, str]]
                ) -> Dict[str, List[Dict[str, object]]]:
    """Run all three readers over `(path, text)` pairs.

    Returns ``{"settings": [...], "directives": [...]}``. `settings`
    merges the table and inline bindings in document order, because a
    consumer asking "what did the design set" does not care which markdown
    idiom carried it.
    """
    settings: List[Dict[str, object]] = []
    directives: List[Dict[str, object]] = []
    for path, text in texts:
        src = str(path)
        settings.extend(table_bindings(text, src))
        settings.extend(inline_bindings(text, src))
        directives.extend(sdc_directive_hits(text, src))
    return {"settings": settings, "directives": directives}
