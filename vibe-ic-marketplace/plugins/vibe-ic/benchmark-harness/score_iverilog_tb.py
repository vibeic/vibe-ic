#!/usr/bin/env python3
"""score_iverilog_tb.py — generic iverilog-substitutes-VCS scorer for Shape B + Shape C.

Generalizes the two scorers used in the 2026-05-28 sweep
(benchmark_external/verilogeval_v2/score_verilogeval.py + .../rtllm/score_rtllm.py).
Driven by the per-benchmark entry in BENCHMARK_REGISTRY.json so a new plugin user
runs `/vibe-ic-benchmark <bench>` and gets the right scoring without writing code.

Substitution disclosure: this scorer uses iverilog 12 -g2012 in place of Synopsys
VCS or Cadence Xcelium (per open-benchmark-methodology skill § 3). It runs vvp
with cwd=design_dir so the official TB's relative-path `$readmemh(...)` resolves
(per § 3 cwd-rule).

LAYOUTS supported (BENCHMARK_REGISTRY.layout):

  Shape B (per-design dir):
    <dataset>/<design>/<prompt_filename>          (e.g. design_description.txt)
    <dataset>/<design>/<tb_filename>              (e.g. testbench.v)
    <run>/samples/<leaf>.v                        (candidate RTL; leaf = last path component of <design>)

  Shape C (flat dataset, one file per piece):
    <dataset>/<Prob><prompt_suffix>               (e.g. _prompt.txt)
    <dataset>/<Prob><tb_suffix>                   (e.g. _test.sv)
    <dataset>/<Prob><ref_suffix>                  (e.g. _ref.sv — compiled with TB if tb_compile_with_ref=true)
    <run>/samples/<Prob>_sample01.sv              (candidate RTL)

Pass detection:
  - PASS iff `pass_regex` matches the vvp stdout/stderr AND (no `fail_regex` match if fail_regex given).
  - Compile-error / sim-timeout / no_sample report explicit FAIL reasons.

Usage examples:
  # Shape B (RTLLM)
  python3 score_iverilog_tb.py --bench rtllm \\
      --dataset /path/to/RTLLM --run /path/to/run_blind_v0126

  # Shape C (VerilogEval-v2)
  python3 score_iverilog_tb.py --bench verilogeval-v2 \\
      --dataset /path/to/dataset_spec-to-rtl --run /path/to/run_fresh_v0125

Honesty: this scorer ONLY touches the hidden testbench/ref/golden at scoring time.
The generation step must be blind (per the skill's absolute-blindness rule).
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile, os, re
from pathlib import Path
from typing import Optional


def _registry_path() -> Path:
    return Path(__file__).resolve().parent / "BENCHMARK_REGISTRY.json"


def _load_bench(name: str) -> dict:
    reg = json.loads(_registry_path().read_text())
    entry = reg.get("benchmarks", {}).get(name)
    if not entry:
        raise SystemExit(f"Benchmark '{name}' not in BENCHMARK_REGISTRY.json. "
                         f"Known: {sorted(reg.get('benchmarks', {}).keys())}")
    if entry.get("shape") not in ("B", "C"):
        raise SystemExit(f"Benchmark '{name}' is Shape {entry.get('shape')} — "
                         f"this scorer handles only B + C. Use the matching scorer "
                         f"(e.g. score_cocotb_mcp.py for Shape D).")
    return entry


def _problems_list_shape_c(run: Path, dataset: Path, prompt_suffix: str) -> list[str]:
    """Return ordered list of <Prob> identifiers for Shape C from problems.list, or
    discovered from the dataset if no problems.list."""
    pl = run / "problems.list"
    if pl.is_file():
        return [l.strip() for l in pl.read_text().splitlines() if l.strip()]
    # discovery fallback: list of files matching <Prob><prompt_suffix>
    return sorted(p.name.removesuffix(prompt_suffix)
                  for p in dataset.glob(f"*{prompt_suffix}"))


def _problems_list_shape_b(run: Path, dataset: Path, prompt_filename: str) -> list[str]:
    """Return ordered list of design dirs (relative to dataset) for Shape B."""
    pl = run / "problems.list"
    if pl.is_file():
        return [l.strip() for l in pl.read_text().splitlines() if l.strip()]
    # discovery fallback
    return sorted(str(p.parent.relative_to(dataset))
                  for p in dataset.rglob(prompt_filename) if p.is_file())


def _score_shape_b(design: str, samples: Path, dataset: Path,
                   layout: dict, args: dict) -> dict:
    leaf = design.split("/")[-1]
    sample = samples / f"{leaf}.v"
    tb = dataset / design / layout["tb_filename"]
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
            # cwd=design dir so the TB's relative-path $readmemh works (skill §3)
            r = subprocess.run(["vvp", binp], capture_output=True, text=True,
                               timeout=120,
                               cwd=str(dataset / design) if args.get("cwd_design_dir", True) else None)
        except subprocess.TimeoutExpired:
            return {"design": design, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        pass_re = re.compile(args["pass_regex"])
        fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
        if pass_re.search(out):
            if fail_re and fail_re.search(out):
                m = re.search(r"(\d+)\s*/\s*\d+\s*failures", out)
                return {"design": design, "verdict": "FAIL",
                        "reason": f"functional_mismatch ({m.group(0) if m else 'test failed'})"}
            return {"design": design, "verdict": "PASS"}
        return {"design": design, "verdict": "FAIL",
                "reason": "no_pass_marker" + (" (some Test failed)" if fail_re and fail_re.search(out) else "")}


def _score_shape_c(prob: str, samples: Path, dataset: Path,
                   layout: dict, args: dict) -> dict:
    sample = samples / f"{prob}_sample01.sv"
    test = dataset / f"{prob}{layout['tb_suffix']}"
    ref = dataset / f"{prob}{layout['ref_suffix']}" if layout.get("ref_suffix") else None
    if not sample.is_file():
        return {"problem": prob, "verdict": "FAIL", "reason": "no_sample"}
    sources = [str(sample), str(test)]
    if args.get("tb_compile_with_ref") and ref:
        if not ref.is_file():
            return {"problem": prob, "verdict": "FAIL", "reason": "no_ref"}
        sources.append(str(ref))
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        cmd = ["iverilog", "-g2012", "-s", "tb", "-o", binp] + sources
        c = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if c.returncode != 0:
            # retry without -s tb if the TB module isn't named "tb"
            c = subprocess.run(["iverilog", "-g2012", "-o", binp] + sources,
                               capture_output=True, text=True, timeout=120)
            if c.returncode != 0:
                return {"problem": prob, "verdict": "FAIL", "reason": "compile_error",
                        "log": c.stderr[-400:]}
        try:
            r = subprocess.run(["vvp", binp], capture_output=True, text=True,
                               timeout=120,
                               cwd=str(dataset) if args.get("cwd_design_dir", False) else None)
        except subprocess.TimeoutExpired:
            return {"problem": prob, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        if re.search(args["pass_regex"], out):
            return {"problem": prob, "verdict": "PASS"}
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        return {"problem": prob, "verdict": "FAIL",
                "reason": f"functional_mismatch ({m.group(0) if m else 'no summary'})"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bench", required=True, help="benchmark name (key in BENCHMARK_REGISTRY.json)")
    ap.add_argument("--dataset", required=True, help="path to the benchmark dataset on disk")
    ap.add_argument("--run", required=True, help="path to the run dir (with samples/, problems.list)")
    ap.add_argument("--emit-close-loop-tasklist", default="",
                    help="v0.1.38: when set, emit a JSON file at this path listing fails + "
                         "their verdicts + their prompt path. Intended as input to a second-pass "
                         "close-loop agent driver (per Vibe-IC architecture: programs first, then "
                         "Claude judgment as backup). This file is NOT the close-loop runner — it "
                         "encodes the WHAT, the orchestrator calling Claude calls the HOW. The "
                         "open-benchmark-methodology skill § 1 'program + LLM backup' contract.")
    a = ap.parse_args()

    entry = _load_bench(a.bench)
    shape = entry["shape"]
    layout = entry["layout"]
    args = entry["scorer_args"]
    dataset, run = Path(a.dataset), Path(a.run)
    samples = run / "samples"
    if not samples.is_dir():
        raise SystemExit(f"Expected {samples}/ with candidate RTL — directory missing.")

    if shape == "B":
        designs = _problems_list_shape_b(run, dataset, layout["prompt_filename"])
        results = [_score_shape_b(d, samples, dataset, layout, args) for d in designs]
        ident = "design"
    else:  # Shape C
        probs = _problems_list_shape_c(run, dataset, layout["prompt_suffix"])
        results = [_score_shape_c(p, samples, dataset, layout, args) for p in probs]
        ident = "problem"

    npass = sum(1 for r in results if r["verdict"] == "PASS")
    n = len(results)
    summary = {
        "benchmark": entry["title"],
        "shape": shape,
        "tool": "iverilog 12 (host) substituting for Synopsys VCS / Cadence Xcelium",
        "tool_substitution_note": "Functional pass@1 only. PPA stage (DC) not scored — would not be apples-to-apples vs the upstream methodology. See open-benchmark-methodology skill § 3.",
        "total": n, "passed": npass,
        "pass_at_1_pct": round(100.0 * npass / n, 2) if n else 0.0,
        "results": results,
    }
    (run / "pass_at_1.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{entry['title']}  pass@1 = {npass}/{n} = {summary['pass_at_1_pct']}%  [Shape {shape}]")
    fails = [r for r in results if r["verdict"] != "PASS"]
    if fails:
        print(f"  fails ({len(fails)}): " +
              ", ".join(f"{(r[ident].split('/')[-1])}:{r['reason'].split()[0]}" for r in fails[:25]) +
              ("..." if len(fails) > 25 else ""))
    print("  pass_at_1.json:", run / "pass_at_1.json")

    # v0.1.38 — emit close-loop tasklist for the Vibe-IC "programs first, then
    # Claude judgment as backup" architecture. The 22-agent v0.1.37 sweep showed
    # that fresh blind one-shot lands ~95% on VerilogEval and ~72% on RTLLM;
    # the close-loop second pass (AI re-authors fails using pass/FAIL feedback
    # only, NEVER reading hidden TB) recovers ~3% on VerilogEval and ~24% on
    # RTLLM. Emitting this tasklist makes that path turnkey for future runs.
    if a.emit_close_loop_tasklist and fails:
        tasklist = {
            "benchmark": entry["title"],
            "shape": shape,
            "run_dir": str(run),
            "dataset_dir": str(dataset),
            "fail_count": len(fails),
            "fails": [
                {"id": r[ident],
                 "prior_sample": str(samples / (f"{r[ident].split('/')[-1]}_sample01.sv"
                                               if shape == "C" else f"{r[ident].split('/')[-1]}.v")),
                 "prompt": str(dataset / (f"{r[ident].split('/')[-1]}{layout.get('prompt_suffix', '')}"
                                          if shape == "C" else
                                          f"{r[ident]}/{layout.get('prompt_filename', '')}")),
                 "verdict": r["verdict"],
                 "reason": r.get("reason", ""),
                 "retry_budget": 3,
                 "blind_contract": (
                     "READ-ALLOWED: prompt, prior_sample, scorer PASS/FAIL verdict only. "
                     "READ-FORBIDDEN: any hidden TB / testbench / verified_*.v / "
                     "<Prob>_test.sv / <Prob>_ref.sv / cocotb harness. Peeking = "
                     "benchmark fraud per open-benchmark-methodology skill § 3.")}
                for r in fails],
            "rescore_command": (
                f"python3 {Path(__file__).name} --bench {a.bench} "
                f"--dataset {dataset} --run {run}"),
        }
        Path(a.emit_close_loop_tasklist).write_text(
            json.dumps(tasklist, indent=2) + "\n")
        print(f"  close_loop_tasklist:", a.emit_close_loop_tasklist)


if __name__ == "__main__":
    main()
