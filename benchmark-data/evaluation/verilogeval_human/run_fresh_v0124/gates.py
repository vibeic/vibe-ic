#!/usr/bin/env python3
"""Deterministic Phase1->Phase2 gate driver for one VerilogEval-v2 problem (v0.1.10).

The agent authors two files in <workdir>/<prob>/:
  - spec.yaml   (PM-Agent output: ic_name/class_path/L1 desc/L9 ports, from the PROMPT ONLY)
  - sample.sv   (blind RTL targeting the L9 contract, from the PROMPT ONLY)

This driver runs the deterministic pipeline + gates (no hidden test/ref ever touched):
  1. phase1_engine run-all  spec.yaml -> generated_docs/L*.json   (structured contract)
  2. spec_self_consistency_check --spec <prompt>                  (pre-RTL lint)
  3. iverilog -g2012 compile of sample.sv                         (syntax gate)
  4. spec_conformance_check --rtl-dir . --spec <prompt>           (port/width/reset vs prompt contract)

On compile PASS it copies sample.sv -> ../samples/<prob>_sample01.sv (the scoreable artifact).
Emits <workdir>/<prob>/gates.json with each step's verdict so the agent can fix flagged
ERRORs and re-run. Exit 0 iff run-all + compile PASS (the two hard gates).

Usage: python3 gates.py --prob <Prob...> [--workdir work] [--dataset <ds>]
"""
from __future__ import annotations
import argparse, json, subprocess, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]                      # /home/reyerchu/vibe-ic
PROG = REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs"
DEF_DS = Path("/home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl")


def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prob", required=True)
    ap.add_argument("--workdir", default=str(HERE / "work"))
    ap.add_argument("--dataset", default=str(DEF_DS))
    a = ap.parse_args()

    ds = Path(a.dataset)
    prompt = ds / f"{a.prob}_prompt.txt"
    wd = Path(a.workdir) / a.prob
    spec = wd / "spec.yaml"
    sample = wd / "sample.sv"
    steps = {}

    if not prompt.is_file():
        print(f"NO_PROMPT {prompt}"); sys.exit(2)
    for f in (spec, sample):
        if not f.is_file():
            print(f"MISSING {f} — author it first"); sys.exit(2)

    # 1. phase1_engine run-all
    rc, out = run([sys.executable, "-m", "tools.phase1_engine.cli",
                   "run-all", str(spec), str(wd / "out")], cwd=str(REPO))
    gd = wd / "out/generated_docs"
    l9_ok = gd.is_dir() and any(gd.glob("L9*.json"))
    steps["phase1_run_all"] = {"verdict": "PASS" if rc == 0 and l9_ok else "FAIL",
                               "rc": rc, "l9_rendered": l9_ok, "log": out[-400:]}

    # 2. pre-RTL spec self-consistency lint (prompt alone)
    rc, out = run([sys.executable, str(PROG / "spec_self_consistency_check.py"),
                   "--spec", str(prompt)])
    steps["spec_self_consistency"] = {"verdict": "PASS" if "PASS" in out else "WARN",
                                      "rc": rc, "log": out[-300:]}

    # 3. iverilog -g2012 syntax compile (no test/ref)
    rc, out = run(["iverilog", "-g2012", "-o", str(wd / "syn.bin"), str(sample)])
    steps["iverilog_compile"] = {"verdict": "PASS" if rc == 0 else "FAIL",
                                 "rc": rc, "log": out[-400:]}

    # 4. spec_conformance_check vs prompt-derived contract (+ semantic confirm manifest)
    sem_manifest = wd / "semantic_manifest.json"
    rc, out = run([sys.executable, str(PROG / "spec_conformance_check.py"),
                   "--rtl-dir", str(wd), "--spec", str(prompt), "--top", "TopModule",
                   "--semantic-manifest", str(sem_manifest)])
    cverd = "PASS" if "PASS" in out.split("\n")[0] else ("WARN" if "WARN" in out else "FAIL")
    steps["spec_conformance"] = {"verdict": cverd, "rc": rc, "log": out[-500:]}
    if sem_manifest.is_file():
        try:
            steps["semantic_confirm"] = json.loads(sem_manifest.read_text())
        except Exception:
            pass

    # 5a. ENFORCE the power-up determinism lesson (v0.1.24): repair reset-less
    #     registered outputs in-place (insert `initial <reg>=0;`) BEFORE emit, so the
    #     blind harness can never leak a power-up-X sample. Structural + prompt-blind +
    #     hidden-test-blind — does NOT over-fit. Closes the v0.1.23 self-inflicted dip
    #     (Prob034/053/104 left at X because the caller treated the WARN as "OK").
    rc, out = run([sys.executable, str(PROG / "rtl_hygiene_lint.py"),
                   "--fix", str(sample)])
    steps["rtl_hygiene_fix"] = {"verdict": "APPLIED" if "repaired" in out else "noop",
                                "rc": rc, "log": out[-300:]}

    # 5b. rtl_hygiene_lint (v0.1.10 rule 5: uninit-registered-output, etc.) on the RTL.
    #     Structural lint — derived from the RTL + reset-presence, never the hidden test.
    rc, out = run([sys.executable, str(PROG / "rtl_hygiene_lint.py"),
                   "--severity", "WARN", str(sample)])
    hverd = "PASS" if rc == 0 else "WARN"
    steps["rtl_hygiene_lint"] = {"verdict": hverd, "rc": rc, "log": out[-600:]}

    hard_ok = steps["phase1_run_all"]["verdict"] == "PASS" and steps["iverilog_compile"]["verdict"] == "PASS"
    if hard_ok:
        dst = HERE / "samples" / f"{a.prob}_sample01.sv"
        dst.write_text(sample.read_text())
        steps["sample_emitted"] = str(dst)

    (wd / "gates.json").write_text(json.dumps({"prob": a.prob, "hard_gates_pass": hard_ok,
                                               "steps": steps}, indent=2) + "\n")
    print(json.dumps({"prob": a.prob, "hard_gates_pass": hard_ok,
                      "summary": {k: v.get("verdict") for k, v in steps.items() if isinstance(v, dict)}}, indent=2))
    sys.exit(0 if hard_ok else 1)


if __name__ == "__main__":
    main()
