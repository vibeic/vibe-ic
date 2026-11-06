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
import re
import shutil
import subprocess
import sys
import time

from flow_config import _load
from flow_ppa_comparison import compare_fields, trial_fields
from flow_ppa_objective import compare_native, final_violation_metrics, objective_weights
from flow_ppa_variants import (L2_SETTINGS, MAX_UTIL, RECOVERY, SAMPLE_SEED, SIZING,
                               level_two_axes, native_candidates, pinned_settings, selected_level)


ENTRY = Path(__file__).with_name("vibe_ic_one_shot_runner.py")
OVERRIDES = Path("work/flow/native_overrides.json")
METRICS = {
    "Cells": "design__instance__count", "Area (um2)": "design__instance__area",
    "Core (um2)": "design__core__area", "Power (W)": "power__total",
    "Wirelength (um)": "route__wirelength",
    "Setup slack (ns)": "timing__setup__ws", "Hold slack (ns)": "timing__hold__ws",
    "Slew violations": "design__max_slew_violation__count",
    "Cap violations": "design__max_cap_violation__count",
    "Fanout violations": "design__max_fanout_violation__count",
}


def variants(project, *, level=1, resolved=None, activity=None):
    original = _load(project / OVERRIDES)
    return native_candidates(project, original, resolved or {}, level=level, activity=activity)


def native_activity(rows):
    calls = [call for row in rows for call in row.get("native_steps", [])
             if call.get("ran") and call.get("exit_code") == 0]
    activity = {"steps": sorted({call["name"] for call in calls}), "cts_preclustering": None}
    for call in calls:
        if call["name"] != "OpenROAD.CTS":
            continue
        path = Path(call["reports"]) / "openroad-cts.log"
        if path.is_file():
            text = path.read_text()
            if re.search(r"CTS-020[46]\]", text) and "CTS-0019]" in text:
                activity["cts_preclustering"] = True
            elif "CTS-0023]" in text and activity["cts_preclustering"] is None:
                activity["cts_preclustering"] = False
    return activity


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
                   str(destination), *flow_args, "--ppa-level", "0"]
        with (output / (name + ".log")).open("w") as log:
            with subprocess.Popen(command, cwd=destination, stdout=log, stderr=subprocess.STDOUT) as completed:
                _, status, usage = os.wait4(completed.pid, 0)
                completed.returncode = os.waitstatus_to_exitcode(status)
                row["cpu_seconds"] = usage.ru_utime + usage.ru_stime
                row["cpu_hours"] = row["cpu_seconds"] / 3600
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
                        "EXTRA_EXCLUDED_CELLS", "MAX_FANOUT_CONSTRAINT",
                        RECOVERY, *MAX_UTIL, *SIZING, *L2_SETTINGS)
                        if key in config})
        row.update(exit_code=completed.returncode,
            rows=[{"name": step["name"], "status": step["status"]} for step in rows],
            metrics={key: metrics.get(key) for key in METRICS.values()},
            resolved_settings=settings,
            native_activity=native_activity(rows),
            violation_metrics=final_violation_metrics(metrics),
            state="COMPLETED" if completed.returncode == 0 else "FAILED",
            all_pass=completed.returncode == 0 and bool(rows) and all(step["status"] == "PASS" for step in rows))
    except (OSError, ValueError) as exc:
        row["detail"] = str(exc)
        row["state"] = "NOT_MEASURED"
    row["wall_seconds"] = time.monotonic() - started
    return row


def explore(project, output, *, cpus=8, jobs=2, flow_args=(), ppa_level=None, spool=None):
    project, output = Path(project).resolve(), Path(output).resolve()
    if output.is_relative_to(project) and not output.is_relative_to(project / "reports"):
        raise ValueError("Exploration output must be outside the project or under its excluded reports directory.")
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
    report_path = output / "results.json"
    if spool:
        from flow_ppa_spool import collect, publish
        from _eda_pin import image_reference
        outbox, result_directory = (Path(path).resolve() for path in spool)
        if outbox == result_directory or any(path.is_relative_to(project)
                                              for path in (outbox, result_directory)):
            raise ValueError("Spool output and results must be distinct and outside the project")
        image = os.environ.get("VIBEIC_EDA_IMAGE") or image_reference()

        def submit_spool(candidate):
            return publish(project, outbox, candidate, cpus=len(cores),
                           flow_args=flow_args, level=level, image=image)

        reference_job = submit_spool(baseline)
        report_path.write_text(json.dumps({"state": "REFERENCE_PENDING", "ppa_level": level,
            "executor": "spool", "spool_job": reference_job}, indent=2) + "\n")
        reference = None
        while reference is None:
            reference = collect(reference_job, result_directory, output / baseline[0])
            if reference is None:
                time.sleep(1)
        if not reference["rows"]:
            report_path.write_text(json.dumps({"state": "REFERENCE_NOT_MEASURED", "ppa_level": level,
                "executor": "spool", "variants": [reference]}, indent=2) + "\n")
            shutil.rmtree(outbox / reference_job)
            raise ValueError("The reference job produced no native public report; see its returned diagnostics")
    else:
        reference = run_variant(project, output, baseline, groups[0], flow_args, level)
    activity = reference.get("native_activity", {})
    candidates = variants(project, level=level, resolved=reference["resolved_settings"], activity=activity)
    rows = [reference, *[{"name": name, "project": str(output / name), "overrides": overrides,
                          "state": "PROPOSED", "exit_code": None, "rows": [],
                          "metrics": {}, "all_pass": False} for name, overrides in candidates[1:]]]
    report = {"selected": None, "selected_project": None, "state": "RUNNING",
              "ppa_level": level, "ppa_level_source": level_source,
              "planned_trials": len(candidates), "reference": reference["name"],
              "cpu_budget": len(cores), "jobs": workers, "public_args": list(flow_args),
              "executor": "spool" if spool else "local", "weights": weights, "variants": rows,
              "sampling_seed": SAMPLE_SEED if level == 2 else None,
              "pinned_native_settings": sorted(pinned_settings(project)),
              "knob_families": ["minimum drive exclusion", "recover_power", "resizer max utilization",
                                "candidate cell sizing area/leakage limits"],
              "native_activity": activity}
    if level == 2:
        axes, skipped = level_two_axes(reference["resolved_settings"], activity)
        report.update(knob_families=report["knob_families"] + sorted(axes), skipped_knobs=skipped)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if spool:
        pending_jobs = {}
        report.update(spool_output=str(outbox), spool_results=str(result_directory),
                      cpu_budget_per_job=len(cores), jobs=None)
        for index, candidate in enumerate(candidates[1:], 1):
            job = submit_spool(candidate)
            pending_jobs[index] = job
            rows[index].update(state="QUEUED", spool_job=job)
            report_path.write_text(json.dumps(report, indent=2) + "\n")
        shutil.rmtree(outbox / reference_job)
        while pending_jobs:
            for index, job in list(pending_jobs.items()):
                completed = collect(job, result_directory, output / rows[index]["name"])
                if completed is not None:
                    rows[index] = completed
                    del pending_jobs[index]
                    report_path.write_text(json.dumps(report, indent=2) + "\n")
                    shutil.rmtree(outbox / job)
            if pending_jobs:
                time.sleep(1)
    else:
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
                    # One active child per disjoint CPU group.
                    submit(group)
                report_path.write_text(json.dumps(report, indent=2) + "\n")
            report_path.write_text(json.dumps(report, indent=2) + "\n")
    for row in rows:
        row["objective"] = compare_native(reference, row, weights)
        row["comparison_to_reference"] = compare_fields(trial_fields(row), trial_fields(reference))
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
             f"{report['public_invocations']} public invocations; executor {report['executor']}.", "",
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
    lines += ["", "Per-field comparisons against the reference (raw native trial scope):", "",
              "| Variant | Field | Subject | Reference | Delta | Result |",
              "|---|---|---:|---:|---:|---|"]
    for row in rows[1:]:
        for field, comparison in row["comparison_to_reference"].items():
            values = [str(comparison[key]) if comparison[key] is not None else "NOT_MEASURED"
                      for key in ("subject", "baseline", "delta")]
            lines.append(f"| {row['name']} | {field} | " + " | ".join(values)
                         + f" | {comparison['verdict']} |")
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


def explore_public(project, *, level, level_source, flow_args=(), spool=None):
    """Publish the adopted trial into the public project's canonical outputs."""
    import vibeic_temp

    started = time.monotonic()
    project = Path(project).resolve()
    output = project / "reports/ppa" / ("run-" + str(time.time_ns()))
    if level > 2:
        output.mkdir(parents=True, exist_ok=True)
        pending = {"ppa_level": level, "ppa_level_source": level_source,
                   "state": "NOT_MEASURED", "reason": "Final native-tool Stage A handoff is required before Stage B execution"}
        (output / "results.json").write_text(json.dumps(pending, indent=2) + "\n")
        summary = {**pending, "steps": [], "fail": 0, "not_measured": 1,
                   "ppa": {"results": str(output / "results.json"), "selected": None}}
        (project / "reports/flow_engine.json").write_text(json.dumps(summary, indent=2) + "\n")
        return 2
    options = {"spool": spool} if spool else {}
    result = explore(project, output, ppa_level=level, flow_args=flow_args, **options)
    chosen = result.get("selected_project")
    diagnostic = chosen or result["variants"][0]["project"]
    source = Path(diagnostic)
    if chosen:
        for folder in ("phase1", "phase2", "phase3", "steps", "work", "reports"):
            if (source / folder).is_dir():
                shutil.copytree(source / folder, project / folder, dirs_exist_ok=True)
        # Keep the complete trial population under reports/ppa. Only canonical
        # published outputs point at the adopted project's new location.
        for folder in ("phase1", "phase2", "phase3", "steps", "work", "reports"):
            for path in (project / folder).rglob("*.json"):
                if path.is_relative_to(project / "reports/ppa"):
                    continue
                try:
                    before = json.loads(path.read_text())
                except (ValueError, OSError):
                    continue
                after = vibeic_temp.relocate(before, {str(source): str(project)})
                if before != after:
                    mode = path.stat().st_mode
                    path.chmod(mode | 0o200)
                    try:
                        path.write_text(json.dumps(after, indent=2) + "\n")
                    finally:
                        path.chmod(mode)
    summary = _load(source / "reports/flow_engine.json")
    if chosen:
        summary = vibeic_temp.relocate(summary, {str(source): str(project)})
    summary.update(ppa_level=level, ppa_level_source=level_source,
                   public_wall_seconds=time.monotonic() - started,
                   ppa={"results": str(output / "results.json"), "selected": result["selected"],
                        "selected_project": chosen, "native_trial_wall_seconds": summary.get("wall_seconds"),
                        "native_child_cpu_hours": (sum(row["cpu_hours"] for row in result["variants"])
                                                   if all("cpu_hours" in row for row in result["variants"]) else None)})
    (project / "reports/flow_engine.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if chosen else 1 if any(row["status"] == "FAIL"
                                   for row in summary.get("steps", [])) else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpus", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--jobs", type=int, choices=range(1, 3), default=2)
    parser.add_argument("--ppa-level", type=int, choices=range(5),
                        help="CLI overrides document PPA_LEVEL; default2. Levels3/4 use the native-tool handoff.")
    parser.add_argument("--spool", nargs=2, type=Path, metavar=("OUTPUT", "RESULTS"),
                        help="Publish self-contained native jobs and read their returned results; default is local.")
    args, forwarded = parser.parse_known_args()
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    try:
        result = explore(args.project, args.output, cpus=args.cpus, jobs=args.jobs,
                         flow_args=forwarded, ppa_level=args.ppa_level, spool=args.spool)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("Selected: " + (result["selected"] or "none"))
    return 0 if result["selected"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
