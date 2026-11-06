"""Produce declared child macros through the public IP entry, then use native views.

LibreLane hardens each child; this adapter only orders the existing public runs
and connects their final State to the supplied MACROS configuration. A child's
native failure is returned unchanged; missing inputs or outputs are NOT_MEASURED.
Authored child RTL and hooks use the normal project layout under
work/flow/children/<name>/; each run_* receives fresh copies of those inputs.
A supplied expert_reference_tb.py may also sit beside the child's config.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import re
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


def native_hierarchy(config, directory, commands):
    """Read Slang's elaborated instance bodies, before synthesis flattens them."""
    directory.mkdir(parents=True, exist_ok=True)
    arguments = ["--top", config["DESIGN_NAME"], "--dump-ast", "--ast-compilation-only",
                 *(config.get("SLANG_ARGUMENTS") or [])]
    arguments += ["-G" + value for value in config.get("SYNTH_PARAMETERS") or []]
    defines = [*(config.get("VERILOG_DEFINES") or []), "__librelane__", "__pnr__",
               "PDK_" + config["PDK"].replace("-", "_"), "SCL_" + config["STD_CELL_LIBRARY"]]
    if config.get("VERILOG_POWER_DEFINE"):
        defines.append(config["VERILOG_POWER_DEFINE"])
    arguments += ["-D" + value for value in defines]
    arguments += ["-I" + str(path) for path in paths(config.get("VERILOG_INCLUDE_DIRS"))]
    arguments += [str(path) for path in paths(config.get("VERILOG_FILES"))]
    # Slang's response-file parser owns quoting for paths and parameter strings.
    (directory / "arguments.f").write_text("\n".join(json.dumps(value) for value in arguments) + "\n")
    before = commands.seconds
    completed = commands.run(["yosys", "-Q", "-T", "-p", "read_slang -f arguments.f"], cwd=directory)
    if completed is not None and commands.records:
        commands.records[-1]["tool_seconds"] = commands.seconds - before
    if completed is None or completed.returncode:
        raise FileNotFoundError(f"Cannot resolve {config['DESIGN_NAME']} parameters: native hierarchy failed; see command log")
    start = re.search(r"(?m)^\{", completed.stdout)
    try:
        tree = json.JSONDecoder().raw_decode(completed.stdout[start.start():])[0] if start else {}
    except ValueError as exc:
        raise FileNotFoundError("Native hierarchy left no readable elaborated AST") from exc
    if tree.get("kind") != "Root":
        raise FileNotFoundError("Native hierarchy left no elaborated instance root")
    (directory / "hierarchy.json").write_text(json.dumps(tree, indent=2) + "\n")
    return tree


def instance_parameters(tree, names, top=None):
    """Keep native constant literals; never evaluate a source expression here."""
    found = {name: [] for name in names}
    literal = re.compile(r'(?:[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|'
                         r"\d+'s?[bodh][+-]?[0-9a-fA-F_]+|'[01]|\"(?:[^\"\\]|\\.)*\")")

    def walk(node, path=""):
        if isinstance(node, list):
            for item in node:
                walk(item, path)
        elif isinstance(node, dict):
            if node.get("kind") == "Instance":
                path = (path + "." if path else "") + node["name"]
                body = node.get("body")
                if not isinstance(body, dict):
                    raise FileNotFoundError(f"Unresolved native instance body at {path}")
                name = body.get("name")
                if name in found:
                    values = {}
                    for member in body.get("members", []):
                        if member.get("isLocal") or member.get("kind") not in {"Parameter", "TypeParameter"}:
                            continue
                        value = str(member.get("value", ""))
                        if member["kind"] == "TypeParameter" or not literal.fullmatch(value):
                            raise FileNotFoundError(f"Unresolved parameter {path}.{member['name']}: {value!r}")
                        values[member["name"]] = value
                    found[name].append((path, values))
            for value in node.values():
                walk(value, path)

    roots = [member for member in tree.get("members", []) if member.get("kind") == "Instance"
             and member.get("body", {}).get("name") == top] if top else [tree]
    if len(roots) != 1:
        raise FileNotFoundError(f"Native hierarchy did not resolve the selected top {top}")
    walk(roots)
    resolved = {}
    for name, instances in found.items():
        if not instances:
            raise FileNotFoundError(f"Child {name}: no resolved instance in the parent's native hierarchy")
        values = instances[0][1]
        if any(bound != values for _, bound in instances[1:]):
            raise FileNotFoundError(f"Child {name}: instances bind different parameter values: {instances}")
        resolved[name] = values
    return resolved


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


def _child(project, name, config, raw, pdk, commands, library=None, parameters=None):
    from librelane.flows import Flow
    from flow_native_adapters import testbenches
    from flow_config import resolve_rtl_inputs
    from formal_property_run import resolve_include_headers
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
    # The child workspace owns authored inputs; every public run stays fresh.
    supplied = paths(resolved.get("VERILOG_FILES"))
    sources = (resolve_rtl_inputs(root)[0] if (root / "phase2/stage1/rtl").is_dir()
               else supplied)
    include_dirs = list(dict.fromkeys([*(path.parent for path in [*sources, *supplied]),
                                      *paths(resolved.get("VERILOG_INCLUDE_DIRS"))]))
    headers = resolve_include_headers(sources, include_dirs)
    if parameters is not None:
        supplied_parameters = native.get("SYNTH_PARAMETERS") or []
        explicit = {value.split("=", 1)[0].strip() for value in supplied_parameters}
        candidate = [f"{key}={value}" for key, value in parameters.items() if key not in explicit]
        selected = native.copy(VERILOG_FILES=list(map(str, sources)),
            VERILOG_INCLUDE_DIRS=list(map(str, include_dirs)), SYNTH_PARAMETERS=candidate + supplied_parameters)
        actual = instance_parameters(native_hierarchy(selected, child / "parameter_resolution", commands),
                                     [name], top=name)[name]
        if set(actual) != set(parameters):
            raise FileNotFoundError(f"Child {name}: parent hierarchy did not resolve child parameters "
                                   f"{sorted(set(actual) - set(parameters))}")
        for key in explicit:
            if key not in parameters or actual.get(key) != parameters[key]:
                raise FileNotFoundError(f"Child {name}: supplied SYNTH_PARAMETERS conflicts with parent binding "
                                       f"for {key}: {actual.get(key)!r} versus {parameters.get(key)!r}")
        if actual != parameters:
            raise FileNotFoundError(f"Child {name}: native child parameter values {actual} cannot implement "
                                   f"the parent's resolved bindings {parameters}")
        resolved["SYNTH_PARAMETERS"] = [f"{key}={value}" for key, value in parameters.items()]
    for source in sources:
        rtl = child / "input/rtl" / source.name
        rtl.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, rtl)
    for header in headers:
        relative = next((header.relative_to(directory) for directory in include_dirs
                         if header.is_relative_to(directory)), Path(header.name))
        target = child / "input/rtl" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(header, target)
    # Native config must follow the fresh run's normal Phase 2 source selection.
    resolved.pop("VERILOG_FILES", None)
    resolved.pop("VERILOG_INCLUDE_DIRS", None)
    for workspace in (project, root):
        for bench in testbenches(workspace, {}):
            if bench.suffix in {".v", ".sv"} and dut_instance(bench.read_text(), name):
                target = child / "phase2/stage1/sim" / bench.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(bench, target)
    hooks = [workspace / "phase2/stage1/sim_professional" / name / "expert_reference_tb.py"
             for workspace in (root, project)]
    hooks.append(config.parent / "expert_reference_tb.py")
    for hook in hooks:
        if hook.is_file():
            target = child / "phase2/stage1/sim_professional" / name / hook.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(hook, target)
            break
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
    from catalog_glue_closure_resolver import _strip_comments, build_index
    from ip_integration_check import audit
    from librelane.flows import Flow
    from flow_config import resolve_rtl_inputs

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
        if not wrapper.get("MACROS", {}).get(name):
            raise FileNotFoundError(f"Supplied wrapper MACROS does not declare {name}")
        if name not in configs:
            raise FileNotFoundError(f"Child {name}: no supplied native hardening configuration or RTL")
    parent = {**wrapper, **current, "MACROS": {}}
    if "VERILOG_FILES" not in current:
        if (project / "phase2/stage1/rtl").is_dir():
            parent["VERILOG_FILES"] = list(map(str, resolve_rtl_inputs(project)[0]))
    # Parent-selected definitions win; read missing child implementations for
    # elaboration while their physical views are still being produced.
    supplied = list(dict.fromkeys(paths(parent.get("VERILOG_FILES"))))
    known = set()
    def definitions(path):
        index = build_index({path: _strip_comments(path.read_text())})
        return {(kind, name) for kind in ("mod_def", "pkg_def", "macro_def") for name in index[kind]}
    for source in supplied:
        known.update(definitions(source))
    for macro in declared:
        child_config = resolve_config(*configs[macro["name"]], pdk, library)
        for source in paths(child_config.get("VERILOG_FILES")):
            names = definitions(source)
            if source in supplied or (names and names <= known):
                continue
            supplied.append(source)
            known.update(names)
    parent["VERILOG_FILES"] = list(map(str, supplied))
    include_dirs = paths(parent.get("VERILOG_INCLUDE_DIRS"))
    parent["VERILOG_INCLUDE_DIRS"] = list(map(str, dict.fromkeys([
        *include_dirs, *(path.parent for path in paths(parent.get("VERILOG_FILES")))])))
    parent_native = Flow.factory.get("Classic")(parent, design_dir=str(wrapper_path.parent),
        pdk_root=os.environ.get("PDK_ROOT")).config
    parameters = instance_parameters(native_hierarchy(parent_native, directory / "parent_parameters", commands),
                                     [macro["name"] for macro in declared], top=top)
    reports.append(directory / "parent_parameters/hierarchy.json")
    for macro in declared:
        name = macro["name"]
        definition = wrapper.get("MACROS", {}).get(name)
        child, summary, code = _child(project, name, *configs[name], pdk, commands,
                                     library=wrapper.get("STD_CELL_LIBRARY"), parameters=parameters[name])
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
                "tool_seconds": tool_seconds + sum(row.get("tool_seconds", 0) for row in commands.records)}
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
        "tool_seconds": tool_seconds + sum(row.get("tool_seconds", 0) for row in commands.records)}
