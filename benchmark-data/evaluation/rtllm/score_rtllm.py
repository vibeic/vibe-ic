#!/usr/bin/env python3
"""Deterministic RTLLM v2.0 scorer (host iverilog 12 — substitutes for Synopsys VCS).

For each design in <run>/problems.list (relative dir under the RTLLM dataset root):
  iverilog -g2012 -o bin <run>/samples/<leaf>.v <dataset>/<design>/testbench.v ; vvp bin
  PASS iff it compiles AND the official testbench prints "Your Design Passed"
  (and shows no "Test failed" line / nonzero failure count).

Substitution disclosure: RTLLM's auto_run.py uses `vcs testbench.v ../*.v` (Synopsys VCS)
+ Design Compiler for the PPA stage. This host has neither; iverilog -g2012 runs the same
standard-Verilog testbenches for the FUNCTIONAL pass@1 (the primary metric). The DC quality
stage is not scored here (noted as a deviation). This mirrors the disclosed iverilog/icarus
substitution already used for VerilogEval + CVDP.

Honesty: the scorer is the ONLY place that touches testbench.v / verified_*.v. Generation is
blind (design_description.txt only). Every design in problems.list is scored; a missing sample
counts as FAIL (no_sample).

Usage: python3 score_rtllm.py [--run <dir>] [--dataset <RTLLM root>]
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile, os, re
from pathlib import Path

EB = Path(__file__).resolve().parent
DEF_RUN = EB / "run_blind_v0126"
DEF_DS = Path("/home/reyerchu/AI_IC_design/_extbench/RTLLM")
PASS_RE = re.compile(r"Your Design Passed")
FAIL_RE = re.compile(r"Test failed|Your Design Failed|failures", re.IGNORECASE)


def score_one(design: str, samples: Path, ds: Path) -> dict:
    leaf = design.split("/")[-1]
    sample = samples / f"{leaf}.v"
    tb = ds / design / "testbench.v"
    if not sample.is_file():
        return {"design": design, "verdict": "FAIL", "reason": "no_sample"}
    if not tb.is_file():
        return {"design": design, "verdict": "FAIL", "reason": "no_testbench"}
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        c = subprocess.run(["iverilog", "-g2012", "-o", binp, str(sample), str(tb)],
                           capture_output=True, text=True, timeout=120)
        if c.returncode != 0:
            return {"design": design, "verdict": "FAIL", "reason": "compile_error",
                    "log": c.stderr[-400:]}
        try:
            # Run vvp FROM the design dir so the official TB's relative-path
            # `$readmemh("reference.txt"|"reference.dat"|"tri_gen.txt")` resolves —
            # exactly as RTLLM's auto_run.py does (os.chdir(design); make vcs).
            r = subprocess.run(["vvp", binp], capture_output=True, text=True,
                               timeout=120, cwd=str(ds / design))
        except subprocess.TimeoutExpired:
            return {"design": design, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        if PASS_RE.search(out):
            # "Your Design Passed" is the authoritative marker; some TBs also print a
            # failure count line — only flag if a real "Test failed" appears.
            if re.search(r"Test failed", out):
                m = re.search(r"(\d+)\s*/\s*\d+\s*failures", out)
                return {"design": design, "verdict": "FAIL",
                        "reason": f"functional_mismatch ({m.group(0) if m else 'test failed'})"}
            return {"design": design, "verdict": "PASS"}
        return {"design": design, "verdict": "FAIL",
                "reason": "no_pass_marker" + (" (some Test failed)" if FAIL_RE.search(out) else "")}


# Known upstream-dataset defects: the design_description contradicts / under-determines
# its own hidden testbench, so NO §4.05-blind author can recover them without peeking at
# the oracle (= cheating). NOT vibe-ic plugin gaps. Durable record + rationale:
#   community/backlogs/ORGANIC-20260706-rtllm-description-testbench-interface-contradictions.yaml
#   + GitHub #106. Keyed by directory-leaf so it is dataset-path independent.
KNOWN_DATASET_DEFECTS = {
    "radix2_div":       "desc omits the res_ready handshake INPUT the TB drives",
    "sequence_detector": "desc names reset `reset_n`; TB instantiates `.rst_n`",
    "adder_pipe_64bit": "TB overrides #(DATA_WIDTH, STG_WIDTH); desc names no parameters",
    "LFSR":             "TB positional output-first `LFSR DUT(out,clk,rst)`; desc doesn't fix header order",
    "freq_divbyeven":   "TB relies on the module default NUM_DIV=6; desc states no default value",
}
# iverilog-12 lacks a SystemVerilog TB feature these designs' testbenches use; they PASS
# under the disclosed Verilator substitution. TB-side, not RTL-side — not a plugin gap.
KNOWN_TOOL_GAPS = {
    "ring_counter": "TB uses whole-array/array-slice assignment (Verilator PASS)",
    "asyn_fifo":    "TB uses `break` (Verilator PASS)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(DEF_RUN))
    ap.add_argument("--dataset", default=str(DEF_DS))
    a = ap.parse_args()
    run, ds = Path(a.run), Path(a.dataset)
    designs = [l.strip() for l in (run / "problems.list").read_text().splitlines() if l.strip()]
    samples = run / "samples"
    results = [score_one(d, samples, ds) for d in designs]
    # Annotate known upstream defects / tool-gaps so a fail on one is NEVER re-diagnosed
    # as a fresh plugin gap, and the "excluding-defects" number is computed automatically.
    for r in results:
        leaf = r["design"].split("/")[-1]
        if leaf in KNOWN_DATASET_DEFECTS:
            r["known_dataset_defect"] = KNOWN_DATASET_DEFECTS[leaf]
        elif leaf in KNOWN_TOOL_GAPS:
            r["known_tool_gap"] = KNOWN_TOOL_GAPS[leaf]
    npass = sum(1 for r in results if r["verdict"] == "PASS")
    n = len(results)
    defect_fails = [r for r in results if r["verdict"] != "PASS" and "known_dataset_defect" in r]
    toolgap_fails = [r for r in results if r["verdict"] != "PASS" and "known_tool_gap" in r]
    excl_den = n - len(defect_fails) - len(toolgap_fails)
    summary = {
        "benchmark": "RTLLM v2.0 (spec-to-RTL)",
        "tool": "iverilog 12 (host) substituting for Synopsys VCS; functional pass@1",
        "total": n, "passed": npass,
        "pass_at_1_pct": round(100.0 * npass / n, 2) if n else 0.0,
        "known_dataset_defects": len(defect_fails),
        "known_tool_gaps": len(toolgap_fails),
        "passed_excluding_defects_and_toolgaps": npass,
        "denominator_excluding_defects_and_toolgaps": excl_den,
        "pass_at_1_excl_pct": round(100.0 * npass / excl_den, 2) if excl_den else 0.0,
        "results": results,
    }
    (run / "pass_at_1.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"RTLLM v2.0 spec-to-RTL  pass@1 = {npass}/{n} = {summary['pass_at_1_pct']}%")
    if defect_fails or toolgap_fails:
        print(f"  excluding {len(defect_fails)} known dataset defect(s) + {len(toolgap_fails)} "
              f"tool-gap(s) = {npass}/{excl_den} = {summary['pass_at_1_excl_pct']}%  (see GitHub #106)")
    fails = [r for r in results if r["verdict"] != "PASS"]
    if fails:
        def _tag(r):
            if "known_dataset_defect" in r: return "[dataset-defect]"
            if "known_tool_gap" in r: return "[tool-gap]"
            return ""
        print(f"  fails ({len(fails)}): " +
              ", ".join(f"{r['design'].split('/')[-1]}:{r['reason'].split()[0]}{_tag(r)}" for r in fails[:30]) +
              ("..." if len(fails) > 30 else ""))


if __name__ == "__main__":
    main()
