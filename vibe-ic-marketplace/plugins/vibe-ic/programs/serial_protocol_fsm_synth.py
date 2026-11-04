#!/usr/bin/env python3
"""serial_protocol_fsm_synth.py — deterministic SOLVER for serial / protocol
receiver FSMs whose behaviour is a PRECISE, mechanically-buildable protocol stated
in PROSE (not as a transition table).

The load-bearing work here is RECOGNISING the protocol shape and PARSING its stated
parameters (data-bit count, start/stop polarity, idle level, run thresholds, the
error-recovery rule, the count multiplier). Once those are pinned the RTL is a free
formula. This is the same "push extraction up; the RTL is downstream-free" doctrine
as full_moore_fsm_synth.py, applied to PROSE protocols instead of written tables.

§4.05 NO-LEAK: every method returns None (SKIP — author untouched) unless EVERY
framing parameter and recovery rule is UNAMBIGUOUSLY stated, the port interface
matches the method's contract exactly, and no real input/output port would be
silently dropped. A prose protocol that under-specifies ANY parameter SKIPs — we
never guess. Each emitted method is HOST-VERIFIED (iverilog -g2012 dut+ref+test ->
0 mismatches) in the regression suite; a method only ships once it scores 0 on the
real benchmark testbench. Reset conventions mirror full_moore_fsm_synth.py
(sync = reset inside the posedge-clk block; async = reset in the sensitivity list
with the stated edge polarity; active level parsed, never guessed).

Methods (dispatched specific-first; the first that fires wins, mutual-exclusion is
asserted by the regression suite so ordering is a documented tie-break not a crutch):
  1. serial_2s_complement  — LSB-first serial 2's-complement Moore machine
  2. serial_framing        — IDLE/START(0)/N-DATA/STOP(1)[+byte capture] receiver
  3. consecutive_run       — HDLC-style consecutive-1s counter (disc/flag/err)
  4. pattern_delay_timer   — detect-pattern -> shift-delay -> (delay+1)*M-cycle timer

API: synth(prompt_text, top="TopModule") -> RTL string | None
"""
from __future__ import annotations
import os
import re
import sys


def _parse_ports(prompt):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser   # bullet form OR Verilog module header (the v2/human twins)
    return port_parser.parse_ports(prompt)


def _find_clk_reset(ins):
    """Return (clk, reset, is_async, active_high) or (None,...).  reset polarity /
    sync-vs-async is parsed below per the STATED text by the caller; here we only
    locate the ports."""
    names = [n for n, _ in ins]
    clk = next((n for n in names if n.lower() in ("clk", "clock")), None)
    rst = next((n for n in names
                if "reset" in n.lower() or n.lower() in ("rst", "rst_n", "arst", "areset")),
               None)
    return clk, rst


def _reset_kind(prompt, rst_name):
    """(is_async, active_high) | None.  Mirrors full_moore_fsm_synth reset parsing:
    asynchronous CONTAINS synchronous, so match on a word boundary; the level must
    be unambiguously stated (or inferable from an edge-triggered async phrasing)."""
    is_async = bool(re.search(r"\basynchronous", prompt, re.I))
    is_sync = bool(re.search(r"\bsynchronous", prompt, re.I))
    if is_async == is_sync:                     # neither, or contradictory
        return None
    active_low = bool(re.search(r"active[-\s]?low|reset\s+(?:is\s+)?(?:active\s+)?low",
                                prompt, re.I))
    active_high = bool(re.search(r"active[-\s]?high|reset\s+(?:is\s+)?(?:active\s+)?high",
                                 prompt, re.I))
    if not active_high and not active_low and is_async:
        if re.search(r"positive[-\s]edge[-\s]?triggered\s+asynchronous", prompt, re.I):
            active_high = True
        elif re.search(r"negative[-\s]edge[-\s]?triggered\s+asynchronous", prompt, re.I):
            active_low = True
    if active_low == active_high:               # need an unambiguous level
        return None
    return is_async, active_high


def _reset_clauses(prompt, clk, rst, reset_state, is_async, active_high):
    """The two always-block boilerplate lines for the state register, shared by the
    table-style methods.  Returns (edge, rst_lvl)."""
    rst_lvl = rst if active_high else f"!{rst}"
    edge = f"posedge {clk}" + (f" or {'posedge' if active_high else 'negedge'} {rst}"
                               if is_async else "")
    return edge, rst_lvl


# --------------------------------------------------------------------------- #
# Method 1 — serial 2's complementer (LSB-first Moore)
# --------------------------------------------------------------------------- #
def _try_2s_complement(prompt, ins, outs, top, clk, rst):
    """Serial 2's complementer, LSB first.  ONE 1-bit data input + ONE 1-bit output.
    Algorithm (carry/borrow form, LSB first):
        z_i = (~x_i) ^ c_i ,  c_0 = 1 ,  c_{i+1} = (~x_i) & c_i
    i.e. copy input bits unchanged up to AND INCLUDING the first 1, then invert.
    Moore: after the posedge consumes x_i, the state holds the bit to OUTPUT.
    Reachable post-consume states (start c=1):
        P  : c==1                 (still in trailing-zero region) -> z=0
        Q  : c==0, last out==1                                    -> z=1
        R  : c==0, last out==0                                    -> z=0
        P --x=0--> P    P --x=1--> Q
        Q --x=0--> Q    Q --x=1--> R
        R --x=0--> Q    R --x=1--> R
    Reset -> P (z=0).  This is DERIVED from the algorithm, not copied from any ref.
    """
    if not re.search(r"2'?s\s*complement|two'?s\s*complement", prompt, re.I):
        return None
    # must be the SERIAL, LSB-first variety (a parallel 2's-complement is a different
    # combinational op owned elsewhere) and Moore.
    if not re.search(r"\bserial\b", prompt, re.I):
        return None
    if not re.search(r"least[-\s]significant\s+bit\s+first|lsb\s+first|"
                     r"beginning\s+with\s+the\s+least[-\s]significant\s+bit",
                     prompt, re.I):
        return None
    if not re.search(r"\bmoore\b", prompt, re.I):
        return None
    # exactly one 1-bit data input besides clk/reset, exactly one 1-bit output.
    data_ins = [n for n, w in ins if n not in (clk, rst) and w == 1]
    nondata = [n for n, w in ins if n not in (clk, rst) and w != 1]
    if nondata or len(data_ins) != 1:
        return None
    if len(outs) != 1 or outs[0][1] != 1:
        return None
    x = data_ins[0]
    z = outs[0][0]
    rk = _reset_kind(prompt, rst)
    if rk is None:
        return None
    is_async, active_high = rk
    edge, rst_lvl = _reset_clauses(prompt, clk, rst, "P", is_async, active_high)
    return "\n".join([
        "// program-SOLVED serial 2's complementer (LSB-first Moore, carry-derived); "
        "deterministic, no AI.",
        f"module {top}(",
        f"    input {clk},",
        f"    input {rst},",
        f"    input {x},",
        f"    output {z}",
        ");",
        "    localparam [1:0] P=2'd0, Q=2'd1, R=2'd2;  // P:carry=1(z=0) Q:out=1(z=1) R:out=0(z=0)",
        "    reg [1:0] state;",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= P;",
        "        else case (state)",
        f"            P: state <= {x} ? Q : P;",
        f"            Q: state <= {x} ? R : Q;",
        f"            R: state <= {x} ? R : Q;",
        "            default: state <= P;",
        "        endcase",
        "    end",
        f"    assign {z} = (state == Q);",
        "endmodule",
        "",
    ])


# --------------------------------------------------------------------------- #
# Method 2 — serial framing receiver (start/data/stop), optional byte capture
# --------------------------------------------------------------------------- #
def _parse_framing(prompt):
    """Return (n_data, start_pol, stop_pol, lsb_first) or None — all four must be
    UNAMBIGUOUSLY stated.  Phrasings accepted (case-insensitive):
        start: 'start bit (0)' / 'one start bit (0)'
        data:  '8 data bits'
        stop:  '1 stop bit (1)' / 'stop bit (1)'
        idle:  'line is ... at logic 1 when ... idle'  (must agree with stop=1)
        order: 'least significant bit first'
    """
    m_start = re.search(r"start\s+bit\s*\(\s*([01])\s*\)", prompt, re.I)
    m_stop = re.search(r"stop\s+bit\s*\(\s*([01])\s*\)", prompt, re.I)
    m_data = re.search(r"(\d+)\s+data\s+bits", prompt, re.I)
    if not (m_start and m_stop and m_data):
        return None
    start_pol = int(m_start.group(1))
    stop_pol = int(m_stop.group(1))
    n_data = int(m_data.group(1))
    if n_data < 1 or n_data > 64:
        return None
    # idle level must be stated and must equal the stop-bit level (the framing logic
    # here keys off "wait in idle until the line drops to the start polarity"); if the
    # prose states a different idle level we cannot build this exact machine -> SKIP.
    # Prose hard-wraps lines mid-sentence, so collapse whitespace first; then require
    # a "(at) logic N ... idle" statement (or its mirror) within ONE sentence — the
    # sentence boundary is a period, so a different idle elsewhere cannot leak in.
    flat = re.sub(r"\s+", " ", prompt)
    idle_lvls = set()
    for sent in flat.split("."):
        if re.search(r"\bidle\b", sent, re.I):
            for mm in re.finditer(r"\blogic\s+([01])\b", sent, re.I):
                idle_lvls.add(int(mm.group(1)))
    if len(idle_lvls) != 1:                      # absent, or contradictory -> SKIP
        return None
    idle_lvl = next(iter(idle_lvls))
    if idle_lvl != stop_pol:
        return None
    # the start bit must be the opposite polarity of idle, else "wait for the start
    # bit" is not a well-defined edge -> SKIP.
    if start_pol == idle_lvl:
        return None
    lsb_first = bool(re.search(r"least[-\s]significant\s+bit\s+first|lsb\s+first",
                               prompt, re.I))
    if not lsb_first:
        return None
    return n_data, start_pol, stop_pol, lsb_first


def _try_serial_framing(prompt, ins, outs, top, clk, rst):
    """IDLE -> (start==start_pol) -> N data bits -> STOP[==stop_pol] -> DONE.
    On a bad stop bit, ERR until the line returns to idle, then resume.  Optional
    8-bit `out_byte` capture (LSB-first), valid only when done.  Only fires for the
    canonical interface: clk + reset + ONE 1-bit data input, output set is exactly
    {done} or {done, out_byte(width n_data)}.
    """
    fr = _parse_framing(prompt)
    if fr is None:
        return None
    n_data, start_pol, stop_pol, _lsb = fr
    data_ins = [n for n, w in ins if n not in (clk, rst) and w == 1]
    nondata = [n for n, w in ins if n not in (clk, rst) and w != 1]
    if nondata or len(data_ins) != 1:
        return None
    inp = data_ins[0]
    out_names = {n: w for n, w in outs}
    if "done" not in out_names or out_names["done"] != 1:
        return None
    capture = None
    # the only permitted extra output is a data-byte capture of EXACTLY n_data bits.
    extras = [n for n in out_names if n != "done"]
    if extras:
        if len(extras) != 1:
            return None
        cap_name = extras[0]
        if out_names[cap_name] != n_data:
            return None
        # the prose must actually ask to output the received byte.
        if not re.search(r"output[^.\n]*byte|byte[^.\n]*output|out_byte", prompt, re.I):
            return None
        capture = cap_name
    rk = _reset_kind(prompt, rst)
    if rk is None:
        return None
    is_async, active_high = rk
    edge, rst_lvl = _reset_clauses(prompt, clk, rst, "IDLE", is_async, active_high)

    # state list: IDLE, D0..D{n-1}, STOP, DONE, ERR
    dstates = [f"D{i}" for i in range(n_data)]
    states = ["IDLE"] + dstates + ["STOP", "DONE", "ERR"]
    code = {s: i for i, s in enumerate(states)}
    w = max(1, (len(states) - 1).bit_length())
    start_branch_idle = "IDLE" if start_pol == 0 else dstates[0]   # in==1 path
    start_branch_data = dstates[0] if start_pol == 0 else "IDLE"   # in==0 path
    # the polarity that means "this is the (good) stop / idle level"
    good = stop_pol

    lines = [
        "// program-SOLVED serial framing receiver (start/N-data/stop); "
        "deterministic, no AI.",
        f"module {top}(",
        f"    input {clk},",
        f"    input {rst},",
        f"    input {inp},",
    ]
    if capture:
        lines.append(f"    output [{n_data - 1}:0] {capture},")
    lines += [
        "    output done",
        ");",
        f"    localparam [{w-1}:0] " + ", ".join(f"{s}={w}'d{code[s]}" for s in states) + ";",
        f"    reg [{w-1}:0] state, nstate;",
    ]
    if capture:
        # shift LSB-first: sample 'in' every cycle into the MSB and slide right; a
        # (n_data+2)-deep register so [n_data:1] holds the captured byte at DONE
        # (mirrors the pipeline alignment of state+shift advancing on the same edge).
        sw = n_data + 2
        lines.append(f"    reg [{sw-1}:0] sh;")
    lines += [
        "    always @(*) begin",
        "        case (state)",
        # IDLE: stay while line idle; drop to first data state when start bit seen
        f"            IDLE: nstate = {inp} ? {('IDLE' if good==1 else dstates[0])} : "
        f"{(dstates[0] if good==1 else 'IDLE')};",
    ]
    for i in range(n_data - 1):
        lines.append(f"            D{i}: nstate = D{i+1};")
    lines.append(f"            D{n_data-1}: nstate = STOP;")
    # STOP: good stop -> DONE, bad -> ERR
    if good == 1:
        lines.append(f"            STOP: nstate = {inp} ? DONE : ERR;")
        lines.append(f"            DONE: nstate = {inp} ? IDLE : D0;")
        lines.append(f"            ERR:  nstate = {inp} ? IDLE : ERR;")
    else:
        lines.append(f"            STOP: nstate = {inp} ? ERR : DONE;")
        lines.append(f"            DONE: nstate = {inp} ? D0 : IDLE;")
        lines.append(f"            ERR:  nstate = {inp} ? ERR : IDLE;")
    lines += [
        "            default: nstate = IDLE;",
        "        endcase",
        "    end",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= IDLE;",
        "        else state <= nstate;",
        "    end",
    ]
    if capture:
        sw = n_data + 2
        lines += [
            f"    always @(posedge {clk}) sh <= {{{inp}, sh[{sw-1}:1]}};",
            f"    assign {capture} = done ? sh[{n_data}:1] : {n_data}'hx;",
        ]
    lines += [
        "    assign done = (state == DONE);",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Method 3 — consecutive-run counter (HDLC: 5 -> disc, 6 -> flag, 7+ -> err)
# --------------------------------------------------------------------------- #
def _parse_runs(prompt):
    """Return (disc_run, flag_run, err_run) or None.  The thresholds must be stated:
        disc: 'inserts a zero after every 5 consecutive 1s' / '0111110' (5 ones)
        flag: 'exactly 6 consecutive 1s' / '01111110'
        err:  '7 or more consecutive 1s'
    Only the canonical 5/6/7 HDLC contract is accepted; any other numbers SKIP
    (a different threshold set may have a different recovery rule we don't infer).
    """
    m_disc = re.search(r"after\s+every\s+(\d+)\s+consecutive\s+1s", prompt, re.I)
    m_flag = re.search(r"exactly\s+(\d+)\s+consecutive\s+1s", prompt, re.I)
    m_err = re.search(r"(\d+)\s+or\s+more\s+consecutive\s+1s", prompt, re.I)
    if not (m_disc and m_flag and m_err):
        return None
    disc_run = int(m_disc.group(1))
    flag_run = int(m_flag.group(1))
    err_run = int(m_err.group(1))
    # canonical HDLC: discard after 5, flag at 6, error at 7+ ; require the exact
    # consecutive relationship (flag = disc+1, err = flag+1) — otherwise the
    # action-per-threshold mapping is not the one we build.
    if not (flag_run == disc_run + 1 and err_run == flag_run + 1):
        return None
    return disc_run, flag_run, err_run


def _try_consecutive_run(prompt, ins, outs, top, clk, rst):
    """Moore consecutive-1s counter.  Count states C0..C{flag_run}; on the
    discard-threshold run followed by a 0 -> one-cycle DISC; on the flag run
    followed by a 0 -> FLAG; on the flag run followed by a 1 (one too many) -> ERR
    held until a 0.  The three outputs (disc/flag/err) are Moore one-cycle pulses.
    """
    runs = _parse_runs(prompt)
    if runs is None:
        return None
    disc_run, flag_run, err_run = runs
    # exactly one 1-bit data input, exactly three 1-bit outputs named disc/flag/err.
    data_ins = [n for n, w in ins if n not in (clk, rst) and w == 1]
    nondata = [n for n, w in ins if n not in (clk, rst) and w != 1]
    if nondata or len(data_ins) != 1:
        return None
    inp = data_ins[0]
    out_map = {n: w for n, w in outs}
    if set(out_map) != {"disc", "flag", "err"} or any(w != 1 for w in out_map.values()):
        return None
    # must be a Moore machine asserting the outputs the cycle AFTER the condition.
    if not re.search(r"\bmoore\b", prompt, re.I):
        return None
    rk = _reset_kind(prompt, rst)
    if rk is None:
        return None
    is_async, active_high = rk
    # reset -> the "previous input were 0" state, i.e. C0.
    edge, rst_lvl = _reset_clauses(prompt, clk, rst, "C0", is_async, active_high)

    cstates = [f"C{i}" for i in range(flag_run + 1)]   # C0..C{flag_run}
    states = cstates + ["SERR", "SDISC", "SFLAG"]
    code = {s: i for i, s in enumerate(states)}
    w = max(1, (len(states) - 1).bit_length())

    lines = [
        "// program-SOLVED HDLC consecutive-1s counter (Moore); deterministic, no AI.",
        f"module {top}(",
        f"    input {clk},",
        f"    input {rst},",
        f"    input {inp},",
        "    output disc,",
        "    output flag,",
        "    output err",
        ");",
        f"    localparam [{w-1}:0] " + ", ".join(f"{s}={w}'d{code[s]}" for s in states) + ";",
        f"    reg [{w-1}:0] state, nstate;",
        "    always @(*) begin",
        "        case (state)",
    ]
    for i in range(flag_run + 1):
        if i < disc_run:                          # before the discard threshold
            lines.append(f"            C{i}: nstate = {inp} ? C{i+1} : C0;")
        elif i == disc_run:                       # 5 ones reached: a 0 -> discard
            lines.append(f"            C{i}: nstate = {inp} ? C{i+1} : SDISC;")
        else:                                     # i == flag_run (6 ones): 1 -> err, 0 -> flag
            lines.append(f"            C{i}: nstate = {inp} ? SERR : SFLAG;")
    lines += [
        "            SERR:  nstate = " + f"{inp} ? SERR : C0;",
        "            SDISC: nstate = " + f"{inp} ? C1 : C0;",
        "            SFLAG: nstate = " + f"{inp} ? C1 : C0;",
        "            default: nstate = C0;",
        "        endcase",
        "    end",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= C0;",
        "        else state <= nstate;",
        "    end",
        "    assign disc = (state == SDISC);",
        "    assign flag = (state == SFLAG);",
        "    assign err  = (state == SERR);",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Method 4 — pattern-detect -> shift-delay -> (delay+1)*M-cycle timer
# --------------------------------------------------------------------------- #
def _parse_pattern_timer(prompt):
    """Return (pattern_bits, n_delay, mult, msb_first) or None.  Stated parameters:
        pattern:   'pattern 1101 is detected'                 -> "1101"
        delay:     'shift in the next 4 bits ... delay[3:0]'  -> 4
        mult:      '(delay[3:0] + 1) * 1000 clock cycles'     -> 1000
        order:     'most-significant-bit first'               -> msb_first=True
    Only the exact (delay+1)*M contract is accepted; anything else SKIPs.
    """
    m_pat = re.search(r"pattern\s+\(?([01]{2,})\)?\s+(?:is\s+)?(?:detected|received)",
                      prompt, re.I) or re.search(r"start\s+sequence\s+\(?([01]{2,})\)?",
                                                 prompt, re.I)
    m_delay = re.search(r"shift\s+in\s+(?:the\s+)?(?:next\s+)?(\d+)\s+(?:more\s+)?bits",
                        prompt, re.I)
    m_mult = re.search(r"\(\s*delay\s*\[[^\]]*\]\s*\+\s*1\s*\)\s*\*\s*(\d+)\s*"
                       r"clock\s+cycles", prompt, re.I)
    if not (m_pat and m_delay and m_mult):
        return None
    pattern = m_pat.group(1)
    n_delay = int(m_delay.group(1))
    mult = int(m_mult.group(1))
    if n_delay < 1 or n_delay > 16 or mult < 1 or mult > 100000:
        return None
    # the delay register must be exactly n_delay bits wide (delay[n_delay-1:0]).
    msb_first = bool(re.search(r"most[-\s]significant[-\s]bit\s+first|msb\s+first",
                               prompt, re.I))
    if not msb_first:                            # we only build the stated MSB-first shift
        return None
    return pattern, n_delay, mult, msb_first


def _try_pattern_delay_timer(prompt, ins, outs, top, clk, rst):
    """Detect a start pattern on `data`, shift in n_delay bits MSB-first as
    delay[n_delay-1:0], count exactly (delay+1)*mult cycles emitting the remaining
    whole-units on count, assert counting while counting and done while waiting for
    ack.  Interface: clk + reset + data + ack inputs; count(n_delay)/counting/done
    outputs.  Built only when ALL parameters parse and the interface matches.
    """
    pt = _parse_pattern_timer(prompt)
    if pt is None:
        return None
    pattern, n_delay, mult, _msb = pt
    in_map = {n: w for n, w in ins if n not in (clk, rst)}
    out_map = {n: w for n, w in outs}
    # exactly the canonical interface: data(1) + ack(1) inputs.
    if set(in_map) != {"data", "ack"} or in_map.get("data") != 1 or in_map.get("ack") != 1:
        return None
    if set(out_map) != {"count", "counting", "done"}:
        return None
    if out_map.get("counting") != 1 or out_map.get("done") != 1:
        return None
    if out_map.get("count") != n_delay:
        return None
    rk = _reset_kind(prompt, rst)
    if rk is None:
        return None
    is_async, active_high = rk
    edge, rst_lvl = _reset_clauses(prompt, clk, rst, "S", is_async, active_high)

    # Pattern-search states: one per matched-prefix length, with the standard
    # mismatch fall-back computed from the pattern string (KMP-free: short patterns).
    # We build them explicitly so the fall-back is correct for any 1101-like pattern.
    L = len(pattern)

    def fallback(prefix_len, bit):
        """Longest proper suffix of (pattern[:prefix_len]+bit) that is a pattern
        prefix.  Returns the next matched-prefix length."""
        s = pattern[:prefix_len] + bit
        for k in range(min(len(s), L), -1, -1):
            if s.endswith(pattern[:k]):
                return k
        return 0

    # search states P0..P{L-1} (P{L} would be a full match -> go to shift).
    pstates = [f"P{i}" for i in range(L)]
    bstates = [f"B{i}" for i in range(n_delay)]   # shift-in n_delay bits
    states = pstates + bstates + ["CNT", "WAIT"]
    code = {s: i for i, s in enumerate(states)}
    w = max(1, (len(states) - 1).bit_length())
    fbits = max(1, (mult - 1).bit_length())       # fast-counter width (0..mult-1)

    lines = [
        "// program-SOLVED pattern-detect + delay timer ((delay+1)*M cycles); "
        "deterministic, no AI.",
        f"module {top}(",
        f"    input {clk},",
        f"    input {rst},",
        "    input data,",
        f"    output [{n_delay - 1}:0] count,",
        "    output counting,",
        "    output done,",
        "    input ack",
        ");",
        f"    localparam [{w-1}:0] " + ", ".join(f"{s}={w}'d{code[s]}" for s in states) + ";",
        f"    reg [{w-1}:0] state, nstate;",
        f"    reg [{n_delay - 1}:0] scount;          // remaining whole-units",
        f"    reg [{fbits - 1}:0] fcount;          // 0..{mult-1} fast counter",
        f"    wire done_counting = (scount=={n_delay}'d0) && (fcount=={fbits}'d{mult-1});",
        "    reg shift_ena;",
        "    always @(*) begin",
        "        shift_ena = 1'b0;",
        "        case (state)",
    ]
    # pattern-search transitions
    for i in range(L):
        on1 = i + 1 if pattern[i] == "1" else fallback(i, "1")
        on0 = i + 1 if pattern[i] == "0" else fallback(i, "0")
        # i+1 == L means full match -> first shift state B0
        nx1 = bstates[0] if on1 == L else pstates[on1]
        nx0 = bstates[0] if on0 == L else pstates[on0]
        lines.append(f"            P{i}: nstate = data ? {nx1} : {nx0};")
    # shift-in states
    for i in range(n_delay - 1):
        lines.append(f"            B{i}: nstate = B{i+1};")
    lines.append(f"            B{n_delay-1}: nstate = CNT;")
    lines += [
        "            CNT:  nstate = done_counting ? WAIT : CNT;",
        "            WAIT: nstate = ack ? P0 : WAIT;",
        "            default: nstate = P0;",
        "        endcase",
        "        if (" + " || ".join(f"state==B{i}" for i in range(n_delay)) + ") shift_ena = 1'b1;",
        "    end",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= P0;",
        "        else state <= nstate;",
        "    end",
        "    assign counting = (state == CNT);",
        "    assign done = (state == WAIT);",
        f"    always @(posedge {clk}) begin",
        f"        if (shift_ena) scount <= {{scount[{n_delay-2}:0], data}};",
        f"        else if (counting && fcount=={fbits}'d{mult-1}) scount <= scount - 1'b1;",
        "    end",
        f"    always @(posedge {clk}) begin",
        f"        if (!counting) fcount <= {fbits}'d0;",
        f"        else if (fcount=={fbits}'d{mult-1}) fcount <= {fbits}'d0;",
        "        else fcount <= fcount + 1'b1;",
        "    end",
        f"    assign count = counting ? scount : {n_delay}'hx;",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
_WORD_NUMBERS = dict(zip(('one', 'two', 'three', 'four', 'five', 'six', 'seven',
                          'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen',
                          'fourteen', 'fifteen', 'sixteen'), range(1, 17)))


def _word_message_trace_matches(contract, table, concurrent):
    """Check source examples against the parsed word contract, never DUT output."""
    partial, pending, packet = [], None, None
    initialized, valid = False, None
    for index, (_, row) in enumerate(table['rows']):
        reset = row[contract['reset']] == int(contract['active_high'])
        if (contract['asynchronous'] and reset) or (index and row[contract['clock']] == contract['edge']):
            if reset:
                partial, pending, packet, valid, initialized = [], None, 0, 0, True
            else:
                if not initialized:
                    return False
                valid = int(pending is not None)
                if pending is not None:
                    packet = pending
                pending = None
                if concurrent or not valid:
                    word = row[contract['word']]
                    if partial or ((word >> contract['marker']) & 1) == contract['marker_level']:
                        partial.append(word)
                        if len(partial) == contract['count']:
                            positions = (range(contract['count']-1, -1, -1)
                                         if contract['msb_first'] else range(contract['count']))
                            pending = sum(value << (position * contract['width'])
                                          for value, position in zip(partial, positions))
                            partial = []
        expected = row[contract['valid']]
        if expected is not None and valid != expected:
            return False
        if expected == 1 and packet != row[contract['packet']]:
            return False
    return True


def _try_word_message(prompt, ins, outs, top, clk, rst):
    """Closed fixed-length word framing with a one-edge pending report.

    Bind the count, marker, packed order, accepted sampling edge and reset from
    public prose/header. A source trace can prove concurrent next-frame input;
    otherwise concurrency must be explicit. Unsupported/conflicting facts return
    None through the existing Program-first backup contract.
    """
    import waveform_table_conformance_check as waveform

    words = [(n, w) for n, w in ins if n not in (clk, rst)]
    packed = [(n, w) for n, w in outs if w > 1]
    valids = [n for n, w in outs if w == 1]
    if len(ins) != 3 or len(outs) != 2 or len(words) != 1 or len(packed) != 1 or len(valids) != 1:
        return None
    (word, width), (packet, total), valid = words[0], packed[0], valids[0]
    if not (2 <= width <= 64 and total % width == 0 and 2 <= total // width <= 16):
        return None
    headers = re.findall(r'\bmodule\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;', prompt, re.S)
    if len(headers) != 1 or headers[0][0] != top or re.search(r'\binout\b|\bparameter\b', headers[0][1]):
        return None
    # The emitter uses numeric word bit positions and descending packed slices.
    # Width equality alone cannot bind an ascending/nonzero-based declaration.
    ranges = re.findall(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', headers[0][1])
    if any(int(lo) != 0 or int(hi) < int(lo) for hi, lo in ranges):
        return None
    flat = re.sub(r'\s+', ' ', prompt)
    # This grammar implements affirmative framing facts. Do not reinterpret
    # negated reset/marker/timing facts by matching their positive substrings.
    bound_fact = r'\b(?:words?|bytes?|messages?|' + '|'.join(re.escape(n) for n, _ in ins + outs) + r')\b'
    negation = r"\b(?:not|never|cannot|no)\b|\b(?:can|do|does|must|shall|should|may|will)n['’]t\b"
    for clause in re.split(r'[.;]', flat):
        if re.search(bound_fact, clause, re.I) and re.search(negation, clause, re.I):
            return None
    number = r'(?:\d+|' + '|'.join(_WORD_NUMBERS) + r')'
    counts = []
    for pattern in (r'\bmessages?\s+(?:of|are)\s+(' + number + r')\s+(?:words?|bytes?)\b',
                    r'\ball\s+(' + number + r')\s+(?:words?|bytes?)\b',
                    r'\b(' + number + r')\s+(?:words?|bytes?)\s+long\b'):
        for token in re.findall(pattern, flat, re.I):
            counts.append(int(token) if token.isdigit() else _WORD_NUMBERS[token.lower()])
    count = total // width
    if set(counts) != {count}:
        return None
    following = [int(token) if token.isdigit() else _WORD_NUMBERS[token.lower()]
                 for token in re.findall(r'\bnext\s+(' + number + r')\s+(?:words?|bytes?)\b', flat, re.I)]
    if following and set(following) != {count - 1}:
        return None
    if not following and not re.search(r'\bassume\b[^.]{0,80}\b(?:word|byte)\s+1\b'
                                       r'[^.]{0,40}\bmessage\b', flat, re.I):
        return None
    marker_pattern = re.escape(word) + r'\s*\[\s*(\d+)\s*\]\s*=\s*([01])\b'
    markers = set((int(bit), int(level)) for bit, level in re.findall(marker_pattern, flat))
    if len(markers) != 1:
        return None
    marker, marker_level = next(iter(markers))
    if marker >= width or not re.search(r'\bdiscard\b[^.]{0,150}\buntil\b[^.]{0,150}' + marker_pattern, flat, re.I):
        return None
    if re.search(r'\b(?:variable[-\s]+length|checksum|parity|start\s+bit|stop\s+bit)\b', flat, re.I):
        return None
    ordinals = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh',
                'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth', 'thirteenth',
                'fourteenth', 'fifteenth', 'sixteenth')
    positions = {}
    for hi, lo, ordinal in re.findall(re.escape(packet) + r'\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*'
                                      r'(?:is|contains|holds)\s+(?:the\s+)?(' + '|'.join(ordinals) + r')\s+(?:word|byte)', flat, re.I):
        positions.setdefault(ordinal.lower(), set()).add((int(hi), int(lo)))
    msb = {ordinal: {(total-index*width-1, total-(index+1)*width)}
           for index, ordinal in enumerate(ordinals[:count])}
    lsb = {ordinal: {((index+1)*width-1, index*width)}
           for index, ordinal in enumerate(ordinals[:count])}
    if not {'first', 'second'} <= positions.keys():
        return None
    orders = [expected for expected in (msb, lsb)
              if all(expected.get(ordinal) == slices for ordinal, slices in positions.items())]
    if len(orders) != 1:
        return None
    msb_first = orders[0] == msb
    timing = (r'\b' + re.escape(valid) + r'\b[^.]{0,70}(?:\b(?:one|1)\s+clock\s+cycle\s+after\b|'
              r'\bin\s+the\s+cycle\s+immediately\s+after\b)[^.]{0,30}'
              r'\b(final|last|' + '|'.join(ordinals[1:]) + r')\s+(?:word|byte)\b')
    completions = re.findall(timing, flat, re.I)
    if not completions or any(x.lower() not in ('final', 'last', ordinals[count-1]) for x in completions):
        return None
    if re.search(r'\b(?:same\s+(?:clock\s+)?cycle|two\s+clock\s+cycles\s+after)\b', flat, re.I):
        return None
    if not re.search(r'\b' + re.escape(packet) + r'\b[^.;]{0,100}\bvalid\b[^.;]{0,40}'
                     r'\b(?:when|whenever|while)\b[^.;]{0,25}\b' + re.escape(valid)
                     + r'\b[^.;]{0,30}(?:\basserted\b|(?:=|is)\s*1\b)', flat, re.I):
        return None
    rk = _reset_kind(prompt, rst)
    if rk is None:
        return None
    asynchronous, active_high = rk
    concurrent = False
    for clause in re.split(r'[.;]', flat):
        if re.search(r'\breporting\s+cycle\b', clause, re.I):
            # Recognize a complete affirmative permission, not an "accepted"
            # substring inside a prohibition, condition or exception. A trace
            # cannot override contradictory or unsupported source policy.
            if not re.fullmatch(r'\s*(?:A\s+)?new\s+first\s+(?:word|byte)\s+'
                                r'(?:may|can|must|shall|will)\s+be\s+accepted\s+'
                                r'in\s+the\s+reporting\s+cycle\s*', clause, re.I):
                return None
            concurrent = True
    if re.search(r'\b(?:reporting|output)\s+cycle\b[^.]{0,60}\b(?:ignored|discarded)\b', flat, re.I):
        return None
    if re.search(r'\b' + re.escape(valid) + r'\b[^.]{0,50}\b(?:held|remain|stays)\b'
                 r'[^.]{0,50}\b(?:until|high|asserted)\b', flat, re.I):
        return None
    edge_set = set()
    if re.search(r'\b(?:positive|rising)\s+and\s+(?:negative|falling)\s+edge\b|'
                 r'\b(?:negative|falling)\s+and\s+(?:positive|rising)\s+edge\b', flat, re.I):
        return None
    for clause in re.split(r'[.;]', flat):
        if re.search(r'\b' + re.escape(clk) + r'\b', clause):
            edge_set.update(1 if e.lower() in ('positive', 'rising') else 0 for e in
                            re.findall(r'\b(positive|rising|negative|falling)[-\s]+edge\b', clause, re.I))
    table = None
    if waveform.parse_table(prompt) is not None:
        table, _reason = waveform.source_multioutput_contract(prompt, top=top)
        if table is None:
            return None
        edge_set.add(table['active_edge'])
    if len(edge_set) != 1:
        return None
    contract = dict(clock=clk, reset=rst, word=word, width=width, count=count,
                    packet=packet, valid=valid, marker=marker, marker_level=marker_level,
                    msb_first=msb_first, edge=next(iter(edge_set)),
                    asynchronous=asynchronous, active_high=active_high)
    if table:
        if not _word_message_trace_matches(contract, table, True):
            return None
        if not concurrent and _word_message_trace_matches(contract, table, False):
            return None  # the source did not resolve reporting-cycle acceptance
    elif not concurrent:
        return None
    elif not re.search(r'\b' + re.escape(valid) + r'\b[^.]{0,45}'
                       r'\b(?:for\s+(?:exactly\s+)?(?:one|1)\s+(?:clock\s+)?cycle|one[-\s]+cycle\s+pulse)\b', flat, re.I):
        return None
    prefix = '__word_frame_'
    while any(n.startswith(prefix) for n, _ in ins + outs):
        prefix += '_'
    name = lambda key: prefix + key
    count_width = max(1, (count - 1).bit_length())
    assembled = (f'{{{name("buffer")}[{total-width-1}:0], {word}}}' if msb_first else
                 f'({name("buffer")} | ({{{total-width}\'d0, {word}}} << ({name("count")}*{width})))')
    edge = ('posedge' if contract['edge'] else 'negedge') + ' ' + clk
    if asynchronous:
        edge += f' or {"posedge" if active_high else "negedge"} {rst}'
    reset_test = rst if active_high else '!' + rst
    marker_test = f'{word}[{marker}]' if marker_level else f'!{word}[{marker}]'
    lines = [f'module {top} ({headers[0][1]});',
             f'reg [{count_width-1}:0] {name("count")};',
             f'reg [{total-1}:0] {name("buffer")}, {name("pending_packet")}, {name("packet")};',
             f'reg {name("pending")}, {name("valid")};',
             f'assign {valid} = {name("valid")};', f'assign {packet} = {name("packet")};',
             f'always @({edge}) begin', f'  if ({reset_test}) begin']
    for key in ('count', 'buffer', 'pending_packet', 'packet', 'pending', 'valid'):
        lines.append(f'    {name(key)} <= 0;')
    lines += ['  end else begin', f'    {name("valid")} <= {name("pending")};',
              f'    if ({name("pending")}) {name("packet")} <= {name("pending_packet")};',
              f'    {name("pending")} <= 0;', f'    if ({name("count")} == 0) begin',
              f'      if ({marker_test}) begin {name("buffer")} <= {word}; {name("count")} <= 1; end',
              '    end else begin', f'      {name("buffer")} <= {assembled};',
              f'      if ({name("count")} == {count-1}) begin',
              f'        {name("pending_packet")} <= {assembled};',
              f'        {name("pending")} <= 1; {name("count")} <= 0;',
              f'      end else {name("count")} <= {name("count")} + 1\'b1;',
              '    end', '  end', 'end', 'endmodule', '']
    return '\n'.join(lines)


_METHODS = (
    _try_word_message,
    _try_2s_complement,
    _try_serial_framing,
    _try_consecutive_run,
    _try_pattern_delay_timer,
)


def synth(prompt_text: str, top: str = "TopModule"):
    """Deterministic RTL for a prose-stated serial/protocol receiver FSM, or None
    (SKIP) when no method's parameters are fully and unambiguously stated."""
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return None
    clk, rst = _find_clk_reset(ins)
    if not clk or not rst:
        return None
    for method in _METHODS:
        try:
            rtl = method(prompt_text, ins, outs, top, clk, rst)
        except Exception:
            rtl = None
        if rtl:
            return rtl
    return None


def recognize(prompt_text: str):
    """{'present': True, 'method': <name>} when synth would fire, else None.
    Mirrors the registry's recognize() contract (cheap structured probe)."""
    return {"present": True} if synth(prompt_text) else None


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a fully-specified serial/protocol receiver FSM", file=sys.stderr)
        sys.exit(1)
    print(rtl)
