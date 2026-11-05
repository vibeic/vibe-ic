"""M06-M09 Default adapters over the existing mixed-signal producers.

The adapter does not translate a legacy component PASS into a canonical row
PASS.  A row-specific owner document binds the exact current material inputs,
geometry, scenario population and candidate/final role.  The completion
consumer then re-opens the native producer and gate reports before accepting
the supported row scope.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json

SCHEMA = "vibeic.flow109.mixed-native.v1"
INPUT_SCHEMA = "vibeic.flow109.mixed-native-input.v1"
COMPLETION_SCHEMA = "vibeic.flow109.default-row-completion.v1"
ROWS = {
    "M06": {"legacy": "M3", "scope": "candidate", "obligations": (
        "base_M5.candidate_ams_scenarios", "base_M5.candidate_ams_performance")},
    "M07": {"legacy": "M1", "scope": "assembly", "obligations": (
        "base_M6.mixed_gds_reference_identity", "base_M6.missing_duplicate_macro_instances")},
    "M08": {"legacy": "M3", "scope": "final", "obligations": (
        "ams_final.final_ams_scenarios", "ams_final.final_ams_noise_settling_calibration")},
    "M09": {"legacy": "M4", "scope": "signoff", "obligations": (
        "base_M7.mixed_requirement_evidence", "base_M7.mixed_model_final_geometry_identity")},
}


def _runtime_image(project):
    """Resolve the exact execution image now; never store a release digest."""
    import librelane_contract as librelane
    try:
        return librelane.resolve_image(Path(project), record=False)
    except librelane.Refusal as exc:
        detail = str(exc)
        prefix = f"{exc.code}: "
        if detail.startswith(prefix):
            detail = detail[len(prefix):]
        raise Refusal(exc.code, detail) from None


class Refusal(RuntimeError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("MIXED_ROW_EVIDENCE_ABSENT_OR_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise Refusal("MIXED_ROW_EVIDENCE_INVALID", str(path))
    return value


def _local(project, name):
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or ".." in Path(name).parts):
        raise Refusal("MIXED_ROW_INPUT_PATH_INVALID", str(name))
    path = (project / name).resolve()
    if not path.is_relative_to(project):
        raise Refusal("MIXED_ROW_INPUT_PATH_INVALID", name)
    return path


def operation_sources():
    from execution_provider_catalog import source_closure
    roots = {Path(__file__), HERE / "flow109.py", HERE / "mixed_signal_m3_run.py",
             HERE / "_mixed_signal_native.py", HERE / "_mixed_signal_current.py",
             HERE / "mixed_signal_cosim_check.py", HERE / "mixed_signal_interface_si_check.py",
             HERE / "mixed_signal_top_lvs_run.py", HERE / "mixed_signal_merge_check.py",
             HERE / "mixed_signal_signoff_run.py", HERE / "mixed_signal_signoff_check.py",
             HERE / "_mixed_signal_top_pv.py", HERE / "flow109_final_extract.py",
             HERE / "analog_native_flow.py", HERE / "analog_hardmacro_check.py"}
    return {str(path.relative_to(HERE.parent)): _sha(path)
            for path in sorted(source_closure(roots))}


def _bound_ref(project, value, label):
    """Reopen one existing receipt/view reference inside this project."""
    ref = value if isinstance(value, dict) else {"path": value}
    path = _local(project, ref.get("path") if isinstance(ref, dict) else "")
    if not path.is_file() or (ref.get("sha256") and ref["sha256"] != _sha(path)):
        raise Refusal("MIXED_ROW_REQUIRED_INPUT_ABSENT", label)
    return path


def _final_parasitic_binding(project, manifest):
    """Bind M08 to D69's validated final geometry and selected RC scene."""
    import _mixed_signal_native as native
    import flow109_final_extract as final_extract

    ref = manifest.get("d69_receipt")
    if not isinstance(ref, dict):
        raise Refusal("MIXED_ROW_FINAL_PARASITICS_ABSENT", "M08 d69_receipt")
    try:
        final = final_extract.validate_final_parasitics(project, ref)
        contract = native.contract(project, manifest["top"])
    except Exception as exc:
        raise Refusal("MIXED_ROW_FINAL_PARASITICS_INVALID", str(exc)) from exc
    selected_spef = _local(project, (contract.get("si") or {}).get("spef", ""))
    selected_netlist = _local(project, (contract.get("digital") or {}).get("netlist", ""))
    final_spefs = final.get("final_spefs") or {}
    matched = [corner for corner, candidate in final_spefs.items()
               if _bound_ref(project, candidate, "D69 final SPEF").resolve() == selected_spef.resolve()
               and candidate.get("sha256") == _sha(selected_spef)]
    adopted = final.get("adopted_views") or {}
    if (len(matched) != 1
            or _bound_ref(project, adopted.get("netlist"), "D69 adopted netlist").resolve()
            != selected_netlist.resolve()
            or not final.get("component_parasitics_current")):
        raise Refusal("MIXED_ROW_FINAL_PARASITICS_NOT_CONSUMED",
                      "M3 must consume one current D69 final SPEF and adopted netlist")
    refs = {"d69_receipt": ref, "final_geometry": final.get("final_geometry"),
            "filled_def": final.get("filled_def"),
            **{"final_spef:" + corner: value for corner, value in final_spefs.items()},
            **{"adopted_" + role: value for role, value in adopted.items()}}
    inputs = {}
    for label, item in refs.items():
        path = _bound_ref(project, item, label)
        inputs[str(path.relative_to(project))] = _sha(path)
    return {"d69_receipt": ref, "selected_corner": matched[0],
            "final_geometry": final["final_geometry"],
            "final_spefs": final_spefs,
            "fill_sensitive_parasitics": final.get("fill_sensitive_parasitics"),
            "inputs": inputs}


def _m09_prerequisites(project, manifest, runtime_image=None):
    """Re-open the current M08 completion and every declared A19 block."""
    import analog_hardmacro_check as hardmacro
    import analog_native_flow as analog
    import flow109

    m08_path = _bound_ref(project, manifest.get("m08_receipt"), "M08 component receipt")
    m08 = _read(m08_path)
    request_path = project / "reports/flow109/requests" / (str(m08.get("context_sha256")) + ".json")
    request = _read(request_path)
    try:
        request = flow109.validate_execution_context(request)
    except Exception as exc:
        raise Refusal("MIXED_ROW_FINAL_AMS_RECEIPT_INVALID", str(exc)) from exc
    if request.get("requested_step") != "M08":
        raise Refusal("MIXED_ROW_FINAL_AMS_RECEIPT_INVALID", "receipt is not M08")
    completion = consume_default_row_completion(project, request, m08)
    if completion.get("default_row_status") != "PASS" or completion.get("completed") is not True:
        raise Refusal("MIXED_ROW_FINAL_AMS_NOT_COMPLETE", str(completion.get("reason")))

    status_path = project / "reports/analog_native/status.json"
    status = _read(status_path)
    blocks = hardmacro._load_block_list(project)
    rows = [row for row in status.get("steps", ())
            if isinstance(row, dict) and row.get("step") == "A19"]
    if (not blocks or sorted(row.get("block") for row in rows) != sorted(blocks)
            or status.get("source_sha256") != _sha(Path(analog.__file__))):
        raise Refusal("MIXED_ROW_A19_POPULATION_INVALID", str(blocks))
    inputs = {str(m08_path.relative_to(project)): _sha(m08_path),
              str(request_path.relative_to(project)): _sha(request_path),
              str(status_path.relative_to(project)): _sha(status_path)}
    runtime_image = runtime_image or _runtime_image(project)
    packages = {}
    for row in rows:
        block = row["block"]
        producer = row.get("producer_context") or {}
        in_views, out_views = row.get("input_views"), row.get("output_views")
        if (row.get("status") != "PASS" or producer.get("image") != runtime_image
                or producer.get("driver_sha256") != status.get("source_sha256")
                or not isinstance(in_views, dict) or not in_views
                or not isinstance(out_views, dict) or not out_views):
            raise Refusal("MIXED_ROW_A19_CURRENT_RESULT_INVALID", block)
        for views, outputs in ((in_views, False), (out_views, True)):
            for name, expected in views.items():
                path = Path(name).resolve()
                if (outputs and not path.is_relative_to(project)) or not path.is_file() \
                        or _sha(path) != expected:
                    raise Refusal("MIXED_ROW_A19_VIEW_STALE", str(name))
                inputs[str(path.relative_to(project)) if path.is_relative_to(project) else str(path)] = expected
        signoff_path = project / "phase3/analog" / block / "signoff.json"
        signoff = _read(signoff_path)
        summary = signoff.get("native_package_summary") or {}
        if (signoff.get("block") != block or signoff.get("status") != "PASS"
                or block not in summary.get("design_bound_blocks", ())
                or len(signoff.get("steps") or ()) != 18
                or len(signoff.get("deliverables") or {}) != 4
                or str(signoff_path) not in out_views):
            raise Refusal("MIXED_ROW_A19_PACKAGE_INVALID", block)
        packages[block] = {"signoff_sha256": _sha(signoff_path),
                           "deliverables": signoff["deliverables"]}
    audit = hardmacro.run_audit(project)
    if not audit.passed or sorted(audit.summary.get("design_bound_blocks", ())) != sorted(blocks):
        raise Refusal("MIXED_ROW_A19_PACKAGE_INVALID", "current hardmacro audit")
    return {"m08_completion": completion, "a19_packages": packages, "inputs": inputs}


def _current_inputs(project, step, top, manifest=None):
    if step in ("M06", "M08"):
        import mixed_signal_m3_run as m3
        values = m3.inputs(project, top)
    elif step == "M07":
        import mixed_signal_top_lvs_run as m1
        values = m1.current_merge_inputs(project, top)[-1]
    elif step == "M09":
        import _mixed_signal_top_pv as top_pv
        import mixed_signal_m3_run as m3
        spec, values = top_pv.request(project, top)
        values = dict(values)
        for name in (m3.RECEIPT, m3.DIR + "/merge.json",
                     m3.DIR + "/top_lvs.json", m3.DIR + "/power_domain_run.json"):
            path = _local(project, name)
            values[name] = m3.digest(path) if path.is_file() else None
        if spec.get("layout"):
            values[spec["layout"]] = m3.digest(_local(project, spec["layout"]))
    else:
        raise Refusal("MIXED_ROW_CONTEXT_MISMATCH", step)
    if not isinstance(values, dict) or not values or any(value is None for value in values.values()):
        raise Refusal("MIXED_ROW_REQUIRED_INPUT_ABSENT", step)
    if step == "M08":
        values.update(_final_parasitic_binding(project, manifest or {})["inputs"])
    elif step == "M09":
        values.update(_m09_prerequisites(project, manifest or {})["inputs"])
    return dict(sorted(values.items()))


def _command_plan(project, step, manifest, attempt):
    python = str(Path(sys.executable).resolve())
    top, pdk = manifest["top"], manifest["pdk"]
    if step in ("M06", "M08"):
        producer = [python, str(HERE / "mixed_signal_m3_run.py"), str(project),
                    "--top", top, "--container", "host", "--json", str(attempt / "producer.json")]
        gates = [
            [python, str(HERE / "mixed_signal_cosim_check.py"), str(project),
             "--require-current-production", "--json", str(attempt / "cosim.json")],
            [python, str(HERE / "mixed_signal_interface_si_check.py"), str(project),
             "--require-current-production", "--json", str(attempt / "si.json")],
        ]
    elif step == "M07":
        producer = [python, str(HERE / "mixed_signal_top_lvs_run.py"), str(project),
                    "--top", top, "--container", "host", "--pdk", pdk,
                    "--json", str(attempt / "producer.json")]
        gates = [[python, str(HERE / "mixed_signal_merge_check.py"), str(project),
                  "--json", str(attempt / "merge.json")]]
    else:
        producer = [python, str(HERE / "mixed_signal_signoff_run.py"), str(project),
                    "--top", top, "--json", str(attempt / "producer.json")]
        gates = [[python, str(HERE / "mixed_signal_signoff_check.py"), str(project),
                  "--require-current-production", "--json", str(attempt / "signoff.json")]]
    return producer, gates


def _run(argv, log):
    done = subprocess.run(argv, text=True, capture_output=True)
    log.write_text(done.stdout + done.stderr)
    return {"argv": argv, "returncode": done.returncode,
            "stdout_sha256": hashlib.sha256(done.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(done.stderr.encode()).hexdigest(),
            "log": {"path": str(log), "sha256": _sha(log)}}


def _semantic_pass(project, step, manifest):
    if step in ("M06", "M08"):
        import mixed_signal_m3_run as m3
        cosim, si = m3.audit(project, "cosim"), m3.audit(project, "si")
        receipt = _read(project / m3.RECEIPT)
        scenarios = receipt.get("scenario_ids")
        required = manifest.get("required_scenarios")
        if (not isinstance(required, list) or not required or scenarios != required
                or len(set(required)) != len(required)):
            raise Refusal("MIXED_ROW_SCENARIO_POPULATION_MISMATCH", str((required, scenarios)))
        if cosim.get("verdict") != "PASS" or si.get("verdict") != "PASS":
            raise Refusal("MIXED_ROW_CURRENT_CONSUMER_REFUSED", str((cosim, si)), status="FAIL")
        evidence = {"cosim": cosim, "si": si, "scenario_ids": scenarios,
                    "geometry_sha256": _sha(project / "phase3/mixed_signal/top_merged.gds")}
        if step == "M08":
            evidence["final_parasitics"] = _final_parasitic_binding(project, manifest)
            evidence["final_parasitics"].pop("inputs", None)
        return evidence
    if step == "M07":
        import mixed_signal_top_lvs_run as m1
        top_lvs = _read(project / "reports/analog/mixed_signal/top_lvs.json")
        merge = _read(project / "reports/analog/mixed_signal/merge.json")
        stale = m1.validate_current_receipt(project, top_lvs)
        if top_lvs.get("verdict") != "PASS" or merge.get("verdict") != "PASS" or stale:
            raise Refusal("MIXED_ROW_CURRENT_LVS_REFUSED", stale or str((merge, top_lvs)), status="FAIL")
        _, macros, _views, _netlist, detail, _hashes = m1.current_merge_inputs(project, manifest["top"])
        population = [(item["inst"], cell) for cell, items in detail["placements"].items()
                      for item in items]
        if not macros or len(population) != len({item[0] for item in population}):
            raise Refusal("MIXED_ROW_MACRO_POPULATION_INVALID", str(population), status="FAIL")
        return {"mixed_gds_sha256": _sha(project / "phase3/mixed_signal/top_merged.gds"),
                "macro_instances": population, "missing_duplicate_macro_instances": 0}
    import mixed_signal_signoff_run as signoff
    audit = signoff.audit(project)
    current = signoff.verify(project)
    if audit.get("verdict") != "PASS" or audit.get("ready_for_tapeout") is not True:
        raise Refusal("MIXED_ROW_CURRENT_SIGNOFF_REFUSED", str(audit), status="FAIL")
    prerequisites = _m09_prerequisites(project, manifest)
    prerequisites.pop("inputs", None)
    return {"signoff": current, "prerequisites": prerequisites,
            "final_geometry_sha256": _sha(project / "phase3/mixed_signal/top_merged.gds")}


def _prepare(project, context):
    step = context.get("requested_step")
    if step not in ROWS or context.get("native_step_id") != "flow109." + str(step):
        raise Refusal("MIXED_ROW_CONTEXT_MISMATCH", str(step))
    row = context.get("resolved_row") or {}
    dispatch = ((row.get("profile") or {}).get("dispatch") or {})
    if row.get("id") != step or dispatch.get("adapter") != "flow109_mixed_native":
        raise Refusal("MIXED_ROW_CONTEXT_MISMATCH", "source-owned dispatch required")
    manifest_path = project / "input/flow109" / (step + ".json")
    manifest = _read(manifest_path)
    runtime_image = _runtime_image(project)
    if (manifest.get("schema") != INPUT_SCHEMA or manifest.get("step_id") != step
            or manifest.get("scope") != ROWS[step]["scope"]
            or manifest.get("image") != runtime_image
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", str(manifest.get("top") or ""))
            or not isinstance(manifest.get("pdk"), str) or not manifest["pdk"]):
        raise Refusal("MIXED_ROW_INPUT_INVALID", str(manifest_path))
    if step == "M07" and manifest.get("geometry_sha256") is not None:
        raise Refusal("MIXED_ROW_INPUT_INVALID", "M07 output cannot be a launch prerequisite")
    current = _current_inputs(project, step, manifest["top"], manifest)
    if manifest.get("input_sha256") != current:
        raise Refusal("MIXED_ROW_INPUT_STALE_OR_INCOMPLETE", step)
    if step != "M07" and manifest.get("geometry_sha256") != _sha(
            project / "phase3/mixed_signal/top_merged.gds"):
        raise Refusal("MIXED_ROW_GEOMETRY_IDENTITY_MISMATCH", step)
    return manifest, current, operation_sources(), runtime_image


def execute(project, context):
    project = Path(project).resolve()
    step = str(context.get("requested_step"))
    attempt = project / "reports/flow109" / step / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    result = {"schema": SCHEMA, "step_id": step, "context_sha256": context.get("context_sha256"),
              "component_status": "NOT_MEASURED", "native_started": False,
              "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED"}
    try:
        manifest, inputs, sources, runtime_image = _prepare(project, context)
        producer, gates = _command_plan(project, step, manifest, attempt)
        records = []
        for index, argv in enumerate([producer, *gates]):
            result["native_started"] = True
            record = _run(argv, attempt / ("command-%02d.log" % index))
            records.append(record)
            if record["returncode"] != 0:
                status = "FAIL" if record["returncode"] == 1 else "NOT_MEASURED"
                raise Refusal("MIXED_ROW_NATIVE_COMMAND_FAILED", str(argv), status=status)
        if _current_inputs(project, step, manifest["top"], manifest) != inputs:
            raise Refusal("MIXED_ROW_INPUT_CHANGED_DURING_EXECUTION", step)
        evidence = _semantic_pass(project, step, manifest)
        outputs = {str(path.relative_to(project)): _sha(path)
                   for path in attempt.rglob("*") if path.is_file()}
        result.update(component_status="PASS", reason="MIXED_ROW_EXISTING_NATIVE_CHAIN_PASS",
                      manifest=manifest, input_sha256=inputs, source_sha256=sources,
                      runtime_image=runtime_image, commands=records, evidence=evidence,
                      output_sha256=outputs)
    except Refusal as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(reason="MIXED_ROW_NATIVE_UNAVAILABLE_OR_UNSUPPORTED", detail=str(exc))
    result["receipt"] = {"path": str((attempt / "component.json").relative_to(project))}
    write_json(attempt / "component.json", result)
    return result


def _completion_base(step, context, code, detail, status="NOT_MEASURED"):
    return {"schema": COMPLETION_SCHEMA, "step_id": step, "default_row_status": status,
            "completed": False, "reason": code, "detail": detail,
            "context_sha256": context.get("context_sha256"),
            "selected_obligations": list(ROWS.get(step, {}).get("obligations", ())),
            "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
            "whole_ic_acceptance": "NOT_MEASURED"}


def consume_default_row_completion(project, context, component):
    project = Path(project).resolve()
    step = str(context.get("requested_step"))
    base = _completion_base(step, context, "MIXED_ROW_COMPLETION_NOT_MEASURED", "not consumed")
    try:
        if step not in ROWS or context.get("native_step_id") != "flow109." + step:
            raise Refusal("MIXED_ROW_COMPLETION_CONTEXT_MISMATCH", step)
        obligations = tuple(item.get("id") for item in
                            (context.get("resolved_row") or {}).get("obligations", ()))
        if obligations != ROWS[step]["obligations"]:
            raise Refusal("MIXED_ROW_COMPLETION_OBLIGATIONS_MISMATCH", str(obligations))
        receipt = component.get("receipt") if isinstance(component, dict) else None
        path = _local(project, receipt.get("path") if isinstance(receipt, dict) else "")
        if (not path.is_file() or path.name != "component.json"
                or not path.is_relative_to(project / "reports/flow109" / step)):
            raise Refusal("MIXED_ROW_COMPLETION_RECEIPT_MISSING", str(path))
        raw = _read(path)
        if raw != component or raw.get("schema") != SCHEMA or raw.get("step_id") != step \
                or raw.get("context_sha256") != context.get("context_sha256"):
            raise Refusal("MIXED_ROW_COMPLETION_RECEIPT_INVALID", str(path))
        if raw.get("component_status") == "FAIL":
            return {**base, "default_row_status": "FAIL", "reason": raw.get("reason"),
                    "component_receipt": {"path": str(path.relative_to(project)), "sha256": _sha(path)}}
        if raw.get("component_status") != "PASS":
            raise Refusal(raw.get("reason") or "MIXED_ROW_COMPLETION_NOT_MEASURED", "component did not pass")
        manifest, inputs, sources, runtime_image = _prepare(project, context)
        if raw.get("manifest") != manifest or raw.get("input_sha256") != inputs \
                or raw.get("source_sha256") != sources \
                or raw.get("runtime_image") != runtime_image:
            raise Refusal("MIXED_ROW_COMPLETION_SOURCE_OR_INPUT_STALE", step)
        for name, expected in (raw.get("output_sha256") or {}).items():
            output = _local(project, name)
            if not output.is_file() or _sha(output) != expected:
                raise Refusal("MIXED_ROW_COMPLETION_EVIDENCE_STALE", name)
        commands = raw.get("commands")
        expected_plan = _command_plan(project, step, manifest, path.parent)
        expected_argv = [expected_plan[0], *expected_plan[1]]
        if (not isinstance(commands, list) or [item.get("argv") for item in commands] != expected_argv
                or any(item.get("returncode") != 0 for item in commands)):
            raise Refusal("MIXED_ROW_COMPLETION_INVOCATION_INVALID", step)
        evidence = _semantic_pass(project, step, manifest)
        if evidence != raw.get("evidence"):
            raise Refusal("MIXED_ROW_COMPLETION_DERIVATION_CHANGED", step)
        if (step == "M08"
                and (evidence.get("final_parasitics", {}).get("fill_sensitive_parasitics") or {}).get("status") != "PASS"):
            raise Refusal("MIXED_ROW_FINAL_PARASITICS_NOT_QUALIFIED",
                          "D69 fill-sensitive final parasitics remain unmeasured")
        return {**base, "default_row_status": "PASS", "completed": True,
                "reason": "MIXED_ROW_SUPPORTED_SCOPE_COMPLETE", "detail": ROWS[step]["scope"],
                "component_receipt": {"path": str(path.relative_to(project)), "sha256": _sha(path)},
                "input_sha256": inputs, "source_sha256": sources, "evidence": evidence}
    except Refusal as exc:
        return {**base, "default_row_status": exc.status, "reason": exc.code, "detail": str(exc)}


def _accepted_upstream(project, manifest, step):
    """Re-open the selected owner's completion; an asserted PASS is insufficient."""
    import importlib
    import flow109

    path = _bound_ref(project, (manifest.get("upstream_receipts") or {}).get(step), step)
    component = _read(path)
    owner_component, owner_path = component, path
    if step in ("M06", "M08") and component.get("schema") == COMPLETION_SCHEMA:
        link = component.get("component_receipt")
        if not isinstance(link, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(link.get("sha256", ""))):
            raise Refusal("M89_UPSTREAM_COMPONENT_LINK_INVALID", step)
        owner_path = _bound_ref(project, link, step + " raw component")
        if _bound_ref(project, component.get("receipt"), step + " owner receipt") != owner_path:
            raise Refusal("M89_UPSTREAM_COMPONENT_LINK_INVALID", step)
        owner_component = _read(owner_path)
        if (owner_component.get("schema") != SCHEMA or owner_component.get("step_id") != step
                or owner_component.get("context_sha256") != component.get("context_sha256")):
            raise Refusal("M89_UPSTREAM_COMPONENT_LINK_INVALID", step)
    if step in ("D69", "M08"):
        role = "d69_receipt" if step == "D69" else "m08_receipt"
        if _bound_ref(project, manifest.get(role), role) not in (path, owner_path):
            raise Refusal("M89_UPSTREAM_RECEIPT_MISMATCH", step)
    request = _read(project / "reports/flow109/requests" /
                    (str(component.get("context_sha256")) + ".json"))
    try:
        request = flow109.validate_execution_context(request)
    except flow109.Flow109Error as exc:
        raise Refusal("M89_UPSTREAM_CONTEXT_INVALID", step) from exc
    if request.get("requested_step") != step:
        raise Refusal("M89_UPSTREAM_CONTEXT_INVALID", step)
    dispatch = request["resolved_row"]["profile"].get("dispatch") or {}
    adapter = importlib.import_module(dispatch["adapter"])
    consume = getattr(adapter, "consume_default_row_completion", None)
    if callable(consume) and step != "A17":
        completion = consume(project, request, owner_component)
        if owner_component is not component:
            for key in ("selected_obligations", "input_sha256", "source_sha256", "evidence", "component_receipt"):
                if key in completion and component.get(key) != completion[key]:
                    raise Refusal("M89_UPSTREAM_COMPLETION_MISMATCH", step + ": " + key)
            # Keep canonical metric/prerequisite vetoes while re-opening raw
            # owner evidence. Neither layer can upgrade the other's refusal.
            states = (component.get("default_row_status"), completion.get("default_row_status"))
            status = ("FAIL" if "FAIL" in states else "PASS"
                      if states == ("PASS", "PASS") and component.get("completed") is True
                      and completion.get("completed") is True else "NOT_MEASURED")
            completion = {**component, **completion, "default_row_status": status,
                          "completed": status == "PASS"}
    elif step in ("D69", "D70"):
        # These owners expose material validators, not the legacy completion API.
        validate = (adapter.validate_final_parasitics if step == "D69"
                    else adapter.validate_final_electrical)
        validate(project, {"path": str(path.relative_to(project)), "sha256": _sha(path)})
        completion = component
    elif step == "M02":
        prepared = adapter.prepare(project, request)
        adapter._before(project, request, prepared)
        import mixed_signal_m3_run as m3
        m3.verify(project, "cosim")
        if (component.get("inputs") != prepared["inputs"]
                or component.get("operation_sources") != prepared["sources"]
                or adapter._literal_measured_failures(project)):
            raise Refusal("M89_UPSTREAM_NOT_ACCEPTED", step)
        completion = component
    elif step == "A17":
        report = component.get("native_results") or {}
        blocks = [row.get("name") or row.get("block") for row in adapter._declared_blocks(project)]
        rows = [row for row in report.get("steps", ()) if row.get("step") == step]
        if (not blocks or sorted(row.get("block") for row in rows) != sorted(blocks)
                or report.get("source_sha256") != _sha(Path(adapter.__file__))):
            raise Refusal("M89_A17_POPULATION_INVALID", step)
        for row in rows:
            views = {**(row.get("input_views") or {}), **(row.get("output_views") or {})}
            current = adapter._input_views(project, row["block"], step)
            if (row.get("status") != "PASS" or not current or not row.get("output_views")
                    or any(row["input_views"].get(key) != value for key, value in current.items())
                    or any(not Path(key).is_file() or _sha(key) != value for key, value in views.items())
                    or (row.get("producer_context") or {}).get("image") != _runtime_image(project)):
                raise Refusal("M89_A17_CURRENT_RESULT_INVALID", row["block"])
        completion = component
    elif step == "M05":
        import mixed_signal_m3_run as m3
        audit = m3.audit(project, "si")
        raise Refusal("M05_SUBSTRATE_SUPPLY_MODEL_UNSUPPORTED_OPEN_DEFAULT", step,
                      status="FAIL" if audit.get("verdict") == "FAIL" else "NOT_MEASURED")
    else:
        raise Refusal("M89_UPSTREAM_CONSUMER_UNAVAILABLE", step)
    if completion.get("default_row_status") != "PASS" or completion.get("completed") is not True:
        raise Refusal("M89_UPSTREAM_NOT_ACCEPTED", step,
                      status="FAIL" if completion.get("default_row_status") == "FAIL" else "NOT_MEASURED")
    if step == "M08":
        accepted = bind_metrics(project, request, owner_component)
        if accepted["status"] != "PASS":
            raise Refusal("M89_UPSTREAM_METRICS_NOT_ACCEPTED", step, status=accepted["status"])
    return completion


def bind_metrics(project, context, component):
    """BLOCKING M08/M09 metric consumption, read-only and without native replay.

    Uses the existing owner completion, native M3 re-derivation and typed
    requirement operators. Unsupported measurements stay NOT_MEASURED. This
    result never establishes tool qualification or whole-IC acceptance.
    """
    import flow109_metric_acceptance as metrics
    import mixed_signal_m3_run as m3
    import _mixed_signal_native as native
    import _mixed_signal_current as current
    import flow109_final_extract as final_extract

    project = Path(project).resolve()
    step = context.get("requested_step")
    answer = {"schema": metrics.SCHEMA, "step_id": step, "status": "NOT_MEASURED",
              "metric_status": "NOT_MEASURED", "qualification": "NOT_MEASURED",
              "delivery_blocked": True, "obligations": [],
              "whole_flow_acceptance": "NOT_MEASURED", "whole_ic_acceptance": "NOT_MEASURED"}
    observations = []
    try:
        if step not in ("M08", "M09"):
            raise Refusal("M89_CONTEXT_INVALID", str(step))
        completion = consume_default_row_completion(project, context, component)
        if completion.get("default_row_status") != "PASS" or completion.get("completed") is not True:
            raise Refusal(completion.get("reason", "M89_OWNER_INCOMPLETE"), step,
                          status="FAIL" if completion.get("default_row_status") == "FAIL" else "NOT_MEASURED")
        manifest = _read(project / "input/flow109" / (step + ".json"))
        inputs = _current_inputs(project, step, manifest["top"], manifest)
        native_inputs = m3.inputs(project, manifest["top"])
        if not native_inputs or any(value is None for value in native_inputs.values()):
            raise Refusal("M89_FINAL_INPUT_ABSENT", "current M3 inputs")
        inputs = {**inputs, **native_inputs}
        geometry = {"path": "phase3/mixed_signal/top_merged.gds",
                    "sha256": _sha(project / "phase3/mixed_signal/top_merged.gds")}
        if manifest.get("geometry_sha256") != geometry["sha256"]:
            raise Refusal("M89_FINAL_GEOMETRY_STALE", step)
        final_manifest = manifest if step == "M08" else _read(project / "input/flow109/M08.json")
        final = final_extract.validate_final_parasitics(project, final_manifest.get("d69_receipt"))
        final_gds = _bound_ref(project, final.get("final_gds"), "D69 final GDS")
        if _sha(final_gds) != geometry["sha256"]:
            raise Refusal("M89_FOREIGN_FINAL_GEOMETRY", "D69 and M3 consume different final GDS")
        data = native.contract(project, manifest["top"])
        if data.get("scope") != current.SCOPE or not data.get("_current"):
            raise Refusal("M89_FINAL_MODEL_NOT_CURRENT", "schematic/component models cannot certify final AMS")
        required_steps = (("M05", "M06", "A17", "D69", "D70") if step == "M08"
                          else ("M02", "M06", "M08", "D70"))
        upstream = {name: _accepted_upstream(project, manifest, name) for name in required_steps}
        # Bind shared material, rather than merely comparing row labels.
        for name, accepted in upstream.items():
            shared = set(inputs) & set(accepted.get("input_sha256") or {})
            if not shared or any(inputs[key] != accepted["input_sha256"][key] for key in shared):
                raise Refusal("M89_UPSTREAM_CARRIER_MISMATCH", name)
            if name in ("M06", "M08") and accepted["input_sha256"].get(geometry["path"]) != geometry["sha256"]:
                raise Refusal("M89_UPSTREAM_CARRIER_MISMATCH", name + " geometry")
        native_record = m3.verify(project, "cosim")
        m3.verify(project, "si")
        cosim, si = _read(project / m3.COSIM), _read(project / m3.SI)
        identity = {"geometry": geometry, "consumed_inputs": inputs,
                    "producer": {"name": m3.PROGRAM, "receipt_sha256": _sha(project / m3.RECEIPT)},
                    "checker": operation_sources(), "tool_execution": native_record.get("execution"),
                    "configuration": {"manifest_sha256": _sha(project / "input/flow109" / (step + ".json"))},
                    "requirements": "bound-per-obligation"}

        def evaluate(oid, operator, measured, authority):
            status, reason = metrics.evaluate_operator(operator,
                {"status": "MEASURED", "identity": {**identity, "requirements": authority}, **measured}, authority)
            observations.append({"id": oid, "status": status, "reason": reason,
                                 "measurement": measured, "authority": authority})

        if step == "M08":
            authority, _ = metrics._approved_authority(project,
                "requirements/ams_final/final_ams_scenarios.json#/required_items", ("scenario",))
            rows = cosim.get("scenarios")
            if (not isinstance(rows, list) or not rows
                    or any(row.get("status") != "PASS" for row in rows)):
                raise Refusal("M89_FINAL_SCENARIOS_INCOMPLETE", "no complete native scenario population")
            evaluate(ROWS[step]["obligations"][0], "covers_all",
                     {"value": [{"scenario": row["id"]} for row in rows]}, authority)
            authority, bounds = metrics._approved_document(project,
                "requirements/ams_final/final_ams_noise_settling_calibration.json",
                authority="requirements_owner", schema=metrics.AUTHORITY_SCHEMA)
            limits, units = bounds.get("limits"), bounds.get("units")
            if (not isinstance(limits, dict) or not limits or not isinstance(units, dict)
                    or set(limits) != set(units)):
                raise Refusal("M89_BOUNDS_INCOMPLETE", "nonempty matching limits/units required")
            # Select only metrics the native reader re-derived from tool output.
            values = {}
            for row in rows:
                for criterion in row.get("criteria", ()):
                    key = row["id"] + "/" + criterion["native_metric"]
                    unit = "V" if criterion["native_metric"] in (
                        "settled_voltage_min_v", "settled_voltage_max_v") else "count"
                    values[key] = {"value": criterion["measured"], "unit": unit}
                for name, value in (row.get("metrics") or {}).items():
                    if name in native.METRICS:
                        unit = "V" if name in ("settled_voltage_min_v", "settled_voltage_max_v") else "count"
                        values[row["id"] + "/" + name] = {"value": value, "unit": unit}
            noise = si.get("receiver_noise") or {}
            for name, measured in (noise.get("metrics") or {}).items():
                values["receiver_noise/" + name] = {"value": measured["measured"], "unit": measured["units"]}
            interfaces = si.get("current_interfaces")
            if interfaces is not None:
                if (not isinstance(interfaces, list)
                        or any(not isinstance(item, dict) for item in interfaces)
                        or [item.get("id") for item in interfaces] != [row["id"] for row in rows]):
                    raise Refusal("M89_INTERFACE_SCENARIO_POPULATION_MISMATCH", step)
                for interface in interfaces:
                    if interface.get("scope") != current.SCOPE or interface.get("verdict") != "PASS":
                        raise Refusal("M89_CURRENT_INTERFACE_NOT_MEASURED", interface.get("id"),
                                      status="FAIL" if interface.get("verdict") == "FAIL" else "NOT_MEASURED")
                    for name, measured in ((interface.get("noise") or {}).get("metrics") or {}).items():
                        values[interface["id"] + "/" + name] = {
                            "value": measured["measured"], "unit": measured["units"]}
                    for criterion in (interface.get("crosstalk") or {}).get("criteria", ()):
                        values[interface["id"] + "/" + criterion["metric"]] = {
                            "value": criterion["measured"], "unit": criterion["units"]}
            for key, band in limits.items():
                if key not in values:
                    raise Refusal("M89_NATIVE_METRIC_ABSENT", key)
                evaluate(ROWS[step]["obligations"][1], "within_declared_bounds", {"name": key, **values[key]},
                         {**authority, "limits": band, "unit": units[key]})
        else:
            prerequisites = _m09_prerequisites(project, manifest)
            authority, _ = metrics._approved_authority(project,
                "requirements/base_M7/mixed_requirement_evidence.json#/required_items", ("step", "obligation"))
            population = []
            for name, accepted in upstream.items():
                for obligation in accepted.get("selected_obligations", ()):
                    population.append({"step": name, "obligation": obligation})
            population.extend({"step": "A19", "obligation": block}
                              for block in prerequisites["a19_packages"])
            evaluate(ROWS[step]["obligations"][0], "covers_all", {"value": population}, authority)
            authority, adopted = metrics._approved_document(project,
                "adopted/base_M7/mixed_model_final_geometry_identity.json",
                authority="requirements_owner", schema=metrics.AUTHORITY_SCHEMA)
            # Identity covers every current model/interface/PEX input, including
            # the A19 package readset, instead of just the merged GDS name.
            reference = {"geometry": geometry, "inputs": inputs}
            evaluate(ROWS[step]["obligations"][1], "matches_adopted_reference", {"value": reference},
                     {**authority, "reference": adopted.get("reference"),
                      "reference_identity": adopted.get("reference_identity")})
        after = {**_current_inputs(project, step, manifest["top"], manifest),
                 **m3.inputs(project, manifest["top"])}
        if after != inputs:
            raise Refusal("M89_INPUT_CHANGED_DURING_CONSUMPTION", step)
        states = [item["status"] for item in observations]
        status = "FAIL" if "FAIL" in states else "PASS" if states and all(s == "PASS" for s in states) else "NOT_MEASURED"
        answer.update(status=status, metric_status=status, obligations=observations,
                      reason="M89_CURRENT_METRICS_" + status, identity=identity)
    except (Refusal, metrics.MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        status = "FAIL" if (getattr(exc, "status", None) == "FAIL"
            or getattr(exc, "rule", None) in ("FAILED_MEASUREMENT", "NATIVE_EXECUTION_FAILED")) or any(
            row["status"] == "FAIL" for row in observations if isinstance(row, dict)) else "NOT_MEASURED"
        answer.update(status=status, metric_status=status, obligations=observations,
                      reason=getattr(exc, "code", getattr(exc, "rule", "M89_INPUT_UNAVAILABLE")), detail=str(exc))
    return answer


__all__ = ["ROWS", "execute", "consume_default_row_completion", "operation_sources", "bind_metrics"]
