#!/usr/bin/env python3
"""Render measured engine results and an integration guide for exported views."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import flow_engine as engine


def integration_guide(project: Path, report: dict) -> None:
    kit = project / "phase3/stage4/hardmacro"
    if not kit.is_dir():
        return
    configs = sorted((project / "steps").glob("*/yosys_synthesis/config.json"))
    config = engine.read_json(configs[0]) if configs else {}
    lines = [f"# {config.get('DESIGN_NAME', project.name)} integration views", "",
             "These are native LibreLane views. Declared signoff limits remain open where listed below.", "",
             f"PDK `{config.get('PDK', 'NOT_MEASURED')}`. Clock port `{config.get('CLOCK_PORT', 'NOT_MEASURED')}`.",
             f"Declared clock period `{config.get('CLOCK_PERIOD', 'NOT_MEASURED')}` ns.", "",
             "Use the exported SDC constraints and the Liberty file for the required corner.", ""]
    lines.extend(f"- [{path.relative_to(kit)}]({path.relative_to(kit)})"
                 for pattern in ("*.lef", "*.gds", "*.lib", "*.v", "sdc/*", "lib/*/*")
                 for path in sorted(kit.glob(pattern)) if path.is_file())
    failures = [(row["title"], check) for row in report["steps"] for check in row["metrics"]
                if check["status"] == "FAIL"]
    lines += ["", "## Open limits", ""]
    if failures:
        lines += ["| Measurement | Native value | Original limit |", "| --- | --- | --- |"]
        lines.extend(f"| {check['metric']} | {check['value']} | {check['operator']} {check['limit']} |"
                     for _, check in failures)
    else:
        lines.append("No failed numeric comparison is recorded. Unmeasured obligations remain open.")
    lines += ["", "See the engine results for missing measurements and the exact native reports.",
              "The exported views alone do not establish release acceptance.", ""]
    (kit / "README.md").write_text("\n".join(lines))


def render(project: Path, output: Path, stage: str, head: str,
           tests_report: Path | None = None) -> dict:
    report = engine.refresh_report(project)
    output.mkdir(parents=True, exist_ok=True)
    table = engine.read_json(engine.TABLE)
    positions = {row["name"]: index + 1 for index, row in enumerate(table["steps"])}
    with (output / "STEPS.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["position", "name", "status", "exit_code", "tool_seconds", "program_seconds",
                         "ai_seconds", "ai_review", "report"])
        for row in report["steps"]:
            writer.writerow([positions[row["name"]], row["name"], row["status"], row["tool_exit_code"],
                             row["tool_seconds"], row["program_seconds"], row.get("ai_seconds"),
                             row.get("ai_review"),
                             project / "steps" / row["name"] / "result.json"])
    with (output / "SELECTED_GAPS.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["step", "metric", "reason"])
        for row in report["steps"]:
            for check in row["metrics"]:
                if check["status"] == "NOT_MEASURED":
                    writer.writerow([row["name"], check["metric"], check.get("missing", row["detail"])])
    def duration(value):
        return "NOT_MEASURED" if value is None else f"{value:.3f} s"
    new_failed = ([case.get("name") for case in ET.parse(tests_report).iter("testcase")
                   if case.find("failure") is not None or case.find("error") is not None]
                  if tests_report is not None else ["NOT_MEASURED"])
    lines = [f"steps {report['pass']} PASS / {report['run']} run / {report['selected']} selected; {stage}; current", "",
             "Run the Router-selected native chain from design documents without hand-written inter-step files.", "",
             f"Project `{project}`. `{report['fail']}` failed rows and `{report['not_measured']}` unmeasured rows.", "",
             f"FIX-PUSHED head={head} branch=flow-engine NEW_FAILED={json.dumps(new_failed)}", "",
             f"Tool time {duration(report['tool_seconds'])}. Program time {duration(report['program_seconds'])}.",
             f"Measured AI review time {duration(report['ai_seconds'])}.",
             f"Total row wall time {duration(report['wall_seconds'])}.", "",
             "Slowest tool steps: " + ", ".join(report["slowest_steps"]) + ".", "",
             "Each row is timed in STEPS.tsv. Missing AI durations are NOT_MEASURED.", "",
             "Unmeasured selected obligations are listed in SELECTED_GAPS.tsv. They are measurement gaps, not requests for new limits.", "",
             "The tool chain did not wait for AI review. Native failures and unmeasured obligations remain open.", ""]
    (output / "RESULT.md").write_text("\n".join(lines))
    integration_guide(project, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", default="verification")
    parser.add_argument("--head", required=True)
    parser.add_argument("--tests-report", type=Path)
    args = parser.parse_args()
    render(args.project.resolve(), args.output.resolve(), args.stage, args.head, args.tests_report)


if __name__ == "__main__":
    main()
