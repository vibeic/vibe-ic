"""Source-owned 109-flow selection and existing Default dispatch bindings.

Selection is not qualification or IC acceptance.  Unimplemented rows remain
visible, and bounded native execution retains the old receipts unchanged.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
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
    """Consume D09 only through the source owner's canonical declaration reader."""
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
    return {
        "schema": "vibeic.flow109.dft-source-intent.v1",
        "source_step": "D01", "source_position": 1,
        "consumer_step": "D22", "consumer_position": 34,
        "requires_scan": requires_scan, "authority": "canonical_d01_spec_declaration",
        "source_binding": dict(binding),
        "source_evidence": {"D01": {
            "path": binding["path"], "sha256": binding["sha256"],
            "sources": binding["sources"]}},
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
        librelane_contract.validate_step_receipt(folder, "OpenROAD.STAPrePNR")
        config = json.loads((folder / "config.json").read_text())
        state_path = folder / "state_out.json"
        state = json.loads(state_path.read_text())
    except Exception as exc:
        raise Flow109Error("FLOW109_D26_SCAN_NATIVE_STALE", mode) from exc
    if (Path(str(config.get("PNR_SDC_FILE") or "")).resolve()
            != (Path(project) / constraint_ref["path"]).resolve()
            or Path(str(state.get("nl") or "")).resolve()
            != (Path(project) / adopted["path"]).resolve()):
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
                and (gate.get("netlist_sha256") != adopted["sha256"]
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
    if intent["requires_scan"]:
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
    lec, lec_ref = _bound_project_json(project, _LEC_REPORT, "FLOW109_D25_PROOF_MISSING")
    if lec.get("verdict") != "PASS" or lec.get("equivalent") is not True:
        raise Flow109Error("FLOW109_D25_PROOF_NOT_ACCEPTED", str(_LEC_REPORT))
    import lec_gate_netlist_select as netlists
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
    chain = {"status": "NOT_APPLICABLE", "reason": "requires_scan is false"}
    if is_scan:
        if Path(rel) != _D24_NETLIST:
            raise Flow109Error("FLOW109_D30_PRE_SCAN_SUBSTITUTION", rel)
        if d24.get("adopted_netlist") != adopted:
            raise Flow109Error("FLOW109_D30_D24_IDENTITY_MISMATCH", rel)
        chain = {"status": "REALIZED_NATIVE", "report": report_ref,
                 "internal_chain_length": values[0],
                 "boundary_chain_length": values[1],
                 "input_flop_count": values[2]}
    timing_modes = _d26_timing_modes_binding(
        project, _d26, intent, top, report=report, report_ref=report_ref,
        adopted=adopted)
    return {
        "schema": "vibeic.flow109.dft-preroute-admission.v1",
        "consumer_step": "D30", "consumer_position": 42,
        "top": top, "requires_scan": intent["requires_scan"], "adopted_netlist": adopted,
        "profile_identity": {"features_sha256": digest(context["features"]),
                             "step_profiles_sha256": digest(context["step_profiles"])},
        "native_chain": chain, "dft_plan_reference": plan_ref,
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


def _tool_uses(row: dict, profile: dict) -> list[dict]:
    """Use identities are source-owned purposes, not caller-selected tool names."""
    dispatch = profile.get("dispatch")
    if dispatch is None:
        return []
    return [{"use_id": f"flow109.{row['id']}.{profile['id']}.{tool}",
             "tool_id": tool, "purpose": f"{row['id']}.{profile['id']}",
             "native_step_id": dispatch["native_step_id"],
             "native_steps": dispatch.get("engine_steps", {}).get(tool, profile.get("native_steps", [])),
             "executable_name": dispatch.get("engine_executables", {}).get(tool, tool),
             "qualification_required": True}
            for tool in dispatch["engine_families"]]


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
    if actual is None and owner == "design_one_shot_runner" and entry in ("8", "10", "11", "12"):
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
    if not isinstance(dispatch, Mapping) or profile.get("id") != "default":
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
        if adapter == "analog_native_flow":
            # The registered analog table owns both legacy A1 and stable
            # A01-A19 entries; reuse the same native admission as digital.
            from analog_native_flow import STEPS
            legacy = {str(item.get("id")) for item in row.get("legacy70", ())
                      if isinstance(item, Mapping)}
            invalid = (common_invalid or row.get("id") not in STEPS
                       or dispatch.get("operation_scope") != "native_analog_step"
                       or not (HERE / "analog_native_flow.py").is_file()
                       or native not in legacy | {"flow109." + str(row.get("id"))})
        elif adapter == "flow109_frontend":
            identities = {
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
                       or not isinstance(adapter, str) or not adapter.startswith("flow109_")
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
    # An explicit runtime/registry request is a qualification claim and stays
    # on the strict generic path.  The Default engineering route is selected
    # only by omitting both; callers cannot use this policy to rescue bad,
    # stale or unsupported qualification evidence.
    if (context.get("runtime_tool_uses") is not None
            or context.get("qualification_registry") is not None):
        return None
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
                      runtime_tool_uses=None, qualification_registry=None) -> dict:
    window = resolve_execution_window(plan, entry, exit_)
    schema = ("vibeic.flow109.execution-context.v1" if "requested_step" in window
              else "vibeic.flow109.execution-window.v1")
    context = {"schema": schema,
               **{key: plan[key] for key in ("registry_sha256", "planner_sha256", "legacy_flow_sha256",
                                             "features", "step_profiles")},
               **window, "runtime_tool_uses": copy.deepcopy(runtime_tool_uses),
               "qualification_registry": qualification_registry}
    context["context_sha256"] = digest(context)
    return context


def validate_execution_context(context: Mapping) -> dict:
    if not isinstance(context, Mapping):
        raise Flow109Error("FLOW109_CONTEXT_INVALID", "expected object")
    keys = (_WINDOW_CONTEXT_KEYS
            if context.get("schema") == "vibeic.flow109.execution-window.v1"
            else _CONTEXT_KEYS)
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
                                 qualification_registry=context["qualification_registry"])
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
        qualification_registry=context["qualification_registry"])


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
    if callable(consume) and not (result.get("completed") is True
                                  and result.get("default_row_status") in ("PASS", "FAIL", "NOT_MEASURED")):
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
    if row["id"] == "D24" and status == "PASS":
        report, report_ref = _bound_project_json(
            project, _SCAN_REPORT, "FLOW109_D24_SCAN_REPORT_MISSING")
        netlist = project / _D24_NETLIST
        if (report.get("published") is not True
                or netlist.is_symlink() or not netlist.is_file()
                or not netlist.resolve().is_relative_to(Path(project).resolve())):
            raise Flow109Error("FLOW109_D24_ADOPTED_NETLIST_UNBOUND", str(_D24_NETLIST))
        answer["adopted_netlist"] = {
            "artifact_id": "D24_POST_SCAN_NETLIST",
            "path": _D24_NETLIST.as_posix(), "sha256": _file_digest(netlist)}
        answer["native_scan_report"] = report_ref
    if row["id"] == "D30" and status == "PASS":
        answer["dft_preroute_admission"] = dft_preroute_admission(project, context)
    from _atomic_artefact import write_json
    write_json(project / "reports/flow109/default_rows" / (row["id"] + ".json"), answer)
    return answer


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
    if not args.flow109_manifest:
        raise Flow109Error("FLOW109_MANIFEST_REQUIRED", "supply explicit resolved features")
    try:
        manifest = json.loads(Path(args.flow109_manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Flow109Error("FLOW109_MANIFEST_INVALID", str(exc)) from exc
    if not isinstance(manifest, dict):
        raise Flow109Error("FLOW109_MANIFEST_INVALID", "expected object")
    if "tool_uses" in manifest and "runtime_tool_uses" in manifest:
        raise Flow109Error("FLOW109_MANIFEST_INVALID", "duplicate runtime tool identity fields")
    plan = resolve_plan(manifest.get("features"), manifest.get("step_profiles"))
    from _delivery_route import report_label
    route = report_label(project).get("delivery_route")
    expected = "IC" if plan["features"]["ic"] else "IP"
    if route != expected:
        raise Flow109Error("FLOW109_ROUTE_CONFLICT", f"manifest endpoint requires {expected}, owner declared {route}")
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
    context = execution_context(plan, args.entry_step, args.exit_step,
                                runtime_tool_uses=manifest.get("runtime_tool_uses", manifest.get("tool_uses")),
                                qualification_registry=manifest.get("qualification_registry"))
    selected_rows = context.get("resolved_rows") or [context.get("resolved_row", {})]
    dft_preroute = (dft_preroute_admission(project, component_context(
        context, requested_step="D30"))
        if any(row.get("id") == "D30" for row in selected_rows) else None)
    # The registered package/test consumer needs the same original catalogue
    # and pad producer inputs after checkpoint relocation. Restore exact bytes
    # only through the existing current-native-owner transport, before it runs.
    import librelane_postroute as _continuation_postroute
    if (any(row.get("id") == "D75" for row in
            (context.get("resolved_rows") or [context.get("resolved_row", {})]))
            and (project / _continuation_postroute.STEP23_RECORD).is_file()):
        from execution_adapters_backend import restore_continuation_prerequisites
        restore_continuation_prerequisites(project)
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
