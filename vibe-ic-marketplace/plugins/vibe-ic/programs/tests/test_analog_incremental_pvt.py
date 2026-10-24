"""Incremental PVT software controls; fixture waveforms are not native evidence."""
import copy
import itertools
import json
import math
from pathlib import Path
import threading
import time

import pytest

import analog_incremental_capture as capture
import analog_incremental_pvt as pvt
from test_analog_incremental_capture import _method_record, _dump


@pytest.fixture
def method(tmp_path):
    project, common_path, _directory, _record = _method_record(tmp_path)
    bdir = project / "phase3/analog/converter"
    # The declared reference pair is an input; pin names are circuit-owned.
    for path in bdir.iterdir():
        if path.suffix in ('.sp', '.json'):
            path.write_text(path.read_text().replace('vrefp', 'ref_hi').replace('vrefn', 'ref_lo'))
    model = project / "model.lib"
    model.write_text("\n".join(f".lib device_{process}\n.param selected_corner=1\n.endl device_{process}"
                              for process in ("tt", "ss", "ff")))
    net = bdir / "converter.sp"
    net.write_text(f'.lib "{model}" device_tt\n' + net.read_text())
    source = json.loads((bdir / "spec.json").read_text())
    next(row for row in source["specs"] if row["name"] == "enob")["min"] = 1
    source["specs"].append({"name": "vref", "min": .8, "max": 1.2, "unit": "V"})
    (bdir / "spec.json").write_text(json.dumps(source))
    common = json.loads(common_path.read_text())
    common.update(series_length=64, tone_bin=9)
    common_path.write_text(json.dumps(common))
    return project, common_path, model


def prepared(method, root, **kwargs):
    project, settings, model = method
    return pvt.prepare(project, "converter", settings, root, model,
                       ["device_tt", "device_ss", "device_ff"], image="fixture-image",
                       reference_ports=kwargs.pop('reference_ports', ['ref_hi', 'ref_lo']), **kwargs)


def test_prepare_materializes_actual_corners_without_running_or_changing_source(method, tmp_path, monkeypatch):
    project, settings, _model = method
    before = {str(path): path.read_bytes() for path in (project / "phase3/analog/converter").iterdir() if path.is_file()}
    monkeypatch.setattr(capture, "series_main", lambda *a: pytest.fail("prepare cannot launch native series"))
    manifest = prepared(method, tmp_path / "pvt")
    assert manifest["status"] == "PASS" and len(manifest["contexts"]) == 9
    assert manifest['reference_ports'] == ['ref_hi', 'ref_lo']
    assert {(row["process"], row["temperature_c"]) for row in manifest["contexts"]} == set(itertools.product(
        ("device_tt", "device_ss", "device_ff"), (-40, 27, 125)))
    assert pvt._validate_manifest(manifest) == manifest["contexts"]
    common = json.loads(settings.read_text())
    for context in manifest["contexts"]:
        actual = json.loads(Path(context["settings"]["path"]).read_text())
        assert {key: value for key, value in actual.items() if key != "testbench"} == common
        assert f'.temp {context["temperature_c"]}' in Path(context["native_inputs"]["testbench"]["path"]).read_text()
    assert all(Path(path).read_bytes() == value for path, value in before.items())


def test_missing_section_or_foreign_library_refuses_preparation(method, tmp_path):
    project, settings, model = method
    with pytest.raises(ValueError, match="absent"):
        pvt.prepare(project, "converter", settings, tmp_path / "missing", model, ["device_tt", "device_ss", "absent_ff"],
            reference_ports=['ref_hi', 'ref_lo'])
    foreign = tmp_path / "foreign.lib"
    foreign.write_bytes(model.read_bytes())
    with pytest.raises(ValueError, match="actual single TT"):
        pvt.prepare(project, "converter", settings, tmp_path / "foreign", foreign, ["device_tt", "device_ss", "device_ff"],
                    reference_ports=['ref_hi', 'ref_lo'])


def test_collect_missing_scores_never_launches_or_credits_cached_words(method, tmp_path, monkeypatch):
    manifest = prepared(method, tmp_path / "pvt")
    monkeypatch.setattr(capture, "series_main", lambda *a: pytest.fail("collect cannot launch native series"))
    result = pvt.collect(manifest)
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["corners_executed"] == 0


@pytest.mark.parametrize('line,status', [('', 'NOT_MEASURED'),
    (';;RESIDUAL_FAIL native numerical error', 'FAIL'), ('fatal error: native analysis', 'FAIL')])
def test_timeout_only_native_corner_is_unmeasured_but_real_error_stays_fail(method, tmp_path, line, status):
    manifest = prepared(method, tmp_path / 'pvt')
    context = manifest['contexts'][0]
    _native_fixture_series(context, limit=1)
    score_path = Path(context['score']); score = json.loads(score_path.read_text())
    point_path = Path(score['points'][0]['path']); point = json.loads(point_path.read_text())
    log = Path(point['executions'][0]['log']); log.write_text(log.read_text() + '\n' + line)
    point['executions'][0].update(returncode=124, log_sha256=capture.bound.sha(log))
    point_path.write_text(json.dumps(point)); score['points'][0] = pvt._view(point_path)
    score_path.write_text(json.dumps(score))
    result = pvt.collect(manifest)
    assert result['status'] == status
    assert result['metrics']['contexts'][0]['status'] == status


def _native_fixture_series(context, limit=None):
    """Finite low-resolution synthetic capture, using the real decoder/fit."""
    settings = json.loads(Path(context["settings"]["path"]).read_text())
    project = Path(context["project"])
    bdir = project / "phase3/analog/converter"
    spec = json.loads((bdir / "spec.json").read_text())
    topology = json.loads((bdir / "topology.json").read_text())
    template = Path(context["native_inputs"]["testbench"]["path"])
    points = []
    prototype = Path(context["score"]).parent / "fixture-prototype.dat"
    prototype.parent.mkdir(parents=True)
    _text, clock, declaration = capture.prepare_deck(template, spec, topology,
        capture.phase_settings(settings, 0), prototype.parent)
    candidates = []
    for pattern in itertools.product((0, 1.2), repeat=3):
        raw = _dump(prototype)
        lines = []
        for line in raw.read_text().splitlines():
            fields = line.split()
            try:
                t = float(fields[0])
            except ValueError:
                lines.append(line)
                continue
            slot = math.floor(t - 1 + 1e-9)
            if 1 <= slot <= 3:
                fields[1] = str(pattern[slot - 1])
            fields[0] = f"{t * 1e-6:.17g}"
            lines.append(" ".join(fields))
        raw.write_text("\n".join(lines))
        decoded = capture.decode_capture(raw, clock, declaration, capture.phase_settings(settings, 0))
        if decoded["conversions"]:
            candidates.append((decoded["conversions"][0]["decoded"], raw.read_text()))
    prototype.unlink()
    for index in range(settings["series_length"] if limit is None else limit):
        local = capture.phase_settings(settings, index)
        destination = Path(context["score"]).parent / f"point-{index:03d}"
        destination.mkdir(parents=True)
        angle = 2 * math.pi * settings["tone_bin"] * index / settings["series_length"]
        # The four-clock fixture's decoded code levels span +/-7.5. Exercise
        # several of them, rather than reducing this instrument to one bit.
        target = 4 * math.sin(angle)
        chosen = min(candidates, key=lambda item: abs(item[0] - target))[1]
        chosen = "\n".join(" ".join([*line.split()[:3], f"{local['held_input_v']:.17g}", *line.split()[4:]])
            if line and line[0].isdigit() else line for line in chosen.splitlines())
        def native(deck, target_dir):
            (target_dir / "conversion.dat").write_text(chosen)
            log = target_dir / "native.log"
            log.write_text(f"Doing analysis at TEMP = {context['temperature_c']:.6f} and TNOM = 27\n" +
                "Initial Transient Solution\n--------------------------\n\nNode Voltage\n---- -------\n" +
                "vdd 1.8\nref_hi 1.4\nref_lo 0.4\n\n")
            return {"returncode": 0, "log": str(log), "log_sha256": capture.bound.sha(log)}
        record = capture.run_point(project, bdir / "converter.sp", template, bdir / "spec.json",
            bdir / "topology.json", local, destination, native)
        assert record["status"] == "PASS", record
        record["image"] = "fixture-image"
        path = destination / "result.json"
        path.write_text(json.dumps(record))
        points.append(pvt._view(path))
    score = Path(context["score"])
    score.write_text(json.dumps({"status": "PASS", "measurements": {"enob": 99}, "points": points}))


@pytest.fixture
def populated(method, tmp_path, request):
    if getattr(request, "param", None) == "outside-vref":
        spec_path = method[0] / "phase3/analog/converter/spec.json"
        spec = json.loads(spec_path.read_text())
        next(row for row in spec["specs"] if row["name"] == "vref")["max"] = .9
        spec_path.write_text(json.dumps(spec))
    manifest = prepared(method, tmp_path / "pvt")
    for context in manifest["contexts"]:
        _native_fixture_series(context)
    return manifest


def test_complete_nine_contexts_replay_actual_waveforms_and_source_threshold(populated):
    original = {row["path"]: row["sha256"] for context in populated["contexts"]
                for row in json.loads(Path(context["score"]).read_text())["points"]}
    result = pvt.collect(populated)
    assert result["status"] == "PASS", result["metrics"]["contexts"]
    assert result["metrics"]["target_bits"] == 1  # Neutral fixture source, not the ADC's14bit requirement.
    assert result["metrics"]["corners_executed"] == 9
    assert result["metrics"]["full_pvt_sweep_executed"] is True
    assert result["metrics"]["source_measurement_coverage"] == {
        "required": ["enob", "vref"], "measured": ["enob", "vref"], "missing": []}
    for name in ("enob", "vref"):
        assert result["metrics"]["source_context_coverage"][name]["required_contexts"] == 9
        assert result["metrics"]["source_context_coverage"][name]["measured_contexts"] == 9
        assert not result["metrics"]["source_context_coverage"][name]["missing_contexts"]
    assert all(len(row["reference_observations"]) == 64 for row in result["metrics"]["contexts"])
    assert all(row["measurements"]["enob"] < 99 for row in result["metrics"]["contexts"])
    assert all(Path(path).is_dir() or Path(path).is_file() for path in result["outputs"])
    assert any(":point:0:log" in key for key in result["native_inputs"])
    assert all(capture.bound.sha(path) == digest for path, digest in original.items())


@pytest.mark.parametrize("populated", ["outside-vref"], indirect=True)
def test_native_vref_violation_forces_overall_fail_with_complete_enob_coverage(populated):
    result = pvt.collect(populated)
    assert result["status"] == "FAIL"
    assert result["metrics"]["source_context_coverage"]["enob"]["measured_contexts"] == 9
    assert result["metrics"]["source_context_coverage"]["vref"]["measured_contexts"] == 9
    assert all(row["status"] == "FAIL" for row in result["metrics"]["contexts"])
    assert any(row["name"] == "vref" and row["status"] == "FAIL" for row in result["metrics"]["spec_results"])


@pytest.mark.parametrize("mutation", ["missing", "nan", "not_constant", "other_dut"])
def test_initial_reference_requires_actual_finite_constant_sources_on_the_correct_dut(method, tmp_path, mutation):
    manifest = prepared(method, tmp_path / "pvt")
    context = manifest["contexts"][0]
    _native_fixture_series(context, limit=1)
    score = json.loads(Path(context["score"]).read_text())
    point = json.loads(Path(score["points"][0]["path"]).read_text())
    transcript = Path(point["executions"][0]["log"]).read_text()
    if mutation == "missing":
        transcript = transcript.replace("ref_lo 0.4\n", "")
    elif mutation == "nan":
        transcript = transcript.replace("ref_lo 0.4", "ref_lo nan")
    else:
        path = Path(point["native_inputs"]["deck"]["path"])
        text = path.read_text()
        path.write_text(text.replace("v_ref_hi ref_hi 0 1.4", "v_ref_hi ref_hi 0 pwl(0 1.4 1u 1.5)")
                        if mutation == "not_constant" else text.replace("dout conv", "dout other_dut"))
    with pytest.raises(ValueError):
        pvt._reference_measurement(point, transcript, manifest['reference_ports'])


@pytest.mark.parametrize("unit,low,high", [("mV", 800, 1200), ("A", .8, 1.2)])
def test_native_reference_is_attributed_in_the_source_voltage_units(method, tmp_path, unit, low, high):
    spec_path = method[0] / "phase3/analog/converter/spec.json"
    spec = json.loads(spec_path.read_text())
    next(row for row in spec["specs"] if row["name"] == "vref").update(unit=unit, min=low, max=high)
    spec_path.write_text(json.dumps(spec))
    manifest = prepared(method, tmp_path / "pvt")
    context = manifest["contexts"][0]
    _native_fixture_series(context, limit=1)
    entry = json.loads(Path(context["score"]).read_text())["points"][0]
    point = json.loads(Path(entry["path"]).read_text())
    log = Path(point["executions"][0]["log"]).read_text()
    if unit == "mV":
        observed = pvt._reference_measurement(point, log, manifest['reference_ports'])
        assert observed["status"] == "PASS" and observed["value"] == 1000
        assert observed["native_difference_v"] == 1 and not observed["violation"]
        assert observed['reference_ports'] == {'positive': 'ref_hi', 'negative': 'ref_lo'}
    else:
        with pytest.raises(ValueError, match="units"):
            pvt._reference_measurement(point, log, manifest['reference_ports'])


@pytest.mark.parametrize('pair', [None, ['ref_hi', 'ref_hi'], ['vrefp', 'vrefn']])
def test_reference_pair_must_be_explicit_distinct_and_declared(method, tmp_path, pair):
    with pytest.raises(ValueError, match='reference ports'):
        prepared(method, tmp_path / 'pvt', reference_ports=pair)


def test_collector_refuses_missing_reference_pair(method, tmp_path):
    manifest = prepared(method, tmp_path / 'pvt')
    del manifest['reference_ports']
    result = pvt.collect(manifest)
    assert result['status'] == 'NOT_MEASURED'
    assert 'reference ports' in result['detail']


def test_source_without_reference_requirement_needs_no_reference_pair(method, tmp_path):
    source = method[0] / 'phase3/analog/converter/spec.json'
    spec = json.loads(source.read_text())
    spec['specs'] = [row for row in spec['specs'] if row['name'] != 'vref']
    source.write_text(json.dumps(spec))
    manifest = prepared(method, tmp_path / 'pvt', reference_ports=None)
    assert manifest['reference_ports'] == []
    assert pvt._validate_manifest(manifest) == manifest['contexts']
    assert pvt.collect(manifest)['status'] == 'NOT_MEASURED'  # Native corners still absent.


def test_producer_provenance_retains_immutable_bytes_without_invalidating_electrical_inputs(method, tmp_path, monkeypatch):
    origin = tmp_path / 'mutable-producer.py'
    origin.write_bytes(Path(pvt.__file__).read_bytes())
    original = origin.read_bytes()
    monkeypatch.setattr(pvt, '__file__', str(origin))
    manifest = prepared(method, tmp_path / 'pvt')
    snapshot = Path(manifest['native_inputs']['producer']['path'])
    assert snapshot != origin and snapshot.read_bytes() == original
    assert manifest['producer_origins']['producer']['path'] == str(origin)
    capture_snapshot = Path(manifest['native_inputs']['incremental_producer']['path'])
    assert capture_snapshot.read_bytes() == Path(capture.__file__).read_bytes()
    origin.write_text('# later source-only change\n')
    assert pvt._validate_manifest(manifest) == manifest['contexts']
    snapshot.write_text('# altered retained provenance\n')
    with pytest.raises(ValueError, match='source inputs are absent or changed'):
        pvt._validate_manifest(manifest)


def test_native_first_conversion_failure_remains_fail_without_any_score(method, tmp_path):
    manifest = prepared(method, tmp_path / "pvt")
    context = manifest["contexts"][0]
    _native_fixture_series(context, limit=1)
    score = Path(context["score"])
    point_path = Path(json.loads(score.read_text())["points"][0]["path"])
    point = json.loads(point_path.read_text())
    log = Path(point["executions"][0]["log"])
    log.write_text(log.read_text() + ";;RESIDUAL_FAIL first conversion\n")
    point["executions"][0]["log_sha256"] = capture.bound.sha(log)
    point_path.write_text(json.dumps(point))
    score.unlink()
    assert pvt.collect(manifest)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["temperature", "missing_phase", "native_failure", "image"])
def test_cached_pass_cannot_hide_wrong_or_incomplete_native_corner(populated, mutation):
    context = populated["contexts"][0]
    score_path = Path(context["score"])
    score = json.loads(score_path.read_text())
    point_path = Path(score["points"][0]["path"])
    point = json.loads(point_path.read_text())
    if mutation == "missing_phase":
        score["points"].pop()
    elif mutation == "image":
        point["image"] = "wrong-runtime"
    else:
        log = Path(point["executions"][0]["log"])
        log.write_text(log.read_text().replace("TEMP = -40.000000", "TEMP = 27.000000") if mutation == "temperature" else
                       log.read_text() + ";;RESIDUAL_FAIL fixture native failure\n")
        point["executions"][0]["log_sha256"] = capture.bound.sha(log)
    point_path.write_text(json.dumps(point))
    score["points"][0] = pvt._view(point_path)
    score_path.write_text(json.dumps(score))
    result = pvt.collect(populated)
    assert result["status"] == ("FAIL" if mutation == "native_failure" else "NOT_MEASURED")


@pytest.mark.parametrize("mutation", ["duplicate", "clock", "geometry"])
def test_prepared_input_mutations_cannot_substitute_for_actual_source_context(method, tmp_path, mutation):
    manifest = prepared(method, tmp_path / "pvt")
    if mutation == "duplicate":
        manifest["contexts"][-1] = copy.deepcopy(manifest["contexts"][0])
    elif mutation == "clock":
        path = Path(manifest["contexts"][0]["native_inputs"]["testbench"]["path"])
        path.write_text(path.read_text().replace("1000n", "2000n"))
        manifest["contexts"][0]["native_inputs"]["testbench"] = pvt._view(path)
    else:
        path = Path(manifest["contexts"][0]["native_inputs"]["netlist"]["path"])
        path.write_text(path.read_text().replace("1k", "2k"))
        manifest["contexts"][0]["native_inputs"]["netlist"] = pvt._view(path)
    assert pvt.collect(manifest)["status"] == "NOT_MEASURED"


def test_run_bounds_outer_corner_concurrency_and_leaves_collect_separate(method, tmp_path):
    manifest = prepared(method, tmp_path / "pvt")
    active = peak = 0
    lock = threading.Lock()
    seen = []
    def launch(argv):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            seen.append(argv)
        time.sleep(.01)
        with lock:
            active -= 1
        return 2
    result = pvt.run(manifest, "fixture-container", "fixture-image", workers=8, cpus=2, launch=launch)
    assert result["status"] == "NOT_MEASURED"
    assert peak == 2 and len(seen) == 9
    assert all(argv[argv.index("--workers") + 1] == "1" and argv[argv.index("--cpus") + 1] == "1" for argv in seen)


def test_missing_nominal_reuse_never_launches_duplicate_a07(method, tmp_path):
    manifest = prepared(method, tmp_path / "pvt", nominal_score=tmp_path / "original-a07/score.json")
    result = pvt.run(manifest, "container", "fixture-image", launch=lambda *args: pytest.fail("nominal A07 is unavailable"))
    assert result["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("budget,outer,inner", [(16, 8, 2), (1, 1, 1)])
def test_shared_worker_budget_fills_sixteen_cpus_without_restarting_nominal(method, tmp_path, monkeypatch, budget, outer, inner):
    manifest = prepared(method, tmp_path / "pvt", nominal_score=tmp_path / "a07/score.json")
    calls, active, peak = [], 0, 0
    lock = threading.Lock()
    # Isolate scheduling from replay, whose real positive and refusal paths
    # are exercised above. The reused nominal corner is already complete.
    def collection(_manifest):
        return {"status": "NOT_MEASURED", "metrics": {"contexts": [
            {"process": "device_tt", "temperature_c": 27, "status": "PASS"}]}}
    monkeypatch.setattr(pvt, "collect", collection)
    def launch(argv):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(argv)
        time.sleep(.02)
        with lock:
            active -= 1
        return 2
    result = pvt.run(manifest, "container", "fixture-image", workers=budget, cpus=budget, launch=launch)
    assert len(calls) == 8 and peak <= outer
    assert all(int(argv[argv.index("--workers") + 1]) == inner and
               int(argv[argv.index("--cpus") + 1]) == inner for argv in calls)
    actual = result["metrics"]["execution_budget"]
    assert actual["corner_workers"] == outer and actual["phase_workers_per_series"] == inner
    assert actual["total_phase_workers"] <= budget and actual["total_cpu_ceiling"] <= budget
