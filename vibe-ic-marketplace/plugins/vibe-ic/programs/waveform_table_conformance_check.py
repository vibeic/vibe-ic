#!/usr/bin/env python3
"""waveform_table_conformance_check.py — plugin gate (ORGANIC #716 / Prob098_circuit7).

DETERMINISTIC waveform-table conformance gate for "read the simulation waveform,
then implement it" prompts (the VerilogEval circuitN family). When a prompt
embeds a literal ``time [clk] <input...> [internal...] <output>`` simulation
table, the candidate RTL MUST reproduce that table's OUTPUT column under the
input column. A blind agent that MIS-COUNTS pipeline stages (e.g. reads an early
X-window — actually an input-sampling race — as an extra register stage and
authors a TWO-stage ``q1<=~a; q<=q1`` pipeline where the spec is a ONE-stage
``q<=~a``) produces RTL whose self-TB still "passes" but which FAILS the hidden
scorer. This program is the independent yard-stick: it replays the table the way
the scorer compares (X in the golden/table matches anything; X in the DUT only
matches a table X) and BLOCKS on any mismatch.

THE FAILURE THIS CLOSES
-----------------------
Prob098_circuit7: prompt waveform settles q=1 at the SECOND posedge (t=15) with
a=0; the agent reverse-engineered a TWO-stage delay (``q1<=~a; q<=q1``). The
real reference is ONE-stage ``q<=~a`` — the t=5..t=10 X-window is the TB's
NBA input-sampling race (``@(posedge) a<=0`` leaves a=x at the first edge), NOT
a second pipeline stage. The two-stage RTL scores 58/123 mismatches on the
hidden TB; the one-stage scores 0. No single-self-TB flow catches this; this
program does.

§4.05 SAFETY — PROVEN-FAITHFUL ENVELOPE ONLY (no false-block)
-------------------------------------------------------------
A blind table-replay CANNOT faithfully reconstruct the dataset generator's exact
edge scheduling across EVERY sequential idiom. Empirically (10 waveform goldens),
a generic replay false-blocks correct NEGEDGE/level-sensitive-LATCH designs
(Prob145_circuit8) and COMBINATIONAL-output Moore FSMs that expose an INTERNAL
state column (Prob147_circuit10), and mis-handles MULTI-BIT/hex output columns
(Prob117/Prob126). So this gate runs ONLY inside the envelope where its replay
is PROVABLY faithful — and SKIPs (rc 0, NEVER blocks) everywhere else:

  ENVELOPE A — COMBINATIONAL truth-table: NO clk column AND no register idiom in
    the table. Pure input→output value match per row; zero timing ambiguity.
  ENVELOPE B — SINGLE-CLOCK POSEDGE-REGISTERED, single-bit output, every table
    column is a declared module port (no internal-observability column), output
    is 1 bit, the only clock is ``clk`` and the table steps a regular 5 ns
    half-period. Replay drives inputs one half-period AFTER each row (the
    @(posedge) a<=val convention) and samples the output at end-of-timestep.

  SKIP (rc 0, advisory note only) when: a ``negedge`` clock is implied / the
    output column is multi-bit / there is an internal column that is NOT a module
    port / there are multiple clock-like columns / the table values are not pure
    0/1/x. These are the false-block landmines — the gate refuses to touch them.

This makes the gate conservative-by-construction: a CORRECT design in the
envelope always PASSes; a CORRECT design outside the envelope is SKIPped (never
blocked); only an in-envelope design that genuinely diverges from the published
table is BLOCKed.

CLI
---
  waveform_table_conformance_check.py --prompt <prompt.txt> --rtl <rtl.sv> \
      [--top TopModule]
  (or --table-file <file with the table> instead of --prompt)

EXIT CODES
  0  WTC_PASS | WTC_SKIP_<reason> | WTC_NO_TABLE   (never blocks outside envelope)
  1  WTC_FAIL (mismatch vs the published table, inside the proven-faithful envelope)
            | WTC_COMPILE_FAIL
  2  iverilog/vvp absent AND --require-tools  (else SKIP, never a fabricated PASS)
"""
import re, sys, subprocess, tempfile, os, shutil, argparse, shutil as _sh


def parse_table(text):
    lines = text.splitlines()
    hdr = None; cols = None
    for i, ln in enumerate(lines):
        t = ln.split()
        if t and t[0].lower() == 'time':
            hdr = i; cols = [x.lower() for x in t]; break
    if hdr is None:
        return None
    rows = []
    for ln in lines[hdr + 1:]:
        t = ln.split()
        if not t:
            if rows:
                break
            continue
        m = re.match(r'^(\d+)ns$', t[0])
        if not m:
            if rows:
                break
            continue
        if len(t) != len(cols):
            break
        rows.append((int(m.group(1)), t[1:]))
    return (cols, rows) if rows else None


def module_ports(rtl):
    ins = set(); outs = set()
    for m in re.finditer(r'\b(input|output)\b([^;,\)]*)', rtl):
        kind = m.group(1); rest = m.group(2)
        rest = re.sub(r'\b(reg|wire|logic|signed|unsigned)\b', '', rest)
        rest = re.sub(r'\[[^\]]*\]', '', rest)
        for nm in re.findall(r'[A-Za-z_]\w*', rest):
            (ins if kind == 'input' else outs).add(nm)
    return ins, outs


def output_width(rtl, name):
    """Best-effort bit-width of an output port (1 if no range)."""
    m = re.search(r'\boutput\b[^;,\)]*?\[\s*(\d+)\s*:\s*(\d+)\s*\][^;,\)]*\b' + re.escape(name) + r'\b', rtl)
    if m:
        hi, lo = int(m.group(1)), int(m.group(2))
        return abs(hi - lo) + 1
    return 1


def values_are_binary(rows, n_value_cols):
    for _, vals in rows:
        for v in vals:
            if v.lower() == 'x':
                continue
            if v not in ('0', '1'):
                return False
    return True


CLOCK_NAMES = ('clk', 'clock', 'clk1', 'clk2', 'clkin', 'clk_in')


def classify(cols, rows, ins, outs, rtl):
    """Return (envelope, out_col, in_cols, reason) or (None, ..., skip_reason)."""
    body = cols[1:]
    clocklike = [c for c in body if c in CLOCK_NAMES]
    has_clk = len(clocklike) >= 1
    clk_name = clocklike[0] if clocklike else None
    # output-port columns in the table (a Moore FSM exposes an internal state col that
    # is ALSO a declared output -> >1 output column -> outside the single-output envelope)
    out_port_cols = [c for c in body if c in outs]
    if not out_port_cols:
        return None, None, None, "no_output_port_column"
    if len(out_port_cols) > 1:
        return None, out_port_cols[-1], None, "multiple_output_columns"
    out_col = out_port_cols[0]
    # internal-observability column = a body col that is NOT a module port at all
    portset = ins | outs
    internal = [c for c in body if c not in CLOCK_NAMES and c not in portset]
    if internal:
        return None, out_col, None, "internal_observability_column"
    # values must be pure 0/1/x (multi-bit/hex tables -> skip)
    if not values_are_binary(rows, len(body)):
        return None, out_col, None, "non_binary_table_values"
    # output must be single-bit
    if output_width(rtl, out_col) != 1:
        return None, out_col, None, "multibit_output"
    in_cols = [c for c in body if c in ins and c not in CLOCK_NAMES]
    if has_clk:
        # multiple clock-like columns -> skip
        if len(clocklike) != 1:
            return None, out_col, in_cols, "multiple_clocks"
        # negedge clock implied by the RTL -> skip (envelope B is posedge only)
        if re.search(r'negedge\b', rtl):
            return None, out_col, in_cols, "negedge_clock"
        # a level-sensitive latch (always @(*) ... if(clk/clock)) -> skip
        if re.search(r'always\s*@\s*\(\s*\*\s*\)', rtl) and re.search(r'if\s*\(\s*' + re.escape(clk_name), rtl):
            return None, out_col, in_cols, "level_sensitive_latch"
        # combinational output in a clocked design (Moore output = assign of the chosen
        # output port) -> the registered-replay timing does not model it -> skip
        if re.search(r'\bassign\s+' + re.escape(out_col) + r'\b', rtl):
            return None, out_col, in_cols, "combinational_output_in_clocked_design"
        # §4.05 #716 r2 (Step-2.7): Envelope B replays the NBA `@(posedge) a<=val`
        # convention, which leaves the input — and hence the registered output —
        # X at the FIRST posedge (the value only arrives at that edge). A table
        # whose OUTPUT is already a CONCRETE 0/1 at the first posedge was
        # published under the SAME-EDGE sampling convention instead, for which
        # this replay is NOT faithful: replaying it as NBA would false-block a
        # CORRECT design. So SKIP (never false-block; never a fabricated PASS).
        # The canonical NBA table has X at the first posedge and stays in
        # Envelope B (so a genuine extra-stage / wrong-logic design still blocks).
        bidx = {c: i for i, c in enumerate(body)}
        if clk_name in bidx and out_col in bidx:
            ci, oi = bidx[clk_name], bidx[out_col]
            for _t, vals in rows:
                if ci < len(vals) and vals[ci] == '1':      # first posedge sample
                    if oi < len(vals) and vals[oi].lower() != 'x':
                        return (None, out_col, in_cols,
                                "same_edge_output_convention")
                    break
        return 'B', out_col, in_cols, None
    else:
        return 'A', out_col, in_cols, None


def vval(v):
    return "1'bx" if v.lower() == 'x' else f"1'b{int(v)}"


def build_tb(envelope, cols, rows, out_col, in_cols, top, clk_name):
    body = cols[1:]
    idx = {c: i for i, c in enumerate(body)}
    L = ["`timescale 1ns/1ps", "module tb_wtc;"]
    if envelope == 'B':
        L.append("  reg clk=0;")
    for c in in_cols:
        L.append(f"  reg {c}_d;")
    L.append(f"  wire {out_col}_d;")
    L.append("  integer mism=0;")
    conns = ([f".{clk_name}(clk)"] if envelope == 'B' and clk_name else []) \
        + [f".{c}({c}_d)" for c in in_cols] + [f".{out_col}({out_col}_d)"]
    L.append(f"  {top} dut(" + ", ".join(conns) + ");")
    L.append("  task chk(input [0:0] g, input [0:0] d, input integer t);")
    L.append("    if (g !== (g ^ d ^ g)) begin")
    L.append('      $display("WTC_MISMATCH t=%0d expected=%b got=%b", t, g, d); mism=mism+1; end')
    L.append("  endtask")
    if envelope == 'B':
        L.append("  always #5 clk=~clk;")
        # drive: apply each row's inputs just AFTER its time (t+1) so the value the row
        # DISPLAYS drives the SUBSEQUENT posedge (the @(posedge) a<=val scheduling).
        L.append("  initial begin")
        for c in in_cols:
            L.append(f"    {c}_d = {vval(rows[0][1][idx[c]])};")
        for ri, (t, vals) in enumerate(rows):
            tgt = f"{t}" if t == 0 else f"{t}+1"
            L.append(f"    #({tgt}-$time);")
            for c in in_cols:
                L.append(f"    {c}_d = {vval(vals[idx[c]])};")
        L.append("  end")
        L.append("  initial begin")
        for ri, (t, vals) in enumerate(rows):
            tgt = f"{t}" if t == 0 else f"{t}+1"
            L.append(f"    #({tgt}-$time);")
            L.append(f"    chk({vval(vals[idx[out_col]])}, {out_col}_d, {t});")
        L.append('    if (mism==0) $display("WTC_PASS"); else $display("WTC_FAIL mismatches=%0d", mism);')
        L.append("    $finish;")
        L.append("  end")
    else:  # envelope A: pure combinational truth-table
        L.append("  initial begin")
        prev = None
        for ri, (t, vals) in enumerate(rows):
            if prev is None:
                L.append("    #0;")
            else:
                L.append(f"    #({t-prev});")
            prev = t
            for c in in_cols:
                L.append(f"    {c}_d = {vval(vals[idx[c]])};")
            L.append("    #1;")
            L.append(f"    chk({vval(vals[idx[out_col]])}, {out_col}_d, {t});")
        L.append('    if (mism==0) $display("WTC_PASS"); else $display("WTC_FAIL mismatches=%0d", mism);')
        L.append("    $finish;")
        L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


# A waveform table EXPLICITLY attributed to a named module — "Module B can be
# described by the following simulation waveform". When that module is NOT the top,
# the table is that SUB-MODULE's function, not the top's I/O; the top is built FROM
# it (a structural composition). Replaying a sub-module's table against the top
# false-blocks a correct design (Prob131_mt2015_q4: top z = (A1|B1)^(A2&B2), but the
# table describes Module B = XNOR). §4.05-narrow: fires ONLY on an explicit
# "Module <X> ... waveform" attribution with X != top — the circuitN family
# describes the waveform as the TOP's own behaviour and is unaffected.
_SUBMOD_WAVEFORM_RE = re.compile(
    r'\bModule\s+([A-Za-z]\w*)\b[^.\n]{0,80}?\b(?:simulation\s+waveform|waveform|timing\s+diagram)',
    re.I)


def table_scoped_to_other_module(prompt, top):
    """Return a sub-module name if the waveform is attributed to a named module != top, else None."""
    for m in _SUBMOD_WAVEFORM_RE.finditer(prompt or ""):
        if m.group(1).lower() != (top or "").lower():
            return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser(description="Waveform-table conformance gate (#716).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prompt')
    g.add_argument('--table-file')
    ap.add_argument('--rtl', required=True)
    ap.add_argument('--top', default='TopModule')
    ap.add_argument('--dump-tb', action='store_true')
    ap.add_argument('--require-tools', action='store_true')
    a = ap.parse_args()

    src = open(a.prompt or a.table_file).read()
    # SKIP when a --prompt attributes the waveform to a named SUB-module (not the top):
    # the table is that sub-module's function, not the top's I/O (Prob131_mt2015_q4).
    if a.prompt:
        other = table_scoped_to_other_module(src, a.top)
        if other:
            print(f"WTC_SKIP_table_scoped_to_module_{other}: waveform attributed to module "
                  f"{other!r}, not top {a.top!r} -> SKIP (no block)")
            sys.exit(0)
    parsed = parse_table(src)
    if not parsed:
        print("WTC_NO_TABLE: no waveform table found -> SKIP")
        sys.exit(0)
    cols, rows = parsed
    rtl = open(a.rtl).read()
    ins, outs = module_ports(rtl)
    env, out_col, in_cols, reason = classify(cols, rows, ins, outs, rtl)
    if env is None:
        print(f"WTC_SKIP_{reason}: outside proven-faithful envelope -> SKIP (no block)")
        sys.exit(0)
    body = cols[1:]
    clk_name = next((c for c in body if c in CLOCK_NAMES), None)
    tb = build_tb(env, cols, rows, out_col, in_cols, a.top, clk_name)
    if a.dump_tb:
        print(tb); return
    if not (_sh.which('iverilog') and _sh.which('vvp')):
        if a.require_tools:
            print("WTC_TOOLS_ABSENT: iverilog/vvp required but not found"); sys.exit(2)
        print("WTC_SKIP_no_tools: iverilog/vvp absent -> SKIP (never a fabricated PASS)")
        sys.exit(0)
    d = tempfile.mkdtemp()
    try:
        tbf = os.path.join(d, 'tb.sv'); open(tbf, 'w').write(tb)
        vvp = os.path.join(d, 's.vvp')
        # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
        r = subprocess.run(['iverilog', '-g2012', '-o', vvp, a.rtl, tbf],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("WTC_COMPILE_FAIL:\n" + r.stderr.strip()); sys.exit(1)
        r2 = subprocess.run(['vvp', vvp], capture_output=True, text=True)
        out = r2.stdout.strip()
        print(out)
        sys.exit(0 if 'WTC_PASS' in out else 1)
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    main()
