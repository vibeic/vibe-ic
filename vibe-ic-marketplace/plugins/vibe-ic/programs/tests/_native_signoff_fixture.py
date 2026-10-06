"""Neutral source protocol inputs driven through the ACTUAL run_chain/judge.

The external process edge writes maintenance State counts, not physical tool
results. No hand-authored producer verdict/receipt and no native signoff claim.
The optional KLayout ownership addition models root's explicit CUT31 API union;
the shipping producer/default dictionaries remain unchanged.
"""
from pathlib import Path
import json
import subprocess

import librelane_contract as contract
import librelane_pv_signoff as pv

IMAGE = 'example.invalid/maintenance@sha256:' + 'a' * 64


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


def producer(project: Path, monkeypatch, half='drc', counts=None, inherited=None,
             missing=(), both_lvs=False, gds_path=None):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    counts = counts or {}
    pdk_root = project / 'maintenance-pdk'
    tree = pdk_root / 'procx'
    tree.mkdir(parents=True, exist_ok=True)
    deck = tree / 'maintenance.deck'
    deck.write_text('neutral source protocol input\n')
    put(project / 'phase3/librelane_switch.json', {
        'steps': {'31': 'librelane', '34': 'librelane', '37': 'direct'},
        'image': IMAGE, 'pdk': 'procx', 'pdk_root_host': str(pdk_root)})
    contract.pdk_root_resolution(project, 'procx', image=IMAGE)
    gds = gds_path or project / 'phase3/stage4/gds/maintenance.gds'
    gds.parent.mkdir(parents=True, exist_ok=True)
    if gds_path is None:
        gds.write_bytes(b'NEUTRAL_PROTOCOL_BYTES_NOT_PHYSICAL_GDS')
    views = {'gds': str(gds)}
    for view in ('def', 'odb', 'nl', 'pnl', 'spice', 'sdc', 'cdl'):
        path = project / f'phase3/librelane/maintenance/input.{view}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'neutral {view} protocol input\n')
        views[view] = str(path)
    state = put(project / 'phase3/librelane/maintenance/initial-state.json', {
        **views, 'metrics': dict(inherited or {})})
    if both_lvs:
        monkeypatch.setitem(pv.PRODUCED, 'KLayout.LVS', ('klayout__lvs_error__count',))
    steps = list(pv.HALVES[half])
    if both_lvs and 'KLayout.LVS' not in steps:
        steps.append('KLayout.LVS')
    configs = {}
    for step in steps:
        configs[step] = put(project / f'phase3/librelane/31-{half}-config/{step}.json', {
            'meta': {'step': step}, 'TECH_FILE': str(deck),
            'MAGIC_EXT_USE_GDS': True, 'MAGIC_EXT_ABSTRACT': False})

    def external_edge(command, **kwargs):
        # run_chain itself owns fingerprint, PDK root and receipt generation.
        step = command[command.index('--id') + 1]
        cfg = Path(command[command.index('-c') + 1])
        before = json.loads(Path(command[command.index('-i') + 1]).read_text())
        folder = Path(command[command.index('-o') + 1])
        put(folder / 'state_in.json', before)
        put(folder / 'config.json', json.loads(cfg.read_text()))
        after = dict(before, metrics=dict(before.get('metrics', {})))
        import librelane_ir_antenna as antenna
        owned = {'OpenROAD.CheckAntennas': antenna.ROUTER_METRICS,
                 'KLayout.Antenna': (antenna.GDS_METRIC,)}
        for key in pv.PRODUCED.get(step, owned.get(step, ())):
            after['metrics'][key] = counts.get(key, 0)
        put(folder / 'state_out.json', after)
        return subprocess.CompletedProcess(command, 0, 'neutral protocol process edge', '')

    monkeypatch.setattr(contract, 'image_capability', lambda *a, **kw: {})
    monkeypatch.setattr(contract, 'openroad_home', lambda *a, **kw: None)
    monkeypatch.setattr(contract, 'run_container', external_edge)
    folders = contract.run_chain(project, IMAGE,
        [(step, configs[step], state) for step in steps if step not in missing],
        mounts=[(tree, '/pdk/procx')], lane=f'31-{half}', pdk_root='/pdk')
    record = project / pv.RECORD_REL.format(half=half)
    scope = {'gds_sha256': pv.digest(gds), 'def_sha256': 'unused-neutral-scope'}
    if half == 'lvs':
        scope.update(magic_ext_use_gds=True, extracted_gds_sha256=pv.digest(gds))
    pv.judge_pv(folders, tuple(steps), record, scope=scope)
    return {'gds': gds, 'folders': folders, 'record': record, 'deck': deck,
            'configs': configs, 'state': state, 'tree': tree}


def finished_producer(project, monkeypatch, counts=None, missing=()):
    # Distinguish the earlier Step31 counts from the final-stream producers.
    # The external process edge closes over this dict; both sets of receipts
    # are still written/judged by the actual Python producer programs.
    initial_counts = {key: 0 for key in (counts or {})}
    info = producer(project, monkeypatch, counts=initial_counts)
    initial_counts.update(counts or {})
    configs = {}
    for step, source in info['configs'].items():
        configs[step] = put(project / f'phase3/librelane/37-config/{step}.json',
                            json.loads(source.read_text()))
    folders = contract.run_chain(project, IMAGE,
        [(step, configs[step], info['state']) for step in ('Magic.DRC', 'KLayout.DRC')
         if step not in missing], mounts=[(info['tree'], '/pdk/procx')],
        namespace='37-magic-final-drc', pdk_root='/pdk')
    contract.judge_step(folders[-1], ['magic__drc_error__count', 'klayout__drc_error__count'],
                        project / 'phase3/librelane/37-magic-final-drc/drc_judgment.json')
    folder = contract.run_chain(project, IMAGE,
        [('KLayout.Density', configs['KLayout.Density'], info['state'])],
        mounts=[(info['tree'], '/pdk/procx')], namespace='37-magic-finish', pdk_root='/pdk')[-1]
    contract.judge_step(folder, ['klayout__density_error__count'],
                        project / 'phase3/librelane/37-magic-density.json',
                        limits={'klayout__density_error__count': {'eq': 0}})
    # This is a neutral selector input (paths/hashes only, no producer PASS).
    source = project / 'phase3/librelane/maintenance/finished.gds'
    source.write_bytes(info['gds'].read_bytes())
    put(project / 'phase3/librelane/37-promotion.json', {
        'selection': 'magic', 'source': str(source), 'source_sha256': pv.digest(source),
        'finished': {'magic': str(source)}, 'canonical': str(info['gds']),
        'canonical_sha256': pv.digest(info['gds'])})
    switch = project / 'phase3/librelane_switch.json'
    doc = json.loads(switch.read_text()); doc['steps']['37'] = 'librelane'; put(switch, doc)
    return info


def antenna_producer(project, monkeypatch, counts=None, missing_router=False):
    import librelane_ir_antenna as antenna
    info = producer(project, monkeypatch, counts=counts)
    switch = project / 'phase3/librelane_switch.json'
    doc = json.loads(switch.read_text()); doc['steps']['26'] = 'librelane'; put(switch, doc)
    routed = project / 'phase3/stage3/pnr/maintenance.def'
    routed.parent.mkdir(parents=True, exist_ok=True)
    routed.write_text('neutral routed DEF input\n')
    original_state = json.loads(info['state'].read_text())
    configs = {}
    for step in (*antenna.ANTENNA_ROUTER_STEPS, *antenna.ANTENNA_GDS_STEPS):
        configs[step] = put(project / f'phase3/librelane/26-config/{step}.json', {
            'meta': {'step': step}, 'KLAYOUT_ANTENNA_RUNSET': str(info['deck'])})
        put(contract.views_path(configs[step]), {'step': step, 'inputs': ['gds'] if step.startswith('KLayout.') else [], 'outputs': []})
    monkeypatch.setattr(antenna, 'resolve_step_configs', lambda *a, **kw: configs)
    original_bridge = contract.state_from_direct
    def bridge(project, image, config, views, output_dir, **kwargs):
        # Supply the neutral ODB as a bridge input. No converter/native tool
        # is being measured; the actual bridge/producer/receipt programs run.
        supplied = dict(views)
        if json.loads(config.read_text())['meta']['step'] == 'OpenROAD.CheckAntennas':
            supplied['odb'] = original_state['odb']
        return original_bridge(project, image, config, supplied, output_dir, **kwargs)
    monkeypatch.setattr(antenna, 'state_from_direct', bridge)
    router = None if missing_router else antenna.run_antenna_router(
        project, IMAGE, info['tree'].parent, 'procx', routed_def=routed,
        netlist=Path(original_state['nl']), sdc=Path(original_state['sdc']))
    gds = antenna.run_antenna_gds(project, IMAGE, info['tree'].parent, 'procx', gds=info['gds'])
    judgment = antenna.judge_antenna(router, gds, {'def': pv.digest(routed), 'gds': pv.digest(info['gds'])})
    import phase3_one_shot_runner as runner
    maintenance_log = '[INFO DRT-0702] Post-route verification: 0 violation(s).\n'
    put(project / 'reports/phase3/antenna_librelane.json', {
        'step': '26', 'mode': 'librelane', 'router': router, 'gds': gds, 'judgment': judgment,
        'def_sha256': pv.digest(routed),
        'routing_incomplete': runner.antenna_routing_incomplete(maintenance_log),
        'route_modified_after_last_verification': runner.antenna_reroute_refusal_after_last_verification(maintenance_log)})
    return info
