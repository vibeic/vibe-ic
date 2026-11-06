"""Produce declared child macros through the public IP entry, then link native views.

LibreLane hardens each child; this adapter only orders the existing public runs
and connects their final State to the supplied MACROS configuration. A child's
native failure is returned unchanged; missing inputs or outputs are NOT_MEASURED.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import shutil
import sys


def supplied_configs(project):
    from floorplan_contract import _iter_input_files

    configs = {}
    for _, path, text in _iter_input_files(project):
        if path.suffix.lower() != ".json":
            continue
        try:
            value = json.loads(text)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("DESIGN_NAME"):
            configs[value["DESIGN_NAME"]] = (path, value)
    return configs


def resolve_config(path, raw, pdk):
    from librelane.config.preprocessor import process_config_dict

    resolved = process_config_dict({**raw, "PDK": pdk}, {"DESIGN_DIR": str(path.parent), "PDK": pdk,
        "PDK_ROOT": os.environ.get("PDK_ROOT", "")})
    for key in ("DESIGN_DIR", "PDK_ROOT"):
        if key not in raw:
            resolved.pop(key, None)
    return resolved


def paths(value):
    if isinstance(value, dict):
        return [p for item in value.values() for p in paths(item)]
    if isinstance(value, list):
        return [p for item in value for p in paths(item)]
    return [Path(value)] if isinstance(value, str) else []


def view_files(macro):
    return [p for key in ("gds", "lef", "lib", "nl", "spef") for p in paths(macro.get(key))]


def _link(source, target):
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.resolve() == source.resolve():
        return
    target.symlink_to(source)


def handover(state, definition, default_corner):
    """Keep corner distinctions; a wildcard alias names the default library only."""
    for kind in ("gds", "lef", "nl", "lib", "spef"):
        requested = definition.get(kind)
        if not requested:
            if kind in {"gds", "lef", "lib"}:
                raise FileNotFoundError(f"Supplied MACROS has no {kind} destination")
            continue
        actual = state.get(kind)
        if not actual or any(not p.is_file() for p in paths(actual)):
            raise FileNotFoundError(f"Child final native State has no {kind} output")
        if not isinstance(actual, dict):
            for destination in paths(requested):
                _link(actual, destination)
            continue
        if not isinstance(requested, dict):
            raise ValueError(f"Cornered native {kind} needs cornered MACROS destinations")
        consumed = {}
        for pattern, destinations in requested.items():
            matches = {corner: value for corner, value in actual.items()
                       if fnmatch.fnmatchcase(corner, pattern) or corner == pattern.removesuffix("_*")}
            if not matches:
                raise FileNotFoundError(f"Child final native {kind} has no corner matching {pattern}")
            alias_corner = default_corner if default_corner in matches else next(iter(matches))
            for corner, value in matches.items():
                sources = paths(value)
                targets = paths(destinations)
                if len(sources) != len(targets):
                    raise ValueError(f"Native {kind} {corner} and configured destination counts differ")
                linked = []
                for source, target in zip(sources, targets):
                    # A single '*' Liberty filename cannot hold several libraries.
                    # Preserve it for the native default; retain every other corner.
                    if len(matches) > 1 and corner != alias_corner:
                        target = target.parent / corner / target.name
                    _link(source, target)
                    linked.append(str(target))
                consumed[corner if kind == "lib" or len(matches) > 1 else pattern] = linked
        definition[kind] = consumed


def _child(project, name, config, raw, pdk, commands):
    from flow_native_adapters import testbenches
    from sim_activity_dump import dut_instance

    child = project / "work/flow/children" / name
    summary = child / "reports/flow_engine.json"
    code = None
    if not summary.is_file():
        child.mkdir(parents=True, exist_ok=True)
        docs = project / "input/docs"
        if docs.is_dir():
            shutil.copytree(docs, child / "input/docs", dirs_exist_ok=True)
        resolved = resolve_config(config, raw, pdk)
        # Reuse the supplied HDL, including its headers, through the existing
        # source-consumption path. Physical views are never staged or copied.
        for source in paths(resolved.get("VERILOG_FILES")):
            rtl = child / "input/rtl" / source.name
            rtl.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, rtl)
            for header in [*source.parent.glob("*.vh"), *source.parent.glob("*.svh")]:
                shutil.copyfile(header, rtl.parent / header.name)
        for bench in testbenches(project, {}):
            if bench.suffix in {".v", ".sv"} and dut_instance(bench.read_text(), name):
                target = child / "phase2/stage1/sim" / bench.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(bench, target)
        declaration = child / "plugin_output/declaration.json"
        declaration.parent.mkdir(parents=True, exist_ok=True)
        declaration.write_text(json.dumps({"top_module": name}) + "\n")
        overrides = child / "work/flow/native_overrides.json"
        overrides.parent.mkdir(parents=True, exist_ok=True)
        overrides.write_text(json.dumps(resolved, default=str, indent=2) + "\n")
        entry = Path(__file__).with_name("vibe_ic_one_shot_runner.py")
        completed = commands.run([sys.executable, entry, child, "--route", "ip",
            "--delivery-target", "ip_hardmacro", "--entry-step", "D1", "--exit-step", "37.5ip",
            "--ic-name", name, "--top-name", name, "--pdk", pdk,
            "--from", "requirements_and_delivery_route", "--to", "ip_release_views_and_documentation"])
        code = completed.returncode if completed is not None else None
    if not summary.is_file():
        if code not in (None, 0, 2):
            return child, {}, code
        raise FileNotFoundError(f"Child {name} public entry left no flow_engine.json")
    return child, json.loads(summary.read_text()), code


def produce(project, directory, commands, route):
    from ip_integration_check import audit

    l9_path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text()) if l9_path.is_file() else {}
    fields = l9.get("fields", l9)
    top = route.get("top_name") or fields.get("top_module")
    declared = [m for m in fields.get("hard_macros", [])
                if isinstance(m, dict) and m.get("hardening_required") is True and m.get("name") != top]
    configs = supplied_configs(project)
    if not declared:
        return None
    from hardmacro_supply_intent import _MACRO_RE, load_macro_lefs
    staged_names = {m.group(1) for text in load_macro_lefs(project) for m in _MACRO_RE.finditer(text)}
    if {m["name"] for m in declared} <= staged_names and audit(project)["rc"] == 0:
        return None
    if top not in configs:
        raise FileNotFoundError(f"No supplied native configuration for wrapper {top}")
    wrapper_path, wrapper_raw = configs[top]
    l19 = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    constraints = json.loads(l19.read_text()) if l19.is_file() else {}
    pdk = route.get("pdk") or constraints.get("fields", constraints).get("pdk_target") or wrapper_raw.get("PDK")
    if not pdk:
        raise FileNotFoundError("Child hardening requires the wrapper's declared PDK")
    from flow_config import _pdk_name
    pdk = _pdk_name(pdk)
    wrapper = resolve_config(wrapper_path, wrapper_raw, pdk)
    overrides = project / "work/flow/native_overrides.json"
    current = json.loads(overrides.read_text()) if overrides.is_file() else {}
    packages, reports, native_steps, tool_seconds = {}, [], [], 0.0
    for macro in declared:
        name = macro["name"]
        definition = wrapper.get("MACROS", {}).get(name)
        if not definition:
            raise FileNotFoundError(f"Supplied wrapper MACROS does not declare {name}")
        previous = current.get("MACROS", {}).get(name)
        if previous and all(p.is_file() for p in view_files(previous)):
            definition.update({k: previous[k] for k in ("gds", "lef", "lib", "nl", "spef") if k in previous})
        files = view_files(definition)
        complete = all(definition.get(k) for k in ("gds", "lef", "lib")) and all(p.is_file() for p in files)
        if not complete:
            if name not in configs:
                raise FileNotFoundError(f"Child {name}: no supplied native hardening configuration or RTL")
            child, summary, code = _child(project, name, *configs[name], pdk, commands)
            if (child / "reports/flow_engine.json").is_file():
                reports.append(str(child / "reports/flow_engine.json"))
            native_steps.extend(run for row in summary.get("steps", [])
                                for run in row.get("native_steps", []) if run.get("ran"))
            tool_seconds += summary.get("tool_seconds", 0.0) if code is not None else 0.0
            failed = [r for r in summary.get("steps", []) if r.get("status") == "FAIL"]
            if failed or summary.get("fail") or code not in (None, 0, 2):
                native_steps.extend({"name": row.get("title", row["name"]),
                    "ran": row.get("tool_ran", True), "exit_code": row.get("tool_exit_code"),
                    "status": row["status"]} for row in failed)
                return {**commands.result(reports=reports, detail=f"Child {name} native failure: " +
                    ("; ".join(r.get("detail") or r.get("title", r["name"]) for r in failed)
                     or f"public entry exited {code}; see child command log")),
                    "ran": True, "exit_code": next((r.get("tool_exit_code") for r in failed
                        if r.get("tool_exit_code")), code or 1), "native_steps": native_steps,
                    "tool_seconds": tool_seconds}
            final = next((child / "steps" / row["name"] / "state_out.json"
                          for row in reversed(summary.get("steps", []))
                          if (child / "steps" / row["name"] / "state_out.json").is_file()), None)
            if final is None:
                raise FileNotFoundError(f"Child {name} has no native final State")
            state = json.loads(final.read_text())
            native_configs = (json.loads(p.read_text()) for p in child.glob("steps/**/config.json"))
            default_corner = next((c["DEFAULT_CORNER"] for c in native_configs
                                   if c.get("DEFAULT_CORNER")), configs[name][1].get("DEFAULT_CORNER"))
            if isinstance(state.get("lib"), dict) and not default_corner:
                raise FileNotFoundError(f"Child {name} has no native default-corner configuration")
            handover(state, definition, default_corner)
            files = view_files(definition)
        packages[name] = files
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text(json.dumps({**wrapper, **current, "MACROS": wrapper["MACROS"]}, indent=2, default=str) + "\n")
    report = audit(project, packages=packages)
    path = directory / "macro_views.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return {**commands.result({"macro_count": len(packages)}, [*reports, path],
        "Child native outputs linked to the supplied MACROS paths; native corner views retained."),
        "ran": True, "exit_code": report["rc"], "native_steps": native_steps,
        "tool_seconds": tool_seconds}
