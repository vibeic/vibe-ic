"""MC wrapper relocation controls; no native yield is claimed by these fakes."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import analog_mc_yield_run as mc
from _hostpaths import require_repo


def test_omitted_seam_preserves_resolver_probe_launch_and_return_shape(monkeypatch):
    seen = {"probe": [], "launch": []}
    monkeypatch.setattr(mc._ars, "_resolve_ngspice",
                        lambda container: "/resolved/ngspice")

    def probe(container, binary):
        seen["probe"].append((container, binary))
        return False

    def launch(container, command, timeout):
        seen["launch"].append((container, command, timeout))
        return SimpleNamespace(returncode=0, stdout="MEAS vout=1.2\n")

    monkeypatch.setattr(mc._ars, "_supports_json_measure", probe)
    monkeypatch.setattr(mc._ars, "_docker", launch)
    result = mc._ars._run_ngspice("ordinary-container", "/project/deck.sp")
    assert len(result) == 4
    ok, values, _log, state = result
    assert ok and values["vout"] == 1.2
    assert seen["probe"] == [("ordinary-container", "/resolved/ngspice")]
    assert seen["launch"] == [(
        "ordinary-container", "/resolved/ngspice -b /project/deck.sp 2>&1",
        state["deadline_s"])]
    assert "native_binary" not in state
    assert "argv" not in state


def test_selected_native_binary_reaches_capability_probe_launch_and_is_hash_bound(
        monkeypatch):
    binary = "/runtime-only/tools/ngspice"
    remote_hash = "a" * 64
    deck = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                        "programs", "calibration",
                        "ngspice47_cal_meas_rows.sp")
    assert not Path(binary).exists()
    commands = []
    monkeypatch.setattr(
        mc._ars, "_resolve_ngspice",
        lambda *args: pytest.fail("explicit selection must bypass resolution"))

    def transport(container, command, timeout=None):
        commands.append((container, command, timeout))
        if command.startswith("test -x "):
            return SimpleNamespace(
                returncode=0, stdout=f"{remote_hash}  {binary}\n")
        if command.startswith("sha256sum "):
            return SimpleNamespace(
                returncode=0, stdout=f"{remote_hash}  {binary}\n")
        if "--json-measure=/dev/null" in command:
            assert binary in command
            return SimpleNamespace(
                returncode=0, stdout="unrecognized option --json-measure\n")
        assert binary in command and " -b " in command
        return SimpleNamespace(returncode=0, stdout="MEAS vout=1.2\n")

    monkeypatch.setattr(mc._ars, "_docker", transport)
    ok, values, _log, state = mc._ars._run_ngspice(
        "container", str(deck), cwd="/project",
        ngspice_bin=binary)
    assert binary in commands[1][1] and "--json-measure=/dev/null" in commands[1][1]
    assert binary in commands[2][1] and " -b " in commands[2][1]
    assert state["argv"] == [binary, "-b", str(deck)]
    assert ok and values["vout"] == 1.2
    assert state["native_binary"] == {
        "path": binary, "sha256": remote_hash, "sha256_after": remote_hash}


def test_selected_container_binary_mutation_cannot_keep_measurements(monkeypatch):
    binary = "/runtime-only/tools/ngspice-mutable"
    before, after = "b" * 64, "c" * 64
    mutated = False

    def transport(container, command, timeout=None):
        nonlocal mutated
        if command.startswith("test -x "):
            return SimpleNamespace(
                returncode=0, stdout=f"{before}  {binary}\n")
        if command.startswith("sha256sum "):
            digest = after if mutated else before
            return SimpleNamespace(
                returncode=0, stdout=f"{digest}  {binary}\n")
        if "--json-measure=/dev/null" in command:
            return SimpleNamespace(
                returncode=0, stdout="unrecognized option --json-measure\n")
        mutated = True
        return SimpleNamespace(returncode=0, stdout="MEAS vout=1.2\n")

    monkeypatch.setattr(mc._ars, "_docker", transport)
    ok, values, _log, state = mc._ars._run_ngspice(
        "container", "/project/deck.sp", ngspice_bin=binary)
    assert not ok and values["vout"] is None
    assert state["changed_inputs"] == ["native_binary"]
    assert state["native_binary"] == {
        "path": binary, "sha256": before, "sha256_after": after}


def test_unusable_selected_container_binary_refuses_before_launch(monkeypatch):
    binary = "/runtime-only/tools/not-executable"
    commands = []

    def transport(container, command, timeout=None):
        commands.append(command)
        return SimpleNamespace(returncode=126, stdout="")

    monkeypatch.setattr(
        mc._ars, "_docker", transport)
    with pytest.raises(ValueError, match="not executable or hashable in container"):
        mc._ars._run_ngspice(
            "container", "/project/deck.sp", ngspice_bin=binary)
    assert commands == [f"test -x {binary} && sha256sum {binary} 2>/dev/null"]


def test_selected_native_binary_requires_absolute_container_path(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        mc, "_run_block",
        lambda *args, **kwargs: pytest.fail("do not launch invalid selection"))
    result = mc.run_block(
        tmp_path, "cell", "container", "process", 2,
        ngspice_bin="relative-engine")
    assert result["verdict"] == "NOT_MEASURED"
    assert result["rc"] == 2 and result["mc_runs"] == 0


def test_host_only_file_cannot_stand_in_for_container_executable(
        tmp_path, monkeypatch):
    host_only = tmp_path / "host-only-engine"
    host_only.write_bytes(b"host bytes do not establish container identity")
    monkeypatch.setattr(
        mc._ars, "_docker",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))
    monkeypatch.setattr(
        mc, "_run_block",
        lambda *args, **kwargs: pytest.fail("container refusal must precede MC"))
    result = mc.run_block(
        tmp_path, "cell", "container", "process", 2,
        ngspice_bin=str(host_only))
    assert host_only.is_file()
    assert result["verdict"] == "NOT_MEASURED"
    assert "not executable or hashable in container" in result["reason"]


def test_mc_forwards_selected_binary_for_every_sample_and_retains_argv(
        tmp_path, monkeypatch):
    _case(tmp_path, monkeypatch)
    binary = "/runtime-only/tools/ngspice"
    remote_hash = "d" * 64
    seen = []
    monkeypatch.setattr(
        mc._ars, "_selected_ngspice_binary",
        lambda container, selected: {"path": selected, "sha256": remote_hash})
    monkeypatch.setattr(
        mc._ars, "_container_binary_sha256",
        lambda container, selected: remote_hash)

    def execute(container, deck, cwd=None, ngspice_bin=None):
        seen.append(ngspice_bin)
        value = 1.17 + 0.01 * len(seen)
        return True, {"vout": value}, f"MEAS vout={value}\n", {
            "partial": False, "warnings": [], "rc": 0,
            "argv": [ngspice_bin, "-b", deck], "cwd": cwd}

    monkeypatch.setattr(mc._ars, "_run_ngspice", execute)
    result = mc.run_block(
        tmp_path, "cell_alpha", "container", "process_alpha", 2,
        ngspice_bin=binary)
    assert result["verdict"] == "PASS"
    assert seen == [binary] * 2
    assert len(result["mc_executions"]) == 2
    assert all(row["argv"][0] == binary
               for row in result["mc_executions"])
    assert (result["mc_native_binary"]["sha256"]
            == result["mc_native_binary"]["sha256_after"])


@pytest.mark.parametrize("native_failure", [False, True])
def test_consumed_input_drift_is_incomplete_and_preserves_native_failure(
        tmp_path, monkeypatch, native_failure):
    _case(tmp_path, monkeypatch)
    binary = "/runtime-only/tools/ngspice"
    remote_hash = "e" * 64
    monkeypatch.setattr(
        mc._ars, "_selected_ngspice_binary",
        lambda container, selected: {"path": selected, "sha256": remote_hash})
    monkeypatch.setattr(
        mc._ars, "_container_binary_sha256",
        lambda container, selected: remote_hash)

    def execute(container, deck, cwd=None, ngspice_bin=None):
        return False, {"vout": None}, (
            "Error: analysis aborted\n" if native_failure
            else "native run completed\n"), {
                "partial": True, "warnings": [],
                "rc": 1 if native_failure else 0,
                "changed_inputs": ["deck"],
                "argv": [ngspice_bin, "-b", deck]}

    monkeypatch.setattr(mc._ars, "_run_ngspice", execute)
    result = mc.run_block(
        tmp_path, "cell_alpha", "container", "process_alpha", 2,
        ngspice_bin=binary)
    assert result["verdict"] == ("FAIL" if native_failure else "NOT_MEASURED")
    assert result["mc_native_failed"] == (2 if native_failure else 0)
    assert len(result["mc_input_drift_logs"]) == 2
    assert result["mc_yield_pct"] is None


def _case(tmp_path, monkeypatch):
    directory = tmp_path / 'phase3/analog/cell_alpha'
    directory.mkdir(parents=True)
    (directory / 'cell_alpha.sp').write_text(
        '.subckt cell_alpha supply out\n'
        'mdevice out supply 0 0 process_alpha_n w=1u l=1u\n.ends cell_alpha\n')
    (directory / 'tb_cell_alpha.sp').write_text(
        '* declared neutral circuit\n.include cell_alpha.sp\n'
        'vsource supply 0 1.2\nxdut supply out cell_alpha\n'
        '.control\nop\nlet vo = v(out)\necho "MEAS vout=" $&vo\n.endc\n.end\n')
    (directory / 'spec.json').write_text(json.dumps({
        'specs': [{'name': 'vout', 'min': 1.1, 'max': 1.3}]}))
    monkeypatch.setattr(mc, '_resolve_native_mc', lambda project, container: None)
    monkeypatch.setitem(mc._MC_SECTION, 'process_alpha', 'statistical')
    monkeypatch.setitem(mc._ars.PDK_LIB, 'process_alpha', '/models/process_alpha.lib')
    monkeypatch.setattr(mc._ars, '_ngspice_available', lambda container: True)
    monkeypatch.setattr(mc._dr, 'resolve_host_root', lambda project, container: tmp_path)
    # A nonidentity container mapping distinguishes a host cwd from the cwd
    # the actual simulator can resolve. No directory-name guess is accepted.
    monkeypatch.setattr(mc._ars, '_container_path',
                        lambda container, root, path: '/mounted/' + str(Path(path).relative_to(root)))
    return directory


def test_mc_relative_dut_include_resolves_from_original_deck_directory(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    seen = []

    def simulator(container, deck, cwd=None):
        seen.append(cwd)
        if cwd != '/mounted/phase3/analog/cell_alpha':
            return False, {}, 'Error: Could not find include file cell_alpha.sp\n'
        assert (directory / 'cell_alpha.sp').is_file()
        value = 1.17 if len(seen) == 1 else 1.18
        return True, {'vout': value}, f'MEAS vout= {value}\n'

    monkeypatch.setattr(mc._ars, '_run_ngspice', simulator)
    source = (directory / 'tb_cell_alpha.sp').read_bytes()
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'PASS', report
    assert seen == ['/mounted/phase3/analog/cell_alpha'] * 2
    assert report['spec_yield']['vout']['runs_scored'] == 2
    assert (directory / 'tb_cell_alpha.sp').read_bytes() == source
    assert '.include cell_alpha.sp' in (directory / 'mc_runs/mc_0001.sp').read_text()


def test_all_native_failures_report_the_failed_execution_not_a_measurement_gap(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (False, {}, 'Error: Could not find include file missing_model.lib\n',
                         {'partial': True, 'warnings': ['native exited 1'], 'rc': 1}))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'FAIL', report
    assert report['rc'] == 1
    assert report['mc_native_failed'] == 2
    assert 'native' in report['reason'].lower()
    assert report['mc_failure_logs'] == [
        'phase3/analog/cell_alpha/mc_runs/mc_0001.log',
        'phase3/analog/cell_alpha/mc_runs/mc_0002.log']
    assert 'missing_model.lib' in (directory / 'mc_runs/mc_0001.log').read_text()
    assert 'mc_yield_pct' not in report
    assert not (directory / 'corner_results.json').is_file()


def test_no_native_spread_remains_unscoreable_after_context_repair(tmp_path, monkeypatch):
    _case(tmp_path, monkeypatch)
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, {'vout': 1.2}, 'MEAS vout=1.2\n'))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'UNSCOREABLE'
    assert report['spec_yield']['vout']['degenerate'] is True
    assert 'mc_yield_pct' not in report


def _native_case(tmp_path, monkeypatch, *, disabled=False, fake_stat=False):
    directory = _case(tmp_path, monkeypatch)
    models = tmp_path / 'input/pdk/models'
    models.mkdir(parents=True)
    parameters = models / 'stat_parameters.lib'
    parameters.write_text('.param delta_v=gauss(1, 0.01, 1)\n')
    model = models / 'device_corners.lib'
    nominal = '.lib fet_typ\n.model process_alpha_n nmos level=1\n.endl fet_typ\n'
    if disabled:
        statistical = ('.lib fet_typ_mismatch\n.subckt process_alpha_n d g s b mm_ok=0\n'
                       'mdevice d g s b inner w=\'agauss(1u,1n,(mm_ok != 1 ? 0 : 1))\'\n'
                       '.ends\n.endl fet_typ_mismatch\n')
    else:
        statistical = ('.lib fet_typ_stat\n'
                       + ('* only a comment mentions gauss(1,0.01,1)\n' if fake_stat
                          else '.include stat_parameters.lib\n')
                       + '.model process_alpha_n nmos level=1 vto=delta_v\n.endl fet_typ_stat\n')
    model.write_text(nominal + statistical)
    passive = models / 'passive_corners.lib'
    passive.write_text('.lib passive_typ\n.param passive_value=1\n.endl\n'
                       '.lib passive_stat\n.include stat_parameters.lib\n.endl\n')
    dut = directory / 'cell_alpha.sp'
    dut.write_text('.lib ../../../input/pdk/models/device_corners.lib fet_typ\n'
                   '.lib ../../../input/pdk/models/passive_corners.lib passive_typ\n'
                   + dut.read_text())
    leaf = models / 'device_mod_mismatch.lib'
    leaf.write_text('.subckt process_alpha_n d g s b mm_ok=0\n'
                    'mdevice d g s b inner w=\'agauss(1u,1n,(mm_ok != 1 ? 0 : 1))\'\n.ends\n')
    monkeypatch.setattr(mc, '_resolve_native_mc', lambda project, container: {
        'mc_lib': str(leaf), 'mc_section': None, 'source': 'project_custom_pdk'})
    return directory, model, passive


def test_native_mc_uses_real_statistical_entry_sections_in_copied_dut(tmp_path, monkeypatch):
    directory, model, passive = _native_case(tmp_path, monkeypatch)
    originals = {path: path.read_bytes() for path in (model, passive, directory / 'cell_alpha.sp',
                                                     directory / 'tb_cell_alpha.sp')}
    seen = []

    def simulate(container, deck, cwd=None):
        seen.append(deck)
        return True, {'vout': 1.17 if len(seen) == 1 else 1.18}, 'MEAS vout=1.17\n'

    monkeypatch.setattr(mc._ars, '_run_ngspice', simulate)
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'PASS', report
    bindings = report['mc_model_bindings']
    assert {item['section'] for item in bindings} == {'fet_typ_stat', 'passive_stat'}
    assert {item['variation_scope'] for item in bindings} == {'foundry_process_statistics'}
    assert all(item['model_inputs'] for item in bindings)
    wrapper = (directory / 'mc_runs/mc_0001.sp').read_text()
    assert 'device_mod_mismatch.lib' not in wrapper
    copied = '\n'.join(path.read_text() for path in (directory / 'mc_runs/inputs').glob('*'))
    assert 'device_corners.lib" fet_typ_stat' in copied
    assert 'passive_corners.lib" passive_stat' in copied
    assert 'device_corners.lib" fet_typ\n' not in copied
    assert all(path.read_bytes() == before for path, before in originals.items())


def test_native_mismatch_with_disabled_device_switch_is_refused_before_samples(tmp_path, monkeypatch):
    _native_case(tmp_path, monkeypatch, disabled=True)
    calls = []
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs: calls.append(args))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'UNSCOREABLE', report
    assert 'mm_ok' in report['reason']
    assert report['mc_runs'] == 0
    assert calls == []
    assert 'mc_yield_pct' not in report


def test_statistical_section_name_without_actual_distribution_is_not_a_model(tmp_path, monkeypatch):
    _native_case(tmp_path, monkeypatch, fake_stat=True)
    calls = []
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs: calls.append(args))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'UNSCOREABLE', report
    assert 'no foundry random distribution' in report['reason']
    assert calls == []


def test_repeated_mc_attempt_preserves_original_samples_and_native_logs(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    values = iter((1.17, 1.18, 1.19, 1.20))
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, {'vout': next(values)}, 'MEAS vout=1.17\n'))
    original = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    kept = {path: path.read_bytes() for path in (directory / 'mc_runs').glob('mc_*.*')}
    repeated = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert original['verdict'] == repeated['verdict'] == 'PASS'
    assert repeated['mc_log_dir'] != original['mc_log_dir']
    assert all(path.read_bytes() == before for path, before in kept.items())


def _performance_source(directory):
    (directory / 'spec.json').write_text(json.dumps({'specs': [
        {'name': 'vout', 'min': 1.1, 'max': 1.3},
        {'name': 'dropout', 'max': 0.5},
        {'name': 'iq', 'max': 50},
        {'name': 'psrr', 'min': 40},
        {'name': 'vin', 'min': 1.6, 'max': 2},
        {'name': 'iout', 'min': 0.1, 'max': 1},
    ]}))


def test_partial_mc_output_coverage_preserves_vout_but_cannot_report_full_yield(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    _performance_source(directory)
    values = iter((1.17, 1.18))
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, {'vout': next(values)}, 'MEAS vout measured\n'))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'NOT_MEASURED', report
    assert report['mc_yield_pct'] is None
    assert report['spec_yield']['vout'] == {
        'runs_scored': 2, 'distinct_values': 2, 'passed': 2, 'yield_pct': 100.0}
    assert report['mc_source_coverage']['required'] == ['dropout', 'iq', 'psrr', 'vout']
    assert report['mc_source_coverage']['missing'] == ['dropout', 'iq', 'psrr']
    assert 'vin' not in report['mc_source_coverage']['missing']
    saved = json.loads((directory / 'corner_results.json').read_text())
    assert saved['mc_yield_pct'] is None
    assert saved['mc_verdict'] == 'NOT_MEASURED'


def test_complete_source_output_coverage_scores_without_measuring_input_conditions(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    _performance_source(directory)
    samples = iter(({'vout': 1.17, 'dropout': 0.1, 'iq': 10, 'psrr': 41},
                    {'vout': 1.18, 'dropout': 0.2, 'iq': 11, 'psrr': 42}))
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, next(samples), 'MEAS source outputs measured\n'))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'PASS', report
    assert report['mc_yield_pct'] == 100.0
    assert report['spec_yield']['vin']['runs_scored'] == 0
    assert report['spec_yield']['iout']['runs_scored'] == 0


def test_real_output_failure_keeps_precedence_over_missing_other_outputs(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    _performance_source(directory)
    values = iter((1.6, 1.7))
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, {'vout': next(values)}, 'MEAS vout measured\n'))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'FAIL', report
    assert report['mc_yield_pct'] is None
    assert report['spec_yield']['vout']['yield_pct'] == 0
    assert report['mc_source_coverage']['missing'] == ['dropout', 'iq', 'psrr']


def test_required_output_missing_from_one_sample_is_incomplete_even_with_finite_yield(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    samples = iter(({'vout': 1.17}, {'vout': 1.18}, {}))
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, next(samples), 'native batch completed\n'))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 3)
    assert report['verdict'] == 'NOT_MEASURED', report
    assert report['spec_yield']['vout']['yield_pct'] == 100.0
    assert report['mc_source_coverage']['missing'] == ['vout']
    assert report['mc_yield_pct'] is None


def test_native_success_without_outputs_clears_stale_aggregate_yield(tmp_path, monkeypatch):
    directory = _case(tmp_path, monkeypatch)
    (directory / 'corner_results.json').write_text(json.dumps({'mc_yield_pct': 100}))
    monkeypatch.setattr(mc._ars, '_run_ngspice', lambda *args, **kwargs:
                        (True, {}, 'native batch completed without measure values\n'))
    report = mc.run_block(tmp_path, 'cell_alpha', 'native_container', 'process_alpha', 2)
    assert report['verdict'] == 'NOT_MEASURED', report
    assert report['mc_yield_pct'] is None
    assert report['mc_source_coverage']['missing'] == ['vout']
    saved = json.loads((directory / 'corner_results.json').read_text())
    assert saved['mc_yield_pct'] is None
    assert saved['mc_verdict'] == 'NOT_MEASURED'
