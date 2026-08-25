#!/usr/bin/env python3
r"""prose_interface_table_read.py — read an interface stated as a MARKDOWN TABLE.

The third reader in the prose-interface chain, beside `prose_port_block_read`
(the indented `Input ports:` prose form) and `prose_interface_bridge_md` (the
`### Inputs` section-scoped bullet form). This one reads the shape a datasheet
or a design spec reaches for most naturally:

    | Signal   | Direction | Bit Width | Description        |
    |----------|-----------|-----------|--------------------|
    | clk      | Input     | 1         | system clock       |
    | data_in  | Input     | [7:0]     | operand            |
    | result   | Output    | WIDTH     | sum                |

Direction is read from the Direction cell (Input/inout -> input, Output ->
output). Width is read from the width cell as a literal int, an `[hi:lo]` range,
an `N-bit` phrase, or a PARAMETER NAME whose default the caller supplies — in
which case `symbolic` records `name -> "PARAM-1:0"` so an emit can
re-parameterize the port rather than freeze the default.

WHY THIS IS ITS OWN MODULE. The reader was written during a CVDP capture and
lived as `_signal_direction_table`, a PRIVATE function inside
`cvdp_atomic_bridge`. Its logic never touched a record field or a dataset
literal — it is prose in, ports out — but under a benchmark prefix, behind a
leading underscore, the general Phase-1 path could not reach it: a plain design
doc stating its pins in the commonest table form in the industry parsed to
([],[]) while a benchmark record parsed fine. Two other modules had already
resorted to reaching across for `_bridge._signal_direction_table`, which is what
a general capability trapped in the wrong file looks like from the outside.

Per the GENERAL-CORE / THIN-ADAPTER rule: the general core owns the reader, and
the benchmark adapter imports it like any other caller.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
def read_signal_direction_table(prompt: str, params: Optional[Dict[str, int]] = None
                            ) -> Tuple[List[str], List[str], Dict[str, int], Dict[str, str]]:
    """(input_names, output_names, widths, symbolic) from a markdown INTERFACE table
    whose header carries a Signal/Port/Name column AND a Direction column — the
    common CVDP `| Signal | Direction | Bit Width | ... |` shape. A PROMPT-sourced
    interface (legal). Names classified by the Direction cell (Input/inout ->
    input, Output -> output); `widths` maps a name to its resolved width from the
    `Bit Width` cell (a literal int, an `[hi:lo]` range, or a parameter name whose
    default is in `params`); `symbolic` records `name -> "PARAM-1:0"` when the width
    cell is a parameter, so the emit re-parameterizes the port. Absent when the
    cell is unresolvable."""
    params = params or {}

    def _width_cell(cell: str) -> Tuple[Optional[int], Optional[str]]:
        cell = cell.strip().strip("`")
        m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1, None
        m = re.fullmatch(r"(\d+)", cell) or re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
        if m:
            return int(m.group(1)), None
        for pnm, pv in params.items():          # a parameter name (WIDTH/DATA_WIDTH)
            if re.search(rf"\b{re.escape(pnm)}\b", cell):
                return pv, f"{pnm}-1:0"
        return None, None

    lines = prompt.splitlines()
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "|" not in ln or "direction" not in low:
            continue
        if not any(k in low for k in ("signal", "port", "name")):
            continue
        if i + 1 >= len(lines) or not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            continue
        headers = [h.strip().strip("`").lower() for h in ln.strip().strip("|").split("|")]
        nci = next((j for j, h in enumerate(headers)
                    if h in ("signal", "port", "name", "signal name", "port name")), None)
        dci = next((j for j, h in enumerate(headers) if "direction" in h), None)
        wci = next((j for j, h in enumerate(headers)
                    if "width" in h or "bit" in h), None)
        if nci is None or dci is None:
            continue
        ins: List[str] = []
        outs: List[str] = []
        widths: Dict[str, int] = {}
        symbolic: Dict[str, str] = {}
        for body in lines[i + 2:]:
            if "|" not in body or not body.strip().startswith("|"):
                break
            cells = [c.strip().strip("`") for c in body.strip().strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            nm = re.match(r"([A-Za-z_]\w*)", cells[nci].strip())
            if not nm:
                continue
            name = nm.group(1)
            d = cells[dci].lower()
            if "out" in d:
                outs.append(name)
            elif "in" in d:                 # input / inout -> input
                ins.append(name)
            else:
                continue
            if wci is not None:
                w, sym = _width_cell(cells[wci])
                if w is not None:
                    widths[name] = w
                if sym is not None:
                    symbolic[name] = sym
        ins = list(dict.fromkeys(ins))
        outs = list(dict.fromkeys(outs))
        if ins and outs:
            return ins, outs, widths, symbolic
    return [], [], {}, {}


def bridge_prompt(text: str, params: Optional[Dict[str, int]] = None) -> str:
    """Prose in, prose out — the chain contract. Returns `text` with an
    equivalent bullet port block PREPENDED when a signal/direction table is
    present, so `port_parser.parse_ports` reads the interface while every
    consumer still sees the full original prose for its body semantics.
    Unchanged when no such table is present (a no-op bridge)."""
    ins, outs, widths, _symbolic = read_signal_direction_table(text, params)
    if not ins and not outs:
        return text
    out_lines = []
    for name in ins:
        w = widths.get(name, 1)
        out_lines.append(f" - input {name} ({w} bits)" if w != 1 else f" - input {name}")
    for name in outs:
        w = widths.get(name, 1)
        out_lines.append(f" - output {name} ({w} bits)" if w != 1 else f" - output {name}")
    return "\n".join(out_lines) + "\n\n" + text


def interface_json(text: str, params: Optional[Dict[str, int]] = None) -> dict:
    """Structured interface JSON: {inputs:[{name,width}], outputs:[...]}.
    Empty lists when no signal/direction table parses."""
    ins, outs, widths, _sym = read_signal_direction_table(text, params)
    return {"inputs": [{"name": n, "width": widths.get(n, 1)} for n in ins],
            "outputs": [{"name": n, "width": widths.get(n, 1)} for n in outs]}


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", help="path to a spec/prose file, or - for stdin")
    ap.add_argument("--json", action="store_true", help="emit interface JSON")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    text = sys.stdin.read() if a.spec == "-" else Path(a.spec).read_text(errors="replace")
    if a.json:
        print(json.dumps(interface_json(text), indent=2))
        return 0
    ins, outs, widths, sym = read_signal_direction_table(text)
    if not ins and not outs:
        print("no signal/direction table found", file=sys.stderr)
        return 1
    for n in ins:
        print(f"input  {n} [{widths.get(n, 1)}]" + (f"  ({sym[n]})" if n in sym else ""))
    for n in outs:
        print(f"output {n} [{widths.get(n, 1)}]" + (f"  ({sym[n]})" if n in sym else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
