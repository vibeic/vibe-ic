"""Minimal ULTRACORE seam for the reviewed 14-row release family."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from pathlib import Path
import sys
from typing import Mapping

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import execution_modes as em
from execution_source_snapshot import python_defined_symbols
from execution_provider_catalog import (RELEASE_IDS, RELEASE_SITES, coverage_rows,
                                        current_source_identity, current_source_tree_identity,
                                        source_closure, implementation_closure)
from execution_release_rows import ROWS

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE
EXTERNAL_IDS = ("40", "41", "42", "43", "44")
UNAVAILABLE_IDS = ("39",)
SOFTWARE_IDS = tuple(s for s in RELEASE_IDS
                     if s not in EXTERNAL_IDS and s not in UNAVAILABLE_IDS and RELEASE_SITES[s])
ALL_IDS = RELEASE_IDS
EXECUTION_DEPENDENCIES = (
    "digital_hardmacro_gen.py", "phase3_one_shot_runner.py",
    "ip_release_docs_gen.py", "digital_hardmacro_check.py", "release_docs_check.py",
    "_release_docs_build.py", "_release_docs_contract.py",
    "tapeout_checklist_gen.py", "foundry_handoff_pack_gen.py",
)

_NATIVE_ENGINES = ('magic', 'sta')
_NATIVE_COMPONENT_LIFETIME_S = 120.0
_NATIVE_ARGV_TEMPLATE = {
    'magic': ('{magic}', '-noconsole', '-dnull', '-rcfile', '{pdk_root}', '{private}'),
    'sta': ('{sta}', '-no_splash', '-exit', '{private}'),
}


RELEASE_PARAMETER_DEFAULTS = {
    "pdk_name": None, "pdk_root": None, "design_name": None,
    "source_sha": None, "module_role": None, "container": "",
    "cell_lef": "", "metal_prefix": "met", "full_lef": False,
    "pinonly": False,
    "source_tree_sha": None,
}


def _site_path(site: str) -> Path:
    module, _, symbol = site.partition(":")
    path = HERE / module
    if not module or not symbol or not path.is_file():
        raise em.Refusal("RELEASE_PRODUCER_SITE_MISSING", site)
    try:
        symbols = python_defined_symbols(path.read_text())
    except (OSError, SyntaxError) as exc:
        raise em.Refusal("RELEASE_PRODUCER_SITE_UNREADABLE", site) from exc
    if symbol not in symbols:
        raise em.Refusal("RELEASE_PRODUCER_SYMBOL_MISSING", site)
    return path


def _source_files(spec: Mapping[str, object]) -> dict[str, str]:
    paths = {Path(__file__), HERE / "execution_modes.py", HERE / "execution_provider_catalog.py",
             HERE / "execution_release_rows.py", HERE / "execution_release_worker.py",
             HERE / "execution_backend_worker.py", HERE / "execution_backend_producers.py",
             HERE / "execution_backend_gates.py", HERE / "execution_backend_snapshot.py"}
    paths.update(HERE / name for name in EXECUTION_DEPENDENCIES)
    paths.update(_site_path(site) for site in spec["producer_sites"])
    for gate in spec["consumer_gates"]:
        candidate = HERE / (str(gate) + ".py")
        if candidate.is_file():
            paths.add(candidate)
    paths.update({HERE / "data/execution_modes_portfolio.json",
                  HERE.parent / "flow/phase1_phase2_phase3.yaml",
                  HERE.parent / "benchmark/CAPTURE_ROUTING.json"})
    paths.update(HERE.glob("_atomic*.py"))
    paths = source_closure({p.resolve() for p in paths
                            if p.is_file() and not p.is_symlink()})
    paths.update(implementation_closure(HERE / 'execution_release_worker.py'))
    paths.add(Path(sys.executable).resolve())
    return {str(p): em.digest(p) for p in sorted(paths)}


def _composite_gate_execution(outputs, binding, report, report_sha):
    """Describe current in-process calls; observed worker issuance is authority."""
    step = str(binding.get("step_id"))
    required = list(binding.get("required_gates", ()))
    if (step not in ROWS or report.get("schema") != "vibeic/release-evidence/2" or
            report.get("source_sha") != binding.get("source_sha") or
            report.get("producer_verdict") != "PASS" or report.get("missing_inputs") or
            len(required) != len(set(required)) or
            set(required) != set(ROWS[step]["policy"]["mandatory_gate_programs"])):
        return {}
    from execution_release_worker import _canonical_gate_invocations, _command_argv
    expected = []
    for invocation in _canonical_gate_invocations(step, Path(outputs) / "project"):
        module, args = _command_argv(invocation["command"], Path(outputs) / "project")
        expected.append((module, [module, *args], bool(invocation["blocking"])))
    rows = report.get("gate_records")
    if not isinstance(rows, list) or len(rows) != len(expected):
        return {}
    groups, sources = {}, {}
    for row, (gate, argv, blocking) in zip(rows, expected):
        if (not isinstance(row, dict) or row.get("gate") != gate or
                row.get("argv") != argv or row.get("blocking") is not blocking):
            return {}
        if gate not in required or not blocking:
            continue
        source = HERE / (gate + ".py")
        if (type(row.get("rc")) is not int or row["rc"] != 0 or
                row.get("verdict") != "PASS" or not source.is_file() or source.is_symlink()):
            return {}
        groups.setdefault(gate, []).append(row)
        sources[str(source)] = em.digest(source)
    if set(groups) != set(required):
        return {}
    return {"schema": "vibeic/composite-gate-execution/1", "worker_component": "release-producer",
            "worker_source": str(HERE / "execution_release_worker.py"),
            "receipt_name": "release-evidence.json", "receipt_sha256": report_sha,
            "required_gates": required, "gate_records": groups, "gate_sources": sources}


def validate(outputs: Path, binding: Mapping[str, object]) -> em.Evidence:
    path = Path(outputs) / "release-evidence.json"
    if not path.is_file() or path.is_symlink():
        return em.Evidence(binding, "NOT_MEASURED", {}, {},
                           detail="NOT_MEASURED: no current release producer receipt")
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return em.Evidence(binding, "NOT_MEASURED", {}, {}, detail=str(exc))
    measured_fail = (report.get("producer_verdict") == "FAIL" or
                     report.get("design_verdict") == "FAIL" or
                     report.get("qualification") == "FAIL" or any(
                         row.get("verdict") == "FAIL"
                         for row in report.get("gate_records", ())
                         if isinstance(row, dict) and row.get("blocking", True)))
    # Requirements come from the issued context, never a mutable report label.
    native_required = binding.get("step_id") == "37.5ip"
    native_verdicts = []
    if native_required or report.get("native_receipts"):
        native_receipts = report.get("native_receipts") or []
        if not isinstance(native_receipts, list):
            native_receipts = [None]
        for native in native_receipts:
            try:
                value = validate_hardmacro_receipt(native)
                native_verdicts.append(value if value in ("PASS", "FAIL") else "NOT_MEASURED")
            except (em.Refusal, AttributeError, TypeError, ValueError):
                native_verdicts.append("NOT_MEASURED")
        measured_fail = measured_fail or "FAIL" in native_verdicts
    if report.get("binding") != dict(binding):
        return em.Evidence(binding, "FAIL" if measured_fail else "NOT_MEASURED", {}, {},
                           detail="RELEASE_RESULT_UNBOUND")
    if report.get("step_id") != binding.get("step_id"):
        return em.Evidence(binding, "FAIL" if measured_fail else "NOT_MEASURED", {}, {},
                           detail="RELEASE_STEP_IDENTITY_MISMATCH")
    if binding.get("step_id") == "39" and report.get("excluded_from_verdict") is not True:
        return em.Evidence(binding, "NOT_MEASURED", {}, {},
                           detail="STEP39_EXCLUSION_DECLARATION_MISSING")
    gates: dict[str, str] = {}
    for row in report.get("gate_records", ()):
        if not isinstance(row, dict) or not row.get("gate") or not row.get("blocking", True):
            continue
        name, verdict = str(row["gate"]), str(row.get("verdict", "NOT_MEASURED"))
        previous = gates.get(name)
        # Duplicate canonical invocations aggregate fail-closed instead of
        # letting the last invocation hide an earlier failure.
        if previous == "FAIL" or verdict == "FAIL":
            gates[name] = "FAIL"
        elif previous == "NOT_MEASURED" or verdict == "NOT_MEASURED":
            gates[name] = "NOT_MEASURED"
        else:
            gates[name] = "PASS"
    outputs_hashes = {"release-evidence.json": em.digest(path)}
    for name, expected in (report.get("outputs") or {}).items():
        file = Path(outputs) / name
        if file.is_file() and not file.is_symlink() and em.digest(file) == expected:
            outputs_hashes[name] = expected
        elif measured_fail:
            return em.Evidence(binding, "FAIL", gates, outputs_hashes,
                               detail="measured FAIL with changed output: " + str(name))
        else:
            return em.Evidence(binding, "NOT_MEASURED", gates, outputs_hashes,
                               detail="RELEASE_OUTPUT_UNMEASURED: " + str(name))
    verdict = "FAIL" if measured_fail else (
        "PASS" if report.get("qualification") == "PASS" and not report.get("missing_outputs") and
        (not native_required or native_verdicts and all(v == "PASS" for v in native_verdicts))
        else "NOT_MEASURED")
    composite = _composite_gate_execution(outputs, binding, report, outputs_hashes["release-evidence.json"])
    return em.Evidence(binding, verdict, gates, outputs_hashes,
                       metrics={"canonical_evidence": int(verdict == "PASS" and bool(composite))},
                       detail=str(report.get("reason", "")),
                       provenance={"composite_gate_execution": composite} if composite else {})


def _native_finite(value, field):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_INCOMPLETE', field)
    return float(value)



def _native_under(path, roots):
    try:
        resolved = Path(path).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)



def validate_native_admission(admission, *, identities, input_population_sha256,
                              project, pdk_root, now=None, output_root=None):
    """Validate the same closed native envelope at prepare and every launch.

    The returned document is not an authority of its own: callers still bind
    the JSON bytes and current input population through their surrounding
    context.  This function only admits a complete, finite, source-owned
    engine contract and refuses ambiguous/partial facts before a native spawn.
    """
    if not isinstance(admission, dict):
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_UNBOUND', 'not an object')
    required = {'source_sha': identities.get('source_sha'), 'top': identities.get('top'),
                'pdk': identities.get('pdk'), 'image': identities.get('image'),
                'step_id': '37.5ip'}
    if admission.get('identities') != required or admission.get('status') != 'ADMITTED':
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_UNBOUND', '37.5ip')
    exact_input = admission.get('exact_input_sha256')
    if (not isinstance(exact_input, str) or not re.fullmatch(r'[0-9a-f]{64}', exact_input)
            or exact_input != input_population_sha256):
        raise em.Refusal('RELEASE_NATIVE_INPUT_NOT_ADMITTED', '37.5ip')
    issued = _native_finite(admission.get('issued_at_epoch_s'), 'issued_at_epoch_s')
    lifetime = _native_finite(admission.get('component_lifetime_s'), 'component_lifetime_s')
    deadline = _native_finite(admission.get('deadline_epoch_s'), 'deadline_epoch_s')
    lease_deadline = _native_finite(admission.get('lease_deadline_epoch_s'), 'lease_deadline_epoch_s')
    if lifetime <= 0 or lifetime > _NATIVE_COMPONENT_LIFETIME_S:
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_INCOMPLETE', 'component_lifetime_s')
    current = time.time() if now is None else _native_finite(now, 'now')
    if deadline <= current or lease_deadline <= current or deadline > issued + lifetime or deadline > lease_deadline:
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_EXPIRED', '37.5ip')
    if issued > current + 5.0:
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_UNBOUND', 'issued_at_epoch_s')
    if not isinstance(project, Path):
        project = Path(project)
    try:
        project = project.resolve(strict=True)
        pdk_root = Path(pdk_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise em.Refusal('RELEASE_NATIVE_PDK_NOT_FROZEN', str(pdk_root)) from exc
    if not pdk_root.is_dir() or not pdk_root.is_relative_to(project):
        raise em.Refusal('RELEASE_NATIVE_PDK_NOT_FROZEN', str(pdk_root))
    binaries = admission.get('tool_binaries')
    if not isinstance(binaries, dict) or set(binaries) != set(_NATIVE_ENGINES):
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_INCOMPLETE', 'tool_binaries')
    resolved_doc = admission.get('resolved_binaries')
    if not isinstance(resolved_doc, dict) or set(resolved_doc) != set(_NATIVE_ENGINES):
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_INCOMPLETE', 'resolved_binaries')
    resolved = {}
    for engine in _NATIVE_ENGINES:
        name, digest = engine, binaries.get(engine)
        # Names are engine labels, while the values bind the actual resolved
        # executable.  This prevents a Python-only or boolean/partial arm.
        path_value = resolved_doc.get(name)
        if not isinstance(path_value, str) or not os.path.isabs(path_value):
            raise em.Refusal('RELEASE_NATIVE_ADMISSION_INCOMPLETE', 'resolved_binaries.' + name)
        binary = Path(path_value)
        if (binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK)
                or binary.name != engine or not isinstance(digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise em.Refusal('RELEASE_NATIVE_BINARY_CHANGED', path_value)
        actual = Path(shutil.which(engine) or '').resolve()
        if not actual.is_file() or actual != binary.resolve() or em.digest(actual) != digest:
            raise em.Refusal('RELEASE_NATIVE_ENGINE_UNBOUND', engine)
        resolved[engine] = actual
    contract = admission.get('allowed_argv')
    if not isinstance(contract, list) or len(contract) != len(_NATIVE_ENGINES):
        raise em.Refusal('RELEASE_NATIVE_ADMISSION_INCOMPLETE', 'allowed_argv')
    seen = set()
    for row in contract:
        if not isinstance(row, dict) or row.get('engine') not in _NATIVE_ENGINES:
            raise em.Refusal('RELEASE_NATIVE_ARGV_NOT_ADMITTED', 'contract')
        engine = row['engine']
        argv = row.get('argv')
        if engine in seen or not isinstance(argv, list) or tuple(argv) != _NATIVE_ARGV_TEMPLATE[engine]:
            raise em.Refusal('RELEASE_NATIVE_ARGV_NOT_ADMITTED', engine)
        if any(not isinstance(token, str) or token in ('bash', 'sh', '-lc', '-c')
               or any(mark in token for mark in (';', '&&', '|', '$(', '`')) for token in argv):
            raise em.Refusal('RELEASE_NATIVE_ARGV_NOT_ADMITTED', engine)
        seen.add(engine)
    if seen != set(_NATIVE_ENGINES):
        raise em.Refusal('RELEASE_NATIVE_ARGV_NOT_ADMITTED', 'contract')
    return {'admission': admission, 'binaries': resolved, 'project': project,
            'pdk_root': pdk_root, 'output_root': Path(output_root).resolve() if output_root else None}



def native_command_allowed(argv, validated, *, output_root=None):
    """Match one concrete leaf argv against the source-owned contract."""
    argv = tuple(map(str, argv))
    if not argv:
        return False
    binaries = validated['binaries']
    binary = Path(shutil.which(argv[0]) or argv[0]).resolve()
    engine = binary.name
    expected_binary = binaries.get(engine)
    if expected_binary is None or binary != expected_binary:
        return False
    template = _NATIVE_ARGV_TEMPLATE[engine]
    if len(argv) != len(template):
        return False
    project = validated['project']
    pdk_root = validated['pdk_root']
    roots = [project]
    if output_root:
        roots.append(Path(output_root).resolve())
    for actual, expected in zip(argv, template):
        if expected == '{' + engine + '}':
            if Path(actual).resolve() != expected_binary:
                return False
        elif expected == '{pdk_root}':
            if not _native_under(actual, (pdk_root,)):
                return False
        elif expected == '{private}':
            if not _native_under(actual, tuple(roots)):
                return False
        elif actual != expected:
            return False
    return True


def validate_hardmacro_receipt(receipt: Mapping[str, object], *, route: str = "native") -> str:
    """Require the generator's typed Magic/OpenSTA facts; never relabel rc0."""
    if receipt.get("status") == "FAIL":
        return "FAIL"
    if route == "direct_magic":
        raise em.Refusal("RELEASE_DIRECT_MAGIC_FALLBACK_REFUSED",
                         "direct Magic is not an independent hardmacro provider")
    processes = receipt.get("processes") or []
    binaries = {Path(str(row.get("binary", row.get("tool", "")))).name
                for row in processes if isinstance(row, dict)}
    typed = all(isinstance(row, dict) and row.get("rc") == 0 and
                isinstance(row.get("version"), str) and row.get("version") and
                isinstance(row.get("argv"), (list, tuple)) and row.get("argv") and
                isinstance(row.get("output_sha256"), str) and
                len(row.get("output_sha256")) == 64
                for row in processes)
    has_sta = "sta" in binaries or "opensta" in binaries
    if (receipt.get("status") != "PRODUCED" or
            "magic" not in binaries or not has_sta or not typed):
        raise em.Refusal("RELEASE_NATIVE_ENGINE_RECEIPT_UNMEASURED", repr(dict(receipt)))
    return "PASS"


def _adapter(spec: Mapping[str, object], source_sha: str, objective: Mapping[str, object], *,
             path: str, available: bool, route_receipt: Mapping[str, object] | None,
             declaration: Mapping[str, object] | None,
             parameters: Mapping[str, object] | None = None,
             native_qualified: bool = False) -> em.Adapter:
    source_sha = current_source_identity()
    from execution_provider_catalog import _applicability
    step_id = str(spec["step_id"])
    app = _applicability(step_id, release=True,
                         route_receipt=dict(route_receipt or {}), declaration=dict(declaration or {})).get(path, "unknown")
    applicability = ("applicable" if app == "applicable" or app.startswith("applicable:") else
                     "inapplicable" if app.startswith("inapplicable") else "unknown")
    worker = HERE / "execution_release_worker.py"
    source_files = _source_files(spec)
    source_files.update({str(p): em.digest(p) for p in em._source_closure(source_files)})
    contract = {name: ("release-evidence.json",) for name in spec["canonical_outputs"]}
    params = dict(RELEASE_PARAMETER_DEFAULTS)
    if parameters:
        for key, value in parameters.items():
            if key not in params:
                raise em.Refusal("RELEASE_PARAMETER_UNDECLARED", str(key))
            if isinstance(value, Path):
                value = str(value)
            params[key] = value
    # source identity is controller-derived and cannot be overridden through
    # the release argv parameter map.
    params["source_sha"] = source_sha
    params["source_tree_sha"] = current_source_tree_identity()
    params.update({"route": path, "row": step_id, "runtime_status": "NOT_MEASURED",
                   "external_handoff": step_id in EXTERNAL_IDS,
                   "input_contract": ROWS[step_id].get("canonical", {}).get("required_inputs")})
    external = step_id in EXTERNAL_IDS
    unavailable = step_id in UNAVAILABLE_IDS
    role = "complementary" if external else "producer"
    reason = ("EXTERNAL_HANDOFF_ONLY" if external else
              "FPGA_HARDWARE_ABSENT_NOT_MEASURED" if unavailable else
              "" if available else "NATIVE_EXECUTION_NOT_MEASURED")
    return em.Adapter(
        arm_id=str(spec["arm_id"]), tool_id="release-worker", step_id=str(spec["step_id"]),
        source_sha=source_sha, source_files=source_files,
        tool_version="source-bound; native qualification NOT_MEASURED",
        engine_families=tuple(spec["engine_families"]),
        components=(em.Component("release-producer", (str(Path(sys.executable).resolve()), str(worker),
                    "{inputs}", "{outputs}", "--step-id", str(spec["step_id"]),
                    "--params-json", json.dumps(params, sort_keys=True)), 60),),
        validate=validate, required_outputs=("release-evidence.json",), output_contract=contract,
        objective=dict(objective), applicability=applicability,
        applicability_reason="" if applicability == "applicable" else str(app),
        qualified=native_qualified, qualification_evidence=(
                                                 "current-tree native qualification receipt bound" if native_qualified else
                                                 "source-bound component; producer sites=" + ",".join(spec["producer_sites"]) +
                                                 "; native qualification NOT_MEASURED" if not external else
                                                 "external handoff classification only; no software producer"),
        available=available and not unavailable and not external, availability_reason=reason,
        # Native OpenROAD reserves about 3.43 GiB of virtual address space
        # before reading the clock plan (EDA 0.4.1); Controller enforces RLIMIT_AS.
        cpus=1, ram_mb=4096 if step_id == "16" else 256,
        role=role,
        own_no_tool_reason="One complete release producer owns the row; physical/external evidence remains outside software.",
    )


def register_release_adapters(registry: em.Registry | None = None, *, source_sha: str,
                              objective: Mapping[str, object] | None = None,
                              path: str = "IC", available: bool = False,
                              route_receipt: Mapping[str, object] | None = None,
                              declaration: Mapping[str, object] | None = None,
                              parameters: Mapping[str, object] | None = None,
                              step_ids=None) -> em.Registry:
    source_sha = current_source_identity()
    registry = registry or em.Registry()
    objective = objective or {"metric": "canonical_evidence", "direction": "max"}
    rows = {row["step_id"]: row for row in coverage_rows()}
    selected = set(ALL_IDS if step_ids is None else map(str, step_ids))
    if not selected.issubset(ALL_IDS):
        raise em.Refusal('UNKNOWN_RELEASE_FIXED_STEP', repr(step_ids))
    for step_id in ALL_IDS:
        if step_id not in selected:
            continue
        registry.register(_adapter(rows[step_id], source_sha, objective, path=path,
                                   available=available, route_receipt=route_receipt,
                                   declaration=declaration, parameters=parameters))
    return registry


def build_registry(**kwargs) -> em.Registry:
    return register_release_adapters(**kwargs)


__all__ = ["ROWS", "RELEASE_IDS", "SOFTWARE_IDS", "UNAVAILABLE_IDS", "EXTERNAL_IDS", "ALL_IDS",
           "register_release_adapters", "build_registry", "validate_hardmacro_receipt"]
