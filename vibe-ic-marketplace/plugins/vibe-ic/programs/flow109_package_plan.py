"""Native pad assignment, test access and bare-die output-load feasibility."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
from typing import Mapping
import uuid

import pad_assignment_gen
import sim_activity_dump
from _atomic_artefact import write_json

IO_REPORT = Path("reports/phase3/io_pad_chip_top.json")
L7_REPORT = Path("phase1/generated_docs/L7_TEST_DEBUG.json")
L8_REPORT = Path("phase1/generated_docs/L8_TIMING_WAVEFORM.json")
L10_REPORT = Path("phase1/generated_docs/L10_TEST_CASES.json")
L20_REPORT = Path("phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json")


class D06Refusal(ValueError):
    def __init__(self, code: str, detail: str, *, failed: bool = False):
        self.code, self.detail, self.failed = code, detail, failed
        super().__init__(f"{code}: {detail}")


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", str(path))
    return value


def _record(project, path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path)}


def _bound_json(project, rel):
    path = project / rel
    return _read(path), _record(project, path)


def _project_path(project, raw, label):
    if not isinstance(raw, str) or not raw:
        raise D06Refusal('D06_NATIVE_INPUT_ABSENT', label)
    path = Path(raw)
    path = path if path.is_absolute() else project / path
    path = path.resolve()
    if not path.is_file():
        raise D06Refusal('D06_NATIVE_INPUT_ABSENT', str(path))
    return path


def _state_inputs(project, options):
    state, config = options.get('state'), options.get('config')
    state_path = None
    if not isinstance(state, Mapping) or not isinstance(config, Mapping):
        raw = options.get('native_state')
        if raw is None:
            report = _read(project / 'reports/phase3/sta_postpnr_signoff.json')
            if (report.get('judgment') or {}).get('verdict') != 'PASS':
                raise D06Refusal('D06_NATIVE_STA_INCOMPLETE', 'selected STA did not pass')
            raw = report.get('sta_state')
        state_path = _project_path(project, raw, 'native State')
        state = _read(state_path)
        config = _read(state_path.with_name('config.json'))
    sdc = _project_path(project, config.get('SIGNOFF_SDC_FILE') or state.get('sdc'), 'native SDC')
    netlist = _project_path(project, state.get('nl'), 'native netlist')
    records = [_record(project, path) for path in (sdc, netlist)]
    if state_path:
        records.extend((_record(project, state_path), _record(project, state_path.with_name('config.json'))))
    return state_path, config, sdc, netlist, records


def _signoff_load_inputs(project):
    return _state_inputs(project, {})


def _scenario_load_inputs(project, selection, output):
    import librelane_prelayout as timing_check
    state_path, config, sdc, netlist, records = _state_inputs(project, selection)
    if state_path is None:
        raise D06Refusal('D06_NATIVE_STA_INPUT_ABSENT', 'native State path is required for timing reports')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    sdc_gate = timing_check.judge_sdc(state_path.parent, config, sdc, output / 'selected_sdc.json')
    slack_gate = timing_check.judge_slack(state_path.parent, output / 'selected_slack.json')
    if sdc_gate.get('verdict') != 'PASS' or slack_gate.get('verdict') != 'PASS':
        raise D06Refusal('D06_NATIVE_STA_INCOMPLETE', 'selected SDC/slack consumer did not pass')
    return state_path, config, sdc, netlist, records


def _expanded_outputs(ports: list[dict]) -> list[str]:
    result = []
    for port in ports:
        if port.get("direction") != "output":
            continue
        name, width, packed = port.get("name"), port.get("width"), port.get("packed")
        if not isinstance(name, str) or not isinstance(width, int) or width < 1:
            raise D06Refusal("D06_CURRENT_NETLIST_PORTS_INVALID", str(port))
        if width == 1:
            result.append(name)
            continue
        match = re.fullmatch(r"\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]", str(packed))
        if not match or abs(int(match[1]) - int(match[2])) + 1 != width:
            raise D06Refusal("D06_CURRENT_NETLIST_PORTS_INVALID", str(port))
        left, right = int(match[1]), int(match[2])
        step = -1 if left > right else 1
        result.extend(f"{name}[{index}]" for index in range(left, right + step, step))
    return sorted(result)


def _current_bare_die_load(project: Path, io: Mapping,
                          output_dir: Path | None = None, *, native: Mapping | None = None) -> tuple[dict, list[dict]]:
    """Bind the load scene consumed by the current STA state to current IO pads."""
    options = native or {}
    if options.get('load_scenario'):
        state_path, config, sdc_path, netlist_path, evidence = _scenario_load_inputs(
            project, options['load_scenario'], output_dir or project / 'reports/native_tools/package_load')
    else:
        state_path, config, sdc_path, netlist_path, evidence = _state_inputs(project, options)
    state_ref = _record(project, state_path) if state_path else None
    top = config.get("DESIGN_NAME")
    if not isinstance(top, str) or not top or not config.get("PDK"):
        raise D06Refusal("D06_CURRENT_STA_AUTHORITY_INVALID", str(state_path or "native configuration"))

    try:
        ports = sim_activity_dump.module_ports(netlist_path, top)
    except (OSError, ValueError) as exc:
        raise D06Refusal("D06_CURRENT_NETLIST_PORTS_INVALID", str(exc)) from exc
    outputs = _expanded_outputs(ports)
    pad_rows = io.get("pad_instances")
    io_outputs = sorted(str(row.get("port")) for row in pad_rows.values()
                        if isinstance(row, Mapping) and row.get("direction") == "output"
                        and row.get("port")) if isinstance(pad_rows, Mapping) else []
    if not outputs or outputs != io_outputs:
        raise D06Refusal("D06_OUTPUT_LOAD_PAD_COVERAGE_MISMATCH",
                         f"netlist={outputs}, io={io_outputs}")

    sdc = sdc_path.read_text(encoding="utf-8")
    active = "\n".join(line.partition("#")[0] for line in sdc.splitlines())
    loads = re.findall(r"(?m)^\s*set_load\s+([0-9.eE+-]+)\s+\[all_outputs\]\s*$", active)
    delays = re.findall(
        r"(?m)^\s*set_output_delay\s+([0-9.eE+-]+)\s+-clock\s+([A-Za-z_][A-Za-z0-9_$]*)\s+\[all_outputs\]\s*$",
        active)
    explicit = re.findall(
        r"(?m)^\s*set_load\s+([0-9.eE+-]+)\s+\[get_ports\s+\{([^{}]*)\}\]\s*$", active)
    if len(re.findall(r"(?m)^\s*set_load\b", active)) != len(loads) + len(explicit):
        raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_UNRESOLVED", "unsupported output load command")
    per_port = {}
    for value, names in explicit:
        for name in names.split():
            if name in per_port:
                raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_UNRESOLVED", "overlapping output loads")
            per_port[name] = float(value)
    if not loads and per_port and sorted(per_port) == outputs and len(set(per_port.values())) == 1:
        loads = [str(next(iter(per_port.values())))]
    elif explicit:
        raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_UNRESOLVED", "incomplete, mixed or unequal output loads")
    if len(loads) != 1 or len(delays) != 1:
        raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_UNRESOLVED",
                         "one complete output load and all-output delay are required")
    load, delay = float(loads[0]), float(delays[0][0])
    if not math.isfinite(load) or load <= 0 or not math.isfinite(delay) or delay <= 0:
        raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_INVALID", str((load, delay)))

    return {
        "scope": "native bare-die interface; not physical package RLC/escape",
        "deliverable": "DIE",
        "sta_state": state_ref,
        "sdc": _record(project, sdc_path), "netlist": _record(project, netlist_path),
        "output_ports": outputs, "output_port_count": len(outputs),
        "capacitance_library_units": load, "output_delay_ns": delay,
        "load_selector": "explicit_output_ports" if per_port else "all_outputs",
        "physical_package_model_consumed": False,
    }, evidence


def _l20_selected_architecture(l20: Mapping) -> bool:
    fields = l20.get("fields")
    if not isinstance(fields, Mapping):
        raise D06Refusal("D06_DFT_INTENT_UNKNOWN", "L20.fields absent")
    positive = (fields.get("dft_present") is True
                or bool(fields.get("scan_chains")) or bool(fields.get("bist_mbist"))
                or fields.get("jtag_tap") is not None
                or fields.get("test_compression") is not None)
    if positive and fields.get("dft_present") is False:
        raise D06Refusal("D06_DFT_INTENT_CONTRADICTION",
                         "L20 says dft_present=false but carries DFT architecture")
    return positive


def _early_test_access(project: Path, context: Mapping,
                       io: Mapping) -> tuple[dict, list[dict]]:
    """Read the source-declared early functional or scan test-access plan."""
    evidence = []
    docs = {}
    for name, rel in (("l7", L7_REPORT), ("l8", L8_REPORT),
                      ("l10", L10_REPORT), ("l20", L20_REPORT)):
        docs[name], bound = _bound_json(project, rel)
        evidence.append(bound)
    l7, l8, l10, l20 = (docs[k] for k in ("l7", "l8", "l10", "l20"))
    if (l7.get("schema_version") != 2 or l7.get("doc_class") != "test_debug"
            or l10.get("schema_version") != 2 or l20.get("doc_id") != "L20"):
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", "canonical L7/L10/L20 identity")

    features = context.get("resolved_features") or context.get("features")
    if not isinstance(features, Mapping):
        present = _l20_selected_architecture(l20)
        features = {"requires_dft": present, "requires_scan": present}
    dft_values = (features.get("requires_dft"), features.get("requires_scan"))
    if any(type(value) is not bool for value in dft_values):
        raise D06Refusal("D06_DFT_INTENT_UNKNOWN", "requires_dft/requires_scan unresolved")
    selected = any(dft_values)
    l20_positive = _l20_selected_architecture(l20)
    scan = io.get("scan_interface")
    selected_scan = scan.get("selected_scan_netlist") if isinstance(scan, Mapping) else None
    if selected != l20_positive and (selected or l20_positive):
        raise D06Refusal("D06_DFT_INTENT_CONTRADICTION",
                         f"features selected={selected}, L20 selected={l20_positive}")

    if selected:
        chains = l20["fields"].get("scan_chains")
        required = ("name", "scan_in", "scan_out", "scan_enable")
        if (not isinstance(chains, list) or not chains
                or any(not isinstance(chain, Mapping)
                       or any(not chain.get(key) for key in required)
                       for chain in chains)):
            raise D06Refusal("D06_SELECTED_DFT_ARCHITECTURE_MISSING",
                             "L20 scan chain protocol needs name/in/out/enable")
        return {"mode": "selected_dft_architecture", "scan_chains": len(chains),
                "post_dft_physical_access_pending": selected_scan is not True}, evidence

    if selected_scan is not False:
        raise D06Refusal("D06_DFT_INTENT_CONTRADICTION",
                         "unscanned Flow109 route conflicts with current IO selection")
    l7_cases, l10_cases = l7.get("test_scenarios"), l10.get("test_cases")
    keys = ("name", "kind", "stimulus", "expected")
    if (not isinstance(l7_cases, list) or not isinstance(l10_cases, list)
            or not l7_cases or any(not isinstance(row, Mapping)
                                   for row in l7_cases + l10_cases)):
        raise D06Refusal("D06_FUNCTIONAL_TEST_PLAN_MISMATCH", "L7/L10 cases")
    # The normal L7 owner adds named prose scenarios after the shared table
    # cases; L10 owns the shared cases, not that additional verification prose.
    # Retain and source-bind the extra plan instead of demanding a fabricated
    # L10 executable case for it. Shared case population and values stay exact.
    named = [row for row in l7_cases if row.get("kind") == "named_scenario"]
    shared = [row for row in l7_cases if row.get("kind") != "named_scenario"]
    if any(row.get("extraction_strategy") != "named_scenario_list"
           or any(not isinstance(row.get(key), str) or not row[key].strip()
                  for key in ("name", "stimulus", "expected", "evidence")) for row in named):
        raise D06Refusal("D06_FUNCTIONAL_TEST_PLAN_MISMATCH", "unbound named L7 scenario")
    normalized = lambda rows: [{key: row.get(key) for key in keys} for row in rows]
    if (normalized(shared) != normalized(l10_cases)
            or not any(row.get("kind") == "functional_vector" for row in l10_cases)):
        raise D06Refusal("D06_FUNCTIONAL_TEST_PLAN_MISMATCH", "L7/L10 cases")
    l7_sources = l7.get("source_documents")
    if (not isinstance(l7_sources, list) or not l7_sources
            or any(not isinstance(row.get("evidence"), str)
                   or not any(row["evidence"].startswith(source) for source in l7_sources)
                   for row in shared)
            or not set(l7_sources).issubset(set(l10.get("source_documents") or []))):
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", "L7/L10 source documents")

    for row in named:
        sources = [source for source in l7_sources
                   if row["evidence"] == source or row["evidence"] == Path(source).name]
        if len(sources) != 1:
            raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", "named L7 scenario source")
        source = _project_path(project, sources[0], "named L7 scenario source")
        evidence.append(_record(project, source))

    waveform = l8.get("clock_and_reset_waveform")
    if not isinstance(waveform, Mapping):
        raise D06Refusal("D06_FUNCTIONAL_ACCESS_INCOMPLETE", "clock/reset plan absent")
    clocks = {str(row.get("name")) for row in waveform.get("clocks", [])
              if isinstance(row, Mapping) and row.get("name")}
    resets = {str(row.get("name")) for row in waveform.get("resets", [])
              if isinstance(row, Mapping) and row.get("name")}
    pads = io.get("pad_instances")
    pad_rows = list(pads.values()) if isinstance(pads, Mapping) else []
    input_ports = {str(row.get("port")) for row in pad_rows
                   if isinstance(row, Mapping) and row.get("direction") == "input"}
    output_ports = {str(row.get("port")) for row in pad_rows
                    if isinstance(row, Mapping) and row.get("direction") == "output"}
    stimulus = sorted(input_ports - clocks - resets)
    observe = sorted(output_ports)
    if not clocks or not resets or not clocks.issubset(input_ports) \
            or not resets.issubset(input_ports) or not stimulus or not observe:
        raise D06Refusal("D06_FUNCTIONAL_ACCESS_INCOMPLETE",
                         "clock/reset/stimulus/observe pads are required")
    return {"mode": "functional_unscanned", "functional_cases": len(l10_cases),
            "additional_named_verification_scenarios": [dict(row) for row in named],
            "clock_pads": sorted(clocks), "reset_pads": sorted(resets),
            "stimulus_pads": stimulus, "observe_pads": observe,
            "authority": "resolved Flow109 no-DFT route + matched L7/L10 + native IO map"}, evidence


def _current_pdk(project, evidence=None):
    from declared_pdk_is_the_pdk_used_check import declared_target
    pdk, source = declared_target(project)
    if not isinstance(pdk, str) or not pdk:
        raise D06Refusal('D06_PDK_UNAVAILABLE', 'design documents do not select a PDK')
    return pdk


def execute(project: Path, context: Mapping) -> dict:
    project = Path(project).resolve(strict=True)
    attempt = project / 'reports/native_tools/package_plan' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'component_status': 'NOT_MEASURED', 'checks': [], 'inputs': []}
    try:
        config = context.get('config') or {}
        pdk = config.get('PDK') or _current_pdk(project)
        root = config.get('PDK_ROOT') or context.get('pdk_root') or os.environ.get('PDK_ROOT', '/foss/pdks')
        report_path = attempt / 'pad_assignment.json'
        assignment = project / 'phase3/stage3/pnr/pad_assignment.json'
        rc = pad_assignment_gen.main([str(project), '--json', str(report_path), '--out', str(assignment),
                                       '--pdk-root', str(root), '--pdk', pdk])
        producer = _read(report_path)
        record['producer_result'] = producer
        record['checks'].append({'check': 'pad_assignment_gen', 'verdict': producer.get('verdict'), 'rc': rc})
        if rc == 1:
            raise D06Refusal('D06_PAD_ASSIGNMENT_PRODUCER_REFUSED', str(producer.get('reason')), failed=True)
        if rc != 0 or producer.get('verdict') != 'WROTE':
            raise D06Refusal('D06_PAD_ASSIGNMENT_INCOMPLETE', str(producer.get('reason')))
        import io_pad_chip_top_gen
        io_path = project / IO_REPORT
        io_rc = io_pad_chip_top_gen.main([str(project), '--pdk-root', str(root), '--pdk', pdk, '--json', str(io_path)])
        io = _read(io_path)
        if io_rc != 0 or io.get('verdict') != 'WROTE' or not io.get('pad_instances'):
            raise D06Refusal('D06_PAD_PIN_PRODUCER_INCOMPLETE', str(io), failed=io_rc == 1)
        test, test_inputs = _early_test_access(project, context, io)
        load, load_inputs = _current_bare_die_load(project, io, attempt, native=context)
        l1, l1_ref = _bound_json(project, Path('phase1/generated_docs/L1_DATASHEET.json'))
        if l1.get('no_package_in_input') is not True or l1.get('package_info') is not None:
            raise D06Refusal('D06_PHYSICAL_PACKAGE_SCOPE_UNRESOLVED', 'physical package RLC/escape is unmeasured')
        if test.get('mode') != 'functional_unscanned':
            raise D06Refusal('D06_POST_DFT_ACCESS_UNMEASURED', 'this native method covers early functional access')
        record['inputs'] = [_record(project, report_path), _record(project, io_path), l1_ref, *test_inputs, *load_inputs]
        record['metrics'] = {'pad_bump_interface_constraints': {'status': 'PASS', 'scope': 'bare-die pad interface; no bumps',
                               'pad_instances': len(io['pad_instances'])},
                             'package_escape_feasibility': {'status': 'PASS', **load},
                             'test_access_plan': {'status': 'PASS', **test}}
        record.update(component_status='PASS', scope='bare-die pad, external-load and functional-test-access feasibility',
                      unsupported_scope='physical package RLC/escape/bumps and post-DFT access')
    except (D06Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        record.update(component_status='FAIL' if getattr(exc, 'failed', False) else 'NOT_MEASURED',
                      reason=getattr(exc, 'code', 'D06_NATIVE_INPUT_ABSENT'), detail=str(exc))
    write_json(attempt / 'result.json', record)
    return record
