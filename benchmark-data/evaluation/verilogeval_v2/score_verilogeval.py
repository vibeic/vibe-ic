#!/usr/bin/env python3
"""Deterministic VerilogEval-v2 spec-to-rtl scorer (host iverilog 12, official method).

For each problem with a generated sample in <run>/samples/<Prob>_sample01.sv:
  iverilog -g2012 -s tb -o bin <sample> <Prob>_test.sv <Prob>_ref.sv ; vvp bin
  PASS iff it compiles AND vvp prints "Mismatches: 0 in" (the official testbench summary).
Emits per-problem results + pass@1 = passes / total_problems.

Honesty: the scorer is the ONLY place that touches _ref.sv / _test.sv. The generation
step is blind (prompt-only). No cherry-picking: every problem in problems.list is scored;
a missing sample counts as FAIL (no_sample).

Usage: python3 score_verilogeval.py [--run <dir>] [--dataset <dir>]
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile, os, re
from pathlib import Path

EB = Path(__file__).resolve().parent
DEF_RUN = EB / "run_v2"
DEF_DS = EB / "verilog-eval" / "dataset_spec-to-rtl"
PASS_RE = re.compile(r"Mismatches:\s*0\s+in\s+\d+\s+samples")


def score_one(prob: str, samples: Path, ds: Path) -> dict:
    sample = samples / f"{prob}_sample01.sv"
    test = ds / f"{prob}_test.sv"
    ref = ds / f"{prob}_ref.sv"
    if not sample.is_file():
        return {"problem": prob, "verdict": "FAIL", "reason": "no_sample"}
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        c = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", binp,
                            str(sample), str(test), str(ref)],
                           capture_output=True, text=True, timeout=120)
        if c.returncode != 0:
            return {"problem": prob, "verdict": "FAIL", "reason": "compile_error",
                    "log": c.stderr[-400:]}
        try:
            r = subprocess.run(["vvp", binp], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"problem": prob, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        if PASS_RE.search(out):
            return {"problem": prob, "verdict": "PASS"}
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        return {"problem": prob, "verdict": "FAIL",
                "reason": f"functional_mismatch ({m.group(0) if m else 'no summary'})"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(DEF_RUN))
    ap.add_argument("--dataset", default=str(DEF_DS))
    a = ap.parse_args()
    run, ds = Path(a.run), Path(a.dataset)
    probs = [l.strip() for l in (run / "problems.list").read_text().splitlines() if l.strip()]
    samples = run / "samples"
    results = [score_one(p, samples, ds) for p in probs]
    npass = sum(1 for r in results if r["verdict"] == "PASS")
    n = len(results)
    summary = {
        "benchmark": "VerilogEval-v2 spec-to-rtl",
        "tool": "iverilog 12 (host), official testbench scoring",
        "total": n, "passed": npass,
        "pass_at_1_pct": round(100.0 * npass / n, 2) if n else 0.0,
        "results": results,
    }
    (run / "pass_at_1.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"VerilogEval-v2 spec-to-rtl  pass@1 = {npass}/{n} = {summary['pass_at_1_pct']}%")
    fails = [r for r in results if r["verdict"] != "PASS"]
    if fails:
        print(f"  fails ({len(fails)}): " +
              ", ".join(f"{r['problem']}:{r['reason'].split()[0]}" for r in fails[:25]) +
              ("..." if len(fails) > 25 else ""))


if __name__ == "__main__":
    main()
