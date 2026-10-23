#!/usr/bin/env python3
"""Native held-input incremental conversions and coherent SNDR/ENOB.

Each point runs the delivered DUT, observes its reset waveform, samples the
registered output once per clock and uses the existing matched decimator.
Complete independent reset conversions can form a coherent held-sine series.
No waveform-presence or arithmetic-loop result is an ENOB measurement.

Holding an input for the conversion interval follows the incremental ADC
measurement model in https://doi.org/10.1049/el.2013.1096 . The stimulus,
capture length and threading are explicit engineering settings, not specs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_json
import analog_bound_measurements as bound
import analog_incremental_decimator as decimator
import analog_resolution_stimulus as stimulus
import analog_adc_enob_corner_check as enob_check
import analog_real_corner_sweep as sweep

DECODER_REVISION = "observed_reset_release_clock_samples_v2"
DECODER_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def capture_sha(path: Path, *, decompressed=False) -> str:
    digest = hashlib.sha256()
    opener = gzip.open if decompressed else open
    with opener(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compress_capture(path: Path) -> dict:
    """Replace only a completed owned raw capture after a lossless-copy check."""
    if path.is_symlink():
        raise ValueError("refusing to compress a capture symlink")
    target = path.with_name(path.name + ".gz")
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    if target.exists() or temporary.exists():
        raise ValueError("compressed capture destination already exists")
    original = capture_sha(path)
    try:
        with temporary.open("xb") as output, path.open("rb") as source:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=6) as compressed:
                shutil.copyfileobj(source, compressed, 1024 * 1024)
        if capture_sha(temporary, decompressed=True) != original or capture_sha(path) != original:
            raise ValueError("lossless capture compression verification failed")
        os.link(temporary, target)  # Publish atomically without replacing another receipt's output.
        temporary.unlink()
        path.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"path": str(target), "sha256": capture_sha(target), "encoding": "gzip", "raw_sha256": original}


def declared_dut_consumed(views: dict) -> bool:
    """An adjacent netlist hash is not evidence that native actually used it."""
    declared = views.get("netlist") or {}
    return bool(declared.get("sha256") and any(view.get("sha256") == declared["sha256"]
        for role, view in views.items() if role.startswith("include:") and isinstance(view, dict)))


def sampled_capture(path: Path, first_clock_s: float, period_s: float,
                    high_v: float, sample_fraction: float = 0.9) -> dict:
    """Stream time/output/reset/input columns; retain only clock samples."""
    if period_s <= 0 or high_v <= 0 or not 0 < sample_fraction < 1:
        raise ValueError("invalid capture clock or sampling phase")
    samples, releases, assertions = [], [], []
    previous = None
    next_sample = first_clock_s + sample_fraction * period_s
    rows = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as stream:
        for line in stream:
            try:
                row = tuple(float(value) for value in line.split()[:4])
            except ValueError:
                continue
            if len(row) != 4:
                continue
            if not all(math.isfinite(value) for value in row):
                raise ValueError("non-finite native capture value")
            rows += 1
            if previous is None and row[0] > next_sample:
                raise ValueError("native capture begins after its first sampling instant")
            if previous is not None:
                if row[0] <= previous[0]:
                    raise ValueError("native capture times are not strictly increasing")
                if previous[2] <= high_v / 2 < row[2]:
                    fraction = (high_v / 2 - previous[2]) / (row[2] - previous[2])
                    releases.append(previous[0] + fraction * (row[0] - previous[0]))
                if previous[2] > high_v / 2 >= row[2]:
                    fraction = (high_v / 2 - previous[2]) / (row[2] - previous[2])
                    assertions.append(previous[0] + fraction * (row[0] - previous[0]))
                while next_sample <= row[0]:
                    value = row if next_sample == row[0] else previous
                    samples.append({"time_s": next_sample,
                                    "decision": 1.0 if value[1] > high_v / 2 else -1.0,
                                    "output_v": value[1], "reset_v": value[2], "input_v": value[3]})
                    next_sample += period_s
            previous = row
    return {"samples": samples, "reset_releases_s": releases, "reset_assertions_s": assertions, "rows_read": rows,
            "end_s": previous[0] if previous else None, "sample_fraction": sample_fraction}


def decode_capture(path: Path, clock: tuple, declaration: dict,
                   settings: dict) -> dict:
    """Decode only complete conversions bounded by observed reset releases."""
    first, period, high = clock
    capture = sampled_capture(path, first, period, high, settings.get("sample_fraction", 0.9))
    window = int(declaration["window_clocks"])
    samples = capture.pop("samples")
    releases = capture["reset_releases_s"]
    decoded, discarded = [], []
    for left, right in zip(releases, releases[1:]):
        # Registered decisions are owned by their observation instant, not by
        # a guessed rising-edge integration phase. A switched-capacitor stage
        # may transfer on clock LOW immediately after reset release.
        sample_origin = first + capture["sample_fraction"] * period
        start = max(0, math.ceil((left - sample_origin) / period - 1e-9))
        period_stop = max(0, math.ceil((right - sample_origin) / period - 1e-9))
        assertions = [value for value in capture["reset_assertions_s"] if left < value < right]
        if start < 0 or period_stop - start != window or period_stop > len(samples) or len(assertions) != 1:
            discarded.append({"release_s": left, "next_release_s": right,
                              "clock_slots": period_stop - start, "assertions": len(assertions)})
            continue
        # A delayed DAC can give the final decision zero weight. Only that
        # mathematically unused decision may be masked by the next reset.
        # A reset-corrupted nonzero-weight decision is never credited.
        stop = period_stop
        sample_count = stop - start
        if sample_count < 1:
            discarded.append({"release_s": left, "reason": "no_complete_conversion_clock"})
            continue
        chosen = samples[start:stop]
        weights = decimator.matched_weights(sample_count, int(declaration["order"]),
            float(declaration["coeff"]), int(declaration["feedback_delay_clocks"]))
        masked = [index for index, sample in enumerate(chosen) if sample["reset_v"] <= high / 2]
        if any(weights[index] != 0.0 for index in masked):
            discarded.append({"release_s": left, "reason": "reset_masks_nonzero_weight_decision"})
            continue
        held = [sample["input_v"] for sample in chosen]
        if max(held) - min(held) > max(1.0, max(abs(value) for value in held)) * 1e-12:
            discarded.append({"release_s": left, "reason": "input_not_held_during_conversion"})
            continue
        if "held_input_v" in settings and not math.isclose(sum(held) / sample_count,
                settings["held_input_v"], rel_tol=1e-12, abs_tol=1e-12):
            discarded.append({"release_s": left, "reason": "native_input_differs_from_executed_stimulus"})
            continue
        output, details = decimator.decimate([sample["decision"] for sample in chosen], sample_count,
            order=int(declaration["order"]), coeff=float(declaration["coeff"]),
            feedback_delay=int(declaration["feedback_delay_clocks"]))
        if not output:
            discarded.append({"release_s": left, "reason": details})
            continue
        decoded.append({"release_s": left, "next_release_s": right,
                        "clock_slots": sample_count, "reset_period_clocks": window,
                        "first_sample_s": chosen[0]["time_s"], "last_sample_s": chosen[-1]["time_s"],
                        "ignored_zero_weight_decisions": len(masked),
                        "decoded": output[0], "input_v": sum(held) / sample_count,
                        "minimum_decision_margin_v": min(abs(sample["output_v"] - high / 2) for sample in chosen),
                        "decimator": details})
    return {**capture, "conversions": decoded, "discarded_intervals": discarded,
            "alignment": DECODER_REVISION}


def fit_coherent_sndr(values: list[float], tone_bin: int, target_bits: float) -> dict:
    """Numerical instrument only; native provenance is checked by its caller."""
    length = len(values)
    if length < 2 or tone_bin < enob_check._MIN_SIGNAL_CYCLES or math.gcd(length, tone_bin) != 1 or 3 * tone_bin >= length / 2:
        raise ValueError("coherent record must resolve the tone and three harmonics")
    if not all(math.isfinite(value) for value in values):
        return {"status": "NOT_MEASURED", "detail": "non-finite conversion result"}
    mean = sum(values) / length
    angles = [2 * math.pi * tone_bin * index / length for index in range(length)]
    sine = 2 * sum((value - mean) * math.sin(angle) for value, angle in zip(values, angles)) / length
    cosine = 2 * sum((value - mean) * math.cos(angle) for value, angle in zip(values, angles)) / length
    signal = (sine * sine + cosine * cosine) / 2
    residual = sum((value - mean - sine * math.sin(angle) - cosine * math.cos(angle)) ** 2
                   for value, angle in zip(values, angles)) / length
    if max(values) == min(values) or signal <= 0:
        return {"status": "FAIL", "detail": "native decoded output carries no input-tone signal"}
    if residual <= signal * 1e-30:
        return {"status": "NOT_MEASURED", "detail": "no finite residual above stored numerical precision"}
    sndr = 10 * math.log10(signal / residual)
    bits = (sndr - 1.76) / 6.02
    return {"status": "PASS" if bits >= target_bits else "FAIL", "measurements": {"sndr_db": sndr, "enob": bits},
            "target_bits": target_bits, "samples": length, "tone_bin": tone_bin,
            "method": "matched_incremental_decimation_coherent_fundamental_fit_all_residual",
            "scope": "deterministic native transient SNDR at the recorded input amplitude; transient device noise not added"}


def validate_point(record: dict) -> tuple:
    """Require current native source/capture/log bytes, then redo the decode."""
    views = record.get("native_inputs") or {}
    current, why = bound.validate_consumed_inputs(Path(record.get("project") or "."), views)
    if not current:
        return False, why
    for view in views.values():
        if not Path(view["path"]).is_file() or bound.sha(view["path"]) != view["sha256"]:
            return False, "native conversion input is stale"
    if not declared_dut_consumed(views):
        return False, "declared native DUT is absent from the executed include closure"
    try:
        settings = record["settings"]
        if "settings" in views and json.loads(Path(views["settings"]["path"]).read_text()) != settings:
            return False, "native settings differ from the executed settings file"
        deck = Path(views["deck"]["path"])
        expected, clock, declaration = prepare_deck(Path(views["testbench"]["path"]),
            json.loads(Path(views["spec"]["path"]).read_text()),
            json.loads(Path(views["topology"]["path"]).read_text()), settings, deck.parent)
        if deck.read_text() != expected or list(clock) != record["clock"] or declaration != record["incremental_decode"]:
            return False, "native conversion metadata differs from its executed deck"
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return False, "native conversion inputs cannot be reconstructed: " + str(exc)
    capture = record.get("capture") or {}
    path = Path(capture.get("path") or "__missing_conversion_capture__")
    if not path.is_file() or capture.get("sha256") != capture_sha(path):
        return False, "native conversion capture is absent or stale"
    try:
        if path.suffix == ".gz" and capture.get("encoding") != "gzip":
            return False, "compressed native capture lacks its lossless encoding receipt"
        if capture.get("encoding") == "gzip" and capture.get("raw_sha256") != capture_sha(path, decompressed=True):
            return False, "compressed native capture differs from its original raw bytes"
        if capture.get("encoding", "raw") not in ("raw", "gzip"):
            return False, "unknown native capture encoding"
    except (OSError, EOFError, ValueError):
        return False, "compressed native capture cannot be read losslessly"
    executions = record.get("executions") or []
    if not executions:
        return False, "native execution is absent"
    for execution in executions:
        log = Path(execution.get("log") or "__missing_conversion_log__")
        if execution.get("returncode") != 0 or not log.is_file() or execution.get("log_sha256") != bound.sha(log):
            return False, "native conversion did not complete with its recorded log"
        if native_failed(log.read_text(errors="replace")):
            return False, "native conversion log reports a numerical/analysis failure"
    try:
        decoded = decode_capture(path, tuple(record["clock"]), record["incremental_decode"], record["settings"])
    except (OSError, EOFError, ValueError) as exc:
        return False, "native capture cannot be decoded: " + str(exc)
    if not decoded.get("conversions"):
        return False, "no complete observed native reset conversion"
    return True, "current native reset-aligned conversion"


def decoded_point(record: dict) -> dict:
    return decode_capture(Path(record["capture"]["path"]), tuple(record["clock"]),
                          record["incremental_decode"], record["settings"])


def write_decoder_replay(record: dict, point_path: Path) -> dict:
    """Derive a new immutable analysis receipt; never rewrite native history."""
    point_path = Path(point_path).resolve()
    original_sha = bound.sha(point_path)
    original = json.loads(point_path.read_text())
    supplied = {key: value for key, value in record.items() if key != "_receipt_path"}
    if original != supplied:
        raise ValueError("point dictionary differs from its original native receipt")
    valid, why = validate_point(original)
    if not valid:
        raise ValueError(why)
    decoded = decoded_point(original)
    report = {"status": "PASS", "original_point": {"path": str(point_path), "sha256": original_sha},
              "decoder": {"program": "analog_incremental_capture.py", "revision": DECODER_REVISION,
                          "sha256": DECODER_SOURCE_SHA256},
              "capture": original["capture"], "native_inputs": original["native_inputs"],
              "executions": original["executions"], "decoded": decoded}
    if bound.sha(point_path) != original_sha:
        raise ValueError("original native receipt changed during decoder replay")
    destination = point_path.parent / "decoder-replays" / (original_sha[:16] + "-" + DECODER_SOURCE_SHA256[:16] + ".json")
    if destination.exists():
        if json.loads(destination.read_text()) != report:
            raise ValueError("immutable decoder replay receipt differs")
    else:
        write_json(destination, report)
    return {"decoded": decoded, "receipt": {"path": str(destination), "sha256": bound.sha(destination)}}


def source_enob_min(spec: dict) -> float:
    rows = [row for row in spec.get("specs", [])
            if sweep.normalize_spec_label(str(row.get("name", ""))) == "enob" and "min" in row]
    if len(rows) != 1 or isinstance(rows[0]["min"], bool) or not isinstance(rows[0]["min"], (int, float)) or not math.isfinite(rows[0]["min"]):
        raise ValueError("one explicit source ENOB minimum is required")
    return float(rows[0]["min"])


def native_failed(log: str) -> bool:
    return any(sweep._scan_analysis_failures(log)) or bool(re.search(
        r"(?im)\bfatal(?: error)?\b|\bsimulation(?:\(s\)|s)?\s+aborted\b|\btimestep too small\b", log))


def native_execution_failure(record: dict) -> bool:
    for execution in record.get("executions") or []:
        code = execution.get("returncode")
        log = Path(execution.get("log") or "__missing_native_log__")
        if log.is_file() and execution.get("log_sha256") == bound.sha(log) and native_failed(log.read_text(errors="replace")):
            return True
        if isinstance(code, int) and code > 0 and code not in (130, 137, 143):
            return True
    return False


def coherent_sndr(points: list[dict], length: int, tone_bin: int, target_bits: float) -> dict:
    """Fit only a complete set of independently validated native conversions."""
    indexed, replays = {}, []
    identities = set()
    for point in points:
        index = point.get("settings", {}).get("phase_index")
        if not isinstance(index, int) or index in indexed:
            return {"status": "NOT_MEASURED", "detail": "missing or duplicate native phase index"}
        if native_execution_failure(point):
            return {"status": "FAIL", "detail": "native conversion execution failed", "phase_index": index}
        for execution in point.get("executions") or []:
            code = execution.get("returncode")
            interrupted = isinstance(code, int) and (code < 0 or code in (130, 137, 143))
            log = Path(execution.get("log") or "__missing_native_log__")
            if interrupted:
                return {"status": "NOT_MEASURED", "detail": "native conversion interrupted", "phase_index": index}
            if (isinstance(code, int) and code != 0) or (log.is_file() and native_failed(log.read_text(errors="replace"))):
                return {"status": "FAIL", "detail": "native conversion execution failed", "phase_index": index}
        current, why = validate_point(point)
        if not current:
            return {"status": "NOT_MEASURED", "detail": why, "phase_index": index}
        replay = (write_decoder_replay(point, Path(point["_receipt_path"])) if point.get("_receipt_path")
                  else {"decoded": decoded_point(point)})
        if replay.get("receipt"):
            replays.append(replay["receipt"])
        conversions = replay["decoded"].get("conversions") or []
        if not conversions:
            return {"status": "NOT_MEASURED", "detail": "native conversion incomplete", "phase_index": index}
        settings = point["settings"]
        try:
            offset, amplitude = settings["dc_offset_v"], settings["amplitude_v"]
            if settings["series_length"] != length or settings["tone_bin"] != tone_bin or not amplitude > 0:
                raise ValueError("coherent input settings disagree")
            expected_input = offset + amplitude * math.sin(2 * math.pi * tone_bin * index / length)
            if not math.isclose(conversions[0]["input_v"], expected_input, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("native input does not match its coherent phase")
            spec = json.loads(Path(point["native_inputs"]["spec"]["path"]).read_text())
            if source_enob_min(spec) != target_bits:
                raise ValueError("target differs from the source ENOB minimum")
        except (KeyError, TypeError, ValueError, OSError) as exc:
            return {"status": "NOT_MEASURED", "detail": str(exc), "phase_index": index}
        signature = tuple(sorted((role, view["sha256"]) for role, view in point["native_inputs"].items()
            if role.startswith("include:") or role in ("netlist", "spec", "topology", "testbench")))
        common_settings = json.dumps({key: value for key, value in settings.items()
            if key not in ("phase_index", "held_input_v")}, sort_keys=True, separators=(",", ":"))
        identities.add((signature, point.get("image"), offset, amplitude, common_settings))
        indexed[index] = conversions[0]["decoded"]
    if len(identities) > 1:
        return {"status": "NOT_MEASURED", "detail": "coherent points do not share one DUT/model/stimulus and common measurement settings context"}
    if set(indexed) != set(range(length)):
        return {"status": "NOT_MEASURED", "detail": "coherent series lacks native conversions",
                "present": len(indexed), "required": length}
    values = [indexed[index] for index in range(length)]
    result = fit_coherent_sndr(values, tone_bin, target_bits)
    result["decoder"] = {"revision": DECODER_REVISION, "sha256": DECODER_SOURCE_SHA256}
    result["decoder_replays"] = replays
    return result


def replay_score(path: Path) -> dict:
    """Consumer API: reconstruct a score from current native point evidence.

    Cached status/measurements are deliberately not authority. The point
    files, captures, logs and consumed inputs own the recomputed result.
    """
    try:
        cached = json.loads(Path(path).read_text())
        entries = cached.get("points")
        if not isinstance(entries, list) or not entries:
            raise ValueError("score lacks its native point files")
        points, seen = [], set()
        for entry in entries:
            point_path = Path(entry["path"]).resolve()
            if point_path in seen or not point_path.is_file() or bound.sha(point_path) != entry["sha256"]:
                raise ValueError("native point file is missing, duplicated or changed")
            seen.add(point_path)
            point = json.loads(point_path.read_text())
            point["_receipt_path"] = str(point_path)
            points.append(point)
        settings = points[0]["settings"]
        spec = json.loads(Path(points[0]["native_inputs"]["spec"]["path"]).read_text())
        result = coherent_sndr(points, settings["series_length"], settings["tone_bin"], source_enob_min(spec))
        result["points"] = entries
        result["outputs"] = [str(Path(path).resolve())] + [str(item) for item in sorted(seen)]
        result["outputs"] += [item["path"] for item in result.get("decoder_replays") or []]
        return result
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return {"status": "NOT_MEASURED", "detail": "native incremental score unavailable: " + str(exc)}


def prepare_deck(template: Path, spec: dict, topology: dict, settings: dict, destination: Path) -> tuple:
    source = bound.contextual_template(template.read_text(), template.parent)
    plan = stimulus.plan(source, spec, topology)
    declaration = stimulus.incremental_decode(spec, topology)
    if not plan.get("applied") or not declaration.get("declared"):
        raise ValueError("incremental stimulus/decode inputs unavailable: " + str(plan.get("reason")))
    clock = enob_check.sample_clock_card(source)
    if clock is None:
        raise ValueError("one delivered native clock is required")
    reset = settings.get("reset_node")
    if not isinstance(reset, str) or not re.fullmatch(r"[A-Za-z_][\w.]*", reset):
        raise ValueError("actual active-low reset node must be specified")
    value = settings.get("held_input_v")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("explicit finite held input required")
    lines = source.splitlines()
    driver = lines[plan["source_line"]].split()
    lines[plan["source_line"]] = " ".join(driver[:3]) + f" {value:.17g}"
    body = "\n".join(lines)
    body = re.sub(r"(?ims)^\s*\.control\b.*?^\s*\.endc\b[^\n]*", "", body)
    body = re.sub(r"(?im)^\s*\.(?:save|tran|meas|measure)\b[^\n]*", "", body)
    body = re.sub(r"(?im)^\s*\.end\s*$", "", body)
    numerical = settings.get("numerical_options", {})
    if not isinstance(numerical, dict) or set(numerical) - {"reltol", "vntol", "abstol", "method"}:
        raise ValueError("numerical_options accepts reltol, vntol, abstol and method only")
    options = []
    for key, value in numerical.items():
        if key == "method":
            if value not in ("trap", "gear"):
                raise ValueError("integration method must be trap or gear")
            options.append("method=" + value)
            if value == "gear":
                options.append("maxord=2")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("numerical tolerances must be finite positive numbers")
        else:
            options.append(f"{key}={value:.17g}")
    if options:
        body += "\n.options " + " ".join(options) + "\n"
    first, period, _high = clock
    clocks = int(settings.get("capture_clocks", declaration["window_clocks"] + 6))
    step = settings.get("timestep_s", period / 200)
    threads = settings.get("threads", 4)
    if (clocks < 1 or isinstance(step, bool) or not isinstance(step, (int, float)) or step <= 0
            or isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 32):
        raise ValueError("invalid native capture settings")
    dump = destination / "conversion.dat"
    probes = f"v({plan['output_node']}) v({reset}) v({plan['signal_input_port']})"
    text = body.rstrip() + "\n" + declaration["stamp"] + f"\n.save {probes}\n.control\nset num_threads={threads}\nset numdgt=15\n"
    text += f"tran {step:.17g} {first + clocks * period:.17g}\nset wr_singlescale\nset wr_vecnames\nwrdata {dump} {probes}\nrusage\n.endc\n.end\n"
    return text, clock, declaration


def run_point(project: Path, netlist: Path, template: Path, spec_path: Path,
              topology_path: Path, settings: dict, destination: Path, run) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    spec, topology = json.loads(spec_path.read_text()), json.loads(topology_path.read_text())
    text, clock, declaration = prepare_deck(template, spec, topology, settings, destination)
    deck = destination / "conversion.sp"
    deck.write_text(text)
    views = {role: {"path": str(path.resolve()), "sha256": bound.sha(path)} for role, path in
             (("deck", deck), ("netlist", netlist), ("testbench", template), ("spec", spec_path), ("topology", topology_path))}
    views.update(bound.consumed_input_views(project, deck))
    if not declared_dut_consumed(views):
        return {"status": "NOT_MEASURED", "detail": "declared native DUT is absent from the executed include closure",
                "project": str(project.resolve()), "settings": settings, "native_inputs": views,
                "executions": [], "clock": list(clock), "incremental_decode": declaration, "decoded": {}}
    execution = run(deck, destination)
    native_log = Path(execution["log"]).read_text(errors="replace")
    interrupted = execution.get("returncode") in (130, 137, 143) or execution.get("returncode", 0) < 0
    failed = execution.get("returncode") != 0 or native_failed(native_log)
    record = {"status": "FAIL" if native_failed(native_log) else "NOT_MEASURED" if interrupted else "FAIL" if failed else "NOT_MEASURED", "project": str(project.resolve()),
              "settings": settings, "native_inputs": views, "executions": [execution],
              "clock": list(clock), "incremental_decode": declaration, "decoded": {}}
    dump = destination / "conversion.dat"
    if not failed and dump.is_file():
        try:
            record["decoded"] = decode_capture(dump, clock, declaration, settings)
            record["status"] = "PASS" if record["decoded"]["conversions"] else "NOT_MEASURED"
        except ValueError as exc:
            record["detail"] = "native capture cannot be decoded: " + str(exc)
        record["capture"] = {"path": str(dump), "sha256": capture_sha(dump)}
    changed = [role for role, view in views.items() if not Path(view["path"]).is_file() or bound.sha(view["path"]) != view["sha256"]]
    current, why = bound.validate_consumed_inputs(project, views)
    if changed or not current:
        record.update(status="FAIL" if record["status"] == "FAIL" else "NOT_MEASURED",
                      changed_inputs=changed, detail=why, decoded={})
    if "capture" in record and settings.get("compress_capture", True):
        try:
            record["capture"] = compress_capture(dump)
        except (OSError, ValueError) as exc:
            # The completed original remains valid evidence if compression
            # fails; never delete it or invent a native circuit failure.
            record["compression_error"] = str(exc)
    return record


def phase_settings(common: dict, index: int) -> dict:
    """The explicit coherent held-sine stimulus, without simulator outputs."""
    length, tone = common.get("series_length"), common.get("tone_bin")
    offset, amplitude = common.get("dc_offset_v"), common.get("amplitude_v")
    if (isinstance(length, bool) or not isinstance(length, int) or length < 2
            or isinstance(tone, bool) or not isinstance(tone, int)
            or tone < enob_check._MIN_SIGNAL_CYCLES or math.gcd(length, tone) != 1 or 3 * tone >= length / 2):
        raise ValueError("explicit coherent series length/tone must resolve three harmonics")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in (offset, amplitude)) or amplitude <= 0 or not 0 <= index < length:
        raise ValueError("finite offset, positive amplitude and valid phase index required")
    return {**common, "phase_index": index,
            "held_input_v": offset + amplitude * math.sin(2 * math.pi * tone * index / length)}


def _process_matches(pid, argv, start_ticks=None):
    try:
        path = Path("/proc") / str(int(pid))
        actual = [os.fsdecode(item) for item in (path / "cmdline").read_bytes().split(b"\0") if item]
        text = (path / "stat").read_text()
        start = text[text.rfind(")") + 2:].split()[19]
        return actual == argv and (start_ticks is None or str(start_ticks) == start)
    except (OSError, ValueError, TypeError, IndexError):
        return False


def active_point(directory: Path) -> bool:
    """Only this exact producer case; unrelated/native density jobs do not block."""
    try:
        receipt = json.loads((directory / "running.json").read_text())
        return (_process_matches(receipt["pid"], receipt["argv"], receipt.get("start_ticks"))
                or ("producer_pid" in receipt and _process_matches(receipt["producer_pid"],
                    receipt["producer_argv"], receipt.get("producer_start_ticks"))))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def series_main(argv, launch=None):
    parser = argparse.ArgumentParser(description="Run reset-validated held-input native conversions with a bounded CPU budget")
    parser.add_argument("project", type=Path)
    parser.add_argument("--block", required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--score", type=Path)
    parser.add_argument("--container", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cpus", type=int, default=1)
    parser.add_argument("--limit-points", type=int)
    args = parser.parse_args(argv)
    project, output = args.project.resolve(), args.out.resolve()
    common = json.loads(args.settings.read_text())
    phase_settings(common, 0)  # Validate the method before creating any jobs.
    threads = common.get("threads", 1)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1 or args.workers < 1 or args.cpus < threads:
        raise ValueError("native threads/workers must fit the explicit CPU budget")
    common.setdefault("threads", threads)
    common.setdefault("openmp_wait_policy", "PASSIVE")
    workers = min(args.workers, args.cpus // threads)
    length = common["series_length"]
    limit = args.limit_points if args.limit_points is not None else length
    if not 1 <= limit <= length:
        raise ValueError("limit-points must be within the declared series")
    bdir = project / "phase3/analog" / args.block
    template = Path(common.get("testbench", bdir / ("tb_" + args.block + ".sp")))
    if not template.is_absolute():
        template = project / template
    expected = {role: bound.sha(path) for role, path in (("netlist", bdir / (args.block + ".sp")),
        ("spec", bdir / "spec.json"), ("topology", bdir / "topology.json"), ("testbench", template))}
    output.mkdir(parents=True, exist_ok=True)
    def one(index):
        directory = output / f"point-{index:03d}"
        point_path = directory / "result.json"
        settings = phase_settings(common, index)
        if point_path.is_file():
            record = json.loads(point_path.read_text())
            matched = (record.get("settings") == settings and record.get("image") == args.image and all(
                record.get("native_inputs", {}).get(role, {}).get("sha256") == digest for role, digest in expected.items()))
            inputs = record.get("native_inputs") or {}
            current_inputs, _ = bound.validate_consumed_inputs(project, inputs)
            current_inputs = current_inputs and all(Path(view["path"]).is_file() and
                bound.sha(view["path"]) == view["sha256"] for view in inputs.values())
            if matched and current_inputs and native_execution_failure(record):
                return {"status": "FAIL", "detail": "current retained native conversion failed", "result": str(point_path)}
            current, why = validate_point(record)
            if not current or not matched:
                if not matched:
                    why = "requested DUT/spec/topology/testbench/settings/image differs"
                return {"status": "NOT_MEASURED", "detail": "existing native point cannot be reused: " + why,
                        "phase_index": index, "result": str(point_path)}
            return {"status": "PASS", "result": str(point_path), "reused": True}
        if active_point(directory):
            return {"status": "NOT_MEASURED", "detail": "exact native conversion already running", "phase_index": index}
        if directory.exists() and any(directory.iterdir()):
            return {"status": "NOT_MEASURED", "detail": "unfinished prior point retained; use a fresh output directory",
                    "phase_index": index}
        directory.mkdir(parents=True, exist_ok=True)
        setting_path = directory / "settings.json"
        write_json(setting_path, settings)
        (launch or main)([str(project), "--block", args.block, "--settings", str(setting_path),
            "--out", str(directory), "--container", args.container, "--image", args.image])
        if not point_path.is_file():
            return {"status": "NOT_MEASURED", "detail": "native producer did not write its terminal point", "phase_index": index}
        record = json.loads(point_path.read_text())
        current, why = validate_point(record)
        if native_execution_failure(record):
            return {"status": "FAIL", "detail": "native control/conversion failed", "result": str(point_path)}
        if not current:
            return {"status": "NOT_MEASURED", "detail": why, "result": str(point_path)}
        return {"status": "PASS", "result": str(point_path)}
    # The actual first complete reset conversion establishes that the method
    # can decode this delivered DUT. No later phase launches before it passes.
    control = one(0)
    if control["status"] != "PASS":
        print(json.dumps(control))
        return 1 if control["status"] == "FAIL" else 2
    results = [control]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for start in range(1, limit, workers):
            batch = list(executor.map(one, range(start, min(start + workers, limit))))
            results += batch
            if any(result["status"] != "PASS" for result in batch):
                outcome = {"status": "FAIL" if any(result["status"] == "FAIL" for result in batch) else "NOT_MEASURED",
                           "detail": "native series stopped on an incomplete/failed conversion", "points": results}
                print(json.dumps(outcome))
                return 1 if outcome["status"] == "FAIL" else 2
    paths = [result["result"] for result in results]
    return score_main([item for path in paths for item in ("--point", path)] +
        ["--length", str(length), "--tone-bin", str(common["tone_bin"]), "--out",
         str(args.score.resolve() if args.score else output / "score.json")])


def consume_study(project: Path, name: str, entry: dict, options: dict, run, step: str) -> dict:
    """A06/A07 adapter for real native incremental measurements.

    Method readiness requires an observed complete control conversion. ENOB
    requires replay of every native point; cached score metrics are not read.
    """
    project = Path(project).resolve()
    row = {"status": "NOT_MEASURED", "detail": "native incremental study is incomplete", "measurements": {},
           "definitions": [], "analyses": [], "outputs": [], "executions": [], "native_inputs": {}}
    def path(value):
        result = Path(value)
        return result if result.is_absolute() else project / result
    try:
        if entry.get("kind") != "incremental_capture":
            raise ValueError("this consumer requires kind incremental_capture")
        settings_path, score_path = path(entry["settings"]), path(entry["result"])
        original = json.loads(settings_path.read_text())
        common = dict(original)
        common.setdefault("threads", 1)
        common.setdefault("openmp_wait_policy", "PASSIVE")
        bdir = project / "phase3/analog" / name
        template = path(entry.get("testbench") or entry.get("template") or
                        common.get("testbench") or bdir / ("tb_" + name + ".sp"))
        default_template = bdir / ("tb_" + name + ".sp")
        if template.resolve() != default_template.resolve() or "testbench" in common:
            common["testbench"] = str(template.resolve())
        expected = {role: {"path": str(source.resolve()), "sha256": bound.sha(source)} for role, source in
            (("netlist", bdir / (name + ".sp")), ("spec", bdir / "spec.json"),
             ("topology", bdir / "topology.json"), ("testbench", template))}
        spec = json.loads((bdir / "spec.json").read_text())
        topology = json.loads((bdir / "topology.json").read_text())
        phase = phase_settings(common, 0)
        prepare_deck(template, spec, topology, phase, score_path.parent / "point-000")
        closure = bound.consumed_input_views(project, template)
        if not declared_dut_consumed({"netlist": expected["netlist"], **closure}):
            raise ValueError("configured method template does not consume the current declared DUT")
        source_enob_min(spec)
        row.update(definitions=["enob"], analyses=[".tran"])
        container, image = options.get("container"), options.get("image")
        cpus = min(int(options.get("cpus", 1)), int(entry.get("cpus", options.get("cpus", 1))))
        workers = min(int(options.get("workers", 1)), int(entry.get("workers", options.get("workers", 1))))
        if not container or not image or cpus < common["threads"] or workers < 1:
            raise ValueError("actual container/image and a sufficient bounded CPU budget are required")
        if common != original:
            digest = hashlib.sha256(json.dumps(common, sort_keys=True).encode()).hexdigest()[:16]
            effective = score_path.parent / ("method-settings-" + digest + ".json")
            if effective.exists() and json.loads(effective.read_text()) != common:
                raise ValueError("immutable effective method settings changed")
            if not effective.exists():
                write_json(effective, common)
            settings_path = effective
        control_path = score_path.parent / "point-000/result.json"
        def bindings_current(record, index):
            matched = (record.get("settings") == phase_settings(common, index)
                and record.get("image") == image and all(record.get("native_inputs", {}).get(role, {}).get("sha256")
                    == view["sha256"] for role, view in expected.items()))
            if not matched:
                return False, "native point inputs/settings/image differ from the current method"
            views = record.get("native_inputs") or {}
            closure_current, reason = bound.validate_consumed_inputs(project, views)
            if not closure_current or not declared_dut_consumed(views):
                return False, reason
            if any(not Path(view["path"]).is_file() or bound.sha(view["path"]) != view["sha256"] for view in views.values()):
                return False, "native point consumed input bytes changed"
            return True, ""
        def current_point(record, index):
            matched, reason = bindings_current(record, index)
            if not matched:
                return False, reason
            return validate_point(record)
        def native_failure(record):
            return native_execution_failure(record)
        def read_control():
            if not control_path.is_file():
                return None, "first native reset conversion has not completed"
            record = json.loads(control_path.read_text())
            current, why = current_point(record, 0)
            if not current:
                return record, why
            return record, ""
        def invoke(limit):
            argv = ["series", str(project), "--block", name, "--settings", str(settings_path),
                    "--out", str(score_path.parent), "--score", str(score_path), "--container", str(container),
                    "--image", str(image), "--workers", str(workers), "--cpus", str(cpus)]
            if limit is not None:
                argv += ["--limit-points", str(limit)]
            receipt = run("analog_incremental_capture.py", argv)
            row["executions"].append(receipt)
            if receipt.get("log"):
                row["outputs"].append(str(receipt["log"]))
        control, why = read_control()
        if why:
            invoke(1)
            control, why = read_control()
        if control:
            row["native_inputs"] = control.get("native_inputs") or {}
            row["outputs"].append(str(control_path))
            if control.get("capture", {}).get("path"):
                row["outputs"].append(control["capture"]["path"])
            row["executions"] += control.get("executions") or []
        if why:
            matched = bindings_current(control, 0)[0] if control else False
            row["status"] = "FAIL" if matched and native_failure(control) else "NOT_MEASURED"
            row["detail"] = why
            return row
        if str(step).upper() == "A06":
            replay = write_decoder_replay(control, control_path)
            row["outputs"].append(replay["receipt"]["path"])
            row.update(status="PASS", detail="native TRAN method prepared and first full reset conversion validated; ENOB is not yet measured")
            return row
        def actual_score():
            if not score_path.is_file():
                return {"status": "NOT_MEASURED", "detail": "full native held-input series has not completed"}
            scored = replay_score(score_path)
            for item in scored.get("points") or []:
                record = json.loads(Path(item["path"]).read_text())
                current, reason = current_point(record, record.get("settings", {}).get("phase_index", -1))
                if not current:
                    if scored["status"] == "FAIL" and bindings_current(record, record["settings"]["phase_index"])[0] and native_failure(record):
                        continue
                    return {"status": "NOT_MEASURED", "detail": reason}
            return scored
        scored = actual_score()
        if scored["status"] == "NOT_MEASURED":
            invoke(None)
            scored = actual_score()
        row.update(status=scored["status"], detail=scored.get("detail") or scored.get("scope") or "native coherent SNDR/ENOB replayed",
                   measurements=scored.get("measurements") or {})
        row["outputs"] += scored.get("outputs") or []
        return row
    except (KeyError, OSError, ValueError, TypeError) as exc:
        row["detail"] = "native incremental method unavailable: " + str(exc)
        return row


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "score":
        return score_main(argv[1:])
    if argv and argv[0] == "series":
        return series_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--block", required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    project, destination = args.project.resolve(), args.out.resolve()
    bdir = project / "phase3/analog" / args.block
    settings_bytes = args.settings.read_bytes()
    settings = json.loads(settings_bytes)
    wait_policy = settings.get("openmp_wait_policy", "PASSIVE")
    if wait_policy not in ("PASSIVE", "ACTIVE"):
        parser.error("openmp_wait_policy must be PASSIVE or ACTIVE")
    os.environ["VIBEIC_EDA_IMAGE"] = args.image
    def native(deck, target):
        import _container_exec
        command = _container_exec.docker_exec_argv(args.container, "bash", "-lc", 'exec "$@"', "incremental-native",
            "env", "-u", "GOMP_SPINCOUNT", f"OMP_NUM_THREADS={int(settings.get('threads', 4))}", f"OMP_WAIT_POLICY={wait_policy}",
            *(["GOMP_SPINCOUNT=0"] if wait_policy == "PASSIVE" else []), "ngspice", "-b", str(deck),
            opts=("--user", f"{os.getuid()}:{os.getgid()}", "-w", str(template.parent)))
        path = target / "ngspice.log"
        start = time.monotonic()
        with path.open("w") as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
            stat_text = Path(f"/proc/{process.pid}/stat").read_text()
            producer_stat = Path(f"/proc/{os.getpid()}/stat").read_text()
            producer_argv = [os.fsdecode(item) for item in Path(f"/proc/{os.getpid()}/cmdline").read_bytes().split(b"\0") if item]
            write_json(target / "running.json", {"pid": process.pid, "argv": command,
                "start_ticks": stat_text[stat_text.rfind(")") + 2:].split()[19],
                "producer_pid": os.getpid(), "producer_argv": producer_argv,
                "producer_start_ticks": producer_stat[producer_stat.rfind(")") + 2:].split()[19],
                "started_at": datetime.now(timezone.utc).isoformat(), "log": str(path)})
            print(json.dumps({"status": "RUNNING", "pid": process.pid, "log": str(path)}), flush=True)
            code = process.wait()
        return {"returncode": code, "argv": command, "log": str(path), "log_sha256": bound.sha(path),
                "duration_s": time.monotonic() - start}
    template = Path(settings.get("testbench", bdir / ("tb_" + args.block + ".sp")))
    if not template.is_absolute():
        template = project / template
    record = run_point(project, bdir / (args.block + ".sp"), template, bdir / "spec.json", bdir / "topology.json",
                       settings, destination, native)
    record["native_inputs"]["settings"] = {"path": str(args.settings.resolve()), "sha256": __import__("hashlib").sha256(settings_bytes).hexdigest()}
    record.update(container=args.container, image=args.image)
    if args.settings.read_bytes() != settings_bytes:
        record.update(status="FAIL" if record["status"] == "FAIL" else "NOT_MEASURED", detail="settings changed during native execution", decoded={})
    write_json(destination / "result.json", record)
    print(json.dumps({"status": record["status"], "conversions": len(record.get("decoded", {}).get("conversions", [])),
                      "result": str(destination / "result.json")}))
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[record["status"]]


def score_main(argv):
    parser = argparse.ArgumentParser(description="Score complete source-bound native incremental conversions")
    parser.add_argument("--point", type=Path, action="append", required=True)
    parser.add_argument("--length", type=int, required=True)
    parser.add_argument("--tone-bin", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        points = [{**json.loads(path.read_text()), "_receipt_path": str(path.resolve())} for path in args.point]
        spec_path = Path(points[0]["native_inputs"]["spec"]["path"])
        target = source_enob_min(json.loads(spec_path.read_text()))
        result = coherent_sndr(points, args.length, args.tone_bin, target)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        result = {"status": "NOT_MEASURED", "detail": "native series unavailable: " + str(exc)}
    result["points"] = [{"path": str(path.resolve()), "sha256": bound.sha(path)} for path in args.point if path.is_file()]
    write_json(args.out, result)
    print(json.dumps(result))
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
