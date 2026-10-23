"""Step27 current-subject controls, including logical/physical identity drift.

Transport substitution is SOURCE_FIXTURE_ONLY and provides no native credit.
"""
import ast
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace
import pytest
import phase3_one_shot_runner as R
import librelane_signoff as LS
import si_crosstalk_check as SG
from test_default_current_power import project, pdk, put, write
from test_default_backend_composition import ReachedFollowingRow
from test_librelane_contract import local_image


def fake_windows(monkeypatch, p):
    def run(project, image, mounts, script, log, **kwargs):
        data = {pin: {'arr_rise_min': 1.0, 'arr_rise_max': 1.2, 'arr_fall_min': 1.0,
                'arr_fall_max': 1.2, 'slew_rise_max': 0.1, 'slew_fall_max': 0.1,
                'slack_max': 4.0} for pin in ('u0:Z', 'u1:Z', 'u2:A', 'z')}
        put(p / 'phase3/stage3/extracted/neutral_si_timing.json', {'pins': data})
        marker = re.search(r'VIBEIC_CURRENT_DONE [a-f0-9]+', script.read_text())[0]
        text = 'SOURCE_FIXTURE_ONLY\nSI_TIMING_JSON_EMIT_DONE\n' + marker + '\n'
        write(log, text)
        return SimpleNamespace(returncode=0, stdout=text, stderr='')
    monkeypatch.setattr(LS, 'run_sta_script', run)


@pytest.mark.parametrize("cached", [False, True], ids=["ORDINARY_FIRST_ADOPTION", "CURRENT_CACHE"])
def test_retained_bundle_si_caller_adopts_supported_current_subject(tmp_path, monkeypatch, cached):
    # This historical bundle owns the cache before continuing to its PDN
    # reader. Ordinary Default now dispatches the native rows independently;
    # keep this compatibility control explicit instead of expecting that old
    # following-row boundary from the new Default dispatcher.
    import execution_policy
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    p, folder, lib = project(tmp_path)
    write(R._pl.pnr_dir(p) / "neutral.def", "VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n")
    fake_windows(monkeypatch, p)
    report = p / "reports/phase3/si_crosstalk.rpt"
    if cached:
        assert R._emit_si_crosstalk_report(p, "neutral", R._pl.extracted_dir(p) / "neutral.spef",
                                          report.parent / "ir_drop.rpt", report, [], pdk(lib), "offline")
    producer = R._emit_si_crosstalk_report
    due = getattr(R, "_step27_current_si_due", None)
    observed = {"cache": "NO_CURRENT_BINDING_CHECK", "productions": 0}

    def admission(*args):
        needed = due(*args) if due else True
        observed["cache"] = "ADOPTION_REQUIRED" if needed else "CURRENT"
        return needed

    def emit(*args, **kwargs):
        observed["productions"] += 1
        return producer(*args, **kwargs)

    def following_row(*args, **kwargs):
        raise ReachedFollowingRow

    monkeypatch.setattr(R, "_step27_current_si_due", admission, raising=False)
    monkeypatch.setattr(R, "_emit_si_crosstalk_report", emit)
    monkeypatch.setattr(R, "_signoff_regen", lambda *args: False)
    monkeypatch.setattr(R, "_step25_native_density_due", lambda *args: False, raising=False)
    monkeypatch.setattr(R, "_emit_power_report", lambda *args, **kwargs: False)
    monkeypatch.setattr(R, "_docker_exec", lambda *args, **kwargs: (1, "", "outside scope"))
    monkeypatch.setattr(R, "_docker_exec_raw", lambda *args, **kwargs: (1, "", "outside scope"))
    monkeypatch.setattr(R, "_discover_container_corner_libs", lambda *args: [])
    monkeypatch.setattr(R, "_pnr_pdn_status", following_row)
    physical_pdk = R.PdkConfig("neutral", str(lib), "", "", None, "unitSite", None)
    with pytest.raises(ReachedFollowingRow):
        R.step_canonicalize_artefacts(p, "neutral", physical_pdk, "offline")
    assert observed["productions"] == (0 if cached else 1), observed
    assert observed["cache"] == ("CURRENT" if cached else "ADOPTION_REQUIRED"), observed
    assert SG.main([str(p), "--json", str(p / "si-row-gate.json")]) == 0
    assert "steps" not in json.loads((p / "phase3/librelane_switch.json").read_text())
    data = json.loads(report.with_suffix(".json").read_text())
    assert data["verdict"] == "ADVISORY_SCREEN_ONLY"


def test_accepted_si_binding_precedes_both_ordinary_formats():
    tree = ast.parse(inspect.getsource(SG.audit))
    bindings = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "si_binding"]
    assert len(bindings) == 1
    json_branch = next(n for n in tree.body[0].body if isinstance(n, ast.If)
                       and ast.unparse(n.test) == "jsn.exists()")
    assert bindings[0].lineno < json_branch.lineno


def physical_project(tmp_path, physical):
    """Seal neutral source inputs with distinct artifact and module names."""
    from test_default_current_power import seal
    import librelane_contract as LC
    p, folder, lib = project(tmp_path)
    nl = p / "phase3/stage3/pnr/neutral_pnr.v"
    spef = p / "phase3/stage3/extracted/neutral.spef"
    nl.write_text(nl.read_text().replace("module neutral(", f"module {physical}("))
    spef.write_text(spef.read_text().replace('*DESIGN "neutral"', f'*DESIGN "{physical}"'))
    original = p / "phase3/librelane/22-config/OpenROAD.STAPostPNR.json"
    config = json.loads(original.read_text())
    config["DESIGN_NAME"] = physical
    put(original, config)
    put(folder / "config.json", config)
    fp = json.loads((folder / "input_fingerprint.json").read_text())
    fp["config"] = LC.digest(original)
    fp["state_files"] = {path: LC.digest(Path(path)) for path in fp["state_files"]}
    seal(folder, fp)
    return p, folder, lib


def emit_physical_si(p, lib):
    report = p / "reports/phase3/si_crosstalk.rpt"
    notes = []
    produced = R._emit_si_crosstalk_report(
        p, "neutral", R._pl.extracted_dir(p) / "neutral.spef",
        report.parent / "ir_drop.rpt", report, notes, pdk(lib), "offline")
    return produced, notes


@pytest.mark.parametrize("physical", ["neutral", "package_shell", "boundary_die"])
def test_si_artifact_stem_and_validated_module_are_independent(tmp_path, monkeypatch, physical):
    import _opensta_current as C
    p, folder, lib = physical_project(tmp_path, physical)
    fake_windows(monkeypatch, p)
    produced, notes = emit_physical_si(p, lib)
    assert produced is True, notes
    assert SG.main([str(p)]) == 0
    receipt = C.si_binding(p)
    assert receipt["top"] == "neutral"
    assert receipt.get("physical_top", receipt["top"]) == physical
    assert f"link_design {physical}" in Path(receipt["execution"]["script"]).read_text()
    assert (p / "phase3/stage3/extracted/neutral_si_timing.json").is_file()
    assert R._step27_current_si_due(p) is False


@pytest.mark.parametrize("mutation", ["source_config", "runtime_config", "missing_config_binding",
    "config_identity", "netlist_identity", "spef_identity", "stale_netlist", "stale_spef"])
def test_si_split_identity_refuses_mismatch_or_stale_input(tmp_path, monkeypatch, mutation):
    import librelane_contract as LC
    from test_default_current_power import seal
    p, folder, lib = physical_project(tmp_path, "package_shell")
    fake_windows(monkeypatch, p)
    # Pre-producer identity mutations remain refused even when a source-fixture
    # tool receipt binds the mismatched material. This is not native evidence.
    fp = json.loads((folder / "input_fingerprint.json").read_text())
    if mutation in ("source_config", "runtime_config", "config_identity"):
        path = (p / "phase3/librelane/22-config/OpenROAD.STAPostPNR.json"
                if mutation == "source_config" else folder / "config.json")
        config = json.loads(path.read_text())
        config["DESIGN_NAME"] = "foreign_die"
        put(path, config)
        if mutation == "config_identity":
            seal(folder, fp)
    elif mutation == "missing_config_binding":
        path = folder / "vibeic_receipt.json"
        receipt = json.loads(path.read_text())
        del receipt["sha256"]["config.json"]
        put(path, receipt)
    else:
        path = (p / "phase3/stage3/pnr/neutral_pnr.v" if "netlist" in mutation
                else p / "phase3/stage3/extracted/neutral.spef")
        path.write_text(path.read_text().replace("package_shell", "foreign_die"))
        if mutation.endswith("identity"):
            fp["state_files"][str(path)] = LC.digest(path)
            seal(folder, fp)
    produced, notes = emit_physical_si(p, lib)
    assert produced is False, notes
    assert SG.main([str(p)]) == 1
    assert R._step27_current_si_due(p) is True
    assert not (p / "reports/phase3/si_crosstalk.current.json").exists()


@pytest.mark.parametrize("mutation", ["physical_top", "top", "source_config", "runtime_config",
                                     "netlist", "spef", "execution"])
def test_si_consumer_revalidates_split_identity(tmp_path, monkeypatch, mutation):
    p, folder, lib = physical_project(tmp_path, "package_shell")
    fake_windows(monkeypatch, p)
    produced, notes = emit_physical_si(p, lib)
    assert produced is True, notes
    assert SG.main([str(p)]) == 0
    if mutation in ("top", "physical_top"):
        receipt = p / "reports/phase3/si_crosstalk.current.json"
        doc = json.loads(receipt.read_text())
        doc[mutation] = "foreign_die"
        put(receipt, doc)
    elif mutation == "execution":
        (folder / "invocation.log").unlink()
    else:
        path = {"source_config": p / "phase3/librelane/22-config/OpenROAD.STAPostPNR.json",
                "runtime_config": folder / "config.json",
                "netlist": p / "phase3/stage3/pnr/neutral_pnr.v",
                "spef": p / "phase3/stage3/extracted/neutral.spef"}[mutation]
        path.write_text(path.read_text() + "\n ")
    assert SG.main([str(p)]) == 1
    assert R._step27_current_si_due(p) is True


def test_declared_si_row_consumes_split_identity_and_blocks_drift(tmp_path, monkeypatch):
    import yaml
    import flow_compliance_check as FC
    from _hostpaths import require_repo
    flow = yaml.safe_load(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
        'flow', 'phase1_phase2_phase3.yaml').read_text())
    row = next(row for row in flow['steps'] if str(row['id']) == '27')
    command = next(clause['program_exit_zero'] for clause in row['gate']['all_of']
                   if 'si_crosstalk_check' in clause.get('program_exit_zero', ''))
    p, folder, lib = physical_project(tmp_path, "package_shell")
    fake_windows(monkeypatch, p)
    produced, notes = emit_physical_si(p, lib)
    assert produced is True, notes
    result = FC._check_program_exit_zero(p, command)
    assert result[0] is True, result
    (folder / "invocation.log").unlink()
    result = FC._check_program_exit_zero(p, command)
    assert result[0] is False, result


def corner_project(tmp_path, physical="package_shell"):
    """Two receipt-bound SPEFs whose differences are legitimate corner data."""
    import librelane_contract as LC
    import librelane_postroute as LP
    from test_default_current_power import seal
    p, folder, lib = physical_project(tmp_path, physical)
    canonical = p / "phase3/stage3/extracted/neutral.spef"
    selected = write(canonical.parent / "spef_corners/neutral.max.spef",
                     canonical.read_text().replace("0.01", "0.02"))
    state_path = folder / "state_out.json"
    state = json.loads(state_path.read_text())
    state["spef"] = {"nom_*": str(canonical), "max_*": str(selected)}
    put(state_path, state)
    write(folder / "max_typ/sta.log",
          (folder / "nom_typ/sta.log").read_text().replace("nom_typ", "max_typ"))
    fp = json.loads((folder / "input_fingerprint.json").read_text())
    fp["state_files"][str(selected)] = LC.digest(selected)
    seal(folder, fp)
    record = json.loads((p / LP.STEP23_RECORD).read_text())
    record["sta_state_sha256"] = LC.digest(state_path)
    record["judgment"]["worst_setup"]["corner"] = "max_typ"
    put(p / LP.STEP23_RECORD, record)
    return p, folder, lib, selected


@pytest.mark.parametrize("physical", ["neutral", "package_shell"])
@pytest.mark.parametrize("caller_view", ["logical_alias", "selected_corner"])
def test_si_corner_spef_drives_screen_timing_and_consumer(tmp_path, monkeypatch, physical, caller_view):
    import _opensta_current as C
    p, folder, lib, selected = corner_project(tmp_path, physical)
    canonical = p / "phase3/stage3/extracted/neutral.spef"
    original = canonical.read_bytes()
    fake_windows(monkeypatch, p)
    report = p / "reports/phase3/si_crosstalk.rpt"
    notes = []
    supplied = canonical if caller_view == "logical_alias" else selected
    produced = R._emit_si_crosstalk_report(p, "neutral", supplied,
        report.parent / "ir_drop.rpt", report, notes, pdk(lib), "offline")
    assert produced is True, notes
    assert SG.main([str(p)]) == 0
    receipt = C.si_binding(p)
    bound = {r["role"]: r for r in receipt["inputs"]}
    assert receipt["tool_corner"] == "max_typ"
    assert bound["spef"]["path"] == str(selected)
    assert bound["spef"]["sha256"] == C.digest(selected)
    body = json.loads(report.with_suffix(".json").read_text())
    assert body["spef"] == str(selected)
    expected = R._si_coupling_metrics(*R._parse_spef_caps(selected.read_text()))
    assert body["max_crosstalk_noise"] == expected["max_crosstalk_noise_mv"]
    script = Path(receipt["execution"]["script"]).read_text()
    assert str(selected) in script and str(canonical) not in script
    assert canonical.read_bytes() == original
    assert R._step27_current_si_due(p) is False


@pytest.mark.parametrize("mutation", ["selected_bytes", "unbound_selected", "ambiguous_corner", "wrong_design"])
def test_si_corner_handoff_refuses_invalid_tool_view(tmp_path, monkeypatch, mutation):
    import librelane_contract as LC
    import librelane_postroute as LP
    from test_default_current_power import seal
    p, folder, lib, selected = corner_project(tmp_path)
    fp = json.loads((folder / "input_fingerprint.json").read_text())
    if mutation == "selected_bytes":
        selected.write_text(selected.read_text() + "\n ")
    elif mutation == "unbound_selected":
        del fp["state_files"][str(selected)]
        seal(folder, fp)
    elif mutation == "wrong_design":
        selected.write_text(selected.read_text().replace('"package_shell"', '"foreign_die"'))
        fp["state_files"][str(selected)] = LC.digest(selected)
        seal(folder, fp)
    else:
        path = folder / "state_out.json"
        state = json.loads(path.read_text())
        state["spef"]["*"] = state["spef"]["nom_*"]
        put(path, state)
        seal(folder, fp)
        record = json.loads((p / LP.STEP23_RECORD).read_text())
        record["sta_state_sha256"] = LC.digest(path)
        put(p / LP.STEP23_RECORD, record)
    fake_windows(monkeypatch, p)
    produced, notes = emit_physical_si(p, lib)
    assert produced is False, notes
    assert SG.main([str(p)]) == 1


@pytest.mark.parametrize("mutation", ["selected_bytes", "report_spef", "timing_spef", "receipt_corner", "step23_corner"])
def test_si_corner_consumer_rejects_stale_or_mixed_scene(tmp_path, monkeypatch, mutation):
    import _opensta_current as C
    import librelane_postroute as LP
    p, folder, lib, selected = corner_project(tmp_path)
    fake_windows(monkeypatch, p)
    produced, notes = emit_physical_si(p, lib)
    assert produced is True, notes
    assert SG.main([str(p)]) == 0
    report = p / "reports/phase3/si_crosstalk.json"
    current = report.with_suffix(".current.json")
    if mutation == "selected_bytes":
        selected.write_text(selected.read_text() + "\n ")
    elif mutation == "step23_corner":
        path = p / LP.STEP23_RECORD
        record = json.loads(path.read_text())
        record["judgment"]["worst_setup"]["corner"] = "nom_typ"
        put(path, record)
    elif mutation == "report_spef":
        doc = json.loads(report.read_text())
        doc["spef"] = str(p / "phase3/stage3/extracted/neutral.spef")
        put(report, doc)
        receipt = json.loads(current.read_text())
        for row in receipt["outputs"]:
            if row["role"] == "si_result":
                row["sha256"] = C.digest(report)
        put(current, receipt)
    else:
        path = (p / "phase3/stage3/extracted/neutral_si_timing.current.json"
                if mutation == "timing_spef" else current)
        receipt = json.loads(path.read_text())
        if mutation == "timing_spef":
            receipt["inputs"] = [C.file_record(p / "phase3/stage3/extracted/neutral.spef", "spef", p)
                                  if r["role"] == "spef" else r for r in receipt["inputs"]]
        else:
            receipt["tool_corner"] = "nom_typ"
        put(path, receipt)
    assert SG.main([str(p)]) == 1
    assert R._step27_current_si_due(p) is True


def _default_step27_transport(tmp_path, monkeypatch, *, case='good', timeout='omitted'):
    """Real row/owner/gates; only STA process transport is neutral software data."""
    import contextlib
    import io
    import execution_backend_producers as backend
    import execution_policy
    import flow_compliance_check as compliance
    import si_mcf_sta as mcf
    from test_default_si_spice_power import current_row_inputs
    p, folder, lib = project(tmp_path, voltage=5.0)
    current_row_inputs(p, monkeypatch)
    cfg = pdk(lib)
    monkeypatch.setattr(backend, '_parameters', lambda *_: (R, None, cfg, 'SOFTWARE_FIXTURE_ONLY'))
    monkeypatch.setattr(backend, '_step15_sdc', lambda *_: p / 'phase3/stage3/pnr/constraint.sdc')
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    if timeout != 'omitted':
        supplied = R._backend_parameter_values(p, cfg)
        monkeypatch.setattr(R, '_backend_parameter_values', lambda *_: {**supplied, 'timeout_s': timeout})
    data = {'pins': {pin: {'arr_rise_min': 1.0, 'arr_rise_max': 1.2,
        'arr_fall_min': 1.0, 'arr_fall_max': 1.2, 'slew_rise_max': 0.1,
        'slack_max': 1e-12 if case == 'delta_fail' else 4.0}
        for pin in ('u0:Z', 'u1:Z', 'u2:A', 'z')}}
    observed = {'mcf_timeouts': [], 'si_checks': 0, 'sta_calls': []}

    def windows_transport(project_path, image, mounts, script, log, **kwargs):
        put(p / 'phase3/stage3/extracted/neutral_si_timing.json', data)
        marker = re.search(r'VIBEIC_CURRENT_DONE [a-f0-9]+', script.read_text())[0]
        text = 'SOURCE_FIXTURE_ONLY\nSI_TIMING_JSON_EMIT_DONE\n' + marker + '\n'
        write(log, text)
        return SimpleNamespace(returncode=0, stdout=text, stderr='')

    def mcf_windows(*args):
        put(args[9], data)
        return data, 0

    def sta_transport(container, work, tag, *args):
        observed['sta_calls'].append(tag)
        rc = 1 if case == 'mcf_unmeasured' else 0
        text = 'SOURCE_FIXTURE_ONLY\nworst setup slack 1.0\nworst hold slack 1.0\n'
        write(work / f'si_mcf_sta_{tag}.rpt', text)
        return 1.0, 1.0, text, rc

    monkeypatch.setattr(LS, 'run_sta_script', windows_transport)
    monkeypatch.setattr(mcf, '_to_container_path', lambda value, *_: value)
    monkeypatch.setattr(mcf, '_run_windows', mcf_windows)
    monkeypatch.setattr(mcf, '_run_sta_slack', sta_transport)
    actual_mcf = mcf.run
    def mcf_observed(*args, **kwargs):
        observed['mcf_timeouts'].append(kwargs['timeout'])
        result = actual_mcf(*args, **kwargs)
        if case == 'mcf_bad_fold':
            # An actual recount must refuse a measured report whose bounded
            # SPEF no longer carries the fold the producer just computed.
            Path(result['corners']['setup']['bounded_spef']).write_text(
                Path(result['spef']).read_text())
        if case == 'missing_si_receipt':
            (p / 'reports/phase3/si_crosstalk.current.json').unlink(missing_ok=True)
        elif case == 'changed_timing':
            path = p / 'phase3/stage3/extracted/neutral_si_timing.json'
            path.write_text(path.read_text() + '\n ')
        return result
    monkeypatch.setattr(mcf, 'run', mcf_observed)
    actual_transport = compliance._watchdog.run_host_supervised
    def gate_transport(argv, **kwargs):
        if Path(argv[1]).name != 'si_crosstalk_check.py':
            return actual_transport(argv, **kwargs)
        observed['si_checks'] += 1
        stdout, stderr = io.StringIO(), io.StringIO()
        with monkeypatch.context() as transport_context:
            transport_context.chdir(kwargs['cwd'])
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = SG.main(argv[2:])
        return compliance._watchdog.SupervisedResult(
            rc=rc, out=stdout.getvalue(), err=stderr.getvalue(), outcome='natural')
    monkeypatch.setattr(compliance._watchdog, 'run_host_supervised', gate_transport)
    return p, cfg, observed


@pytest.mark.parametrize('case,expected', [('good', 'PASS'), ('delta_fail', 'FAIL'),
    ('missing_si_receipt', 'FAIL'), ('changed_timing', 'FAIL'), ('mcf_bad_fold', 'FAIL'), ('mcf_unmeasured', 'NOT_MEASURED')])
def test_default_row27_uses_the_complete_current_si_owner(tmp_path, monkeypatch, case, expected):
    import execution_adapters_backend as adapters
    import _opensta_current as current
    p, cfg, observed = _default_step27_transport(tmp_path, monkeypatch, case=case)
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    assert row.status == expected, row.detail
    assert observed['mcf_timeouts'] == [adapters.BACKEND_PARAMETER_DEFAULTS['timeout_s']]
    assert observed['sta_calls'] == ['nominal', 'mcf_setup', 'mcf_hold']
    assert observed['si_checks'] == (0 if case == 'mcf_unmeasured' else 1)
    receipt = json.loads((p / 'reports/phase3/default_steps/27/backend_result.json').read_text())
    assert receipt['verdict'] == expected
    report = json.loads((p / 'reports/phase3/si_crosstalk.json').read_text())
    assert report['timing_aware_advisory']['timing_json'].endswith('neutral_si_timing.json')
    assert report['timing_aware_advisory']['vdd_v'] == 5.0
    assert report['delta_delay']['vdd_v'] == 5.0
    assert report['max_crosstalk_noise'] == pytest.approx(10000 / 3, abs=0.01)
    assert json.loads((p / 'reports/phase3/si_mcf_sta.json').read_text())['vdd_v'] == 5.0
    if case in ('good', 'mcf_bad_fold', 'mcf_unmeasured', 'delta_fail'):
        assert current.si_binding(p)['step'] == '27'
    if case == 'good':
        assert SG.main([str(p)]) == 0
        assert report['delta_delay_verdict'] == 'PASS'
    elif case == 'delta_fail':
        assert report['delta_delay_verdict'] == 'FAIL'
        assert SG.main([str(p)]) == 1
        assert 'SI_DELTA_DELAY_FAIL' in (p / 'reports/phase2/gates/si_crosstalk.json').read_text()
    elif case == 'mcf_bad_fold':
        assert SG.main([str(p)]) == 0
        assert 'FOLD_NOT_APPLIED' in (p / 'reports/phase3/si_mcf_sta_check.json').read_text()
    elif case == 'mcf_unmeasured':
        assert SG.main([str(p)]) == 0
        assert not (p / 'reports/phase3/si_mcf_sta.rpt').exists()
    else:
        assert SG.main([str(p)]) == 1


def test_default_row27_missing_spef_does_not_start_native_or_mcf(tmp_path, monkeypatch):
    p, cfg, observed = _default_step27_transport(tmp_path, monkeypatch)
    (p / 'phase3/stage3/extracted/neutral.spef').unlink()
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    assert row.status == 'NOT_MEASURED', row.detail
    assert observed['mcf_timeouts'] == [] and observed['sta_calls'] == []
    assert not (p / 'reports/phase3/si_crosstalk.current.json').exists()


def test_default_row27_explicit_invalid_timeout_is_not_defaulted(tmp_path, monkeypatch):
    p, cfg, observed = _default_step27_transport(tmp_path, monkeypatch, timeout=None)
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    assert row.status == 'NOT_MEASURED'
    assert 'TypeError: int() argument' in row.detail
    assert observed['mcf_timeouts'] == []


def test_ultra_row27_keeps_the_existing_flat_producer(tmp_path, monkeypatch):
    import execution_backend_producers as backend
    import si_mcf_sta as mcf
    p, cfg, _ = _default_step27_transport(tmp_path, monkeypatch)
    calls = []
    def timing(project_path, top, config, container, spef, sdc, nl, out, notes, voltage):
        put(out, {'pins': {pin: {'arr_rise_min': 1.0, 'arr_rise_max': 1.2,
            'arr_fall_min': 1.0, 'arr_fall_max': 1.2, 'slew_rise_max': 0.1,
            'slack_max': 4.0} for pin in ('u0:Z', 'u1:Z', 'u2:A', 'z')}})
        calls.append('flat_timing')
        return True
    monkeypatch.setattr(R, '_emit_si_timing_json', timing)
    monkeypatch.setattr(R, '_emit_si_crosstalk_report', lambda *a, **k: pytest.fail('Ultra called the Default owner'))
    monkeypatch.setattr(mcf, 'run', lambda *a, **k: calls.append(('mcf', k['timeout'])))
    result = backend.produce_signoff(p, {'step_id': '27', 'top': 'neutral',
        'pdk_root': str(p / 'fixture_pdk'), 'image_id': 'SOURCE_FIXTURE_ONLY',
        'execution_mode': 'ultra', 'timeout_s': 73})
    assert result['verdict'] == 'PASS'
    assert calls == ['flat_timing', ('mcf', 73)]
    data = json.loads((p / 'reports/phase3/si_crosstalk.json').read_text())
    assert 'timing_json' in data and 'timing_aware_advisory' not in data


def test_complete_si_owner_does_not_invent_an_undeclared_voltage(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path, voltage=None)
    fake_windows(monkeypatch, p)
    report = p / 'reports/phase3/si_crosstalk.rpt'
    notes = []
    assert R._emit_si_crosstalk_report(p, 'neutral',
        p / 'phase3/stage3/extracted/neutral.spef', report.parent / 'ir_drop.rpt',
        report, notes, pdk=pdk(lib), container='SOFTWARE_FIXTURE_ONLY') is False
    assert 'CURRENT_SI_VOLTAGE_UNSTATED' in '; '.join(notes)
    assert not report.with_suffix('.current.json').exists()


def _local_step23_for_default_si(tmp_path, monkeypatch, local_image, *, case='good'):
    """Actual run_chain owns LOCAL root/receipt; only tool process is neutral."""
    import subprocess
    import librelane_contract as LC
    import librelane_postroute as LP
    p, cfg, observed = _default_step27_transport(tmp_path, monkeypatch, case=case)
    record_path = p / LP.STEP23_RECORD
    record = json.loads(record_path.read_text())
    previous = Path(record['sta_state']).parent
    before = json.loads((previous / 'state_in.json').read_text())
    before['odb'] = str(write(p / 'phase3/stage3/pnr/neutral.odb',
                              'SOURCE_FIXTURE_ONLY retained ODB process input\n'))
    before['def'] = str(write(p / 'phase3/stage3/pnr/neutral.def',
                              'VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n'))
    state = put(p / 'phase3/librelane/local-si-input.json', before)
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    switch = json.loads((p / 'phase3/librelane_switch.json').read_text())
    switch['image'] = local_image.image
    put(p / 'phase3/librelane_switch.json', switch)

    def external_edge(command, **kwargs):
        assert command[command.index('--pdk-root') + 1] == str(p / 'fixture_pdk')
        folder = Path(command[command.index('-o') + 1])
        before = json.loads(Path(command[command.index('-i') + 1]).read_text())
        put(folder / 'state_in.json', before)
        put(folder / 'state_out.json', before)
        put(folder / 'config.json', json.loads(config.read_text()))
        write(folder / 'nom_typ/sta.log', (previous / 'nom_typ/sta.log').read_text())
        write(folder / 'nom_typ/power.rpt', (previous / 'nom_typ/power.rpt').read_text())
        return subprocess.CompletedProcess(command, 0, 'SOURCE_FIXTURE_ONLY LOCAL STA edge', '')

    monkeypatch.setattr(LC, 'image_capability', lambda *a, **kw: {})
    monkeypatch.setattr(LC, 'openroad_home', lambda *a, **kw: None)
    monkeypatch.setattr(LC, 'run_container', external_edge)
    folder = LC.run_chain(p, local_image.image,
        [('OpenROAD.STAPostPNR', config, state)], lane='23', pdk_root='/pdk',
        mounts=[(p / 'fixture_pdk', '/pdk')])[0]
    record.update(sta_state=str(folder / 'state_out.json'),
                  sta_state_sha256=LC.digest(folder / 'state_out.json'))
    put(record_path, record)
    root = json.loads((folder / 'pdk_root.json').read_text())
    assert root['execution_route'] == 'LOCAL'
    assert root['cli_pdk_root'] == str(p / 'fixture_pdk')
    assert root['requested_pdk_root'] == '/pdk'
    assert root['mounts_under_it'] == [[str(p / 'fixture_pdk'), str(p / 'fixture_pdk')]]
    assert root['requested_mounts'] == [[str(p / 'fixture_pdk'), '/pdk']]
    assert LC.validate_step_receipt(folder, 'OpenROAD.STAPostPNR')['sha256']['pdk_root.json'] == LC.digest(folder / 'pdk_root.json')
    return p, cfg, observed, folder


@pytest.mark.parametrize('case,expected', [('good', 'PASS'), ('delta_fail', 'FAIL')])
def test_default_si_consumes_run_chain_local_pdk_root(tmp_path, monkeypatch, local_image, case, expected):
    import _opensta_current as current
    p, cfg, observed, folder = _local_step23_for_default_si(
        tmp_path, monkeypatch, local_image, case=case)
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    assert row.status == expected, row.detail
    subject, tool = current.tool_subject(p, 'neutral', coupling=True)
    assert tool['mounts'] == [(p / 'fixture_pdk', '/pdk')]
    assert subject['tool_image'] == local_image.image
    assert current.si_binding(p)['step'] == '27'
    assert SG.main([str(p)]) == (0 if case == 'good' else 1)
    assert observed['sta_calls'] == ['nominal', 'mcf_setup', 'mcf_hold']
    assert observed['si_checks'] == 1
    if case == 'delta_fail':
        assert 'SI_DELTA_DELAY_FAIL' in (p / 'reports/phase2/gates/si_crosstalk.json').read_text()


@pytest.mark.parametrize('damage', ['requested_root', 'requested_mounts', 'cli_root',
    'executed_mount', 'foreign_mapping', 'provenance_pdk', 'image', 'root_bytes'])
def test_default_si_local_pdk_mapping_or_receipt_damage_stays_unmeasured(
        tmp_path, monkeypatch, local_image, damage):
    import librelane_contract as LC
    p, cfg, observed, folder = _local_step23_for_default_si(tmp_path, monkeypatch, local_image)
    root_path = folder / 'pdk_root.json'
    root = json.loads(root_path.read_text())
    if damage == 'requested_root':
        root.pop('requested_pdk_root')
    elif damage == 'requested_mounts':
        root.pop('requested_mounts')
    elif damage == 'cli_root':
        root['cli_pdk_root'] = '/foreign-pdks'
    elif damage == 'executed_mount':
        root['mounts_under_it'][0][1] = '/foreign-pdks'
    elif damage == 'foreign_mapping':
        foreign = p / 'foreign-pdk'
        (foreign / 'neutral').mkdir(parents=True)
        root['cli_pdk_root'] = str(foreign)
        root['requested_mounts'] = [[str(foreign), '/pdk']]
        root['mounts_under_it'] = [[str(foreign), str(foreign)]]
    elif damage == 'provenance_pdk':
        path = p / 'phase3/librelane_pdk_root.provenance.json'
        doc = json.loads(path.read_text())
        doc['pdk'] = 'foreign'
        put(path, doc)
    elif damage == 'image':
        path = p / 'phase3/librelane_switch.json'
        doc = json.loads(path.read_text())
        doc['image'] = 'example.invalid/changed@sha256:' + 'b' * 64
        put(path, doc)
    put(root_path, root)
    if damage != 'root_bytes':
        # A producer-bound malformed mapping must also be refused. For the
        # root_bytes case leave the original receipt hash untouched instead.
        path = folder / 'vibeic_receipt.json'
        receipt = json.loads(path.read_text())
        receipt['sha256']['pdk_root.json'] = LC.digest(root_path)
        put(path, receipt)
    else:
        root_path.write_text(root_path.read_text() + '\n ')
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    assert row.status == 'NOT_MEASURED', row.detail
    assert observed['mcf_timeouts'] == [] and observed['sta_calls'] == []
    assert SG.main([str(p)]) == 1
    assert not (p / 'reports/phase3/si_crosstalk.current.json').exists()


def _default_mcf_physical_subject(tmp_path, monkeypatch, *, physical, case):
    """Real MCF Tcl/fold/report; neutral process edge checks the linked module."""
    import shlex
    import gate_utils
    import librelane_contract as LC
    import librelane_postroute as LP
    import si_mcf_sta as mcf
    from test_default_current_power import seal
    actual_windows, actual_slack = mcf._run_windows, mcf._run_sta_slack
    fixture_case = case if case in ('delta_fail', 'mcf_bad_fold') else 'good'
    p, cfg, observed = _default_step27_transport(tmp_path, monkeypatch, case=fixture_case)
    record_path = p / LP.STEP23_RECORD
    record = json.loads(record_path.read_text())
    folder = Path(record['sta_state']).parent
    nl = p / 'phase3/stage3/pnr/neutral_pnr.v'
    nl.write_text(nl.read_text().replace('module neutral(', f'module {physical}('))
    nominal = p / 'phase3/stage3/extracted/neutral.spef'
    nominal.write_text(nominal.read_text().replace('*DESIGN "neutral"', f'*DESIGN "{physical}"'))
    selected = write(nominal.parent / 'spef_corners/neutral.max.spef',
                     nominal.read_text().replace('0.01', '0.02'))
    primary = write(p / 'fixture_pdk/neutral/selected.lib',
                    'library(selected_max) { nom_voltage : 5.0; }\n')
    extra = write(p / 'fixture_pdk/neutral/selected_macro.lib',
                  'library(selected_macro) { nom_voltage : 5.0; }\n')
    guests = ['/pdk/neutral/selected.lib', '/pdk/neutral/selected_macro.lib']
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    raw = json.loads(config.read_text())
    raw.update(DESIGN_NAME=physical,
               CELL_LIBS={'nom_*': ['/pdk/neutral/neutral.lib'], 'max_*': guests})
    put(config, raw)
    put(folder / 'config.json', raw)
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    state['spef'] = {'nom_*': str(nominal), 'max_*': str(selected)}
    put(state_path, state)
    write(folder / 'max_typ/sta.log', 'SOURCE_FIXTURE_ONLY\n' + ''.join(
        f"Reading cell library for the 'max_typ' corner at '{guest}'\n" for guest in guests))
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = LC.digest(config)
    fp['state_files'] = {path: LC.digest(Path(path)) for path in fp['state_files']}
    fp['state_files'][str(selected)] = LC.digest(selected)
    for guest, lib in zip(guests, (primary, extra)):
        fp['config_files'][guest] = LC.digest(lib)
        fp['liberty_files'][guest] = LC.digest(lib)
    seal(folder, fp)
    record.update(sta_state_sha256=LC.digest(state_path),
                  judgment={'worst_setup': {'corner': 'max_typ'}})
    put(record_path, record)
    observed['mcf_processes'] = []

    def sta_edge(container, command, **kwargs):
        # The external tool edge is explicit neutral data. The real MCF
        # functions build every Tcl, parse rc/slacks, fold and publish outputs.
        words = shlex.split(command)
        script = Path(words[words.index('-exit') + 1])
        log = Path(words[words.index('>') + 1])
        text = script.read_text()
        linked = re.search(r'^link_design (\S+)$', text, re.M)[1]
        source = Path(re.search(r'^read_verilog (.+)$', text, re.M)[1])
        libraries = re.findall(r'^read_liberty (.+)$', text, re.M)
        sdc = re.search(r'^read_sdc (.+)$', text, re.M)[1]
        spef = re.search(r'^read_spef (.+)$', text, re.M)[1]
        observed['mcf_processes'].append({'script': str(script), 'top': linked,
            'netlist': str(source), 'libraries': libraries, 'sdc': sdc, 'spef': spef})
        modules = {span.name for span in gate_utils.find_modules(source.read_text())}
        if case == 'tool_error' or linked not in modules:
            message = f'Error: SOURCE_FIXTURE_ONLY {linked} is not a verilog module.\n'
            write(log, message)
            return 1, '', message
        if script.name == 'si_mcf_windows.tcl':
            output = Path(re.search(r'set _mcf_o \[open (.+) w\]', text)[1])
            put(output, {'design': linked, 'pins': {pin: {
                'arr_rise_min': 1.0, 'arr_rise_max': 1.2,
                'arr_fall_min': 1.0, 'arr_fall_max': 1.2,
                'slew_rise_max': 0.1, 'slew_fall_max': 0.1}
                for pin in ('u0:Z', 'u1:Z', 'u2:A', 'z')}})
            message = 'SOURCE_FIXTURE_ONLY\nMCF_WINDOW_EMIT_DONE\n'
        else:
            message = 'SOURCE_FIXTURE_ONLY\nworst slack max 1.0\nworst slack min 1.0\n'
        write(log, message)
        return 0, message, ''

    monkeypatch.setattr(mcf, '_run_windows', actual_windows)
    monkeypatch.setattr(mcf, '_run_sta_slack', actual_slack)
    monkeypatch.setattr(mcf, '_docker_exec', sta_edge)
    return p, cfg, observed, selected, primary, extra


@pytest.mark.parametrize('physical,case,expected', [
    ('package_shell', 'good', 'PASS'), ('neutral', 'good', 'PASS'),
    ('package_shell', 'delta_fail', 'FAIL'),
    ('package_shell', 'mcf_bad_fold', 'FAIL'),
    ('package_shell', 'tool_error', 'NOT_MEASURED')])
def test_default_mcf_uses_current_physical_subject_and_owns_all_outputs(
        tmp_path, monkeypatch, physical, case, expected):
    import time
    import _flow_yaml
    import _opensta_current as current
    import execution_backend_worker as worker
    import step_output_collector as versions
    import _sta_basis
    p, cfg, observed, selected, primary, extra = _default_mcf_physical_subject(
        tmp_path, monkeypatch, physical=physical, case=case)
    import execution_backend_producers as producers
    def historical_placement_sdc(*args):
        raise AssertionError('Default SI must use its current STA subject, not Step15 SDC')
    monkeypatch.setattr(producers, '_current_physical_sdc', historical_placement_sdc)
    began = time.time()
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    assert row.status == expected, row.detail
    assert current.si_binding(p).get('physical_top', 'neutral') == physical
    calls = observed['mcf_processes']
    assert len(calls) == 4
    assert all(c['top'] == physical for c in calls)
    assert all(c['libraries'] == [str(primary), str(extra)] for c in calls)
    assert all(c['netlist'] == str(p / 'phase3/stage3/pnr/neutral_pnr.v')
               and c['sdc'] == str(p / 'phase3/stage3/pnr/constraint.sdc') for c in calls)
    assert calls[0]['spef'] == calls[1]['spef'] == str(selected)
    report = json.loads((p / 'reports/phase3/si_mcf_sta.json').read_text())
    assert report['design_top'] == physical and report['spef'] == str(selected)
    assert report['vdd_v'] == 5.0
    definition = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '27')
    files, missing = worker.resolve_contract(p, definition['required_outputs'])
    output = p / 'reports/phase3/si_mcf_sta.rpt'
    if case == 'tool_error':
        assert report['verdict'] == 'ERROR'
        assert report['windows_rc'] == report['nominal']['sta_rc'] == 1
        assert all(c['sta_rc'] == 1 for c in report['corners'].values())
        assert not output.exists()
        assert missing == ['reports/phase3/si_mcf_sta.rpt']
        assert versions.latest_pass(p, '27') is None
    else:
        assert missing == []
        assert 'reports/phase3/si_mcf_sta.rpt' in files and output.stat().st_size > 0
        assert _sta_basis.declared_basis(output.read_text()) == 'POST_ROUTE'
        assert f'design_top: {physical}' in output.read_text()
        accepted = next(r for r in versions.current_acceptance(p, began) if r['id'] == '27')
        assert accepted['status'] == expected and accepted['canonical_pass'] == (expected == 'PASS')
        captured = {r['rel'] for r in accepted['outputs']}
        assert {'reports/phase3/si_mcf_sta.json', 'reports/phase3/si_mcf_sta.rpt'} <= captured
        if case == 'delta_fail':
            assert 'SI_DELTA_DELAY_FAIL' in (p / 'reports/phase2/gates/si_crosstalk.json').read_text()
        elif case == 'mcf_bad_fold':
            assert 'FOLD_NOT_APPLIED' in (p / 'reports/phase3/si_mcf_sta_check.json').read_text()
        else:
            assert report['verdict'] == 'PASS'
            assert versions.latest_pass(p, '27')['current_inputs'] is True
# The saved Step23 is neutral retained input, not a rerun of its native tool.
# Step27's producer, current readers, MCF and full canonical consumer are real.
def test_default_row27_reuses_the_typed_local_pdk_witness(tmp_path, monkeypatch):
    import copy
    import sys
    import librelane_contract as LC
    native_sta = LS.run_sta_script
    p, cfg, observed = _default_step27_transport(tmp_path, monkeypatch)
    put(p / 'reports/phase1/submission_template_fetch.json',
        {'pdk': 'neutral', 'pdk_source': '--pdk'})
    source = tmp_path / 'native-source'
    write(source / 'librelane/__init__.py', '# SOURCE_FIXTURE_ONLY\n')
    switch_path = p / 'phase3/librelane_switch.json'
    switch = json.loads(switch_path.read_text())
    switch.pop('pdk', None)  # The runtime is unnamed; the PDK role stays named.
    switch.pop('image', None)  # The saved native receipt owns its source image.
    switch.update(execution_route='LOCAL', local_network_mode='host',
                  librelane_root_host=str(source), librelane_executable=sys.executable)
    put(switch_path, switch)
    import librelane_postroute as LP
    import _watchdog
    # Restore the real launcher; only its supervised process leaf is neutral.
    record_path = p / LP.STEP23_RECORD
    state_record = json.loads(record_path.read_text())
    previous = Path(state_record['sta_state']).parent
    state_in = json.loads((previous / 'state_in.json').read_text())
    state_in['odb'] = str(write(p / 'phase3/stage3/pnr/neutral.odb', 'SOURCE_FIXTURE_ONLY\n'))
    state_in['def'] = str(write(p / 'phase3/stage3/pnr/neutral.def',
        'VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n'))
    state = put(p / 'phase3/librelane/typed-si-state.json', state_in)
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    actual_gate_transport = _watchdog.run_host_supervised
    calls = []
    def native_leaf(command, **kwargs):
        if '--id' in command:
            folder = Path(command[command.index('-o') + 1])
            before = json.loads(Path(command[command.index('-i') + 1]).read_text())
            put(folder / 'state_in.json', before)
            put(folder / 'state_out.json', before)
            put(folder / 'config.json', json.loads(config.read_text()))
            for name in ('sta.log', 'power.rpt'):
                write(folder / 'nom_typ' / name, (previous / 'nom_typ' / name).read_text())
            return _watchdog.SupervisedResult(rc=0, out='SOURCE_FIXTURE_ONLY\n', err='', outcome='natural')
        if 'sta' in command:
            calls.append({'argv': command, 'network': kwargs['env']['VIBEIC_LOCAL_NETWORK_MODE']})
            data = {'pins': {pin: {'arr_rise_min': 1.0, 'arr_rise_max': 1.2,
                'arr_fall_min': 1.0, 'arr_fall_max': 1.2, 'slew_rise_max': 0.1,
                'slack_max': 4.0} for pin in ('u0:Z', 'u1:Z', 'u2:A', 'z')}}
            put(p / 'phase3/stage3/extracted/neutral_si_timing.json', data)
            marker = re.search(r'VIBEIC_CURRENT_DONE [a-f0-9]+', Path(command[-1]).read_text())[0]
            text = 'SOURCE_FIXTURE_ONLY\nSI_TIMING_JSON_EMIT_DONE\n' + marker + '\n'
            return _watchdog.SupervisedResult(rc=0, out=text, err='', outcome='natural')
        return actual_gate_transport(command, **kwargs)
    monkeypatch.setattr(_watchdog, 'run_host_supervised', native_leaf)
    monkeypatch.setattr(LS, 'run_sta_script', native_sta)
    monkeypatch.setattr(LC, 'image_capability', lambda *a, **k: {})
    monkeypatch.setattr(LC, 'openroad_home', lambda *a, **k: None)
    live_namespace = LC._local_network_namespace()
    with monkeypatch.context() as old_context:
        # Neutral old-context metadata goes through the actual LC producer.
        old_context.setattr(LC, '_local_network_namespace', lambda: 'net:[retained-fixture]')
        image = LC.resolve_image(p, record=False)
        root_doc = LC.pdk_root_resolution(p, 'neutral', image=image)
        folder = LC.run_chain(p, image, [('OpenROAD.STAPostPNR', config, state)],
            lane='23-si-retained', pdk_root='/pdk',
            mounts=[(p / 'fixture_pdk', '/pdk')])[0]
    state_record.update(sta_state=str(folder / 'state_out.json'),
                        sta_state_sha256=LC.digest(folder / 'state_out.json'))
    put(record_path, state_record)
    fresh = LC.resolve_image(p, record=False)
    assert fresh != image and fresh.network_namespace == live_namespace
    assert root_doc['provider']['pdk'] is None and root_doc['pdk'] == 'neutral'
    assert root_doc['source'] == 'local_provider' and 'derivation' not in root_doc
    retained = {name: LC.digest(folder / name) for name in
                ('vibeic_receipt.json', 'input_fingerprint.json', 'pdk_root.json')}
    LC._LOCAL_PROVIDER_IDENTITIES.pop(str(image), None)
    root_path = p / 'phase3/librelane_pdk_root.provenance.json'

    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
    record_path = p / 'reports/phase3/default_steps/27/backend_result.json'
    record = json.loads(record_path.read_text())
    observation = {'status': row.status, 'detail': row.detail,
                   'record': record, 'provider': root_doc,
                   'calls': copy.deepcopy(observed), 'native_calls': calls,
                   'fresh_runtime': fresh.as_record(), 'retained': retained, 'refusals': {}}
    put(tmp_path / 'LOCAL_SI_OBSERVATION.json', observation)
    assert row.status == 'PASS', row.detail
    assert record['producer_verdict'] == record['verdict'] == 'PASS'
    assert record['canonical_step_result']['status'] == 'PASS'
    assert SG.main([str(p)]) == 0
    assert observed['sta_calls'] == ['nominal', 'mcf_setup', 'mcf_hold']
    assert observed['si_checks'] == 1
    assert calls and all(call['network'] == 'host' for call in calls)
    assert {name: LC.digest(folder / name) for name in retained} == retained
    import _opensta_current as current
    subject, tool = current.tool_subject(p, 'neutral', coupling=True)
    assert subject['tool_image'] == current.si_binding(p)['tool_image'] == image
    assert isinstance(tool['image'], LC.LocalProviderIdentity) and tool['image'] == fresh
    original_calls = copy.deepcopy(observed)

    for damage in ('provider', 'missing_provider', 'pdk', 'root', 'material'):
        bad = copy.deepcopy(root_doc)
        if damage == 'provider':
            bad['provider']['source_sha256'] = '0' * 64
        elif damage == 'missing_provider':
            bad.pop('provider')
        elif damage == 'pdk':
            bad['pdk'] = 'foreign'
        elif damage == 'root':
            bad['path'] = str(tmp_path)
        else:
            Path(cfg.liberty).write_text(Path(cfg.liberty).read_text() + '\n# changed\n')
        put(root_path, bad)
        rejected = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ['27'])
        observation['refusals'][damage] = {'status': rejected.status, 'detail': rejected.detail}
        put(tmp_path / 'LOCAL_SI_OBSERVATION.json', observation)
        assert rejected.status == 'NOT_MEASURED', (damage, rejected.detail)
        assert observed == original_calls, (damage, observed)
        put(root_path, root_doc)
