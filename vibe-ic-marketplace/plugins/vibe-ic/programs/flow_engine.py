#!/usr/bin/env python3
"""Run the Router-selected window of the native step table."""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from decimal import Decimal
import fnmatch
import importlib
import json
import math
import operator
import os
from pathlib import Path
import re
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


def decimal_number(value):
    return Decimal(int(value)) if isinstance(value, bool) else Decimal(str(value))


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
    expressions += [check["when"] for row in table["steps"] for check in row.get("checks", [])
                    if check.get("when") not in (None, "otherwise")]
    expressions += [item["when"] for row in table["steps"] for item in row.get("observations", [])
                    if item.get("when") not in (None, "otherwise")]
    expressions += list(table.get("predicates", {}).values())
    expressions += [default["when"] for default in table.get("feature_defaults", {}).values()]
    for expression in expressions:
        names.update(node.id for node in ast.walk(ast.parse(expression, mode="eval"))
                     if isinstance(node, ast.Name))
    features = dict.fromkeys(names, False)
    docs = project / "phase1/generated_docs"
    target = route["delivery_target"]
    features.update(always=True, ic=target in {"gds", "shippable_gds", "foundry_handoff"}, hard_ip=target == "ip_hardmacro",
                    soft_ip=target == "ip_soft", model_ip=target == "ip_model",
                    rtl_only=target == "rtl", has_digital=True)
    explicit = set()
    for path in sorted(docs.glob("L*.json")):
        document = read_json(path)
        for container in (document, document.get("fields", {}), document.get("features", {})):
            if not isinstance(container, dict):
                continue
            declared = {key: value for key, value in container.items()
                        if key in names and type(value) is bool}
            features.update(declared)
            explicit.update(declared)
    features.update(ic=target in {"gds", "shippable_gds", "foundry_handoff"},
                    hard_ip=target == "ip_hardmacro", rtl_only=target == "rtl")
    if "requires_cts" not in explicit:
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
        for key, default in table.get("feature_defaults", {}).items():
            if key not in explicit and predicate(default["when"], features):
                features[key] = default["value"]
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
    physical_delivery = route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff", "ip_hardmacro"}
    closed = set(route.get("verify_closed_steps", [])) if not physical_delivery else set()
    if closed:
        indices = [i for i, row in enumerate(rows) if closed.intersection(aliases(row))]
        if indices:
            start, end = min(indices), max(indices)
    first = find(from_name) if from_name else start
    last = find(to_name) if to_name else end
    if not start <= first <= last <= end:
        raise ValueError("Requested names lie outside the Router-selected window")
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
    def __init__(self, project: Path, route: dict, pdk: str | None = None):
        self.project, self.route = project, route
        self.pdk = pdk
        self.owner = self.state = self.toolbox = None
        self.config: dict = {}
        self.common_started: float | None = None
        self.preparation_runs: list[dict] = []
        self.preparation_accounted = 0
        self.initialization_error: Exception | None = None

    def observe_preparation(self, run):
        self.preparation_runs.append(run)
        if run["name"] == "Yosys.Synthesis" and run["ran"] and self.common_started is None:
            self.common_started = time.perf_counter() - run["tool_seconds"]

    def initialize(self):
        if self.initialization_error is not None:
            raise self.initialization_error
        if self.owner is not None:
            return
        from flow_config import build_native_config as build_config
        from librelane.flows import Flow
        from librelane.state import State
        from librelane.common import Toolbox
        kind = "Chip" if self.route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"} else "Classic"
        config = build_config(self.project, route="ic" if kind == "Chip" else "ip",
                              **({"pdk": self.pdk} if self.pdk else {}),
                              **({"on_tool_run": self.observe_preparation} if kind == "Chip" else {}))
        os.environ["_OPENLANE_MAX_CORES"] = "8"
        self.owner = Flow.factory.get(kind)(config, design_dir=str(self.project),
                                            pdk_root=os.environ.get("PDK_ROOT"))
        self.config = self.owner.config.to_raw_dict()
        self.toolbox = Toolbox(str(self.project / "work/flow/tool_tmp"))
        self.state = State()

    def prepare(self):
        try:
            self.initialize()
        except Exception as exc:
            if not isinstance(exc, (ImportError, FileNotFoundError, ValueError)) and not self.preparation_runs:
                raise
            self.initialization_error = exc
            return exc
        return None

    def preparation_result(self) -> ToolResult:
        runs = self.preparation_runs[self.preparation_accounted:]
        self.preparation_accounted = len(self.preparation_runs)
        result = ToolResult(any(run["ran"] for run in runs),
            next((run["exit_code"] for run in runs if run.get("exit_code")), 0 if runs else None),
            reports=[run["reports"] for run in runs],
            tool_seconds=sum(run["tool_seconds"] for run in runs), native_steps=list(runs))
        if self.initialization_error is not None:
            result.detail = str(self.initialization_error)
            result.native_steps.append({"name": "Native configuration", "ran": False,
                "exit_code": None, "status": "NOT_MEASURED", "detail": result.detail})
        return result

    def restore(self, directory: Path):
        from librelane.state import State
        path = directory / "state_out.json"
        if path.is_file():
            restored = State.load(read_json(path))
            self.state = restored

    def execute(self, directory: Path, tool: dict) -> ToolResult:
        error = self.prepare()
        result = self.preparation_result()
        if error is not None:
            return result
        from librelane.steps import Step, StepError, StepException
        for module in tool.get("imports", []):
            importlib.import_module(module)
        producer_unavailable = False
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
            emitted = {}

            class ObservedStep(step_class):
                def run(self, *args, **kwargs):
                    views, metrics = super().run(*args, **kwargs)
                    emitted.update(metrics)
                    return views, metrics

            step = ObservedStep(self.owner.config, self.state)
            metric_name = getattr(step, "metric_name", None)
            if (metric_name and producer_unavailable and not any(
                    key == metric_name or key.startswith(metric_name + "__corner:") for key in result.metrics)):
                result.native_steps.append({"name": name, "ran": False, "exit_code": None,
                                            "status": "NOT_MEASURED", "missing_inputs": [metric_name]})
                continue
            if metric_name:
                result.metrics.update({key: value for key, value in self.state.metrics.items()
                                       if key == metric_name or key.startswith(metric_name + "__corner:")})
            missing = [item.id for item in step.inputs
                       if not item.optional and self.state.get_by_df(item) is None]
            if missing:
                producer_unavailable = True
                result.detail += f" {name} missing input: {missing}."
                result.native_steps.append({"name": name, "ran": False, "exit_code": None,
                                            "missing_inputs": missing})
                self.state = type(self.state)(self.state, overrides={item: None for item in step.outputs
                                                                    if item not in step.inputs},
                                              metrics=self.state.metrics)
                continue
            destination = directory / name.lower().replace(".", "_")
            started = time.perf_counter()
            if name in {"Yosys.Synthesis", "Pyosys.Synthesis"} and self.common_started is None:
                self.common_started = started
            code, ran, detail = 0, True, ""
            status = "PASS"
            try:
                destination.mkdir(parents=True, exist_ok=True)
                working_directory = Path.cwd()
                try:
                    os.chdir(destination)
                    self.state = step.start(toolbox=self.toolbox, step_dir=str(destination))
                finally:
                    os.chdir(working_directory)
            except StepError as exc:
                underlying = getattr(exc, "underlying_error", None)
                code = getattr(underlying, "returncode", 1) or 1
                detail = str(exc)
                status = "NOT_MEASURED" if "NOT_MEASURED" in detail else "FAIL"
            except (StepException, FileNotFoundError) as exc:
                code, ran, detail = None, False, str(exc)
                status = "NOT_MEASURED"
            if code or not ran:
                producer_unavailable = True
                self.state = type(self.state)(self.state, overrides={item: None for item in step.outputs
                                                                    if item not in step.inputs},
                                              metrics=self.state.metrics)
            result.metrics.update(emitted)
            if name == "OpenROAD.IRDropReport" and "ir__drop__worst" in emitted:
                libraries = self.toolbox.filter_views(self.owner.config, self.owner.config["LIB"])
                voltage = self.toolbox.get_lib_voltage(str(libraries[0])) if libraries else None
                if voltage:
                    result.metrics["ir__drop__worst__pct"] = float(emitted["ir__drop__worst"]) / float(voltage) * 100
            elapsed = time.perf_counter() - started
            result.tool_seconds += elapsed
            result.ran |= ran
            if code:
                result.exit_code = code
            elif result.exit_code is None and ran:
                result.exit_code = 0
            result.native_steps.append({"name": name, "ran": ran, "exit_code": code,
                                        "status": status,
                                        "tool_seconds": elapsed, "detail": detail,
                                        "reports": str(destination)})
            result.detail += detail
        result.reports = [str(path) for path in directory.rglob("*") if path.is_file()]
        (directory / "state_out.json").write_text(self.state.dumps())
        return result

    def snapshot(self, directory: Path, tool: dict) -> ToolResult:
        if self.state is None:
            return ToolResult(detail="No native State has been produced")
        destination = self.project / tool["destination"]
        self.state.save_snapshot(str(destination))
        formats = tool.get("formats", {})
        from librelane.state import DesignFormat
        missing = []
        exported = []
        for name, extension in formats.items():
            value = self.state.get_by_df(DesignFormat.factory.get(name))
            if value is None:
                missing.append(name)
                continue
            if isinstance(value, dict):
                value = value.get(self.config["DEFAULT_CORNER"])
            if value is None:
                missing.append(name)
                continue
            shutil.copyfile(str(value), destination / (self.config["DESIGN_NAME"] + extension))
            exported.append(name)
        text = [f"# {self.config['DESIGN_NAME']} integration views", "",
                "Views and reports were exported by LibreLane from its final State.",
                "See the native metrics and the per-step results for measured limits.", ""]
        if missing:
            text.append("NOT_MEASURED views: " + ", ".join(missing))
        (destination / "README.md").write_text("\n".join(text) + "\n")
        reports = [str(path) for path in destination.rglob("*") if path.is_file()]
        metrics = {**dict(self.state.metrics), tool.get("metric", "ip_endpoint_views"): {
            "required": list(formats), "observed": exported}}
        return ToolResult(True, 0, metrics, reports,
                          detail="Missing native views: " + ", ".join(missing) if missing else "Native views exported")


def choose_tool(tool: dict, features: dict) -> dict:
    if tool["kind"] != "profiles":
        return tool
    for profile in tool["profiles"]:
        if profile["when"] == "otherwise" or predicate(profile["when"], features):
            return {**profile["tool"], "selected_profile": profile["when"]}
    return {"kind": "adapter", "gap": "No applicable native tool profile"}


def document_value(project: Path | None, reference: dict) -> Any:
    if project is None:
        return None
    for location in reference.get("paths", []):
        filename, _, pointer = location.partition("#")
        for path in sorted(project.glob(filename)):
            value = read_json(path)
            try:
                for key in pointer.strip("/").split("/") if pointer.strip("/") else []:
                    value = value[int(key)] if isinstance(value, list) else value[key]
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            return value
    if reference.get("metric"):
        found = []
        def visit(value):
            if isinstance(value, dict):
                if reference["metric"] in value and value[reference["metric"]] is not None:
                    found.append(value[reference["metric"]])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        for path in sorted((project / "phase1/generated_docs").glob("L*.json")):
            visit(read_json(path))
        if found:
            return found[0] if all(value == found[0] for value in found) else {"conflicting_bounds": found}
    return None


def measure(checks: list, metrics: dict, config: dict, features: dict,
            project: Path | None = None) -> list[dict]:
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
        if limit is None and check.get("limit_from"):
            limit = document_value(project, check["limit_from"])
        matches = {name: value for name, value in metrics.items()
                   if fnmatch.fnmatchcase(name, check["metric"])}
        corners = [corner for corner in config.get(check.get("corner_config"), []) or [] if corner]
        if corners:
            matches = {key: value for key, value in matches.items()
                       if any(fnmatch.fnmatchcase(key.split("__corner:")[-1], corner)
                              for corner in corners)}
        if not matches:
            matches = {check["metric"]: None}
        for name, value in matches.items():
            status = "NOT_MEASURED"
            compare = COMPARE.get(check.get("operator"))
            if check.get("operator") == "covers_all":
                required = (value.get("required") if isinstance(value, dict) else None)
                if required is None:
                    required = document_value(project, check.get("required_from", {}))
                observed_set = value.get("observed") if isinstance(value, dict) else value
                if isinstance(required, list) and isinstance(observed_set, list):
                    missing = [item for item in required if item not in observed_set]
                    status, limit = ("FAIL" if missing else "PASS"), required
                    value = {"observed": observed_set, "missing": missing}
            elif check.get("operator") == "within_declared_bounds":
                if isinstance(limit, dict) and isinstance(value, (int, float, Decimal)) and math.isfinite(value):
                    lower, upper = limit.get("min"), limit.get("max")
                    bounds = [bound for bound in (lower, upper) if bound is not None]
                    if bounds and all(isinstance(bound, (int, float, Decimal)) and math.isfinite(bound) for bound in bounds):
                        number = decimal_number(value)
                        lower = decimal_number(lower) if lower is not None else None
                        upper = decimal_number(upper) if upper is not None else None
                        lower_ok = lower is None or (number > lower if limit.get("min_exclusive") else number >= lower)
                        upper_ok = upper is None or (number < upper if limit.get("max_exclusive") else number <= upper)
                        status = "PASS" if lower_ok and upper_ok else "FAIL"
            if (compare and isinstance(value, (int, float, Decimal))
                    and isinstance(limit, (int, float, Decimal)) and math.isfinite(value) and math.isfinite(limit)):
                status = "PASS" if compare(decimal_number(value), decimal_number(limit)) else "FAIL"
            unavailable = value in check.get("unavailable_values", [])
            if unavailable:
                status = "NOT_MEASURED"
            observed.append({**check, "metric": name, "value": value,
                             "limit": limit, "status": status,
                             **({"missing": check["unavailable_reason"] if unavailable else
                                 check.get("missing") or f"Native value or original limit for {check['metric']}"}
                                if status == "NOT_MEASURED" else {})})
    return observed


def report_observations(row, directory, native, config, features, project):
    observations, checks = [], []
    for item in row.get("observations", []):
        if item.get("when", "always") != "otherwise" and not predicate(item.get("when", "always"), features):
            continue
        values = {key: value for key, value in native.metrics.items()
                  if any(fnmatch.fnmatchcase(key, name) or key.startswith(name + "__corner:")
                         for name in item.get("native_metrics", []))}
        for number in item.get("native_report_numbers", []):
            path = directory / number["report"]
            matches = re.findall(number["pattern"], path.read_text()) if path.is_file() else []
            if matches:
                values[number["metric"]] = float(matches[-1])
                native.metrics[number["metric"]] = values[number["metric"]]
        limit = config.get(item["limit_config"]) if item.get("limit_config") else item.get("limit")
        if limit is None:
            limit = document_value(project, item.get("declared_limit_from", {}))
        observations.append({**item, "values": values, "limit": limit,
                             "status": "OBSERVED" if values else "NOT_MEASURED"})
        if limit is not None:
            if len(item.get("native_metrics", [])) == 1:
                checks.append({**item, "metric": item["native_metrics"][0], "limit": limit})
            elif isinstance(limit, dict) and not {"min", "max"}.intersection(limit):
                checks.extend({**item, "metric": key, "limit": value} for key, value in limit.items())
            else:
                checks.append({**item, "limit": limit})
    return observations, checks


def evaluate(tool: ToolResult, measurements: list) -> str:
    actual_failure = (not tool.native_steps or any(
        item.get("exit_code") and item.get("status") != "NOT_MEASURED" for item in tool.native_steps))
    if tool.ran and tool.exit_code and actual_failure:
        return "FAIL"
    if not tool.ran:
        return "NOT_MEASURED"
    if any(item.get("status") == "FAIL" for item in tool.native_steps):
        return "FAIL"
    if any(item["status"] == "FAIL" for item in measurements):
        return "FAIL"
    if any((not item["ran"] or item.get("status") == "NOT_MEASURED")
           and not item.get("native_config_disabled") for item in tool.native_steps):
        return "NOT_MEASURED"
    if any(item["status"] == "NOT_MEASURED" for item in measurements):
        return "NOT_MEASURED"
    if not measurements and tool.exit_code is None and not any(
            item.get("status") == "PASS" or item.get("exit_code") == 0 for item in tool.native_steps):
        return "NOT_MEASURED"
    return "PASS"


def finish_step(project, row, tool, native, config, features, *, elapsed, started_at,
                saved=None, retained=False, extra_tool_seconds=0.0, preparation=None,
                previous=None, execution=None):
    finishing = time.perf_counter()
    directory = project / "steps" / row["name"]
    kind = tool["kind"]
    saved, previous, execution = saved or {}, previous or {}, execution or {}
    preparation = preparation or ToolResult()
    if preparation.native_steps:
        native.ran = native.ran or preparation.ran
        native.tool_seconds += preparation.tool_seconds
        extra_tool_seconds += preparation.tool_seconds
        native.native_steps = preparation.native_steps + native.native_steps
        native.reports.extend(preparation.reports)
        if preparation.exit_code:
            native.exit_code = preparation.exit_code
    for reader in tool.get("report_readers", []):
        module, function = reader["reader"].rsplit(".", 1)
        source = directory / reader["native_step"].lower().replace(".", "_")
        report = getattr(importlib.import_module(module), function)(
            source, read_json(source / "config.json") or config)
        native.metrics.update(report.get("metrics", {}))
        native.reports.extend(report.get("reports", []))
        native.detail += " " + report.get("detail", "")
    checks = [check for check in row["checks"] if check.get("when") != "otherwise"
              or tool.get("selected_profile", "otherwise") == "otherwise"]
    for reader in tool.get("check_readers", []):
        module, function = reader.rsplit(".", 1)
        checks.extend(getattr(importlib.import_module(module), function)(project))
    observations, declared_checks = report_observations(row, directory, native, config, features, project)
    checks.extend(declared_checks)
    if "Checker.SetupViolations" in tool.get("steps", []):
        from flow_native_adapters import declared_electrical_checks
        checks = [*checks, *declared_electrical_checks(project)]
    observed = measure(checks, native.metrics, config, features, project)
    elapsed += time.perf_counter() - finishing
    status = evaluate(native, observed)
    if (kind == "native_report" and not observed
            and (not preparation.native_steps or evaluate(preparation, []) == "PASS")):
        status = previous.get("status", "NOT_MEASURED")
    result = {"name": row["name"], "title": row["title"], "status": status,
              "tool_ran": native.ran,
              "tool_exit_code": native.exit_code, "metrics": observed,
              "native_metrics": native.metrics, "native_steps": native.native_steps,
              "observations": observations,
              "reports": native.reports, "detail": native.detail,
              "tool_seconds": native.tool_seconds,
              "program_seconds": (saved["program_seconds"] if retained else 0) + max(0, elapsed - (extra_tool_seconds if retained else native.tool_seconds)),
              "ai_seconds": saved.get("ai_seconds") if retained else None,
              "ai_review": saved.get("ai_review", "PENDING") if retained else "PENDING",
              "wall_seconds": (saved["wall_seconds"] if retained else 0) + elapsed,
              "started_at": saved.get("started_at", started_at) if retained else execution.get("started_at", started_at),
              "completed_at": saved.get("completed_at", time.time()) if retained else execution.get("completed_at", time.time()),
              "tool_kind": kind, "retained": retained}
    complete_timing = execution.get("timing_complete", True)
    result.update(timing_group=tool.get("timing_group", previous.get("timing_group", "other")
                  if kind == "native_report" else "librelane" if kind == "librelane" else "other"),
                  timing_complete=complete_timing, queue_seconds=execution.get("queue_seconds", 0))
    if not complete_timing:
        result.update(program_seconds=0.0, unclassified_seconds=max(0, elapsed - native.tool_seconds),
                      tool_timing="NOT_MEASURED")
    for key in ("ai_finding", "reviewed_at"):
        if retained and key in saved:
            result[key] = saved[key]
    if not native.ran:
        result.update(ai_seconds=0.0, ai_review="NO_NATIVE_RESULT")
    elif kind == "native_report":
        result.update(ai_seconds=0.0, ai_review="REUSES_PRODUCER_REVIEW", review_from=tool["from"])
    return result


def keep_author_failure(directory: Path) -> None:
    if read_json(directory / "result.json").get("status") != "FAIL":
        return
    history = directory / "author_history"
    history.mkdir(exist_ok=True)
    destination = history / f"{len(list(history.iterdir())) + 1:06d}"
    destination.mkdir()
    for source in directory.iterdir():
        if source.is_file():
            shutil.copyfile(source, destination / source.name)


def run(project: Path | str, *, table: dict | None = None, route: dict | None = None,
        from_name: str | None = None, to_name: str | None = None,
        budget_seconds: float | None = None, pdk: str | None = None) -> dict:
    project = Path(project).resolve()
    table = table or read_json(TABLE)
    route = route or select_route(project)
    from flow_engine_frontend import OwnerSession
    owner_route = route
    if from_name and route.get("input_contract") == "original":
        requested = next(row for row in table["steps"] if row["name"] == from_name)
        mapped = requested.get("legacy_id", {})
        if isinstance(mapped, dict) and mapped.get("native"):
            owner_route = {**route, "entry_step": mapped["native"][0]}
    owner_session = OwnerSession(project, owner_route, force=bool(from_name), table=table)
    prepared = {}
    entry_rows = [row for row in table["steps"]
                  if str(route["entry_step"]) in [row["name"], *aliases(row)]]
    if len(entry_rows) == 1:
        entry = entry_rows[0]
        tool = entry["tool"]
        if (from_name in (None, entry["name"]) and tool.get("function") == "doc_extract"
                and tool.get("program") == "phase1_one_shot_runner.py"
                and (from_name == entry["name"]
                     or not (project / "reports/orchestrator/phase1_one_shot.json").is_file())):
            before = time.perf_counter()
            directory = project / "steps" / entry["name"]
            prepared[entry["name"]] = (ToolResult(**owner_session.result(directory, "phase1")),
                                        time.perf_counter() - before)
    features = design_features(project, route, table)
    selected = select_steps(table, route, features, from_name, to_name)
    complete_selection = select_steps(table, route, features, None, None)
    chain = NativeChain(project, route, pdk=pdk)
    positions = {row["name"]: i + 1 for i, row in enumerate(table["steps"])}
    results: dict[str, dict] = {}
    step_root = project / "steps"
    step_root.mkdir(parents=True, exist_ok=True)
    restore_directory = None
    if from_name:
        first = positions[from_name]
        for row in table["steps"][first - 1:]:
            if row["tool"].get("function") == "step_rtl_gen":
                keep_author_failure(step_root / row["name"])
            for name in ("result.json", "state_out.json"):
                (step_root / row["name"] / name).unlink(missing_ok=True)
        for row in reversed(table["steps"][:first - 1]):
            directory = step_root / row["name"]
            if (directory / "state_out.json").is_file():
                restore_directory = directory
                break
    started = time.perf_counter()
    for row in selected:
        beginning, row_started_at = time.perf_counter(), time.time()
        preparation = ToolResult()
        if restore_directory is not None:
            if chain.prepare() is None:
                chain.restore(restore_directory)
            preparation = chain.preparation_result()
            restore_directory = None
        directory = step_root / row["name"]
        tool = choose_tool(row["tool"], features)
        if ((route.get("input_contract") == "original" or route["delivery_target"] == "rtl")
                and "Verilator.Lint" in tool.get("steps", [])):
            tool = {"kind": "adapter", "function": "rtl_validate"}
        kind = tool["kind"]
        saved = read_json(directory / "result.json")
        refresh_author = tool.get("function") == "step_rtl_gen"
        if refresh_author:
            keep_author_failure(directory)
        extra_tool_seconds = 0.0
        retained = bool(saved.get("tool_ran") and (
            kind in {"librelane", "command", "snapshot"}
            or kind == "adapter" and (
                tool.get("adapter") and any(isinstance(value, (int, float))
                                             for value in saved.get("native_metrics", {}).values())
                or tool.get("function") == "doc_extract"
                and any(item.get("ran") for item in saved.get("native_steps", [])))))
        if retained:
            native = ToolResult(True, saved["tool_exit_code"], saved.get("native_metrics", {}),
                                saved.get("reports", []), saved["tool_seconds"], saved.get("detail", ""),
                                saved.get("native_steps", []))
            for item in native.native_steps:
                if "NOT_MEASURED" in item.get("detail", ""):
                    item["status"] = "NOT_MEASURED"
            if kind == "librelane":
                error = chain.prepare()
                initialized = chain.preparation_result()
                native.tool_seconds += initialized.tool_seconds
                extra_tool_seconds += initialized.tool_seconds
                native.native_steps.extend(initialized.native_steps)
                native.reports.extend(initialized.reports)
                if initialized.exit_code:
                    native.exit_code = initialized.exit_code
                if error is None:
                    chain.restore(directory)
                completed = {item["name"] for item in native.native_steps}
                additional = [name for name in tool["steps"] if name not in completed]
                if additional and error is None:
                    added = chain.execute(directory, {**tool, "steps": additional})
                    native.metrics.update(added.metrics)
                    native.native_steps.extend(added.native_steps)
                    native.reports = added.reports
                    native.tool_seconds += added.tool_seconds
                    extra_tool_seconds += added.tool_seconds
                    if added.exit_code:
                        native.exit_code = added.exit_code
        else:
            if directory.exists() and row["name"] not in prepared and not refresh_author:
                shutil.rmtree(directory)
            directory.mkdir(exist_ok=True)
        if retained:
            pass
        elif row["name"] in prepared:
            native = prepared[row["name"]][0]
        elif tool.get("function") == "step_rtl_gen":
            native = ToolResult(**owner_session.result(directory, "rtl_gen"))
        elif tool.get("function") == "rtl_validate":
            native = ToolResult(**owner_session.result(directory, "rtl_validate"))
        elif kind == "command":
            native = command_tool(project, directory, tool)
        elif kind == "librelane":
            native = chain.execute(directory, tool)
        elif kind == "snapshot":
            native = chain.snapshot(directory, tool)
        elif kind == "aggregate":
            earlier = [item for item in complete_selection
                       if positions[item["name"]] < positions[row["name"]]]
            statuses = {item["name"]: read_json(step_root / item["name"] / "result.json").get("status", "NOT_MEASURED")
                        for item in earlier}
            report_path = directory / "aggregate.json"
            write_json(report_path, statuses)
            native = ToolResult(True, 0, {"non_passing_steps": sum(value != "PASS" for value in statuses.values())},
                                [str(report_path)])
        elif kind == "native_report":
            previous = results.get(tool["from"]) or read_json(step_root / tool["from"] / "result.json")
            native = ToolResult(bool(previous.get("tool_ran")), None,
                                previous.get("native_metrics", {}), previous.get("reports", []),
                                detail=f"Native reports from {tool['from']}")
        elif kind == "adapter" and tool.get("adapter"):
            from flow_native_adapters import execute
            native = ToolResult(**execute(project, directory, tool, route, state=chain.state, config=chain.config))
        elif kind == "adapter" and tool.get("function") == "doc_extract":
            native = ToolResult(**owner_session.result(directory, "phase1"))
        else:
            native = ToolResult(detail=tool.get("gap", "Native adapter is not available"))
        result = finish_step(project, row, tool, native, chain.config, features,
            elapsed=time.perf_counter() - beginning + prepared.get(row["name"], (None, 0))[1],
            started_at=row_started_at, saved=saved, retained=retained,
            extra_tool_seconds=extra_tool_seconds, preparation=preparation,
            previous=previous if kind == "native_report" else None)
        write_json(directory / "result.json", result)
        results[row["name"]] = result
        results = {name: read_json(step_root / name / "result.json") for name in results}
        print(f"第 {positions[row['name']]} 步 {row['title']}: {result['status']}", flush=True)
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
    result.setdefault("completed_at", path.stat().st_mtime)
    result.update(ai_seconds=(result.get("ai_seconds") or 0) + seconds,
                  ai_review="FINDING" if finding else "REVIEWED",
                  ai_finding=finding, reviewed_at=time.time())
    write_json(path, result)


def refresh_report(project: Path, budget_seconds: float | None = None) -> dict:
    path = project / "reports/flow_engine.json"
    report = read_json(path)
    rows = [read_json(project / "steps" / row["name"] / "result.json") for row in report["steps"]]
    report.update(steps=rows, run=len(rows),
                  **{status: sum(row["status"] == value for row in rows)
                     for status, value in (("pass", "PASS"), ("fail", "FAIL"), ("not_measured", "NOT_MEASURED"))})
    for metric in ("tool_seconds", "program_seconds"):
        report[metric] = sum(row[metric] for row in rows)
    report["ai_seconds"] = (sum(row["ai_seconds"] for row in rows)
                            if all(row.get("ai_seconds") is not None for row in rows) else None)
    report["ai_measured_seconds"] = sum(row.get("ai_seconds") or 0 for row in rows)
    report["ai_unmeasured_steps"] = [row["name"] for row in rows if row.get("ai_seconds") is None]
    native_starts, native_ends = [], []
    for row in rows:
        for native in row.get("native_steps", []):
            directory = Path(native.get("reports", ""))
            config = directory / "config.json"
            if native["name"] in {"Yosys.Synthesis", "Pyosys.Synthesis"} and config.is_file():
                native_starts.append(config.stat().st_mtime)
            runtime = directory / "runtime.txt"
            if runtime.is_file():
                native_ends.append(runtime.stat().st_mtime)
        if row.get("reviewed_at") is not None and row["tool_kind"] in {"librelane", "native_report"}:
            native_ends.append(row["reviewed_at"])
    report["common_wall_seconds"] = max(native_ends) - min(native_starts) if native_starts and native_ends else None
    report["timing_reference"] = "Native synthesis config publication through native completion and concurrent review completion"
    budget = budget_seconds if budget_seconds is not None else report.get("budget_seconds")
    report["budget_seconds"] = budget
    elapsed = report["common_wall_seconds"]
    report["runtime_status"] = ("OVER_BUDGET" if budget is not None and elapsed is not None and elapsed > budget
                                else "IN_BUDGET" if budget is not None and elapsed is not None else "NOT_MEASURED")
    report["slowest_steps"] = [row["name"] for row in sorted(rows, key=lambda row: row["tool_seconds"], reverse=True)[:5]]
    write_json(path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("run")
    command.add_argument("--project", type=Path, required=True)
    command.add_argument("--from", dest="from_name")
    command.add_argument("--to", dest="to_name")
    command.add_argument("--budget-seconds", type=float)
    command.add_argument("--pdk")
    review = sub.add_parser("review")
    review.add_argument("--project", type=Path, required=True)
    review.add_argument("--step", required=True)
    review.add_argument("--seconds", type=float, required=True)
    review.add_argument("--finding")
    report = sub.add_parser("report")
    report.add_argument("--project", type=Path, required=True)
    report.add_argument("--budget-seconds", type=float)
    args = parser.parse_args()
    try:
        if args.action == "review":
            record_review(args.project, args.step, args.seconds, args.finding)
            return 0
        if args.action == "report":
            print(json.dumps(refresh_report(args.project, args.budget_seconds), default=str))
            return 0
        result = run(args.project, from_name=args.from_name, to_name=args.to_name,
                     budget_seconds=args.budget_seconds, pdk=args.pdk)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"NOT_MEASURED: {exc}", file=sys.stderr)
        return 2
    return 1 if result.get("fail") else 2 if result.get("not_measured") else 0


if __name__ == "__main__":
    raise SystemExit(main())
