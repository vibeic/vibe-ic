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


def _explicit_container_option(argv):
    """Return ``(present, value)`` for the process's explicit container option."""
    for at, arg in enumerate(argv[1:], 1):
        if arg == "--container":
            return True, argv[at + 1] if at + 1 < len(argv) else ""
        if arg.startswith("--container="):
            return True, arg.split("=", 1)[1]
    return False, ""


def _adapter_transport(project):
    """Select LOCAL inside an attested runtime unless external transport is explicit.

    The canonical front door historically gives ``--container`` a named-container
    default and exports it through ``VIBEIC_ANALOG_CONTAINER``.  That default is
    not an instruction to leave an already host-attested LOCAL runtime.  A CLI
    option or project configuration remains an explicit external selection.
    """
    config = _read(Path(project) / "input" / "analog_flow.json", {})
    configured = config.get("container", "") if isinstance(config, dict) else ""
    inherited = os.environ.get("VIBEIC_ANALOG_CONTAINER", "")
    explicit, selected = _explicit_container_option(sys.argv)
    if configured:
        return configured, "", "CONTAINER"
    if explicit:
        return selected, "", "CONTAINER" if selected else "HOST"
    try:
        import librelane_contract as contract
        identity = contract.local_image_attestation()
    except ImportError:
        raise
    except Exception as exc:
        # Only a validated receipt changes the inherited legacy route.  Keep
        # ordinary host/named-container behavior when no LOCAL proof exists.
        if not isinstance(exc, contract.Refusal):
            raise
        return inherited, "", "CONTAINER" if inherited else "HOST"
    return "", identity["image"], "LOCAL"


def _input_views(project, name, step=None):
    paths = list((project / "input").rglob("*"))
    paths += list(layout.generated_docs_dir(project).glob("*.json"))
    directory = layout.analog_dir(project) / name
    paths += [directory / leaf for leaf in
              ("spec.json", "topology.json", "topology.md", f"{name}.sp", f"tb_{name}.sp")]
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
    from analog_native_sim import _config, _inputs, _included_paths
    config = _read(project / "input" / "analog_flow.json", {})
    for selected_step in STEPS[5:10]:
        selected = _config({"config": config}, {"name": name}, selected_step)
        if selected_step == "A07" and selected.get("nominal_testbench"):
            selected = {**selected, "testbench": selected["nominal_testbench"]}
        if selected_step == "A10" and isinstance(selected.get("calibration"), dict):
            selected = {**selected, **selected["calibration"]}
        netlist, deck, spec = _inputs(project, name, selected)
        paths.extend([netlist, deck, spec])
        paths.extend(_included_paths(deck))
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
    import librelane_contract as launch
    from declared_pdk_is_the_pdk_used_check import declared_target

    try:
        root = availability.local_pdks_root(image)
    except launch.Refusal as exc:
        raise ValueError(str(exc)) from exc
    if root is None:
        return {}, None
    target, _ = declared_target(project)
    selected = availability.resolve_pdk(target, project=project, container='')
    if not selected.get('available') or selected.get('source') != 'container_installed':
        return {}, None  # Project-staged/builtin models keep their existing startup.
    init = Path(cwd) / '.spiceinit'
    if not init.is_file():
        init = Path(selected['pdk_root']) / 'libs.tech/ngspice/.spiceinit'
    environment = {'PDK_ROOT': root, 'PDK': selected['matched_dir']}
    if not init.is_file():
        return environment, None  # An absent optional init is not a model verdict.
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
            # This native path uses tools directly. Do not make a child's
            # legacy entry re-enter the optional qualification reader.
            environment.pop("VIBEIC_FLOW109_CONTEXT", None)
            environment.pop("VIBEIC_FLOW109_ATTEMPT", None)
            if self.image:
                environment["VIBEIC_EDA_IMAGE"] = self.image
            native_tool = program[1:] if program.startswith("@") else ""
            if program == "@env":
                native_tool = next((item for item in argv
                                    if not re.match(r"^[A-Za-z_]\w*=", item)), "")
            if (self.step in ("A02", "A05", "A06", "A07", None)
                    and Path(native_tool).name == "ngspice" and not self.container
                    and os.environ.get("VIBEIC_LIBRELANE_LOCAL_ATTESTATION")):
                startup_environment, native_init = _local_ngspice_startup(self.project, cwd, self.image)
                environment.update(startup_environment)
                if native_init:
                    self.native_inputs[native_init['path']] = native_init['sha256']
            completed = subprocess.run(command, cwd=cwd, env=environment,
                                       capture_output=True, text=True, errors="replace",
                                       input=input_text)
            rc, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
            if native_init and _sha(native_init['path']) != native_init['sha256']:
                rc = rc or 1
                stderr += "\nA05_NATIVE_STARTUP_CHANGED_DURING_EXECUTION"
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


def _a18_metrics(project, name, settings, evidence, execution, limits_before):
    """Consume A18 values without promoting component evidence to row acceptance."""
    import flow109_metric_acceptance as metrics

    keys = ("analog_top_pad_core_connectivity_errors", "analog_sensitive_route_constraints")
    rows = {key: {"status": "NOT_MEASURED", "reason": "A18_IDENTITY_ABSENT"} for key in keys}
    inputs = {}
    try:
        def reopen(relative, digest):
            path = metrics._safe_project_file(project, relative)
            if not path.is_file() or not path.stat().st_size or _sha(path) != digest:
                raise ValueError("A18_INPUT_STALE: " + relative)
            inputs[str(path)] = digest
            return path

        outputs = evidence.get("outputs")
        if not isinstance(outputs, dict) or not outputs:
            raise ValueError("A18_PRODUCER_OUTPUT_IDENTITY_ABSENT")
        receipt = Path(settings["evidence"])
        receipt = receipt if receipt.is_absolute() else project / receipt
        reopen(str(receipt.relative_to(project)), execution.get("outputs", {}).get(str(receipt)))
        if _read(receipt) != evidence:
            raise ValueError("A18_RECEIPT_CONTENT_CHANGED")
        bound = {}
        for leaf, view in outputs.items():
            if Path(leaf).name != leaf or not isinstance(view, dict):
                raise ValueError("A18_PRODUCER_OUTPUT_INVALID")
            path = receipt.parent / leaf
            relative = str(path.relative_to(project))
            reopen(relative, view.get("sha256"))
            observed = execution.get("outputs", {}).get(str(path))
            if observed != view.get("sha256"):
                raise ValueError("A18_OUTPUT_NOT_FROM_EXECUTION: " + leaf)
            bound[leaf] = path
        tops = [p for p in bound.values() if p.suffix == ".gds"]
        extracted = [p for p in bound.values() if p.name.endswith(".extracted.spice")]
        if len(tops) != 1 or len(extracted) != 1:
            raise ValueError("A18_TOP_LAYOUT_PEX_ABSENT")
        provenance = layout.analog_dir(project) / "hardmacro" / name / "a8_views_provenance.json"
        adopted = _read(provenance, {})
        if (adopted.get("producer") != "analog_a8_hardmacro_emit"
                or adopted.get("block") != name
                or evidence.get("core_embedded_unchanged") is not True
                or evidence.get("core_input_sha256") != adopted.get("source_gds_sha256")):
            raise ValueError("A18_A17_CORE_IDENTITY_ABSENT")
        reopen(str(provenance.relative_to(project)), _sha(provenance))
        reopen(adopted["source_gds"], adopted["source_gds_sha256"])
        for view in adopted["views"].values():
            reopen(view["path"], view["sha256"])
        measurement = adopted["native_measurement"]
        reopen(measurement["path"], measurement["sha256"])
        reopen(measurement["source_netlist"], measurement["source_netlist_sha256"])
        reopen(measurement["native_log"], measurement["native_log_sha256"])
        count = evidence.get("checks", {}).get(keys[0])
        metrics._finite_number(count, count=True)
        rows[keys[0]] = {"status": "PASS" if count == 0 else "FAIL",
                         "value": count, "unit": "count", "reason": "A18_NATIVE_CONNECTIVITY"}
        relative = "requirements/analog_top_route/analog_sensitive_route_constraints.json"
        authority, limits = metrics._approved_document(project, relative,
            authority="requirements_owner", schema=metrics.AUTHORITY_SCHEMA)
        if limits_before is None or authority["sha256"] != limits_before:
            raise ValueError("A18_ROUTE_LIMITS_NOT_PREDECLARED")
        inputs[str(project / relative)] = authority["sha256"]
        inputs[str(project / authority["source"]["path"])] = authority["source"]["sha256"]
        declared, units = limits.get("limits"), limits.get("units")
        routes = evidence.get("route_measurements")
        if (not isinstance(declared, dict) or not declared or not isinstance(units, dict)
                or not isinstance(routes, list) or not routes):
            raise ValueError("A18_ROUTE_MEASUREMENTS_OR_LIMITS_ABSENT")
        nets = [row["net"] for row in routes]
        if len(set(nets)) != len(nets) or set(nets) != set(declared) or set(units) != set(declared):
            raise ValueError("A18_ROUTE_POPULATION_MISMATCH")
        route_rows = []
        for route in routes:
            net = route["net"]
            if (route.get("geometry_sha256") != _sha(tops[0])
                    or route.get("pex_sha256") != _sha(extracted[0])):
                raise ValueError("A18_ROUTE_GEOMETRY_UNBOUND: " + net)
            if metrics._finite_number(route.get("length_um")) < 0:
                raise ValueError("A18_ROUTE_LENGTH_INVALID: " + net)
            status, reason = metrics.evaluate_operator("within_declared_bounds",
                {"status": "MEASURED", "value": route.get("length_um"), "unit": route.get("unit"),
                 "identity": {"producer": "analog_native.A18", "checker": _sha(Path(__file__)),
                              "tool_execution": {"outputs": execution["outputs"],
                                                 "returncode": execution["returncode"]}, "consumed_inputs": inputs,
                              "requirements": authority, "configuration": settings}},
                {"status": "APPROVED", "limits": declared[net], "unit": units[net]})
            if units[net] != "um":
                raise ValueError("A18_ROUTE_UNIT_UNSUPPORTED: " + net)
            route_rows.append({"net": net, "status": status, "reason": reason,
                               "value": route["length_um"], "unit": "um"})
        rows[keys[1]] = {"status": _aggregate(route_rows), "routes": route_rows,
                         "reason": "A18_NATIVE_ROUTE_BOUNDS"}
    except (metrics.MetricRefusal, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        for row in rows.values():
            if row["status"] == "NOT_MEASURED":
                row["reason"] = str(exc)
    return {"status": _aggregate(list(rows.values())), "metrics": rows,
            "input_views": inputs, "scope": "A18 measurements only; qualification separate"}


def _views(step, project, block, options, run):
    name = block.get("name") or block.get("block")
    directory = layout.analog_dir(project) / name
    if step == "A18":
        if options["features"].get("digital_physical") is True:
            return {"status": "NOT_APPLICABLE", "detail":
                    "The declared mixed-signal digital top owns pad/power integration.",
                    "outputs": []}
        settings = options["config"].get("analog_top", {})
        script = Path(settings.get("implementation_script", "__absent_top_script__"))
        script = script if script.is_absolute() else project / script
        if not script.is_file():
            return {"status": "NOT_MEASURED", "detail":
                    "Pure-analog top implementation script is absent", "outputs": []}
        magicrc = settings.get("magicrc")
        command = ["-dnull", "-noconsole"] + (["-rcfile", str(magicrc)] if magicrc else [])
        limits_path = project / "requirements/analog_top_route/analog_sensitive_route_constraints.json"
        limits_before = _sha(limits_path) if limits_path.is_file() else None
        script_before = _sha(script)
        result = run("@magic", command, cwd=script.parent,
                     input_text=script.read_text() + "\nquit -noprompt\n",
                     outputs=settings.get("outputs", []))
        receipt = Path(settings.get("evidence", "__absent_a18_evidence__"))
        receipt = receipt if receipt.is_absolute() else project / receipt
        evidence = _read(receipt, {})
        if not isinstance(evidence, dict):
            evidence = {}
        status = evidence.get("component_status", "NOT_MEASURED")
        if status not in STATUSES:
            status = "NOT_MEASURED"
        detail = (evidence.get("reason") or evidence.get("detail") or
                  f"Native A18 component reported {status}")
        if status != "FAIL" and result["returncode"] != 0:
            status = "FAIL"
            detail = f"Native pure-analog top implementation exited {result['returncode']}"
        elif status != "FAIL" and not settings.get("outputs"):
            status = "FAIL"
            detail = "Native pure-analog top implementation declares no outputs"
        elif status != "FAIL" and result["missing_outputs"]:
            status = "FAIL"
            detail = "Native pure-analog top implementation omitted declared outputs"
        acceptance = _a18_metrics(project, name, settings, evidence, result, limits_before)
        if _sha(script) != script_before:
            acceptance = {"status": "NOT_MEASURED", "metrics": {}, "input_views": {},
                          "reason": "A18_PRODUCER_CHANGED_DURING_EXECUTION"}
        acceptance["input_views"][str(script)] = script_before
        if acceptance["status"] == "FAIL" and status != "FAIL":
            status, detail = "FAIL", "A18 native measurement misses declared expectation"
        return {"status": status, "detail": detail,
                "outputs": settings.get("outputs", []), "executions": [result],
                "native_evidence": evidence, "metric_acceptance": acceptance,
                "native_inputs": {path: {"path": path, "sha256": digest}
                                  for path, digest in acceptance["input_views"].items()}}
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
    manifest_path = getattr(args, "flow109_manifest", None)
    if manifest_path is None:
        manifest_path = project / "manifest-formal.json"
    manifest = _read(Path(manifest_path), {})
    features = features if features is not None else manifest.get("features", config.get("features", {}))
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

    def execute_block(block):
        # A long simulation in one block does not hold another block's ready
        # layout, extraction or delivery work behind a global step barrier.
        for step in STEPS[STEPS.index(entry):STEPS.index(exit_) + 1]:
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
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(attempt / "result.json", report)
    write_json(parent / "status.json", report)
    return report


def execute_window(project, context):
    """Run one analog window so independent blocks can advance together."""
    from flow109 import validate_execution_context
    context = validate_execution_context(context)
    entry = context.get("requested_step", context.get("requested_entry"))
    exit_ = context.get("requested_step", context.get("requested_exit"))
    container, image, transport = _adapter_transport(project)
    args = SimpleNamespace(entry_step=entry, exit_step=exit_, blocks="", pdk="",
                           container=container, image=image, transport=transport)
    try:
        return run_window(project, args, features=context["features"])
    except (OSError, ValueError) as exc:
        return {"window_verdict": "NOT_MEASURED", "steps": [],
                "native_started": False, "reason": str(exc)}


def _a18_current_rows(project, report, step, blocks, image):
    """Reopen the existing native attempt and its complete declared readset."""
    import flow109
    attempt = Path(report["attempt"])
    ref = {"path": str((attempt / "result.json").relative_to(project)),
           "sha256": _sha(attempt / "result.json")}
    flow109._current_project_ref(project, ref, "A18_NATIVE_ATTEMPT_FOREIGN")
    stored = _read(attempt / "result.json")
    if report != stored and report != {"attempt": str(attempt), "steps": [
            row for row in stored.get("steps", []) if row.get("step") == step]}:
        raise ValueError("A18_NATIVE_ATTEMPT_RECORD_MISMATCH")
    report = stored
    if (not attempt.resolve().is_relative_to(project / "reports/analog_native")
            or report.get("source_sha256") != _sha(Path(__file__))
            or report.get("image") != image):
        raise ValueError("A18_NATIVE_ATTEMPT_STALE")
    rows = [row for row in report["steps"] if row.get("step") == step]
    if sorted(row["block"] for row in rows) != sorted(blocks):
        raise ValueError("A18_NATIVE_BLOCK_POPULATION_MISMATCH")
    readset = {str(attempt / "result.json"): ref["sha256"]}
    for row in rows:
        producer = row.get("producer_context", {})
        if (row.get("status") != "PASS" or producer.get("image") != image
                or producer.get("driver_sha256") != report["source_sha256"]
                or not row.get("input_views") or not row.get("output_views")
                or any(row["input_views"].get(key) != digest
                       for key, digest in _input_views(project, row["block"], step).items())):
            raise ValueError("A18_NATIVE_ROW_NOT_CURRENT")
        for key in ("input_views", "output_views"):
            for name, digest in row[key].items():
                path = Path(name)
                path = path if path.is_absolute() else project / path
                if (not path.is_file() or _sha(path) != digest
                        or key == "output_views" and not path.resolve().is_relative_to(project)):
                    raise ValueError("A18_NATIVE_READSET_STALE: " + name)
                readset[str(path)] = digest
    return rows, readset


def _a18_prerequisites(project, context, blocks, image):
    """Consume accepted source-selected predecessors and their material readers."""
    import importlib
    import flow109
    import flow109_admission as admission
    selected = {r["id"] for r in flow109.resolve_plan(context["features"], context["step_profiles"])["rows"]}
    readset, accepted = {}, {}
    for step in context["resolved_row"]["acceptance_deps"]:
        if step not in selected:
            continue
        body, ref = flow109._accepted_row(project, Path("reports/flow109/default_rows") / (step + ".json"), step)
        if body.get("component_status") != "PASS":
            raise ValueError("A18_PREREQUISITE_NATIVE_NOT_PASS: " + step)
        readset[str(project / ref["path"])] = ref["sha256"]
        request_path = project / "reports/flow109/requests" / (body["context_sha256"] + ".json")
        original = flow109.validate_execution_context(_read(request_path))
        original = flow109.component_context(original, requested_step=step)
        if (original["features"] != context["features"]
                or original["context_sha256"] != body["context_sha256"]):
            raise ValueError("A18_PREREQUISITE_CARRIER_FOREIGN: " + step)
        readset[str(request_path)] = _sha(request_path)
        owner = importlib.import_module(original["resolved_row"]["profile"]["dispatch"]["adapter"])
        if step == "A17":
            _, views = _a18_current_rows(project, body["native_results"], step, blocks, image)
            readset.update(views)
            import analog_hardmacro_check as packages
            if set(packages.run_audit(project).summary.get("design_bound_blocks", [])) != set(blocks):
                raise ValueError("A18_A17_MATERIAL_POPULATION_MISMATCH")
        elif step == "D32":
            material = owner._d32_inputs(project)
            if (body.get("inputs") != material["inputs"] or body.get("unmeasured")
                    or body.get("native_db", {}).get("top") != material["top"]
                    or body.get("native_launch", {}).get("image") != image):
                raise ValueError("A18_D32_MATERIAL_NOT_ACCEPTED")
            for use in original["runtime_tool_uses"]:
                tool = body.get("tools", {}).get(use["tool_id"], {})
                if (tool.get("sha256") != use["build_sha256"]
                        or Path(tool.get("path", "")).resolve() != Path(use["executable"]["path"]).resolve()):
                    raise ValueError("A18_D32_NATIVE_TOOL_UNQUALIFIED")
            readset.update(material["inputs"])
            if not body.get("outputs"):
                raise ValueError("A18_D32_OUTPUTS_ABSENT")
            for view in body["outputs"]:
                flow109._current_project_ref(project, view, "A18_D32_OUTPUT_STALE")
                readset[str(project / view["path"])] = view["sha256"]
        elif step == "D31":
            if not isinstance(body.get("outputs"), list) or len(body["outputs"]) != 2:
                raise ValueError("A18_D31_OUTPUT_POPULATION_INCOMPLETE")
            flow109._current_project_ref(project, body["outputs"][0], "A18_D31_OUTPUT_STALE")
            raw_path = (project / body["outputs"][0]["path"]).parent / "component.json"
            raw = _read(raw_path)
            if (raw.get("context_sha256") != body["context_sha256"]
                    or raw.get("component_status") != "PASS" or raw.get("outputs") != body["outputs"]):
                raise ValueError("A18_D31_COMPONENT_LINK_FOREIGN")
            readset[str(raw_path)] = _sha(raw_path)
            completion = owner.consume_default_row_completion(project, original, raw)
            if completion.get("default_row_status") != "PASS" or completion.get("completed") is not True:
                raise ValueError("A18_D31_GEOMETRY_NOT_ACCEPTED")
        elif step == "D03":
            if not body.get("inputs"):
                raise ValueError("A18_D03_READSET_ABSENT")
            for view in body["inputs"]:
                path = Path(view["path"])
                path = path if path.is_absolute() else project / path
                if not path.is_file() or _sha(path) != view["sha256"]:
                    raise ValueError("A18_D03_INPUT_STALE")
                readset[str(path)] = view["sha256"]
        else:
            raise ValueError("A18_PREREQUISITE_CONSUMER_UNAVAILABLE: " + step)
        admission.require_admission(project, original)
        accepted[step] = ref
    return accepted, readset


def consume_default_row_completion(project, context, component):
    """Complete A18 only from current native metrics and qualified predecessors."""
    if context.get("requested_step") != "A18":
        return component
    project = Path(project).resolve()
    base = {"step_id": "A18", "context_sha256": context.get("context_sha256"),
            "default_row_status": "NOT_MEASURED", "completed": False,
            "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
            "delivery_accepted": False, "qualification": "NOT_MEASURED"}
    if component.get("component_status") == "FAIL":
        return {**base, "default_row_status": "FAIL", "reason": component.get("reason")}
    try:
        import flow109
        import flow109_admission as admission
        import flow109_metric_acceptance as metrics
        import librelane_contract as launch
        context = flow109.validate_execution_context(context)
        if component.get("component_status") != "PASS" or context["native_step_id"] != "flow109.A18":
            raise ValueError("A18_NATIVE_COMPONENT_NOT_PASS")
        qualified = admission.require_admission(project, context)
        sources = {p.name: _sha(p) for p in (Path(__file__), Path(metrics.__file__))}
        for use in context["runtime_tool_uses"]:
            config = _read(project / use["config"]["path"])
            if config != {"purpose": use["semantics"]["purpose"],
                          "native_steps": use["semantics"]["native_steps"], "model_sources": sources}:
                raise ValueError("A18_QUALIFIED_MODEL_STALE")
        image = launch.resolve_image(project, record=False)
        blocks = [b.get("name") or b.get("block") for b in _declared_blocks(project)]
        rows, readset = _a18_current_rows(project, component["native_results"], "A18", blocks, image)
        config = _read(project / "input/analog_flow.json")
        settings = config["analog_top"]
        receipt = Path(settings["evidence"])
        receipt = receipt if receipt.is_absolute() else project / receipt
        limits = project / "requirements/analog_top_route/analog_sensitive_route_constraints.json"
        observations = []
        for row in rows:
            executions = row.get("executions", [])
            if len(executions) != 1 or executions[0].get("returncode") != 0 or executions[0].get("missing_outputs"):
                raise ValueError("A18_NATIVE_EXECUTION_INCOMPLETE")
            execution = executions[0]
            script = Path(settings["implementation_script"])
            script = script if script.is_absolute() else project / script
            argv = ["magic", "-dnull", "-noconsole"]
            if settings.get("magicrc"):
                argv += ["-rcfile", str(settings["magicrc"])]
            if execution.get("argv") != argv or execution.get("cwd") != str(script.parent):
                raise ValueError("A18_QUALIFIED_INVOCATION_MISMATCH")
            log = Path(execution["log"])
            log = log if log.is_absolute() else project / log
            flow109._current_project_ref(project,
                {"path": str(log.relative_to(project)), "sha256": execution["log_sha256"]}, "A18_NATIVE_LOG_STALE")
            readset[str(log)] = execution["log_sha256"]
            observed = _a18_metrics(project, row["block"], settings, _read(receipt), executions[0],
                                    row["input_views"].get(str(limits)))
            observations.append(observed)
            readset.update(observed["input_views"])
        obligations = context["resolved_row"]["obligations"]
        if sorted(item["metric"] for item in obligations) != sorted(observations[0]["metrics"]):
            raise ValueError("A18_REQUIRED_METRIC_POPULATION_MISMATCH")
        status = _aggregate(observations)
        base["metric_acceptance"] = {"status": status, "blocks": observations}
        base["metric_acceptance_status"] = status
        if status != "PASS":
            return {**base, "default_row_status": status, "reason": "A18_METRICS_NOT_CURRENT_OR_PASS"}
        accepted, views = _a18_prerequisites(project, context, blocks, image)
        readset.update(views)
        if (any(not Path(path).is_file() or _sha(path) != digest for path, digest in readset.items())
                or admission.require_admission(project, context) != qualified):
            raise ValueError("A18_INPUT_CHANGED_DURING_COMPLETION")
        return {**base, "default_row_status": "PASS", "completed": True,
                "flow109_acceptance": "PASS", "qualification": "PASS",
                "reason": "A18_CURRENT_METRICS_PREREQUISITES_AND_QUALIFICATION_PASS",
                "accepted_dependencies": accepted, "input_views": readset}
    except (ValueError, OSError, TypeError, KeyError, AttributeError, launch.Refusal) as exc:
        return {**base, "reason": getattr(exc, "code", "A18_COMPLETION_INPUT_NOT_CURRENT"), "detail": str(exc)}


def execute(project, context):
    """Existing whole-flow front-door adapter for one analog row."""
    report = execute_window(project, context)
    step = context["requested_step"]
    result = {"step_id": step, "component_status": report["window_verdict"],
              "flow109_acceptance": "NOT_MEASURED", "native_results": report,
              **({"native_started": False} if report.get("native_started") is False else {}),
              "reason": report.get("reason", "native analog step executed; whole IC acceptance remains separate")}
    if step == "A18":
        observations = [item.get("metric_acceptance", {"status": "NOT_MEASURED"})
                        for item in report.get("steps", []) if item.get("step") == "A18"]
        result["metric_acceptance"] = {"status": _aggregate(observations), "blocks": observations,
                                       "scope": "A18 measurements only; qualification separate"}
        result["metric_acceptance_status"] = result["metric_acceptance"]["status"]
    return result
