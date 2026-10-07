"""Current subjects for steps 16, 31, 37.3 and 37.5ip.

These records supplement native measurements. They never turn an absent or
failed measurement into PASS. Consumers refuse changed inputs and outputs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = "vibeic.default_physical_current/1"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def entry(project, path, *, external=False):
    project, path = Path(project).resolve(), Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"CURRENT_FILE_EMPTY: {path}")
    try:
        name = path.relative_to(project).as_posix()
    except ValueError:
        if not external:
            raise ValueError(f"CURRENT_PATH_ESCAPES: {path}")
        name = str(path)
    return {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}


def design_of(path):
    match = re.search(r"(?m)^\s*DESIGN\s+(\S+)\s*;", Path(path).read_text())
    if not match:
        raise ValueError("CURRENT_DEF_DESIGN_MISSING")
    return match.group(1)


def pdk_of(project):
    """Read the producer's technology record, never guess a technology."""
    path = Path(project) / "reports/phase3/technology_units.json"
    doc = json.loads(path.read_text())
    name = doc.get("pdk")
    if not name and isinstance(doc.get("tech_lef"), str):
        parts = Path(doc["tech_lef"]).parts
        if "libs.ref" in parts:
            name = parts[parts.index("libs.ref") - 1]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("CURRENT_PDK_MISSING")
    return name, path


def build(project, step, stage, design, pdk, tool, inputs, outputs, execution):
    if not all(isinstance(v, str) and v.strip()
               for v in (step, stage, design, pdk, tool)):
        raise ValueError("CURRENT_CONTEXT_EMPTY")
    return {"schema": SCHEMA, "step": step, "stage": stage,
            "design": design, "pdk": pdk, "tool": tool,
            "inputs": inputs, "outputs": outputs, "execution": execution}


def validate(project, record, *, step, stage, tools, required_inputs,
             required_outputs, marker=None):
    """Read-only, blocking subject check; return the refusal or an empty string."""
    try:
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            raise ValueError("CURRENT_RECORD_MISSING")
        if record.get("step") != step or record.get("stage") != stage:
            raise ValueError("CURRENT_STEP_STAGE_MISMATCH")
        if record.get("tool") not in tools:
            raise ValueError("CURRENT_TOOL_MISMATCH")
        if not record.get("pdk") or not record.get("design"):
            raise ValueError("CURRENT_CONTEXT_EMPTY")
        for field, required in (("inputs", required_inputs),
                                ("outputs", required_outputs)):
            rows = record.get(field)
            if not isinstance(rows, dict) or not set(required) <= rows.keys():
                raise ValueError(f"CURRENT_{field.upper()}_MISSING")
            for role, row in rows.items():
                if not isinstance(row, dict) or not re.fullmatch(
                        r"[0-9a-f]{64}", str(row.get("sha256", ""))):
                    raise ValueError(f"CURRENT_HASH_MISSING: {role}")
                path = Path(row["path"])
                external = field == "inputs" and role.startswith("pdk_")
                if path.is_absolute() and not external:
                    raise ValueError(f"CURRENT_PATH_ESCAPES: {role}")
                path = path if path.is_absolute() else Path(project) / path
                if entry(project, path, external=external) != row:
                    raise ValueError(f"CURRENT_BYTES_CHANGED: {role}")
                if role in ("floorplan", "def") and design_of(path) != record["design"]:
                    raise ValueError("CURRENT_DESIGN_MISMATCH")
                if role == "technology":
                    if pdk_of(project)[0] != record["pdk"]:
                        raise ValueError("CURRENT_PDK_MISMATCH")
        execution = record.get("execution")
        if not isinstance(execution, dict) or execution.get("rc") != 0:
            raise ValueError("CURRENT_EXECUTION_MISSING")
        if not isinstance(execution.get("argv"), list) or not execution["argv"]:
            raise ValueError("CURRENT_ARGV_MISSING")
        log = record["outputs"].get("log")
        if log is None:
            raise ValueError("CURRENT_LOG_MISSING")
        if marker and marker not in (Path(project) / log["path"]).read_text():
            raise ValueError("CURRENT_EXECUTION_MARKER_MISSING")
        return ""
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return str(exc)


def native_argv(project, tool, args):
    """Use the local native tool in an image, or the pinned docker-run wrapper."""
    import shutil
    if shutil.which(tool):
        return [tool, *args]
    from librelane_contract import resolve_image
    from _docker_memory import docker_memory_flags
    image = resolve_image(Path(project))
    return ["docker", "run", *docker_memory_flags(), "--rm", "--network", "none",
            "-v", f"{Path(project).resolve()}:{Path(project).resolve()}",
            image, "--skip", tool, *args]


def run_native(project, tool, args, log):
    argv = native_argv(project, tool, args)
    if argv[0] == "docker":
        from librelane_contract import run_container
        cp = run_container(argv, supervised=True, log=log)
        rc, stdout, stderr = cp.returncode, cp.stdout, cp.stderr
    else:
        from _watchdog import run_host_supervised
        cp = run_host_supervised(argv, stall_grace_s=300)
        rc, stdout, stderr = cp.rc, cp.out, cp.err
    Path(log).write_text((stdout or "") + "\n" + (stderr or ""))
    return rc, {"rc": rc, "argv": argv}


def clock_plan(project, plan, floorplan, sdcs, pdk):
    """OpenROAD reads the current floorplan and evaluates the declared SDC."""
    from _atomic_artefact import write_json
    project, plan, floorplan = map(Path, (project, plan, floorplan))
    if floorplan.resolve() != (project / "phase3/stage3/pnr/floorplan.def").resolve():
        raise ValueError("CLOCK_PLAN_REQUIRES_FLOORPLAN")
    design = design_of(floorplan)
    inputs = {"floorplan": entry(project, floorplan)}
    from _ppa.timing import ASIC_SDC_RECORD
    from _path_layout import constraints_dir
    asic_record = constraints_dir(project) / ASIC_SDC_RECORD
    inputs["asic_record"] = entry(project, asic_record)
    for i, path in enumerate(sdcs):
        inputs[f"sdc_{i}"] = entry(project, path)
    if not sdcs:
        raise ValueError("CLOCK_PLAN_SDC_MISSING")
    refusal = clock_plan_asic_refusal(project, {"inputs": inputs, "pdk": pdk.name})
    if refusal:
        raise ValueError(refusal)
    lefs = list(dict.fromkeys([pdk.tech_lef, pdk.cell_lef,
                               *(getattr(pdk, "macro_lefs", []) or [])]))
    for i, path in enumerate(lefs):
        inputs[f"pdk_lef_{i}"] = entry(project, path, external=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    script, log = plan.with_suffix(".tcl"), plan.with_suffix(".log")
    def quote(path):
        if any(c in str(path) for c in "{}\n\r"):
            raise ValueError("CLOCK_PLAN_TCL_PATH_INVALID")
        return "{" + str(Path(path).resolve()) + "}"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", pdk.name):
        raise ValueError("CLOCK_PLAN_PDK_NAME_INVALID")
    script.write_text("\n".join([
        f'puts "CLOCK_PLAN_PDK {pdk.name}"',
        *[f"read_lef {quote(path)}" for path in lefs],
        f"read_def {quote(floorplan)}",
        *[f"read_sdc {quote(path)}" for path in sdcs],
        'foreach c [all_clocks] {',
        '  set pins [get_full_name [get_property $c sources]]',
        '  if {$pins eq ""} {error "CLOCK_SOURCE_MISSING"}',
        '  puts "CLOCK_PLAN_NATIVE [get_full_name $c]|[get_property $c period]|$pins"',
        '}',
        'if {[llength [all_clocks]] == 0} {error "CLOCK_PLAN_NO_CLOCKS"}',
        'puts "CLOCK_PLAN_DONE"', ""]))
    inputs["recipe"] = entry(project, script)
    rc, execution = run_native(project, "openroad", ["-exit", str(script)], log)
    text = log.read_text()
    clocks = []
    for name, period, source in re.findall(r"(?m)^CLOCK_PLAN_NATIVE ([^|\n]+)\|([^|\n]+)\|([^\n]+)$", text):
        period = float(period)
        if period <= 0 or not source.strip():
            raise ValueError("CLOCK_PLAN_NATIVE_CLOCK_INVALID")
        clocks.append({"name": name, "period_ns": period, "source": source})
    if rc or not clocks or "CLOCK_PLAN_DONE" not in text or re.search(r"\[ERROR\]|^Error:", text, re.M):
        raise ValueError(f"CLOCK_PLAN_NATIVE_REFUSED: rc={rc}; {text[-500:]}")
    for role, row in inputs.items():
        if entry(project, project / row["path"], external=role.startswith("pdk_")) != row:
            raise ValueError(f"CLOCK_PLAN_INPUT_CHANGED: {role}")
    refusal = clock_plan_asic_refusal(project, {"inputs": inputs, "pdk": pdk.name})
    if refusal:
        raise ValueError(refusal)
    current = build(project, "16", "stage3", design, pdk.name, "openroad",
                    inputs, {"log": entry(project, log)}, execution)
    write_json(plan, {"tool": "openroad", "primary_clock": clocks[0]["name"],
                      "clocks": clocks, "current": current,
                      "derived_from": {str(Path(p).relative_to(project)): digest(p) for p in sdcs}})
    return str(plan)


def clock_plan_asic_refusal(project, record):
    """Blocking reader: the measured ASIC bundle still belongs to its sources."""
    try:
        import phase3_one_shot_runner as runner
        from _ppa import timing
        project = Path(project)
        path = runner._pl.constraints_dir(project) / timing.ASIC_SDC_RECORD
        if record["inputs"]["asic_record"] != entry(project, path):
            return "CLOCK_PLAN_ASIC_RECORD_CHANGED"
        doc = json.loads(path.read_text())
        if not isinstance(doc, dict) or not isinstance(doc.get("top"), str):
            return "CLOCK_PLAN_ASIC_SDC_RECORD_INVALID"
        declared = runner._read_declared_pdk_target(project)
        if not declared:
            return "CLOCK_PLAN_ASIC_PDK_UNDECLARED"
        pdk = runner._detect_pdk(project, declared)
        if pdk is None:
            return "CLOCK_PLAN_ASIC_PDK_UNRESOLVED"
        if pdk.name != record["pdk"]:
            return "CLOCK_PLAN_ASIC_PDK_CHANGED"
        asic, why = timing.read_step7_asic_sdc(runner, project, doc["top"], pdk)
        if asic is None:
            return f"CLOCK_PLAN_ASIC_SDC_REFUSED: {why}"
        selected = {role: row for role, row in record["inputs"].items()
                    if role.startswith("sdc_")}
        if selected != {"sdc_0": entry(project, project / asic["path"])}:
            return "CLOCK_PLAN_ASIC_SDC_SET_CHANGED"
        return ""
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return f"CLOCK_PLAN_ASIC_SDC_REFUSED: {exc}"


def direct_half(project, top, pdk, half, producer):
    """Bind the direct native DRC/LVS invocation, without masking its FAIL."""
    from _atomic_artefact import write_json
    import _signoff_drc_format as sdf
    project = Path(project)
    path = project / f"reports/phase3/direct_current_{half}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    inputs, refusal = {}, ""
    try:
        pnr = project / "phase3/stage3/pnr"
        for role, source in (("gds", pnr / f"{top}.gds"),
                             ("def", pnr / f"{top}.def"),
                             ("netlist", pnr / f"{top}_pnr.v"),
                             ("pdk_tech_lef", pdk.tech_lef),
                             ("pdk_cell_lef", pdk.cell_lef)):
            inputs[role] = entry(project, source, external=role.startswith("pdk_"))
        deck = pdk.drc_deck if half == "drc" else getattr(pdk, "bridge_netgen_setup", None)
        if not deck and half == "lvs":
            deck = Path("/foss/pdks") / pdk.name / "libs.tech/netgen" / f"{pdk.name}_setup.tcl"
        if not deck:
            raise ValueError("CURRENT_NATIVE_DECK_MISSING")
        inputs["pdk_deck"] = entry(project, deck, external=True)
        declared_pdk, technology = pdk_of(project)
        if declared_pdk != pdk.name:
            raise ValueError("CURRENT_PDK_MISMATCH")
        inputs["technology"] = entry(project, technology)
        design = design_of(pnr / f"{top}.def")
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        refusal = str(exc)
        design = top
    before = list(sdf._prov_entries(project))
    row = producer()
    try:
        if refusal:
            raise ValueError(refusal)
        report = project / f"reports/phase3/{'drc_signoff' if half == 'drc' else 'lvs'}.rpt"
        native_report = project / "phase3/reports/drc.rpt" if half == "drc" else report
        invoked = [e for e in list(sdf._prov_entries(project))[len(before):]
                   if e.get("record") == "invocation"
                   and any(Path(k).name == native_report.name for k in (e.get("outputs") or {}))
                   and e.get("tool") in ("klayout", "magic", "netgen", "svrfdrc")]
        if not invoked:
            raise ValueError("CURRENT_NATIVE_INVOCATION_MISSING")
        execution = invoked[-1]
        if execution.get("measured") is not True or execution.get("exit_code") != 0:
            raise ValueError("CURRENT_NATIVE_EXECUTION_MISSING")
        for role, expected in inputs.items():
            if entry(project, project / expected["path"], external=role.startswith("pdk_")) != expected:
                raise ValueError(f"CURRENT_INPUT_CHANGED_DURING_TOOL: {role}")
        log = native_report.with_suffix(".log")
        record = build(project, "31", "stage4", design, pdk.name, execution["tool"],
                       inputs, {"report": entry(project, report), "log": entry(project, log),
                                "native_report": entry(project, native_report)},
                       {"rc": execution["exit_code"],
                        "argv": [execution.get("command") or execution.get("cmd") or execution["tool"]],
                        "native_invocation": execution})
        write_json(path, record)
        row.extras["current_subject"] = str(path)
        row.extras["current_reader"] = read_direct_half(project, half)
    except (OSError, ValueError, TypeError) as exc:
        refusal = str(exc)
        write_json(path, {"schema": SCHEMA, "step": "31", "stage": "stage4",
                          "verdict": "NOT_MEASURED", "reason": refusal})
        if row.status == "PASS":
            row.status = "NOT_MEASURED"
            row.reason_class = "NOT_EXECUTED"
        row.detail += f"; current native subject: {refusal}"
    return row


def _direct_half_refusal(project, half):
    """Strict reader for the Step-31 declared DRC/LVS gates."""
    project = Path(project)
    try:
        record = json.loads((project / f"reports/phase3/direct_current_{half}.json").read_text())
    except (OSError, ValueError) as exc:
        return f"CURRENT_NATIVE_RECORD_MISSING: {exc}"
    refusal = validate(project, record, step="31", stage="stage4",
                       tools=("klayout", "magic", "netgen", "svrfdrc"),
                       required_inputs=("gds", "def", "netlist", "technology", "pdk_deck", "pdk_tech_lef", "pdk_cell_lef"),
                       required_outputs=("report", "native_report", "log"))
    if refusal:
        return refusal
    report = project / f"reports/phase3/{'drc_signoff' if half == 'drc' else 'lvs'}.rpt"
    if record["outputs"]["report"] != entry(project, report):
        return "CURRENT_NATIVE_REPORT_SWAPPED"
    native = record["execution"].get("native_invocation") or {}
    if (native.get("tool") != record["tool"] or native.get("measured") is not True
            or native.get("exit_code") != 0):
        return "CURRENT_NATIVE_INVOCATION_MISMATCH"
    for role in ("native_report", "log"):
        row = record["outputs"][role]
        if (native.get("outputs") or {}).get(row["path"]) != "sha256:" + row["sha256"]:
            return "CURRENT_NATIVE_OUTPUT_UNBOUND"
    pnr = project / "phase3/stage3/pnr"
    for role, suffix in (("gds", ".gds"), ("def", ".def"), ("netlist", "_pnr.v")):
        if record["inputs"][role] != entry(project, pnr / (record["design"] + suffix)):
            return "CURRENT_NATIVE_SUBJECT_SWAPPED"
    # The report's own invocation must bind the layout, not only its filename.
    want = record["inputs"]["gds"]
    bound = (native.get("inputs") or {}).get(want["path"])
    if bound not in (want["sha256"], "sha256:" + want["sha256"]):
        return "CURRENT_NATIVE_LAYOUT_UNBOUND"
    return ""


def check_direct_half(project, half):
    try:
        return _direct_half_refusal(project, half)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return f"CURRENT_NATIVE_REFUSED: {exc}"


def read_direct_half(project, half):
    """Explicit strict-reader receipt; an empty refusal is never the evidence."""
    refusal = check_direct_half(project, half)
    if refusal:
        return {"verdict": "NOT_MEASURED", "reason": refusal, "half": half}
    path = Path(project) / f"reports/phase3/direct_current_{half}.json"
    record = json.loads(path.read_text())
    return {"verdict": "CURRENT", "half": half, "subject": entry(project, path),
            "step": record["step"], "stage": record["stage"], "design": record["design"],
            "tool": record["tool"], "pdk": record["pdk"],
            "inputs": record["inputs"], "outputs": record["outputs"]}


def check_kit(project):
    """Both kit and documentation gates consume this exact current kit."""
    project = Path(project)
    hm = project / "phase3/stage4/hardmacro"
    try:
        record = json.loads((hm / "current_kit.json").read_text())
        refusal = validate(
            project, record, step="37.5ip", stage="stage4", tools=("magic+opensta",),
            required_inputs=("def", "gds", "route", "technology", "timing_netlist",
                             "timing_sdc", "timing_spef", "timing_sta_report", "timing_recipe",
                             "pdk_timing_liberty", "pdk_magicrc", "lef_recipe"),
            required_outputs=("lef", "liberty", "gds", "verilog", "log", "timing_log"),
            marker="DIGITAL_LEF_WRITE_DONE")
        if refusal:
            return refusal
        import digital_hardmacro_gen as producer
        if (record["inputs"]["def"] != entry(project, producer.find_def(project))
                or record["inputs"]["gds"] != entry(project, producer.find_signoff_gds(project))):
            return "IP_KIT_CURRENT_SUBJECT_SWAPPED"
        import _tapeout_declaration as td
        declaration = project / td.DECLARATION_REL
        doc, error = td.load(declaration)
        if (error or td.answer(doc, "deliverable") != td.DELIVERABLE_HARDMACRO
                or record["inputs"]["route"] != entry(project, declaration)):
            return "IP_KIT_ROUTE_CHANGED"
        for role, suffix in (("lef", ".lef"), ("liberty", ".lib"),
                             ("gds", ".gds"), ("verilog", ".v")):
            if record["outputs"][role] != entry(project, hm / (record["design"] + suffix)):
                return "IP_KIT_VIEW_SWAPPED"
        if record["outputs"]["gds"]["sha256"] != record["inputs"]["gds"]["sha256"]:
            return "IP_KIT_LAYOUT_SWAPPED"
        if record["outputs"]["verilog"]["sha256"] != record["inputs"]["timing_netlist"]["sha256"]:
            return "IP_KIT_NETLIST_SWAPPED"
        timing = record["execution"].get("timing") or {}
        text = (project / record["outputs"]["timing_log"]["path"]).read_text()
        if timing.get("rc") != 0 or not timing.get("argv") or "TIMING_MODEL_DONE" not in text:
            return "IP_KIT_TIMING_EXECUTION_MISSING"
        return ""
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return f"IP_KIT_CURRENT_REFUSED: {exc}"
