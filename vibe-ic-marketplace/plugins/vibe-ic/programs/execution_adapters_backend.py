"""Minimal ULTRACORE seam for the reviewed 23-row backend family.

This module registers one complete source-owned producer per canonical row in
the existing :mod:`execution_modes` registry.  It contains no native runner,
lease, dispatch, or scheduler.  A registered adapter is a reachability
description; native qualification stays ``NOT_MEASURED`` until a current
producer receipt and every downstream gate are observed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
import shlex
from pathlib import Path
import sys
from typing import Mapping

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import execution_modes as em
from execution_source_snapshot import python_defined_symbols
from execution_provider_catalog import (BACKEND_IDS, BACKEND_ROWS, coverage_rows,
                                        current_source_identity, current_source_tree_identity,
                                        source_closure, implementation_closure)

HERE = Path(__file__).resolve().parent
POLICY = HERE / "data/execution_backend_policy.json"
ROWS = BACKEND_ROWS

# Every producer receives the complete typed parameter envelope. ``None`` is
# intentional for source-only registrations: the key is bound in argv while
# the worker still refuses to run until a current project supplies the value.
BACKEND_PARAMETER_DEFAULTS = {
    "pdk_name": None, "image_id": None, "pdk_root": None, "top": None,
    "container": "", "die_um": None, "util": None, "state_in": None,
    "overlay": {}, "streamout_route": None, "simulators": None,
    "spice_paths": 1, "timeout_s": 60,
    "source_tree_sha": None,
    # Issued immediately before dispatch by execution_policy._fixed_inputs.
    # ``None`` keeps source-only registration stable; a live worker receives
    # the exact path->digest census from that invocation.
    "resolved_input_manifest": None,
}

# These are imported by the actual dispatcher/producer call paths.  Binding
# only the catalog entrypoint would let a changed runner or LibreLane contract
# execute under an old adapter identity.
EXECUTION_DEPENDENCIES = (
    "phase3_one_shot_runner.py", "librelane_contract.py", "librelane_cts_hold.py",
    "librelane_route.py", "librelane_postroute_repair.py", "librelane_signoff.py",
    "librelane_step37.py", "librelane_fill_dfm.py", "path_spice_tool.py",
    "spice_correlation_check.py", "gds_xor_check.py", "si_signoff_timing_aware.py",
    "si_mcf_sta.py", "perc_corpus_sweep.py", "hold_area_budget_check.py",
    "flow_compliance_check.py",
)


@dataclass(frozen=True)
class Step30InstrumentPlan:
    simulators: tuple[str, ...]
    defaulted: bool
    runtime_status: str = "NOT_MEASURED"


def _site_path(site: str) -> Path:
    module, _, symbol = site.partition(":")
    path = HERE / module
    if not module or not symbol or not path.is_file():
        raise em.Refusal("BACKEND_PRODUCER_SITE_MISSING", f"{path}: producer site {site!r} requires module:symbol and an existing source file")
    try:
        symbols = python_defined_symbols(path.read_text())
    except (OSError, SyntaxError) as exc:
        raise em.Refusal("BACKEND_PRODUCER_SITE_UNREADABLE", site) from exc
    if symbol not in symbols:
        raise em.Refusal("BACKEND_PRODUCER_SYMBOL_MISSING", f"{path}: producer symbol {symbol!r} from site {site!r} is not among parsed Python definitions")
    return path


def _source_files(spec: Mapping[str, object]) -> dict[str, str]:
    paths = {HERE / "execution_modes.py", Path(__file__), HERE / "execution_provider_catalog.py"}
    paths.update(_site_path(site) for site in spec["producer_sites"])
    # The worker imports this module and calls its row dispatcher directly.
    # Bind the dispatcher and its canonical gate implementation in the same
    # source identity; a file:symbol catalog entry is not an executable CLI.
    paths.update({HERE / "execution_backend_producers.py", HERE / "execution_backend_gates.py"})
    paths.add(HERE / "execution_backend_consumer.py")
    paths.update(HERE / name for name in EXECUTION_DEPENDENCIES)
    for gate in spec["consumer_gates"]:
        candidate = HERE / (str(gate) + ".py")
        if candidate.is_file():
            paths.add(candidate)
    paths.add(HERE / "execution_backend_snapshot.py")
    paths.add(HERE / "execution_backend_worker.py")
    # Policy/index and canonical routing are executable authority, not merely
    # descriptive documentation. Bind them and every local Python import they
    # reach before a receipt can be adopted.
    paths.update({POLICY, HERE / "data/execution_modes_portfolio.json",
                  HERE.parent / "flow/phase1_phase2_phase3.yaml",
                  HERE.parent / "benchmark/CAPTURE_ROUTING.json"})
    paths.update(HERE.glob("_atomic*.py"))
    paths = source_closure({p.resolve() for p in paths
                            if p.is_file() and not p.is_symlink()})
    paths.update(implementation_closure(HERE / 'execution_backend_worker.py'))
    paths.add(Path(sys.executable).resolve())
    return {str(p): em.digest(p) for p in sorted(paths)}


def _issue_direct_inputs(project, params, sid, extra):
    """Issue a complete direct-provider contract from current frozen inputs.

    Direct arms are omitted unless the caller supplied the source-owned
    preparation facts and every digest-bound input needed to derive a builder
    invocation.  Builder derivation and native execution intentionally use
    separate private directories.
    """
    if sid not in ('15', '19'):
        return None
    supplied = params.get('direct_inputs')
    if not isinstance(supplied, dict):
        return None
    required = ('predecessor_state', 'preparation_input', 'spare_plan',
                'row_inputs', 'expected_inputs', 'mounts')
    if any(key not in supplied for key in required):
        return None
    import phase3_one_shot_runner as runner
    prepare_direct_pnr_builder_input = getattr(runner, 'prepare_direct_pnr_builder_input', None)
    if not callable(prepare_direct_pnr_builder_input):
        return None
    builder_dir = project.parent / ('.backend-builder-' + sid)
    execution_dir = project / '.backend-direct-execution' / sid
    if builder_dir.exists() or execution_dir.exists():
        return None
    try:
        issued = prepare_direct_pnr_builder_input(
            project, step_id=sid,
            predecessor_state=Path(supplied['predecessor_state']).absolute(),
            preparation_input=Path(supplied['preparation_input']).absolute(),
            spare_plan=(Path(supplied['spare_plan']).absolute()
                        if supplied.get('spare_plan') else None),
            row_inputs={str(k): Path(v).absolute()
                        for k, v in dict(supplied['row_inputs']).items()},
            expected_inputs={str(k): str(v)
                             for k, v in dict(supplied['expected_inputs']).items()},
            mounts=[(Path(a).absolute(), str(b)) for a, b in supplied['mounts']],
            arm_dir=builder_dir)
    except (OSError, TypeError, ValueError, em.Refusal):
        return None
    # Every derived byte is issued as an external INPUT and therefore enters
    # the lexical capture before the registry qualifies the direct arm.
    for name, value in {
        'direct_predecessor_state': issued['predecessor_state'],
        'direct_builder_input': issued['builder_input'],
        'direct_builder_transform': issued['transform'],
    }.items():
        extra[name] = Path(value)
    for index, value in enumerate(issued['expected_inputs']):
        path = Path(value)
        if path.is_file() and not path.is_symlink():
            extra['direct-input-%03d' % index] = path
    complete = dict(issued)
    complete['preparation_input'] = str(Path(supplied['preparation_input']).absolute())
    complete['spare_plan'] = (str(Path(supplied['spare_plan']).absolute())
                              if supplied.get('spare_plan') else None)
    extra['direct_preparation_input'] = Path(complete['preparation_input'])
    if complete['spare_plan']:
        extra['direct_spare_plan'] = Path(complete['spare_plan'])
    complete['execution_arm_dir'] = str(execution_dir)
    complete['builder_dir'] = str(builder_dir)
    params['direct_inputs'] = complete
    return complete


def _composite_gate_execution(binding, result, report_sha):
    """Project the canonical consumer ledger without inventing child processes."""
    step = str(binding.get("step_id"))
    required = list(binding.get("required_gates", ()))
    from execution_backend_gates import required_programs, required_commands
    summaries = {"backend_canonical", "backend_native_substance"}
    if (step not in ROWS or result.get("schema") != "vibeic/backend-result/2" or
            result.get("step_id") != step or result.get("source_sha") != binding.get("source_sha") or
            result.get("producer_verdict") != "PASS" or result.get("verdict") != "PASS" or
            result.get("missing_inputs") or result.get("missing_outputs") or
            set(result.get("gates", {})) != set(required) | summaries or
            any(result["gates"].get(name) != "PASS" for name in summaries) or
            len(required) != len(set(required)) or
            not required or
            set(required) != set(required_programs(ROWS[step]["canonical_row"]))):
        return {}
    producers = result.get("canonical_receipts")
    if (not isinstance(producers, list) or not producers or any(
            not isinstance(row, dict) or row.get("schema") != "vibeic/backend-producer-receipt/1" or
            row.get("producer") != "execution_backend_producers.produce" or
            row.get("step_id") != step or row.get("verdict") != "PASS" for row in producers)):
        return {}
    commands = required_commands(ROWS[step]["canonical_row"])
    ledger = result.get("gate_ledger")
    if not isinstance(ledger, list):
        return {}
    groups, sources = {}, {}
    for gate in required:
        if result.get("gates", {}).get(gate) != "PASS":
            return {}
        if gate == "backend_canonical":
            groups[gate] = [{"consumer": "execution_backend_gates.evaluate", "ledger": ledger}]
            source = HERE / "execution_backend_gates.py"
        elif gate == "backend_native_substance":
            groups[gate] = [{"producer_receipts": producers}]
            source = HERE / "execution_backend_producers.py"
        else:
            expected = [cmd for cmd in commands if Path(shlex.split(cmd)[0]).stem == gate]
            rows = [row for row in ledger if isinstance(row, dict) and
                    row.get("gate") == gate and row.get("cmd") in expected]
            if (not expected or sorted(row.get("cmd", "") for row in rows) != sorted(expected) or
                    any(type(row.get("rc")) is not int or row["rc"] != 0 or
                        row.get("verdict") != "PASS" or row.get("exit_code", 0) != 0 for row in rows)):
                return {}
            groups[gate] = rows
            source = HERE / (gate + ".py")
        if not source.is_file() or source.is_symlink():
            return {}
        sources[str(source)] = em.digest(source)
    return {"schema": "vibeic/composite-gate-execution/1", "worker_component": "producer",
            "worker_source": str(HERE / "execution_backend_worker.py"),
            "receipt_name": "backend_result.json", "receipt_sha256": report_sha,
            "required_gates": required, "gate_records": groups, "gate_sources": sources}


def _evidence_from_receipt(outputs: Path, binding: Mapping[str, object], *, gates: tuple[str, ...]) -> em.Evidence:
    """Read a provider receipt without treating rc0 or metadata as evidence."""
    path = outputs / "backend_result.json"
    if not path.is_file() or path.is_symlink():
        return em.Evidence(binding, "NOT_MEASURED", {g: "NOT_MEASURED" for g in gates}, {},
                           detail="NOT_MEASURED: no current backend native receipt")
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return em.Evidence(binding, "NOT_MEASURED", {}, {}, detail=f"malformed receipt: {exc}")
    measured_fail = result.get("verdict") == "FAIL" or result.get("producer_verdict") == "FAIL" or any(
        value == "FAIL" for value in (result.get("gates") or {}).values())
    if result.get("binding") != dict(binding):
        return em.Evidence(binding, "FAIL" if measured_fail else "NOT_MEASURED", {}, {},
                           detail="BACKEND_RESULT_UNBOUND")
    # The canonical worker also reports two composition summaries. Their FAIL
    # was reduced above; they are supporting facts in the hash-bound report,
    # not additional required gate invocations.
    observed = {name: (result.get("gates") or {}).get(name, "NOT_MEASURED") for name in gates}
    status = "FAIL" if measured_fail else "NOT_MEASURED"
    if (not measured_fail and result.get("verdict") == "PASS" and
            result.get("producer_verdict") == "PASS" and all(
            observed.get(g) == "PASS" for g in gates) and (
                result.get("native_receipts") or result.get("canonical_receipts"))):
        status = "PASS"
    outputs_hashes = {"backend_result.json": em.digest(path)}
    for name, expected in (result.get("outputs") or {}).items():
        candidate = outputs / Path(name)
        if candidate.is_file() and not candidate.is_symlink() and em.digest(candidate) == expected:
            outputs_hashes[name] = expected
        elif measured_fail:
            return em.Evidence(binding, "FAIL", observed, outputs_hashes,
                               detail="measured FAIL with changed output: " + str(name))
        else:
            return em.Evidence(binding, "NOT_MEASURED", observed, outputs_hashes,
                               detail="BACKEND_OUTPUT_UNMEASURED: " + str(name))
    composite = _composite_gate_execution(binding, result, outputs_hashes["backend_result.json"])
    return em.Evidence(binding, status, observed, outputs_hashes,
                       metrics={"canonical_evidence": int(status == "PASS" and bool(composite))},
                       detail=str(result.get("detail", "")),
                       provenance={"composite_gate_execution": composite} if composite else {})


def validate(outputs: Path, binding: Mapping[str, object]) -> em.Evidence:
    return _evidence_from_receipt(Path(outputs), binding,
                                  gates=tuple(binding.get("required_gates", ())))


def _step30_simulators(params: Mapping[str, object] | None = None) -> tuple[str, ...]:
    """Resolve one default ngspice instrument or an explicit Xyce request."""
    import path_spice_tool as spice
    params = params or {}
    if "simulators" not in params:
        return tuple(spice.SIMULATORS[:1])
    requested = params["simulators"]
    if isinstance(requested, str):
        requested = (requested,)
    if not isinstance(requested, (tuple, list)) or not requested:
        raise em.Refusal("BACKEND_SPICE_PROVIDER_UNSTATED", repr(requested))
    values = tuple(str(x).lower() for x in requested)
    if any(x not in tuple(spice.SIMULATORS) for x in values) or len(set(values)) != len(values):
        raise em.Refusal("BACKEND_SPICE_PROVIDER_UNSTATED", repr(requested))
    return values


def _step30_status(simulator, params, capabilities):
    """Return ``(eligible, reason)`` from complete issued capability facts."""
    available = params.get('available_simulators', params.get('feasible_simulators'))
    if isinstance(available, (list, tuple, set)) and simulator not in available:
        return False, 'EXECUTABLE_UNAVAILABLE'
    unavailable = params.get('unavailable_simulators')
    if isinstance(unavailable, (list, tuple, set)) and simulator in unavailable:
        return False, 'EXECUTABLE_UNAVAILABLE'
    if capabilities is None:
        if params.get('execution_mode') == 'ultra':
            return False, 'CAPABILITY_UNSTATED'
        # Direct default callers from the frozen API do not issue capacity
        # facts. Keep their historical primary attempt, but label it as
        # attempt eligibility rather than proven tool feasibility.
        return True, 'ATTEMPT_ELIGIBLE'
    if simulator not in capabilities:
        return False, 'CAPABILITY_UNSTATED'
    facts = capabilities[simulator]
    if facts is False:
        return False, 'EXECUTABLE_UNAVAILABLE'
    if facts is True:
        return False, 'CAPABILITY_MALFORMED'
    if not isinstance(facts, dict):
        return False, 'CAPABILITY_MALFORMED'
    if facts.get('available') is False:
        return False, 'EXECUTABLE_UNAVAILABLE'
    if facts.get('image') is False:
        return False, 'IMAGE_UNAVAILABLE'
    if facts.get('executable') is not True and facts.get('executable_available') is not True:
        return False, ('EXECUTABLE_UNAVAILABLE' if any(
            facts.get(key) is False for key in ('executable', 'executable_available'))
            else 'EXECUTABLE_UNSTATED')
    image = facts.get('image_id')
    current_image = params.get('image_id')
    if current_image is None and isinstance(params.get('native_facts'), dict):
        current_image = params['native_facts'].get('image_id')
    if not isinstance(image, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        return False, 'IMAGE_UNSTATED'
    if not isinstance(current_image, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', current_image):
        return False, 'IMAGE_UNBOUND'
    if image != current_image:
        return False, 'IMAGE_UNAVAILABLE'
    image_binding_facts = ('image_compatible', 'image_bound', 'image_binding')
    if not any(facts.get(key) is True for key in image_binding_facts):
        return False, ('IMAGE_UNAVAILABLE' if any(
            facts.get(key) is False for key in image_binding_facts)
            else 'IMAGE_UNSTATED')
    if facts.get('models') is not True and facts.get('model_compatible') is not True:
        return False, ('MODEL_UNAVAILABLE' if any(
            facts.get(key) is False for key in ('models', 'model_compatible'))
            else 'MODEL_UNSTATED')
    if facts.get('inputs') is not True and facts.get('input_compatible') is not True:
        return False, ('INPUT_UNAVAILABLE' if any(
            facts.get(key) is False for key in ('inputs', 'input_compatible'))
            else 'INPUT_UNSTATED')
    return True, ''


def step30_instrument_plan(params: Mapping[str, object] | None = None) -> Step30InstrumentPlan:
    params = params or {}
    return Step30InstrumentPlan(_step30_simulators(params), not params.get("simulators_explicit", "simulators" in params))


def _provider_route(step_id: str, params: Mapping[str, object] | None = None) -> tuple[str, tuple[str, ...]]:
    if step_id == "30":
        instruments = _step30_simulators(params)
        return instruments[0], ("opensta",) + tuple(instruments)
    spec = next(row for row in coverage_rows() if row["step_id"] == step_id)
    return str(spec["tool_id"]), tuple(spec["engine_families"])


def _step17_direct_inputs_available(params, project=None):
    """Whether the direct arm has a complete source-bound input population."""
    if params.get('step17_direct_applicable') is False:
        return False, 'caller declared the direct Step17 input population unavailable'
    required = ('step15_state', 'sta_config', 'builder_input')
    if all(params.get(key) for key in required):
        return True, 'current Step15 state, STA config and builder input are bound'
    # A source-preparation record is sufficient for the worker to derive the
    # complete builder input from the current Step15 views.
    if params.get('builder_preparation_input') and (
            params.get('step15_state') or params.get('state_in')):
        return True, 'source-owned builder preparation and predecessor are bound'
    if project is not None:
        pnr = Path(project) / 'phase3/stage3/pnr'
        if ((pnr / 'floorplan.def').is_file() and
                (pnr / 'constraint.sdc').is_file() and
                (pnr / 'builder.preparation.input.json').is_file()):
            return True, 'current Step15 floorplan, constraints and source preparation are present'
    return False, 'Step17 direct arm requires bound state/config/builder inputs'



def _adapter_routes(sid, params, boundary_available, project=None):
    """Return the complete producer routes admitted for one backend row."""
    if sid != '17':
        tool_id, families = _provider_route(sid, params)
        return ({'arm_id': 'backend_' + sid.replace('.', '_'),
                 'tool_id': tool_id, 'engine_families': families,
                 'applicability': 'applicable', 'applicability_reason': '',
                 'available': boundary_available,
                 'availability_reason': '' if boundary_available else
                     'F1_NATIVE_BOUNDARY_UNAVAILABLE'},)
    direct_ok, direct_reason = _step17_direct_inputs_available(params, project)
    ll_available = boundary_available and params.get('librelane_available', True) is not False
    # Descriptor labels cannot supply missing current-factory dependencies.
    import phase3_one_shot_runner as runner
    helpers = ('prepare_direct_pnr_builder_input', 'prepare_step17_direct_placement',
               'run_step17_direct_placement')
    dependencies = all(callable(getattr(runner, name, None)) for name in helpers)
    direct_available = boundary_available and direct_ok and dependencies and params.get(
        'direct_available', True) is not False
    return (
        {'arm_id': 'backend_17_librelane', 'tool_id': 'librelane',
         'engine_families': ('openroad',), 'applicability': 'applicable',
         'applicability_reason': 'Step17 LibreLane composite producer',
         'available': ll_available,
         'availability_reason': '' if ll_available else
             'LIBRELANE_PROVIDER_UNAVAILABLE'},
        {'arm_id': 'backend_17_openroad', 'tool_id': 'openroad',
         'engine_families': ('openroad',),
         'applicability': 'applicable' if direct_ok else 'inapplicable',
         'applicability_reason': '' if direct_ok else direct_reason,
         'available': direct_available,
         'availability_reason': '' if direct_available else
             ('CURRENT_FACTORY_DEPENDENCY_UNAVAILABLE' if direct_ok and not dependencies
              else direct_reason if direct_ok else 'DIRECT_STEP17_INPUTS_UNAVAILABLE'),
         'ultra_only': True},
    )


def _typed_parameters(spec: Mapping[str, object], source_sha: str,
                      supplied: Mapping[str, object] | None = None) -> dict:
    """Build the exact typed producer parameter envelope carried in argv."""
    params = dict(BACKEND_PARAMETER_DEFAULTS)
    explicit_simulators = bool(supplied and 'simulators' in supplied and supplied['simulators'] is not None)
    if str(spec["step_id"]) == "30" and params["simulators"] is None:
        params["simulators"] = "ngspice"
    if supplied:
        for key, value in supplied.items():
            if key not in params:
                raise em.Refusal("BACKEND_PARAMETER_UNDECLARED", str(key))
            if isinstance(value, Path):
                value = str(value)
            params[key] = value
    # A manifest is an issuer capability, not a public registration option.
    # ``execution_policy._fixed_inputs`` binds the freshly resolved manifest
    # only for the duration of one dispatch through
    # ``_backend_manifest_parameters``.  Keep registration fail-closed so a
    # direct Controller caller cannot smuggle an empty/optionalized manifest.
    params["resolved_input_manifest"] = None
    params["simulators_explicit"] = explicit_simulators
    params.update({
        "route": "librelane" if str(spec["step_id"]) != "30" else "path_spice",
        "input_contract": BACKEND_ROWS[str(spec["step_id"])]
        ["canonical_row"].get("required_inputs", ()),
        "source_sha": source_sha,
        "source_tree_sha": current_source_tree_identity(),
    })
    if str(spec["step_id"]) == "37":
        route = params["streamout_route"] or "librelane"
        if route != "librelane":
            raise em.Refusal("BACKEND_DIRECT_MAGIC_FALLBACK_REFUSED", str(route))
        params["streamout_route"] = params["route"] = route
    return params


def _producer_timeout_s(spec: Mapping[str, object], params: Mapping[str, object]) -> float:
    """Return the controller wall bound for one backend producer.

    Backend rows have very different native runtimes.  The controller bound
    is therefore a row-owned policy value when one is declared, with the
    typed parameter default retained for rows that do not need a longer
    native window.  This keeps small fixtures fast while preventing a
    stream-out producer from being killed by the generic 30-second component
    default before it can publish its measured receipt.
    """
    policy = spec.get("_portfolio_policy", spec.get("portfolio_policy", {}))
    configured = policy.get("producer_timeout_s") if isinstance(policy, Mapping) else None
    raw = params.get("timeout_s", 60) if configured is None else configured
    if isinstance(raw, bool):
        raise em.Refusal("BACKEND_PRODUCER_TIMEOUT_INVALID", repr(raw))
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise em.Refusal("BACKEND_PRODUCER_TIMEOUT_INVALID", repr(raw)) from exc
    if not math.isfinite(timeout) or not (timeout > 0):
        raise em.Refusal("BACKEND_PRODUCER_TIMEOUT_INVALID", repr(raw))
    return timeout


def _producer_ram_mb(spec: Mapping[str, object], params: Mapping[str, object]) -> int:
    """Return the row-owned address-space bound for one backend producer."""
    policy = spec.get("_portfolio_policy", spec.get("portfolio_policy", {}))
    configured = policy.get("producer_ram_mb") if isinstance(policy, Mapping) else None
    raw = 256 if configured is None else configured
    if isinstance(raw, bool) or type(raw) is not int or raw <= 0:
        raise em.Refusal("BACKEND_PRODUCER_RAM_INVALID", repr(raw))
    return raw


def _producer_cpus(spec: Mapping[str, object], params: Mapping[str, object]) -> int:
    """Return the row-owned CPU admission bound, defaulting to one."""
    policy = spec.get("_portfolio_policy", spec.get("portfolio_policy", {}))
    has_value = isinstance(policy, Mapping) and "producer_cpus" in policy
    raw = policy["producer_cpus"] if has_value else 1
    if isinstance(raw, bool) or type(raw) is not int or raw <= 0:
        raise em.Refusal("BACKEND_PRODUCER_CPUS_INVALID", repr(raw))
    return raw


def _step37_route_specs() -> tuple[dict, ...]:
    """Expose one streamout producer family; direct Magic is fallback refusal."""
    spec = next(row for row in coverage_rows() if row["step_id"] == "37")
    return ({"route": "librelane", "tool_id": spec["tool_id"],
             "engine_families": tuple(spec["engine_families"])},)


def validate_streamout_receipt(receipt: Mapping[str, object], *, route: str = "librelane",
                               measured_verdict: str | None = None) -> str:
    """Validate the actual streamout-engine receipt with measured FAIL priority."""
    if measured_verdict == "FAIL" or receipt.get("status") == "FAIL":
        return "FAIL"
    if route == "direct_magic":
        raise em.Refusal("BACKEND_DIRECT_MAGIC_FALLBACK_REFUSED",
                         "direct Magic fallback is not an independent Ultra arm")
    allowed = ("magic", "klayout") if route == "librelane" else ()
    expected_arm = "backend_37_librelane"
    if (receipt.get("schema") != "vibeic/step37-streamout-engine/1" or
            receipt.get("step_id") != "37" or receipt.get("arm_id") != expected_arm or
            receipt.get("route") != route or
            receipt.get("allowed_streamout_engines") != list(allowed) or
            receipt.get("streamout_engine") not in allowed or
            receipt.get("status") != "PASS"):
        raise em.Refusal("BACKEND_STEP37_STREAMOUT_ENGINE_MISMATCH", repr(dict(receipt)))
    return "PASS"


def _step37_validator(route: str):
    def validator(outputs: Path, binding: Mapping[str, object]) -> em.Evidence:
        evidence = validate(outputs, binding)
        if evidence.verdict != "PASS":
            return evidence
        receipt_path = Path(outputs) / "reports/phase3/step37_streamout/vibeic_receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text())
            validate_streamout_receipt(receipt, route=route)
        except (OSError, ValueError, em.Refusal) as exc:
            return em.Evidence(binding, "NOT_MEASURED", evidence.gates, evidence.outputs,
                               detail=str(exc))
        return evidence
    return validator


def _adapter(spec: Mapping[str, object], source_sha: str, objective: Mapping[str, object], *,
             path: str, available: bool,
             parameters: Mapping[str, object] | None = None,
             native_qualified: bool = False, execution_mode: str = "default") -> em.Adapter:
    source_sha = current_source_identity()
    applicability = spec["applicability"].get(path, "inapplicable: path not declared")
    applicable = applicability == "applicable"
    applicability_kind = ("applicable" if applicable else
                          "inapplicable" if applicability.startswith("inapplicable") else "unknown")
    producer = HERE / "execution_backend_worker.py"
    source_files = _source_files(spec)
    source_files.update({str(p): em.digest(p) for p in em._source_closure(source_files)})
    gates = tuple(spec["consumer_gates"])
    # The controller consumes one exact staged receipt. The worker expands the
    # canonical OR/glob clauses into concrete output members before hashing
    # them in that receipt; wildcard strings never enter Adapter.required_outputs.
    output_contract = {name: ("backend_result.json",) for name in spec["canonical_outputs"]}
    params = _typed_parameters(spec, current_source_identity(), parameters)
    # R7 has no live Step30 capability/share issuer. A label or supplied
    # feasibility boolean cannot qualify the concurrent native arm.
    missing_step30_authority = str(spec['step_id']) == '30' and execution_mode == 'ultra'
    if missing_step30_authority:
        available = False
    params['execution_mode'] = execution_mode
    validator = _step37_validator("librelane") if spec["step_id"] == "37" else validate
    # Backend producers are run in a clean arm directory.  The canonical
    # runner consumes the already-issued Phase-1/2 and physical checkpoint;
    # declaring only the row's terminal YAML inputs silently dropped that
    # checkpoint and made the producer consult an ambient project path.  Keep
    # the closure explicit and relative so the controller snapshots the exact
    # bytes without granting the worker access to its parent project.
    input_contract = _backend_input_contract(str(spec["step_id"]), spec)
    return em.Adapter(
        arm_id=str(spec["arm_id"]), tool_id="backend-worker", step_id=str(spec["step_id"]),
        source_sha=source_sha, source_files=source_files,
        tool_version="source-bound; native qualification NOT_MEASURED",
        engine_families=tuple(spec["engine_families"]),
        components=(em.Component("producer", (str(Path(sys.executable).resolve()), str(producer), "{inputs}", "{outputs}", "--step-id", str(spec["step_id"]), "--params-json", json.dumps(params, sort_keys=True)), _producer_timeout_s(spec, params)),),
        validate=validator, required_outputs=("backend_result.json",),
        objective=dict(objective), applicability=applicability_kind,
        applicability_reason="" if applicable else str(applicability), role="producer",
        # Qualification here means the current-tree source component is
        # callable.  The worker's evidence verdict still remains
        # NOT_MEASURED until native receipts and gates exist.
        qualified=native_qualified, qualification_evidence=(
            "current-tree native qualification receipt bound" if native_qualified else
            "source-bound component; native qualification NOT_MEASURED; producer site=" + str(producer)),
        available=available, availability_reason=("STEP30_CAPABILITY_OR_LIVE_SHARE_UNAVAILABLE" if missing_step30_authority
                              else "" if available else "NATIVE_EXECUTION_NOT_MEASURED"),
        cpus=_producer_cpus(spec, params), ram_mb=_producer_ram_mb(spec, params), output_contract=output_contract,
        own_no_tool_reason="One complete producer owns all row outputs and gates; checker components are complementary.",
        input_contract=input_contract,
    )


def _backend_input_contract(step_id: str, spec: Mapping[str, object]) -> tuple[object, ...]:
    """Return the frozen project closure needed by a backend producer.

    ``required_inputs`` are the row's gate contract, not the producer's full
    source population.  The native PnR/streamout producer verifies the
    current L-doc, RTL, synthesis receipt, and prior physical state; all of
    those must be copied into the isolated worker.  These are project-relative
    directory declarations, so ``execution_policy`` rejects traversal and
    symlinks before issuing the manifest.  We deliberately exclude
    ``reports/execution`` and the worker's own output tree.
    """
    row = spec.get("canonical_row", {})
    # Keep producer metadata on the row declarations.  The fixed-input issuer
    # and worker apply the producer's shared flow condition before expanding
    # these entries; flattening them to strings here would make a conditional
    # output mandatory again.
    declared = [dict(item) for item in row.get("required_inputs", ())
                if isinstance(item, Mapping) and item.get("path")]
    common = [
        "input/docs", "input/project.json", "input/step_0_5ic_answers.json", "input/submission_template",
        "phase1/generated_docs", "phase1/pdk_staging_read.json",
        "phase1/merged_docs", "phase2/stage1/rtl", "phase2/stage2", "reports/phase2/dft",
        "phase2/stage2/synth/synth_inputs.json",
        "reports/pdk_via_patch_legalization.json",
    ]
    # PnR and streamout rows consume the current physical checkpoint.  Keep
    # it separate from the generic synthesis closure so earlier rows do not
    # accidentally claim a later output as an input.
    if step_id in {"15.5ic", "17", "18", "19", "20", "21", "22",
                   "23", "24", "26", "26.5ic", "27", "28", "29", "30",
                   "31", "32", "33", "34", "37", "37.3"}:
        common.append("phase3/stage3/pnr")
    if step_id in {"22", "23", "24", "30", "31", "32", "33", "34", "37", "37.3"}:
        common.extend(("phase3/stage3/extracted", "phase3/stage3/signoff"))
    values: list[object] = []
    seen: set[str] = set()
    for value in (*declared, *common):
        key = (json.dumps(value, sort_keys=True, separators=(",", ":"))
               if isinstance(value, Mapping) else str(value))
        if key not in seen:
            seen.add(key)
            values.append(value)
    return tuple(values)


def backend_project_input_contract(project: Path, step_id: str, *,
                                   collect_missing: bool = False,
                                   execution_mode: str = "ultra") -> tuple[object, ...]:
    """Add only the current synthesis receipt namespace to a worker manifest.

    The static adapter contract cannot know the design's published synthesis
    folder at registry construction time.  Resolve that binding from the
    current project immediately before issuance instead of copying the whole
    ``phase3/librelane`` output tree (which could include this step's stale
    outputs).  Invalid declarations are left for the consumer's fail-closed
    handoff check; this helper never invents a path or receipt.
    """
    root = Path(project).resolve(strict=True)
    result: list[object] = []

    def carry_checkpoint_file(raw: str, *, allow_directory: bool = False) -> None:
        """Carry one issued checkpoint file after proving its namespace."""
        rel = Path(raw)
        if (rel.is_absolute() or not raw or ".." in rel.parts
                or rel.as_posix() != raw):
            raise ValueError(f"backend checkpoint path is unsafe: {raw!r}")
        target = root / rel
        try:
            resolved = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            if collect_missing:
                result.append(raw)
                return
            raise ValueError(f"backend checkpoint path is absent: {raw!r}") from exc
        if (target.is_symlink() or resolved != target
                or not resolved.is_relative_to(root)
                or not (resolved.is_file() or (allow_directory and resolved.is_dir()))):
            raise ValueError(f"backend checkpoint path is unsafe: {raw!r}")
        result.append(raw)

    def carry_optional_checkpoint_file(raw: str) -> None:
        """Carry an existing prior proof input without inventing absence."""
        target = root / raw
        if not target.exists():
            return
        carry_checkpoint_file(raw, allow_directory=(raw == "phase2/stage1/sim/tb"))

    def carry_optional_file(raw: str, *, require_nonempty: bool = True) -> None:
        """Carry an existing optional consumer file without changing its bytes."""
        target = root / raw
        if target.is_symlink() or not target.is_file():
            return
        # Liberty and switch globs are presence conditions whose empty files
        # do not name a usable input.  waivers.json is different: an existing
        # empty file is malformed input and must reach the consumer so its
        # schema check fails closed instead of silently taking the missing-file
        # waiver synthesis path.
        if require_nonempty and target.stat().st_size <= 0:
            return
        carry_checkpoint_file(raw)

    # These are optional consumer edges.  Their absence means the consumer's
    # own condition does not apply; it must not become an issuer prerequisite.
    carry_optional_file("phase3/librelane_switch.json")
    carry_optional_file("waivers.json", require_nonempty=False)
    liberty_root = root / "input/pdk/liberty"
    if liberty_root.is_dir() and not liberty_root.is_symlink():
        for target in sorted(liberty_root.glob("*.lib")):
            if target.is_symlink() or not target.is_file():
                continue
            carry_optional_file(str(target.relative_to(root)))

    def prelayout_subject_paths(summary_raw: str) -> tuple[str, ...]:
        """Resolve Step 10's issued subject from its producer summary.

        The summary is the existing STA consumer contract.  Do not maintain a
        second hard-coded corner list here: a producer may publish a different
        finite corner set, and the consumer binds every item by current bytes
        and digest.  This adapter only validates the path namespace and digest
        shape before carrying those exact files.
        """
        summary = root / summary_raw
        try:
            doc = json.loads(summary.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if collect_missing:
                return (summary_raw,)
            raise ValueError(f"Step-10 summary is not valid JSON: {summary_raw!r}")
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"Step-10 summary is not valid JSON: {summary_raw!r}") from exc
        subject = doc.get("subject") if isinstance(doc, Mapping) else None
        items = subject.get("items") if isinstance(subject, Mapping) else None
        if not isinstance(items, list) or not items:
            raise ValueError(f"Step-10 summary has no subject.items: {summary_raw!r}")
        result: list[str] = []
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError("Step-10 subject.items contains a non-object")
            raw = item.get("path")
            digest = item.get("sha256")
            rel = Path(raw) if isinstance(raw, str) else None
            if (rel is None or rel.is_absolute() or not raw or ".." in rel.parts
                    or rel.as_posix() != raw
                    or rel.parent != Path("phase3/stage3/sta") and
                       not rel.is_relative_to(Path("phase3/stage3/sta/prelayout_per_corner"))
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest)):
                raise ValueError(f"Step-10 subject item is unsafe: {item!r}")
            target = root / rel
            try:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError as exc:
                if collect_missing:
                    result.append(raw)
                    continue
                raise ValueError(f"Step-10 subject item is absent: {raw!r}") from exc
            if actual != digest.removeprefix("sha256:"):
                raise ValueError(f"Step-10 subject digest changed: {raw!r}")
            if raw not in result:
                result.append(raw)
        return tuple(result)

    # A backend arm with a published synthesis netlist consumes the same
    # issued proof namespace as the producer.  These files are deliberately
    # enumerated: copying the whole reports tree would admit stale outputs.
    # Their bytes remain bound by the ordinary input manifest after this
    # function returns; absence is a hard refusal rather than a silent omit.
    step7_record = root / "phase2/stage2/constraints/asic_sdc.json"
    try:
        step7 = json.loads(step7_record.read_text())
    except (OSError, ValueError, TypeError):
        step7 = None
    issued_constraint = step7.get("path") if isinstance(step7, Mapping) else None
    if (root / "phase2/stage2/synth/netlist.v").is_file() and isinstance(issued_constraint, str):
        constraint_rel = Path(issued_constraint)
        if (constraint_rel.parent != Path("phase2/stage2/constraints")
                or not constraint_rel.name.endswith(".sdc")):
            raise ValueError(f"Step-7 constraint path is unsafe: {issued_constraint!r}")
        for raw in (
            # Default producers append this run's audit journal. It is not
            # an immutable scientific input; explicit producer/Step7 bindings
            # below still carry any journal they actually cite. The isolated
            # Ultra worker retains its established transport dependency.
            *(("provenance.jsonl",) if execution_mode != "default" and step_id != "32" else ()),
            "phase3/librelane/prelayout/gates/step8_sdc_opensta.json",
            "phase2/stage2/constraints/asic_sdc.json",
            issued_constraint,
            # Default15 derives this working deck from the bound Step7/PDK/
            # pad inputs below. Its own publication is not an issued input.
            *(("phase3/stage3/pnr/constraint.sdc",)
              if step_id == "15" and execution_mode != "default" else ()),
        ):
            carry_checkpoint_file(raw)
        if step_id == "15":
            for raw in ("reports/phase2/sdc_check.json",
                        "reports/phase3/sta/pre_pnr_summary.json"):
                carry_checkpoint_file(raw)
            for raw in prelayout_subject_paths(
                    "reports/phase3/sta/pre_pnr_summary.json"):
                carry_checkpoint_file(raw)
            for raw in ("reports/lec.json", "reports/lec.rpt",
                        "reports/analog/stage_analog_compliance.json"):
                carry_checkpoint_file(raw)
        # These are prior stage-1 proof inputs consumed by the compliance
        # reader.  Carry only files already issued by the checkpoint; missing
        # proof remains the consumer's honest FAIL.
        for raw in (
            "rig_topology.json",
            "reports/phase2/cdc/netlist.json",
            "reports/phase2/cdc/netlist_front_end.json",
            "reports/phase2/cdc/netlist.yosys.log",
            "reports/phase2/cdc/crossing.json",
            "reports/phase2/cdc/async_input.json",
            "reports/phase2/cdc/reset_dep.json",
            "reports/phase2/lint/rtl_hygiene.json",
            "reports/phase2/lint/rom_init_lint.json",
            "reports/crosslayer/rewrite_equivalence_check.json",
            "reports/phase1/extraction_coverage_report.md",
            "reports/phase1/extraction_coverage_report.json",
            "plugin_output/declaration.json",
            "phase2/stage1/sim/tb",
        ):
            carry_optional_checkpoint_file(raw)

    # Step 7's ASIC SDC is an input-bound handoff.  Its record deliberately
    # stores project-relative paths separately from image/PDK/code bindings
    # (the latter are ``@`` keys and must remain external).  A backend arm
    # receives a fresh staged project, so carrying only the YAML row inputs
    # silently drops those exact files and makes the read-only Step-7 reader
    # observe a different input digest.  Carry the producer's non-``@`` paths
    # verbatim; the consumer still owns the digest and provenance verdict.
    #
    # This is intentionally data-driven: no design, PDK, or filename literal
    # is admitted, and the same safe-path checks used by the receipt mapper
    # reject absolute, traversal, non-canonical, symlinked, or missing paths.
    try:
        step7 = json.loads(step7_record.read_text())
    except (OSError, ValueError, TypeError):
        step7 = None
    bound = step7.get("inputs") if isinstance(step7, Mapping) else None
    if isinstance(bound, Mapping):
        for raw in sorted(bound):
            if not isinstance(raw, str) or raw.startswith("@"):
                continue
            rel = Path(raw)
            if (rel.is_absolute() or not raw or ".." in rel.parts
                    or rel.as_posix() != raw):
                raise ValueError(f"step-7 input path is unsafe: {raw!r}")
            target = root / rel
            try:
                resolved = target.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                if collect_missing:
                    result.append(raw)
                    continue
                raise ValueError(f"step-7 input path is absent: {raw!r}") from exc
            if (target.is_symlink() or resolved != target
                    or not resolved.is_relative_to(root)
                    or not resolved.is_file()):
                raise ValueError(f"step-7 input path is unsafe: {raw!r}")
            result.append(rel.as_posix())
        # The isolated reader needs the report transported to recompute the
        # semantic binding. Default reads it live on the same host: ephemeral
        # container/attestation metadata is not an immutable design input.
        # Explicit non-@ report paths above remain bound in either mode.
        if "@container_image" in bound and execution_mode != "default":
            raw = "reports/container_image.json"
            target = root / raw
            try:
                resolved = target.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                if collect_missing:
                    result.append(raw)
                else:
                    raise ValueError(f"step-7 input path is absent: {raw!r}") from exc
            else:
                if (target.is_symlink() or resolved != target
                        or not resolved.is_relative_to(root)
                        or not resolved.is_file()):
                    raise ValueError(f"step-7 input path is unsafe: {raw!r}")
                result.append(raw)
    # The Step-7 pad-ring record is itself a bound input.  Its
    # ``documents_scanned`` list is the producer's transitive source closure;
    # omit it and the isolated producer silently sees a smaller document set,
    # then rewrites the same hardware record with different provenance.  Carry
    # each project-relative source under the same fail-closed path rules.
    io_record = root / "reports/phase3/io_pad_chip_top.json"
    try:
        io_doc = json.loads(io_record.read_text())
    except (OSError, ValueError, TypeError):
        io_doc = None
    scanned = io_doc.get("documents_scanned") if isinstance(io_doc, Mapping) else None
    if isinstance(scanned, list):
        for raw in sorted({item for item in scanned if isinstance(item, str)}):
            rel = Path(raw)
            if (rel.is_absolute() or not raw or ".." in rel.parts
                    or rel.as_posix() != raw):
                raise ValueError(f"pad-ring input path is unsafe: {raw!r}")
            target = root / rel
            try:
                resolved = target.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                if collect_missing:
                    result.append(raw)
                    continue
                raise ValueError(f"pad-ring input path is absent: {raw!r}") from exc
            if (target.is_symlink() or resolved != target
                    or not resolved.is_relative_to(root)
                    or not resolved.is_file()):
                raise ValueError(f"pad-ring input path is unsafe: {raw!r}")
            result.append(rel.as_posix())
    if step_id == "20" and execution_mode == "default":
        cts_paths, _ = _cts_handoff_input_files(root, collect_missing=collect_missing)
        result.extend(cts_paths)
    sidecar = root / "phase2/stage2/synth/synth_inputs.json"
    try:
        doc = json.loads(sidecar.read_text())
    except (OSError, ValueError, TypeError):
        doc = {}
    binding = doc.get("librelane_synthesis") if isinstance(doc, dict) else None
    if isinstance(binding, dict):
        folder_path = None
        for key in ("folder", "mapped"):
            value = binding.get(key)
            if not isinstance(value, str):
                continue
            rel = Path(value)
            if (rel.is_absolute() or ".." in rel.parts or not rel.parts
                    or not (root / rel).resolve().is_relative_to(root)):
                raise ValueError(f"backend synthesis binding has unsafe {key}: {value}")
            target = root / rel
            if target.is_symlink():
                raise ValueError(f"backend synthesis binding uses symlinked {key}: {value}")
            if key == "folder":
                folder_path = target
            else:
                result.append(rel.as_posix())
        # The synthesis receipt's state_files can point to an earlier
        # producer in the same LibreLane chain (for example the Yosys JSON
        # header consumed by Yosys.Synthesis).  Include those exact relative
        # files, rather than reopening the entire producer directory.
        if folder_path is not None:
            try:
                receipt = json.loads((folder_path / "vibeic_receipt.json").read_text())
                state = json.loads((folder_path / "state_out.json").read_text())
            except (OSError, ValueError, TypeError):
                if collect_missing:
                    result.extend((str((folder_path / "vibeic_receipt.json").relative_to(root)),
                                   str((folder_path / "state_out.json").relative_to(root))))
                else:
                    raise ValueError("backend synthesis receipt/state is unreadable")
            else:
                # The folder is a namespace, not a recursive dependency.
                # Carry the handoff reader's fixed metadata plus the existing
                # receipt's exact output closure. Unreferenced native caches
                # and locks are not inputs to this backend invocation.
                for name in ("vibeic_receipt.json", "config.json", "state_out.json",
                             "reports/stat.json", "input_fingerprint.json", "pdk_root.json"):
                    carry_checkpoint_file(str((folder_path / name).relative_to(root)))
                hashes = receipt.get("sha256", {})
                if not isinstance(hashes, Mapping):
                    raise ValueError("backend synthesis receipt has malformed sha256")
                for raw, digest in hashes.items():
                    rel = Path(raw) if isinstance(raw, str) else None
                    if (rel is None or rel.is_absolute() or not raw or ".." in rel.parts
                            or rel.as_posix() != raw or not isinstance(digest, str)):
                        raise ValueError(f"backend synthesis receipt path is unsafe: {raw!r}")
                    target = folder_path / rel
                    carry_checkpoint_file(str(target.relative_to(root)))
                    if target.is_file() and em.digest(target) != digest:
                        raise ValueError(f"backend synthesis receipt digest mismatch: {raw}")
                result.extend(_mapped_receipt_state_files(
                    root, folder_path, receipt, state,
                    collect_missing=collect_missing))
    # A selected mapped-product child is part of this same checkpoint subject.
    # Carry its exact native receipt closure, never an ambient source project.
    child = binding.get("post_map") if isinstance(binding, dict) else None
    if child is not None:
        if not isinstance(child, dict):
            raise ValueError("backend post-map binding is malformed")
        for key in ("folder", "resolved_config", "state_in"):
            value = child.get(key)
            rel = Path(value) if isinstance(value, str) else Path("..")
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise ValueError("backend post-map path escaped project")
            target = root / rel
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                raise ValueError("backend post-map path is unsafe")
            if key != "folder":
                carry_checkpoint_file(rel.as_posix())
        child_folder = root / child["folder"]
        receipt = json.loads((child_folder / "vibeic_receipt.json").read_text())
        state = json.loads((child_folder / "state_out.json").read_text())
        carry_checkpoint_file(str((child_folder / "vibeic_receipt.json").relative_to(root)))
        for name, digest in receipt["sha256"].items():
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise ValueError("backend post-map receipt path is unsafe")
            target = child_folder / rel
            carry_checkpoint_file(str(target.relative_to(root)))
            if target.is_file() and em.digest(target) != digest:
                raise ValueError("backend post-map receipt digest mismatch")
        result.extend(_mapped_receipt_state_files(root, child_folder, receipt, state,
                                                 collect_missing=collect_missing))
        for name in (child.get("basis") or {}):
            carry_checkpoint_file(name)
    # The resolver validates the original producer state path from this
    # receipt; the resolved config is its explicit input fingerprint.
    if (root / "phase3/librelane/synthesis_resolved.json").is_file():
        result.append("phase3/librelane/synthesis_resolved.json")
    unique: list[object] = []
    seen: set[str] = set()
    for item in result:
        key = str(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


def _mapped_receipt_state_files(project: Path, folder: Path, receipt: Mapping[str, object],
                                state: Mapping[str, object], *,
                                collect_missing: bool = False,
                                original_root: Path | None = None) -> tuple[str, ...]:
    """Admit receipt state files only after lexical, containment, and digest proof.

    The producer records absolute paths from its own project namespace.  The
    worker gets a staged copy, so an old absolute path is usable only when its
    relative path is derived from the current producer folder and the staged
    bytes have the receipt's digest.  Foreign, traversal, duplicate, missing,
    symlinked, or stale entries remain hard errors.
    """
    project = Path(project).resolve(strict=True)
    folder = Path(folder).resolve(strict=True)
    librelane = (project / "phase3/librelane").resolve(strict=True)
    if not folder.is_relative_to(librelane):
        raise ValueError("native receipt producer folder is outside project")
    if original_root is None:
        netlist_value = state.get("nl") if isinstance(state, Mapping) else None
        recorded = Path(netlist_value) if isinstance(netlist_value, str) else Path()
        rel_folder = folder.relative_to(project)
        if (not isinstance(netlist_value, str) or not recorded.is_absolute()
                or ".." in recorded.parts or str(recorded) != netlist_value):
            raise ValueError("native state netlist path is not absolute")
        recorded_parent = recorded.parent
        if len(recorded_parent.parts) <= len(rel_folder.parts):
            raise ValueError("native state netlist has no project prefix")
        original_root = recorded_parent
        for _ in rel_folder.parts:
            original_root = original_root.parent
        if original_root / rel_folder != recorded_parent:
            raise ValueError("native state netlist folder is not canonical")
    inp = receipt.get("input") if isinstance(receipt, Mapping) else None
    state_files = inp.get("state_files") if isinstance(inp, Mapping) else None
    if not isinstance(state_files, Mapping):
        raise ValueError("native receipt has malformed state_files")
    seen: set[str] = set()
    mapped: list[str] = []
    config_files = inp.get("config_files", {})
    if not isinstance(config_files, Mapping):
        raise ValueError("native receipt has malformed config_files")
    for raw, digest in {**config_files, **state_files}.items():
        if (not isinstance(raw, str) or not isinstance(digest, str)
                or not raw.startswith("/") or ".." in Path(raw).parts
                or str(Path(raw)) != raw):
            raise ValueError(f"native receipt state path is unsafe: {raw}")
        source = Path(raw)
        if not source.is_relative_to(original_root):
            if raw in state_files:
                raise ValueError(f"native receipt state path is foreign: {raw}")
            # PDK/image config material is resolved by the existing receipt
            # mount reader; it is not a project file to stage here.
            continue
        relative = source.relative_to(original_root)
        target = project / relative
        try:
            resolved = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            if collect_missing:
                seen.add(relative.as_posix())
                mapped.append(relative.as_posix())
                continue
            raise ValueError(f"staged project input is absent: {relative}") from exc
        if (target.is_symlink() or resolved != target or
                not resolved.is_relative_to(project) or not resolved.is_file()):
            raise ValueError(f"native receipt state path is unsafe: {raw}")
        rel = relative.as_posix()
        if rel in seen:
            raise ValueError(f"native receipt state path maps ambiguously: {raw}")
        if em.digest(target) != digest:
            raise ValueError(f"native receipt state digest mismatch: {raw}")
        seen.add(rel)
        mapped.append(rel)
    return tuple(mapped)


def _cts_handoff_input_files(project: Path, *, collect_missing: bool = False):
    """Resolve Step 19's selected native proof into the one issued manifest.

    The handoff's source view and its named chain establish the producer's
    lexical project root. The existing receipt mapper then binds its exact
    inputs; native output digests remain the producer's recorded digests.
    No history search or recursive native-directory declaration is involved.
    """
    import librelane_contract as ll
    root = Path(project).resolve(strict=True)
    handoff_rel = "reports/phase3/librelane_cts_handoff.json"
    path = root / handoff_rel
    if not path.exists() and collect_missing:
        return (handoff_rel,), None
    document = json.loads(path.read_text())
    chain = document["chain"]
    view = document["views"]["post_cts_def"]
    source = Path(view["source"])
    if (not source.is_absolute() or ".." in source.parts
            or str(source) != view["source"] or not isinstance(chain, dict) or not chain):
        raise ValueError("CTS handoff source/chain is unsafe")
    folders = []
    origins = set()
    for step, raw in chain.items():
        rel = Path(raw)
        if (rel.is_absolute() or ".." in rel.parts or rel.as_posix() != raw
                or not rel.is_relative_to("phase3/librelane")):
            raise ValueError(f"CTS native folder is unsafe: {raw!r}")
        folders.append((step, rel))
        if tuple(source.parent.parts[-len(rel.parts):]) == rel.parts:
            origin = source.parent
            for _ in rel.parts:
                origin = origin.parent
            origins.add(origin)
    if len(origins) != 1:
        raise ValueError("CTS source is not bound to its selected native chain")
    original_root = origins.pop()
    bound = {}
    files = [handoff_rel]
    empty_ancillary_reports = set()
    semantic_views = set()

    def carry(raw, digest):
        rel = Path(raw)
        if (rel.is_absolute() or not raw or ".." in rel.parts or rel.as_posix() != raw
                or not re.fullmatch("[0-9a-f]{64}", str(digest))):
            raise ValueError(f"CTS proof path/digest is unsafe: {raw!r}")
        target = root / rel
        if not target.exists() and collect_missing:
            files.append(raw)
            return
        if (target.is_symlink() or target.resolve(strict=True) != target
                or not target.is_file() or em.digest(target) != digest):
            raise ValueError(f"CTS proof file is absent or changed: {raw}")
        if raw in bound and bound[raw] != digest:
            raise ValueError(f"CTS proof has conflicting bindings: {raw}")
        bound[raw] = digest
        files.append(raw)

    states = []
    for step, rel in folders:
        folder = root / rel
        receipt = ll.validate_step_receipt(folder, step)
        state = json.loads((folder / "state_out.json").read_text())
        files.append((rel / "vibeic_receipt.json").as_posix())
        for name, digest in receipt["sha256"].items():
            member = (rel / name).as_posix()
            carry(member, digest)
            if name.endswith('.rpt') and digest == hashlib.sha256(b'').hexdigest():
                empty_ancillary_reports.add(member)
        mapped = _mapped_receipt_state_files(root, folder, receipt, state,
                    collect_missing=collect_missing, original_root=original_root)
        files.extend(mapped)
        for name, digest in {**receipt["input"].get("config_files", {}),
                             **receipt["input"]["state_files"]}.items():
            recorded = Path(name)
            if recorded.is_relative_to(original_root):
                carry(recorded.relative_to(original_root).as_posix(), digest)
        states.append(state)
    for info in document["views"].values():
        recorded = Path(info["source"])
        if not recorded.is_absolute() or not recorded.is_relative_to(original_root):
            raise ValueError("CTS view source is outside its producer project")
        source_rel = recorded.relative_to(original_root).as_posix()
        semantic_views.update((source_rel, info['dest']))
        carry(source_rel, info["source_sha256"])
        carry(info["dest"], info["dest_sha256"])
    carry(document["measured_state"], document["measured_state_sha256"])
    for state in states:
        for recorded in ll._walk_paths({k: v for k, v in state.items() if k != "metrics"}):
            if not recorded.is_relative_to(original_root):
                raise ValueError("CTS state view is outside its producer project")
            raw = recorded.relative_to(original_root).as_posix()
            semantic_views.add(raw)
            if raw not in bound:
                raise ValueError(f"CTS state view has no producer digest: {raw}")
    # clock_plan_check reads the selected CTS transcript in addition to its
    # bound cts.rpt. It is an issued input, not a newly invented native result.
    import clock_plan_check as clock_reader
    cts_folder = root / chain[clock_reader._LL_CTS_STEP]
    transcript = cts_folder / clock_reader._LL_CTS_LOG
    if (transcript.is_symlink() or transcript.resolve(strict=True) != transcript
            or not transcript.is_file()):
        raise ValueError("CTS transcript is absent or unsafe")
    files.append(transcript.relative_to(root).as_posix())
    # A native report can legitimately contain zero diagnostic entries. Its
    # producer receipt and the issued manifest still require the exact file
    # bytes; it is not a standalone nonempty measurement declaration. Keep
    # actual handoff/state views under their existing substantive-input rule.
    return tuple(
        {'from': 'external', 'path': raw, 'required': False}
        if raw in empty_ancillary_reports and raw not in semantic_views else raw
        for raw in dict.fromkeys(files)), original_root


def register_backend_adapters(registry: em.Registry | None = None, *, source_sha: str,
                              objective: Mapping[str, object] | None = None,
                              path: str = "IC", available: bool = False,
                              route_receipt: Mapping[str, object] | None = None,
                              declaration: Mapping[str, object] | None = None,
                              parameters: Mapping[str, object] | None = None,
                              execution_mode: str = "default") -> em.Registry:
    source_sha = current_source_identity()
    registry = registry or em.Registry()
    objective = objective or {"metric": "canonical_evidence", "direction": "max"}
    rows = {row["step_id"]: row for row in coverage_rows()}
    for step_id in BACKEND_IDS:
        spec = dict(rows[step_id])
        # Conditional rows are resolved from the exact current route inputs;
        # no declaration means UNKNOWN and remains visible to the controller.
        if step_id in {"15.5ic", "26.5ic"}:
            from execution_provider_catalog import _applicability
            spec["applicability"] = _applicability(step_id, release=False,
                                                     route_receipt=dict(route_receipt or {}),
                                                     declaration=dict(declaration or {}))
        if spec["applicability"].get(path, "").startswith("inapplicable"):
            continue
        registry.register(_adapter(spec, source_sha, objective, path=path, available=available,
                                   parameters=parameters, execution_mode=execution_mode))
    return registry


def build_registry(**kwargs) -> em.Registry:
    return register_backend_adapters(**kwargs)


__all__ = ["ROWS", "BACKEND_IDS", "register_backend_adapters", "build_registry",
           "step30_instrument_plan", "_step30_simulators", "_step37_route_specs",
           "validate_streamout_receipt"]
