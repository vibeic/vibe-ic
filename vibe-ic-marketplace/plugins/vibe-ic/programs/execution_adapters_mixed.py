"""Registry adapters for the existing fixed mixed-signal producer sequence.

Each canonical row has one source-owned candidate.  The candidate invokes the
ordinary producer and its existing consumers; it does not implement a second
mixed-signal flow or qualify native tools by installation alone.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import execution_modes as em
from execution_provider_catalog import (current_source_identity, source_closure,
                                        implementation_closure)

HERE = Path(__file__).resolve().parent
FLOW = HERE.parent / "flow/phase1_phase2_phase3.yaml"
PORTFOLIO = HERE / "data/execution_modes_portfolio.json"
IDS = ("M1", "M2", "M3", "M4")
M2_SIDECAR_OUTPUTS = (
    "reports/analog/mixed_signal/power_domain_tool/netlist.json",
    "reports/analog/mixed_signal/power_domain_tool/yosys.log",
    "reports/analog/mixed_signal/power_domain_tool/read.ys",
)
PRODUCERS = {
    "M1": "mixed_signal_top_lvs_run",
    "M2": "mixed_signal_power_domain_run",
    "M3": "mixed_signal_m3_run",
    "M4": "mixed_signal_signoff_run",
}
OUTPUTS = {
    "M1": ("phase3/mixed_signal/top_merged.gds",
           "reports/analog/mixed_signal/merge.json",
           "reports/analog/mixed_signal/top_lvs.json",
           "reports/analog/mixed_signal/top_lvs_run.json"),
    "M2": ("reports/analog/mixed_signal/power_domain.json",
           "reports/analog/mixed_signal/level_shifter.json",
           "reports/analog/mixed_signal/isolation.json",
           "reports/analog/mixed_signal/pd_connectivity.json",
           "reports/analog/mixed_signal/power_domain_run.json",
           *M2_SIDECAR_OUTPUTS),
    "M3": ("phase3/mixed_signal/cosim/mixed_signal_results.json",
           "reports/analog/mixed_signal/interface_si.json",
           "reports/analog/mixed_signal/m3_run.json"),
    "M4": ("reports/analog/mixed_signal/signoff.json",
           "reports/analog/mixed_signal/top_pv_run.json",
           "reports/phase3/librelane_pv_drc.json", "reports/phase3/librelane_pv_lvs.json",
           "reports/phase3/antenna_librelane.json", "reports/phase3/fill_librelane.json",
           "phase3/librelane_pdk_root.provenance.json"),
}
GATE_REPORTS = {
    "M1": ("reports/analog/mixed_signal/merge.json",),
    "M2": ("reports/analog/mixed_signal/power_domain_native_audit.json",
           "reports/analog/mixed_signal/power_domain_crossing_audit.json",
           "reports/analog/mixed_signal/level_shifter_audit.json",
           "reports/analog/mixed_signal/isolation_audit.json",
           "reports/phase2/gates/power_domain_signal_crossing.json"),
    "M3": ("reports/analog/mixed_signal/cosim_audit.json",
           "reports/analog/mixed_signal/interface_si_audit.json"),
    "M4": ("reports/analog/mixed_signal/signoff_audit.json",),
}
INPUTS = {
    "M1": ("phase1/analog", "phase3/stage3/pnr", "phase3/stage4/gds",
           "phase3/analog/hardmacro"),
    "M2": ("phase3/mixed_signal/top_merged.gds", "phase2/stage2/constraints/*.upf",
           "phase3/stage3/pnr/*_pnr.v", "phase3/stage3/pnr/*.def",
           "input/pdk/liberty/*.lib"),
    "M3": ("phase1/analog/analog_block_list.json", "phase3/mixed_signal/top_merged.gds",
           "phase3/stage3/pnr/*.spef", "phase3/stage3/pnr/*_pnr.v",
           "phase3/stage3/pnr/routed.def", "phase2/stage2/constraints/*.sdc",
           "input/pdk/liberty/**/*.lib", "phase3/analog/**/*.lib",
           "phase3/analog/**/*.v", "phase3/analog/**/*.sp", "phase3/analog/**/*.gds",
           "phase3/analog/**/a7_post_layout.json", "phase3/analog/**/layout_provenance.json",
           "phase3/analog/**/pre_vs_post.json", "phase3/librelane/analog/**/a7_resim/*.sp",
           "input/mixed_signal", "phase1/generated_docs/L22_*.json",
           "input/submission_template"),
    "M4": ("reports/analog/mixed_signal/merge.json",
           "reports/analog/mixed_signal/top_lvs.json",
           "reports/analog/mixed_signal/power_domain.json",
           "reports/analog/mixed_signal/level_shifter.json",
           "reports/analog/mixed_signal/isolation.json",
           "reports/analog/mixed_signal/pd_connectivity.json",
           "reports/analog/mixed_signal/power_domain_run.json",
           "reports/analog/mixed_signal/m3_run.json",
           "reports/analog/mixed_signal/interface_si.json",
           "reports/analog/mixed_signal/top_pv_run.json",
           "phase3/mixed_signal/top_merged.gds",
           "phase3/mixed_signal/cosim/mixed_signal_results.json",
           "reports/phase3/librelane_pv_drc.json",
           "reports/phase3/librelane_pv_lvs.json", "reports/phase3/antenna_librelane.json",
           "reports/phase3/fill_librelane.json", "reports/phase3/librelane_pv_erc.json",
           "input/mixed_signal", "input/pdk/liberty/**/*.lib",
           "phase3/stage3/pnr", "phase3/stage4/gds", "phase3/analog/hardmacro",
           "phase3/librelane"),
}


def validate(outputs: Path, binding: Mapping[str, object]) -> em.Evidence:
    path = Path(outputs) / "mixed-result.json"
    gates = tuple(binding.get("required_gates", ()))
    if not path.is_file() or path.is_symlink():
        return em.Evidence(binding, "NOT_MEASURED", {g: "NOT_MEASURED" for g in gates}, {},
                           detail="MIXED_CURRENT_RECEIPT_ABSENT")
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return em.Evidence(binding, "NOT_MEASURED", {g: "NOT_MEASURED" for g in gates}, {},
                           detail=f"MIXED_RECEIPT_INVALID: {exc}")
    raw_gate_records = value.get("gate_records")
    if not isinstance(raw_gate_records, list):
        return em.Evidence(binding, "NOT_MEASURED", {g: "NOT_MEASURED" for g in gates}, {},
                           detail="MIXED_GATE_CENSUS_INVALID")
    measured_fail = (value.get("producer_verdict") == "FAIL" or
                     any(row.get("verdict") == "FAIL" for row in raw_gate_records
                         if isinstance(row, dict)))
    if value.get("binding") != dict(binding):
        verdict = "FAIL" if measured_fail else "NOT_MEASURED"
        return em.Evidence(binding, verdict, {}, {}, detail="MIXED_RECEIPT_UNBOUND")
    step = str(binding.get("step_id"))
    if step not in IDS or value.get("step_id") != step or value.get("producer") != PRODUCERS[step]:
        return em.Evidence(binding, "NOT_MEASURED", {}, {}, detail="MIXED_SUBJECT_MISMATCH")
    outputs_hashes = {"mixed-result.json": em.digest(path)}
    for name, expected in (value.get("outputs") or {}).items():
        rel = Path(name)
        if (rel.is_absolute() or ".." in rel.parts or
                not (name in OUTPUTS[step] or name in GATE_REPORTS[step] or
                     (step == "M4" and name.startswith("phase3/librelane/")))):
            return em.Evidence(binding, "NOT_MEASURED", {}, {}, detail="MIXED_OUTPUT_PATH_INVALID")
        candidate = Path(outputs) / name
        if (candidate.is_file() and not candidate.is_symlink() and
                em.digest(candidate) == expected):
            outputs_hashes[name] = expected
        elif measured_fail:
            return em.Evidence(binding, "FAIL", {}, outputs_hashes,
                               detail="MIXED_MEASURED_FAIL_OUTPUT_CHANGED: " + str(name))
        else:
            return em.Evidence(binding, "NOT_MEASURED", {}, outputs_hashes,
                               detail="MIXED_OUTPUT_UNMEASURED: " + str(name))
    if step == "M2" and value.get("producer_verdict") == "PASS":
        try:
            from execution_mixed_worker import (_load_m2_receipt,
                                                validate_m2_producer_output_population)
            receipt_path = (Path(outputs) / "project" /
                            "reports/analog/mixed_signal/power_domain_run.json")
            producer_receipt = _load_m2_receipt(receipt_path)
            producer_outputs = validate_m2_producer_output_population(
                producer_receipt, Path(outputs) / "project")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return em.Evidence(binding, "NOT_MEASURED", {}, outputs_hashes,
                               detail=f"MIXED_M2_PRODUCER_OUTPUT_POPULATION_INVALID: {exc}")
        if any(outputs_hashes.get(name) != digest
               for name, digest in producer_outputs.items()):
            return em.Evidence(binding, "NOT_MEASURED", {}, outputs_hashes,
                               detail="MIXED_M2_PRODUCER_OUTPUT_EXPORT_INCOMPLETE")
    gate_states = {}
    gate_rows = {}
    for row in raw_gate_records:
        if isinstance(row, dict) and row.get("gate") in gates:
            gate = row["gate"]
            if gate in gate_rows:
                return em.Evidence(binding, "NOT_MEASURED", {}, outputs_hashes,
                                   detail="MIXED_GATE_DUPLICATE: " + str(gate))
            gate_rows[gate] = row
            verdict = row.get("verdict", "NOT_MEASURED")
            old = gate_states.get(gate)
            gate_states[gate] = ("FAIL" if old == "FAIL" or verdict == "FAIL" else
                                 "NOT_MEASURED" if old == "NOT_MEASURED" or verdict != "PASS" else "PASS")
        else:
            return em.Evidence(binding, "FAIL" if measured_fail else "NOT_MEASURED", {},
                               outputs_hashes, detail="MIXED_GATE_CENSUS_UNBOUND")
    for gate in gates:
        gate_states.setdefault(gate, "NOT_MEASURED")
    producer_verdict = value.get("producer_verdict")
    verdict = ("FAIL" if measured_fail else
               "PASS" if producer_verdict == "PASS" and all(gate_states[g] == "PASS" for g in gates)
               else "NOT_MEASURED")
    if verdict == "PASS" and not set(GATE_REPORTS[step]).issubset(value.get("outputs", {})):
        return em.Evidence(binding, "NOT_MEASURED", gate_states, outputs_hashes,
                           detail="MIXED_GATE_REPORT_ABSENT")
    nested_gate_records = []
    if verdict == "PASS":
        # The mixed adapter intentionally has one outer Controller component;
        # its source-bound worker runs the existing gates in sequence. Expose
        # only exact, successful nested executions to Controller eligibility.
        try:
            from execution_mixed_worker import GATES
            specs = GATES[step]
        except (ImportError, KeyError):
            specs = ()
        project = str((Path(outputs) / "project").resolve())
        expected = {}
        for name, report_path, *flags in specs:
            expected[name] = _nested_gate_argv(name, project, report_path, flags)
        if (set(gate_rows) != set(gates) or set(expected) != set(gates)):
            return em.Evidence(binding, "NOT_MEASURED", gate_states, outputs_hashes,
                               detail="MIXED_GATE_CENSUS_UNBOUND")
        for gate in gates:
            row = gate_rows[gate]
            if (row.get("command") != expected[gate] or row.get("rc") != 0 or
                    row.get("verdict") != "PASS" or
                    not all(isinstance(row.get(k), str) and len(row[k]) == 64
                            for k in ("stdout_sha256", "stderr_sha256"))):
                return em.Evidence(binding, "FAIL" if row.get("verdict") == "FAIL" else "NOT_MEASURED",
                                   gate_states, outputs_hashes,
                                   detail="MIXED_NESTED_GATE_UNBOUND: " + str(gate))
            nested_gate_records.append({**row, "worker_component": "ordinary-mixed-producer"})
    return em.Evidence(binding, verdict, gate_states, outputs_hashes,
                       metrics={"canonical_evidence": 1.0 if verdict == "PASS" else 0.0},
                       detail=str(value.get("detail", "")),
                       provenance={"step_id": step,
                                   "nested_gate_records": nested_gate_records})


def _nested_gate_argv(name: str, project: str, report_path: str,
                      flags: list[str]) -> list[str]:
    """Return the exact worker command using the canonical Python identity."""
    script = str(HERE / (name + ".py"))
    interpreter = str(Path(sys.executable).resolve())
    report = str(Path(project) / report_path)
    if name == "mixed_signal_power_domain_run":
        return [interpreter, script, project, "--check-only", "--json", report]
    return [interpreter, script, project, *flags, "--json", report]


def register_mixed_adapters(registry: em.Registry, *, source_sha: str,
                            path: str = "IC", project: Path,
                            parameters: Mapping[str, object] | None = None):
    source_sha = current_source_identity()
    import _flow_yaml
    rows = {str(row["id"]): row for row in _flow_yaml.load()["steps"]}
    params = dict(parameters or {})
    import execution_adapters_analog as analog
    declaration = analog.declaration_path(Path(project))
    empty_population = (path == "IC" and
        (declaration.exists() or declaration.is_symlink()) and
        not analog._blocks(Path(project), declaration))
    worker = HERE / "execution_mixed_worker.py"
    sources = {Path(__file__), worker, HERE / "execution_modes.py",
               HERE / "execution_provider_catalog.py", HERE / "execution_backend_snapshot.py",
               HERE / "execution_policy.py", HERE / "vibe_ic_one_shot_runner.py",
               HERE / "execution_mixed_subject.py", FLOW, PORTFOLIO}
    sources.update(HERE / name for name in (
        "mixed_signal_top_lvs_run.py", "mixed_signal_merge_check.py",
        "mixed_signal_power_domain_run.py", "power_domain_crossing_check.py",
        "level_shifter_required_check.py", "isolation_cell_required_check.py",
        "power_domain_signal_crossing_check.py", "mixed_signal_m3_run.py",
        "mixed_signal_cosim_check.py", "mixed_signal_interface_si_check.py",
        "mixed_signal_signoff_run.py", "mixed_signal_signoff_check.py"))
    sources.update(HERE.glob("_atomic*.py"))
    sources = source_closure({p.resolve() for p in sources if p.is_file() and not p.is_symlink()})
    sources.update(implementation_closure(worker))
    sources.add(Path(sys.executable).resolve())
    source_files = {str(p): em.digest(p) for p in sorted(sources)}
    # The shared design bootstrap gives Step 9 its typed PdkConfig.  Mixed
    # workers carry only the already-resolved public name in their JSON argv;
    # do not serialize the Step 9 object or resolve a second PDK here.
    pdk = params.get("pdk_name") or params.get("pdk")
    if isinstance(pdk, Mapping):
        pdk = pdk.get("name")
    elif not isinstance(pdk, str):
        pdk = getattr(pdk, "name", None)
    producer_params = {
        "top_name": params.get("top_name") or params.get("top") or "chip_top",
        "container": params.get("container") or "vibeic-eda",
        "pdk": pdk or "auto",
    }
    producer_params["project_subject"] = str(Path(project).resolve(strict=True))
    objective = {"metric": "canonical_evidence", "direction": "max", **producer_params}
    for sid in IDS:
        flow = rows[sid]
        canonical = tuple(flow.get("required_outputs", ()))
        required = tuple(dict.fromkeys((*OUTPUTS[sid], "mixed-result.json")))
        output_contract = {name: (name,) for name in canonical}
        # Bind every current project input that the existing producers may
        # consume.  This intentionally makes missing source artifacts visible
        # as absent current inputs instead of consulting ambient project bytes.
        input_contract = list(INPUTS[sid])
        if sid == "M4":
            # The top-PV consumer follows an issued request whose hash map is
            # the authoritative list of extra material inputs. Bind those
            # exact project-relative files into the arm snapshot as well as
            # the fixed request/configuration files. Invalid or absent request
            # data remains the producer's fail-closed responsibility.
            input_contract.extend(("phase3/librelane_switch.json",
                                   "input/submission_template/tapeout_declaration.json"))
            request_path = Path(project) / "input/mixed_signal/top_pv.json"
            try:
                request_doc = json.loads(request_path.read_text())
            except (OSError, ValueError, TypeError):
                request_doc = {}
            declared = request_doc.get("input_sha256", {}) if isinstance(request_doc, dict) else {}
            if isinstance(declared, dict):
                for name in declared:
                    rel = Path(name)
                    candidate = Path(project) / rel
                    if (not rel.is_absolute() and ".." not in rel.parts and
                            candidate.is_file() and not candidate.is_symlink() and
                            candidate.resolve().is_relative_to(Path(project).resolve())):
                        input_contract.append(rel.as_posix())
        input_contract = tuple(dict.fromkeys(input_contract))
        argv = (str(Path(sys.executable).resolve()), str(worker), "{inputs}", "{outputs}",
                "--step-id", sid, "--params-json", json.dumps(producer_params, sort_keys=True))
        registry.register(em.Adapter(
            arm_id=f"{sid}_ordinary_producer", tool_id="vibeic", step_id=sid,
            source_sha=source_sha, source_files=source_files,
            tool_version="existing ordinary producer; native status comes from current receipts",
            engine_families=("mixed_signal",),
            components=(em.Component("ordinary-mixed-producer", argv, 3600),),
            validate=validate, required_outputs=required, objective=objective,
            applicability="applicable" if path == "IC" and not empty_population else "inapplicable",
            applicability_reason=("mixed-signal is IC-only" if path != "IC" else
                                  "declared analog block population is empty" if empty_population else ""),
            role="producer", qualified=True,
            qualification_evidence="source component is runnable; native tool qualification and producer measurement remain runtime-bound",
            available=True, cpus=1, ram_mb=512,
            own_no_tool_reason="The canonical row uses one existing Vibe-IC producer chain; gates are complementary consumers, not competing tool arms.",
            output_contract=output_contract, input_contract=input_contract))
    return registry


__all__ = ["IDS", "PRODUCERS", "OUTPUTS", "GATE_REPORTS",
           "register_mixed_adapters", "validate"]
