"""Default analog simulation steps A06--A10 using delivered DUT testbenches.

The caller stops dependent work on FAIL or NOT_MEASURED. These functions run
existing producers and native ngspice; they do not issue tool qualifications.
Limits and calibration applicability come from the project's ordinary config.
An executed measurement without its required limits is reported NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import analog_real_corner_sweep as sweep
import ams_analysis_select
from _atomic_artefact import write_json

_ANALYSIS = re.compile(r"(?im)^\s*\.?((?:tran|ac|dc|op|noise|tf|pz|disto))\b")
_MEASURE = re.compile(r"(?im)^\s*\.?meas(?:ure)?\s+(?:tran|ac|dc|op|noise|sp)\s+([A-Za-z_]\w*)\b")
_INCLUDE = re.compile(r"(?im)^\s*\.inc(?:lude)?\s+([^\n]+)")
_SUBCKT = re.compile(r"(?im)^\s*\.subckt\s+(\S+)")
_LET = re.compile(r"(?i)^\s*let\s+([A-Za-z_]\w*)\s*=\s*(.+)")
_ECHO_OUTPUT = re.compile(r"(?i)\b([A-Za-z_]\w*)\s*=\s*[\"']?\s*\$&([A-Za-z_]\w*)\b")


def _result(status, detail, *, outputs=None, metrics=None, executions=None):
    return {"status": status, "detail": detail, "outputs": outputs or [],
            "metrics": metrics or {}, "executions": executions or []}


def _config(options, block, step):
    config = options.get("config") or {}
    blocks = config.get("blocks") or {}
    name = str(block.get("name") or block.get("block") or "")
    local = blocks.get(name, {}) if isinstance(blocks, dict) else {}
    if not isinstance(local, dict):
        local = {}
    selected = (config.get("steps") or {}).get(step, {})
    local_step = (local.get("steps") or {}).get(step, {})
    return {**local, **(selected if isinstance(selected, dict) else {}),
            **(local_step if isinstance(local_step, dict) else {})}


def _read(path):
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace")
        return json.loads(data)
    except (OSError, ValueError):
        return None


def _path(project, value, fallback):
    path = Path(value) if value else fallback
    return path if path.is_absolute() else project / path


def _inputs(project, name, config):
    roots = [project / phase / "analog" / name for phase in ("phase3", "phase2")]
    bdir = next((root for root in roots if root.is_dir()), roots[0])
    return (_path(project, config.get("netlist"), bdir / (name + ".sp")),
            _path(project, config.get("testbench"), bdir / ("tb_" + name + ".sp")),
            _path(project, config.get("spec"), bdir / "spec.json"))


def _attempt(project, step, name):
    root = project / "reports" / "analog_native" / step / name
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=root))


def _incremental_source_manifest(project, name, config, options, reference, kind):
    """Bind an explicit native population manifest to this delivered block."""
    if not isinstance(reference, dict) or not reference.get("path") or not reference.get("sha256"):
        raise ValueError("incremental study requires a manifest path and digest")
    path = _path(project, reference["path"], project).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("incremental study manifest digest changed")
    manifest = _read(path)
    if (not isinstance(manifest, dict) or manifest.get("kind") != kind
            or manifest.get("stage") != "PRE" or manifest.get("block") != name
            or Path(manifest.get("project") or "").resolve() != project.resolve()
            or not options.get("image") or manifest.get("image") != options["image"]):
        raise ValueError("incremental study manifest does not belong to this block/runtime")
    views = manifest.get("native_inputs") or {}
    if not isinstance(views, dict):
        raise ValueError("incremental study source views must be an object")
    for role, current in zip(("netlist", "testbench", "spec"), _inputs(project, name, config)):
        view = views.get(role) or {}
        if (not isinstance(view, dict) or Path(view.get("path") or "").resolve() != current.resolve()
                or view.get("sha256") != hashlib.sha256(current.read_bytes()).hexdigest()):
            raise ValueError("incremental study source differs from the current " + role)
    return path, manifest


def _deck_text(path):
    return "\n".join(line for line in path.read_text(errors="replace").splitlines()
                     if not line.lstrip().startswith(("*", ";")))


def _included_paths(deck, seen=None):
    seen = set() if seen is None else seen
    if deck in seen or not deck.is_file():
        return seen
    seen.add(deck)
    for match in _INCLUDE.finditer(_deck_text(deck)):
        try:
            parts = shlex.split(match.group(1))
        except ValueError:
            continue
        if parts:
            candidate = Path(parts[0])
            if not candidate.is_absolute():
                candidate = deck.parent / candidate
            _included_paths(candidate.resolve(), seen)
    return seen


def _measurement_names(text):
    """Native .meas names and MEAS echoes of measured ngspice vectors.

    The existing OP producer uses ``let value = v(node)`` then an echo of
    ``$&value``. A numeric echo or a let of a constant is not a DUT measure.
    """
    measured = {name.casefold() for name in _MEASURE.findall(text)}
    vectors = set(measured)
    for line in text.splitlines():
        assignment = _LET.match(line)
        if assignment:
            name, expression = assignment.group(1).casefold(), assignment.group(2)
            references = {token.casefold() for token in re.findall(r"[A-Za-z_]\w*", expression)}
            if re.search(r"(?i)\b(?:v(?:db|p|m)?|i)\s*\(", expression) or vectors.intersection(references):
                vectors.add(name)
            else:
                vectors.discard(name)
        if re.match(r"(?i)^\s*echo\s+", line) and re.search(r"\bMEAS\b", line, re.I):
            for name, value in _ECHO_OUTPUT.findall(line):
                if value.casefold() in vectors:
                    measured.add(name.casefold())
    return sorted(measured)


def _validate_deck(netlist, deck, config):
    if not netlist.is_file() or not deck.is_file():
        return "NOT_MEASURED", "delivered DUT netlist or testbench is absent", []
    text = _deck_text(deck)
    if netlist.resolve() not in _included_paths(deck.resolve()):
        return "FAIL", "testbench does not include the delivered DUT netlist", []
    subckts = {name.casefold() for name in _SUBCKT.findall(_deck_text(netlist))}
    top_text = re.sub(r"(?ims)^\s*\.subckt\b.*?^\s*\.ends\b[^\n]*", "", text)
    instances = [line.split() for line in top_text.splitlines()
                 if re.match(r"(?i)^\s*x\S+\s", line)]
    if subckts and not any(subckts.intersection(token.casefold() for token in row[1:])
                          for row in instances):
        return "FAIL", "testbench includes a subcircuit library but never instantiates its DUT", []
    if not _ANALYSIS.search(top_text):
        return "NOT_MEASURED", "testbench contains no native analysis", []
    span = sweep.measurement_span(top_text)
    stop = span.get("declared_stop_s")
    if stop is not None and any(row["end_s"] > stop for row in span["windowed"]):
        return "FAIL", "measurement window extends beyond the declared transient record", []
    measures = _measurement_names(top_text)
    required = config.get("required_measurements", measures)
    if not isinstance(required, list) or not required or any(not isinstance(x, str) for x in required):
        return "NOT_MEASURED", "testbench has no declared measurement names", []
    required = sorted({name.casefold() for name in required})
    absent = sorted(set(required) - set(measures))
    if absent:
        return "NOT_MEASURED", "required measurements absent from testbench: " + ", ".join(absent), required
    return "PASS", "delivered DUT is instantiated and native analyses/measurements are present", required


def _selected_ngspice_identity(options):
    """Resolve the tool from the execution side, never from an active-run claim."""
    container = str(options.get("container") or "")
    if container:
        try:
            selected = sweep._resolve_ngspice(container)
            if not selected:
                return None
            from analog_a8_hardmacro_emit import _remote_sha256
            digest, _reason = _remote_sha256(container, selected)
            if not digest:
                return None
            return {"scope": "container", "path": selected, "sha256": digest}
        except Exception:  # Existing resolver refusal means unverified, not absent.
            return None
    selected = shutil.which("ngspice")
    if not selected:
        return None
    try:
        path = Path(selected).resolve(strict=True)
        return {"scope": "host", "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    except OSError:
        return None


def _active_runs(options, name):
    records = ((options.get("config") or {}).get("active_runs") or {}).get(name, [])
    alive = []
    for record in records:
        try:
            pid = int(record["pid"])
            if pid <= 0:
                continue
            proc = Path("/proc") / str(pid)
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            state, starttime = fields[0], int(fields[19])
            if state == "Z":
                continue
            if type(record.get("starttime")) is not int or record["starttime"] != starttime:
                continue
            argv = [(item.decode("utf-8")) for item in
                    (proc / "cmdline").read_bytes().split(b"\0") if item]
            if (not argv or not isinstance(record.get("argv"), list)
                    or argv != record["argv"] or any(not isinstance(item, str) for item in argv)):
                continue
            executable = Path(os.readlink(proc / "exe")).resolve()
            executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
            cwd = (proc / "cwd").resolve()
            def option_path(flag):
                index = argv.index(flag)
                value = Path(argv[index + 1])
                return (value if value.is_absolute() else cwd / value).resolve()
            deck = Path(record["deck"]).resolve()
            log = Path(record["log"]).resolve()
            if option_path("-b") != deck or option_path("-o") != log or not log.is_file():
                continue
            if hashlib.sha256(deck.read_bytes()).hexdigest() != record["deck_sha256"]:
                continue
            expected_container = str(options.get("container") or "")
            if expected_container:
                cid = record.get("cid")
                if (record.get("container") != expected_container or not isinstance(cid, str)
                        or not cid or cid not in (proc / "cgroup").read_text()):
                    continue
            elif record.get("container") or record.get("cid"):
                continue
            final_starttime = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[19])
            if final_starttime != starttime:
                continue
            retained = {key: record[key] for key in
                          ("pid", "starttime", "argv", "executable", "executable_sha256",
                           "container", "cid", "deck", "log", "deck_sha256")
                          if key in record}
            selected = _selected_ngspice_identity(options)
            if selected is None:
                alive.append({**retained, "transport_identity": "UNVERIFIED",
                              "reason": "selected ngspice identity is not currently observable"})
                continue
            if selected["scope"] == "host":
                matches = (str(executable) == selected["path"]
                           and executable_sha256 == selected["sha256"])
            else:
                selected_name = Path(selected["path"]).name
                matches = (Path(argv[0]).name == selected_name
                           and executable_sha256 == selected["sha256"])
            if not matches:
                continue
            alive.append({**retained, "transport_identity": "VERIFIED",
                          "selected_tool": selected})
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, IndexError):
            continue
    return alive


def _changed_native_inputs(native_inputs):
    changed = []
    for role, view in native_inputs.items():
        path = Path(view.get("path") or "__missing_native_input__")
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            current = None
        if current != view.get("sha256"):
            changed.append(role)
    return changed


def _log_text(execution):
    text = "\n".join(str(execution.get(key) or "") for key in ("stdout", "stderr"))
    for key in ("log", "log_path", "stdout_path", "stderr_path"):
        value = execution.get(key)
        if isinstance(value, dict):
            value = value.get("path")
        if isinstance(value, (str, Path)) and Path(value).is_file():
            text += "\n" + Path(value).read_text(errors="replace")
    return text


def _bounds(spec_path, config, required):
    if "limits" in config:
        limits = config["limits"]
        return ({str(k).casefold(): v for k, v in limits.items()}
                if isinstance(limits, dict) else {})
    spec = _read(spec_path) or {}
    rows = spec.get("specs") or spec.get("spec") or []
    return {str(row["name"]).casefold(): {k: row[k] for k in ("min", "max", "unit") if k in row}
            for row in rows if isinstance(row, dict) and row.get("name")
            and str(row["name"]).casefold() in required
            and any(k in row for k in ("min", "max"))} if isinstance(rows, list) else {}


def _source_measurement_coverage(spec_path, rows):
    """Compare graded PVT metrics with the existing source-analysis mapping.

    The selector identifies measured performance requirements; supply/load
    conditions that it does not classify are not invented output metrics.
    Numeric native results are required even when their status says PASS.
    """
    spec = _read(spec_path)
    if not isinstance(spec, dict):
        return {"required": [], "measured": [], "missing": [],
                "detail": "analog source specification is absent or unreadable"}
    analyses, mapping = ams_analysis_select.select(spec)
    normalize = lambda name: sweep.normalize_spec_label(name) or str(name).casefold()
    required = sorted({normalize(row["key"]) for row in mapping})
    measured = sorted({normalize(row["name"]) for row in rows
                       if isinstance(row, dict) and row.get("name")
                       and row.get("status") == "PASS"
                       and isinstance(row.get("value"), (int, float))
                       and not isinstance(row["value"], bool)
                       and math.isfinite(row["value"])})
    return {"required": required, "measured": measured,
            "missing": sorted(set(required) - set(measured)), "analyses": analyses,
            "detail": "" if required else "source-required analyses could not be selected"}


def _source_deck_coverage(spec_path, deck):
    """Check delivered definitions without inventing measured values."""
    source = _read(spec_path)
    if not isinstance(source, dict):
        return {}, "analog source specification is absent or unreadable"
    analyses, mapping = ams_analysis_select.select(source)
    normalize = lambda name: sweep.normalize_spec_label(name) or str(name).casefold()
    required = sorted({normalize(row["key"]) for row in mapping})
    text = _deck_text(deck)
    defined = sorted({normalize(name) for name in _measurement_names(text)})
    observed = sorted({"." + match.casefold() for match in _ANALYSIS.findall(text)})
    missing_names = sorted(set(required) - set(defined))
    missing_analyses = sorted(set(analyses) - set(observed))
    metrics = {
        "measurement_definition_coverage": {"source_required": required, "defined": defined,
                                            "missing": missing_names},
        "analysis_coverage": {"source_required": analyses, "observed": observed,
                              "missing": missing_analyses}}
    absent = []
    if missing_names:
        absent.append("source-required measurement definitions absent: " + ", ".join(missing_names))
    if missing_analyses:
        absent.append("source-required analyses absent: " + ", ".join(missing_analyses))
    return metrics, "; ".join(absent)


def attributed_study_measurements(spec_path, bindings, values):
    """Grade explicitly attributed native contexts against existing source limits."""
    required = _source_measurement_coverage(spec_path, [])["required"]
    limits = _bounds(spec_path, {}, required)
    normalize = lambda key: sweep.normalize_spec_label(str(key)) or str(key).casefold()
    unit = lambda value: str(value).replace("µ", "u").replace("μ", "u")
    rows = []
    for label, value in values.items():
        binding = (bindings.get("measurements") or {}).get(label) or {}
        key = normalize(binding.get("spec_key", label))
        if key not in required:
            continue  # An engineering point is not an undeclared global metric.
        bound = limits.get(key) or {}
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        compatible = not bound.get("unit") or unit(binding.get("unit")) == unit(bound["unit"])
        edges = [bound[edge] for edge in ("min", "max") if edge in bound]
        valid_limits = bool(edges) and all(isinstance(limit, (int, float)) and
            not isinstance(limit, bool) and math.isfinite(limit) for limit in edges)
        row = {"name": key, "label": label, "value": value, "unit": binding.get("unit"),
               "status": "PASS" if numeric and compatible and valid_limits else "NOT_MEASURED"}
        if binding.get("interpretation") == "upper_bound_when_regulated":
            paired = binding.get("regulation_measurement")
            pair_binding = (bindings.get("measurements") or {}).get(paired) or {}
            pair_value, regulated = values.get(paired), limits.get("vout") or {}
            regulation_limits = [regulated[edge] for edge in ("min", "max") if edge in regulated]
            valid_regulation_limits = bool(regulation_limits) and all(
                isinstance(limit, (int, float)) and not isinstance(limit, bool) and math.isfinite(limit)
                for limit in regulation_limits)
            same_point = all(binding.get(field) == pair_binding.get(field)
                             for field in ("analysis", "at", "frequency_hz"))
            regulation_ok = (same_point and normalize(pair_binding.get("spec_key", paired)) == "vout"
                and isinstance(pair_value, (int, float)) and not isinstance(pair_value, bool)
                and math.isfinite(pair_value) and valid_regulation_limits
                and (not regulated.get("unit") or unit(pair_binding.get("unit")) == unit(regulated["unit"]))
                and all((edge != "min" or pair_value >= limit) and
                        (edge != "max" or pair_value <= limit) for edge, limit in regulated.items()
                        if edge in ("min", "max")))
            row.update(interpretation="upper_bound_when_regulated", regulation_measurement=paired,
                       regulation_valid=regulation_ok)
            if not regulation_ok:
                row["status"] = "NOT_MEASURED"
            if not numeric or value < 0:
                row.update(status="NOT_MEASURED", detail="dropout headroom upper bound must be nonnegative")
            elif valid_limits and (("max" in bound and value > bound["max"]) or "min" in bound):
                row.update(status="NOT_MEASURED", detail="an upper bound alone does not establish this source limit")
        row["violation"] = row["status"] == "PASS" and any(
            (edge == "min" and value < limit) or (edge == "max" and value > limit)
            for edge, limit in bound.items() if edge in ("min", "max"))
        rows.append(row)
    return rows


def _bound_studies(project, name, config, options, run, step):
    """Consume/run ordinary explicit measurement inputs, keeping scope partial."""
    netlist, _deck, spec = _inputs(project, name, config)
    entries = config.get("measurement_studies")
    if entries is None:
        entries = _read(netlist.parent / "measurement_studies.json")
        if isinstance(entries, dict):
            entries = entries.get("studies")
    if not isinstance(entries, list) or not entries:
        return None
    values, units, studies, outputs, executions = {}, {}, [], [], []
    attributed, definitions, analyses, native_inputs = [], set(), set(), {}

    def valid(record, template, bindings_path, bindings):
        if not isinstance(record, dict) or record.get("bindings") != bindings:
            return False
        source = bindings.get("source") or {}
        if isinstance(source, dict) and source.get("path") and source.get("sha256"):
            source_path = Path(source["path"])
            if not source_path.is_file() or source["sha256"] != hashlib.sha256(source_path.read_bytes()).hexdigest():
                return False
        views = record.get("native_inputs") or {}
        from analog_bound_measurements import validate_consumed_inputs
        current, _why = validate_consumed_inputs(project, views)
        if not current:
            return False
        for role, path in (("netlist", netlist), ("testbench", template), ("bindings", bindings_path)):
            view = views.get(role) or {}
            if view.get("path") != str(path.resolve()) or view.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
                return False
        for view in views.values():
            if not isinstance(view, dict) or not view.get("path") or not Path(view["path"]).is_file() or view.get("sha256") != hashlib.sha256(Path(view["path"]).read_bytes()).hexdigest():
                return False
        capture = record.get("capture")
        if capture and (not Path(capture.get("path", "")).is_file()
                        or capture.get("sha256") != hashlib.sha256(Path(capture["path"]).read_bytes()).hexdigest()):
            return False
        native = record.get("executions") or []
        if not native:
            return False
        for execution in native:
            log = Path(execution.get("log") or "__missing_native_log__")
            if not log.is_file() or execution.get("log_sha256") != hashlib.sha256(log.read_bytes()).hexdigest():
                return False
        # The native transcript is the value authority, even for retained JSON.
        transcript = "\n".join(Path(execution["log"]).read_text(errors="replace") for execution in native)
        expected_temperature = (bindings.get("analysis") or {}).get("temperature_c")
        if expected_temperature is not None:
            if (isinstance(expected_temperature, bool) or
                    not isinstance(expected_temperature, (int, float)) or
                    not math.isfinite(expected_temperature) or expected_temperature <= -273.15):
                return False
            native_temperatures = [float(value) for value in re.findall(
                r"(?i)Doing analysis at TEMP\s*=\s*([-+\d.eE]+)", transcript)]
            if (not native_temperatures or not all(math.isclose(value, expected_temperature,
                    rel_tol=0, abs_tol=1e-6) for value in native_temperatures)):
                return False
        actual = {key.casefold(): value for key, value in sweep.native_meas_rows(transcript).items()}
        for match in sweep._MEAS_LINE_RE.finditer(transcript):
            for key, value in sweep._KV_RE.findall(match.group(1)):
                actual.setdefault(key.casefold(), float(value))
        return all(actual.get(key) == value for key, value in (record.get("measurements") or {}).items())

    previous = ((options.get("previous_results") or {}).get("A06") or {}).get(name) or {}
    retained_studies = (previous.get("metrics") or {}).get("native_measurement_studies") or []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("kind") == "incremental_capture":
            import analog_incremental_capture as incremental
            row = incremental.consume_study(project, name, entry, options, run, step)
            studies.append(row)
            outputs += row.get("outputs", [])
            executions += row.get("executions", [])
            native_inputs.update(row.get("native_inputs", {}))
            if row["status"] == "PASS":
                definitions.update(row.get("definitions", []))
                analyses.update(row.get("analyses", []))
                measured = row.get("measurements", {})
                values.update(measured)
                binding = {"measurements": {key: {"unit": "bit" if key == "enob" else "dB"}
                                             for key in measured}}
                attributed += attributed_study_measurements(spec, binding, measured)
            continue
        if not isinstance(entry, dict) or not entry.get("testbench") or not entry.get("bindings"):
            studies.append({"status": "NOT_MEASURED", "detail": "measurement study lacks template/bindings"})
            continue
        template = _path(project, entry["testbench"], netlist.parent)
        bindings_path = _path(project, entry["bindings"], netlist.parent)
        bindings = _read(bindings_path)
        if not template.is_file() or not isinstance(bindings, dict):
            studies.append({"status": "NOT_MEASURED", "detail": "measurement study input absent"})
            continue
        candidates = ([entry["result"]] if entry.get("result") else []) + [row["result"]
            for row in retained_studies if row.get("bindings_path") == str(bindings_path.resolve()) and row.get("result")]
        record, result_path = None, None
        for candidate in candidates:
            path = _path(project, candidate, netlist.parent)
            data = _read(path)
            if valid(data, template, bindings_path, bindings):
                record, result_path = data, path
                break
        reused = record is not None
        if record is None:
            destination = _attempt(project, step + "-measurements", name)
            result_path = destination / "result.json"
            execution = run("analog_bound_measurements.py", [str(project), "--netlist", str(netlist),
                "--testbench", str(template), "--bindings", str(bindings_path), "--out", str(destination),
                "--container", str(options.get("container", "")), "--image", str(options.get("image", ""))],
                outputs=[str(result_path)])
            executions.append(execution)
            record = _read(result_path)
            if not valid(record, template, bindings_path, bindings):
                studies.append({"status": "NOT_MEASURED", "detail": "native study has no current input/log-bound terminal result"})
                continue
        native = record.get("executions") or []
        codes = [execution.get("returncode") for execution in native]
        transcript = "\n".join(Path(execution["log"]).read_text(errors="replace") for execution in native)
        interrupted = any(code in (130, 137, 143) or isinstance(code, int) and code < 0 for code in codes)
        native_failed = any(isinstance(code, int) and code != 0 for code in codes) or any(
            sweep._scan_analysis_failures(transcript)) or re.search(
                r"(?im)\bfatal(?: error)?\b|\bsimulation(?:\(s\)|s)?\s+aborted\b|\btimestep too small\b", transcript)
        state = record.get("status") if record.get("status") in ("PASS", "FAIL", "NOT_MEASURED") else "NOT_MEASURED"
        if interrupted or any(not isinstance(code, int) for code in codes):
            state = "NOT_MEASURED"
        elif native_failed:
            state = "FAIL"
        studies.append({"status": state, "result": str(result_path), "bindings_path": str(bindings_path.resolve()),
                        "reused": reused, "measurements": record.get("measurements", {}),
                        "capture": record.get("capture"), "scope": record.get("scope"),
                        "native_returncodes": codes})
        outputs.append(str(result_path))
        if record.get("capture"):
            outputs.append(record["capture"]["path"])
        if state == "PASS":
            graded = attributed_study_measurements(spec, bindings, record.get("measurements", {}))
            attributed += graded
            definitions.update(row["name"] for row in graded if row["status"] == "PASS")
            analyses.add("." + str((bindings.get("analysis") or {}).get("kind", "")).lower())
            native_inputs.update({f"study:{len(studies)}:{role}": view
                                  for role, view in (record.get("native_inputs") or {}).items()})
            for key, value in record.get("measurements", {}).items():
                if key not in values:
                    values[key] = value
                    units[key] = (bindings.get("measurements", {}).get(key) or {}).get("unit")
    violations = [row["label"] for row in attributed if row["violation"]]
    coverage = _source_measurement_coverage(spec, attributed)
    missing_analyses = sorted(set(coverage.get("analyses", [])) - analyses)
    method_missing = sorted(set(coverage["required"]) - definitions)
    metrics = {**values, "native_measurement_studies": studies, "source_measurement_coverage": coverage,
               "attributed_measurements": attributed,
               "measurement_definition_coverage": {"source_required": coverage["required"],
                    "defined": sorted(definitions), "missing": method_missing},
               "analysis_coverage": {"source_required": coverage.get("analyses", []),
                    "observed": sorted(analyses), "missing": missing_analyses},
               "measured_spec_violations": violations,
               "ungraded_native_units": [row["label"] for row in attributed if row["status"] != "PASS"]}
    complete = (bool(coverage["required"]) and not missing_analyses
                and not (method_missing if step == "A06" else coverage["missing"])
                and all(row["status"] == "PASS" for row in studies)
                and all(row["status"] == "PASS" for row in attributed))
    status = "FAIL" if violations or any(row["status"] == "FAIL" for row in studies) else "PASS" if complete else "NOT_MEASURED"
    absent = method_missing if step == "A06" else coverage["missing"]
    detail = ("native study methods cover source requirements" if complete and step == "A06" else
              "native study measurements cover source requirements" if complete else
              "explicit native studies retained; whole-block measurement coverage remains incomplete")
    if violations:
        detail = "native study measurements violate source limits: " + ", ".join(violations)
    elif any(row["status"] == "FAIL" for row in studies):
        detail = "native measurement study failed"
    if absent:
        detail += "; source requirements missing: " + ", ".join(absent)
    if missing_analyses:
        detail += "; source analyses missing: " + ", ".join(missing_analyses)
    result = _result(status, detail,
                   outputs=outputs, metrics=metrics, executions=executions)
    result["native_inputs"] = native_inputs
    return result


def _has_incremental_study(project, name, config):
    entries = config.get("measurement_studies")
    if entries is None:
        entries = _read(project / "phase3/analog" / name / "measurement_studies.json")
        entries = entries.get("studies", []) if isinstance(entries, dict) else entries
    return isinstance(entries, list) and any(isinstance(entry, dict) and
        entry.get("kind") == "incremental_capture" for entry in entries)


def _nominal(project, name, config, options, run, *, step="A07"):
    netlist, deck, spec_path = _inputs(project, name, config)
    native_inputs = {role: {"path": str(path.resolve()),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
                     for role, path in (("netlist", netlist), ("testbench", deck), ("spec", spec_path))}

    def result(status, detail, **values):
        measured_inputs = values.pop("native_inputs", {})
        return {**_result(status, detail, **values), "native_inputs": {**native_inputs, **measured_inputs}}

    status, detail, required = _validate_deck(netlist, deck, config)
    if status != "PASS":
        studies = _bound_studies(project, name, config, options, run, step) if (
            status == "NOT_MEASURED" and netlist.is_file()) else None
        if studies is not None:
            return result(studies["status"], studies["detail"], metrics=studies["metrics"],
                          outputs=studies["outputs"], executions=studies["executions"],
                          native_inputs=studies.get("native_inputs", {}))
        return result(status, detail)
    if step == "A07":
        readiness, missing = _source_deck_coverage(spec_path, deck)
        if missing:
            studies = _bound_studies(project, name, config, options, run, step)
            if studies is not None:
                return result(studies["status"], studies["detail"],
                              metrics={**readiness, **studies["metrics"]}, outputs=studies["outputs"],
                              executions=studies["executions"], native_inputs=studies.get("native_inputs", {}))
            return result("NOT_MEASURED", missing, metrics=readiness)
    execution = run("@ngspice", ["-b", str(deck)], cwd=deck.parent)
    transcript = _log_text(execution)
    metrics = {key.casefold(): value for key, value in sweep.native_meas_rows(transcript).items()}
    for match in sweep._MEAS_LINE_RE.finditer(transcript):
        for key, value in sweep._KV_RE.findall(match.group(1)):
            metrics.setdefault(key.casefold(), float(value))
    failures = sweep._scan_analysis_failures(transcript)
    aborted = re.search(r"(?im)\bfatal(?: error)?\b|\bsimulation(?:\(s\)|s)?\s+aborted\b|\btimestep too small\b", transcript)
    native_failure = bool(failures[0] or failures[1] or failures[2] or aborted)
    rc = execution.get("returncode")
    interrupted = isinstance(rc, int) and (rc < 0 or rc in (130, 137, 143))
    changed_inputs = _changed_native_inputs(native_inputs)
    coverage = _source_measurement_coverage(spec_path, [
        {"name": key, "value": value, "status": "PASS"} for key, value in metrics.items()])
    if coverage["required"]:
        required = sorted(set(required) | set(coverage["required"]))
        metrics["source_measurement_coverage"] = coverage
    missing = [key for key in required if key not in metrics or not math.isfinite(metrics[key])]
    limits = _bounds(spec_path, config, required)
    malformed, violated = [], []
    for key in required:
        bound = limits.get(key)
        if not isinstance(bound, dict) or not any(k in bound for k in ("min", "max")):
            malformed.append(key)
            continue
        for edge in ("min", "max"):
            limit = bound.get(edge)
            if limit is None:
                continue
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit):
                malformed.append(key)
                continue
            if key not in missing and ((edge == "min" and metrics[key] < limit)
                                       or (edge == "max" and metrics[key] > limit)):
                violated.append(key)
    # Partial coverage removes PASS; it cannot erase a measured violation.
    if violated:
        detail = "native measurement outside declared spec limit: " + ", ".join(sorted(set(violated)))
        if missing:
            detail += "; native measurement absent or non-finite: " + ", ".join(missing)
        return result("FAIL", detail, metrics=metrics, executions=[execution])
    if native_failure:
        return result("FAIL", "native ngspice reports an analysis or measurement error",
                       metrics=metrics, executions=[execution])
    if interrupted:
        return result("NOT_MEASURED", "native ngspice execution was interrupted",
                       metrics=metrics, executions=[execution])
    if rc != 0:
        return result("FAIL", "native ngspice did not complete successfully",
                       metrics=metrics, executions=[execution])
    if changed_inputs:
        return result("NOT_MEASURED", "native consumed inputs changed during execution: "
                       + ", ".join(changed_inputs), metrics=metrics, executions=[execution])
    if missing:
        return result("NOT_MEASURED", "native measurement absent or non-finite: " + ", ".join(missing),
                       metrics=metrics, executions=[execution])
    if not limits or set(required) - set(limits):
        return result("NOT_MEASURED", "native measurements obtained; required numeric spec limits are absent",
                       metrics=metrics, executions=[execution])
    if malformed:
        return result("NOT_MEASURED", "numeric spec limit is malformed: " + ", ".join(sorted(set(malformed))),
                       metrics=metrics, executions=[execution])
    return result("PASS", "native DUT measurements satisfy the declared testbench limits",
                   outputs=[str(deck)], metrics=metrics, executions=[execution])


def run_step(step_id, project, block, options, run):
    """Run one Default simulation responsibility; preserve the native result."""
    project = Path(project).resolve()
    name = str(block.get("name") or block.get("block") or "")
    if not name or Path(name).name != name or name in (".", ".."):
        return _result("NOT_MEASURED", "analog block name is absent or invalid")
    config = _config(options, block, step_id)
    sidecar_name = {"A08": "pvt_inputs.json", "A09": "statistics_inputs.json"}.get(step_id)
    if sidecar_name:
        sidecar = project / "phase3" / "analog" / name / sidecar_name
        if sidecar.is_file():
            try:
                defaults = json.loads(sidecar.read_bytes())
            except (OSError, ValueError) as exc:
                return _result("NOT_MEASURED", f"{sidecar_name} execution inputs unreadable: {exc}")
            if not isinstance(defaults, dict):
                return _result("NOT_MEASURED", f"{sidecar_name} execution inputs must be an object")
            config = {**defaults, **config}
    if step_id == "A10":
        calibration = config.get("calibration")
        features = options.get("features") or (options.get("config") or {}).get("features") or {}
        if calibration is False or (isinstance(calibration, dict) and calibration.get("applicable") is False) or features.get("analog_trim") is False:
            return _result("NOT_APPLICABLE", "project declares no applicable trim/calibration algorithm")
        if not isinstance(calibration, dict) or not calibration.get("testbench"):
            return _result("NOT_MEASURED", "source-provided calibration DUT testbench is absent")
        config = {**config, **calibration}
    if step_id in ("A07", "A08", "A09", "A10"):
        active = _active_runs(options, name)
        independent_capture = step_id == "A07" and _has_incremental_study(project, name, config)
        if (active or name in (options.get("active_blocks") or [])) and not independent_capture:
            return _result("NOT_MEASURED", "existing native jobs are running; duplicate simulation was not launched",
                           executions=active)
    if step_id == "A06":
        netlist, deck, spec = _inputs(project, name, config)
        status, detail, required = _validate_deck(netlist, deck, config)
        executions, outputs = [], [str(deck)] if deck.is_file() else []
        metrics = {"required_measurements": required}
        if status != "PASS":
            studies = _bound_studies(project, name, config, options, run, step_id) if (
                status == "NOT_MEASURED" and netlist.is_file()) else None
            if studies is not None:
                result = _result(studies["status"], studies["detail"], outputs=studies["outputs"],
                    metrics=studies["metrics"], executions=studies["executions"])
                result["native_inputs"] = studies.get("native_inputs", {})
                return result
            return _result(status, detail, outputs=outputs, metrics=metrics)
        coverage, missing = _source_deck_coverage(spec, deck)
        metrics.update(coverage)
        if config.get("generate_measurements") and spec.is_file():
            attempt = _attempt(project, step_id, name)
            report, generated = attempt / "measurements.json", attempt / "measurements.sp"
            execution = run("analog_meas_from_spec_gen.py", [str(spec), "--out", str(generated), "--json", str(report)],
                            outputs=[str(report), str(generated)])
            executions.append(execution)
            outputs += [str(path) for path in (report, generated) if path.is_file()]
            if execution.get("returncode") != 0:
                return _result("NOT_MEASURED", "source measurement generation did not complete", outputs=outputs, executions=executions)
        if missing:
            status, detail = "NOT_MEASURED", missing
            studies = _bound_studies(project, name, config, options, run, step_id)
            if studies is not None:
                status, detail = studies["status"], studies["detail"]
                metrics.update(studies["metrics"])
                outputs += studies["outputs"]
                executions += studies["executions"]
        result = _result(status, detail, outputs=outputs, metrics=metrics, executions=executions)
        if missing and studies is not None:
            result["native_inputs"] = studies.get("native_inputs", {})
        return result
    if step_id in ("A07", "A10"):
        if step_id == "A07" and config.get("nominal_testbench"):
            config = {**config, "testbench": config["nominal_testbench"]}
        return _nominal(project, name, config, options, run, step=step_id)
    if step_id == "A08":
        prior = (options.get("previous_results") or {}).get("A07", {})
        nominal = prior.get(name, {}) if isinstance(prior, dict) else {}
        if nominal.get("status") != "PASS":
            return _result("NOT_MEASURED", "nominal A07 has not passed; PVT sweep was not launched")
        pvt = config.get("pvt")
        incremental = isinstance(pvt, dict) and pvt.get("kind") == "incremental_capture"
        if isinstance(pvt, dict) and (incremental or "result" in pvt):
            reference = pvt.get("manifest") if incremental else pvt["result"]
            if not isinstance(reference, dict) or not reference.get("path") or not reference.get("sha256"):
                return _result("NOT_MEASURED", "bound PRE PVT requires an actual result path and digest")
            reference = {**reference, "path": str(_path(project, reference["path"], project).resolve())}
            if incremental:
                try:
                    _incremental_source_manifest(project, name, config, options, reference,
                                                 "incremental_capture_pvt")
                except (OSError, ValueError, TypeError) as exc:
                    return _result("NOT_MEASURED", str(exc))
            report = _attempt(project, step_id, name) / "pvt-studies.json"
            if incremental:
                program, argv = "analog_incremental_pvt.py", ["run", reference["path"],
                    "--container", options["container"], "--image", options["image"],
                    "--workers", str(options.get("workers", 1)), "--cpus", str(options.get("cpus", 1)),
                    "--json", str(report)]
            else:
                program, argv = "analog_native_physical.py", ["pvt", str(project), "--block", name,
                    "--container", options["container"], "--image", str(options.get("image", "")),
                    "--pdk", options["pdk"], "--settings", json.dumps({"result": reference}),
                    "--json", str(report)]
            execution = run(program, argv, outputs=[str(report)])
            record = _read(report)
            record = record if isinstance(record, dict) else {}
            status = record.get("status") if record.get("status") in ("PASS", "FAIL") else "NOT_MEASURED"
            metrics = record.get("metrics")
            metrics = metrics if isinstance(metrics, dict) else {}
            _netlist, _deck, spec = _inputs(project, name, config)
            required = _source_measurement_coverage(spec, [])["required"]
            contexts = metrics.get("source_context_coverage")
            contexts = contexts if isinstance(contexts, dict) else {}
            total = metrics.get("total_corners")
            complete = (execution.get("returncode") == 0 and metrics.get("stage") == "PRE"
                and metrics.get("full_pvt_sweep_executed") is True and metrics.get("design_traceable") is True
                and isinstance(total, int) and not isinstance(total, bool) and total > 0
                and metrics.get("corners_executed") == total and bool(required)
                and not metrics.get("gaps") and not metrics.get("missing_contexts")
                and all(isinstance(contexts.get(key), dict)
                    and isinstance(contexts[key].get("required_contexts"), int)
                    and not isinstance(contexts[key]["required_contexts"], bool)
                    and contexts[key]["required_contexts"] > 0
                    and contexts[key].get("measured_contexts") == contexts[key]["required_contexts"]
                    and not contexts[key].get("missing_contexts") and not contexts[key].get("gaps")
                    for key in required))
            if metrics.get("stage") != "PRE" or status == "PASS" and not complete:
                status = "NOT_MEASURED"
            result = _result(status, record.get("detail") or "current PRE native PVT study measurements",
                outputs=[str(report), *record.get("outputs", [])], metrics=metrics, executions=[execution])
            result["native_inputs"] = record.get("native_inputs", {})
            return result
        netlist, deck, spec = _inputs(project, name, config)
        status, detail, _required = _validate_deck(netlist, deck, config)
        if status != "PASS":
            return _result(status, detail)
        result_path = netlist.parent / "corner_results.json"
        attempt = _attempt(project, step_id, name)
        previous_mtime = result_path.stat().st_mtime_ns if result_path.is_file() else None
        if result_path.is_file():
            shutil.copy2(result_path, attempt / "previous_corner_results.json")
        execution = run("analog_real_corner_sweep.py", [str(project), "--block", name, "--container", options["container"], "--pdk", options["pdk"]], outputs=[str(result_path)])
        executions = [execution]
        record = _read(result_path)
        if not isinstance(record, dict) or result_path.stat().st_mtime_ns == previous_mtime:
            return _result("NOT_MEASURED", "native PVT producer did not publish current results", executions=executions)
        metrics = {key: record.get(key) for key in ("total_corners", "corners_executed", "full_pvt_sweep_executed", "spec_results")}
        if execution.get("returncode") != 0:
            if any(row.get("status") == "FAIL" for row in record.get("spec_results", []) if isinstance(row, dict)):
                return _result("FAIL", "current native PVT results contain a measured spec failure",
                               outputs=[str(result_path)], metrics=metrics, executions=executions)
            return _result("NOT_MEASURED", "native PVT producer did not complete",
                           outputs=[str(result_path)], metrics=metrics, executions=executions)
        gate_path = attempt / "corner_check.json"
        gate = run("analog_a4_corner_sweep_check.py", [str(project), "--block", name, "--json", str(gate_path)], outputs=[str(gate_path)])
        executions.append(gate)
        outputs = [str(result_path)] + ([str(gate_path)] if gate_path.is_file() else [])
        if gate.get("returncode") == 1 or any(row.get("status") == "FAIL" for row in record.get("spec_results", []) if isinstance(row, dict)):
            return _result("FAIL", "native PVT results fail the existing per-block consumer", outputs=outputs, metrics=metrics, executions=executions)
        rows = record.get("spec_results")
        total = record.get("total_corners")
        if (gate.get("returncode") != 0 or record.get("full_pvt_sweep_executed") is not True
                or record.get("design_traceable") is not True or record.get("partial_measurement")
                or not isinstance(total, int) or total < 1 or record.get("corners_executed") != total
                or not isinstance(rows, list) or not rows
                or any(not isinstance(row, dict) or row.get("status") != "PASS" for row in rows)):
            return _result("NOT_MEASURED", "complete design-traceable PVT/spec evidence is unavailable", outputs=outputs, metrics=metrics, executions=executions)
        coverage = _source_measurement_coverage(spec, rows)
        metrics["source_measurement_coverage"] = coverage
        if coverage["detail"] or coverage["missing"]:
            detail = coverage["detail"] or ("source-required PVT measurements are missing: "
                                            + ", ".join(coverage["missing"]))
            return _result("NOT_MEASURED", detail, outputs=outputs, metrics=metrics, executions=executions)
        return _result("PASS", "native PVT sweep and existing per-block consumer passed", outputs=outputs, metrics=metrics, executions=executions)
    if step_id == "A09":
        stats = config.get("statistics", {})
        features = options.get("features") or (options.get("config") or {}).get("features") or {}
        if stats is False or (isinstance(stats, dict) and stats.get("applicable") is False) or features.get("analog_statistics") is False:
            return _result("NOT_APPLICABLE", "project declares statistics/mismatch verification inapplicable")
        prior = (options.get("previous_results") or {}).get("A07", {})
        nominal = prior.get(name, {}) if isinstance(prior, dict) else {}
        if nominal.get("status") != "PASS":
            return _result("NOT_MEASURED", "nominal A07 has not passed; Monte Carlo was not launched")
        attempt = _attempt(project, step_id, name)
        report = attempt / "mc.json"
        count = stats.get("n", 100) if isinstance(stats, dict) else 100
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            return _result("NOT_MEASURED", "Monte Carlo sample count must be a positive integer")
        incremental = isinstance(stats, dict) and stats.get("kind") == "incremental_capture"
        population = isinstance(stats, dict) and "references" in stats
        exports, measured_inputs = [], {}
        if incremental:
            try:
                manifest_path, manifest = _incremental_source_manifest(project, name, config, options,
                    stats.get("manifest"), "incremental_capture_statistics")
                samples = manifest.get("requested_samples")
                if (count < 2 or not isinstance(samples, int) or isinstance(samples, bool)
                        or samples != count):
                    raise ValueError("incremental statistics require the requested >=2 native chip samples")
            except (OSError, ValueError, TypeError) as exc:
                return _result("NOT_MEASURED", str(exc))
            execution = run("analog_incremental_statistics.py", ["run", str(manifest_path),
                "--container", options["container"], "--image", options["image"],
                "--workers", str(options.get("workers", 1)), "--cpus", str(options.get("cpus", 1)),
                "--json", str(report)], outputs=[str(report)])
            wrapper = _read(report)
            wrapper = wrapper if isinstance(wrapper, dict) else {}
            record = wrapper.get("metrics")
            if not isinstance(record, dict) or record.get("stage") != "PRE":
                return _result("NOT_MEASURED", "native incremental population did not return a PRE study",
                               outputs=[str(report)], executions=[execution])
            exports, measured_inputs = wrapper.get("outputs", []), wrapper.get("native_inputs", {})
            record = {**record, "verdict": wrapper.get("status"), "reason": wrapper.get("detail"),
                      "mc_runs": record.get("samples_executed")}
        elif population:
            references = stats["references"]
            if count < 2 or not isinstance(references, list) or not references or any(
                    not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256") for ref in references):
                return _result("NOT_MEASURED", "bound PRE statistics require >=2 samples and actual result references")
            settings = {"stage": "PRE", "samples": count, "references": [
                {**ref, "path": str(_path(project, ref["path"], project).resolve())} for ref in references]}
            execution = run("analog_native_physical.py", ["population", str(project), "--block", name,
                "--container", options["container"], "--image", str(options.get("image", "")),
                "--pdk", options["pdk"], "--settings", json.dumps(settings), "--json", str(report)],
                outputs=[str(report)])
            wrapper = _read(report)
            wrapper = wrapper if isinstance(wrapper, dict) else {}
            record = wrapper.get("metrics")
            exports, measured_inputs = wrapper.get("outputs", []), wrapper.get("native_inputs", {})
            if not isinstance(record, dict) or record.get("stage") != "PRE":
                return _result("NOT_MEASURED", "native population did not return the requested PRE study",
                               outputs=[str(report)], executions=[execution])
        else:
            execution = run("analog_native_sim.py", ["mc", str(project), "--block", name, "--container", options["container"], "--pdk", options["pdk"], "--n", str(count), "--json", str(report)], outputs=[str(report)])
            record = _read(report)
        if not isinstance(record, dict):
            return _result("NOT_MEASURED", "native Monte Carlo result is absent", executions=[execution])
        status = record.get("verdict")
        status = status if status in ("PASS", "FAIL") else "NOT_MEASURED"
        if status == "PASS" and (execution.get("returncode") != 0 or not record.get("mc_runs")
                                 or (population or incremental) and record.get("mc_runs") != count
                                 or incremental and (record.get("requested_samples") != count
                                     or record.get("native_activation_proven") is not True or record.get("gaps"))):
            status = "NOT_MEASURED"
        metrics = {key: record.get(key) for key in ("mc_runs", "mc_yield_pct", "spec_yield", "corner_results")}
        if incremental:
            metrics.update({key: record.get(key) for key in ("requested_samples", "native_activation_proven",
                            "mc_source_coverage", "cohorts", "gaps", "scope")})
        detail = str(record.get("reason") or "native Monte Carlo yield result")
        if status == "PASS":
            _netlist, _deck, spec = _inputs(project, name, config)
            rows = [{"name": key, "value": value.get("yield_pct"), "status": "PASS"}
                    for key, value in (record.get("spec_yield") or {}).items()
                    if isinstance(value, dict) and value.get("runs_scored") == record["mc_runs"]]
            coverage = _source_measurement_coverage(spec, rows)
            metrics["source_measurement_coverage"] = coverage
            if coverage["detail"] or coverage["missing"]:
                status = "NOT_MEASURED"
                detail = coverage["detail"] or ("source-required Monte Carlo measurements are missing: "
                                                 + ", ".join(coverage["missing"]))
        result = _result(status, detail, outputs=[str(report), *exports], metrics=metrics, executions=[execution])
        if population or incremental:
            result["native_inputs"] = measured_inputs
        return result
    return _result("NOT_MEASURED", "simulation responsibility is unsupported: " + str(step_id))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["mc"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--block", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--pdk", required=True)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    import analog_mc_yield_run
    report = analog_mc_yield_run.run_block(args.project.resolve(), args.block, args.container, args.pdk, args.n)
    write_json(args.json, report, indent=2, ensure_ascii=True)
    return report.get("rc", 2)


if __name__ == "__main__":
    sys.exit(main())
