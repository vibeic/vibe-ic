"""Issued input-only I/O metadata for downstream benchmark fixture tests.

This does not admit a route, launch a producer, or claim AI acceptance. Existing
solve policies/results are retained, including the historical manual score
fixtures whose downstream audit policy predates Program First acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import task_nature_route as tnr


def issue_io_fixture(run: Path, bench: str, dataset: Path, *,
                     task: dict | None = None) -> dict:
    run, dataset = Path(run).resolve(), Path(dataset).resolve()
    fmt = bd._BENCH_FORMAT[bench]
    pid = task["id"] if task is not None else "Prob001"
    project = Path(task["project"]) if task is not None else run / "projects" / pid
    prompt = project / "input" / "phase1_prompt.md"
    if not prompt.is_file():
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text((dataset / f"{pid}_prompt.txt").read_text())
        public = bio._stage_public_original(pid, prompt.read_text(), {}, project)
    else:
        public = bio.public_original_input(
            project, pid, bd._sha256_text(prompt.read_text()),
            expected=(task or {}).get("public_original_input"))
    proposal = tnr.classify_task_nature(prompt.read_text(), False, None)
    route = bd._make_ai_route_task(
        pid, project, {"public_original_input": public,
                       "prompt_chars": len(prompt.read_text())},
        proposal, run, fmt, benchmark=bench, dataset_path=dataset)
    bd._publish_route_input_anchor(
        run, bd._route_input_anchor(bench, fmt, dataset, [route]))
    bd._write_jsonl(run / bd._ROUTE_WORKLIST, [route])
    config_path = run / ".bench_config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {
        "schema": "vibeic.benchmark.general_run.v1",
        "clean_room": True, "full_dataset": True, "diagnostic_limit": 0,
        "inherited_from": None, "seed_run": None, "reused_samples_from": None,
    }
    config.update(bench=bench, format=fmt, dataset=str(dataset))
    bd._atomic_write_json(config_path, config)
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text()) if solve_path.exists() else {
        "results": [],
        "measurement_scope": "SYNTHETIC_INPUT_ONLY_IO_FIXTURE",
    }
    solve.update(bench=bench, format=fmt, dataset=str(dataset))
    bd._atomic_write_json(solve_path, solve)
    return route
