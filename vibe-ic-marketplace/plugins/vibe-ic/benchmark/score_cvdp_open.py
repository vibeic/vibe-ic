#!/usr/bin/env python3
"""Score accepted general-flow CVDP candidates with the official harness.

This module is a scorer adapter only. It never routes a problem, authors RTL,
repairs a candidate, or changes accepted bytes. The dispatcher supplies a
complete flat JSONL produced after Program First + hash-bound AI acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent / "programs"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROGRAMS))

from _atomic_artefact import write_json, write_text  # noqa: E402
from eda_image_preflight import recommended_scoring_env  # noqa: E402
from score_one import parse_result  # noqa: E402


def _dataset_ids(dataset: Path) -> List[str]:
    ids: List[str] = []
    for raw in dataset.read_text(errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if row.get("id"):
            ids.append(str(row["id"]))
    return ids


def _response_rows(path: Path) -> Tuple[List[dict], List[str]]:
    rows, errors = [], []
    for lineno, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {lineno}: row is not an object")
            continue
        if not row.get("id") or not isinstance(row.get("completion"), str):
            errors.append(f"line {lineno}: id/completion contract is invalid")
            continue
        if not row["completion"].strip():
            errors.append(f"line {lineno}: completion is empty")
            continue
        rows.append(row)
    return rows, errors


def _image_present(image: str) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def score(dataset: Path, responses: Path, run: Path, scorer_root: Path,
          sim_image: str, pnr_image: str, threads: int) -> int:
    dataset, responses, run = map(Path, (dataset, responses, run))
    scorer_root = Path(scorer_root)
    official = scorer_root / "run_benchmark.py"
    if not dataset.is_file() or not responses.is_file():
        print("ERROR: dataset/responses file is absent", file=sys.stderr)
        return 2
    if not official.is_file():
        print(f"ERROR: official run_benchmark.py absent under {scorer_root}",
              file=sys.stderr)
        return 2

    ids = _dataset_ids(dataset)
    rows, errors = _response_rows(responses)
    response_ids = [str(row["id"]) for row in rows]
    if len(set(ids)) != len(ids):
        errors.append("dataset contains duplicate ids")
    if len(set(response_ids)) != len(response_ids):
        errors.append("responses contain duplicate ids")
    if response_ids != ids:
        errors.append(
            "response ids/order do not exactly match the full dataset")
    if errors:
        print("ERROR: CVDP response contract refused:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 2

    missing = [image for image in dict.fromkeys((sim_image, pnr_image))
               if not _image_present(image)]
    if missing:
        print("ERROR: scoring image(s) absent: " + ", ".join(missing),
              file=sys.stderr)
        return 2
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    preflight_json = reports / "cvdp_image_preflight.json"
    preflight = subprocess.run(
        [sys.executable, str(PROGRAMS / "eda_image_preflight.py"),
         "--image", sim_image, "--json", str(preflight_json)],
        capture_output=True, text=True)
    write_text(reports / "cvdp_image_preflight.log",
               preflight.stdout + preflight.stderr)
    if preflight.returncode != 0:
        print("ERROR: CVDP scoring image preflight failed; see "
              f"{preflight_json}", file=sys.stderr)
        return 2

    prefix = run / "official_score"
    if prefix.exists() and any(prefix.iterdir()):
        print(f"ERROR: score prefix is not fresh: {prefix}", file=sys.stderr)
        return 2
    prefix.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(recommended_scoring_env())
    env["OSS_SIM_IMAGE"] = sim_image
    env["OSS_PNR_IMAGE"] = pnr_image
    cmd = [
        sys.executable, str(official),
        "--filename", str(dataset),
        "--llm",
        "--model", "local_import",
        "--prompts-responses-file", str(responses),
        "--threads", str(max(1, int(threads))),
        "--prefix", str(prefix),
    ]
    proc = subprocess.run(
        cmd, cwd=str(scorer_root), env=env, capture_output=True, text=True)
    write_text(reports / "cvdp_official_score.log",
               "$ " + " ".join(cmd) + "\n\n" + proc.stdout + proc.stderr)

    raw = prefix / "raw_result.json"
    if not raw.is_file():
        print("ERROR: official scorer wrote no raw_result.json; see "
              f"{reports / 'cvdp_official_score.log'}", file=sys.stderr)
        return 2
    verdicts: Dict[str, dict] = {}
    for pid in ids:
        verdict, logs = parse_result(raw, pid)
        verdicts[pid] = {"verdict": verdict, "fail_logs": logs}
    passed = sum(row["verdict"] == "PASS" for row in verdicts.values())
    failed = sum(row["verdict"] == "FAIL" for row in verdicts.values())
    not_measured = len(ids) - passed - failed
    result = {
        "schema": "vibeic.benchmark.cvdp_pass_at_1.v1",
        "benchmark": "cvdp-open",
        "total": len(ids),
        "passed": passed,
        "failed": failed,
        "not_measured": not_measured,
        "pass_at_1": (passed / len(ids)) if ids else 0.0,
        "official_scorer_rc": proc.returncode,
        "dataset": str(dataset.resolve()),
        "responses": str(responses.resolve()),
        "raw_result": str(raw.resolve()),
        "sim_image": sim_image,
        "pnr_image": pnr_image,
        "per_problem": verdicts,
    }
    pass_path = run / "pass_at_1.json"
    write_json(pass_path, result)
    passrate_map = run / "reports" / "cvdp_passrate_map.json"
    write_json(passrate_map, {
        pid: row["verdict"] == "PASS" for pid, row in verdicts.items()})

    triage = run / "reports" / "cvdp_fail_triage.json"
    triage_proc = subprocess.run(
        [sys.executable, str(PROGRAMS / "verify_fail_triage.py"),
         "--raw", str(raw), "--reports", str(prefix),
         "--passrate-json", str(passrate_map), "--out", str(triage)],
        capture_output=True, text=True)
    write_text(reports / "cvdp_fail_triage.log",
               triage_proc.stdout + triage_proc.stderr)
    print(f"CVDP official score: {passed}/{len(ids)} "
          f"({result['pass_at_1']:.2%}), FAIL={failed}, "
          f"NOT_MEASURED={not_measured}")
    print(f"  result: {pass_path}")
    print(f"  raw:    {raw}")
    print(f"  triage: {triage}")
    return (0 if (proc.returncode == 0 and not_measured == 0
                  and triage_proc.returncode == 0) else 2)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--responses", required=True, type=Path)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument(
        "--scorer-root", type=Path,
        default=(Path(os.environ["CVDP_BENCHMARK_ROOT"])
                 if os.environ.get("CVDP_BENCHMARK_ROOT") else None),
        help="directory containing official run_benchmark.py; or set "
             "CVDP_BENCHMARK_ROOT")
    ap.add_argument("--sim-image",
                    default=os.environ.get("OSS_SIM_IMAGE", ""))
    ap.add_argument("--pnr-image",
                    default=os.environ.get("OSS_PNR_IMAGE", ""))
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)
    if args.scorer_root is None:
        print("ERROR: pass --scorer-root or set CVDP_BENCHMARK_ROOT",
              file=sys.stderr)
        return 2
    if not args.sim_image or not args.pnr_image:
        print("ERROR: set BOTH OSS_SIM_IMAGE and OSS_PNR_IMAGE",
              file=sys.stderr)
        return 2
    return score(args.dataset, args.responses, args.run, args.scorer_root,
                 args.sim_image, args.pnr_image, args.threads)


if __name__ == "__main__":
    raise SystemExit(main())
