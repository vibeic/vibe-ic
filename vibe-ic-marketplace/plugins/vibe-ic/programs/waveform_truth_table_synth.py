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
# A trailing line comment (`// 10-bit one-hot current state`) or block comment is
# tolerated: VerilogEval code-complete headers routinely annotate a port line, and
# the `$`-anchored decl must not be broken by it (else e.g. the `state` port of
# Prob150_review2015_fsmonehot is dropped and the one-hot synth SKIPs a solvable
# problem). chip-AGNOSTIC: pure Verilog port-decl grammar.
_PORT_DECL = re.compile(
    r"^\s*(input|output)\b\s*(?:wire|reg|logic|signed|unsigned)?\s*"
    r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?([A-Za-z_]\w*)\s*,?\s*"
    r"(?://[^\n]*|/\*.*?\*/)?\s*$",
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


# A timestamp-led waveform DATA row, mirroring (and broadening) parse_table's own
# `^\d+ns$` first-token test: any `<digits>` optionally with an alpha unit suffix
# (`ns`/`ps`/`us`/none). Used ONLY to DETECT truncation, never to parse.
_TS_LOOSE_RE = re.compile(r"^\d+[a-z]*$", re.IGNORECASE)
_BINVAL_RE = re.compile(r"^[01xzXZ]$")


def _table_is_complete(prompt: str, cols: List[str], n_rows: int) -> bool:
    """True only when `parse_table` consumed the WHOLE waveform table with no
    silently-dropped row. `parse_table` stops at the first row it cannot parse —
    a blank line GROUPING the table, a trailing annotation token (wrong arity), or
    a non-`ns` time unit — so a synth built on its output can emit an SOP over a
    TRUNCATED prefix → a wrong boolean function (Step-2.7 §4.05: the shared parser
    means even the sibling conformance CHECK replays the same truncation and
    passes the wrong sample). This independent scan re-counts every timestamp-led
    line in the table region: a CLEAN `<ts> <bits…>` row that parse_table accepts
    is counted; any timestamp-led row parse_table would DROP (malformed/annotated,
    or clean-but-after a break) makes the parse untrustworthy. If the clean-row
    count differs from the rows parse_table returned, or any timestamp-led row is
    malformed, the caller SKIPs. chip-AGNOSTIC: pure table-shape arithmetic."""
    lines = prompt.splitlines()
    hdr = next((i for i, ln in enumerate(lines)
                if ln.split() and ln.split()[0].lower() == "time"), None)
    if hdr is None:
        return False
    width = len(cols)            # time + value columns (a full parseable row)
    clean = 0                    # rows parse_table would accept
    for ln in lines[hdr + 1:]:
        t = ln.split()
        if not t or not _TS_LOOSE_RE.match(t[0]):
            continue             # blank / prose line — not a data row
        is_clean = (re.match(r"^\d+ns$", t[0], re.IGNORECASE)
                    and len(t) == width
                    and all(_BINVAL_RE.match(v) for v in t[1:]))
        if is_clean:
            clean += 1
        else:
            return False         # a timestamp-led row parse_table drops → truncation
    return clean == n_rows


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
    """Return synthesized module text, or None to SKIP. Tries the combinational
    envelope, then the single-flip-flop observable-state sequential envelope."""
    return _synth_combinational(prompt, top) or _synth_sequential_1ff(prompt, top)


def _synth_combinational(prompt: str, top: str = "TopModule") -> Optional[str]:
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
    # The table must be parsed IN FULL. parse_table truncates at the first row it
    # can't read (blank-line table grouping, a trailing annotation token, a non-ns
    # time unit), so an SOP over the surviving prefix is a WRONG function — and the
    # sibling conformance CHECK shares the same truncating parser, so it would pass
    # the wrong sample. A truncated/untrustworthy parse → SKIP. (Step-2.7 §4.05.)
    if not _table_is_complete(prompt, cols, len(rows)):
        return None
    # No clock-like column allowed in the combinational envelope.
    if any(c in CLOCK_NAMES for c in body):
        return None
    # Every body column must be a declared port; collect ins/outs in table order.
    in_cols = [c for c in body if ports.get(c, ('', 0, ''))[0] == 'input']
    out_cols = [c for c in body if ports.get(c, ('', 0, ''))[0] == 'output']
    if not out_cols or (len(in_cols) + len(out_cols)) != len(body):
        return None  # an unmapped/internal column -> SKIP
    # …and CONVERSELY every DECLARED port must appear as a table column. The synth
    # builds the emitted module interface from the table columns, so a declared
    # port absent from the table would be SILENTLY DROPPED from the port list → a
    # port-truncated module (a wrong sample whose interface mismatches the
    # reference). The table is then not a complete spec for the interface → SKIP.
    if any(p not in body for p in ports):
        return None
    # Every table column must be a 1-BIT port. The SOP model treats each column as
    # a single boolean variable, so a MULTI-BIT declared port (`input [1:0] a`) is
    # out of envelope: even when its observed rows show only 0/1 (so
    # values_are_binary passes), emitting `assign q = a` over a bus is
    # width-mismatched and wrong for any unobserved bus value. Enforce on the
    # DECLARED width, not just observed values. (Step-2.7 §4.05.)
    if any(ports[c][1] != 1 for c in body):
        return None
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


# A prompt that observes the single flip-flop through a named output:
# "the output of the flip-flop has been made observable through the output state".
_FF_OBSERVABLE = re.compile(
    r"one (?:bit of memory|flip[- ]?flop).*?observable through the output\s+"
    r"([A-Za-z_]\w*)", re.IGNORECASE | re.DOTALL)


def _synth_sequential_1ff(prompt: str, top: str = "TopModule") -> Optional[str]:
    """Single-flip-flop, observable-state sequential waveform → RTL.

    The prompt names the FF's observable output (`state`); the table samples
    clk + inputs + state + combinational outputs every half-period. For every
    consecutive pair of POSEDGE rows, the registered state at the later edge is a
    function of (inputs, state) at the earlier edge — a deterministic next-state
    truth table; each combinational output is a function of (inputs, state) read
    per row. Fires ONLY for: exactly one observable-state 1-bit output, a single
    posedge clk, all-1-bit ports, every table column a declared port, and
    self-consistent next-state + output tables. SKIPs otherwise (§4.05 no-leak)."""
    m = _FF_OBSERVABLE.search(prompt)
    if not m:
        return None
    state_name = m.group(1).lower()
    if "negedge" in prompt.lower():
        return None
    ports = parse_ports(prompt)
    if not ports:
        return None
    parsed = _wtc.parse_table(prompt)
    if not parsed:
        return None
    cols, rows = parsed
    # Same truncation hazard as the combinational path: parse_table stops at the
    # first un-parseable row (blank-line grouping / annotation token / non-ns
    # unit), so a next-state SOP built on a TRUNCATED prefix is a wrong sequential
    # function. The combinational path SKIPs on this; the sequential path must too.
    # (Step-2.7 §4.05 — a truncated parse must never EMIT.)
    if not _table_is_complete(prompt, cols, len(rows)):
        return None
    body = cols[1:]
    clk_cols = [c for c in body if c in CLOCK_NAMES]
    if len(clk_cols) != 1:
        return None
    clk = clk_cols[0]
    if state_name not in ports or ports[state_name][0] != "output" or ports[state_name][1] != 1:
        return None
    in_cols = [c for c in body if ports.get(c, ('', 0, ''))[0] == "input" and c not in CLOCK_NAMES]
    out_cols = [c for c in body if ports.get(c, ('', 0, ''))[0] == "output"]
    if state_name not in out_cols or any(ports[c][1] != 1 for c in (in_cols + out_cols)):
        return None
    if (len(in_cols) + len(out_cols) + 1) != len(body):
        return None  # an unmapped/internal column -> SKIP
    if not _wtc.values_are_binary(rows, len(body)):
        return None
    idx = {c: i for i, c in enumerate(body)}
    comb_outs = [o for o in out_cols if o != state_name]
    ff_in = list(in_cols) + [state_name]   # next-state depends on (inputs, state)

    # posedge rows: clk == 1 whose PREVIOUS row's clk == 0 (a genuine 0→1 edge).
    # Step-2.7 §4.05: row 0 must NOT be treated as a posedge — a waveform that
    # starts with clk already high (no preceding clk=0) carries no edge into row 0,
    # so pairing its (inputs,state) sample as a registering edge injects a PHANTOM
    # next-state minterm and emits wrong next-state logic. Require a real 0→1
    # transition; a leading-high first row simply isn't an edge.
    pos = []
    for i, (_t, vals) in enumerate(rows):
        if vals[idx[clk]] == '1' and i > 0 and rows[i - 1][1][idx[clk]] == '0':
            pos.append(i)

    def _collect(in_names, out_col, sample_rows, next_offset=0):
        ones, seen = [], {}
        for r in sample_rows:
            ri = r + next_offset
            if ri >= len(rows):
                continue
            combo = tuple(rows[r][1][idx[c]] for c in in_names)
            ov = rows[ri][1][idx[out_col]]
            if any(b.lower() == 'x' for b in combo) or ov.lower() == 'x':
                continue
            prev = seen.get(combo)
            if prev is not None and prev != ov:
                return None
            seen[combo] = ov
            if prev is None and ov == '1':
                ones.append(combo)
        return ones

    # next-state: (inputs,state) at posedge r -> state at the NEXT posedge
    ns_ones = []
    ns_seen = {}
    for a_i in range(len(pos) - 1):
        r, rn = pos[a_i], pos[a_i + 1]
        combo = tuple(rows[r][1][idx[c]] for c in ff_in)
        ov = rows[rn][1][idx[state_name]]
        if any(b.lower() == 'x' for b in combo) or ov.lower() == 'x':
            continue
        prev = ns_seen.get(combo)
        if prev is not None and prev != ov:
            return None
        ns_seen[combo] = ov
        if prev is None and ov == '1':
            ns_ones.append(combo)
    # combinational outputs: (inputs,state) at a row -> out at the SAME row
    comb_ones = {}
    for o in comb_outs:
        res = _collect(ff_in, o, range(len(rows)), next_offset=0)
        if res is None:
            return None
        comb_ones[o] = res

    ff_in_orig = [ports[c][2] for c in ff_in]
    decl = []
    for nm in body:
        d, w, orig = ports[nm]
        if nm == state_name and d == "output":
            decl.append(f"    output reg {orig}")
        else:
            decl.append(f"    {d:<6} {orig}")
    lines = [f"module {top} (", ",\n".join(decl), ");", ""]
    lines.append(f"  always @(posedge {ports[clk][2]})")
    lines.append(f"    {ports[state_name][2]} <= {_sop(ff_in_orig, ns_ones)};")
    for o in comb_outs:
        lines.append(f"  assign {ports[o][2]} = {_sop(ff_in_orig, comb_ones[o])};")
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
        print("SKIP: outside the waveform synth envelope", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
