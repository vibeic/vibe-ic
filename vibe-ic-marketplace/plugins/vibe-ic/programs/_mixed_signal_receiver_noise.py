"""Current declared receiver thermal/device noise from actual ngspice output.

This qualifies only the supplied two-port component at the declared bias,
temperature and frequency band. It supplies no post-route, crosstalk or PDK
coverage. The ordinary M3 producer owns execution and receipt publication.
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

import math
import re

from _atomic_artefact import write_text

SCHEMA = "vibeic.mixed_signal.receiver_noise_inputs.v1"
METRIC = "integrated_output_noise_v_rms"
UNITS = "V_RMS"
KEYS = {"schema", "id", "top", "scope", "analysis", "model", "model_sha256", "subckt",
        "ports", "dependencies", "temperature_c", "dc_drive_v", "frequency_start_hz",
        "frequency_stop_hz", "points_per_decade", "criteria"}


def native():
    import _mixed_signal_native as n
    return n


def declaration(project, data):
    n = native()
    si = data.get("si")
    if not isinstance(si, dict) or "receiver_noise" not in si:
        return None
    spec = si["receiver_noise"]
    if not isinstance(spec, dict) or set(spec) != KEYS:
        raise n.api().Refusal("UNSUPPORTED_NOISE_DECLARATION", "complete known receiver_noise fields required")
    if (spec["schema"] != SCHEMA or spec["analysis"] != "ngspice_noise" or
            spec["scope"] != "declared_model_component"):
        raise n.api().Refusal("UNSUPPORTED_NOISE_DECLARATION", "unknown analysis/schema/scope")
    if spec["top"] != data["top"]:
        raise n.api().Refusal("WRONG_DESIGN", "receiver/noise declaration belongs to another top")
    for k in ("id", "subckt"):
        if not isinstance(spec[k], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", spec[k]):
            raise n.api().Refusal("UNSUPPORTED_NOISE_DECLARATION", "literal noise identity/subcircuit required")
    if spec["ports"] != ["drive", "sense"] or not isinstance(spec["dependencies"], dict):
        raise n.api().Refusal("UNSUPPORTED_NOISE_DECLARATION", "two-port model and declared dependency hashes required")
    if spec["model"] in spec["dependencies"]:
        raise n.api().Refusal("UNSUPPORTED_NOISE_DECLARATION", "model cannot shadow its own declared hash through dependencies")
    for rel, sha in {spec["model"]: spec["model_sha256"], **spec["dependencies"]}.items():
        path = n.local(project, rel)
        if any(c in str(path) for c in '"\n\r') or not path.is_file():
            raise n.api().Refusal("MISSING_NOISE_MODEL", "project-local current model required: " + str(rel))
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) or n.api().digest(path) != sha:
            raise n.api().Refusal("STALE_NOISE_MODEL", "declared model bytes differ: " + rel)
        text = path.read_text()
        if re.search(r"(?im)^\s*\.(?:control|include|inc|lib|end|ac|noise|tran|op|dc|options?|temp|alter|save|print|plot)\b", text):
            raise n.api().Refusal("UNSUPPORTED_NOISE_MODEL", "flattened model definitions only; no hidden analysis/include/control")
    model = n.local(project, spec["model"]).read_text()
    if not re.search(r"(?im)^\s*\.subckt\s+" + re.escape(spec["subckt"]) + r"\s+\S+\s+\S+\s*$", model):
        raise n.api().Refusal("UNSUPPORTED_NOISE_MODEL", "declared two-port subcircuit absent")
    start = n.number(spec["frequency_start_hz"], "frequency_start_hz", True)
    stop = n.number(spec["frequency_stop_hz"], "frequency_stop_hz", True)
    points = spec["points_per_decade"]
    if type(points) is not int or not 20 <= points <= 200 or not start < stop <= 1e12:
        raise n.api().Refusal("UNBOUNDED_NOISE_ANALYSIS", "bounded positive frequency band and 20..200 points/decade required")
    intervals = points * math.log10(stop / start)
    if not 2 <= intervals <= 20000 or not math.isclose(intervals, round(intervals), abs_tol=1e-7):
        raise n.api().Refusal("UNBOUNDED_NOISE_ANALYSIS", "2..20000 exact logarithmic intervals required")
    temp = n.number(spec["temperature_c"], "temperature_c")
    bias = n.number(spec["dc_drive_v"], "dc_drive_v")
    if not -273.15 < temp <= 200 or not data["analog"]["drive_low_v"] <= bias <= data["analog"]["drive_high_v"]:
        raise n.api().Refusal("UNSUPPORTED_NOISE_DECLARATION", "bias/temperature outside supported declared range")
    criteria = spec["criteria"]
    if not isinstance(criteria, list) or not criteria:
        raise n.api().Refusal("UNBOUNDED_NOISE_CRITERIA", "nonempty bounded V_RMS noise criteria required")
    for c in criteria:
        if (not isinstance(c, dict) or set(c) - {"metric", "units", "min", "max"} or
                c.get("metric") != METRIC or c.get("units") != UNITS or "max" not in c):
            raise n.api().Refusal("UNBOUNDED_NOISE_CRITERIA", "known integrated output voltage noise and finite maximum required")
        for k in ("min", "max"):
            if k in c and n.number(c[k], k) < 0:
                raise n.api().Refusal("UNBOUNDED_NOISE_CRITERIA", "nonnegative noise bounds required")
        if c.get("min", 0) > c["max"]:
            raise n.api().Refusal("UNBOUNDED_NOISE_CRITERIA", "inverted noise bounds")
    return spec


def input_paths(project, data):
    spec = declaration(project, data)
    return {spec["model"], *spec["dependencies"]} if spec else set()


def deck(project, spec, token):
    n = native()
    return "\n".join([
        "* Current declared receiver noise; component evidence only",
        *(f'.include "{n.local(project, p)}"' for p in spec["dependencies"]),
        f'.include "{n.local(project, spec["model"])}"',
        f'Vdrive drive 0 DC {spec["dc_drive_v"]:.17g} AC 1',
        f'Xreceiver drive sense {spec["subckt"]}', f'.temp {spec["temperature_c"]:.17g}',
        ".control", "set sparse", "unset sqrnoise", "set numdgt=15",
        "set wr_singlescale", "set wr_vecnames",
        f'echo M3NOISE_RUN {token} {spec["id"]} {spec["model_sha256"]}',
        f'noise v(sense) Vdrive dec {spec["points_per_decade"]} {spec["frequency_start_hz"]:.17g} {spec["frequency_stop_hz"]:.17g}',
        "setplot noise1", "wrdata spectrum.txt onoise_spectrum", "setplot noise2",
        "wrdata integrated.txt onoise_total", "print onoise_total",
        f'echo M3NOISE_DONE {token} {spec["id"]}', ".endc", ".end", ""])


def command(work):
    return ["/usr/bin/time", "-q", "-f", "%M", "-o", str(work / "noise.rss"),
            "ngspice", "-q", "-b", str(work / "noise.sp")]


def samples(path, header):
    n = native()
    lines = path.read_text().splitlines()
    if not lines or lines[0].split() != header:
        raise n.api().Refusal("MISSING_NOISE_OBSERVATION", "native noise vector/header missing")
    result = []
    for line in lines[1:]:
        try:
            row = list(map(float, line.split()))
        except ValueError as exc:
            raise n.api().Refusal("FAILED_MEASUREMENT", "malformed native noise sample") from exc
        if len(row) != 2 or any(not math.isfinite(v) or v < 0 for v in row):
            raise n.api().Refusal("FAILED_MEASUREMENT", "invalid native noise sample")
        result.append(row)
    return result


def derive(project, spec, work, token):
    n = native()
    log = (work / "noise.log").read_text()
    if (f'M3NOISE_RUN {token} {spec["id"]} {spec["model_sha256"]}' not in log or
            f'M3NOISE_DONE {token} {spec["id"]}' not in log or
            re.search(r"(?mi)^\s*(?:Error(?:\s|:)|Warning:.*(?:no.*noise|unknown))", log)):
        raise n.api().Refusal("MISSING_NOISE_OBSERVATION", "no completed noise analysis for current model/invocation")
    spectrum = samples(work / "spectrum.txt", ["frequency", "onoise_spectrum"])
    count = round(spec["points_per_decade"] * math.log10(spec["frequency_stop_hz"] / spec["frequency_start_hz"])) + 1
    if len(spectrum) != count:
        raise n.api().Refusal("MISSING_NOISE_OBSERVATION", "noise sweep has an incomplete declared band/grid")
    for i, (frequency, _) in enumerate(spectrum):
        expected = spec["frequency_start_hz"] * 10 ** (i / spec["points_per_decade"])
        if not math.isclose(frequency, expected, rel_tol=1e-8):
            raise n.api().Refusal("FAILED_MEASUREMENT", "native noise frequency grid differs from declaration")
    integrated = samples(work / "integrated.txt", ["onoise_total", "onoise_total"])
    if len(integrated) != 1 or integrated[0][0] != integrated[0][1]:
        raise n.api().Refusal("MISSING_NOISE_OBSERVATION", "native integrated noise scalar missing")
    value = integrated[0][1]
    printed = re.findall(r"(?m)^onoise_total\s*=\s*(\S+)\s*$", log)
    if len(printed) != 1 or not math.isclose(float(printed[0]), value, rel_tol=1e-12):
        raise n.api().Refusal("CONTRADICTS_NATIVE_OUTPUT", "native noise scalar/log disagree")
    # Cross-check integration of the independently captured voltage-density
    # spectrum. ngspice uses logarithmic integration; a fine-grid trapezoid
    # bounds this cross-check (not the grading quantity) within 3 percent.
    area = sum((b[0] - a[0]) * (a[1]**2 + b[1]**2) / 2 for a, b in zip(spectrum, spectrum[1:]))
    if not math.isclose(math.sqrt(area), value, rel_tol=0.03, abs_tol=1e-18):
        raise n.api().Refusal("CONTRADICTS_NATIVE_OUTPUT", "integrated scalar disagrees with native noise spectrum")
    criteria = [{**c, "measured": value,
                 "verdict": "PASS" if c.get("min", 0) <= value <= c["max"] else "FAIL"}
                for c in spec["criteria"]]
    return {"id": spec["id"], "top": spec["top"], "scope": spec["scope"], "analysis": spec["analysis"],
            "model": spec["model"], "model_sha256": spec["model_sha256"], "subckt": spec["subckt"],
            "temperature_c": spec["temperature_c"], "dc_drive_v": spec["dc_drive_v"],
            "frequency_band_hz": [spec["frequency_start_hz"], spec["frequency_stop_hz"]],
            "sample_count": len(spectrum), "metrics": {METRIC: {"measured": value, "units": UNITS}},
            "criteria": criteria, "verdict": "PASS" if all(c["verdict"] == "PASS" for c in criteria) else "FAIL"}


def run(project, spec, root, token, engine):
    n = native()
    work = root / "receiver_noise"
    work.mkdir(parents=True)
    write_text(work / "noise.sp", deck(project, spec, token))
    try:
        engine.run(command(work), work / "noise.log", "measurement", cwd=work)
    finally:
        if (work / "noise.rss").is_file() and engine.execution and engine.execution[-1]["command"] == command(work):
            peak = int((work / "noise.rss").read_text().strip())
            engine.execution[-1]["peak_rss_kib"] = peak
            if peak * 1024 > n.LIMIT:
                raise n.api().Refusal("MEMORY_BUDGET_EXCEEDED", "native noise exceeds 8 GiB; stop expansion")
    return derive(project, spec, work, token)


def verify(project, data, root, record):
    n = native()
    spec = declaration(project, data)
    if spec is None:
        return None
    work = root / "si/receiver_noise"
    execution = [e for e in record["execution"] if e["command"] == command(work) and
                 e["stage"] == "measurement" and e["cwd"] == str(work) and
                 e["log"] == str((work / "noise.log").relative_to(project))]
    if len(execution) != 1:
        raise n.api().Refusal("MISSING_NOISE_OBSERVATION", "one exact native receiver/noise execution required")
    e = execution[0]
    if (work / "noise.sp").read_text() != deck(project, spec, record["run_id"]):
        raise n.api().Refusal("CONTRADICTS_NATIVE_OUTPUT", "noise instrument differs from current receiver/scenario")
    for name in ("spectrum.txt", "integrated.txt", "noise.rss"):
        path = work / name
        if not path.is_file() or not e["started_ns"] <= path.stat().st_mtime_ns <= e["finished_ns"]:
            raise n.api().Refusal("STALE_NATIVE_OUTPUT", "noise observations predate/differ from this invocation")
    peak = int((work / "noise.rss").read_text().strip())
    if peak <= 0 or peak * 1024 > n.LIMIT or e.get("peak_rss_kib") != peak:
        raise n.api().Refusal("MEMORY_BUDGET_EXCEEDED", "missing/invalid native noise RSS evidence")
    return derive(project, spec, work, record["run_id"])
