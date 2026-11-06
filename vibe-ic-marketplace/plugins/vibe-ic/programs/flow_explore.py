#!/usr/bin/env python3
"""Compare public native runs on copies; adopt the best passing native override.

Arguments after -- go to the public entry. The chosen settings are written to
work/flow/native_overrides.json; native measurements remain in the chosen copy.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from flow_config import _load, native_excluded_cells


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


def variants(project):
    original = _load(project / OVERRIDES)
    declaration = _load(project / "plugin_output/declaration.json")
    excluded = original.get("EXTRA_EXCLUDED_CELLS", declaration.get("EXTRA_EXCLUDED_CELLS", []))
    base = [cell for cell in native_excluded_cells({"EXTRA_EXCLUDED_CELLS": excluded}) if cell != "*_1"]
    return [("exclude_min_drive", {**original, "EXTRA_EXCLUDED_CELLS": [*base, "*_1"]}),
            ("allow_min_drive", {**original, "EXTRA_EXCLUDED_CELLS": base})]


def run_variant(project, output, variant, cores, flow_args):
    name, overrides = variant
    destination = output / name
    row = {"name": name, "project": str(destination), "overrides": overrides,
           "exit_code": None, "rows": [], "metrics": {}, "all_pass": False}
    try:
        shutil.copytree(project, destination, ignore=lambda path, names: {
            item for item in names if Path(path) == project
            and item in {"steps", "reports", "work", "runs", ".git"}})
        (destination / OVERRIDES).parent.mkdir(parents=True, exist_ok=True)
        (destination / OVERRIDES).write_text(json.dumps(overrides, indent=2) + "\n")
        launcher = ("import os,sys; os.sched_setaffinity(0,map(int,sys.argv[1].split(','))); "
                    "os.execv(sys.executable,[sys.executable,*sys.argv[2:]])")
        command = [sys.executable, "-c", launcher, ",".join(map(str, cores)), str(ENTRY),
                   str(destination), *flow_args, "--engine", "native"]
        with (output / (name + ".log")).open("w") as log:
            completed = subprocess.run(command, cwd=destination, stdout=log, stderr=subprocess.STDOUT)
        report = _load(destination / "reports/flow_engine.json")
        rows = report.get("steps", [])
        metrics = {}
        for step in rows:
            metrics.update(step.get("native_metrics", {}))
        row.update(exit_code=completed.returncode,
            rows=[{"name": step["name"], "status": step["status"]} for step in rows],
            metrics={key: metrics.get(key) for key in METRICS.values()},
            all_pass=completed.returncode == 0 and bool(rows) and all(step["status"] == "PASS" for step in rows))
    except (OSError, ValueError) as exc:
        row["detail"] = str(exc)
    return row


def explore(project, output, *, cpus=8, jobs=2, flow_args=()):
    project, output = Path(project).resolve(), Path(output).resolve()
    if output.is_relative_to(project):
        raise ValueError("The exploration output must be outside the source project.")
    output.mkdir(parents=True, exist_ok=True)
    candidates = variants(project)
    cores = sorted(os.sched_getaffinity(0))[:min(cpus, 8)]
    workers = min(jobs, len(candidates), len(cores))
    groups = [cores[index::workers] for index in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_variant, project, output, variant, groups[index % workers], flow_args)
                   for index, variant in enumerate(candidates)]
        rows = [future.result() for future in futures]
    eligible = [row for row in rows if row["all_pass"] and all(
        isinstance(row["metrics"].get(key), (int, float)) and math.isfinite(row["metrics"][key])
        for key in ("design__instance__area", "power__total"))]
    winner = min(eligible, key=lambda row: (row["metrics"]["design__instance__area"],
                                          row["metrics"]["power__total"]), default=None)
    if winner is not None:
        (project / OVERRIDES).parent.mkdir(parents=True, exist_ok=True)
        (project / OVERRIDES).write_text(json.dumps(winner["overrides"], indent=2) + "\n")
    report = {"selected": winner["name"] if winner else None,
              "selected_project": winner["project"] if winner else None,
              "cpu_budget": len(cores), "jobs": workers, "public_args": list(flow_args), "variants": rows}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["| Variant | Passing rows | " + " | ".join(METRICS) + " |",
             "|---|---|" + "---|" * len(METRICS)]
    for row in rows:
        passing = sum(step["status"] == "PASS" for step in row["rows"])
        values = [str(row["metrics"].get(key)) if row["metrics"].get(key) is not None else "NOT_MEASURED"
                  for key in METRICS.values()]
        lines.append(f"| {row['name']} | {passing}/{len(row['rows'])} | " + " | ".join(values) + " |")
    lines += ["", "Selected: " + (winner["name"] if winner else "none; no all-PASS variant with native area and power."),
              "", "Area is native design__instance__area (including physical fill when present); "
              "power is native power__total. Only the winning native overrides are adopted into the source project. "
              "Measured outputs remain in the selected project copy; scope is the public run window."]
    (output / "RESULT.md").write_text("\n".join(lines) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpus", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--jobs", type=int, choices=range(1, 3), default=2)
    args, forwarded = parser.parse_known_args()
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    result = explore(args.project, args.output, cpus=args.cpus, jobs=args.jobs, flow_args=forwarded)
    print("Selected: " + (result["selected"] or "none"))
    return 0 if result["selected"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
