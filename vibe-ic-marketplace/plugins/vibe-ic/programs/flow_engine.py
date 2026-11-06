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
import vibeic_temp

from flow_engine_timing import timing_summary

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


def design_features(project: Path, route: dict, table: dict, *, sources: dict | None = None) -> dict:
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
    sources = sources if sources is not None else {}
    sources.update({key: "No structured Phase 1 declaration; defaults to false." for key in names})
    sources.update({key: f"Router delivery_target={target}" for key in
                    ("ic", "hard_ip", "soft_ip", "model_ip", "rtl_only")})
    sources.update(always="Step-table constant", has_digital="Digital task entry; pure-analog classification can disable it.")
    explicit, layers = set(), {}
    for path in sorted(docs.glob("L*.json")):
        document = read_json(path)
        layers.setdefault(path.stem.split("_", 1)[0],
                          (document["fields"] if isinstance(document.get("fields"), dict) else document,
                           str(path.relative_to(project)),
                           "fields/" if isinstance(document.get("fields"), dict) else ""))
        for prefix, container in (("", document), ("fields/", document.get("fields", {})),
                                  ("features/", document.get("features", {}))):
            if not isinstance(container, dict):
                continue
            declared = {key: value for key, value in container.items()
                        if key in names and type(value) is bool}
            features.update(declared)
            explicit.update(declared)
            sources.update({key: str(path.relative_to(project)) + "#/" + prefix + key for key in declared})

    def present(value):
        return (value is True or isinstance(value, (list, dict)) and bool(value)
                or type(value) in (int, float)
                or isinstance(value, str) and value.strip().upper() not in {
                    "", "NONE", "NULL", "N/A", "FALSE", "NO", "UNKNOWN",
                    "NOT_APPLICABLE", "NOT_DETERMINED", "NOT_STATED", "NOT_YET_EXTRACTED"})

    def observe(name, layer, *fields):
        payload, path, prefix = layers.get(layer, ({}, layer + " (absent)", ""))
        if name not in explicit and not features.get(name):
            sources[name] = "No positive declaration in " + path + "#/" + prefix + ",".join(fields)
        for field in fields:
            if name not in explicit and present(payload.get(field)):
                features[name] = True
                sources[name] = path + "#/" + prefix + field

    profile = read_json(project / "reports/ic_class.json")
    if "has_analog" not in explicit and type(profile.get("has_analog")) is bool:
        features["has_analog"] = profile["has_analog"]
        sources["has_analog"] = "reports/ic_class.json#/has_analog"
    elif "has_analog" not in explicit:
        observe("has_analog", "L5", "analog_blocks_detected")
    if "has_digital" not in explicit and profile.get("is_pure_analog") is True:
        features["has_digital"] = bool(profile.get("is_data_converter") or profile.get("is_mixed_signal"))
        sources["has_digital"] = "reports/ic_class.json#/is_pure_analog,is_data_converter,is_mixed_signal"
    observe("has_power_intent", "L21", "power_intent_present", "power_domains", "upf_path",
            "isolation_cells", "level_shifters")
    observe("requires_scan", "L20", "scan_required", "scan_chains")
    observe("requires_dft", "L20", "dft_present", "scan_chains", "bist_mbist", "jtag_tap", "test_compression")
    if layers.get("L20", ({}, ""))[0].get("dft_intent_status") == "PLANNED_UNMEASURED":
        observe("requires_dft", "L20", "dft_intent_status")
    observe("requires_security", "L23", "security_requirements_present", "secure_boot",
            "key_handling", "attack_surface", "side_channel_mitigation")
    observe("uses_macros", "L9", "hard_macros", "macro_instances", "macros")
    observe("uses_macros", "L21", "hard_macro_supplies")
    observe("multidie", "L18", "dies", "chiplets")
    observe("package_model_required", "L1", "package_model")
    package = layers.get("L1", ({}, ""))[0].get("package_info")
    if isinstance(package, dict) and present(package.get("package_type")):
        observe("package_declared", "L1", "package_info")
        observe("package_interface", "L1", "package_info")
        observe("package_model_required", "L1", "package_info")
    elif not features.get("package_model_required") and "package_model_required" not in explicit:
        sources["package_model_required"] = "No declared package type or model in L1 package_info/package_type or package_model."
    observe("requires_aging", "L25", "aging_margin")
    observe("requires_em", "L25", "em_budget")
    observe("requires_system_scenarios", "L22", "system_scenarios")
    for item in layers.get("L24", ({}, ""))[0].get("signoff_requirements", []):
        name = {"IR_drop": "requires_ir", "EM": "requires_em", "SI": "requires_si"}.get(item.get("check"))
        if name and item.get("stated") is True:
            observe(name, "L24", "signoff_requirements")
    for item in layers.get("L25", ({}, ""))[0].get("unmeasured_obligations", []):
        name = {"aging": "requires_aging", "EM": "requires_em", "ESD": "requires_perc"}.get(item.get("subject"))
        if name:
            observe(name, "L25", "unmeasured_obligations")
    features.update(ic=target in {"gds", "shippable_gds", "foundry_handoff"},
                    hard_ip=target == "ip_hardmacro", rtl_only=target == "rtl")
    if "requires_cts" not in explicit:
        features["requires_cts"] = bool(
            (features["ic"] or features["hard_ip"] or features.get("assembly_only"))
            and (read_json(docs / "L8_TIMING_WAVEFORM.json").get("clock_domains")
                 or read_json(docs / "L8_RTL_CONSTANTS.json").get("clock_domains")))
        if features["requires_cts"]:
            sources["requires_cts"] = "L8 timing/RTL constants #/clock_domains"
    pending = dict(table.get("predicates", {}))
    for _ in range(len(pending) + 1):
        for key, expression in pending.items():
            features[key] = predicate(expression, features)
            sources[key] = "Derived from " + expression
        for source, implied in table.get("implications", {}).items():
            if features.get(source):
                for key in implied:
                    if not features.get(key):
                        sources[key] = "Implied by " + source + ": " + sources.get(source, "")
                    features[key] = True
        for key, default in table.get("feature_defaults", {}).items():
            if key not in explicit and predicate(default["when"], features):
                if features[key] != default["value"]:
                    sources[key] = "Native tool default: " + json.dumps(default.get("source", {}))
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
        self.preparation_runs: list[dict] = []
        self.preparation_accounted = 0
        self.initialization_error: Exception | None = None
        self.synthesis_fixed = False

    def observe_preparation(self, run):
        self.preparation_runs.append(run)

    def initialize(self):
        if self.initialization_error is not None:
            raise self.initialization_error
        if self.owner is not None:
            return
        from flow_config import build_native_config as build_config, native_defaults
        from librelane.flows import Flow
        from librelane.state import State
        from librelane.common import Toolbox
        kind = "Chip" if self.route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"} else "Classic"
        config = build_config(self.project, route="ic" if kind == "Chip" else "ip",
                              **({"pdk": self.pdk} if self.pdk else {}),
                              **({"on_tool_run": self.observe_preparation} if kind == "Chip" else {}))
        self.synthesis_fixed = "SYNTH_STRATEGY" in config
        os.environ["_OPENLANE_MAX_CORES"] = "8"
        self.owner = Flow.factory.get(kind)(config, design_dir=str(self.project),
                                            pdk_root=os.environ.get("PDK_ROOT"))
        self.toolbox = Toolbox(str(vibeic_temp.current_run() / "tool_tmp"))
        self.owner.config = native_defaults(self.owner.config)
        self.config = self.owner.config.to_raw_dict()
        self.state = State()

    def prepare(self, *, floorplan=False, synthesis=False, directory=None):
        try:
            self.initialize()
            if synthesis and not self.synthesis_fixed:
                from flow_config import explore_synthesis
                strategy = explore_synthesis(self.owner.config, self.state,
                    directory / "synthesis_exploration", self.observe_preparation)
                if strategy is not None:
                    self.owner.config = self.owner.config.copy(SYNTH_STRATEGY=strategy)
                    self.config = self.owner.config.to_raw_dict()
            if floorplan:
                from flow_pdn_current import current_settings
                from flow_config import _native_pdn_numbers
                extent = self.config.get("DIE_AREA") or self.config.get("CORE_AREA")
                span = (max(float(extent[2]) - float(extent[0]), float(extent[3]) - float(extent[1]))
                        if extent else None)
                settings = current_settings(self.project, self.config, parallel_length_um=span)
                if directory is not None and self.route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"}:
                    from flow_chip_inputs import netlist_area, sized_floorplan
                    area = netlist_area(self.owner.config, self.state, self.toolbox,
                                        directory / "openroad_area", self.observe_preparation)
                    if area is None:
                        raise FileNotFoundError("OpenROAD left no current-netlist area")
                    settings.update(sized_floorplan(self.project, self.config, settings, float(area)))
                self.owner.config = self.owner.config.copy(**_native_pdn_numbers(settings))
                self.config = self.owner.config.to_raw_dict()
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
            geometry = {key: [float(value) for value in bounds.split()] if isinstance(bounds, str) else bounds
                for metric, key in (("design__die__bbox", "DIE_AREA"), ("design__core__bbox", "CORE_AREA"))
                if (bounds := restored.metrics.get(metric)) is not None}
            if geometry and self.owner is not None:
                self.owner.config = self.owner.config.copy(**geometry)
                self.config = self.owner.config.to_raw_dict()

    def execute(self, directory: Path, tool: dict) -> ToolResult:
        error = self.prepare(floorplan="OpenROAD.Floorplan" in tool.get("steps", []),
                             synthesis="Yosys.Synthesis" in tool.get("steps", []), directory=directory)
        result = self.preparation_result()
        if error is not None:
            return result
        from librelane.steps import Step, StepError, StepException
        for module in tool.get("imports", []):
            importlib.import_module(module)
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
            if (metric_name and any((not item["ran"] or item.get("exit_code"))
                    and not item.get("native_config_disabled") for item in result.native_steps)
                    and not any(key == metric_name or key.startswith(metric_name + "__corner:")
                                for key in result.metrics)):
                result.native_steps.append({"name": name, "ran": False, "exit_code": None,
                                            "status": "NOT_MEASURED", "missing_inputs": [metric_name]})
                continue
            if metric_name:
                result.metrics.update({key: value for key, value in self.state.metrics.items()
                                       if key == metric_name or key.startswith(metric_name + "__corner:")})
            destination = directory / name.lower().replace(".", "_")
            started = time.perf_counter()
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
            except (StepException, FileNotFoundError) as exc:
                code, ran, detail = None, False, str(exc)
                status = "NOT_MEASURED"
            except StepError as exc:
                underlying = getattr(exc, "underlying_error", None)
                code = getattr(underlying, "returncode", 1) or 1
                detail = str(exc)
                status = "NOT_MEASURED" if "NOT_MEASURED" in detail else "FAIL"
            if code or not ran:
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
            if name == "lib" and self.state.get("def"):
                from digital_hardmacro_gen import liberty_with_pg_pins, read_interface
                from hardmacro_supply_intent import liberty_pg_pins
                library = destination / (self.config["DESIGN_NAME"] + extension)
                text = library.read_text()
                if not liberty_pg_pins(text):
                    pins = read_interface(Path(str(self.state["def"])).read_text())
                    exported_library = liberty_with_pg_pins(text, self.config["DESIGN_NAME"], pins)
                    if exported_library is not None:
                        library.write_text(exported_library)
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
        if check.get("limit_from", {}).get("kind") == "declared_analog_specs":
            from flow_native_analog import declared_spec_checks
            specs = declared_spec_checks(project, config=config, metrics=metrics)
            if specs:
                observed.extend({**check, **item} for item in specs)
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
            points = metrics.get(name.removesuffix("_pct") + "_points")
            if (re.fullmatch(r"coverage_(line|toggle|branch)_pct", name)
                    and type(points) is int and points == 0):
                observed.append({**check, "metric": name, "value": None, "limit": limit,
                    "status": "NOT_APPLICABLE", "points": points,
                    "reason": "A measured category with zero coverage points has no percentage floor."})
                continue
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


def finish_step(project, row, tool, native, config, features, *, elapsed,
                preparation=None,
                previous=None):
    finishing = time.perf_counter()
    directory = project / "steps" / row["name"]
    kind = tool["kind"]
    previous = previous or {}
    preparation = preparation or ToolResult()
    if preparation.native_steps:
        native.ran = native.ran or preparation.ran
        native.tool_seconds += preparation.tool_seconds
        native.native_steps = preparation.native_steps + native.native_steps
        native.reports.extend(preparation.reports)
        if preparation.exit_code:
            native.exit_code = preparation.exit_code
    reader_observations = []
    for reader in tool.get("report_readers", []):
        module, function = reader["reader"].rsplit(".", 1)
        source = directory / reader["native_step"].lower().replace(".", "_")
        report = getattr(importlib.import_module(module), function)(
            source, read_json(source / "config.json") or config, project=project)
        native.metrics.update(report.get("metrics", {}))
        native.reports.extend(report.get("reports", []))
        native.detail += " " + report.get("detail", "")
        reader_observations.extend(report.get("observations", []))
        native.tool_seconds += report.get("tool_seconds", 0)
        native.native_steps.extend(report.get("native_steps", []))
    checks = [check for check in row["checks"] if check.get("when") != "otherwise"
              or tool.get("selected_profile", "otherwise") == "otherwise"]
    for reader in tool.get("check_readers", []):
        module, function = reader.rsplit(".", 1)
        for check in getattr(importlib.import_module(module), function)(project, config=config, metrics=native.metrics):
            if check.get("applicable") is False:
                reader_observations.append({**check, "status": "NOT_APPLICABLE"})
            else:
                checks.append(check)
    observations, declared_checks = report_observations(row, directory, native, config, features, project)
    observations.extend(reader_observations)
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
              "program_seconds": max(0, elapsed - native.tool_seconds),
              "ai_seconds": None,
              "ai_review": "PENDING",
              "wall_seconds": elapsed,
              "tool_kind": kind}
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
        pdk: str | None = None, keep_temp: bool = False) -> dict:
    project = Path(project).resolve()
    with vibeic_temp.execution("flow", project.name, keep=keep_temp,
                               destination=project / "reports/native") as work:
        try:
            result = _run(project, table=table, route=route,
                          from_name=from_name, to_name=to_name, pdk=pdk)
        finally:
            if work.publish() is not None:
                paths = [path for folder in ("steps", "reports", "phase1", "phase2", "phase3")
                         for path in (project / folder).glob("**/*.json")]
                for path in paths:
                    try:
                        before = read_json(path)
                    except (ValueError, OSError):
                        continue
                    after = vibeic_temp.relocate(before, work.mapping)
                    if after != before:
                        write_json(path, after)
        return vibeic_temp.relocate(result, work.mapping)


def _run(project: Path | str, *, table: dict | None = None, route: dict | None = None,
        from_name: str | None = None, to_name: str | None = None,
        pdk: str | None = None) -> dict:
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
    owner_session = OwnerSession(project, owner_route, force=True, table=table)
    prepared = {}
    entry_rows = [row for row in table["steps"]
                  if str(route["entry_step"]) in [row["name"], *aliases(row)]]
    if len(entry_rows) == 1:
        entry = entry_rows[0]
        tool = entry["tool"]
        if (from_name in (None, entry["name"]) and tool.get("function") == "doc_extract"
                and tool.get("program") == "phase1_one_shot_runner.py"):
            before = time.perf_counter()
            directory = project / "steps" / entry["name"]
            prepared[entry["name"]] = (ToolResult(**owner_session.result(directory, "phase1")),
                                        time.perf_counter() - before)
    feature_sources = {}
    features = design_features(project, route, table, sources=feature_sources)
    selected = select_steps(table, route, features, from_name, to_name)
    complete_selection = select_steps(table, route, features, None, None)
    chain = NativeChain(project, route, pdk=pdk)
    positions = {row["name"]: i + 1 for i, row in enumerate(table["steps"])}
    results: dict[str, dict] = {}
    step_root = project / "steps"
    step_root.mkdir(parents=True, exist_ok=True)
    restore_directory = None
    first = positions[from_name] if from_name else 1
    last = positions[to_name] if from_name and to_name else len(table["steps"])
    for row in table["steps"][first - 1:last]:
        if row["tool"].get("function") == "step_rtl_gen":
            keep_author_failure(step_root / row["name"])
        for name in ("result.json", "state_out.json"):
            (step_root / row["name"] / name).unlink(missing_ok=True)
    if from_name:
        for row in reversed(table["steps"][:first - 1]):
            directory = step_root / row["name"]
            if (directory / "state_out.json").is_file():
                restore_directory = directory
                break
    tools = {row["name"]: choose_tool(row["tool"], features) for row in selected}
    for name, tool in tools.items():
        if ((route.get("input_contract") == "original" or route["delivery_target"] == "rtl")
                and "Verilator.Lint" in tool.get("steps", [])):
            tools[name] = {"kind": "adapter", "function": "rtl_validate"}
    selected_names = set(tools)
    replayed_aggregates = [row for row in complete_selection if from_name and to_name
        and positions[row["name"]] > positions[to_name]
        and choose_tool(row["tool"], features)["kind"] == "aggregate"
        and (step_root / row["name"] / "result.json").is_file()]
    deferred, summary = [], {}

    def write_summary():
        nonlocal summary
        rows = [read_json(step_root / name / "result.json") for name in sorted(results, key=positions.get)]
        summary = {"route": route, "features": features, "feature_sources": feature_sources,
                   "selected": len(selected), "selected_names": [row["name"] for row in selected],
                   "not_selected": [{"name": row["name"], "condition": row["when"],
                       "features": {node.id: features[node.id] for node in ast.walk(ast.parse(row["when"], mode="eval")) if isinstance(node, ast.Name)},
                       "feature_sources": {node.id: feature_sources[node.id] for node in ast.walk(ast.parse(row["when"], mode="eval")) if isinstance(node, ast.Name)},
                       "reason": row.get("applicability_reason")} for row in table["steps"] if row["name"] not in selected_names],
                   "run": len(rows), "steps": rows,
                   **{key: sum(item["status"] == value for item in rows)
                      for key, value in (("pass", "PASS"), ("fail", "FAIL"), ("not_measured", "NOT_MEASURED"))},
                   }
        summary.update(timing_summary(summary))
        write_json(project / "reports/flow_engine.json", summary)
        return summary

    def publish(context, native):
        row, tool = context["row"], context["tool"]
        result = finish_step(project, row, tool, native, context["config"], features,
            elapsed=context["elapsed"],
            preparation=context["preparation"], previous=context.get("previous"))
        write_json(step_root / row["name"] / "result.json", result)
        if row["name"] in selected_names:
            results[row["name"]] = result
        print(f"第 {positions[row['name']]} 步 {row['title']}: {result['status']}", flush=True)
        write_summary()

    def previous_result(tool):
        return read_json(step_root / tool["from"] / "result.json")

    def reused_report(tool, previous):
        return ToolResult(bool(previous.get("tool_ran")), None, previous.get("native_metrics", {}),
                          previous.get("reports", []), detail=f"Native reports from {tool['from']}")

    def ready_reports():
        while True:
            ready = [context for context in deferred if
                     (context["tool"]["kind"] == "native_report" and
                      (context["tool"]["from"] not in selected_names or context["tool"]["from"] in results))
                     or (context["tool"]["kind"] == "aggregate" and all(
                         item["name"] in results for item in selected
                         if positions[item["name"]] < positions[context["row"]["name"]]))]
            if not ready:
                return
            for context in ready:
                deferred.remove(context)
                beginning = time.perf_counter()
                row, tool = context["row"], context["tool"]
                if tool["kind"] == "native_report":
                    context["previous"] = previous_result(tool)
                    native = reused_report(tool, context["previous"])
                else:
                    earlier = [item for item in complete_selection
                               if positions[item["name"]] < positions[row["name"]]]
                    statuses = {item["name"]: read_json(step_root / item["name"] / "result.json").get("status", "NOT_MEASURED")
                                for item in earlier}
                    path = step_root / row["name"] / "aggregate.json"
                    write_json(path, statuses)
                    native = ToolResult(True, 0, {"non_passing_steps": sum(value != "PASS" for value in statuses.values())}, [str(path)])
                context.update(config=chain.config, elapsed=context["elapsed"] + time.perf_counter() - beginning)
                publish(context, native)

    for row in [*selected, *replayed_aggregates]:
        ready_reports()
        beginning = time.perf_counter()
        preparation = ToolResult()
        if restore_directory is not None:
            if chain.prepare() is None:
                chain.restore(restore_directory)
                if first > positions.get("die_floorplan_and_macros", first):
                    chain.prepare(floorplan=True)
            preparation = chain.preparation_result()
            restore_directory = None
        directory = step_root / row["name"]
        tool = tools.get(row["name"]) or choose_tool(row["tool"], features)
        kind = tool["kind"]
        refresh_author = tool.get("function") == "step_rtl_gen"
        if refresh_author:
            keep_author_failure(directory)
        if directory.exists() and row["name"] in selected_names and row["name"] not in prepared and not refresh_author:
            shutil.rmtree(directory)
        directory.mkdir(exist_ok=True)
        context = {"row": row, "tool": tool, "preparation": preparation,
                   "config": chain.config,
                   "elapsed": time.perf_counter() - beginning + prepared.get(row["name"], (None, 0))[1]}
        if kind in {"aggregate", "native_report"}:
            if kind == "aggregate" or tool["from"] in selected_names and tool["from"] not in results:
                deferred.append(context)
                continue
        if row["name"] in prepared:
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
        elif kind == "native_report":
            context["previous"] = previous_result(tool)
            native = reused_report(tool, context["previous"])
        elif kind == "adapter" and tool.get("adapter"):
            from flow_native_adapters import execute
            native = ToolResult(**execute(project, directory, tool, route, state=chain.state, config=chain.config))
        elif kind == "adapter" and tool.get("function") == "doc_extract":
            native = ToolResult(**owner_session.result(directory, "phase1"))
        else:
            native = ToolResult(detail=tool.get("gap", "Native adapter is not available"))
        context.update(config=chain.config, elapsed=time.perf_counter() - beginning + prepared.get(row["name"], (None, 0))[1])
        publish(context, native)
    ready_reports()
    return write_summary()


def record_review(project: Path, name: str, seconds: float, finding: str | None = None) -> None:
    """Record a timed concurrent expert reading without changing native verdicts."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Review duration must be measured nonnegative seconds")
    path = project / "steps" / name / "result.json"
    result = read_json(path)
    if not result:
        raise FileNotFoundError(path)
    result.update(ai_seconds=(result.get("ai_seconds") or 0) + seconds,
                  ai_review="FINDING" if finding else "REVIEWED",
                  ai_finding=finding)
    write_json(path, result)


def refresh_report(project: Path) -> dict:
    path = project / "reports/flow_engine.json"
    report = read_json(path)
    names = report.get("selected_names", [row["name"] for row in report["steps"]])
    rows = [read_json(project / "steps" / name / "result.json") for name in names]
    rows = [row for row in rows if row]
    report.update(steps=rows, run=len(rows),
                  **{key: sum(row["status"] == value for row in rows)
                     for key, value in (("pass", "PASS"), ("fail", "FAIL"), ("not_measured", "NOT_MEASURED"))})
    report.update(timing_summary(report))
    report["slowest_steps"] = [row["name"] for row in sorted(rows, key=lambda row: row.get("tool_seconds", 0), reverse=True)[:5]]
    write_json(path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("run")
    command.add_argument("--project", type=Path, required=True)
    command.add_argument("--from", dest="from_name")
    command.add_argument("--to", dest="to_name")
    command.add_argument("--pdk")
    command.add_argument("--keep-temp", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("--project", type=Path, required=True)
    review.add_argument("--step", required=True)
    review.add_argument("--seconds", type=float, required=True)
    review.add_argument("--finding")
    report = sub.add_parser("report")
    report.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "review":
            record_review(args.project, args.step, args.seconds, args.finding)
            return 0
        if args.action == "report":
            print(json.dumps(refresh_report(args.project), default=str))
            return 0
        result = run(args.project, from_name=args.from_name, to_name=args.to_name, pdk=args.pdk, keep_temp=args.keep_temp)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"NOT_MEASURED: {exc}", file=sys.stderr)
        return 2
    return 1 if result.get("fail") else 2 if result.get("not_measured") else 0


if __name__ == "__main__":
    raise SystemExit(main())
