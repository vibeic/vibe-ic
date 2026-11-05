#!/usr/bin/env python3
"""Run the Router-selected window of the native step table."""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from decimal import Decimal
import fnmatch
import json
import math
import operator
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
TABLE = HERE.parent / "flow/steps.json"
COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
           ">=": operator.ge, "==": operator.eq, "eq": operator.eq}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def write_json(path: Path, value: Any) -> None:
    def native_numbers(item):
        if isinstance(item, dict):
            return {str(key): native_numbers(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [native_numbers(val) for val in item]
        if isinstance(item, (float, Decimal)):
            if not math.isfinite(item):
                return "Infinity" if item > 0 else "-Infinity" if item < 0 else "NaN"
            return float(item)
        return item
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(native_numbers(value), indent=2, default=str, allow_nan=False) + "\n")
    temporary.replace(path)


def predicate(expression: str, features: dict) -> bool:
    def visit(node):
        if isinstance(node, ast.Name):
            return features[node.id]
        if isinstance(node, ast.Constant) and type(node.value) is bool:
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not visit(node.operand)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [visit(item) for item in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        raise ValueError(f"Unsupported predicate {expression}")
    return visit(ast.parse(expression, mode="eval").body)


def design_text(project: Path) -> str:
    paths = sorted((project / "input/docs").glob("*.md"))
    prompt = project / "input/phase1_prompt.md"
    if prompt.is_file():
        paths = [prompt]
    if not paths:
        raise FileNotFoundError("Design documents or input/phase1_prompt.md are required")
    return "\n\n".join(path.read_text() for path in paths)


def select_route(project: Path) -> dict:
    import task_nature_route as router
    for path in (project / "reports/route_decision.json", project / "route_decision.json"):
        existing = read_json(path)
        if existing:
            return existing.get("route_receipt", existing)
    text = design_text(project)
    proposal = router.route_task(text)
    answers = read_json(project / "input/step_0_5ic_answers.json").get("answers", {})
    deliverable = answers.get("deliverable")
    if deliverable in {"DIE", "HARDMACRO"}:
        target = "shippable_gds" if deliverable == "DIE" else "ip_hardmacro"
    else:
        requirements = router.prompt_delivery_requirements(text)
        resolved = router.resolve_prompt_delivery_target(requirements, None)
        if not resolved.get("ok"):
            raise ValueError(f"Router needs delivery clarification: {resolved}")
        target = resolved["target"]
    return router.route_decision_receipt(
        text, nature=proposal["entry_nature"], delivery_target=target)


def design_features(project: Path, route: dict, table: dict) -> dict:
    names = set()
    expressions = [row["when"] for row in table["steps"]]
    expressions += list(table.get("predicates", {}).values())
    for expression in expressions:
        names.update(node.id for node in ast.walk(ast.parse(expression, mode="eval"))
                     if isinstance(node, ast.Name))
    features = dict.fromkeys(names, False)
    docs = project / "phase1/generated_docs"
    target = route["delivery_target"]
    features.update(always=True, ic=target in {"gds", "shippable_gds", "foundry_handoff"}, hard_ip=target == "ip_hardmacro",
                    soft_ip=target == "ip_soft", model_ip=target == "ip_model",
                    rtl_only=target == "rtl", has_digital=True)
    for path in sorted(docs.glob("L*.json")):
        document = read_json(path)
        for container in (document, document.get("fields", {}), document.get("features", {})):
            features.update({key: value for key, value in container.items()
                             if key in names and type(value) is bool})
    features["requires_cts"] = bool(
        read_json(docs / "L8_TIMING_WAVEFORM.json").get("clock_domains")
        or read_json(docs / "L8_RTL_CONSTANTS.json").get("clock_domains"))
    pending = dict(table.get("predicates", {}))
    for _ in range(len(pending) + 1):
        for key, expression in pending.items():
            features[key] = predicate(expression, features)
        for source, implied in table.get("implications", {}).items():
            if features.get(source):
                features.update(dict.fromkeys(implied, True))
    return features


def aliases(row: dict) -> list[str]:
    legacy = row.get("legacy_id", {})
    if isinstance(legacy, str):
        return [legacy, *row.get("legacy_steps", [])]
    return [legacy.get("registry", ""), *legacy.get("native", [])]


def select_steps(table: dict, route: dict, features: dict,
                 from_name: str | None, to_name: str | None) -> list[dict]:
    rows = table["steps"]
    def find(value):
        matches = [i for i, row in enumerate(rows)
                   if value == row["name"] or value in aliases(row)]
        if len(matches) != 1:
            raise ValueError(f"Router boundary has no unique table address: {value}")
        return matches[0]
    start, end = find(str(route["entry_step"])), find(str(route["verify_through"]))
    first = find(from_name) if from_name else start
    last = find(to_name) if to_name else end
    if not start <= first <= last <= end:
        raise ValueError("Requested names lie outside the Router-selected window")
    closed = set(route.get("verify_closed_steps", [])) if route.get("input_contract") == "original" else set()
    return [row for row in rows[first:last + 1] if predicate(row["when"], features)
            and (not closed or bool(closed.intersection(aliases(row))))]


@dataclass
class ToolResult:
    ran: bool = False
    exit_code: int | None = None
    metrics: dict = field(default_factory=dict)
    reports: list = field(default_factory=list)
    tool_seconds: float = 0.0
    detail: str = ""
    native_steps: list = field(default_factory=list)


def command_tool(project: Path, directory: Path, tool: dict) -> ToolResult:
    missing = [item for item in tool.get("inputs", []) if not (project / item).exists()]
    if missing:
        return ToolResult(detail=f"Missing input: {', '.join(missing)}")
    command = [str(item).replace("{project}", str(project)).replace("{step}", str(directory))
               .replace("{python}", sys.executable) for item in tool["command"]]
    log = directory / "tool.log"
    started = time.perf_counter()
    try:
        with log.open("w") as stream:
            completed = subprocess.run(command, cwd=project, stdout=stream, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        return ToolResult(detail=str(exc))
    result = ToolResult(True, completed.returncode, reports=[str(log)],
                        tool_seconds=time.perf_counter() - started)
    report = directory / tool.get("report", "metrics.json")
    if report.is_file():
        value = read_json(report)
        result.metrics = value.get("metrics", value)
        result.reports.append(str(report))
    return result


class NativeChain:
    def __init__(self, project: Path, route: dict):
        self.project, self.route = project, route
        self.owner = self.state = self.toolbox = None
        self.config: dict = {}
        self.common_started: float | None = None

    def initialize(self):
        if self.owner is not None:
            return
        from flow_config import build_config
        from librelane.flows import Flow
        from librelane.state import State
        from librelane.common import Toolbox
        kind = "Chip" if self.route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"} else "Classic"
        config = build_config(self.project, route="ic" if kind == "Chip" else "ip")
        os.environ["_OPENLANE_MAX_CORES"] = "8"
        self.owner = Flow.factory.get(kind)(config, design_dir=str(self.project),
                                            pdk_root=os.environ.get("PDK_ROOT"))
        self.config = self.owner.config.to_raw_dict()
        self.toolbox = Toolbox(str(self.project / "work/flow/tool_tmp"))
        self.state = State()

    def restore(self, directory: Path):
        from librelane.state import State
        path = directory / "state_out.json"
        if path.is_file():
            self.state = State.load(read_json(path))

    def execute(self, directory: Path, tool: dict) -> ToolResult:
        try:
            self.initialize()
        except (ImportError, FileNotFoundError, ValueError) as exc:
            return ToolResult(detail=str(exc))
        from librelane.steps import Step, StepError, StepException
        result = ToolResult()
        for name in tool.get("steps", []):
            step_class = Step.factory.get(name)
            if step_class is None:
                result.detail += f" Native step unavailable: {name}."
                result.native_steps.append({"name": name, "ran": False, "exit_code": None})
                continue
            gates = [key for pattern, keys in self.owner.gating_config_vars.items()
                     if fnmatch.fnmatchcase(name, pattern) for key in keys]
            if any(not self.config[key] for key in gates):
                result.native_steps.append({"name": name, "ran": False, "exit_code": None,
                                            "native_config_disabled": True})
                continue
            step = step_class(self.owner.config, self.state)
            missing = [item.id for item in step.inputs
                       if not item.optional and self.state.get_by_df(item) is None]
            if missing:
                result.detail += f" {name} missing input: {missing}."
                result.native_steps.append({"name": name, "ran": False, "exit_code": None,
                                            "missing_inputs": missing})
                self.state = type(self.state)(self.state, overrides={item: None for item in step.outputs})
                continue
            destination = directory / name.lower().replace(".", "_")
            started = time.perf_counter()
            if name in {"Yosys.Synthesis", "Pyosys.Synthesis"} and self.common_started is None:
                self.common_started = started
            code, ran, detail = 0, True, ""
            try:
                self.state = step.start(toolbox=self.toolbox, step_dir=str(destination))
            except StepError as exc:
                underlying = getattr(exc, "underlying_error", None)
                code = getattr(underlying, "returncode", 1) or 1
                detail = str(exc)
            except (StepException, FileNotFoundError) as exc:
                code, ran, detail = None, False, str(exc)
            if code or not ran:
                self.state = type(self.state)(self.state, overrides={item: None for item in step.outputs})
            elapsed = time.perf_counter() - started
            result.tool_seconds += elapsed
            result.ran |= ran
            if code:
                result.exit_code = code
            elif result.exit_code is None and ran:
                result.exit_code = 0
            result.native_steps.append({"name": name, "ran": ran, "exit_code": code,
                                        "tool_seconds": elapsed, "detail": detail,
                                        "reports": str(destination)})
            result.detail += detail
        result.metrics = dict(self.state.metrics)
        result.reports = [str(path) for path in directory.rglob("*") if path.is_file()]
        (directory / "state_out.json").write_text(self.state.dumps())
        return result


def choose_tool(tool: dict, features: dict) -> dict:
    if tool["kind"] != "profiles":
        return tool
    for profile in tool["profiles"]:
        if profile["when"] == "otherwise" or predicate(profile["when"], features):
            return profile["tool"]
    return {"kind": "adapter", "gap": "No applicable native tool profile"}


def measure(checks: list, metrics: dict, config: dict, features: dict) -> list[dict]:
    observed = []
    for check in checks:
        expression = check.get("when", "always")
        if expression != "otherwise" and not predicate(expression, features):
            continue
        enabled = check.get("enabled_by")
        if enabled and not config.get(enabled, check.get("enabled_default", True)):
            continue
        limit = check.get("limit")
        if check.get("limit_config"):
            limit = config.get(check["limit_config"])
        matches = {name: value for name, value in metrics.items()
                   if fnmatch.fnmatchcase(name, check["metric"])}
        if check.get("corner_config") and config.get(check["corner_config"]) is not None:
            corners = config[check["corner_config"]]
            matches = {key: value for key, value in matches.items()
                       if any(fnmatch.fnmatchcase(key.split("__corner:")[-1], corner)
                              for corner in corners)}
        if not matches:
            matches = {check["metric"]: None}
        for name, value in matches.items():
            status = "NOT_MEASURED"
            compare = COMPARE.get(check.get("operator"))
            if (compare and isinstance(value, (int, float, Decimal))
                    and isinstance(limit, (int, float, Decimal)) and math.isfinite(value)):
                status = "PASS" if compare(value, limit) else "FAIL"
            observed.append({**check, "metric": name, "value": value,
                             "limit": limit, "status": status})
    return observed


def evaluate(tool: ToolResult, measurements: list) -> str:
    if tool.ran and tool.exit_code:
        return "FAIL"
    if not tool.ran:
        return "NOT_MEASURED"
    if any(not item["ran"] and not item.get("native_config_disabled") for item in tool.native_steps):
        return "NOT_MEASURED"
    if any(item["status"] == "FAIL" for item in measurements):
        return "FAIL"
    if not tool.ran or not measurements or any(item["status"] == "NOT_MEASURED" for item in measurements):
        return "NOT_MEASURED"
    return "PASS"


def run(project: Path | str, *, table: dict | None = None, route: dict | None = None,
        from_name: str | None = None, to_name: str | None = None,
        budget_seconds: float | None = None) -> dict:
    project = Path(project).resolve()
    table = table or read_json(TABLE)
    route = route or select_route(project)
    features = design_features(project, route, table)
    selected = select_steps(table, route, features, from_name, to_name)
    chain = NativeChain(project, route)
    positions = {row["name"]: i + 1 for i, row in enumerate(table["steps"])}
    results: dict[str, dict] = {}
    step_root = project / "steps"
    step_root.mkdir(parents=True, exist_ok=True)
    if from_name:
        first = positions[from_name]
        for row in table["steps"][first - 1:]:
            path = step_root / row["name"] / "result.json"
            path.unlink(missing_ok=True)
        for row in reversed(table["steps"][:first - 1]):
            directory = step_root / row["name"]
            if (directory / "state_out.json").is_file():
                chain.initialize()
                chain.restore(directory)
                break
    started = time.perf_counter()
    for row in selected:
        beginning = time.perf_counter()
        directory = step_root / row["name"]
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
        tool = choose_tool(row["tool"], features)
        kind = tool["kind"]
        if kind == "command":
            native = command_tool(project, directory, tool)
        elif kind == "librelane":
            native = chain.execute(directory, tool)
        elif kind == "native_report":
            previous = results.get(tool["from"]) or read_json(step_root / tool["from"] / "result.json")
            native = ToolResult(bool(previous.get("tool_ran")), previous.get("tool_exit_code"),
                                previous.get("native_metrics", {}), previous.get("reports", []),
                                detail=f"Native reports from {tool['from']}")
        elif kind == "adapter" and tool.get("adapter"):
            from flow_native_adapters import execute
            native = ToolResult(**execute(project, directory, tool, route))
        elif kind == "adapter" and tool.get("program") in {"phase1_one_shot_runner.py", "design_one_shot_runner.py"}:
            from flow_engine_frontend import run_owner
            owner_kind = "phase1" if tool["program"] == "phase1_one_shot_runner.py" else "rtl"
            native = ToolResult(**run_owner(project, route, directory, owner_kind))
        else:
            native = ToolResult(detail=tool.get("gap", "Native adapter is not available"))
        observed = measure(row["checks"], native.metrics, chain.config, features)
        elapsed = time.perf_counter() - beginning
        result = {"name": row["name"], "title": row["title"],
                  "status": evaluate(native, observed), "tool_ran": native.ran,
                  "tool_exit_code": native.exit_code, "metrics": observed,
                  "native_metrics": native.metrics, "native_steps": native.native_steps,
                  "reports": native.reports, "detail": native.detail,
                  "tool_seconds": native.tool_seconds,
                  "program_seconds": max(0, elapsed - native.tool_seconds),
                  "ai_seconds": None, "ai_review": "PENDING",
                  "wall_seconds": elapsed, "tool_kind": kind}
        write_json(directory / "result.json", result)
        results[row["name"]] = result
        results = {name: read_json(step_root / name / "result.json") for name in results}
        print(f"Step {positions[row['name']]} {row['title']}: {result['status']}", flush=True)
        summary = {"route": route, "selected": len(selected), "run": len(results),
                   "pass": sum(item["status"] == "PASS" for item in results.values()),
                   "fail": sum(item["status"] == "FAIL" for item in results.values()),
                   "not_measured": sum(item["status"] == "NOT_MEASURED" for item in results.values()),
                   "tool_seconds": sum(item["tool_seconds"] for item in results.values()),
                   "program_seconds": sum(item["program_seconds"] for item in results.values()),
                   "ai_seconds": (sum(item["ai_seconds"] for item in results.values())
                                  if all(item["ai_seconds"] is not None for item in results.values()) else None),
                   "wall_seconds": time.perf_counter() - started,
                   "common_wall_seconds": (time.perf_counter() - chain.common_started
                                           if chain.common_started is not None else None),
                   "budget_seconds": budget_seconds,
                   "steps": list(results.values())}
        common = summary["common_wall_seconds"]
        summary["runtime_status"] = ("OVER_BUDGET" if budget_seconds is not None and common is not None
                                     and common > budget_seconds else "IN_BUDGET" if budget_seconds is not None
                                     and common is not None else "NOT_MEASURED")
        summary["timing_groups"] = {
            group: {metric: sum(item[metric] for item in results.values()
                                if (item["tool_kind"] in {"librelane", "native_report"}) == native)
                    for metric in ("tool_seconds", "program_seconds")}
            for group, native in (("librelane", True), ("other", False))}
        write_json(project / "reports/flow_engine.json", summary)
    return summary if selected else {"route": route, "selected": 0, "run": 0, "steps": []}


def record_review(project: Path, name: str, seconds: float, finding: str | None = None) -> None:
    """Record a timed concurrent expert reading without changing native verdicts."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Review duration must be measured nonnegative seconds")
    path = project / "steps" / name / "result.json"
    result = read_json(path)
    if not result:
        raise FileNotFoundError(path)
    result.update(ai_seconds=seconds, ai_review="FINDING" if finding else "REVIEWED",
                  ai_finding=finding)
    write_json(path, result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("run")
    command.add_argument("--project", type=Path, required=True)
    command.add_argument("--from", dest="from_name")
    command.add_argument("--to", dest="to_name")
    command.add_argument("--budget-seconds", type=float)
    review = sub.add_parser("review")
    review.add_argument("--project", type=Path, required=True)
    review.add_argument("--step", required=True)
    review.add_argument("--seconds", type=float, required=True)
    review.add_argument("--finding")
    args = parser.parse_args()
    try:
        if args.action == "review":
            record_review(args.project, args.step, args.seconds, args.finding)
            return 0
        result = run(args.project, from_name=args.from_name, to_name=args.to_name,
                     budget_seconds=args.budget_seconds)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"NOT_MEASURED: {exc}", file=sys.stderr)
        return 2
    return 1 if result.get("fail") else 2 if result.get("not_measured") else 0


if __name__ == "__main__":
    raise SystemExit(main())
