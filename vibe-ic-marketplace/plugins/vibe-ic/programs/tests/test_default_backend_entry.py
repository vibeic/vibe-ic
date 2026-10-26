"""Source CLI controls: native backend entries remain bounded and mode-specific.

No phase/tool is dispatched: every positive entry deliberately omits its exit.
"""
from pathlib import Path
import subprocess
import sys

import pytest

from _route_fixture import stage_owner_route


RUNNER = Path(__file__).resolve().parents[1] / "vibe_ic_one_shot_runner.py"


def observe(project, step, mode="default"):
    stage_owner_route(project, "ic")
    return subprocess.run(
        [sys.executable, str(RUNNER), str(project), "--route", "ic",
         "--execution-mode", mode, "--entry-step", step,
         "--no-dashboard", "--skip-hardware"],
        capture_output=True, text=True)


@pytest.mark.parametrize("step", ["32", "23", "35", "17", "15.5ic", "31"])
def test_supported_default_entry_reaches_required_exit_guard(tmp_path, step):
    result = observe(tmp_path, step)
    assert result.returncode == 2
    assert "needs --exit-step" in result.stderr, result.stdout + result.stderr
    assert "no runner can be entered" not in result.stderr


@pytest.mark.parametrize("step", ["999", "not_a_step", "36", "3"])
def test_unknown_or_non_native_span_keeps_entry_refusal(tmp_path, step):
    result = observe(tmp_path, step)
    assert result.returncode == 2
    if step == "36":
        # The fixed-order release owner now supports this canonical row;
        # it must still refuse an unbounded entry before dispatching a tool.
        assert "needs --exit-step" in result.stderr, result.stdout + result.stderr
        assert "no runner can be entered" not in result.stderr
    else:
        assert "no runner can be entered" in result.stderr, result.stdout + result.stderr


def test_ultra_does_not_gain_midspan_entry(tmp_path):
    result = observe(tmp_path, "32", "ultra")
    assert result.returncode == 2
    assert "no runner can be entered" in result.stderr, result.stdout + result.stderr
    assert "needs --exit-step" not in result.stderr
    assert "[entry] step 32 ->" not in result.stdout


def test_other_runner_owner_is_not_reassigned_to_phase3(tmp_path):
    result = observe(tmp_path, "A2")
    assert result.returncode == 2
    assert "owned by analog_one_shot_runner" in result.stderr
    assert "[entry] step A2 -> phase3" not in result.stdout


def test_backend_window_authority_reads_the_shipped_canonical_row(monkeypatch):
    import _flow_yaml
    import execution_policy
    import phase3_one_shot_runner as phase3
    from _hostpaths import require_repo

    flow = _flow_yaml.load(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml"))
    row = next(item for item in flow["steps"] if str(item["id"]) == "32")
    assert row["stage"] == "stage3"
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "default"})
    assert phase3._phase3_window_sites(str(row["id"]), str(row["id"])) == ["default_backend"]
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    assert phase3._phase3_window_sites(str(row["id"]), str(row["id"])) == ["enclosing_canonicalize"]


@pytest.fixture
def cross_phase_transport(monkeypatch):
    from test_execution_receipt_chain import isolated_transport
    transport = isolated_transport.__wrapped__(monkeypatch)
    next(transport)
    yield
    with pytest.raises(StopIteration):
        next(transport)


@pytest.mark.parametrize("case", ["current", "phase2_failure", "handoff_failure",
                                  "handoff_missing_input", "step31"])
def test_default_cross_phase_keeps_synthesis_in_phase2(
        tmp_path, monkeypatch, cross_phase_transport, case):
    """Real front door, Step9/14 owners and P3 window; no physical EDA.

    The Phase2 process transport drives the existing Step9 producer only;
    this does not claim execution of all of design.main or Steps10--13.
    The actual Step14 producer/full consumer must authorize the transition.
    The real P3 dispatcher then stops on absent physical inputs, rather than
    running a native physical tool or inventing a physical row PASS.
    """
    import json
    import os
    from dataclasses import asdict
    from types import SimpleNamespace
    import _path_layout as layout
    import execution_policy as policy
    import phase3_one_shot_runner as phase3
    import design_one_shot_runner as design
    import librelane_contract as contract
    import step_output_collector as versions
    import vibe_ic_one_shot_runner as front
    from test_default_frontend_r2 import _synthesis, put
    from test_step14_report_producer_authorship import GOOD

    project, rtl, pdk, native_calls = _synthesis(tmp_path, monkeypatch, ordinary=True)
    # This partial Phase2 transport retains the normal Step7 corner inputs
    # before the real front door checks the physical handoff dependencies.
    for process_corner in ("ss", "tt", "ff"):
        put(project / f"input/pdk/liberty/neutral__{process_corner}.lib",
            Path(pdk.liberty).read_text())
    design._emit_step7_pvt_matrix(project, pdk, "")
    # This transport executes synthesis, not native prelayout STA. The
    # existing direct SDC consumer still checks the actual emitted deck.
    put(project / "phase3/librelane_switch.json", {"steps": {"8": "direct"}})
    stage_owner_route(project, "ic")
    # The real front door constructs the ordinary PROGRAM_DEFAULT runtime.
    if case != "handoff_missing_input":
        put(project / "phase1/generated_docs/L5_ADI_SPEC.json", {"no_analog": True})
    # Admission reads image metadata, not the forbidden generic producer.
    # Replay only this exact read from the real enclosing launch observation.
    import _eda_pin
    docker_metadata = _eda_pin._docker
    authority = json.loads(Path(os.environ["VIBEIC_LIBRELANE_LOCAL_ATTESTATION"]).read_text())
    def inspect_metadata(*argv, **kwargs):
        if argv[:3] == ("inspect", "--format", "{{.Image}}\t{{.Config.Image}}"):
            item = authority["container_inspect"]
            return 0, item["Image"] + "\t" + item["Config"]["Image"] + "\n", ""
        return docker_metadata(*argv, **kwargs)
    monkeypatch.setattr(_eda_pin, "_docker", inspect_metadata)
    # Native resolved config and original report files, before the neutral
    # transport issues its first receipt. Do not restamp real field evidence.
    resolve, chain = contract.resolve_step_config, contract.run_chain

    def resolved(*args, **kwargs):
        path = resolve(*args, **kwargs)
        cfg = json.loads(path.read_text())
        cfg.update(TRISTATE_CELLS=[], SYNTH_CHECKS_ALLOW_TRISTATE=True,
                   SYNTH_ELABORATE_ONLY=False)
        put(path, cfg)
        return path

    def native_chain(*args, **kwargs):
        folders = chain(*args, **kwargs)
        folder = folders[1]
        recipe = GOOD.replace("core", "top").replace("TIE_H Y", "lib__tieh Z").replace(
            "TIE_L Y", "lib__tiel ZN")
        (folder / "COMMANDS").write_text("yosys -p '" + "; ".join(recipe.splitlines()) + "'\n")
        for name in ("pre_synth_chk.rpt", "chk.rpt"):
            text = "Found and reported 0 problems.\n"
            if case == "phase2_failure" and name == "chk.rpt":
                text = ("Warning: Wire top.\\live is used but has no driver.\n"
                        "Found and reported 1 problems.\n")
            (folder / "reports" / name).write_text(text)
        path = folder / "vibeic_receipt.json"
        receipt = json.loads(path.read_text())
        receipt["sha256"] = {str(p.relative_to(folder)): contract.digest(p)
                             for p in folder.rglob("*") if p.is_file() and p != path}
        put(path, receipt)
        return folders

    monkeypatch.setattr(contract, "resolve_step_config", resolved)
    monkeypatch.setattr(contract, "run_chain", native_chain)
    preserved = {p: p.read_bytes() for p in (project / "phase1").rglob("*.json")}
    preserved[rtl] = rtl.read_bytes()
    history = project / "steps/history/old_attempt/outputs.json"
    put(history, {"scope": "SOURCE_CONTROL historical bytes; not a PASS claim"})
    preserved[history] = history.read_bytes()
    observed = {"case": case, "phase_calls": [], "native_calls": native_calls}
    original_phase = front._run_phase

    class WrongPhysicalOwner(Exception):
        pass

    def unexpected_synthesis(*args, **kwargs):
        observed["wrong_physical_owner"] = "step_synth"
        raise WrongPhysicalOwner("the physical window re-entered synthesis")

    def process(label, runner, argv, env=None, **kwargs):
        observed["phase_calls"].append(runner.name)
        if runner.name == "phase2_one_shot_runner.py":
            row = design.step_yosys_synth(project, "top", "", pdk_name=pdk.name)
            observed["step9"] = asdict(row)
            path = layout.report_path(project, "phase2_one_shot.json")
            put(path, {"verdict": row.status, "steps": [asdict(row)],
                       "scope": "SOURCE_CONTROL Step9 producer; neutral phase process transport",
                       "declared_window": {"entry_step": "9", "exit_step": "38"}})
            if row.status == "PASS":
                canonical = project / "phase2/stage2/synth/netlist.v"
                if case == "handoff_failure":
                    canonical.write_text(canonical.read_text() + "// changed handoff bytes\n")
            return 0 if row.status == "PASS" else 1
        if runner.name == "phase3_one_shot_runner.py":
            entry = argv[argv.index("--entry-step") + 1]
            exit_ = argv[argv.index("--exit-step") + 1]
            sites = phase3._phase3_window_sites(entry, exit_)
            observed.update(p3_entry=entry, p3_exit=exit_, p3_sites=sites,
                            p3_order=phase3._phase3_window_steps(entry, exit_))
            args = SimpleNamespace(entry_step=entry, exit_step=exit_,
                                   container="", die_um="auto", util=.4,
                                   spare_density=None, pdk=pdk.name)
            with monkeypatch.context() as edge:
                edge.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", env["VIBEIC_PHASE3_WINDOW_RUN_ID"])
                # This expensive native leaf is deliberately forbidden here:
                # Phase2 has just run the actual selected synthesis owner.
                edge.setattr(phase3, "step_synth", unexpected_synthesis)
                return phase3._run_phase3_window(project, "top", pdk, args, sites)
        if runner.name == "phase1_one_shot_runner.py":
            raise AssertionError("a synthesis resume must preserve Phase1")
        return original_phase(label, runner, argv, env=env, **kwargs)

    monkeypatch.setattr(front, "_run_phase", process)
    entry, exit_ = ("31", "31") if case == "step31" else ("9", "38")
    monkeypatch.setattr(sys, "argv", [str(RUNNER), str(project), "--route", "ic",
        "--execution-mode", "default", "--entry-step", entry, "--exit-step", exit_,
        "--top-name", "top", "--ic-name", "top", "--pdk", pdk.name,
        "--container", "", "--no-dashboard", "--skip-hardware", "--skip-analog"])
    try:
        observed["frontdoor_rc"] = front.main()
    except WrongPhysicalOwner as exc:
        observed["wrong_owner_reason"] = str(exc)
    finally:
        index = versions._read_index(project)
        observed["saved_rows"] = []
        for item in index["steps"]:
            if item.get("versioned"):
                path = project / "steps" / item["folder"] / "outputs.json"
                if path.is_file():
                    record = json.loads(path.read_text())
                    observed["saved_rows"].append({"id": record["id"],
                        "status": record["status"], "canonical_pass": record.get("canonical_pass"),
                        "result": record.get("result")})
        (project / "cross_phase_observation.json").write_text(
            json.dumps(observed, indent=2) + "\n")
    assert {p: p.read_bytes() for p in preserved} == preserved
    assert "phase1_one_shot_runner.py" not in observed["phase_calls"]
    if case in ("phase2_failure", "handoff_failure", "handoff_missing_input"):
        assert "phase3_one_shot_runner.py" not in observed["phase_calls"], observed
        summary = json.loads(layout.report_path(project, "vibe_ic_one_shot.json").read_text())
        assert summary["halted_at"] == "phase2", summary
        if case == "phase2_failure":
            assert observed["step9"]["status"] == "FAIL"
        else:
            expected = "FAIL" if case == "handoff_failure" else "NOT_MEASURED"
            assert summary["step14_handoff"]["verdict"] == expected, summary
    else:
        assert observed["p3_sites"] == ["default_backend"], observed
        assert observed["p3_entry"] == ("31" if case == "step31" else "15")
        assert "wrong_physical_owner" not in observed
        if case == "current":
            step14 = next(r for r in observed["saved_rows"] if r["id"] == "14")
            assert step14["canonical_pass"] and step14["status"] == "PASS", step14
            assert len(native_calls) == 1
            assert observed["p3_order"][0] == "15" and observed["p3_order"][-1] == "38"
        else:
            assert native_calls == []
            assert observed["p3_order"] == ["31"]
        # The untouched required-input guards stop before native physical work.
        first = next(r for r in observed["saved_rows"] if r["id"] == observed["p3_entry"])
        assert first["status"] == "NOT_MEASURED" and not first["canonical_pass"]


def _entry10_retained_checkpoint(tmp_path, monkeypatch):
    """Seed the existing neutral Step9 fixture; resume readers are never stubbed.

    This is retained-artifact input data, not a new synthesis qualification.
    The source45 transport supplies the receipt-bound native grammar only.
    """
    import json
    import librelane_contract as contract
    import design_one_shot_runner as design
    from test_default_frontend_r2 import _synthesis, put
    from test_step14_report_producer_authorship import GOOD

    with monkeypatch.context() as seed:
        project, rtl, pdk, seed_calls = _synthesis(tmp_path, seed, ordinary=True)
        put(project / 'phase1/generated_docs/L5_ADI_SPEC.json', {'no_analog': True})
        resolve, chain = contract.resolve_step_config, contract.run_chain

        def resolved(*args, **kwargs):
            path = resolve(*args, **kwargs)
            cfg = json.loads(path.read_text())
            cfg.update(TRISTATE_CELLS=[], SYNTH_CHECKS_ALLOW_TRISTATE=True,
                       SYNTH_ELABORATE_ONLY=False)
            put(path, cfg)
            return path

        def native_data(*args, **kwargs):
            folders = chain(*args, **kwargs)
            folder = folders[1]
            recipe = GOOD.replace('core', 'top').replace('TIE_H Y', 'lib__tieh Z').replace(
                'TIE_L Y', 'lib__tiel ZN')
            (folder / 'COMMANDS').write_text("yosys -p '" + '; '.join(recipe.splitlines()) + "'\n")
            for name in ('pre_synth_chk.rpt', 'chk.rpt'):
                (folder / 'reports' / name).write_text('Found and reported 0 problems.\n')
            path = folder / 'vibeic_receipt.json'
            receipt = json.loads(path.read_text())
            receipt['sha256'] = {str(p.relative_to(folder)): contract.digest(p)
                                 for p in folder.rglob('*') if p.is_file() and p != path}
            put(path, receipt)
            return folders

        seed.setattr(contract, 'resolve_step_config', resolved)
        seed.setattr(contract, 'run_chain', native_data)
        import step_preflight as preflight
        row = preflight.retained_call(
            project, '9', design.step_yosys_synth, project, 'top', '',
            pdk_name=pdk.name, canonical_acceptance=True)
        assert row.status == 'PASS', row.detail
    # All seed transports have left scope before the actual entry helper reads 9.
    import step_output_collector as versions
    import synth_handoff_netlist_check as handoff
    prior = versions.latest_pass(project, '9')
    assert prior and prior['canonical_pass'] and prior['current_inputs'], prior
    assert handoff.bound_handoff(project)['verdict'] == 'PASS'
    return project, rtl, pdk


def _entry10_prelayout_transport(project, pdk, monkeypatch, case, observed):
    """Neutral native file transport; P3, LP readers and full consumers stay real."""
    import json
    import shutil
    import librelane_contract as contract
    import librelane_prelayout as prelayout
    import phase3_one_shot_runner as phase3
    from test_step8_post_prelayout import put

    root = Path(pdk.liberty).parents[4]
    monkeypatch.setattr(contract, 'pdk_root_resolution', lambda *a, **k: {'path': str(root)})
    monkeypatch.setattr(phase3, '_detect_pdk', lambda current, name: pdk if name == pdk.name else None)
    # The saved synthesis receipt keeps the same stated native image namespace.
    monkeypatch.setattr(contract, 'resolve_image', lambda *_: 'img')
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'7': 'librelane', '8': 'librelane', '10': 'librelane'}})
    deck = ('create_clock -name clk -period 10 [get_ports clk]\n'
            'set_input_delay 1 -clock clk [get_ports a]\n'
            'set_output_delay 1 -clock clk [get_ports q]\n')
    put(project / 'input/constraints/clock.sdc', deck)
    libs = {}
    for process in ('ss', 'tt', 'ff'):
        lib = put(project / f'input/pdk/liberty/neutral__{process}.lib',
                  Path(pdk.liberty).read_text())
        libs[f'*_{process}_*'] = [str(lib)]
    corners = [f'{rc}_{process}_025C' for rc in ('min', 'nom', 'max')
               for process in ('ss', 'tt', 'ff')]
    population = {'STA_CORNERS': corners, 'DEFAULT_CORNER': 'nom_tt_025C', 'LIB': libs}

    def resolved(current, image, raw, output, **kwargs):
        observed['native_resolution'].append(json.loads(raw.read_text())['meta']['step'])
        return put(output, {**json.loads(raw.read_text()), **population})

    def native(current, image, steps, **kwargs):
        observed['native_prelayout'].append([step for step, _, _ in steps])
        outputs = []
        previous = None
        for index, (sid, cfg_path, state_in) in enumerate(steps, 1):
            folder = project / 'phase3/librelane/prelayout/design_sdc' / f'{index:02d}-{sid.lower().replace(".", "-")}'
            cfg = json.loads(Path(cfg_path).read_text())
            state = json.loads((previous or Path(state_in)).read_text())
            put(folder / 'config.json', cfg)
            if sid == 'OpenROAD.STAPrePNR':
                state['metrics'] = {}
                calibration = Path(prelayout.__file__).parent / 'calibration'
                for corner in (c for c in corners if c.startswith('nom_')):
                    target = folder / corner
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(calibration / 'sta_prepnr_linked_clean_negative.log', target / 'sta.log')
                    shutil.copyfile(calibration / 'sta_prepnr_check_setup_clean_negative.rpt', target / 'checks.rpt')
                    process = 'ss' if '_ss_' in corner else 'tt'
                    for sense in ('max', 'min'):
                        shutil.copyfile(calibration / f'sta_prepnr_cal_{process}_{sense}.rpt', target / f'{sense}.rpt')
                    for check, slack in (('setup', -.25 if case == '10FAIL' else 1.0), ('hold', .2)):
                        for metric, value in (('ws', slack), ('wns', min(slack, 0)), ('tns', min(slack, 0))):
                            if case != '10NOT_MEASURED':
                                state['metrics'][f'timing__{check}__{metric}__corner:{corner}'] = value
                    # Native command-unit output, before the fixture receipt.
                    put(target / 'vibeic_time_unit.rpt', 'STA_TIME_UNIT: ns\n')
            put(folder / 'state_out.json', state)
            put(folder / 'invocation.log', 'neutral native OpenROAD prelayout process output\n')
            fingerprint = {'step': sid, 'image': image, 'config': contract.digest(Path(cfg_path)),
                'state': contract.digest(previous or Path(state_in)),
                'state_files': {str(Path(state['nl'])): contract.digest(Path(state['nl']))},
                'config_files': contract.config_file_hashes(cfg, kwargs.get('mounts') or [])}
            put(folder / 'input_fingerprint.json', fingerprint)
            put(folder / 'pdk_root.json', {'cli_pdk_root': kwargs['pdk_root'],
                'mounts_under_it': [[str(host), guest] for host, guest in kwargs.get('mounts', [])],
                'stated_by': 'run_chain(pdk_root=...)'})
            put(folder / 'vibeic_receipt.json', {'input': fingerprint,
                'sha256': {str(p.relative_to(folder)): contract.digest(p)
                           for p in folder.rglob('*') if p.is_file()}})
            previous = folder / 'state_out.json'
            outputs.append(folder)
        return outputs

    monkeypatch.setattr(prelayout, 'resolve_step_config', resolved)
    monkeypatch.setattr(prelayout, 'run_chain', native)


@pytest.mark.parametrize('case', ['current', 'exit10', 'missing9', '10FAIL',
                                  '10NOT_MEASURED', '14FAIL', '14NOT_MEASURED', 'phase2FAIL'])
def test_default_entry10_resumes_current_checkpoint(
        tmp_path, monkeypatch, cross_phase_transport, case):
    """Retained9 reader + real Step10/full consumer + routing/real14 boundary.

    Phase2 process output represents routing only: it proves entry11/exit38,
    never qualification of unchanged DFT/LEC11--13. Native STA file writes are
    neutral calibration data, not an actual physical or timing run.
    """
    import json
    import os
    from types import SimpleNamespace
    import _eda_pin
    import _path_layout as layout
    import phase3_one_shot_runner as phase3
    import step_output_collector as versions
    import vibe_ic_one_shot_runner as front
    from test_default_frontend_r2 import put

    project, rtl, pdk = _entry10_retained_checkpoint(tmp_path, monkeypatch)
    observed = {'case': case, 'phase_calls': [], 'native_resolution': [],
                'native_prelayout': [], 'phase2_scope': 'ROUTING_ONLY_NOT_DFT_LEC_QUALIFICATION'}
    _entry10_prelayout_transport(project, pdk, monkeypatch, case, observed)
    # Preserve the actual nested audit process result if its report cannot
    # be published. This observes the real transport without replacing it.
    import _watchdog
    native_host_run = _watchdog.run_host_supervised
    def observed_host_run(argv, **kwargs):
        result = native_host_run(argv, **kwargs)
        if any(Path(str(arg)).name == 'stage1_compliance.py' for arg in argv):
            observed.setdefault('stage1_native_process', []).append({
                'argv': list(argv), 'rc': result.rc,
                'stdout': result.out, 'stderr': result.err})
        return result
    monkeypatch.setattr(_watchdog, 'run_host_supervised', observed_host_run)
    stage_owner_route(project, 'ic')
    history = put(project / 'steps/history/retained_entry10/outputs.json',
                  {'scope': 'neutral retained input history; no current PASS claim'})
    preserved = {path: path.read_bytes() for path in (project / 'phase1').rglob('*.json')}
    preserved.update({rtl: rtl.read_bytes(), history: history.read_bytes()})
    saved9 = versions.latest_pass(project, '9')
    receipt9 = project / saved9['folder'] / 'outputs.json'
    if not receipt9.is_file():
        receipt9 = project / 'steps' / saved9['folder'] / 'outputs.json'
    original9 = receipt9.read_bytes()
    if case == 'missing9':
        (project / 'phase2/stage2/synth/netlist.v').unlink()
    authority = json.loads(Path(os.environ['VIBEIC_LIBRELANE_LOCAL_ATTESTATION']).read_text())
    metadata = _eda_pin._docker
    def image_metadata(*argv, **kwargs):
        if argv[:3] == ('inspect', '--format', '{{.Image}}\t{{.Config.Image}}'):
            item = authority['container_inspect']
            return 0, item['Image'] + '\t' + item['Config']['Image'] + '\n', ''
        return metadata(*argv, **kwargs)
    monkeypatch.setattr(_eda_pin, '_docker', image_metadata)
    original_phase = front._run_phase
    def process(label, runner, argv, env=None, **kwargs):
        observed['phase_calls'].append(runner.name)
        if runner.name == 'phase2_one_shot_runner.py':
            observed['phase2_argv'] = list(argv)
            assert argv[argv.index('--entry-step') + 1] == '11'
            assert argv[argv.index('--exit-step') + 1] == '38'
            if case == '14FAIL':
                nl = project / 'phase2/stage2/synth/netlist.v'
                nl.write_text(nl.read_text() + '// changed retained handoff\n')
            elif case == '14NOT_MEASURED':
                (project / 'phase1/generated_docs/L5_ADI_SPEC.json').unlink()
            status = 'FAIL' if case == 'phase2FAIL' else 'PASS'
            put(layout.report_path(project, 'phase2_one_shot.json'), {
                'verdict': status, 'steps': [],
                'scope': 'SOURCE_CONTROL routing-only phase process; no DFT/LEC tool qualification',
                'declared_window': {'entry_step': '11', 'exit_step': '38'}})
            return 1 if status == 'FAIL' else 0
        if runner.name == 'phase3_one_shot_runner.py':
            entry = argv[argv.index('--entry-step') + 1]
            exit_ = argv[argv.index('--exit-step') + 1]
            sites = phase3._phase3_window_sites(entry, exit_)
            observed.update(p3_entry=entry, p3_exit=exit_, p3_sites=sites)
            args = SimpleNamespace(entry_step=entry, exit_step=exit_, container='',
                die_um='auto', util=.4, spare_density=None, pdk=pdk.name)
            with monkeypatch.context() as edge:
                edge.setenv('VIBEIC_PHASE3_WINDOW_RUN_ID', env['VIBEIC_PHASE3_WINDOW_RUN_ID'])
                return phase3._run_phase3_window(project, 'top', pdk, args, sites)
        if runner.name == 'phase1_one_shot_runner.py':
            raise AssertionError('Step10 resume dispatched Phase1')
        return original_phase(label, runner, argv, env=env, **kwargs)
    monkeypatch.setattr(front, '_run_phase', process)
    exit_ = '10' if case == 'exit10' else '38'
    monkeypatch.setattr(sys, 'argv', [str(RUNNER), str(project), '--route', 'ic',
        '--execution-mode', 'default', '--entry-step', '10', '--exit-step', exit_,
        '--top-name', 'top', '--ic-name', 'top', '--pdk', pdk.name, '--container', '',
        '--no-dashboard', '--skip-hardware', '--skip-analog'])
    try:
        observed['frontdoor_rc'] = front.main()
    finally:
        observed['rows'] = []
        for item in versions._read_index(project)['steps']:
            if item.get('versioned'):
                path = project / 'steps' / item['folder'] / 'outputs.json'
                if path.is_file():
                    row = json.loads(path.read_text())
                    observed['rows'].append({key: row.get(key) for key in
                        ('id', 'status', 'canonical_pass', 'result')})
        summary_path = layout.report_path(project, 'vibe_ic_one_shot.json')
        observed['summary'] = json.loads(summary_path.read_text()) if summary_path.is_file() else None
        (project / 'ENTRY10_OBSERVATION.json').write_text(json.dumps(observed, indent=2) + '\n')
    assert receipt9.read_bytes() == original9
    for path, data in preserved.items():
        if case == '14NOT_MEASURED' and path.name == 'L5_ADI_SPEC.json':
            continue
        assert path.read_bytes() == data, path
    assert 'phase1_one_shot_runner.py' not in observed['phase_calls']
    summary = observed['summary']
    assert summary is not None, observed
    if case == 'missing9':
        assert not observed['native_prelayout'] and not observed['phase_calls'], observed
        assert summary['step10_prelayout']['verdict'] == 'NOT_MEASURED', observed
    else:
        step10 = next(row for row in observed['rows'] if str(row['id']) == '10')
        expected = 'FAIL' if case == '10FAIL' else 'NOT_MEASURED' if case == '10NOT_MEASURED' else 'PASS'
        assert step10['status'] == expected, observed
        assert bool(step10['canonical_pass']) is (expected == 'PASS'), observed
        if case in ('10FAIL', '10NOT_MEASURED', 'exit10'):
            assert not observed['phase_calls'], observed
            assert observed['frontdoor_rc'] == (0 if case == 'exit10' else 1 if case == '10FAIL' else 2)
        elif case in ('14FAIL', '14NOT_MEASURED', 'phase2FAIL'):
            assert observed['phase_calls'] == ['phase2_one_shot_runner.py', 'flow_compliance_check.py'], observed
            assert summary['halted_at'] == 'phase2', observed
            if case != 'phase2FAIL':
                assert summary['step14_handoff']['verdict'] == ('FAIL' if case == '14FAIL' else 'NOT_MEASURED'), observed
        else:
            step14 = next(row for row in observed['rows'] if str(row['id']) == '14')
            assert step14['status'] == 'PASS' and step14['canonical_pass'], observed
            assert observed['p3_entry'] == '15' and observed['p3_sites'] == ['default_backend'], observed


@pytest.mark.parametrize('case', ['current', 'forwarded', 'missing_L8',
                                  'current_missing_PVT', 'invalid_sdc', 'missing_liberty'])
def test_default_entry15_refreshes_step7_before_physical_handoff(
        tmp_path, monkeypatch, cross_phase_transport, case):
    """True front door/Step7 owner/full consumer; real P3 stops before physical tools."""
    import json
    import os
    from types import SimpleNamespace
    import _eda_pin
    import _path_layout as layout
    import phase3_one_shot_runner as phase3
    import step_output_collector as versions
    import vibe_ic_one_shot_runner as front
    from _ppa import timing
    from test_default_frontend_r2 import put

    project, rtl, pdk = _entry10_retained_checkpoint(tmp_path, monkeypatch)
    observed = {'case': case, 'phase_calls': [], 'native_resolution': [],
                'native_prelayout': []}
    _entry10_prelayout_transport(project, pdk, monkeypatch, 'current', observed)
    stage_owner_route(project, 'ic')
    authority = json.loads(Path(os.environ['VIBEIC_LIBRELANE_LOCAL_ATTESTATION']).read_text())
    metadata = _eda_pin._docker
    def image_metadata(*argv, **kwargs):
        if argv[:3] == ('inspect', '--format', '{{.Image}}\t{{.Config.Image}}'):
            item = authority['container_inspect']
            return 0, item['Image'] + '\t' + item['Config']['Image'] + '\n', ''
        return metadata(*argv, **kwargs)
    monkeypatch.setattr(_eda_pin, '_docker', image_metadata)
    front._capture_container_image(project, '', None)
    # Construct the previous valid constraint/timing data before this resume.
    # Only an unrelated source comment differs; the canonical emitter binds it.
    old_source = tmp_path / 'prior_source/phase3_one_shot_runner.py'
    old_source.parent.mkdir()
    old_source.write_bytes(Path(phase3.__file__).read_bytes() + b'\n# prior unrelated source revision\n')
    with monkeypatch.context() as previous:
        previous.setattr(phase3, '__file__', str(old_source))
        seed = phase3.step_prelayout_signoff(project, 'top', pdk, '')
        assert seed.status == 'PASS', seed.detail
    current, stale = timing.read_step7_asic_sdc(phase3, project, 'top', pdk)
    assert current is None and '@code:phase3_one_shot_runner.py' in stale
    before_sdc = next((project / 'phase2/stage2/constraints').glob('*.sdc')).read_bytes()
    pvt = project / 'phase2/stage2/constraints/pvt_matrix.json'
    stance = project / 'reports/phase3/single_corner_stance.json'
    preserved = {p: p.read_bytes() for p in [rtl, pvt, stance,
                 *[p for p in (project / 'phase1').rglob('*.json')],
                 *[p for p in (project / 'steps').rglob('outputs.json')]]}
    observed['native_resolution'].clear();observed['native_prelayout'].clear()
    if case == 'missing_L8':
        (project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json').unlink()
    elif case == 'current_missing_PVT':
        timing.emit_step7_asic_sdc(phase3, project, 'top', pdk, '')
        pvt.unlink()
        observed['sdcreader_with_missing_pvt'] = timing.read_step7_asic_sdc(
            phase3, project, 'top', pdk)[1]
    elif case == 'invalid_sdc':
        (project / 'input/constraints/clock.sdc').write_text('set_input_delay {unterminated\n')
    elif case == 'missing_liberty':
        Path(pdk.liberty).unlink()
    original_phase = front._run_phase
    def process(label, runner, argv, env=None, **kwargs):
        observed['phase_calls'].append(runner.name)
        if runner.name == 'phase1_one_shot_runner.py':
            raise AssertionError('a physical continuation reran Phase1')
        if runner.name == 'phase2_one_shot_runner.py':
            assert case == 'forwarded'
            assert argv[argv.index('--entry-step') + 1] == '11'
            put(layout.report_path(project, 'phase2_one_shot.json'), {
                'verdict': 'PASS', 'steps': [],
                'declared_window': {'entry_step': '11', 'exit_step': '15'},
                'scope': 'SOURCE_CONTROL unchanged phase process routing only; not DFT/LEC PASS'})
            return 0
        if runner.name == 'phase3_one_shot_runner.py':
            entry = argv[argv.index('--entry-step') + 1]
            exit_ = argv[argv.index('--exit-step') + 1]
            path, why = phase3._prepnr_constraint_file(project, 'top', pdk)
            observed.update(p3_entry=entry, p3_sdc_path=str(path), p3_sdc_reason=why)
            args = SimpleNamespace(entry_step=entry, exit_step=exit_, container='',
                die_um='auto', util=.4, spare_density=None, pdk=pdk.name)
            with monkeypatch.context() as edge:
                edge.setenv('VIBEIC_PHASE3_WINDOW_RUN_ID', env['VIBEIC_PHASE3_WINDOW_RUN_ID'])
                return phase3._run_phase3_window(
                    project, 'top', pdk, args, phase3._phase3_window_sites(entry, exit_))
        return original_phase(label, runner, argv, env=env, **kwargs)
    monkeypatch.setattr(front, '_run_phase', process)
    monkeypatch.setattr(sys, 'argv', [str(RUNNER), str(project), '--route', 'ic',
        '--execution-mode', 'default', '--entry-step', '11' if case == 'forwarded' else '15', '--exit-step', '15',
        '--top-name', 'top', '--ic-name', 'top', '--pdk', pdk.name, '--container', '',
        '--no-dashboard', '--skip-hardware', '--skip-analog'])
    try:
        observed['frontdoor_rc'] = front.main()
    finally:
        observed['rows'] = [json.loads((project / 'steps' / r['folder'] / 'outputs.json').read_text())
                            for r in versions._read_index(project)['steps'] if r.get('versioned')]
        summary = layout.report_path(project, 'vibe_ic_one_shot.json')
        observed['summary'] = json.loads(summary.read_text()) if summary.is_file() else None
        put(project / 'ENTRY15_STEP7_OBSERVATION.json', observed)
    if case not in ('current', 'forwarded'):
        assert 'phase3_one_shot_runner.py' not in observed['phase_calls'], observed['summary']
        assert observed['frontdoor_rc'] != 0, observed['summary']
        assert observed['summary']['step7_sdc_refresh']['verdict'] != 'PASS'
        assert not observed['native_prelayout']
        for p, raw in preserved.items():
            if (case == 'missing_L8' and p.name == 'L8_TIMING_WAVEFORM.json'
                    or case == 'current_missing_PVT' and p == pvt):
                continue
            assert p.read_bytes() == raw, p
        return
    assert observed.get('p3_sdc_path') != 'None', observed.get('p3_sdc_reason', observed['summary'])
    assert observed['p3_entry'] == '15'
    current, error = timing.read_step7_asic_sdc(phase3, project, 'top', pdk)
    assert current is not None, error
    assert (project / current['path']).read_bytes() == before_sdc
    accepted = versions.latest_pass(project, '7')
    assert accepted['canonical_pass'] and accepted['current_inputs']
    assert accepted['result']['canonical_consumer']['status'] == 'PASS'
    assert not observed['native_prelayout'], 'entry15 must not rerun native Step10'
    selected_folder = accepted['folder']
    receipt_bytes = (project / 'phase2/stage2/constraints/asic_sdc.json').read_bytes()
    reused = front._complete_step7_sdc(project, 'top', pdk.name, '')
    assert reused['verdict'] == 'PASS' and reused['producer_reused'] is True
    assert versions.latest_pass(project, '7')['folder'] == selected_folder
    assert (project / 'phase2/stage2/constraints/asic_sdc.json').read_bytes() == receipt_bytes
    if case == 'forwarded':
        handoff = versions.latest_pass(project, '14')
        assert handoff['canonical_pass'] and handoff['status'] == 'PASS'
        assert handoff['result']['canonical_consumer']['status'] == 'PASS'
    for p, raw in preserved.items():
        assert p.read_bytes() == raw, p


@pytest.mark.parametrize('case', ['current', 'changed9', 'changed10',
                                  'missing_gate', 'failed_gate', 'entry10'])
def test_default_postcheck8_consumes_saved_prelayout_without_native_replay(
        tmp_path, monkeypatch, cross_phase_transport, case):
    """Real public entry, retained owners and consumers; native seed is neutral."""
    import json
    import os
    import _eda_pin
    import _path_layout as layout
    from _ppa import timing
    import design_one_shot_runner as design
    import phase3_one_shot_runner as phase3
    import step_output_collector as versions
    import vibe_ic_one_shot_runner as front
    from test_default_frontend_r2 import put

    project, rtl, pdk = _entry10_retained_checkpoint(tmp_path, monkeypatch)
    observed = {'case': case, 'native_resolution': [], 'native_prelayout': [],
                'phases': [], 'scope': 'saved neutral native data; real postcheck/full consumer'}
    _entry10_prelayout_transport(project, pdk, monkeypatch, 'current', observed)
    stage_owner_route(project, 'ic')
    if case != 'entry10':
        seeded = front._complete_step10_prelayout(project, 'top', pdk.name, '')
        assert seeded['verdict'] == 'PASS', seeded
    saved = {sid: versions.latest_pass(project, sid)
             for sid in (('9',) if case == 'entry10' else ('9', '10'))}
    assert all(row and row['current_inputs'] and row['canonical_pass'] for row in saved.values())
    preserved = {project / 'steps' / row['folder'] / 'outputs.json':
                 (project / 'steps' / row['folder'] / 'outputs.json').read_bytes()
                 for row in saved.values()}
    for path in (project / 'phase1').rglob('*.json'):
        preserved[path] = path.read_bytes()
    preserved[rtl] = rtl.read_bytes()
    staged_sdc = project / 'input/constraints/clock.sdc'
    preserved[staged_sdc] = staged_sdc.read_bytes()
    if case != 'entry10':
        sdc = json.loads((project / 'phase2/stage2/constraints/asic_sdc.json').read_text())
        for path in (project / sdc['path'],
                     project / 'phase2/stage2/constraints/pvt_matrix.json'):
            preserved[path] = path.read_bytes()
    gate = project / 'phase3/librelane/prelayout/gates/step8_sdc_opensta.json'
    if case == 'changed9':
        put(project / 'phase2/stage2/synth/netlist.v', 'module changed; endmodule\n')
    elif case == 'changed10':
        path = project / 'reports/phase3/sta/pre_pnr_summary.json'
        path.write_text(path.read_text() + '\n')
    elif case == 'missing_gate':
        gate.unlink()
    elif case == 'failed_gate':
        doc = json.loads(gate.read_text())
        doc['verdict'] = 'FAIL'
        doc['findings'] = ['neutral retained OpenSTA SDC failure']
        put(gate, doc)
    observed['native_resolution'].clear()
    observed['native_prelayout'].clear()

    def no_producer(*args, **kwargs):
        raise AssertionError('postcheck-only entry reran an upstream producer')
    monkeypatch.setattr(design, 'step_yosys_synth', no_producer)
    if case != 'entry10':
        monkeypatch.setattr(timing, 'emit_step7_asic_sdc', no_producer)
        monkeypatch.setattr(phase3, 'step_prelayout_signoff', no_producer)
    original_phase = front._run_phase
    def phase(label, runner, argv, **kwargs):
        observed['phases'].append(runner.name)
        if runner.name in ('phase1_one_shot_runner.py', 'phase2_one_shot_runner.py',
                           'phase3_one_shot_runner.py'):
            raise AssertionError('postcheck-only bounded entry dispatched another phase')
        return original_phase(label, runner, argv, **kwargs)
    monkeypatch.setattr(front, '_run_phase', phase)
    authority = json.loads(Path(os.environ['VIBEIC_LIBRELANE_LOCAL_ATTESTATION']).read_text())
    metadata = _eda_pin._docker
    def image_metadata(*argv, **kwargs):
        if argv[:3] == ('inspect', '--format', '{{.Image}}\t{{.Config.Image}}'):
            item = authority['container_inspect']
            return 0, item['Image'] + '\t' + item['Config']['Image'] + '\n', ''
        return metadata(*argv, **kwargs)
    monkeypatch.setattr(_eda_pin, '_docker', image_metadata)
    entry = '10' if case == 'entry10' else '8'
    monkeypatch.setattr(sys, 'argv', [str(RUNNER), str(project), '--route', 'ic',
        '--execution-mode', 'default', '--entry-step', entry, '--exit-step', entry,
        '--top-name', 'top', '--ic-name', 'top', '--pdk', pdk.name, '--container', '',
        '--no-dashboard', '--skip-hardware', '--skip-analog'])
    try:
        observed['rc'] = front.main()
    finally:
        summary = layout.report_path(project, 'vibe_ic_one_shot.json')
        observed['summary'] = json.loads(summary.read_text()) if summary.is_file() else None
        selected = next((r for r in versions._read_index(project)['steps'] if str(r['id']) == '8'), None)
        observed['step8'] = (json.loads((project / 'steps' / selected['folder'] / 'outputs.json').read_text())
                             if selected and selected.get('folder') else None)
        put(project / 'POSTCHECK8_OBSERVATION.json', observed)
    assert observed['rc'] == (0 if case in ('current', 'entry10') else
                              1 if case == 'failed_gate' else 2), observed
    assert not observed['phases'], observed
    assert len(observed['native_prelayout']) == (1 if case == 'entry10' else 0), observed
    if case in ('current', 'entry10'):
        record = observed['step8']
        assert record['status'] == 'PASS' and record['canonical_pass'], observed
        assert record['result']['canonical_consumer']['status'] == 'PASS'
        assert observed['summary']['step8_postcheck']['verdict'] == 'PASS'
        assert observed['summary']['whole_flow_verdict'] == 'NOT_MEASURED'
    else:
        assert observed['summary']['step8_postcheck']['verdict'] != 'PASS', observed
        assert not (observed['step8'] or {}).get('canonical_pass'), observed
    for path, raw in preserved.items():
        assert path.read_bytes() == raw, path


@pytest.mark.parametrize('case,expected,calls,terminal_expected', [
    ('no_scan', 'PASS', 0, 'PASS'),
    ('scan_pass', 'PASS', 2, 'PASS'),
    ('terminal_missing', 'PASS', 2, 'NOT_MEASURED'),
    ('terminal_changed', 'PASS', 2, 'NOT_MEASURED'),
    ('stale_subject', 'NOT_MEASURED', 0, None),
    ('missing_scan_sdc', 'NOT_MEASURED', 0, None),
    ('scan_violation', 'FAIL', 2, 'FAIL'),
    ('terminal_violation_changed', 'FAIL', 2, 'NOT_MEASURED'),
])
def test_default_d26_scan_mode_prelayout_is_subject_bound_and_fail_closed(
        tmp_path, monkeypatch, case, expected, calls, terminal_expected):
    """D26 times both modes on D24 bytes; absence/red cannot borrow baseline."""
    import hashlib
    import json
    from types import SimpleNamespace
    import design_one_shot_runner as design
    import dft_signoff_check as signoff
    import fault_scan_chain_insert as scan
    import flow109
    import lec_gate_netlist_select as netlists
    import librelane_contract as contract
    import librelane_prelayout as prelayout
    import phase3_one_shot_runner as phase3
    import step_output_collector as versions
    import synth_handoff_netlist_check as handoff
    import vibe_ic_one_shot_runner as front
    from test_default_frontend_r2 import put

    project = tmp_path.resolve()
    mapped = put(project / 'phase2/stage2/synth/top_synth.v',
                 'module top(input clk, test, shift); endmodule\n')
    adopted = put(project / 'phase2/stage2/synth/post_dft_netlist.v',
                  'module top(input clk, tck, test, shift); endmodule\n')
    put(project / 'phase2/stage1/rtl/top.v', 'module top; endmodule\n')
    functional_sdc = put(project / 'phase2/stage2/constraints/top.sdc',
                         'create_clock -period 10 [get_ports {clk}]\n')
    gate = {'verdict': 'PASS', 'sdc': str(functional_sdc),
            'sdc_sha256': contract.digest(functional_sdc)}
    put(project / 'phase3/librelane/prelayout/gates/step8_sdc_opensta.json', gate)
    scan_sdc = put(project / 'phase2/stage2/dft/scan_mode.sdc',
                   'create_clock -period 100 [get_ports {tck}]\n'
                   'set_case_analysis 1 [get_ports {shift}]\n'
                   'set_case_analysis 1 [get_ports {test}]\n')
    d09 = {'path': 'phase1/generated_docs/dft.json', 'sha256': '1' * 64,
           'sources': {'input/spec.json': 'sha256:' + '2' * 64},
           'intent': {'scan_test': case != 'no_scan',
                      'test_port_def': {
                          'scan_enable': {'native': 'shift', 'public': 'scan_enable'},
                          'scan_in': {'native': 'sin', 'public': 'scan_in'},
                          'scan_out': {'native': 'sout', 'public': 'scan_out'},
                          'test': {'native': 'test', 'public': 'test_mode'},
                          'tck': {'native': 'tck', 'public': 'scan_clock'}},
                      'test_mode': {'clock': 'clk', 'clock_domains': ['clk'],
                          'edge': 'rising', 'scan_clock': 'tck',
                          'scan_clock_domains': ['tck'], 'scan_edge': 'rising',
                          'clock_select': {'native': 'test', 'functional_value': 0,
                                           'scan_value': 1},
                          'reset': {'style': 'synchronous', 'signal': 'rst_n',
                                    'active_level': 0, 'shift_value': 1}}}}
    put(project / d09['path'], {'dft': d09['intent']})
    put(project / 'input/spec.json', {})
    constraint = {'kind': 'scan_shift_clock',
                  'path': str(scan_sdc.relative_to(project)),
                  'sha256': contract.digest(scan_sdc),
                  'l20_path': 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
                  'l20_sha256': '3' * 64, 'clock': 'tck',
                  'frequency_mhz': '10.0', 'period_ns': '100.0'}
    scan_report = {'published': True, 'd09_contract': d09,
                   'scan_mode_constraint': constraint,
                   'measured_artifacts': {'phase2/stage2/dft/scan_chain_work/chained.v': '4' * 64},
                   'native_clock_controls': {'functional_clock': 'clk',
                                             'scan_clock': 'tck',
                                             'clock_select': 'test'}}
    put(project / 'reports/phase2/dft/scan_chain.json', scan_report)
    liberty = put(project / 'pdk/neutral/lib/neutral__tt.lib', 'library(neutral) {}\n')

    monkeypatch.setattr(front, '_current_step9_checkpoint', lambda *_a, **_k:
                        ({'step9_record': {}, 'native_handoff': {}}, None))
    monkeypatch.setattr(front, '_flow109_selected_row', lambda row: row == 'D26')
    monkeypatch.setattr(handoff, 'bound_handoff', lambda *_:
                        {'verdict': 'PASS', 'mapped': str(mapped)})
    pdk = SimpleNamespace(name='neutral', liberty=str(liberty))
    monkeypatch.setattr(design, '_phase2_pdk_config', lambda *_: pdk)
    monkeypatch.setattr(phase3, 'step_prelayout_signoff', lambda *_:
                        SimpleNamespace(status='PASS', detail='retained functional PASS'))
    current = {'id': '10', 'status': 'PASS', 'folder': 'phase3/stage3/10',
               'canonical_pass': True, 'current_inputs': True,
               'result': {'canonical_consumer': {'status': 'PASS',
                                                  'step': {'reasons': []}}}}
    monkeypatch.setattr(versions, 'current_acceptance', lambda *_: [current])
    d24_sha = contract.digest(adopted) if case != 'stale_subject' else '0' * 64
    d24 = {'status': 'PASS', 'canonical_pass': True, 'current_inputs': True,
           'folder': 'phase2/stage2/12',
           'outputs': [{'rel': str(adopted.relative_to(project)), 'sha256': d24_sha}],
           'result': {'canonical_consumer': {'status': 'PASS'}}}
    monkeypatch.setattr(versions, 'latest_pass', lambda _p, sid:
                        d24 if str(sid) == '12' else None)
    monkeypatch.setattr(design, 'derive_dft_clock_reset', lambda *_:
                        ('clk', 'rst_n', True))
    monkeypatch.setattr(scan, 'load_d09_dft_contract', lambda *_a, **_k: (d09, []))
    monkeypatch.setattr(scan, 'l20_binding_is_current', lambda *_: (True, 'current'))
    monkeypatch.setattr(signoff, 'evaluate_scan_shift_timing', lambda *_: {
        'status': 'PASS', 'required': True, 'constraint': constraint, 'reasons': []})
    monkeypatch.setattr(netlists, 'pnr_consumed_netlist', lambda *_:
                        (adopted, 'post-DFT netlist selected', True))
    monkeypatch.setattr(contract, 'resolve_image', lambda *_: 'neutral-image@sha256:' + '5' * 64)
    monkeypatch.setattr(contract, 'pdk_root_resolution', lambda *_a, **_k:
                        {'path': str(project / 'pdk')})

    launched = []
    def run_prelayout(current_project, _image, _pdk, _top, netlist, sdc, _rtl,
                      *, arm, **_kwargs):
        launched.append({'netlist': Path(netlist), 'sdc': Path(sdc), 'arm': arm})
        folder = current_project / 'phase3/librelane' / arm / '02-openroad-staprepnr'
        put(folder / 'config.json', {'PNR_SDC_FILE': str(Path(sdc).resolve())})
        put(folder / 'state_out.json', {'nl': str(Path(netlist).resolve()), 'metrics': {}})
        put(folder / 'vibeic_receipt.json', {'input': {'step': 'OpenROAD.STAPrePNR'}})
        return folder
    monkeypatch.setattr(prelayout, 'run_prelayout', run_prelayout)
    monkeypatch.setattr(contract, 'validate_step_receipt', lambda *_:
                        {'input': {'step': 'OpenROAD.STAPrePNR'}})

    def judge_sdc(folder, _config, declared_sdc, output):
        doc = {'verdict': 'PASS', 'findings': [], 'corners': {'tt': {}},
               'netlist_sha256': contract.digest(adopted),
               'sdc_sha256': contract.digest(Path(declared_sdc)),
               'state_out_sha256': contract.digest(folder / 'state_out.json')}
        put(output, doc)
        return doc
    def judge_slack(folder, output):
        red = case in ('scan_violation', 'terminal_violation_changed') \
            and 'scan_slack_gate' in output.name
        doc = {'verdict': 'FAIL' if red else 'PASS',
               'findings': ['LL_STA_SETUP_VIOLATION'] if red else [],
               'corners': {'tt': {'setup_ws': {'status': 'MEASURED',
                                                'value': -0.2 if red else 0.2}}},
               'state_out_sha256': contract.digest(folder / 'state_out.json')}
        put(output, doc)
        return doc
    monkeypatch.setattr(prelayout, 'judge_sdc', judge_sdc)
    monkeypatch.setattr(prelayout, 'judge_slack', judge_slack)
    if case == 'missing_scan_sdc':
        scan_sdc.unlink()

    result = front._complete_step10_prelayout(project, 'top', 'neutral', '')
    assert result['verdict'] == expected, result
    assert set(result) == {'verdict', 'detail', 'folder', 'timing_modes_receipt'}
    receipt_path = project / result['timing_modes_receipt']['path']
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == \
        result['timing_modes_receipt']['sha256']
    receipt = json.loads(receipt_path.read_text())
    assert receipt['schema'] == 'vibeic.flow109.d26-timing-modes.v1'
    assert receipt['position'] == 38 and receipt['aggregate_status'] == expected
    assert receipt['functional_baseline']['canonical_pass'] is True
    assert len(launched) == calls
    if calls:
        assert {row['arm'] for row in launched} == {
            'd26_post_scan_functional', 'd26_post_scan_scan'}
        assert all(row['netlist'] == adopted for row in launched)
        functional = next(row for row in launched if row['arm'].endswith('functional'))
        scan_row = next(row for row in launched if row['arm'].endswith('scan'))
        text = functional['sdc'].read_text()
        assert 'create_clock -period 10' in text
        assert 'set_case_analysis 0 [get_ports {test}]' in text
        assert 'set_case_analysis 0 [get_ports {shift}]' in text
        assert 'set_case_analysis 0 [get_ports {sin}]' in text
        assert 'set_case_analysis 0 [get_ports {tck}]' in text
        assert 'set_case_analysis 1 [get_ports {rst_n}]' in text
        assert scan_row['sdc'] == scan_sdc
        assert receipt['scan']['adopted_d24']['sha256'] == contract.digest(adopted)
        assert set(receipt['post_scan_arms']) == {'functional', 'scan'}
    elif case == 'no_scan':
        assert receipt['scan']['status'] == 'NOT_APPLICABLE'
    else:
        assert receipt['scan']['status'] == 'NOT_MEASURED'

    if terminal_expected is not None:
        terminal = {**result, 'detail': 'postcheck terminal'}
        if case == 'terminal_missing':
            receipt_path.unlink()
        elif case in ('terminal_changed', 'terminal_violation_changed'):
            receipt_path.write_text(receipt_path.read_text() + ' ')
        import _delivery_route
        from test_flow109_selection import profile
        assert _delivery_route.admit(project, 'ip') is None
        manifest = project / 'manifest.json'
        manifest.write_text(json.dumps({
            'features': profile('Mapped soft-IP with prestitched scan')}))
        monkeypatch.setattr(front, '_activate_runtime_program_tree', lambda _p: None)
        monkeypatch.setattr(front, '_capture_container_image', lambda *_a, **_k: {
            'verdict': 'PASS'})
        monkeypatch.setattr(front, '_complete_step10_prelayout', lambda *_a, **_k: result)
        monkeypatch.setattr(front, '_complete_step8_postcheck', lambda *_a, **_k: {
            'verdict': 'PASS', 'detail': 'postcheck PASS'})
        monkeypatch.setattr(sys, 'argv', [str(Path(front.__file__)), str(project),
                            '--flow', '109', '--flow109-manifest', str(manifest),
                            '--entry-step', 'D26', '--exit-step', 'D26',
                            '--route', 'ip', '--no-dashboard'])
        expected_rc = {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[terminal_expected]
        assert front._main() == expected_rc
        attempt = next((project / 'reports/flow109/attempts').glob('window-*'))
        finished = json.loads((attempt / 'result.json').read_text())
        assert finished['default_row_status'] == terminal_expected
        component = finished['components'][0]
        summary = json.loads(
            (project / 'reports/orchestrator/vibe_ic_one_shot.json').read_text())
        final = summary['d26_finalization']
        assert final['verdict'] == terminal_expected, final
        if terminal_expected in ('PASS', 'FAIL'):
            assert component['timing_modes_receipt'] == result['timing_modes_receipt']
        else:
            assert 'timing_modes_receipt' not in component
            assert 'D26_TIMING_MODES_RECEIPT_REFUSED' in final['detail']
