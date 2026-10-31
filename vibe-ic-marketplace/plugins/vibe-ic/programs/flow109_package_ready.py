#!/usr/bin/env python3
"""Flow109 D75 Default package/test interface component.

This is a BLOCKING component check for the inputs it actually consumes.  It
does not approve a package or a tapeout: packaged SI/PI/thermal co-design and
all Flow109 metric acceptance remain NOT_MEASURED.  The supported path reuses
the existing declaration, pad-side, pad/BTerm, bond-opening, PERC and DFT
consumers.  Missing geometry or authority is named, never read as PASS.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _pad_ring
import _submission_template as submission
import _tapeout_declaration as declaration
import dft_atpg_coverage_check
import flow109_package_electrical
import pad_bterm_coincidence_check
import pad_side_constraint_check
import perc_signoff_check
import provider_bond_pad_edge
import submission_template_check
import tapeout_declaration_check
import tapeout_readiness_check
from _staged_pdk_tech_lef import (TechLefResolutionError,
                                  discover_staged_tech_lefs,
                                  select_staged_tech_lef)

SCHEMA = "vibeic.flow109.package-ready.v1"
STEP = "D75"
NATIVE_STEP = "flow109.D75"
DECLARATION = Path(declaration.DECLARATION_REL)
OPERATOR_ANSWERS = Path("input/submission_template/operator_answers.json")
DESIGN_ANSWERS = Path(submission.DESIGN_ANSWERS_REL)
CATALOGUE_REPORT = Path(submission.REPORT_REL)
CATALOGUE_SOURCE = Path(submission.STAGED_TEMPLATE_REL)
IO_REPORT = Path("reports/phase3/io_pad_chip_top.json")
PAD_DEF = Path(_pad_ring.PADRING_DEF_REL)
PDK_DIR = Path("input/pdk")
CONTEXT_REQUESTS = Path("reports/flow109/requests")
PROVIDER_TARGET = Path("input/submission_template/provider_target.json")
D67_REPORT = Path("reports/flow109/components/D67.json")


class D75Refusal(ValueError):
    def __init__(self, code: str, detail: str, *, failed: bool = False):
        self.code, self.detail, self.failed = code, detail, failed
        super().__init__(f"{code}: {detail}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operation_sources() -> dict[str, str]:
    """Bind the exact adapter and existing consumers loaded for D75."""
    names = (
        "flow109_package_ready.py",
        "flow109_package_electrical.py",
        "submission_template_check.py",
        "tapeout_declaration_check.py",
        "pad_side_constraint_check.py",
        "pad_bterm_coincidence_check.py",
        "provider_bond_pad_edge.py",
        "perc_signoff_check.py",
        "dft_atpg_coverage_check.py",
        "execution_adapters_backend.py",
        "_opensta_current.py",
        "librelane_postroute.py",
        "librelane_contract.py",
        "librelane_signoff_evidence.py",
    )
    return {"programs/" + name: _sha(HERE / name) for name in names}


def _d67_record(project: Path, value: object, label: str) -> dict:
    """Rebind one path/hash identity published by the D67 producer."""
    if (not isinstance(value, Mapping)
            or not isinstance(value.get("path"), str)
            or not isinstance(value.get("sha256"), str)):
        raise D75Refusal("D75_D67_RECEIPT_INVALID", label)
    record = _record(project, Path(value["path"]))
    if record["sha256"] != value["sha256"]:
        raise D75Refusal("D75_D67_INPUT_STALE", str(value["path"]))
    return record


def _consume_d67(project: Path) -> tuple[dict, list[dict]]:
    """Consume the current D67 receipt through D67's declared consumer.

    D75 does not interpret package models, reconstruct a D67 context, or infer
    missing package facts.  It reopens the producer's saved canonical context
    and lets D67 recheck its current source/model/bounds/tool/native evidence.
    """
    report_path = project / D67_REPORT
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise D75Refusal(
            "D75_D67_REPORT_ABSENT_OR_INVALID", str(D67_REPORT)) from exc
    if not isinstance(report, dict):
        raise D75Refusal("D75_D67_REPORT_ABSENT_OR_INVALID", str(D67_REPORT))
    identity = report.get("context_sha256")
    if not isinstance(identity, str) or len(identity) != 64:
        raise D75Refusal("D75_D67_CONTEXT_UNBOUND", repr(identity))
    context_path = project / CONTEXT_REQUESTS / f"{identity}.json"
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise D75Refusal(
            "D75_D67_CONTEXT_ABSENT_OR_INVALID",
            str(context_path.relative_to(project))) from exc
    if not isinstance(context, dict):
        raise D75Refusal("D75_D67_CONTEXT_ABSENT_OR_INVALID",
                         str(context_path.relative_to(project)))
    try:
        consumed = flow109_package_electrical.consume(project, context, report)
    except (flow109_package_electrical.AdmissionRefusal,
            flow109_package_electrical.MetricRefusal) as exc:
        raise D75Refusal(
            "D75_D67_CONSUMER_REFUSED", f"{exc.code}: {exc}",
            failed=getattr(exc, "status", "NOT_MEASURED") == "FAIL") from exc
    if consumed.get("status") not in ("PASS", "FAIL"):
        raise D75Refusal("D75_D67_STATUS_UNSUPPORTED",
                         str(consumed.get("status")))
    if (report.get("component_status") != consumed["status"]
            or report.get("metrics") != consumed):
        raise D75Refusal("D75_D67_RECEIPT_STATUS_MISMATCH",
                         "producer status/metrics differ from current consumer",
                         failed=consumed["status"] == "FAIL")
    records = [_record(project, report_path), _record(project, context_path)]
    published_inputs = report.get("inputs")
    if not isinstance(published_inputs, Mapping) or not published_inputs:
        raise D75Refusal("D75_D67_RECEIPT_INVALID", "inputs")
    for path, digest in sorted(published_inputs.items()):
        records.append(_d67_record(project, {"path": path, "sha256": digest},
                                   "inputs"))
    native = report.get("native")
    if not isinstance(native, list) or not native:
        raise D75Refusal("D75_D67_NATIVE_RECEIPT_INVALID", "native")
    for row in native:
        if not isinstance(row, Mapping):
            raise D75Refusal("D75_D67_NATIVE_RECEIPT_INVALID", "native row")
        for field in ("model", "deck", "log"):
            records.append(_d67_record(project, row.get(field), field))
    detail = {
        "status": consumed["status"],
        "d67_context_sha256": identity,
        "d67_report": _record(project, report_path),
        "d67_context": _record(project, context_path),
        "package_model_ports_identity": consumed.get(
            "package_model_ports_identity"),
        "metrics": consumed,
    }
    return detail, records


def _join_d67_subject(project: Path, detail: Mapping, io: Mapping,
                      current_geometry: Mapping | None) -> dict:
    """Prove the accepted D67 result applies to D75's selected subject."""
    port_identity = detail.get("package_model_ports_identity")
    identity = (port_identity.get("value")
                if isinstance(port_identity, Mapping) else None)
    if (not isinstance(port_identity, Mapping)
            or port_identity.get("status") != "PASS"
            or not isinstance(identity, Mapping)):
        raise D75Refusal("D75_D67_SUBJECT_UNBOUND",
                         "D67 package_model_ports_identity is not measured PASS")
    d67_top = identity.get("top")
    io_top = io.get("chip_top_module")
    if not isinstance(d67_top, str) or not d67_top:
        raise D75Refusal("D75_D67_SUBJECT_UNBOUND", "D67 top")
    if not isinstance(io_top, str) or not io_top:
        raise D75Refusal("D75_D67_SUBJECT_UNBOUND", "D75 IO top")
    d67_netlist_identity = identity.get("netlist")
    d67_netlist = _d67_record(project, d67_netlist_identity, "netlist")
    models = identity.get("models")
    if not isinstance(models, list) or not models:
        raise D75Refusal("D75_D67_SUBJECT_UNBOUND", "D67 model port maps")
    port_maps = []
    for model in models:
        mapping = model.get("port_map") if isinstance(model, Mapping) else None
        if not isinstance(mapping, Mapping) or not mapping:
            raise D75Refusal("D75_D67_SUBJECT_UNBOUND", "D67 model port map")
        design_ports = sorted({row["design_port"] for row in mapping.values()
                               if isinstance(row, Mapping)
                               and isinstance(row.get("design_port"), str)
                               and row["design_port"]})
        if not design_ports:
            raise D75Refusal("D75_D67_SUBJECT_UNBOUND",
                             "D67 model has no bound design port")
        port_maps.append({"id": model.get("id"), "design_ports": design_ports})

    native_top = native_netlist = None
    mismatches = []
    if d67_top != io_top:
        mismatches.append("D67 top differs from D75 IO top")
    if current_geometry is not None:
        native = current_geometry.get("detail")
        if not isinstance(native, Mapping):
            raise D75Refusal("D75_D67_SUBJECT_UNBOUND",
                             "current native subject detail")
        native_top = native.get("top")
        native_netlist = native.get("netlist")
        if native_top != io_top:
            mismatches.append("current native top differs from D75 IO top")
        if (not isinstance(native_netlist, Mapping)
                or d67_netlist.get("path") != native_netlist.get("path")
                or d67_netlist.get("sha256") != native_netlist.get("sha256")):
            mismatches.append("D67 netlist differs from current native netlist")
    return {
        "status": "FAIL" if mismatches else "PASS",
        "basis": ("IO top plus exact current-native netlist"
                  if current_geometry is not None else
                  "existing legacy applicability: IO top"),
        "d67_top": d67_top,
        "d75_io_top": io_top,
        "d75_native_top": native_top,
        "netlist": dict(d67_netlist_identity),
        "current_native_netlist": native_netlist,
        "model_design_ports": port_maps,
        "mismatches": mismatches,
    }


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path))
    return value


def _record(project: Path, path: Path) -> dict:
    resolved = path if path.is_absolute() else project / path
    if not resolved.is_file():
        raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path))
    try:
        rel = str(resolved.resolve().relative_to(project.resolve()))
    except ValueError:
        rel = str(resolved.resolve())
    return {"path": rel, "sha256": _sha(resolved), "bytes": resolved.stat().st_size}


def _tree_records(project: Path, relative: Path) -> list[dict]:
    root = project / relative
    return [_record(project, path) for path in sorted(root.rglob("*"))
            if path.is_file()]


def _release_records(project: Path, value) -> list[dict]:
    """Turn existing provider `_release_file` identities back into inputs."""
    records = []
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            rec = _record(project, Path(item["path"]))
            if rec["sha256"] != item.get("sha256"):
                raise D75Refusal("D75_PROVIDER_SOURCE_STALE", item["path"])
            records.append(rec)
    return records


def _provider_identity(project: Path, edge: Mapping) -> dict:
    """Bind the provider consumed by the bond-edge checker to its source."""
    target_path = project / PROVIDER_TARGET
    target = _read(target_path)
    provider = target.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise D75Refusal("D75_PROVIDER_IDENTITY_UNBOUND", str(PROVIDER_TARGET))
    source = _record(project, target_path)
    release = edge.get("profile") if isinstance(edge, Mapping) else None
    if (not isinstance(release, Mapping)
            or release.get("sha256") != source["sha256"]
            or Path(str(release.get("path", ""))).resolve() != target_path.resolve()):
        raise D75Refusal("D75_PROVIDER_IDENTITY_MISMATCH", str(PROVIDER_TARGET))
    return {"provider": provider, "source": source}


def _provider_scope(project: Path, doc: Mapping,
                    slots: list[Path]) -> tuple[bool, dict]:
    """Whether an operator/provider bond-edge rule is owed by this route.

    Absence of ``provider_target.json`` never decides this.  Only the existing
    owner-attested SELF_TAPEOUT contract can make a provider-specific rule not
    applicable, and a retained catalogue must first pass its existing source
    and hash validation.  Any missing, stale, selected, or contradictory fact
    degrades toward requiring provider authority.
    """
    route, route_error = declaration.declared_route_on_disk(
        project, bool(slots))
    owner_self = declaration.owner_self_tapeout(project, dict(doc))
    catalogue_ok, catalogue_reason = (True, "no retained operator catalogue")
    if slots:
        catalogue_ok, catalogue_reason = \
            submission_template_check.catalogue_selects_self_tapeout(project)
    marker = project / declaration.SELF_TAPEOUT_REL
    try:
        marker_valid = (marker.read_text(errors="replace").splitlines()[0].strip()
                        == declaration.SELF_TAPEOUT_MARKER)
    except (OSError, IndexError):
        marker_valid = False
    provider_declared = (project / PROVIDER_TARGET).is_file()
    not_owed = (route_error is None
                and route == declaration.ROUTE_SELF_TAPEOUT
                and owner_self and catalogue_ok and marker_valid
                and not provider_declared)
    return not not_owed, {
        "route": route,
        "route_error": route_error,
        "owner_self_tapeout": owner_self,
        "self_tapeout_marker_valid": marker_valid,
        "catalogue_validated": catalogue_ok,
        "catalogue_reason": catalogue_reason,
        "provider_target_declared": provider_declared,
        "declaration": str(DECLARATION),
        "owner_answers": str(DESIGN_ANSWERS),
    }


def _context(context: Mapping) -> None:
    row = context.get("resolved_row") if isinstance(context, Mapping) else None
    dispatch = (row.get("profile", {}).get("dispatch", {})
                if isinstance(row, Mapping) else {})
    if (context.get("requested_step") != STEP
            or context.get("native_step_id") != NATIVE_STEP
            or dispatch.get("adapter") != "flow109_package_ready"):
        raise D75Refusal("D75_CONTEXT_MISMATCH", "D75 adapter context required")


def _context_input(project: Path, context: Mapping) -> dict:
    """Bind the exact canonical request whose feature choices D75 consumes."""
    try:
        import flow109
        current = flow109.validate_execution_context(context)
    except (KeyError, TypeError, ValueError) as exc:
        raise D75Refusal("D75_CONTEXT_INVALID", str(exc)) from exc
    identity = current.get("context_sha256")
    if not isinstance(identity, str) or len(identity) != 64:
        raise D75Refusal("D75_CONTEXT_INVALID", "context_sha256")
    path = project / CONTEXT_REQUESTS / f"{identity}.json"
    if not path.is_file():
        raise D75Refusal("D75_CONTEXT_SOURCE_UNBOUND", str(path.relative_to(project)))
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise D75Refusal("D75_CONTEXT_SOURCE_INVALID", str(path.relative_to(project))) from exc
    if recorded != current:
        raise D75Refusal("D75_CONTEXT_SOURCE_STALE", str(path.relative_to(project)))
    return _record(project, path)


def _io_lefs(project: Path, report: dict) -> list[Path]:
    values = report.get("io_library_lefs")
    if not isinstance(values, list) or not values:
        raise D75Refusal("D75_IO_LIBRARY_UNBOUND", str(IO_REPORT))
    paths = []
    for raw in values:
        if not isinstance(raw, str) or not raw.strip():
            raise D75Refusal("D75_IO_LIBRARY_UNBOUND", repr(raw))
        path = Path(raw)
        if not path.is_absolute():
            path = project / path
            try:
                path.resolve().relative_to(project.resolve())
            except ValueError as exc:
                raise D75Refusal("D75_INPUT_ESCAPES_PROJECT", raw) from exc
        if not path.is_file():
            raise D75Refusal("D75_IO_LIBRARY_UNBOUND", raw)
        paths.append(path)
    return paths


def _tech_lef(project: Path) -> Path:
    candidates = discover_staged_tech_lefs(project / PDK_DIR)
    try:
        selected = select_staged_tech_lef(project / PDK_DIR, candidates)
    except TechLefResolutionError as exc:
        raise D75Refusal("D75_TECH_LEF_UNBOUND", str(exc)) from exc
    if selected is None:
        raise D75Refusal("D75_TECH_LEF_UNBOUND", str(PDK_DIR))
    return selected.path


def _current_native_geometry(project: Path, io_lefs: list[Path]) -> dict | None:
    """Bind D75 geometry to the already-adopted native STA checkpoint."""
    import fnmatch
    import execution_adapters_backend as backend
    import librelane_contract as contract
    import librelane_ir_antenna as ir
    import librelane_postroute as postroute

    if not (project / ir.CURRENT_STA_RECORD).is_file():
        return None
    try:
        selected = backend._default_step24_current_subject(
            project, execution_mode="default")
        if selected is None:
            raise ValueError("current-owner record did not select a native subject")
        folder, state = postroute.stapostpnr_state(project)
        receipt = contract.validate_step_receipt(folder, "OpenROAD.STAPostPNR")
        config_path = folder / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        fingerprint = receipt["input"]["config_files"]
        state_fingerprint = receipt["input"]["state_files"]
        if not isinstance(fingerprint, Mapping) or not isinstance(state_fingerprint, Mapping):
            raise ValueError("native config/state fingerprints are malformed")
        views = selected.get("views")
        if not isinstance(views, Mapping):
            raise ValueError("current native selector returned no views")

        def selected_view(name: str, state_name: str) -> Path:
            path = Path(views.get(name) or "").resolve(strict=True)
            raw = Path(state.get(state_name) or "")
            state_path = (raw if raw.is_absolute() else project / raw).resolve(strict=True)
            recorded = (state_fingerprint.get(str(raw))
                        or state_fingerprint.get(str(project / raw))
                        or state_fingerprint.get(str(state_path)))
            if path != state_path or not path.is_file() or recorded != _sha(path):
                raise ValueError(f"selected {name} is not the executed current view")
            return path

        current_def = selected_view("def", "def")
        current_odb = selected_view("odb", "odb")
        current_netlist = selected_view("netlist", "nl")
        root_record = json.loads((folder / "pdk_root.json").read_text(encoding="utf-8"))
        mounts = (root_record.get("requested_mounts")
                  if root_record.get("execution_route") == "LOCAL"
                  else root_record.get("mounts_under_it"))
        if not isinstance(mounts, list) or not mounts:
            raise ValueError("native PDK mount authority is absent")

        def host_path(raw: str) -> Path:
            named = Path(raw)
            matches = []
            for row in mounts:
                if not isinstance(row, list) or len(row) != 2:
                    raise ValueError("native PDK mount authority is malformed")
                host, guest = Path(row[0]), Path(row[1])
                if named == guest or named.is_relative_to(guest):
                    matches.append(host / named.relative_to(guest))
            if matches and len({path.resolve() for path in matches}) != 1:
                raise ValueError(f"ambiguous native path mapping: {raw}")
            path = matches[0] if matches else (named if named.is_absolute()
                                                else project / named)
            return path.resolve(strict=True)

        def bound_config_file(raw: str, kind: str) -> tuple[Path, dict]:
            if not isinstance(raw, str) or not raw:
                raise ValueError(f"empty {kind} path")
            path = host_path(raw)
            recorded = fingerprint.get(raw) or fingerprint.get(str(path))
            if not path.is_file() or recorded != _sha(path):
                raise ValueError(f"{kind} is absent, changed, or not config-bound: {raw}")
            return path, _record(project, path)

        tech_lefs = config.get("TECH_LEFS")
        corner = config.get("DEFAULT_CORNER")
        if (not isinstance(tech_lefs, Mapping) or not tech_lefs
                or not isinstance(corner, str) or not corner):
            raise ValueError("current TECH_LEFS/default corner is undeclared")
        matches = [pattern for pattern in tech_lefs
                   if isinstance(pattern, str) and fnmatch.fnmatch(corner, pattern)]
        if len(matches) != 1:
            raise ValueError(
                f"current TECH_LEF selection is ambiguous for {corner!r}: {matches}")
        tech_records, tech_paths = {}, {}
        for pattern, raw in tech_lefs.items():
            path, record = bound_config_file(raw, f"TECH_LEFS[{pattern!r}]")
            tech_paths[pattern], tech_records[pattern] = path, record
        tech = tech_paths[matches[0]]
        text = tech.read_text(encoding="utf-8", errors="strict")
        units = re.findall(r"(?is)\bDATABASE\s+MICRONS\s+(\d+)\s*;", text)
        routing_layers = re.findall(
            r"(?is)\bLAYER\s+(\S+)\s+(?:(?!\bEND\s+\1\b).)*?\bTYPE\s+ROUTING\s*;",
            text)
        if len(units) != 1 or int(units[0]) <= 0 or not routing_layers:
            raise ValueError("selected current TECH_LEF has no unique units/routing semantics")

        pad_config = config.get("PAD_LEFS")
        if not isinstance(pad_config, list) or not pad_config:
            raise ValueError("current PAD_LEFS are undeclared")
        configured_pad_paths = {
            bound_config_file(raw, "PAD_LEFS")[0]: raw for raw in pad_config}
        for path in io_lefs:
            if path.resolve() not in configured_pad_paths:
                raise ValueError(f"IO LEF is not selected by current PAD_LEFS: {path}")
            bound_config_file(configured_pad_paths[path.resolve()], "PAD_LEFS")

        inputs = [_record(project, current_def), _record(project, current_odb),
                  _record(project, current_netlist),
                  _record(project, config_path), _record(project, folder / "state_out.json"),
                  _record(project, folder / "vibeic_receipt.json"),
                  _record(project, folder / "pdk_root.json"),
                  _record(project, project / ir.CURRENT_STA_RECORD)]
        provenance = project / "phase3/librelane_pdk_root.provenance.json"
        if provenance.is_file():
            inputs.append(_record(project, provenance))
        inputs.extend(tech_records.values())
        for rel in selected.get("inputs") or ():
            record = _record(project, Path(rel))
            if record not in inputs:
                inputs.append(record)
        return {
            "def": current_def, "odb": current_odb,
            "netlist": current_netlist, "tech": tech,
            "inputs": inputs,
            "detail": {
                "source": "current validated OpenROAD.STAPostPNR state",
                "top": selected.get("top"),
                "def": _record(project, current_def),
                "odb": _record(project, current_odb),
                "netlist": _record(project, current_netlist),
                "config": _record(project, config_path),
                "receipt": _record(project, folder / "vibeic_receipt.json"),
                "pdk_root": _record(project, folder / "pdk_root.json"),
                "tool_image": receipt["input"].get("image"),
                "default_corner": corner,
                "selected_tech_pattern": matches[0],
                "selected_tech_lef": tech_records[matches[0]],
                "tech_lefs": tech_records,
                "database_microns": int(units[0]),
                "routing_layers": sorted(set(routing_layers)),
            },
        }
    except (OSError, UnicodeError, ValueError, KeyError, TypeError,
            contract.Refusal) as exc:
        raise D75Refusal("D75_CURRENT_NATIVE_GEOMETRY_UNBOUND", str(exc)) from exc


def _check(name: str, status: str, detail: object, **extra) -> dict:
    return {"check": name, "status": status, "detail": detail, **extra}


def _aggregate(checks: list[dict]) -> str:
    if any(item["status"] == "FAIL" for item in checks):
        return "FAIL"
    if any(item["status"] == "NOT_MEASURED" for item in checks):
        return "NOT_MEASURED"
    return "PASS"


def validate(project: Path, receipt: Mapping) -> None:
    """Rebind every recorded source; a copied/stale D75 PASS is unusable."""
    if receipt.get("schema") != SCHEMA or receipt.get("step_id") != STEP:
        raise D75Refusal("D75_RECEIPT_INVALID", "schema/step")
    context_sha256 = receipt.get("context_sha256")
    expected_context = str(CONTEXT_REQUESTS / f"{context_sha256}.json")
    context_refusals = {
        "D75_CONTEXT_INVALID", "D75_CONTEXT_SOURCE_UNBOUND",
        "D75_CONTEXT_SOURCE_INVALID", "D75_CONTEXT_SOURCE_STALE",
    }
    refused_context = receipt.get("reason") in context_refusals
    if refused_context and receipt.get("component_status") != "NOT_MEASURED":
        raise D75Refusal("D75_RECEIPT_INVALID", "context refusal status")
    if (not refused_context
            and (not isinstance(context_sha256, str) or len(context_sha256) != 64
                 or not any(isinstance(item, Mapping)
                            and item.get("path") == expected_context
                            for item in receipt.get("inputs", [])))):
        raise D75Refusal("D75_RECEIPT_INVALID", "context identity")
    if receipt.get("consumer_load_identity") != operation_sources():
        raise D75Refusal("D75_LOAD_IDENTITY_MISMATCH", "D75 adapter/consumer sources")
    for item in receipt.get("inputs", []):
        if not isinstance(item, Mapping) or not item.get("path") or not item.get("sha256"):
            raise D75Refusal("D75_RECEIPT_INVALID", "input identity")
        path = Path(str(item["path"]))
        resolved = path if path.is_absolute() else project / path
        if not resolved.is_file() or _sha(resolved) != item["sha256"]:
            raise D75Refusal("D75_INPUT_STALE", str(path))
    if not refused_context:
        context_path = project / CONTEXT_REQUESTS / f"{context_sha256}.json"
        saved_context = _read(context_path)
        package_required = (saved_context.get("features") or {}).get(
            "package_model_required") is True
        package_check = next((item for item in receipt.get("checks", [])
                              if isinstance(item, Mapping)
                              and item.get("check") == "package_electrical_feedback"), None)
        if package_required:
            if package_check is not None and package_check.get("status") == "PASS":
                detail, _ = _consume_d67(project)
                io = _read(project / IO_REPORT)
                current_geometry = _current_native_geometry(
                    project, _io_lefs(project, io))
                detail["subject_join"] = _join_d67_subject(
                    project, detail, io, current_geometry)
                if package_check.get("detail") != detail:
                    raise D75Refusal("D75_D67_RECEIPT_STALE",
                                     "current D67 consumer result changed")
            elif receipt.get("component_status") == "PASS":
                raise D75Refusal("D75_D67_RECEIPT_INVALID",
                                 "PASS omitted required D67 consumption")
        elif (package_check is not None
              and package_check.get("status") not in ("NOT_APPLICABLE",)):
            raise D75Refusal("D75_D67_SCOPE_MISMATCH",
                             "package model is not selected")
        provider = receipt.get("provider_identity")
        provider_ran = any(isinstance(item, Mapping)
                           and item.get("check") == "provider_bond_pad_edge"
                           for item in receipt.get("checks", []))
        decl = _read(project / DECLARATION)
        slots = sorted((project / submission.SLOTS_DIR_REL).glob("*.yaml"))
        provider_owed, provider_scope = _provider_scope(project, decl, slots)
        provider_check = next((item for item in receipt.get("checks", [])
                               if isinstance(item, Mapping)
                               and item.get("check") == "provider_bond_pad_edge"), None)
        if not provider_owed:
            if provider is not None:
                raise D75Refusal("D75_PROVIDER_SCOPE_MISMATCH",
                                 "validated self-tapeout provider scope")
            if provider_check is not None and (
                    provider_check.get("status") != "NOT_APPLICABLE"
                    or provider_check.get("detail") != provider_scope):
                raise D75Refusal("D75_PROVIDER_SCOPE_MISMATCH",
                                 "validated self-tapeout provider scope")
            if provider_check is None and receipt.get("component_status") == "PASS":
                raise D75Refusal("D75_PROVIDER_SCOPE_MISMATCH",
                                 "PASS omitted self-tapeout provider disposition")
        elif provider is not None or provider_ran or receipt.get("component_status") == "PASS":
            target_path = project / PROVIDER_TARGET
            current_provider = _provider_identity(project, {"profile": {
                "path": str(target_path.resolve()), "sha256": _sha(target_path)}})
            if not isinstance(provider, Mapping) or provider != current_provider:
                raise D75Refusal("D75_PROVIDER_IDENTITY_MISMATCH", str(PROVIDER_TARGET))


def execute(project: Path, context: Mapping) -> dict:
    project = Path(project).resolve()
    checks: list[dict] = []
    inputs: list[dict] = []
    provider_identity = None
    d67_detail = None
    try:
        _context(context)
        inputs.append(_context_input(project, context))
        decl_path = project / DECLARATION
        own_path = project / OPERATOR_ANSWERS
        inputs.extend(_tree_records(project, Path("input/submission_template")))
        inputs.extend(_tree_records(project, Path("input/docs")))
        inputs.extend((_record(project, decl_path), _record(project, own_path)))
        slots = sorted((project / submission.SLOTS_DIR_REL).glob("*.yaml"))
        if (project / declaration.SELF_TAPEOUT_REL).is_file():
            # The declaration consumer distinguishes a retained catalogue from
            # a selected shuttle route by reading these producer-owned facts.
            # Bind every one into the D75 receipt; otherwise a copied report or
            # an unrecorded owner answer could silently change that decision.
            inputs.append(_record(project, DESIGN_ANSWERS))
            if slots:
                inputs.append(_record(project, CATALOGUE_REPORT))
                inputs.extend(_tree_records(project, CATALOGUE_SOURCE))
        declaration_result = tapeout_declaration_check.evaluate(project)
        if declaration_result.get("verdict") != "PASS":
            checks.append(_check("tapeout_declaration_check", "FAIL",
                                 declaration_result))
            raise D75Refusal("D75_DECLARATION_CONSUMER_FAILED",
                             declaration_result.get("summary", "declaration refused"),
                             failed=True)
        checks.append(_check("tapeout_declaration_check", "PASS",
                             declaration_result))

        doc = _read(decl_path)
        delivery = declaration.answer(doc, "deliverable")
        if delivery != declaration.DELIVERABLE_DIE:
            raise D75Refusal("D75_DELIVERY_FORM_UNSUPPORTED", str(delivery))
        checks.append(_check("declared_delivery_form", "PASS", "bare die interface",
                             deliverable=delivery))

        features = context.get("features") or {}
        if features.get("package_model_required") is True:
            d67_detail, d67_inputs = _consume_d67(project)
            inputs.extend(d67_inputs)
            if d67_detail["status"] != "PASS":
                checks.append(_check("package_electrical_feedback",
                                     d67_detail["status"], d67_detail))
                raise D75Refusal(
                    "D75_D67_CONSUMER_FAILED",
                    "current D67 package electrical result failed",
                    failed=True)

        io_path = project / IO_REPORT
        io = _read(io_path)
        inputs.append(_record(project, io_path))
        if io.get("program") != "io_pad_chip_top_gen" or io.get("verdict") != "WROTE":
            raise D75Refusal("D75_PAD_INTERFACE_PRODUCER_INVALID", str(IO_REPORT), failed=True)
        io_lefs = _io_lefs(project, io)
        inputs.extend(_record(project, path) for path in io_lefs)

        current_geometry = _current_native_geometry(project, io_lefs)
        if current_geometry is None:
            def_path = project / PAD_DEF
            tech = _tech_lef(project)
            inputs.extend((_record(project, def_path), _record(project, tech)))
        else:
            def_path = current_geometry["def"]
            tech = current_geometry["tech"]
            inputs.extend(current_geometry["inputs"])
            checks.append(_check("current_native_geometry_authority", "PASS",
                                 current_geometry["detail"]))

        if d67_detail is not None:
            subject_join = _join_d67_subject(
                project, d67_detail, io, current_geometry)
            d67_detail["subject_join"] = subject_join
            checks.append(_check("package_electrical_feedback",
                                 subject_join["status"], d67_detail))
            if subject_join["status"] != "PASS":
                raise D75Refusal(
                    "D75_D67_SUBJECT_MISMATCH",
                    "; ".join(subject_join["mismatches"]), failed=True)
        side = pad_side_constraint_check.check(project, def_path)
        if side.get("verdict") == "FAIL":
            checks.append(_check("pad_side_constraint_check", "FAIL", side))
        elif side.get("verdict") != "PASS":
            checks.append(_check("pad_side_constraint_check", "NOT_MEASURED", side))
        else:
            checks.append(_check("pad_side_constraint_check", "PASS", side))

        rc, pads = pad_bterm_coincidence_check.run(
            def_path.read_text(errors="replace"),
            tech.read_text(errors="replace"), io_lefs)
        if rc != 0 or pads.get("undecided_nets"):
            pad_status = "NOT_MEASURED"
        elif pads.get("not_connected_nets") or not pads.get("connected_nets"):
            pad_status = "FAIL"
        else:
            pad_status = "PASS"
        checks.append(_check("pad_bterm_coincidence_check", pad_status, pads))

        layouts = tapeout_readiness_check.discover_layouts(project)
        if len(layouts) != 1:
            raise D75Refusal("D75_FINAL_GEOMETRY_UNBOUND",
                             f"expected one finished layout, found {len(layouts)}")
        gds = layouts[0]
        inputs.append(_record(project, gds))
        provider_owed, provider_scope = _provider_scope(project, doc, slots)
        if not provider_owed:
            checks.append(_check("provider_bond_pad_edge", "NOT_APPLICABLE",
                                 provider_scope))
        else:
            edge = provider_bond_pad_edge.measure(
                project, gds, top=str(io.get("chip_top_module") or ""))
            provider_identity = _provider_identity(project, edge)
            inputs.extend(_release_records(project, edge.get("profile")))
            inputs.extend(_release_records(
                project, edge.get("opening_layer", {}).get("source")))
            inputs.extend(_release_records(project, edge.get("master_sources")))
            if edge.get("verdict") == "FAIL":
                edge_status = "FAIL"
            elif edge.get("verdict") == "PASS":
                edge_status = "PASS"
            else:
                # MANUAL_REVIEW is a measured value without an authoritative
                # bound. It remains NOT_MEASURED and is never upgraded to PASS.
                edge_status = "NOT_MEASURED"
            checks.append(_check("provider_bond_pad_edge", edge_status, edge))

        l20_path = project / "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json"
        inputs.append(_record(project, l20_path))
        l20 = dft_atpg_coverage_check.l20_dft_applicability(project)
        requires_dft = features.get("requires_dft") is True
        if requires_dft:
            dft = dft_atpg_coverage_check.audit(project)
            status = "PASS" if dft.get("verdict") == "PASS" else (
                "FAIL" if dft.get("verdict") == "FAIL" else "NOT_MEASURED")
            checks.append(_check("dft_atpg_coverage_check", status, dft))
        elif l20.get("asserts_dft") is False:
            checks.append(_check("test_access_applicability", "NOT_APPLICABLE", l20))
        elif l20.get("asserts_dft") is True:
            checks.append(_check("test_access_applicability", "FAIL",
                                 "L20 declares DFT but Flow109 selection does not"))
        else:
            checks.append(_check("test_access_applicability", "NOT_MEASURED", l20))

        if features.get("requires_perc") is True:
            perc = perc_signoff_check.audit(project)
            pstatus = ("PASS" if perc.get("verdict") == "PASS" else
                       "FAIL" if perc.get("verdict") == "FAIL" else
                       "NOT_MEASURED")
            checks.append(_check("perc_signoff_check", pstatus, perc))
            for rel, _ in perc_signoff_check.PROJECTIONS:
                path = project / rel
                if path.is_file():
                    inputs.append(_record(project, path))
            summary = project / "reports/phase3/perc_equivalent.json"
            if summary.is_file():
                inputs.append(_record(project, summary))
        else:
            checks.append(_check("perc_signoff_check", "NOT_APPLICABLE",
                                 "requires_perc is false"))

        if features.get("package_model_required") is not True:
            checks.append(_check("package_electrical_feedback", "NOT_APPLICABLE",
                                 "package_model_required is false"))
        status = _aggregate(checks)
        reason = "D75_BARE_DIE_INTERFACE_COMPONENT_" + status
    except D75Refusal as exc:
        status = "FAIL" if exc.failed or any(c["status"]=="FAIL" for c in checks) else "NOT_MEASURED"
        reason = exc.code
        checks.append(_check("adapter_refusal", status, exc.detail))

    result = {
        "schema": SCHEMA, "step_id": STEP, "program": "flow109_package_ready",
        "context_sha256": context.get("context_sha256"),
        "component_status": status, "reason": reason, "checks": checks,
        "inputs": inputs, "native_started": bool(checks),
        "provider_identity": provider_identity,
        "consumer_load_identity": operation_sources(),
        "metric_acceptance_status": "UNIMPLEMENTED",
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "delivery_accepted": False,
        "scope": "Default package/test interface plus consumed D67 component only",
    }
    validate(project, result)
    return result


def _d75_metric_values(checks):
    """Harvest existing consumer results, keeping unknowns distinct from zero."""
    by_name = {}
    for check in checks:
        by_name.setdefault(check['check'],[]).append(check)
    failed_checks = sorted({c['check'] for c in checks if c.get('status')=='FAIL'})
    pads = [c['detail'] for c in by_name.get('pad_bterm_coincidence_check',[]) if isinstance(c.get('detail'),dict)]
    edges = [c['detail'] for c in by_name.get('provider_bond_pad_edge',[]) if isinstance(c.get('detail'),dict)]
    return {'status':'FAIL' if failed_checks else 'NOT_MEASURED','failed_checks':failed_checks,
            'pad_bterm':pads,'bond_pad_edge':edges,'checks':checks,
            'scope':'existing bare-die pad/bond/PERC/test consumers; full package/reference coverage unmeasured'}


def _d75_metric_observation(project, context, component):
    validate(project, component)
    saved = _read(project/CONTEXT_REQUESTS/f"{context['context_sha256']}.json")
    if saved != context:raise ValueError('D75_METRIC_CONTEXT_CHANGED')
    observed = _d75_metric_values(component['checks'])
    observed.update(inputs=component['inputs'],consumer_load_identity=component['consumer_load_identity'],
                    provider_identity=component.get('provider_identity'))
    return observed


def _d75_metric_acceptance(project, context, component):
    import flow109
    ids = ['package_ready.pad_bump_package_layout_agreement','package_ready.escape_bond_feasibility',
           'package_ready.package_feedback_unresolved','package_ready.test_access_ready',
           'package_ready.package_electrical_feedback_coverage']
    checks = component.get('checks') or []
    failed_names = {c.get('check') for c in checks if c.get('status')=='FAIL'}
    failed = component.get('component_status')=='FAIL' or bool(failed_names)
    result = {'row_id':'D75','status':'NOT_MEASURED','qualification':'NOT_MEASURED','obligations':[]}
    try:
        current = flow109.validate_execution_context(context)
        if current['resolved_row']['id']!='D75' or [o['id'] for o in current['resolved_row']['obligations']]!=ids:
            raise ValueError('D75_METRIC_CONTEXT_UNREGISTERED')
        observed = _d75_metric_observation(project, context, component)
        result['native_observation'] = observed
        failed_names.update(observed['failed_checks'])
        failed = failed or observed['status']=='FAIL'
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        result['reason'] = str(exc)
    owners = [ {'pad_side_constraint_check','pad_bterm_coincidence_check'},
               {'provider_bond_pad_edge'}, {'package_electrical_feedback'},
               {'dft_atpg_coverage_check','test_access_applicability'}, {'package_electrical_feedback'} ]
    gaps = ['D75_ADOPTED_FINAL_PAD_BUMP_LAYOUT_REFERENCE_UNAVAILABLE',
            'D75_REQUIRED_BOND_POPULATION_AND_SOURCE_RULE_COVERAGE_UNMEASURED',
            'D75_COMPLETE_REQUIRED_FEEDBACK_POPULATION_UNBOUND',
            'D75_INDEPENDENT_REQUIRED_TEST_ACCESS_POPULATION_UNBOUND',
            'D75_INDEPENDENT_REQUIRED_PACKAGE_ELECTRICAL_POPULATION_UNBOUND']
    for oid, names, gap in zip(ids,owners,gaps):
        failures = sorted(failed_names & names)
        result['obligations'].append({'id':oid,'status':'FAIL' if failures else 'NOT_MEASURED',
            'failed_checks':failures,'reason':'D75_EXISTING_CONSUMER_FAILURE' if failures else gap})
    if failed:result['status']='FAIL'
    return result

def consume_default_row_completion(project, context, component):
    """Canonical row completion; partial measurements do not qualify the row."""
    accepted = _d75_metric_acceptance(Path(project).resolve(), context, component)
    prior = component.get('metric_acceptance') or {}
    prior_ids = {o.get('id') for o in prior.get('obligations', []) if o.get('status') == 'FAIL'} if isinstance(prior, dict) else set()
    for item in accepted['obligations']:
        if item['id'] in prior_ids and item['status'] != 'FAIL':
            item.update(status='FAIL', reason='D75_PRIOR_MEASURED_FAILURE')
    if (component.get('default_row_status') == 'FAIL' or component.get('metric_acceptance_status') == 'FAIL'
            or isinstance(prior, dict) and prior.get('status') == 'FAIL' or prior_ids):
        accepted['status'] = 'FAIL'
        accepted['prior_failed_obligation_ids'] = sorted(prior_ids)
    return {**component, 'step_id': 'D75', 'context_sha256': context['context_sha256'],
        'metric_acceptance': accepted, 'metric_acceptance_status': accepted['status'],
        'default_row_status': accepted['status'], 'flow109_acceptance': accepted['status'],
        'completed': False, 'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
