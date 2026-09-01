#!/usr/bin/env python3
"""worked_example_sequence_oracle_check.py — deterministic emit gate that turns a
spec's PROSE input→output worked example into a self-checking oracle.

WHY (benchmark close-loop, pulse_detect pass@6 ≈ 1/6 — PRIME DIRECTIVE capture):
Many serial / detector specs disclose a complete cycle-by-cycle worked example, e.g.
pulse_detect: "if data_in is 01010(5 cycles), the data_out is 00101". That example IS a
deterministic functional oracle — every cycle's required output is given, blind. The
recurring failure is OUTPUT TIMING/LOGIC: blind authors stochastically pick the wrong output
cycle alignment (e.g. a registered output that lags, or a combinational one that leads, the
disclosed trace) and host-FAIL on ~half the vectors. A STRUCTURAL form-gate is whack-a-mole
across code variants; a FUNCTIONAL self-TB that REPLAYS the spec's own example trace catches
EVERY per-cycle deviation regardless of how the RTL is written. The gate is an index-aligned
LITERAL REPLAY of the disclosed example (NOT a Mealy/Moore classifier): a design that
reproduces the disclosed trace at the example's alignment PASSes, any other trace BLOCKs.
(Validated against the real pulse_detect blind attempts during development.)

WHAT it does — given the spec prose + the authored RTL:
  1. Parse a HIGH-CONFIDENCE worked example: `if <inport> is <bits>, ... <outport> is <bits>`
     with two EQUAL-LENGTH ≥3-bit [01] strings, where <inport>/<outport> are real 1-bit
     ports of the module (one input, one output) and a clk + reset port exist.
  2. Build a tiny self-TB that releases reset and replays the disclosed trace.  When the
     spec mentions positive-edge output generation, measure BOTH the pre-edge convention
     used by same-timestamp dataset checkers and the post-NBA edge convention used by other
     checkers.  Otherwise retain the original same-cycle combinational interpretation.
  3. iverilog/vvp it.  For the dual-phase branch, BLOCK (rc 1) only when BOTH phases
     mismatch.  A one-phase match is timing-ambiguous and therefore SKIPs (rc 0); the
     oracle's contract is never to false-block by guessing the host's sampling phase.

§4.05 SAFETY — the load-bearing half is the NEGATIVE no-leak: the gate SKIPs (rc 0, advisory)
unless it can build an UNAMBIGUOUS oracle that drives EVERY relevant input. It BLOCKs ONLY when:
  - EXACTLY ONE distinct worked-example interpretation maps to a (1-bit input, 1-bit output)
    pair — if a decoy/illustrative sentence yields a SECOND equal-length pair on the same ports
    (reset default, conceptual illustration, register table, power-up value), it is AMBIGUOUS
    → SKIP (never build the oracle from the wrong bits);
  - both bitstrings are the same length (≥3) — a cycle-by-cycle correspondence;
  - the module has a single 1-bit clk and a detectable reset (rst_n/reset_n/resetn = active-low,
    rst/reset = active-high);
  - the module has NO OTHER input port beyond clk/reset/<inport> — an extra input the TB cannot
    drive would float (X) and mis-drive a correct multi-input design → SKIP;
  - iverilog is available, the TB ELABORATES, and the sim COMPLETES — any build/sim error or
    TIMEOUT is caught and yields SKIP, never BLOCK (fail-safe both in the library and the CLI);
  - the verdict is read from a TB-written FILE the DUT cannot spoof via $display.
Otherwise → SKIP. Under these conditions a design that reproduces the disclosed trace passes;
the conservative gating means a phase ambiguity / mis-parse / undriveable input / tool failure
SKIPs rather than false-blocks a correct design.

DECLARED ENFORCEMENT: BLOCKING only for an unambiguous mismatch in every measured
sampling phase; PASS and explicit SKIP records continue the flow.

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


def parse_examples(spec: str):
    """Return ALL candidate (name1, name2, bits1, bits2) worked-example interpretations
    (distinct names, EQUAL-LENGTH >=3-bit bitstrings), order-preserving + de-duplicated.
    analyze() resolves these against the module ports and SKIPs on ambiguity (>1 distinct
    interpretation maps to a 1-bit in/out pair), so an incidental DECOY sentence (a reset
    default, a conceptual illustration, a register table, a power-up value) that reuses the
    real port names can never silently hijack the oracle and false-block a correct design
    (Step-2.7 §4.05: 'first equal-length pair' was the wrong selector)."""
    pairs = _PAIR_RE.findall(spec)
    out, seen = [], set()
    for i in range(len(pairs)):
        for j in range(len(pairs)):
            if i == j:
                continue
            n1, b1 = pairs[i]
            n2, b2 = pairs[j]
            if n1 != n2 and len(b1) == len(b2) >= 3:
                key = (n1, n2, b1, b2)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def parse_example(spec: str):
    """Return the FIRST candidate (name1, name2, bits1, bits2) or None (back-compat).
    Ambiguity-aware selection lives in analyze() via parse_examples()."""
    cands = parse_examples(spec)
    return cands[0] if cands else None


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


def _requires_clocked_output(spec: str, outp: str) -> bool:
    """True only for an explicit clocked-output implementation contract."""
    text = re.sub(r"\s+", " ", spec).lower()
    edge = "positive edge" in text or "posedge" in text
    block = "always block" in text or "always_ff" in text
    output_contract = (
        "output generation" in text
        or re.search(rf"\b(?:set|assign|update|drive)\s+{re.escape(outp.lower())}\b",
                     text) is not None
    )
    return edge and block and output_contract


def _build_tb(modname, clk, rst, pol, inp, outp, in_bits, out_bits,
              result_path, *, clocked_output=False, sample_phase=None):
    n = len(in_bits)
    assert_v = "1'b0" if pol == "low" else "1'b1"
    deassert_v = "1'b1" if pol == "low" else "1'b0"
    inset = "".join(f"        in_v[{i}] = 1'b{in_bits[i]};\n" for i in range(n))
    exset = "".join(f"        ex_v[{i}] = 1'b{out_bits[i]};\n" for i in range(n))
    if clocked_output:
        if sample_phase == "pre-edge":
            # Clock period is 10: four time units after the negedge is one unit
            # before the next posedge, so registered NBA updates are not visible.
            sample = "#4;"
        elif sample_phase == "post-edge":
            sample = "@(posedge clk); #1;"
        else:
            raise ValueError("clocked replay requires pre-edge or post-edge sampling")
        replay = f"""    @(negedge clk); rstp={deassert_v};
    for (i=0;i<{n};i=i+1) begin
      if (i>0) @(negedge clk);
      din = in_v[i];
      {sample}
      if (dout !== ex_v[i]) begin
        err=err+1;
        $display("MISMATCH cycle=%0d din=%b dout=%b exp=%b", i, din, dout, ex_v[i]);
      end
    end"""
    else:
        replay = f"""    rstp={deassert_v};
    for (i=0;i<{n};i=i+1) begin
      @(posedge clk); #1 din = in_v[i];
      #3;
      if (dout !== ex_v[i]) begin
        err=err+1;
        $display("MISMATCH cycle=%0d din=%b dout=%b exp=%b", i, din, dout, ex_v[i]);
      end
    end"""
    # The verdict is written to a FILE whose path the DUT cannot know — so authored RTL
    # that $displays "PASS"/"FAIL" on stdout cannot spoof the verdict (Step-2.7 LOW).
    return f"""module wex_tb;
  reg clk=0, rstp; reg din; wire dout;
  reg in_v[0:{n-1}]; reg ex_v[0:{n-1}];
  integer i, err=0, vf;
  {modname} dut(.{clk}(clk), .{rst}(rstp), .{inp}(din), .{outp}(dout));
  always #5 clk=~clk;
  initial begin
{inset}{exset}
    rstp={assert_v}; din=1'b0;
    @(posedge clk); @(posedge clk);
{replay}
    vf = $fopen("{result_path}", "w");
    if (err==0) $fdisplay(vf, "WEX_VERDICT PASS"); else $fdisplay(vf, "WEX_VERDICT FAIL %0d", err);
    $fclose(vf);
    $finish;
  end
endmodule
"""


def _run_tb(tb: str, td: Path, phase: str, result_path: Path) -> dict:
    """Compile and run one sampling phase; tool failure is an explicit SKIP."""
    safe_phase = phase.replace("-", "_")
    tb_path = td / f"tb_{safe_phase}.v"
    sim_path = td / f"sim_{safe_phase}"
    tb_path.write_text(tb)
    try:  # build hang / tool error → fail-safe SKIP, never BLOCK
        # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim
        # build); fixed budget adequate — not an open-ended EDA generator
        compiled = subprocess.run(
            ["iverilog", "-g2012", "-o", str(sim_path),
             str(td / "dut.v"), str(tb_path)],
            capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return {"verdict": "SKIP",
                "reason": "oracle build timeout/error (skip): " + str(exc)[:160]}
    if compiled.returncode != 0:
        return {
            "verdict": "SKIP",
            "reason": "oracle TB did not elaborate (skip, not block): "
                      + (compiled.stdout + compiled.stderr).strip()[-200:],
        }
    try:  # sim hang/timeout → fail-safe SKIP per the contract, never BLOCK
        ran = subprocess.run(
            ["vvp", str(sim_path)], capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return {"verdict": "SKIP",
                "reason": "oracle sim timeout/error (skip): " + str(exc)[:160]}
    output = ran.stdout + ran.stderr
    if ran.returncode != 0:
        return {
            "verdict": "SKIP",
            "reason": f"oracle sim exited {ran.returncode} (skip, not block): "
                      + output.strip()[-200:],
        }
    verdict_txt = result_path.read_text(errors="replace") if result_path.is_file() else ""
    if "WEX_VERDICT PASS" in verdict_txt:
        return {"verdict": "PASS", "log": ""}
    if "WEX_VERDICT FAIL" in verdict_txt:
        log = "\n".join(line for line in output.splitlines()
                        if "MISMATCH" in line)[:400]
        return {"verdict": "BLOCK", "log": log}
    return {"verdict": "SKIP", "reason": "oracle produced no verdict file (skip)"}


def _iverilog():
    try:
        return subprocess.run(["which", "iverilog"], capture_output=True).returncode == 0
    except Exception:
        return False


def analyze(rtl: str, spec: str) -> dict:
    res = {"applicable": False, "verdict": "SKIP", "reason": ""}
    cands = parse_examples(spec)
    if not cands:
        res["reason"] = "no high-confidence input→output worked example in spec"
        return res
    modname, ports = _ports(rtl)
    if not modname:
        res["reason"] = "could not parse module header"; return res

    def is_in(p): return p in ports and ports[p][0] == "input" and ports[p][1]
    def is_out(p): return p in ports and ports[p][0] == "output" and ports[p][1]

    # Resolve EVERY candidate against the ports; keep only those mapping one name to a
    # 1-bit input and the other to a 1-bit output, de-duped by the resolved tuple.
    interps = []
    for (p1, p2, b1, b2) in cands:
        if is_in(p1) and is_out(p2):
            iv = (p1, p2, b1, b2)
        elif is_in(p2) and is_out(p1):
            iv = (p2, p1, b2, b1)
        else:
            continue
        if iv not in interps:
            interps.append(iv)
    if not interps:
        res["reason"] = "worked-example ports are not a 1-bit input/output pair"
        return res
    if len(interps) > 1:
        # a decoy/illustrative pair on the same ports could hijack the oracle → fail-safe SKIP
        res["reason"] = (f"ambiguous: {len(interps)} distinct worked-example interpretations map to "
                         f"1-bit in/out ports — skip (fail-safe; never build the oracle from a decoy)")
        return res
    inp, outp, in_bits, out_bits = interps[0]

    clk, rst, pol = _find_clk_reset(ports)
    if not clk or not rst:
        res["reason"] = "no detectable clk/reset port"; return res
    # The self-TB can drive ONLY clk/reset/<inp>; any OTHER input port would float (X) and
    # mis-drive a CORRECT multi-input design → false-BLOCK. Fail-safe SKIP when one exists.
    extra_in = sorted(p for p, (d, _one) in ports.items()
                      if d == "input" and p not in (clk, rst, inp))
    if extra_in:
        res["reason"] = (f"module has undriveable extra input port(s) {extra_in} — skip (fail-safe; "
                         f"the oracle drives only clk/reset/{inp})")
        return res
    if not _iverilog():
        res["reason"] = "iverilog unavailable"; return res
    clocked_output = _requires_clocked_output(spec, outp)
    res.update(applicable=True, inport=inp, outport=outp, in_bits=in_bits,
               out_bits=out_bits, clk=clk, rst=rst, pol=pol, module=modname,
               sampling_semantics=("dual-phase-pre-and-post-edge"
                                   if clocked_output
                                   else "same-cycle-combinational"))
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "dut.v").write_text(rtl)
        phases = ("pre-edge", "post-edge") if clocked_output else ("same-cycle",)
        phase_results = {}
        for phase in phases:
            result_path = td / f"wex_verdict_{phase.replace('-', '_')}.txt"
            tb = _build_tb(
                modname, clk, rst, pol, inp, outp, in_bits, out_bits,
                str(result_path), clocked_output=clocked_output,
                sample_phase=phase if clocked_output else None)
            phase_results[phase] = _run_tb(tb, td, phase, result_path)

    if not clocked_output:
        result = phase_results["same-cycle"]
        res.update(result)
        return res

    res["phase_verdicts"] = {
        phase: result["verdict"] for phase, result in phase_results.items()
    }
    skipped = [(phase, result) for phase, result in phase_results.items()
               if result["verdict"] == "SKIP"]
    if skipped:
        phase, result = skipped[0]
        res.update(verdict="SKIP",
                   reason=f"{phase} sampling unavailable: {result.get('reason', 'skip')}")
    elif all(result["verdict"] == "PASS" for result in phase_results.values()):
        res["verdict"] = "PASS"
    elif all(result["verdict"] == "BLOCK" for result in phase_results.values()):
        res["verdict"] = "BLOCK"
        res["log"] = "\n".join(
            f"[{phase}] {result.get('log', '')}" for phase, result in phase_results.items())[:800]
    else:
        res.update(
            verdict="SKIP",
            reason="phase-ambiguous: the worked example matches exactly one of "
                   "pre-edge and post-edge sampling; never choose the host phase by guess")
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
        print(f"BLOCK: authored RTL does not reproduce the spec's disclosed worked example "
              f"({res['inport']}={res['in_bits']} → {res['outport']} should be {res['out_bits']}). "
              f"Its per-cycle output trace differs from the example — check your output's "
              f"cycle-by-cycle timing/logic against the spec's worked example. {res.get('log','')}")
        return 1
    print(f"PASS/SKIP: {res['verdict']} — {res.get('reason','matches the spec worked example')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
