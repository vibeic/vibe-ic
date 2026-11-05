"""D34 adapter for the existing special Default clock-plan producer.

This is intentionally not an ``execution_backend_producers`` row.  Native
step 16 is special-cased by the Phase-3 runner: ``emit_clock_plan`` drives the
current OpenROAD measurement, and the unchanged canonical row-16 consumer
runs ``clock_plan_check``.  This adapter only binds that real pair to D34 and
retains its identities; Flow109 and whole-flow acceptance remain unmeasured.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json

SCHEMA = "vibeic.flow109.clock-plan-component.v1"
OUTPUT = "phase3/stage3/cts/clock_plan.json"
NATIVE_STEP = "16"
STEP17_REUSE_ENV = "VIBEIC_FLOW109_STEP17_REUSE_REQUEST"

# D34 metric binding. The per-clock sink inventory is reconciled between two
# methods that share no code: the timing graph's propagation (OpenSTA, in the
# native plan) and a structural trace of the floorplan's NETS from each Liberty
# ff/latch clock pin back to a declared clock source, the latter adopted by the
# requirements owner. The pinned CTS takes no skew/insertion target, so the
# planning targets count as consumed only when the CTS row's acceptance
# authority is sourced from them; the built tree's skew and insertion delay
# remain D38's measurement, not this row's.
SINK_REFERENCE = "adopted/base_22/clock_sink_inventory.json"
SINK_SOURCE = "input/flow109/D34/clock_sink_inventory.json"
PLANNING_TARGETS = "input/flow109/D34/clock_planning_targets.json"
TARGET_BOUNDS = "requirements/base_22/skew_insertion_targets.json"
# Root ruling 2026-11-01 (option a): the planning targets are consumed when the
# CTS row's own acceptance authority is sourced from this exact targets file
# and holds its numbers as its limits. That binding, not a D38 PASS, is the
# consumption evidence; D38 still measures the built tree against it.
TARGET_CONSUMER = "requirements/base_25/clock_skew_insertion_drv.json"
TARGET_KEYS = ("clock_skew_ns", "insertion_delay_ns")
D34_SPECS = {
    "base_22.clock_sink_inventory": {"operator": "matches_adopted_reference",
                                     "reference_ref": SINK_REFERENCE},
    "base_22.skew_insertion_targets": {"operator": "within_declared_bounds",
                                       "bounds_ref": TARGET_BOUNDS + "#/limits",
                                       "unit_ref": TARGET_BOUNDS + "#/units"},
}
D34_PURPOSE = "D34.default.clock_sink_inventory"

# Only the reviewed 634 -> 805 Flow109 ownership work may differ while a
# retained Step-17 producer is adopted.  Everything that could have authored
# the old placement remains byte-identical or reuse refuses.
_REUSE_SOURCE_EXCEPTIONS = {
    "flow/FLOW109.md",
    "flow/flow109.json",
    "programs/flow109.py",
    "programs/flow109_clock_plan.py",
    "programs/flow109_final_lec.py",
    "programs/phase3_one_shot_runner.py",
    "programs/tests/test_flow109_clock_plan.py",
    "programs/tests/test_flow109_final_lec.py",
    "programs/tests/test_flow109_mixed_native_window.py",
    "programs/tests/test_flow109_selection.py",
    "programs/tests/test_flow109_window_continuation.py",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operation_sources() -> dict[str, str]:
    paths = (
        Path(__file__),
        HERE / "phase3_one_shot_runner.py",
        HERE / "_physical_current.py",
        HERE / "_path_layout.py",
        HERE / "clock_plan_check.py",
        HERE / "execution_backend_gates.py",
    )
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in paths}


def _inputs(project: Path) -> dict[str, dict[str, object]]:
    import _path_layout as layout

    paths = [project / "phase3/stage3/pnr/floorplan.def",
             project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"]
    paths.extend(layout.clock_plan_input_sdcs(project))
    result = {}
    for path in paths:
        path = Path(path)
        if path.is_file():
            result[str(path.resolve().relative_to(project))] = {
                "sha256": _sha(path), "bytes": path.stat().st_size}
    return result


def _consumer_row() -> dict:
    import execution_backend_gates as gates

    row = gates.canonical_family_row(NATIVE_STEP)
    if (not isinstance(row, dict)
            or row.get("required_outputs") != [OUTPUT]
            or gates.required_commands(row) != [
                "clock_plan_check . --json reports/phase2/gates/clock_plan.json"]):
        raise ValueError("D34_CLOCK_CONSUMER_UNREGISTERED")
    return row


def _step17_reuse_request(project: Path, component_attempt: Path,
                          context: dict) -> Path:
    """Seal an exact retained-placement request; never authorize by presence."""
    runtime = json.loads((project / "reports/orchestrator/runtime_program_tree.json").read_text())
    prior_root = Path(runtime["retained_plugin_root"])
    current_root = HERE.parent
    checked = {}
    for prior in sorted(prior_root.rglob("*")):
        if not prior.is_file() or prior.is_symlink():
            continue
        rel = str(prior.relative_to(prior_root))
        if rel in _REUSE_SOURCE_EXCEPTIONS:
            continue
        current = current_root / rel
        if current.is_symlink() or not current.is_file() or _sha(current) != _sha(prior):
            raise ValueError("D35_RETAINED_SOURCE_CHANGED: " + rel)
        checked[rel] = _sha(current)
    if not checked:
        raise ValueError("D35_RETAINED_SOURCE_CENSUS_EMPTY")

    import step_output_collector as versions
    retained = versions.latest_pass(project, "17")
    backend = project / "reports/phase3/default_steps/17/backend_result.json"
    placed = project / "phase3/stage3/pnr/placed.def"
    handoff = project / "reports/phase3/librelane_placement_handoff.json"
    if (not retained or retained.get("current_inputs") is not True
            or retained.get("canonical_pass") is not True
            or retained.get("status") != "PASS"):
        raise ValueError("D35_RETAINED_CURRENT_PASS_ABSENT")
    for path, reason in ((backend, "BACKEND"), (placed, "PLACED_DEF"),
                         (handoff, "NATIVE_HANDOFF")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("D35_RETAINED_" + reason + "_ABSENT")
    request = component_attempt / "step17_reuse_request.json"
    clock = json.loads((project / OUTPUT).read_text())
    clock_pdk = (clock.get("current") or {}).get("pdk")
    if not isinstance(clock_pdk, str) or not clock_pdk:
        raise ValueError("D35_RETAINED_CLOCK_PDK_ABSENT")
    write_json(request, {
        "schema": "vibeic.flow109.step17-reuse-request.v1",
        "context_sha256": context.get("context_sha256"),
        "source_census_count": len(checked),
        "source_census_sha256": hashlib.sha256(
            json.dumps(checked, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "retained_step_folder": retained.get("folder"),
        "backend_result_sha256": _sha(backend),
        "placed_def_sha256": _sha(placed),
        "native_handoff_sha256": _sha(handoff),
        "pdk": clock_pdk,
    })
    return request


def execute(project, context):
    project = Path(project).resolve()
    component_attempt = project / "reports/flow109/D34" / uuid.uuid4().hex
    component_attempt.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": SCHEMA,
        "step_id": "D34",
        "native_step_id": NATIVE_STEP,
        "component_status": "NOT_MEASURED",
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "native_started": False,
        "context_sha256": context.get("context_sha256"),
        "producer": "phase3_one_shot_runner.emit_clock_plan",
        "consumer": "clock_plan_check",
    }
    try:
        if (context.get("requested_step") != "D34"
                or context.get("native_step_id") != "flow109.D34"):
            raise ValueError("D34_CONTEXT_MISMATCH")
        row = _consumer_row()
        sources = operation_sources()
        inputs = _inputs(project)
        floorplan = project / "phase3/stage3/pnr/floorplan.def"
        pdk = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
        sdc_count = sum(path.endswith(".sdc") for path in inputs)
        if not floorplan.is_file():
            raise ValueError("D34_FLOORPLAN_ABSENT")
        if not pdk.is_file():
            raise ValueError("D34_PDK_DECLARATION_ABSENT")
        if not sdc_count:
            raise ValueError("D34_SDC_ABSENT")

        import step_output_collector as versions
        step_attempt = versions.begin_step(project, NATIVE_STEP, inputs)
        output = project / OUTPUT
        before = _sha(output) if output.is_file() else None
        import phase3_one_shot_runner as runner
        notes: list[str] = []
        with versions.active_steps(project, [step_attempt]):
            try:
                produced = runner.emit_clock_plan(
                    project, output, floorplan, floorplan.parent, notes)
                after = _sha(output) if output.is_file() else None
                record["native_started"] = bool(produced and after and after != before)
                record["producer_notes"] = notes
                record["inputs"] = inputs
                record["operation_sources"] = sources

                # Fail closed if current source or any producer input changed
                # across the native producer/consumer boundary.
                if operation_sources() != sources:
                    raise ValueError("D34_OPERATION_SOURCE_CHANGED")
                if _inputs(project) != inputs:
                    raise ValueError("D34_INPUT_CHANGED")

                versions.publish_producer_outputs(project, step_attempt)
                import execution_backend_gates as gates
                gate = gates.evaluate(project, row)
                record["consumer_result"] = gate
                if after:
                    record["outputs"] = {OUTPUT: after}
                    current = json.loads(output.read_text()).get("current", {})
                    record["native_execution"] = current.get("execution")
                else:
                    record["outputs"] = {}

                if gate.get("status") == "FAIL":
                    record.update(component_status="FAIL",
                                  reason="D34_CLOCK_PLAN_CONSUMER_FAILED")
                elif produced and after and gate.get("status") == "PASS":
                    record.update(component_status="PASS",
                                  reason=("D34_CURRENT_CLOCK_PLAN_PRODUCED"
                                          if record["native_started"] else
                                          "D34_CURRENT_CLOCK_PLAN_REUSED"))
                else:
                    record["reason"] = "D34_CLOCK_PLAN_NOT_MEASURED"
                parent_path = os.environ.get("VIBEIC_FLOW109_CONTEXT")
                try:
                    parent = json.loads(Path(parent_path).read_text()) if parent_path else {}
                except (OSError, ValueError, TypeError):
                    parent = {}
                if (record["component_status"] == "PASS"
                        and parent.get("schema") == "vibeic.flow109.execution-window.v1"
                        and parent.get("requested_entry") == "D34"
                        and parent.get("requested_exit") == "D35"
                        and parent.get("dispatch_kind") == "selected_native_sequence"):
                    request = _step17_reuse_request(project, component_attempt, context)
                    record["step17_reuse_request"] = {
                        "path": str(request.relative_to(project)), "sha256": _sha(request)}
                    os.environ[STEP17_REUSE_ENV] = str(request.resolve())
                receipt = {
                    "step_id": NATIVE_STEP,
                    "verdict": record["component_status"],
                    "outputs": record["outputs"],
                    "gate_ledger": gate.get("ledger", []),
                    "canonical_step_result": gate.get("step"),
                }
                receipt_path = project / (
                    "reports/phase3/default_steps/16/backend_result.json")
                write_json(receipt_path, receipt)
                version = versions.finish_step(
                    project, step_attempt,
                    verdict=record["component_status"], result=receipt,
                    canonical_pass=(record["component_status"] == "PASS"))
                record["output_version"] = version["folder"]
                if version["capture_errors"]:
                    raise OSError("D34_OUTPUT_RETENTION_FAILED: " +
                                  "; ".join(version["capture_errors"]))
            except BaseException as exc:
                if not (project / "steps" / step_attempt["folder"] /
                        "outputs.json").is_file():
                    versions.finish_step(
                        project, step_attempt, verdict="NOT_MEASURED",
                        result={"step_id": NATIVE_STEP, "detail": str(exc)})
                raise
    except (OSError, ValueError, TypeError, ImportError) as exc:
        record.update(reason=str(exc).split(":", 1)[0], detail=str(exc))
    targets = project / PLANNING_TARGETS
    if targets.is_file() and not targets.is_symlink():
        # The plan carries the declared CTS targets it hands downstream; D34
        # judges them against the requirement bounds, D38 judges the tree.
        record["planning_targets"] = {"path": PLANNING_TARGETS, "sha256": _sha(targets)}
    component = component_attempt / "component.json"
    write_json(component, record)
    return {**record, "component_record": {
        "path": str(component.relative_to(project)), "sha256": _sha(component)}}


def liberty_clock_pins(text: str) -> dict[str, str]:
    """``cell -> clock pin`` for every Liberty ``ff``/``latch`` group.

    The library's own declaration decides what is sequential, never a cell
    name. A multi-bit bank or a clock expression that is not a single pin is
    refused rather than guessed at.
    """
    import re
    starts = [(m.start(), m.group(1)) for m in re.finditer(
        r'\bcell\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', text)]
    pins = {}
    for index, (start, name) in enumerate(starts):
        block = text[start:starts[index + 1][0] if index + 1 < len(starts) else len(text)]
        if re.search(r"\b(ff_bank|latch_bank)\s*\(", block):
            raise ValueError("D34_LIBERTY_BANK_UNSUPPORTED: " + name)
        group = re.search(r"\b(ff|latch)\s*\([^)]*\)\s*\{([^{}]*)\}", block, re.S)
        if not group:
            continue
        key = "clocked_on" if group.group(1) == "ff" else "enable"
        value = re.search(key + r'\s*:\s*"([^"]*)"', group.group(2))
        pin = re.sub(r"[!()'\s]", "", value.group(1)) if value else ""
        if not re.fullmatch(r"[A-Za-z_][\w$]*", pin):
            raise ValueError(f"D34_LIBERTY_CLOCK_EXPRESSION_UNSUPPORTED: {name}: {value and value.group(1)}")
        pins[name] = pin
    return pins


def _liberty_group(text: str, brace: int) -> tuple[str, int]:
    """The body of the group whose ``{`` is at ``brace``, with nested groups blanked."""
    depth, top = 0, []
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return "".join(top), index
        elif depth == 1:
            top.append(char)
    raise ValueError("D34_LIBERTY_GROUP_UNTERMINATED")


def liberty_pin_roles(text: str) -> dict[str, dict[str, dict]]:
    """``cell -> pin -> {direction, clock, is_pad}`` from each pin's own attributes.

    Only a pin group's top-level attributes count; timing and power subgroups
    are blanked so their keywords cannot be read as the pin's.
    """
    import re
    roles = {}
    for cell in re.finditer(r'\bcell\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', text):
        _, end = _liberty_group(text, cell.end() - 1)
        block, pins = text[cell.end() - 1:end + 1], {}
        for pin in re.finditer(r'\bpin\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', block):
            body, pin_end = _liberty_group(block, pin.end() - 1)
            pin_block, arcs = block[pin.end():pin_end], []
            for timing in re.finditer(r'\btiming\s*\([^)]*\)\s*\{', pin_block):
                arc, _ = _liberty_group(pin_block, timing.end() - 1)
                fields = [re.search(r'\b' + key + r'\s*:\s*"?([\w$]+)', arc)
                          for key in ("related_pin", "timing_sense")]
                arcs.append(tuple(f.group(1) if f else None for f in fields))
            direction = re.search(r'\bdirection\s*:\s*"?(\w+)', body)
            pins[pin.group(1)] = {
                "direction": direction.group(1) if direction else None,
                "clock": bool(re.search(r'\bclock\s*:\s*"?true', body)),
                "is_pad": bool(re.search(r'\bis_pad\s*:\s*"?true', body)),
                "timing_arcs": arcs,
                **{key: bool(re.search(r"\b" + key + r'\s*:\s*"?true', body))
                   for key in ("clock_gate_clock_pin", "clock_gate_out_pin")}}
        roles[cell.group(1)] = pins
    return roles


def structural_clock_domains(def_text: str, clock_pins: dict[str, str],
                             pin_roles: dict[str, dict[str, dict]],
                             clock_sources: dict[str, str]) -> dict:
    """Assign every sequential clock pin to the clock whose source it traces back to.

    The trace follows the floorplan's own NETS backwards from each register
    clock pin through single-input cells, an input marked ``clock`` (clock
    gates) or ``is_pad`` (IO pads), until it reaches a declared clock source:
    a top-level port or a pin a clock is defined on. It shares no code with the
    timing graph. A register whose clock pin has no driver, or whose source is
    no declared clock, is ``unclocked`` and is a required sink the census must
    report. Any path the rules cannot decide raises: an unknown association is
    never guessed, so no reference exists and the row stays unmeasured.
    """
    import re

    def section(name):
        found = re.search(r"\n" + name + r"\s+\d+\s*;(.*?)\nEND " + name, def_text, re.S)
        if not found:
            raise ValueError("D34_DEF_" + name + "_ABSENT")
        return found.group(1)

    clean = lambda token: token.replace("\\", "")
    masters = {clean(i): m for i, m in re.findall(r"-\s+(\S+)\s+(\S+)", section("COMPONENTS"))}
    inputs = set()
    for entry in section("PINS").split(";"):
        name, direction = re.search(r"-\s+(\S+)", entry), re.search(r"\+\s+DIRECTION\s+(\w+)", entry)
        if name and direction and direction.group(1) == "INPUT":
            inputs.add(clean(name.group(1)))
    net_of, members = {}, {}
    for net, body in re.findall(r"-\s+(\S+)((?:\s*\(\s*\S+\s+\S+\s*\))+)", section("NETS")):
        for owner, pin in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", body):
            node = (clean(owner), clean(pin))
            net_of[node] = clean(net)
            members.setdefault(clean(net), []).append(node)

    def drivers(net):
        return [(owner, pin) for owner, pin in members.get(net, [])
                if (owner == "PIN" and pin in inputs) or (owner != "PIN" and
                    pin_roles.get(masters.get(owner), {}).get(pin, {}).get("direction") == "output")]

    domains, unclocked = {name: [] for name in set(clock_sources.values())}, []
    for instance, master in sorted(masters.items()):
        if master not in clock_pins:
            continue
        sink = instance + "/" + clock_pins[master]
        node, seen, clock = (instance, clock_pins[master]), set(), None
        while True:
            net = net_of.get(node)
            found = drivers(net) if net else []
            if not found:
                break
            if len(found) > 1:
                raise ValueError("D34_CLOCK_TRACE_UNRESOLVED: multiple drivers for " + sink)
            owner, pin = found[0]
            name = pin if owner == "PIN" else owner + "/" + pin
            if name in clock_sources:
                clock = clock_sources[name]
                break
            if owner == "PIN" or (owner, pin) in seen:
                break
            seen.add((owner, pin))
            ins = {p: r for p, r in pin_roles.get(masters.get(owner), {}).items()
                   if r.get("direction") == "input"}
            follow = ([p for p, r in ins.items() if r["clock"]] or
                      [p for p, r in ins.items() if r["is_pad"]] or
                      (list(ins) if len(ins) == 1 else []))
            if len(follow) != 1:
                raise ValueError(f"D34_CLOCK_TRACE_UNRESOLVED: {sink} through {owner} ({masters.get(owner)})")
            node = (owner, follow[0])
        (domains[clock] if clock else unclocked).append(sink)
    return {"clocks": {name: sorted(pins) for name, pins in domains.items()},
            "unclocked": sorted(unclocked)}


def d34_model_sources() -> dict[str, str]:
    """The exact consumer, census and operator code this row's verdict rests on."""
    import ast
    import _physical_current as current
    import flow109_metric_acceptance as metrics
    sources = {}
    for module, names in ((Path(__file__), ("accept_d34", "_d34_observe", "_d34_targets",
                                            "consume_default_row_completion", "liberty_clock_pins",
                                            "_liberty_group", "liberty_pin_roles",
                                            "structural_clock_domains", "d34_model_sources")),
                          (Path(current.__file__), ("clock_plan", "clock_plan_sinks")),
                          (Path(metrics.__file__), ("evaluate_operator", "_approved_document",
                                                    "_identity_complete"))):
        text = module.read_text()
        nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
        for name in names:
            sources[module.name + ":" + name] = hashlib.sha256(
                ast.get_source_segment(text, nodes[name]).encode()).hexdigest()
    return sources


def _d34_observe(project: Path, context: dict, component: dict) -> tuple[dict, dict]:
    """Reopen the exact native plan this component published and re-derive its census."""
    import _physical_current as current
    import flow109_metric_acceptance as metrics
    record = component.get("component_record")
    if not isinstance(record, dict):
        raise metrics.MetricRefusal("D34_COMPONENT_UNBOUND", "component_record required")
    path = project / str(record.get("path", ""))
    if (not str(record.get("path", "")).startswith("reports/flow109/D34/") or path.is_symlink()
            or not path.is_file() or _sha(path) != record.get("sha256")
            or json.loads(path.read_text()) != {k: v for k, v in component.items() if k != "component_record"}):
        raise metrics.MetricRefusal("D34_COMPONENT_STALE", str(record.get("path")))
    if (component.get("step_id") != "D34" or component.get("component_status") != "PASS"
            or component.get("context_sha256") != context["context_sha256"]):
        raise metrics.MetricRefusal("D34_COMPONENT_NOT_PASS", str(component.get("reason")))
    plan_path = project / OUTPUT
    if not plan_path.is_file() or _sha(plan_path) != (component.get("outputs") or {}).get(OUTPUT):
        raise metrics.MetricRefusal("D34_PLAN_STALE", OUTPUT)
    plan = json.loads(plan_path.read_text())
    subject = plan.get("current")
    refusal = current.validate(project, subject, step=NATIVE_STEP, stage="stage3",
                               tools=("openroad",), required_inputs=("floorplan", "recipe", "sdc_0"),
                               required_outputs=("log",), marker="CLOCK_PLAN_DONE")
    if refusal:
        raise metrics.MetricRefusal("D34_NATIVE_SUBJECT_STALE", refusal)
    if (plan.get("sink_census", {}).get("method") != current.CLOCK_SINK_METHOD
            or not isinstance(plan.get("sinks"), dict)):
        raise metrics.MetricRefusal("D34_SINK_CENSUS_ABSENT", OUTPUT)
    # The JSON is a summary; the native log is the measurement.
    log = (project / subject["outputs"]["log"]["path"]).read_text()
    names = [clock["name"] for clock in plan.get("clocks", [])]
    if current.clock_plan_sinks(log, names) != plan["sinks"]:
        raise metrics.MetricRefusal("D34_SINK_CENSUS_DIFFERS_FROM_LOG", OUTPUT)
    identity = {"producer": {"name": "phase3_one_shot_runner.emit_clock_plan",
                             "method": current.CLOCK_SINK_METHOD},
                "checker": {"methods": d34_model_sources()},
                "tool_execution": subject["execution"],
                "consumed_inputs": {role: row["sha256"] for role, row in subject["inputs"].items()},
                "requirements": {"registry_sha256": context["registry_sha256"],
                                 "obligations": sorted(D34_SPECS)},
                "configuration": {"context_sha256": context["context_sha256"],
                                  "plan": {"path": OUTPUT, "sha256": _sha(plan_path)}}}
    return plan, identity


def _d34_targets(project: Path, component: dict, identity: dict) -> dict:
    """Declared targets must sit inside their bound AND be consumed by the CTS row.

    The pinned LibreLane CTS exposes no skew or insertion-delay target, so the
    only consumer is the CTS row's acceptance authority (``TARGET_CONSUMER``):
    it must be approved, sourced from this exact targets file, and hold the
    same numbers as its limits. Without that binding the targets are a design
    decision, never a PASS. A target outside its bound, or a consumer holding
    different numbers than the plan declared, is a real defect and FAILS.
    """
    import flow109_metric_acceptance as metrics
    declared = component.get("planning_targets")
    path = project / PLANNING_TARGETS
    if (not isinstance(declared, dict) or declared.get("path") != PLANNING_TARGETS
            or path.is_symlink() or not path.is_file() or _sha(path) != declared.get("sha256")):
        raise metrics.MetricRefusal("D34_PLANNING_TARGETS_UNBOUND", PLANNING_TARGETS)
    plan = json.loads(path.read_text())
    authority, bounds = metrics._approved_document(project, TARGET_BOUNDS,
        authority="requirements_owner", schema=metrics.AUTHORITY_SCHEMA)
    limits, units = bounds.get("limits"), bounds.get("units")
    if (not isinstance(limits, dict) or not isinstance(units, dict)
            or set(limits) != set(TARGET_KEYS) or set(units) != set(TARGET_KEYS)
            or plan.get("units") != units or set(plan.get("targets") or {}) != set(TARGET_KEYS)):
        raise metrics.MetricRefusal("D34_TARGET_SHAPE_UNSUPPORTED", TARGET_BOUNDS)
    checks = {}
    for key in TARGET_KEYS:
        checks[key] = metrics.evaluate_operator("within_declared_bounds",
            {"status": "MEASURED", "value": plan["targets"][key], "unit": units[key], "identity": identity},
            {"status": "APPROVED", "limits": limits[key], "unit": units[key]})
    result = {"id": "base_22.skew_insertion_targets", "authority": authority, "value": plan["targets"],
              "checks": {k: {"status": s, "detail": d} for k, (s, d) in checks.items()},
              "scope": "declared planning targets consumed by the CTS row's acceptance authority; "
                       "the built tree is D38's measurement"}
    if any(state == "FAIL" for state, _ in checks.values()):
        return {**result, "status": "FAIL", "reason": "D34_PLANNING_TARGET_EXCEEDS_BOUND"}
    if any(state != "PASS" for state, _ in checks.values()):
        # An undeclared or unusable bound is not a satisfied bound.
        return {**result, "status": "NOT_MEASURED", "reason": "D34_PLANNING_TARGET_BOUND_NOT_MEASURED"}
    if not (project / TARGET_CONSUMER).is_file():
        return {**result, "status": "NOT_MEASURED", "reason": "D34_TARGET_CONSUMER_ABSENT"}
    consumer, body = metrics._approved_document(project, TARGET_CONSUMER,
        authority="requirements_owner", schema=metrics.AUTHORITY_SCHEMA)
    if consumer["source"] != {"path": PLANNING_TARGETS, "sha256": declared["sha256"]}:
        return {**result, "status": "NOT_MEASURED", "reason": "D34_TARGET_CONSUMER_UNBOUND",
                "consumer": consumer}
    held = {key: ((body.get("limits") or {}).get(key) or {}).get("max") for key in TARGET_KEYS}
    if any(value is None for value in held.values()):
        return {**result, "status": "NOT_MEASURED", "reason": "D34_TARGET_CONSUMER_INCOMPLETE",
                "consumer": consumer, "consumed": held}
    if held != plan["targets"] or {k: (body.get("units") or {}).get(k) for k in TARGET_KEYS} != units:
        return {**result, "status": "FAIL", "reason": "D34_TARGET_CONSUMER_DIFFERS",
                "consumer": consumer, "consumed": held}
    return {**result, "status": "PASS", "reason": "D34_TARGETS_CONSUMED_BY_CTS_AUTHORITY",
            "consumer": consumer}


def accept_d34(project, context, component):
    """Complete D34's two registered obligations; never claim a clock-tree result."""
    import flow109
    import flow109_admission as admission
    import flow109_metric_acceptance as metrics
    project = Path(project).resolve()
    result = {"schema": metrics.SCHEMA, "row_id": "D34", "status": "NOT_MEASURED",
              "qualification": "NOT_MEASURED", "delivery_blocked": True, "obligations": []}
    try:
        context = flow109.validate_execution_context(context)
        obligations = context["resolved_row"]["obligations"]
        if (context["resolved_row"]["id"] != "D34" or {o["id"] for o in obligations} != set(D34_SPECS)
                or any(any(o["expectation"].get(k) != v for k, v in D34_SPECS[o["id"]].items())
                       for o in obligations)):
            raise metrics.MetricRefusal("D34_OBLIGATIONS_UNREGISTERED", "the two base_22 operators only")
        plan, identity = _d34_observe(project, context, component)
        adopted, body = metrics._approved_document(project, SINK_REFERENCE,
            authority="requirements_owner", schema="vibeic.flow109.adopted-reference.v1")
        source = json.loads((project / adopted["source"]["path"]).read_text())
        if (adopted["source"]["path"] != SINK_SOURCE
                or source.get("clock_sink_inventory") != {k: v for k, v in body.items()
                                                          if k not in ("schema", "approval")}):
            raise metrics.MetricRefusal("D34_SINK_REFERENCE_SOURCE_UNBOUND", SINK_REFERENCE)
        reference = body.get("reference")
        if (not isinstance(reference, dict) or set(reference) != {"clocks", "unclocked"}
                or not isinstance(reference["clocks"], dict) or not isinstance(reference["unclocked"], list)):
            raise metrics.MetricRefusal("D34_SINK_REFERENCE_SHAPE", "per-clock domains plus unclocked sinks")
        # Clock-domain association is the measurement: a sink reached by the
        # wrong clock is as wrong as a sink reached by none.
        status, detail = metrics.evaluate_operator("matches_adopted_reference",
            {"status": "MEASURED", "value": plan["sinks"], "identity": identity},
            {**adopted, "reference": reference["clocks"], "reference_identity": body.get("reference_identity")})
        if reference["unclocked"]:
            status, detail = "FAIL", "required sinks whose clock pin reaches no declared clock"
        clocks = set(reference["clocks"]) | set(plan["sinks"])
        result["obligations"].append({
            "id": "base_22.clock_sink_inventory", "status": status, "detail": detail,
            "authority": adopted, "counts": plan["sink_census"]["counts"],
            "unclocked_required_sinks": reference["unclocked"],
            "unreached_sinks": {c: sorted(set(reference["clocks"].get(c, [])) - set(plan["sinks"].get(c, [])))
                                for c in sorted(clocks)},
            "unexpected_sinks": {c: sorted(set(plan["sinks"].get(c, [])) - set(reference["clocks"].get(c, [])))
                                 for c in sorted(clocks)}})
        result["obligations"].append(_d34_targets(project, component, identity))
        if any(item["status"] == "FAIL" for item in result["obligations"]):
            result.update(status="FAIL", reason="D34_METRIC_FAIL")
            return result
        if any(item["status"] != "PASS" for item in result["obligations"]):
            result["reason"] = "D34_METRIC_NOT_MEASURED"
            return result
        result["accepted_dependencies"] = {step: flow109._accepted_row(project,
            Path("reports/flow109/default_rows") / (step + ".json"), step)[1]
            for step in context["resolved_row"]["acceptance_deps"]}
        qualified = admission.require_admission(project, context)
        expected = {"purpose": D34_PURPOSE, "model_sources": d34_model_sources()}
        for use in context["runtime_tool_uses"]:
            if json.loads((project / use["config"]["path"]).read_text()) != expected:
                raise metrics.MetricRefusal("D34_MODEL_QUALIFICATION_STALE", use["use_id"])
        if _d34_observe(project, context, component) != (plan, identity):
            raise metrics.MetricRefusal("D34_INPUT_CHANGED_DURING_READ", OUTPUT)
        result.update(status="PASS", qualification=qualified["status"], delivery_blocked=False,
                      reason="D34_SINKS_TARGETS_DEPENDENCIES_AND_METHOD_PASS")
    except (flow109.Flow109Error, admission.AdmissionRefusal, metrics.MetricRefusal,
            OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        failed = any(item["status"] == "FAIL" for item in result["obligations"])
        result.update(status="FAIL" if failed else "NOT_MEASURED", qualification="NOT_MEASURED",
                      delivery_blocked=True, reason=getattr(exc, "code", "D34_EVIDENCE_NOT_MEASURED"),
                      detail=str(exc))
    return result


def consume_default_row_completion(project, context, result):
    """Complete from the native clock plan and its existing SDC consumer.

    OpenSTA owns the sink census. A second adopted inventory and duplicate
    CTS authority are not prerequisites for reading its answer (Charter C5).
    """
    answer = {"step_id": "D34", "context_sha256": context["context_sha256"],
              "whole_flow_acceptance": "NOT_MEASURED", "delivery_accepted": False}
    if result.get("component_status") != "PASS" or result.get("default_row_status") == "FAIL":
        status = ("FAIL" if "FAIL" in (result.get("component_status"), result.get("default_row_status"))
                  else "NOT_MEASURED")
        return {**answer, "default_row_status": status, "completed": False,
                "flow109_acceptance": status, "reason": result.get("reason")}
    consumer = (result.get("consumer_result") or {}).get("status")
    measured = (result.get("native_execution") or {}).get("rc") == 0 and consumer == "PASS"
    status = "FAIL" if consumer == "FAIL" else "PASS" if measured else "NOT_MEASURED"
    return {**answer, "default_row_status": status, "completed": status == "PASS",
            "flow109_acceptance": status,
            "reason": "D34_NATIVE_CLOCK_PLAN" if measured else "D34_NATIVE_PLAN_NOT_ACCEPTED"}


def propose_sink_reference(project: Path, liberties: list[Path]) -> dict:
    """Write the structural census for the requirements owner to adopt.

    This is a proposal, never an approval: the owner adopts it by writing
    ``SINK_REFERENCE`` with ``approval.source_reference`` naming this file.
    """
    project = Path(project).resolve()
    floorplan = project / "phase3/stage3/pnr/floorplan.def"
    plan = json.loads((project / OUTPUT).read_text())
    # Clock definitions come from the SDC the plan read; only the sink
    # association is derived here, from the floorplan's own connectivity.
    sources = {source: clock["name"] for clock in plan.get("clocks", [])
               for source in str(clock.get("source", "")).split()}
    if not sources:
        raise ValueError("D34_CLOCK_SOURCES_ABSENT: " + OUTPUT)
    pins, roles = {}, {}
    for path in liberties:
        text = Path(path).read_text(errors="ignore")
        pins.update(liberty_clock_pins(text))
        roles.update(liberty_pin_roles(text))
    if not pins:
        raise ValueError("D34_LIBERTY_SEQUENTIAL_CELLS_ABSENT")
    reference = structural_clock_domains(floorplan.read_text(), pins, roles, sources)
    consumed = {"phase3/stage3/pnr/floorplan.def": _sha(floorplan), OUTPUT: _sha(project / OUTPUT),
                **{str(Path(p).resolve()): _sha(Path(p)) for p in liberties}}
    payload = {"reference": reference, "reference_identity": {
        "producer": {"name": "flow109_clock_plan.structural_clock_domains",
                     "method": "floorplan NETS traced from each Liberty ff/latch clock pin to a declared clock source"},
        "checker": {"methods": d34_model_sources()},
        "tool_execution": {"program": "flow109_clock_plan.py propose-sink-reference"},
        "consumed_inputs": consumed,
        "requirements": {"obligation": "base_22.clock_sink_inventory"},
        "configuration": {"sequential_cells": len(pins), "clocks": sorted(set(sources.values())),
                          "unclocked": len(reference["unclocked"])}}}
    target = project / SINK_SOURCE
    if target.exists():
        raise ValueError("D34_SINK_SOURCE_EXISTS: " + SINK_SOURCE)
    write_json(target, {"schema": "vibeic.flow109.d34-sink-reference-source.v1",
                        "clock_sink_inventory": payload})
    return {"path": SINK_SOURCE, "sha256": _sha(target),
            "sinks": {name: len(found) for name, found in reference["clocks"].items()},
            "unclocked": len(reference["unclocked"])}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="D34 structural sink census proposal")
    parser.add_argument("command", choices=["propose-sink-reference"])
    parser.add_argument("project")
    parser.add_argument("--liberty", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(propose_sink_reference(Path(args.project), [Path(p) for p in args.liberty])))
