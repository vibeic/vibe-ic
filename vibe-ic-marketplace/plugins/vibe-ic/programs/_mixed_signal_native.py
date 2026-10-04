"""Bounded sampled RNM + native SPICE production, and current-input STA.

This is a component simulation contract, not extracted-noise signoff. All
tool calls are sequential; GNU time + the inherited 8 GiB address-space ceiling
bound ngspice. Outside a native environment, use the existing Docker run
wrapper with IMAGE --skip (never attach to a running container).
"""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import bisect
import json
import math
import os
import re
import resource
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from _atomic_artefact import write_json, write_text

CONTRACT = "input/mixed_signal/native.json"
SCHEMA = "vibeic.mixed_signal.m3.native.v1"
INPUT_SCHEMA = "vibeic.mixed_signal.native_inputs.v1"
METRICS = {"settled_voltage_min_v", "settled_voltage_max_v", "response_mismatches",
           "unknown_samples", "drive_transitions"}
LIMIT = 8 * 1024**3


def api():
    import mixed_signal_m3_run as m3
    return m3


def local(project, rel):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise api().Refusal("FOREIGN_INPUT", str(rel))
    path = project / rel
    if not path.resolve().is_relative_to(project.resolve()):
        raise api().Refusal("FOREIGN_INPUT", rel)
    return path


def contract(project, top):
    data = api().read(local(project, CONTRACT))
    if data.get("schema") != INPUT_SCHEMA or data.get("top") != top:
        raise api().Refusal("WRONG_DESIGN", "native input contract schema/top mismatch")
    if data.get("scope") != "declared_model_component":
        raise api().Refusal("UNSUPPORTED_MODEL_SCOPE", "supported scope is declared_model_component; no physical certification")
    return data


def input_paths(project, top):
    data = contract(project, top)
    d, a = data["digital"], data["analog"]
    paths = {CONTRACT, d["netlist"], a["netlist"], *d.get("extra_sources", []),
             *a.get("dependencies", [])}
    si = data.get("si")
    if isinstance(si, dict):
        paths.update(si[k] for k in ("netlist", "sdc", "spef") if k in si)
        paths.update(si.get("liberties", []))
    from _mixed_signal_receiver_noise import input_paths as receiver_inputs
    paths.update(receiver_inputs(project, data))
    for rel in paths:
        local(project, rel)
    return paths


def number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise api().Refusal("UNSUPPORTED_SCENARIO", "finite numeric " + name + " required")
    return float(value)


def settings(row):
    n = row["native"]
    period = number(n["clock_period_ns"], "clock_period_ns", True)
    step = number(n["tran_step_ns"], "tran_step_ns", True)
    start = number(n["measure_from_ns"], "measure_from_ns")
    cycles = n["cycles"]
    if type(cycles) is not int or not 3 <= cycles <= 4096:
        raise api().Refusal("UNSUPPORTED_SCENARIO", "3..4096 cycles required")
    if period < 0.01 or not 0 <= start < (cycles - 0.5) * period or cycles * period / step > 1_000_000:
        raise api().Refusal("UNSUPPORTED_SCENARIO", "empty measurement window / unsupported transient size")
    criteria = row.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise api().Refusal("UNSUPPORTED_SCENARIO", "nonempty input-derived criteria required")
    for c in criteria:
        if c.get("native_metric") not in METRICS or not any(k in c for k in ("min", "max")):
            raise api().Refusal("UNSUPPORTED_SCENARIO", "unsupported/unbounded native criterion")
        for k in ("min", "max"):
            if k in c:
                number(c[k], k)
        if "min" in c and "max" in c and c["min"] > c["max"]:
            raise api().Refusal("UNSUPPORTED_SCENARIO", "inverted criterion bounds")
    return period, step, start, cycles


def tb(data, row, feedback, token):
    period, _, _, cycles = settings(row)
    d = data["digital"]
    names = [data["top"], *(d[k] for k in ("clock", "reset_n", "drive", "sense", "response"))]
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", n) for n in names) or len(set(names[1:])) != 5:
        raise api().Refusal("UNSUPPORTED_INTERFACE", "five distinct scalar wrapper ports required")
    return f'''`timescale 1ns/1ps
module m3_sampled_tb;
  reg clk=0, reset_n=0, sense=0;
  wire drive, response;
  reg feedback [0:{cycles - 1}];
  integer k;
  {data['top']} dut(.{d['clock']}(clk), .{d['reset_n']}(reset_n),
      .{d['sense']}(sense), .{d['drive']}(drive), .{d['response']}(response));
  initial begin
    $readmemb({json.dumps(str(feedback))}, feedback);
    $display("M3RUN {token}");
    for(k=0;k<{cycles};k=k+1) begin
      #{period / 2:g}; reset_n=(k>0); sense=feedback[k]; clk=1;
      #0.001;
      $display("M3OBS k=%0d t=%0.3f drive=%b sense=%b response=%b", k, $realtime, drive, sense, response);
      #{period / 2 - 0.001:g}; clk=0;
    end
    $display("M3DONE {token}");
    $finish;
  end
endmodule
'''


OBS = re.compile(r"M3OBS k=(\d+) t=([0-9.]+) drive=([01xz]) sense=([01xz]) response=([01xz])")


def observations(path, token, cycles):
    text = path.read_text()
    if f"M3RUN {token}" not in text or f"M3DONE {token}" not in text:
        raise api().Refusal("MISSING_EXECUTION", "no completed VVP simulation of this instrument")
    rows = [{"k": int(k), "time_ns": float(t), "drive": d, "sense": s, "response": r}
            for k, t, d, s, r in OBS.findall(text)]
    if len(rows) != cycles or [r["k"] for r in rows] != list(range(cycles)):
        raise api().Refusal("EMPTY_SCENARIOS", "incomplete native wrapper observations")
    if any(r["drive"] not in ("0", "1") for r in rows):
        raise api().Refusal("FAILED_MEASUREMENT", "unresolved digital drive")
    return rows


def deck(project, data, row, drive, wave):
    period, step, _, cycles = settings(row)
    a = data["analog"]
    for k in ("drive_low_v", "drive_high_v", "drive_transition_ns", "adc_low_v", "adc_high_v"):
        number(a[k], k, positive=k == "drive_transition_ns")
    if not (a["drive_low_v"] <= a["adc_low_v"] < a["adc_high_v"] <= a["drive_high_v"]):
        raise api().Refusal("UNSUPPORTED_INTERFACE", "ADC thresholds must lie inside declared rails")
    if a["drive_transition_ns"] >= period / 2 or a.get("ports") != ["drive", "sense"]:
        raise api().Refusal("UNSUPPORTED_INTERFACE", "two-port circuit and bounded DAC transition required")
    model = local(project, a["netlist"])
    text = model.read_text()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a["subckt"]):
        raise api().Refusal("UNSUPPORTED_INTERFACE", "literal subcircuit required")
    if not re.search(r"(?im)^\s*\.subckt\s+" + re.escape(a["subckt"]) + r"\s+\S+\s+\S+\s*$", text):
        raise api().Refusal("UNSUPPORTED_INTERFACE", "model must define the declared two-port subcircuit")
    # Dependences must be declared/current. This restricted sampled path does
    # not support hidden includes or arbitrary .control sections in models.
    if re.search(r"(?im)^\s*\.(?:control|include|inc|lib)\b", text):
        raise api().Refusal("UNSUPPORTED_MODEL", "use self-contained declared models; hidden include/control unsupported")
    for dep in a.get("dependencies", []):
        if re.search(r"(?im)^\s*\.(?:control|include|inc|lib)\b", local(project, dep).read_text()):
            raise api().Refusal("UNSUPPORTED_MODEL", "nested model includes/control are not bound by this contract")
    low, high, rise = a["drive_low_v"], a["drive_high_v"], a["drive_transition_ns"]
    previous = int(drive[0]["drive"])
    points = [(0, high if previous else low)]
    for r in drive[1:]:
        value = int(r["drive"])
        if value != previous:
            points.extend([(r["time_ns"], high if previous else low),
                           (r["time_ns"] + rise, high if value else low)])
            previous = value
    points.append((cycles * period, high if previous else low))
    pwl = " ".join(f"{t * 1e-9:.12g} {v:g}" for t, v in points)
    return "\n".join([
        "* Current wrapper drive -> supplied functional/model SPICE; component evidence",
        *(f'.include "{local(project, dep)}"' for dep in a.get("dependencies", [])),
        f'.include "{model}"', f"Vdrive drive 0 PWL({pwl})",
        f"Xreceiver drive sense {a['subckt']}", ".control",
        f"echo M3RUN {wave.parent.parent.name}",
        "set wr_singlescale", "set wr_vecnames",
        f"tran {step * 1e-9:g} {cycles * period * 1e-9:g}",
        "wrdata wave.txt v(sense)", f"echo M3DONE {wave.parent.parent.name}", ".endc", ".end", ""])


def waveform(path):
    rows = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            t, v = map(float, parts)
        except ValueError:
            continue
        if not math.isfinite(t) or not math.isfinite(v):
            raise api().Refusal("FAILED_MEASUREMENT", "nonfinite native waveform")
        t *= 1e9  # compare and retain one time unit (ns), not seconds vs ns
        if rows and t <= rows[-1][0]:
            raise api().Refusal("FAILED_MEASUREMENT", "unordered native waveform")
        rows.append((t, v))
    if len(rows) < 3:
        raise api().Refusal("MISSING_EXECUTION", "no substantive ngspice waveform")
    return rows


def interpolate(wave, times):
    ts = [r[0] for r in wave]
    values = []
    for t in times:
        k = bisect.bisect_left(ts, t)
        if k == 0 or k >= len(ts):
            raise api().Refusal("MISSING_EXECUTION", "waveform does not span wrapper sampling times")
        t0, v0 = wave[k - 1]
        t1, v1 = wave[k]
        values.append(v0 + (v1 - v0) * (t - t0) / (t1 - t0))
    return values


def adc(data, values):
    a = data["analog"]
    return ["0" if v <= a["adc_low_v"] else "1" if v >= a["adc_high_v"] else "x" for v in values]


def grade(project, data, row, work, token):
    _, _, start, cycles = settings(row)
    first = observations(work / "drive.log", token, cycles)
    replay = observations(work / "response.log", token, cycles)
    if [(r["time_ns"], r["drive"]) for r in first] != [(r["time_ns"], r["drive"]) for r in replay]:
        raise api().Refusal("FEEDBACK_ALTERS_DRIVE", "sampled path requires feed-forward drive; use coupled solver")
    values = interpolate(waveform(work / "wave.txt"), [r["time_ns"] for r in first])
    bits = adc(data, values)
    if (work / "feedback.mem").read_text() != "\n".join(bits) + "\n":
        raise api().Refusal("CONTRADICTS_NATIVE_OUTPUT", "RNM samples differ from ngspice observations")
    if any(r["sense"] != b for r, b in zip(replay, bits)):
        raise api().Refusal("CONTRADICTS_NATIVE_OUTPUT", "wrapper did not consume measured RNM samples")
    selected = [i for i, r in enumerate(replay) if r["time_ns"] >= start]
    measured = {
        "settled_voltage_min_v": min(values[i] for i in selected),
        "settled_voltage_max_v": max(values[i] for i in selected),
        "unknown_samples": sum(bits[i] == "x" for i in selected),
        "response_mismatches": sum(replay[i]["response"] != bits[i] for i in selected),
        "drive_transitions": sum(a["drive"] != b["drive"] for a, b in zip(first, first[1:])),
    }
    criteria = []
    for c in row["criteria"]:
        value = measured[c["native_metric"]]
        ok = ("min" not in c or value >= c["min"]) and ("max" not in c or value <= c["max"])
        criteria.append({**c, "measured": value, "verdict": "PASS" if ok else "FAIL"})
    return {"id": row["id"], "status": "PASS" if all(c["verdict"] == "PASS" for c in criteria) else "FAIL",
            "criteria": criteria, "sample_count": len(selected), "metrics": measured,
            "scope": "declared_model_component"}


def limit_address_space():
    resource.setrlimit(resource.RLIMIT_AS, (LIMIT, LIMIT))


class Engine:
    def __init__(self, project, container, bound_inputs):
        self.project, self.container = project, container
        self.inputs = bound_inputs
        self.execution, self.versions = [], {}

    def run(self, command, log, stage, cwd=None):
        import _watchdog as wd
        import librelane_contract as lc
        before = time.time_ns()
        if self.container == "host" or Path("/.dockerenv").exists():
            def spawn(cmd, **kw):
                return subprocess.Popen(cmd, start_new_session=True, preexec_fn=limit_address_space, **kw)
            done = wd.completed_process(command, wd.run_host_supervised(
                command, cwd=cwd or self.project, popen_factory=spawn, stall_grace_s=60))
        else:
            image = lc.resolve_image(None)
            argv = [shutil.which("docker") or "docker", "run", "--rm", "--network", "none",
                    "--cpus", "2", "--memory", str(LIMIT), "--memory-swap", str(LIMIT),
                    "-v", f"{self.project}:{self.project}", "-w", str(cwd or self.project),
                    image, "--skip", *command]
            try:
                done = lc.run_container(argv, supervised=True, log=log)
            except lc.Refusal as exc:
                raise api().Refusal("NATIVE_TOOL_NOT_MEASURED", str(exc)) from exc
        write_text(log, done.stdout + done.stderr)
        self.execution.append({"command": command, "stage": stage, "exit_code": done.returncode,
                               "started_ns": before, "finished_ns": time.time_ns(),
                               "log": str(log.relative_to(self.project)), "cwd": str(cwd or self.project),
                               "input_sha256": self.inputs})
        if done.returncode:
            raise api().Refusal("NATIVE_EXECUTION_FAILED", f"{command[0]} rc={done.returncode}; {log}")
        return done

    def version(self, name, args, root):
        done = self.run([name, *args], root / (name + "-version.log"), "version")
        value = done.stdout + done.stderr
        if not value.strip():
            raise api().Refusal("MISSING_TOOL_VERSION", name)
        self.versions[name] = value.strip()


def simulate(project, data, row, work, token, engine):
    _, _, _, cycles = settings(row)
    work.mkdir(parents=True)
    feedback = work / "feedback.mem"
    # Stage one runs the actual wrapper with inactive feedback. Stage two
    # uses observed analog samples and must preserve that drive trajectory.
    initial = work / "initial.mem"
    write_text(initial, "0\n" * cycles)
    d = data["digital"]
    sources = [str(local(project, d["netlist"])),
               *(str(local(project, p)) for p in d.get("extra_sources", []))]
    if any(re.search(r'(?m)^\s*`include\b', Path(s).read_text()) for s in sources):
        raise api().Refusal("UNSUPPORTED_MODEL", "digital includes require a flattened, explicitly bound source view")
    write_text(work / "drive_tb.v", tb(data, row, initial, token))
    engine.run(["iverilog", "-g2012", "-s", "m3_sampled_tb", "-o", str(work / "drive.vvp"),
                *sources, str(work / "drive_tb.v")], work / "compile-drive.log", "compile")
    engine.run(["vvp", str(work / "drive.vvp")], work / "drive.log", "measurement")
    drive = observations(work / "drive.log", token, cycles)
    spice = work / "scenario.sp"
    write_text(spice, deck(project, data, row, drive, work / "wave.txt"))
    engine.run(["/usr/bin/time", "-f", "%M", "-o", str(work / "ngspice.rss"),
                "ngspice", "-q", "-b", str(spice)], work / "ngspice.log", "measurement", cwd=work)
    rss = int((work / "ngspice.rss").read_text().strip())
    engine.execution[-1]["peak_rss_kib"] = rss
    if rss * 1024 > LIMIT:
        raise api().Refusal("MEMORY_BUDGET_EXCEEDED", "stop expansion above 8 GiB")
    if not (work / "wave.txt").is_file():
        raise api().Refusal("NATIVE_EXECUTION_FAILED", "ngspice wrote no requested waveform (even if rc=0)")
    values = interpolate(waveform(work / "wave.txt"), [r["time_ns"] for r in drive])
    write_text(feedback, "\n".join(adc(data, values)) + "\n")
    write_text(work / "response_tb.v", tb(data, row, feedback, token))
    engine.run(["iverilog", "-g2012", "-s", "m3_sampled_tb", "-o", str(work / "response.vvp"),
                *sources, str(work / "response_tb.v")], work / "compile-response.log", "compile")
    engine.run(["vvp", str(work / "response.vvp")], work / "response.log", "measurement")
    return grade(project, data, row, work, token)


def timing_preflight(project, data):
    spec = data.get("si")
    result = {"interfaces": [], "coverage": {k: "NOT_MEASURED" for k in ("timing", "noise", "crosstalk")},
              "verdict": "NOT_MEASURED", "all_interfaces_clean": False,
              "blockers": ["qualified extracted receiver/noise/crosstalk coverage unavailable"]}
    if not isinstance(spec, dict):
        result["blockers"].append("current SPEF/Liberty/SDC interface contract absent")
        return result
    libs = spec.get("liberties", [])
    if (not isinstance(libs, list) or not libs or
            any(not local(project, p).is_file() for p in
                [spec.get("netlist"), spec.get("sdc"), spec.get("spef"), *libs])):
        result["blockers"].append("current SPEF/Liberty/SDC inputs missing")
        return result
    validate_si(project, data)
    return None


def interface_timing(project, data, root, engine):
    missing = timing_preflight(project, data)
    if missing is not None:
        return missing
    root.mkdir()
    engine.version("sta", ["-version"], root)
    write_text(root / "timing.tcl", si_tcl(project, data, root))
    engine.run(["sta", "-exit", str(root / "timing.tcl")], root / "sta.log", "measurement")
    log = (root / "sta.log").read_text()
    if re.search(r"(?mi)^\s*Error(?:\s|:)", log) or "SI_TIMING_JSON_EMIT_DONE" not in log:
        raise api().Refusal("NATIVE_EXECUTION_FAILED", "OpenSTA error/incomplete emission, even if rc=0")
    return derive_si(project, data, root)


def si_refusal(exc):
    return {"interfaces": [], "coverage": {k: "NOT_MEASURED" for k in ("timing", "noise", "crosstalk")},
            "verdict": "FAIL" if getattr(exc, "rule", "") == "NATIVE_EXECUTION_FAILED" else "NOT_MEASURED",
            "all_interfaces_clean": False, "blockers": [str(exc)]}


def blend_receiver_noise(result, measured):
    # These are independent coverage dimensions. Component noise cannot turn
    # an advisory coupling screen into measured crosstalk or physical signoff.
    result = {**result, "coverage": dict(result["coverage"]), "blockers": list(result["blockers"]),
              "receiver_noise": measured}
    result["coverage"]["noise"] = "MEASURED" if measured["verdict"] in ("PASS", "FAIL") and measured.get("criteria") else "NOT_MEASURED"
    ready = all(v == "MEASURED" for v in result["coverage"].values())
    result["verdict"] = "FAIL" if "FAIL" in (result["verdict"], measured["verdict"]) else "PASS" if ready else "NOT_MEASURED"
    result["all_interfaces_clean"] = result["verdict"] == "PASS"
    if result["coverage"]["noise"] == "MEASURED":
        result["blockers"] = [b for b in result["blockers"] if "receiver/noise" not in b]
    if result["coverage"]["crosstalk"] != "MEASURED":
        result["blockers"].append("qualified component crosstalk coverage NOT_MEASURED; capacitive screen is advisory")
    return result


def interface_si(project, data, root, engine):
    from _mixed_signal_receiver_noise import declaration, run
    spec = declaration(project, data)  # preflight also happens before any execution in inputs()
    if spec is None:
        return interface_timing(project, data, root, engine)
    try:
        result = interface_timing(project, data, root, engine)
    except (api().Refusal, OSError, ValueError, KeyError) as exc:
        result = si_refusal(exc)
    try:
        measured = run(project, spec, root, root.parent.name, engine)
    except (api().Refusal, OSError, ValueError, KeyError) as exc:
        measured = {"id": spec["id"], "scope": spec["scope"], "verdict": "FAIL" if getattr(exc, "rule", "") in
                    ("NATIVE_EXECUTION_FAILED", "FAILED_MEASUREMENT") else "NOT_MEASURED",
                    "criteria": [], "rule": getattr(exc, "rule", "INVALID_EVIDENCE"), "reason": str(exc)}
    return blend_receiver_noise(result, measured)


def validate_si(project, data):
    from si_signoff_timing_aware import parse_spef
    spec = data["si"]
    text = local(project, spec["spef"]).read_text()
    design = re.search(r'(?m)^\*DESIGN\s+"?([^"\s]+)', text)
    if not design or design[1] != data["top"]:
        raise api().Refusal("WRONG_DESIGN", "SPEF belongs to another design")
    starts = len(re.findall(r"(?m)^\*D_NET\s", text))
    if not starts or starts != len(re.findall(r"(?m)^\*END\s*$", text)):
        raise api().Refusal("SI_INPUTS_NOT_MEASURED", "SPEF lacks complete extracted D_NET records")
    parsed = parse_spef(text)
    if not parsed["cg"] or not parsed["node_net"]:
        raise api().Refusal("SI_INPUTS_NOT_MEASURED", "SPEF lacks substantive extracted node/capacitance coverage")
    number(spec["vdd_v"], "vdd_v", True)
    number(spec["noise_margin_mv"], "noise_margin_mv", True)
    interfaces = spec.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces:
        raise api().Refusal("SI_TIMING_NOT_MEASURED", "nonempty declared interface criteria required")
    for item in interfaces:
        if not isinstance(item.get("pin"), str) or not item.get("criteria"):
            raise api().Refusal("SI_TIMING_NOT_MEASURED", "every declared interface requires bounded metrics")
        pins = {pin for key in ("net_driver_pins", "net_load_pins")
                for group in parsed[key].values() for pin in group}
        if item["pin"] not in pins:
            raise api().Refusal("SI_INPUTS_NOT_MEASURED", "declared interface pin has no extracted SPEF connection")
        for c in item["criteria"]:
            if c.get("metric") not in ("arr_rise_min", "arr_rise_max", "arr_fall_min", "arr_fall_max",
                                      "slew_rise_max", "slew_fall_max", "slack_max") or not any(k in c for k in ("min", "max")):
                raise api().Refusal("SI_TIMING_NOT_MEASURED", "unsupported/unbounded interface timing metric")
            for k in ("min", "max"):
                if k in c:
                    number(c[k], k)


def si_tcl(project, data, root):
    from si_signoff_timing_aware import build_opensta_si_tcl
    spec = data["si"]
    def q(path):
        value = str(path)
        if any(c in value for c in "{}\n\r"):
            raise api().Refusal("UNSUPPORTED_INTERFACE", "unsupported Tcl path characters")
        return "{" + value + "}"
    libs = spec["liberties"]
    return build_opensta_si_tcl(q(local(project, libs[0])), q(local(project, spec["netlist"])),
        data["top"], q(local(project, spec["sdc"])), q(local(project, spec["spef"])), q(root / "timing.json"),
        vdd_v=spec["vdd_v"], extra_liberties=[q(local(project, p)) for p in libs[1:]],
        propagated_clock=bool(spec.get("propagated_clock"))) + "\nexit\n"


def derive_si(project, data, root):
    from si_signoff_timing_aware import run_si_signoff_timing_aware
    spec = data["si"]
    timing = api().read(root / "timing.json")
    if timing.get("tool") != "OpenSTA" or timing.get("design") != data["top"] or not timing.get("pins"):
        raise api().Refusal("SI_TIMING_NOT_MEASURED", "no current native OpenSTA pin observations")
    interfaces = []
    for item in spec.get("interfaces", []):
        metrics = {}
        for c in item.get("criteria", []):
            value = timing["pins"].get(item["pin"], {}).get(c["metric"])
            if type(value) in (float, int) and math.isfinite(value):
                metrics[c["metric"]] = {"measured": value, **{k: c[k] for k in ("min", "max") if k in c}}
            else:
                raise api().Refusal("SI_TIMING_NOT_MEASURED", "declared pin/metric not measured: " + item["pin"] + "/" + c["metric"])
        if metrics:
            interfaces.append({"name": item["pin"], "metrics": metrics})
    if not interfaces:
        raise api().Refusal("SI_TIMING_NOT_MEASURED", "declared interface timing metrics unavailable")
    screen = run_si_signoff_timing_aware(local(project, spec["spef"]), root / "timing.json",
                                       vdd_v=spec["vdd_v"], noise_margin_mv=spec["noise_margin_mv"])
    failed = screen.get("delta_delay_verdict") == "FAIL"
    for iface in interfaces:
        for metric in iface["metrics"].values():
            failed |= ("min" in metric and metric["measured"] < metric["min"]) or (
                       "max" in metric and metric["measured"] > metric["max"])
    return {"interfaces": interfaces, "coverage": {"timing": "MEASURED", "noise": "NOT_MEASURED", "crosstalk": "ADVISORY"},
            "verdict": "FAIL" if failed else "NOT_MEASURED", "all_interfaces_clean": False,
            "native_screen": screen, "blockers": ["receiver/noise coverage NOT_MEASURED; capacitive crosstalk screen ADVISORY"]}


def produce(project, top, container):
    m3 = api()
    data = contract(project, top)
    before = m3.inputs(project, top)
    rows = m3.plan(project)
    ids = [row.get("id") for row in rows]
    if not rows or any(not isinstance(i, str) or not re.fullmatch(r"[\w-]+", i) or i == "si" for i in ids) or len(set(ids)) != len(ids):
        raise m3.Refusal("UNSUPPORTED_SCENARIO", "nonempty uniquely identified L22 scenarios required")
    for rel in (*m3.OUTPUTS.values(), m3.RECEIPT):
        if not (project / rel).resolve().is_relative_to(project):
            raise m3.Refusal("FOREIGN_OUTPUT", rel)
        (project / rel).unlink(missing_ok=True)
    token = uuid.uuid4().hex
    root = project / m3.DIR / "native" / token
    if not root.resolve().is_relative_to(project):
        raise m3.Refusal("FOREIGN_OUTPUT", "native run directory resolves outside the project")
    root.mkdir(parents=True)
    engine = Engine(project, container, before)
    scenarios = []
    si = {"interfaces": [], "verdict": "NOT_MEASURED", "all_interfaces_clean": False,
          "coverage": {k: "NOT_MEASURED" for k in ("timing", "noise", "crosstalk")}, "blockers": []}
    try:
        for name, args in (("ngspice", ["--version"]), ("iverilog", ["-V"]), ("vvp", ["-V"])):
            engine.version(name, args, root)
        for row in rows:
            try:
                scenarios.append(simulate(project, data, row, root / row["id"], token, engine))
            except (m3.Refusal, OSError, KeyError, ValueError) as exc:
                scenarios.append({"id": row["id"], "status": "FAIL" if getattr(exc, "rule", "") in
                                  ("NATIVE_EXECUTION_FAILED", "FAILED_MEASUREMENT") else "NOT_MEASURED",
                                  "criteria": [], "reason": str(exc), "rule": getattr(exc, "rule", "INVALID_EVIDENCE")})
                if getattr(exc, "rule", "") == "MEMORY_BUDGET_EXCEEDED":
                    break
        try:
            si = interface_si(project, data, root / "si", engine)
        except (m3.Refusal, OSError, ValueError, KeyError) as exc:
            si["blockers"] = [str(exc)]
            si["verdict"] = "FAIL" if getattr(exc, "rule", "") == "NATIVE_EXECUTION_FAILED" else "NOT_MEASURED"
    except (m3.Refusal, OSError, ValueError) as exc:
        scenarios = [{"id": row["id"], "status": "NOT_MEASURED", "criteria": [], "reason": str(exc)} for row in rows]
    if m3.inputs(project, top) != before:
        raise m3.Refusal("STALE_INPUT", "inputs changed during native execution")
    common = {"producer": m3.PROGRAM, "schema": SCHEMA, **m3.subject(project, top),
              "scope": data["scope"], "full_design_verified": False}
    verdict = "FAIL" if any(s["status"] == "FAIL" for s in scenarios) else (
        "PASS" if len(scenarios) == len(rows) and all(s["status"] == "PASS" for s in scenarios) else "NOT_MEASURED")
    cosim = {**common, "verdict": verdict, "scenarios": scenarios, "all_scenarios_passed": verdict == "PASS"}
    write_json(project / m3.COSIM, cosim)
    write_json(project / m3.SI, {**common, **si})
    artifacts = [p for p in root.rglob("*") if p.is_file()]
    outputs = {str(p.relative_to(project)): m3.digest(p) for p in artifacts}
    outputs.update({rel: m3.digest(project / rel) for rel in m3.OUTPUTS.values()})
    overall = "FAIL" if "FAIL" in (verdict, si["verdict"]) else "NOT_MEASURED"
    record = {"program": m3.PROGRAM, "schema": SCHEMA, **m3.subject(project, top),
              "scope": data["scope"], "full_design_verified": False, "verdict": overall,
              "inputs": before, "outputs": outputs, "execution": engine.execution,
              "tool_versions": engine.versions, "run_id": token,
              "native_root": str(root.relative_to(project)), "scenario_ids": ids,
              "cosim_verdict": verdict, "si_verdict": si["verdict"]}
    write_json(project / m3.RECEIPT, record)
    return record


def verify(project, record, kind):
    m3 = api()
    top = record.get("top")
    if record.get("project") != str(project.resolve()):
        raise m3.Refusal("WRONG_PROJECT", "foreign native production")
    if m3.inputs(project, top) != record.get("inputs"):
        raise m3.Refusal("STALE_INPUT", "native production inputs changed")
    root = local(project, record["native_root"])
    if not re.fullmatch(r"[0-9a-f]{32}", record["run_id"]) or root != project / m3.DIR / "native" / record["run_id"]:
        raise m3.Refusal("WRONG_OUTPUT_PATH", "native output root differs from invocation")
    expected_paths = {str(p.relative_to(project)) for p in root.rglob("*") if p.is_file()} | set(m3.OUTPUTS.values())
    if set(record.get("outputs", {})) != expected_paths:
        raise m3.Refusal("WRONG_OUTPUT_PATH", "missing/extra canonical/native output binding")
    for rel, sha in record["outputs"].items():
        p = local(project, rel)
        if not p.is_file() or m3.digest(p) != sha:
            raise m3.Refusal("STALE_OUTPUT", rel)
    commands = record.get("execution", [])
    if not isinstance(commands, list) or not commands:
        raise m3.Refusal("MISSING_EXECUTION", "native execution missing")
    previous = 0
    for e in commands:
        if (not isinstance(e, dict) or not isinstance(e.get("command"), list)
                or type(e.get("started_ns")) is not int or type(e.get("finished_ns")) is not int
                or not previous <= e["started_ns"] <= e["finished_ns"] <= time.time_ns()):
            raise m3.Refusal("MISSING_EXECUTION", "invalid/native command sequence")
        previous = e["finished_ns"]
        if e.get("input_sha256") != record["inputs"]:
            raise m3.Refusal("STALE_INPUT", "native command inputs differ from current production inputs")
        log = local(project, e["log"])
        if (str(log.relative_to(project)) not in record["outputs"] or
                not e["started_ns"] <= log.stat().st_mtime_ns <= e["finished_ns"]):
            raise m3.Refusal("STALE_NATIVE_OUTPUT", "command log is not from this invocation")
        if e.get("exit_code") != 0:
            raise m3.Refusal("NATIVE_EXECUTION_FAILED", "native execution failed")
    data = contract(project, top)
    rows = m3.plan(project)
    ids = [r.get("id") for r in rows]
    if not rows or len(set(ids)) != len(ids) or record.get("scenario_ids") != ids:
        raise m3.Refusal("WRONG_SCENARIOS", "current nonempty L22 denominator differs")
    common = {"producer": m3.PROGRAM, "schema": SCHEMA, **m3.subject(project, top),
              "scope": data["scope"], "full_design_verified": False}
    actual = m3.read(project / m3.OUTPUTS[kind])
    if any(actual.get(k) != v for k, v in common.items()):
        raise m3.Refusal("WRONG_DESIGN", "native result belongs to another subject/scope")
    # The producer cannot replace the real tool probes with version assertions.
    for i, (name, flags) in enumerate((("ngspice", ["--version"]), ("iverilog", ["-V"]), ("vvp", ["-V"]))):
        e = commands[i] if i < len(commands) else {}
        log = root / (name + "-version.log")
        if (e.get("command") != [name, *flags] or e.get("stage") != "version" or
                e.get("log") != str(log.relative_to(project)) or not log.is_file() or
                record.get("tool_versions", {}).get(name) != log.read_text().strip() or
                not log.read_text().strip()):
            raise m3.Refusal("MISSING_TOOL_VERSION", name)
    if kind == "cosim":
        native = []
        for row in rows:
            work = root / row["id"]
            d = data["digital"]
            sources = [str(local(project, d["netlist"])), *(str(local(project, p)) for p in d.get("extra_sources", []))]
            specs = [
                (["iverilog", "-g2012", "-s", "m3_sampled_tb", "-o", str(work / "drive.vvp"),
                  *sources, str(work / "drive_tb.v")], "compile", "compile-drive.log", project, ["drive.vvp"]),
                (["vvp", str(work / "drive.vvp")], "measurement", "drive.log", project, []),
                (["/usr/bin/time", "-f", "%M", "-o", str(work / "ngspice.rss"),
                  "ngspice", "-q", "-b", str(work / "scenario.sp")], "measurement", "ngspice.log", work,
                 ["wave.txt", "ngspice.rss"]),
                (["iverilog", "-g2012", "-s", "m3_sampled_tb", "-o", str(work / "response.vvp"),
                  *sources, str(work / "response_tb.v")], "compile", "compile-response.log", project, ["response.vvp"]),
                (["vvp", str(work / "response.vvp")], "measurement", "response.log", project, []),
            ]
            offset = 3 + 5 * rows.index(row)
            for index, (cmd, stage, logfile, cwd, files) in enumerate(specs, offset):
                e = commands[index] if index < len(commands) else {}
                if (e.get("command") != cmd or e.get("stage") != stage or e.get("cwd") != str(cwd)
                        or e.get("log") != str((work / logfile).relative_to(project))):
                    raise m3.Refusal("MISSING_EXECUTION", "exact current-source compilation, ngspice and both VVP runs required")
                for filename in files:
                    file = work / filename
                    if not file.is_file() or not e["started_ns"] <= file.stat().st_mtime_ns <= e["finished_ns"]:
                        raise m3.Refusal("STALE_NATIVE_OUTPUT", "native output predates/differs from execution: " + filename)
            nglog = (work / "ngspice.log").read_text()
            if (f'M3RUN {record["run_id"]}' not in nglog or f'M3DONE {record["run_id"]}' not in nglog or
                    "No. of Data Rows" not in nglog):
                raise m3.Refusal("MISSING_EXECUTION", "no completed transient run of this deck")
            peak = int((work / "ngspice.rss").read_text().strip())
            if peak <= 0 or peak * 1024 > LIMIT or commands[offset + 2].get("peak_rss_kib") != peak:
                raise m3.Refusal("MEMORY_BUDGET_EXCEEDED", "invalid/excessive ngspice RSS receipt")
            _, _, _, cycles = settings(row)
            if (work / "initial.mem").read_text() != "0\n" * cycles:
                raise m3.Refusal("CONTRADICTS_NATIVE_OUTPUT", "initial RNM state differs from declared reset drive run")
            first = observations(work / "drive.log", record["run_id"], cycles)
            if (work / "scenario.sp").read_text() != deck(project, data, row, first, work / "wave.txt"):
                raise m3.Refusal("CONTRADICTS_NATIVE_OUTPUT", "deck differs from actual current wrapper drive")
            for name, feedback in (("drive", work / "initial.mem"), ("response", work / "feedback.mem")):
                if (work / (name + "_tb.v")).read_text() != tb(data, row, feedback, record["run_id"]):
                    raise m3.Refusal("CONTRADICTS_NATIVE_OUTPUT", "instrument differs from current contract")
            native.append(grade(project, data, row, work, record["run_id"]))
        passed = all(r["status"] == "PASS" for r in native)
        if (actual.get("scenarios") != native or actual.get("verdict") != ("PASS" if passed else "FAIL")
                or actual.get("all_scenarios_passed") is not passed):
            raise m3.Refusal("CONTRADICTS_NATIVE_OUTPUT", "scenario measurements/limits differ")
        if any(r["status"] != "PASS" for r in native):
            raise m3.Refusal("FAILED_MEASUREMENT", "native component measurement failed")
        return record
    from _mixed_signal_receiver_noise import declaration as noise_declaration, verify as verify_noise
    noise_spec = noise_declaration(project, data)
    if actual.get("verdict") == "FAIL" and noise_spec is None:
        raise m3.Refusal("FAILED_MEASUREMENT", "native interface timing/measurement failed")
    derived = None
    if (root / "si/timing.json").is_file():
        validate_si(project, data)
        work = root / "si"
        sta_cmds = [e for e in commands if e["command"] == ["sta", "-exit", str(work / "timing.tcl")]
                    and e["stage"] == "measurement" and e["log"] == str((work / "sta.log").relative_to(project))]
        if len(sta_cmds) != 1 or (work / "timing.tcl").read_text() != si_tcl(project, data, work):
            raise m3.Refusal("MISSING_EXECUTION", "exact current-input native STA execution required")
        e = sta_cmds[0]
        if not e["started_ns"] <= (work / "timing.json").stat().st_mtime_ns <= e["finished_ns"]:
            raise m3.Refusal("STALE_NATIVE_OUTPUT", "native STA observations predate this invocation")
        version = (work / "sta-version.log").read_text().strip()
        if not version or record.get("tool_versions", {}).get("sta") != version:
            raise m3.Refusal("MISSING_TOOL_VERSION", "sta")
        derived = derive_si(project, data, root / "si")
    elif noise_spec is not None:
        try:
            derived = timing_preflight(project, data)
        except (m3.Refusal, OSError, ValueError, KeyError) as exc:
            derived = si_refusal(exc)
        if derived is None:
            raise m3.Refusal("MISSING_EXECUTION", "complete timing inputs have no native STA observation")
    if noise_spec is not None:
        measured = verify_noise(project, data, root, record)
        derived = blend_receiver_noise(derived, measured)
    if derived is not None:
        if any(actual.get(k) != v for k, v in derived.items()):
            raise m3.Refusal("CONTRADICTS_NATIVE_OUTPUT", "SI report differs from current STA/SPEF")
        diagnostics = {"coverage": derived["coverage"], "scope": data["scope"], "full_design_verified": False}
        if noise_spec is not None:
            diagnostics["receiver_noise"] = measured
        if derived["verdict"] == "FAIL":
            exc = m3.Refusal("FAILED_MEASUREMENT", "current native interface timing/noise measurement failed")
        elif any(v != "MEASURED" for v in derived["coverage"].values()):
            exc = m3.Refusal("SI_COVERAGE_NOT_MEASURED", "required timing/noise/crosstalk dimensions remain unmeasured/advisory")
        else:
            return record
        exc.diagnostics = diagnostics
        raise exc
    raise m3.Refusal("SI_COVERAGE_NOT_MEASURED", "receiver/noise/crosstalk coverage cannot qualify full M3")
