"""Export native hardmacro views and check their physical and document substance."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Mapping
import uuid

from _atomic_artefact import write_json
import _physical_current as current_kit
import analog_a8_hardmacro_emit as analog_export
import analog_hardmacro_check as analog_check
import analog_hardmacro_pinname_consistency_check as analog_pins
import analog_lef_gds_outline_check as analog_outline
import digital_hardmacro_check as digital_check
import digital_hardmacro_gen as digital_export
import ip_release_docs_gen as docs
import release_docs_check as docs_check

VIEW_ROLES = {".lef": "lef", ".lib": "liberty", ".gds": "gds", ".v": "verilog"}
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


def _record(project, raw, code="D79_REQUIRED_INPUT_ABSENT"):
    raw = Path(raw)
    raw = raw if raw.is_absolute() else project / raw
    path = raw.resolve()
    if (raw.is_symlink() or not path.is_relative_to(project)
            or not path.is_file() or path.stat().st_size == 0
            or any(p.is_symlink() for p in raw.parents if p != project.parent)):
        raise D79Refusal(code, str(raw))
    return {"path": str(path.relative_to(project)), "bytes": path.stat().st_size}


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


def _endpoints(project, context):
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
            for path in (routed, gds[0]))))
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
                for path in (manifest, root / "spec.json", root / "topology.json",
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
                or summary.get("undisclosed_blocks")):
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


def execute(project: Path, context: Mapping) -> dict:
    project = Path(project).resolve()
    report = {"component_status": "NOT_MEASURED", "native_started": False,
              "native_attempts": [], "packages": [], "checks": []}
    output = project / 'reports/native_tools/ip_release' / uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=True)
    try:
        features = context.get('features') or {
            'has_digital': any((project / path).is_file() for path in digital_export._DEF_CANDIDATES),
            'has_analog': bool(analog_export.declared_blocks(project))}
        endpoints = _endpoints(project, {'features': features})
        config = context.get('config') or {}
        if config.get('PDK'):
            pdk = config['PDK']
        else:
            pdk, _ = current_kit.pdk_of(project)
        root = config.get('PDK_ROOT') or context.get('pdk_root') or os.environ.get('VIBEIC_LIBRELANE_PDK_ROOT') or os.environ.get('PDK_ROOT')
        if not root:
            raise D79Refusal('D79_PDK_UNAVAILABLE', 'native PDK root is required')
        container = context.get('container', 'host')
        for ep in endpoints:
            attempts = []
            try:
                if ep.kind == 'digital':
                    rc, produced = digital_export.run(project, root, False, False,
                        container=container, pdk_name=pdk, native_attempts=attempts)
                    producer = {'producer': 'digital_hardmacro_gen.run', 'rc': rc, 'detail': asdict(produced)}
                else:
                    produced = analog_export.emit_block(project, ep.name, container, root,
                                                        native_attempts=attempts)
                    rc = produced.get('rc', 1)
                    producer = {'producer': 'analog_a8_hardmacro_emit.emit_block', 'rc': rc, 'detail': produced}
            finally:
                report['native_attempts'].extend(dict(attempt, endpoint=ep.name) for attempt in attempts)
                report['native_started'] = bool(report['native_attempts'])
            write_json(output / (ep.name + '.producer.json'), producer)
            if rc != 0 or (ep.kind == 'analog' and produced.get('emitted') is not True):
                raise D79Refusal('D79_EXPORT_INCOMPLETE', producer)
            structural = _structural(project, ep)
            _require_checks([structural])
            package = {'name': ep.name, 'kind': ep.kind, 'views': _views(project, ep),
                       'checks': [structural], 'producer': producer}
            report['packages'].append(package)
        report['checks'] = _audits(project, endpoints)
        _require_checks(report['checks'])
        for ep, package in zip(endpoints, report['packages']):
            kit = docs.read_kit(project, ep.name, ep.paths(project))
            audit_path = output / (ep.name + '.audit.json')
            write_json(audit_path, {'name': ep.name, 'kind': ep.kind,
                'checks': package['checks'] + report['checks'], 'verdict_tier': 'PASS'})
            kit.verdict_source = str(audit_path.relative_to(project))
            out = project / 'phase3/stage4/documentation/ip' / ep.name
            written, _derived, _holes = docs.emit(project, out, kit)
            findings, detail = docs_check.check_release(project, 'ip', out, ep.name,
                ip_views=ep.paths(project), expected_constraints=docs.constraints_for(project, kit))
            package['documentation_check'] = {'detail': detail, 'findings': [asdict(f) for f in findings]}
            package['documents'] = [_record(project, path) for _name, path in written]
            if not detail['pass']:
                raise D79Refusal('D79_RELEASE_DOCUMENT_MISMATCH', detail, failed=True)
            if detail['pin_count_cross_check'] != 'AGREES':
                raise D79Refusal('D79_DOCUMENT_INTERFACE_UNMEASURED', detail)
        report.update(component_status='PASS')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        report.update(component_status='FAIL' if getattr(exc, 'failed', False) else 'NOT_MEASURED',
                      reason=getattr(exc, 'code', 'D79_REQUIRED_INPUT_ABSENT'), detail=str(exc))
    write_json(output / 'result.json', report)
    return report
