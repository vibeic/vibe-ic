"""Current native Step37.3 artefacts and substantive refusal controls."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _native373_current as native
import _physical_current as pc
import gds_xor_check as xor
import librelane_contract as lc
from test_librelane_contract import local_image  # existing attested-image fixture


def retained_local_receipt(tmp_path, local_image, *, change=None):
    """Neutral immutable producer receipt with a distinct 32 GiB frame."""
    project = tmp_path / 'retained-project'
    folder = project / 'phase3/librelane/37.3-compare/02-klayout-xor'
    folder.mkdir(parents=True)
    current = lc.local_image_attestation(local_image.image)
    original = {**current, 'memory': 32 * 1024**3,
                'memory_swap': 32 * 1024**3}
    if change == 'image':
        original['image'] = 'registry.invalid/changed@sha256:' + '1' * 64
    elif change == 'frame':
        original['memory'] = 0
    fingerprint = {'step': 'KLayout.XOR', 'local_image': original}
    files = {
        'state_out.json': {'metrics': {}},
        'input_fingerprint.json': fingerprint,
        'pdk_root.json': {'execution_route': 'LOCAL'},
    }
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value))
    (folder / 'invocation.log').write_text('SOURCE_CONTROL retained rc0 producer\n')
    names = [*files, 'invocation.log']
    (folder / 'vibeic_receipt.json').write_text(json.dumps({
        'input': fingerprint,
        'sha256': {name: pc.digest(folder / name) for name in names}}))
    return project, folder, original


def test_retained_local_producer_frame_is_independent_of_readonly_consumer_budget(
        tmp_path, monkeypatch, local_image):
    launch = json.loads(local_image.receipt.read_text())
    launch['container_inspect']['HostConfig'].update(
        Memory=8 * 1024**3, MemorySwap=8 * 1024**3)
    local_image.receipt.write_text(json.dumps(launch))
    project, folder, original = retained_local_receipt(tmp_path, local_image)
    try:
        result = native._local_execution(project, folder, 'KLayout.XOR', local_image.image)
        observed = {'status': 'ACCEPTED', 'kind': result.get('kind'),
                    'producer_memory': result.get('local_image', {}).get('memory')}
    except (ValueError, lc.Refusal) as exc:
        observed = {'status': 'REFUSED', 'reason': str(exc)}
    assert observed == {'status': 'ACCEPTED', 'kind': 'retained_local_step_receipt',
                        'producer_memory': 32 * 1024**3}
    assert result['kind'] == 'retained_local_step_receipt'
    assert result['local_image'] == original
    assert result['local_image']['memory'] == 32 * 1024**3
    assert lc.local_image_attestation(local_image.image)['memory'] == 8 * 1024**3


@pytest.mark.parametrize('change,reason', [
    ('image', 'NATIVE373_LOCAL_IMAGE_CHANGED'),
    ('frame', 'NATIVE373_RETAINED_FRAME_INVALID'),
    ('stale', 'LL_STEP_OUTPUT_UNBOUND'),
])
def test_retained_local_producer_refuses_changed_identity_frame_or_input(
        tmp_path, local_image, change, reason):
    project, folder, _ = retained_local_receipt(
        tmp_path, local_image, change=change if change != 'stale' else None)
    if change == 'stale':
        fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
        fingerprint['stale'] = True
        (folder / 'input_fingerprint.json').write_text(json.dumps(fingerprint))
    with pytest.raises((ValueError, lc.Refusal), match=reason):
        native._local_execution(project, folder, 'KLayout.XOR', local_image.image)


@pytest.fixture
def project():
    declared = os.environ.get("VIBEIC_XOR373_NATIVE_PROJECT")
    if not declared:
        pytest.skip("native producer artefacts not supplied: NOT_VERIFIED")
    path = Path(declared)
    assert path.is_dir()
    return path


def test_native_ordinary_caller_and_declared_consumer(project):
    result = json.loads((project / "NATIVE_RESULT.json").read_text())
    assert result["ordinary_rows"][0]["status"] == "PASS"
    assert result["gate_rc"] == 0
    assert native.read_current(project)["count"] == 0
    rc, line, doc = xor.judge_receipt(project, xor.REPORT_REL)
    assert rc == 0, line
    assert doc["reference"]["kind"] == "native_stream"
    assert doc["connectivity"]["measurements"][0]["evidence"] == native.REL


@pytest.mark.parametrize("mutation", ["shipped", "reference", "def", "netlist", "sdc", "technology",
                                     "stage", "design", "pdk", "tool", "execution", "argv", "log",
                                     "count", "connectivity", "shipped_identity", "missing_dependency", "material_hash",
                                     "material_unbound", "material_path", "mount", "image", "native_log",
                                     "native_execution", "stream_swapped", "identical_streams"])
def test_current_native_refusal(project, mutation):
    saved = {}
    def edit(path, content):
        path = Path(path)
        saved.setdefault(path, path.read_bytes())
        path.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
    try:
        dep_path = project / native.REL
        dep = json.loads(dep_path.read_text())
        report_path = project / xor.REPORT_REL
        report = json.loads(report_path.read_text())
        current = dep["current"]
        if mutation in ("shipped", "reference"):
            path = project / report["current"]["inputs"][mutation]["path"]
            edit(path, path.read_bytes() + b"changed")
        elif mutation in ("def", "netlist", "sdc", "technology", "log"):
            field = "outputs" if mutation == "log" else "inputs"
            path = project / current[field][mutation]["path"]
            edit(path, path.read_bytes() + b"changed")
        elif mutation in ("stage", "design", "pdk", "tool"):
            current[mutation] = "wrong"
            edit(dep_path, dep)
        elif mutation == "execution":
            current["execution"]["rc"] = 1
            edit(dep_path, dep)
        elif mutation == "argv":
            current["execution"]["argv"] = ["wrong_tool"]
            edit(dep_path, dep)
        elif mutation == "count":
            dep["count"] = 99
            edit(dep_path, dep)
        elif mutation == "connectivity":
            report["connectivity"]["measurements"][0]["evidence_sha256"] = "0" * 64
            edit(report_path, report)
        elif mutation == "shipped_identity":
            report["shipped_sha256_live"] = "0" * 64
            report["connectivity"]["subject_sha256"] = "0" * 64
            edit(report_path, report)
        elif mutation == "missing_dependency":
            edit(dep_path, {})
        elif mutation in ("material_hash", "material_unbound", "material_path"):
            folder = project / dep["folders"][0]
            receipt_path = folder / "vibeic_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            fp = receipt["input"]
            key = next(key for key in fp["config_files"] if "libs.ref" in key)
            if mutation == "material_hash":
                fp["config_files"][key] = "0" * 64
            elif mutation == "material_unbound":
                del fp["config_files"][key]
            else:
                fp["config_files"][str(project / "absent.pdk")] = fp["config_files"].pop(key)
            edit(folder / "input_fingerprint.json", fp)
            receipt["sha256"]["input_fingerprint.json"] = pc.digest(folder / "input_fingerprint.json")
            edit(receipt_path, receipt)
            current["outputs"]["producer_0_vibeic_receipt.json"] = pc.entry(project, receipt_path)
            edit(dep_path, dep)
        elif mutation in ("mount", "image", "native_log", "native_execution"):
            folder = project / dep["folders"][-1]
            if mutation == "mount":
                path = folder / "pdk_root.json"
                record = json.loads(path.read_text())
                record["mounts_under_it"][0][0] = str(project / "wrong_pdk")
                edit(path, record)
            elif mutation == "image":
                path = project / "phase3/librelane_switch.json"
                record = json.loads(path.read_text())
                record["image"] = "wrong"
                edit(path, record)
            elif mutation == "native_log":
                edit(folder / "invocation.log", b"no execution\n")
            else:
                path = project / current["outputs"]["launches"]["path"]
                launches = [json.loads(line) for line in path.read_text().splitlines()]
                launches = [run for run in launches if "KLayout.XOR" not in run["argv"]]
                edit(path, ("\n".join(json.dumps(run) for run in launches) + "\n").encode())
                current["outputs"]["launches"] = pc.entry(project, path)
                edit(dep_path, dep)
        else:
            current["outputs"]["magic_gds"] = current["outputs"]["klayout_gds"]
            if mutation == "stream_swapped":
                report["current"]["inputs"]["reference"] = report["current"]["inputs"]["shipped"]
                edit(report_path, report)
            edit(dep_path, dep)
        # Rebind the actual mutated dependency bytes in the outer comparison.
        # This forces the typed consumer to judge the changed native evidence,
        # rather than allowing only an outer receipt hash to catch the change.
        if dep_path in saved:
            report["current"]["inputs"]["connectivity"] = pc.entry(project, dep_path)
            edit(report_path, report)
        rc, _, _ = xor.judge_receipt(project, xor.REPORT_REL)
        assert rc != 0
    finally:
        for path, content in saved.items():
            path.write_bytes(content)


@pytest.mark.parametrize("scenario", ["current", "changed", "missing"])
def test_material_bytes_and_mount_are_read(tmp_path, scenario):
    root = tmp_path / "real_mount"
    root.mkdir()
    deck = root / "declared.deck"
    deck.write_text("declared fixture material\n")
    config = {"deck": "/pdk/declared.deck"}
    mounts = [(root, "/pdk")]
    first = lc._current_config_material(config, mounts)
    assert first == {str(deck): pc.digest(deck)}
    if scenario == "changed":
        deck.write_text("changed declared fixture material\n")
        assert lc._current_config_material(config, mounts) != first
    elif scenario == "missing":
        deck.unlink()
        with pytest.raises(lc.Refusal, match="LL_CONFIG_MATERIAL_MISSING"):
            lc._current_config_material(config, mounts)


def test_real_geometry_change_is_measured_failure(project, tmp_path):
    """A native GDS mutation must reach the measured-defect arm of the gate."""
    report = json.loads((project / xor.REPORT_REL).read_text())
    shipped = project / report["current"]["inputs"]["shipped"]["path"]
    paths = [shipped, project / xor.REPORT_REL, project / "reports/phase3/gds_xor_native.log",
             project / "reports/phase3/gds_xor_native.rb"]
    saved = {path: path.read_bytes() for path in paths}
    script = project / "reports/phase3/xor_reverse_geometry.py"
    script.write_text('import klayout.db as db,sys\n'
                      'p=sys.argv[1]; layout=db.Layout(); layout.read(p)\n'
                      'layout.top_cell().shapes(layout.layer(68,20)).insert(db.Box(1000,1000,1400,1400))\n'
                      'layout.write(p)\n')
    image = native.read_current(project)["image"]
    try:
        argv = ["docker", "run", "--rm", "--network", "none", "--cpus", "2", "--memory", "6g",
                "--memory-swap", "6g", "-v", f"{project}:{project}", image, "--skip",
                "/usr/bin/time", "-v", "python3", str(script), str(shipped)]
        cp = lc.run_container(argv, supervised=True, log=project / "reports/phase3/xor_reverse_geometry.log")
        (project / "reports/phase3/xor_reverse_geometry.log").write_text(cp.stdout + "\n" + cp.stderr)
        assert cp.returncode == 0
        assert xor.main([str(project), "--json", str(project / xor.REPORT_REL)]) == 1
        rc, _, measured = xor.judge_receipt(project, xor.REPORT_REL)
        assert rc == 1
        assert measured["design__xor_difference__count"] > 0
        (project / "GEOMETRY_REVERSE.json").write_text(json.dumps(measured, indent=2))
    finally:
        for path, content in saved.items():
            path.write_bytes(content)
        script.unlink()


@pytest.mark.parametrize('different', [False, True], ids=['equal', 'different'])
def test_launcher_main_measures_neutral_geometry_and_current_consumer(tmp_path, monkeypatch, different):
    """Actual adapter/native geometry/current producer; transport SOURCE_CONTROL.

    No complete three-stream/PDK connectivity is claimed. A geometric zero
    therefore remains NOT_MEASURED at the composed canonical consumer.
    """
    from types import SimpleNamespace
    import shutil
    import klayout.db as db
    import _klayout_launch as kl
    import _native373_docker as launcher

    project = tmp_path / 'component'
    pnr = project / 'phase3/stage3/pnr'
    shipped = project / 'phase3/stage4/gds/neutral_top.gds'
    reference = pnr / 'reference.oas'
    for path in (pnr, shipped.parent, project / 'reports/phase3'):
        path.mkdir(parents=True, exist_ok=True)
    for path, extra in ((reference, False), (shipped, different)):
        layout = db.Layout()
        cell = layout.create_cell('neutral_top')
        layer = layout.layer(1, 0)
        cell.shapes(layer).insert(db.Box(0, 0, 1000, 1000))
        if extra:
            cell.shapes(layer).insert(db.Box(2000, 0, 3000, 1000))
        layout.write(str(path))
    (pnr / 'routed.def').write_text('VERSION 5.8 ;\nDESIGN neutral_top ;\nEND DESIGN\n')
    (project / 'reports/phase3/technology_units.json').write_text(json.dumps({
        'pdk': 'neutral_geometry', 'scope': 'SOURCE_CONTROL metadata; no PDK signoff'}))
    # Two actual file formats preserve equal geometry but distinct bytes.
    assert pc.digest(shipped) != pc.digest(reference)
    inputs = {str(p.relative_to(project)): pc.digest(p) for p in
              (shipped, reference, pnr / 'routed.def', project / 'reports/phase3/technology_units.json')}
    image = os.environ['VIBEIC_EDA_IMAGE']
    journal = project / 'launcher.jsonl'
    monkeypatch.setenv('VIBEIC_NATIVE373_IMAGE', image)
    monkeypatch.setenv('VIBEIC_NATIVE373_LAUNCH_LOG', str(journal))
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    host = kl.HostRunner(shutil.which('klayout'), ['-b', '-r'])
    real_run = host.run
    native_calls = []

    def through_adapter(script, env, *, path_keys=(), timeout=1800):
        observed = []
        def transport(requested):
            # Docker delegation alone is controlled; the existing native
            # launcher executes KLayout and its unchanged XOR recipe.
            native_argv = [host._bin, *host._flags, str(script)]
            value = real_run(script, env, path_keys=path_keys, timeout=timeout)
            observed.append(value)
            native_calls.append({'requested_docker_argv': requested,
                                 'actual_native_argv': native_argv,
                                 'native_rc': value[0], 'stdout': value[1], 'stderr': value[2]})
            host.execution = {'rc': value[0], 'argv': native_argv}
            return SimpleNamespace(returncode=value[0])
        flags = ['run', '--rm', '--memory', '4g', '--cpus', '2', '--network', 'none']
        command = ['-b', '-r', str(script)]
        args = ([*flags, '--entrypoint', host._bin, image, *command] if different else
                [*flags, image, '--skip', host._bin, *command])
        with monkeypatch.context() as patcher:
            patcher.setattr(launcher, 'subprocess', SimpleNamespace(run=transport))
            patcher.setattr(sys, 'argv', [str(Path(launcher.__file__)), *args])
            rc = launcher.main()
        value = observed[-1] if observed else (rc, '', '')
        return rc, value[1], value[2]

    monkeypatch.setattr(host, 'run', through_adapter)
    monkeypatch.setattr(kl, 'find_runner', lambda *a, **kw: host)
    # This component does not supply an actual full Magic/PDK stream chain.
    def unsupported_chain(*args, **kwargs):
        raise ValueError('SOURCE_CONTROL component has no full three-stream/PDK chain')
    monkeypatch.setattr(native, 'produce', unsupported_chain)
    monkeypatch.setattr(xor, 'resolve_reference', lambda *a: (
        reference, 'authored component', {'kind': 'component_source_control',
                                        'path': str(reference.relative_to(project))}))
    report_path = project / xor.REPORT_REL
    producer_rc = xor.main([str(project), '--json', str(report_path)])
    before = pc.digest(report_path)
    consumer_rc, line, report = xor.judge_receipt(project, xor.REPORT_REL)
    launches = [json.loads(v) for v in journal.read_text().splitlines()] if journal.is_file() else []
    refusal = pc.validate(project, report.get('current'), step='37.3', stage='stage4',
                          tools=('klayout',),
                          required_inputs=('shipped', 'reference', 'def', 'technology', 'recipe'),
                          required_outputs=('log',), marker='XOR_DONE')
    result = {'input_role': 'SOURCE_CONTROL geometry/transport/unsupported antecedent',
              'inputs': inputs, 'different': different, 'native_calls': native_calls,
              'launches': launches, 'producer_rc': producer_rc, 'consumer_rc': consumer_rc,
              'consumer_line': line, 'current_refusal': refusal, 'report': report,
              'consumer_read_only': pc.digest(report_path) == before}
    (project / 'component_control.json').write_text(json.dumps(result, indent=2) + '\n')
    assert len(native_calls) == len(launches) == 1, result
    assert native_calls[0]['native_rc'] == launches[0]['rc'] == 0
    assert launches[0]['argv'] == native_calls[0]['requested_docker_argv']
    argv = launches[0]['argv']
    assert argv[argv.index(image) + 1:argv.index(image) + 5] == [
        '--skip', '/usr/bin/time', '-v', host._bin]
    assert argv[argv.index('--cpus') + 1] == '2' and argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index('--memory') + 1] == argv[argv.index('--memory-swap') + 1] == '4g'
    assert not refusal, result
    assert report['verdict'] == ('FAIL' if different else 'PASS'), result
    assert report['design__xor_difference__count'] == (1 if different else 0), result
    assert producer_rc == (1 if different else 0), result
    assert consumer_rc == (1 if different else 2), result
    assert result['consumer_read_only']


@pytest.mark.parametrize('mutation', ['current', 'changed-nl', 'missing-nl', 'changed-state'])
def test_default_stream_producer_and_reader_use_bound_filled_views(
        tmp_path, monkeypatch, mutation):
    """Source control: actual fill receipt and current reader, neutral tools.

    The upstream promotion selection and native process edges are controlled;
    fill handoff validation, receipt/output hashes and both source consumers run.
    No geometry, native stream measurement or canonical Step37.3 PASS is claimed.
    """
    import execution_policy
    import librelane_fill_dfm as fill
    import _default_backend_fixtures as fixtures
    import _stream_input_record as stream_inputs

    monkeypatch.setattr(fixtures, 'IMAGE', os.environ['VIBEIC_EDA_IMAGE'])
    project = tmp_path / 'component'
    pnr = project / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    routed = pnr / 'routed.def'
    routed.write_text('VERSION 5.8 ;\nDESIGN package_shell ;\n'
                      'UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 10000 10000 ) ;\nEND DESIGN\n')
    old_nl = pnr / 'logical_source.v'
    old_nl.write_text('module package_shell(input a, output z); assign z=a; endmodule\n')
    old_sdc = pnr / 'constraint.sdc'
    old_sdc.write_text('# SOURCE_CONTROL routed constraints\n')
    record = fixtures.fill_record(project, subject=routed)
    folder = Path(record['state']).parent
    netlist, sdc = folder / 'filled_logic.v', folder / 'filled_clock.sdc'
    netlist.write_text(old_nl.read_text() + '// SOURCE_CONTROL filled producer view\n')
    sdc.write_text(old_sdc.read_text() + '# SOURCE_CONTROL filled producer view\n')
    before = {'def': str(routed), 'nl': str(old_nl), 'sdc': str(old_sdc), 'metrics': {}}
    after = {'def': record['filled_def'], 'nl': str(netlist), 'sdc': str(sdc), 'metrics': {}}
    _, binding = fixtures.producer(project, fill.ODB_FILL_STEP, before, after,
        lane='34/01-openroad-fillinsertion', name='package_shell')
    record.update(binding=binding, state_sha256=pc.digest(Path(record['state'])))
    fixtures.consume_fill(project, record)
    fill.update_record(project, 'odb', {'shipped': 'librelane', 'tool': record})
    filled = pnr / 'filled.def'
    pointer = {'filled_def': str(filled), 'pnr_gds': str(pnr / 'logical_alias.gds')}
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project: pointer)
    fill.validate_fill_consumption(project)
    fixtures.put(project / 'reports/phase3/technology_units.json', {'pdk': 'neutral'})
    recipe = pnr / 'stream_out.py'
    recipe.write_text('# SOURCE_CONTROL promotion metadata\n')
    readset = stream_inputs.build(engine='klayout', output=Path(pointer['pnr_gds']),
        top='package_shell', project=project, project_c=str(project), recipe=recipe,
        def_file=filled, files={}, scalars={}, rcfile=None, hashes={})
    readset['native_cli'] = {'inputs': []}
    stream_inputs.write(Path(pointer['pnr_gds']), readset)
    monkeypatch.setattr(lc, 'pdk_root_resolution', lambda *a, **kw: {
        'path': str(project / 'fixture_pdk')})
    monkeypatch.setattr(native.pv, 'tech_lef_overlay', lambda project: None)
    calls = []

    def configs(project, image, pdk, steps, **kwargs):
        assert kwargs['overlay']['VERILOG_FILES'][0] == [str(netlist)]
        assert kwargs['overlay']['FALLBACK_SDC'][0] == str(sdc)
        return {step: fixtures.put(project / native.CONFIG / (step + '.json'), {
            'meta': {'step': step}, 'DESIGN_NAME': 'package_shell', 'PDK': 'neutral'})
            for step in steps}

    def bridge(project, image, config, views, output, **kwargs):
        assert views == {'def': filled, 'nl': netlist, 'sdc': sdc}
        return fixtures.put(output / 'initial.json', {k: str(v) for k, v in views.items()})

    def chain(project, image, steps, **kwargs):
        current = json.loads(Path(steps[0][2]).read_text())
        folders = []
        for step, config, _ in steps:
            target = project / 'phase3/librelane' / kwargs['lane'] / ('01-' + step.lower())
            target.mkdir(parents=True, exist_ok=True)
            after = dict(current)
            if step in ('Magic.StreamOut', 'KLayout.StreamOut'):
                view = 'mag_gds' if step.startswith('Magic') else 'klayout_gds'
                gds = target / (view + '.gds')
                gds.write_text('SOURCE_CONTROL ' + step + '\n')
                after[view] = str(gds)
            else:
                after['metrics'] = {native.KEY: 0}
                (target / 'xor.xml').write_text(
                    '<report-database><top-cell>package_shell</top-cell><description>'
                    f"XOR {after['mag_gds']} vs. {after['klayout_gds']}"
                    '</description><items/></report-database>')
            target, _ = fixtures.producer(project, step, current, after,
                lane=str(target.relative_to(project / 'phase3/librelane')),
                config_folder='37.3-config', name='package_shell')
            argv = ['docker', 'run', image, '--skip', 'python3', '--id', step,
                    '-o', str(target), '-c', str(config), '--pdk-root', '/pdk']
            (target / 'invocation.log').write_text(
                'SOURCE_CONTROL process boundary --id ' + step + ' \nExit status: 0\n')
            receipt = json.loads((target / 'vibeic_receipt.json').read_text())
            receipt['sha256']['invocation.log'] = pc.digest(target / 'invocation.log')
            if step == 'KLayout.XOR':
                receipt = lc.bind_xor_report(target, receipt)
            fixtures.put(target / 'vibeic_receipt.json', receipt)
            journal = Path(os.environ['VIBEIC_NATIVE373_LAUNCH_LOG'])
            with journal.open('a') as f:
                f.write(json.dumps({'argv': argv, 'rc': 0}) + '\n')
            current = after
            folders.append(target)
            calls.append(step)
        return folders

    monkeypatch.setattr(lc, 'resolve_step_configs', configs)
    monkeypatch.setattr(lc, 'state_from_direct', bridge)
    monkeypatch.setattr(lc, 'run_chain', chain)
    monkeypatch.setattr(native.native, 'count_row', lambda *a, **kw: {'value': 0})
    produced = native.produce(project, filled)
    assert calls == list(native.STEPS)
    assert produced['current']['inputs']['netlist'] == pc.entry(project, netlist)
    assert produced['current']['inputs']['sdc'] == pc.entry(project, sdc)
    assert not (pnr / 'package_shell_pnr.v').exists()
    assert native.read_current(project) == produced
    if mutation == 'current':
        return
    if mutation == 'changed-nl':
        netlist.write_text('module wrong; endmodule\n')
    elif mutation == 'missing-nl':
        netlist.unlink()
    else:
        changed = json.loads(Path(record['state']).read_text())
        changed['nl'] = str(old_nl)
        fixtures.put(Path(record['state']), changed)
    with pytest.raises((ValueError, OSError, lc.Refusal)):
        native.read_current(project)
    with pytest.raises((ValueError, OSError, lc.Refusal)):
        native.produce(project, filled)
    assert calls == list(native.STEPS), 'changed authority must refuse before new native work'
