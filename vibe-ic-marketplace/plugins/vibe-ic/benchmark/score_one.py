#!/usr/bin/env python3
"""score_one.py — score ONE CVDP design through the OFFICIAL harness.

The convergence loop needs a fast, authoritative single-design verdict: gate a
draft through `cvdp_gate.py` (the sole-emit path), run the official
`run_benchmark.py` against just that one response, and report PASS/FAIL with the
cocotb log path on failure. This is the ground-truth self-verify an authoring /
re-author agent should use instead of trusting a local iverilog approximation
(a local elaborate can be clean while the official multi-file assembly fails).

Deterministic wrapper — no LLM. chip-AGNOSTIC.

Usage:
    score_one.py --id <cvdp_id> --draft <file.sv> \\
        --dataset <dataset.jsonl> --bench <cvdp_benchmark_dir> \\
        [--prompts <prompts.jsonl>] [--sim-image <img>] \\
        [--gate <cvdp_gate.py>] [--workdir <dir>]

Exit: 0 = PASS, 1 = FAIL, 2 = could-not-score (gate blocked / no result / setup).
The verdict line is printed to stdout regardless.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_GATE = HERE / "cvdp_gate.py"
DEFAULT_SIM_IMAGE = os.environ.get("OSS_SIM_IMAGE", "cvdp-sim-oss:v110")


def parse_result(raw_result_path: Path, design_id: str) -> Tuple[str, List[str]]:
    """Read the official run_benchmark raw_result.json and return
    (verdict, fail_logs). verdict ∈ {'PASS','FAIL','NO_RESULT'}.

    CVDP result semantics: a test's `result` is 0 = PASS, 1 = FAIL. A design
    PASSES iff it has tests and ALL of them are result==0."""
    if not raw_result_path.is_file():
        return "NO_RESULT", []
    try:
        raw = json.loads(raw_result_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "NO_RESULT", []
    rec = raw.get(design_id)
    if not isinstance(rec, dict):
        return "NO_RESULT", []
    tests = rec.get("tests") or []
    if not tests:
        return "NO_RESULT", []
    fail_logs = [t.get("log") for t in tests
                 if t.get("result") != 0 and t.get("log")]
    verdict = "PASS" if all(t.get("result") == 0 for t in tests) else "FAIL"
    return verdict, fail_logs


def score_one(design_id: str, draft: Path, dataset: Path, bench: Path,
              prompts: Optional[Path] = None,
              sim_image: str = DEFAULT_SIM_IMAGE,
              gate: Path = DEFAULT_GATE,
              workdir: Optional[Path] = None) -> Tuple[str, List[str], str]:
    """Gate + officially score one design. Returns (verdict, fail_logs, detail).

    verdict ∈ {'PASS','FAIL','NO_RESULT','GATE_BLOCKED','NO_DRAFT'}."""
    if not draft.is_file():
        return "NO_DRAFT", [], f"draft not found: {draft}"
    tmp_owner = None
    if workdir is None:
        tmp_owner = tempfile.TemporaryDirectory(prefix="score_one_")
        wd = Path(tmp_owner.name)
    else:
        wd = workdir
        wd.mkdir(parents=True, exist_ok=True)
    try:
        batch = wd / "batch"
        batch.mkdir(parents=True, exist_ok=True)
        # name the staged draft by the id so the gate's filename/module
        # conformance + the harness toplevel derivation align.
        (batch / f"{design_id}.sv").write_text(draft.read_text(errors="replace"))
        resp = wd / "resp.jsonl"
        gate_cmd = [sys.executable, str(gate), "--batch-dir", str(batch),
                    "--out", str(resp), "--report", str(wd / "gate.json"),
                    "--dataset", str(dataset), "--prompts-advisory"]
        if prompts:
            gate_cmd += ["--prompts", str(prompts)]
        g = subprocess.run(gate_cmd, capture_output=True, text=True)
        if not resp.is_file() or not resp.read_text().strip():
            tail = (g.stdout + g.stderr).strip().splitlines()[-3:]
            return "GATE_BLOCKED", [], " | ".join(tail)
        # official scorer on just this one response
        score_prefix = wd / "score"
        env = dict(os.environ)
        env["OSS_SIM_IMAGE"] = sim_image
        subprocess.run(
            [sys.executable, "run_benchmark.py", "-f", str(dataset),
             "--model", "local_import", "--prompts-responses-file", str(resp),
             "--llm", "-t", "2", "--prefix", str(score_prefix)],
            cwd=str(bench), env=env, capture_output=True, text=True)
        verdict, logs = parse_result(score_prefix / "raw_result.json",
                                     design_id)
        return verdict, logs, f"scored via {sim_image}"
    finally:
        if tmp_owner is not None:
            tmp_owner.cleanup()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True, help="cvdp design id")
    ap.add_argument("--draft", required=True, type=Path,
                    help="the authored RTL (.sv) or JSON multi-file completion")
    ap.add_argument("--dataset", required=True, type=Path,
                    help="CVDP dataset JSONL (authoritative expected files / "
                    "synth-scored / context)")
    ap.add_argument("--bench", required=True, type=Path,
                    help="cvdp_benchmark dir containing run_benchmark.py")
    ap.add_argument("--prompts", type=Path, default=None)
    ap.add_argument("--sim-image", default=DEFAULT_SIM_IMAGE,
                    help=f"OSS sim image (default {DEFAULT_SIM_IMAGE})")
    ap.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    ap.add_argument("--workdir", type=Path, default=None,
                    help="keep artifacts here (default: a temp dir)")
    args = ap.parse_args(argv)

    if not args.dataset.is_file():
        print(f"score_one: dataset not found: {args.dataset}", file=sys.stderr)
        return 2
    if not (args.bench / "run_benchmark.py").is_file():
        print(f"score_one: run_benchmark.py not under --bench {args.bench}",
              file=sys.stderr)
        return 2

    verdict, logs, detail = score_one(
        args.id, args.draft, args.dataset, args.bench,
        prompts=args.prompts, sim_image=args.sim_image,
        gate=args.gate, workdir=args.workdir)
    print(f"{verdict}  {args.id}  ({detail})")
    for lg in logs:
        print(f"  LOG: {lg}")
    return 0 if verdict == "PASS" else (1 if verdict == "FAIL" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
