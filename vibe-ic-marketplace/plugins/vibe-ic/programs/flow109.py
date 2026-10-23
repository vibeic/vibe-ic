"""Source-owned 109-flow selection and existing Default dispatch bindings.

Selection is not qualification or IC acceptance.  Unimplemented rows remain
visible, and bounded native execution retains the old receipts unchanged.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
REGISTRY = HERE.parent / "flow" / "flow109.json"
CONTEXT_ENV = "VIBEIC_FLOW109_CONTEXT"
ATTEMPT_ENV = "VIBEIC_FLOW109_ATTEMPT"


class Flow109Error(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def predicate(expression: str, features: Mapping[str, bool]) -> bool:
    """Evaluate the published Boolean grammar; no Python eval or false default."""
    try:
        node = ast.parse(expression, mode="eval").body
    except (SyntaxError, TypeError) as exc:
        raise Flow109Error("FLOW109_PREDICATE_INVALID", str(expression)) from exc

    def visit(item):
        if isinstance(item, ast.Name):
            if item.id not in features or type(features[item.id]) is not bool:
                raise Flow109Error("FLOW109_FEATURE_UNRESOLVED", item.id)
            return features[item.id]
        if isinstance(item, ast.Constant) and type(item.value) is bool:
            return item.value
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.Not):
            return not visit(item.operand)
        if isinstance(item, ast.BoolOp) and isinstance(item.op, (ast.And, ast.Or)):
            # Visit all names, including ones hidden behind a false prefix.
            values = [visit(value) for value in item.values]
            return all(values) if isinstance(item.op, ast.And) else any(values)
        raise Flow109Error("FLOW109_PREDICATE_INVALID", expression)

    return visit(node)


def load_registry() -> dict:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if data.get("schema") != "vibeic.flow109.registry.v1":
        raise Flow109Error("FLOW109_REGISTRY_INVALID", "unsupported schema")
    rows = data["rows"]
    if (len({row["id"] for row in rows}) != len(rows)
            or len({row["key"] for row in rows}) != len(rows)
            or [row["position"] for row in rows] != list(range(1, len(rows) + 1))):
        raise Flow109Error("FLOW109_REGISTRY_INVALID", "duplicate IDs or reordered positions")
    native = HERE.parent / data["legacy_flow_path"]
    if _file_digest(native) != data["legacy_flow_sha256"]:
        raise Flow109Error("FLOW109_LEGACY_MAP_STALE", "canonical source changed; review the mapping")
    return data


def resolve_features(supplied: Mapping[str, bool], registry: dict) -> dict:
    if not isinstance(supplied, Mapping):
        raise Flow109Error("FLOW109_FEATURES_INVALID", "features must be an object")
    names = set(registry["predicate_names"])
    unknown = sorted(set(supplied) - names)
    invalid = sorted(str(k) for k, value in supplied.items() if type(value) is not bool)
    if unknown or invalid:
        raise Flow109Error("FLOW109_FEATURES_INVALID", f"unknown={unknown}, non_boolean={invalid}")
    definitions = registry["predicate_definitions"]
    missing = sorted(names - set(definitions) - set(supplied) - {"always"})
    if missing:
        raise Flow109Error("FLOW109_FEATURE_UNRESOLVED", ", ".join(missing))
    result = dict(supplied)
    if result.get("always", True) is not True:
        raise Flow109Error("FLOW109_FEATURES_INVALID", "always must be true")
    result["always"] = True
    pending = dict(definitions)
    while pending:
        progressed = False
        for name, expression in list(pending.items()):
            try:
                # Derived names supplied by a caller do not override definitions.
                available = {k: v for k, v in result.items() if k not in pending}
                expected = predicate(expression, available)
            except Flow109Error as exc:
                if exc.code == "FLOW109_FEATURE_UNRESOLVED":
                    continue
                raise
            if name in supplied and supplied[name] != expected:
                raise Flow109Error("FLOW109_FEATURE_CONFLICT", name)
            result[name] = expected
            del pending[name]
            progressed = True
        if not progressed:
            raise Flow109Error("FLOW109_DEFINITION_CYCLE", ", ".join(pending))
    endpoints = [name for name in registry["endpoints"] if result[name]]
    if len(endpoints) != 1:
        raise Flow109Error("FLOW109_ENDPOINT_CONFLICT", str(endpoints))
    for antecedent, consequences in registry["feature_implications"].items():
        absent = [name for name in consequences if result[antecedent] and not result[name]]
        if absent:
            raise Flow109Error("FLOW109_FEATURE_CONFLICT", f"{antecedent} requires {absent}")
    for group in registry["feature_exclusions"]:
        if all(result[name] for name in group):
            raise Flow109Error("FLOW109_FEATURE_CONFLICT", "mutually exclusive: " + ", ".join(group))
    return result


def _selected_profile(row: dict, features: dict, override: str | None) -> dict:
    choices = [p for p in row["profiles"] if p["select_when"] != "otherwise"
               and predicate(p["select_when"], features)]
    if not choices:
        choices = [p for p in row["profiles"] if p["select_when"] == "otherwise"]
    if len(choices) != 1:
        raise Flow109Error("FLOW109_PROFILE_AMBIGUOUS", row["id"])
    choice = choices[0]
    if override is not None and override != choice["id"]:
        raise Flow109Error("FLOW109_PROFILE_INAPPLICABLE", f"{row['id']}.{override}")
    return copy.deepcopy(choice)


def _tool_uses(row: dict, profile: dict) -> list[dict]:
    """Use identities are source-owned purposes, not caller-selected tool names."""
    dispatch = profile.get("dispatch")
    if dispatch is None:
        return []
    return [{"use_id": f"flow109.{row['id']}.{profile['id']}.{tool}",
             "tool_id": tool, "purpose": f"{row['id']}.{profile['id']}",
             "native_step_id": dispatch["native_step_id"],
             "native_steps": dispatch.get("engine_steps", {}).get(tool, profile.get("native_steps", [])),
             "executable_name": dispatch.get("engine_executables", {}).get(tool, tool),
             "qualification_required": True}
            for tool in dispatch["engine_families"]]


def resolve_plan(features: Mapping[str, bool], step_profiles: Mapping[str, str] | None = None) -> dict:
    registry = load_registry()
    selected_features = resolve_features(features, registry)
    if step_profiles is not None and (not isinstance(step_profiles, Mapping)
                                     or any(not isinstance(v, str) for v in step_profiles.values())):
        raise Flow109Error("FLOW109_PROFILE_INVALID", "step_profiles must map stable IDs to profile names")
    overrides = dict(step_profiles or {})
    known = {r["id"] for r in registry["rows"]}
    if set(overrides) - known:
        raise Flow109Error("FLOW109_STEP_UNKNOWN", str(sorted(set(overrides) - known)))
    rows = []
    for spec in registry["rows"]:
        if not predicate(spec["when"], selected_features):
            if spec["id"] in overrides:
                raise Flow109Error("FLOW109_STEP_NOT_SELECTED", spec["id"])
            continue
        row = copy.deepcopy(spec)
        row["profile"] = _selected_profile(row, selected_features, overrides.get(row["id"]))
        row["selected_profile"] = row["profile"]["id"]
        row["tool_uses"] = _tool_uses(row, row["profile"])
        rows.append(row)
    selected = {r["id"] for r in rows}
    for row in rows:
        for dep in row["data_deps"]:
            required = (dep["step"] in selected if dep["when"] == "producer_selected"
                        else predicate(dep["when"], selected_features))
            if required and dep["step"] not in selected:
                raise Flow109Error("FLOW109_DEPENDENCY_NOT_SELECTED", f"{row['id']} <- {dep['step']}")
    return {"schema": "vibeic.flow109.plan.v1", "flow_id": "109",
            "status": "PLAN_RESOLVED_NOT_EXECUTED", "revision": registry["revision"],
            "registry_sha256": _file_digest(REGISTRY),
            "planner_sha256": _file_digest(Path(__file__)),
            "legacy_source_commit": registry["legacy_source_commit"],
            "legacy_flow_sha256": registry["legacy_flow_sha256"],
            "features": selected_features, "step_profiles": overrides,
            "phases": registry["phases"], "stages": registry["stages"],
            "gate_layers": registry["gate_layers"], "namespaces": registry["namespaces"],
            "rows": rows, "selected_count": len(rows),
            "runtime_verdict": "NOT_MEASURED", "flow109_acceptance": "NOT_MEASURED"}


def resolve_step(plan: Mapping, step_id: str) -> dict:
    row = next((r for r in plan["rows"] if r["id"] == step_id), None)
    if row is None:
        raise Flow109Error("FLOW109_STEP_NOT_SELECTED", str(step_id))
    return copy.deepcopy(row)


def _canonical_owner_dispatch(row: Mapping) -> dict | None:
    """Validate a source-owned route into an existing Default runner site."""
    dispatch = row.get("profile", {}).get("dispatch")
    if not isinstance(dispatch, Mapping) or dispatch.get("kind") != "canonical_owner_window":
        return None
    native = str(dispatch.get("native_step_id") or "")
    legacy = {str(item.get("id")) for item in row.get("legacy70", [])
              if isinstance(item, Mapping)}
    if not native or native not in legacy:
        raise Flow109Error("FLOW109_OWNER_NATIVE_MAPPING_UNKNOWN",
                           f"{row.get('id')} -> {native or '<missing>'}")
    owner = str(dispatch.get("owner_runner") or "")
    entry = str(dispatch.get("owner_entry_step") or "")
    exit_ = str(dispatch.get("owner_exit_step") or "")
    if not owner or not entry or not exit_:
        raise Flow109Error("FLOW109_OWNER_WINDOW_INVALID", str(row.get("id")))
    import step_preflight
    actual = step_preflight.runner_for_step(entry)
    # Default Steps 8 and 10 are retained front-door consumers whose special
    # entry branches deliberately sit outside the generic span-head table.
    if actual is None and owner == "design_one_shot_runner" and entry in ("8", "10"):
        actual = owner
    if actual != owner:
        raise Flow109Error("FLOW109_OWNER_MISMATCH",
                           f"{row.get('id')}: declared {owner}, actual {actual}")
    if owner not in ("phase1_one_shot_runner", "design_one_shot_runner",
                     "phase3_one_shot_runner"):
        raise Flow109Error("FLOW109_OWNER_UNSUPPORTED", owner)
    return dict(dispatch)


def source_owned_native_dispatch(row: Mapping) -> dict | None:
    """Validate the registered Default component route that owns native checks.

    This is the adapter analogue of ``canonical_owner_window``: the frozen
    source registry, not caller data, selects an existing local owner.  It does
    not claim generic tool qualification or Flow109 acceptance.
    """
    profile = row.get("profile", {})
    dispatch = profile.get("dispatch")
    if not isinstance(dispatch, Mapping) or profile.get("id") != "default":
        return None
    native = dispatch.get("native_step_id")
    engines = dispatch.get("engine_families")
    common_invalid = (
            dispatch.get("acceptance_scope") != "existing_native_component_only"
            or not isinstance(engines, list) or not engines
            or set(dispatch.get("engine_steps", {})) != set(engines)
            or set(dispatch.get("engine_executables", {})) != set(engines))
    adapter = dispatch.get("adapter")
    if dispatch.get("admission_policy") == "source_owned_existing_native":
        invalid = (common_invalid
                   or not isinstance(adapter, str) or not adapter.startswith("flow109_")
                   or not (HERE / (adapter + ".py")).is_file()
                   or native != "flow109." + str(row.get("id")))
    elif dispatch.get("kind") == "canonical_backend_window" and adapter is None:
        # The existing backend/release catalogs are the native owner registry.
        # Flow109 only names their already-supported Default rows; it does not
        # create a second generic tool-qualification registry.
        import execution_backend_gates as backend_gates
        canonical = backend_gates.canonical_family_row(str(native))
        legacy = {str(item.get("id")) for item in row.get("legacy70", [])
                  if isinstance(item, Mapping)}
        invalid = (common_invalid or canonical is None or str(native) not in legacy
                   or dispatch.get("producer") != "execution_backend_producers.py:produce"
                   or dispatch.get("consumer") != "execution_backend_gates.py:evaluate"
                   or not isinstance(dispatch.get("producer_sites"), list)
                   or not dispatch["producer_sites"]
                   or any(not isinstance(site, str) or not site
                          for site in dispatch["producer_sites"])
                   or list(dispatch.get("native_required_outputs", ())) !=
                   list(canonical.get("required_outputs", ())))
    else:
        return None
    if invalid:
        raise Flow109Error("FLOW109_NATIVE_OWNER_INVALID", str(row.get("id")))
    return dict(dispatch)


def _selected_native_sequence(rows) -> dict | None:
    """Return the one executable mixed-owner layout, or refuse its crossing.

    The front door can run registered adapters before it enters the existing
    Phase-3 backend, but it cannot resume adapters after that backend returns.
    Keep that physical ordering explicit instead of treating arbitrary mixed
    owners as a generic scheduler.
    """
    dispatches = [source_owned_native_dispatch(row) for row in rows]
    if not dispatches or any(dispatch is None for dispatch in dispatches):
        return None
    adapters = [bool(dispatch.get("adapter")) for dispatch in dispatches]
    if not any(adapters) or all(adapters):
        return None
    backend_start = next(index for index, adapter in enumerate(adapters)
                         if not adapter)
    if (backend_start == 0 or not all(adapters[:backend_start])
            or any(adapters[backend_start:])
            or any(dispatch.get("kind") != "canonical_backend_window"
                   for dispatch in dispatches[backend_start:])):
        raise Flow109Error(
            "FLOW109_WINDOW_DISPATCH_UNSUPPORTED",
            "mixed native windows require an adapter prefix and canonical-backend suffix")
    return {
        "adapter_count": backend_start,
        "backend_entry_step": dispatches[backend_start]["native_step_id"],
        "backend_exit_step": dispatches[-1]["native_step_id"],
    }


def source_owned_native_admission(context: Mapping) -> dict | None:
    """Record engineering-native ownership without asserting qualification."""
    # An explicit runtime/registry request is a qualification claim and stays
    # on the strict generic path.  The Default engineering route is selected
    # only by omitting both; callers cannot use this policy to rescue bad,
    # stale or unsupported qualification evidence.
    if (context.get("runtime_tool_uses") is not None
            or context.get("qualification_registry") is not None):
        return None
    if context.get("schema") == "vibeic.flow109.execution-window.v1":
        if context.get("dispatch_kind") not in (
                "canonical_backend_window", "selected_native_sequence"):
            return None
        dispatches = [source_owned_native_dispatch(row)
                      for row in context.get("resolved_rows", ())]
        if not dispatches or any(dispatch is None for dispatch in dispatches):
            return None
        native_step = [dispatch["native_step_id"] for dispatch in dispatches]
        scope = {dispatch["acceptance_scope"] for dispatch in dispatches}
        if len(scope) != 1:
            raise Flow109Error("FLOW109_NATIVE_OWNER_INVALID", "mixed acceptance scope")
    else:
        dispatch = source_owned_native_dispatch(context.get("resolved_row", {}))
        if dispatch is None:
            return None
        native_step = dispatch["native_step_id"]
        scope = {dispatch["acceptance_scope"]}
    return {
        "status": "NOT_APPLICABLE",
        "reason": "SOURCE_OWNED_EXISTING_NATIVE_COMPONENT",
        "admitted": True,
        "qualification_status": "NOT_CLAIMED",
        "acceptance_scope": next(iter(scope)),
        "native_step_id": native_step,
        "context_sha256": context.get("context_sha256"),
        "native_started": False,
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
    }


def resolve_execution_window(plan: Mapping, entry: str | None, exit_: str | None) -> dict:
    """Resolve an inclusive selected-row window onto existing component owners.

    This is deliberately not a 109 acceptance scheduler. Every selected row
    must already name a dispatch owner; a gap refuses the complete request
    before a neighbouring legacy span can silently cover it.
    """
    if not entry or not exit_:
        raise Flow109Error("FLOW109_WINDOW_REQUIRED", "explicit entry and exit rows are required")
    ids = [row["id"] for row in plan["rows"]]
    if entry not in ids:
        raise Flow109Error("FLOW109_STEP_NOT_SELECTED", str(entry))
    if exit_ not in ids:
        raise Flow109Error("FLOW109_STEP_NOT_SELECTED", str(exit_))
    first, last = ids.index(entry), ids.index(exit_)
    if first > last:
        raise Flow109Error("FLOW109_WINDOW_REVERSED", f"{entry} follows {exit_}")
    rows = [copy.deepcopy(row) for row in plan["rows"][first:last + 1]]
    missing = [f"{row['id']}.{row['selected_profile']}" for row in rows
               if not row["profile"].get("dispatch")]
    if missing:
        raise Flow109Error("FLOW109_PRODUCER_UNIMPLEMENTED", ", ".join(missing))
    if len(rows) == 1:
        dispatch = rows[0]["profile"]["dispatch"]
        _canonical_owner_dispatch(rows[0])
        return {"requested_step": entry, "resolved_row": rows[0],
                "native_step_id": dispatch["native_step_id"]}

    dispatches = [row["profile"]["dispatch"] for row in rows]
    adapters = [bool(dispatch.get("adapter")) for dispatch in dispatches]
    if all(adapters):
        kind = "ordered_adapters"
    elif not any(adapters) and all(dispatch.get("kind") == "canonical_backend_window"
                                   for dispatch in dispatches):
        kind = "canonical_backend_window"
    elif not any(adapters) and all(dispatch.get("kind") == "canonical_owner_window"
                                   for dispatch in dispatches):
        owners = [_canonical_owner_dispatch(row)["owner_runner"] for row in rows]
        if len(set(owners)) != 1:
            raise Flow109Error("FLOW109_WINDOW_OWNER_CROSSING_UNSUPPORTED",
                               " -> ".join(owners))
        kind = "canonical_owner_window"
    elif _selected_native_sequence(rows) is not None:
        kind = "selected_native_sequence"
    else:
        raise Flow109Error(
            "FLOW109_WINDOW_DISPATCH_UNSUPPORTED",
            "a window may not cross adapter and canonical-backend ownership")
    native_entry = (dispatches[0].get("owner_entry_step") if kind == "canonical_owner_window"
                    else dispatches[0]["native_step_id"])
    native_exit = (dispatches[-1].get("owner_exit_step") if kind == "canonical_owner_window"
                   else dispatches[-1]["native_step_id"])
    return {"requested_entry": entry, "requested_exit": exit_,
            "resolved_rows": rows, "dispatch_kind": kind,
            "native_entry_step": native_entry,
            "native_exit_step": native_exit}


_CONTEXT_KEYS = {"schema", "registry_sha256", "planner_sha256", "legacy_flow_sha256",
                 "features", "step_profiles", "requested_step", "resolved_row",
                 "native_step_id", "runtime_tool_uses", "qualification_registry", "context_sha256"}
_WINDOW_CONTEXT_KEYS = {
    "schema", "registry_sha256", "planner_sha256", "legacy_flow_sha256",
    "features", "step_profiles", "requested_entry", "requested_exit",
    "resolved_rows", "dispatch_kind", "native_entry_step", "native_exit_step",
    "runtime_tool_uses", "qualification_registry", "context_sha256",
}


def execution_context(plan: dict, entry: str, exit_: str, *,
                      runtime_tool_uses=None, qualification_registry=None) -> dict:
    window = resolve_execution_window(plan, entry, exit_)
    schema = ("vibeic.flow109.execution-context.v1" if "requested_step" in window
              else "vibeic.flow109.execution-window.v1")
    context = {"schema": schema,
               **{key: plan[key] for key in ("registry_sha256", "planner_sha256", "legacy_flow_sha256",
                                             "features", "step_profiles")},
               **window, "runtime_tool_uses": copy.deepcopy(runtime_tool_uses),
               "qualification_registry": qualification_registry}
    context["context_sha256"] = digest(context)
    return context


def validate_execution_context(context: Mapping) -> dict:
    if not isinstance(context, Mapping):
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "expected object")
    keys = (_WINDOW_CONTEXT_KEYS
            if context.get("schema") == "vibeic.flow109.execution-window.v1"
            else _CONTEXT_KEYS)
    if set(context) != keys:
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "unexpected or missing fields")
    if context["schema"] not in ("vibeic.flow109.execution-context.v1",
                                 "vibeic.flow109.execution-window.v1"):
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "schema")
    payload = {key: value for key, value in context.items() if key != "context_sha256"}
    if context["context_sha256"] != digest(payload):
        raise Flow109Error("FLOW109_CONTEXT_STALE", "request identity changed")
    current = resolve_plan(context["features"], context["step_profiles"])
    entry = context.get("requested_step", context.get("requested_entry"))
    exit_ = context.get("requested_step", context.get("requested_exit"))
    expected = execution_context(current, entry, exit_,
                                 runtime_tool_uses=context["runtime_tool_uses"],
                                 qualification_registry=context["qualification_registry"])
    if dict(context) != expected:
        raise Flow109Error("FLOW109_CONTEXT_STALE", "source registry, producer or selection changed")
    return expected


def component_context(context: Mapping, *, native_step_id: str | None = None,
                      requested_step: str | None = None) -> dict:
    """Return the current one-row contract selected from a validated window."""
    context = validate_execution_context(context)
    if context["schema"] == "vibeic.flow109.execution-context.v1":
        return context
    matches = [row for row in context["resolved_rows"]
               if (requested_step is not None and row["id"] == requested_step)
               or (requested_step is None and native_step_id is not None
                   and str(row["profile"]["dispatch"]["native_step_id"])
                   == str(native_step_id))]
    if len(matches) != 1:
        raise Flow109Error("FLOW109_NATIVE_STEP_MISMATCH",
                           str(requested_step if requested_step is not None else native_step_id))
    row = matches[0]
    expected_ids = {item["use_id"] for item in row["tool_uses"]}
    runtime = context.get("runtime_tool_uses")
    selected = ([copy.deepcopy(item) for item in runtime
                 if isinstance(item, dict) and item.get("use_id") in expected_ids]
                if isinstance(runtime, list) else runtime)
    plan = resolve_plan(context["features"], context["step_profiles"])
    return execution_context(
        plan, row["id"], row["id"], runtime_tool_uses=selected,
        qualification_registry=context["qualification_registry"])


def _window_inventory(context: Mapping) -> None:
    runtime = context.get("runtime_tool_uses")
    expected = [use["use_id"] for row in context["resolved_rows"] for use in row["tool_uses"]]
    actual = [item.get("use_id") for item in runtime if isinstance(item, dict)] \
        if isinstance(runtime, list) else []
    if not expected or len(actual) != len(runtime or []) or len(actual) != len(set(actual)) \
            or set(actual) != set(expected):
        raise Flow109Error("FLOW109_WINDOW_USE_MISMATCH",
                           "runtime inventory must exactly cover every selected row use")
    if not isinstance(context.get("qualification_registry"), str) \
            or not context["qualification_registry"]:
        raise Flow109Error("FLOW109_QUALIFICATION_REGISTRY_ABSENT",
                           "qualification registry required")


def _new_attempt(project: Path, context: Mapping) -> Path:
    parent = project / "reports" / "flow109" / "attempts"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = parent / ("window-" + uuid.uuid4().hex)
    attempt.mkdir()
    request = {"schema": "vibeic.flow109.window-attempt-request.v1",
               "context_sha256": context["context_sha256"],
               "entry": context["requested_entry"], "exit": context["requested_exit"],
               "dispatch_kind": context["dispatch_kind"],
               "component_ids": [row["id"] for row in context["resolved_rows"]],
               "flow109_acceptance": "NOT_MEASURED"}
    with (attempt / "request.json").open("x", encoding="utf-8") as handle:
        json.dump(request, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return attempt


def _finish_attempt(attempt: Path, result: Mapping) -> Path:
    path = attempt / "result.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(dict(result), handle, sort_keys=True, indent=2)
        handle.write("\n")
    return path


def _not_executed_component(context: Mapping, row: Mapping, reason: str) -> dict:
    return {
        "schema": "vibeic.flow109.window-component.v1",
        "step_id": row["id"],
        "native_step_id": row["profile"]["dispatch"]["native_step_id"],
        "component_status": "NOT_MEASURED",
        "reason": reason,
        "context_sha256": context["context_sha256"],
        "native_started": False,
        "metric_acceptance_status": row.get("metric_acceptance_status", "UNIMPLEMENTED"),
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "data_dependencies": row["data_deps"],
        "acceptance_dependencies": row["acceptance_deps"],
    }


def _attempt_result(context: Mapping, components: list[dict]) -> dict:
    aggregate = ("FAIL" if any(item["component_status"] == "FAIL" for item in components)
                 else "PASS" if len(components) == len(context["resolved_rows"])
                 and all(item["component_status"] == "PASS" for item in components)
                 else "NOT_MEASURED")
    return {"schema": "vibeic.flow109.window-attempt-result.v1",
            "context_sha256": context["context_sha256"],
            "component_status": aggregate, "components": components,
            "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
            "bounded": True, "delivery_accepted": False}


def finish_native_window(project: Path, report: Mapping, report_path: Path | None = None) -> dict | None:
    """Bind a canonical backend report to per-row component evidence."""
    path = os.environ.get(CONTEXT_ENV)
    attempt_name = os.environ.get(ATTEMPT_ENV)
    if not path or not attempt_name:
        return None
    try:
        context = validate_execution_context(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, Flow109Error):
        return None
    if (context["schema"] != "vibeic.flow109.execution-window.v1"
            or context["dispatch_kind"] not in (
                "canonical_backend_window", "selected_native_sequence")):
        return None
    attempt = Path(attempt_name)
    canonical = []
    for site in report.get("steps", []) if isinstance(report, Mapping) else []:
        if isinstance(site, dict):
            canonical.extend((site.get("extras") or {}).get("canonical_steps") or [])
    by_native = {str((item.get("extras") or {}).get("step_id")): item
                 for item in canonical if isinstance(item, dict)}
    components = []
    stopped = False
    for row in context["resolved_rows"]:
        dispatch = row["profile"]["dispatch"]
        native = str(dispatch["native_step_id"])
        if dispatch.get("adapter"):
            component_path = (project / "reports" / "flow109" / "components"
                              / (row["id"] + ".json"))
            try:
                component = json.loads(component_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                component = _not_executed_component(
                    context, row, "selected adapter component receipt absent or invalid")
            if (not isinstance(component, dict)
                    or component.get("step_id") != row["id"]
                    or component.get("context_sha256") != context["context_sha256"]
                    or component.get("component_status") not in (
                        "PASS", "FAIL", "NOT_MEASURED")
                    or component.get("flow109_acceptance") != "NOT_MEASURED"):
                component = _not_executed_component(
                    context, row, "selected adapter component receipt absent or invalid")
            components.append(component)
            if component["component_status"] != "PASS":
                stopped = True
            continue
        if stopped:
            component = _not_executed_component(
                context, row, "not executed: an earlier row stopped")
            components.append(component)
            from _atomic_artefact import write_json
            write_json(project / "reports" / "flow109" / "components"
                       / (row["id"] + ".json"), component)
            continue
        item = by_native.get(native)
        status = str(item.get("status")) if item else "NOT_MEASURED"
        native_not_applicable = status == "NOT_APPLICABLE"
        if status not in ("PASS", "FAIL", "NOT_MEASURED"):
            status = "NOT_MEASURED"
        reason = ("selected Flow109 row cannot inherit native NOT_APPLICABLE"
                  if native_not_applicable else
                  str(item.get("detail") or "") if item else
                  "not executed: an earlier row stopped" if stopped else
                  str(report.get("flow109_stop_reason") or "canonical row result absent"))
        receipt = project / "reports" / "phase3" / "default_steps" / native / "backend_result.json"
        receipt_body = None
        if receipt.is_file():
            try:
                receipt_body = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                receipt_body = None
        if status == "PASS" and (not isinstance(receipt_body, dict)
                                 or receipt_body.get("verdict") != "PASS"):
            status = "NOT_MEASURED"
            reason = "canonical current native PASS receipt absent or invalid"
        component = {
            "schema": "vibeic.flow109.window-component.v1", "step_id": row["id"],
            "native_step_id": native, "component_status": status,
            "reason": reason, "context_sha256": context["context_sha256"],
            "metric_acceptance_status": row.get("metric_acceptance_status", "UNIMPLEMENTED"),
            "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
            "data_dependencies": row["data_deps"],
            "acceptance_dependencies": row["acceptance_deps"],
        }
        if receipt.is_file():
            component["canonical_receipt"] = {
                "path": str(receipt.relative_to(project)), "sha256": _file_digest(receipt)}
        components.append(component)
        from _atomic_artefact import write_json
        write_json(project / "reports" / "flow109" / "components" / (row["id"] + ".json"), component)
        if status != "PASS":
            stopped = True
    result = _attempt_result(context, components)
    if report_path is not None and Path(report_path).is_file():
        result["canonical_window_report"] = {
            "path": str(Path(report_path).relative_to(project)),
            "sha256": _file_digest(Path(report_path))}
    _finish_attempt(attempt, result)
    return result


def prepare_front_door(args, project: Path) -> int | None:
    """Return an exit code for planning/refusal, or continue the real front door."""
    if args.flow != "109":
        if args.flow109_manifest or args.flow109_plan_only:
            raise Flow109Error("FLOW109_SELECTION_REQUIRED", "use --flow 109")
        # A stale parent selection cannot turn a later 70-flow launch into 109.
        os.environ.pop(CONTEXT_ENV, None)
        os.environ.pop(ATTEMPT_ENV, None)
        return None
    # The existing policy parser uses None for an omitted mode and resolves
    # it to Default. Preserve that CLI contract rather than demanding a flag.
    if args.execution_mode not in (None, "default"):
        raise Flow109Error("FLOW109_MODE_UNIMPLEMENTED", "109 currently selects Default only")
    if not args.flow109_manifest:
        raise Flow109Error("FLOW109_MANIFEST_REQUIRED", "supply explicit resolved features")
    try:
        manifest = json.loads(Path(args.flow109_manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Flow109Error("FLOW109_MANIFEST_INVALID", str(exc)) from exc
    if not isinstance(manifest, dict):
        raise Flow109Error("FLOW109_MANIFEST_INVALID", "expected object")
    if "tool_uses" in manifest and "runtime_tool_uses" in manifest:
        raise Flow109Error("FLOW109_MANIFEST_INVALID", "duplicate runtime tool identity fields")
    plan = resolve_plan(manifest.get("features"), manifest.get("step_profiles"))
    from _delivery_route import report_label
    route = report_label(project).get("delivery_route")
    expected = "IC" if plan["features"]["ic"] else "IP"
    if route != expected:
        raise Flow109Error("FLOW109_ROUTE_CONFLICT", f"manifest endpoint requires {expected}, owner declared {route}")
    from _atomic_artefact import write_json
    destination = project / "reports" / "flow109"
    write_json(destination / "plan.json", plan)
    print(f"FLOW109 PLAN: {plan['selected_count']} selected; runtime NOT_MEASURED")
    if args.flow109_plan_only:
        return 0
    context = execution_context(plan, args.entry_step, args.exit_step,
                                runtime_tool_uses=manifest.get("runtime_tool_uses", manifest.get("tool_uses")),
                                qualification_registry=manifest.get("qualification_registry"))
    if context["schema"] == "vibeic.flow109.execution-window.v1":
        if context["dispatch_kind"] == "canonical_owner_window":
            path = destination / "requests" / (context["context_sha256"] + ".json")
            write_json(path, context)
            os.environ[CONTEXT_ENV] = str(path.resolve())
            os.environ.pop(ATTEMPT_ENV, None)
            owner = context["resolved_rows"][0]["profile"]["dispatch"]["owner_runner"]
            write_json(destination / "owner_route.json", {
                "schema": "vibeic.flow109.owner-route.v1",
                "context_sha256": context["context_sha256"],
                "registry_sha256": context["registry_sha256"],
                "planner_sha256": context["planner_sha256"],
                "owner_runner": owner,
                "entry_step": context["native_entry_step"],
                "exit_step": context["native_exit_step"],
                "component_status": "NOT_MEASURED",
                "flow109_acceptance": "NOT_MEASURED",
                "native_started": False,
            })
            args.entry_step = context["native_entry_step"]
            args.exit_step = context["native_exit_step"]
            return None
        window_admission = source_owned_native_admission(context)
        # Ordinary Default windows use the registered existing native owners.
        # Each launch retains its native input and current-source checks;
        # explicit qualification claims keep the strict inventory path.
        source_owned_window = (
            context["dispatch_kind"] == "ordered_adapters"
            and all(source_owned_native_admission(component_context(
                context, requested_step=row["id"])) is not None
                    for row in context["resolved_rows"])
        )
        if window_admission is None and not source_owned_window:
            _window_inventory(context)
        attempt = _new_attempt(project, context)
        path = destination / "requests" / (context["context_sha256"] + ".json")
        write_json(path, context)
        os.environ[CONTEXT_ENV] = str(path.resolve())
        os.environ[ATTEMPT_ENV] = str(attempt.resolve())
        if context["dispatch_kind"] == "selected_native_sequence":
            layout = _selected_native_sequence(context["resolved_rows"])
            if layout is None:
                raise Flow109Error("FLOW109_WINDOW_DISPATCH_UNSUPPORTED",
                                   "selected native sequence changed")
            write_json(destination / "admission.json", window_admission or {
                "status": "NOT_MEASURED", "reason": "PER_LAUNCH_REVALIDATION_REQUIRED",
                "context_sha256": context["context_sha256"], "native_started": False})
            components = []
            for row in context["resolved_rows"][:layout["adapter_count"]]:
                current = component_context(context, requested_step=row["id"])
                adapter = row["profile"]["dispatch"]["adapter"]
                try:
                    from flow109_admission import require_admission, AdmissionRefusal
                    if source_owned_native_admission(current) is None:
                        require_admission(project, current)
                    from importlib import import_module
                    result = import_module(adapter).execute(project, current)
                except AdmissionRefusal as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": str(exc),
                              "qualification": exc.report, "native_started": False,
                              "context_sha256": current["context_sha256"],
                              "flow109_acceptance": "NOT_MEASURED",
                              "whole_flow_acceptance": "NOT_MEASURED"}
                except Flow109Error as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": exc.detail,
                              "native_started": False,
                              "context_sha256": current["context_sha256"],
                              "flow109_acceptance": "NOT_MEASURED",
                              "whole_flow_acceptance": "NOT_MEASURED"}
                if (not isinstance(result, dict)
                        or result.get("step_id") != row["id"]
                        or result.get("component_status") not in (
                            "PASS", "FAIL", "NOT_MEASURED")
                        or result.get("flow109_acceptance") != "NOT_MEASURED"):
                    raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", adapter)
                # The window identity, rather than a one-row derived identity,
                # binds this retained component into the later aggregate.
                result = dict(result, context_sha256=context["context_sha256"])
                components.append(result)
                write_json(destination / "components" / (row["id"] + ".json"), result)
                if result["component_status"] != "PASS":
                    for later in context["resolved_rows"][len(components):]:
                        missing = _not_executed_component(
                            context, later, "not executed: an earlier row stopped")
                        components.append(missing)
                        write_json(destination / "components" / (later["id"] + ".json"), missing)
                    finished = _attempt_result(context, components)
                    _finish_attempt(attempt, finished)
                    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[
                        finished["component_status"]]
            args.entry_step = layout["backend_entry_step"]
            args.exit_step = layout["backend_exit_step"]
            return None
        if context["dispatch_kind"] == "ordered_adapters":
            components = []
            for row in context["resolved_rows"]:
                current = component_context(context, requested_step=row["id"])
                adapter = row["profile"]["dispatch"]["adapter"]
                try:
                    from flow109_admission import require_admission, AdmissionRefusal
                    if source_owned_native_admission(current) is None:
                        require_admission(project, current)
                    from importlib import import_module
                    result = import_module(adapter).execute(project, current)
                except AdmissionRefusal as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": str(exc),
                              "qualification": exc.report, "native_started": False,
                              "flow109_acceptance": "NOT_MEASURED"}
                except Flow109Error as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": exc.detail,
                              "native_started": False,
                              "flow109_acceptance": "NOT_MEASURED"}
                if (not isinstance(result, dict)
                        or result.get("component_status") not in ("PASS", "FAIL", "NOT_MEASURED")
                        or result.get("flow109_acceptance") != "NOT_MEASURED"):
                    raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", adapter)
                components.append(result)
                write_json(destination / "components" / (row["id"] + ".json"), result)
                if result["component_status"] != "PASS":
                    break
            aggregate = ("FAIL" if any(x["component_status"] == "FAIL" for x in components)
                         else "PASS" if len(components) == len(context["resolved_rows"])
                         and all(x["component_status"] == "PASS" for x in components)
                         else "NOT_MEASURED")
            _finish_attempt(attempt, {
                "schema": "vibeic.flow109.window-attempt-result.v1",
                "context_sha256": context["context_sha256"],
                "component_status": aggregate, "components": components,
                "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
                "bounded": True, "delivery_accepted": False})
            return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[aggregate]
        write_json(destination / "admission.json", window_admission or {
            "status": "NOT_MEASURED", "reason": "PER_LAUNCH_REVALIDATION_REQUIRED",
            "context_sha256": context["context_sha256"], "native_started": False})
        args.entry_step = context["native_entry_step"]
        args.exit_step = context["native_exit_step"]
        return None
    owner_dispatch = _canonical_owner_dispatch(context["resolved_row"])
    if owner_dispatch is not None:
        path = destination / "requests" / (context["context_sha256"] + ".json")
        write_json(path, context)
        os.environ[CONTEXT_ENV] = str(path.resolve())
        os.environ.pop(ATTEMPT_ENV, None)
        write_json(destination / "owner_route.json", {
            "schema": "vibeic.flow109.owner-route.v1",
            "context_sha256": context["context_sha256"],
            "registry_sha256": context["registry_sha256"],
            "planner_sha256": context["planner_sha256"],
            "owner_runner": owner_dispatch["owner_runner"],
            "native_step_id": owner_dispatch["native_step_id"],
            "entry_step": owner_dispatch["owner_entry_step"],
            "exit_step": owner_dispatch["owner_exit_step"],
            "component_status": "NOT_MEASURED",
            "flow109_acceptance": "NOT_MEASURED",
            "native_started": False,
        })
        args.entry_step = owner_dispatch["owner_entry_step"]
        args.exit_step = owner_dispatch["owner_exit_step"]
        return None
    os.environ.pop(ATTEMPT_ENV, None)
    # Source-registered Default component owners retain their existing native
    # input/tool/consumer checks, like canonical_owner_window.  Every route
    # that explicitly claims generic qualification remains on strict admission.
    admission = source_owned_native_admission(context)
    if admission is None:
        from flow109_admission import require_admission
        admission = require_admission(project, context)
        if not isinstance(admission, dict) or admission.get("status") != "PASS":
            raise Flow109Error("FLOW109_ADMISSION_REFUSED", "qualification did not return PASS")
    write_json(destination / "admission.json", admission)
    path = destination / "requests" / (context["context_sha256"] + ".json")
    write_json(path, context)
    os.environ[CONTEXT_ENV] = str(path.resolve())
    adapter = context['resolved_row']['profile']['dispatch'].get('adapter')
    if adapter:
        # Only source-owned dispatch data selects this bounded adapter. It
        # calls existing producers/consumers and retains their actual receipts.
        from importlib import import_module
        result = import_module(adapter).execute(project, context)
        if (not isinstance(result, dict)
                or result.get('component_status') not in ('PASS', 'FAIL', 'NOT_MEASURED')
                or result.get('flow109_acceptance') != 'NOT_MEASURED'):
            raise Flow109Error('FLOW109_COMPONENT_RESULT_INVALID', adapter)
        write_json(destination / 'components' / (context['requested_step'] + '.json'), result)
        row_status = result['component_status']
        if context['requested_step'] == 'D45':
            # D45 is the first explicitly supported bounded Default-row result.
            # Its row-local consumer re-opens and validates the native receipt;
            # this does not change Flow109 or whole-IC acceptance.
            completion = import_module(adapter).consume_default_row_completion(
                project, context, result)
            write_json(destination / 'default_rows' / 'D45.json', completion)
            row_status = completion['default_row_status']
        print(f"FLOW109 {context['requested_step']}: component {result['component_status']}; "
              f"Default row {row_status}; flow acceptance NOT_MEASURED")
        return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[row_status]
    args.entry_step = context["native_step_id"]
    args.exit_step = context["native_step_id"]
    return None
