"""Native power-intent evaluation, power simulation and at-speed ATPG.

Inputs are the actual files and design facts supplied by the caller. Mapped
synthesis uses the same native chain and step table as the public runner.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from _atomic_artefact import write_json

D05_SCHEMA = "vibeic.flow109.power-intent.v1"
D15_SCHEMA = "vibeic.flow109.power-simulation.v1"


class Refusal(ValueError):

    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        (self.code, self.status) = (code, status)
        super().__init__(f"{code}: {detail}")


def _path(project, value):
    path = Path(value["path"] if isinstance(value, dict) else value)
    path = path if path.is_absolute() else Path(project) / path
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def _d05_area(value):
    return (
        isinstance(value, list)
        and len(value) == 4
        and all((isinstance(item, (int, float)) and (not isinstance(item, bool)) for item in value))
        and (value[0] < value[2])
        and (value[1] < value[3])
    )


def _d05_prepare(project, context):
    evaluation = context["evaluation"]
    if (
        not isinstance(context.get("top"), str)
        or not re.fullmatch("[A-Za-z_][A-Za-z0-9_$]*", context["top"])
        or (not re.fullmatch("[A-Za-z_][A-Za-z0-9_$]*", str(evaluation.get("site", ""))))
        or (not _d05_area(evaluation.get("die_area")))
        or (not _d05_area(evaluation.get("core_area")))
        or (not isinstance(evaluation.get("domain_areas"), dict))
        or any(
            (
                not re.fullmatch("[A-Za-z_][A-Za-z0-9_$]*", str(name)) or not _d05_area(area)
                for (name, area) in evaluation["domain_areas"].items()
            )
        )
    ):
        raise ValueError("Native top, site and floorplan areas are required")
    return {
        "manifest": {"top": context["top"]},
        "evaluation": evaluation,
        "upf": _path(project, context["upf"]),
        "rtl": [_path(project, p) for p in context["rtl"]],
        "liberty": _path(project, context["liberty"]),
        "lefs": [_path(project, p) for p in context["lefs"]],
    }


def _d05_tcl_path(path):
    value = str(path)
    if any((char in value for char in "{}\n\r")):
        raise Refusal("D05_INPUT_INVALID", "Tcl-unsafe path")
    return "{" + value + "}"


def _execute_d05(project, context):
    """Run OpenROAD's existing UPF evaluator; keep unsupported row metrics NM."""
    project = Path(project).resolve()
    attempt = project / "reports/phase2/power-intent" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": D05_SCHEMA,
        "step_id": "D05",
        "component_status": "NOT_MEASURED",
        "native_started": False,
    }
    try:
        prepared = _d05_prepare(project, context)
        binary = shutil.which("openroad")
        if not binary:
            raise Refusal("D05_NATIVE_TOOL_ABSENT", "openroad")
        script = [f"read_liberty {_d05_tcl_path(prepared['liberty'])}"]
        script += [f"read_lef {_d05_tcl_path(path)}" for path in prepared["lefs"]]
        script += [f"read_verilog {_d05_tcl_path(path)}" for path in prepared["rtl"]]
        script += [
            f"link_design {prepared['manifest']['top']}",
            f"read_upf -file {_d05_tcl_path(prepared['upf'])}",
            "set block [[[ord::get_db] getChip] getBlock]",
        ]
        for domain, bounds in sorted(prepared["evaluation"]["domain_areas"].items()):
            script.append(f"set_domain_area {domain} -area {{{' '.join(map(str, bounds))}}}")
        script += [
            f"initialize_floorplan -die_area {{{' '.join(map(str, prepared['evaluation']['die_area']))}}} -core_area {{{' '.join(map(str, prepared['evaluation']['core_area']))}}} -site {prepared['evaluation']['site']}",
            'puts "FLOW109_D05_EVALUATE_UPF=PASS"',
        ]
        getters = {
            "domains": "getPowerDomains",
            "power_switches": "getPowerSwitches",
            "isolations": "getIsolations",
            "level_shifters": "getLevelShifters",
        }
        for key, getter in getters.items():
            script += [
                f"set names_{key} {{}}",
                f"foreach obj [$block {getter}] {{ lappend names_{key} [$obj getName] }}",
                f'puts "FLOW109_D05_{key.upper()}=[join [lsort $names_{key}] ,]"',
            ]
        roundtrip = attempt / "roundtrip.upf"
        script.append(f"write_upf {_d05_tcl_path(roundtrip)}")
        tcl = attempt / "read_upf.tcl"
        tcl.write_text("\n".join(script) + "\n", encoding="utf-8")
        record["native_started"] = True
        launched = subprocess.run(
            [binary, "-no_init", "-exit", str(tcl)], text=True, capture_output=True, timeout=300
        )
        log = attempt / "openroad.log"
        log.write_text(launched.stdout + launched.stderr, encoding="utf-8")
        record["native_result"] = {
            "path": str(log.relative_to(project)),
            "returncode": launched.returncode,
        }
        if launched.returncode:
            record.update(
                component_status="FAIL", reason="D05_OPENROAD_READ_OR_EVALUATE_UPF_FAILED"
            )
        elif not re.search("(?m)^FLOW109_D05_EVALUATE_UPF=PASS$", launched.stdout):
            raise Refusal("D05_NATIVE_RESULT_ABSENT", "evaluate_upf")
        else:
            measured = {}
            for key in getters:
                match = re.search(f"(?m)^FLOW109_D05_{key.upper()}=(.*)$", launched.stdout)
                if match is None:
                    raise Refusal("D05_NATIVE_RESULT_ABSENT", key)
                measured[key] = sorted(filter(None, match.group(1).strip().split(",")))
            semantic_objects = sum(
                (len(measured[key]) for key in ("power_switches", "isolations", "level_shifters"))
            )
            if not measured["domains"] or semantic_objects == 0:
                record.update(
                    component_status="FAIL", reason="D05_NATIVE_SEMANTIC_POPULATION_MISSING"
                )
            else:
                reason = "D05_NATIVE_STATE_AND_SUPPLY_ANALYSIS_UNAVAILABLE"
                record["metrics"] = {
                    "native_structure": {
                        "status": "PASS",
                        "mechanism": "read_upf -> initialize_floorplan -> upf::eval_upf",
                        "population": measured,
                        "roundtrip_upf": {"path": str(roundtrip.relative_to(project))},
                    },
                    "semantic_demand_coverage": {"status": "NOT_MEASURED", "reason": reason},
                    "illegal_power_states": {"status": "NOT_MEASURED", "reason": reason},
                    "supply_cell_assignments": {"status": "NOT_MEASURED", "reason": reason},
                }
                record.update(component_status="PASS", reason=reason)
    except Refusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        record.update(reason="D05_NATIVE_UNAVAILABLE_OR_UNSUPPORTED", detail=str(exc))
    write_json(attempt / "component.json", record)
    return record


def _d15_env():
    return {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ} | {
        "LANG": "C",
        "LC_ALL": "C",
    }


def _d15_json(path):

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def _d15_bound(project, value):
    return _path(project, value)


def _d15_tool():
    binary = shutil.which("xezim")
    if not binary:
        raise FileNotFoundError("xezim")
    return {"executable": binary}


def _d15_prepare(project, context):
    (required, checks) = (context["required"], context["expected_checks"])
    if (
        not isinstance(required, list)
        or not required
        or (not isinstance(checks, dict))
        or (set(checks) != {"isolation", "retention"})
        or any(
            (
                not isinstance(v, list)
                or not v
                or any(
                    (not isinstance(s, str) or not s.startswith("ok   ") or "\n" in s for s in v)
                )
                for v in checks.values()
            )
        )
        or (len({r["id"] for r in required}) != len(required))
        or any(
            (
                r["state"] not in {"up", "down"}
                or not str(r["time"]).isdigit()
                or (not re.fullmatch("[A-Za-z_][\\w$]*", r["domain"]))
                for r in required
            )
        )
    ):
        raise ValueError("Design power transitions and isolation/retention checks are required")
    top = context["top"]
    if not isinstance(top, str) or not re.fullmatch("[A-Za-z_][A-Za-z0-9_$]*", top):
        raise ValueError("Native simulation top module is required")
    rtl = [_path(project, p) for p in context["rtl"]]
    if not rtl:
        raise ValueError("Native simulation RTL is required")
    return {
        "manifest": {"top": top, "expected_checks": checks},
        "rtl": rtl,
        "upf": _path(project, context["upf"]),
        "testbench": _path(project, context["testbench"]),
        "required": required,
    }


def consume_d15(project, context, component):
    """Read native transition coverage and isolation/retention behavior."""
    project = Path(project).resolve()
    answer = {
        "status": "NOT_MEASURED",
        "obligations": [],
        "scope": "declared xezim runtime subset only",
    }
    try:
        prepared = _d15_prepare(project, context)
        out = _d15_bound(project, component["stdout"]).read_text()
        err = _d15_bound(project, component["stderr"]).read_text()
        if re.search("warning|unresolved|ignored|unsupported|not supported", out + err, re.I):
            raise Refusal("D15_NATIVE_FEATURE_UNRESOLVED", "native diagnostic")
        if not re.search("(?m)^Simulation finished at time \\d+ \\(\\$finish called\\)$", out):
            raise Refusal("D15_NATIVE_INCOMPLETE", "no terminal $finish")
        events = {
            (m[0], m[1], m[2])
            for m in re.findall(
                "(?m)^\\[UPF\\] Time: (\\d+), Power domain '([^']+)' is powered (up|down)$", out
            )
        }
        covered = [
            r["id"]
            for r in prepared["required"]
            if (str(r["time"]), r["domain"], r["state"]) in events
        ]
        failures = re.findall("(?mi)^FAIL\\b.*|^.*\\$(?:error|fatal).*|^Error:.*", out + err)
        missing_checks = [
            s
            for values in prepared["manifest"]["expected_checks"].values()
            for s in values
            if s not in out.splitlines()
        ]
        errors = len(failures)
        if missing_checks and (not failures):
            raise Refusal("D15_BEHAVIOR_CHECKS_INCOMPLETE", ", ".join(missing_checks))
        if type(component.get("returncode")) is not int or component["returncode"] != 0:
            raise Refusal("D15_NATIVE_PROCESS_FAILED", str(component.get("returncode")))
        answer["obligations"] = [
            {
                "id": "power_verify.required_power_transitions",
                "observed_value": covered,
                "required_items": [r["id"] for r in prepared["required"]],
                "status": "PASS" if len(covered) == len(prepared["required"]) else "FAIL",
            },
            {
                "id": "power_verify.isolation_retention_behavior_errors",
                "observed_value": errors,
                "status": "PASS" if errors == 0 else "FAIL",
            },
        ]
        answer.update(
            status=(
                "PASS" if all((r["status"] == "PASS" for r in answer["obligations"])) else "FAIL"
            ),
            missing_checks=missing_checks,
            failures=failures,
            scope="declared xezim runtime subset only",
        )
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        answer.update(reason=getattr(exc, "code", "D15_EVIDENCE_INVALID"), detail=str(exc))
    return answer


def _execute_d15(project, context):
    """Existing native engine invocation; publication never grants row credit."""
    project = Path(project).resolve()
    attempt = project / "reports/phase2/power-simulation" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": D15_SCHEMA,
        "step_id": "D15",
        "component_status": "NOT_MEASURED",
        "native_started": False,
    }
    try:
        prepared = _d15_prepare(project, context)
        tool = _d15_tool()
        record["tool"] = tool
        argv = [
            tool["executable"],
            "--simulate",
            "--no-cache",
            "-s",
            prepared["manifest"]["top"],
            "--upf",
            str(prepared["upf"]),
            *map(str, prepared["rtl"]),
            str(prepared["testbench"]),
        ]
        env = _d15_env()
        record.update(argv=argv, native_started=True)
        native = subprocess.run(argv, cwd=attempt, env=env, capture_output=True, text=True)
        record["returncode"] = native.returncode
        for key, value in (("stdout", native.stdout), ("stderr", native.stderr)):
            path = attempt / (key + ".log")
            path.write_text(value)
            record[key] = {"path": str(path.relative_to(project))}
        observed = consume_d15(project, context, record)
        record.update(component_status=observed["status"], observations=observed)
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        record.update(reason=getattr(exc, "code", "D15_NATIVE_INPUT_UNAVAILABLE"), detail=str(exc))
    write_json(attempt / "component.json", record)
    return record


def _execute_dft_tail(project, context):
    project = Path(project).resolve()
    step = context.get("requested_step")
    attempt = project / "reports/phase2/dft" / step / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": "vibeic.flow109.dft-tail-component.v1",
        "step_id": step,
        "component_status": "NOT_MEASURED",
        "native_started": False,
    }
    try:
        argv = [
            str(project),
            "--clock",
            context["clock"],
            "--librelane-state",
            str(context["state"]),
            "--librelane-corner",
            context["corner"],
        ]
        if step == "D50":
            import path_delay_fault_atpg_run as producer
            import path_delay_coverage_check as consumer

            output = project / "reports/phase2/dft/path_delay_coverage.json"
        else:
            import sdd_atpg_run as producer
            import sdd_coverage_check as consumer

            output = project / "reports/phase2/dft/sdd_coverage.json"
        argv += ["--json", str(output)]
        record["native_started"] = True
        rc = producer.main(argv)
        judged = consumer.audit(project, str(output))
        record.update(native_rc=rc, consumer=judged)
        if rc == 0 and judged.get("verdict") == "PASS":
            record.update(component_status="PASS", reason=step + "_EXISTING_CONSUMER_PASSED")
        elif judged.get("verdict") == "FAIL":
            record.update(component_status="FAIL", reason=step + "_EXISTING_CONSUMER_FAILED")
        else:
            record["reason"] = step + "_EXISTING_CONSUMER_NOT_MEASURED"
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        record.update(reason=step + "_NATIVE_UNAVAILABLE_OR_UNSUPPORTED", detail=str(exc))
    write_json(attempt / "component.json", record)
    return record


def execute(project, context):
    step = context.get("requested_step")
    if step == "D05":
        return _execute_d05(project, context)
    if step == "D15":
        return _execute_d15(project, context)
    if step in {"D50", "D51"}:
        return _execute_dft_tail(project, context)
    if step == "D22":
        from dataclasses import asdict
        from flow_engine import NativeChain, TABLE, read_json

        tool = next(
            (row["tool"] for row in read_json(TABLE)["steps"] if row["name"] == "synthesis")
        )
        chain = NativeChain(Path(project), context["route"], pdk=context.get("pdk"))
        directory = Path(project) / "steps/synthesis"
        directory.mkdir(parents=True, exist_ok=True)
        return asdict(chain.execute(directory, tool))
    raise ValueError("Select native power intent, power simulation, synthesis or at-speed ATPG")
