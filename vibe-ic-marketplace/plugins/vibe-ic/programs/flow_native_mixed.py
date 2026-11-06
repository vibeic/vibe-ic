"""Connect mixed-signal rows to their existing producers."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time
import vibeic_temp


NATIVE_STEPS = dict(zip((
    "mixed_signal_interface_contract", "pre_layout_mixed_signal_verification", "analog_macro_integration",
    "mixed_signal_power_domains", "substrate_and_supply_coupling", "candidate_mixed_signal_scenarios",
    "complete_top_level_layout_assembly", "final_geometry_mixed_signal_scenarios", "mixed_signal_signoff",
), (f"M{number:02d}" for number in range(1, 10))))

def _result(name, ran=False, status="NOT_MEASURED", detail="", metrics=None, reports=(), steps=(), elapsed=0):
    code = 1 if status == "FAIL" else 0 if ran else None
    native = list(steps) or [{"name": name, "ran": ran, "exit_code": code,
                               "status": status, "detail": detail}]
    return {"ran": ran, "exit_code": code, "metrics": metrics or {},
            "reports": list(map(str, reports)), "tool_seconds": elapsed,
            "detail": detail, "native_steps": native}


def _top(project, tool, config):
    from flow_config import resolve_rtl_inputs
    top = tool.get("top") or config.get("DESIGN_NAME")
    if top:
        return top
    document = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    if document.is_file():
        data = json.loads(document.read_text())
        top = data.get("top_module") or data.get("fields", {}).get("top_module")
        if top:
            return top
    try:
        _, top = resolve_rtl_inputs(project)
        if top:
            return top
    except FileNotFoundError:
        pass
    from mixed_signal_top_lvs_run import resolve_top
    return resolve_top(project)[0]


def _m01(project, directory):
    import analog_digital_interface_check as audit
    result = audit.run_audit(project)
    report = directory / "mixed_interface.json"
    report.write_text(json.dumps(asdict(result), indent=2) + "\n")
    skipped = result.summary.get("skipped", False)
    status = "NOT_MEASURED" if skipped else "PASS" if result.passed else "FAIL"
    detail = ("Interface documentation audit only; no electrical measurement. " +
              (str(result.summary.get("reason")) if skipped else ""))
    metrics = {"interface_errors": result.summary["errors"]} if "errors" in result.summary else {}
    return _result("analog_digital_interface_check", True, status, detail, metrics, [report])


def _m3(project, directory, top, container):
    import mixed_signal_m3_run as m3
    result = m3.produce(project, top, container)
    steps = []
    for row in result.get("execution", []):
        command = row.get("command") or []
        code = row.get("exit_code")
        steps.append({"name": Path(command[0]).name if command else "mixed_signal_m3_run",
                      "ran": True, "exit_code": code,
                      "status": "FAIL" if code else "PASS", "detail": row.get("stage", "")})
    reports, metrics, reasons = [], {}, []
    for kind, path in m3.OUTPUTS.items():
        file = project / path
        if not file.is_file():
            reasons.append(f"{kind} report absent")
            continue
        reports.append(file)
        data = json.loads(file.read_text())
        reasons.extend(data.get("blockers", []))
        for scenario in data.get("scenarios", []):
            if scenario.get("reason"):
                reasons.append(str(scenario["reason"]))
            for key, value in scenario.get("metrics", {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics[f"{scenario.get('id', 'scenario')}.{key}"] = value
            for criterion in scenario.get("criteria", []):
                key = criterion.get("native_metric") or criterion.get("metric")
                if not key:
                    continue
                prefix = f"{scenario.get('id', 'scenario')}.{key}"
                for field in ("measured", "min", "max"):
                    value = criterion.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        metrics[prefix if field == "measured" else f"{prefix}.{field}"] = value
    ran = bool(steps)
    status = result.get("verdict", "NOT_MEASURED")
    status = status if status in ("FAIL", "PASS") and ran else "NOT_MEASURED"
    if status == "PASS" and not result.get("full_design_verified", False):
        status = "NOT_MEASURED"
        reasons.append("Native mixed-signal scenario is bounded; full design verification was not measured")
    if status == "NOT_MEASURED":
        steps.append({"name": "mixed_signal_coverage", "ran": False, "exit_code": None,
                      "status": status, "detail": "; ".join(reasons) or "Mixed-signal coverage not measured"})
    elif status == "FAIL":
        steps.append({"name": "mixed_signal_measurement", "ran": True, "exit_code": 1,
                      "status": "FAIL", "detail": "; ".join(reasons) or "A native scenario or interface measurement failed"})
    return _result("mixed_signal_m3_run", ran, status, "; ".join(reasons), metrics, reports, steps)


def _lvs(project, top, pdk, container):
    import mixed_signal_top_lvs_run as lvs
    resolved_top, ts = lvs.resolve_top(project, top)
    resolved_pdk, ps = lvs.resolve_pdk(project, pdk)
    result = lvs.run(project, resolved_top, container, resolved_pdk, pdk_source=ps, top_source=ts)
    compared = bool(result.get("compared")) or (result.get("verdict") in ("PASS", "FAIL") and bool(result.get("lvs_report")))
    ran = compared or bool(result.get("ran")) or bool(result.get("merge_provenance"))
    status = result.get("verdict") if compared else "NOT_MEASURED"
    status = status if status in ("PASS", "FAIL") else "NOT_MEASURED"
    report = result.get("lvs_report")
    return _result("mixed_signal_top_lvs_run", ran, status, result.get("reason", ""),
                   reports=[project / report] if report else [])


def _power(project, directory, top, container):
    import mixed_signal_power_domain_run as power
    paths, libs = power.inputs(project, top)
    power.power_model(paths["upf"], top)
    power.library_cells(libs)
    script, native = directory / "power_domain.ys", directory / "netlist.json"
    quote = lambda p: json.dumps(str(p))
    script.write_text("\n".join([*[f"read_liberty -lib {quote(p)}" for p in libs],
                                 f"read_verilog {quote(paths['netlist'])}",
                                 f"hierarchy -check -top {top}", f"write_json {quote(native)}"]) + "\n")
    code = power.run_tool(script, directory, container)
    if code:
        return _result("yosys", True, "FAIL", f"Yosys rc={code}", reports=[directory / "yosys.log", script])
    if not native.is_file():
        return _result("yosys", True, "NOT_MEASURED", "Yosys did not produce a netlist", reports=[script])
    try:
        evidence = power.derive(paths, libs, top, power.read_json(native))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = getattr(exc, "rule", "")
        status = "FAIL" if reason in {"MISSING_LEVEL_SHIFTER", "MISSING_ISOLATION_CELL", "UNCONNECTED_PROTECTION_CONTROL"} else "NOT_MEASURED"
        return _result("yosys", True, status, (f"{reason}: " if reason else "") + str(exc), reports=[directory / "yosys.log", script, native])
    report = directory / "power_domain.json"
    report.write_text(json.dumps(evidence, indent=2) + "\n")
    measured = evidence.get("power_domain.json", {})
    metrics = {"examined_cells": measured["examined_cells"]} if "examined_cells" in measured else {}
    return _result("yosys", True, "PASS", "Placed structural protection paths only; no electrical or dynamic signoff.", metrics,
                   [directory / "yosys.log", script, native, report])



def _signoff(project, state):
    """Reuse earlier native results, while disclosing their physical scope."""
    files = {
        "lvs": "complete_top_level_layout_assembly",
        "scenarios": "final_geometry_mixed_signal_scenarios",
        "drc": "final_physical_verification",
        "antenna": "antenna_checks",
        "density": "metal_density_fill",
    }
    counts = {
        "drc": ("magic__drc_error__count", "klayout__drc_error__count"),
        "lvs": ("design__lvs_error__count", "design__lvs_unmatched_device__count",
                "design__lvs_unmatched_net__count", "design__lvs_unmatched_pin__count",
                "klayout__lvs_error__count"),
        "antenna": ("antenna__violating__nets", "antenna__violating__pins", "klayout__antenna_error__count"),
        "density": ("klayout__density_error__count", "magic__density_error__count"),
    }
    state_metrics = getattr(state, "metrics", None)
    if state_metrics is None and isinstance(state, dict):
        state_metrics = state.get("metrics", {})
    state_metrics = state_metrics or {}
    steps, reports, numbers, reasons = [], [], {}, []
    for kind, name in files.items():
        path = project / "steps" / name / "result.json"
        row = {}
        try:
            row = json.loads(path.read_text())
            if not isinstance(row, dict):
                raise ValueError("result is not an object")
        except (OSError, ValueError) as exc:
            row = {}
            reason = f"{kind}: native result absent or unreadable ({path}: {exc})"
            if kind in ("lvs", "scenarios"):
                raw = sorted([*(path for parent in (project / "steps", vibeic_temp.current_run())
                                for path in (parent / name).glob("**/mixed_results.json")),
                              *(project / "reports/native").glob(f"*/{name}/**/mixed_results.json")],
                             key=lambda item: item.stat().st_mtime_ns, reverse=True)
                expected = "M07" if kind == "lvs" else "M08"
                for candidate in raw:
                    try:
                        packet = json.loads(candidate.read_text())
                        if packet.get("step") != expected:
                            continue
                        value = packet["result"]
                        native = value.get("native_steps", [])
                        status = ("FAIL" if any(item.get("status") == "FAIL" for item in native)
                                  else "NOT_MEASURED" if not value.get("ran") or any(
                                      item.get("status") == "NOT_MEASURED" for item in native)
                                  else "PASS")
                        row = {"status": status, "tool_ran": value.get("ran"),
                               "tool_exit_code": value.get("exit_code"),
                               "native_metrics": value.get("metrics", {}), "detail": value.get("detail", "")}
                        path = candidate
                        break
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
        if row:
            reports.append(path)
            reason = f"{kind}: reused {name}"
        measured = dict(state_metrics)
        measured.update(row.get("native_metrics") or {})
        if kind == "scenarios":
            for key, value in (row.get("native_metrics") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numbers[key] = value
        else:
            for key in counts[kind]:
                value = measured.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numbers[key] = value
        ran = bool(row.get("tool_ran"))
        status = row.get("status", "NOT_MEASURED") if ran else "NOT_MEASURED"
        if status not in ("PASS", "FAIL"):
            status = "NOT_MEASURED"
        if kind in ("drc", "antenna", "density"):
            status = "NOT_MEASURED"
            reason += "; merged-top " + kind.upper() + " was not measured"
        elif kind == "scenarios" and status == "PASS":
            status = "NOT_MEASURED"
            reason += "; bounded scenarios do not establish full physical mixed-signal coverage"
        elif status == "NOT_MEASURED":
            reason += "; " + (row.get("detail") or "native result not measured")
        if kind in counts and any(key in numbers for key in counts[kind]):
            reason += "; State/source native counts are reported as reused"
        reasons.append(reason)
        steps.append({"name": name, "ran": ran, "exit_code": row.get("tool_exit_code") if ran else None,
                      "status": status, "detail": reason, "reused": bool(row)})
    failed = any(step["status"] == "FAIL" for step in steps)
    ran = any(step["ran"] for step in steps)
    status = "FAIL" if failed else "NOT_MEASURED"
    return _result("mixed_signal_signoff", ran, status, "; ".join(reasons), numbers, reports, steps)

def execute(project, directory, tool, commands, *, state=None, config=None, route=None):
    project, directory, config = Path(project).resolve(), Path(directory).resolve(), config or {}
    directory.mkdir(parents=True, exist_ok=True)
    step = NATIVE_STEPS.get(tool.get("step", ""), "")
    start = time.monotonic()
    try:
        if step == "M01":
            result = _m01(project, directory)
        elif step == "M09":
            result = _signoff(project, state)
        elif step == "M05":
            result = _result("substrate_supply_coupling", detail="M05_SUBSTRATE_SUPPLY_MODEL_UNSUPPORTED_OPEN_DEFAULT: physical substrate and supply coupling extraction model unavailable")
        else:
            top = _top(project, tool, config)
            if not top:
                result = _result(step, detail="Design top is absent from the documents and native configuration")
                result["tool_seconds"] = time.monotonic() - start
                (directory / "mixed_results.json").write_text(json.dumps({"step": step, "result": result}, indent=2) + "\n")
                return result
            container = tool.get("container") or config.get("VIBEIC_EDA_CONTAINER") or "host"
            if step in ("M02", "M06", "M08"):
                result = _m3(project, directory, top, container)
            elif step in ("M03", "M07"):
                result = _lvs(project, top, tool.get("pdk") or config.get("PDK"), container)
            elif step == "M04":
                result = _power(project, directory, top, container)
            else:
                result = _result(step, detail=f"Unknown mixed-signal step {step}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        rule = getattr(exc, "rule", "")
        result = _result(step, detail=(f"{rule}: " if rule else "") + str(exc))
    result["tool_seconds"] = time.monotonic() - start
    (directory / "mixed_results.json").write_text(json.dumps({"step": step, "result": result}, indent=2) + "\n")
    return result
