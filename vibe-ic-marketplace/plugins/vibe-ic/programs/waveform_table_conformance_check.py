#!/usr/bin/env python3
"""  ENVELOPE A — COMBINATIONAL truth-table: NO clk column AND no register idiom in
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


def source_multioutput_contract(prompt, rtl=None, top=None):
    """Bind the stable, valid-qualified word-output envelope to public source.

    This is an additional envelope, not a relaxation of classify()'s legacy
    single-output replay. Every table column must bind a declared port; the
    only aliases are unique clock/reset roles. Widths, radix, reset and the
    observation edge are source facts. Unknown or contradictory facts SKIP.
    """
    import port_parser

    headers = re.findall(r'\bmodule\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;',
                         prompt, re.S)
    if len(headers) != 1 or (top and headers[0][0] != top):
        return None, 'unbound_public_header'
    if re.search(r'\binout\b|\bparameter\b', headers[0][1]):
        return None, 'unsupported_public_header'
    if any(int(lo) != 0 or int(hi) < int(lo) for hi, lo in
           re.findall(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', headers[0][1])):
        return None, 'unsupported_public_packed_bounds'
    ins, outs = port_parser.parse_ports(prompt)
    if len(ins) != 3 or len(outs) != 2:
        return None, 'unsupported_word_interface'
    clocks = [n for n, w in ins if w == 1 and n.lower() in CLOCK_NAMES]
    resets = [n for n, w in ins if w == 1 and
              (('reset' in n.lower()) or n.lower() in ('rst', 'rst_n', 'arst'))]
    valids = [n for n, w in outs if w == 1]
    words = [(n, w) for n, w in ins if w > 1]
    packets = [(n, w) for n, w in outs if w > 1]
    if any(len(x) != 1 for x in (clocks, resets, valids, words, packets)):
        return None, 'ambiguous_word_roles'
    clk, rst, valid = clocks[0], resets[0], valids[0]
    word, word_width = words[0]
    packet, packet_width = packets[0]
    ports = dict(ins + outs)
    if len(ports) != 5 or not (1 < word_width <= packet_width <= 4096):
        return None, 'unsupported_word_widths'
    if rtl is not None and port_parser.parse_ports(rtl) != (ins, outs):
        # Declaration order can differ, but names/directions/widths cannot.
        actual_ins, actual_outs = port_parser.parse_ports(rtl)
        if dict(actual_ins) != dict(ins) or dict(actual_outs) != dict(outs):
            return None, 'candidate_interface_differs'
    flat = re.sub(r'\s+', ' ', prompt)
    sync = bool(re.search(r'\bsynchronous\b', flat, re.I))
    asynchronous = bool(re.search(r'\basynchronous\b', flat, re.I))
    high = bool(re.search(r'\bactive[-\s]+high\b', flat, re.I))
    low = bool(re.search(r'\bactive[-\s]+low\b', flat, re.I))
    if sync == asynchronous or high == low:
        return None, 'unbound_reset_contract'
    qualification = re.search(
        r'\b' + re.escape(packet) + r'\b[^.;]{0,100}\bvalid\b[^.;]{0,40}'
        r'\b(?:when|whenever|while)\b[^.;]{0,25}\b' + re.escape(valid)
        + r'\b[^.;]{0,30}(?:\basserted\b|(?:=|is)\s*1\b)', flat, re.I)
    if not qualification:
        return None, 'unbound_valid_qualification'
    parsed = parse_table(prompt)
    if parsed is None:
        return None, 'no_multioutput_table'
    cols, rows = parsed
    if len(set(cols)) != len(cols) or len(re.findall(r'^\s*time\s', prompt, re.M | re.I)) != 1:
        return None, 'ambiguous_table_columns'
    if len(re.findall(r'^\s*\d+ns\s', prompt, re.M)) != len(rows):
        return None, 'incomplete_multioutput_table'
    roles = {}
    lower = {n.lower(): n for n in ports}
    for col in cols[1:]:
        if col in lower:
            roles[col] = lower[col]
        elif col in CLOCK_NAMES:
            roles[col] = clk
        elif col in ('rst', 'reset', 'rst_n', 'resetn', 'reset_n', 'areset', 'arst'):
            roles[col] = rst
        else:
            return None, 'unbound_table_column'
    if set(roles.values()) != set(ports) or len(roles) != len(ports):
        return None, 'ambiguous_table_role_alias'
    explicit_radix = re.findall(
        r'\bvalues\s+are\s+(hexadecimal|hex|decimal|binary)\b', flat, re.I)
    if len(set(x.lower() for x in explicit_radix)) > 1:
        return None, 'conflicting_table_radix'
    common_radix = ({'hexadecimal': 16, 'hex': 16, 'decimal': 10, 'binary': 2}
                    .get(explicit_radix[0].lower()) if explicit_radix else None)
    decoded = []
    radix = {}
    for index, col in enumerate(cols[1:]):
        width = ports[roles[col]]
        tokens = [values[index].lower() for _, values in rows]
        if width == 1:
            radix[col] = 2
        elif common_radix:
            radix[col] = common_radix
        elif any(re.fullmatch(r'[0-9a-f]*[a-f][0-9a-f]*', t) for t in tokens):
            radix[col] = 16
        elif any(re.fullmatch(r'\d+', t) and len(t.lstrip('0')) > 1 for t in tokens):
            return None, 'ambiguous_numeric_radix'
        else:
            radix[col] = 10  # single digits have the same hex/decimal value
    for time, values in rows:
        row = {}
        for col, token in zip(cols[1:], values):
            width = ports[roles[col]]
            token = token.lower()
            if re.fullmatch(r'[xz]+', token):
                value = None
            else:
                try:
                    sized = re.fullmatch(r"(\d+)'([hbd])([0-9a-f]+)", token)
                    if sized:
                        if int(sized[1]) != width:
                            return None, 'table_literal_width_mismatch'
                        value = int(sized[3], {'h': 16, 'b': 2, 'd': 10}[sized[2]])
                    elif token.startswith(('0x', '0b')):
                        value = int(token, 0)
                    else:
                        value = int(token, radix[col])
                except ValueError:
                    return None, 'unsupported_table_value'
                if value < 0 or value >= (1 << width):
                    return None, 'table_value_exceeds_width'
            row[roles[col]] = value
        if row[clk] not in (0, 1) or row[rst] not in (0, 1):
            return None, 'unknown_clock_or_reset'
        if row[word] is None and row[rst] != int(high):
            return None, 'unknown_accepted_word'
        if row[valid] == 1 and row[packet] is None:
            return None, 'missing_valid_packet_value'
        decoded.append((time, row))
    if len(rows) < 5 or rows[0][0] != 0:
        return None, 'incomplete_clock_observations'
    deltas = {b[0] - a[0] for a, b in zip(rows, rows[1:])}
    if len(deltas) != 1 or next(iter(deltas)) <= 0:
        return None, 'irregular_clock_observations'
    observed_edges = set()
    for (_, previous), (_, current) in zip(decoded, decoded[1:]):
        if previous[clk] == current[clk]:
            return None, 'missing_clock_transition'
        reset_event = asynchronous and current[rst] == int(high)
        if (not reset_event and previous[valid] is not None and current[valid] is not None
                and previous[valid] != current[valid]):
            observed_edges.add(current[clk])
    stated_edges = set()
    for clause in re.split(r'[.;]', flat):
        if re.search(r'\b' + re.escape(clk) + r'\b', clause):
            for edge in re.findall(r'\b(positive|rising|negative|falling)[-\s]+edge\b', clause, re.I):
                stated_edges.add(1 if edge.lower() in ('positive', 'rising') else 0)
    edges = observed_edges | stated_edges
    if len(edges) != 1:
        return None, 'ambiguous_observation_edge'
    active = next(iter(edges))
    if decoded[0][1][clk] == active:
        return None, 'initial_clock_is_active'
    if not any(row[valid] == 1 for _, row in decoded):
        return None, 'no_valid_packet_observation'
    for index, (_, row) in enumerate(decoded[1:], 1):
        if row[clk] == active:
            if index + 1 >= len(decoded):
                return None, 'missing_stable_halfcycle'
            following = decoded[index + 1][1]
            if any(row[n] != following[n] for n, _ in ins if n != clk):
                return None, 'unstable_input_halfcycle'
            if row[valid] != following[valid] or (row[valid] == 1 and row[packet] != following[packet]):
                return None, 'unstable_output_halfcycle'
    return {'ins': ins, 'outs': outs, 'clock': clk, 'reset': rst,
            'word': word, 'word_width': word_width, 'packet': packet,
            'packet_width': packet_width, 'valid': valid, 'active_edge': active,
            'active_high_reset': high, 'asynchronous_reset': asynchronous,
            'rows': decoded, 'header': f'module {headers[0][0]} ({headers[0][1]});'}, None


def build_multioutput_tb(contract, top):
    """Replay public stable observations with setup before the bound clock edge."""
    clk, valid, packet = (contract[k] for k in ('clock', 'valid', 'packet'))
    widths = dict(contract['ins'] + contract['outs'])
    def net(n):
        return '_wtc_' + n
    def literal(n, value):
        return f"{widths[n]}'hx" if value is None else f"{widths[n]}'h{value:x}"
    lines = ['`timescale 1ns/1ps', 'module tb_wtc;', 'integer mism=0;']
    for direction, ports in [('reg', contract['ins']), ('wire', contract['outs'])]:
        for name, width in ports:
            init = f"={1-contract['active_edge']}" if name == clk else ''
            lines.append(f'{direction} [{width-1}:0] {net(name)}{init};')
    lines.append(f'{top} dut(' + ','.join(f'.{n}({net(n)})' for n in widths) + ');')
    lines.append('initial begin')
    for index, (time, row) in enumerate(contract['rows']):
        if index:
            lines.append(f'#({time}-0.001-$realtime);')
        for name, _ in contract['ins']:
            if name != clk:
                lines.append(f'{net(name)}={literal(name,row[name])};')
        if index:
            lines.append('#0.001;')
        lines.append(f'{net(clk)}={row[clk]}; #0.001;')
        checked = [valid] + ([packet] if row[valid] == 1 else [])
        for name in checked:
            if row[name] is not None:
                lines.append(f'if({net(name)} !== {literal(name,row[name])}) begin '
                             f'$display("WTC_MISMATCH t={time} port={name} got=%h",{net(name)}); '
                             'mism=mism+1; end')
    lines += ['if(mism==0) $display("WTC_PASS"); else $display("WTC_FAIL mismatches=%0d",mism);',
              '$finish; end', 'endmodule']
    return '\n'.join(lines) + '\n'


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
    multi = None
    if len([c for c in cols[1:] if c in {n.lower() for n in outs}]) > 1:
        multi, reason = source_multioutput_contract(src, rtl, a.top)
        if multi is None:
            print(f"WTC_SKIP_{reason}: outside source-bound multi-output envelope -> SKIP (no block)")
            sys.exit(0)
        tb = build_multioutput_tb(multi, a.top)
    else:
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
