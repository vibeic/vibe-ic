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
    return _dedup_ports(list(table) + list(inline))


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
    """The L8R-shaped structural fact bundle from a prompt."""
    return {
        "ports": extract_ports(prompt),
        "parameters": extract_params(prompt),
        "reset": extract_reset(prompt),
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
