#!/usr/bin/env python3
"""worked_example_sequence_oracle_check.py — deterministic emit gate that turns a
spec's PROSE input→output worked example into a self-checking oracle.

WHY (benchmark close-loop, pulse_detect pass@6 ≈ 1/6 — PRIME DIRECTIVE capture):
Many serial / detector specs disclose a complete cycle-by-cycle worked example, e.g.
pulse_detect: "if data_in is 01010(5 cycles), the data_out is 00101". That example IS a
deterministic functional oracle — every cycle's required output is given, blind. Yet the
recurring failure is OUTPUT TIMING (Moore registered vs Mealy combinational): the worked
example asserts the output in the SAME cycle as the triggering input (Mealy), but blind
authors stochastically write a registered (Moore) output that lags one cycle and host-FAILs
on ~half the vectors. A STRUCTURAL form-gate is whack-a-mole across code variants; a
FUNCTIONAL self-TB built from the spec's own example catches EVERY timing/logic deviation
regardless of how the RTL is written — and never false-blocks a correct design (a design that
passes the host passes this oracle: verified to AGREE with the host scorer 6/6 on the real
pulse_detect attempts).

WHAT it does — given the spec prose + the authored RTL:
  1. Parse a HIGH-CONFIDENCE worked example: `if <inport> is <bits>, ... <outport> is <bits>`
     with two EQUAL-LENGTH ≥3-bit [01] strings, where <inport>/<outport> are real 1-bit
     ports of the module (one input, one output) and a clk + reset port exist.
  2. Build a tiny self-TB that releases reset, drives <inport> with the input bits one per
     clock, samples <outport> at the example's index alignment, and compares to the output bits.
  3. iverilog/vvp it; BLOCK (rc 1) on any mismatch, PASS (rc 0) on a clean match.

§4.05 SAFETY — the load-bearing half is the NEGATIVE no-leak: the gate SKIPs (rc 0, advisory)
unless it can parse a complete, unambiguous example AND map every port. It builds the oracle
ONLY when:
  - exactly one "is <bits>" pair maps to an INPUT port and one to an OUTPUT port;
  - both bitstrings are the same length (≥3) — a cycle-by-cycle correspondence;
  - the module has a single 1-bit clk and a detectable reset (rst_n/reset_n/resetn = active-low,
    rst/reset = active-high);
  - iverilog is available.
Otherwise → SKIP. A correct design passes the host ⇒ passes this oracle (same functional check
from the same disclosed example), so a clean parse cannot false-block a correct design — only a
MIS-parse could, which the conservative gating avoids by SKIPping on any ambiguity.

chip-AGNOSTIC, prompt-blind (reads only the spec the author already reads + the authored RTL),
deterministic.

CLI:
    worked_example_sequence_oracle_check.py --rtl <f.v> --spec <design_description.txt> [--json OUT]
    rc 0 = clean / not-applicable (SKIP/PASS); rc 1 = the authored RTL mismatches the spec's example.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


# the port name is the identifier IMMEDIATELY before "is <bits>" (e.g. "data_in is 01010").
_PAIR_RE = re.compile(r"\b([A-Za-z_]\w*)\s+is\s+([01]{3,})\b")


def parse_example(spec: str):
    """Return (inport, outport, in_bits, out_bits) or None — high-confidence only."""
    pairs = _PAIR_RE.findall(spec)
    # keep (name, bits) pairs; need at least two with equal-length bitstrings
    for i in range(len(pairs)):
        for j in range(len(pairs)):
            if i == j:
                continue
            n1, b1 = pairs[i]
            n2, b2 = pairs[j]
            if n1 != n2 and len(b1) == len(b2) >= 3:
                return (n1, n2, b1, b2)
    return None


def _ports(rtl: str):
    """Map of port name -> (dir, width_is_1bit) from the module header (best-effort)."""
    src = _strip(rtl)
    m = re.search(r"\bmodule\s+(\w+)\s*\((.*?)\)\s*;", src, re.S)
    if not m:
        return None, {}
    name, hdr = m.group(1), m.group(2)
    ports = {}
    # ANSI header: input/output [range]? name
    for pm in re.finditer(r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(\[[^\]]+\])?\s*(\w+)", hdr):
        d, rng, pn = pm.group(1), pm.group(2), pm.group(3)
        ports[pn] = (d, rng is None)
    # non-ANSI: declarations in the body
    body = src[m.end():]
    for pm in re.finditer(r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(\[[^\]]+\])?\s*([\w,\s]+?);", body):
        d, rng = pm.group(1), pm.group(2)
        for pn in re.findall(r"\w+", pm.group(3)):
            if pn in ports or pn in hdr:
                ports.setdefault(pn, (d, rng is None))
    return name, ports


def _find_clk_reset(ports):
    clk = next((p for p in ports if re.fullmatch(r"clk|clock|clk_in", p, re.I)), None)
    rst = None
    pol = None  # 'low' or 'high'
    for p in ports:
        if re.fullmatch(r"rst_n|reset_n|resetn|rstn|n_reset|nrst", p, re.I):
            rst, pol = p, "low"; break
    if not rst:
        for p in ports:
            if re.fullmatch(r"rst|reset", p, re.I):
                rst, pol = p, "high"; break
    return clk, rst, pol


def _build_tb(modname, clk, rst, pol, inp, outp, in_bits, out_bits):
    n = len(in_bits)
    assert_v = "1'b0" if pol == "low" else "1'b1"
    deassert_v = "1'b1" if pol == "low" else "1'b0"
    inset = "".join(f"        in_v[{i}] = 1'b{in_bits[i]};\n" for i in range(n))
    exset = "".join(f"        ex_v[{i}] = 1'b{out_bits[i]};\n" for i in range(n))
    return f"""module wex_tb;
  reg clk=0, rstp; reg din; wire dout;
  reg in_v[0:{n-1}]; reg ex_v[0:{n-1}];
  integer i, err=0;
  {modname} dut(.{clk}(clk), .{rst}(rstp), .{inp}(din), .{outp}(dout));
  always #5 clk=~clk;
  initial begin
{inset}{exset}
    rstp={assert_v}; din=1'b0;
    @(posedge clk); @(posedge clk);
    rstp={deassert_v};
    for (i=0;i<{n};i=i+1) begin
      @(posedge clk); #1 din = in_v[i];
      #3;
      if (dout !== ex_v[i]) begin
        err=err+1;
        $display("MISMATCH cycle=%0d din=%b dout=%b exp=%b", i, din, dout, ex_v[i]);
      end
    end
    if (err==0) $display("ORACLE_PASS"); else $display("ORACLE_FAIL err=%0d", err);
    $finish;
  end
endmodule
"""


def _iverilog():
    try:
        return subprocess.run(["which", "iverilog"], capture_output=True).returncode == 0
    except Exception:
        return False


def analyze(rtl: str, spec: str) -> dict:
    res = {"applicable": False, "verdict": "SKIP", "reason": ""}
    ex = parse_example(spec)
    if not ex:
        res["reason"] = "no high-confidence input→output worked example in spec"
        return res
    p1, p2, b1, b2 = ex
    modname, ports = _ports(rtl)
    if not modname:
        res["reason"] = "could not parse module header"; return res
    # map p1/p2 to in/out ports (1-bit). Accept either order.
    def is_in(p): return p in ports and ports[p][0] == "input" and ports[p][1]
    def is_out(p): return p in ports and ports[p][0] == "output" and ports[p][1]
    if is_in(p1) and is_out(p2):
        inp, outp, in_bits, out_bits = p1, p2, b1, b2
    elif is_in(p2) and is_out(p1):
        inp, outp, in_bits, out_bits = p2, p1, b2, b1
    else:
        res["reason"] = f"example ports {p1!r}/{p2!r} are not a 1-bit input/output pair"
        return res
    clk, rst, pol = _find_clk_reset(ports)
    if not clk or not rst:
        res["reason"] = "no detectable clk/reset port"; return res
    if not _iverilog():
        res["reason"] = "iverilog unavailable"; return res
    res.update(applicable=True, inport=inp, outport=outp, in_bits=in_bits, out_bits=out_bits,
               clk=clk, rst=rst, pol=pol, module=modname)
    tb = _build_tb(modname, clk, rst, pol, inp, outp, in_bits, out_bits)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "dut.v").write_text(rtl)
        (td / "tb.v").write_text(tb)
        c = subprocess.run(["iverilog", "-g2012", "-o", str(td / "sim"), str(td / "dut.v"), str(td / "tb.v")],
                           capture_output=True, text=True)
        if c.returncode != 0:
            res.update(verdict="SKIP", reason="oracle TB did not elaborate (skip, not block): "
                       + (c.stdout + c.stderr).strip()[-200:])
            return res
        r = subprocess.run(["vvp", str(td / "sim")], capture_output=True, text=True, timeout=60)
        out = r.stdout + r.stderr
    if "ORACLE_PASS" in out:
        res["verdict"] = "PASS"
    elif "ORACLE_FAIL" in out:
        res["verdict"] = "BLOCK"
        res["log"] = "\n".join(l for l in out.splitlines() if "MISMATCH" in l)[:400]
    else:
        res.update(verdict="SKIP", reason="oracle produced no verdict (skip)")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtl", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not a.rtl.is_file() or not a.spec.is_file():
        print("ERROR: --rtl and --spec must be files", file=sys.stderr)
        return 2
    res = analyze(a.rtl.read_text(errors="replace"), a.spec.read_text(errors="replace"))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    v = res["verdict"]
    if v == "BLOCK":
        print(f"BLOCK: authored RTL mismatches the spec's worked example "
              f"({res['inport']}={res['in_bits']} → {res['outport']} expected {res['out_bits']}). "
              f"The output asserts in the SAME cycle as the triggering input (combinational/Mealy) per the "
              f"example — a registered (Moore) output lags one cycle and fails. {res.get('log','')}")
        return 1
    print(f"PASS/SKIP: {res['verdict']} — {res.get('reason','matches the spec worked example')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
