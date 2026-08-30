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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_GATE = HERE / "cvdp_gate.py"
DEFAULT_SIM_IMAGE = os.environ.get("OSS_SIM_IMAGE", "cvdp-sim-oss:v110")


# CVDP records a test's `result` as the integer 0 OR the string "0" for PASS
# (the official harness emits both forms). This matches the in-repo schema
# authority `verify_fail_triage.py` (`result in (0, "0")` == passing); strict
# `== 0` would FALSE-FAIL a genuinely-passing design recorded with string
# results and trap the convergence loop in an endless re-author.
_PASS_RESULTS = (0, "0")


def extract_one_record(dataset: Path, design_id: str) -> Optional[str]:
    """Return the raw JSONL line for `design_id` from a CVDP dataset, or None if
    absent. Used to build a SINGLE-PROBLEM dataset so the official scorer only
    assembles this one design's harness (see score_one). A cheap substring
    pre-filter avoids json-parsing every large line; the id is confirmed by an
    exact JSON `id` match so a substring collision (e.g. `..._0001` vs
    `..._00010`) never selects the wrong record."""
    needle = f'"{design_id}"'
    try:
        with dataset.open(errors="replace") as fh:
            for ln in fh:
                if needle not in ln:
                    continue
                s = ln.strip()
                try:
                    if json.loads(s).get("id") == design_id:
                        return s
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None
    return None


def parse_result(raw_result_path: Path, design_id: str) -> Tuple[str, List[str]]:
    """Read the official run_benchmark raw_result.json and return
    (verdict, fail_logs). verdict ∈ {'PASS','FAIL','NO_RESULT'}.

    CVDP result semantics: a test's `result` is 0/"0" = PASS, else FAIL. A design
    PASSES iff it has tests and ALL of them pass. ANY malformed / wrong-shape
    result degrades to NO_RESULT (could-not-score) — NEVER a fabricated PASS or a
    misleading FAIL: a crashed/partial harness must not be read as a definitive
    verdict."""
    if not raw_result_path.is_file():
        return "NO_RESULT", []
    try:
        raw = json.loads(raw_result_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "NO_RESULT", []
    if not isinstance(raw, dict):                 # valid JSON, wrong top shape
        return "NO_RESULT", []
    rec = raw.get(design_id)
    if not isinstance(rec, dict):
        return "NO_RESULT", []
    tests = rec.get("tests")
    if not isinstance(tests, list) or not tests:
        return "NO_RESULT", []
    if not all(isinstance(t, dict) for t in tests):   # a non-dict entry =
        return "NO_RESULT", []                         # untrustworthy → no verdict
    fail_logs = [t.get("log") for t in tests
                 if t.get("result") not in _PASS_RESULTS and t.get("log")]
    verdict = ("PASS" if all(t.get("result") in _PASS_RESULTS for t in tests)
               else "FAIL")
    return verdict, fail_logs


def score_one(design_id: str, draft: Path, dataset: Path, bench: Path,
              prompts: Optional[Path] = None,
              sim_image: str = DEFAULT_SIM_IMAGE,
              gate: Path = DEFAULT_GATE,
              workdir: Optional[Path] = None) -> Tuple[str, List[str], str]:
    """Gate + officially score one design. Returns (verdict, fail_logs, detail).

    verdict ∈ {'PASS','FAIL','NO_RESULT','GATE_BLOCKED','NO_DRAFT',
                'IMAGE_MISSING'}. Everything that is not PASS/FAIL is
    could-not-score (exit 2) — a verdict about the run, never about the draft."""
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
        # official scorer on just this one response. CRITICAL: pass a
        # SINGLE-PROBLEM dataset subset to `run_benchmark.py -f`, NOT the full
        # 302-problem dataset. `-f <full dataset>` makes the official harness
        # iterate/assemble EVERY problem in the file (building unrelated designs'
        # cocotb harnesses), turning a one-design score into a ~7-min full-suite
        # pass that trips convergence-loop timeouts (observed: 420s TIMEOUT =
        # false FAIL). Subsetting to the single `design_id` record keeps the
        # verdict identical (each problem scores independently) while dropping the
        # wall-clock to a few seconds. Fall back to the full dataset only if the
        # id can't be found (never silently mis-score).
        one_line = extract_one_record(dataset, design_id)
        if one_line is not None:
            score_dataset = wd / "dataset_one.jsonl"
            score_dataset.write_text(one_line + "\n")
        else:
            score_dataset = dataset
        # A REUSED PREFIX MAKES THE SCORER REPLAY THE PREVIOUS DRAFT'S VERDICT.
        # `run_benchmark.py` will not re-run over an existing `--prefix` tree; it
        # leaves the earlier `raw_result.json` and `reports/*.txt` exactly where
        # they were, and `parse_result` below then reads THAT. The failure is
        # silent and it is not merely a wasted iteration — it reports the wrong
        # answer. Measured on `cvdp_copilot_binary_to_gray_0001`: score the
        # correct draft into a fresh workdir (PASS), then score a deliberately
        # WRONG one (`gray_out[i] = ~(b[i+1]^b[i])`) into the SAME workdir and it
        # still says PASS; the identical wrong draft into a fresh workdir says
        # FAIL. So a broken design can be certified correct.
        #
        # Four independent convergence agents hit this during a 302-design CVDP
        # campaign, each losing an iteration to a verdict that described a draft
        # they had already replaced, and several "cannot determine the root
        # cause, no log" triage notes were this bug rather than missing evidence.
        #
        # Clearing the prefix — not the whole workdir — keeps `--workdir` usable
        # as a stable place to look at the batch and the response the caller
        # staged, while guaranteeing the verdict describes THIS draft.
        score_prefix = wd / "score"
        if score_prefix.exists():
            shutil.rmtree(score_prefix, ignore_errors=True)
        env = dict(os.environ)
        env["OSS_SIM_IMAGE"] = sim_image
        # THE OFFICIAL HARNESS TAKES **TWO** IMAGES, AND SETTING ONE IS NOT A
        # PARTIAL RUN — IT IS A WRONG VERDICT. An area-opt / cid007 problem
        # scores its `*_synth` subtest in a SECOND container named by
        # `OSS_PNR_IMAGE`; unset, the harness falls back to the gated
        # `nvidia/cvdp-sim:v1.0.0`, the pull is denied, and the subtest is
        # recorded as a FAILURE OF THE DESIGN. Measured on 302 authored CVDP
        # completions: 6 designs whose functional half was clean
        # (`TESTS=n PASS=n FAIL=0`) were scored FAIL on a `*_synth.txt` whose
        # entire body is `ERROR: pull access denied`. Control/variant on
        # `cvdp_copilot_generic_nbit_counter_0039`, same draft: unset -> FAIL,
        # set -> PASS. All six flip to PASS with this line.
        #
        # `eda_image_preflight.py` was written for exactly this (#714) and
        # nothing called it. Default the synth image to the sim image the
        # caller already proved they have; an explicit env still wins.
        env.setdefault("OSS_PNR_IMAGE", sim_image)

        # ...AND "the sim image the caller already proved they have" is an
        # assumption the caller never actually discharges. When the named image
        # is absent, the harness still runs: it fails to start the container,
        # writes a `reports/1.txt` whose entire body is the two lines
        # "Running harness with project name: ..." / "Cleaning up Docker
        # resources...", and records `{"result": 1, "errors": 1,
        # "execution": 1.27}` — a 1.3-second "test" in which no simulation ever
        # happened. `parse_result` faithfully reads that as FAIL, so an ABSENT
        # IMAGE IS REPORTED AS A DEFECT IN THE DESIGN.
        #
        # That is the same lie as #714 in the opposite direction, and it is
        # worse than a crash: measured here, a draft and a deliberately altered
        # variant of it both scored FAIL, which reads as "the change didn't
        # help" when in truth NEITHER was ever simulated. A convergence loop
        # fed those verdicts re-authors a correct design forever.
        #
        # An image is either present or it is not, so this preflight cannot
        # misfire — and it must run BEFORE the harness, because afterwards the
        # environment failure is indistinguishable from a design failure in
        # everything except a timing heuristic.
        missing = [img for img in dict.fromkeys(
                       (sim_image, env.get("OSS_PNR_IMAGE")))
                   if img and subprocess.run(
                       ["docker", "image", "inspect", img],
                       capture_output=True).returncode != 0]
        if missing:
            return ("IMAGE_MISSING", [], "cannot score: image(s) not present "
                    "locally: " + ", ".join(missing) + " — the harness would "
                    "record this as a FAILING TEST, which is a verdict about "
                    "the environment, not the design. Build/pull the image, or "
                    "pass --sim-image with one you have.")
        subprocess.run(
            [sys.executable, "run_benchmark.py", "-f", str(score_dataset),
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
