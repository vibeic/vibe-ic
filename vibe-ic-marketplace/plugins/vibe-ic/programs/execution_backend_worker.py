"""Real source-owned backend component for the common execution controller."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import execution_modes as em
from execution_adapters_backend import ROWS
from execution_backend_gates import evaluate, states
from execution_backend_producers import produce, _current_step_producer_authority
from execution_backend_snapshot import sha


_L20_DFT_ABSENT = {
    "dft_present": False,
    "scan_chains": [],
    "bist_mbist": [],
    "jtag_tap": None,
}


def _condition_is_exact_no_dft(condition: object) -> bool:
    if not isinstance(condition, Mapping):
        return False
    declaration = condition.get("l_doc_declares")
    return (isinstance(declaration, Mapping)
            and declaration.get("l_doc") == "L20"
            and declaration.get("all_absent") == _L20_DFT_ABSENT)


def _receipt_owns_output(project: Path, output_spec: object) -> bool:
    if not isinstance(output_spec, str) or " OR " in output_spec:
        return False
    output = Path(output_spec)
    if output.is_absolute() or ".." in output.parts or not output.parts:
        return False
    marker = project / output.parent / "post_dft_not_run.json"
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    owned = data.get("skips_required_output")
    owns = (owned == output_spec if isinstance(owned, str)
            else isinstance(owned, list) and output_spec in owned)
    if not owns or data.get("reason_class") != "DESIGN_DECLARED_NA":
        return False
    try:
        from flow_compliance_check import _marker_declares_output_not_applicable
        return _marker_declares_output_not_applicable(project, data) is not None
    except Exception:
        return False


def _conditioned_entry_is_not_owed(project: Path, entry: Mapping[str, Any],
                                   rows: Mapping[str, Mapping[str, Any]]) -> bool:
    row = rows.get(str(entry.get("from")))
    if not isinstance(row, Mapping):
        return False
    condition = row.get("condition")
    if not _condition_is_exact_no_dft(condition):
        return False
    try:
        from flow_compliance_check import _check_condition
        if _check_condition(project, condition):
            return False
    except Exception:
        return False
    specs: list[str] = []
    if isinstance(entry.get("path"), str):
        specs.append(entry["path"])
    elif entry.get("outputs") == "all":
        specs.extend(str(value) for value in (row.get("required_outputs") or ())
                     if isinstance(value, str))
    return bool(specs) and any(_receipt_owns_output(project, spec)
                               for spec in specs)


def condition_aware_declarations(project: Path, declarations,
                                 rows: Mapping[str, Mapping[str, Any]] | None = None):
    """Apply producer conditions before backend declarations are expanded."""
    if rows is None:
        try:
            import _flow_yaml
            rows = {str(row.get("id")): row for row in _flow_yaml.load()["steps"]}
        except Exception:
            rows = {}
    filtered = []
    for entry in declarations or ():
        if (isinstance(entry, Mapping) and entry.get("from") != "external"
                and _conditioned_entry_is_not_owed(project, entry, rows)):
            continue
        filtered.append(entry)
    return filtered


def _copy_input_tree(inputs: Path, project: Path) -> None:
    source = inputs / "project"
    if source.is_dir():
        shutil.copytree(source, project)
    else:
        # The controller's input binding is authoritative; JSON is a valid
        # canonical input (netlist metadata, route declarations, manifests),
        # so do not silently drop it in the compatibility layout.
        shutil.copytree(inputs, project)


def resolve_contract(project: Path, patterns) -> tuple[dict, list[str]]:
    found, missing = {}, []
    for raw in patterns:
        alternatives = [part.strip() for part in str(raw).split(" OR ")]
        paths = sorted({p for pattern in alternatives for p in project.glob(pattern)
                        if p.is_file() and not p.is_symlink() and p.stat().st_size})
        if not paths:
            missing.append(str(raw))
        for path in paths:
            found[str(path.relative_to(project))] = sha(path)
    return found, missing


def resolve_input_contract(project: Path, declarations, manifest=None) -> list[str]:
    """Return the aggregate missing set used by issuer and worker preflight."""
    return _resolve_input_contract(project, declarations, manifest)["missing"]


def _valid_manifest_declaration(entry) -> bool:
    """Validate one JSON declaration before treating a manifest as authority."""
    if isinstance(entry, str):
        return bool(entry)
    if not isinstance(entry, Mapping):
        return False
    if 'required' in entry and type(entry['required']) is not bool:
        return False
    if 'check' in entry and not isinstance(entry['check'], str):
        return False
    path = entry.get('path')
    if path is not None and not isinstance(path, str):
        return False
    source = entry.get('from')
    source_is_step = (isinstance(source, int) and not isinstance(source, bool))
    source_is_name = isinstance(source, str) and bool(source)
    if source is not None and not (source_is_step or source_is_name):
        return False
    if entry.get('check') == 'none':
        return (source == 'external' and
                isinstance(entry.get('what'), str) and
                bool(entry['what']))
    if entry.get('outputs') == 'all':
        return source_is_step or source_is_name
    # The worker retains the historical path-only shape for direct callers;
    # the issuer's canonical expand path still rejects it before issuance.
    return isinstance(path, str) and bool(path)


def _valid_resolved_manifest(manifest) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    declarations = manifest.get('declarations')
    files = manifest.get('files')
    missing = manifest.get('missing')
    if (type(declarations) is not list or not isinstance(files, Mapping)
            or type(missing) is not list or
            not all(_valid_manifest_declaration(entry) for entry in declarations)
            or not all(isinstance(item, str) for item in missing)):
        return False
    for raw, expected in files.items():
        if not isinstance(raw, str) or not raw:
            return False
        digest = expected.get('sha256') if isinstance(expected, Mapping) else expected
        if not isinstance(digest, str) or not digest:
            return False
    return True


def _resolve_input_contract(project: Path, declarations, manifest=None) -> dict:
    """Resolve the issuer's one contract without dropping declaration shapes.

    The result is deliberately aggregate: every absent declaration is returned
    before the worker is allowed to call ``produce``.  Mapping declarations use
    the canonical ``step_required_inputs_check.expand`` implementation, so
    ``outputs: all``, OR alternatives and conditional no-DFT edges retain their
    existing semantics.  String entries are only mandatory when the issuer
    explicitly carried them as declarations; an optional entry may say
    ``required: false``.
    """
    import hashlib
    from step_required_inputs_check import expand
    try:
        import _flow_yaml
        rows = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    except Exception:
        rows = {}
    declarations = condition_aware_declarations(project, declarations, rows)
    missing = []
    seen = set()
    # An existing empty waiver is malformed input that must reach the schema
    # consumer.  Every other zero-byte member remains a preflight missing
    # input.  Grant this exception only through the explicit optional mapping
    # emitted by the backend issuer.
    zero_byte_allowed = {
        str(entry.get('path'))
        for entry in declarations or ()
        if isinstance(entry, Mapping)
        and entry.get('required') is False
        and isinstance(entry.get('path'), str)
    }

    def add(value):
        value = str(value)
        if value not in seen:
            seen.add(value)
            missing.append(value)

    def present(spec):
        root = project.resolve()

        def valid_candidate(candidate):
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                return False
            if (candidate.is_symlink() or not resolved.is_relative_to(root)
                    or not (candidate.is_file() or candidate.is_dir())):
                return False
            if candidate.is_file():
                return candidate.stat().st_size > 0
            # Directory declarations are part of the producer's staged
            # closure.  Require at least one substantive file and validate
            # every descendant so a symlink or escaped path cannot make the
            # directory appear present.
            files = []
            for child in candidate.rglob('*'):
                if child.is_symlink():
                    return False
                if child.is_file():
                    try:
                        child_resolved = child.resolve(strict=True)
                    except (OSError, RuntimeError):
                        return False
                    if (not child_resolved.is_relative_to(root)
                            or child.stat().st_size <= 0):
                        continue
                    files.append(child)
            return bool(files)

        for alternative in (part.strip() for part in str(spec).split(' OR ')):
            if not alternative:
                continue
            path = Path(alternative)
            if path.is_absolute() or '..' in path.parts:
                add(alternative)
                continue
            for candidate in project.glob(alternative):
                if valid_candidate(candidate):
                    return True
        return False

    for entry in declarations or ():
        if isinstance(entry, Mapping):
            if entry.get('required', True) is False:
                continue
            if entry.get('from') == 'external' and entry.get('check') == 'none':
                continue
            try:
                expanded = expand(dict(entry), rows)
            except KeyError:
                # Direct worker callers may carry the legacy path-only
                # declaration shape.  The issuer still rejects that shape;
                # here preserve its path and OR semantics for preflight.
                path = entry.get('path')
                expanded = [('external', path)] if isinstance(path, str) else []
            except TypeError:
                expanded = []
            if not expanded:
                if entry.get('path'):
                    add(entry['path'])
                continue
            for _, spec in expanded:
                if not present(spec):
                    add(spec)
        elif isinstance(entry, str):
            if not present(entry):
                add(entry)
        else:
            add(repr(entry))

    observed = manifest.get('files', {}) if isinstance(manifest, Mapping) else {}
    if isinstance(observed, Mapping):
        for raw, expected in observed.items():
            rel = Path(raw) if isinstance(raw, str) else None
            digest = expected.get('sha256') if isinstance(expected, Mapping) else expected
            if (rel is None or rel.is_absolute() or '..' in rel.parts or
                    rel.as_posix() != raw or not isinstance(digest, str)):
                add(raw)
                continue
            target = project / rel
            try:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError:
                add(raw)
                continue
            if (target.is_symlink() or not target.is_file() or
                    (not target.stat().st_size and str(rel) not in zero_byte_allowed)
                    or actual != digest.removeprefix('sha256:')):
                add(raw)
    if isinstance(manifest, Mapping):
        for item in manifest.get('missing', ()):
            add(item)
    return {'declarations': declarations, 'files': dict(observed) if isinstance(observed, Mapping) else {},
            'missing': missing}


def _declared_input_files(project: Path, declarations) -> dict[str, str]:
    """Derive a direct caller's input identity from declared paths only."""
    import hashlib
    from step_required_inputs_check import expand
    try:
        import _flow_yaml
        rows = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    except Exception:
        rows = {}
    specs = []
    for entry in condition_aware_declarations(project, declarations, rows):
        if isinstance(entry, str):
            specs.append(entry)
            continue
        if not isinstance(entry, Mapping):
            continue
        if entry.get('from') == 'external' and entry.get('check') == 'none':
            continue
        try:
            expanded = expand(dict(entry), rows)
        except (KeyError, TypeError, ValueError):
            expanded = []
        if expanded:
            specs.extend(spec for _, spec in expanded if isinstance(spec, str))
        elif isinstance(entry.get('path'), str):
            specs.append(entry['path'])
    found, _ = resolve_contract(project, specs)
    return {name: digest for name, digest in found.items()
            if isinstance(digest, str) and digest}


def _binding(inputs: Path) -> dict:
    raw = os.environ.get("VIBEIC_EXECUTION_BINDING")
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    files = {str(p.relative_to(inputs)): sha(p) for p in inputs.rglob("*")
             if p.is_file() and not p.is_symlink()}
    return {"inputs": files}


def execute_current_step(project: Path, *, step_id: str,
                         producer: Mapping[str, Any],
                         binding: Mapping[str, Any] | None = None) -> dict:
    """Consume a producer that already ran in the caller's canonical tree.

    The normal worker copies an isolated input tree and owns the producer
    invocation.  Default's phase runner owns the direct PnR invocation, so it
    cannot call :func:`execute` without running PnR twice.  This seam keeps the
    same authority -> consumer -> hash-bound result contract for that one
    caller-owned producer invocation.
    """
    project = Path(project)
    sid = str(step_id)
    row = ROWS[sid]["canonical_row"]
    if sid == '23':
        # This Default-only seam consumes the current row before stream-out
        # and LVS. Keep the canonical final-audit row immutable: its later
        # post-stream gate must still refuse an in-flow bundle.
        row = copy.deepcopy(row)
        for clause in row.get('gate', {}).get('all_of', []):
            command = clause.get('program_exit_zero', '')
            if command.startswith('drv_signoff_judge '):
                clause['program_exit_zero'] = command.replace(
                    '--capture-point post_stream', '--capture-point in_flow', 1)
    binding = dict(binding or {
        "step_id": sid,
        "source_sha": "default-direct",
        "required_gates": ("backend_canonical", "backend_native_substance"),
    })
    binding.setdefault("step_id", sid)
    binding.setdefault("required_gates", (
        "backend_canonical", "backend_native_substance"))
    producer = dict(producer or {})
    producer_verdict = producer.get("verdict", "NOT_MEASURED")
    current = producer.get("current_step_declared_producers")
    allowed, reason, authority_verdict = _current_step_producer_authority(
        current, project=project)
    if not allowed:
        if producer_verdict != "FAIL":
            producer_verdict = authority_verdict
        gate_result = {"status": "NOT_MEASURED", "ledger": [{
            "gate": "backend_consumer", "verdict": "NOT_MEASURED",
            "reason": reason}]}
    else:
        try:
            gate_result = evaluate(project, row)
        except BaseException as exc:  # noqa: BLE001 — disclose consumer errors
            gate_result = {"status": "NOT_MEASURED", "ledger": [{
                "gate": "backend_consumer", "verdict": "NOT_MEASURED",
                "reason": f"{type(exc).__name__}: {exc}"}]}
    files, missing = resolve_contract(project, row.get("required_outputs", ()))
    canonical_receipts = producer.get("canonical_receipts") or [{
        "schema": "vibeic/backend-producer-receipt/1",
        "producer": "default-canonical-producer",
        "step_id": sid,
        "verdict": producer_verdict,
        "current_step_declared_producers": current,
    }]
    native_receipts = producer.get("native_receipts") or []
    gate_status = gate_result.get("status", "NOT_MEASURED")
    gate_states = states(binding, gate_result, producer_verdict)
    verdict = ("FAIL" if producer_verdict == "FAIL" or gate_status == "FAIL" else
               "PASS" if producer_verdict == "PASS" and gate_status == "PASS" and
               canonical_receipts and not missing else "NOT_MEASURED")
    result = {
        "schema": "vibeic/backend-result/2", "step_id": sid,
        "source_sha": binding.get("source_sha"), "binding": binding,
        "producer_verdict": producer_verdict, "gates": gate_states,
        "gate_ledger": gate_result.get("ledger", []), "outputs": files,
        "canonical_step_result": gate_result.get("step"),
        "missing_outputs": missing, "native_receipts": native_receipts,
        "canonical_receipts": canonical_receipts, "verdict": verdict,
        "detail": producer.get("detail", ""),
        "current_step_declared_producers": current,
    }
    (project / "backend_result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def execute(inputs: Path, outputs: Path, *, step_id: str, params: dict) -> dict:
    inputs, outputs = Path(inputs), Path(outputs)
    outputs.mkdir(parents=True, exist_ok=True)
    project = outputs / "project"
    _copy_input_tree(inputs, project)
    binding = _binding(inputs)
    row = ROWS[str(step_id)]["canonical_row"]
    manifest_supplied = 'resolved_input_manifest' in params
    manifest = params.get('resolved_input_manifest')
    if manifest_supplied and not _valid_resolved_manifest(manifest):
        input_contract = []
        resolved = {'declarations': [], 'files': {},
                    'missing': ['resolved_input_manifest']}
    else:
        input_contract = (manifest.get('declarations') if manifest_supplied
                          else params.get("input_contract", row.get("required_inputs", ())))
        resolved = _resolve_input_contract(project, input_contract, manifest)
    input_contract = resolved['declarations']
    missing_inputs = resolved['missing']
    # The resolved declaration contract is the only producer input identity.
    # Never replace an empty/conditional declaration with the entire copied
    # project tree: that would admit stale outputs and unrelated inputs.
    producer_manifest = dict(resolved)
    if not manifest_supplied:
        producer_manifest['files'] = _declared_input_files(project, input_contract)
    producer = {"verdict": "NOT_MEASURED", "detail": "producer did not run"}
    gate_result = {"status": "NOT_MEASURED", "ledger": []}
    if missing_inputs:
        # Do not launch a producer against an incomplete project.  In
        # particular, a native producer may create or mutate artifacts before
        # the later gate stage can report the missing input.  The existing
        # fail-closed ledger remains the sole result for this path.
        gate_result = {"status": "NOT_MEASURED", "ledger": [{
            "gate": gate, "rc": None, "verdict": "NOT_MEASURED",
            "reason": "REQUIRED_INPUT_ABSENT"} for gate in binding.get("required_gates", ())]}
    else:
        try:
            params = dict(params, step_id=str(step_id), project=project,
                          resolved_input_manifest=producer_manifest)
            producer = produce(project, params)
            if not isinstance(producer, dict):
                producer = {"verdict": "NOT_MEASURED", "detail": "producer returned no result"}
        except BaseException as exc:
            producer = {"verdict": "NOT_MEASURED", "detail": f"{type(exc).__name__}: {exc}",
                        "canonical_receipts": [{
                            "schema": "vibeic/backend-producer-receipt/1",
                            "producer": "execution_backend_producers.produce",
                            "step_id": str(step_id), "verdict": "NOT_MEASURED",
                            "detail": f"{type(exc).__name__}: {exc}"}]}
        # A current-step producer census is authoritative.  If it is
        # incomplete, zero-population, nonzero, or wrong-owner, do not let the
        # consumer manufacture a PASS from pre-existing/audit-authored files.
        current = producer.get("current_step_declared_producers")
        allowed, reason, authority_verdict = _current_step_producer_authority(
            current, project=project)
        if not allowed:
            if producer.get('verdict') != 'FAIL':
                producer['verdict'] = authority_verdict
            gate_result = {"status": "NOT_MEASURED", "ledger": [{
                "gate": "backend_consumer", "verdict": "NOT_MEASURED",
                "reason": reason}]}
        else:
            # A producer exception must not erase a measured FAIL, and a
            # consumer exception must not prevent the canonical gate from being
            # represented in the digest-bound result.
            try:
                gate_result = evaluate(project, row)
            except BaseException as exc:
                gate_result = {"status": "NOT_MEASURED", "ledger": [{
                    "gate": "backend_consumer", "verdict": "NOT_MEASURED",
                    "reason": f"{type(exc).__name__}: {exc}"}]}
    files, missing = resolve_contract(project, row.get("required_outputs", ()))
    # Publish only exact current producer/gate bytes; no placeholder output is
    # created for a missing canonical contract.
    for name in files:
        source = project / name
        target = outputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    producer_verdict = producer.get("verdict", "NOT_MEASURED")
    gate_status = gate_result.get("status", "NOT_MEASURED")
    gate_states = states(binding, gate_result, producer.get("verdict", "NOT_MEASURED"))
    native_receipts = producer.get("native_receipts") or []
    canonical_receipts = producer.get("canonical_receipts") or []
    verdict = ("FAIL" if producer_verdict == "FAIL" or gate_status == "FAIL" else
               "PASS" if producer_verdict == "PASS" and gate_status == "PASS" and
               canonical_receipts and not missing and not missing_inputs else "NOT_MEASURED")
    result = {
        "schema": "vibeic/backend-result/2", "step_id": str(step_id),
        "source_sha": binding.get("source_sha"), "binding": binding,
        "producer_verdict": producer_verdict, "gates": gate_states,
        "gate_ledger": gate_result.get("ledger", []), "outputs": files,
        "missing_outputs": missing, "native_receipts": native_receipts,
        "canonical_receipts": canonical_receipts,
        "verdict": verdict, "detail": producer.get("detail", ""),
        "current_step_declared_producers": producer.get(
            "current_step_declared_producers"),
        "input_contract": input_contract, "missing_inputs": missing_inputs,
        "resolved_input_manifest": resolved,
    }
    (outputs / "backend_result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", type=Path)
    ap.add_argument("outputs", type=Path)
    ap.add_argument("--step-id", required=True)
    ap.add_argument("--params-json", default="{}")
    args = ap.parse_args(argv)
    try:
        params = json.loads(args.params_json)
        execute(args.inputs, args.outputs, step_id=args.step_id, params=params)
        return 0
    except Exception as exc:
        args.outputs.mkdir(parents=True, exist_ok=True)
        (args.outputs / "backend_result.json").write_text(json.dumps({
            "schema": "vibeic/backend-result/2", "step_id": args.step_id,
            "verdict": "NOT_MEASURED", "reason": f"{type(exc).__name__}: {exc}",
            "native_receipts": []}, sort_keys=True) + "\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
