#!/usr/bin/env python3
"""Public owner-program adapters for the opt-in native step engine."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def selected_engine(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--engine", choices=("legacy", "native"),
                        default=os.environ.get("VIBEIC_FLOW_ENGINE", "legacy"))
    return parser.parse_known_args(argv)[0].engine


def phase1_main(argv=None):
    """Run the existing document extractor without submission admission."""
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--engine", choices=("native",), default="native")
    parser.add_argument("--route", choices=("ic", "ip"))
    parser.add_argument("--ic-name", default="UNNAMED_CHIP")
    parser.add_argument("--mode", choices=("auto", "docs", "prompt"), default="auto")
    parser.add_argument("--pdk")
    parser.add_argument("--skip-analog", action="store_true")
    parser.add_argument("--execution-mode", choices=("default",), default="default")
    args, forwarded = parser.parse_known_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        parser.error(f"not a directory: {project}")
    import _delivery_route
    refusal = _delivery_route.admit(project, args.route, allow_rtl_scope=False)
    if refusal:
        print(_delivery_route.refusal_message(refusal), file=sys.stderr)
        return 2
    import phase1_one_shot_runner as owner
    if args.pdk:
        forwarded += ["--pdk", args.pdk]
    start = time.monotonic()
    code = owner._run_docs_mode(project, args.ic_name, forwarded)
    status = {0: "PASS", 1: "FAIL"}.get(code, "NOT_MEASURED")
    report = {
        "project": str(project), "phase": 1, "mode": "docs",
        "verdict": status, "duration_s": time.monotonic() - start,
        "delegated_to": "phase1_doc_one_shot_runner", "delegated_rc": code,
        "steps": [{"name": owner.D1_STEP_NAME, "status": status,
                   "exit_code": code}],
        "expert_review": "PENDING",
    }
    output = project / "reports/orchestrator/phase1_one_shot.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return code


def run_owner(project, route, directory, kind):
    """Use owner reports, running the selected bounded RTL window when needed."""
    project, directory = Path(project).resolve(), Path(directory)
    report_name = "phase1_one_shot.json" if kind == "phase1" else "phase2_one_shot.json"
    report_path = project / "reports/orchestrator" / report_name
    code = None
    elapsed = 0.0
    if kind == "rtl" and route["delivery_target"] == "rtl":
        command = [sys.executable, str(Path(__file__).with_name("design_one_shot_runner.py")),
                   str(project), "--entry-step", str(route["entry_step"]),
                   "--exit-step", str(route["verify_through"]),
                   "--rtl-input", route.get("input_contract", "structured"),
                   "--skip-hardware", "--skip-analog", "--skip-phase3",
                   "--execution-mode", "default"]
        directory.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "VIBEIC_FLOW_ENGINE": "legacy"}
        started = time.monotonic()
        with (directory / "owner.log").open("w") as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                     env=environment, check=False)
        elapsed = time.monotonic() - started
        code = process.returncode
    if not report_path.is_file():
        return {"ran": code is not None, "exit_code": code, "metrics": {},
                "reports": [], "tool_seconds": 0.0,
                "detail": "The existing owner produced no report."}
    report = json.loads(report_path.read_text())
    return {"ran": True, "exit_code": code,
            "metrics": {row["name"]: row.get("status") for row in report.get("steps", [])},
            "reports": [str(report_path)], "tool_seconds": elapsed,
            "detail": "Existing owner report; native verdicts remain in its steps."}


def run_public(args):
    """Forward the public entry's selected Router window to the native engine."""
    import flow_engine
    project = args.project.resolve()
    if args.entry_step is not None or args.exit_step is not None:
        if args.entry_step is None or args.exit_step is None:
            raise ValueError("The native entry requires both Router window bounds.")
        route = {"entry_step": args.entry_step, "verify_through": args.exit_step,
                 "input_contract": args.rtl_input,
                 "delivery_target": args.delivery_target or
                    ("ip_hardmacro" if args.route == "ip" else "shippable_gds")}
    else:
        import task_nature_route as router
        text = flow_engine.design_text(project)
        proposal = router.route_task(text)
        target = args.delivery_target
        if target is None and args.route == "ip":
            target = "ip_hardmacro"
        if target is None:
            requirements = router.prompt_delivery_requirements(text)
            resolved = router.resolve_prompt_delivery_target(requirements, None)
            if not resolved["ok"]:
                raise ValueError(resolved["reason"])
            target = resolved["target"]
        route = router.route_decision_receipt(
            text, nature=proposal["entry_nature"], delivery_target=target)
    summary = flow_engine.run(project, route=route)
    return 1 if summary.get("fail") else 2 if summary.get("not_measured") else 0


if __name__ == "__main__":
    sys.exit(phase1_main())
