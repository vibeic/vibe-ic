#!/usr/bin/env python3
"""D79 exports owner-selected IP endpoints and consumes their existing audits.

Component observations and source controls do not qualify native tools or the
whole flow. Analog Liberty keeps A8's measured-OP scope and unmeasured arcs.
D79 is BLOCKING for its component/row; missing or failing evidence stops the
requested Flow109 window. Whole-flow qualification remains separate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _analog_a_check_common as analog_content
from _atomic_artefact import write_json
import _physical_current as current_kit
import _tapeout_declaration as declaration
import analog_a8_hardmacro_emit as analog_export
import analog_hardmacro_check as analog_check
import analog_hardmacro_pinname_consistency_check as analog_pins
import analog_lef_gds_outline_check as analog_outline
import digital_hardmacro_check as digital_check
import digital_hardmacro_gen as digital_export
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import ip_release_docs_gen as docs
import pdk_family_identity as pdk_identity
import release_docs_check as docs_check

SCHEMA = "vibeic.flow109.ip-release.v1"
STEP = "D79"
NATIVE_STEP = "flow109.D79"
VIEW_ROLES = {".lef": "lef", ".lib": "liberty", ".gds": "gds", ".v": "verilog"}
METRIC_FIELDS = {"ip_endpoint_views": ("name", "view"),
                 "ip_integration_limits_documented": ("name", "constraint")}
SAFE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_$.-]*\Z")


class D79Refusal(ValueError):
    def __init__(self, code, detail, *, failed=False):
        self.code, self.detail, self.failed = code, str(detail), failed
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class Endpoint:
    kind: str
    name: str
    inputs: tuple[dict, ...]

    def paths(self, project):
        root = (project / "phase3/stage4/hardmacro" if self.kind == "digital"
                else project / "phase3/analog/hardmacro" / self.name)
        return {suffix: root / (self.name + suffix) for suffix in VIEW_ROLES}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(project, raw, code="D79_REQUIRED_INPUT_ABSENT"):
    raw = Path(raw)
    raw = raw if raw.is_absolute() else project / raw
    path = raw.resolve()
    if (raw.is_symlink() or not path.is_relative_to(project)
            or not path.is_file() or path.stat().st_size == 0
            or any(p.is_symlink() for p in raw.parents if p != project.parent)):
        raise D79Refusal(code, str(raw))
    return {"path": str(path.relative_to(project)), "sha256": _sha(path),
            "bytes": path.stat().st_size}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key " + key)
        result[key] = value
    return result


def _read(project, path, *, object_only=True):
    record = _record(project, path)
    try:
        value = json.loads((project / record["path"]).read_text(), object_pairs_hook=_pairs)
    except (OSError, ValueError) as exc:
        raise D79Refusal("D79_REQUIRED_INPUT_INVALID", str(path)) from exc
    if object_only and not isinstance(value, dict):
        raise D79Refusal("D79_REQUIRED_INPUT_INVALID", str(path))
    return value


def operation_sources():
    names = ("flow109_ip_release.py", "flow109.py", "flow109_admission.py",
             "flow109_metric_acceptance.py", "digital_hardmacro_gen.py",
             "digital_hardmacro_check.py", "_physical_current.py",
             "analog_a8_hardmacro_emit.py", "_analog_a_check_common.py",
             "_analog_stub_marker.py", "analog_a5_layout_check.py", "_opensta_current.py",
             "_analog_a8_extraction_wrapper.py",
             "analog_hardmacro_check.py", "analog_hardmacro_pinname_consistency_check.py",
             "analog_lef_gds_outline_check.py", "hardmacro_supply_intent.py",
             "ip_release_docs_gen.py", "release_docs_check.py", "_release_docs_build.py",
             "_release_docs_contract.py", "_tapeout_declaration.py", "pdk_family_identity.py",
             "pdk_registry.json", "analog_a7_post_layout_emit.py")
    return {"programs/" + name: _sha(HERE / name) for name in names}


def _context(project, context):
    try:
        checked = flow109.validate_execution_context(context)
        row = checked["resolved_row"]
        if (checked["requested_step"] != STEP or checked["native_step_id"] != NATIVE_STEP
                or row["selected_profile"] != "default" or row["id"] != STEP
                or row["profile"]["dispatch"]["adapter"] != "flow109_ip_release"
                or not flow109.predicate("ip", checked["features"])):
            raise ValueError("selected D79/default IP context required")
        path = Path("reports/flow109/requests") / (checked["context_sha256"] + ".json")
        if _read(project, path) != checked:
            raise ValueError("saved canonical request differs")
        return checked, _record(project, path)
    except (KeyError, TypeError, ValueError) as exc:
        raise D79Refusal("D79_CONTEXT_MISMATCH", str(exc)) from exc


def _endpoints(project, context):
    owner_path = Path(declaration.DECLARATION_REL)
    owner = _read(project, owner_path)
    route, error = declaration.load(project / owner_path)
    provenance = owner.get("answer_provenance", {}).get("deliverable", {})
    if (error or declaration.answer(route, "deliverable") != declaration.DELIVERABLE_HARDMACRO
            or provenance.get("answered_by") != "owner" or not provenance.get("citation")):
        raise D79Refusal("D79_ENDPOINT_UNBOUND", "owner HARDMACRO declaration required")
    endpoints = []
    if context["features"]["has_digital"]:
        candidates = [project / value for value in digital_export._DEF_CANDIDATES
                      if (project / value).is_file()]
        if not candidates:
            raise D79Refusal("D79_REQUIRED_INPUT_ABSENT", "canonical routed DEF")
        routed = candidates[0]
        match = digital_export._DEF_DESIGN_RE.search(routed.read_text())
        if match is None or not SAFE_NAME.fullmatch(match.group(1)):
            raise D79Refusal("D79_ENDPOINT_UNBOUND", "routed DEF DESIGN")
        name = match.group(1)
        gds = list((project / "phase3/stage4/gds").glob("*.gds"))
        if len(gds) != 1 or gds[0].stem != name:
            raise D79Refusal("D79_ENDPOINT_UNBOUND", "unique signoff GDS must match routed DESIGN")
        endpoints.append(Endpoint("digital", name, tuple(_record(project, path)
            for path in (owner_path, routed, gds[0]))))
    if context["features"]["has_analog"]:
        manifest = Path("phase3/analog/analog_block_list.json")
        declaration_doc = _read(project, manifest, object_only=False)
        declared = declaration_doc.get("blocks") if isinstance(declaration_doc, dict) else declaration_doc
        names = analog_export.declared_blocks(project)
        if (not isinstance(declared, list) or len(declared) != len(names)
                or any(isinstance(entry, dict) and entry.get("name") and entry.get("block")
                       and entry["name"] != entry["block"] for entry in declared)
                or not names or len(names) != len(set(names))
                or any(not isinstance(name, str) or not SAFE_NAME.fullmatch(name) for name in names)):
            raise D79Refusal("D79_ENDPOINT_UNBOUND", "nonempty unique declared analog blocks required")
        discovered = analog_pins._discover_blocks(project)
        if set(discovered) != set(names):
            raise D79Refusal("D79_ENDPOINT_UNBOUND", "declared and spec-bearing analog populations differ")
        for name in sorted(names):
            root = Path("phase3/analog") / name
            endpoints.append(Endpoint("analog", name, tuple(_record(project, path)
                for path in (owner_path, manifest, root / "spec.json", root / "topology.json",
                             root / (name + ".gds")))))
    if not endpoints or len({ep.name for ep in endpoints}) != len(endpoints):
        raise D79Refusal("D79_ENDPOINT_UNBOUND", "empty or colliding release population")
    return endpoints


def _views(project, endpoint):
    return {suffix: _record(project, path, "D79_VIEW_MISSING")
            for suffix, path in endpoint.paths(project).items()}


def _structural(project, endpoint):
    views = endpoint.paths(project)
    _views(project, endpoint)
    ok, findings, detail = digital_check.check_package(endpoint.name, views, project,
        digital_check.DEFAULT_TOL_PCT, digital_check.DEFAULT_TOL_UM)
    return {"check": "digital_hardmacro_check.check_package", "status": "PASS" if ok else "FAIL",
            "detail": detail, "findings": [asdict(row) for row in findings]}


def _lineage(project, endpoint):
    if endpoint.kind == "digital":
        refusal = current_kit.check_kit(project)
        if refusal:
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", refusal)
        path = Path("phase3/stage4/hardmacro/current_kit.json")
        native = _read(project, path)
        if native.get("design") != endpoint.name:
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", "current_kit design differs")
        audit = digital_check.run_audit(project)
        _require_checks([_digital_audit(audit)])
        return [_record(project, path)], {"timing_arcs": "CURRENT_CHECKED_LIBERTY",
            "audit_tier": audit.verdict_tier,
            "obstruction_not_determined": audit.summary.get("obstruction_not_determined", [])}
    root = project / "phase3/analog" / endpoint.name
    topology = _read(project, root / "topology.json")
    measurement, reason = analog_export.load_native_measurement(
        project, endpoint.name, root / (endpoint.name + ".gds"), topology)
    if measurement is None or analog_content._a8_declared_content(root) is None:
        raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", reason or "A8 current view/A3 binding refused")
    manifest_path = Path("phase3/analog/hardmacro") / endpoint.name / "a8_views_provenance.json"
    manifest = _read(project, manifest_path)
    return [_record(project, manifest_path), _record(project, root / "a8_measurement.json")], \
        manifest["characterization_scope"]


def _require_checks(checks):
    if any(row["status"] == "FAIL" for row in checks):
        raise D79Refusal("D79_EXISTING_CONSUMER_FAILURE", checks, failed=True)
    for row in checks:
        if row["status"] != "PASS":
            raise D79Refusal(row.get("reason", "D79_EXISTING_CONSUMER_UNMEASURED"), row)


def _digital_audit(result):
    status = "FAIL" if result.summary.get("failed") else "PASS" if result.passed else "NOT_MEASURED"
    if status != "FAIL" and result.summary.get("timing_uncharacterised"):
        status = "NOT_MEASURED"
    return {"check": "digital_hardmacro_check", "status": status,
            "reason": "D79_DIGITAL_TIMING_NOT_MEASURED" if status == "NOT_MEASURED" else None,
            "detail": asdict(result)}


def _audits(project, endpoints):
    checks = []
    digital = [ep for ep in endpoints if ep.kind == "digital"]
    if digital:
        if set(digital_check.discover_packages(digital_check.hardmacro_dir(project))) != {ep.name for ep in digital}:
            raise D79Refusal("D79_ENDPOINT_UNBOUND", "digital package population differs from carrier")
        result = digital_check.run_audit(project)
        checks.append(_digital_audit(result))
        _require_checks(checks)
    analog = [ep for ep in endpoints if ep.kind == "analog"]
    if analog:
        names = {ep.name for ep in analog}
        result = analog_check.run_audit(project)
        checks.append({"check": "analog_hardmacro_check", "status": "PASS" if result.passed else "FAIL",
                       "detail": asdict(result)})
        _require_checks(checks)
        summary = result.summary
        if (summary.get("skipped") or summary.get("total_blocks") != len(names)
                or summary.get("stub_blocks") or summary.get("structure_only_blocks")
                or summary.get("undisclosed_blocks") or set(summary.get("design_bound_blocks", [])) != names):
            raise D79Refusal("D79_ANALOG_PACKAGE_UNMEASURED", summary)
        pins = analog_pins.run_audit(project)
        checks.append({"check": "analog_hardmacro_pinname_consistency_check",
                       "status": "PASS" if pins.passed else "FAIL", "detail": asdict(pins)})
        _require_checks(checks)
        if (pins.summary.get("skipped") or pins.summary.get("skipped_blocks")
                or pins.summary.get("total_blocks") != len(names)
                or pins.summary.get("checked") != len(names)):
            raise D79Refusal("D79_ANALOG_PIN_AUDIT_UNMEASURED", pins.summary)
        _rc, outline = analog_outline.build_report(project, None, analog_outline.DEFAULT_TOL_PCT)
        rows = outline.get("blocks", [])
        if any(row.get("status") == "FAIL" for row in rows):
            raise D79Refusal("D79_EXISTING_CONSUMER_FAILURE", outline, failed=True)
        if ({row.get("block") for row in rows} != names or len(rows) != len(names)
                or any(row.get("status") not in ("PASS", "FAIL") for row in rows)):
            raise D79Refusal("D79_ANALOG_OUTLINE_UNMEASURED", outline)
        checks.append({"check": "analog_lef_gds_outline_check",
                       "status": "FAIL" if any(r["status"] == "FAIL" for r in rows) else "PASS",
                       "detail": outline})
    return checks


def _ambient_inputs(project):
    records = []
    for root in ("input", "phase1/generated_docs"):
        records.extend(_record(project, path) for path in sorted((project / root).rglob("*"))
                       if path.is_file())
    return records


def _analog_binding(project, endpoint, runtime):
    root = project / "phase3/analog" / endpoint.name
    container = "" if runtime["container"] == "host" else runtime["container"]
    tech = analog_export.layout_tech(root)
    if pdk_identity.same_family(runtime["pdk"], tech) is not True:
        raise D79Refusal("D79_ANALOG_PDK_UNBOUND", {"selected": runtime["pdk"], "layout": tech})
    magicrc = analog_export.magicrc_for(runtime["pdk_root"], container, tech)
    if not magicrc or "/libs.tech/magic/" not in magicrc:
        raise D79Refusal("D79_ANALOG_PDK_UNBOUND", "selected Magic namespace absent")
    kit_root = Path(magicrc.split("/libs.tech/magic/", 1)[0])
    if (not kit_root.is_relative_to(Path(runtime["pdk_root"]))
            or pdk_identity.same_family(runtime["pdk"], kit_root.name) is not True):
        raise D79Refusal("D79_ANALOG_PDK_UNBOUND", {"selected": runtime["pdk"], "magicrc": magicrc})
    topology = _read(project, root / "topology.json")
    measurement, reason = analog_export.load_native_measurement(
        project, endpoint.name, root / (endpoint.name + ".gds"), topology)
    if measurement is None:
        raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", reason)
    netlist = root / (endpoint.name + ".sp")
    try:
        lines = analog_export._a7.model_binding_lines(netlist.read_text(), root, root)
        models = analog_export._bound_models(container, lines, root)
    except (OSError, ValueError) as exc:
        raise D79Refusal("D79_ANALOG_MODEL_UNBOUND", str(exc)) from exc
    if not lines:
        raise D79Refusal("D79_ANALOG_MODEL_UNBOUND", "delivered A3 model bindings absent")
    if (not models or models != measurement.get("model_bindings")
            or measurement.get("model_source") != models[0]["path"]
            or measurement.get("model_source_sha256") != models[0]["sha256"]
            or measurement.get("model_section") != models[0]["section"]
            or any(not Path(model["path"]).is_relative_to(kit_root) for model in models)):
        raise D79Refusal("D79_ANALOG_MODEL_UNBOUND", "current selected-kit model/measurement closure differs")
    return {"pdk": pdk_identity.canonical_or_normalised(runtime["pdk"]), "layout_tech": tech,
            "magicrc": magicrc, "models": models,
            "measurement": _record(project, root / "a8_measurement.json")}


def execute(project: Path, context: Mapping) -> dict:
    project = Path(project).resolve()
    report = {"schema": SCHEMA, "step_id": STEP, "context_sha256": context.get("context_sha256"),
              "component_status": "NOT_MEASURED", "reason": "D79_NOT_EXECUTED",
              "native_started": False, "native_attempts": [], "inputs": [], "outputs": [], "packages": [], "checks": [],
              "consumer_load_identity": operation_sources(), "metric_acceptance_status": "NOT_MEASURED",
              "default_row_status": "NOT_MEASURED", "completed": False,
              "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
              "delivery_accepted": False}
    try:
        checked, request = _context(project, context)
        report["inputs"] = [request] + _ambient_inputs(project)
        endpoints = _endpoints(project, checked)
        report["endpoints"] = json.loads(json.dumps([asdict(ep) for ep in endpoints]))
        for ep in endpoints:
            report["inputs"].extend(ep.inputs)
        pdk, technology = current_kit.pdk_of(project)
        report["inputs"].append(_record(project, technology))
        root = os.environ.get("VIBEIC_LIBRELANE_PDK_ROOT") or os.environ.get("PDK_ROOT")
        if not root:
            raise D79Refusal("D79_PDK_UNBOUND", "explicit PDK_ROOT or VIBEIC_LIBRELANE_PDK_ROOT required")
        container = (os.environ.get("VIBEIC_ANALOG_CONTAINER") or os.environ.get("EDA_CONTAINER")
                     or os.environ.get("VIBEIC_EDA_CONTAINER", ""))
        report["runtime"] = {"pdk": pdk, "pdk_root": root, "container": container or "host"}
        admitted = admission.require_launch_admission(project, NATIVE_STEP, {"flow109_context": checked})
        report["launch_admission"] = admitted
        for ep in endpoints:
            binding = _analog_binding(project, ep, report["runtime"]) if ep.kind == "analog" else None
            report["producer_invoked"] = True
            if ep.kind == "digital":
                rc, produced = digital_export.run(project, root, False, False,
                    container=container, pdk_name=pdk)
                producer = {"producer": "digital_hardmacro_gen.run", "rc": rc, "detail": asdict(produced)}
                attempts = produced.native_attempts
            else:
                produced = analog_export.emit_block(project, ep.name, container, root)
                rc = produced.get("rc", 1)
                producer = {"producer": "analog_a8_hardmacro_emit.emit_block", "rc": rc, "detail": produced}
                attempts = produced["native_attempts"]
            report["native_attempts"].extend(dict(attempt, endpoint=ep.name) for attempt in attempts)
            report["native_started"] = bool(report["native_attempts"])
            producer.update(context_sha256=checked["context_sha256"], name=ep.name,
                            runtime=report["runtime"])
            path = Path("reports/flow109/ip_release") / checked["context_sha256"] / (ep.name + ".producer.json")
            write_json(project / path, producer)
            package = {"name": ep.name, "kind": ep.kind, "producer_receipts": [_record(project, path)]}
            if binding is not None:
                package["pdk_binding"] = binding
            report["packages"].append(package)
            if rc != 0 or (ep.kind == "analog" and produced.get("emitted") is not True):
                code = "D79_NATIVE_TOOL_UNAVAILABLE" if rc == 2 else "D79_EXPORT_REFUSED"
                raise D79Refusal(code, producer)
            if binding is not None:
                current_binding = _analog_binding(project, ep, report["runtime"])
                if (produced.get("magicrc") != binding["magicrc"]
                        or current_binding["magicrc"] != binding["magicrc"]
                        or current_binding["models"] != binding["models"]):
                    raise D79Refusal("D79_ANALOG_PDK_UNBOUND", "export used a different selected kit")
                package["pdk_binding"] = current_binding
            package["views"] = _views(project, ep)
            structural = _structural(project, ep)
            package["checks"] = [structural]
            if structural["status"] == "FAIL":
                raise D79Refusal("D79_INTERFACE_OR_OUTLINE_MISMATCH", structural, failed=True)
            lineage, scope = _lineage(project, ep)
            package["producer_receipts"].extend(lineage)
            package["characterization_scope"] = scope
        report["checks"] = _audits(project, endpoints)
        if any(row["status"] == "FAIL" for row in report["checks"]):
            raise D79Refusal("D79_EXISTING_CONSUMER_FAILURE", report["checks"], failed=True)
        for ep, package in zip(endpoints, report["packages"]):
            kit = docs.read_kit(project, ep.name, ep.paths(project))
            audit_path = Path("reports/flow109/ip_release") / checked["context_sha256"] / (ep.name + ".audit.json")
            audit = {"name": ep.name, "kind": ep.kind, "context_sha256": checked["context_sha256"],
                     "views": package["views"],
                     "producer_receipts": package["producer_receipts"], "checks": package["checks"] + report["checks"],
                     "consumer_load_identity": operation_sources(), "verdict_tier": "PASS"}
            write_json(project / audit_path, audit)
            kit.verdict_source = str(audit_path)
            out = project / "phase3/stage4/documentation/ip" / ep.name
            written, _derived, _holes = docs.emit(project, out, kit)
            constraints = docs.constraints_for(project, kit)
            findings, detail = docs_check.check_release(project, "ip", out, ep.name,
                ip_views=ep.paths(project), expected_constraints=constraints)
            package["documentation_check"] = {"detail": detail, "findings": [asdict(f) for f in findings]}
            package["documents"] = [_record(project, path) for _name, path in written]
            package["documents"].extend((_record(project, out / docs.MANIFEST_NAME), _record(project, audit_path)))
            package["integration_constraints"] = detail["observed_constraints"]
            if not detail["pass"]:
                raise D79Refusal("D79_RELEASE_DOCUMENT_MISMATCH", detail, failed=True)
            if detail["pin_count_cross_check"] != "AGREES":
                raise D79Refusal("D79_DOCUMENT_INTERFACE_UNMEASURED", detail)
        report.update(component_status="PASS", reason="D79_EXISTING_COMPONENT_CHECKS_PASS")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        report.update(component_status="FAIL" if getattr(exc, "failed", False) else "NOT_MEASURED",
                      reason=getattr(exc, "code", "D79_REQUIRED_INPUT_ABSENT"), detail=str(exc))
    for package in report["packages"]:
        report["outputs"].extend(package.get("views", {}).values())
        report["outputs"].extend(package.get("producer_receipts", []))
        report["outputs"].extend(package.get("documents", []))
    return json.loads(json.dumps(report))


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def validate(project: Path, receipt: Mapping) -> None:
    project = Path(project).resolve()
    if (receipt.get("schema") != SCHEMA or receipt.get("step_id") != STEP
            or receipt.get("consumer_load_identity") != operation_sources()):
        raise D79Refusal("D79_RECEIPT_IDENTITY_MISMATCH", "schema/step/loaded sources")
    for record in receipt.get("inputs", []) + receipt.get("outputs", []):
        if not isinstance(record, Mapping) or _record(project, record["path"]) != record:
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", "receipt input/output drift")


def _observation(project, context, component):
    checked, request = _context(project, context)
    validate(project, component)
    if component.get("context_sha256") != checked["context_sha256"] or request not in component["inputs"]:
        raise D79Refusal("D79_CONTEXT_MISMATCH", "component and saved request differ")
    endpoints = _endpoints(project, checked)
    if json.loads(json.dumps([asdict(ep) for ep in endpoints])) != component.get("endpoints"):
        raise D79Refusal("D79_ENDPOINT_UNBOUND", "selected endpoints changed")
    if component.get("component_status") != "PASS":
        raise D79Refusal(component.get("reason", "D79_COMPONENT_UNMEASURED"), "component not PASS",
                         failed=component.get("component_status") == "FAIL")
    if len(component["packages"]) != len(endpoints):
        raise D79Refusal("D79_ENDPOINT_UNBOUND", "package population changed")
    actual = {name: [] for name in METRIC_FIELDS}
    checks = _audits(project, endpoints)
    _require_checks(checks)
    if not _same(checks, component.get("checks")):
        raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", "audits changed",
                         failed=any(row["status"] == "FAIL" for row in checks))
    for ep, package in zip(endpoints, component["packages"]):
        structural = _structural(project, ep)
        _require_checks([structural])
        if (package.get("name") != ep.name or package.get("kind") != ep.kind
                or package.get("views") != _views(project, ep)
                or not _same(package.get("checks"), [structural])):
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", ep.name)
        lineage, scope = _lineage(project, ep)
        if ep.kind == "analog":
            runtime_pdk, _ = current_kit.pdk_of(project)
            if runtime_pdk != component["runtime"]["pdk"]:
                raise D79Refusal("D79_ANALOG_PDK_UNBOUND", "current selected PDK changed")
            if package.get("pdk_binding") != _analog_binding(project, ep, component["runtime"]):
                raise D79Refusal("D79_ANALOG_PDK_UNBOUND", "current layout/selected-kit model binding changed")
        if package.get("producer_receipts", [])[1:] != lineage or not _same(package.get("characterization_scope"), scope):
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", "native lineage/scope changed")
        producer = _read(project, package["producer_receipts"][0]["path"])
        expected = ("digital_hardmacro_gen.run" if ep.kind == "digital" else "analog_a8_hardmacro_emit.emit_block")
        expected_path = (Path("reports/flow109/ip_release") / checked["context_sha256"]
                         / (ep.name + ".producer.json"))
        if (producer.get("producer") != expected or producer.get("rc") != 0
                or producer.get("context_sha256") != checked["context_sha256"]
                or producer.get("name") != ep.name or producer.get("runtime") != component.get("runtime")
                or package["producer_receipts"][0]["path"] != str(expected_path)):
            raise D79Refusal("D79_EXPORT_REFUSED", "producer invocation receipt required")
        if ep.kind == "analog" and producer["detail"].get("magicrc") != package["pdk_binding"]["magicrc"]:
            raise D79Refusal("D79_ANALOG_PDK_UNBOUND", "export Magic namespace differs")
        audit_path = expected_path.with_name(ep.name + ".audit.json")
        expected_audit = {"name": ep.name, "kind": ep.kind, "context_sha256": checked["context_sha256"],
            "views": package["views"], "producer_receipts": package["producer_receipts"],
            "checks": package["checks"] + checks, "consumer_load_identity": operation_sources(),
            "verdict_tier": "PASS"}
        if not _same(_read(project, audit_path), expected_audit):
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", "per-package audit differs")
        out = project / "phase3/stage4/documentation/ip" / ep.name
        constraints = docs.constraints_for(project, docs.read_kit(project, ep.name, ep.paths(project)))
        findings, detail = docs_check.check_release(project, "ip", out, ep.name,
            ip_views=ep.paths(project), expected_constraints=constraints)
        if (not detail["pass"] or detail["pin_count_cross_check"] != "AGREES"
                or package["documentation_check"] != {"detail": detail, "findings": [asdict(f) for f in findings]}):
            raise D79Refusal("D79_RELEASE_DOCUMENT_MISMATCH", detail, failed=not detail["pass"])
        constraints = detail["observed_constraints"]
        if package.get("integration_constraints") != constraints or not constraints:
            raise D79Refusal("D79_REQUIREMENTS_UNBOUND", "current integration constraints absent/changed")
        actual["ip_endpoint_views"].extend({"name": ep.name, "view": suffix} for suffix in package["views"])
        actual["ip_integration_limits_documented"].extend({"name": ep.name, "constraint": row["cid"]}
                                                       for row in constraints)
    return actual


def _authority(project, name, actual):
    relative = f"requirements/base_49/{name}.json"
    _read(project, relative)
    authority, body = metrics._approved_authority(project,
        relative + "#/required_items", METRIC_FIELDS[name])
    source = authority["source"]
    if (not source["path"].startswith("input/") or not (project / source["path"]).resolve().is_relative_to(
            (project / "input").resolve())):
        raise D79Refusal("D79_REQUIREMENTS_UNBOUND", "independent normal input required")
    payload = {key: value for key, value in body.items() if key not in ("schema", "approval")}
    if _read(project, source["path"]).get(name) != payload or not authority["required_items"]:
        raise D79Refusal("D79_REQUIREMENTS_UNBOUND", "empty or independently unbound required set")
    if any(row not in actual for row in authority["required_items"]):
        raise D79Refusal("D79_REQUIREMENTS_UNRECOGNIZED", "requested view/constraint is not a validated package fact")
    return authority


def consume_default_row_completion(project, context, component):
    project = Path(project).resolve()
    prior = component.get("metric_acceptance") or {}
    failed = (component.get("component_status") == "FAIL" or component.get("default_row_status") == "FAIL"
              or component.get("metric_acceptance_status") == "FAIL"
              or prior.get("status") == "FAIL"
              or any(row.get("status") == "FAIL" for row in prior.get("obligations", [])))
    result = {"row_id": STEP, "status": "FAIL" if failed else "NOT_MEASURED",
              "metric_status": "FAIL" if failed else "NOT_MEASURED", "obligations": [],
              "qualification": "NOT_CLAIMED"}
    try:
        actual = _observation(project, context, component)
        for name in METRIC_FIELDS:
            item = {"id": "base_49." + name, "status": "NOT_MEASURED"}
            result["obligations"].append(item)
            try:
                authority = _authority(project, name, actual[name])
                identity = {"producer": component["consumer_load_identity"],
                    "checker": operation_sources(), "tool_execution": component["runtime"],
                    "consumed_inputs": {r["path"]: r["sha256"] for r in component["inputs"] + component["outputs"]},
                    "requirements": authority, "configuration": {"context_sha256": context["context_sha256"]}}
                measured = {"status": "MEASURED", "identity": identity, "value": actual[name]}
                status, reason = metrics.evaluate_operator("covers_all", measured, authority)
                item.update(status=status, reason=reason, measurement=measured, authority=authority)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                code = getattr(exc, "code", "D79_REQUIREMENTS_UNBOUND")
                item.update(reason=code if code.startswith("D79_") else "D79_REQUIREMENTS_UNBOUND", detail=str(exc))
        if any(row["status"] == "FAIL" for row in result["obligations"]):
            failed = True
            result.update(status="FAIL", metric_status="FAIL")
        if not failed and all(row["status"] == "PASS" for row in result["obligations"]):
            receipt = admission.require_launch_admission(project, NATIVE_STEP, {"flow109_context": context})
            if (receipt.get("admitted") is True and receipt.get("reason") == "SOURCE_OWNED_EXISTING_NATIVE_COMPONENT"
                    and receipt.get("context_sha256") == context["context_sha256"]
                    and receipt.get("native_step_id") == NATIVE_STEP
                    and receipt.get("acceptance_scope") == "existing_native_component_only"):
                result.update(status="PASS", metric_status="PASS", qualification_receipt=receipt)
            else:
                raise D79Refusal("D79_ADMISSION_SCOPE_MISMATCH", receipt)
        validate(project, component)
        for item in result["obligations"]:
            if "authority" in item:
                name = item["id"].split(".")[-1]
                if _authority(project, name, actual[name]) != item["authority"]:
                    raise D79Refusal("D79_REQUIREMENTS_UNBOUND", "authority changed during read")
        if _observation(project, context, component) != actual:
            raise D79Refusal("D79_CURRENT_PROVENANCE_UNBOUND", "observation changed during read")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(status="FAIL" if failed or getattr(exc, "failed", False) else "NOT_MEASURED",
                      metric_status="FAIL" if failed or getattr(exc, "failed", False) else "NOT_MEASURED",
                      reason=getattr(exc, "code", "D79_CURRENT_PROVENANCE_UNBOUND"), detail=str(exc))
    return {**component, "metric_acceptance": result, "metric_acceptance_status": result["status"],
            "default_row_status": result["status"], "flow109_acceptance": result["status"],
            "completed": result["status"] == "PASS", "whole_flow_acceptance": "NOT_MEASURED",
            "delivery_accepted": False}
