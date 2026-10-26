"""Native-instrument controls; synthetic arithmetic is never silicon evidence."""
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_incremental_capture as capture


def _timing():
    return {"kind": "source_derived_sc_transfer_gates_v1",
            "columns": ["v(xdut.transfer_n)", "v(xdut.transfer_p)"],
            "groups": [{"capacitor": "sample_unit", "n_gate": "v(xdut.transfer_n)",
                        "p_gate": "v(xdut.transfer_p)"}]}


def _declaration(*, delay=1):
    return {"window_clocks": 4, "order": 1, "coeff": .25,
            "feedback_delay_clocks": delay, "native_timing": _timing()}


def _dump(path, *, moving=False, truncated=False, assert_at=5.5):
    rows = []
    for tick in range(0, 61 if truncated else 81):
        t = tick / 10
        reset = 0 if 1.5 <= t < 2.5 or assert_at <= t < 6.5 else 1.2
        # Reset period4 has three actual transfer pulses; the final sampled
        # decision is reset-active and cannot add a fourth recurrence update.
        slot = math.floor(t - 1 + 1e-9)
        bit = 0 if slot in (2, 4) else 1.2
        transfer = (tick % 10) >= 6
        rows.append(f"{t:.17g} {bit} {reset} {0.7 + (t / 100 if moving else 0):.17g} "
                    f"{1.2 if transfer else 0} {0 if transfer else 1.2}")
    path.write_text("time output reset input v(xdut.transfer_n) v(xdut.transfer_p)\n" + "\n".join(rows))
    return path


def test_reset_alignment_discards_startup_and_decodes_complete_conversion(tmp_path):
    out = capture.decode_capture(_dump(tmp_path / "wave.dat"), (1, 1, 1.2),
        _declaration(), {})
    assert len(out["conversions"]) == 1
    assert out["conversions"][0]["decoded"] == 0  # +,-,unused; the old4-update kernel wrongly credited +1/4
    assert out["conversions"][0]["clock_slots"] == 3
    assert out["conversions"][0]["active_update_clocks"] == 3
    assert out["conversions"][0]["reset_period_clocks"] == 4
    assert out["conversions"][0]["ignored_zero_weight_decisions"] == 0
    assert out["conversions"][0]["excluded_reset_active_slots"] == 1
    assert out["conversions"][0]["first_sample_s"] == pytest.approx(2.9)
    assert out["conversions"][0]["last_sample_s"] == pytest.approx(4.9)
    assert out["discarded_intervals"] == []


def test_low_phase_first_decision_after_release_is_not_skipped(tmp_path):
    # Native-style timing: reset releases just after clock fall; the first
    # registered decision follows that same falling edge, before the next rise.
    events = [(0, 1.2, 1.2), (1.5016e-6, 1.2, 1.2), (1.5017e-6, 1.2, 0),
              (2.5015e-6, 1.2, 0), (2.5016e-6, 1.2, 1.2),
              (2.5101e-6, 0, 1.2), (3.5101e-6, 1.2, 1.2), (4.5101e-6, 0, 1.2),
              (5.5016e-6, 0, 1.2), (5.5017e-6, 0, 0), (5.5101e-6, 1.2, 0),
              (6.5015e-6, 1.2, 0), (6.5016e-6, 1.2, 1.2), (7e-6, 1.2, 1.2)]
    path = tmp_path / "falling.dat"
    events += [(x * 1e-6, 0 if x < 3.51 else 1.2 if x < 4.51 else 0,
                1.2 if x < 5.5016 else 0) for x in (2.6, 2.99, 3.0, 3.6, 3.99, 4.0, 4.6, 4.99, 5.0)]
    events.sort()
    path.write_text("time output reset input v(xdut.transfer_n) v(xdut.transfer_p)\n" + "\n".join(
        f"{t:.17g} {bit} {reset} .7 {1.2 if .6 <= (t * 1e6 % 1) < .9999 else 0} "
        f"{0 if .6 <= (t * 1e6 % 1) < .9999 else 1.2}" for t, bit, reset in events))
    result = capture.decode_capture(path, (1e-6, 1e-6, 1.2),
        _declaration(), {"held_input_v": .7})
    conversion = result["conversions"][0]
    assert conversion["release_s"] == pytest.approx(2.50155e-6)
    assert conversion["first_sample_s"] == pytest.approx(2.9e-6)
    assert conversion["clock_slots"] == 3 and conversion["ignored_zero_weight_decisions"] == 0
    assert conversion["decoded"] == 0  # -,+,unused; no final feedback update during reset


@pytest.mark.parametrize("kwargs", [{"moving": True}, {"truncated": True}])
def test_moving_or_incomplete_conversion_is_not_credited(tmp_path, kwargs):
    out = capture.decode_capture(_dump(tmp_path / "wave.dat", **kwargs), (1, 1, 1.2),
        _declaration(), {})
    assert out["conversions"] == []


def test_reset_cannot_mask_a_decision_with_nonzero_decode_weight(tmp_path):
    result = capture.decode_capture(_dump(tmp_path / "wave.dat", assert_at=5.8), (1, 1, 1.2),
        _declaration(delay=0), {})
    assert not result["conversions"]
    assert result["discarded_intervals"][0]["reason"] == "transfer_pulse_overlaps_reset"


def test_native_input_must_match_the_executed_held_stimulus(tmp_path):
    result = capture.decode_capture(_dump(tmp_path / "wave.dat"), (1, 1, 1.2),
        _declaration(), {"held_input_v": .8})
    assert not result["conversions"]
    assert result["discarded_intervals"][0]["reason"] == "native_input_differs_from_executed_stimulus"


def test_lossless_gzip_preserves_every_capture_byte_and_decoded_value(tmp_path):
    path = _dump(tmp_path / "wave.dat")
    original = capture.capture_sha(path)
    declaration = _declaration()
    decoded = capture.decode_capture(path, (1, 1, 1.2), declaration, {})
    receipt = capture.compress_capture(path)
    assert not path.exists()
    compressed = Path(receipt["path"])
    assert receipt["raw_sha256"] == original == capture.capture_sha(compressed, decompressed=True)
    assert receipt["sha256"] == capture.capture_sha(compressed)
    assert capture.decode_capture(compressed, (1, 1, 1.2), declaration, {}) == decoded


def test_failed_compression_preserves_original_capture(tmp_path, monkeypatch):
    path = _dump(tmp_path / "wave.dat")
    before = path.read_bytes()
    real = capture.capture_sha
    monkeypatch.setattr(capture, "capture_sha", lambda p, **kw: "wrong" if kw.get("decompressed") else real(p))
    with pytest.raises(ValueError, match="lossless"):
        capture.compress_capture(path)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".gz").exists()


def test_capture_missing_first_sample_is_refused(tmp_path):
    path = tmp_path / "late.dat"
    path.write_text("2 1.2 1.2 .7\n3 1.2 1.2 .7\n")
    with pytest.raises(ValueError, match="first sampling instant"):
        capture.sampled_capture(path, 1, 1, 1.2)


def test_delayed_recurrence_uses_observed_updates_not_reset_period(tmp_path):
    declaration = _declaration()
    declaration['order'] = 2
    result = capture.decode_capture(_dump(tmp_path / 'wave.dat'), (1, 1, 1.2), declaration, {})
    conversion, = result['conversions']
    assert conversion['clock_slots'] == 3 and conversion['reset_period_clocks'] == 4
    bits = [1., -1., 1.]
    x1 = x2 = previous_bit = 0.
    for bit in bits:
        x2 += .25 * (x1 - previous_bit)
        x1 += .25 * (.1 - previous_bit)
        previous_bit = bit
    normalizer = sum(capture.decimator.input_weights(3, 2, .25))
    assert conversion['decoded'] == pytest.approx(.1 - x2 / normalizer)
    assert conversion['decoded'] == pytest.approx(1 / 3)
    # The old period4 kernel gives the final active bit nonzero future credit.
    old, _ = capture.decimator.decimate([*bits, -1.], 4, 2, .25, 1)
    assert old[0] == pytest.approx(5 / 6)


def test_all_four_updates_are_retained_when_observed_before_reset(tmp_path):
    result = capture.decode_capture(_dump(tmp_path / 'wave.dat', assert_at=6.05),
                                    (1, 1, 1.2), _declaration(), {})
    conversion, = result['conversions']
    assert conversion['clock_slots'] == conversion['reset_period_clocks'] == 4
    assert conversion['excluded_reset_active_slots'] == 0


def test_propagated_transfer_closure_can_cross_ideal_clock_boundary(tmp_path):
    path = _dump(tmp_path / 'wave.dat')
    lines = path.read_text().splitlines()
    for index in range(1, len(lines)):
        fields = lines[index].split()
        phase = int(round(float(fields[0]) * 10)) % 10
        enabled = phase >= 6 or phase == 0  # falls0.05period after ideal boundary
        fields[4:] = ['1.2', '0'] if enabled else ['0', '1.2']
        lines[index] = ' '.join(fields)
    path.write_text('\n'.join(lines))
    result = capture.decode_capture(path, (1, 1, 1.2), _declaration(), {})
    conversion, = result['conversions']
    assert conversion['active_update_clocks'] == 3
    assert conversion['decoded'] == 0


@pytest.mark.parametrize('fault', ['missing_pulse', 'midwindow_reset', 'missing_reset'])
def test_inconsistent_transfer_or_reset_intervals_refuse(tmp_path, fault):
    path = _dump(tmp_path / 'wave.dat')
    lines = path.read_text().splitlines()
    for index in range(1, len(lines)):
        fields = lines[index].split(); when = float(fields[0])
        if fault == 'missing_pulse' and 3.5 <= when <= 4:
            fields[4:] = ['0', '1.2']
        if fault == 'midwindow_reset' and 3.2 <= when < 3.4:
            fields[2] = '0'
        if fault == 'missing_reset' and when >= 2.5:
            fields[2] = '1.2'
        lines[index] = ' '.join(fields)
    path.write_text('\n'.join(lines))
    assert not capture.decode_capture(path, (1, 1, 1.2), _declaration(), {})['conversions']


def test_phase_header_must_name_the_actual_derived_vectors(tmp_path):
    path = _dump(tmp_path / 'wave.dat')
    path.write_text(path.read_text().replace('v(xdut.transfer_n)', 'v(xdut.other_node)'))
    with pytest.raises(ValueError, match='phase header differs'):
        capture.decode_capture(path, (1, 1, 1.2), _declaration(), {})


def test_legacy_reset_only_capture_has_no_guessed_update_count(tmp_path):
    declaration = _declaration(); declaration.pop('native_timing')
    result = capture.decode_capture(_dump(tmp_path / 'wave.dat'), (1, 1, 1.2), declaration, {})
    assert not result['conversions']
    assert result['discarded_intervals'] == [{'reason': 'native_transfer_phase_attribution_absent'}]


def test_coherent_fit_counts_harmonics_as_distortion():
    values = [0.3 + 0.7 * math.sin(2 * math.pi * 9 * n / 64)
              + 0.007 * math.sin(2 * math.pi * 27 * n / 64) for n in range(64)]
    result = capture.fit_coherent_sndr(values, 9, 14)
    assert result["status"] == "FAIL"
    assert result["measurements"]["sndr_db"] == pytest.approx(40, abs=1e-10)
    assert result["measurements"]["enob"] == pytest.approx((40 - 1.76) / 6.02)


def test_constant_and_perfect_arithmetic_cannot_manufacture_enob():
    assert capture.fit_coherent_sndr([1.0] * 64, 9, 14)["status"] == "FAIL"
    ideal = [math.sin(2 * math.pi * 9 * n / 64) for n in range(64)]
    assert capture.fit_coherent_sndr(ideal, 9, 14)["status"] == "NOT_MEASURED"
    with pytest.raises(ValueError, match="three harmonics"):
        capture.fit_coherent_sndr(ideal[:54], 9, 14)


def test_pass_word_without_native_execution_is_not_evidence():
    result = capture.coherent_sndr([{"status": "PASS", "settings": {"phase_index": 0},
        "decoded": {"conversions": [{"decoded": 0.2}]}}], 64, 9, 14)
    assert result["status"] == "NOT_MEASURED"
    assert "executed deck" in result["detail"]


@pytest.mark.parametrize("line", [";;RESIDUAL_FAIL x", "Error: transient analysis failed", "fatal error: model", "timestep too small"])
def test_native_failure_text_is_decisive(line):
    assert capture.native_failed(line)


def _template(tmp_path):
    from test_analog_resolution_stimulus import _deck, _spec, _topo
    source = tmp_path / "source.sp"
    source.write_text(_deck(stop_ns=560000))
    spec = _spec(enob=14, osr=8)
    topology = _topo()
    topology["conversion_mode"] = "incremental"
    topology["constants"] = {"window_clocks": 8, "feedback_delay_clocks": 1}
    topology["stage_expansion"] = {"count_from": "order", "stages": 2,
                                  "coefficients": [0.25, 0.25], "chain": ["ain", "n1", "n2"]}
    topology["loop_probe"] = {"coefficient_devices": {"sampling": "sample{i}",
        "feedback": "feedback{i}", "integrating": "store{i}"}}
    devices = []
    def pair(name, a, b, n="transfer_n", p="transfer_p"):
        devices.extend([{"name": "mn_" + name, "role": "nmos", "nets": [a, n, b, "vss"]},
                        {"name": "mp_" + name, "role": "pmos", "nets": [a, p, b, "vdd"]}])
    for stage in (1, 2):
        summing, out = f"sum{stage}", f"n{stage}"
        devices.extend([{"name": f"store{stage}", "role": "capacitor", "nets": [summing, out]},
                        {"name": f"mn_amplifier{stage}", "role": "nmos",
                         "nets": [f"drain{stage}", summing, "vss", "vss"]}])
        pair(f"reset{stage}", summing, out, "reset_on", "reset_b")
        for branch, source_net in (("sample", "ain" if stage == 1 else "n1"), ("feedback", "reference_state")):
            name = f"{branch}{stage}"
            bottom, top = name + "_bottom", name + "_top"
            devices.append({"name": name, "role": "capacitor", "nets": [bottom, top]})
            pair(name + "_transfer", top, summing)
            pair(name + "_reference", top, "vcm", "sample_on", "sample_off")
            pair(name + "_sample", bottom, source_net, "sample_on", "sample_off")
            pair(name + "_return", bottom, "vcm")
    topology["devices"] = devices
    cards = []
    for device in devices:
        if len(device['nets']) == 2:
            cards.append('c_' + device['name'] + ' ' + ' '.join(device['nets']) + ' 1p')
        else:
            cards.append('m_' + device['name'] + ' ' + ' '.join(device['nets'])
                         + (' NTEST' if device['role'] == 'nmos' else ' PTEST') + ' w=1u l=1u')
    source.write_text(source.read_text().replace('.ends conv', '\n'.join(cards) + '\n.ends conv'))
    return source, spec, topology


def test_held_deck_keeps_delivered_circuit_clock_and_numerical_settings(tmp_path):
    source, spec, topology = _template(tmp_path)
    text, clock, declaration = capture.prepare_deck(source, spec, topology,
        {"reset_node": "xdut.reset_b", "held_input_v": 0.8}, tmp_path)
    assert "r1 ain dout 1k" in text
    assert "v_clk clk 0 pulse(0 1.8 0n 1n 1n 499n 1000n)" in text
    assert "v_ain ain 0 0.80000000000000004" in text
    assert "sin(" not in text.casefold()
    assert declaration["window_clocks"] == 8
    assert clock == pytest.approx((0.0, 1e-6, 1.8))
    assert "v(xdut.reset_b)" in text and "set num_threads=4" in text
    assert source.read_text().count("meas tran vavg") == 1


def test_reset_and_held_level_must_be_explicit(tmp_path):
    source, spec, topology = _template(tmp_path)
    with pytest.raises(ValueError, match="reset node"):
        capture.prepare_deck(source, spec, topology, {"held_input_v": 0.8}, tmp_path)
    with pytest.raises(ValueError, match="held input"):
        capture.prepare_deck(source, spec, topology, {"reset_node": "xdut.reset_b"}, tmp_path)


def test_precision_settings_are_explicit_and_recordable(tmp_path):
    source, spec, topology = _template(tmp_path)
    settings = {"reset_node": "xdut.reset_b", "held_input_v": 0.8,
                "numerical_options": {"reltol": 1e-6, "vntol": 1e-8, "abstol": 1e-15, "method": "gear"}}
    text, _, _ = capture.prepare_deck(source, spec, topology, settings, tmp_path)
    assert "method=gear maxord=2" in text and "abstol=" in text
    settings["numerical_options"]["method"] = "gear; alter circuit"
    with pytest.raises(ValueError, match="integration method"):
        capture.prepare_deck(source, spec, topology, settings, tmp_path)


def test_metadata_cannot_reinterpret_an_executed_deck(tmp_path, monkeypatch):
    source, spec, topology = _template(tmp_path)
    spec_path, topology_path = tmp_path / "spec.json", tmp_path / "topology.json"
    spec_path.write_text(json.dumps(spec)); topology_path.write_text(json.dumps(topology))
    settings = {"reset_node": "xdut.reset_b", "held_input_v": 0.8}
    text, clock, declaration = capture.prepare_deck(source, spec, topology, settings, tmp_path)
    deck = tmp_path / "conversion.sp"; deck.write_text(text)
    views = {role: {"path": str(path), "sha256": capture.bound.sha(path)} for role, path in
        (("deck", deck), ("testbench", source), ("spec", spec_path), ("topology", topology_path))}
    monkeypatch.setattr(capture.bound, "validate_consumed_inputs", lambda *args: (True, "fixture closure"))
    monkeypatch.setattr(capture, "declared_dut_consumed", lambda views: True)
    record = {"native_inputs": views, "settings": settings, "clock": list(clock), "incremental_decode": declaration}
    record["clock"][0] += 1e-6
    assert capture.validate_point(record) == (False, "native conversion metadata differs from its executed deck")


def test_declared_dut_must_be_in_the_actual_include_closure(tmp_path):
    source, spec, topology = _template(tmp_path)
    text = source.read_text()
    body = text[text.index(".subckt"):text.index(".ends conv") + len(".ends conv")]
    actual = tmp_path / "actual DUT.sp"; actual.write_text(body)
    unrelated = tmp_path / "declared.sp"; unrelated.write_text(body.replace("1k", "2k"))
    source.write_text(text.replace(body, '.include "actual DUT.sp"'))
    spec_path, topology_path = tmp_path / "spec.json", tmp_path / "topology.json"
    spec_path.write_text(json.dumps(spec)); topology_path.write_text(json.dumps(topology))
    def forbidden(*args):
        pytest.fail("native launched for a DUT absent from the actual include closure")
    result = capture.run_point(tmp_path, unrelated, source, spec_path, topology_path,
        {"reset_node": "xdut.reset_b", "held_input_v": .8}, tmp_path / "native", forbidden)
    assert result["status"] == "NOT_MEASURED" and "include closure" in result["detail"]
    assert result["executions"] == []
    assert not capture.declared_dut_consumed(result["native_inputs"])
    views = dict(result["native_inputs"])
    views["netlist"] = {"path": str(actual), "sha256": capture.bound.sha(actual)}
    assert capture.declared_dut_consumed(views)


def _series(tmp_path, monkeypatch):
    """Isolate series arithmetic; provenance itself is tested separately."""
    monkeypatch.setattr(capture, "validate_point", lambda point: (True, "component fixture"))
    monkeypatch.setattr(capture, "decoded_point", lambda point: point["decoded"])
    monkeypatch.setattr(capture, "write_decoder_replay", lambda point, path: {"decoded": point["decoded"],
        "receipt": {"path": str(path), "sha256": "synthetic instrument fixture"}})
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"specs": [{"name": "enob", "min": 14}]}))
    views = {role: {"path": str(spec), "sha256": "fixture"} for role in ("spec", "netlist", "topology", "testbench")}
    points = []
    for n in range(64):
        angle = 2 * math.pi * 9 * n / 64
        vin = 0.6 + 0.3 * math.sin(angle)
        points.append({"status": "PASS", "native_inputs": dict(views), "image": "fixture-image",
            "settings": {"phase_index": n, "series_length": 64, "tone_bin": 9, "dc_offset_v": 0.6, "amplitude_v": 0.3},
            "decoded": {"conversions": [{"input_v": vin, "decoded": vin + .003 * math.sin(3 * angle)}]}})
    return points


def test_series_binds_native_inputs_to_phase_and_source_target(tmp_path, monkeypatch):
    points = _series(tmp_path, monkeypatch)
    assert capture.coherent_sndr(points, 64, 9, 14)["measurements"]["sndr_db"] == pytest.approx(40)
    assert "source ENOB" in capture.coherent_sndr(points, 64, 9, 6)["detail"]
    points[1]["settings"]["phase_index"], points[2]["settings"]["phase_index"] = 2, 1
    result = capture.coherent_sndr(points, 64, 9, 14)
    assert result["status"] == "NOT_MEASURED" and "coherent phase" in result["detail"]


def test_series_rejects_mixed_model_context_and_missing_points(tmp_path, monkeypatch):
    points = _series(tmp_path, monkeypatch)
    assert capture.coherent_sndr(points[:-1], 64, 9, 14)["status"] == "NOT_MEASURED"
    points[-1]["native_inputs"]["include:model"] = {"path": "fixture", "sha256": "changed"}
    result = capture.coherent_sndr(points, 64, 9, 14)
    assert result["status"] == "NOT_MEASURED" and "DUT/model/stimulus" in result["detail"]


@pytest.mark.parametrize("change", [{"numerical_options": {"reltol": 1e-3}}, {"sample_fraction": .8}])
def test_score_refuses_mixed_common_numerical_or_sampling_settings(tmp_path, monkeypatch, change):
    points = _series(tmp_path, monkeypatch)
    points[-1]["settings"].update(change)
    result = capture.coherent_sndr(points, 64, 9, 14)
    assert result["status"] == "NOT_MEASURED" and "common measurement settings" in result["detail"]


@pytest.mark.parametrize("code,line,status", [(1, "", "FAIL"), (0, ";;RESIDUAL_FAIL native", "FAIL"),
                                             (143, "", "NOT_MEASURED"), (143, ";;RESIDUAL_FAIL native", "FAIL")])
def test_cached_pass_cannot_hide_native_failure_or_interruption(tmp_path, monkeypatch, code, line, status):
    points = _series(tmp_path, monkeypatch)
    log = tmp_path / "ngspice.log"; log.write_text(line)
    points[0]["executions"] = [{"returncode": code, "log": str(log), "log_sha256": capture.bound.sha(log)}]
    assert capture.coherent_sndr(points, 64, 9, 14)["status"] == status


@pytest.mark.parametrize('code,line,status', [(124, '', 'NOT_MEASURED'),
    (124, ';;RESIDUAL_FAIL actual numerical error', 'FAIL'),
    (124, 'fatal error: actual native analysis', 'FAIL'), (1, '', 'FAIL')])
def test_current_raw_value_does_not_turn_a_timeout_into_design_failure(tmp_path, code, line, status):
    project, _settings, directory, record = _method_record(tmp_path)
    assert record['decoded']['conversions']  # Real decoder output from this finite software-fixture capture.
    execution = record['executions'][0]
    log = Path(execution['log']); log.write_text(line)
    execution.update(returncode=code, log_sha256=capture.bound.sha(log))
    assert capture.native_execution_failure(record) is (status == 'FAIL')
    assert capture.coherent_sndr([record], 64, 9, 14)['status'] == status
    paths = record['native_inputs']
    def native(deck, target):
        transcript = target / 'native.log'; transcript.write_text(line)
        return {'returncode': code, 'log': str(transcript), 'log_sha256': capture.bound.sha(transcript)}
    measured = capture.run_point(project, Path(paths['netlist']['path']), Path(paths['testbench']['path']),
        Path(paths['spec']['path']), Path(paths['topology']['path']), record['settings'], tmp_path / 'interrupted', native)
    assert measured['status'] == status and measured['decoded'] == {}


def test_consumer_replays_native_score_instead_of_trusting_cached_pass(tmp_path, monkeypatch):
    points = _series(tmp_path, monkeypatch)
    entries = []
    for n, point in enumerate(points):
        path = tmp_path / f"point-{n}.json"
        path.write_text(json.dumps(point)); entries.append({"path": str(path), "sha256": capture.bound.sha(path)})
    score = tmp_path / "score.json"
    score.write_text(json.dumps({"status": "PASS", "measurements": {"enob": 99}, "points": entries}))
    actual = capture.replay_score(score)
    assert actual["status"] == "FAIL" and actual["measurements"]["enob"] < 7
    (tmp_path / "point-0.json").write_text("{}")
    result = capture.replay_score(score)
    assert result["status"] == "NOT_MEASURED" and "changed" in result["detail"]


def _series_arguments(tmp_path, *, threads=1, cpus=2, workers=2, limit=3):
    bdir = tmp_path / "phase3/analog/converter"
    bdir.mkdir(parents=True)
    for name in ("converter.sp", "spec.json", "topology.json", "tb_converter.sp"):
        (bdir / name).write_text("{}")
    settings = tmp_path / "common.json"
    settings.write_text(json.dumps({"series_length": 64, "tone_bin": 9, "dc_offset_v": .6,
        "amplitude_v": .3, "reset_node": "xdut.reset_b", "threads": threads}))
    return [str(tmp_path), "--block", "converter", "--settings", str(settings), "--out", str(tmp_path / "native"),
        "--container", "test-container", "--image", "test-image", "--workers", str(workers), "--cpus", str(cpus),
        "--limit-points", str(limit)]


def test_series_never_launches_later_phases_before_native_control_is_complete(tmp_path, monkeypatch):
    args = _series_arguments(tmp_path)
    called = []
    def incomplete(argv):
        called.append(argv)
        destination = Path(argv[argv.index("--out") + 1])
        (destination / "result.json").write_text(json.dumps({"status": "NOT_MEASURED"}))
    monkeypatch.setattr(capture, "validate_point", lambda record: (False, "incomplete native reset interval"))
    assert capture.series_main(args, incomplete) == 2
    assert len(called) == 1
    assert "point-000" in called[0][called[0].index("--out") + 1]
    assert not (tmp_path / "native/point-001").exists()


def test_exact_running_point_prevents_duplicate_launch(tmp_path, monkeypatch):
    args = _series_arguments(tmp_path)
    monkeypatch.setattr(capture, "active_point", lambda path: True)
    def forbidden(argv):
        pytest.fail("duplicate native conversion launched")
    assert capture.series_main(args, forbidden) == 2


def test_series_refuses_thread_budget_before_native_launch(tmp_path):
    args = _series_arguments(tmp_path, threads=4, cpus=2)
    with pytest.raises(ValueError, match="CPU budget"):
        capture.series_main(args)


def test_series_generates_recorded_held_inputs_and_scores_only_native_points(tmp_path, monkeypatch):
    args = _series_arguments(tmp_path)
    launched, scored = [], []
    def native_fixture(argv):
        destination = Path(argv[argv.index("--out") + 1])
        settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        launched.append(settings)
        (destination / "result.json").write_text(json.dumps({"status": "PASS", "settings": settings}))
    monkeypatch.setattr(capture, "validate_point", lambda record: (True, "orchestration component fixture"))
    monkeypatch.setattr(capture, "score_main", lambda argv: scored.append(argv) or 2)
    assert capture.series_main(args, native_fixture) == 2
    assert sorted(setting["phase_index"] for setting in launched) == [0, 1, 2]
    assert all(setting["threads"] == 1 and setting["openmp_wait_policy"] == "PASSIVE" for setting in launched)
    assert next(s for s in launched if s["phase_index"] == 0)["held_input_v"] == .6
    assert scored[0].count("--point") == 3
    assert scored[0][scored[0].index("--length") + 1] == "64"  # partial execution cannot shrink the required record


def _method_record(tmp_path):
    """A small synthetic protocol capture with actual consumed-file hashing."""
    project = tmp_path / "project"
    bdir = project / "phase3/analog/converter"
    bdir.mkdir(parents=True)
    source, spec, topology = _template(bdir)
    topology["constants"]["window_clocks"] = 4
    text = source.read_text()
    body = text[text.index(".subckt"):text.index(".ends conv") + len(".ends conv")]
    netlist = bdir / "converter.sp"; netlist.write_text(body)
    template = bdir / "tb_converter.sp"; template.write_text(text.replace(body, '.include "converter.sp"'))
    source.unlink()
    spec_path, topology_path = bdir / "spec.json", bdir / "topology.json"
    spec_path.write_text(json.dumps(spec)); topology_path.write_text(json.dumps(topology))
    common = {"series_length": 64, "tone_bin": 9, "dc_offset_v": .7, "amplitude_v": .2,
              "reset_node": "xdut.reset_b", "threads": 1, "openmp_wait_policy": "PASSIVE"}
    common_path = project / "common.json"; common_path.write_text(json.dumps(common))
    directory = project / "native/point-000"; directory.mkdir(parents=True)
    settings = capture.phase_settings(common, 0)
    setting_path = directory / "settings.json"; setting_path.write_text(json.dumps(settings))
    text, clock, declaration = capture.prepare_deck(template, spec, topology, settings, directory)
    deck = directory / "conversion.sp"; deck.write_text(text)
    dump = _dump(directory / "conversion.dat")
    dump.write_text("\n".join(" ".join([f"{float(line.split()[0]) * 1e-6:.17g}", *line.split()[1:]])
        if line and line[0].isdigit() else line for line in dump.read_text().splitlines()))
    log = directory / "ngspice.log"; log.write_text("No. of Data Rows : 81\n")
    views = {role: {"path": str(path), "sha256": capture.bound.sha(path)} for role, path in
        (("deck", deck), ("netlist", netlist), ("testbench", template), ("spec", spec_path),
         ("topology", topology_path), ("settings", setting_path))}
    views.update(capture.bound.consumed_input_views(project, deck))
    record = {"status": "PASS", "project": str(project), "settings": settings, "native_inputs": views,
        "image": "test-image", "clock": list(clock), "incremental_decode": declaration,
        "decoded": capture.decode_capture(dump, clock, declaration, settings),
        "capture": {"path": str(dump), "sha256": capture.capture_sha(dump)},
        "executions": [{"returncode": 0, "log": str(log), "log_sha256": capture.bound.sha(log)}]}
    assert capture.validate_point(record)[0], record["decoded"]
    (directory / "result.json").write_text(json.dumps(record))
    return project, common_path, directory, record


def test_raw_and_lossless_gzip_points_remain_valid_but_wrong_raw_digest_refuses(tmp_path):
    _project, _settings, directory, record = _method_record(tmp_path)
    record["capture"] = capture.compress_capture(directory / "conversion.dat")
    assert capture.validate_point(record)[0]
    record["capture"]["raw_sha256"] = "0" * 64
    current, why = capture.validate_point(record)
    assert not current and "original raw bytes" in why


def test_derived_decoder_replay_preserves_original_receipt_and_ignores_old_decoded_values(tmp_path):
    _project, _settings, directory, record = _method_record(tmp_path)
    point = directory / "result.json"
    record["decoded"] = {"conversions": [{"decoded": 99, "clock_slots": 3}], "alignment": "old_rising_edge_rule"}
    point.write_text(json.dumps(record))
    original = point.read_bytes()
    replay = capture.write_decoder_replay(record, point)
    assert point.read_bytes() == original
    assert replay["decoded"]["conversions"][0]["clock_slots"] == 3
    assert replay["decoded"]["conversions"][0]["decoded"] != 99
    receipt = json.loads(Path(replay["receipt"]["path"]).read_text())
    assert receipt["original_point"]["sha256"] == capture.bound.sha(point)
    assert receipt["decoder"]["sha256"] == capture.DECODER_SOURCE_SHA256
    assert receipt["capture"] == record["capture"]
    assert receipt["native_inputs"] == record["native_inputs"]
    # A replay cannot be attached to a different original receipt.
    record["settings"]["held_input_v"] = .8
    with pytest.raises(ValueError, match="original native receipt"):
        capture.write_decoder_replay(record, point)


def test_native_failure_cannot_be_repaired_by_replaying_cached_decoded_values(tmp_path):
    _project, _settings, directory, record = _method_record(tmp_path)
    log = directory / "ngspice.log"; log.write_text(";;RESIDUAL_FAIL native current\n")
    record["executions"][0]["log_sha256"] = capture.bound.sha(log)
    record["decoded"]["conversions"][0]["decoded"] = 99
    point = directory / "result.json"; point.write_text(json.dumps(record))
    before = point.read_bytes()
    with pytest.raises(ValueError, match="failure"):
        capture.write_decoder_replay(record, point)
    assert capture.native_execution_failure(record)
    assert point.read_bytes() == before


def test_native_method_pass_does_not_manufacture_enob(tmp_path):
    project, settings, directory, _record = _method_record(tmp_path)
    entry = {"kind": "incremental_capture", "settings": str(settings), "result": str(directory.parent / "score.json")}
    def forbidden(*args):
        pytest.fail("valid retained native control should be reused")
    row = capture.consume_study(project, "converter", entry,
        {"container": "test-container", "image": "test-image", "cpus": 2, "workers": 2}, forbidden, "A06")
    assert row["status"] == "PASS", row
    assert row["definitions"] == ["enob"] and row["analyses"] == [".tran"]
    assert row["measurements"] == {}
    assert row["native_inputs"]["netlist"]["path"].endswith("converter.sp")


def test_method_consumer_refuses_changed_actual_dut_even_with_retained_pass(tmp_path):
    project, settings, directory, record = _method_record(tmp_path)
    netlist = Path(record["native_inputs"]["netlist"]["path"])
    netlist.write_text(netlist.read_text().replace("1k", "2k"))
    calls = []
    row = capture.consume_study(project, "converter",
        {"kind": "incremental_capture", "settings": str(settings), "result": str(directory.parent / "score.json")},
        {"container": "test-container", "image": "test-image", "cpus": 2, "workers": 2},
        lambda *args: calls.append(args) or {"returncode": 2}, "A06")
    assert row["status"] == "NOT_MEASURED" and row["measurements"] == {}
    assert calls and "--limit-points" in calls[0][1]  # only the control can be requested


def test_a07_requests_full_series_only_after_valid_control_and_keeps_missing_score_unmeasured(tmp_path):
    project, settings, directory, _record = _method_record(tmp_path)
    calls = []
    row = capture.consume_study(project, "converter",
        {"kind": "incremental_capture", "settings": str(settings), "result": str(directory.parent / "score.json")},
        {"container": "test-container", "image": "test-image", "cpus": 2, "workers": 2},
        lambda *args: calls.append(args) or {"returncode": 2}, "A07")
    assert row["status"] == "NOT_MEASURED" and row["measurements"] == {}
    assert len(calls) == 1 and "--limit-points" not in calls[0][1]


def test_typed_switch_endpoints_derive_every_branch_and_native_probes(tmp_path):
    source, spec, topology = _template(tmp_path)
    text, _clock, declaration = capture.prepare_deck(source, spec, topology,
        {'reset_node': 'xdut.reset_b', 'held_input_v': .8}, tmp_path)
    timing = declaration['native_timing']
    assert {g['capacitor'] for g in timing['groups']} == {'sample1', 'feedback1', 'sample2', 'feedback2'}
    assert len(timing['columns']) == 2
    assert all(column in text.split('wrdata ', 1)[1] for column in timing['columns'])
    assert {g['n_switch'] for g in timing['groups']} == {
        'mn_sample1_transfer', 'mn_feedback1_transfer', 'mn_sample2_transfer', 'mn_feedback2_transfer'}


def test_actual_mapped_gate_inventory_supports_extracted_hierarchy(tmp_path):
    _source, _spec, topology = _template(tmp_path)
    before = capture._transfer_timing(topology, 'xdut.reset_b')
    mapping = {g[polarity + '_switch']: 'xdut.physical.' + g[polarity + '_switch'] + '_gate#'
               for g in before['groups'] for polarity in ('n', 'p')}
    after = capture._transfer_timing(topology, 'xdut.physical.reset_fragment#', mapping)
    assert len(after['columns']) == 8
    assert all('xdut.physical.' in column for column in after['columns'])
    with pytest.raises(ValueError, match='actual native transfer gate node is absent'):
        capture._transfer_timing(topology, 'xdut.physical.reset_fragment#', dict(list(mapping.items())[1:]))
    with pytest.raises(ValueError, match='remapped reset requires'):
        capture._transfer_timing(topology, 'xdut.physical.reset_fragment#')


def test_wrong_source_switch_endpoint_cannot_vouch_for_a_phase_probe(tmp_path):
    _source, _spec, topology = _template(tmp_path)
    switch = next(d for d in topology['devices'] if d['name'] == 'mp_sample1_transfer')
    switch['nets'][2] = 'unrelated_summing_node'
    with pytest.raises(ValueError, match='actual nMOS/pMOS switch pair'):
        capture._transfer_timing(topology, 'xdut.reset_b')


def test_disagreeing_branch_pulses_cannot_supply_one_cascade_update(tmp_path):
    path = _dump(tmp_path / 'wave.dat')
    declaration = _declaration()
    declaration['native_timing']['columns'] += ['v(xdut.extra_n)', 'v(xdut.extra_p)']
    declaration['native_timing']['groups'].append({'capacitor': 'other_branch',
        'n_gate': 'v(xdut.extra_n)', 'p_gate': 'v(xdut.extra_p)'})
    lines = path.read_text().splitlines()
    lines[0] += ' v(xdut.extra_n) v(xdut.extra_p)'
    for index in range(1, len(lines)):
        fields = lines[index].split(); when = float(fields[0])
        extra = ['0', '1.2'] if 3.5 <= when <= 4 else fields[4:]
        lines[index] += ' ' + ' '.join(extra)
    path.write_text('\n'.join(lines))
    assert not capture.decode_capture(path, (1, 1, 1.2), declaration, {})['conversions']
