"""Minimal ULTRACORE seam for the reviewed 23-row backend family.

This module registers one complete source-owned producer per canonical row in
the existing :mod:`execution_modes` registry.  It contains no native runner,
lease, dispatch, or scheduler.  A registered adapter is a reachability
description; native qualification stays ``NOT_MEASURED`` until a current
producer receipt and every downstream gate are observed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
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
        raise em.Refusal("BACKEND_PRODUCER_SITE_MISSING", site)
    try:
        symbols = python_defined_symbols(path.read_text())
    except (OSError, SyntaxError) as exc:
        raise em.Refusal("BACKEND_PRODUCER_SITE_UNREADABLE", site) from exc
    if symbol not in symbols:
        raise em.Refusal("BACKEND_PRODUCER_SYMBOL_MISSING", site)
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
    summaries = {"backend_canonical", "backend_native_substance"}
    if (step not in ROWS or result.get("schema") != "vibeic/backend-result/2" or
            result.get("step_id") != step or result.get("source_sha") != binding.get("source_sha") or
            result.get("producer_verdict") != "PASS" or result.get("verdict") != "PASS" or
            result.get("missing_inputs") or result.get("missing_outputs") or
            set(result.get("gates", {})) != set(required) | summaries or
            any(result["gates"].get(name) != "PASS" for name in summaries) or
            len(required) != len(set(required)) or
            set(required) != set(ROWS[step]["portfolio_policy"]["mandatory_gate_programs"])):
        return {}
    producers = result.get("canonical_receipts")
    if (not isinstance(producers, list) or not producers or any(
            not isinstance(row, dict) or row.get("schema") != "vibeic/backend-producer-receipt/1" or
            row.get("producer") != "execution_backend_producers.produce" or
            row.get("step_id") != step or row.get("verdict") != "PASS" for row in producers)):
        return {}
    commands = []
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero", "optional_program_exit_zero"):
                    command = value.get("command") if isinstance(value, dict) else value
                    if isinstance(command, str):
                        commands.append(command)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(ROWS[step]["canonical_row"].get("gate", {}))
    if step == "20":
        commands.append("hold_area_budget_check")
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
            rows = [row for row in ledger if isinstance(row, dict) and row.get("gate") == gate]
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
    measured_fail = result.get("producer_verdict") == "FAIL" or any(
        value == "FAIL" for value in (result.get("gates") or {}).values())
    if result.get("binding") != dict(binding):
        return em.Evidence(binding, "FAIL" if measured_fail else "NOT_MEASURED", {}, {},
                           detail="BACKEND_RESULT_UNBOUND")
    # The canonical worker also reports two composition summaries. Their FAIL
    # was reduced above; they are supporting facts in the hash-bound report,
    # not additional required gate invocations.
    observed = {name: (result.get("gates") or {}).get(name, "NOT_MEASURED") for name in gates}
    status = "FAIL" if measured_fail else "NOT_MEASURED"
    if not measured_fail and result.get("producer_verdict") == "PASS" and all(
            observed.get(g) == "PASS" for g in gates) and (
                result.get("native_receipts") or result.get("canonical_receipts")):
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
        components=(em.Component("producer", (str(Path(sys.executable).resolve()), str(producer), "{inputs}", "{outputs}", "--step-id", str(spec["step_id"]), "--params-json", json.dumps(params, sort_keys=True)), 30),),
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
        cpus=1, ram_mb=256, output_contract=output_contract,
        own_no_tool_reason="One complete producer owns all row outputs and gates; checker components are complementary.",
        input_contract=input_contract,
    )


def _backend_input_contract(step_id: str, spec: Mapping[str, object]) -> tuple[str, ...]:
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
    declared = [str(item.get("path")) for item in row.get("required_inputs", ())
                if isinstance(item, Mapping) and item.get("path")]
    common = [
        "input/docs", "input/project.json", "input/step_0_5ic_answers.json", "input/submission_template",
        "phase1/generated_docs", "phase1/pdk_staging_read.json",
        "phase1/merged_docs", "phase2/stage1/rtl", "phase2/stage2", "reports/phase2/dft",
        "phase2/stage2/synth/synth_inputs.json", "phase3/librelane_switch.json",
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
    return tuple(dict.fromkeys((*declared, *common)))


def backend_project_input_contract(project: Path, step_id: str) -> tuple[str, ...]:
    """Add only the current synthesis receipt namespace to a worker manifest.

    The static adapter contract cannot know the design's published synthesis
    folder at registry construction time.  Resolve that binding from the
    current project immediately before issuance instead of copying the whole
    ``phase3/librelane`` output tree (which could include this step's stale
    outputs).  Invalid declarations are left for the consumer's fail-closed
    handoff check; this helper never invents a path or receipt.
    """
    root = Path(project).resolve(strict=True)
    result: list[str] = []
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
            if (not rel.is_absolute() and ".." not in rel.parts
                    and rel.parts and (root / rel).resolve().is_relative_to(root)):
                result.append(rel.as_posix())
                if key == "folder":
                    folder_path = root / rel
        # The synthesis receipt's state_files can point to an earlier
        # producer in the same LibreLane chain (for example the Yosys JSON
        # header consumed by Yosys.Synthesis).  Include those exact relative
        # files, rather than reopening the entire producer directory.
        if folder_path is not None:
            try:
                receipt = json.loads((folder_path / "vibeic_receipt.json").read_text())
                state_files = receipt.get("input", {}).get("state_files", {})
            except (OSError, ValueError, TypeError):
                state_files = {}
            if isinstance(state_files, dict):
                for raw in state_files:
                    path = Path(str(raw))
                    if (path.is_absolute() and path.is_relative_to(root)
                            and ".." not in path.parts):
                        result.append(path.relative_to(root).as_posix())
    # The resolver validates the original producer state path from this
    # receipt; the resolved config is its explicit input fingerprint.
    if (root / "phase3/librelane/synthesis_resolved.json").is_file():
        result.append("phase3/librelane/synthesis_resolved.json")
    return tuple(dict.fromkeys(result))


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
