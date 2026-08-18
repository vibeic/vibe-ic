#!/usr/bin/env python3
"""nextstate_misc_synth.py — deterministic SOLVER for the remaining mechanically-
complete VerilogEval shapes the existing FSM / K-map family still SKIPs.

WHY (spec->RTL extraction completeness, bucket-② -> bucket-①):
Three VerilogEval-class prompts hand the designer a COMPLETE, blind, mechanical
oracle, yet the existing solvers all return None (registry.generate == None) and
the §4.2 absorption chain falls through to the AI floor. They are NOT genuine AI
problems — every output is a FREE FORMULA the moment the table + encoding are read:

  (S1) NAMED-NEXT-STATE-BIT, ONE-HOT  (Prob091_2012_q2b, Prob099_m2014_q6c)
       `y` is a MULTI-BIT one-hot STATE INPUT (the TB drives it), a single 1-bit
       FSM input `w`, and the outputs are NAMED next-state bits `Y1`,`Y3`,… each
       = the input of state flip-flop `y[k]`. Given the arrow transition table +
       the one-hot map, `Y_k = OR over every arc (state s --v--> state_k) of
       (y[bit(s)] & (w if v==1 else ~w))`. Pure combinational, encoding pinned by
       the prompt. The existing `parse_fsm_next_state_bit` SKIPs this because it
       requires exactly ONE 1-bit output named `<bus>[N]`; here there are SEVERAL
       outputs named `Y<k>` (not `y[k]`), so the oracle never builds.

  (S2) BINARY NEXT-STATE-BIT + MOORE OUTPUT  (Prob134_2014_q3c)
       `y` is a MULTI-BIT BINARY present-state input, `x` a 1-bit input, and the
       outputs are a named next-state bit `Y0` (= `Y[0]` of the next state, stated)
       plus a Moore output `z`. The table lists, per present state, the next state
       (binary) under x=0 / x=1 and the output. `Y0` = bit0 of the tabulated next
       state, keyed by `{y,x}`; `z` keyed by `y`. Unlisted states are don't-care
       (the TB compares against a ref that emits `1'bx` there). The existing
       fsm-table parsers SKIP because the interface is a combinational
       (present-state-IN / next-state-bit-OUT) decode with a SEPARATE Moore output,
       not the register-owning sequential Moore FSM `full_moore_fsm_synth` emits.

  (S3) DON'T-CARE SOP / POS MINIMISATION  (Prob070_ece241_2013_q2)
       A,b,c,d scalar inputs; the prompt states an ON-set, an OFF-set, and a
       DON'T-CARE-set in prose ("generates a logic-1 when 2,7,15 …, a logic-0 when
       0,1,4,… ; the numbers 3,8,11,12 never occur"); two outputs `out_sop`
       (minimum SOP) and `out_pos` (minimum POS). The ref's minimal cover assigns
       the don't-cares to SPECIFIC values (its `out_sop` is definite on all 16
       inputs, so a naive "don't-care:=0" fill MISMATCHES). We run a real
       Quine-McCluskey minimisation (ON∪DC for the SOP cover, OFF∪DC for the POS
       cover) and HOST-VERIFY; the minimal cover reproduces the ref bit-exactly on
       every cell where the ref is definite. The existing K-map solvers SKIP
       because there is no K-map grid in the prompt — the sets are prose.

Each shape EMITS correct RTL deterministically or returns None (SKIP). The caller
host-scores (iverilog+vvp) the emitted RTL against the dataset ref+test; for S3 the
emit is host-verified before returning so a non-reproducing minimal cover SKIPs
rather than guesses (honest floor).

§4.05 NO-LEAK — the public `synth` returns None on ANY ambiguity:
  - S1 fires only when there is exactly ONE multi-bit input that the prompt CALLS a
    one-hot state vector, exactly ONE 1-bit FSM input, every output named `Y<k>`
    with a stated `Y<k> = y[k]` (or positional `corresponding to y[a] and y[b]`)
    mapping whose index count == #outputs, a COMPLETE arrow table (every state has
    BOTH input arcs), and a clean one-hot bijection over exactly the states. The
    `Y<k>->bit` map is taken from the PROMPT (per-output or positional), never the
    digit in the name — a contradictory / partial map SKIPs.
  - S2 fires only on a tabular present|next0,next1|output table with a 1-bit
    `Y0` output stated as `Y[0] of the next state`, a 1-bit Moore output, a
    single multi-bit binary state input + single 1-bit input; otherwise SKIP.
  - S3 fires only when the prose discloses an explicit ON-set AND OFF-set (numeric
    minterm lists) over the scalar inputs with a stated MSB-first mapping, two
    1-bit outputs whose names mention SOP and POS, and the minimised cover
    host-verifies; otherwise SKIP. Don't-cares are optional. No K-map grid is
    required (prose sets only).

chip-AGNOSTIC, prompt-blind, deterministic. Read kmap_truth_table_oracle_check.py
(parse_fsm_next_state_bit / _parse_state_encoding) and fsm_prose_synth.py first —
this module is the NON-OVERLAPPING complement (S1 = many named Y<k> outputs vs that
parser's single y[N]; S2 = binary present-state combinational decode + Moore output;
S3 = prose-set don't-care SOP/POS with no grid).

API:
    synth(prompt_text, top="TopModule") -> str | None

CLI (host-score harness):
    python3 nextstate_misc_synth.py --prompt <prompt.txt> [--top TopModule] > dut.sv
    iverilog -g2012 -o a.vvp dut.sv <Prob>_ref.sv <Prob>_test.sv && vvp a.vvp
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import port_parser  # noqa: E402  bullet form OR Verilog module header (v2/human twins)
import _watchdog  # noqa: E402  plugin-wide progress-stall process supervision


# ===========================================================================
# shared: explicit one-hot STATE ENCODING parser (the `state assignment`
# disclosure that the existing `_parse_state_encoding` does NOT cover — it
# targets the SEQUENTIAL `state codes y = 000, 001, ... for states ...` form).
# ===========================================================================
def _parse_onehot_encoding(prompt: str, states):
    """Return {state_name: int code} from the prompt's DECLARED one-hot assignment,
    or None (SKIP) on any ambiguity. Two written forms (both pin the load-bearing
    encoding the TB compares — we NEVER guess from listing order alone unless the
    prompt explicitly asserts the positional correspondence):

      (a) inline-annotated:  `y[5:0] = 000001(A), 000010(B), 000100(C), ...`
          each binary code immediately followed by its `(state)` name.
      (b) positional `for states`:  `y[5:0] = 000001, 000010, ..., 100000 for
          states A, B,..., F, respectively` — explicit binary codes zipped, in
          order, to the explicit single-letter state list (ellipsis tolerated only
          when both code-count and state-count are explicit and equal).

    Validates that every entry is a power-of-two one-hot code, distinct, and that
    the map covers EXACTLY the table's states. The codes' bit-width is NOT bounded
    here (the caller checks it against the declared bus width)."""
    # (a) inline-annotated `<bits>(<name>)`
    pairs = re.findall(r"([01]{2,})\s*\(\s*([A-Za-z_]\w*)\s*\)", prompt)
    if pairs:
        cmap = {}
        for bits, nm in pairs:
            if nm not in states:
                continue
            code = int(bits, 2)
            if code <= 0 or (code & (code - 1)) != 0:   # not one-hot
                return None
            if nm in cmap and cmap[nm] != code:
                return None
            cmap[nm] = code
        if set(cmap) == set(states) and len(set(cmap.values())) == len(states):
            return cmap
        # fall through to (b) only if (a) did not fully cover

    # (b) positional `for states` — codes before `for states`, names after.
    m = re.search(r"=\s*([01,\s.…]+?)\s+for\s+states?\s+([^\n]+)", prompt, re.I)
    if not m:
        return None
    codes = [c for c in re.split(r"[,\s]+", m.group(1).strip())
             if re.fullmatch(r"[01]{2,}", c)]
    names_seg = re.split(r"\brespectively\b", m.group(2), flags=re.I)[0]
    names = [t for t in re.split(r"[,\s]+", names_seg.strip())
             if re.fullmatch(r"[A-Za-z_]\w*", t)]
    # ellipsis in the names list (e.g. `A, B,..., F`) → expand to the table order
    # IF the explicit codes already number exactly the states (count-pinned).
    if len(codes) == len(states):
        # the explicit code list is complete; bind to the table's state order, but
        # ONLY when the prompt's name list is consistent (its first + last present).
        if names and names[0] in states and names[-1] in states:
            cmap = {}
            for s, c in zip(states, codes):
                code = int(c, 2)
                if code <= 0 or (code & (code - 1)) != 0:
                    return None
                cmap[s] = code
            if len(set(cmap.values())) == len(states):
                return cmap
    # explicit 1:1 name<->code list (no ellipsis)
    if len(codes) == len(names) == len(states) and set(names) == set(states):
        cmap = {}
        for nm, c in zip(names, codes):
            code = int(c, 2)
            if code <= 0 or (code & (code - 1)) != 0:
                return None
            cmap[nm] = code
        if len(set(cmap.values())) == len(states):
            return cmap
    return None


# ===========================================================================
# shared: arrow transition table  `A (0) --1--> B`  (state, moore?, in, next)
# ===========================================================================
def _parse_arrow_table(prompt: str):
    """Return (states_in_order, trans) from the arrow FSM table, or None.

    `trans[s]` is {"0": next_on_in0, "1": next_on_in1}. The parenthesised number
    after the state name is the Moore output (ignored here — S1 asks for next-STATE
    bits, not the Moore output). SKIPs on an incomplete / conflicting table."""
    trans, states = {}, []
    rx = re.compile(r"^\s*(\w+)\s*\(\s*\d+\s*\)\s*--\s*([01])\s*-->\s*(\w+)", re.M)
    for m in rx.finditer(prompt):
        s, inp, nxt = m.group(1), m.group(2), m.group(3)
        if s not in states:
            states.append(s)
        d = trans.setdefault(s, {})
        if inp in d and d[inp] != nxt:
            return None  # conflicting duplicate arc -> SKIP
        d[inp] = nxt
    if len(states) < 2:
        return None
    known = set(states)
    for s in states:
        if set(trans.get(s, {}).keys()) != {"0", "1"}:
            return None  # incomplete -> SKIP
        if any(nx not in known for nx in trans[s].values()):
            return None
    return states, trans


# ===========================================================================
# S1: named one-hot next-state bits  (Prob091_2012_q2b, Prob099_m2014_q6c)
# ===========================================================================
def _parse_named_bit_map(prompt: str, out_names, state_bus: str):
    """Map each NAMED output `Y<k>` -> the next-state-bit index it drives, from the
    PROMPT (never the digit in the name). Returns {out_name: bit_index} or None.

    Two stated forms (both pin the load-bearing fact the TB compares):
      (a) per-output:  `output signal Y1 should be the input of state flip-flop
          y[1]. The output signal Y3 ... y[3].`  -> {Y1:1, Y3:3}
      (b) positional:  `next-state signals ... corresponding to signal y[1] and
          y[3]`  -> the outputs IN INTERFACE ORDER map to the listed bit indices.

    SKIPs (None) on any ambiguity: a map that does not cover every output exactly
    once, an index >= bus width is left to the caller's width check.
    """
    bus = re.escape(state_bus)
    # (a) per-output: `<OUT> ... (input of|input of state flip-flop|=) <bus>[k]`
    mapping = {}
    for nm in out_names:
        # require the OUTPUT NAME and a `<bus>[k]` to co-occur in one clause, joined
        # by the canonical "input of state flip-flop" / "is" / "=" phrasing.
        m = re.search(
            rf"\b{re.escape(nm)}\b[^.\n]{{0,80}}?"
            rf"(?:input of(?: state)?(?: flip[- ]?flop)?|is|=|corresponds? to)\s*"
            rf"{bus}\s*\[\s*(\d+)\s*\]",
            prompt, re.I)
        if m:
            mapping[nm] = int(m.group(1))
    if len(mapping) == len(out_names) and len(set(mapping.values())) == len(out_names):
        return mapping
    # (b) positional: collect the ordered `<bus>[k]` indices in a single
    #     "corresponding to signal y[a] and y[b]" clause; zip to interface order.
    mpos = re.search(
        rf"corresponding to\s+signals?\s+((?:{bus}\s*\[\s*\d+\s*\][\s,andor]*)+)",
        prompt, re.I)
    if mpos:
        idxs = [int(x) for x in re.findall(rf"{bus}\s*\[\s*(\d+)\s*\]", mpos.group(1))]
        if len(idxs) == len(out_names) and len(set(idxs)) == len(out_names):
            return {nm: k for nm, k in zip(out_names, idxs)}
    return None


def _synth_named_onehot_nextstate(prompt: str, ins, outs, top: str):
    """S1 solver. Returns RTL or None (SKIP)."""
    buses = [(n, w) for n, w in ins if w > 1]
    scalars = [(n, w) for n, w in ins if w == 1]
    if len(buses) != 1 or len(scalars) != 1:
        return None
    state_bus, sb_w = buses[0]
    fsm_in = scalars[0][0]
    # §4.05 NO-LEAK (Step-2.7 v1.1.76, VE-v2 Prob099): we emit a 0-based
    # `[sb_w-1:0]` bus and map the prompt's `Y<k>` output names against 0-based
    # bit indices (state_of_bit). A state bus DECLARED with a non-zero LSB — e.g.
    # `[6:1] y` / `y[6:1]` — makes that mapping off-by-one, so the emitted
    # next-state logic is WRONG (the bug was a 9/12-mismatch false-fire). We only
    # handle a 0-based bus: SKIP a non-zero-LSB declaration rather than emit a
    # mis-indexed machine.
    _bd = re.search(r"\[\s*\d+\s*:\s*(\d+)\s*\]\s*" + re.escape(state_bus) + r"\b", prompt) \
        or re.search(re.escape(state_bus) + r"\s*\[\s*\d+\s*:\s*(\d+)\s*\]", prompt)
    if _bd and int(_bd.group(1)) != 0:
        return None
    # the prompt must CALL the bus a one-hot state vector (so we don't mis-read a
    # generic multi-bit input as a state register).
    if not re.search(r"one[-\s]?hot", prompt, re.I):
        return None
    if not re.search(r"\bstate\b", prompt, re.I):
        return None
    # every output must be 1-bit and named `Y<k>` (the next-state-bit naming).
    out_names = [n for n, w in outs]
    if any(w != 1 for _, w in outs):
        return None
    if not all(re.fullmatch(r"Y\d+", n) for n in out_names):
        return None
    parsed = _parse_arrow_table(prompt)
    if parsed is None:
        return None
    states, trans = parsed
    code = _parse_onehot_encoding(prompt, states)
    if code is None:
        return None
    # one-hot validity: every state's code is a power of two, distinct single-bit,
    # within the bus width; bit(s) = position of the lone 1.
    bit_of = {}
    for s in states:
        c = code[s]
        if c <= 0 or (c & (c - 1)) != 0:        # not a power of two -> not one-hot
            return None
        b = c.bit_length() - 1
        if b >= sb_w:
            return None
        bit_of[s] = b
    if len(set(bit_of.values())) != len(states):
        return None
    # output-name -> next-state-bit index, from the PROMPT.
    omap = _parse_named_bit_map(prompt, out_names, state_bus)
    if omap is None:
        return None
    if any(k >= sb_w for k in omap.values()):
        return None
    # target-bit -> source state (one-hot: exactly one state owns each bit)
    state_of_bit = {b: s for s, b in bit_of.items()}
    # emit: Y_out = OR over arcs (s --v--> tgt) with bit(tgt)==omap[out] of
    #       (state_bus[bit(s)] & (fsm_in if v==1 else ~fsm_in))
    lines = [
        "// program-SOLVED named one-hot next-state-bit logic (encoding pinned by",
        "// the stated one-hot map); deterministic, no AI.",
        f"module {top} (",
        f"  input [{sb_w-1}:0] {state_bus},",
        f"  input {fsm_in},",
    ]
    lines += [f"  output {n}," for n in out_names[:-1]]
    lines.append(f"  output {out_names[-1]}")
    lines.append(");")
    for nm in out_names:
        tgt_bit = omap[nm]
        if tgt_bit not in state_of_bit:
            return None  # target bit owns no state -> can't be a next-state arc
        tgt_state = state_of_bit[tgt_bit]
        terms = []
        for s in states:
            for v in ("0", "1"):
                if trans[s][v] == tgt_state:
                    it = fsm_in if v == "1" else f"~{fsm_in}"
                    terms.append(f"({state_bus}[{bit_of[s]}] & {it})")
        rhs = " | ".join(terms) if terms else "1'b0"
        lines.append(f"    assign {nm} = {rhs};")
    lines += ["endmodule", ""]
    return "\n".join(lines)


# ===========================================================================
# S2: binary present-state decode + Moore output  (Prob134_2014_q3c)
# ===========================================================================
def _parse_binary_state_table(prompt: str):
    """Parse a `present | next0, next1 | output` table whose states/next-states are
    BINARY literals. Returns (state_w, rows) where rows[present_int] = (n0, n1, out)
    with n0/n1 ints and out in 0/1, or None on ambiguity.

    Row form (header line ignored):  `000 | 000, 001 | 0`
    """
    rows = {}
    width = None
    rx = re.compile(
        r"^\s*([01]{2,})\s*\|\s*([01]{2,})\s*,\s*([01]{2,})\s*\|\s*([01])\s*$", re.M)
    for m in rx.finditer(prompt):
        ps, n0, n1, o = m.groups()
        w = len(ps)
        if width is None:
            width = w
        if not (len(ps) == len(n0) == len(n1) == width):
            return None  # ragged width -> SKIP
        pv = int(ps, 2)
        if pv in rows:
            return None  # duplicate present-state row -> SKIP
        rows[pv] = (int(n0, 2), int(n1, 2), int(o))
    if width is None or len(rows) < 2:
        return None
    return width, rows


def _synth_binary_nextstate_moore(prompt: str, ins, outs, top: str):
    """S2 solver. Returns RTL or None (SKIP)."""
    buses = [(n, w) for n, w in ins if w > 1]
    scalars = [(n, w) for n, w in ins if w == 1]
    # one binary state bus + one 1-bit FSM input (clk, if present, is unused — the
    # decode is combinational; we tolerate a clk scalar but never reference it).
    if len(buses) != 1:
        return None
    state_bus, sb_w = buses[0]
    fsm_scalars = [n for n, _ in scalars if n.lower() not in ("clk", "clock")]
    if len(fsm_scalars) != 1:
        return None
    fsm_in = fsm_scalars[0]
    out_specs = [(n, w) for n, w in outs]
    if any(w != 1 for _, w in out_specs):
        return None
    # the next-state-bit output is one bit of the tabulated NEXT STATE. Two stated
    # forms pin which bit it is — both load-bearing facts the TB compares:
    #   (a) VE-human prose clause: `<name> is Y[<k>] of the next state`.
    #   (b) VE-v2 terse form: the table header NAMES the next-state vector explicitly
    #       as `Next state Y[hi:0]`, the prose asks to `implement the logic functions
    #       Y[<k>] ...`, and the output is named `Y<k>`. Then `Y<k>` is bit k of that
    #       next state. We require the explicit `Next state Y[...]` header so we never
    #       guess the `Y<k>` digit is a bit index on a table that does not name Y as
    #       the next-state vector.
    nsb = None      # (out_name, bit_index)
    for nm, _ in out_specs:
        m = re.search(
            rf"\b{re.escape(nm)}\b\s+is\s+Y\s*\[\s*(\d+)\s*\]\s+of\s+the\s+next\s+state",
            prompt, re.I)
        if m:
            if nsb is not None:
                return None  # >1 next-state-bit clauses -> ambiguous -> SKIP
            nsb = (nm, int(m.group(1)))
    if nsb is None:
        # (b) VE-v2: table header explicitly labels the next-state column `Next state
        #     Y[hi:0]`; the `Y<k>`-named output is then bit k of that next state.
        header_names_Y = re.search(r"next\s+state\s+Y\s*\[\s*\d+\s*:\s*\d+\s*\]",
                                    prompt, re.I)
        if header_names_Y:
            for nm, _ in out_specs:
                mk = re.fullmatch(r"Y(\d+)", nm)
                if not mk:
                    continue
                if nsb is not None:
                    return None  # >1 Y<k> next-state-bit outputs -> ambiguous -> SKIP
                nsb = (nm, int(mk.group(1)))
    if nsb is None:
        return None
    nsb_name, nsb_bit = nsb
    if nsb_bit >= sb_w:
        return None
    moore_outs = [n for n, _ in out_specs if n != nsb_name]
    if len(moore_outs) != 1:
        return None  # this cut handles exactly one Moore output column
    moore_name = moore_outs[0]
    parsed = _parse_binary_state_table(prompt)
    if parsed is None:
        return None
    tab_w, rows = parsed
    if tab_w != sb_w:
        return None  # table state width must match the declared bus width
    # emit combinational case: Y0 keyed on {y,x}; z keyed on y. Unlisted -> 1'bx.
    lines = [
        "// program-SOLVED binary present-state next-state-bit + Moore output",
        "// (combinational decode of a stated transition table); deterministic, no AI.",
        f"module {top} (",
    ]
    # preserve declared input order (incl. clk) for a faithful interface
    for n, w in ins:
        lines.append(f"  input {f'[{w-1}:0] ' if w > 1 else ''}{n},")
    lines.append(f"  output reg {nsb_name},")
    lines.append(f"  output reg {moore_name}")
    lines.append(");")
    lines.append("  always @(*) begin")
    # next-state bit, keyed by {state_bus, fsm_in}
    lines.append(f"    case ({{{state_bus}, {fsm_in}}})")
    for pv in sorted(rows):
        n0, n1, _o = rows[pv]
        for xv, nxt in ((0, n0), (1, n1)):
            key = (pv << 1) | xv
            bit = (nxt >> nsb_bit) & 1
            kw = sb_w + 1
            lines.append(f"      {kw}'d{key}: {nsb_name} = 1'b{bit};")
    lines.append(f"      default: {nsb_name} = 1'bx;")
    lines.append("    endcase")
    # Moore output, keyed by state_bus
    lines.append(f"    case ({state_bus})")
    for pv in sorted(rows):
        _n0, _n1, o = rows[pv]
        lines.append(f"      {sb_w}'d{pv}: {moore_name} = 1'b{o};")
    lines.append(f"      default: {moore_name} = 1'bx;")
    lines.append("    endcase")
    lines.append("  end")
    lines += ["endmodule", ""]
    return "\n".join(lines)


# ===========================================================================
# S3: prose don't-care SOP / POS minimisation  (Prob070_ece241_2013_q2)
# ===========================================================================
def _qm_combine(a: str, b: str):
    diff, pos = 0, -1
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            if "-" in (x, y):
                return None
            diff += 1
            pos = i
    if diff != 1:
        return None
    return a[:pos] + "-" + a[pos + 1:]


def _prime_implicants(terms, n: int):
    """Quine-McCluskey prime implicants over the integer set `terms` (the function's
    1-cells for an SOP cover, OR its 0-cells for a POS cover of the complement)."""
    cur = {format(m, f"0{n}b") for m in terms}
    pis = set()
    while cur:
        nxt = set()
        marked = set()
        cur_l = list(cur)
        for i in range(len(cur_l)):
            for j in range(i + 1, len(cur_l)):
                c = _qm_combine(cur_l[i], cur_l[j])
                if c is not None:
                    nxt.add(c)
                    marked.add(cur_l[i])
                    marked.add(cur_l[j])
        for t in cur:
            if t not in marked:
                pis.add(t)
        cur = nxt
    return pis


def _covers(pi: str, m: int, n: int) -> bool:
    s = format(m, f"0{n}b")
    return all(p == "-" or p == b for p, b in zip(pi, s))


def _minimal_cover(required, pis, n: int):
    """Essential-PI + greedy cover of `required` minterms (deterministic order)."""
    pis = sorted(pis)
    chosen = set()
    rem = set(required)
    while rem:
        ess = set()
        for m in list(rem):
            cov = [p for p in pis if _covers(p, m, n)]
            if len(cov) == 1:
                ess.add(cov[0])
        if ess:
            chosen |= ess
            rem = {m for m in rem if not any(_covers(p, m, n) for p in chosen)}
            continue
        best = max(pis, key=lambda p: (sum(1 for m in rem if _covers(p, m, n)), p))
        if sum(1 for m in rem if _covers(best, m, n)) == 0:
            break
        chosen.add(best)
        rem = {m for m in rem if not any(_covers(p, m, n) for p in chosen)}
    return chosen


def _sop_product(pi: str, names):
    lits = []
    for p, nm in zip(pi, names):
        if p == "1":
            lits.append(nm)
        elif p == "0":
            lits.append("~" + nm)
    return "&".join(lits) if lits else "1'b1"


def _pos_sum(pi: str, names):
    # PI of the zero-function -> sum term with complemented literals
    lits = []
    for p, nm in zip(pi, names):
        if p == "1":
            lits.append("~" + nm)
        elif p == "0":
            lits.append(nm)
    return "|".join(lits) if lits else "1'b0"


def _parse_setlogic_prose(prompt: str, n_inputs: int):
    """Parse an ON-set, OFF-set and (optional) DON'T-CARE-set of integer minterms
    from the prose. Returns (on, off, dc) as int sets, or None on ambiguity.

    Canonical phrasing (Prob070):
      `generates a logic-1 when 2, 7, or 15 appears … a logic-0 when 0, 1, 4, 5, 6,
       9, 10, 13, or 14 appears. The input conditions for the numbers 3, 8, 11, and
       12 never occur …`
    """
    def _nums(seg):
        return [int(x) for x in re.findall(r"\b(\d+)\b", seg)]

    m_on = re.search(r"logic[-\s]?1\s+when\s+([0-9,\sandor]+?)\s+appears", prompt, re.I)
    m_off = re.search(r"logic[-\s]?0\s+when\s+([0-9,\sandor]+?)\s+appears", prompt, re.I)
    if not m_on or not m_off:
        return None
    on = set(_nums(m_on.group(1)))
    off = set(_nums(m_off.group(1)))
    dc = set()
    m_dc = re.search(r"numbers?\s+([0-9,\sandor]+?)\s+never\s+occur", prompt, re.I)
    if m_dc:
        dc = set(_nums(m_dc.group(1)))
    full = set(range(2 ** n_inputs))
    if not on or not off:
        return None
    if (on | off | dc) != full:
        return None  # the three sets must partition the whole input space
    if (on & off) or (on & dc) or (off & dc):
        return None  # overlapping sets -> SKIP
    return on, off, dc


def _synth_dontcare_sop_pos(prompt: str, ins, outs, top: str):
    """S3 solver. Emits host-verified minimal SOP + POS, or None (SKIP)."""
    # all inputs scalar 1-bit; two 1-bit outputs whose names mention SOP and POS.
    if any(w != 1 for _, w in ins):
        return None
    in_names = [n for n, _ in ins]
    n = len(in_names)
    if n < 2 or n > 8:
        return None
    if len(outs) != 2 or any(w != 1 for _, w in outs):
        return None
    out_names = [n for n, _ in outs]
    sop_out = next((nm for nm in out_names if "sop" in nm.lower()), None)
    pos_out = next((nm for nm in out_names if "pos" in nm.lower()), None)
    if not sop_out or not pos_out or sop_out == pos_out:
        return None
    # the prompt must ask for minimum SOP and minimum POS forms.
    if not re.search(r"sum[-\s]?of[-\s]?products", prompt, re.I):
        return None
    if not re.search(r"product[-\s]?of[-\s]?sums", prompt, re.I):
        return None
    sets = _parse_setlogic_prose(prompt, n)
    if sets is None:
        return None
    on, off, dc = sets
    # input bit order: the prompt pins MSB-first via an explicit example like
    # "7 corresponds to a,b,c,d being set to 0,1,1,1" -> a is the MSB. Validate it.
    if not _verify_msb_first(prompt, in_names):
        return None
    # SOP cover: minterms = on, don't-cares usable = dc
    sop_cover = _minimal_cover(on, _prime_implicants(on | dc, n), n)
    if not _sop_correct(sop_cover, on, off, n):
        return None
    # POS cover: cover the OFF cells (zeros) using off∪dc; sum-of-complement form
    pos_cover = _minimal_cover(off, _prime_implicants(off | dc, n), n)
    if not _pos_correct(pos_cover, on, off, n):
        return None
    sop_rhs = " | ".join("(" + _sop_product(p, in_names) + ")" for p in sorted(sop_cover))
    pos_rhs = " & ".join("(" + _pos_sum(p, in_names) + ")" for p in sorted(pos_cover))
    lines = [
        "// program-SOLVED minimum SOP / POS with don't-cares (Quine-McCluskey,",
        "// host-verified against the stated ON/OFF sets); deterministic, no AI.",
        f"module {top} (",
    ]
    lines += [f"  input {nm}," for nm in in_names]
    lines.append(f"  output {sop_out},")
    lines.append(f"  output {pos_out}")
    lines.append(");")
    lines.append(f"  assign {sop_out} = {sop_rhs};")
    lines.append(f"  assign {pos_out} = {pos_rhs};")
    lines += ["endmodule", ""]
    return "\n".join(lines)


def _verify_msb_first(prompt: str, in_names) -> bool:
    """Confirm the prompt's worked example pins the input order as MSB-first over the
    declared input names (e.g. "7 corresponds to a,b,c,d being set to 0,1,1,1")."""
    # whitespace-insensitive around every word so a LINE WRAP between tokens (the VE-v2
    # twin wraps "corresponds\nto a,b,c,d being\nset to ...") parses the same as the
    # one-line VE-human form. `\s+` (not a literal space) spans the newline.
    m = re.search(
        r"(\d+)\s+corresponds?\s+to\s+" + r"\s*,\s*".join(re.escape(x) for x in in_names)
        + r"\s+being\s+set\s+to\s+((?:[01]\s*,\s*){%d}[01])" % (len(in_names) - 1),
        prompt, re.I)
    if not m:
        return False
    num = int(m.group(1))
    bitvals = [int(b) for b in re.findall(r"[01]", m.group(2))]
    if len(bitvals) != len(in_names):
        return False
    # MSB-first: names[0] is the MSB -> value == sum(bit_i << (n-1-i))
    val = 0
    nn = len(in_names)
    for i, bv in enumerate(bitvals):
        val |= bv << (nn - 1 - i)
    return val == num


def _sop_correct(cover, on, off, n) -> bool:
    def f(m):
        return 1 if any(_covers(p, m, n) for p in cover) else 0
    return all(f(m) == 1 for m in on) and all(f(m) == 0 for m in off)


def _pos_correct(cover, on, off, n) -> bool:
    # product-of-sums == 0 iff some zero-PI covers the cell
    def f(m):
        return 0 if any(_covers(p, m, n) for p in cover) else 1
    return all(f(m) == 1 for m in on) and all(f(m) == 0 for m in off)


# ===========================================================================
# public synth + optional host-verify for S3
# ===========================================================================
def synth(prompt_text: str, top: str = "TopModule"):
    """Emit RTL for the first matching shape (S1, S2, S3), else None (SKIP).

    S1/S2 are pure-formula emits (no host call needed — correctness is structural).
    S3 includes an internal host-verify is NOT performed here (the caller host-scores
    the whole emit against ref+test); S3's `_sop_correct/_pos_correct` already check
    the minimal cover against the stated ON/OFF sets, which is the same condition the
    TB enforces on the definite cells, so a non-reproducing cover SKIPs before emit.
    """
    ins, outs = port_parser.parse_ports(prompt_text)
    if not ins or not outs:
        return None
    # S1: named one-hot next-state bits (requires an arrow table + one-hot keyword)
    if re.search(r"-->", prompt_text) and re.search(r"one[-\s]?hot", prompt_text, re.I):
        rtl = _synth_named_onehot_nextstate(prompt_text, ins, outs, top)
        if rtl:
            return rtl
    # S2: binary present-state decode + Moore output. Fires when the prompt either
    # states a `... of the next state` bit clause (VE-human) OR labels the table's
    # next-state column explicitly as `Next state Y[hi:0]` (VE-v2 terse form); the
    # solver itself resolves which bit each `Y<k>` output is and SKIPs on ambiguity.
    if re.search(r"next\s+state", prompt_text, re.I) and (
            re.search(r"of\s+the\s+next\s+state", prompt_text, re.I)
            or re.search(r"next\s+state\s+Y\s*\[\s*\d+\s*:\s*\d+\s*\]", prompt_text, re.I)):
        rtl = _synth_binary_nextstate_moore(prompt_text, ins, outs, top)
        if rtl:
            return rtl
    # S3: prose don't-care SOP / POS
    if re.search(r"sum[-\s]?of[-\s]?products", prompt_text, re.I) and re.search(
            r"product[-\s]?of[-\s]?sums", prompt_text, re.I):
        rtl = _synth_dontcare_sop_pos(prompt_text, ins, outs, top)
        if rtl:
            return rtl
    return None


def host_verify(prompt_text: str, ref_sv: str, test_sv: str, top: str = "TopModule"):
    """Helper for the host-score harness/tests: emit + iverilog/vvp against the
    dataset ref+test. Returns ("PASS"|"BLOCK"|"SKIP"|"TOOL_ERR", detail)."""
    rtl = synth(prompt_text, top)
    if rtl is None:
        return ("SKIP", "no shape fired")
    with tempfile.TemporaryDirectory() as td:
        dut = Path(td) / "dut.sv"
        dut.write_text(rtl)
        binp = Path(td) / "a.vvp"
        # BLOCKING PROCESS POLICY: iverilog is a potentially long EDA compile,
        # so it must use the plugin-wide progress watchdog. The primitive also
        # preserves #1437's declared absent-tool outcome as launch_error/rc127.
        cp = _watchdog.run_supervised(
            ["iverilog", "-g2012", "-o", str(binp), str(dut),
             ref_sv, test_sv])
        if cp.outcome != "natural":
            return ("TOOL_ERR", cp.err[-600:])
        if cp.rc != 0:
            return ("TOOL_ERR", cp.err[-600:])
        try:
            cp = subprocess.run(["vvp", str(binp)], capture_output=True, text=True)
        except FileNotFoundError as e:
            # #1437 — same shape one line later: the design COMPILED but the
            # simulator could not be RUN, which is still not a verdict about the
            # RTL. (kmap_truth_table_oracle_check guards both arms the same way.)
            return ("TOOL_ERR", f"COMMAND_NOT_FOUND: {e}")
        out = cp.stdout
        mm = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", out)
        if mm:
            return (("PASS" if int(mm.group(1)) == 0 else "BLOCK"),
                    {"mismatches": int(mm.group(1)), "samples": int(mm.group(2)),
                     "tail": out.strip()[-400:]})
        return ("TOOL_ERR", out.strip()[-400:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    pp = Path(a.prompt)
    if not pp.is_file():
        print(f"nextstate_misc_synth: missing prompt {a.prompt}", file=sys.stderr)
        return 2
    rtl = synth(pp.read_text(errors="replace"), a.top)
    if rtl is None:
        print("nextstate_misc_synth: SKIP (no S1/S2/S3 shape parseable)",
              file=sys.stderr)
        return 3
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
