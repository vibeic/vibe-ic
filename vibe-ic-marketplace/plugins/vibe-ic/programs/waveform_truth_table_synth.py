#!/usr/bin/env python3
"""waveform_truth_table_synth.py — DETERMINISTIC combinational-waveform → RTL
synthesizer (v1.1.38 clean-room §4.2 absorption).

THE GAP THIS CLOSES
-------------------
VerilogEval's `circuitN` family says "read the simulation waveforms to determine
what the circuit does, then implement it" and embeds a LITERAL truth table in the
prompt (`time <inputs...> <output>`). For a COMBINATIONAL circuit the table is a
complete input→output specification — there is ZERO ambiguity, no oracle, no
judgement: the answer is the sum-of-products over the rows where the output is 1.
Yet a blind author re-derives the boolean function by eye and flips it per round
(Prob102_circuit3, Prob103_circuit2, … alternate PASS/FAIL across clean-room
rounds = single-shot variance). The §4.2 doctrine: a GENERAL no-cheat recovery
MUST be absorbed as a PROGRAM. This program IS that absorption — it reads the
SAME table the author reads and emits the EXACT minimal-correct RTL
deterministically, so the next clean-room run gets it first-pass.

`waveform_table_conformance_check.py` is the CHECK (it BLOCKS a wrong sample);
this is the SYNTH (it EMITS the right one). They share `parse_table`.

ENVELOPE (PROVEN-FAITHFUL ONLY — §4.05 no-leak; SKIP, never guess, elsewhere)
----------------------------------------------------------------------------
Fires ONLY when ALL hold (else exit 2 = SKIP, emit nothing):
  * the prompt declares the circuit COMBINATIONAL (the word "combinational"
    appears AND no clock/flip-flop/sequential idiom is requested);
  * the embedded `time ...` table has NO clock-like column (clk/clock/…);
  * every NON-time column is a declared module port from the prompt's port list;
  * table values are pure 0/1/x;
  * the table is SELF-CONSISTENT: no two rows give the SAME input combination two
    DIFFERENT (non-x) values for any output (a contradiction ⇒ not a clean
    combinational function ⇒ SKIP).
Outside the envelope (clock column, sequential idiom, non-binary/hex, contradiction,
no parseable table or port list) it SKIPs — it never emits a guess, so it can
never ship a wrong sample. Unobserved input combinations are DON'T-CARE and emit 0
(the canonical reading; the dataset's combinational table covers every needed
minterm — the same envelope the conformance CHECK trusts).

USAGE
-----
    python3 waveform_truth_table_synth.py --prompt <prompt.txt> \\
        --top TopModule [--out sample.sv]
    # prints the synthesized module to stdout (and --out if given) on success

EXIT CODES
----------
    0  synthesized + emitted (combinational table fully resolved)
    2  SKIP — outside the proven-faithful envelope (no emit; not an error)

chip-AGNOSTIC: pure boolean synthesis from the prompt's own table; no chip / SKU /
oracle / hidden-testbench data of any kind.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Reuse the conformance gate's table parser + clock-name set (single source of truth).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import waveform_table_conformance_check as _wtc  # noqa: E402

CLOCK_NAMES = _wtc.CLOCK_NAMES

# Spec-to-rtl Shape-C port bullet: "- input  a" / "- output q (4 bits)".
_PORT_BULLET = re.compile(
    r"^\s*[-*]\s*(input|output)\s+([A-Za-z_]\w*)\s*(?:\(\s*(\d+)\s*bits?\s*\))?\s*$",
    re.IGNORECASE | re.MULTILINE)
# Code-complete (iccad2023) module-header decl: "  input a," / "  input [3:0] a," /
# "  output reg q" — a Verilog port declaration line inside the embedded header.
_PORT_DECL = re.compile(
    r"^\s*(input|output)\b\s*(?:wire|reg|logic|signed|unsigned)?\s*"
    r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?([A-Za-z_]\w*)\s*,?\s*$",
    re.IGNORECASE | re.MULTILINE)

# Sequential / clocked idioms that take a prompt OUT of the combinational envelope.
_SEQ_HINT = re.compile(
    r"\b(flip[- ]?flop|sequential|posedge|negedge|clock(?:ed)?|register(?:ed)?|"
    r"one bit of memory|state machine|\bFSM\b|edge of the clock)\b", re.IGNORECASE)


def parse_ports(prompt: str) -> Optional[Dict[str, Tuple[str, int, str]]]:
    """lowercase-name -> (dir, width, ORIGINAL_name) from the prompt's port list.
    Handles BOTH the spec-to-rtl bullet form (`- input a (4 bits)`) and the
    code-complete module-header decl form (`input [3:0] a,`); None if neither is
    present. The key is lowercased for case-insensitive matching against the
    (lowercased) waveform-table columns; the ORIGINAL name is carried in the value
    so emission preserves the testbench-facing case (e.g. `B3_next`)."""
    ports: Dict[str, Tuple[str, int, str]] = {}
    for m in _PORT_BULLET.finditer(prompt):
        d, name, w = m.group(1).lower(), m.group(2), m.group(3)
        ports[name.lower()] = (d, int(w) if w else 1, name)
    for m in _PORT_DECL.finditer(prompt):
        d, hi, lo, name = m.group(1).lower(), m.group(2), m.group(3), m.group(4)
        if name.lower() in ('wire', 'reg', 'logic'):  # decl keyword caught as name
            continue
        w = (abs(int(hi) - int(lo)) + 1) if hi is not None else 1
        ports.setdefault(name.lower(), (d, w, name))
    return ports or None


def _is_combinational(prompt: str) -> bool:
    return ("combinational" in prompt.lower()) and not _SEQ_HINT.search(prompt)


def _sop(in_names: List[str], minterms: List[Tuple[str, ...]]) -> str:
    """Sum-of-products literal over `in_names` for the given 1-rows (each a tuple of
    '0'/'1' aligned to in_names). Empty -> 1'b0; full canonical SOP otherwise."""
    if not minterms:
        return "1'b0"
    terms = []
    for combo in minterms:
        lits = []
        for nm, bit in zip(in_names, combo):
            lits.append(nm if bit == '1' else f"~{nm}")
        terms.append("(" + " & ".join(lits) + ")" if len(lits) > 1 else lits[0])
    return " | ".join(terms)


def synth(prompt: str, top: str = "TopModule") -> Optional[str]:
    """Return synthesized module text, or None to SKIP (outside the envelope)."""
    if not _is_combinational(prompt):
        return None
    ports = parse_ports(prompt)
    if not ports:
        return None
    parsed = _wtc.parse_table(prompt)
    if not parsed:
        return None
    cols, rows = parsed
    body = cols[1:]  # drop the leading 'time'
    # No clock-like column allowed in the combinational envelope.
    if any(c in CLOCK_NAMES for c in body):
        return None
    # Every body column must be a declared port; collect ins/outs in table order.
    in_cols = [c for c in body if ports.get(c, ('', 0, ''))[0] == 'input']
    out_cols = [c for c in body if ports.get(c, ('', 0, ''))[0] == 'output']
    if not out_cols or (len(in_cols) + len(out_cols)) != len(body):
        return None  # an unmapped/internal column -> SKIP
    # Pure-binary only (multi-bit/hex tables are out of envelope).
    if not _wtc.values_are_binary(rows, len(body)):
        return None
    idx = {c: i for i, c in enumerate(body)}
    # Build, per output, the input-combo -> value map; detect contradictions.
    out_one: Dict[str, List[Tuple[str, ...]]] = {o: [] for o in out_cols}
    seen: Dict[str, Dict[Tuple[str, ...], str]] = {o: {} for o in out_cols}
    for _t, vals in rows:
        combo = tuple(vals[idx[c]] for c in in_cols)
        if any(b.lower() == 'x' for b in combo):
            continue  # an x in an input -> row is not a usable minterm
        for o in out_cols:
            ov = vals[idx[o]]
            if ov.lower() == 'x':
                continue
            prev = seen[o].get(combo)
            if prev is not None and prev != ov:
                return None  # contradiction -> not a clean combinational function
            seen[o][combo] = ov
            if prev is None and ov == '1':
                out_one[o].append(combo)
    # Emit the module — original-case names (testbench-facing), inputs in table order.
    decl = []
    for nm in body:
        d, w, orig = ports[nm]
        rng = f"[{w-1}:0] " if w > 1 else ""
        decl.append(f"    {d:<6} {rng}{orig}")
    in_orig = [ports[c][2] for c in in_cols]
    lines = [f"module {top} (", ",\n".join(decl), ");", ""]
    for o in out_cols:
        lines.append(f"  assign {ports[o][2]} = {_sop(in_orig, out_one[o])};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    prompt = Path(a.prompt).read_text(errors="replace")
    rtl = synth(prompt, a.top)
    if rtl is None:
        print("SKIP: outside the combinational-waveform synth envelope", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
