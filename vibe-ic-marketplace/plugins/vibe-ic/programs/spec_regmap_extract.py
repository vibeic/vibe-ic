#!/usr/bin/env python3
"""spec_regmap_extract.py — PROGRAM-FIRST structural register-map extractor.

A CVDP "register map" spec states a peripheral's programming model as either

  (A) a markdown table whose header carries an OFFSET/ADDRESS column plus one or
      more of {name, width, access, reset} columns, e.g.

        | Offset | Register Name | Width | Access | Reset |
        |--------|---------------|-------|--------|-------|
        | 0x0    | Count         | 32    | RO     | 0x0   |

      header synonyms vary widely (Address/Addr/Offset/Reg.Addr; Register/Name/
      Field; R/W/RO/WO/RW/Permission; bit-range `[7:0]`); or

  (B) inline offset lines that name a register and give its offset, e.g.

        - `ADDR_START` (0x00): Write 1 to start the counter.
        2. **r_operand_2**
           - **Address:** 0x1

This module turns that structure into ONE checklist item PER register (and, when
a bit-range / bitfield column is present, one extra item per bitfield),
recording offset / name / width / access / reset.

§4.05 NO-LEAK (the load-bearing rule): an item is emitted ONLY when it is
anchored to a REAL structural source — a genuine markdown table ROW whose header
proves it is a register map, or an inline offset line that literally pairs a name
with a `0xNN` offset. Free prose that merely mentions the word "register" with no
table and no `0xNN` offset yields NOTHING. `extract()` returns [] when no
register-map structure is present.

chip-AGNOSTIC: every decision keys on TABLE/OFFSET STRUCTURE and generic header
vocabulary — never on a design name, problem id, or SKU literal. Renaming every
identifier in a prompt yields the SAME number of items.

The emitted dicts match the `ChecklistItem` dataclass in spec_coverage_check.py
(fields: kind, requirement, evidence, covered, coverage_note, stations). The
kind is a STRUCTURAL kind — `register` for a whole register row / offset line,
`register_field` for a bitfield carved out of a bit-range column — NOT a
prose-heuristic kind, because the evidence is a real table row / `0xNN` line.

Public API
    extract(prompt_text: str) -> list[dict]
        Each dict has at least: kind, requirement, evidence, plus the structured
        offset / name / width / access / reset it was parsed from, and
        stations=['user_prompt'] so it drops straight into the checklist.

CLI
    python3 spec_regmap_extract.py --prompt FILE   # prints items as JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional

# A structural kind (real table row / `0xNN` offset line) — NOT in
# spec_coverage_check._PROSE_HEURISTIC_KINDS, so the produced items keep
# STRUCTURAL (blocking) provenance when wired into the checklist.
KIND_REGISTER = "register"
KIND_REGISTER_FIELD = "register_field"

# An offset literal: 0x-prefixed hex (`0x1C`, `0x100`). We deliberately do NOT
# treat a bare decimal as an offset — an offset must be self-evidently an
# address (`0x..`) so a generic numeric report column can never masquerade as
# one. (§4.05: anchor to an unambiguous structural token.)
_OFFSET_RE = re.compile(r"0[xX][0-9A-Fa-f]+")

# A bit-range field token: `[7:0]`, `[31:GPIO_WIDTH]`, `Bits[0]`, `Bit[31:1]`.
_BITRANGE_RE = re.compile(
    r"\b[Bb]its?\s*\[\s*([0-9A-Za-z_]+)\s*(?::\s*([0-9A-Za-z_]+)\s*)?\]"
    r"|(?<![\w$])\[\s*([0-9]+)\s*:\s*([0-9]+)\s*\]")

# Access-token normalisation. Keys are matched case-insensitively against a
# whole access cell (after stripping markdown emphasis / slashes / spaces).
_ACCESS_CANON = [
    (re.compile(r"^\s*read\s*[/-]?\s*write\s*$", re.I), "RW"),
    (re.compile(r"^\s*r\s*/?\s*w\s*$", re.I), "RW"),
    (re.compile(r"^\s*w\s*/?\s*r\s*$", re.I), "RW"),
    (re.compile(r"^\s*rw\s*$", re.I), "RW"),
    (re.compile(r"^\s*read[\s\-]*only\s*$", re.I), "RO"),
    (re.compile(r"^\s*ro\s*$", re.I), "RO"),
    (re.compile(r"^\s*read\s*$", re.I), "RO"),
    (re.compile(r"^\s*write[\s\-]*only\s*$", re.I), "WO"),
    (re.compile(r"^\s*wo\s*$", re.I), "WO"),
    (re.compile(r"^\s*write\s*$", re.I), "WO"),
    (re.compile(r"^\s*permission\s*$", re.I), ""),  # header echoed into a cell
]

# A header cell may carry a trailing parenthetical unit/note — `Address (Hex)`,
# `Reset Value (POR)`, `Width (bits)`. Strip it before synonym matching so the
# core token is what classifies the column.
_HDR_PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")

# ---- header-column classification (synonym tables) -----------------------
_HDR_OFFSET = re.compile(
    r"^(offset|address|addr|reg\.?\s*addr|register\s*address|base\s*addr(ess)?)$",
    re.I)
_HDR_NAME = re.compile(
    r"^(register(\s*name)?|reg(\s*name)?|name|field(\s*name)?|signal(\s*name)?)$",
    re.I)
# WIDTH = a scalar bit count (Width / Bit Width / Size). It deliberately does
# NOT claim `bitfield` / `bit field` / `bit range` — those denote a FIELD
# layout column and belong to _HDR_BITS so the row carves per-field items.
_HDR_WIDTH = re.compile(
    r"^(width|bit\s*width|size|bits)$",
    re.I)
_HDR_ACCESS = re.compile(
    r"^(access|permission|perm|r\s*/?\s*w|rw|type|mode|access\s*type)$", re.I)
_HDR_RESET = re.compile(
    r"^(reset(\s*value)?|default(\s*value)?|init(ial)?(\s*value)?|por(\s*value)?)$",
    re.I)
_HDR_BITS = re.compile(
    r"^(bit\s*field|bitfield|bit\s*range|field\s*bits|bit\s*\[?\d|range)$",
    re.I)


def _blank_code_fences(text: str) -> str:
    """Replace the body of every ```-fenced code block (and the fence lines)
    with blank lines, preserving line numbering. A register map is stated as
    markdown prose/table — never inside a code/diagram fence (e.g. a ```mermaid
    block or a Verilog listing) — so a `0xNN` inside a fence is NOT a register
    offset. §4.05: this prevents fabricating a register from fenced code."""
    out = []
    in_fence = False
    for ln in text.splitlines():
        if re.match(r"^\s*```", ln):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else ln)
    return "\n".join(out)


def _strip_md(cell: str) -> str:
    """Strip markdown emphasis (`**`, `*`, `_`, backticks) and surrounding
    whitespace from a single table cell."""
    s = cell.strip()
    s = s.replace("`", "")
    s = re.sub(r"\*\*|__", "", s)
    s = re.sub(r"(?<!\w)[*_](?!\w)", "", s)
    return s.strip()


def _split_row(line: str) -> List[str]:
    """Split a `|`-delimited markdown row into trimmed cells (emphasis kept;
    callers strip emphasis per-cell so header matching is consistent)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_delim_row(line: str) -> bool:
    """True for a markdown header/body separator row, e.g. `|---|:--:|`."""
    s = line.strip()
    if "|" not in s and "-" not in s:
        return False
    body = s.replace("|", "").replace(":", "").replace("-", "").replace(" ", "")
    return body == "" and "-" in s


def _canon_access(cell: str) -> str:
    """Normalise an access cell to RW/RO/WO/'' (empty when not an access kind)."""
    raw = _strip_md(cell)
    for rx, canon in _ACCESS_CANON:
        if rx.match(raw):
            return canon
    return ""


def _canon_width(cell: str) -> str:
    """Normalise a width cell to a bare bit count when it states one.

    `32 bits` -> `32`; `20` -> `20`; `1 bit` -> `1`; a bit-range `[7:0]` -> the
    span (`8`). Returns the trimmed original when it is not a recognisable
    numeric width (kept as evidence, never invented)."""
    raw = _strip_md(cell)
    m = re.match(r"^\s*(\d+)\s*(?:bits?)?\s*$", raw, re.I)
    if m:
        return m.group(1)
    # a bit-range width cell like `[7:0]` -> span
    m = re.match(r"^\s*\[?\s*(\d+)\s*:\s*(\d+)\s*\]?\s*$", raw)
    if m:
        hi, lo = int(m.group(1)), int(m.group(2))
        return str(abs(hi - lo) + 1)
    return raw


def _canon_reset(cell: str) -> str:
    """Trim/strip a reset/default cell (kept verbatim-ish; never fabricated)."""
    return _strip_md(cell)


# ---------------------------------------------------------------------------
# (A) markdown-table register map
# ---------------------------------------------------------------------------
def _classify_header(cells: List[str]) -> Optional[Dict[str, int]]:
    """Map a header row's columns to {offset,name,width,access,reset,bits} ->
    column index. Returns None unless the header proves it is a register map.

    A register map REQUIRES an OFFSET/ADDRESS column (the unambiguous structural
    anchor). A bit-range/bitfield column is recorded when present so the row can
    spawn per-field items, but it is not by itself sufficient — a pure field
    table with no offsets is not addressed in this register-map structural form.
    """
    norm = [_HDR_PAREN_TAIL.sub("", _strip_md(c)).lower() for c in cells]
    cols: Dict[str, int] = {}
    for i, h in enumerate(norm):
        if "offset" not in cols and _HDR_OFFSET.match(h):
            cols["offset"] = i
        elif "name" not in cols and _HDR_NAME.match(h):
            cols["name"] = i
        elif "bits" not in cols and _HDR_BITS.match(h) and not _HDR_WIDTH.match(h):
            cols["bits"] = i
        elif "width" not in cols and _HDR_WIDTH.match(h):
            cols["width"] = i
        elif "access" not in cols and _HDR_ACCESS.match(h):
            cols["access"] = i
        elif "reset" not in cols and _HDR_RESET.match(h):
            cols["reset"] = i
        elif "bits" not in cols and _HDR_BITS.match(h):
            cols["bits"] = i
    # §4.05: an OFFSET/ADDRESS anchor is mandatory, plus at least a NAME so the
    # row is a real register entry and not a generic address report.
    if "offset" in cols and "name" in cols:
        return cols
    return None


def _cell(cells: List[str], cols: Dict[str, int], key: str) -> str:
    idx = cols.get(key)
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx]


def _extract_field_items(bits_cell: str, reg_name: str, reg_offset: str,
                         evidence: str) -> List[dict]:
    """Carve per-bitfield items out of a bit-range / bitfield cell. Only emits
    when the cell literally contains a bit-range token; otherwise []."""
    items: List[dict] = []
    raw = bits_cell.strip()
    for m in _BITRANGE_RE.finditer(raw):
        if m.group(1) is not None:           # `Bits[hi:lo]` / `Bit[n]`
            hi, lo = m.group(1), (m.group(2) if m.group(2) is not None else m.group(1))
            span = f"[{hi}:{lo}]" if m.group(2) is not None else f"[{hi}]"
        else:                                 # bare `[hi:lo]`
            hi, lo = m.group(3), m.group(4)
            span = f"[{hi}:{lo}]"
        width = ""
        if hi.isdigit() and lo.isdigit():
            width = str(abs(int(hi) - int(lo)) + 1)
        items.append({
            "kind": KIND_REGISTER_FIELD,
            "requirement": (f"register `{reg_name}` (offset {reg_offset}) "
                            f"bitfield {span}"),
            "evidence": evidence.strip(),
            "offset": reg_offset,
            "name": reg_name,
            "field_bits": span,
            "width": width,
            "access": "",
            "reset": "",
            "covered": None,
            "coverage_note": "",
            "stations": ["user_prompt"],
        })
    return items


def _extract_table(text: str) -> List[dict]:
    """Find every register-map markdown table and emit per-register (+per-field)
    items. A table qualifies only if its header has an offset+name pair."""
    items: List[dict] = []
    lines = text.splitlines()
    n = len(lines)
    i = 0
    while i < n - 1:
        if lines[i].count("|") < 2:
            i += 1
            continue
        if not _is_delim_row(lines[i + 1]):
            i += 1
            continue
        header = _split_row(lines[i])
        cols = _classify_header(header)
        if cols is None:
            i += 1
            continue
        # consume body rows
        j = i + 2
        while j < n and lines[j].count("|") >= 2:
            if _is_delim_row(lines[j]):
                j += 1
                continue
            cells = _split_row(lines[j])
            offset_cell = _cell(cells, cols, "offset")
            name_cell = _cell(cells, cols, "name")
            off_m = _OFFSET_RE.search(_strip_md(offset_cell))
            name = _strip_md(name_cell)
            # §4.05: a body row counts ONLY when it carries a real `0xNN` offset
            # AND a non-empty name. Anything else (note row, blank) is skipped.
            if off_m and name:
                offset = off_m.group(0)
                width = _canon_width(_cell(cells, cols, "width"))
                access = _canon_access(_cell(cells, cols, "access"))
                reset = _canon_reset(_cell(cells, cols, "reset"))
                items.append({
                    "kind": KIND_REGISTER,
                    "requirement": (f"register `{name}` at offset {offset}"
                                    + (f", width {width}" if width else "")
                                    + (f", access {access}" if access else "")
                                    + (f", reset {reset}" if reset else "")),
                    "evidence": lines[j].strip(),
                    "offset": offset,
                    "name": name,
                    "width": width,
                    "access": access,
                    "reset": reset,
                    "covered": None,
                    "coverage_note": "",
                    "stations": ["user_prompt"],
                })
                # per-field items from a dedicated bits column or bitfield text
                bits_cell = _cell(cells, cols, "bits")
                if bits_cell:
                    items.extend(_extract_field_items(
                        bits_cell, name, offset, lines[j].strip()))
            j += 1
        i = j if j > i + 2 else i + 1
    return items


# ---------------------------------------------------------------------------
# (B) inline `NAME (0xNN)` / `0xNN: NAME` / `**Address:** 0xNN` offset lines
# ---------------------------------------------------------------------------
# Form B1: a register name token immediately followed by its offset in parens —
#   `ADDR_START` (0x00):   |   **r_operand_1** (0x0)
_INLINE_NAME_THEN_OFFSET = re.compile(
    r"[`*]*\b([A-Za-z_]\w*)\b[`*]*\s*\(\s*(0[xX][0-9A-Fa-f]+)\s*\)")
# Form B2: an offset then a name —  `0x04: ADDR_STOP`  |  `0x1C - Direction`
_INLINE_OFFSET_THEN_NAME = re.compile(
    r"(0[xX][0-9A-Fa-f]+)\s*[:\-]\s*[`*]*\b([A-Za-z_]\w*)\b")
# Form B3: a register-description block where a name line is followed (within a
# few lines) by an `Address:`/`Offset:` line —
#   **r_operand_1**
#      - **Address:** 0x0
_INLINE_NAME_LINE = re.compile(r"^[\s\-\d.)*`]*([A-Za-z_]\w*)\s*[`*:]*\s*$")
_INLINE_ADDR_LINE = re.compile(
    r"(?:address|offset|addr)\s*[:=]\s*[`*]*\s*(0[xX][0-9A-Fa-f]+)", re.I)
_INLINE_DEFAULT_LINE = re.compile(
    r"(?:default(?:\s*value)?|reset(?:\s*value)?)\s*[:=]\s*[`*]*\s*"
    r"([0-9]+'[hbod][0-9A-Fa-fxXzZ_]+|0[xX][0-9A-Fa-f]+|\d+)", re.I)


def _looks_like_register_name(tok: str) -> bool:
    """A heuristic-free structural guard: a register-name token is an
    identifier of length >= 2 that is not a pure hex/number. We do NOT key on
    any design-specific vocabulary."""
    if len(tok) < 2:
        return False
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", tok):
        return False
    if tok.isdigit():
        return False
    return True


def _extract_inline(text: str) -> List[dict]:
    """Emit one item per inline offset-bearing register line. Each item's
    evidence is the exact source line. Dedupe on (name, offset)."""
    items: List[dict] = []
    seen = set()
    lines = text.splitlines()

    def _emit(name: str, offset: str, evidence: str, reset: str = ""):
        if not _looks_like_register_name(name):
            return
        key = (name, offset.lower())
        if key in seen:
            return
        seen.add(key)
        items.append({
            "kind": KIND_REGISTER,
            "requirement": (f"register `{name}` at offset {offset}"
                            + (f", reset {reset}" if reset else "")),
            "evidence": evidence.strip(),
            "offset": offset,
            "name": name,
            "width": "",
            "access": "",
            "reset": reset,
            "covered": None,
            "coverage_note": "",
            "stations": ["user_prompt"],
        })

    # Form B3 — a name line followed within a small window by an explicit
    # Address/Offset LABEL line — is the strongest structural anchor (the
    # literal word "Address"/"Offset" proves a programming-model register, not
    # a parenthetical aside). It is mined FIRST; if it yields any register, the
    # weaker parenthetical forms (B1/B2) are SUPPRESSED for this document, so a
    # prose value-encoding such as `Write Mode (0x3)` (an enum value of a
    # register, NOT a register) cannot leak in beside the real Address-labeled
    # registers. §4.05: prefer the unambiguous structural source.
    for idx, ln in enumerate(lines):
        nm = _INLINE_NAME_LINE.match(ln)
        if not nm:
            continue
        name = nm.group(1)
        if not _looks_like_register_name(name):
            continue
        # look ahead a few lines for an Address/Offset line; stop at the next
        # name line so we never cross-attribute one register's address to the
        # following register.
        offset = None
        reset = ""
        addr_evidence = ln
        for k in range(idx + 1, min(idx + 6, len(lines))):
            nxt = lines[k]
            am = _INLINE_ADDR_LINE.search(nxt)
            if am and offset is None:
                offset = am.group(1)
                addr_evidence = f"{ln.strip()} | {nxt.strip()}"
            dm = _INLINE_DEFAULT_LINE.search(nxt)
            if dm and not reset:
                reset = dm.group(1)
            # a following stand-alone name line ends this register's block
            if k > idx + 1 and _INLINE_NAME_LINE.match(nxt) and \
                    _looks_like_register_name(_INLINE_NAME_LINE.match(nxt).group(1)):
                break
        if offset is not None:
            _emit(name, offset, addr_evidence, reset)

    # Forms B1 / B2 — single-line `NAME (0xNN)` / `0xNN: NAME` pairings — are a
    # WEAKER anchor (a parenthetical hex can be a mode value / worked example,
    # not a register address). Mine them ONLY when the strong Address-labeled
    # form (B3) found nothing, so a register list that uses ONLY the `NAME
    # (0xNN)` convention (no `Address:` label) is still recovered, while a doc
    # that has an explicit Address-labeled register block is not polluted by its
    # prose mode-encodings.
    if not items:
        for ln in lines:
            for m in _INLINE_NAME_THEN_OFFSET.finditer(ln):
                _emit(m.group(1), m.group(2), ln)
            for m in _INLINE_OFFSET_THEN_NAME.finditer(ln):
                _emit(m.group(2), m.group(1), ln)

    return items


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[dict]:
    """Extract a structural register-map checklist from `prompt_text`.

    Returns one dict per register (kind='register') and one per bitfield
    (kind='register_field'), each anchored to a real markdown table row or a
    `0xNN` offset line via its `evidence`. Returns [] when no register-map
    structure is present (§4.05 no-leak — never fabricated from free prose)."""
    if not prompt_text or not isinstance(prompt_text, str):
        return []
    # Blank out fenced code/diagram blocks first: a register map lives in
    # markdown prose/table, so a `0xNN` inside a ```...``` fence (Verilog
    # listing, mermaid diagram, waveform) is never a register offset.
    text = _blank_code_fences(prompt_text)
    items = _extract_table(text)
    # Only mine inline offset lines when the table form found nothing — a real
    # register-map table is the authoritative source; mixing the two would
    # double-count a register that appears both in the table and in prose.
    if not items:
        items = _extract_inline(text)
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Structural register-map extractor for CVDP specs.")
    ap.add_argument("--prompt", required=True,
                    help="path to a prompt/spec text file")
    ap.add_argument("--indent", type=int, default=2)
    args = ap.parse_args(argv)
    try:
        text = open(args.prompt, "r", encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"error: cannot read --prompt: {e}", file=sys.stderr)
        return 2
    items = extract(text)
    print(json.dumps(items, indent=args.indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
