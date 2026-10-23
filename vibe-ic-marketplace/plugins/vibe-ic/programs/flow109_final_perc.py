"""D66 thin binding to the existing Step-28 PERC-equivalent owner.

The existing producer measures open-source structural/electrical screens and
the existing consumer checks its canonical outputs.  This adapter adds no PERC
algorithm.  It binds that run to the current D65-accepted final DEF/GDS and
adopted power netlist.  Automated FAIL is blocking; missing evidence and the
producer's disclosed manual/device-physics residuals remain NOT_MEASURED.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109_admission import AdmissionRefusal, require_launch_admission
import execution_backend_gates as backend_gates
import execution_backend_producers as backend_producers

SCHEMA = "vibeic.flow109.final-perc.v1"
INPUT = "input/flow109/D66.json"
EDA_IMAGE = ("ghcr.io/vibeic/vibeic-eda@sha256:"
             "0fc30ecd1307a11bd7757d1c5710127cd88e245059f29eab8b52e38ba4d60406")
OUTPUTS = (
    "reports/phase3/perc_equivalent.json",
    "reports/phase3/perc_equivalent.rpt",
    "reports/phase3/PERC_SIGNOFF_MEMO.md",
    "reports/phase2/gates/perc_signoff.json",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MANUAL = {
    "ESD protection presence",
    "io_supply_pad_sufficiency",
    "Latch-up / well-tap (spacing + device-physics)",
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code="D66_REQUIRED_INPUT_INVALID"):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project, ref, label):
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str)
            or not isinstance(ref["sha256"], str)
            or not SHA256_RE.fullmatch(ref["sha256"])):
        raise AdmissionRefusal("D66_REQUIRED_INPUT_UNBOUND", label)
    project = Path(project).resolve()
    raw = project / ref["path"]
    path = raw.resolve()
    if raw.is_symlink() or not path.is_relative_to(project) or not path.is_file():
        raise AdmissionRefusal("D66_REQUIRED_INPUT_ABSENT", label)
    if _sha(path) != ref["sha256"]:
        raise AdmissionRefusal("D66_REQUIRED_INPUT_CHANGED", label)
    return path


def _record(project, path):
    project, raw = Path(project).resolve(), Path(path)
    path = raw.resolve()
    if raw.is_symlink() or not path.is_relative_to(project) or not path.is_file():
        raise AdmissionRefusal("D66_OUTPUT_OUTSIDE_PROJECT", str(path))
    return {"path": str(path.relative_to(project)), "sha256": _sha(path)}


def operation_sources():
    names = ("flow109_final_perc.py", "execution_backend_producers.py",
             "execution_backend_gates.py", "phase3_one_shot_runner.py",
             "perc_signoff_check.py", "perc_corpus_sweep.py",
             "latchup_esd_spacing_check.py", "librelane_postroute.py")
    return {"programs/" + name: _sha(HERE / name) for name in names}


def _canonical_step31_bindings(receipt, geometry_def_sha):
    """Validate the existing canonical Step-31 authority, without inventing a wrapper."""
    statuses = [receipt.get("verdict"), receipt.get("producer_verdict")]
    gates = receipt.get("gates")
    if isinstance(gates, dict):
        statuses += list(gates.values())
    statuses.append((receipt.get("canonical_step_result") or {}).get("status"))
    canonical = receipt.get("canonical_receipts")
    if isinstance(canonical, list):
        statuses += [row.get("verdict") for row in canonical if isinstance(row, dict)]
    ledger = receipt.get("gate_ledger")
    if isinstance(ledger, list):
        statuses += [row.get("verdict") for row in ledger if isinstance(row, dict)]
    if "FAIL" in statuses:
        raise AdmissionRefusal("D66_D65_CANONICAL_FAILED", "Step 31 FAIL",
                               status="FAIL")
    if receipt.get("schema") != "vibeic/backend-result/2":
        raise AdmissionRefusal("D66_D65_CANONICAL_SCHEMA_INVALID",
                               "vibeic/backend-result/2 required")
    if str(receipt.get("step_id")) != "31":
        raise AdmissionRefusal("D66_D65_CANONICAL_WRONG_STEP",
                               repr(receipt.get("step_id")))
    if receipt.get("verdict") != "PASS" or receipt.get("producer_verdict") != "PASS":
        raise AdmissionRefusal("D66_D65_CANONICAL_NOT_ACCEPTED", "Step 31 PASS required")
    binding = receipt.get("binding")
    required_gates = {"backend_canonical", "backend_native_substance"}
    if (not isinstance(binding, dict) or str(binding.get("step_id")) != "31"
            or binding.get("source_sha") != receipt.get("source_sha")
            or not isinstance(binding.get("required_gates"), list)
            or not required_gates.issubset(binding["required_gates"])
            or not isinstance(gates, dict)
            or any(gates.get(name) != "PASS"
                   for name in required_gates)):
        raise AdmissionRefusal("D66_D65_CANONICAL_GATE_BINDING_INVALID",
                               "Step 31 canonical/native gates")
    census = receipt.get("current_step_declared_producers")
    if (not isinstance(census, dict)
            or census.get("schema") != "vibeic/current-step-producer-census/1"
            or str(census.get("step_id")) != "31" or census.get("verdict") != "PRODUCED"
            or census.get("consumer_allowed") is not True
            or census.get("authority_verdict") != "PASS"
            or census.get("cross_invocation_reuse") is not False
            or census.get("input_identity_scope") != "row_manifest_and_native_siblings"
            or census.get("invalid_results") != [] or census.get("unexecutable") != []
            or not isinstance(census.get("population"), int) or census["population"] <= 0
            or census.get("executed") != census["population"]
            or census.get("documents_now_present") != census["population"]):
        raise AdmissionRefusal("D66_D65_CANONICAL_PRODUCER_BINDING_INVALID",
                               "current Step 31 producer census")
    allowed, detail, authority = backend_producers._current_step_producer_authority(census)
    if not allowed:
        raise AdmissionRefusal("D66_D65_CANONICAL_PRODUCER_BINDING_INVALID", detail,
                               status="FAIL" if authority == "FAIL" else "NOT_MEASURED")
    identity = census.get("input_identity")
    files = identity.get("files") if isinstance(identity, dict) else None
    source_files = identity.get("source_files") if isinstance(identity, dict) else None
    source_sha = identity.get("source_sha") if isinstance(identity, dict) else None
    if (not isinstance(files, dict) or not isinstance(source_files, dict) or not source_files
            or not isinstance(source_sha, str)
            or not SHA256_RE.fullmatch(source_sha.removeprefix("sha256:"))
            or any(not isinstance(name, str) or not isinstance(digest, str)
                   or not SHA256_RE.fullmatch(digest)
                   for name, digest in {**files, **source_files}.items())):
        raise AdmissionRefusal("D66_D65_CANONICAL_INPUT_IDENTITY_INVALID",
                               "current Step 31 input/source hashes")
    routed_def = "phase3/stage3/pnr/routed.def"
    if files.get(routed_def) != geometry_def_sha:
        raise AdmissionRefusal("D66_D65_CANONICAL_FINAL_DEF_MISMATCH", routed_def)
    if (not isinstance(canonical, list) or len(canonical) != 1
            or not isinstance(canonical[0], dict)
            or canonical[0].get("schema") != "vibeic/backend-producer-receipt/1"
            or canonical[0].get("producer") != "execution_backend_producers.produce"
            or str(canonical[0].get("step_id")) != "31"
            or canonical[0].get("verdict") != "PASS"
            or canonical[0].get("current_step_declared_producers") != census):
        raise AdmissionRefusal("D66_D65_CANONICAL_PRODUCER_RECEIPT_INVALID",
                               "matching Step 31 producer receipt")
    if (not isinstance(ledger, list) or not ledger
            or any(not isinstance(row, dict) or row.get("rc") != 0
                   or row.get("verdict") != "PASS" for row in ledger)):
        raise AdmissionRefusal("D66_D65_CANONICAL_GATE_LEDGER_INVALID",
                               "executed Step 31 PASS gates required")
    step = receipt.get("canonical_step_result")
    output_binding = step.get("output_binding") if isinstance(step, dict) else None
    outputs = receipt.get("outputs")
    specs = output_binding.get("specs") if isinstance(output_binding, dict) else None
    if (not isinstance(step, dict) or str(step.get("id")) != "31"
            or step.get("status") != "PASS" or receipt.get("missing_outputs") != []
            or not isinstance(outputs, dict) or not outputs
            or not isinstance(specs, list) or not specs
            or output_binding.get("mode") != "step_attributed"
            or output_binding.get("source") != "step_folder"
            or output_binding.get("n_project_glob") != 0
            or output_binding.get("n_specs") != len(outputs)
            or output_binding.get("n_satisfied") != len(outputs)
            or output_binding.get("n_step_attributed") != len(outputs)
            or set(output_binding.get("codes") or []) != {"step_attributed"}
            or output_binding.get("notes") != []
            or any(not isinstance(row, dict) or row.get("satisfied") is not True
                   or row.get("mode") != "step_attributed"
                   or row.get("code") != "step_attributed"
                   or not isinstance(row.get("spec"), str) for row in specs)
            or any(not isinstance(path, str) or Path(path).is_absolute()
                   or ".." in Path(path).parts or not isinstance(digest, str)
                   or not SHA256_RE.fullmatch(digest) for path, digest in outputs.items())):
        raise AdmissionRefusal("D66_D65_CANONICAL_OUTPUT_BINDING_INVALID",
                               "all Step 31 outputs must be live and step-attributed")
    if {row["spec"] for row in specs} != set(outputs):
        raise AdmissionRefusal("D66_D65_CANONICAL_OUTPUT_BINDING_INVALID",
                               "Step 31 output specifications differ")
    results = census.get("results")
    if (not isinstance(results, list) or len(results) != census["population"]
            or any(not isinstance(row, dict) or str(row.get("step")) != "31"
                   or row.get("target_content_valid") is not True
                   or row.get("authorship") != "producer"
                   or outputs.get(row.get("target")) != row.get("target_sha256")
                   for row in results)):
        raise AdmissionRefusal("D66_D65_CANONICAL_PRODUCER_RESULTS_INVALID",
                               "Step 31 producer result/output identity")
    return {"routed_def": {"path": routed_def, "sha256": geometry_def_sha},
            "outputs": outputs}


def _d65_current(project, ref, paths):
    path = _bound(project, ref, "D65 evidence")
    evidence = _read(path)
    if evidence.get("schema") == "vibeic.flow109.window-component.v1":
        if (evidence.get("step_id") != "D65" or evidence.get("native_step_id") != "31"
                or evidence.get("component_status") != "PASS"
                or evidence.get("flow109_acceptance") != "NOT_MEASURED"):
            raise AdmissionRefusal("D66_D65_COMPONENT_NOT_ACCEPTED", str(path))
        receipt_ref = evidence.get("canonical_receipt")
        receipt_path = _bound(project, receipt_ref, "D65 canonical receipt")
        receipt = _read(receipt_path)
        if (receipt.get("schema") != "vibeic/backend-result/2"
                or str(receipt.get("step_id")) != "31" or receipt.get("verdict") != "PASS"):
            raise AdmissionRefusal("D66_D65_COMPONENT_NOT_ACCEPTED", "canonical Step 31 PASS")
        return {"kind": "window_component", "evidence": evidence, "receipt": receipt,
                "bound_paths": [path, receipt_path]}
    bindings = _canonical_step31_bindings(evidence, _sha(paths["geometry_def"]))
    bound = [path, _bound(project, bindings["routed_def"], "D65 routed DEF")]
    bound.extend(_bound(project, {"path": name, "sha256": digest},
                        "D65 canonical output: " + name)
                 for name, digest in bindings["outputs"].items())
    return {"kind": "canonical_step31", "evidence": evidence, "receipt": evidence,
            "bound_paths": bound}


def _expected_extracted(project):
    root = Path(project) / "phase3/stage3/extracted"
    if not root.is_dir():
        return None
    candidates = (sorted(root.glob("*.spice")) + sorted(root.glob("*.cir"))
                  + sorted(root.glob("*_pex.v")))
    return candidates[0].resolve() if candidates else None


def _prepare(project, context):
    project = Path(project).resolve()
    if (context.get("requested_step") != "D66"
            or context.get("native_step_id") != "flow109.D66"):
        raise AdmissionRefusal("D66_CONTEXT_MISMATCH", "final PERC adapter only")
    manifest_path = project / INPUT
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise AdmissionRefusal("D66_REQUIRED_INPUT_ABSENT", INPUT)
    manifest = _read(manifest_path)
    if manifest.get("schema") != SCHEMA or set(manifest) != {
            "schema", "d65_component", "final_subjects", "backend"}:
        raise AdmissionRefusal("D66_REQUIRED_INPUT_INVALID", "D66 manifest schema")
    subjects = manifest.get("final_subjects")
    if not isinstance(subjects, dict) or set(subjects) != {
            "geometry_def", "geometry_gds", "adopted_netlist",
            "extracted_netlist", "pad_supply_def"}:
        raise AdmissionRefusal("D66_FINAL_SUBJECTS_ABSENT", "five typed final roles required")
    paths = {}
    for name in ("geometry_def", "geometry_gds", "adopted_netlist", "pad_supply_def"):
        paths[name] = _bound(project, subjects[name], name)
    if subjects["extracted_netlist"] is None:
        paths["extracted_netlist"] = None
    else:
        paths["extracted_netlist"] = _bound(
            project, subjects["extracted_netlist"], "extracted_netlist")
    backend = manifest.get("backend")
    if (not isinstance(backend, dict) or set(backend) != {
            "image_id", "pdk_root", "pdk_name", "top"}
            or backend.get("image_id") != EDA_IMAGE
            or not all(isinstance(backend.get(name), str) and backend[name]
                       for name in ("pdk_root", "pdk_name", "top"))):
        raise AdmissionRefusal("D66_NATIVE_CONFIGURATION_ABSENT",
                               "pinned image/pdk_root/pdk_name/top required")
    top = backend["top"]
    expected = {
        "geometry_def": project / f"phase3/stage3/pnr/{top}.def",
        "geometry_gds": project / f"phase3/stage3/pnr/{top}.gds",
        "adopted_netlist": project / f"phase3/stage3/pnr/{top}_pnr.v",
    }
    if any(paths[name] != value.resolve() for name, value in expected.items()):
        raise AdmissionRefusal("D66_FINAL_SUBJECT_ROLE_MISMATCH", str(expected))
    if paths["pad_supply_def"] != paths["geometry_def"]:
        raise AdmissionRefusal("D66_PAD_SUPPLY_VIEW_MISMATCH",
                               "pad/supply topology must use the final DEF")
    if paths["extracted_netlist"] != _expected_extracted(project):
        raise AdmissionRefusal("D66_EXTRACTED_NETLIST_MISMATCH",
                               "declared view differs from producer selection")
    d65 = _d65_current(project, manifest["d65_component"], paths)
    inputs = {str(path): _sha(path) for path in paths.values() if path is not None}
    inputs.update({str(path): _sha(path) for path in d65["bound_paths"]})
    inputs[str(project / INPUT)] = _sha(project / INPUT)
    resolved_files = {str(Path(path).relative_to(project)): digest
                      for path, digest in inputs.items()}
    params = {**backend, "step_id": "28", "execution_mode": "default",
              "stop_on_producer_failure": True, "timeout_s": 1800,
              "resolved_input_manifest": {"files": resolved_files}}
    return {"manifest": manifest, "subjects": subjects, "paths": paths,
            "inputs": inputs, "params": params, "sources": operation_sources(),
            "d65": d65["evidence"], "d65_receipt": d65["receipt"],
            "d65_evidence_kind": d65["kind"]}


def _assert_current(prepared):
    if prepared["sources"] != operation_sources():
        raise AdmissionRefusal("D66_OPERATION_SOURCE_CHANGED", "D66 owner/consumer source")
    for path, digest in prepared["inputs"].items():
        if Path(path).is_symlink() or not Path(path).is_file() or _sha(path) != digest:
            raise AdmissionRefusal("D66_REQUIRED_INPUT_CHANGED", path)


def _d65_geometry_current(project, prepared):
    """Reuse Step 31's own admitted-GDS boundary for the exact final GDS."""
    runner, _ll, pdk, container = backend_producers._parameters(
        Path(project), prepared["params"])
    basis, error = runner._layout_basis(Path(project), prepared["params"]["top"],
                                        pdk, container)
    if (error or not runner._ga.admitted_gds(
            Path(project), prepared["paths"]["geometry_gds"], basis)):
        raise AdmissionRefusal("D66_D65_FINAL_GEOMETRY_NOT_ADMITTED", str(error or basis))


def _manual_and_limits(summary):
    categories = summary.get("categories")
    if not isinstance(categories, list) or not categories:
        raise AdmissionRefusal("D66_PERC_RESULT_INVALID", "category population absent")
    if any(not isinstance(row, dict) or not isinstance(row.get("category"), str)
           for row in categories):
        raise AdmissionRefusal("D66_PERC_RESULT_INVALID", "category record invalid")
    manual = [row["category"] for row in categories
              if row.get("status") == "MANUAL_REVIEW"]
    if summary.get("manual_review_pending") != manual:
        raise AdmissionRefusal("D66_MANUAL_DISCLOSURE_MISMATCH", repr(manual))
    if not REQUIRED_MANUAL.issubset(manual):
        raise AdmissionRefusal("D66_REQUIRED_REVIEW_CATEGORY_ABSENT",
                               repr(sorted(REQUIRED_MANUAL - set(manual))))
    failed = [row["category"] for row in categories
              if row.get("status") == "AUTOMATED" and row.get("result") == "FAIL"]
    incomplete = [row["category"] for row in categories
                  if row.get("status") == "AUTOMATED"
                  and row.get("result") == "INCOMPLETE"]
    if summary.get("automated_failed") != failed or summary.get("automated_incomplete") != incomplete:
        raise AdmissionRefusal("D66_AUTOMATED_DISCLOSURE_MISMATCH",
                               repr({"failed": failed, "incomplete": incomplete}))
    expected = ("PERC_EQUIV_FAIL" if failed else
                "PERC_EQUIV_INCOMPLETE" if incomplete else "PERC_EQUIV_PASS")
    if (summary.get("verdict") != expected
            or summary.get("commercial_calibre_perc_run") is not False):
        raise AdmissionRefusal("D66_PERC_RESULT_INVALID", "verdict/capability disclosure")
    unsupported = []
    residual = summary.get("geometry_foundry_data_residual")
    if not isinstance(residual, str) or not residual.strip():
        raise AdmissionRefusal("D66_FOUNDRY_CAPABILITY_DISCLOSURE_ABSENT",
                               "device-physics residual required")
    unsupported.append(residual)
    return manual, failed, incomplete, unsupported


def _output_records(project):
    return {name: _record(project, Path(project) / name) for name in OUTPUTS}


def _io_sources(summary):
    sources = next((row.get("library_sources") or []
                    for row in summary.get("categories", [])
                    if row.get("category") == "ESD protection presence"), [])
    if not isinstance(sources, list) or not sources or any(
            not isinstance(item, dict) or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or not SHA256_RE.fullmatch(item["sha256"])
            for item in sources):
        raise AdmissionRefusal("D66_PAD_LIBRARY_EVIDENCE_INVALID", "IO library sources")
    return sources


def _owner_status(producer, gate, summary):
    manual, failed, incomplete, unsupported = _manual_and_limits(summary)
    producer_status, gate_status = producer.get("verdict"), gate.get("status")
    if producer_status == "FAIL" or gate_status == "FAIL" or failed:
        status, reason = "FAIL", "D66_AUTOMATED_PERC_FAILED"
    elif (producer_status != "PASS" or gate_status != "PASS" or incomplete
          or summary.get("verdict") != "PERC_EQUIV_PASS"):
        status, reason = "NOT_MEASURED", "D66_AUTOMATED_PERC_INCOMPLETE"
    elif manual:
        status, reason = "NOT_MEASURED", "D66_MANUAL_REVIEW_PENDING"
    elif unsupported:
        status, reason = "NOT_MEASURED", "D66_DEVICE_PHYSICS_UNSUPPORTED"
    else:
        status, reason = "PASS", "D66_OPEN_SOURCE_PERC_COMPONENT_COMPLETE"
    automated = "FAIL" if failed or producer_status == "FAIL" or gate_status == "FAIL" else (
        "PASS" if producer_status == gate_status == "PASS" and not incomplete else "NOT_MEASURED")
    return status, reason, automated, manual, unsupported


def execute(project, context):
    project = Path(project).resolve()
    attempt = project / "reports/flow109/D66" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {"schema": SCHEMA, "step_id": "D66", "component_status": "NOT_MEASURED",
              "automated_component_status": "NOT_MEASURED",
              "flow109_acceptance": "NOT_MEASURED", "whole_ic_acceptance": "NOT_MEASURED",
              "native_started": False, "context_sha256": context.get("context_sha256")}
    try:
        require_launch_admission(project, "flow109.D66", {"flow109_context": context})
        prepared = _prepare(project, context)
        _assert_current(prepared)
        _d65_geometry_current(project, prepared)
        result["native_started"] = True
        producer = backend_producers.produce(project, prepared["params"])
        if not isinstance(producer, dict) or producer.get("verdict") not in {
                "PASS", "FAIL", "NOT_MEASURED"}:
            raise AdmissionRefusal("D66_EXISTING_PRODUCER_RESULT_INVALID", repr(producer))
        _assert_current(prepared)
        if producer["verdict"] != "PASS":
            failed = producer["verdict"] == "FAIL"
            result.update(
                component_status="FAIL" if failed else "NOT_MEASURED",
                automated_component_status="FAIL" if failed else "NOT_MEASURED",
                reason="D66_AUTOMATED_PERC_FAILED" if failed
                       else "D66_AUTOMATED_PERC_INCOMPLETE",
                producer_result=producer,
                consumer_result={"status": "NOT_MEASURED",
                                 "reason": "D66_PRODUCER_DID_NOT_PASS"},
                commercial_perc_qualification="NOT_CLAIMED",
                final_subjects=prepared["subjects"], inputs=prepared["inputs"],
                d65_component=prepared["manifest"]["d65_component"],
                d65_evidence_kind=prepared["d65_evidence_kind"],
                operation_sources=prepared["sources"], execution_context=context)
        else:
            canonical = backend_gates.canonical_family_row("28")
            if (not isinstance(canonical, dict)
                    or "perc_signoff_check" not in backend_gates.required_programs(canonical)):
                raise AdmissionRefusal("D66_EXISTING_CONSUMER_ABSENT", "canonical Step 28")
            gate = backend_gates.evaluate(project, canonical)
            _assert_current(prepared)
            summary = _read(project / OUTPUTS[0], "D66_PERC_RESULT_INVALID")
            status, reason, automated, manual, unsupported = _owner_status(
                producer, gate, summary)
            outputs = _output_records(project)
            io_sources = _io_sources(summary)
            result.update(component_status=status, automated_component_status=automated,
                          reason=reason, producer_result=producer, consumer_result=gate,
                          perc_summary=summary, manual_review_pending=manual,
                          unsupported_capabilities=unsupported,
                          commercial_perc_qualification="NOT_CLAIMED",
                          final_subjects=prepared["subjects"], inputs=prepared["inputs"],
                          d65_component=prepared["manifest"]["d65_component"],
                          d65_evidence_kind=prepared["d65_evidence_kind"],
                          outputs=outputs, io_library_sources=io_sources,
                          operation_sources=prepared["sources"], execution_context=context)
    except AdmissionRefusal as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Exception as exc:
        result.update(component_status="NOT_MEASURED",
                      reason="D66_EXISTING_OWNER_UNAVAILABLE_OR_UNSUPPORTED", detail=str(exc))
    path = attempt / "component.json"
    write_json(path, result)
    result["receipt"] = _record(project, path)
    return result


def validate_final_perc(project, receipt_ref):
    """Re-open D66 component evidence; never promote manual residuals to PASS."""
    project = Path(project).resolve()
    record = _read(_bound(project, receipt_ref, "D66 component"))
    if record.get("schema") != SCHEMA or record.get("step_id") != "D66":
        raise AdmissionRefusal("D66_COMPONENT_NOT_ACCEPTED", "typed D66 receipt required")
    require_launch_admission(project, "flow109.D66",
                             {"flow109_context": record.get("execution_context")})
    prepared = _prepare(project, record["execution_context"])
    _assert_current(prepared)
    _d65_geometry_current(project, prepared)
    if (record.get("operation_sources") != prepared["sources"]
            or record.get("inputs") != prepared["inputs"]
            or record.get("final_subjects") != prepared["subjects"]
            or record.get("d65_component") != prepared["manifest"]["d65_component"]
            or record.get("d65_evidence_kind") != prepared["d65_evidence_kind"]
            or record.get("outputs") != _output_records(project)):
        raise AdmissionRefusal("D66_COMPONENT_SUBJECT_CHANGED", "final subject/output binding")
    summary = _read(project / OUTPUTS[0], "D66_PERC_RESULT_INVALID")
    status, reason, automated, manual, unsupported = _owner_status(
        record.get("producer_result") or {}, record.get("consumer_result") or {}, summary)
    if (record.get("perc_summary") != summary or record.get("component_status") != status
            or record.get("reason") != reason
            or record.get("automated_component_status") != automated
            or record.get("manual_review_pending") != manual
            or record.get("unsupported_capabilities") != unsupported
            or record.get("io_library_sources") != _io_sources(summary)):
        raise AdmissionRefusal("D66_COMPONENT_VERDICT_CHANGED", "current owner result differs")
    return {"component_status": status, "automated_component_status": automated,
            "manual_review_pending": manual, "unsupported_capabilities": unsupported,
            "final_subjects": prepared["subjects"], "d65_component": record["d65_component"],
            "d65_evidence_kind": prepared["d65_evidence_kind"],
            "perc_receipt": receipt_ref, "flow109_acceptance": "NOT_MEASURED",
            "whole_ic_acceptance": "NOT_MEASURED"}
