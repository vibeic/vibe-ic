#!/usr/bin/env python3
"""Compare public native runs on copies; adopt the best passing native override.

Arguments after -- go to the public entry. The chosen settings are written to
work/flow/native_overrides.json; native measurements remain in the chosen copy.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from flow_config import _load
from flow_ppa_objective import compare_native, final_violation_metrics, objective_weights
from flow_ppa_variants import (MAX_UTIL, RECOVERY, SAMPLE_SEED, SIZING,
                               native_candidates, pinned_settings, selected_level)


ENTRY = Path(__file__).with_name("vibe_ic_one_shot_runner.py")
OVERRIDES = Path("work/flow/native_overrides.json")
METRICS = {
    "Cells": "design__instance__count", "Area (um2)": "design__instance__area",
    "Core (um2)": "design__core__area", "Power (W)": "power__total",
    "Setup slack (ns)": "timing__setup__ws", "Hold slack (ns)": "timing__hold__ws",
    "Slew violations": "design__max_slew_violation__count",
    "Cap violations": "design__max_cap_violation__count",
    "Fanout violations": "design__max_fanout_violation__count",
}


def variants(project, *, level=1, resolved=None):
    original = _load(project / OVERRIDES)
    return native_candidates(project, original, resolved or {}, level=level)


def run_variant(project, output, variant, cores, flow_args, ppa_level=0):
    name, overrides = variant
    destination = output / name
    row = {"name": name, "project": str(destination), "overrides": overrides,
           "exit_code": None, "rows": [], "metrics": {}, "all_pass": False,
           "state": "RUNNING", "resolved_settings": {}, "ppa_level": ppa_level}
    started = time.monotonic()
    try:
        shutil.copytree(project, destination, ignore=lambda path, names: {
            item for item in names if Path(path) == project
            and item in {"steps", "reports", "work", "runs", ".git"}})
        (destination / OVERRIDES).parent.mkdir(parents=True, exist_ok=True)
        (destination / OVERRIDES).write_text(json.dumps(overrides, indent=2) + "\n")
        launcher = ("import os,sys; os.sched_setaffinity(0,map(int,sys.argv[1].split(','))); "
                    "os.execv(sys.executable,[sys.executable,*sys.argv[2:]])")
        command = [sys.executable, "-c", launcher, ",".join(map(str, cores)), str(ENTRY),
                   str(destination), *flow_args]
        with (output / (name + ".log")).open("w") as log:
            completed = subprocess.run(command, cwd=destination, stdout=log, stderr=subprocess.STDOUT)
        report = _load(destination / "reports/flow_engine.json")
        rows = report.get("steps", [])
        metrics = {}
        settings = {}
        for step in rows:
            metrics.update(step.get("native_metrics", {}))
            for call in step.get("native_steps", []):
                directory = call.get("reports")
                if isinstance(directory, str):
                    config = _load(Path(directory) / "config.json")
                    settings.update({key: config[key] for key in (
                        "CLOCK_PERIOD", "PDK", "STD_CELL_LIBRARY", "STA_CORNERS",
                        "EXTRA_EXCLUDED_CELLS", RECOVERY, *MAX_UTIL, *SIZING)
                        if key in config})
        row.update(exit_code=completed.returncode,
            rows=[{"name": step["name"], "status": step["status"]} for step in rows],
            metrics={key: metrics.get(key) for key in METRICS.values()},
            resolved_settings=settings,
            violation_metrics=final_violation_metrics(metrics),
            state="COMPLETED" if completed.returncode == 0 else "FAILED",
            all_pass=completed.returncode == 0 and bool(rows) and all(step["status"] == "PASS" for step in rows))
    except (OSError, ValueError) as exc:
        row["detail"] = str(exc)
        row["state"] = "NOT_MEASURED"
    row["wall_seconds"] = time.monotonic() - started
    return row


def explore(project, output, *, cpus=8, jobs=2, flow_args=(), ppa_level=None):
    project, output = Path(project).resolve(), Path(output).resolve()
    if output.is_relative_to(project):
        raise ValueError("The exploration output must be outside the source project.")
    level, level_source = selected_level(project, ppa_level)
    if level > 2:
        raise ValueError("Levels3/4 use the native-tool handoff, not the Levels1/2 knob driver")
    weights = objective_weights(project)
    output.mkdir(parents=True, exist_ok=True)
    cores = sorted(os.sched_getaffinity(0))[:min(cpus, 8)]
    workers = min(jobs, 1 if level == 0 else 2, len(cores))
    groups = [cores[index::workers] for index in range(workers)]
    started = time.monotonic()
    baseline = variants(project, level=0)[0]
    reference = run_variant(project, output, baseline, groups[0], flow_args, level)
    candidates = variants(project, level=level, resolved=reference["resolved_settings"])
    rows = [reference, *[{"name": name, "project": str(output / name), "overrides": overrides,
                          "state": "PROPOSED", "exit_code": None, "rows": [],
                          "metrics": {}, "all_pass": False} for name, overrides in candidates[1:]]]
    report = {"selected": None, "selected_project": None, "state": "RUNNING",
              "ppa_level": level, "ppa_level_source": level_source,
              "planned_trials": len(candidates), "reference": reference["name"],
              "cpu_budget": len(cores), "jobs": workers, "public_args": list(flow_args),
              "executor": "local", "weights": weights, "variants": rows,
              "sampling_seed": SAMPLE_SEED if level == 2 else None,
              "pinned_native_settings": sorted(pinned_settings(project)),
              "knob_families": ["minimum drive exclusion", "recover_power", "resizer max utilization",
                                "candidate cell sizing area/leakage limits"]}
    report_path = output / "results.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    pending = iter(enumerate(candidates[1:], 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active = {}

        def submit(group):
            item = next(pending, None)
            if item is not None:
                index, candidate = item
                active[pool.submit(run_variant, project, output, candidate,
                                   group, flow_args, level)] = (index, group)

        for group in groups:
            submit(group)
        while active:
            finished, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in finished:
                index, group = active.pop(future)
                rows[index] = future.result()
                # One active native process per disjoint affinity group. A fast
                # worker must not launch into another worker's still-busy group.
                submit(group)
            report_path.write_text(json.dumps(report, indent=2) + "\n")
    for row in rows:
        row["objective"] = compare_native(reference, row, weights)
    eligible = [row for row in rows if row["all_pass"] and
                (level == 0 or row["objective"]["eligible"] and row["objective"]["score"] is not None)]
    winner = (next(iter(eligible), None) if level == 0 else
              min(eligible, key=lambda row: row["objective"]["score"], default=None))
    if winner is not None:
        (project / OVERRIDES).parent.mkdir(parents=True, exist_ok=True)
        (project / OVERRIDES).write_text(json.dumps(winner["overrides"], indent=2) + "\n")
    report.update(selected=winner["name"] if winner else None,
                  selected_project=winner["project"] if winner else None,
                  state="COMPLETE", wall_seconds=time.monotonic() - started,
                  public_invocations=sum(row.get("exit_code") is not None for row in rows))
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    lines = [f"PPA level {level} ({level_source}); {len(rows)} planned trials, "
             f"{report['public_invocations']} public invocations; executor local.", "",
             "Weights: " + json.dumps(weights) + ".", "",
             "| Variant | Passing rows | Score (lower) | " + " | ".join(METRICS) + " |",
             "|---|---|---|" + "---|" * len(METRICS)]
    for row in rows:
        passing = sum(step["status"] == "PASS" for step in row["rows"])
        values = [str(row["metrics"].get(key)) if row["metrics"].get(key) is not None else "NOT_MEASURED"
                  for key in METRICS.values()]
        score = row["objective"]["score"]
        lines.append(f"| {row['name']} | {passing}/{len(row['rows'])} | "
                     + (str(score) if score is not None else "NOT_MEASURED") + " | " + " | ".join(values) + " |")
    lines += ["", "Selected: " + (winner["name"] if winner else "none; no comparable all-PASS native PPA result."),
              "", "Area is native design__instance__area (including physical fill when present); "
              "power is native power__total. Only the winning native overrides are adopted into the source project. "
              "Measured outputs remain in the selected project copy; scope is the public run window. "
              "Objective percentages use native instance area/power and ORFS's clipped effective period, "
              "not percentage change of signed slack or ORFS utilization-complement area. "
              "Native failures remain ineligible regardless of score. Candidate populations shrink when "
              "documents pin settings; they are not padded with duplicate runs."]
    (output / "RESULT.md").write_text("\n".join(lines) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpus", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--jobs", type=int, choices=range(1, 3), default=2)
    parser.add_argument("--ppa-level", type=int, choices=range(5),
                        help="CLI overrides document PPA_LEVEL; default2. Levels3/4 use the native-tool handoff.")
    args, forwarded = parser.parse_known_args()
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    try:
        result = explore(args.project, args.output, cpus=args.cpus, jobs=args.jobs,
                         flow_args=forwarded, ppa_level=args.ppa_level)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("Selected: " + (result["selected"] or "none"))
    return 0 if result["selected"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
