"""Run the A01-A19 analog track with existing native producers.

This is the analog runner's Default dispatch table. Tool configuration and
design artifacts are inputs; a separately authored qualification registry is
not required to execute. Native errors and missing measurements remain visible.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
import _path_layout as layout

STEPS = tuple(f"A{number:02d}" for number in range(1, 20))
STATUSES = {"PASS", "FAIL", "NOT_MEASURED", "NOT_APPLICABLE"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def _aggregate(rows):
    states = [row["status"] for row in rows]
    if "FAIL" in states:
        return "FAIL"
    if not states or any(state not in ("PASS", "NOT_APPLICABLE") for state in states):
        return "NOT_MEASURED"
    return "PASS"






def _input_views(project, name, step=None):
    paths = list((project / "input").rglob("*"))
    paths += list(layout.generated_docs_dir(project).glob("*.json"))
    if step == "A01":
        from analog_a1_spec_emit import ATTRIBUTION_REL
        paths.append(project / ATTRIBUTION_REL)
    directory = layout.analog_dir(project) / name
    paths += [directory / leaf for leaf in
              ("spec.json", "topology.json", "topology.md", f"{name}.sp", f"tb_{name}.sp")]
    if step in ("A12", "A18"):
        paths += [directory / f"{name}.lvs.cdl",
                  directory / "lvs_provenance.json"]
    if step in STEPS[3:]:
        paths.append(directory / "sizing_inputs.json")
    if step in STEPS[10:]:
        paths.append(directory / "layout_inputs.json")
    if step in ("A06", "A07"):
        paths.append(directory / "measurement_studies.json")
    if step == "A16":
        paths.append(directory / "reliability_inputs.json")
    if step == "A17":
        declaration = directory / "characterization_inputs.json"
        paths.append(declaration)
        from analog_native_physical import _settings
        selected = {**_read(declaration, {}), **_settings(
            {"config": _read(project / "input/analog_flow.json", {})}, "A17", name)}
        if selected.get("ngspice_bin"):
            paths.append(Path(selected["ngspice_bin"]))
    # A configured nominal/calibration deck can live outside the canonical
    # block directory. Retain the actual selected inputs, not only defaults.
    from analog_native_sim import (_config, _selected_config, _inputs, _included_paths,
                                   _testbench_inputs_path, _declared_testbench)
    config = _read(project / "input" / "analog_flow.json", {})
    for selected_step in STEPS[5:10]:
        try:
            selected = (_selected_config(project, {"config": config}, {"name": name}, selected_step)
                        if selected_step == step == 'A08' else
                        _config({"config": config}, {"name": name}, selected_step))
        except (OSError, ValueError):
            selected = _config({"config": config}, {"name": name}, selected_step)
        if selected_step == "A07" and selected.get("nominal_testbench"):
            selected = {**selected, "testbench": selected["nominal_testbench"]}
        if selected_step == "A10" and isinstance(selected.get("calibration"), dict):
            selected = {**selected, **selected["calibration"]}
        netlist, deck, spec = _inputs(project, name, selected)
        paths.extend([netlist, deck, spec])
        paths.extend(_included_paths(deck))
        if selected_step == 'A07' or selected_step == step == 'A08':
            try:
                declaration = _testbench_inputs_path(project, name, selected)
            except ValueError:
                declaration = None  # The producer reports the invalid declaration.
            if declaration is not None:
                paths += [declaration, netlist.parent / "netlist_provenance.json"]
                try:
                    _text, views = _declared_testbench(project, name, selected, netlist.parent)
                    paths.extend(Path(view["path"]) for view in views.values())
                    pvt = selected.get('pvt') or {}
                    if selected_step == 'A08' and isinstance(pvt, dict) and pvt.get('kind') == 'declared_testbench':
                        import analog_declared_pvt as declared
                        section, temperature = declared.coordinates(pvt)[0]
                        sections = pvt['process_sections']
                        _deck, _dut, views = declared.render_corner(project, name, selected, netlist.parent,
                            sections, section, temperature)
                        paths.extend(Path(view['path']) for view in views.values())
                except ValueError:
                    pass  # The producer reports the invalid declaration.
    if step in ("A06", "A07"):
        # The declaration names real study inputs outside input/. Changing
        # one of those inputs must invalidate its retained measurement too.
        selected = _config({"config": config}, {"name": name}, step)
        studies = selected.get("measurement_studies")
        if studies is None:
            studies = _read(directory / "measurement_studies.json", [])
        if isinstance(studies, dict):
            studies = studies.get("studies", [])
        def referenced(value):
            if not isinstance(value, str) or not value:
                return None
            path = Path(value)
            path = path if path.is_absolute() else project / path
            paths.append(path)
            return path
        for study in studies if isinstance(studies, list) else []:
            if not isinstance(study, dict):
                continue
            referenced(study.get("testbench"))
            settings_path = referenced(study.get("settings"))
            settings = _read(settings_path, {}) if settings_path else {}
            if isinstance(settings, dict):
                referenced(settings.get("testbench"))
            bindings_path = referenced(study.get("bindings"))
            bindings = _read(bindings_path, {}) if bindings_path else {}
            if isinstance(bindings, dict) and isinstance(bindings.get("source"), dict):
                referenced(bindings["source"].get("path"))
            result_path = referenced(study.get("result"))
            record = _read(result_path, {}) if result_path else {}
            if not isinstance(record, dict):
                continue
            records = [record]
            for point in record.get("points") or []:
                if isinstance(point, dict):
                    path = referenced(point.get("path"))
                    data = _read(path, {}) if path else {}
                    if isinstance(data, dict):
                        records.append(data)
            for data in records:
                for view in (data.get("native_inputs") or {}).values():
                    if isinstance(view, dict):
                        referenced(view.get("path"))
                for execution in data.get("executions") or []:
                    if isinstance(execution, dict):
                        referenced(execution.get("log"))
                if isinstance(data.get("capture"), dict):
                    referenced(data["capture"].get("path"))
    return {str(path): _sha(path) for path in paths if path.is_file()}


def _output_views(result):
    paths = []
    for value in result.get("outputs", []):
        path = Path(value)
        paths.extend(path.rglob("*")) if path.is_dir() else paths.append(path)
    return {str(path): _sha(path) for path in paths if path.is_file()}



def _local_ngspice_startup(project, cwd, image):
    """Select ngspice's existing startup stream from the attested PDK."""
    import analog_pdk_availability as availability
    from declared_pdk_is_the_pdk_used_check import declared_target

    root = availability.local_pdks_root(image)
    if root is None:
        return {}, None
    target, _ = declared_target(project)
    # Staged model libraries do not replace the runtime technology's startup.
    # Use the same installed-PDK selection as the default path; keep model
    # resolution and its project-first precedence unchanged.
    selected = availability.resolve_pdk(target, container='')
    if not selected.get('available') or selected.get('source') != 'container_installed':
        return {}, None  # Project-staged/builtin models keep their existing startup.
    init = Path(cwd) / '.spiceinit' if cwd is not None else None
    if init is None or not init.is_file():
        init = Path(selected['pdk_root']) / 'libs.tech/ngspice/.spiceinit'
    environment = {'PDK_ROOT': root, 'PDK': selected['matched_dir']}
    if not init.is_file():
        # Compiled models need the PDK's startup to register their device types.
        # Built-in SPICE models can still run without an optional startup.
        osdi = next((path for path in init.parent.rglob('*.osdi') if path.is_file()), None)
        if osdi is not None:
            raise ValueError(f'NGSPICE_NATIVE_INIT_MISSING: {init} (required by {osdi})')
        return environment, None
    environment['SPICE_USERINIT_DIR'] = str(init.parent)
    return environment, {'path': str(init), 'sha256': _sha(init)}


class NativeCommands:
    """One subprocess seam: retain the tool's command, output and exit status."""

    def __init__(self, project, destination, container, image="", step=None):
        self.project = Path(project)
        self.destination = Path(destination)
        self.container = container
        self.image = image
        self.step = step
        self.native_inputs = {}
        self.count = 0

    def __call__(self, program, argv, *, cwd=None, outputs=None, input_text=None):
        self.count += 1
        argv = [str(item) for item in argv]
        cwd = Path(cwd or self.project)
        if program.startswith("@"):
            tool = program[1:]
            command = [tool, *argv]
        else:
            command = [sys.executable, str(HERE / program), *argv]
        if self.container:
            # Keep model paths and the Python/native toolchain in the same
            # environment. The continuation project is mounted at this path.
            if not program.startswith("@"):
                command[0] = "python3"
            socket = Path("/var/run/docker.sock")
            group = socket.stat().st_gid if socket.exists() else os.getgid()
            command = ["docker", "exec", "--user", f"{os.getuid()}:{group}",
                       "-e", "PYTHONDONTWRITEBYTECODE=1",
                       *(["-e", "VIBEIC_EDA_IMAGE=" + self.image] if self.image else []),
                       "-w", str(cwd), self.container, "bash", "-lc",
                       'exec "$@"', "analog-native", *command]
        log = self.destination / f"{self.count:02d}-{Path(program).stem.lstrip('@')}.log"
        started = time.monotonic()
        native_init, startup_environment = None, {}
        try:
            environment = dict(os.environ)
            if self.image:
                environment["VIBEIC_EDA_IMAGE"] = self.image
            native_tool = program[1:] if program.startswith("@") else ""
            if program == "@env":
                native_tool = next((item for item in argv
                                    if not re.match(r"^[A-Za-z_]\w*=", item)), "")
            if (self.step in ("A02", "A05", "A06", "A07", "A08", None)
                    and Path(native_tool).name == "ngspice" and not self.container):
                startup_environment, native_init = _local_ngspice_startup(self.project, cwd, self.image)
                environment.update(startup_environment)
                if native_init:
                    self.native_inputs[native_init['path']] = native_init['sha256']
            completed = subprocess.run(command, cwd=cwd, env=environment,
                                       capture_output=True, text=True, errors="replace",
                                       input=input_text)
            rc, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except OSError as exc:
            rc, stdout, stderr = 127, "", str(exc)
        log.write_text(stdout + stderr)
        expected = [Path(path) if Path(path).is_absolute() else self.project / path
                    for path in (outputs or [])]
        missing = [str(path) for path in expected if not path.is_file()]
        return {"argv": command, "cwd": str(cwd), "returncode": rc,
                "stdout": stdout, "stderr": stderr, "log": str(log),
                "log_sha256": _sha(log), "duration_s": time.monotonic() - started,
                "outputs": {str(path): _sha(path) for path in expected if path.is_file()},
                "missing_outputs": missing, "native_init": native_init,
                "native_environment": startup_environment}




def _a18_metrics(project, evidence):
    """Compare native top connectivity and route lengths with declared limits."""
    keys = ("analog_top_pad_core_connectivity_errors", "analog_sensitive_route_constraints")
    rows = {key: {"status": "NOT_MEASURED", "reason": "Native measurement absent"} for key in keys}
    count = evidence.get("checks", {}).get(keys[0])
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        rows[keys[0]] = {"status": "PASS" if count == 0 else "FAIL", "value": count, "unit": "count"}
    declaration = _read(Path(project) / "requirements/analog_top_route/analog_sensitive_route_constraints.json", {})
    bounds, units = declaration.get("limits", {}), declaration.get("units", {})
    routes = evidence.get("route_measurements", [])
    if (isinstance(bounds, dict) and bounds and isinstance(units, dict)
            and isinstance(routes, list) and routes
            and len({row.get("net") for row in routes}) == len(routes)
            and {row.get("net") for row in routes} == set(bounds) == set(units)):
        comparisons = []
        for row in routes:
            net = row["net"]
            value, limits = row.get("length_um"), bounds[net]
            result = {"net": net, "value": value, "unit": "um", "status": "NOT_MEASURED"}
            if (units[net] == "um" and isinstance(value, (int, float))
                    and not isinstance(value, bool) and math.isfinite(value) and value >= 0
                    and isinstance(limits, dict)):
                low, high = limits.get("min"), limits.get("max")
                declared = [limit for limit in (low, high) if limit is not None]
                if (declared and all(isinstance(limit, (int, float))
                        and not isinstance(limit, bool) and math.isfinite(limit) for limit in declared)
                        and (low is None or high is None or low <= high)):
                    result["status"] = "FAIL" if (low is not None and value < low
                        or high is not None and value > high) else "PASS"
            comparisons.append(result)
        rows[keys[1]] = {"status": _aggregate(comparisons), "routes": comparisons}
    return {"status": _aggregate(list(rows.values())), "metrics": rows}


def _views(step, project, block, options, run):
    name = block.get("name") or block.get("block")
    directory = layout.analog_dir(project) / name
    if step == "A18":
        if options["features"].get("digital_physical") is True:
            return {"status": "NOT_APPLICABLE", "detail":
                    "The declared mixed-signal digital top owns pad/power integration.",
                    "outputs": []}
        import analog_macro_top_gen as top
        from analog_macro_top_run import RUN_RECORD
        import copy
        settings = options["config"].get("analog_top", {})
        if "a18_result" in options:
            result = copy.deepcopy(options["a18_result"])
            if not result.get("executions"):
                return result
            generated = _read(project / top.RECORD)
            execution = result["executions"][0]
            evidence = result["native_evidence"]
            status = result["status"]
            outputs = result["outputs"]
        else:
            try:
                generated = top.generate(project)
            except (OSError, ValueError, TypeError, KeyError, top.Refusal) as exc:
                result = {"status": "NOT_MEASURED", "detail": str(exc), "outputs": [],
                          "reason": getattr(exc, "code", "A18_DECLARATION_INVALID"),
                          "native_inputs": {}, "metric_acceptance": {
                              "status": "NOT_MEASURED", "metrics": {}, "reason": str(exc)}}
                write_json(project / top.RECORD, {"verdict": "REFUSED", **result})
                options["a18_result"] = result
                return result
            receipt = project / RUN_RECORD
            receipt.unlink(missing_ok=True)
            execution = run("analog_macro_top_run.py", [str(project)], outputs=[str(receipt)])
            evidence = _read(receipt, {})
            if not isinstance(evidence, dict):
                evidence = {}
            outputs = list(generated["outputs"]) + [str(project / top.RECORD), str(receipt)]
            native_outputs = evidence.get("outputs", {})
            outputs += list(native_outputs) if isinstance(native_outputs, dict) else []
            status = evidence.get("component_status", "NOT_MEASURED")
            if status not in STATUSES:
                status = "NOT_MEASURED"
            if execution["returncode"] or execution["missing_outputs"]:
                status = "FAIL"
            if any(not Path(path).is_file() or _sha(path) != digest
                   for path, digest in generated["inputs"].items()):
                status = "FAIL"
                evidence["reason"] = "A18_INPUT_CHANGED_DURING_EXECUTION"
            if status == "PASS" and (not native_outputs or any(
                    not Path(path).is_file() or _sha(path) != digest
                    for path, digest in native_outputs.items())):
                status = "FAIL"
            options["a18_result"] = {"status": status, "outputs": outputs,
                                     "executions": [execution], "native_evidence": evidence}
        acceptance = _a18_metrics(project, evidence)
        status = _aggregate([{"status": status}, acceptance])
        result = {"status": status, "detail": evidence.get("detail") or evidence.get("reason")
                  or "A18 native implementation receipt absent", "outputs": outputs,
                  "executions": [execution], "native_evidence": evidence,
                  "measurements": acceptance}
        return result
    if step == "A19":
        prior = options["previous_results"]
        rows = [{"step": sid, **prior.get(sid, {}).get(name, {
            "status": "NOT_MEASURED", "detail": "step not executed in this continuation"})}
                for sid in STEPS[:-1]]
        status = _aggregate(rows)
        package = layout.analog_dir(project) / "hardmacro" / name
        expected = [package / f"{name}.{suffix}" for suffix in ("gds", "lef", "lib", "v")]
        outputs = {str(path): _sha(path) for path in expected if path.is_file()}
        if len(outputs) != len(expected) and status == "PASS":
            status = "NOT_MEASURED"
        import analog_hardmacro_check as hardmacro
        package_audit = hardmacro.run_audit(project)
        if name not in package_audit.summary.get("design_bound_blocks", []):
            status = "FAIL" if name in package_audit.summary.get("incomplete", []) else (
                "NOT_MEASURED" if status == "PASS" else status)
        record = directory / "signoff.json"
        write_json(record, {"block": name, "status": status, "steps": rows,
                            "deliverables": outputs, "native_package_summary": package_audit.summary,
                            "scope": "analog block; whole IC acceptance is separate"})
        return {"status": status, "detail": "Native analog results and delivery views aggregated",
                "outputs": [str(record)], "steps": rows}
    if not (directory / "layout.mag").is_file() and not (directory / f"{name}.gds").is_file():
        return {"status": "NOT_MEASURED", "detail": "Native layout input is absent",
                "outputs": []}
    executions = []
    from analog_native_physical import _settings
    settings = {**_read(directory / "characterization_inputs.json", {}),
                **_settings(options, "A17", name)}
    for program in ("analog_hardmacro_gds_emit.py", "analog_a8_hardmacro_emit.py"):
        argv = [str(project), "--block", name, "--container", options["container"]]
        if program == "analog_a8_hardmacro_emit.py" and settings.get("ngspice_bin"):
            argv += ["--ngspice-bin", str(settings["ngspice_bin"])]
        result = run(program, argv)
        executions.append(result)
        if result["returncode"]:
            rc = result["returncode"]
            return {"status": "NOT_MEASURED" if rc in (2, 127, 130, 137, 143) or rc < 0 else "FAIL",
                    "detail": f"{program} exited {result['returncode']}",
                    "outputs": [], "executions": executions}
    import analog_liberty_nonzero_delay_check as liberty
    audit = liberty.run_audit(project)
    findings = [vars(finding) for finding in audit.findings if finding.block == name]
    package = layout.analog_dir(project) / "hardmacro" / name
    provenance = _read(package / "a8_views_provenance.json", {})
    status = ("FAIL" if any(finding["severity"] == "ERROR" for finding in findings) else
              "PASS" if name in audit.summary.get("design_bound_blocks", []) else "NOT_MEASURED")
    return {"status": status,
            "detail": "Native layout views emitted and characterization checked",
            "outputs": [str(package)],
            "executions": executions, "findings": findings,
            "metrics": {"characterization_scope": provenance.get("characterization_scope"),
                        "native_measurement": provenance.get("native_measurement")}}


def _dispatch(step, project, block, options, run):
    if step in STEPS[:5]:
        from analog_native_front import run_step
    elif step in STEPS[5:10]:
        from analog_native_sim import run_step
    elif step in STEPS[10:16]:
        from analog_native_physical import run_step
    else:
        return _views(step, project, block, options, run)
    return run_step(step, project, block, options, run)



def _declared_blocks(project):
    """Keep native producers and file-based checkers on the same declaration."""
    from analog_native_front import _stale

    def blocks_at(path, key):
        body = _read(path)
        blocks = body.get(key) if isinstance(body, dict) else (body if key == 'blocks' else None)
        if (not isinstance(blocks, list) or not blocks
                or any(not isinstance(block, dict) for block in blocks)):
            raise ValueError(f"nonempty object block list required: {path}")
        if isinstance(body, dict):
            if 'block_count' in body and (type(body['block_count']) is not int
                                         or body['block_count'] != len(blocks)):
                raise ValueError(f"block list count mismatch: {path}")
            if _stale(project, body):
                raise ValueError(f"block list source changed: {path}")
        names = [block.get('name') or block.get('block') for block in blocks]
        if (any(not isinstance(name, str)
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', name)
                or name in ('.', '..') for name in names)
                or len(set(names)) != len(names)):
            raise ValueError(f"block list names must be unique safe components: {path}")
        return blocks

    def agrees(first, second):
        from analog_a1_spec_emit import _canonical_type
        first = {block.get('name') or block.get('block'): block for block in first}
        second = {block.get('name') or block.get('block'): block for block in second}
        return first.keys() == second.keys() and all(
            _canonical_type(first[name].get('type') or first[name].get('block_type'))
            == _canonical_type(second[name].get('type') or second[name].get('block_type'))
            for name in first) and all(
            first[name][key] == second[name][key]
            for name in first for key in ('count', 'multiplicity', 'spec', 'pins', 'ports')
            if key in first[name] and key in second[name])

    candidates = [layout.analog_dir(project) / 'analog_block_list.json',
                  project / 'phase1/analog/analog_block_list.json']
    existing = [(path, blocks_at(path, 'blocks')) for path in candidates if path.exists()]
    l5 = layout.generated_docs_dir(project) / 'L5_ADI_SPEC.json'
    source_blocks = blocks_at(l5, 'analog_blocks') if l5.exists() else None
    if existing:
        blocks = existing[0][1]
        if (any(not agrees(blocks, other) for _, other in existing[1:])
                or source_blocks is not None and not agrees(blocks, source_blocks)):
            raise ValueError('conflicting analog block declarations')
        return blocks
    if source_blocks is None:
        raise ValueError('a nonempty design analog block list is required')
    # The legacy runner already materializes this L5 fallback before running
    # its file-based checkers. Keep the full population before subset selection.
    write_json(candidates[0], {
        'blocks': source_blocks, 'block_count': len(source_blocks),
        '_provenance': {'producer': 'analog_native_flow',
                        'input': {'path': str(l5.relative_to(project)), 'sha256': _sha(l5)}}})
    return source_blocks


def run_window(project, args, *, features=None):
    project = Path(project).resolve()
    entry = getattr(args, "entry_step", None) or "A01"
    exit_ = getattr(args, "exit_step", None) or "A19"
    if entry not in STEPS or exit_ not in STEPS or STEPS.index(entry) > STEPS.index(exit_):
        raise ValueError("analog window must be ordered A01 through A19")
    config_path = project / "input" / "analog_flow.json"
    config = _read(config_path, {})
    if not isinstance(config, dict):
        raise ValueError("input/analog_flow.json must contain an object")
    features = features if features is not None else config.get("features", {})
    blocks = [dict(block) for block in _declared_blocks(project)]
    names = [block.get("name") or block.get("block") for block in blocks]
    declared_names = set(names)
    wanted = {name.strip() for name in (getattr(args, "blocks", "") or "").split(",") if name.strip()}
    if wanted:
        if not wanted.issubset(names):
            raise ValueError("requested analog block is not declared")
        blocks = [block for block in blocks if (block.get("name") or block.get("block")) in wanted]
    names = [block.get("name") or block.get("block") for block in blocks]
    parent = project / "reports" / "analog_native"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    container = getattr(args, "container", None) or config.get("container", "")
    image = getattr(args, "image", None) or config.get("image", "")
    transport = getattr(args, "transport", None) or ("CONTAINER" if container else "HOST")
    if container:
        inspected = subprocess.run(["docker", "inspect", "--format", "{{.Config.Image}}", container],
                                   capture_output=True, text=True)
        if inspected.returncode == 0:
            image = inspected.stdout.strip()
    from analog_one_shot_runner import _effective_analog_pdk, _pdk_contradiction
    selected_pdk = getattr(args, "pdk", "") or config.get("pdk", "")
    pdk_args = SimpleNamespace(pdk=selected_pdk)
    contradiction = _pdk_contradiction(pdk_args, project)
    if contradiction:
        raise ValueError(f"PDK mismatch: requested {contradiction[0]}, declared {contradiction[1]}")
    options = {"container": container, "image": image, "transport": transport,
               "pdk": _effective_analog_pdk(pdk_args, project),
               "cpus": getattr(args, "execution_cpus", None) or config.get("cpus", 4),
               "workers": getattr(args, "execution_workers", None) or config.get("workers", 1),
               "post_mc_samples": getattr(args, "post_mc_samples", None),
               "config": config, "features": features, "previous_results": {},
               "active_blocks": config.get("active_blocks", []), "attempt_dir": str(attempt)}
    options["workers"] = max(1, min(int(options["workers"]), len(blocks)))
    previous = _read(parent / "status.json", {})
    rows = []
    if previous.get("features") == features:
        for retained in previous.get("steps", []):
            name = retained.get("block")
            inputs, outputs = retained.get("input_views"), retained.get("output_views")
            current_inputs = _input_views(project, name, retained.get("step")) if name in declared_names else {}
            if (name in declared_names and inputs
                    and all(inputs.get(path) == digest for path, digest in current_inputs.items())
                    and all(Path(path).is_file() and _sha(path) == digest
                            for path, digest in inputs.items())
                    and isinstance(outputs, dict)
                    and all(Path(path).is_file() and _sha(path) == digest
                            for path, digest in outputs.items())):
                retained = dict(retained)
                retained.setdefault("producer_context", {
                    "image": previous.get("image"), "container": previous.get("container"),
                    "driver_sha256": previous.get("source_sha256"),
                    "attribution": "retained prior execution; not rerun under this window"})
                options["previous_results"].setdefault(retained["step"], {})[name] = retained
                if (name not in names or
                        retained["step"] not in STEPS[STEPS.index(entry):STEPS.index(exit_) + 1]):
                    rows.append(retained)
    report = {"flow": "analog-A01-A19", "project": str(project),
              "started_at": datetime.now(timezone.utc).isoformat(),
              "entry": entry, "exit": exit_, "image": image,
              "container": container, "transport": transport,
              "steps": rows, "verdict": "NOT_MEASURED",
              "window_verdict": "NOT_MEASURED",
              "features": features,
              "attempt": str(attempt), "source_sha256": _sha(Path(__file__)),
              "configuration": str(config_path) if config_path.is_file() else None}

    def execute_one(step, block):
        name = block.get("name") or block.get("block")
        directory = attempt / step / name
        directory.mkdir(parents=True)
        runner = NativeCommands(project, directory, container, image, step=step)
        started = time.monotonic()
        try:
            result = _dispatch(step, project, block, options, runner)
            if not isinstance(result, dict) or result.get("status") not in STATUSES:
                raise ValueError("native step returned an invalid result")
            missing = [path for execution in result.get("executions", [])
                       for path in execution.get("missing_outputs", [])]
            if result["status"] == "PASS" and missing:
                result.update(status="NOT_MEASURED", detail="Native outputs absent: " + ", ".join(missing))
        except (OSError, ValueError, KeyError) as exc:
            result = {"status": "NOT_MEASURED", "detail": str(exc), "outputs": []}
        result.update(step=step, block=name, duration_s=time.monotonic() - started)
        result["producer_context"] = {"image": image, "container": container,
                                      "transport": transport,
                                      "driver_sha256": report["source_sha256"]}
        result["input_views"] = _input_views(project, name, step)
        result["input_views"].update(runner.native_inputs)
        for view in (result.get("native_inputs") or {}).values():
            if isinstance(view, dict) and view.get("path") and view.get("sha256"):
                result["input_views"][view["path"]] = view["sha256"]
        result["output_views"] = _output_views(result)
        write_json(directory / "result.json", result)
        print(f"{step} {name}: {result['status']} — {result.get('detail', '')}", flush=True)
        return result

    state_lock = threading.Lock()

    window_steps = list(STEPS[STEPS.index(entry):STEPS.index(exit_) + 1])
    selected_steps = [s for s in window_steps if s < "A18"] if "A18" in window_steps else window_steps

    def execute_block(block):
        # A long simulation in one block does not hold another block's ready
        # layout, extraction or delivery work behind a global step barrier.
        for step in selected_steps:
            current = execute_one(step, block)
            with state_lock:
                rows.append(current)
                options["previous_results"].setdefault(step, {})[current["block"]] = current
                report["verdict"] = _aggregate(rows)
                report["window_verdict"] = _aggregate([row for row in rows
                    if entry <= row["step"] <= exit_ and row["block"] in names])
                write_json(attempt / "result.json", report)
                write_json(parent / "status.json", report)

    with ThreadPoolExecutor(max_workers=options["workers"]) as pool:
        list(pool.map(execute_block, blocks))
        if "A18" in window_steps:
            # Global chip assembly must not race another block's A17 writer.
            selected_steps = ["A18"]
            for block in blocks:
                execute_block(block)
            if "A19" in window_steps:
                selected_steps = ["A19"]
                list(pool.map(execute_block, blocks))
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(attempt / "result.json", report)
    write_json(parent / "status.json", report)
    return report
