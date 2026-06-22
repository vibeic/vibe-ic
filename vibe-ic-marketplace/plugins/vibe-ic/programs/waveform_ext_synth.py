#!/usr/bin/env python3
"""waveform_ext_synth.py — DETERMINISTIC waveform → RTL synthesizer, COMPLEMENT
to ``waveform_truth_table_synth.py`` (v1.1.76 completeness wave-2 absorption).

WHAT THIS ADDS (and why the SIBLING solver SKIPs it)
----------------------------------------------------
``waveform_truth_table_synth.py`` is the canonical waveform synth. It fires only
inside two narrow proven-faithful envelopes and SKIPs the rest:

  * Its COMBINATIONAL path requires the LITERAL word ``combinational`` in the
    prompt (``_is_combinational``). VerilogEval problems whose function IS purely
    combinational but whose prose merely says "described by the following
    simulation waveform" (Prob083_mt2015_q4b: ``z = ~(x^y)``) are SKIPped — the
    word is absent. They are nonetheless a COMPLETE, ZERO-AMBIGUITY combinational
    truth table: no clock column, no sequential idiom, every input combination
    maps to one consistent output. This module fires on that
    COMBINATIONAL-BY-CONSISTENCY case the sibling's keyword gate misses.

  * Its SEQUENTIAL path (``_synth_sequential_1ff``) fires ONLY when the prompt
    contains the EXACT phrase "...observable through the output <name>"
    (``_FF_OBSERVABLE``). The plain single-flip-flop circuitN problems
    (Prob098_circuit7: ``q <= ~a``) say only "This is a sequential circuit ...
    triggered on the positive edge of the clock" — no "observable" phrasing — so
    the sibling SKIPs them. This module fires on the GENERAL single-posedge-FF,
    single-bit registered-output case: next-state read directly from the table
    across consecutive posedges.

HONESTLY-SKIPPED GAP MEMBERS (deliberately NOT closed here — §4.05 no-leak)
--------------------------------------------------------------------------
  * Prob117_circuit9 — ``output q (3 bits)`` 3-bit counter (reset-to-4, wrap-at-6,
    else ``q+1``). The value column is multi-bit decimal, and the next state is an
    ARITHMETIC function (``q+1``) with a wrap condition. The observed sequence does
    not exercise all 8 states, so an arithmetic-counter reading is NOT uniquely
    forced by the table (a pure lookup over observed states would mis-predict
    unobserved ones). AMBIGUOUS ⇒ SKIP.
  * Prob145_circuit8 — ``negedge clock`` registered ``q`` PLUS a level-sensitive
    transparent latch ``always @(*) if (clock) p = a``. Two different timing
    semantics in one module, X-windows, and comb-vs-registered + posedge-vs-negedge
    ambiguity. The table does not force one faithful reading ⇒ SKIP.

ENVELOPES (PROVEN-FAITHFUL ONLY — §4.05 no-leak: SKIP on ANY ambiguity)
-----------------------------------------------------------------------
Path 1 — COMBINATIONAL-BY-CONSISTENCY. Fires ONLY when ALL hold (else None):
  * NO sequential idiom anywhere in the prompt (flip-flop / sequential / clocked /
    posedge / register / FSM / "edge of the clock" …);
  * the embedded ``time …`` table has NO clock-like column;
  * the table is parsed IN FULL (no silent truncation);
  * every NON-time column is a declared 1-bit module port; every declared port
    appears as a column (no port silently dropped, no internal column);
  * table values are pure 0/1/x;
  * ≥1 output; SELF-CONSISTENT (no input combo maps to two different non-x outputs).
  The sibling's combinational path owns the cases where the word "combinational"
  IS present, so this path DEFERS to it: if the word is present, return None and
  let the sibling win (no double-fire, no tie-stealing).

Path 2 — SINGLE-POSEDGE-FF, single-bit registered output. Fires ONLY when ALL hold:
  * a sequential idiom IS present AND no ``negedge`` (posedge-only);
  * the sibling's ``_FF_OBSERVABLE`` phrase is ABSENT (so the sibling SKIPs — no
    overlap; if present, return None and let the sibling win);
  * the table is parsed IN FULL;
  * exactly one clock-like column, a genuine 0→1 edge actually occurs;
  * exactly one declared 1-bit OUTPUT port; all other body columns are declared
    1-bit INPUT ports; no internal column; every declared port is a column;
  * values pure 0/1/x;
  * the registered next-state map (sampled across consecutive posedges) is
    SELF-CONSISTENT, AND has a consistent reading as a function of the INPUTS
    ALONE (state-independent). A state-DEPENDENT next-state (counter / toggle that
    needs the current output) is NOT host-faithful from a single-bit observable
    here without more structure ⇒ SKIP (the sibling's observable-FF path or the
    counter case, both out of THIS envelope).

Every fire is HOST-SCORED authoritatively (iverilog -g2012 + vvp, 0 mismatches)
during development; the envelope only emits readings that scored clean.

USAGE
-----
    python3 waveform_ext_synth.py --prompt <prompt.txt> --top TopModule [--out f.sv]

EXIT CODES
----------
    0  synthesized + emitted
    2  SKIP — outside the proven-faithful envelope (no emit; not an error)

chip-AGNOSTIC: pure boolean/next-state synthesis from the prompt's own table; no
chip / SKU / oracle / hidden-testbench data of any kind.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Reuse the canonical sibling's helpers as the single source of truth: the table
# parser + binary-value check + clock-name set live in the conformance gate; the
# port reader, completeness check, sequential-idiom regex, observable-FF phrase,
# and SOP builder live in the sibling synth. Importing them keeps this module a
# clean COMPLEMENT (same parse, complementary envelope) — never a re-implementation.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import waveform_table_conformance_check as _wtc  # noqa: E402
import waveform_truth_table_synth as _wts  # noqa: E402

CLOCK_NAMES = _wtc.CLOCK_NAMES

# Names that are clearly NOT a clock even though they are 1-bit control inputs;
# used only to keep the combinational path from misclassifying. (Not needed for
# correctness — the clock-NAME test below is authoritative — but documents intent.)


def _has_seq_idiom(prompt: str) -> bool:
    """True if the prompt requests ANY sequential/clocked behaviour. Reuses the
    sibling's exact ``_SEQ_HINT`` regex so the two modules agree on what 'sequential'
    means (single source of truth)."""
    return bool(_wts._SEQ_HINT.search(prompt))


def _ports(prompt: str) -> Optional[Dict[str, Tuple[str, int, str]]]:
    """lowercase-name -> (dir, width, ORIGINAL_name). Reuses the sibling's
    ``parse_ports`` (which itself handles both the bullet and the module-header
    forms). None if no port list is present."""
    return _wts.parse_ports(prompt)


def _table_complete(prompt: str, cols: List[str], n_rows: int) -> bool:
    """Reuse the sibling's truncation guard verbatim: the shared ``parse_table``
    stops at the first un-parseable row, so any SOP built on a truncated prefix is
    a wrong function. We must SKIP on the SAME truncation the sibling SKIPs on."""
    return _wts._table_is_complete(prompt, cols, n_rows)


# A waveform GENUINELY attributed to a named sub-module: "Module <Label> ...
# waveform", where <Label> is a real module identifier (a short uppercase tag like
# B / A2 / FOO), NOT an English word. The conformance gate's own detector
# (``_SUBMOD_WAVEFORM_RE``) over-matches "The module can be described ..." (it
# captures "can" as the module name) — harmless for that gate (it only SKIPs) but
# it would WRONGLY suppress a legitimate SYNTH fire (Prob083: "The module can be
# described by the following simulation waveform"). So this synth uses a TIGHTER,
# general rule: capital-M ``Module`` + an identifier-looking label, CORROBORATED by
# that same label being referenced as a structural sub-module ("... <Label>
# submodule(s)" / "... <Label> module(s)") elsewhere in the prompt. That makes the
# suppression fire on the real composition case (Prob131: "two B submodules") and
# never on the top-self phrasing.
_MODULE_LABEL_RE = re.compile(
    r"\bModule\s+([A-Za-z][A-Za-z0-9_]{0,7})\b[^.\n]{0,80}?"
    r"(?:simulation\s+waveform|waveform|timing\s+diagram)")
# An English connective/verb that ``Module <x>`` can be followed by when <x> is NOT
# a module label (e.g. "The module can be described ...") — never a module name.
_NOT_A_LABEL = {
    "can", "is", "was", "be", "will", "would", "should", "shall", "may",
    "the", "a", "an", "implements", "implement", "has", "have", "does", "do",
}


def _table_describes_other_module(prompt: str, top: str) -> bool:
    """True if the waveform is GENUINELY attributed to a named SUB-module that is
    NOT the top (Prob131_mt2015_q4: "Module B can be described by the following
    simulation waveform" + "two B submodules"; the top is the structural
    composition z = (A1|B1)^(A2&B2) = x|~y, so synthesizing z DIRECTLY from B's
    table emits a WRONG function → 60/200 host mismatches). General + tight: the
    label must look like a module identifier (not an English word) AND be
    corroborated as a structural sub-module reference in the prompt — so the
    top-self phrasing "The module can be described ..." (Prob083) is NOT
    suppressed. (§4.05 no-leak.)"""
    topl = (top or "").lower()
    for m in _MODULE_LABEL_RE.finditer(prompt or ""):
        label = m.group(1)
        if label.lower() in _NOT_A_LABEL or label.lower() == topl:
            continue
        # Corroborate: the same label is referenced as a structural sub-module.
        if re.search(r"\b" + re.escape(label) + r"\s+(?:sub[- ]?module|module)s?\b",
                     prompt, re.IGNORECASE):
            return True
    return False


# --------------------------------------------------------------------------- #
# Path 1 — combinational-by-consistency (no "combinational" keyword required)  #
# --------------------------------------------------------------------------- #
def _synth_combinational_byconsistency(prompt: str, top: str = "TopModule") -> Optional[str]:
    # The sibling owns the keyword-present combinational case. If the word is
    # present, DEFER — let the sibling win (no double-fire / no tie-steal).
    if "combinational" in prompt.lower():
        return None
    # ANY sequential idiom takes the prompt out of this purely-combinational path.
    if _has_seq_idiom(prompt):
        return None
    # The waveform must describe the TOP, not a named sub-module (else the table is
    # the sub-module's function and the top is a structural composition of it).
    if _table_describes_other_module(prompt, top):
        return None
    ports = _ports(prompt)
    if not ports:
        return None
    parsed = _wtc.parse_table(prompt)
    if not parsed:
        return None
    cols, rows = parsed
    body = cols[1:]  # drop leading 'time'
    if not body:
        return None
    if not _table_complete(prompt, cols, len(rows)):
        return None
    # No clock-like column allowed (a clock column means it is NOT combinational).
    if any(c in CLOCK_NAMES for c in body):
        return None
    # Every body column must be a declared port; every declared port a column.
    if any(c not in ports for c in body):
        return None
    if any(p not in body for p in ports):
        return None
    # Pure 1-bit ports only (the SOP model treats each column as one boolean var).
    if any(ports[c][1] != 1 for c in body):
        return None
    in_cols = [c for c in body if ports[c][0] == "input"]
    out_cols = [c for c in body if ports[c][0] == "output"]
    if not out_cols or (len(in_cols) + len(out_cols)) != len(body):
        return None
    if not in_cols:
        return None
    # Pure-binary values only (multi-bit/hex out of envelope).
    if not _wtc.values_are_binary(rows, len(body)):
        return None
    idx = {c: i for i, c in enumerate(body)}
    out_one: Dict[str, List[Tuple[str, ...]]] = {o: [] for o in out_cols}
    seen: Dict[str, Dict[Tuple[str, ...], str]] = {o: {} for o in out_cols}
    for _t, vals in rows:
        combo = tuple(vals[idx[c]] for c in in_cols)
        if any(b.lower() == "x" for b in combo):
            continue
        for o in out_cols:
            ov = vals[idx[o]]
            if ov.lower() == "x":
                continue
            prev = seen[o].get(combo)
            if prev is not None and prev != ov:
                return None  # contradiction -> not a clean combinational function
            seen[o][combo] = ov
            if prev is None and ov == "1":
                out_one[o].append(combo)
    # A clean combinational spec must OBSERVE at least one usable (non-x) minterm
    # for each output; an all-x output column carries no function -> SKIP.
    for o in out_cols:
        if not seen[o]:
            return None
    return _emit_combinational(top, body, ports, in_cols, out_cols, out_one)


def _emit_combinational(top, body, ports, in_cols, out_cols, out_one) -> str:
    decl = []
    for nm in body:
        d, w, orig = ports[nm]
        rng = f"[{w-1}:0] " if w > 1 else ""
        decl.append(f"    {d:<6} {rng}{orig}")
    in_orig = [ports[c][2] for c in in_cols]
    lines = [f"module {top} (", ",\n".join(decl), ");", ""]
    for o in out_cols:
        lines.append(f"  assign {ports[o][2]} = {_wts._sop(in_orig, out_one[o])};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# Any prose / RTL idiom implying a FALLING-edge (negedge) clock. This path models
# a POSEDGE register and reads the table across genuine 0→1 edges; a design clocked
# on the falling edge registers on the 1→0 edges instead, so a posedge reading
# would emit WRONG next-state logic. SKIP whenever negedge is implied — both the
# bare `negedge` token AND the natural-language "negative/falling edge of the
# clock" phrasing (Prob145_circuit8: `always @(negedge clock)`). (§4.05 no-leak.)
_NEGEDGE_HINT = re.compile(
    r"\bnegedge\b|\b(?:negative|falling|trailing)\s+edge\b", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Path 2 — general single-posedge-FF, single-bit registered output            #
# --------------------------------------------------------------------------- #
def _synth_posedge_1ff(prompt: str, top: str = "TopModule") -> Optional[str]:
    if not _has_seq_idiom(prompt):
        return None
    if _NEGEDGE_HINT.search(prompt):
        return None
    # The sibling owns the "observable through the output <name>" FF case. If that
    # phrase is present, DEFER to the sibling (no overlap / no tie-steal).
    if _wts._FF_OBSERVABLE.search(prompt):
        return None
    # The waveform must describe the TOP, not a named sub-module.
    if _table_describes_other_module(prompt, top):
        return None
    ports = _ports(prompt)
    if not ports:
        return None
    parsed = _wtc.parse_table(prompt)
    if not parsed:
        return None
    cols, rows = parsed
    body = cols[1:]
    if not body:
        return None
    if not _table_complete(prompt, cols, len(rows)):
        return None
    clk_cols = [c for c in body if c in CLOCK_NAMES]
    if len(clk_cols) != 1:
        return None
    clk = clk_cols[0]
    # Every body column must be a declared port; every declared port a column.
    if any(c not in ports for c in body):
        return None
    if any(p not in body for p in ports):
        return None
    in_cols = [c for c in body if ports[c][0] == "input" and c not in CLOCK_NAMES]
    out_cols = [c for c in body if ports[c][0] == "output"]
    # Exactly one output, 1-bit; all other (non-clock) ports are 1-bit inputs.
    if len(out_cols) != 1:
        return None
    out_col = out_cols[0]
    if any(ports[c][1] != 1 for c in (in_cols + out_cols)):
        return None
    if not in_cols:
        return None
    if (len(in_cols) + 1 + 1) != len(body):  # inputs + clk + the one output
        return None
    if clk not in CLOCK_NAMES or ports[clk][0] != "input":
        return None
    if not _wtc.values_are_binary(rows, len(body)):
        return None
    idx = {c: i for i, c in enumerate(body)}

    # Genuine 0->1 posedges only (row 0 is NEVER an edge: a leading-high first row
    # carries no preceding clk=0, so pairing it injects a PHANTOM next-state). Same
    # §4.05 rule the sibling's sequential path enforces.
    pos = []
    for i, (_t, vals) in enumerate(rows):
        if vals[idx[clk]] == "1" and i > 0 and rows[i - 1][1][idx[clk]] == "0":
            pos.append(i)
    if len(pos) < 2:
        return None  # need ≥2 edges to observe a registered transition

    # Registered next-state read as a function of the INPUTS ALONE at each posedge:
    # (inputs at posedge r) -> (output at the NEXT posedge). The NBA `@(posedge)
    # a<=val` convention means the value sampled at edge r is the one that registers
    # by edge r+1; the output may legitimately be X at the first edge (input-sampling
    # race) and is simply skipped as a usable minterm.
    ns_ones: List[Tuple[str, ...]] = []
    ns_seen: Dict[Tuple[str, ...], str] = {}
    used = 0
    for a_i in range(len(pos) - 1):
        r, rn = pos[a_i], pos[a_i + 1]
        combo = tuple(rows[r][1][idx[c]] for c in in_cols)
        ov = rows[rn][1][idx[out_col]]
        if any(b.lower() == "x" for b in combo) or ov.lower() == "x":
            continue
        prev = ns_seen.get(combo)
        if prev is not None and prev != ov:
            # Inputs-alone is inconsistent ⇒ the next-state needs the current state
            # (counter/toggle). That is OUT of this single-bit-observable envelope
            # (no faithful, uniquely-forced reading here) ⇒ SKIP. (§4.05.)
            return None
        ns_seen[combo] = ov
        if prev is None and ov == "1":
            ns_ones.append(combo)
        used += 1
    if used == 0 or not ns_seen:
        return None  # no usable registered transition observed -> SKIP

    in_orig = [ports[c][2] for c in in_cols]
    decl = []
    for nm in body:
        d, w, orig = ports[nm]
        if nm == out_col and d == "output":
            decl.append(f"    output reg {orig}")
        else:
            decl.append(f"    {d:<6} {orig}")
    lines = [f"module {top} (", ",\n".join(decl), ");", ""]
    lines.append(f"  always @(posedge {ports[clk][2]})")
    lines.append(f"    {ports[out_col][2]} <= {_wts._sop(in_orig, ns_ones)};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    """Return synthesized module text, or None to SKIP. Tries the
    combinational-by-consistency envelope, then the general single-posedge-FF
    envelope. Both paths DEFER to the canonical sibling on its owned cases."""
    return (_synth_combinational_byconsistency(prompt_text, top)
            or _synth_posedge_1ff(prompt_text, top))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    prompt = Path(a.prompt).read_text(errors="replace")
    rtl = synth(prompt, a.top)
    if rtl is None:
        print("SKIP: outside the waveform_ext synth envelope", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
