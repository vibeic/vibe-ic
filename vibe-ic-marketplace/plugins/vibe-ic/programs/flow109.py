"""Source-owned 109-flow selection and existing Default dispatch bindings.

Selection is not qualification or IC acceptance.  Unimplemented rows remain
visible, and bounded native execution retains the old receipts unchanged.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sys
from typing import Mapping
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
REGISTRY = HERE.parent / "flow" / "flow109.json"
CONTEXT_ENV = "VIBEIC_FLOW109_CONTEXT"
ATTEMPT_ENV = "VIBEIC_FLOW109_ATTEMPT"


class Flow109Error(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_D25_RESULT = Path("reports/flow109/default_rows/D25.json")
_D26_RESULT = Path("reports/flow109/default_rows/D26.json")
_D24_RESULT = Path("reports/flow109/default_rows/D24.json")
_D24_NETLIST = Path("phase2/stage2/synth/post_dft_netlist.v")
_SCAN_REPORT = Path("reports/phase2/dft/scan_chain.json")
_LEC_REPORT = Path("reports/lec.json")


def _bound_project_json(project: Path, relative: Path, code: str) -> tuple[dict, dict]:
    """Read one existing project authority and bind the exact parsed bytes."""
    project = Path(project).resolve()
    path = project / relative
    try:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(project):
            raise OSError("not a current regular project file")
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise Flow109Error(code, str(relative)) from exc
    if not isinstance(value, dict):
        raise Flow109Error(code, str(relative))
    return value, {"path": relative.as_posix(),
                   "sha256": hashlib.sha256(raw).hexdigest()}


def dft_source_intent(project: Path, context: Mapping) -> dict:
    """Consume the current D01 report and its canonical declaration reader."""
    project = Path(project).resolve()
    features = context.get("features")
    if (not isinstance(features, Mapping)
            or type(features.get("requires_scan")) is not bool
            or type(features.get("requires_dft")) is not bool):
        raise Flow109Error("FLOW109_DFT_INTENT_UNRESOLVED", "requires_dft/requires_scan")
    import design_one_shot_runner as runner
    import fault_scan_chain_insert as scan
    reader = getattr(scan, "load_d09_dft_contract", None)
    if not callable(reader):
        raise Flow109Error("D09_DFT_AUTHORITY_INVALID",
                           "canonical fault_scan_chain_insert D09 reader is not landed")
    clock, reset, reset_active_low = runner.derive_dft_clock_reset(project)
    try:
        binding, problems = reader(
            project, expected_clock=clock or None, expected_reset=reset or None,
            reset_active_low=reset_active_low if reset else False)
    except (OSError, TypeError, ValueError) as exc:
        raise Flow109Error("D09_DFT_AUTHORITY_INVALID", str(exc)) from exc
    problem_codes = {
        (str(item.get("code")) if isinstance(item, Mapping)
         else str(item).split(":", 1)[0]) for item in (problems or [])}
    if binding is None or problems:
        missing = any("DFT_INTENT_MISSING" in str(item) for item in (problems or []))
        code = ("FLOW109_DFT_INTENT_MISSING"
                if missing or "D09_DFT_SPEC_MISSING" in problem_codes
                else "D09_DFT_AUTHORITY_INVALID")
        raise Flow109Error(code, "; ".join(map(str, problems or ["no binding"])))
    if (not isinstance(binding, Mapping)
            or set(binding) != {"path", "sha256", "sources", "intent"}
            or not isinstance(binding.get("path"), str) or not binding["path"]
            or not isinstance(binding.get("sha256"), str)
            or len(binding["sha256"]) != 64
            or binding.get("sources") in (None, {}, [])
            or not isinstance(binding.get("intent"), Mapping)
            or type(binding["intent"].get("requires_scan")) is not bool):
        raise Flow109Error("D09_DFT_AUTHORITY_INVALID",
                           "canonical reader returned a malformed binding")
    requires_scan = binding["intent"]["requires_scan"]
    reason = binding["intent"].get("reason")
    if not requires_scan and (not isinstance(reason, str) or not reason.strip()):
        raise Flow109Error("FLOW109_DFT_INTENT_MISSING", "non-scan decision requires a reason")
    if requires_scan != features["requires_scan"]:
        raise Flow109Error("FLOW109_DFT_INTENT_CONFLICT",
                           f"source requires_scan={requires_scan}, plan requires_scan={features['requires_scan']}")
    if requires_scan and features["requires_dft"] is not True:
        raise Flow109Error("FLOW109_DFT_INTENT_CONFLICT",
                           "requires_scan:true requires requires_dft:true")
    import _path_layout as layout
    d01_path = layout.report_path(project, 'phase1_one_shot.json').relative_to(project)
    owner, owner_ref = _bound_project_json(project, d01_path, 'FLOW109_D01_RESULT_MISSING')
    endpoint_route = 'IC' if features.get('ic') else 'IP' if features.get('ip') else None
    if endpoint_route is not None and owner.get('delivery_route') != endpoint_route:
        raise Flow109Error('FLOW109_D01_ROUTE_MISMATCH', 'current endpoint differs from D01')
    return {
        "schema": "vibeic.flow109.dft-source-intent.v1",
        "source_step": "D01", "source_position": 1,
        "consumer_step": "D22", "consumer_position": 34,
        "requires_scan": requires_scan, "authority": "canonical_d01_spec_declaration",
        "source_binding": dict(binding),
        "source_evidence": {"D01": {
            "path": binding["path"], "sha256": binding["sha256"],
            "sources": binding["sources"], "producer_result": owner_ref}},
        "realized_chain_length": "NOT_YET_REALIZED",
    }


def _accepted_row(project: Path, relative: Path, step: str) -> tuple[dict, dict]:
    body, ref = _bound_project_json(project, relative, f"FLOW109_{step}_RESULT_MISSING")
    if (body.get("step_id") != step or body.get("default_row_status") != "PASS"
            or body.get("completed") is not True):
        raise Flow109Error(f"FLOW109_{step}_RESULT_NOT_ACCEPTED", str(relative))
    return body, ref


def _current_project_ref(project: Path, value: Mapping, code: str) -> dict:
    """Verify a producer path/SHA reference against current project bytes."""
    if (not isinstance(value, Mapping) or set(value) != {"path", "sha256"}
            or not isinstance(value.get("path"), str)
            or not isinstance(value.get("sha256"), str)):
        raise Flow109Error(code, "expected exact path/sha256 reference")
    project = Path(project).resolve()
    path = project / value["path"]
    try:
        relative = path.resolve().relative_to(project).as_posix()
    except (OSError, ValueError) as exc:
        raise Flow109Error(code, str(path)) from exc
    if (path.is_symlink() or not path.is_file() or relative != value["path"]
            or _file_digest(path) != value["sha256"]):
        raise Flow109Error(code, value["path"])
    return dict(value)


def _d26_timed_arm(project: Path, arm: Mapping, intent: Mapping,
                   adopted: Mapping, mode: str) -> dict:
    """Reopen one producer-defined D26 arm and bind its real native inputs."""
    if not isinstance(arm, Mapping) or arm.get("status") != "PASS":
        raise Flow109Error("FLOW109_D26_SCAN_TIMING_NOT_MEASURED", mode)
    expected_subject = {key: adopted[key] for key in ("path", "sha256")}
    if arm.get("adopted_netlist") != expected_subject:
        raise Flow109Error("FLOW109_D26_SCAN_NETLIST_MISMATCH", mode)
    _current_project_ref(project, expected_subject, "FLOW109_D26_SCAN_NETLIST_STALE")
    constraint = arm.get("constraint")
    if not isinstance(constraint, Mapping) or constraint.get("mode") != mode:
        raise Flow109Error("FLOW109_D26_SCAN_CONSTRAINT_MISMATCH", mode)
    constraint_ref = _current_project_ref(
        project, {key: constraint.get(key) for key in ("path", "sha256")},
        "FLOW109_D26_SCAN_CONSTRAINT_STALE")
    d09 = intent["source_binding"]["intent"]
    if mode == "functional":
        selector = d09["test_mode"]["clock_select"]
        reset = d09["test_mode"]["reset"]
        expected = {
            "clock": d09["test_mode"]["clock"],
            "clock_select": selector["native"], "clock_select_value": 0,
            "scan_enable": d09["test_port_def"]["scan_enable"]["native"],
            "scan_enable_value": 0,
            "scan_input": d09["test_port_def"]["scan_in"]["native"],
            "scan_input_value": 0,
            "scan_clock": d09["test_port_def"]["tck"]["native"],
            "scan_clock_value": 0,
            "reset": reset["signal"], "reset_value": 1 - reset["active_level"],
            "d09_path": intent["source_binding"]["path"],
            "d09_sha256": intent["source_binding"]["sha256"],
        }
        if any(constraint.get(key) != value for key, value in expected.items()):
            raise Flow109Error("FLOW109_D26_MODE_VALIDATOR_MISMATCH", mode)
        _current_project_ref(project, constraint.get("base_sdc"),
                             "FLOW109_D26_SCAN_CONSTRAINT_STALE")
    deck = (Path(project) / constraint_ref["path"]).read_text(errors="replace")
    expected_clock = (d09["test_mode"]["clock"] if mode == "functional"
                      else d09["test_mode"]["scan_clock"])
    test_signal = d09["test_port_def"]["test"]["native"]
    expected_value = 0 if mode == "functional" else 1
    if (f"[get_ports {{{expected_clock}}}]" not in deck
            or f"set_case_analysis {expected_value} [get_ports {{{test_signal}}}]" not in deck):
        raise Flow109Error("FLOW109_D26_MODE_VALIDATOR_MISMATCH", mode)
    if mode == "scan":
        shift = d09["test_port_def"]["scan_enable"]["native"]
        if f"set_case_analysis 1 [get_ports {{{shift}}}]" not in deck:
            raise Flow109Error("FLOW109_D26_MODE_VALIDATOR_MISMATCH", mode)
    native = arm.get("native")
    if not isinstance(native, Mapping) or native.get("input_step") != "OpenROAD.STAPrePNR":
        raise Flow109Error("FLOW109_D26_SCAN_NATIVE_MISSING", mode)
    folder = (Path(project) / str(native.get("folder") or "")).resolve()
    try:
        folder.relative_to(Path(project).resolve())
    except ValueError as exc:
        raise Flow109Error("FLOW109_D26_SCAN_NATIVE_STALE", mode) from exc
    native_ref = _current_project_ref(
        project, native.get("receipt"), "FLOW109_D26_SCAN_NATIVE_STALE")
    if (not folder.is_dir()
            or (Path(project) / native_ref["path"]).resolve()
            != folder / "vibeic_receipt.json"):
        raise Flow109Error("FLOW109_D26_SCAN_NATIVE_STALE", mode)
    import librelane_contract
    try:
        producer = librelane_contract.validate_step_receipt(folder, "OpenROAD.STAPrePNR")
        config = json.loads((folder / "config.json").read_text())
        state_path = folder / "state_out.json"
        state = json.loads(state_path.read_text())
        state_in_path = folder / "state_in.json"
        state_in = json.loads(state_in_path.read_text())
        fingerprint = producer["input"]
        hashes = producer["sha256"]
        raw_input = state_in.get("nl")
        if (not isinstance(raw_input, str) or not raw_input
                or hashes.get("state_in.json") != _file_digest(state_in_path)
                or fingerprint.get("state") != _file_digest(state_in_path)):
            raise Flow109Error("FLOW109_D26_INPUT_NETLIST_UNBOUND", mode)
        input_path = Path(raw_input).resolve()
        input_rel = input_path.relative_to(Path(project).resolve()).as_posix()
        input_sha = fingerprint.get("state_files", {}).get(raw_input)
        _current_project_ref(project, {'path': input_rel, 'sha256': input_sha},
                             "FLOW109_D26_INPUT_NETLIST_UNBOUND")
        if Path(str(state.get('nl') or '')).resolve() != input_path:
            raise Flow109Error("FLOW109_D26_INPUT_NETLIST_UNBOUND", mode)
    except Flow109Error:
        raise
    except Exception as exc:
        raise Flow109Error("FLOW109_D26_SCAN_NATIVE_STALE", mode) from exc
    if (Path(str(config.get("PNR_SDC_FILE") or "")).resolve()
            != (Path(project) / constraint_ref["path"]).resolve()):
        raise Flow109Error("FLOW109_D26_SCAN_NATIVE_MISMATCH", mode)
    for gate_name in ("sdc_gate", "slack_gate"):
        gate_ref = arm.get(gate_name)
        current_gate = _current_project_ref(
            project, {key: gate_ref.get(key) for key in ("path", "sha256")}
            if isinstance(gate_ref, Mapping) else gate_ref,
            "FLOW109_D26_SCAN_GATE_STALE")
        gate, _ = _bound_project_json(
            project, Path(current_gate["path"]), "FLOW109_D26_SCAN_GATE_STALE")
        if (gate.get("verdict") != "PASS"
                or gate.get("state_out_sha256") != _file_digest(state_path)
                or gate_ref.get("verdict") != gate.get("verdict")
                or gate_ref.get("findings") != gate.get("findings")
                or gate_ref.get("corners") != gate.get("corners")):
            raise Flow109Error("FLOW109_D26_SCAN_GATE_FAIL", f"{mode}.{gate_name}")
        if (gate_name == "sdc_gate"
                and (gate.get("netlist_sha256") != input_sha
                     or gate.get("sdc_sha256") != constraint["sha256"])):
            raise Flow109Error("FLOW109_D26_SCAN_GATE_MISMATCH", mode)
        if not isinstance(gate.get("corners"), Mapping) or not gate["corners"]:
            raise Flow109Error("FLOW109_D26_SCAN_TIMING_NOT_MEASURED",
                               f"{mode}.{gate_name} has no corner evidence")
    return dict(arm)


def _d26_timing_modes_binding(project: Path, d26: Mapping, intent: Mapping,
                              top: str, *, report: Mapping | None = None,
                              report_ref: Mapping | None = None,
                              adopted: Mapping | None = None) -> dict:
    """Reopen the exact released D26 timing_modes_receipt and fail closed."""
    reference = d26.get("timing_modes_receipt")
    if (not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256"}
            or not isinstance(reference.get("path"), str)):
        raise Flow109Error("FLOW109_D26_TIMING_MODES_MISSING", "timing_modes_receipt")
    timing, current_ref = _bound_project_json(
        project, Path(reference["path"]), "FLOW109_D26_TIMING_MODES_MISSING")
    if dict(reference) != current_ref:
        raise Flow109Error("FLOW109_D26_TIMING_MODES_STALE", reference["path"])
    baseline = timing.get("functional_baseline")
    if (timing.get("schema") != "vibeic.flow109.d26-timing-modes.v1"
            or timing.get("step_id") != "D26" or timing.get("position") != 38
            or timing.get("top") != top or timing.get("aggregate_status") != "PASS"
            or not isinstance(baseline, Mapping) or baseline.get("status") != "PASS"
            or baseline.get("canonical_pass") is not True
            or baseline.get("current_inputs") is not True
            or baseline.get("canonical_consumer_status") != "PASS"):
        raise Flow109Error("FLOW109_D26_TIMING_MODES_INVALID", "schema/PASS baseline")
    scan = timing.get("scan")
    if not isinstance(scan, Mapping) or scan.get("d09_binding") != intent["source_binding"]:
        raise Flow109Error("FLOW109_D26_SCAN_D09_MISMATCH", "D09 binding")
    if not intent["requires_scan"]:
        if (scan.get("applicability") != "NOT_APPLICABLE"
                or scan.get("status") != "NOT_APPLICABLE"
                or timing.get("post_scan_arms") != {}
                or timing.get("modes_measured") != ["functional_baseline"]):
            raise Flow109Error("FLOW109_D26_SCAN_APPLICABILITY_INVALID", "no-scan receipt")
        return {"receipt": current_ref, "functional_baseline": dict(baseline),
                "scan": dict(scan), "modes_measured": list(timing["modes_measured"])}
    arms = timing.get("post_scan_arms")
    if (not isinstance(arms, Mapping) or "functional" not in arms
            or "post_scan_functional" not in timing.get("modes_measured", [])
            or adopted is None):
        raise Flow109Error("FLOW109_D26_SCAN_TIMING_NOT_MEASURED", "functional mode")
    d24 = scan.get("adopted_d24")
    if (not isinstance(d24, Mapping) or d24.get("path") != adopted["path"]
            or d24.get("sha256") != adopted["sha256"]
            or d24.get("current") is not True or d24.get("is_scan_inserted") is not True
            or d24.get("native_step") != "12" or d24.get("flow109_step") != "D24"
            or d24.get("position") != 36):
        raise Flow109Error("FLOW109_D26_SCAN_NETLIST_MISMATCH", "D24 adoption")
    functional = _d26_timed_arm(project, arms["functional"], intent, adopted, "functional")
    return {"receipt": current_ref, "functional_baseline": dict(baseline),
            "post_scan_arms": {"functional": functional},
            "modes_measured": ["functional_baseline", "post_scan_functional"]}


def dft_plan_reference(intent: Mapping) -> dict:
    """Bind the planned scan limits to the current D01 specification."""
    if type(intent.get("requires_scan")) is not bool:
        raise Flow109Error("FLOW109_D30_DFT_PLAN_MISSING", "scan applicability unresolved")
    if not intent["requires_scan"]:
        return {"status": "NOT_APPLICABLE", "reason": "scan is not required"}
    binding = intent.get("source_binding")
    data = binding.get("intent") if isinstance(binding, Mapping) else None
    plan = data.get("dft_plan") if isinstance(data, Mapping) else None
    if not isinstance(plan, Mapping):
        raise Flow109Error("FLOW109_D30_DFT_PLAN_MISSING", "D01 dft_plan")
    count, limit = plan.get("planned_chain_count"), plan.get("max_chain_length")
    if type(count) is not int or count < 1 or type(limit) is not int or limit < 1:
        raise Flow109Error("FLOW109_D30_DFT_PLAN_MISSING", "D01 chain count and limit must be positive integers")
    if (intent.get("source_step") != "D01" or not isinstance(binding.get("path"), str)
            or not isinstance(binding.get("sha256"), str) or len(binding["sha256"]) != 64):
        raise Flow109Error("FLOW109_D30_DFT_PLAN_UNBOUND", "D01 source identity")
    return {"status": "PASS", "producer": "D01", "path": binding["path"],
            "sha256": binding["sha256"], "planned_chain_count": count,
            "max_chain_length": limit}


def _d23_original_launch(doc: Mapping, current: Mapping) -> None:
    """Reopen the host-retained D23 launch before reusing its native output."""
    import re
    import _eda_pin
    path = Path(os.environ.get('VIBEIC_FLOW109_D23_ATTESTATION') or
                str(current.get('attestation_path', '')))
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc.get('attestation_sha256'):
            raise ValueError('original host receipt hash mismatch')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate receipt key')
                result[key] = value
            return result
        record = json.loads(raw, object_pairs_hook=unique)
        inspected = record['container_inspect']
        cid, reference = record['cid'], record['image']
        config = inspected['Config']
        original_image = next(item for item in record['image_inspect']
                              if item['Id'] == inspected['Image'])
        digest = _eda_pin.reference_digest(reference)
        listed = original_image.get('RepoDigests', [])
        manifest = (inspected.get('ImageManifestDescriptor') or {}).get('digest')
        image_bound = (bool(re.fullmatch(r'sha256:[0-9a-f]{64}', reference))
                       and reference == config['Image'] == inspected['Image']) or (
            bool(digest) and '@sha256:' in reference
            and _eda_pin.reference_digest(config['Image']) == digest
            and (manifest == digest or digest in [_eda_pin.reference_digest(x) for x in listed]))
        if (not re.fullmatch(r'[0-9a-f]{64}', str(cid))
                or cid != doc.get('cid') or inspected['Id'] != cid
                or not isinstance(config.get('Hostname'), str)
                or not config['Hostname'].startswith(cid[:12])
                or inspected['State']['Running'] is not True
                or inspected['State'].get('Paused') or inspected['State'].get('Dead')
                or reference != doc.get('image') or reference != current.get('image')
                or inspected['Image'] != doc.get('image_id')
                or inspected['Image'] != current.get('image_id') or not image_bound):
            raise ValueError('original CID, image or running state mismatch')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        raise Flow109Error('FLOW109_D23_ORIGINAL_LAUNCH_UNPROVEN', str(exc)) from exc


def d23_scan_replacement_binding(project: Path, context: Mapping, intent: Mapping) -> dict:
    """Reopen the current D23 native scan-replacement component and its list."""
    import re
    import shutil
    import librelane_contract as contract
    import dft_post_optimization_scan_survival_check as cells_gate
    import vibe_ic_one_shot_runner as runner
    project = Path(project).resolve()
    row, row_ref = _bound_project_json(project, Path('reports/flow109/default_rows/D23.json'),
                                       'FLOW109_D23_SCAN_CELLS_MISSING')
    ref = row.get('scan_cell_list')
    if (row.get('step_id') != 'D23' or row.get('native_component_status') != 'PASS'
            or row.get('default_row_status') not in ('PASS', 'NOT_MEASURED')):
        raise Flow109Error('FLOW109_D23_SCAN_CELLS_UNPROVEN', 'D23 native component')
    ref = _current_project_ref(project, ref, 'FLOW109_D23_SCAN_CELLS_STALE')
    doc, _ = _bound_project_json(project, Path(ref['path']), 'FLOW109_D23_SCAN_CELLS_MISSING')
    attempt = (project / ref['path']).parent
    root = project / 'reports/flow109/attempts'
    if (attempt.is_symlink() or attempt.parent != root or not attempt.name.startswith('window-')):
        raise Flow109Error('FLOW109_D23_SCAN_CELLS_UNPROVEN', 'foreign attempt')
    terminal, _ = _bound_project_json(project, attempt.relative_to(project) / 'result.json',
                                      'FLOW109_D23_SCAN_CELLS_UNPROVEN')
    matches = [item for item in terminal.get('components', []) if item.get('step_id') == 'D23']
    if (len(matches) != 1 or matches[0].get('scan_cell_list') != ref
            or matches[0].get('native_component_status') != 'PASS'
            or matches[0].get('context_sha256') != row.get('context_sha256')):
        raise Flow109Error('FLOW109_D23_SCAN_CELLS_UNPROVEN', 'D23 attempt binding')
    if (doc.get('schema') != 'vibeic.flow109.d23-scan-cells.v1'
            or doc.get('producer') != 'D23' or doc.get('operation') != 'OpenROAD.scan_replace'
            or doc.get('d01_intent') != intent['source_binding']
            or doc.get('dft_plan') != dft_plan_reference(intent)
            or doc.get('returncode') != 0):
        raise Flow109Error('FLOW109_D23_SCAN_CELLS_UNPROVEN', 'producer or intent identity')
    try:
        current = contract.local_image_attestation()
        _d23_original_launch(doc, current)
        if (doc.get('image_id') != current.get('image_id') or doc.get('image') != current.get('image')
                or not re.fullmatch(r'[0-9a-f]{64}', str(doc.get('cid', '')))
                or not re.fullmatch(r'[0-9a-f]{64}', str(doc.get('attestation_sha256', '')))):
            raise ValueError('image or launch identity differs')
        for key, module in (('producer_source_sha256', runner), ('comparator_source_sha256', cells_gate)):
            if doc.get(key) != _file_digest(Path(module.__file__)):
                raise ValueError(key + ' changed')
        for key, executable in (('openroad_sha256', 'openroad'), ('yosys_sha256', 'yosys')):
            path = shutil.which(executable)
            if not path or doc.get(key) != _file_digest(Path(path)):
                raise ValueError(key + ' changed')
        pdk = doc.get('pdk_sha256')
        if not isinstance(pdk, Mapping) or len(pdk) != 3:
            raise ValueError('PDK identity missing')
        for path, digest in pdk.items():
            if not isinstance(path, str) or _file_digest(Path(path)) != digest:
                raise ValueError('PDK input changed')
        mapped = _current_project_ref(project, doc.get('mapped'), 'FLOW109_D23_SCAN_CELLS_STALE')
        replaced = _current_project_ref(project, doc.get('replaced'), 'FLOW109_D23_SCAN_CELLS_STALE')
        for name in ('recipe', 'log'):
            item = _current_project_ref(project, doc.get(name), 'FLOW109_D23_SCAN_CELLS_STALE')
            if (project / item['path']).parent != attempt:
                raise ValueError(name + ' foreign attempt')
        if (project / replaced['path']).parent != attempt:
            raise ValueError('replacement foreign attempt')
        argv = doc.get('argv')
        if (not isinstance(argv, list) or len(argv) != 4 or argv[1:3] != ['-no_init', '-exit']
                or argv[0] != shutil.which('openroad')):
            raise ValueError('native argv mismatch')
        source = (project / mapped['path']).read_text()
        replaced_text = (project / replaced['path']).read_text()
        check = cells_gate.reconcile_scan_cell_list(source, replaced_text, replaced_text,
                                                    doc.get('cells'), top=doc.get('top'))
        if check.get('verdict') != 'PASS':
            raise ValueError('scan list does not match native replacement: ' + str(check))
    except (contract.Refusal, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise Flow109Error('FLOW109_D23_SCAN_CELLS_UNPROVEN', str(exc)) from exc
    return {'D23_result': row_ref, 'scan_cell_list': ref, 'mapped': mapped,
            'replaced': replaced, 'cells': doc['cells'], 'top': doc['top']}


def d24_scan_content(project: Path, context: Mapping, intent: Mapping, adopted: Mapping) -> dict:
    """Compare the current D24 subject against the bound D23 scan-cell list."""
    import dft_post_optimization_scan_survival_check as gate
    source = d23_scan_replacement_binding(project, context, intent)
    current = _current_project_ref(project, {'path': adopted.get('path'), 'sha256': adopted.get('sha256')},
                                   'FLOW109_D24_ADOPTED_NETLIST_UNBOUND')
    if current['path'] != _D24_NETLIST.as_posix():
        raise Flow109Error('FLOW109_D30_PRE_SCAN_SUBSTITUTION', current['path'])
    try:
        result = gate.reconcile_scan_cell_list(
            (Path(project) / source['mapped']['path']).read_text(),
            (Path(project) / source['replaced']['path']).read_text(),
            (Path(project) / current['path']).read_text(), source['cells'], top=source['top'])
    except (OSError, UnicodeError) as exc:
        raise Flow109Error('FLOW109_D30_SCAN_CELL_LIST_UNMEASURED', str(exc)) from exc
    if result.get('verdict') != 'PASS':
        raise Flow109Error('FLOW109_D30_SCAN_CELL_LIST_MISMATCH', str(result))
    return {'scan_cell_list': source['scan_cell_list'], 'D23_result': source['D23_result'],
            'adopted_netlist': current, 'cells': result['cells'],
            'parser_sha256': result['parser_sha256']}


def physical_d24_binding(project: Path, context: Mapping, intent: Mapping) -> dict:
    """Reopen the D24 accepted record and independently reconcile its cells."""
    d24, ref = _accepted_row(project, _D24_RESULT, 'D24')
    adopted = d24.get('adopted_netlist')
    if (not isinstance(adopted, Mapping) or adopted.get('artifact_id') != 'D24_POST_SCAN_NETLIST'):
        raise Flow109Error('FLOW109_D24_ADOPTED_NETLIST_UNBOUND', 'D24 identity')
    check = d24_scan_content(project, context, intent, adopted)
    if d24.get('scan_cell_list') != check['scan_cell_list']:
        raise Flow109Error('FLOW109_D23_SCAN_CELLS_STALE', 'D24 list binding')
    return {'D24_result': ref, 'adopted_netlist': dict(adopted), 'scan_cell_reconciliation': check}
def _preroute_chain_observation(project: Path, top: str, intent: Mapping,
                                  adopted: Mapping, lec: Mapping, timing: Mapping, *,
                                  native_proof: Mapping | None = None) -> dict:
    """Observe separately bound inputs; D30 delivery is not yet produced here.

    The current canonical handoff owner emits audit reports but no independently
    bound D30 delivered netlist. Do not substitute the upstream adopted path.
    """
    import dft_post_optimization_scan_survival_check as normalizer
    if type(intent.get('requires_scan')) is not bool:
        return {'status': 'NOT_MEASURED', 'reason': 'SCAN_APPLICABILITY_UNRESOLVED',
                'flow109_acceptance': 'NOT_MEASURED'}
    start_name = 'D24' if intent['requires_scan'] else 'D22'
    try:
        start = _current_project_ref(project, {k: adopted.get(k) for k in ('path', 'sha256')},
                                     'FLOW109_' + start_name + '_ADOPTED_NETLIST_UNBOUND')
        if start_name == 'D22':
            _accepted_row(project, Path('reports/flow109/default_rows/D22.json'), 'D22')
            import synth_handoff_netlist_check as handoff
            source = handoff.bound_handoff(project)
            if (not isinstance(source, Mapping) or source.get('verdict') != 'PASS'
                    or source.get('netlist_sha256') != start['sha256']
                    or Path(str(source.get('mapped') or '')).resolve() !=
                       (Path(project) / start['path']).resolve()):
                raise ValueError('D22 native synthesis adoption not bound')
        if native_proof is not None:
            gate = native_proof['subject']['gate_netlist']
            proof_input = {key: gate[key] for key in ('path', 'sha256')}
        else:
            gate = lec['proof_identity']['gate_netlist']
            gate_sha = gate['sha256']
            if not isinstance(gate_sha, str) or not gate_sha.startswith('sha256:'):
                raise ValueError('D25 proof netlist digest missing')
            proof_input = {'path': gate['path'], 'sha256': gate_sha[7:]}
        d25 = _current_project_ref(project, proof_input,
                                   'FLOW109_D25_PROOF_INPUT_STALE')
        if start_name == 'D24':
            native = timing['post_scan_arms']['functional']['native']
            folder = (Path(project) / native['folder']).resolve()
        else:
            import design_one_shot_runner as design
            baseline = timing['functional_baseline']
            current = design._current_phase2_consumer(project, '10', 0)
            if (not isinstance(current, Mapping)
                    or current.get('folder') != baseline.get('folder')):
                raise ValueError('D26 functional baseline consumer is not current')
            gate, _ = _bound_project_json(project,
                Path('phase3/librelane/prelayout/gates/step10_slack.json'),
                'FLOW109_D26_FUNCTIONAL_GATE_UNBOUND')
            state_out = Path(str(gate.get('source') or '')).resolve()
            if (gate.get('verdict') != 'PASS' or not gate.get('corners')
                    or not state_out.is_relative_to(Path(project).resolve())
                    or state_out.name != 'state_out.json'
                    or not state_out.is_file()
                    or _file_digest(state_out) != gate.get('state_out_sha256')):
                raise ValueError('D26 functional gate is not bound to current native state')
            folder = state_out.parent
        if not folder.is_relative_to(Path(project).resolve()):
            raise ValueError('D26 folder is outside project')
        state = json.loads((folder / 'state_in.json').read_text())
        path = Path(state['nl']).resolve()
        relative = path.relative_to(Path(project).resolve()).as_posix()
        output_state = json.loads((folder / 'state_out.json').read_text())
        if Path(str(output_state.get('nl') or '')).resolve() != path:
            raise ValueError('D26 output state differs from the actual input netlist')
        import librelane_contract
        receipt = librelane_contract.validate_step_receipt(folder, 'OpenROAD.STAPrePNR')
        fingerprint = receipt['input']
        sha = fingerprint['state_files'][state['nl']]
        if (receipt['sha256']['state_in.json'] != _file_digest(folder / 'state_in.json')
                or fingerprint['state'] != _file_digest(folder / 'state_in.json')):
            raise ValueError('D26 state input not bound')
        d26 = _current_project_ref(project, {'path': relative, 'sha256': sha},
                                   'FLOW109_D26_INPUT_NETLIST_UNBOUND')
        evidence = {}
        for point, reference in ((start_name, start), ('D25', d25), ('D26', d26)):
            result = normalizer.normalized_netlist_digest(
                (Path(project) / reference['path']).read_text(), top=top)
            if result.get('status') != 'MEASURED':
                return {'status': 'NOT_MEASURED', 'reason': result.get('reason'),
                        'point': point, 'flow109_acceptance': 'NOT_MEASURED'}
            evidence[point] = {'input': reference, **result}
        if len({(v['yosys_sha256'], v['source_sha256']) for v in evidence.values()}) != 1:
            return {'status': 'NOT_MEASURED', 'reason': 'NORMALIZER_IDENTITY_CHANGED',
                    'flow109_acceptance': 'NOT_MEASURED'}
        baseline = evidence[start_name]['normalized_sha256']
        mismatch = [name for name in ('D25', 'D26')
                    if evidence[name]['normalized_sha256'] != baseline]
        if mismatch:
            return {'status': 'FAIL', 'reason': 'PREROUTE_NETLIST_MISMATCH',
                    'mismatch': mismatch, 'points': evidence,
                    'flow109_acceptance': 'NOT_MEASURED'}
        return {'status': 'NOT_MEASURED', 'reason': 'D30_DELIVERY_ARTIFACT_UNBOUND',
                'missing': ['D30'], 'start': start_name, 'points': evidence, 'flow109_acceptance': 'NOT_MEASURED'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'status': 'NOT_MEASURED', 'reason': 'PREROUTE_INPUT_BINDING_UNPROVEN',
                'detail': str(exc), 'flow109_acceptance': 'NOT_MEASURED'}


def _complete_preroute_chain(project: Path, context: Mapping, admission: Mapping,
                             delivery_ref: Mapping, *, d30_context_sha256: str) -> dict:
    """Reopen the actual D30 delivery and compare four independently bound points."""
    import dft_post_optimization_scan_survival_check as normalizer
    import design_one_shot_runner as design
    import step_output_collector as versions
    project = Path(project).resolve()
    observed = admission.get('normalized_preroute_chain') or {}
    if observed.get('status') != 'NOT_MEASURED' or observed.get('reason') != 'D30_DELIVERY_ARTIFACT_UNBOUND':
        return dict(observed)
    try:
        ref = _current_project_ref(project, delivery_ref, 'FLOW109_D30_DELIVERY_RECEIPT_UNBOUND')
        receipt, receipt_ref = _bound_project_json(project, Path(ref['path']),
                                                    'FLOW109_D30_DELIVERY_RECEIPT_UNBOUND')
        if receipt_ref != ref:
            raise ValueError('D30 delivery receipt changed')
        attempt = (project / ref['path']).parent
        root = _attempt_root(project, create=False)
        if (attempt.parent != root or attempt.is_symlink() or not attempt.name.startswith('window-')):
            raise ValueError('D30 delivery receipt is outside its immutable attempt')
        request, _ = _bound_project_json(project, (attempt / 'request.json').relative_to(project),
                                          'FLOW109_D30_DELIVERY_REQUEST_UNBOUND')
        profile = {'features_sha256': digest(context['features']),
                   'step_profiles_sha256': digest(context['step_profiles'])}
        if (request.get('project_root_sha256') != hashlib.sha256(str(project).encode()).hexdigest()
                or request.get('context_sha256') != receipt.get('window_context_sha256')
                or 'D30' not in request.get('component_ids', [])
                or receipt.get('schema') != 'vibeic.flow109.d30-delivery.v1'
                or receipt.get('step_id') != 'D30'
                or receipt.get('context_sha256') != d30_context_sha256
                or receipt.get('profile_identity') != profile
                or receipt.get('producer_source_sha256') != _file_digest(Path(design.__file__))
                or receipt.get('flow109_source_sha256') != _file_digest(Path(__file__))):
            raise ValueError('D30 context, profile or producer identity differs')
        handoff = design._current_phase2_consumer(project, '14', 0)
        folder = receipt.get('handoff_folder')
        if not isinstance(handoff, Mapping) or not folder or handoff.get('folder') != folder:
            raise ValueError('current canonical D30 owner handoff is absent')
        expected_record = (versions._versions_root(project) / folder / 'outputs.json').resolve()
        if not expected_record.is_relative_to(project):
            raise ValueError('D30 owner handoff is outside project')
        handoff_ref = _current_project_ref(project, receipt.get('handoff_record'),
                                           'FLOW109_D30_HANDOFF_UNBOUND')
        if (project / handoff_ref['path']).resolve() != expected_record:
            raise ValueError('D30 owner handoff record differs')
        points = observed.get('points')
        start_name = 'D24' if admission.get('requires_scan') is True else 'D22'
        if (type(admission.get('requires_scan')) is not bool or not isinstance(points, Mapping)
                or set(points) != {start_name, 'D25', 'D26'}):
            raise ValueError('pre-route input evidence is incomplete')
        refs = {name: _current_project_ref(project, points[name]['input'],
                                          'FLOW109_PREROUTE_INPUT_STALE')
                for name in (start_name, 'D25', 'D26')}
        source = _current_project_ref(project, receipt.get('source_netlist'),
                                      'FLOW109_D30_DELIVERY_SOURCE_STALE')
        if source != refs[start_name]:
            raise ValueError('D30 source differs from upstream adoption')
        delivered = _current_project_ref(project, receipt.get('delivered_netlist'),
                                         'FLOW109_D30_DELIVERY_NETLIST_STALE')
        output = project / delivered['path']
        if output.parent != attempt or delivered['path'] == source['path']:
            raise ValueError('D30 delivered netlist is not an independent attempt output')
        refs['D30'] = delivered
        texts = {name: (project / item['path']).read_text() for name, item in refs.items()}
        answer = normalizer.compare_normalized_preroute_netlists(
            texts, top=admission['top'], requires_scan=admission['requires_scan'])
        if (any(_current_project_ref(project, item, 'FLOW109_PREROUTE_INPUT_STALE') != item
                for item in refs.values())
                or _current_project_ref(project, ref, 'FLOW109_D30_DELIVERY_RECEIPT_UNBOUND') != ref
                or _current_project_ref(project, handoff_ref, 'FLOW109_D30_HANDOFF_UNBOUND') != handoff_ref
                or receipt['producer_source_sha256'] != _file_digest(Path(design.__file__))
                or receipt['flow109_source_sha256'] != _file_digest(Path(__file__))):
            raise ValueError('D30 chain inputs changed during normalization')
        answer['references'] = refs
        answer['d30_delivery_receipt'] = ref
        answer['handoff_record'] = handoff_ref
        return answer
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'status': 'NOT_MEASURED', 'reason': 'D30_DELIVERY_BINDING_UNPROVEN',
                'detail': str(exc), 'flow109_acceptance': 'NOT_MEASURED'}


def dft_preroute_admission(project: Path, context: Mapping) -> dict:
    """Re-open D24/D25/D26's actual consumers before D30 native handoff."""
    project = Path(project).resolve()
    intent = dft_source_intent(project, context)
    plan_ref = dft_plan_reference(intent)
    _d25, d25_ref = _accepted_row(project, _D25_RESULT, "D25")
    _d26, d26_ref = _accepted_row(project, _D26_RESULT, "D26")
    manifest, _ = _bound_project_json(
        project, Path("input/flow109/D22.json"), "FLOW109_D30_SYNTHESIS_IDENTITY_MISSING")
    top = manifest.get("top")
    if not isinstance(top, str) or not top:
        raise Flow109Error("FLOW109_D30_SYNTHESIS_IDENTITY_MISSING", "D22 top")
    report = report_ref = d24_ref = None
    physical_default = intent["requires_scan"] and context.get("features", {}).get("physical") is True
    physical_binding = physical_d24_binding(project, context, intent) if physical_default else None
    if physical_binding:
        d24_ref = physical_binding['D24_result']
        d24, _ = _accepted_row(project, _D24_RESULT, "D24")
    elif intent["requires_scan"]:
        d24, d24_ref = _accepted_row(project, _D24_RESULT, "D24")
        report, report_ref = _bound_project_json(
            project, _SCAN_REPORT, "FLOW109_D30_SCAN_REPORT_MISSING")
        values = (report.get("internal_chain_length"),
                  report.get("boundary_chain_length"), report.get("input_flop_count"))
        if (report.get("published") is not True
                or report.get("chain_length_matches_flop_count") is not True
                or any(type(value) is not int or value < 0 for value in values)
                or values[0] == 0):
            raise Flow109Error("FLOW109_D30_CHAIN_STATISTICS_UNRESOLVED",
                               str(_SCAN_REPORT))
        import fault_scan_chain_insert as scan
        current, reason = scan.l20_binding_is_current(project, report)
        if not current:
            raise Flow109Error("FLOW109_D30_SCAN_REPORT_STALE", reason)
        if d24.get("native_scan_report") != report_ref:
            raise Flow109Error("FLOW109_D30_SCAN_REPORT_STALE", str(_SCAN_REPORT))
    import lec_gate_netlist_select as netlists
    native_proof = None
    named = ('input/flow109/D25.json', 'input/flow109/D25_source_authority.json',
             'reports/lec_eqy_execution.json')
    if any((project / name).exists() or (project / name).is_symlink() for name in named):
        # The original native consumer binds its independent execution adoption,
        # full partition census, mode, models and launch. Do not manufacture a
        # legacy proof_identity or fall back to lec_run after a native refusal.
        import flow109_metric_acceptance as metrics
        current = execution_context(resolve_plan(context['features'], context['step_profiles']),
                                    'D25', 'D25')
        accepted = metrics.accept_d25(project, current)
        if intent['requires_scan'] or accepted.get('status') != 'PASS':
            raise Flow109Error('FLOW109_D25_PROOF_NOT_ACCEPTED', accepted.get('reason', 'native scope'))
        native_proof = accepted['native_execution']
        lec, lec_ref = {}, native_proof['execution_record']
    else:
        lec, lec_ref = _bound_project_json(project, _LEC_REPORT, "FLOW109_D25_PROOF_MISSING")
        if lec.get("verdict") != "PASS" or lec.get("equivalent") is not True:
            raise Flow109Error("FLOW109_D25_PROOF_NOT_ACCEPTED", str(_LEC_REPORT))
        binding = netlists.proof_subject_binding(project, lec, top)
        if binding.get("state") != netlists.BINDING_MATCH:
            raise Flow109Error("FLOW109_D25_GATE_IDENTITY_MISMATCH", str(binding))
    consumed, note, is_scan = netlists.pnr_consumed_netlist(project, top)
    if consumed is None or not consumed.is_file() or is_scan is not intent["requires_scan"]:
        raise Flow109Error("FLOW109_D30_NETLIST_NOT_ADOPTED",
                           f"requires_scan={intent['requires_scan']}, consumer_scan={is_scan}: {note}")
    try:
        rel = consumed.resolve().relative_to(project).as_posix()
    except ValueError as exc:
        raise Flow109Error("FLOW109_D30_NETLIST_FOREIGN", str(consumed)) from exc
    adopted = {"artifact_id": ("D24_POST_SCAN_NETLIST" if is_scan
                                else "D22_MAPPED_NETLIST"),
               "path": rel, "sha256": _file_digest(consumed)}
    if (native_proof is not None and {key: adopted[key] for key in ('path', 'sha256')}
            != native_proof['subject']['gate_netlist']):
        raise Flow109Error('FLOW109_D25_GATE_IDENTITY_MISMATCH', 'native proof and delivered subject differ')
    chain = {"status": "NOT_APPLICABLE", "reason": "requires_scan is false"}
    if is_scan:
        if Path(rel) != _D24_NETLIST:
            raise Flow109Error("FLOW109_D30_PRE_SCAN_SUBSTITUTION", rel)
        if d24.get("adopted_netlist") != adopted:
            raise Flow109Error("FLOW109_D30_D24_IDENTITY_MISMATCH", rel)
        if physical_default:
            chain = {"status": "NOT_MEASURED", "reason": "physical scan stitching is owned by D36",
                     "producer_step": "D36"}
        else:
            chain = {"status": "REALIZED_NATIVE", "report": report_ref,
                     "internal_chain_length": values[0],
                     "boundary_chain_length": values[1],
                     "input_flop_count": values[2]}
    timing_modes = _d26_timing_modes_binding(
        project, _d26, intent, top, report=report, report_ref=report_ref,
        adopted=adopted)
    observed_chain = _preroute_chain_observation(project, top, intent, adopted, lec, timing_modes,
                                               native_proof=native_proof)
    if observed_chain.get('status') == 'FAIL':
        raise Flow109Error('FLOW109_PREROUTE_NETLIST_MISMATCH', str(observed_chain.get('mismatch')))
    if (observed_chain.get('status') != 'NOT_MEASURED'
            or observed_chain.get('reason') != 'D30_DELIVERY_ARTIFACT_UNBOUND'):
        raise Flow109Error('FLOW109_PREROUTE_INPUTS_UNPROVEN', str(observed_chain.get('reason')))
    return {
        "schema": "vibeic.flow109.dft-preroute-admission.v1",
        "normalized_preroute_chain": observed_chain,
        "consumer_step": "D30", "consumer_position": 42,
        "top": top, "requires_scan": intent["requires_scan"], "adopted_netlist": adopted,
        "profile_identity": {"features_sha256": digest(context["features"]),
                             "step_profiles_sha256": digest(context["step_profiles"])},
        "native_chain": chain, "dft_plan_reference": plan_ref,
        **({"scan_cell_list_reconciliation": physical_binding['scan_cell_reconciliation']}
           if physical_binding else {}),
        "functional_equivalence": lec_ref,
        "pre_route_timing": {
            "owner_step": "D26", "owner_position": 38,
            "D26_result": d26_ref,
            "timing_modes": timing_modes,
            "applicable_modes": ["functional"],
            "scope": "timing applicability; D25 functional LEC grants no timing credit"},
        "D25_result": d25_ref,
        **({"D24_result": d24_ref} if d24_ref is not None else {}),
        "identity_agreement": "D24_D25_D30_MATCH" if is_scan else "D22_D25_D30_MATCH",
        "flow109_acceptance": "NOT_MEASURED",
    }


def _d44_pre_source_binding(project: Path, baseline: Mapping,
                            pre_route: Mapping, final_record: Mapping, *,
                            physical_top: str | None = None,
                            logical_top: str | None = None,
                            physical_input: Mapping | None = None) -> dict:
    """Reopen D44's validated transform source and bind it to D30 bytes."""
    if (physical_top is None
            and final_record.get("sha256") == pre_route.get("sha256")):
        return {"mode": "UNCHANGED_D30_BYTES", **dict(pre_route)}
    transforms = baseline.get("transformations")
    receipt_ref = baseline.get("transformation_receipt")
    if (not isinstance(transforms, list) or not transforms
            or not isinstance(receipt_ref, Mapping)):
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_MISSING",
                           "changed final bytes require D44 transformation authority")
    path = receipt_ref.get("path")
    if not isinstance(path, str) or not path:
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_MISSING",
                           "D44 transformation receipt path")
    receipt, current_ref = _bound_project_json(
        project, Path(path), "FLOW109_D44_PRE_SOURCE_MISSING")
    if dict(receipt_ref) != current_ref:
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_STALE", path)
    if physical_top is not None:
        import flow109_final_lec_physical as physical
        if (receipt.get("schema") != physical.SCHEMA
                or receipt.get("producer") != "flow109_final_lec_physical"
                or receipt.get("status") != "PREPARED_NOT_EQUIVALENCE_PROVEN"
                or receipt.get("kind") != physical.KIND
                or not isinstance(physical_input, Mapping)):
            raise Flow109Error("FLOW109_D44_PHYSICAL_TRACE_MISSING", str(path))
        if receipt.get("logical_top") != logical_top:
            raise Flow109Error("FLOW109_D44_LOGICAL_TOP_MISMATCH",
                               f"D30={logical_top}, D44={receipt.get('logical_top')}")
        if receipt.get("top") != physical_top:
            raise Flow109Error("FLOW109_D44_PHYSICAL_TOP_MISMATCH",
                               f"manifest={physical_top}, receipt={receipt.get('top')}")
        input_path = Path(str(physical_input.get("path") or ""))
        if not input_path.is_absolute():
            input_path = Path(project).resolve() / input_path
        inputs = receipt.get("inputs")
        if (not isinstance(inputs, Mapping)
                or inputs.get(str(input_path.resolve())) != physical_input.get("sha256")):
            raise Flow109Error("FLOW109_D44_PHYSICAL_TRACE_MISSING",
                               str(physical_input.get("path")))
    raw = receipt.get("raw_adopted_netlist")
    if (not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str)
            or not isinstance(raw.get("sha256"), str)):
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_MISSING",
                           "D44 transformation carries no bound raw source")
    project_root = Path(project).resolve()
    declared = Path(raw["path"])
    if ".." in declared.parts:
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_FOREIGN", str(declared))
    raw_path = declared if declared.is_absolute() else project_root / declared
    try:
        raw_resolved = raw_path.resolve()
        raw_rel = raw_resolved.relative_to(project_root).as_posix()
    except (OSError, ValueError) as exc:
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_FOREIGN", str(raw_path)) from exc
    if (raw_path.is_symlink() or not raw_resolved.is_file()
            or _file_digest(raw_resolved) != raw["sha256"]):
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_STALE", str(raw.get("path")))
    pre_declared = Path(str(pre_route.get("path") or ""))
    pre_path = pre_declared if pre_declared.is_absolute() else project_root / pre_declared
    try:
        pre_resolved = pre_path.resolve()
        pre_rel = pre_resolved.relative_to(project_root).as_posix()
    except (OSError, ValueError) as exc:
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_FOREIGN", str(pre_path)) from exc
    if (pre_path.is_symlink() or not pre_resolved.is_file()
            or _file_digest(pre_resolved) != pre_route.get("sha256")):
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_STALE", str(pre_route.get("path")))
    if (raw_resolved != pre_resolved or raw["sha256"] != pre_route.get("sha256")):
        raise Flow109Error("FLOW109_D44_PRE_SOURCE_MISMATCH",
                           f"D30={pre_rel}@{pre_route.get('sha256')}, "
                           f"D44={raw_rel}@{raw['sha256']}")
    return {"mode": "D44_TRANSFORM_SOURCE", **dict(raw),
            "resolved_path": raw_rel,
            "transformation_receipt": current_ref}


def dft_final_timing_admission(project: Path, context: Mapping) -> dict:
    """Bind D50/D51 to the adopted final rewrite and its real timing views."""
    project = Path(project).resolve()
    row = context.get("resolved_row") or {}
    if row.get("id") not in {"D50", "D51"}:
        raise Flow109Error("FLOW109_DFT_FINAL_CONTEXT_MISMATCH", str(row.get("id")))
    d30, d30_ref = _accepted_row(
        project, Path("reports/flow109/default_rows/D30.json"), "D30")
    prior = d30.get("dft_preroute_admission")
    expected_profile = {"features_sha256": digest(context["features"]),
                        "step_profiles_sha256": digest(context["step_profiles"])}
    if not isinstance(prior, Mapping) or prior.get("profile_identity") != expected_profile:
        raise Flow109Error("FLOW109_D30_PROFILE_MISMATCH", str(d30_ref["path"]))
    current_pre = dft_preroute_admission(project, context)
    current_pre['normalized_preroute_chain'] = _complete_preroute_chain(
        project, context, current_pre, d30.get('d30_delivery_receipt'),
        d30_context_sha256=d30.get('context_sha256'))
    if current_pre['normalized_preroute_chain'].get('status') != 'PASS':
        raise Flow109Error("FLOW109_D30_DELIVERY_CHAIN_UNPROVEN", str(d30_ref["path"]))
    if prior != current_pre:
        raise Flow109Error("FLOW109_D30_ADOPTION_STALE", str(d30_ref["path"]))
    _d44, d44_ref = _accepted_row(
        project, Path("reports/flow109/default_rows/D44.json"), "D44")
    _d49, d49_ref = _accepted_row(
        project, Path("reports/flow109/default_rows/D49.json"), "D49")
    d50_ref = None
    if row.get("id") == "D51":
        _d50, d50_ref = _accepted_row(
            project, Path("reports/flow109/default_rows/D50.json"), "D50")
    import flow109_final_lec as final_lec
    try:
        final = final_lec.validate_common_baseline(project, d44_ref)
    except Exception as exc:
        raise Flow109Error("FLOW109_D44_FINAL_EQUIVALENCE_UNACCEPTED", str(exc)) from exc
    final_manifest, _ = _bound_project_json(
        project, Path(final_lec.INPUT), "FLOW109_D44_FINAL_NETLIST_UNBOUND")
    logical_top = current_pre["top"]
    physical_top = final_manifest.get("top")
    physical_input = None
    baseline, _ = _bound_project_json(
        project, Path(final["baseline"]["path"]), "FLOW109_D44_BASELINE_UNBOUND")
    transforms = baseline.get("transformations")
    if transforms == []:
        if physical_top != logical_top:
            raise Flow109Error("FLOW109_D44_FINAL_NETLIST_FOREIGN",
                               f"D30={logical_top}, D44={physical_top}")
    else:
        import flow109_final_lec_physical as physical
        if (not isinstance(transforms, list) or len(transforms) != 1
                or final_manifest.get("transformations") != transforms
                or not isinstance(transforms[0], Mapping)
                or set(transforms[0]) != {"kind", "input"}
                or transforms[0].get("kind") != physical.KIND
                or not isinstance(transforms[0].get("input"), Mapping)):
            raise Flow109Error("FLOW109_D44_PHYSICAL_TRACE_MISSING",
                               f"D30={logical_top}, D44={physical_top}")
        physical_input = transforms[0]["input"]
        input_path = Path(str(physical_input.get("path") or ""))
        physical_manifest, current_input = _bound_project_json(
            project, input_path, "FLOW109_D44_PHYSICAL_TRACE_MISSING")
        if dict(physical_input) != current_input or physical_manifest.get("schema") != physical.SCHEMA:
            raise Flow109Error("FLOW109_D44_PHYSICAL_TRACE_MISSING", str(input_path))
        if physical_manifest.get("logical_top") != logical_top:
            raise Flow109Error("FLOW109_D44_LOGICAL_TOP_MISMATCH",
                               f"D30={logical_top}, manifest={physical_manifest.get('logical_top')}")
        if physical_manifest.get("top") != physical_top:
            raise Flow109Error("FLOW109_D44_PHYSICAL_TOP_MISMATCH",
                               f"D44={physical_top}, manifest={physical_manifest.get('top')}")
    final_record = final.get("adopted_netlist")
    if not isinstance(final_record, Mapping):
        raise Flow109Error("FLOW109_D44_FINAL_NETLIST_UNBOUND", str(final_record))
    final_path = project / str(final_record.get("path") or "")
    if (not final_path.is_file() or final_path.is_symlink()
            or final_path.resolve().is_relative_to(project) is False
            or final_record.get("sha256") != _file_digest(final_path)):
        raise Flow109Error("FLOW109_D44_FINAL_NETLIST_UNBOUND", str(final_record))
    pre = current_pre["adopted_netlist"]
    pre_source = _d44_pre_source_binding(
        project, baseline, pre, final_record,
        physical_top=(physical_top if physical_input is not None else None),
        logical_top=logical_top, physical_input=physical_input)

    sta, sta_ref = _bound_project_json(
        project, Path("reports/phase3/sta_postpnr_signoff.json"),
        "FLOW109_D49_TIMING_AUTHORITY_MISSING")
    state_raw = sta.get("sta_state")
    state_path = Path(state_raw) if isinstance(state_raw, str) else Path()
    if not state_path.is_absolute():
        state_path = project / state_path
    if (sta.get("judgment", {}).get("verdict") != "PASS"
            or not state_path.is_file()
            or sta.get("sta_state_sha256") != _file_digest(state_path)):
        raise Flow109Error("FLOW109_D49_TIMING_AUTHORITY_STALE", str(sta_ref["path"]))
    corner = ((sta.get("judgment", {}).get("worst_setup") or {}).get("corner")
              or next(iter(sorted((sta.get("corners") or {}).keys())), None))
    if not isinstance(corner, str) or not corner:
        raise Flow109Error("FLOW109_D49_TIMING_CORNER_UNRESOLVED", str(sta_ref["path"]))
    import librelane_contract
    try:
        timing = librelane_contract.post_pnr_timing_inputs(project, state_path, corner)
    except Exception as exc:
        raise Flow109Error("FLOW109_D49_TIMING_PROVENANCE_MISMATCH", str(exc)) from exc
    if timing["sha256"]["sta_netlist"] != final_record["sha256"]:
        raise Flow109Error("FLOW109_D49_TIMING_NETLIST_MISMATCH",
                           f"D44={final_record['sha256']}, D49={timing['sha256']['sta_netlist']}")
    if physical_input is not None:
        try:
            config_rel = (state_path.resolve().parent / "config.json").relative_to(project)
        except ValueError as exc:
            raise Flow109Error("FLOW109_D49_TIMING_TOP_MISMATCH", str(state_path)) from exc
        sta_config, _ = _bound_project_json(
            project, config_rel, "FLOW109_D49_TIMING_TOP_MISMATCH")
        if (sta_config.get("meta", {}).get("step") != "OpenROAD.STAPostPNR"
                or sta_config.get("DESIGN_NAME") != physical_top):
            raise Flow109Error("FLOW109_D49_TIMING_TOP_MISMATCH",
                               f"D44={physical_top}, D49={sta_config.get('DESIGN_NAME')}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    sdfs = state.get("sdf") or {}
    if isinstance(sdfs, str):
        sdfs = {"*": sdfs}
    import fnmatch
    matched_sdf = [Path(path) for pattern, path in sdfs.items()
                   if fnmatch.fnmatch(corner, pattern)] if isinstance(sdfs, Mapping) else []
    if len(matched_sdf) != 1 or not matched_sdf[0].is_file():
        raise Flow109Error("FLOW109_D49_SDF_UNRESOLVED", corner)
    sdf_path = matched_sdf[0]
    try:
        sdf_rel = sdf_path.resolve().relative_to(project).as_posix()
    except ValueError as exc:
        raise Flow109Error("FLOW109_D49_TIMING_PROVENANCE_MISMATCH", str(sdf_path)) from exc
    return {
        "schema": "vibeic.flow109.dft-final-timing-admission.v1",
        "consumer_step": row["id"], "consumer_position": row["position"],
        "D30": d30_ref, "D44": d44_ref, "D49": d49_ref,
        **({"D50": d50_ref} if d50_ref is not None else {}),
        "pre_route_netlist": pre, "final_adopted_netlist": dict(final_record),
        "logical_top": logical_top, "physical_top": physical_top,
        "D44_pre_source": pre_source,
        "physical_transform": baseline.get("transformation_receipt"),
        "functional_equivalence_trace": {
            "D25": current_pre["functional_equivalence"],
            "D44": final.get("proof")},
        "timing": {**timing, "sdf": sdf_rel, "sdf_sha256": _file_digest(sdf_path)},
        "lec_measures_timing": False,
        "flow109_acceptance": "NOT_MEASURED",
    }


def predicate(expression: str, features: Mapping[str, bool]) -> bool:
    """Evaluate the published Boolean grammar; no Python eval or false default."""
    try:
        node = ast.parse(expression, mode="eval").body
    except (SyntaxError, TypeError) as exc:
        raise Flow109Error("FLOW109_PREDICATE_INVALID", str(expression)) from exc

    def visit(item):
        if isinstance(item, ast.Name):
            if item.id not in features or type(features[item.id]) is not bool:
                raise Flow109Error("FLOW109_FEATURE_UNRESOLVED", item.id)
            return features[item.id]
        if isinstance(item, ast.Constant) and type(item.value) is bool:
            return item.value
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.Not):
            return not visit(item.operand)
        if isinstance(item, ast.BoolOp) and isinstance(item.op, (ast.And, ast.Or)):
            # Visit all names, including ones hidden behind a false prefix.
            values = [visit(value) for value in item.values]
            return all(values) if isinstance(item.op, ast.And) else any(values)
        raise Flow109Error("FLOW109_PREDICATE_INVALID", expression)

    return visit(node)


def load_registry() -> dict:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if data.get("schema") != "vibeic.flow109.registry.v1":
        raise Flow109Error("FLOW109_REGISTRY_INVALID", "unsupported schema")
    rows = data["rows"]
    if (len({row["id"] for row in rows}) != len(rows)
            or len({row["key"] for row in rows}) != len(rows)
            or [row["position"] for row in rows] != list(range(1, len(rows) + 1))):
        raise Flow109Error("FLOW109_REGISTRY_INVALID", "duplicate IDs or reordered positions")
    native = HERE.parent / data["legacy_flow_path"]
    if _file_digest(native) != data["legacy_flow_sha256"]:
        raise Flow109Error("FLOW109_LEGACY_MAP_STALE", "canonical source changed; review the mapping")
    return data


def resolve_features(supplied: Mapping[str, bool], registry: dict) -> dict:
    if not isinstance(supplied, Mapping):
        raise Flow109Error("FLOW109_FEATURES_INVALID", "features must be an object")
    names = set(registry["predicate_names"])
    unknown = sorted(set(supplied) - names)
    invalid = sorted(str(k) for k, value in supplied.items() if type(value) is not bool)
    if unknown or invalid:
        raise Flow109Error("FLOW109_FEATURES_INVALID", f"unknown={unknown}, non_boolean={invalid}")
    definitions = registry["predicate_definitions"]
    missing = sorted(names - set(definitions) - set(supplied) - {"always"})
    if missing:
        raise Flow109Error("FLOW109_FEATURE_UNRESOLVED", ", ".join(missing))
    result = dict(supplied)
    if result.get("always", True) is not True:
        raise Flow109Error("FLOW109_FEATURES_INVALID", "always must be true")
    result["always"] = True
    pending = dict(definitions)
    while pending:
        progressed = False
        for name, expression in list(pending.items()):
            try:
                # Derived names supplied by a caller do not override definitions.
                available = {k: v for k, v in result.items() if k not in pending}
                expected = predicate(expression, available)
            except Flow109Error as exc:
                if exc.code == "FLOW109_FEATURE_UNRESOLVED":
                    continue
                raise
            if name in supplied and supplied[name] != expected:
                raise Flow109Error("FLOW109_FEATURE_CONFLICT", name)
            result[name] = expected
            del pending[name]
            progressed = True
        if not progressed:
            raise Flow109Error("FLOW109_DEFINITION_CYCLE", ", ".join(pending))
    endpoints = [name for name in registry["endpoints"] if result[name]]
    if len(endpoints) != 1:
        raise Flow109Error("FLOW109_ENDPOINT_CONFLICT", str(endpoints))
    for antecedent, consequences in registry["feature_implications"].items():
        absent = [name for name in consequences if result[antecedent] and not result[name]]
        if absent:
            raise Flow109Error("FLOW109_FEATURE_CONFLICT", f"{antecedent} requires {absent}")
    for group in registry["feature_exclusions"]:
        if all(result[name] for name in group):
            raise Flow109Error("FLOW109_FEATURE_CONFLICT", "mutually exclusive: " + ", ".join(group))
    return result


def _selected_profile(row: dict, features: dict, override: str | None) -> dict:
    choices = [p for p in row["profiles"] if p["select_when"] != "otherwise"
               and predicate(p["select_when"], features)]
    if not choices:
        choices = [p for p in row["profiles"] if p["select_when"] == "otherwise"]
    if len(choices) != 1:
        raise Flow109Error("FLOW109_PROFILE_AMBIGUOUS", row["id"])
    choice = choices[0]
    if override is not None and override != choice["id"]:
        raise Flow109Error("FLOW109_PROFILE_INAPPLICABLE", f"{row['id']}.{override}")
    return copy.deepcopy(choice)


def _tool_uses(row: dict, profile: dict, *, mode: str | None = None) -> list[dict]:
    """Use identities are source-owned purposes, not caller-selected tool names."""
    dispatch = profile.get("dispatch")
    if dispatch is None:
        return []
    purpose = f"{row['id']}.{profile['id']}"
    inventory = dispatch
    if mode is not None:
        # D14's installed SMT proof mode has no ABC/BMC invocation. Its
        # inventory is source-owned; declared runtime purpose only selects it.
        if row['id'] != 'D14' or mode not in dispatch.get('qualification_modes', {}):
            raise Flow109Error("FLOW109_QUALIFICATION_MODE_UNSUPPORTED", str(mode))
        inventory = dispatch['qualification_modes'][mode]
        purpose = inventory['purpose']
    return [{"use_id": f"flow109.{purpose}.{tool}",
             "tool_id": tool, "purpose": purpose,
             "native_step_id": dispatch["native_step_id"],
             "native_steps": inventory.get("engine_steps", {}).get(tool, profile.get("native_steps", [])),
             "executable_name": dispatch.get("engine_executables", {}).get(tool, tool),
             "qualification_required": True}
            for tool in inventory["engine_families"]]


def resolve_plan(features: Mapping[str, bool], step_profiles: Mapping[str, str] | None = None) -> dict:
    registry = load_registry()
    selected_features = resolve_features(features, registry)
    if step_profiles is not None and (not isinstance(step_profiles, Mapping)
                                     or any(not isinstance(v, str) for v in step_profiles.values())):
        raise Flow109Error("FLOW109_PROFILE_INVALID", "step_profiles must map stable IDs to profile names")
    overrides = dict(step_profiles or {})
    known = {r["id"] for r in registry["rows"]}
    if set(overrides) - known:
        raise Flow109Error("FLOW109_STEP_UNKNOWN", str(sorted(set(overrides) - known)))
    rows = []
    for spec in registry["rows"]:
        if not predicate(spec["when"], selected_features):
            if spec["id"] in overrides:
                raise Flow109Error("FLOW109_STEP_NOT_SELECTED", spec["id"])
            continue
        row = copy.deepcopy(spec)
        row["profile"] = _selected_profile(row, selected_features, overrides.get(row["id"]))
        row["selected_profile"] = row["profile"]["id"]
        row["tool_uses"] = _tool_uses(row, row["profile"])
        rows.append(row)
    selected = {r["id"] for r in rows}
    for row in rows:
        for dep in row["data_deps"]:
            required = (dep["step"] in selected if dep["when"] == "producer_selected"
                        else predicate(dep["when"], selected_features))
            if required and dep["step"] not in selected:
                raise Flow109Error("FLOW109_DEPENDENCY_NOT_SELECTED", f"{row['id']} <- {dep['step']}")
    return {"schema": "vibeic.flow109.plan.v1", "flow_id": "109",
            "status": "PLAN_RESOLVED_NOT_EXECUTED", "revision": registry["revision"],
            "registry_sha256": _file_digest(REGISTRY),
            "planner_sha256": _file_digest(Path(__file__)),
            "legacy_source_commit": registry["legacy_source_commit"],
            "legacy_flow_sha256": registry["legacy_flow_sha256"],
            "features": selected_features, "step_profiles": overrides,
            "phases": registry["phases"], "stages": registry["stages"],
            "gate_layers": registry["gate_layers"], "namespaces": registry["namespaces"],
            "rows": rows, "selected_count": len(rows),
            # Absence from the feature-selected rows is not itself a skip
            # authority.  prepare_front_door adds the two records only after
            # the canonical D09 declaration reader has validated explicit false.
            "conditional_skips": [],
            "runtime_verdict": "NOT_MEASURED", "flow109_acceptance": "NOT_MEASURED"}


def resolve_step(plan: Mapping, step_id: str) -> dict:
    row = next((r for r in plan["rows"] if r["id"] == step_id), None)
    if row is None:
        raise Flow109Error("FLOW109_STEP_NOT_SELECTED", str(step_id))
    return copy.deepcopy(row)


def _canonical_owner_dispatch(row: Mapping) -> dict | None:
    """Validate a source-owned route into an existing Default runner site."""
    dispatch = row.get("profile", {}).get("dispatch")
    if not isinstance(dispatch, Mapping) or dispatch.get("kind") != "canonical_owner_window":
        return None
    native = str(dispatch.get("native_step_id") or "")
    legacy = {str(item.get("id")) for item in row.get("legacy70", [])
              if isinstance(item, Mapping)}
    if not native or native not in legacy:
        raise Flow109Error("FLOW109_OWNER_NATIVE_MAPPING_UNKNOWN",
                           f"{row.get('id')} -> {native or '<missing>'}")
    owner = str(dispatch.get("owner_runner") or "")
    entry = str(dispatch.get("owner_entry_step") or "")
    exit_ = str(dispatch.get("owner_exit_step") or "")
    if not owner or not entry or not exit_:
        raise Flow109Error("FLOW109_OWNER_WINDOW_INVALID", str(row.get("id")))
    import step_preflight
    actual = step_preflight.runner_for_step(entry)
    # Default Steps 8, 10, 11 and 12 are retained front-door consumers whose special
    # entry branches deliberately sit outside the generic span-head table.
    if (actual is None and owner == "design_one_shot_runner"
            and (entry in ("8", "10", "11", "12")
                 or row.get('id') == 'D12' and entry == exit_ == '3')):
        actual = owner
    if actual != owner:
        raise Flow109Error("FLOW109_OWNER_MISMATCH",
                           f"{row.get('id')}: declared {owner}, actual {actual}")
    if owner not in ("phase1_one_shot_runner", "design_one_shot_runner",
                     "phase3_one_shot_runner"):
        raise Flow109Error("FLOW109_OWNER_UNSUPPORTED", owner)
    return dict(dispatch)


def source_owned_native_dispatch(row: Mapping) -> dict | None:
    """Validate the registered Default component route that owns native checks.

    This is the adapter analogue of ``canonical_owner_window``: the frozen
    source registry, not caller data, selects an existing local owner.  It does
    not claim generic tool qualification or Flow109 acceptance.
    """
    profile = row.get("profile", {})
    dispatch = profile.get("dispatch")
    analog_floorplan = (row.get("id") == "D31" and profile.get("id") == "analog_die"
                        and isinstance(dispatch, Mapping)
                        and dispatch.get("adapter") == "flow109_analog_floorplan")
    analog_fill = (row.get("id") == "D62" and profile.get("id") == "gds_only_analog"
                   and isinstance(dispatch, Mapping)
                   and dispatch.get("adapter") == "flow109_density_fill")
    analog_stream = (row.get("id") == "D60" and profile.get("id") == "analog_die"
                     and isinstance(dispatch, Mapping)
                     and dispatch.get("adapter") == "analog_hardmacro_gds_emit")
    analog_extract = (row.get("id") == "D47" and profile.get("id") == "analog_die"
                      and isinstance(dispatch, Mapping)
                      and dispatch.get("adapter") == "magic_extract_spice_emit")
    analog_final_extract = (row.get("id") == "D69" and profile.get("id") == "analog_die"
                            and isinstance(dispatch, Mapping)
                            and dispatch.get("adapter") == "flow109_final_extract")
    analog_pv = (row.get("id") == "D42" and profile.get("id") == "analog_die"
                 and isinstance(dispatch, Mapping)
                 and dispatch.get("adapter") == "analog_a6_native_pv")
    analog_antenna = (row.get("id") == "D43" and profile.get("id") == "analog_die"
                      and isinstance(dispatch, Mapping)
                      and dispatch.get("adapter") == "gds_antenna_deck_check")
    analog_pad = (row.get("id") == "D32" and profile.get("id") == "analog_die"
                  and isinstance(dispatch, Mapping)
                  and dispatch.get("adapter") == "pad_ring_gen")
    analog_ir = (row.get("id") == "D57" and profile.get("id") == "analog_die"
                 and isinstance(dispatch, Mapping)
                 and dispatch.get("adapter") == "ir_drop_budget_check")
    analog_power = (row.get("id") == "D56" and profile.get("id") == "analog_die"
                    and isinstance(dispatch, Mapping)
                    and dispatch.get("adapter") == "analog_native_em")
    analog_si = (row.get("id") == "D48" and profile.get("id") == "analog_die"
                 and isinstance(dispatch, Mapping)
                 and dispatch.get("adapter") == "si_crosstalk_check")
    analog_final = (row.get("id") == "D70" and profile.get("id") == "analog_die"
                    and isinstance(dispatch, Mapping)
                    and dispatch.get("adapter") == "flow109_final_electrical")
    analog_correlation = (row.get("id") == "D54" and profile.get("id") == "analog_die"
                          and isinstance(dispatch, Mapping)
                          and dispatch.get("adapter") == "analog_native_flow")
    analog_em = (row.get("id") == "D58" and profile.get("id") == "analog_die"
                 and isinstance(dispatch, Mapping)
                 and dispatch.get("adapter") == "em_current_density_check")
    if not isinstance(dispatch, Mapping) or (profile.get("id") not in ("default", "digital_odb")
                                             and not analog_floorplan and not analog_fill and not analog_stream and not analog_extract and not analog_final_extract and not analog_pv and not analog_antenna and not analog_pad and not analog_ir and not analog_power and not analog_em and not analog_final and not analog_si and not analog_correlation):
        return None
    native = dispatch.get("native_step_id")
    engines = dispatch.get("engine_families")
    common_invalid = (
            dispatch.get("acceptance_scope") != "existing_native_component_only"
            or not isinstance(engines, list) or not engines
            or set(dispatch.get("engine_steps", {})) != set(engines)
            or set(dispatch.get("engine_executables", {})) != set(engines))
    adapter = dispatch.get("adapter")
    if dispatch.get("admission_policy") == "source_owned_existing_native":
        if adapter == "analog_native_flow" and analog_correlation:
            invalid = (common_invalid or native != "flow109.D54"
                       or dispatch.get("producer") != "analog_native_physical.py:_resim existing A14 results"
                       or dispatch.get("consumer") != "analog_native_flow.py:_d54_correlation")
        elif adapter == "analog_native_flow":
            # The registered analog table owns both legacy A1 and stable
            # A01-A19 entries; reuse the same native admission as digital.
            from analog_native_flow import STEPS
            legacy = {str(item.get("id")) for item in row.get("legacy70", ())
                      if isinstance(item, Mapping)}
            invalid = (common_invalid or row.get("id") not in STEPS
                       or dispatch.get("operation_scope") != "native_analog_step"
                       or not (HERE / "analog_native_flow.py").is_file()
                       or native not in legacy | {"flow109." + str(row.get("id"))})
        elif adapter == "analog_hardmacro_gds_emit":
            invalid = (common_invalid or not analog_stream or native != "flow109.D60"
                       or dispatch.get("producer") != "analog_hardmacro_gds_emit.py:execute Magic native stream"
                       or dispatch.get("consumer") != "analog_hardmacro_gds_emit.py:_D60_READBACK KLayout native readback")
        elif adapter == "magic_extract_spice_emit":
            invalid = (common_invalid or not analog_extract or native != "flow109.D47"
                       or dispatch.get("producer") != "magic_extract_spice_emit.py:execute native candidate extraction"
                       or dispatch.get("consumer") != "magic_extract_spice_emit.py:_d47_audit")
        elif adapter == "flow109_final_extract" and analog_final_extract:
            invalid = (common_invalid or native != "flow109.D69"
                       or dispatch.get("producer") != "flow109_final_extract.py:execute"
                       or dispatch.get("consumer") != "flow109_final_extract.py:validate_final_parasitics"
                       or dispatch.get("component_scope") != "native_analog_final_gds_capacitance_component")
        elif adapter == "analog_a6_native_pv":
            invalid = (common_invalid or not analog_pv or native != "flow109.D42"
                       or dispatch.get("producer") != "analog_a6_native_pv.py:execute native candidate PV"
                       or dispatch.get("consumer") != "analog_a6_native_pv.py:_klayout_drc_runner/_klayout_lvs_runset_runner")
        elif adapter == "gds_antenna_deck_check":
            invalid = (common_invalid or not analog_antenna or native != "flow109.D43"
                       or dispatch.get("producer") != "gds_antenna_deck_check.py:execute native candidate antenna"
                       or dispatch.get("consumer") != "gds_antenna_deck_check.py:_bound_native_count")
        elif adapter == "pad_ring_gen":
            invalid = (common_invalid or not analog_pad or native != "flow109.D32"
                       or dispatch.get("producer") != "pad_ring_gen.py:execute existing pad ring"
                       or dispatch.get("consumer") != "pad_ring_check.py:main and native IO/net readback")
        elif adapter == "ir_drop_budget_check":
            invalid = (common_invalid or not analog_ir or native != "flow109.D57"
                       or dispatch.get("producer") != "analog_bound_measurements.py:source-bound native voltage capture"
                       or dispatch.get("consumer") != "ir_drop_budget_check.py:_d57_grade and evaluate")
        elif adapter == "em_current_density_check":
            invalid = (common_invalid or not analog_em or native != "flow109.D58"
                       or dispatch.get("producer") != "analog_native_interconnect_run.py:run native interconnect capture"
                       or dispatch.get("consumer") != "analog_native_em.py:run grade_case")
        elif adapter == "analog_native_em":
            invalid = (common_invalid or not analog_power or native != "flow109.D56"
                       or dispatch.get("producer") != "analog_native_interconnect_run.py:execute retained native capture"
                       or dispatch.get("consumer") != "analog_native_em.py:execute supply_wave_statistics")
        elif adapter == "si_crosstalk_check":
            invalid = (common_invalid or not analog_si or native != "flow109.D48"
                       or dispatch.get("producer") != "analog_bound_measurements.py:run_measurements"
                       or dispatch.get("consumer") != "si_crosstalk_check.py:_d48_consume")
        elif adapter == "flow109_final_electrical" and profile.get("id") == "analog_die":
            invalid = (common_invalid or not analog_final or native != "flow109.D70"
                       or dispatch.get("producer") != "analog_bound_measurements.py:explicit final analog mission"
                       or dispatch.get("consumer") != "flow109_final_electrical.py:validate_analog_mission")
        elif adapter == "flow109_frontend":
            identities = {
                "D15": ("flow109.D15", "xezim --simulate --no-cache --upf",
                        "flow109_frontend.py:consume_d15"),
                "D05": ("flow109.D05", "l21_to_upf_emit.py:main",
                        "flow109_frontend.py:_execute_d05"),
                "D22": ("9", "design_one_shot_runner.py:step_yosys_synth",
                        "design_one_shot_runner.py:step_yosys_synth native synthesis checks and mapped handoff"),
                "D50": ("flow109.D50", "path_delay_fault_atpg_run.py:main",
                        "path_delay_coverage_check.py:audit"),
                "D51": ("flow109.D51", "sdd_atpg_run.py:main",
                        "sdd_coverage_check.py:audit"),
            }
            expected = identities.get(row.get("id"))
            invalid = (common_invalid or expected is None or native != expected[0]
                       or dispatch.get("producer") != expected[1]
                       or dispatch.get("consumer") != expected[2])
        else:
            invalid = (common_invalid
                       or not isinstance(adapter, str)
                       or not (HERE / (adapter + ".py")).is_file()
                       or native != "flow109." + str(row.get("id")))
    elif dispatch.get("kind") == "canonical_backend_window" and adapter is None:
        # The existing backend/release catalogs are the native owner registry.
        # Flow109 only names their already-supported Default rows; it does not
        # create a second generic tool-qualification registry.
        import execution_backend_gates as backend_gates
        canonical = backend_gates.canonical_family_row(str(native))
        legacy = {str(item.get("id")) for item in row.get("legacy70", [])
                  if isinstance(item, Mapping)}
        invalid = (common_invalid or canonical is None or str(native) not in legacy
                   or dispatch.get("producer") != "execution_backend_producers.py:produce"
                   or dispatch.get("consumer") != "execution_backend_gates.py:evaluate"
                   or not isinstance(dispatch.get("producer_sites"), list)
                   or not dispatch["producer_sites"]
                   or any(not isinstance(site, str) or not site
                          for site in dispatch["producer_sites"])
                   or list(dispatch.get("native_required_outputs", ())) !=
                   list(canonical.get("required_outputs", ())))
    else:
        return None
    if invalid:
        raise Flow109Error("FLOW109_NATIVE_OWNER_INVALID", str(row.get("id")))
    return dict(dispatch)


def _selected_native_sequence(rows) -> dict | None:
    """Return the one executable mixed-owner layout, or refuse its crossing.

    The front door can run registered adapters before it enters the existing
    Phase-3 backend, but it cannot resume adapters after that backend returns.
    Keep that physical ordering explicit instead of treating arbitrary mixed
    owners as a generic scheduler.
    """
    dispatches = [source_owned_native_dispatch(row) for row in rows]
    if not dispatches or any(dispatch is None for dispatch in dispatches):
        return None
    adapters = [bool(dispatch.get("adapter")) for dispatch in dispatches]
    if not any(adapters) or all(adapters):
        return None
    backend_start = next(index for index, adapter in enumerate(adapters)
                         if not adapter)
    if (backend_start == 0 or not all(adapters[:backend_start])
            or any(adapters[backend_start:])
            or any(dispatch.get("kind") != "canonical_backend_window"
                   for dispatch in dispatches[backend_start:])):
        raise Flow109Error(
            "FLOW109_WINDOW_DISPATCH_UNSUPPORTED",
            "mixed native windows require an adapter prefix and canonical-backend suffix")
    return {
        "adapter_count": backend_start,
        "backend_entry_step": dispatches[backend_start]["native_step_id"],
        "backend_exit_step": dispatches[-1]["native_step_id"],
    }


def source_owned_native_admission(context: Mapping) -> dict | None:
    """Record engineering-native ownership without asserting qualification."""
    # Default runs the registered tool owner. Retained qualification metadata
    # in a shared manifest does not turn a chip run into tool qualification.
    if context.get("schema") == "vibeic.flow109.execution-window.v1":
        if context.get("dispatch_kind") not in (
                "canonical_backend_window", "selected_native_sequence"):
            return None
        dispatches = [source_owned_native_dispatch(row)
                      for row in context.get("resolved_rows", ())]
        if not dispatches or any(dispatch is None for dispatch in dispatches):
            return None
        native_step = [dispatch["native_step_id"] for dispatch in dispatches]
        scope = {dispatch["acceptance_scope"] for dispatch in dispatches}
        if len(scope) != 1:
            raise Flow109Error("FLOW109_NATIVE_OWNER_INVALID", "mixed acceptance scope")
    else:
        dispatch = source_owned_native_dispatch(context.get("resolved_row", {}))
        if dispatch is None:
            return None
        native_step = dispatch["native_step_id"]
        scope = {dispatch["acceptance_scope"]}
    return {
        "status": "NOT_APPLICABLE",
        "reason": "SOURCE_OWNED_EXISTING_NATIVE_COMPONENT",
        "admitted": True,
        "qualification_status": "NOT_CLAIMED",
        "acceptance_scope": next(iter(scope)),
        "native_step_id": native_step,
        "context_sha256": context.get("context_sha256"),
        "native_started": False,
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
    }


def resolve_execution_window(plan: Mapping, entry: str | None, exit_: str | None) -> dict:
    """Resolve an inclusive selected-row window onto existing component owners.

    This is deliberately not a 109 acceptance scheduler. Every selected row
    must already name a dispatch owner; a gap refuses the complete request
    before a neighbouring legacy span can silently cover it.
    """
    if not entry or not exit_:
        raise Flow109Error("FLOW109_WINDOW_REQUIRED", "explicit entry and exit rows are required")
    ids = [row["id"] for row in plan["rows"]]
    if entry not in ids:
        raise Flow109Error("FLOW109_STEP_NOT_SELECTED", str(entry))
    if exit_ not in ids:
        raise Flow109Error("FLOW109_STEP_NOT_SELECTED", str(exit_))
    first, last = ids.index(entry), ids.index(exit_)
    if first > last:
        raise Flow109Error("FLOW109_WINDOW_REVERSED", f"{entry} follows {exit_}")
    rows = [copy.deepcopy(row) for row in plan["rows"][first:last + 1]]
    missing = [f"{row['id']}.{row['selected_profile']}" for row in rows
               if not row["profile"].get("dispatch")]
    if missing:
        raise Flow109Error("FLOW109_PRODUCER_UNIMPLEMENTED", ", ".join(missing))
    if len(rows) == 1:
        dispatch = rows[0]["profile"]["dispatch"]
        _canonical_owner_dispatch(rows[0])
        return {"requested_step": entry, "resolved_row": rows[0],
                "native_step_id": dispatch["native_step_id"]}

    dispatches = [row["profile"]["dispatch"] for row in rows]
    adapters = [bool(dispatch.get("adapter")) for dispatch in dispatches]
    if all(adapters):
        kind = "ordered_adapters"
    elif not any(adapters) and all(dispatch.get("kind") == "canonical_backend_window"
                                   for dispatch in dispatches):
        kind = "canonical_backend_window"
    elif not any(adapters) and all(dispatch.get("kind") == "canonical_owner_window"
                                   for dispatch in dispatches):
        owners = [_canonical_owner_dispatch(row)["owner_runner"] for row in rows]
        if len(set(owners)) != 1:
            raise Flow109Error("FLOW109_WINDOW_OWNER_CROSSING_UNSUPPORTED",
                               " -> ".join(owners))
        kind = "canonical_owner_window"
    elif _selected_native_sequence(rows) is not None:
        kind = "selected_native_sequence"
    else:
        raise Flow109Error(
            "FLOW109_WINDOW_DISPATCH_UNSUPPORTED",
            "a window may not cross adapter and canonical-backend ownership")
    native_entry = (dispatches[0].get("owner_entry_step") if kind == "canonical_owner_window"
                    else dispatches[0]["native_step_id"])
    native_exit = (dispatches[-1].get("owner_exit_step") if kind == "canonical_owner_window"
                   else dispatches[-1]["native_step_id"])
    if kind == "canonical_owner_window":
        # A selected producer may own checks beyond the last selected row
        # (RTL authoring owns 1..4). Never truncate its native closure when a
        # later semantic row, such as lint, has an earlier native endpoint.
        from task_nature_route import flow_step_ids
        order = {step: index for index, step in enumerate(flow_step_ids())}
        native_exit = max((d["owner_exit_step"] for d in dispatches),
                          key=lambda step: order[step])
    return {"requested_entry": entry, "requested_exit": exit_,
            "resolved_rows": rows, "dispatch_kind": kind,
            "native_entry_step": native_entry,
            "native_exit_step": native_exit}


_CONTEXT_KEYS = {"schema", "registry_sha256", "planner_sha256", "legacy_flow_sha256",
                 "features", "step_profiles", "requested_step", "resolved_row",
                 "native_step_id", "runtime_tool_uses", "qualification_registry", "context_sha256"}
_WINDOW_CONTEXT_KEYS = {
    "schema", "registry_sha256", "planner_sha256", "legacy_flow_sha256",
    "features", "step_profiles", "requested_entry", "requested_exit",
    "resolved_rows", "dispatch_kind", "native_entry_step", "native_exit_step",
    "runtime_tool_uses", "qualification_registry", "context_sha256",
}


def execution_context(plan: dict, entry: str, exit_: str, *,
                      runtime_tool_uses=None, qualification_registry=None, rtl_scope=None) -> dict:
    window = resolve_execution_window(plan, entry, exit_)
    window = copy.deepcopy(window)
    for row in window.get('resolved_rows', [window.get('resolved_row')]):
        if not row or row['id'] != 'D14' or not isinstance(runtime_tool_uses, list):
            continue
        declared = [u for u in runtime_tool_uses if isinstance(u, dict)
                    and str(u.get('use_id', '')).startswith('flow109.D14.')]
        purposes = {str(u['semantics'].get('purpose')) for u in declared
                    if isinstance(u.get('semantics'), Mapping)}
        modes = row['profile']['dispatch'].get('qualification_modes', {})
        for mode, spec in modes.items():
            if purposes == {spec['purpose']}:
                row['tool_uses'] = _tool_uses(row, row['profile'], mode=mode)
    if "requested_step" in window and isinstance(runtime_tool_uses, list):
        # A manifest may serve several rows. Exclude only uses owned by other
        # selected source rows; unknown/malformed and duplicate current uses
        # must reach strict admission unchanged rather than disappear here.
        other_ids = {use["use_id"] for row in plan["rows"]
                     if row["id"] != window["requested_step"]
                     for use in row["tool_uses"]}
        runtime_tool_uses = [item for item in runtime_tool_uses
                            if not (isinstance(item, dict)
                                    and isinstance(item.get("use_id"), str)
                                    and item["use_id"] in other_ids)]
    schema = ("vibeic.flow109.execution-context.v1" if "requested_step" in window
              else "vibeic.flow109.execution-window.v1")
    context = {"schema": schema,
               **{key: plan[key] for key in ("registry_sha256", "planner_sha256", "legacy_flow_sha256",
                                             "features", "step_profiles")},
               **window, "runtime_tool_uses": copy.deepcopy(runtime_tool_uses),
               "qualification_registry": qualification_registry}
    if rtl_scope is not None:
        context["rtl_scope"] = copy.deepcopy(rtl_scope)
    context["context_sha256"] = digest(context)
    return context


def validate_execution_context(context: Mapping) -> dict:
    if not isinstance(context, Mapping):
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "expected object")
    keys = (_WINDOW_CONTEXT_KEYS
            if context.get("schema") == "vibeic.flow109.execution-window.v1"
            else _CONTEXT_KEYS)
    if "rtl_scope" in context:
        keys = keys | {"rtl_scope"}
    if set(context) != keys:
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "unexpected or missing fields")
    if context["schema"] not in ("vibeic.flow109.execution-context.v1",
                                 "vibeic.flow109.execution-window.v1"):
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "schema")
    payload = {key: value for key, value in context.items() if key != "context_sha256"}
    if context["context_sha256"] != digest(payload):
        raise Flow109Error("FLOW109_CONTEXT_STALE", "request identity changed")
    current = resolve_plan(context["features"], context["step_profiles"])
    entry = context.get("requested_step", context.get("requested_entry"))
    exit_ = context.get("requested_step", context.get("requested_exit"))
    expected = execution_context(current, entry, exit_,
                                 runtime_tool_uses=context["runtime_tool_uses"],
                                 qualification_registry=context["qualification_registry"],
                                 rtl_scope=context.get("rtl_scope"))
    if dict(context) != expected:
        raise Flow109Error("FLOW109_CONTEXT_STALE", "source registry, producer or selection changed")
    return expected


def component_context(context: Mapping, *, native_step_id: str | None = None,
                      requested_step: str | None = None) -> dict:
    """Return the current one-row contract selected from a validated window."""
    context = validate_execution_context(context)
    if context["schema"] == "vibeic.flow109.execution-context.v1":
        return context
    matches = [row for row in context["resolved_rows"]
               if (requested_step is not None and row["id"] == requested_step)
               or (requested_step is None and native_step_id is not None
                   and str(row["profile"]["dispatch"]["native_step_id"])
                   == str(native_step_id))]
    if len(matches) != 1:
        raise Flow109Error("FLOW109_NATIVE_STEP_MISMATCH",
                           str(requested_step if requested_step is not None else native_step_id))
    row = matches[0]
    expected_ids = {item["use_id"] for item in row["tool_uses"]}
    runtime = context.get("runtime_tool_uses")
    selected = ([copy.deepcopy(item) for item in runtime
                 if isinstance(item, dict) and item.get("use_id") in expected_ids]
                if isinstance(runtime, list) else runtime)
    plan = resolve_plan(context["features"], context["step_profiles"])
    return execution_context(
        plan, row["id"], row["id"], runtime_tool_uses=selected,
        qualification_registry=context["qualification_registry"],
        rtl_scope=context.get("rtl_scope"))


def _rtl_scope_inputs(project: Path) -> list[dict]:
    """Bind the ordinary original request and supplied RTL without changing it."""
    from _path_layout import original_input_sources

    def supplied_files(relative):
        root = project / relative
        entries = [root, *root.rglob("*")] if root.exists() or root.is_symlink() else []
        if any(path.is_symlink() for path in [*root.parents, *entries]):
            raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", "linked supplied source")
        return {path for path in entries if path.is_file()}

    prompt = project / "input/phase1_prompt.md"
    try:
        if prompt.exists() or prompt.is_symlink():
            files = set(original_input_sources(project))
        else:
            # Both raw docs and canonical input_doc are normal front doors.
            # Neither requires synthesizing a prompt that the owner never gave.
            files = supplied_files("input/docs") or supplied_files("phase1/input_doc")
        original_hashes = {_file_digest(path) for path in files}
        for relative in ("input/docs", "input/rtl", "input/vendor_rtl"):
            # The ordinary front door materializes byte-identical source copies.
            # These add no authority; new or changed content still changes this set.
            files.update(path for path in supplied_files(relative)
                         if path in files or _file_digest(path) not in original_hashes)
        if not files or not any(path.read_bytes().strip() for path in files):
            raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", "no nonempty original design input")
        return [{"path": path.relative_to(project).as_posix(), "sha256": _file_digest(path)}
                for path in sorted(files)]
    except (OSError, ValueError) as exc:
        if isinstance(exc, Flow109Error):
            raise
        raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", str(exc)) from exc


def _rtl_scope_window(context: Mapping) -> None:
    """RTL applicability never grants physical or generic qualification credit."""
    features = context["features"]
    if (features["physical"] or features["technology_specific"]
            or features["has_analog"] or not features["has_digital"]
            or context.get("qualification_registry") is not None
            or context.get("runtime_tool_uses") is not None):
        raise Flow109Error("FLOW109_RTL_SCOPE_CONFLICT", "physical or qualified request")
    from task_nature_route import EVIDENCE_EXIT
    last = int(EVIDENCE_EXIT["proof"]["exit_step"])
    for row in context.get("resolved_rows") or [context["resolved_row"]]:
        dispatch = row["profile"].get("dispatch") or {}
        native = str(dispatch.get("native_step_id"))
        owner = dispatch.get("owner_runner")
        if not (dispatch.get("kind") == "canonical_owner_window"
                and ((native == "D1" and owner == "phase1_one_shot_runner")
                     or (owner == "design_one_shot_runner"
                         and (native == "P0" or native.isdigit() and 1 <= int(native) <= last)))):
            raise Flow109Error("FLOW109_RTL_SCOPE_CONFLICT", "window is outside RTL owners")


def _rtl_source_inputs(project: Path) -> list[dict]:
    """The existing RTL scope's source-bound delivery check, shared at selection."""
    inputs = _rtl_scope_inputs(project)
    from task_nature_route import prompt_delivery_requirements, resolve_prompt_delivery_target
    for source in inputs:
        text = (project / source["path"]).read_text(encoding="utf-8", errors="replace")
        demand = prompt_delivery_requirements(text)
        resolved = resolve_prompt_delivery_target(demand, "rtl")
        if not resolved["ok"] or demand["route_family"] is not None:
            raise Flow109Error("FLOW109_RTL_SCOPE_CONFLICT",
                               "original source requests physical delivery: " + source["path"])
    return inputs


def resolve_task_manifest(project: Path, entry_step: str | None, exit_step: str | None,
                          delivery_target: str | None = None,
                          delivery_route: str | None = None) -> Path | None:
    """Select the shipped RTL profile for a bounded, source-compatible task.

    This is applicability, not acceptance. Explicit manifests are never changed;
    unresolved/physical scope retains the normal BLOCKING admission refusal.
    No feature is guessed from a task name, dataset or absent Boolean.
    """
    project = project.resolve()
    path = project / "input/flow109-manifest.json"
    if (not entry_step or not exit_step
            or delivery_target not in (None, "rtl")
            or delivery_route not in (None, "ip")):
        return None
    profiles = [row for row in load_registry()["reference_profiles"]
                if row["name"] == "RTL-only" and row["endpoint"] == "rtl_only"]
    if len(profiles) != 1:
        if path.exists() or path.is_symlink():
            # Existing explicit input has its own ordinary feature validation;
            # default availability cannot veto it or cause it to be replaced.
            return None
        raise Flow109Error("FLOW109_PROFILE_INVALID", "no unique shipped RTL-only profile")
    manifest = {"features": dict(profiles[0]["features"])}
    existing = path.exists() or path.is_symlink()
    if existing:
        try:
            supplied, _ = _bound_project_json(project, Path("input/flow109-manifest.json"),
                                             "FLOW109_MANIFEST_INVALID")
        except Flow109Error:
            return None
        if supplied != manifest:
            return None
    plan = resolve_plan(manifest["features"])
    from task_nature_route import flow109_product_window, is_rtl_only_evidence
    try:
        first, last = flow109_product_window(manifest, entry_step, exit_step, "ip")
        context = execution_context(plan, first, last)
        _rtl_scope_window(context)
        terminal = (context.get("resolved_rows") or [context["resolved_row"]])[-1]
        native_exit = terminal["profile"]["dispatch"]["native_step_id"]
        if native_exit == "D1" and delivery_target != "rtl":
            return None
        if native_exit != "D1" and not is_rtl_only_evidence(exit_step=native_exit):
            return None
        _rtl_source_inputs(project)
    except ValueError:
        # Unsupported windows, absent original inputs and physical source
        # demands cannot create a default; ordinary admission remains blocking.
        return None
    if existing:
        # Recheck current sources/window on every invocation; the same input
        # bytes carry no prior execution or acceptance authority.
        return path
    # Publish complete bytes without replacing a concurrently supplied input.
    from _atomic_artefact import write_json
    staged = path.with_name(path.name + ".selection." + uuid.uuid4().hex)
    try:
        write_json(staged, manifest)
        os.link(staged, path)
    except FileExistsError as exc:
        raise Flow109Error("FLOW109_MANIFEST_CONFLICT", "input appeared during profile selection") from exc
    finally:
        staged.unlink(missing_ok=True)
    return path


def prepare_task_features(args, project: Path) -> None:
    """Resolve bounded RTL applicability before the general IC/IP question."""
    if (args.flow != "109" or args.flow109_manifest
            or args.execution_mode not in (None, "default")
            or getattr(args, "resume_request", None)):
        return
    selected = resolve_task_manifest(project, args.entry_step, args.exit_step,
                                     getattr(args, "delivery_target", None),
                                     getattr(args, "route", None))
    if selected is not None:
        args.flow109_manifest = selected
        args.delivery_target = "rtl"


def _rtl_scope_binding(project: Path, manifest: Path, context: Mapping) -> dict:
    project = project.resolve()
    manifest = manifest.absolute()
    if (manifest.is_symlink() or not manifest.is_file()
            or not manifest.resolve().is_relative_to(project)):
        raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", "manifest is not a regular project input")
    _rtl_scope_window(context)
    inputs = _rtl_source_inputs(project)
    retained = []
    for relative in (Path("input/step_0_5ic_answers.json"),
                     Path("input/submission_template/tapeout_declaration.json")):
        path = project / relative
        if path.exists() or path.is_symlink():
            declaration, reference = _bound_project_json(project, relative, "FLOW109_RTL_SCOPE_INVALID")
            answers = declaration.get("answers")
            retained.append({**reference,
                             "declared_deliverable": (answers.get("deliverable")
                                                      if isinstance(answers, Mapping) else None),
                             "scope_authority": False,
                             "disposition": "retained unchanged; current RTL scope comes from original sources and explicit request"})
    return {"delivery_target": "rtl", "project": str(project),
            "manifest": {"path": manifest.relative_to(project).as_posix(),
                         "sha256": _file_digest(manifest)},
            "inputs": inputs, "retained_delivery_declarations": retained,
            "issuer_sources": {name: _file_digest(HERE / name) for name in
                ("flow109.py", "_delivery_route.py", "vibe_ic_one_shot_runner.py",
                 "phase1_one_shot_runner.py")}}


def active_rtl_scope(project: Path) -> dict | None:
    """Read the existing source-owned request; stale/foreign scope is BLOCKING.

    This is invocation applicability, never owner physical-delivery authority.
    Unscoped requests retain the ordinary IC/IP admission contract.
    """
    raw = os.environ.get(CONTEXT_ENV)
    if not raw:
        return None
    project = Path(project).resolve()
    path = Path(raw)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if "rtl_scope" not in value:
            return None
        if (path.is_symlink() or path.resolve().parent !=
                (project / "reports/flow109/requests").resolve()):
            raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", "foreign request path")
        context = validate_execution_context(value)
        if path.name != context["context_sha256"] + ".json":
            raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", "request filename changed")
        scope = context["rtl_scope"]
        manifest, _ = _bound_project_json(project, Path(scope["manifest"]["path"]),
                                        "FLOW109_RTL_SCOPE_INVALID")
        plan = resolve_plan(manifest.get("features"), manifest.get("step_profiles"))
        if plan["features"] != context["features"] or plan["step_profiles"] != context["step_profiles"]:
            raise Flow109Error("FLOW109_RTL_SCOPE_STALE", "manifest selection changed")
        expected = _rtl_scope_binding(project, project / scope["manifest"]["path"], context)
        if scope != expected:
            raise Flow109Error("FLOW109_RTL_SCOPE_STALE", "source, manifest, project or issuer changed")
        return {**scope, "context_sha256": context["context_sha256"]}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, Flow109Error):
            raise
        raise Flow109Error("FLOW109_RTL_SCOPE_INVALID", str(exc)) from exc


def active_native_predecessor(project: Path, native_step_id: str) -> dict | None:
    """Resolve the selected physical predecessor for one canonical native row.

    Legacy Default runs have no Flow109 context and retain their static YAML
    predecessor.  A bounded Flow109 launch, however, must not require an
    optional producer that its validated feature plan did not select.
    """
    raw = os.environ.get(CONTEXT_ENV)
    if not raw:
        return None
    project = Path(project).resolve()
    path = Path(raw)
    try:
        expected_parent = (project / "reports" / "flow109" / "requests").resolve()
        resolved = path.resolve(strict=True)
        if path.is_symlink() or resolved.parent != expected_parent or not resolved.is_file():
            raise Flow109Error("FLOW109_CONTEXT_INVALID", "request path is not current project authority")
        context = validate_execution_context(json.loads(resolved.read_text(encoding="utf-8")))
        current = component_context(context, native_step_id=str(native_step_id))
    except (OSError, ValueError, Flow109Error) as exc:
        if isinstance(exc, Flow109Error):
            raise
        raise Flow109Error("FLOW109_CONTEXT_INVALID", str(exc)) from exc
    row = current["resolved_row"]
    plan = resolve_plan(current["features"], current["step_profiles"])
    selected = {item["id"]: item for item in plan["rows"]}
    candidates = []
    for dependency in row["data_deps"]:
        dependency_id = dependency["step"]
        if dependency["when"] == "producer_selected" and dependency_id not in selected:
            continue
        upstream = selected.get(dependency_id)
        if upstream is None:
            continue
        dispatch = upstream["profile"].get("dispatch") or {}
        if dispatch.get("kind") != "canonical_backend_window":
            continue
        defs = [item for item in dispatch.get("native_required_outputs", ())
                if isinstance(item, str) and item.endswith(".def")]
        if len(defs) != 1:
            continue
        candidates.append((upstream["position"], upstream, dispatch, defs[0]))
    if not candidates:
        raise Flow109Error("FLOW109_NATIVE_PREDECESSOR_UNRESOLVED", row["id"])
    _, upstream, dispatch, output = max(candidates, key=lambda item: item[0])
    return {"row_id": upstream["id"],
            "native_step_id": str(dispatch["native_step_id"]),
            "output": output}


def _window_inventory(context: Mapping) -> None:
    runtime = context.get("runtime_tool_uses")
    expected = [use["use_id"] for row in context["resolved_rows"] for use in row["tool_uses"]]
    actual = [item.get("use_id") for item in runtime if isinstance(item, dict)] \
        if isinstance(runtime, list) else []
    if not expected or len(actual) != len(runtime or []) or len(actual) != len(set(actual)) \
            or set(actual) != set(expected):
        raise Flow109Error("FLOW109_WINDOW_USE_MISMATCH",
                           "runtime inventory must exactly cover every selected row use")
    if not isinstance(context.get("qualification_registry"), str) \
            or not context["qualification_registry"]:
        raise Flow109Error("FLOW109_QUALIFICATION_REGISTRY_ABSENT",
                           "qualification registry required")


def _attempt_root(project: Path, *, create: bool) -> Path:
    project = Path(project).resolve()
    parent = project / "reports" / "flow109" / "attempts"
    cursor = project
    for part in ("reports", "flow109", "attempts"):
        cursor /= part
        if cursor.is_symlink():
            raise Flow109Error("FLOW109_ATTEMPT_PATH_INVALID",
                               "attempt authority contains a symlink")
    if create:
        parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir() or parent.resolve() != parent:
        raise Flow109Error("FLOW109_ATTEMPT_PATH_INVALID",
                           "attempt authority is not a current-project directory")
    return parent


def _attempt_request(project: Path, context: Mapping) -> dict:
    return {"schema": "vibeic.flow109.window-attempt-request.v1",
            "project_root_sha256": hashlib.sha256(
                str(Path(project).resolve()).encode()).hexdigest(),
            "context_sha256": context["context_sha256"],
            "registry_sha256": context["registry_sha256"],
            "planner_sha256": context["planner_sha256"],
            "entry": context.get("requested_entry", context.get("requested_step")),
            "exit": context.get("requested_exit", context.get("requested_step")),
            "dispatch_kind": context.get("dispatch_kind", "canonical_owner_window"),
            "component_ids": [row["id"] for row in
                              (context.get("resolved_rows") or [context["resolved_row"]])],
            "flow109_acceptance": "NOT_MEASURED"}


def _new_attempt(project: Path, context: Mapping) -> Path:
    parent = _attempt_root(project, create=True)
    attempt = parent / ("window-" + uuid.uuid4().hex)
    attempt.mkdir()
    request = _attempt_request(project, context)
    with (attempt / "request.json").open("x", encoding="utf-8") as handle:
        json.dump(request, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return attempt


def _bound_attempt(project: Path, context: Mapping, attempt_name: str | None) -> Path:
    if not attempt_name:
        raise Flow109Error("FLOW109_ATTEMPT_ABSENT", "immutable attempt request absent")
    parent = _attempt_root(project, create=False)
    attempt = Path(attempt_name)
    if (not attempt.is_absolute() or ".." in attempt.parts or attempt.parent != parent
            or attempt.is_symlink() or not attempt.is_dir()):
        raise Flow109Error("FLOW109_ATTEMPT_PATH_INVALID",
                           "attempt is not a direct current-project attempt directory")
    try:
        prefix, token = attempt.name.split("-", 1)
        if prefix != "window" or uuid.UUID(hex=token).hex != token:
            raise ValueError("attempt name")
    except (ValueError, AttributeError) as exc:
        raise Flow109Error("FLOW109_ATTEMPT_PATH_INVALID",
                           "attempt directory name is invalid") from exc
    request_path = attempt / "request.json"
    if request_path.is_symlink() or not request_path.is_file():
        raise Flow109Error("FLOW109_ATTEMPT_REQUEST_INVALID",
                           "immutable attempt request is absent or a symlink")
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Flow109Error("FLOW109_ATTEMPT_REQUEST_INVALID", str(exc)) from exc
    if request != _attempt_request(project, context):
        raise Flow109Error("FLOW109_ATTEMPT_REQUEST_INVALID",
                           "immutable attempt request identity differs")
    return attempt


def _finish_attempt(attempt: Path, result: Mapping) -> Path:
    path = attempt / "result.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(dict(result), handle, sort_keys=True, indent=2)
        handle.write("\n")
    return path


def _not_executed_component(context: Mapping, row: Mapping, reason: str) -> dict:
    return {
        "schema": "vibeic.flow109.window-component.v1",
        "step_id": row["id"],
        "native_step_id": row["profile"]["dispatch"]["native_step_id"],
        "component_status": "NOT_MEASURED",
        "reason": reason,
        "context_sha256": context["context_sha256"],
        "native_started": False,
        "metric_acceptance_status": row.get("metric_acceptance_status", "UNIMPLEMENTED"),
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "data_dependencies": row["data_deps"],
        "acceptance_dependencies": row["acceptance_deps"],
    }


def _selected_step_result(project: Path, context: Mapping, result: Mapping,
                          adapter=None) -> dict:
    """Propagate an owner's completed step, never promote component success.

    Owners judge their required native checks. This boundary only preserves
    that answer and its identity; whole-flow and delivery are separate claims.
    Legacy row consumers remain callable without a list of privileged row IDs.
    """
    row = context["resolved_row"]
    if (not isinstance(result, Mapping)
            or result.get("component_status") not in ("PASS", "FAIL", "NOT_MEASURED")
            or result.get("step_id", row["id"]) != row["id"]
            or result.get("context_sha256", context["context_sha256"]) != context["context_sha256"]
            or result.get("whole_flow_acceptance", "NOT_MEASURED") != "NOT_MEASURED"
            or result.get("delivery_accepted", False) is not False):
        raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", row["id"])
    completion = dict(result)
    consume = getattr(adapter, "consume_default_row_completion", None)
    if callable(consume) and (row["id"] in ("D15", "A18") or not (result.get("completed") is True
                                  and result.get("default_row_status") in ("PASS", "FAIL", "NOT_MEASURED"))):
        completion = dict(consume(project, context, result))
        if (completion.get("step_id") != row["id"]
                or completion.get("context_sha256") != context["context_sha256"]):
            raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", row["id"])
    status = completion.get("default_row_status", "NOT_MEASURED")
    if (status not in ("PASS", "FAIL", "NOT_MEASURED")
            or completion.get("whole_flow_acceptance", "NOT_MEASURED") != "NOT_MEASURED"
            or completion.get("delivery_accepted", False) is not False):
        raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", row["id"])
    if result["component_status"] == "FAIL":
        status = "FAIL"
    elif status == "PASS" and (result["component_status"] != "PASS"
                                or completion.get("completed") is not True):
        status = "NOT_MEASURED"
    if status == "PASS" and (completion.get("step_id") != row["id"]
                              or completion.get("context_sha256") != context["context_sha256"]):
        raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", row["id"])
    # A legacy partial result may report native PASS but owes no row verdict.
    # An explicit step PASS is accepted only through completed owner work.
    if result.get("flow109_acceptance", "NOT_MEASURED") not in ("PASS", "FAIL", "NOT_MEASURED"):
        raise Flow109Error("FLOW109_COMPONENT_RESULT_INVALID", row["id"])
    answer = {**result, **completion, "step_id": row["id"],
              "context_sha256": context["context_sha256"],
              "component_status": result["component_status"],
              "default_row_status": status,
              "completed": status == "PASS" and completion.get("completed") is True,
              "flow109_acceptance": status,
              "whole_flow_acceptance": "NOT_MEASURED", "delivery_accepted": False}
    if row["id"] in ("M08", "M09"):
        import flow109_metric_acceptance as metrics
        acceptance = metrics.accept_m89(project, context, result)
        row_status = ("FAIL" if "FAIL" in (status, acceptance["status"]) else
                      "PASS" if status == acceptance["status"] == "PASS"
                      and completion.get("completed") is True else "NOT_MEASURED")
        answer.update(metric_acceptance=acceptance, metric_acceptance_status=acceptance["status"],
                      default_row_status=row_status, flow109_acceptance=row_status,
                      completed=row_status == "PASS", normalized_chain_reason=acceptance.get("reason"))
    if row["id"] == "D24":
        import flow109_metric_acceptance as metrics
        acceptance = metrics.accept_d24(project, context, completion)
        row_status = ('FAIL' if status == 'FAIL' or acceptance['status'] == 'FAIL' else
                      'PASS' if status == 'PASS' and completion.get('completed') is True
                      and acceptance['status'] == acceptance['qualification'] == 'PASS' else 'NOT_MEASURED')
        answer.update(metric_acceptance=acceptance, metric_acceptance_status=acceptance['status'],
            qualification=acceptance['qualification'], default_row_status=row_status,
            flow109_acceptance=row_status, completed=row_status == 'PASS',
            normalized_chain_reason=acceptance.get('reason'))
        if row_status == 'PASS':
            adopted = acceptance['adopted_netlist']
            current = _current_project_ref(project, {k: adopted[k] for k in ('path', 'sha256')},
                                           'FLOW109_D24_ADOPTED_NETLIST_UNBOUND')
            answer['adopted_netlist'] = dict(adopted)
            source = acceptance['native_observation']['upstream']
            answer['scan_cell_list'] = source['scan_cell_list']
            answer['scan_cell_reconciliation'] = acceptance['native_observation']['scan']
    if row["id"] == "D14" and 'native_measurements' not in answer:
        import flow109_metric_acceptance as metrics
        acceptance = metrics.accept_d14(project, context)
        row_status = 'FAIL' if status == 'FAIL' else acceptance['status']
        if row_status == 'PASS' and (acceptance.get('qualification') != 'PASS'
                or status != 'PASS' or completion.get('completed') is not True):
            row_status = 'NOT_MEASURED'
        answer.update(metric_acceptance=acceptance, metric_acceptance_status=acceptance['status'],
                      qualification=acceptance.get('qualification', 'NOT_MEASURED'),
                      default_row_status=row_status, flow109_acceptance=row_status,
                      completed=row_status == 'PASS', normalized_chain_reason=acceptance.get('reason'))
    if row["id"] == "D30" and status == "PASS" and 'native_measurements' not in answer:
        admission = dft_preroute_admission(project, context)
        chain = _complete_preroute_chain(project, context, admission,
                    completion.get('d30_delivery_receipt'),
                    d30_context_sha256=context['context_sha256'])
        admission['normalized_preroute_chain'] = chain
        answer["dft_preroute_admission"] = admission
        if chain.get("status") != "PASS":
            row_status = "FAIL" if chain.get("status") == "FAIL" else "NOT_MEASURED"
            answer.update(default_row_status=row_status, flow109_acceptance=row_status,
                          completed=False, normalized_chain_reason=chain.get("reason"))
        else:
            import flow109_metric_acceptance as metrics
            acceptance = metrics.accept_d30(project, context, completion)
            row_status = acceptance['status']
            answer.update(metric_acceptance=acceptance, metric_acceptance_status=row_status,
                          default_row_status=row_status, flow109_acceptance=row_status,
                          completed=row_status == 'PASS',
                          normalized_chain_reason='D30_METRIC_BINDINGS_UNIMPLEMENTED'
                          if row_status == 'NOT_MEASURED' else acceptance['reason'])
    from _atomic_artefact import write_json
    write_json(project / "reports/flow109/default_rows" / (row["id"] + ".json"), answer)
    return answer


def whole_run_verdict(project: Path) -> dict:
    """The run's verdict: every row the manifest selected PASS. FPGA board rows report apart."""
    plan = json.loads((Path(project) / "reports/flow109/plan.json").read_text())
    rows, fpga = [], []
    for spec in plan["rows"]:
        try:
            from step_output_collector import flow109_step_folder
            results = sorted((Path(project) / 'steps' / flow109_step_folder(spec)).glob('*/result.json'))
            record = json.loads(results[-1].read_text()) if results else {}
        except (OSError, ValueError):
            record = {}
        status = record.get("default_row_status", "NOT_MEASURED")
        if status == "PASS" and record.get("completed") is not True:
            status = "NOT_MEASURED"
        row = {"id": spec["id"], "position": spec["position"], "name": spec["name"],
               "status": status, "reason": record.get("reason")}
        (fpga if "fpga" in spec["when"] else rows).append(row)
    statuses = [row["status"] for row in rows]
    return {"verdict": "FAIL" if "FAIL" in statuses else
                       "PASS" if rows and set(statuses) == {"PASS"} else "NOT_MEASURED",
            "counts": {s: statuses.count(s) for s in ("PASS", "FAIL", "NOT_MEASURED")},
            "steps": rows, "fpga_rows": fpga}


def _execution_manifest(args):
    if not args.flow109_manifest:
        raise Flow109Error('FLOW109_MANIFEST_REQUIRED', 'supply explicit resolved features')
    try:
        manifest = json.loads(Path(args.flow109_manifest).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Flow109Error('FLOW109_MANIFEST_INVALID', str(exc)) from exc
    if not isinstance(manifest, dict):
        raise Flow109Error('FLOW109_MANIFEST_INVALID', 'expected object')
    if 'tool_uses' in manifest and 'runtime_tool_uses' in manifest:
        raise Flow109Error('FLOW109_MANIFEST_INVALID', 'duplicate runtime tool identity fields')
    return manifest


def run_rows(args, project: Path, run_row) -> int:
    """Run the public entry once per selected row, retaining bytes before the next."""
    import step_output_collector as outputs
    manifest = _execution_manifest(args)
    plan = resolve_plan(manifest.get('features'), manifest.get('step_profiles'))
    window = resolve_execution_window(plan, args.entry_step, args.exit_step)
    rows = window.get('resolved_rows') or [window['resolved_row']]
    code = 0
    for row in rows:
        current = execution_context(plan, row['id'], row['id'],
            runtime_tool_uses=manifest.get('runtime_tool_uses', manifest.get('tool_uses')),
            qualification_registry=manifest.get('qualification_registry'))
        attempt = outputs.begin_flow109_row(project, row, current)
        result = {'step_id': row['id'], 'context_sha256': current['context_sha256'],
                  'component_status': 'NOT_MEASURED', 'default_row_status': 'NOT_MEASURED',
                  'completed': False, 'reason': 'not executed: an earlier row stopped'}
        if code:
            outputs.finish_flow109_row(project, row, current, result, attempt)
            continue
        selected = copy.copy(args)
        selected.entry_step = selected.exit_step = row['id']
        selected.resume_request = None
        selected._flow109_row_active = True
        working = project / 'reports/flow109/default_rows' / (row['id'] + '.json')
        before = outputs._working_files(project).get(str(working.relative_to(project)))
        try:
            code = run_row(selected)
            after = outputs._working_files(project).get(str(working.relative_to(project)))
            if after is not None and after != before:
                result = json.loads(working.read_text())
            else:
                result['reason'] = f'row returned {code} without a row result'
        except Exception as exc:
            result['reason'] = str(exc)
            raise
        finally:
            outputs.finish_flow109_row(project, row, current, result, attempt)
    return code


def _attempt_result(context: Mapping, components: list[dict]) -> dict:
    aggregate = ("FAIL" if any(item["component_status"] == "FAIL" for item in components)
                 else "PASS" if len(components) == len(context["resolved_rows"])
                 and all(item["component_status"] == "PASS" for item in components)
                 else "NOT_MEASURED")
    selected = [item.get("default_row_status", "FAIL" if item["component_status"] == "FAIL"
                         else "NOT_MEASURED") for item in components]
    step_status = ("FAIL" if "FAIL" in selected else "PASS"
                   if len(components) == len(context["resolved_rows"])
                   and all(status == "PASS" for status in selected) else "NOT_MEASURED")
    return {"schema": "vibeic.flow109.window-attempt-result.v1",
            "context_sha256": context["context_sha256"],
            "component_status": aggregate, "components": components,
            "default_row_status": step_status,
            "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
            "bounded": True, "delivery_accepted": False}


def finish_native_window(project: Path, report: Mapping, report_path: Path | None = None) -> dict | None:
    """Bind a canonical backend report to per-row component evidence."""
    path = os.environ.get(CONTEXT_ENV)
    attempt_name = os.environ.get(ATTEMPT_ENV)
    if not path:
        return None
    try:
        context = validate_execution_context(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, Flow109Error):
        return None

    attempt = _bound_attempt(project, context, attempt_name)
    owner_rows = context.get("resolved_rows") or [context.get("resolved_row", {})]
    if owner_rows and all((row.get("profile", {}).get("dispatch") or {}).get("kind")
                          == "canonical_owner_window" for row in owner_rows):
        # The existing owner report carries the native step's completed answer.
        # No backend alias, extra row consumer or second native judgment.
        components = []
        for row in owner_rows:
            native = str(row["profile"]["dispatch"]["native_step_id"])
            matches = [item for item in report.get("steps", [])
                       if str((item.get("extras") or {}).get("step_id")) == native]
            current = component_context(context, requested_step=row["id"])
            item = matches[0] if len(matches) == 1 else {}
            extras = item.get("extras") or {}
            if extras.get("context_sha256", context["context_sha256"]) not in (
                    context["context_sha256"], current["context_sha256"]):
                raise Flow109Error("FLOW109_CONTEXT_STALE", "native owner result")
            result = {**extras, "step_id": row["id"],
                      "context_sha256": current["context_sha256"],
                      "component_status": item.get("status", "NOT_MEASURED")}
            components.append(_selected_step_result(project, current, result))
        result = _attempt_result({**context, "resolved_rows": owner_rows}, components)
        result["default_row_status"] = (
            "FAIL" if any(c["default_row_status"] == "FAIL" for c in components)
            else "PASS" if all(c["default_row_status"] == "PASS" for c in components)
            else "NOT_MEASURED")
        _finish_attempt(attempt, result)
        return result
    if context["schema"] == "vibeic.flow109.execution-context.v1":
        dispatch = context["resolved_row"]["profile"].get("dispatch") or {}
        if dispatch.get("kind") != "canonical_backend_window":
            return None
        rows = [context["resolved_row"]]
    elif context.get("dispatch_kind") in (
            "canonical_backend_window", "selected_native_sequence"):
        rows = context["resolved_rows"]
    else:
        return None
    canonical = []
    for site in report.get("steps", []) if isinstance(report, Mapping) else []:
        if isinstance(site, dict):
            canonical.extend((site.get("extras") or {}).get("canonical_steps") or [])
    by_native = {str((item.get("extras") or {}).get("step_id")): item
                 for item in canonical if isinstance(item, dict)}
    components = []
    stopped = False
    for row in rows:
        dispatch = row["profile"]["dispatch"]
        native = str(dispatch["native_step_id"])
        if dispatch.get("adapter"):
            component_path = (project / "reports" / "flow109" / "components"
                              / (row["id"] + ".json"))
            try:
                component = json.loads(component_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                component = _not_executed_component(
                    context, row, "selected adapter component receipt absent or invalid")
            if (not isinstance(component, dict)
                    or component.get("step_id") != row["id"]
                    or component.get("context_sha256") != context["context_sha256"]
                    or component.get("component_status") not in (
                        "PASS", "FAIL", "NOT_MEASURED")
                    or component.get("flow109_acceptance") not in ("PASS", "FAIL", "NOT_MEASURED")
                    or (component.get("flow109_acceptance") == "PASS" and not (
                        component.get("completed") is True and component.get("default_row_status") == "PASS"))):
                component = _not_executed_component(
                    context, row, "selected adapter component receipt absent or invalid")
            components.append(component)
            if component["component_status"] != "PASS":
                stopped = True
            continue
        if stopped:
            component = _not_executed_component(
                context, row, "not executed: an earlier row stopped")
            components.append(component)
            from _atomic_artefact import write_json
            write_json(project / "reports" / "flow109" / "components"
                       / (row["id"] + ".json"), component)
            continue
        item = by_native.get(native)
        status = str(item.get("status")) if item else "NOT_MEASURED"
        native_not_applicable = status == "NOT_APPLICABLE"
        if status not in ("PASS", "FAIL", "NOT_MEASURED"):
            status = "NOT_MEASURED"
        reason = ("selected Flow109 row cannot inherit native NOT_APPLICABLE"
                  if native_not_applicable else
                  str(item.get("detail") or "") if item else
                  "not executed: an earlier row stopped" if stopped else
                  str(report.get("flow109_stop_reason") or "canonical row result absent"))
        receipt = project / "reports" / "phase3" / "default_steps" / native / "backend_result.json"
        receipt_body = None
        if receipt.is_file():
            try:
                receipt_body = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                receipt_body = None
        if status == "PASS" and (not isinstance(receipt_body, dict)
                                 or receipt_body.get("verdict") != "PASS"):
            status = "NOT_MEASURED"
            reason = "canonical current native PASS receipt absent or invalid"
        component = {
            "schema": "vibeic.flow109.window-component.v1", "step_id": row["id"],
            "native_step_id": native, "component_status": status,
            "reason": reason, "context_sha256": context["context_sha256"],
            "metric_acceptance_status": row.get("metric_acceptance_status", "UNIMPLEMENTED"),
            "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
            "data_dependencies": row["data_deps"],
            "acceptance_dependencies": row["acceptance_deps"],
        }
        if receipt.is_file():
            component["canonical_receipt"] = {
                "path": str(receipt.relative_to(project)), "sha256": _file_digest(receipt)}
        if (row['id'] in ('D35', 'D37', 'D38', 'D39', 'D40', 'D41')
                or (row['id'], native) in (('D31', '15'), ('D32', '15.5ic'))):
            # These owners judge native values again. A saved nested PASS is
            # provenance to bind, never the current metric verdict.
            import flow109_metric_acceptance as metrics
            import flow109_admission as admission
            import execution_backend_producers as producers
            import step_output_collector as versions
            import librelane_contract as native_chain
            current = component_context(context, requested_step=row['id'])
            accepted = {'row_id': row['id'], 'status': 'NOT_MEASURED',
                        'metric_status': 'NOT_MEASURED', 'obligations': []}
            row_status = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
            readset = []
            component['qualification'] = {'status': 'NOT_MEASURED', 'reason': 'ADMISSION_NOT_REACHED'}

            def _d3537_read(relative):
                relative = Path(relative)
                if relative.is_absolute() or '..' in relative.parts:
                    raise Flow109Error('FLOW109_BACKEND_RECEIPT_UNBOUND', str(relative))
                body, reference = _bound_project_json(
                    project, relative, 'FLOW109_BACKEND_RECEIPT_UNBOUND')
                _current_project_ref(project, reference, 'FLOW109_BACKEND_RECEIPT_UNBOUND')
                readset.append(reference)
                return body

            try:
                if row['id'] == 'D38':
                    chain = _d3537_read('reports/phase3/librelane_cts_handoff.json')
                    first_step = 'OpenROAD.CTS'
                    state = Path(chain['chain'][first_step]) / 'state_out.json'
                elif row['id'] == 'D39':
                    chain = _d3537_read('reports/phase3/librelane_cts_hold_handoff.json')
                    first_step = 'OpenROAD.ResizerTimingPostCTS'
                    state = Path(chain['chain'][first_step]) / 'state_out.json'
                else:
                    chain_native = '15' if native == '15.5ic' else native
                    chain = _d3537_read('reports/phase3/execution-backend-' + chain_native + '.json')
                    first_step = chain['states'][0]['step']
                    state = Path(chain['states'][0]['state'])
                state = state if state.is_absolute() else project / state
                native_path = (state.parent / 'vibeic_receipt.json').relative_to(project)
                native_ref = {'path': native_path.as_posix(),
                              'sha256': _file_digest(project / native_path)}
                _current_project_ref(project, native_ref, 'FLOW109_BACKEND_RECEIPT_UNBOUND')
                readset.append(native_ref)
                native_receipt = native_chain.validate_step_receipt(
                    state.parent, first_step)
                judge = {'D31': metrics.accept_d31_digital, 'D32': metrics.accept_d32_digital,
                         'D35': metrics.accept_d35, 'D37': metrics.accept_d37,
                         'D38': metrics.accept_d38, 'D39': metrics.accept_d39,
                         'D40': metrics.accept_d40, 'D41': metrics.accept_d41}[row['id']]
                owner_input = {'native_image': native_receipt['input']['image'], 'verdict': 'NOT_MEASURED'}
                if row['id'] == 'D38':
                    owner_input['flow109_d38_targets'] = chain.get('flow109_d38_targets')
                observed = judge(project, current, owner_input)
                if (not isinstance(observed, Mapping) or observed.get('row_id') != row['id']
                        or observed.get('status') not in ('PASS', 'FAIL', 'NOT_MEASURED')
                        or observed.get('metric_status') not in ('PASS', 'FAIL', 'NOT_MEASURED')):
                    raise Flow109Error('FLOW109_BACKEND_METRIC_RESULT_INVALID', row['id'])
                accepted = dict(observed)
                if (accepted.get('status') == 'FAIL' or accepted.get('metric_status') == 'FAIL'
                        or any(o.get('status') == 'FAIL' for o in accepted.get('obligations', []))):
                    row_status = 'FAIL'
                body = _d3537_read(receipt.relative_to(project))
                binding = body.get('binding') or {}
                if (body.get('schema') != 'vibeic/backend-result/2' or body.get('step_id') != native
                        or binding.get('step_id') != native or body.get('source_sha') != binding.get('source_sha')
                        or not isinstance(body.get('source_sha'), str) or not body['source_sha']):
                    raise Flow109Error('FLOW109_BACKEND_RECEIPT_UNBOUND', native)
                folder = Path((item.get('extras') or {})['output_version'])
                root = versions._versions_root(project)
                relative = (root / folder).relative_to(project)
                journal = _d3537_read(relative / 'attempt.json')
                saved = _d3537_read(relative / 'outputs.json')
                index = _d3537_read(root.relative_to(project) / 'index.json')
                indexed = [entry for entry in index['steps'] if str(entry.get('id')) == native]
                keys = ('id', 'name', 'phase', 'stage', 'folder', 'storage_root',
                        'started_at', 'inputs', 'input_files')
                if (len(indexed) != 1 or indexed[0].get('folder') != str(folder)
                        or str(saved.get('id')) != native or saved.get('folder') != str(folder)
                        or saved.get('result') != body or saved.get('status') != body.get('verdict')
                        or journal.get('status') != 'RUNNING'
                        or any(saved.get(key) != journal.get(key) for key in keys)
                        or saved.get('capture_errors') != [] or journal.get('capture_errors') != []
                        or not versions._inputs_current(project, saved.get('inputs'))):
                    raise Flow109Error('FLOW109_BACKEND_RECEIPT_STALE', native)
                copies = [entry for entry in saved.get('written_files', [])
                          if entry.get('rel') == str(receipt.relative_to(project))]
                if len(copies) != 1:
                    raise Flow109Error('FLOW109_BACKEND_RECEIPT_UNBOUND', 'original backend result copy absent')
                copy_path = relative / copies[0]['snapshot']
                if not (project / copy_path).resolve().is_relative_to((project / relative).resolve()):
                    raise Flow109Error('FLOW109_BACKEND_RECEIPT_UNBOUND', 'foreign result copy')
                original = _d3537_read(copy_path)
                if (original != body or copies[0]['sha256'] != _file_digest(receipt)
                        or copies[0]['size'] != receipt.stat().st_size):
                    raise Flow109Error('FLOW109_BACKEND_RECEIPT_STALE', 'backend result changed')
                if (body.get('verdict') == 'FAIL' or body.get('producer_verdict') == 'FAIL'
                        or any(value == 'FAIL' for value in (body.get('gates') or {}).values())):
                    row_status = 'FAIL'
                    component['component_status'] = 'FAIL'
                allowed, detail, _ = producers._current_step_producer_authority(
                    body.get('current_step_declared_producers'), project=project)
                if not allowed:
                    raise Flow109Error('FLOW109_BACKEND_PRODUCER_UNBOUND', detail)
                records = body.get('canonical_receipts')
                if (not isinstance(records, list) or len(records) != 1
                        or records[0].get('schema') != 'vibeic/backend-producer-receipt/1'
                        or records[0].get('producer') != 'execution_backend_producers.produce'
                        or records[0].get('step_id') != native):
                    raise Flow109Error('FLOW109_BACKEND_PRODUCER_UNBOUND', native)
                prior = records[0].get('metric_acceptance') or {}
                if prior.get('row_id') != row['id']:
                    raise Flow109Error('FLOW109_BACKEND_CONTEXT_MISMATCH', row['id'])
                prior_measurements = [m for obligation in prior.get('obligations', [])
                    for m in ([obligation['measurement']] if 'measurement' in obligation
                              else obligation.get('measurements', []))]
                if (not prior_measurements or any(
                        (m.get('measurement', m).get('identity', {}).get('configuration', {})
                         .get('context_sha256')) != current['context_sha256'] for m in prior_measurements)):
                    raise Flow109Error('FLOW109_BACKEND_CONTEXT_MISMATCH', row['id'])
                if row['id'] == 'D41':
                    reference = prior.get('native_readback')
                    if not isinstance(reference, Mapping) or reference != accepted.get('native_readback'):
                        raise Flow109Error('FLOW109_D41_READBACK_STALE', 'original producer snapshot differs')
                    _current_project_ref(project, reference, 'FLOW109_D41_READBACK_STALE')
                    readset.append(reference)
                qualified = admission.require_admission(project, current)
                component['qualification'] = qualified
                selected = {entry['id'] for entry in resolve_plan(
                    current['features'], current['step_profiles'])['rows']}
                dependencies = {}
                required = set(row['acceptance_deps']) | {dep['step'] for dep in row['data_deps']}
                for dependency in sorted(required & selected):
                    upstream, reference = _accepted_row(project,
                        Path('reports/flow109/default_rows') / (dependency + '.json'), dependency)
                    upstream_context = validate_execution_context(_d3537_read(
                        'reports/flow109/requests/' + str(upstream.get('context_sha256')) + '.json'))
                    if (upstream_context['requested_step'] != dependency
                            or upstream_context['features'] != current['features']
                            or upstream_context['step_profiles'] != current['step_profiles']
                            or upstream_context.get('rtl_scope') != current.get('rtl_scope')):
                        raise Flow109Error('FLOW109_BACKEND_DEPENDENCY_STALE', dependency)
                    if upstream.get('canonical_receipt'):
                        _current_project_ref(project, upstream['canonical_receipt'],
                                             'FLOW109_BACKEND_DEPENDENCY_STALE')
                    readset.append(reference)
                    dependencies[dependency] = reference
                component['accepted_dependencies'] = dependencies
                eligible = (status == 'PASS' and body.get('verdict') == 'PASS'
                    and body.get('producer_verdict') == 'PASS' and saved.get('canonical_pass') is True
                    and not body.get('missing_outputs') and not body.get('missing_inputs')
                    and all(body.get('gates', {}).get(gate) == 'PASS'
                            for gate in ('backend_canonical', 'backend_native_substance'))
                    and accepted.get('row_id') == row['id'] and accepted.get('status') == 'PASS'
                    and accepted.get('metric_status') == 'PASS'
                    and accepted.get('qualification') == 'PASS'
                    and {o['id'] for o in accepted.get('obligations', [])} == {o['id'] for o in row['obligations']}
                    and all(o.get('status') == 'PASS' for o in accepted['obligations']))
                if row_status != 'FAIL' and eligible:
                    row_status = 'PASS'
                for reference in readset:
                    _current_project_ref(project, reference, 'FLOW109_BACKEND_INPUT_CHANGED')
                if admission.require_admission(project, current) != qualified:
                    raise Flow109Error('FLOW109_BACKEND_QUALIFICATION_CHANGED', row['id'])
                request = project / 'reports/flow109/requests' / (current['context_sha256'] + '.json')
                if request.is_symlink() or request.parent.resolve() != request.parent:
                    raise Flow109Error('FLOW109_BACKEND_CONTEXT_MISMATCH', 'linked request path')
                if request.exists() and _d3537_read(request.relative_to(project)) != current:
                    raise Flow109Error('FLOW109_BACKEND_CONTEXT_MISMATCH', row['id'])
                from _atomic_artefact import write_json
                if not request.exists():
                    write_json(request, current)
            except (Flow109Error, admission.AdmissionRefusal, native_chain.Refusal, OSError, ValueError,
                    KeyError, TypeError, AttributeError) as exc:
                if row_status != 'FAIL':
                    row_status = 'NOT_MEASURED'
                if isinstance(exc, admission.AdmissionRefusal):
                    component['qualification'] = exc.report
                component['reason'] = str(exc)
            component.update(metric_acceptance=accepted,
                metric_acceptance_status=accepted.get('metric_status', 'NOT_MEASURED'),
                default_row_status=row_status, flow109_acceptance=row_status,
                completed=row_status == 'PASS', context_sha256=current['context_sha256'],
                delivery_accepted=False)
            from _atomic_artefact import write_json
            write_json(project / 'reports/flow109/default_rows' / (row['id'] + '.json'), component)
        components.append(component)
        from _atomic_artefact import write_json
        write_json(project / "reports" / "flow109" / "components" / (row["id"] + ".json"), component)
        if status != "PASS":
            stopped = True
    aggregate_context = dict(context)
    aggregate_context["resolved_rows"] = rows
    result = _attempt_result(aggregate_context, components)
    if report_path is not None and Path(report_path).is_file():
        result["canonical_window_report"] = {
            "path": str(Path(report_path).relative_to(project)),
            "sha256": _file_digest(Path(report_path))}
    if attempt is not None:
        _finish_attempt(attempt, result)
    return result


def _retained_native_result(project: Path, context: Mapping) -> dict | None:
    """Read one row's completed native result against its original limits."""
    from flow109_final_electrical import IR_LIMIT_PCT
    contracts = {
        **{step: {} for step in ('D31', 'D35', 'D37', 'D40')},
        'D32': {'native_steps': ('OpenROAD.PadRing', 'OpenROAD.GeneratePDN')},
        'D38': {'method': 'cts'}, 'D39': {'method': 'repair'},
        'D42': {'steps': {'Checker.TrDRC': 'route__drc_errors',
                         'Checker.DisconnectedPins': 'design__critical_disconnected_pin__count',
                         'Checker.WireLength': None}},
        **{step: {'report': 'reports/phase3/sta_postpnr_signoff.json', 'state': 'sta_state',
            'limits': {**{f'corners.*.{key}': ('ge', 0) for key in ('setup_ws', 'hold_ws')},
                       **{f'corners.*.{key}': ('eq', 0) for key in ('setup_tns', 'hold_tns',
                           'setup_vio', 'hold_vio', 'max_slew_vio', 'max_cap_vio', 'max_fanout_vio')},
                       **{f'state.metrics.design__max_{key}_violation__count': ('eq', 0)
                          for key in ('slew', 'cap', 'fanout')}}} for step in ('D41', 'D49')},
        'D43': {'report': 'reports/phase3/antenna.json', 'state': 'tool_state',
                'limits': {'net_violations': ('eq', 0), 'pin_violations': ('eq', 0)}},
        'D47': {'report': 'reports/phase3/librelane_rcx_handoff.json', 'state': 'state',
                'files': ('state.spef.*',)},
        'D48': {'report': 'reports/phase3/si_mcf_sta.json', 'limits': {
            'windows_rc': ('eq', 0), 'corners.*.sta_rc': ('eq', 0),
            'corners.*.worst_slack_after_ns': ('ge', 0)}},
        'D56': {'report': 'reports/phase3/sta_postpnr_signoff.json', 'state': 'sta_state',
                'observe': ('state.metrics.power__total__corner:*',),
                'unmeasured': ['functional-activity power and undeclared owner power budgets']},
        'D57': {'report': 'reports/phase3/ir_drop.json', 'state': 'tool_state',
                'limits': {'worst_ir_pct_vdd': ('lt', IR_LIMIT_PCT)}},
        'D58': {'report': 'reports/phase3/em_openroad_density.json', 'limits': {
            'nets.*.violated': ('eq', 0)}, 'available': {'nets.*.no_limit': 0},
                'unmeasured': ['signal EM']},
        'D59': {'report': 'reports/phase3/perc_equivalent.json',
                'limits': {'CVC_total': ('eq', 0)},
                'unmeasured': ['latch-up spacing', 'ESD characterization']},
        'D54': {'report': 'reports/phase3/spice_correlation.json', 'status': 'verdict'},
        'D55': {'report': 'reports/phase3/functional_activity.json', 'status': 'component_status'},
        'D53': {'report': 'reports/phase3/gls_corners.json', 'status': 'verdict'},
        'D03': {'method': 'config', 'report': 'phase3/librelane/02-yosys-synthesis/config.json'},
        'D06': {'method': 'verdict', 'report': 'reports/phase3/io_pad_chip_top.json'},
        'D10': {'method': 'p0', 'report': 'reports/flow109/default_rows/D10.json'},
        'D11': {'method': 'verdict', 'report': 'reports/phase2/lint/verilator_lint_gate.json'},
        'D13': {'method': 'simulation', 'report': 'reports/phase2/sim/l10_execution.json'},
        'D14': {'method': 'formal', 'report': 'phase2/stage1/formal/results.json'},
        'D19': {'method': 'sdc_copy', 'report': 'phase2/stage2/constraints/asic_sdc.json'},
        'D20': {'method': 'verdict', 'report': 'reports/sdc_validator.json'},
        'D22': {'method': 'synthesis', 'report': 'phase3/librelane/02-yosys-synthesis/state_out.json'},
        'D25': {'method': 'equivalence', 'report': 'reports/lec_eqy_execution.json'},
        'D26': {'method': 'sta', 'report': 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr/state_out.json'},
        'D30': {'method': 'verdict', 'report': 'phase3/librelane/02-yosys-synthesis/handoff_netlist_gate.json'},
    }
    row = context.get('resolved_row', {})
    step = row.get('id')
    entry = contracts.get(step)
    if entry is None or row.get('profile', {}).get('id') != 'default':
        return None
    method = entry.get('method', 'report' if entry.get('report') else 'physical')
    physical = method in ('physical', 'cts', 'repair')
    measurements = {}
    error_counts = None
    status = 'NOT_MEASURED'
    timing_failed = failed = False
    result = {'step_id': step, 'context_sha256': context['context_sha256'],
        'native_started': False, 'native_measurements': measurements}
    try:
        if method == 'report':
            result.update(native_reports_reused=True, native_reports=[entry['report']],
                          unmeasured_obligations=entry.get('unmeasured', []))
            import fnmatch
            def values_at(doc, field):
                nodes = [doc]
                for part in field.split('.'):
                    nodes = [value for node in nodes if isinstance(node, dict)
                             for key, value in node.items() if fnmatch.fnmatchcase(key, part)]
                return nodes
            def local(raw):
                path = Path(raw)
                if path.is_absolute() and not path.is_relative_to(project):
                    path = Path(*path.parts[path.parts.index('phase3'):])
                return project / path
            path = project / entry['report']
            if not path.is_file():
                return None
            text = path.read_text()
            native = json.loads(text)
            if entry.get('state'):
                state = local(native[entry['state']])
                fields = [*entry.get('limits', {}), *entry.get('files', ()), *entry.get('observe', ())]
                if any(field.startswith('state.') for field in fields):
                    native['state'] = json.loads(state.read_text())
                fingerprint = state.parent / 'input_fingerprint.json'
                if fingerprint.is_file():
                    inputs = json.loads(fingerprint.read_text()).get('state_files', {})
                    if any(_file_digest(local(name)) != sha for name, sha in inputs.items()
                           if '/phase3/stage3/' in name or name.startswith('phase3/stage3/')):
                        return None
            for field, (op, limit) in entry.get('limits', {}).items():
                values = values_at(native, field)
                if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                    raise ValueError('native measurement unavailable: ' + field)
                measurements[field] = values
                failed |= any(not (v >= limit if op == 'ge' else v < limit if op == 'lt'
                                   else v == limit) for v in values)
            for field, limit in entry.get('available', {}).items():
                values = values_at(native, field)
                if not values or any(v != limit for v in values):
                    raise ValueError('native limit unavailable: ' + field)
            for field in entry.get('files', ()):
                values = values_at(native, field)
                if not values or not all(local(v).is_file() for v in values):
                    raise ValueError('native output absent: ' + field)
                measurements[field] = values
            for field in entry.get('observe', ()):
                values = values_at(native, field)
                if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                    raise ValueError('native measurement unavailable: ' + field)
                measurements[field] = values
            if entry.get('status'):
                verdict = native.get(entry['status'])
                if verdict not in ('PASS', 'FAIL'):
                    raise ValueError('native result not measurements: ' + str(verdict))
                failed |= verdict == 'FAIL'
                measurements[entry['status']] = verdict
            status = 'FAIL' if failed else 'PASS'
            detail = None
        elif physical:
            chain_path = project / 'reports/phase3/execution-backend-15.json'
            if not chain_path.is_file():
                return None
            result['reason'] = step + '_NATIVE_PHYSICAL_RESULT'
            chain = json.loads(chain_path.read_text())
            states = {item["step"]: project / item["state"] for item in chain["states"]}
            steps = (entry.get("native_steps") or tuple(entry.get("steps", ()))
                     or row["profile"]["native_steps"])
            if any(native_step not in states for native_step in steps):
                root = next(iter(states.values())).parent.parent
                ordered = []
                for config_path in root.glob("*/config.json"):
                    native_step = json.loads(config_path.read_text()).get("meta", {}).get("step")
                    ordinal = config_path.parent.name.split("-", 1)[0]
                    if ordinal.isdigit():
                        ordered.append((int(ordinal), native_step, config_path.parent / "state_out.json"))
                    if method in ("cts", "repair"):
                        continue
                    if native_step not in steps:
                        continue
                    state = config_path.parent / "state_out.json"
                    if native_step in states and states[native_step] != state:
                        raise ValueError("ambiguous native step: " + native_step)
                    states[native_step] = state
                if method in ("cts", "repair"):
                    ordered.sort()
                    anchors = [i for i, item in enumerate(ordered) if item[1] == steps[0]]
                    if not anchors:
                        return None
                    if len(anchors) != 1 or anchors[0] + 1 >= len(ordered):
                        raise ValueError("native CTS/repair State unavailable")
                    own, sta = ordered[anchors[0]:anchors[0] + 2]
                    if sta[1] != "OpenROAD.STAMidPNR":
                        raise ValueError("STA does not follow the selected native State")
                    states.update({own[1]: own[2], sta[1]: sta[2]})
                elif steps[0] not in states:
                    return None
            for native_step in steps:
                state_path = states[native_step]
                state = json.loads(state_path.read_text())
                values = state["metrics"]
                measurements[native_step] = {"report": str(state_path)}
                if native_step != "Yosys.JsonHeader":
                    measurements[native_step]["errors"] = values["flow__errors__count"]
                if entry.get('steps', {}).get(native_step):
                    metric = entry['steps'][native_step]
                    measurements[native_step][metric] = values[metric]
                if native_step == 'Checker.WireLength':
                    config = json.loads((state_path.parent / 'config.json').read_text())
                    if config.get('WIRE_LENGTH_THRESHOLD') is None:
                        result['unmeasured_obligations'] = ['wire-length limit absent from PDK']
                    elif values['route__wirelength__max'] > config['WIRE_LENGTH_THRESHOLD']:
                        measurements[native_step]['wire_length_violations'] = 1
                if native_step == "OpenROAD.GeneratePDN":
                    measurements[native_step]["connectivity_errors"] = values["design__power_grid_violation__count"]
                if native_step == "OpenROAD.DetailedPlacement":
                    measurements[native_step]["placement_errors"] = values["design__violations"]
                if native_step == "Vibeic.InsertSpareCells":
                    for key in ("vibeic__spare__pg__unconnected", "vibeic__spare__check_placement__violations"):
                        measurements[native_step][key] = values[key]
                    for wanted, actual in (("planned", "inserted"), ("tieoff__candidates", "tieoff__connected")):
                        pair = [values["vibeic__spare__" + key] for key in (wanted, actual)]
                        if any(type(v) not in (int, float) or not math.isfinite(v)
                               or v < 0 or v != int(v) for v in pair):
                            raise ValueError("invalid native spare count")
                        measurements[native_step][wanted + "_mismatch"] = abs(pair[0] - pair[1])
                if native_step == "OpenROAD.FillInsertion":
                    measurements[native_step]["routing_errors"] = values["route__drc_errors_final"]
                    measurements[native_step]["disconnected_required_pins"] = values["design__critical_disconnected_pin__count"]
                if native_step == "OpenROAD.CTS":
                    report = state_path.parent / "cts.rpt"
                    text = report.read_text()
                    result["cts"] = {"report": str(report), **{
                        key: int(re.search(pattern + r"\s*(\d+)", text).group(1))
                        for key, pattern in (("sinks", "Total number of Sinks:"),
                                             ("buffers", "Total number of Buffers Inserted:"))}}
                if native_step == "OpenROAD.STAMidPNR":
                    timing = {key: values["timing__" + key + "__ws"] for key in ("setup", "hold")}
                    if any(type(v) not in (int, float) or not math.isfinite(v) for v in timing.values()):
                        raise ValueError("native setup/hold slack unavailable")
                    timing_failed = any(v < 0 for v in timing.values())
                    result["timing"] = {"report": str(state_path), "worst_slack_ns": timing, "limit_ns": 0}
                    result["intermediate_drv"] = {
                        "scope": "reported, not limits here; post-route signoff owns closure",
                        **{key: values.get("design__max_" + key + "_violation__count")
                           for key in ("slew", "cap", "fanout")}}
            error_counts = [value for observed in measurements.values()
                      for key, value in observed.items() if key != "report"]
        else:
            report = project / entry['report']
            if not report.exists():
                return None
            import _path_layout as layout
            import _specrtl_common as sources
            synthesis = json.loads((project / 'phase2/stage2/synth/synth_inputs.json').read_text())
            rtl = layout.rtl_dir(project)
            if synthesis['rtl_sha256'] != {
                    p.relative_to(rtl).as_posix(): _file_digest(p)
                    for p in sources.rtl_source_files(project)}:
                return None
            if method == 'config':
                from declared_pdk_is_the_pdk_used_check import declared_distribution
                config = json.loads(report.read_text())
                declared, _ = declared_distribution(project)
                measurements.update(report=str(report), pdk=config['PDK'],
                                    library=config['STD_CELL_LIBRARY'])
                status = 'PASS' if config['PDK'] == declared else 'FAIL'
            elif method == 'verdict':
                native = json.loads(report.read_text())
                if step == 'D06':
                    owner = json.loads((project / 'input/submission_template/tapeout_declaration.json').read_text())
                    if owner.get('answers', {}).get('deliverable') != 'DIE':
                        return None
                    result['scope'] = 'bare-die interface; owner input/submission_template/tapeout_declaration.json'
                    assignment = project / 'phase3/stage3/pnr/pad_assignment.json'
                    measurements['pad_assignment'] = json.loads(assignment.read_text())['SIGNAL_MAP']
                measurements.update(report=str(report), native=native)
                status = {'WROTE': 'PASS', 'PASS': 'PASS', 'FAIL': 'FAIL'}.get(native['verdict'], 'NOT_MEASURED')
            elif method == 'p0':
                prior = json.loads(report.read_text())
                p0 = prior.get('p0_native') or prior['evidence']['p0_native']
                native = json.loads((project / p0['producer_result']['path']).read_text())
                measurements.update(report=p0['producer_result']['path'], tools=native['tools'])
                failed = any(native['tools'][name]['exit_code'] != 0
                             for name in ('Yosys.JsonHeader', 'Verilator.Lint'))
                if failed or native['passed'] is False:
                    status = 'FAIL'
                else:
                    import flow109_metric_acceptance as metrics
                    graph = json.loads((project / p0['elaboration_path']).read_text())
                    measured = metrics._d10_feature_inventory(graph, p0['top'])
                    measurements['interface'] = measured
                    status = 'PASS'
                result['p0_native'] = p0
            elif method == 'simulation':
                native = json.loads(report.read_text())
                required = json.loads((project / 'requirements/base_07/required_function_scenarios.json').read_text())
                cases = {case['id']: case for case in native['cases']}
                selected = [cases[item['name']] for item in required['required_items']]
                measurements.update(report=str(report), cases=selected)
                status = 'FAIL' if any(case['verdict'] == 'FAIL' for case in selected) else 'PASS'
                if not selected or any(not case['sim_executed'] or case['verdict'] != 'PASS' for case in selected):
                    status = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
                coverage = json.loads((project / 'reports/phase2/coverage/coverage_verilator.json').read_text())
                targets = json.loads((project / 'requirements/base_07/coverage_targets.json').read_text())
                measurements['coverage'] = coverage['totals']
                if set(coverage['scope_files']) != {str(p) for p in sources.rtl_source_files(project)}:
                    status = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
                for category, limits in targets['limits'].items():
                    observed = coverage['totals'][category]
                    if category == 'branch':
                        from verilator_coverage_measure import measured_empty_branch_population
                        empty_branch = measured_empty_branch_population(coverage)
                        if empty_branch is not None:
                            measurements['branch_applicability'] = empty_branch
                            continue
                    if observed['total'] <= 0 or not math.isfinite(observed['pct']):
                        status = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
                    elif targets['acceptance_applicable'] and (
                            'min' in limits and observed['pct'] < limits['min']
                            or 'max' in limits and observed['pct'] > limits['max']):
                        status = 'FAIL'
                result['coverage_scope'] = targets['reason']
            elif method == 'formal':
                native = json.loads(report.read_text())
                required = json.loads((project / 'requirements/base_08/proof_partition_coverage.json').read_text())
                tasks = {item['task']: item for item in native['properties']}
                selected = [tasks[item['task']] for item in required['required_items']]
                measurements.update(report=str(report), tasks=selected,
                                    completion=native.get('formal_completion'),
                                    unresolved=native.get('unresolved_obligations', []))
                states = [item['status'] for item in selected]
                status = 'FAIL' if 'FAIL' in states else 'PASS' if states and set(states) == {'PASS'} else 'NOT_MEASURED'
            elif method == 'sdc_copy':
                native = json.loads(report.read_text())
                deck = project / native.get('staged_sdc', native['path'])
                copies = []
                for state in (project / 'reports/flow109/attempts').glob('*/load_base_sdc/*/state_out.json'):
                    copied = state.with_name(Path(json.loads(state.read_text())['sdc']).name)
                    if copied.read_bytes() == deck.read_bytes():
                        copies.append(str(copied))
                measurements.update(report=str(report), native_copies=copies,
                                    clock_period_source=str(deck))
                status = 'PASS' if copies else 'NOT_MEASURED'
            elif method == 'synthesis':
                folder = project / 'phase3/librelane/02-yosys-synthesis'
                if not (folder / 'state_out.json').is_file():
                    return None
                state = json.loads((folder / 'state_out.json').read_text())
                measurements.update(report=str(folder / 'state_out.json'), **{
                    key: state['metrics'][key] for key in
                    ('design__instance_unmapped__count', 'synthesis__check_error__count')})
                error_counts = [v for k, v in measurements.items() if k != 'report']
            elif method == 'equivalence':
                import librelane_eqy
                execution = project / 'reports/lec_eqy_execution.json'
                if not execution.is_file():
                    return None
                native = json.loads(execution.read_text())
                if any(_file_digest(project / item['path']) != item['sha256']
                       for item in [*native['subject']['rtl'], native['subject']['gate_netlist']]):
                    return None
                folder = project / native['native_directory']
                proof = librelane_eqy.judge_eqy(folder,
                    project / 'reports/flow109/components/D25-native.json')
                measurements.update(proof)
                status = proof['verdict'] if proof['verdict'] in ('PASS', 'FAIL') else 'NOT_MEASURED'
            else:
                import librelane_prelayout as sta
                if context['features'].get('requires_scan'):
                    return None
                folder = project / 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr'
                if not (folder / 'state_out.json').is_file():
                    return None
                before = json.loads((folder / 'state_in.json').read_text())
                inputs = json.loads((folder / 'input_fingerprint.json').read_text())
                netlist = layout.synth_dir(project) / Path(before['nl']).name
                config = json.loads((folder / 'config.json').read_text())
                sdc = layout.constraints_dir(project) / Path(config['PNR_SDC_FILE']).name
                if (_file_digest(netlist) != inputs['state_files'][before['nl']]
                        or _file_digest(sdc) != inputs['config_files'][config['PNR_SDC_FILE']]):
                    return None
                timing = sta.judge_slack(folder,
                    project / 'reports/flow109/components/D26-native.json')
                measurements.update(timing)
                status = timing['verdict']
                bounds = json.loads((project /
                    'requirements/base_13/prelayout_timing_targets.json').read_text())
                for corner in sta._corners(folder):
                    counts = sta.check_setup_counts((corner / 'checks.rpt').read_text(),
                                                    sta.supply_names(config))
                    if counts is None:
                        status = 'NOT_MEASURED' if status != 'FAIL' else status
                    elif any(counts.values()):
                        status = 'FAIL'
                    for metric, limits in bounds['limits'].items():
                        measured = timing['corners'][corner.name][metric]
                        if bounds['units'][metric] != 'ns' or measured['status'] != 'MEASURED':
                            status = 'NOT_MEASURED' if status != 'FAIL' else status
                        elif ('min' in limits and measured['value'] < limits['min']
                              or 'max' in limits and measured['value'] > limits['max']):
                            status = 'FAIL'
            result['reason'] = step + '_RETAINED_NATIVE_REPORT'
        if error_counts is not None:
            if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                   or v != int(v) for v in error_counts):
                raise ValueError('invalid native error count')
            status = 'FAIL' if any(error_counts) or timing_failed else 'PASS'
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        failed = status == 'FAIL' or failed or timing_failed or physical and any(
            type(v) in (int, float) and math.isfinite(v) and v > 0
            for observed in measurements.values() for k, v in observed.items() if k != 'report')
        status = 'FAIL' if failed else 'NOT_MEASURED'
        result.update(reason=step + '_NATIVE_REPORT_UNAVAILABLE', detail=str(exc))
    if method == 'report':
        result.update(reason=step + '_NATIVE_REPORT_' + status, detail=result.get('detail'))
    return {**result, 'component_status': status, 'default_row_status': status,
            'completed': status == 'PASS', 'flow109_acceptance': status}


def prepare_front_door(args, project: Path) -> int | None:
    """Return an exit code for planning/refusal, or continue the real front door."""
    if args.flow != "109":
        if args.flow109_manifest or args.flow109_plan_only:
            raise Flow109Error("FLOW109_SELECTION_REQUIRED", "use --flow 109")
        # A stale parent selection cannot turn a later 70-flow launch into 109.
        os.environ.pop(CONTEXT_ENV, None)
        os.environ.pop(ATTEMPT_ENV, None)
        return None
    # The existing policy parser uses None for an omitted mode and resolves
    # it to Default. Preserve that CLI contract rather than demanding a flag.
    if args.execution_mode not in (None, "default"):
        raise Flow109Error("FLOW109_MODE_UNIMPLEMENTED", "109 currently selects Default only")
    prepare_task_features(args, project)
    manifest = _execution_manifest(args)
    plan = resolve_plan(manifest.get("features"), manifest.get("step_profiles"))
    context = execution_context(plan, args.entry_step, args.exit_step,
                                runtime_tool_uses=manifest.get("runtime_tool_uses", manifest.get("tool_uses")),
                                qualification_registry=manifest.get("qualification_registry"))
    if getattr(args, "delivery_target", None) == "rtl":
        if getattr(args, "route", None) == "ic":
            raise Flow109Error("FLOW109_RTL_SCOPE_CONFLICT", "RTL request also selected physical IC delivery")
        context = execution_context(plan, args.entry_step, args.exit_step,
                                    runtime_tool_uses=context["runtime_tool_uses"],
                                    qualification_registry=context["qualification_registry"],
                                    rtl_scope=_rtl_scope_binding(project, Path(args.flow109_manifest), context))
    else:
        from _delivery_route import report_label
        route = report_label(project, allow_rtl_scope=False).get("delivery_route")
        expected = "IC" if plan["features"]["ic"] else "IP"
        if route != expected:
            raise Flow109Error("FLOW109_ROUTE_CONFLICT", f"manifest endpoint requires {expected}, owner declared {route}")
    import _container_exec
    retained = None if args.flow109_plan_only else _retained_native_result(project, context)
    retry_native = (context.get('resolved_row', {}).get('id') in ('D53', 'D55', 'D59')
                    and retained is not None and retained['component_status'] == 'NOT_MEASURED'
                    and _container_exec.no_container_route())
    if retained is not None and not retry_native:
        from _atomic_artefact import write_json
        write_json(project / 'reports/flow109/plan.json', plan)
        result = _selected_step_result(project, context, retained)
        print(f"FLOW109 {context['requested_step']}: Default row {result['default_row_status']}; "
              "read retained native report; no producer rerun")
        return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[result['default_row_status']]
    dft_contract_rows = {"D22", "D23", "D24", "D25", "D26", "D30", "D50", "D51"}
    registry_rows = load_registry()["rows"]
    positions = {row["id"]: row["position"] for row in registry_rows}
    entry_position, exit_position = positions.get(str(args.entry_step)), positions.get(str(args.exit_step))
    touches_dft_contract = (isinstance(entry_position, int) and isinstance(exit_position, int)
                            and any(entry_position <= positions[row] <= exit_position
                                    for row in dft_contract_rows))
    if plan["features"]["has_digital"] and touches_dft_contract:
        source_intent = dft_source_intent(project, {"features": plan["features"]})
        plan["dft_source_admission"] = source_intent
        if source_intent["requires_scan"] is False:
            reason = source_intent["source_binding"]["intent"]["reason"]
            common = {"reason_code": "FLOW109_REQUIRES_SCAN_FALSE",
                      "reason": reason, "source_validated": True,
                      "source_evidence": source_intent["source_evidence"]}
            skips = []
            if not plan["features"]["requires_dft"]:
                skips.extend({"step_id": step, "position": position, **common}
                             for step, position in (("D23", 35), ("D24", 36)))
            else:
                for row in plan["rows"]:
                    if row["id"] not in ("D23", "D24"):
                        continue
                    for obligation in row.get("obligations", []):
                        if obligation.get("when") == "requires_scan":
                            skips.append({"step_id": row["id"], "metric": obligation["metric"],
                                          "position": row["position"], **common})
            if plan["features"]["physical"]:
                skips.append({"step_id": "D36", "position": 57, **common})
            plan["conditional_skips"] = skips
    from _atomic_artefact import write_json
    destination = project / "reports" / "flow109"
    write_json(destination / "plan.json", plan)
    print(f"FLOW109 PLAN: {plan['selected_count']} selected; runtime NOT_MEASURED")
    if args.flow109_plan_only:
        return 0
    selected_rows = context.get("resolved_rows") or [context.get("resolved_row", {})]
    if len(selected_rows) == 1 and selected_rows[0]['id'] == 'D54':
        import _container_exec
        if _container_exec.no_container_route():
            import path_spice_tool
            current = component_context(context, requested_step='D54')
            selected = json.loads((project / 'reports/phase3/sta_postpnr_signoff.json').read_text())
            native = path_spice_tool.run_case_correlation(project,
                os.environ.get('VIBEIC_EDA_IMAGE'), Path(os.environ['VIBEIC_LIBRELANE_PDK_ROOT']),
                args.pdk, sta_step_dir=Path(selected['sta_state']).parent)
            status = native['verdict']
            _selected_step_result(project, current, {'step_id': 'D54', 'component_status': status,
                'context_sha256': current['context_sha256'],
                'default_row_status': status, 'completed': status == 'PASS', 'native_started': True,
                'wall_seconds': native['wall_seconds'], 'native_result': native})
            return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[status]
    if len(selected_rows) == 1 and selected_rows[0]['id'] == 'D59':
        import _container_exec
        if _container_exec.no_container_route():
            current = component_context(context, requested_step='D59')
            result = retained
            if result is None or result['component_status'] == 'NOT_MEASURED':
                import phase3_one_shot_runner as backend
                native = backend._cvc_from_native_state(project)
                status = native['verdict']
                result = {'step_id': 'D59', 'context_sha256': current['context_sha256'],
                    'component_status': status, 'default_row_status': status,
                    'completed': status == 'PASS', 'native_started': True, 'native_result': native,
                    'wall_seconds': native['wall_seconds']}
            _selected_step_result(project, current, result)
            return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[result['component_status']]
    if len(selected_rows) == 1 and selected_rows[0]['id'] == 'D53':
        import _container_exec
        if _container_exec.no_container_route():
            current = component_context(context, requested_step='D53')
            import librelane_postroute
            native = librelane_postroute.gate_level_sim(project, args.top_name,
                os.environ.get('VIBEIC_EDA_IMAGE'),
                Path(os.environ['VIBEIC_LIBRELANE_PDK_ROOT']), args.pdk)
            status = native['verdict'] if native['verdict'] in ('PASS', 'FAIL') else 'NOT_MEASURED'
            _selected_step_result(project, current, {'step_id': 'D53',
                'context_sha256': current['context_sha256'],
                'component_status': status, 'default_row_status': status, 'completed': status == 'PASS',
                'native_started': True, 'reason': 'NATIVE_DEADLINE_GLS_' + status,
                'wall_seconds': native.get('wall_seconds'), 'native_result': native})
            return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[status]
    try:
        dft_preroute = (dft_preroute_admission(project, component_context(
            context, requested_step="D30"))
            if any(row.get("id") == "D30" for row in selected_rows) else None)
    except Flow109Error as exc:
        if exc.code != 'FLOW109_PREROUTE_NETLIST_MISMATCH':
            raise
        # This is an observed netlist mismatch, not missing evidence.  Refuse
        # before the D30 producer and preserve the measured FAIL status.
        write_json(destination / 'admission.json', {
            'step_id': 'D30', 'status': 'FAIL', 'reason': exc.code,
            'detail': exc.detail, 'native_started': False,
            'flow109_acceptance': 'NOT_MEASURED'})
        print(f'FLOW109 D30: FAIL {exc.code}; native delivery not started')
        return 1
    # Native analog steps consume ordinary design configuration and artifacts.
    # Qualification documents are not a prerequisite for running these tools.
    if getattr(args, "container", None):
        os.environ["VIBEIC_ANALOG_CONTAINER"] = str(args.container)
    if context["schema"] == "vibeic.flow109.execution-window.v1":
        if context["dispatch_kind"] == "canonical_owner_window":
            attempt = _new_attempt(project, context)
            path = destination / "requests" / (context["context_sha256"] + ".json")
            write_json(path, context)
            os.environ[CONTEXT_ENV] = str(path.resolve())
            os.environ[ATTEMPT_ENV] = str(attempt.resolve())
            owner = context["resolved_rows"][0]["profile"]["dispatch"]["owner_runner"]
            write_json(destination / "owner_route.json", {
                "schema": "vibeic.flow109.owner-route.v1",
                "context_sha256": context["context_sha256"],
                "registry_sha256": context["registry_sha256"],
                "planner_sha256": context["planner_sha256"],
                "owner_runner": owner,
                "entry_step": context["native_entry_step"],
                "exit_step": context["native_exit_step"],
                "component_status": "NOT_MEASURED",
                "flow109_acceptance": "NOT_MEASURED",
                "native_started": False,
                **({"dft_preroute_admission": dft_preroute}
                   if dft_preroute is not None else {}),
            })
            args.entry_step = context["native_entry_step"]
            args.exit_step = context["native_exit_step"]
            return None
        window_admission = source_owned_native_admission(context)
        # Ordinary Default windows use the registered existing native owners.
        # Each launch retains its native input and current-source checks;
        # explicit qualification claims keep the strict inventory path.
        source_owned_window = (
            context["dispatch_kind"] == "ordered_adapters"
            and all(source_owned_native_admission(component_context(
                context, requested_step=row["id"])) is not None
                    for row in context["resolved_rows"])
        )
        if window_admission is None and not source_owned_window:
            _window_inventory(context)
        attempt = _new_attempt(project, context)
        path = destination / "requests" / (context["context_sha256"] + ".json")
        write_json(path, context)
        os.environ[CONTEXT_ENV] = str(path.resolve())
        os.environ[ATTEMPT_ENV] = str(attempt.resolve())
        if context["dispatch_kind"] == "selected_native_sequence":
            layout = _selected_native_sequence(context["resolved_rows"])
            if layout is None:
                raise Flow109Error("FLOW109_WINDOW_DISPATCH_UNSUPPORTED",
                                   "selected native sequence changed")
            write_json(destination / "admission.json", window_admission or {
                "status": "NOT_MEASURED", "reason": "PER_LAUNCH_REVALIDATION_REQUIRED",
                "context_sha256": context["context_sha256"], "native_started": False})
            components = []
            for row in context["resolved_rows"][:layout["adapter_count"]]:
                current = component_context(context, requested_step=row["id"])
                adapter = row["profile"]["dispatch"]["adapter"]
                try:
                    from flow109_admission import require_admission, AdmissionRefusal
                    if source_owned_native_admission(current) is None:
                        require_admission(project, current)
                    from importlib import import_module
                    result = import_module(adapter).execute(project, current)
                except AdmissionRefusal as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": str(exc),
                              "qualification": exc.report, "native_started": False,
                              "context_sha256": current["context_sha256"],
                              "flow109_acceptance": "NOT_MEASURED",
                              "whole_flow_acceptance": "NOT_MEASURED"}
                except Flow109Error as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": exc.detail,
                              "native_started": False,
                              "context_sha256": current["context_sha256"],
                              "flow109_acceptance": "NOT_MEASURED",
                              "whole_flow_acceptance": "NOT_MEASURED"}
                result = _selected_step_result(project, current, result, import_module(adapter))
                # The window identity, rather than a one-row derived identity,
                # binds this retained component into the later aggregate.
                result = dict(result, context_sha256=context["context_sha256"])
                components.append(result)
                write_json(destination / "components" / (row["id"] + ".json"), result)
                if result["default_row_status"] != "PASS":
                    for later in context["resolved_rows"][len(components):]:
                        missing = _not_executed_component(
                            context, later, "not executed: an earlier row stopped")
                        components.append(missing)
                        write_json(destination / "components" / (later["id"] + ".json"), missing)
                    finished = _attempt_result(context, components)
                    _finish_attempt(attempt, finished)
                    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[
                        finished["default_row_status"]]
            args.entry_step = layout["backend_entry_step"]
            args.exit_step = layout["backend_exit_step"]
            return None
        if context["dispatch_kind"] == "ordered_adapters":
            if all(row["profile"]["dispatch"].get("adapter") == "analog_native_flow"
                   for row in context["resolved_rows"]):
                from analog_native_flow import execute_window, _aggregate
                native = execute_window(project, context)
                components = []
                for row in context["resolved_rows"]:
                    results = [item for item in native["steps"] if item["step"] == row["id"]]
                    result = {"step_id": row["id"], "component_status": _aggregate(results),
                              "flow109_acceptance": "NOT_MEASURED",
                              "native_results": {"steps": results, "attempt": native.get("attempt")},
                              "reason": native.get("reason", "native analog window executed")}
                    components.append(result)
                    write_json(destination / "components" / (row["id"] + ".json"), result)
                _finish_attempt(attempt, {
                    "schema": "vibeic.flow109.window-attempt-result.v1",
                    "context_sha256": context["context_sha256"],
                    "component_status": native["window_verdict"], "components": components,
                    "flow109_acceptance": "NOT_MEASURED", "whole_flow_acceptance": "NOT_MEASURED",
                    "bounded": True, "delivery_accepted": False})
                return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[native["window_verdict"]]
            components = []
            for row in context["resolved_rows"]:
                current = component_context(context, requested_step=row["id"])
                adapter = row["profile"]["dispatch"]["adapter"]
                try:
                    from flow109_admission import require_admission, AdmissionRefusal
                    if source_owned_native_admission(current) is None:
                        require_admission(project, current)
                    from importlib import import_module
                    result = import_module(adapter).execute(project, current)
                except AdmissionRefusal as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": str(exc),
                              "qualification": exc.report, "native_started": False,
                              "flow109_acceptance": "NOT_MEASURED"}
                except Flow109Error as exc:
                    result = {"schema": "vibeic.flow109.window-component.v1",
                              "step_id": row["id"], "component_status": "NOT_MEASURED",
                              "reason": exc.code, "detail": exc.detail,
                              "native_started": False,
                              "flow109_acceptance": "NOT_MEASURED"}
                result = _selected_step_result(project, current, result, import_module(adapter))
                components.append(result)
                write_json(destination / "components" / (row["id"] + ".json"), result)
                if result["default_row_status"] != "PASS":
                    break
            finished = _attempt_result(context, components)
            _finish_attempt(attempt, finished)
            return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[finished["default_row_status"]]
        write_json(destination / "admission.json", window_admission or {
            "status": "NOT_MEASURED", "reason": "PER_LAUNCH_REVALIDATION_REQUIRED",
            "context_sha256": context["context_sha256"], "native_started": False})
        args.entry_step = context["native_entry_step"]
        args.exit_step = context["native_exit_step"]
        return None
    owner_dispatch = _canonical_owner_dispatch(context["resolved_row"])
    if owner_dispatch is not None:
        attempt = _new_attempt(project, context)
        path = destination / "requests" / (context["context_sha256"] + ".json")
        write_json(path, context)
        os.environ[CONTEXT_ENV] = str(path.resolve())
        os.environ[ATTEMPT_ENV] = str(attempt.resolve())
        write_json(destination / "owner_route.json", {
            "schema": "vibeic.flow109.owner-route.v1",
            "context_sha256": context["context_sha256"],
            "registry_sha256": context["registry_sha256"],
            "planner_sha256": context["planner_sha256"],
            "owner_runner": owner_dispatch["owner_runner"],
            "native_step_id": owner_dispatch["native_step_id"],
            "entry_step": owner_dispatch["owner_entry_step"],
            "exit_step": owner_dispatch["owner_exit_step"],
            "component_status": "NOT_MEASURED",
            "flow109_acceptance": "NOT_MEASURED",
            "native_started": False,
            **({"dft_preroute_admission": dft_preroute}
               if dft_preroute is not None else {}),
        })
        args.entry_step = owner_dispatch["owner_entry_step"]
        args.exit_step = owner_dispatch["owner_exit_step"]
        return None
    # Source-registered Default component owners retain their existing native
    # input/tool/consumer checks, like canonical_owner_window.  Every route
    # that explicitly claims generic qualification remains on strict admission.
    admission = source_owned_native_admission(context)
    if admission is None:
        from flow109_admission import require_admission
        admission = require_admission(project, context)
        if not isinstance(admission, dict) or admission.get("status") != "PASS":
            raise Flow109Error("FLOW109_ADMISSION_REFUSED", "qualification did not return PASS")
    write_json(destination / "admission.json", admission)
    path = destination / "requests" / (context["context_sha256"] + ".json")
    write_json(path, context)
    os.environ[CONTEXT_ENV] = str(path.resolve())
    attempt = _new_attempt(project, context)
    os.environ[ATTEMPT_ENV] = str(attempt.resolve())
    adapter = context['resolved_row']['profile']['dispatch'].get('adapter')
    if adapter:
        # Only source-owned dispatch data selects this bounded adapter. It
        # calls existing producers/consumers and retains their actual receipts.
        from importlib import import_module
        result = import_module(adapter).execute(project, context)
        result = _selected_step_result(project, context, result, import_module(adapter))
        write_json(destination / 'components' / (context['requested_step'] + '.json'), result)
        _finish_attempt(attempt, _attempt_result({**context, "resolved_rows": [context["resolved_row"]]},
                                                 [result]))
        row_status = result['default_row_status']
        print(f"FLOW109 {context['requested_step']}: component {result['component_status']}; "
              f"Default row {row_status}; flow acceptance NOT_MEASURED")
        return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[row_status]
    args.entry_step = context["native_step_id"]
    args.exit_step = context["native_step_id"]
    return None
