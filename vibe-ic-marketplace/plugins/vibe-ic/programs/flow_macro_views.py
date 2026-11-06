"""Produce declared child macros through the public IP entry, then use native views.

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
import tempfile


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


def resolve_config(path, raw, pdk, library=None):
    from librelane.config.preprocessor import process_config_dict

    resolved = process_config_dict({**raw, "PDK": pdk}, {"DESIGN_DIR": str(path.parent), "PDK": pdk,
        "PDK_ROOT": os.environ.get("PDK_ROOT", ""),
        "STD_CELL_LIBRARY": raw.get("STD_CELL_LIBRARY", library)})
    for key in ("DESIGN_DIR", "PDK_ROOT"):
        if key not in raw:
            resolved.pop(key, None)
    if resolved.get("STD_CELL_LIBRARY") is None:
        resolved.pop("STD_CELL_LIBRARY", None)
    return resolved


def paths(value):
    if isinstance(value, dict):
        return [p for item in value.values() for p in paths(item)]
    if isinstance(value, list):
        return [p for item in value for p in paths(item)]
    return [Path(value)] if isinstance(value, (str, os.PathLike)) else []


def view_files(macro):
    return [p for key in ("gds", "lef", "lib", "nl", "spef") for p in paths(macro.get(key))]


def handover(state, definition):
    """Point MACROS directly at native files, keeping corner distinctions."""
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
            definition[kind] = [str(p) for p in paths(actual)]
            continue
        if not isinstance(requested, dict):
            raise ValueError(f"Cornered native {kind} needs cornered MACROS destinations")
        consumed = {}
        for pattern in requested:
            matches = {corner: value for corner, value in actual.items()
                       if fnmatch.fnmatchcase(corner, pattern) or corner == pattern.removesuffix("_*")}
            if not matches:
                raise FileNotFoundError(f"Child final native {kind} has no corner matching {pattern}")
            for corner, value in matches.items():
                consumed[corner if kind == "lib" or len(matches) > 1 else pattern] = [str(p) for p in paths(value)]
        definition[kind] = consumed


def _child(project, name, config, raw, pdk, commands, library=None):
    from librelane.flows import Flow
    from flow_native_adapters import testbenches
    from sim_activity_dump import dut_instance

    root = project / "work/flow/children" / name
    root.mkdir(parents=True, exist_ok=True)
    child = Path(tempfile.mkdtemp(prefix="run_", dir=root))
    summary = child / "reports/flow_engine.json"
    docs = project / "input/docs"
    if docs.is_dir():
        shutil.copytree(docs, child / "input/docs")
    resolved = resolve_config(config, raw, pdk, library)
    native = Flow.factory.get("Classic")(resolved, design_dir=str(config.parent),
        pdk_root=os.environ.get("PDK_ROOT")).config
    supplied_sdc = {p for p in paths(resolved) if p.suffix.lower() == ".sdc"}
    staged_sdc = set()
    for key, value in native.items():
        for index, source in enumerate(paths(value)):
            if source not in supplied_sdc or source in staged_sdc or not source.is_file():
                continue
            target = child / "input/docs/supplied_constraints" / f"{key.lower()}_{index}.sdc"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            staged_sdc.add(source)
    # Stage only supplied design sources; physical views stay in native outputs.
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
    qualification = project / "steps/pdk_library_deck_and_tool_use_qualification/result.json"
    qualified = json.loads(qualification.read_text()) if qualification.is_file() else {}
    library = qualified.get("native_metrics", {}).get("standard_cell_library")
    wrapper = resolve_config(wrapper_path, wrapper_raw, pdk, library)
    overrides = project / "work/flow/native_overrides.json"
    current = json.loads(overrides.read_text()) if overrides.is_file() else {}
    current.pop("MACROS", None)
    if overrides.is_file():
        overrides.write_text(json.dumps(current, indent=2) + "\n")
    packages, reports, native_steps, tool_seconds = {}, [], [], 0.0
    for macro in declared:
        name = macro["name"]
        definition = wrapper.get("MACROS", {}).get(name)
        if not definition:
            raise FileNotFoundError(f"Supplied wrapper MACROS does not declare {name}")
        if name not in configs:
            raise FileNotFoundError(f"Child {name}: no supplied native hardening configuration or RTL")
        child, summary, code = _child(project, name, *configs[name], pdk, commands,
                                     library=wrapper.get("STD_CELL_LIBRARY"))
        if (child / "reports/flow_engine.json").is_file():
            reports.append(str(child / "reports/flow_engine.json"))
        native_steps.extend(run for row in summary.get("steps", [])
                            for run in row.get("native_steps", []) if run.get("ran"))
        tool_seconds += summary.get("tool_seconds", 0.0)
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
        handover(json.loads(final.read_text()), definition)
        packages[name] = view_files(definition)
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text(json.dumps({**wrapper, **current, "MACROS": wrapper["MACROS"]}, indent=2, default=str) + "\n")
    report = audit(project, packages=packages)
    path = directory / "macro_views.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return {**commands.result({"macro_count": len(packages)}, [*reports, path],
        "MACROS points directly at child native outputs; native corner views retained."),
        "ran": True, "exit_code": report["rc"], "native_steps": native_steps,
        "tool_seconds": tool_seconds}
