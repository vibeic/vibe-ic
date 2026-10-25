#!/usr/bin/env python3
"""phase1_port_extract.py — deterministic PORT / PARAM / RESET extraction for the
Phase-1 NL ingester.

Field measurement (CVDP 12-prompt AI-vs-program audit, 2026-06-20): the phase1
NL ingester captured only ~17% of the ports an AI extracts, because it only
catches ports written as inline Verilog declarations (`input wire clk,`) and
MISSES ports stated in a markdown interface/pin TABLE or a prose signal list —
the dominant form in CVDP-style prompts (e.g. `| In_Data | in | InWidth_g |`).

This program reuses the already-shipped structural parsers in `_specrtl_common`
(`parse_verilog_ports` for inline decls + `_parse_md_table_ports` for markdown
interface tables) and adds a parameter-table / `parameter X = N` extractor, so
the deterministic ingest captures the RTL-critical structural facts (ports with
direction+width, parameters with defaults) that determine correct downstream RTL.
chip-AGNOSTIC: pure structural extraction; no design/vendor literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
# vibe-ic#712 — the ONE negation vocabulary. A width cell that DENIES a range
# must not publish it; see `_signal_table_rows` and `_stated_width`.
from _prose_polarity import is_denied as _prose_is_denied  # noqa: E402
# vibe-ic#731 — offset-PRESERVING blanker. `_verilog_region_spans` publishes
# offsets into the caller's text, so the delete-style stripper next to it
# cannot be used there.
from _hdl_code_text import strip_hdl_comments_and_strings  # noqa: E402

from _specrtl_common import (  # noqa: E402
    parse_verilog_ports, _parse_md_table_ports, Port, strip_comments,
    _strip_subprograms, _PORT_DECL as _PORT_DECL_SPAN, _parse_module_params,
    _safe_eval_int, WIDTH_UNKNOWN,
)

# `parameter NAME = VALUE` / `localparam NAME = VALUE` (Verilog form).
_PARAM_DECL = re.compile(
    r'\b(?:parameter|localparam)\b(?:\s+\w+)?\s+([A-Za-z_]\w*)\s*=\s*([^,;\n)]+)')
# a markdown parameter table row: `| NAME | DEFAULT | description |` where the
# first cell is a bare identifier and the second a number/expr (NOT a direction).
_MD_ROW = re.compile(r'^\s*\|(.+)\|\s*$')


def _dedup_ports(ports: List[Port]) -> List[Dict]:
    seen, out = set(), []
    for p in ports:
        if p.name in seen:
            continue
        seen.add(p.name)
        out.append({"name": p.name, "dir": p.direction, "width": p.width})
    return out


# A Verilog code region: a fenced ```…``` block, or a `module … endmodule` span.
# parse_verilog_ports is ONLY run inside these — running it on free PROSE scrapes
# the English word after a literal `input`/`output` as a phantom port
# (`input data vector` -> 'data'/'vector'); the markdown-table parser is precise
# on its own and needs no such region gating.
_FENCE = re.compile(r'```[a-zA-Z]*\n(.*?)```', re.S)
# vibe-ic#2060 — the span must OPEN on a real module HEADER, not on the English
# word "module". Measured on the 18 real prompt-entry design inputs: every one of
# these prompts says "module" in its first prose sentence ("Complete the given
# partial System Verilog module `binary_to_bcd`", "Perform a LINT code review on
# the `image_rotate` module") and closes a code fence with `endmodule`, so
# `\bmodule\b.*?\bendmodule\b` spanned the WHOLE DOCUMENT. `_looks_like_verilog`
# then said yes — correctly, there IS a real module header inside that span — and
# `parse_verilog_ports` ran over running English, publishing `a`, `and`, `be`,
# `been`, `bit`, `changes`, `combinational`, `managing`, `matches`, `signal`,
# `the`, `to`, `until`, `whether` as ports of real designs. The anti-phantom
# contract this module states in its own docstring was defeated by its own
# region finder. A Verilog module header is `module <name>` immediately followed
# by `(` (ANSI port list), `#(` (parameter list) or `;` (non-ANSI header) — a
# prose mention is followed by a backtick, a verb or a full stop and no longer
# opens a region.
_MODULE_SPAN = re.compile(
    r'\bmodule\s+[A-Za-z_]\w*\s*[#(;].*?\bendmodule\b', re.S)

# Step-2.7 §4.05 — a candidate region (fence or module-span) is only fed to
# parse_verilog_ports when it ACTUALLY LOOKS LIKE Verilog. A markdown code fence
# is the universal container for logs / pseudo-code / ASCII waveforms / register
# dumps, and the bare words `module`/`endmodule` are common in IC spec PROSE — so
# gating merely on "inside a fence / module-span" (not on Verilog content) let a
# non-Verilog fence (` ```\ninput message byte stream\n``` `) and a prose span
# (`Each module accepts an input signal … endmodule …`) scrape phantom ports,
# defeating this module's own anti-phantom contract. A region qualifies iff it
# has a REAL module header (`module <name> (`/`#(`) OR a genuine Verilog port
# DECL line — a direction keyword NOT followed by `=`/`:`/`(` (excludes Python
# `output = compute(x)` / `input(...)`), an optional net-type/width, an
# identifier, then the decl-terminating `,`/`;`. Prose `input message byte
# stream` (no terminator) and pseudo-code never match.
_VERILOG_MODULE_HDR = re.compile(r'\bmodule\s+\w+\s*[#(]', re.I)
_VERILOG_PORT_DECL = re.compile(
    r'^\s*(?:input|output|inout)\b(?!\s*[=:(])'
    r'(?:\s+(?:wire|reg|logic|signed|unsigned|tri\d?|bit|byte))*'
    r'\s*(?:\[[^\]]*\]\s*)?\w+\s*[,;]', re.I | re.M)
# A genuine Verilog parameter/localparam declaration (`localparam IDLE = 2'b00`)
# also marks a region as Verilog — it carries the enum/param content the
# extractor wants, and a param-only block has no input/output so it can still
# never inject a phantom PORT. Prose ("the parameter is configurable") lacks the
# `<name> =` form and does not match.
_VERILOG_PARAM_DECL = re.compile(
    r'\b(?:localparam|parameter)\b\s+(?:\w+\s+)?\w+\s*=', re.I)


def _looks_like_verilog(region: str) -> bool:
    return bool(_VERILOG_MODULE_HDR.search(region)
                or _VERILOG_PORT_DECL.search(region)
                or _VERILOG_PARAM_DECL.search(region))


def _verilog_region_spans(text: str) -> List[tuple]:
    """The `(start, end)` offsets into `text` of every region that actually IS
    Verilog. Split out of `_verilog_regions` for vibe-ic#2060 so a caller can
    quote the SOURCE LINE a port was read from — evidence a reader can check
    against the input document, which a joined region string cannot give."""
    # vibe-ic#731 — the module-span scan runs over BLANKED text: a prose
    # sentence inside a `//` comment ("// module foo … endmodule") otherwise
    # opens a span whose content is then read for ports. Blanked, not deleted,
    # because the spans returned here index the CALLER's `text`; a delete-style
    # strip would shift every offset and `_source_line` would quote the wrong
    # line, which is a worse and quieter defect than the one being closed.
    scanned = strip_hdl_comments_and_strings(text)
    cand = [(m.start(1), m.end(1)) for m in _FENCE.finditer(text)]
    cand += [m.span() for m in _MODULE_SPAN.finditer(scanned)]
    # Only KEEP regions whose content is actually Verilog (see above) — a fence
    # holding logs/pseudo-code or a prose module…endmodule span is dropped, so a
    # non-Verilog region can never inject a phantom port.
    return [(a, b) for a, b in cand if _looks_like_verilog(text[a:b])]


def _verilog_regions(text: str) -> str:
    # strip comments so an inline `// the reset …` comment after a port decl
    # cannot scrape its first word as a phantom port.
    return strip_comments(
        "\n".join(text[a:b] for a, b in _verilog_region_spans(text)))


#: vibe-ic#2060 — the strategy tags a consumer records so a published port can
#: be traced back to the SHAPE it was read from. One spelling, in the module
#: that owns the grammar, so the two Phase-1 front doors cannot drift apart on
#: the label the way they drifted on the top-module status vocabulary (#2052).
CODE_REGION_PORT_STRATEGY = "verilog_code_region_port_decl_issue2060"
SIGNAL_TABLE_PORT_STRATEGY = "markdown_signal_table_port_row_issue2060"
STRUCTURED_SPEC_PORT_STRATEGY = "structured_spec_ports_mapping"

#: The direction values a structured spec may write. Verilog's own keywords
#: only: a mapping whose `dir` says anything else is not a port declaration.
_SPEC_DIRECTIONS = {"input": "input", "output": "output", "inout": "inout"}


def _structured_spec_port_entries(value) -> List[tuple]:
    """`(name, fields)` pairs from one `ports:` value, in document order.

    Two shapes, both a direct transcription of a port list: a mapping
    `name: {dir, width}` and a list of `{name, dir, width}` records.
    """
    if isinstance(value, dict):
        return [(k, v) for k, v in value.items() if isinstance(v, dict)]
    if isinstance(value, list):
        return [(v.get("name"), v) for v in value if isinstance(v, dict)]
    return []


def extract_structured_spec_ports(text: str) -> List[Dict[str, Any]]:
    """Every port a STRUCTURED spec (a YAML/JSON document) declares under a
    `ports:` key, each carrying the source line it was read from.

    A Shape-C `spec.yaml` states its interface as data (`L9: {ports: {a: {dir:
    input, width: 1}}}`), which neither the code-region nor the table grammar
    reads, so the Phase-1 front doors published ZERO ports for a spec that
    declares five, and the sufficiency gate — which does see them in the
    input — halted on an extraction gap. GRAMMAR, as for the other shapes: the
    document must parse to a mapping, the entry must sit under a key named
    `ports`, and its `dir`/`direction` must be a Verilog direction keyword.
    Prose parses to a string and yields nothing. A `width` that is not an
    integer is `WIDTH_UNKNOWN`, never a made-up 1.
    """
    try:
        import yaml
        doc = yaml.safe_load(text)
    except Exception:
        return []
    if not isinstance(doc, dict):
        return []
    lines = text.splitlines()
    out: List[Dict[str, Any]] = []
    seen: set = set()
    stack = [doc]
    while stack:
        node = stack.pop(0)
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if str(key).strip().lower() != "ports":
                stack.append(value)
                continue
            for name, fields in _structured_spec_port_entries(value):
                name = str(name or "").strip()
                raw_dir = fields.get("dir", fields.get("direction"))
                direction = _SPEC_DIRECTIONS.get(str(raw_dir or "").strip().lower())
                if not re.fullmatch(r"[A-Za-z_]\w*", name) or not direction:
                    continue
                if name in seen:
                    continue
                seen.add(name)
                width = fields.get("width")
                if isinstance(width, bool) or not isinstance(width, (int, str)) \
                        or not str(width).strip().isdigit():
                    width = WIDTH_UNKNOWN
                else:
                    width = int(width)
                name_rx = re.compile(r"^\s*(?:-\s*)?(?:name\s*:\s*)?['\"]?%s['\"]?\s*(?::|,|}|$)"
                                     % re.escape(name))
                line = next((ln.strip() for ln in lines if name_rx.match(ln)), "")
                out.append({"name": name, "dir": direction, "width": width,
                            "width_cell": "",
                            "source": "structured_spec_ports",
                            "source_line": line,
                            "description": line or None,
                            "extraction_strategy": STRUCTURED_SPEC_PORT_STRATEGY})
    return out


def _source_line(text: str, offset: int) -> str:
    """The whole line of `text` that `offset` falls on, stripped."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


#: A width cell states a width only when it states a NUMBER. `NUM_INTERRUPTS`,
#: `$clog2(NUM_INTERRUPTS)` and `NUM_INTERRUPTS x ADDR_WIDTH` are real width
#: cells from one real design input and none of them is 1.
_INT_WIDTH_CELL = re.compile(r'^\s*(\d+)\s*(?:[- ]?bits?)?\s*$', re.I)
#: A width cell that STATES a number without being only that number:
#: `24-bit (`[23:0]`)` is a real cell from a real interface table and it
#: declares 24. Measured: returning WIDTH_UNKNOWN for it loses a width the
#: document gives, which is the same failure as inventing one, in the other
#: direction. `N-bit (`[DEPTH-1:0]`)` matches NEITHER and stays UNKNOWN, which
#: is the honest answer for a symbolic bound.
_LEADING_BIT_COUNT = re.compile(r'^\s*(\d+)\s*[- ]?bits?\b', re.I)
_EMBEDDED_RANGE = re.compile(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]')
#: Description-column header vocabulary. `_specrtl_common` defines the name /
#: direction / width header vocabularies (a port table is identified by the
#: first two); it has no description column because `Port` has no description
#: field. This is the only cell this module needs that it does not.
_DESC_HDR = re.compile(r'^\s*(desc|description|comment|notes?|function|'
                       r'meaning|purpose)\s*$', re.I)
_BRACKET_WIDTH_CELL = re.compile(r'^\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*$')


def _signal_table_rows(text: str) -> Dict[str, Dict[str, Any]]:
    """Row CONTEXT for every port a markdown signal table states, by name:
    the row line itself, the raw width cell and the description cell.

    `_parse_md_table_ports` stays the authority on WHICH ports a table
    declares — this walker adds no port and drops none; it only recovers the
    cells that the `Port` record cannot carry. It is here because
    `_specrtl_common.Port.width` is 1 for a width cell it could not parse, so
    forwarding that number would publish `width: 1` for a port the document
    declares as `NUM_INTERRUPTS` wide. A width the document does not state is
    WIDTH_UNKNOWN, exactly as `parse_verilog_ports` already documents for a
    symbolic packed dimension — never a literal 1.
    """
    out: Dict[str, Dict[str, Any]] = {}
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n - 1:
        header = _split_md_row(lines[i])
        delim = _split_md_row(lines[i + 1])
        if (lines[i].count("|") < 2 or not _is_md_delim_row(delim)
                or len(delim) != len(header)):
            i += 1
            continue
        name_col = next((k for k, h in enumerate(header)
                         if _NAME_HDR.match(h)), None)
        dir_col = next((k for k, h in enumerate(header)
                        if _DIR_HDR.match(h)), None)
        if name_col is None or dir_col is None:
            i += 1
            continue
        width_col = next((k for k, h in enumerate(header)
                          if _WIDTH_HDR.match(h)), None)
        desc_col = next((k for k, h in enumerate(header)
                         if _DESC_HDR.match(h)), None)
        j = i + 2
        while j < n and lines[j].count("|") >= 2:
            cells = _split_md_row(lines[j])
            if len(cells) == len(header):
                nm = _strip_md_emphasis(cells[name_col])
                if nm and nm not in out:
                    _wcell = (cells[width_col].strip()
                              if width_col is not None
                              and width_col < len(cells) else "")
                    # DOES THE CELL DENY THE WIDTH IT CONTAINS? (#712, #2060)
                    #
                    # MEASURED on this reader before the consult existed:
                    #
                    #     `not [7:0]`           -> width 8
                    #     `no longer [7:0]`     -> width 8
                    #     `removed, was [7:0]`  -> width 8
                    #
                    # `_EMBEDDED_RANGE` searches ANYWHERE in the cell, so a row
                    # that retires a range republished it as a declaration —
                    # #711's `die_area_budget_um` ("has NO meaning here and is
                    # REMOVED, not translated" re-declared that exact
                    # rectangle) one field over. `not stated` / `no width` /
                    # `N/A` already came back WIDTH_UNKNOWN, but only because
                    # they carry no digits: nothing asked.
                    #
                    # The question is asked HERE, at the site that reads the
                    # cell, with the shared vocabulary — imported, never copied,
                    # because three private copies of it is how #712 happened.
                    # The denial WORD is recorded, not a bare flag: a refusal
                    # that names its evidence is checkable.
                    #
                    # Bracketed qualifiers are blanked by `is_denied` (#711), so
                    # a legitimate `1 (not used)` still reads as width 1.
                    _wdenial = _prose_is_denied(_wcell) if _wcell else None
                    out[nm] = {
                        "row": lines[j].strip(),
                        "width_cell": _wcell,
                        "width_cell_denial": _wdenial,
                        "description": (_strip_md_emphasis(cells[desc_col])
                                        if desc_col is not None
                                        and desc_col < len(cells) else ""),
                    }
            j += 1
        i = j
    return out


def _stated_width(cell: str) -> int:
    """The width a table cell STATES.

    THREE answers, not two, and conflating the last two is a regression rather
    than a tightening — measured on 162 port widths across 41 real design-input
    documents before this distinction existed:

      a NUMBER (`8`, `8 bits`, `[7:0]`)  -> that width
      a cell that is NOT a number (`NUM_INTERRUPTS`, `$clog2(N)`, `N x M`)
                                         -> WIDTH_UNKNOWN; the document states
                                            a width and this reader cannot
                                            resolve it, so it must not invent 1
      NO width cell at all (the table has no Width column, or the row has no
      cell for it)                       -> 1, a genuine 1-bit scalar

    The last case is not ignorance, it is a DECLARATION: a port with no packed
    dimension is 1 bit, which is the contract `parse_verilog_ports` states in
    this same package ("no packed dimension -> genuine 1-bit scalar"). Reading
    `| clk | input |` as an unknown width would lose a fact the document does
    give, and `clk`/`reset_n`/`cs` in a two-column signal table are exactly the
    rows that shape occurs on.
    """
    if not (cell or "").strip():
        return 1
    # A DENIED WIDTH IS NOT A WIDTH. The cell states one and takes it back, so
    # the document does not give a width this reader may publish — that is
    # WIDTH_UNKNOWN, the same answer a symbolic dimension gets, and never the
    # number standing inside the denial. See the measurement in
    # `_signal_table_rows`. An EMPTY cell is untouched above: no cell is a
    # declaration of a 1-bit scalar, not a denial of anything.
    if _prose_is_denied(cell):
        return WIDTH_UNKNOWN
    m = _INT_WIDTH_CELL.match(cell)
    if m:
        return int(m.group(1))
    m = _BRACKET_WIDTH_CELL.match(cell)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    m = _LEADING_BIT_COUNT.match(cell)
    if m:
        return int(m.group(1))
    m = _EMBEDDED_RANGE.search(cell)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    return WIDTH_UNKNOWN


def extract_code_block_ports(text: str) -> List[Dict[str, Any]]:
    """Every port a document DECLARES in a Verilog/SystemVerilog code region or
    in a markdown signal table (or, see `extract_structured_spec_ports`, under
    a structured spec's `ports:` key), each carrying the source line it was
    read from.

    vibe-ic#2060. GRAMMAR, never a token match: an entry needs a DIRECTION
    keyword (`input`/`output`/`inout`), an optional packed width, and an
    identifier, standing where Verilog declares a port — inside a region that
    `_looks_like_verilog` accepts, with comments and subprogram bodies blanked
    — or standing in a table row under a header that carries BOTH a name column
    and a DIRECTION column. A prose sentence ("the input signal is sampled") is
    in neither position and yields nothing; a waveform table
    (`| Clock Cycle | clk | rst_n | data_in |`) has no direction column and
    yields nothing.

    Returns entries `{name, dir, width, source, source_line,
    extraction_strategy}`; `width` is the integer width
    `parse_verilog_ports` derives (`_specrtl_common.WIDTH_UNKNOWN` when a
    symbolic bound cannot be resolved), never a made-up 1.
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()
    # Tables first: they are precise on the whole text and are the shape a spec
    # writes its interface in when it writes one at all, so on a name both
    # shapes carry, the table's entry is the one kept.
    table, _notes = _parse_md_table_ports(text, union=True)
    rows = _signal_table_rows(text)
    for prt in table:
        if prt.name in seen:
            continue
        seen.add(prt.name)
        ctx = rows.get(prt.name, {})
        out.append({"name": prt.name, "dir": prt.direction,
                    "width": _stated_width(ctx.get("width_cell", "")),
                    "width_cell": ctx.get("width_cell", ""),
                    "source": "markdown_signal_table",
                    "source_line": ctx.get("row", ""),
                    "description": ctx.get("description") or None,
                    "extraction_strategy": SIGNAL_TABLE_PORT_STRATEGY})
    for a, b in _verilog_region_spans(text):
        raw = text[a:b]
        # Both blank in place (comment / subprogram characters become spaces and
        # newlines), so an offset in `clean` is the SAME offset in `raw` and the
        # quoted source line is the document's own line, comment included.
        clean = _strip_subprograms(strip_comments(raw))
        # The region's OWN parameters, so `[DATA_WIDTH-1:0]` resolves to a real
        # width exactly as it does when `parse_verilog_ports` is handed the
        # whole region — matching one declaration at a time must not cost the
        # width that only the region can supply.
        params = _parse_module_params(clean)
        for m in _PORT_DECL_SPAN.finditer(clean):
            names = [nm.strip() for nm in re.split(r"\s*,\s*", m.group(3))]
            for prt in parse_verilog_ports(m.group(0), params):
                if prt.name in seen or prt.name not in names:
                    continue
                seen.add(prt.name)
                line = _source_line(raw, m.start())
                out.append({
                    "name": prt.name, "dir": prt.direction, "width": prt.width,
                    "width_cell": "",
                    "source": "verilog_code_region",
                    "source_line": line,
                    # the declaration IS the best description this shape has,
                    # and quoting it is what makes the port checkable against
                    # the document that stated it.
                    "description": line,
                    "extraction_strategy": CODE_REGION_PORT_STRATEGY})
    # A structured spec states its ports as data. Last, so on a name a table or
    # a code region also declares, the existing entry and its provenance stand.
    for entry in extract_structured_spec_ports(text):
        if entry["name"] not in seen:
            seen.add(entry["name"])
            out.append(entry)
    return out


def extract_ports(prompt: str) -> List[Dict]:
    """Union of markdown-interface-table ports (precise on the whole text) and
    inline-Verilog-declared ports — the latter parsed ONLY from real Verilog code
    regions so a prose sentence can never inject a phantom port."""
    # vibe-ic#2060 — ONE implementation of the code-region + signal-table
    # grammar, in `extract_code_block_ports`, which the DOCS front door also
    # calls. Before this, each door ran its own regex over its own idea of a
    # code region and they disagreed: the docs door's `_RE_VERILOG_PORT_DECL`
    # dropped every declaration carrying a symbolic width (`[WIDTH-1:0]`) or a
    # trailing `// comment`, which is most of them, and this one read whole
    # documents as Verilog. Same file: same answer.
    table_inline = [{"name": e["name"], "dir": e["dir"], "width": e["width"]}
                    for e in extract_code_block_ports(prompt)]
    if table_inline:
        return table_inline
    # only fall back to the structured-prose signal-definition list when no table
    # / code interface was found (tables/code are higher-confidence).
    #
    # #czl9prompt — the fallback tier is a UNION of the two prose grammars, not
    # one of them. `extract_prose_ports` is HEADING-anchored (`Inputs:` then
    # `name:` bullets); `extract_inline_direction_bullet_ports` reads a bullet
    # that carries its own direction keyword (`- input clk`). A plain-language
    # description that lists its pins one per bullet under no heading matches
    # only the second, and before this union THIS function returned [] on it —
    # which is what made the prompt front door halt on a port-declaring input
    # while the docs front door, which called the second grammar directly, read
    # all five. Order: heading-anchored first, then the bullet grammar, so the
    # dedup keeps the heading form's entry on a name both produce.
    prose = extract_prose_ports(prompt)
    fallback = [Port(p["name"], p["dir"], p["width"]) for p in prose]
    for e in extract_inline_direction_bullet_ports(prompt):
        w = e.get("width")
        try:
            width = int(w) if w is not None else 1
        except (TypeError, ValueError):
            width = 1
        fallback.append(Port(e["name"], e["mode"], width))
    return _dedup_ports(fallback)


_PROSE_MODULE_NAME = re.compile(
    r'(?im)^[ \t]*(?:#{1,6}[ \t]*)?Module[ \t]+name[ \t]*:[ \t]*'
    r'(?:`?([A-Za-z_]\w*)`?[ \t]*$|\n[ \t]*`?([A-Za-z_]\w*)`?[ \t]*$)')


def _prose_module_scopes(prompt: str) -> List[tuple]:
    """Lexical module-name sections, never a corpus-wide parameter namespace."""
    headers = list(_PROSE_MODULE_NAME.finditer(prompt))
    if not headers:
        return [(0, len(prompt), None)]
    return [(m.start(), headers[i + 1].start() if i + 1 < len(headers)
             else len(prompt), m.group(1) or m.group(2))
            for i, m in enumerate(headers)]


def extract_prose_parameters(prompt: str) -> List[Dict]:
    """Declared prose parameters, including declarations with NO default.

    Only an explicit parameter heading admits rows. Descriptive colon rows do
    not acquire a guessed numeric value. Module-name sections retain ownership.
    """
    rows = []
    for lo, hi, owner in _prose_module_scopes(prompt):
        active = False
        for line in prompt[lo:hi].splitlines():
            core = re.sub(r'[^a-z ]', '', line.strip().lower()).strip()
            if core in ('parameter', 'parameters', 'input parameters',
                        'parameterized values'):
                active = True
                continue
            if not active or not line.strip():
                continue
            match = re.fullmatch(
                r'\s*(?:[-*]\s*)?`?([A-Za-z_]\w*)`?\s*(=|:)\s*(.+?)\s*', line)
            if not match:
                active = False
                continue
            name, sep, value = match.groups()
            # An unindented named heading is not a parameter description.
            if sep == ':' and not line[:1].isspace() and not line.lstrip().startswith(('-', '*')):
                active = False
                continue
            row = {'name': name, 'default': value.rstrip('; ,').strip() if sep == '=' else None,
                   'declaration_kind': 'parameter',
                   'extraction_strategy': 'headed_prose_parameter_declaration',
                   'literal': line.strip()}
            if sep == ':':
                row['description'] = value
            if owner is not None:
                row['module_owner'] = owner
            rows.append(row)
    # A descriptive declaration and a separately stated default are one
    # parameter, not contradictory defaults. Two different stated values stay
    # separate so the owning producer can refuse the real conflict.
    merged = []
    for row in rows:
        prior = next((p for p in merged if (p.get('module_owner'), p['name']) ==
                      (row.get('module_owner'), row['name'])), None)
        if prior is not None and (prior.get('default') is None or row.get('default') is None):
            if prior.get('default') is None and row.get('default') is not None:
                prior.update(row)
            elif row.get('description'):
                prior.setdefault('description', row['description'])
        else:
            merged.append(row)
    return merged


def extract_params(prompt: str) -> List[Dict]:
    out: Dict[str, str] = {}
    for m in _PARAM_DECL.finditer(prompt):
        out.setdefault(m.group(1), m.group(2).strip())
    # A prose parameter list states the same defaults without repeating the
    # Verilog keyword: `Parameter:` followed by `WIDTH = 8`. Only this explicit
    # section admits bare assignments; implementation assignments are not
    # parameter declarations.
    for row in extract_prose_parameters(prompt):
        out.setdefault(row['name'], row['default'])
    # markdown parameter table: a 2+-column row whose 1st cell is an identifier
    # and 2nd is a pure integer/expr default (and the row is NOT a port row — a
    # port row's 2nd cell is a direction in/out/input/output).
    for line in prompt.splitlines():
        m = _MD_ROW.match(line)
        if not m:
            continue
        cells = [c.strip().strip('`') for c in m.group(1).split('|')]
        if len(cells) < 2:
            continue
        name, default = cells[0], cells[1]
        if (re.fullmatch(r'[A-Za-z_]\w*', name)
                and re.fullmatch(r'[-+]?\d[\w\'\".]*', default)
                and name not in out):
            out[name] = default
    return [{"name": k, "default": v} for k, v in out.items()]


# Register-map table column vocabulary. A regmap table is distinguished from a
# port table by an OFFSET/ADDRESS column (a port table has a direction column).
_REGNAME_HDR = re.compile(r'^\s*(register|reg|field|name)\s*$', re.I)
_OFFSET_HDR = re.compile(r'^\s*(offset|address|addr|adr|location)\s*$', re.I)
_ACCESS_HDR = re.compile(r'^\s*(access|type|mode|r\s*/\s*w|rw|permission)\s*$', re.I)
from _specrtl_common import (  # noqa: E402
    _split_md_row, _is_md_delim_row, _strip_md_emphasis,
    _NAME_HDR, _DIR_HDR, _WIDTH_HDR)


#: `aes.[`CTRL_SHADOWED`](#ctrl_shadowed)` -> `CTRL_SHADOWED`.
#:
#: vibe-ic#593. A register-tool summary table writes the name as a markdown LINK
#: under a block prefix, and the identifier match rejected the whole cell — so
#: the summary table contributed NOTHING and the 28 registers that did come out
#: were read from a different table elsewhere in the document. The ones the
#: summary uniquely carries are exactly the ones with FIELDS: CTRL_SHADOWED,
#: CTRL_AUX_SHADOWED, CTRL_GCM_SHADOWED, TRIGGER, STATUS. Measured on the
#: shipped OpenTitan AES register document.
#:
#: Markdown link grammar plus an optional `<block>.` qualifier; no vendor or
#: design token. The identifier match below is unchanged, so a cell that is not
#: a name after this is still rejected.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _regmap_name_cell(cell: str) -> str:
    """The register name a summary-table Name cell states."""
    txt = _strip_md_emphasis(cell)
    m = _MD_LINK_RE.search(txt)
    if m:
        txt = _strip_md_emphasis(m.group(1))
    # `aes.CTRL_SHADOWED` -> `CTRL_SHADOWED`; the block qualifier names the IP,
    # not the register, and every row in a table carries the same one.
    if "." in txt:
        txt = txt.rsplit(".", 1)[-1]
    return txt.strip()


def extract_regmap(prompt: str) -> List[Dict]:
    """Parse a markdown REGISTER-MAP table: a table carrying a name column AND an
    OFFSET/ADDRESS column (the offset is what makes it a regmap, not a port list).
    Returns [{name, offset, width?, access?}]."""
    lines = prompt.splitlines()
    out: List[Dict] = []
    seen = set()
    i, n = 0, len(lines)
    while i < n - 1:
        if lines[i].count('|') < 2:
            i += 1
            continue
        header = [_strip_md_emphasis(h) for h in _split_md_row(lines[i])]
        delim = _split_md_row(lines[i + 1]) if i + 1 < n else []
        if not _is_md_delim_row(delim) or len(delim) != len(header):
            i += 1
            continue
        name_c = next((k for k, h in enumerate(header) if _REGNAME_HDR.match(h)), None)
        off_c = next((k for k, h in enumerate(header) if _OFFSET_HDR.match(h)), None)
        if name_c is None or off_c is None:
            i += 1
            continue
        acc_c = next((k for k, h in enumerate(header) if _ACCESS_HDR.match(h)), None)
        wid_c = next((k for k, h in enumerate(header)
                      if re.match(r'^\s*(width|bits?|size|len(?:gth)?|bit\s*width)\s*$',
                                  h, re.I)), None)
        j = i + 2
        while j < n:
            cells = _split_md_row(lines[j])
            if not cells or _is_md_delim_row(cells) or all(c == '' for c in cells):
                break
            if len(cells) <= max(name_c, off_c):
                j += 1
                continue
            name = _regmap_name_cell(cells[name_c])
            off = _strip_md_emphasis(cells[off_c])
            if (not re.fullmatch(r'[A-Za-z_]\w*', name)
                    or not re.search(r'0x[0-9a-fA-F]+|\d', off)):
                j += 1
                continue
            if name in seen:
                j += 1
                continue
            seen.add(name)
            rec = {"name": name, "offset": off}
            if acc_c is not None and len(cells) > acc_c and cells[acc_c]:
                rec["access"] = _strip_md_emphasis(cells[acc_c])
            if wid_c is not None and len(cells) > wid_c:
                w = re.search(r'\d+', cells[wid_c])
                if w:
                    rec["width"] = int(w.group(0))
            out.append(rec)
            j += 1
        i = j if j > i else i + 1
    _attach_regmap_fields(prompt, out)
    return out


#: `## CTRL_SHADOWED` — the per-register section heading a register-tool doc
#: emits above that register's own field description.
#: The LEVEL is captured because a register's own field diagram lives in a
#: SUBSECTION (`### Fields`) of it. Ending the register's slice at the next
#: heading of any depth cuts the diagram off — measured: `## CTRL_SHADOWED`
#: ended at `### Fields` and the wavejson fence, the only thing worth reading,
#: fell outside every slice. The slice ends at the next heading of the SAME or
#: SHALLOWER level.
_REG_SECTION_RE = re.compile(
    r"^(?P<hashes>##+)\s+(?:\w+\.)?[`\[]*([A-Za-z_]\w*)[`\]]*\s*$",
    re.MULTILINE)
#: The wavejson fence a register tool writes under `### Fields`. wavedrom /
#: wavejson is a general register-diagram format, not a vendor token.
_WAVEJSON_FENCE_RE = re.compile(r"```\s*wavejson\s*\n(.*?)\n```", re.S)


def extract_register_fields(section_text: str):
    """``[{name, lsb, width, msb, access?}]`` from a wavejson register diagram.

    vibe-ic#593. `extract_regmap` returns a FLAT `{name, offset, width}` per
    register and emits no `fields[]`, so every field-level name a document
    declares — and every `<REG>_<FIELD>_MASK` / `_OFFSET` accessor macro built
    on it — lands in no L layer.

    The fields are already MACHINE-READABLE in these documents: the register
    tool writes them as a `wavejson` diagram whose `reg` array is JSON, in bit
    order, LSB first. An unnamed entry is reserved padding — it is NOT emitted
    as a field, but its width still advances the bit position, because dropping
    it would shift every field above it.

    Reads the document; invents nothing. A fence that does not parse, or whose
    `reg` is not a list, yields no fields rather than a guess.
    """
    m = _WAVEJSON_FENCE_RE.search(section_text)
    if not m:
        return []
    try:
        obj = json.loads(m.group(1))
    except (ValueError, TypeError):
        return []
    reg = obj.get("reg") if isinstance(obj, dict) else None
    if not isinstance(reg, list):
        return []
    fields = []
    lsb = 0
    for ent in reg:
        if not isinstance(ent, dict):
            return []
        try:
            width = int(ent.get("bits"))
        except (TypeError, ValueError):
            return []
        if width <= 0:
            return []
        name = ent.get("name")
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z_]\w*", name.strip()):
            rec = {"name": name.strip(), "lsb": lsb, "width": width,
                   "msb": lsb + width - 1}
            attr = ent.get("attr")
            if isinstance(attr, list) and attr and isinstance(attr[0], str):
                rec["access"] = attr[0]
            elif isinstance(attr, str) and attr:
                rec["access"] = attr
            fields.append(rec)
        lsb += width
    return fields


def _attach_regmap_fields(prompt: str, regs):
    """Attach `fields[]` to each register that has a wavejson section."""
    if not regs:
        return
    by_name = {r["name"]: r for r in regs if r.get("name")}
    if not by_name:
        return
    marks = [(m.start(), m.group(2), len(m.group("hashes")))
             for m in _REG_SECTION_RE.finditer(prompt)]
    for k, (pos, name, level) in enumerate(marks):
        reg = by_name.get(name)
        if reg is None or reg.get("fields"):
            continue
        end = len(prompt)
        for pos2, _n2, lvl2 in marks[k + 1:]:
            if lvl2 <= level:
                end = pos2
                break
        got = extract_register_fields(prompt[pos:end])
        if got:
            reg["fields"] = got


# Prose signal-DEFINITION bullet: `- [**|`]?[ [w-1:0] ]?NAME[`|**]? : description`.
# The NAME must be IMMEDIATELY followed by `:` (a definition), which excludes a
# prose REFERENCE bullet like "- `a` and `b` are toggle signals" (name followed by
# a word, not a colon). Optional leading width `[3:0]` / `[WIDTH-1:0]`.
_PROSE_SIG = re.compile(
    r'^\s*[-*]\s*\**\s*(?:\[\s*([^\]]*?)\s*\]\s*)?`?\**\s*'
    r'([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*'
    r'(?:\[\s*([^\]]*?)\s*\])?\**`?\**\s*:',
)
# The same definition shape with the bullet made optional, used ONLY while a
# port-section header is in force (see `extract_prose_ports`). Groups match
# `_PROSE_SIG`'s: (leading-range, name, trailing-range).
_PROSE_SIG_UNBULLETED = re.compile(
    r'^[ \t]*(?:\[\s*([^\]]*?)\s*\]\s*)?`?\**\s*'
    r'([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*'
    r'(?:\[\s*([^\]]*?)\s*\])?\**`?\**\s*'
    # an optional parenthesised type/direction group: `clk (input)`,
    # `a (input [31:0])`, `z (output reg [31:0])`. It is where a spec that
    # annotates its own list puts BOTH the direction and the range.
    r'(?:\(\s*([^)]*?)\s*\)\s*)?:',
)

#: a declared range inside that parenthetical / anywhere a port is dimensioned.
_RANGE = re.compile(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]')
#: a bare index of a named signal, `q[7]` — the design's own lower bound on it.
_INDEXED = r'(?<![A-Za-z0-9_])%s\s*\[\s*(\d+)\s*\]'
#: a dimensioned declaration of a named signal anywhere in the prompt,
#: `reg [7:0] q`, `input [31:0] a` — the width the design itself states.
_DECLARED = r'\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(?:\w+\s+)*%s(?![A-Za-z0-9_])'
_INPUTS_HDR = re.compile(r'\binputs?\b', re.I)
_OUTPUTS_HDR = re.compile(r'\boutputs?\b', re.I)
# TitleCase English labels that head a descriptor bullet, never a real signal name.
_PROSE_STOP = frozenset((
    "inputs", "outputs", "input", "output", "note", "notes", "step", "clock",
    "reset", "signal", "signals", "data", "description", "functionality",
    "behavior", "behaviour", "overview", "constraints", "interface", "ports",
    "parameters", "parameter", "registers", "example", "examples", "summary",
    "default", "state", "states", "operation", "functionality:", "general",
))


# The stop-list above rejects DESCRIPTOR bullets, and it pays for that by also
# rejecting the handful of English words that are real signal names — `clock`,
# `reset`, `data`, `state`, `signal`. Under an explicit `Input ports:` heading
# that trade is wrong: `reset: Reset signal to initialize the counter` IS the
# port, and dropping it publishes an interface that is missing a pin. Inside a
# declared port section only META words that denote headings or annotations
# are rejected. Outside that section TitleCase descriptors remain excluded.
_PROSE_STOP_META = frozenset((
    "inputs", "outputs", "input", "output", "note", "notes", "description",
    "functionality", "behavior", "behaviour", "overview", "constraints",
    "interface", "ports", "parameters", "parameter", "registers", "example",
    "examples", "summary", "general", "operation", "functionality:",
))


def _width_from(expr: Optional[str], params: Optional[Dict[str, int]] = None) -> int:
    if not expr:
        return 1
    if expr.count(':') != 1:
        return WIDTH_UNKNOWN
    hi, lo = (_safe_eval_int(part, params or {}) for part in expr.split(':'))
    return abs(hi - lo) + 1 if hi is not None and lo is not None else WIDTH_UNKNOWN


def _prose_port_dimension(match, desc: str, name: str, prompt: str,
                          params: Dict[str, int]) -> Dict[str, Any]:
    """Read an explicitly stated dimension, retaining unresolved expressions."""
    rng = match.group(1) or match.group(3)
    paren = match.group(4) if match.lastindex and match.lastindex >= 4 else None
    if not rng and paren:
        stated = re.search(r'\[([^\]]+)\]', paren)
        if stated:
            rng = stated.group(1)
    if not rng:
        stated = re.search(r'\bwidth\s*\[([^\]]+)\]', desc, re.I)
        if stated:
            rng = stated.group(1)
    if rng and ':' in rng:
        width = _width_from(rng, params)
        if width == WIDTH_UNKNOWN:
            return {"width": WIDTH_UNKNOWN, "width_symbolic": f"[{rng}]"}
        hi, lo = (_safe_eval_int(part, params) for part in rng.split(':'))
        return {"width": width, "msb": hi, "lsb": lo}
    count = re.search(r'\b(?:data\s+)?width\s+of\s+(.+?)\s+bits?\b', desc, re.I)
    if count:
        expr = re.sub(r'["`]', '', count.group(1)).strip()
        width = _safe_eval_int(expr, params)
        if width is not None and width > 0:
            return {'width': width}
        return {'width': WIDTH_UNKNOWN, 'width_symbolic': f'[({expr})-1:0]'}
    bit_count = re.search(r'\b(\d+)\s*-?\s*bits?\b', desc, re.I)
    if bit_count:
        return {"width": int(bit_count.group(1))}
    # Preserve the existing input-derived lower-bound recovery for a scalar
    # definition whose declaration or indexed uses elsewhere state its width.
    declared = re.search(_DECLARED % re.escape(name), prompt)
    if declared:
        hi, lo = int(declared.group(1)), int(declared.group(2))
        return {"width": abs(hi - lo) + 1, "msb": hi, "lsb": lo}
    indexed = re.findall(_INDEXED % re.escape(name), prompt)
    if indexed:
        hi = max(int(value) for value in indexed)
        return {"width": hi + 1, "msb": hi, "lsb": 0}
    if re.search(r'\baddress\s+for\s+(?:the\s+)?(?:read|write|memory)\b|'
                 r'\bdata\s+(?:to\s+be\s+written\s+to|read\s+from)\s+'
                 r'(?:the\s+)?(?:ram|memory)\b|\b(?:data|address)\s+(?:bus|vector)\b',
                 desc, re.I):
        return {'width': WIDTH_UNKNOWN, 'width_unresolved': {
            'reason': 'bus_width_not_stated', 'source': desc.strip()}}
    return {"width": 1}


def extract_prose_ports(prompt: str) -> List[Dict]:
    """Deterministic ports from a STRUCTURED-PROSE signal-definition list — the
    `**Inputs**:` / `**Outputs**:` sectioned bullet form common when a spec has no
    interface table. Direction comes from the section header or an `N-bit
    input/output` phrase in the description; precision-anchored on the
    NAME-immediately-followed-by-colon definition shape (a prose reference to a
    signal does not match)."""
    out: List[Dict] = []
    seen = set()
    scoped = []
    for lo, hi, owner in _prose_module_scopes(prompt):
        body = prompt[lo:hi]
        # A sibling HDL module's defaults cannot dimension a prose interface.
        defaults = extract_prose_parameters(body)
        if not _VERILOG_MODULE_HDR.search(body):
            defaults += [{'name': m.group(1), 'default': m.group(2).strip()}
                         for m in _PARAM_DECL.finditer(body)]
        raw = {}
        conflicts = set()
        for item in defaults:
            name, value = item['name'], item.get('default')
            if name in raw and raw[name] != value:
                conflicts.add(name)
            raw[name] = value
        params: Dict[str, int] = {}
        for _ in range(len(raw) + 1):
            previous = len(params)
            for name, value in raw.items():
                if name not in params and name not in conflicts and isinstance(value, str):
                    resolved = _safe_eval_int(value, params)
                    if resolved is not None:
                        params[name] = resolved
            if len(params) == previous:
                break
        scoped.append((lo, hi, params))
    section = None  # 'input' | 'output' | 'inout' | None
    after_blank = False
    offset = 0
    for source_line in prompt.splitlines(keepends=True):
        line = source_line.rstrip('\r\n')
        params = next((env for lo, hi, env in scoped if lo <= offset < hi), {})
        offset += len(source_line)
        # a short header line that names Inputs/Outputs sets the section — strip
        # leading bullets (`- `, `* `, `•`), markdown emphasis, numbering and the
        # trailing colon, then match the alphanumeric core.
        core = re.sub(r'[^a-z ]', '', line.strip().lower()).strip()
        if core in ("inputs", "input port", "input ports", "input signal", "input signals", "input",
                    "input interface"):
            section = "input"; after_blank = False; continue
        if core in ("outputs", "output port", "output ports", "output signal", "output signals", "output",
                    "output interface"):
            section = "output"; after_blank = False; continue
        if core in ("inouts", "inout port", "inout ports", "inout signal", "inout signals", "inout",
                    "inout interface"):
            section = "inout"; after_blank = False; continue
        if section is not None and not line.strip():
            after_blank = True
            continue
        m = _PROSE_SIG.match(line)
        if m is None and section is not None:
            # INSIDE a declared port section the definition lines often carry NO
            # bullet at all — `\tclk: Clock signal.`, `out [7:0]: 8-bit output`.
            # The bullet is a markdown habit, not the anchor; the anchor is
            # "a bare identifier, optionally a range, then a colon, on a line
            # under a header that already said these are the ports".
            m = _PROSE_SIG_UNBULLETED.match(line)
            if m is None:
                # The RUN of definition lines IS the list. Anything else — a
                # blank line, the next heading, a sentence — ends it, so a
                # later `Implementation:` paragraph cannot inherit `section`
                # and turn its prose into ports.
                section = None
                after_blank = False
                continue
        if m is not None and section is not None and after_blank:
            desc = line[m.end():]
            # Apply the same blank-boundary rule to both bullet spellings.
            if (not line[:1].isspace() or not
                    (m.group(1) or m.group(3) or m.group(4)
                     or re.search(r'\b(?:input|output|inout)\b', desc, re.I))):
                section = None
                after_blank = False
                continue
        if not m:
            continue
        after_blank = False
        names = re.split(r'\s*,\s*', m.group(2))
        desc = line[m.end():]
        paren = m.group(4) if m.lastindex and m.lastindex >= 4 else None
        if not desc.strip() and not (m.group(1) or m.group(3) or paren):
            # An empty scalar label introduces another section; it does not
            # define a port field that can inherit the previous direction.
            section = None
            continue
        pd = re.search(r'\b(input|output|inout)\b', paren, re.I) if paren else None
        dm = re.search(r'\b(input|output|inout)\b', desc, re.I)
        direction = (pd.group(1).lower() if pd else
                     dm.group(1).lower() if dm else section)
        if direction is None and re.search(r'\b(clock|reset|clk)\b', desc, re.I):
            direction = "input"
        for name in names:
            # An explicit port section already declares the role of each
            # identifier-colon row. Capitalization is not evidence that a
            # scalar is a descriptor; outside such a section keep that guard.
            if name.lower() in (_PROSE_STOP_META if section else _PROSE_STOP):
                continue
            if section is None and re.fullmatch(r'[A-Z][a-z]{2,}', name):
                continue
            if direction is None or name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "dir": direction,
                        **_prose_port_dimension(m, desc, name, prompt, params)})
    return out


# An enumerated constant: a `localparam`/`parameter` NAME = <sized literal>
# (`2'b01`, `8'hAF`, `3'd5`) — the canonical FSM-state / opcode / mode encoding.
# Also a markdown encoding-table row `| NAME | <sized-literal|0x..|int> |`.
# Every `NAME = <sized literal>` pair (the sized literal `2'b01` is the precision
# anchor) — catches comma-separated enums in one `localparam A=.., B=.., C=..`.
_ENUM_DECL = re.compile(
    r'\b([A-Za-z_]\w*)\s*=\s*'
    r"(\d+'[bdhoBDHO][0-9a-fA-FxXzZ_]+)")
_ENUM_VAL = re.compile(r"^(?:\d+'[bdhoBDHO][0-9a-fA-FxXzZ_]+|0x[0-9a-fA-F]+|\d+)$")


def extract_enums(prompt: str) -> List[Dict]:
    """Enumerated constants (FSM states / opcodes / mode encodings): Verilog
    `localparam NAME = <sized literal>` (parsed from code regions to stay precise)
    + markdown encoding-table rows `| NAME | <sized-literal/hex/int> |`."""
    out: List[Dict] = []
    seen = set()
    for m in _ENUM_DECL.finditer(_verilog_regions(prompt)):
        nm, val = m.group(1), m.group(2)
        if nm not in seen:
            seen.add(nm)
            out.append({"name": nm, "value": val})
    # markdown encoding tables: a 2+-col row whose 1st cell is an UPPER/ident name
    # and 2nd cell is a sized-literal / hex / int — only when a sibling header row
    # names an encoding column (state/mode/opcode/encoding/code/value).
    lines = prompt.splitlines()
    for i in range(len(lines) - 1):
        if lines[i].count('|') < 2:
            continue
        hdr = [_strip_md_emphasis(c).lower() for c in _split_md_row(lines[i])]
        if not any(re.search(r'state|mode|opcode|encod|code|value|command', h)
                   for h in hdr):
            continue
        delim = _split_md_row(lines[i + 1])
        if not _is_md_delim_row(delim) or len(delim) != len(hdr):
            continue
        for j in range(i + 2, len(lines)):
            cells = _split_md_row(lines[j])
            if not cells or _is_md_delim_row(cells) or all(c == '' for c in cells):
                break
            if len(cells) < 2:
                continue
            nm = _strip_md_emphasis(cells[0])
            val = _strip_md_emphasis(cells[1])
            if re.fullmatch(r'[A-Za-z_]\w*', nm) and _ENUM_VAL.match(val) \
                    and nm not in seen and nm.lower() not in _PROSE_STOP:
                seen.add(nm)
                out.append({"name": nm, "value": val})
    return out


def extract_reset(prompt: str) -> Dict:
    """Best-effort reset name + polarity from prose / decls (advisory)."""
    names = re.findall(r'\b(rst_n|reset_n|rst|reset|clr|clear|nreset|por)\b',
                       prompt, re.I)
    if not names:
        return {}
    nm = names[0]
    active_low = bool(re.search(r'active[- ]?low|negedge|_n\b|low\b.*reset'
                                r'|reset.*\blow\b', prompt, re.I)
                      or nm.lower().endswith('_n'))
    return {"name": nm, "polarity": "active_low" if active_low else "active_high"}


# ══ #czl9prompt — ONE interface recovery core, called by BOTH front doors ══
#
# These definitions were AUTHORED for the docs front door (#czl9docs) and lived
# inside `phase1_doc_one_shot_runner.py`, where only that door could reach them.
# The PROMPT front door runs a different ingester (`tools/phase1_engine`) and
# already called THIS module for its structural port seed — so on the identical
# input, one door read five ports and the other read zero and halted.
#
# The fix is not a second implementation. The code below is the docs door's own,
# MOVED here unchanged apart from the rename to a public name; the docs door now
# imports it back. One implementation, two callers: a grammar either door learns
# is a grammar both doors know, and neither can drift from the other.

DIRECTIONAL_PORT_STOP = {
    "input", "inputs", "output", "outputs", "inout", "inouts",
    "signal", "signals", "port", "ports", "pin", "pins", "description",
    "parameter", "parameters", "note", "notes", "example", "examples",
    "functionality", "behavior", "behaviour", "overview", "interface",
    "where", "the", "this", "register", "registers", "field", "fields",
    # Step-2.7: attribute/parameter words that are NEVER a top-level I/O port
    # name — a `- Width: configurable` / `- Latency: 3 cycles` colon-bullet
    # under an Inputs:/Outputs: heading describes a CONFIG value, not a pin.
    # (reset / enable / valid / clock / mode are deliberately NOT here — those
    # ARE common real port names.)
    "width", "latency", "throughput", "protocol", "frequency",
    "endianness", "depth", "bandwidth", "resolution", "period", "duty",
    "encoding", "polarity", "format", "size",
}


# v1.17.x — for #czl9docs. A list bullet that carries its OWN direction
# keyword — `- input clk`, `* output cmd_out (4 bits)`, `- inout sda` — is a
# port declaration whose direction is stated by the bullet itself, so it
# needs NO enclosing `Ports:` heading. Both pre-existing bullet extractors
# (`_l1_bullet_port_extract`, `_l1_directional_prose_port_extract`) are
# HEADING-anchored: they open a port block only after a `Ports:` /
# `Inputs:` line. A plain-language design description that opens with one
# sentence and then lists its pins one per bullet matches neither, so its
# entire interface was dropped and L1 asserted `no_pin_table_in_input` —
# a positive claim about an input that does declare ports.
#
# Precision rule (the discriminator against documentation prose such as
# `- Input validation is performed by the host`): after the identifier the
# bullet must END, or continue only with a WIDTH / a separated description
# (`(`, `[`, `:`, `,`, `-`, en/em dash). A bullet that continues with bare
# prose words is a sentence, not a declaration, and never contributes.
#
# Chip-AGNOSTIC: Verilog/SV direction grammar + Markdown/RST list grammar
# only. No chip, vendor, PDK or port-name literal participates.
_RE_L1_INLINE_DIR_BULLET = re.compile(
    r"(?m)^\s*[-*+]\s+`?"
    r"(?P<dir>input|output|inout)\b`?"
    r"(?:\s+(?:wire|reg|logic|signal|port|pin))?"
    r"(?:\s*\[\s*(?P<wpre>[^\]\n]{1,40})\s*\])?"
    r"\s+`?(?P<name>[A-Za-z_][A-Za-z0-9_]{0,40})`?"
    r"(?:\s*\[\s*(?P<wpost>[^\]\n]{1,40})\s*\])?"
    r"`?(?P<rest>[^\n]{0,240})$"
)
# A trailing remainder that is bare prose (starts with a letter/digit that is
# not part of a separator) means the bullet was a SENTENCE.
_RE_L1_INLINE_DIR_SEP = re.compile(r"^\s*(?:[(\[:,;.]|-{1,2}\s|[–—])")
# `(4 bits)` / `(4-bit)` / `4 bits` — a stated width, not a description.
_RE_L1_INLINE_DIR_WIDTH_WORDS = re.compile(
    r"(?i)^\s*\(?\s*(\d{1,5})\s*[- ]?bits?\b\s*(?:wide)?\s*\)?\s*$")


def extract_inline_direction_bullet_ports(text: str) -> List[Dict[str, Any]]:
    """Ports declared as list bullets that carry their own direction keyword,
    with NO enclosing port heading: ``- input clk`` / ``* output cmd_out
    (4 bits)`` / ``- inout [7:0] data``.

    Returns ``[{name, mode, width, description}]``. A bullet contributes ONLY
    when the identifier is followed by end-of-line, a width, or a SEPARATED
    description — a bullet that runs on into bare prose is a sentence and is
    rejected."""
    out: List[Dict[str, Any]] = []
    if not text:
        return out
    for m in _RE_L1_INLINE_DIR_BULLET.finditer(text):
        name = m.group("name")
        # A single-character name (`q`, `d`) is a legitimate port here and is
        # NOT rejected the way the heading-anchored prose extractor rejects it:
        # there, direction came from a heading and a lone letter was as likely
        # to be a stray token; here the bullet's own `input`/`output` keyword
        # is the evidence, so the name does not have to carry it too.
        if not name or name.lower() in DIRECTIONAL_PORT_STOP:
            continue
        rest = (m.group("rest") or "").strip()
        desc = None
        width = None
        wraw = m.group("wpre") or m.group("wpost")
        if rest:
            if not _RE_L1_INLINE_DIR_SEP.match(rest):
                # bare prose continuation — a sentence, not a declaration.
                continue
            body = rest
            if body.startswith("("):
                close = body.find(")")
                paren = body[1:close] if close > 0 else body[1:]
                tail = body[close + 1:] if close > 0 else ""
                wm = _RE_L1_INLINE_DIR_WIDTH_WORDS.match(paren)
                if wm:
                    if wraw is None:
                        width = wm.group(1)
                    body = tail.strip()
                else:
                    desc = paren.strip() or None
                    body = tail.strip()
            if desc is None and body:
                stripped = body.lstrip(" \t:,;.-–—")
                wm = _RE_L1_INLINE_DIR_WIDTH_WORDS.match(stripped)
                if wm:
                    if wraw is None and width is None:
                        width = wm.group(1)
                else:
                    desc = stripped.strip() or None
        if wraw and width is None:
            wraw = wraw.strip()
            if ":" in wraw:
                bw = re.match(r"\s*([^:]+):([^\]]+)\s*$", wraw)
                if bw:
                    try:
                        width = str(abs(int(bw.group(1).strip())
                                        - int(bw.group(2).strip())) + 1)
                    except ValueError:
                        width = None
            elif wraw.isdigit():
                width = wraw
        out.append({"name": name, "mode": m.group("dir").lower(),
                    "width": width, "description": desc})
    return out

# ── #czl9docs — L9's prose channel, which carried nothing ──────────────
#
# `_frame_contract.input_prose_from_json` assembles the prose an L9 carries by
# walking it for the declared prose keys (description / summary / overview /
# notes / …), and `spec_conformance_check` feeds that channel to every
# frame-contract rule. Measured on this base with the flow's own step-2
# invocation, one RTL body violating all three elements:
#
#   L9 as the front door emits it   PASS rc=0, 0 findings
#   the SAME L9 + the input's own
#   interface sentences in `notes`  FAIL rc=1, 2 errors + composition INFO
#
# The L9 emitter never wrote a single prose key, so the channel was empty and
# every prose-derived rule downstream was structurally dormant — a verdict over
# ZERO characters, the same shape as a verdict over zero ports.
#
# L9 already has a PER-PORT prose channel (`top_ports[].description`, cascaded
# from L1 by `_v1_6_463_cascade_l1_descriptions_to_l9`). That channel is
# correctly empty when the input glosses no individual port. What had NO home in
# L9 at all is an interface constraint stated as a SENTENCE ABOUT THE DESIGN
# rather than as a gloss on one pin — "`cmd_out` must be valid in the same clock
# cycle that `frame_done` asserts". This emits those, verbatim, with provenance.
#
# §4.05: reads the extracted INPUT documents only. Nothing is paraphrased,
# summarised or invented — every character is copied from the input, and the
# provenance record names the document and the rule that selected it.
#
# Chip-AGNOSTIC: anchors on the design's OWN declared port names, whatever they
# are; no chip, vendor, protocol or signal-name literal participates.
# Historical compatibility names re-exported by the docs runner. Source prose
# is no longer selected or truncated according to these former budgets.
MAX_INTERFACE_PROSE_BLOCK_CHARS = 600
MAX_INTERFACE_PROSE_TOTAL_CHARS = 4000
# vibe-ic#2060 item 3 (from #2059's measurement) — THIS PATTERN DOES NOT RETURN.
#
#   (?m)\A(?:\s*(?:[-*+]\s+[^\n]*)?\n?)+\Z
#
# The outer `+` quantifies a body that can match the EMPTY string, and `\s*`
# (which spans newlines) competes with `\n?` for every line separator, so on a
# block that FAILS the engine enumerates every way to split the text between
# them. Measured on 8HD-6 over
# `"- item i with some ordinary text" * n + "\n---"` — an ordinary nested
# bullet list closed by a horizontal rule, which is block 4 of a real corpus
# input prompt:
#
#     indent 0:   4 lines 0.5 ms  ->  11 lines 8458 ms   (x4.0 per added line)
#     indent 2:   4 lines 107 ms  ->   6 lines 27234 ms  (x16.0 per added line)
#     indent 4:   4 lines 26267 ms
#
# A 21-line nested list never returns, and NOTHING LOOKS EXPENSIVE: the same
# text without the closing `---` MATCHES, instantly, on the first greedy path.
# `emit_interface_prose` runs this over blocks of a document the caller hands
# it, so that is a hang in the Phase-1 front door.
#
# The answer is the SAME LANGUAGE read by a linear scanner, not a timeout and
# not a size cap: a block is bullet-only when every NON-BLANK line of it is a
# bullet line. A line is a bullet line when a `-`/`*`/`+` marker, after
# optional indent, is followed by whitespace OR by the end of the line — the
# marker is followed by whitespace ON ITS OWN LINE. `---` is not a bullet line:
# the marker is followed by another marker. That is precisely why the real
# block fails, and why it used to fail so expensively.
#
# THE ONE PLACE THE TWO DISAGREE, stated rather than discovered later. In the
# old pattern `\s+` could match the LINE SEPARATOR, so a bare marker alone on a
# line swallowed the NEXT line as its own text: `"-\n---"`, `"-\nprose line"`
# and `"-\n  continued"` all read as bullet-only, and the call site DROPS a
# bullet-only block ("the port table itself — L9 already carries it
# structurally"). A block whose first line is a bare `-` therefore lost its
# prose silently. Found by an exhaustive sweep of every block over a 9-symbol
# line alphabet up to 4 lines (7381 cases), not by review — my own written
# prediction said the two languages were identical and it was wrong. The
# shapes are absent from all 4787 real design-input documents (corpus control
# in the lane record), so no published document moves; where they do occur the
# new answer keeps the prose the old one dropped.
_RE_BULLET_LINE = re.compile(r"[ \t]*[-*+][ \t]")


def is_bullet_only_block(text: str) -> bool:
    """Is every non-blank line of `text` a bullet line?

    The linear replacement for `_RE_BULLET_ONLY`. Cost is one application of
    `_RE_BULLET_LINE` per non-blank line — a bound in STEPS, which is what
    makes it a property of the code rather than of how busy the host is.
    """
    for line in text.splitlines():
        if not line.strip():
            continue
        if not _RE_BULLET_LINE.match(line):
            return False
    return True


#: BACK-COMPATIBLE NAME, and the reason it is a name and not a pattern.
#: `phase1_doc_one_shot_runner` re-exports this symbol
#: (`_RE_CZL9_BULLET_ONLY = _ppx._RE_BULLET_ONLY`) and that file is held by
#: another lane, so the name must keep resolving or the docs door does not
#: import at all. It now names the PREDICATE: the non-returning pattern is gone
#: from the tree, not kept alive behind an alias, and there is exactly one
#: implementation of this question. The one-line hunk that renames the
#: re-export is written out in the lane's LAND.md.
_RE_BULLET_ONLY = is_bullet_only_block


def declared_port_names(content: Dict[str, Any]) -> List[str]:
    """Every port name L9 itself declares, from whichever container carries
    them. Order-stable and deduped."""
    names: List[str] = []
    for key in ("ports", "top_ports", "top_module_pins"):
        for entry in content.get(key) or []:
            if isinstance(entry, dict):
                nm = entry.get("name")
                if isinstance(nm, str) and nm.strip() and nm not in names:
                    names.append(nm.strip())
    return names


def block_mentions_port(block: str, names: List[str]) -> bool:
    """Does this block name one of the design's declared ports?

    A name of three characters or more matches bare; a one- or two-character
    name (`q`, `rx`) must appear in a code span, because a bare two-letter token
    matches ordinary English far too often to be evidence of anything."""
    for nm in names:
        if len(nm) >= 3:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(nm)}(?![A-Za-z0-9_])",
                         block):
                return True
        else:
            if re.search(rf"`{re.escape(nm)}`", block):
                return True
    return False


def emit_interface_prose(content: Dict[str, Any],
                         extracted: Dict[str, str]) -> None:
    """Preserve permitted extracted design input in the consumer's prose channel.

    The short-input path already carried the entire source. Input length must
    not change that semantic contract: selecting port-bearing paragraphs drops
    requirements that name no port, and slicing a paragraph can end mid-word.
    Source eligibility belongs to the upstream extractor; this producer copies
    its permitted documents without summarizing or imposing a character budget.
    """
    documents = [name for name in sorted(extracted)
                 if isinstance(extracted.get(name), str)
                 and extracted[name].strip()]
    whole = "\n\n".join(extracted[name].strip() for name in documents)
    content["interface_prose_provenance"] = {
        "selection": "whole" if whole else "none",
        "rule": "the permitted extracted design input carried whole, without truncation",
        "documents": documents,
        "blocks": 1 if whole else 0,
        "chars": len(whole),
        "truncated": False,
        "anchored_on": declared_port_names(content),
    }
    if whole:
        content["notes"] = whole
        content.pop("no_interface_prose_in_input", None)
    else:
        content.pop("notes", None)
        content["no_interface_prose_in_input"] = True


def extract(prompt: str) -> Dict:
    """The structural fact bundle from a prompt (ports/params/reset/enums → L8R,
    regmap → L4)."""
    return {
        "ports": extract_ports(prompt),
        "parameters": extract_params(prompt),
        "reset": extract_reset(prompt),
        "regmap": extract_regmap(prompt),
        "enums": extract_enums(prompt),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic port/param/reset extraction for Phase-1 NL.")
    ap.add_argument("--prompt", required=True, help="prompt file path")
    ap.add_argument("--json", default=None, help="write the fact bundle here")
    args = ap.parse_args(argv)
    p = Path(args.prompt)
    if not p.is_file():
        sys.stderr.write(f"phase1_port_extract: prompt not found: {p}\n")
        return 2
    facts = extract(p.read_text(errors="replace"))
    text = json.dumps(facts, indent=2)
    if args.json:
        Path(args.json).write_text(text + "\n")
    print(text)
    sys.stderr.write(f"phase1_port_extract: {len(facts['ports'])} ports, "
                     f"{len(facts['parameters'])} params\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
