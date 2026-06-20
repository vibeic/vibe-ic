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
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _specrtl_common import (  # noqa: E402
    parse_verilog_ports, _parse_md_table_ports, Port, strip_comments,
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
_MODULE_SPAN = re.compile(r'\bmodule\b.*?\bendmodule\b', re.S)


def _verilog_regions(text: str) -> str:
    regions = [m.group(1) for m in _FENCE.finditer(text)]
    regions += [m.group(0) for m in _MODULE_SPAN.finditer(text)]
    # strip comments so an inline `// the reset …` comment after a port decl
    # cannot scrape its first word as a phantom port.
    return strip_comments("\n".join(regions))


def extract_ports(prompt: str) -> List[Dict]:
    """Union of markdown-interface-table ports (precise on the whole text) and
    inline-Verilog-declared ports — the latter parsed ONLY from real Verilog code
    regions so a prose sentence can never inject a phantom port."""
    # union=True: a spec often splits its interface across separate clock/reset,
    # input and output tables — Phase 1 needs every port, not just the largest table.
    table, _notes = _parse_md_table_ports(prompt, union=True)
    inline = parse_verilog_ports(_verilog_regions(prompt))
    table_inline = _dedup_ports(list(table) + list(inline))
    if table_inline:
        return table_inline
    # only fall back to the structured-prose signal-definition list when no table
    # / code interface was found (tables/code are higher-confidence).
    prose = extract_prose_ports(prompt)
    return _dedup_ports([Port(p["name"], p["dir"], p["width"]) for p in prose])


def extract_params(prompt: str) -> List[Dict]:
    out: Dict[str, str] = {}
    for m in _PARAM_DECL.finditer(prompt):
        out.setdefault(m.group(1), m.group(2).strip())
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
    _split_md_row, _is_md_delim_row, _strip_md_emphasis)


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
            name = _strip_md_emphasis(cells[name_c])
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
    return out


# Prose signal-DEFINITION bullet: `- [**|`]?[ [w-1:0] ]?NAME[`|**]? : description`.
# The NAME must be IMMEDIATELY followed by `:` (a definition), which excludes a
# prose REFERENCE bullet like "- `a` and `b` are toggle signals" (name followed by
# a word, not a colon). Optional leading width `[3:0]` / `[WIDTH-1:0]`.
_PROSE_SIG = re.compile(
    r'^\s*[-*]\s*\**\s*(?:\[\s*([^\]]*?)\s*\]\s*)?`?\**\s*'
    r'([A-Za-z_]\w*)\s*'
    r'(?:\[\s*([^\]]*?)\s*\])?\**`?\**\s*:',
)
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


def _width_from(expr: Optional[str]) -> int:
    if not expr:
        return 1
    m = re.fullmatch(r'\s*(\d+)\s*:\s*(\d+)\s*', expr)
    return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else 1


def extract_prose_ports(prompt: str) -> List[Dict]:
    """Deterministic ports from a STRUCTURED-PROSE signal-definition list — the
    `**Inputs**:` / `**Outputs**:` sectioned bullet form common when a spec has no
    interface table. Direction comes from the section header or an `N-bit
    input/output` phrase in the description; precision-anchored on the
    NAME-immediately-followed-by-colon definition shape (a prose reference to a
    signal does not match)."""
    out: List[Dict] = []
    seen = set()
    section = None  # 'input' | 'output' | None
    for line in prompt.splitlines():
        # a short header line that names Inputs/Outputs sets the section — strip
        # leading bullets (`- `, `* `, `•`), markdown emphasis, numbering and the
        # trailing colon, then match the alphanumeric core.
        core = re.sub(r'[^a-z ]', '', line.strip().lower()).strip()
        if core in ("inputs", "input ports", "input signals", "input",
                    "input interface"):
            section = "input"; continue
        if core in ("outputs", "output ports", "output signals", "output",
                    "output interface"):
            section = "output"; continue
        m = _PROSE_SIG.match(line)
        if not m:
            continue
        name = m.group(2)
        # section-DESCRIPTOR bullets ("- **Clock:** the `clk` signal is …",
        # "- Reset: …", "- Inputs:") use a TitleCase English label, not the real
        # signal name (which is the backtick token in the description). Skip them.
        if name.lower() in _PROSE_STOP:
            continue
        # A `[A-Z][a-z]{2,}` TitleCase English WORD (Address, Operation, Result,
        # Default, Status…) heads a descriptor bullet — never a real port. Real
        # ports are lowercase/snake_case (clk, coin_input) or short all-caps
        # acronyms (A, B, OUT), which this does NOT match.
        if re.fullmatch(r'[A-Z][a-z]{2,}', name):
            continue
        desc = line.split(':', 1)[1] if ':' in line else ""
        # direction: explicit N-bit input/output in the description wins, else section
        d = None
        dm = re.search(r'\b(\d+\s*-?\s*bit\s+)?(input|output|inout)\b', desc, re.I)
        if dm:
            d = dm.group(2).lower()
        elif re.search(r'\bclock\b|\breset\b|\bclk\b', desc, re.I) and section is None:
            d = "input"
        else:
            d = section
        if d is None:
            continue
        width = _width_from(m.group(1) or m.group(3))
        if width == 1:
            bm = re.search(r'(\d+)\s*-?\s*bit', desc)
            if bm:
                width = int(bm.group(1))
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "dir": d, "width": width})
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


def extract(prompt: str) -> Dict:
    """The structural fact bundle from a prompt (ports/params/reset → L8R,
    regmap → L4)."""
    return {
        "ports": extract_ports(prompt),
        "parameters": extract_params(prompt),
        "reset": extract_reset(prompt),
        "regmap": extract_regmap(prompt),
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
