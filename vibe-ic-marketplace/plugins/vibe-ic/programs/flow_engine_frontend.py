#!/usr/bin/env python3
"""Public owner-program adapters for the opt-in native step engine."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
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


if __name__ == "__main__":
    sys.exit(phase1_main())
