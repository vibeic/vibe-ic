#!/usr/bin/env python3
"""Replay native incremental ADC PVT and mismatch cohorts after actual PEX.

Preparation creates isolated runtime input views. Every performance number
comes from the existing native capture decoder; an OP value is not ENOB.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import analog_a7_post_layout_emit as a7
import analog_bound_measurements as bound
import analog_incremental_capture as capture
import analog_incremental_pvt as pvt
import analog_incremental_statistics as stats
import analog_mc_yield_run as mc

KIND = 'incremental_capture_post_layout'


def _view(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': bound.sha(path)}


def _current(views):
    if not isinstance(views, dict) or not views or any(not isinstance(row, dict) for row in views.values()):
        return False
    unique = {(row.get('path'), row.get('sha256')): row for row in views.values()}
    return stats._current({str(index): row for index, row in enumerate(unique.values())})


def _result(status, detail, outputs=(), **fields):
    return {'status': status, 'detail': detail, 'outputs': [str(path) for path in outputs], **fields}


def _read(path):
    return json.loads(Path(path).read_text())


def _pre_plan(project, block, reference, source, common):
    if not _current({'pre_pvt_manifest': reference}):
        raise ValueError('PRE PVT plan is absent or changed')
    plan = _read(reference['path'])
    if plan.get('project') != str(project) or plan.get('block') != block:
        raise ValueError('PRE PVT plan belongs to another project/block')
    pvt._validate_manifest(plan)
    if any(plan['native_inputs'].get(role) != source[role] for role in ('netlist', 'testbench', 'spec', 'topology')) \
            or plan['common_settings'] != common:
        raise ValueError('PRE PVT source/method differs from the declared source inputs')
    return plan


def _wrapped_body(block, source_net, raw, destination):
    ports = a7.subckt_ports(source_net.read_text(), block)
    if not ports:
        raise ValueError('source DUT interface is absent')
    header = []
    for line in bound.contextual_template(source_net.read_text(), source_net.parent).splitlines():
        if re.match(r'^\s*\.subckt\b', line, re.I):
            break
        header.append(line)
    whole, mapping = a7.post_layout_netlist(block, ports, raw, header)
    lines = whole.splitlines()
    begin = [index for index, line in enumerate(lines)
             if re.match(r'^\s*\.subckt\s+' + re.escape(block + '__rcx') + r'\s', line, re.I)]
    if len(begin) != 1:
        raise ValueError('actual extraction body is ambiguous')
    finish = next((index for index in range(begin[0] + 1, len(lines))
                   if re.match(r'^\s*\.ends\b', lines[index], re.I)), None)
    if finish is None:
        raise ValueError('actual extraction body is unterminated')
    body_path = destination / (block + '__rcx.sp')
    body = '\n'.join(lines[begin[0]:finish + 1]) + '\n'
    # This is the existing A7 wrapper with the same body in an included file.
    # Hierarchy, electrical cards, RC elements and port connections are retained.
    wrapper = '\n'.join(lines[:begin[0]] + ['.include "' + str(body_path) + '"'] + lines[finish + 1:]) + '\n'
    return wrapper, body, mapping


def _source_reset_observation(block, source_net, source_tb, raw, corner, original_reset, selector):
    """Choose an actual retained gate; pre-R aliases never short positive R."""
    import analog_a5_layout_emit as layout
    from _analog_producer_common import layout_netlist_identity
    if corner is None:
        raise ValueError('actual extracted reset node is absent; source-terminal mapping inputs are required')
    instance, separator, logical = original_reset.partition('.')
    if not separator or instance.casefold() not in a7.dut_instances(source_tb.read_text(), block):
        raise ValueError('logical reset does not identify the actual source DUT')
    record_path = source_net.parent / 'layout_provenance.json'
    if not record_path.is_file():
        raise ValueError('actual extracted reset node is absent; source-to-layout identity is unavailable')
    record = _read(record_path)
    if record.get('producer') != 'analog_a5_layout_emit' or record.get('result') != 'OK' \
            or layout_netlist_identity(record, source_net.read_text())[0] != 'MATCH':
        raise ValueError('actual source-to-layout device identity is unavailable')
    mag = Path(record.get('layout_mag') or source_net.parent / 'layout.mag')
    ext = Path(corner.get('step_dir') or Path(corner['extracted_netlist']).parent) / 'extraction_full' / (block + '.ext')
    if not mag.is_file() or not ext.is_file():
        raise ValueError('actual A5 layout/Magic extraction identity files are absent')
    uses = {}
    for line in mag.read_text().splitlines():
        tokens = shlex.split(line)
        if len(tokens) >= 3 and tokens[0] == 'use':
            uses.setdefault(tokens[2].casefold(), []).append(tokens[1].casefold())
    selected, _files = mc._statistical_closure(source_net.parent, source_net, None)
    headers = {}
    for line in a7._joined_lines(selected):
        tokens = line.split()
        if len(tokens) >= 3 and tokens[0].casefold() == '.subckt':
            pins = re.split(r'\s+(?:params?:|[A-Za-z_]\w*\s*=)', ' '.join(tokens[2:]), maxsplit=1, flags=re.I)[0]
            headers.setdefault(tokens[1].casefold(), set()).add(tuple(pin.casefold() for pin in pins.split()))
    _name, _ports, devices = layout.parse_netlist(source_net)
    parent, ext_nodes = {}, set()
    def root(node):
        node = node.casefold()
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = root(parent[node])
        return parent[node]
    for line in ext.read_text().splitlines():
        tokens = shlex.split(line)
        if tokens and tokens[0] == 'node' and len(tokens) >= 2:
            ext_nodes.add(tokens[1].casefold())
        if tokens and tokens[0] == 'equiv' and len(tokens) == 3:
            ext_nodes.update(token.casefold() for token in tokens[1:])
            parent[root(tokens[2])] = root(tokens[1])
    aliases, candidates = [], []
    for index, device in enumerate(devices):
        options = headers.get(device['model'].casefold(), set())
        if len(options) != 1:
            if logical.casefold() in (net.casefold() for net in device['nets']):
                raise ValueError('actual source device terminal order is ambiguous')
            continue
        pins = next(iter(options))
        if len(pins) != len(device['nets']):
            raise ValueError('actual source device terminal count is ambiguous')
        for pin, net in zip(pins, device['nets']):
            if net.casefold() == logical.casefold():
                aliases.append(f'd{index}.{pin}')
                if pin == 'g':
                    candidates.append((index, device, f'd{index}.G'))
    raw_ports, raw_internal = a7.rcx_nets(raw, block)
    raw_nodes = raw_ports | raw_internal
    for index, device, node in candidates:
        if selector is not None and selector != {'device': device['name'], 'terminal': 'g'}:
            continue
        if node.casefold() not in raw_nodes or node.casefold() not in ext_nodes:
            continue
        cells = uses.get(f'd{index}', [])
        if len(cells) != 1 or not (cells[0] == device['model'].casefold() or cells[0].startswith(device['model'].casefold() + '_')):
            raise ValueError('actual layout instance does not identify the source model')
        component = root(node)
        if any(root(alias) != component for alias in aliases):
            raise ValueError('source reset fanout lacks native pre-resistance connectivity evidence')
        for other_index, other in enumerate(devices):
            options = headers.get(other['model'].casefold(), set())
            if len(options) != 1:
                continue
            for pin, net in zip(next(iter(options)), other['nets']):
                if f'd{other_index}.{pin}'.casefold() in parent and root(f'd{other_index}.{pin}') == component \
                        and net.casefold() != logical.casefold():
                    raise ValueError('native pre-resistance component joins different source nets')
        return instance + '.' + node, {'kind': 'source_labeled_conductor', 'logical_reset': original_reset,
            'source_device': device['name'], 'source_terminal': 'g', 'layout_instance': f'd{index}',
            'native_node': node, 'pre_resistance_aliases': aliases,
            'selection': 'explicit source gate' if selector is not None else 'first retained source gate in A5 card order',
            'scope': 'one source-labeled physical conductor observation; distributed positive resistors retained; transistor gates and fanouts not declared equipotential',
            'supporting_inputs': {'layout_provenance': _view(record_path), 'layout_mag': _view(mag),
                                 'native_ext': _view(ext)}}
    raise ValueError('actual extracted reset node is absent at the selected source gate')


def _post_template(block, source_net, source_tb, post_net, raw, mapping, original_reset, *, corner=None, selector=None, observation=None):
    text = a7.post_layout_testbench(source_tb.read_text(), block, '"' + str(post_net) + '"', source_tb.parent, post_net.parent)
    ports, internal = a7.rcx_nets(raw, block)
    text, dropped = a7.remap_probes(text, block, ports, internal, mapping)
    reset_context, reset_dropped = a7.remap_probes(text + '\n.save v(' + original_reset + ')',
        block, ports, internal, mapping)
    reset = reset_context.splitlines()[-1]
    match = re.fullmatch(r'\s*\.save\s+v\(([^()]+)\)\s*', reset)
    proof = {'kind': 'retained_logical_node', 'logical_reset': original_reset}
    if not match or reset_dropped or reset.lstrip().startswith('*'):
        native_reset, proof = _source_reset_observation(block, source_net, source_tb, raw, corner, original_reset, selector)
        reset_context, _drop = a7.remap_probes(text + '\n.save v(' + native_reset + ')', block, ports, internal, mapping)
        match = re.fullmatch(r'\s*\.save\s+v\(([^()]+)\)\s*', reset_context.splitlines()[-1])
        if not match:
            raise ValueError('actual physical reset observation cannot be represented by the native capture')
    if observation is not None:
        observation.update(proof)
    return text, match[1], dropped


def _physical_transfer_gate(block, source_net, source_tb, raw, corner, device, logical):
    """Observe the MOS gate itself, retaining every distributed resistor."""
    import analog_a5_layout_emit as layout
    import analog_lvs_comparison_prep as calls

    def mos_cards(text):
        result = []
        for line in a7._joined_lines(text):
            parts = line.split()
            if not parts:
                continue
            if parts[0].lower().startswith('x'):
                call = calls._split_call(' '.join(parts[1:]))
                if call and len(call[0]) == 4:
                    result.append((parts[0], call[0], call[1]))
            elif parts[0].lower().startswith('m') and len(parts) >= 6:
                result.append((parts[0], parts[1:5], parts[5]))
        return result

    source_cards = [row for row in mos_cards(source_net.read_text())
                    if [node.casefold() for node in row[1]] == [node.casefold() for node in device['nets']]]
    if len(source_cards) != 1:
        raise ValueError('source transfer switch card is absent or ambiguous: ' + device['name'])
    source_card = source_cards[0]
    if source_card[0].casefold().startswith('x'):
        closure, _ = mc._statistical_closure(source_net.parent, source_net, None)
        headers = []
        for line in a7._joined_lines(closure):
            tokens = line.split()
            if len(tokens) >= 3 and tokens[0].casefold() == '.subckt' and tokens[1].casefold() == source_card[2].casefold():
                pins = re.split(r'\s+(?:params?:|[A-Za-z_]\w*\s*=)',
                    ' '.join(tokens[2:]), maxsplit=1, flags=re.I)[0]
                headers.append(tuple(pin.casefold() for pin in pins.split()))
        if not headers or set(headers) != {('d', 'g', 's', 'b')}:
            raise ValueError('transfer MOS model does not declare d/g/s/b terminal order')
    raw_cards = mos_cards(raw)
    ports, internal = a7.rcx_nets(raw, block)
    raw_nodes = {node.casefold() for node in ports | internal}
    parent = {}

    def root(node):
        node = node.casefold()
        parent.setdefault(node, node)
        trail = []
        while parent[node] != node:
            trail.append(node)
            node = parent[node]
        for previous in trail:
            parent[previous] = node
        return node

    for line in a7._joined_lines(raw):
        tokens = line.split()
        if len(tokens) == 4 and tokens[0].casefold().startswith('r'):
            parent[root(tokens[2])] = root(tokens[1])
    instance = logical.partition('.')[0]
    if instance.casefold() not in a7.dut_instances(source_tb.read_text(), block):
        raise ValueError('transfer observation does not identify the actual source DUT')
    # Some extractors retain both instance identity and logical conductor
    # names. Match connectivity; do not assume a resistor makes equal voltage.
    direct = [row for row in raw_cards if row[0].casefold() == source_card[0].casefold()
              and row[2].casefold() == source_card[2].casefold()
              and all(node.casefold() in raw_nodes for node in source_card[1])
              and [root(node) for node in row[1]] == [root(node) for node in source_card[1]]]
    if len(direct) == 1:
        return instance + '.' + direct[0][1][1], {
            'kind': 'retained_native_device_terminal', 'source_device': device['name'],
            'source_terminal': 'g', 'native_instance': direct[0][0],
            'native_node': direct[0][1][1], 'supporting_inputs': {},
            'scope': 'actual retained MOS gate; distributed resistors are not collapsed'}
    if len(direct) > 1:
        raise ValueError('native transfer switch identity is ambiguous')

    # Reuse the existing source/layout/native-ext identity seam, then resolve
    # the selected device terminal beyond its positive interconnect resistors.
    from _analog_producer_common import layout_netlist_identity
    record_path = source_net.parent / 'layout_provenance.json'
    if corner is None or not record_path.is_file():
        raise ValueError('actual transfer terminal requires source-to-layout identity')
    record = _read(record_path)
    if record.get('producer') != 'analog_a5_layout_emit' or record.get('result') != 'OK' \
            or layout_netlist_identity(record, source_net.read_text())[0] != 'MATCH':
        raise ValueError('actual source-to-layout transfer identity is unavailable')
    mag = Path(record.get('layout_mag') or source_net.parent / 'layout.mag')
    ext = Path(corner.get('step_dir') or Path(corner['extracted_netlist']).parent) / 'extraction_full' / (block + '.ext')
    if not mag.is_file() or not ext.is_file():
        raise ValueError('actual transfer layout/native extraction identity is absent')
    support = {'supporting_inputs': {'layout_provenance': _view(record_path),
        'layout_mag': _view(mag), 'native_ext': _view(ext)}}
    _name, _pins, devices = layout.parse_netlist(source_net)
    selected = [(index, row) for index, row in enumerate(devices)
                if row['name'].casefold() == device['name'].casefold()]
    if len(selected) != 1 or selected[0][1]['model'].casefold() != source_card[2].casefold():
        raise ValueError('source transfer switch has no unique A5 device identity')
    index, selected_device = selected[0]
    mag = Path(support['supporting_inputs']['layout_mag']['path'])
    uses = [shlex.split(line)[1] for line in mag.read_text().splitlines()
            if line.startswith('use ') and len(shlex.split(line)) >= 3
            and shlex.split(line)[2].casefold() == f'd{index}']
    if len(uses) != 1 or not (uses[0].casefold() == selected_device['model'].casefold()
            or uses[0].casefold().startswith(selected_device['model'].casefold() + '_')):
        raise ValueError('selected transfer layout instance does not identify its source model')
    ext_parent = {}

    def ext_root(node):
        node = node.casefold()
        ext_parent.setdefault(node, node)
        trail = []
        while ext_parent[node] != node:
            trail.append(node)
            node = ext_parent[node]
        for previous in trail:
            ext_parent[previous] = node
        return node

    ext = Path(support['supporting_inputs']['native_ext']['path'])
    for line in ext.read_text().splitlines():
        tokens = shlex.split(line)
        if tokens and tokens[0] == 'node' and len(tokens) >= 2:
            ext_root(tokens[1])
        elif tokens and tokens[0] == 'equiv' and len(tokens) == 3:
            ext_parent[ext_root(tokens[2])] = ext_root(tokens[1])
    expected = []
    for terminal in 'dgsb':
        alias = f'd{index}.{terminal}'.casefold()
        if alias not in ext_parent:
            raise ValueError('selected transfer terminal lacks native pre-resistance identity')
        component = ext_root(alias)
        anchors = {root(node) for node in list(ext_parent) if node in raw_nodes and ext_root(node) == component}
        if len(anchors) != 1:
            raise ValueError('selected transfer terminal has ambiguous extracted connectivity')
        expected.append(next(iter(anchors)))
    for left in range(4):
        for right in range(left + 1, 4):
            if source_card[1][left].casefold() != source_card[1][right].casefold() and expected[left] == expected[right]:
                raise ValueError('native interconnect joins different transfer source nets')
    found = [row for row in raw_cards if row[2].casefold() == selected_device['model'].casefold()
             and root(row[1][1]) == expected[1] and root(row[1][3]) == expected[3]
             and {root(row[1][0]), root(row[1][2])} == {expected[0], expected[2]}]
    if len(found) != 1:
        raise ValueError('actual transfer MOS gate is absent or ambiguous after extraction')
    return instance + '.' + found[0][1][1], {
        'kind': 'source_physical_device_terminal', 'source_device': device['name'],
        'source_terminal': 'g', 'layout_instance': f'd{index}',
        'native_instance': found[0][0], 'native_node': found[0][1][1],
        'supporting_inputs': support['supporting_inputs'],
        'scope': 'actual MOS gate selected by source/layout/terminal connectivity; positive resistors retained'}


def _post_transfer_observations(block, source_net, source_tb, topology, raw, corner, mapping, reset):
    timing = capture._transfer_timing(topology, reset)
    devices = {device['name']: device for device in topology['devices']}
    ports, internal = a7.rcx_nets(raw, block)
    nodes, observations = {}, {}
    for group in timing['groups']:
        for polarity in ('n', 'p'):
            switch = group[polarity + '_switch']
            if switch in nodes:
                continue
            logical = group[polarity + '_gate'][2:-1]
            native, proof = _physical_transfer_gate(
                block, source_net, source_tb, raw, corner, devices[switch], logical)
            text, _dropped = a7.remap_probes(source_tb.read_text() + '\n.save v(' + native + ')',
                block, ports, internal, mapping)
            match = re.fullmatch(r'\s*\.save\s+v\(([^()]+)\)\s*', text.splitlines()[-1])
            if not match:
                raise ValueError('actual extracted transfer gate cannot be observed')
            nodes[switch], observations[switch] = match[1], proof
    return {'nodes': nodes, 'observations': observations}


def _make_style(project, block, source, common, corner, root, pre_plan, image, native_binary, reset_observation):
    study = root / 'project'
    paths = pvt._paths(study, block)
    paths['netlist'].parent.mkdir(parents=True)
    raw = Path(corner['extracted_netlist']).read_text()
    wrapper, body, mapping = _wrapped_body(block, Path(source['netlist']['path']), raw, paths['netlist'].parent)
    body_path = paths['netlist'].with_name(block + '__rcx.sp')
    body_path.write_text(body)
    paths['netlist'].write_text(wrapper)
    observation = {}
    template, reset, dropped = _post_template(block, Path(source['netlist']['path']),
        Path(source['testbench']['path']), paths['netlist'], raw, mapping, common['reset_node'],
        corner=corner, selector=reset_observation, observation=observation)
    paths['testbench'].write_text(template)
    for role in ('spec', 'topology'):
        paths[role].symlink_to(source[role]['path'])
    transfer = _post_transfer_observations(block, Path(source['netlist']['path']),
        Path(source['testbench']['path']), _read(source['topology']['path']), raw, corner, mapping, common['reset_node'])
    effective = {**common, 'testbench': str(paths['testbench']), 'reset_node': reset,
                 'transfer_gate_nodes': transfer['nodes']}
    if native_binary:
        effective['native_binary'] = native_binary
    settings = root / 'common.json'
    capture.write_json(settings, effective)
    plan = pvt.prepare(study, block, settings, root / 'pvt', Path(pre_plan['native_inputs']['model_lib']['path']),
        pre_plan['process_sections'], image=image, reference_ports=pre_plan['reference_ports'])
    plan_path = root / 'pvt-manifest.json'
    capture.write_json(plan_path, plan)
    return {'style': corner['style'], 'project': str(study), 'settings': _view(settings),
        'native_inputs': {role: _view(path) for role, path in paths.items()}, 'extracted_body': _view(body_path),
        'pvt_manifest': _view(plan_path), 'probe_mapping': {'source_reset': common['reset_node'], 'post_reset': reset,
            'observation': observation, 'transfer_gates': transfer},
        'dropped_template_measures': dropped, 'extracted_netlist': _view(corner['extracted_netlist'])}


def prepare(project, block, settings, extraction, pre_pvt_manifest, pre_score, destination, image,
            *, technology=None, styles=None, samples=None, first_seed=1, max_delta_pct=None, native_binary=None, reset_observation=None):
    project, destination = Path(project).resolve(), Path(destination).resolve()
    if not re.fullmatch(r'[A-Za-z_][\w.-]*', block):
        raise ValueError('invalid source block')
    paths = pvt._paths(project, block)
    common = _read(settings)
    common.setdefault('threads', 1); common.setdefault('openmp_wait_policy', 'PASSIVE')
    capture.phase_settings(common, 0)
    template = Path(common.get('testbench', paths['testbench']))
    paths['testbench'] = template if template.is_absolute() else project / template
    source = {role: _view(path) for role, path in paths.items()}
    source['settings'] = _view(settings)
    closure = bound.consumed_input_views(project, paths['testbench'])
    if not capture.declared_dut_consumed({'netlist': source['netlist'], **closure}):
        raise ValueError('actual source template does not consume the declared source DUT')
    source.update(closure)
    declared_closure = bound.consumed_input_views(project, paths['netlist'])
    if {view['sha256'] for view in declared_closure.values()} - {view['sha256'] for view in closure.values()}:
        raise ValueError('source testbench model/include closure differs from the declared DUT')
    source.update({'declared-source:' + key: view for key, view in declared_closure.items()})
    pre_reference = _view(pre_pvt_manifest)
    pre_plan = _pre_plan(project, block, pre_reference, source, common)
    if pre_plan.get('image') != image:
        raise ValueError('PRE PVT runtime differs from the requested runtime')
    extraction = Path(extraction).resolve()
    record = _read(extraction); data = record.get('metrics') or {}
    gds = paths['netlist'].with_suffix('.gds')
    if record.get('status') != 'PASS' or data.get('netlist_sha256') != source['netlist']['sha256'] \
            or not gds.is_file() or data.get('layout_sha256') != bound.sha(gds):
        raise ValueError('actual A13 extraction does not bind the current source DUT/GDS')
    corners = data.get('corners') or []
    if not corners or len({row['style'] for row in corners}) != len(corners):
        raise ValueError('actual extraction styles are absent or duplicated')
    for row in corners:
        if not Path(row['extracted_netlist']).is_file() or bound.sha(row['extracted_netlist']) != row.get('sha256'):
            raise ValueError('actual A13 extracted netlist changed')
    tech = Path(data.get('magic_tech') or '__missing_magic_technology__')
    if not tech.is_file():
        tech = extraction.parent / 'magic_tech.flat'
    if not tech.is_file():
        raise ValueError('actual extraction-style technology source is unavailable')
    if technology is not None and a7._tech_text(Path(technology)) != a7._tech_text(tech):
        raise ValueError('explicit technology differs from the actual A13 technology source')
    expected_styles = a7.extraction_styles(tech)
    if not expected_styles or len(set(expected_styles)) != len(expected_styles):
        raise ValueError('technology does not declare a unique parasitic-style inventory')
    selected = list(styles) if styles is not None else [row['style'] for row in corners]
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(expected_styles) \
            or set(selected) - {row['style'] for row in corners}:
        raise ValueError('selected diagnostic styles lack actual technology/extraction inputs')
    if max_delta_pct is not None and (isinstance(max_delta_pct, bool) or not isinstance(max_delta_pct, (int, float))
                                    or not math.isfinite(max_delta_pct) or max_delta_pct < 0):
        raise ValueError('max_delta_pct must be explicitly finite and nonnegative')
    destination.mkdir(parents=True, exist_ok=False)
    selected_binary = _view(native_binary) if native_binary else None
    if selected_binary:
        source['native_binary'] = selected_binary
    flat = destination / 'extraction-technology.flat'
    flat.write_text(a7._tech_text(tech))
    source.update(extraction=_view(extraction), layout=_view(gds), technology_snapshot=_view(flat), pre_pvt_manifest=pre_reference)
    source.update({'A13:' + key: value for key, value in (record.get('native_inputs') or {}).items()})
    origins = {}
    for role, path in (('producer', Path(__file__)), ('incremental_producer', Path(capture.__file__)),
                       ('pvt_producer', Path(pvt.__file__)), ('statistics_producer', Path(stats.__file__))):
        snapshot = destination / 'producer-sources' / path.name
        snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_bytes(path.read_bytes())
        source[role] = _view(snapshot); origins[role] = _view(path)
    contexts = [_make_style(project, block, source, common, next(row for row in corners if row['style'] == style),
        destination / a7._style_slug(style), pre_plan, image, selected_binary, reset_observation) for style in selected]
    for context in contexts:
        source.update({'reset-support:' + context['style'] + ':' + key: value
                       for key, value in context['probe_mapping']['observation'].get('supporting_inputs', {}).items()})
        for switch, proof in context['probe_mapping']['transfer_gates']['observations'].items():
            source.update({'transfer-support:' + context['style'] + ':' + switch + ':' + key: value
                           for key, value in proof.get('supporting_inputs', {}).items()})
    manifest = {'kind': KIND, 'stage': 'POST', 'operation': 'prepare', 'status': 'PASS',
        'detail': 'actual PEX PVT input views prepared; no POST conversion measured', 'project': str(project),
        'block': block, 'destination': str(destination), 'image': image, 'common_settings': common,
        'pre_score': str(Path(pre_score).resolve()), 'native_inputs': source, 'producer_origins': origins,
        'technology_origin': _view(tech),
        'expected_styles': expected_styles, 'styles': contexts, 'max_delta_pct': max_delta_pct,
        'reset_observation': reset_observation,
        'statistics': None}
    if samples is not None:
        manifest['statistics'] = _prepare_statistics(manifest, samples, first_seed)
    if not _current(source):
        raise ValueError('source inputs changed during POST preparation')
    return manifest


def _validate(manifest):
    if not isinstance(manifest, dict) or manifest.get('kind') != KIND or manifest.get('stage') != 'POST' or not _current(manifest.get('native_inputs') or {}):
        raise ValueError('current source-bound POST manifest required')
    source, common = manifest['native_inputs'], manifest['common_settings']
    if not isinstance(common, dict) or not isinstance(manifest.get('producer_origins'), dict):
        raise ValueError('POST COMMON/producer inputs must be objects')
    delta = manifest.get('max_delta_pct')
    if delta is not None and (isinstance(delta, bool) or not isinstance(delta, (int, float))
                              or not math.isfinite(delta) or delta < 0):
        raise ValueError('explicit max_delta_pct is not finite/nonnegative')
    for role in ('producer', 'incremental_producer', 'pvt_producer', 'statistics_producer'):
        if source.get(role, {}).get('sha256') != manifest.get('producer_origins', {}).get(role, {}).get('sha256'):
            raise ValueError('immutable preparation producer snapshot is absent')
    project, block = Path(manifest['project']).resolve(), manifest['block']
    paths = pvt._paths(project, block)
    for role in ('netlist', 'spec', 'topology'):
        if source[role] != _view(paths[role]):
            raise ValueError('POST project/block does not identify its actual source ' + role)
    original = _read(source['settings']['path'])
    original.setdefault('threads', 1); original.setdefault('openmp_wait_policy', 'PASSIVE')
    template = Path(original.get('testbench', paths['testbench']))
    if not template.is_absolute():
        template = project / template
    if common != original or source['testbench'] != _view(template):
        raise ValueError('POST source COMMON/testbench identity changed')
    actual_closure = bound.consumed_input_views(project, template)
    declared_closure = bound.consumed_input_views(project, paths['netlist'])
    if {key: view for key, view in source.items() if key.startswith('include:')} != actual_closure \
            or {key[len('declared-source:'):]: view for key, view in source.items() if key.startswith('declared-source:')} != declared_closure:
        raise ValueError('POST source include/model dependency closure changed or was omitted')
    pre_plan = _pre_plan(project, block, source['pre_pvt_manifest'], source, common)
    if pre_plan.get('image') != manifest.get('image'):
        raise ValueError('POST runtime differs from PRE')
    record = _read(source['extraction']['path']); data = record.get('metrics') or {}
    if record.get('status') != 'PASS' or data.get('netlist_sha256') != source['netlist']['sha256'] \
            or data.get('layout_sha256') != source['layout']['sha256']:
        raise ValueError('A13 no longer binds the current source DUT/layout')
    technology = Path(data.get('magic_tech') or '__missing_magic_technology__')
    if not technology.is_file():
        technology = Path(source['extraction']['path']).parent / 'magic_tech.flat'
    if manifest.get('technology_origin') != _view(technology) \
            or Path(source['technology_snapshot']['path']).read_text() != a7._tech_text(technology) \
            or a7.extraction_styles(technology) != manifest['expected_styles']:
        raise ValueError('actual technology style inventory changed')
    names = [row['style'] for row in manifest['styles']]
    if not names or len(set(names)) != len(names) or set(names) - set(manifest['expected_styles']):
        raise ValueError('POST styles are absent, duplicated or outside the actual inventory')
    for context in manifest['styles']:
        expected_project = Path(manifest['destination']) / a7._style_slug(context['style']) / 'project'
        if Path(context['project']).resolve() != expected_project.resolve():
            raise ValueError('POST style project differs from its prepared extraction context')
        corner = next((row for row in data.get('corners', []) if row['style'] == context['style']), None)
        if not corner or context['extracted_netlist'] != _view(corner['extracted_netlist']) \
                or corner['sha256'] != context['extracted_netlist']['sha256']:
            raise ValueError('POST style does not bind its actual A13 extraction')
        current = pvt._paths(Path(context['project']), block)
        if context['native_inputs'] != {role: _view(path) for role, path in current.items()}:
            raise ValueError('prepared POST style inputs changed')
        wrapper, body, mapping = _wrapped_body(block, paths['netlist'], Path(corner['extracted_netlist']).read_text(), current['netlist'].parent)
        observation = {}
        text, reset, dropped = _post_template(block, paths['netlist'], template, current['netlist'],
            Path(corner['extracted_netlist']).read_text(), mapping, common['reset_node'],
            corner=corner, selector=manifest.get('reset_observation'), observation=observation)
        transfer = _post_transfer_observations(block, paths['netlist'], template, _read(source['topology']['path']),
            Path(corner['extracted_netlist']).read_text(), corner, mapping, common['reset_node'])
        effective = {**common, 'testbench': str(current['testbench']), 'reset_node': reset,
                     'transfer_gate_nodes': transfer['nodes']}
        if source.get('native_binary'):
            effective['native_binary'] = source['native_binary']
        if current['netlist'].read_text() != wrapper or Path(context['extracted_body']['path']).read_text() != body \
                or context['extracted_body'] != _view(current['netlist'].with_name(block + '__rcx.sp')) \
                or current['testbench'].read_text() != text or context['dropped_template_measures'] != dropped \
                or context['probe_mapping'] != {'source_reset': common['reset_node'], 'post_reset': reset,
                    'observation': observation, 'transfer_gates': transfer} \
                or not _current({'settings': context['settings'], 'pvt': context['pvt_manifest']}) \
                or _read(context['settings']['path']) != effective:
            raise ValueError('POST inputs differ beyond the actual extraction wrapper/probe remap')
        plan = _read(context['pvt_manifest']['path'])
        pvt._validate_manifest(plan)
        if plan['project'] != context['project'] or plan['block'] != block or plan['image'] != manifest['image'] \
                or plan['process_sections'] != pre_plan['process_sections'] \
                or plan['reference_ports'] != pre_plan['reference_ports'] \
                or plan['common_settings'] != _read(context['settings']['path']):
            raise ValueError('POST PVT differs from the source PRE matrix or method')
    return pre_plan


def _pre_score(manifest):
    path = Path(manifest['pre_score'])
    if not path.is_file():
        raise ValueError('complete native nominal PRE score is not available')
    reference = _view(path)
    source, common = manifest['native_inputs'], manifest['common_settings']
    cached = _read(path)
    for entry in cached.get('points') or []:
        point = _read(entry['path'])
        phase = point.get('settings', {}).get('phase_index')
        if point.get('settings') != capture.phase_settings(common, phase) or point.get('image') != manifest['image'] \
                or any(point.get('native_inputs', {}).get(role, {}).get('sha256') != source[role]['sha256']
                       for role in ('netlist', 'testbench', 'spec', 'topology')):
            raise ValueError('native PRE score does not consume this source DUT/method/runtime')
        expected_models = {view['sha256'] for key, view in source.items() if key.startswith('declared-source:')}
        actual_models = {view['sha256'] for key, view in point.get('native_inputs', {}).items() if key.startswith('include:')}
        if expected_models - actual_models:
            raise ValueError('native PRE values consume another model/include closure')
    actual = capture.replay_score(path)
    if not _current({'pre_score': reference}):
        raise ValueError('native PRE score changed during raw replay')
    if actual.get('status') != 'PASS':
        raise ValueError('current nominal PRE raw score has not passed: ' + actual.get('detail', actual['status']))
    return actual, reference


def _resim_collect(manifest, pre_plan):
    inputs = dict(manifest['native_inputs'])
    outputs, rows, comparisons, gaps = [], [], [], []
    pre = pvt.collect(pre_plan)
    inputs.update({'PRE:' + key: value for key, value in pre.get('native_inputs', {}).items()})
    outputs += pre.get('outputs', [])
    failed = pre['status'] == 'FAIL'
    if pre['status'] != 'PASS':
        gaps.append('complete native PRE PVT matrix has not passed')
    before = {(row['process'], row['temperature_c']): row for row in pre.get('metrics', {}).get('contexts', [])}
    for context in manifest['styles']:
        plan = _read(context['pvt_manifest']['path'])
        post = pvt.collect(plan)
        runtime_gaps = _pvt_binary_gaps(plan)
        if runtime_gaps:
            post = {**post, 'status': 'FAIL' if post['status'] == 'FAIL' else 'NOT_MEASURED',
                    'detail': post['detail'] + '; selected POST binary evidence is incomplete',
                    'runtime_gaps': runtime_gaps}
        failed |= post['status'] == 'FAIL'
        if post['status'] != 'PASS':
            gaps.append(context['style'] + ': complete POST PVT matrix has not passed')
        rows.append({'style': context['style'], 'status': post['status'], 'result': post})
        inputs['plan:' + context['style']] = context['pvt_manifest']
        inputs.update({context['style'] + ':' + key: value for key, value in post.get('native_inputs', {}).items()})
        outputs += post.get('outputs', [])
        for row in post.get('metrics', {}).get('contexts', []):
            previous = before.get((row['process'], row['temperature_c']), {})
            for metric, value in row.get('measurements', {}).items():
                original = previous.get('measurements', {}).get(metric)
                if not all(isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number)
                           for number in (original, value)):
                    continue
                delta = 100 * abs(value - original) / abs(original) if original else None
                violation = delta is not None and manifest.get('max_delta_pct') is not None and delta > manifest['max_delta_pct']
                failed |= violation
                comparisons.append({'style': context['style'], 'process': row['process'],
                    'temperature_c': row['temperature_c'], 'metric': metric, 'pre': original, 'post': value,
                    'delta_pct': delta, 'delta_violation': violation})
    missing = sorted(set(manifest['expected_styles']) - {row['style'] for row in rows})
    if missing:
        gaps.append('actual extraction styles not measured: ' + ', '.join(missing))
    if not _current(inputs):
        gaps.append('consumed PRE/POST inputs changed')
    return _result('FAIL' if failed else 'NOT_MEASURED' if gaps else 'PASS',
        'native incremental PRE/POST PVT comparisons across actual extraction styles', sorted(set(outputs)),
        native_inputs=inputs, metrics={'stage': 'POST', 'pre_pvt': pre, 'corners': rows, 'comparisons': comparisons,
            'expected_styles': manifest['expected_styles'], 'missing_styles': missing, 'gaps': gaps,
            'scope': 'full coherent native conversion series at each source PRE PVT context and extraction style'})


def collect(manifest, operation='resim', samples=None):
    try:
        pre_plan = _validate(manifest)
        if operation == 'statistics':
            result = _statistics_collect(manifest, samples)
        elif operation == 'resim':
            result = _resim_collect(manifest, pre_plan)
        else:
            raise ValueError('operation must be resim or statistics')
        try:
            pre, reference = _pre_score(manifest)
            result['native_inputs']['nominal_PRE_score'] = reference
            result['metrics']['nominal_PRE'] = pre
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if result['status'] != 'FAIL':
                result['status'] = 'NOT_MEASURED'
            result['detail'] += '; ' + str(exc)
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _result('NOT_MEASURED', str(exc), native_inputs=manifest.get('native_inputs', {}), metrics={'stage': 'POST'})


def _budget(manifest, workers, cpus, count):
    threads = manifest['common_settings'].get('threads', 1)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (workers, cpus, threads)) or cpus < threads:
        raise ValueError('bounded workers/CPU budget must accommodate the actual native thread count')
    width = min(count, workers, cpus // threads)
    return width, min(workers // width, cpus // (width * threads)), threads


def _claim(directory):
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(directory / 'running.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    proc = Path('/proc') / str(os.getpid())
    stat = (proc / 'stat').read_text()
    with os.fdopen(fd, 'w') as stream:
        json.dump({'pid': os.getpid(), 'argv': [os.fsdecode(item) for item in (proc / 'cmdline').read_bytes().split(b'\0') if item],
                   'start_ticks': stat[stat.rfind(')') + 2:].split()[19]}, stream)
    return True


def _native_runner(project, directory, container, image, settings):
    from analog_native_flow import NativeCommands
    selected = settings.get('native_binary')
    if selected and not _current({'native_binary': selected}):
        raise ValueError('selected native binary is absent or changed')
    if selected and not os.access(selected['path'], os.X_OK):
        raise ValueError('selected native binary is not executable')
    native = NativeCommands(project, directory, container, image)
    threads = settings.get('threads', 1)
    wait = settings.get('openmp_wait_policy', 'PASSIVE')
    if wait not in ('PASSIVE', 'ACTIVE'):
        raise ValueError('native OpenMP wait policy is invalid')
    def run(deck, target):
        return native('@env', ['-u', 'GOMP_SPINCOUNT', f'OMP_NUM_THREADS={threads}', 'OMP_WAIT_POLICY=' + wait,
            *(['GOMP_SPINCOUNT=0'] if wait == 'PASSIVE' else []),
            selected['path'] if selected else 'ngspice', '-b', str(deck)], cwd=Path(deck).parent)
    return run


def _point_launch(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path); parser.add_argument('--block', required=True)
    parser.add_argument('--settings', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--container', required=True); parser.add_argument('--image', required=True)
    args = parser.parse_args(argv)
    if (args.out / 'result.json').exists() or not _claim(args.out):
        return 2
    settings_raw = args.settings.read_bytes(); settings = json.loads(settings_raw)
    paths = pvt._paths(args.project, args.block)
    template = Path(settings.get('testbench', paths['testbench']))
    if not template.is_absolute():
        template = args.project / template
    record = capture.run_point(args.project, paths['netlist'], template, paths['spec'], paths['topology'], settings,
        args.out, _native_runner(args.project, args.out, args.container, args.image, settings))
    record['native_inputs']['settings'] = {'path': str(args.settings.resolve()), 'sha256': hashlib.sha256(settings_raw).hexdigest()}
    if settings.get('native_binary'):
        record['native_inputs']['native_binary'] = settings['native_binary']
    record.update(container=args.container, image=args.image)
    if args.settings.read_bytes() != settings_raw or not _current(record['native_inputs']):
        if record['status'] != 'FAIL':
            record.update(status='NOT_MEASURED', detail='native inputs changed during POST conversion', decoded={})
    capture.write_json(args.out / 'result.json', record)
    return {'PASS': 0, 'FAIL': 1}.get(record['status'], 2)


def _series_launch(argv):
    return capture.series_main(argv, launch=_point_launch)


def _fingerprints(project, block, body, wrapper, template, sections, mapping):
    # Both inputs are actual consumed files: the RC body declares __rcx,
    # and the A7 wrapper contains its real xrcx instance. Prefix its real
    # testbench instance rather than inventing a replacement circuit.
    sampled = stats._fingerprint_bindings(project, Path(body), Path(wrapper), sections, mapping)
    instances = a7.dut_instances(Path(template).read_text(), block)
    if len(instances) != 1:
        raise ValueError('POST fingerprint requires the single actual DUT instance')
    source_calls = {}
    for line in a7._subckt_body(Path(body).read_text(), block + '__rcx') or []:
        if line.casefold().startswith('x'):
            name, rest = line.split(None, 1)
            call = stats.calls._split_call(rest)
            if call:
                source_calls.setdefault(call[1].casefold(), []).append(name.casefold())
    fields, seen = [], set()
    for field in sampled:
        pattern = field['expression'].replace('.' + field['source_instance'] + '.', '.{device}.', 1)
        signature = (field['model'], field['parameter'], pattern)
        if signature in seen:
            continue
        seen.add(signature)
        for name in sorted(source_calls[field['model']]):
            prefix, rest = pattern.format(device=name).split('.', 1)
            fields.append({**field, 'key': f'fp_{len(fields):05d}', 'source_instance': name,
                           'expression': prefix + '.' + instances[0] + '.' + rest})
    return fields


def _probe_text(paths, common, fields, phase, root):
    text = stats._probe_text(paths, common, fields, phase, root)
    return text.replace('\n.control\n', '\n.control\nset numdgt=17\n', 1)


def _probe(project, paths, common, fields, seed, phase, root):
    root.mkdir(parents=True, exist_ok=False)
    deck = root / 'activation.sp'
    deck.write_text(_probe_text(paths, common, fields, phase, root))
    return {'seed': seed, 'phase_index': phase, 'project': str(project), 'deck': _view(deck),
            'receipt': str(root / 'result.json'), 'scope': 'realized native input parameters; no ENOB/OP surrogate'}


def _prepare_statistics(manifest, samples, first_seed):
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (samples, first_seed)) or samples < 2:
        raise ValueError('POST statistics requires at least two explicitly requested chip seeds')
    source_project = Path(manifest['project']); block = manifest['block']
    destination = Path(manifest['destination']) / 'statistics'
    sections, files = stats._source_sections(source_project, Path(manifest['styles'][0]['native_inputs']['netlist']['path']))
    enabled = stats._models(source_project, files, destination / 'models/enabled', True)
    disabled = stats._models(source_project, files, destination / 'models/disabled', False)
    groups = []
    for style in manifest['styles']:
        source_paths = {role: Path(view['path']) for role, view in style['native_inputs'].items()}
        actual_sections, actual_files = stats._source_sections(source_project, source_paths['netlist'])
        if actual_sections != sections or actual_files != files:
            raise ValueError('extraction styles do not share the same source mismatch model inputs')
        fields = _fingerprints(source_project, block, style['extracted_body']['path'], source_paths['netlist'],
                               source_paths['testbench'], sections, enabled['mapping'])
        common = _read(style['settings']['path'])
        chips, control = [], None
        for seed in range(first_seed, first_seed + samples):
            root = destination / a7._style_slug(style['style']) / f'chip-{seed:06d}'
            project = root / 'project'; paths = pvt._paths(project, block)
            paths['netlist'].parent.mkdir(parents=True)
            for role in ('spec', 'topology'):
                paths[role].symlink_to(source_paths[role])
            paths['netlist'].write_text(stats._dut_text(source_paths['netlist'], sections, enabled['mapping']))
            paths['testbench'].write_text(stats._template(source_paths['testbench'], source_paths['netlist'], paths['netlist'], seed))
            method = {**common, 'testbench': str(paths['testbench'])}
            settings = root / 'common.json'; capture.write_json(settings, method)
            probes = [_probe(project, paths, method, fields, seed, phase, root / f'activation/phase-{phase:03d}')
                      for phase in (0, method['series_length'] // 4)]
            chips.append({'seed': seed, 'project': str(project), 'settings': _view(settings),
                'native_inputs': {role: _view(path) for role, path in paths.items()}, 'probes': probes,
                'score': str(root / 'series/score.json')})
            if control is None:
                project = root / 'disabled-project'; paths = pvt._paths(project, block)
                paths['netlist'].parent.mkdir(parents=True)
                for role in ('spec', 'topology'):
                    paths[role].symlink_to(source_paths[role])
                paths['netlist'].write_text(stats._dut_text(source_paths['netlist'], sections, disabled['mapping']))
                paths['testbench'].write_text(stats._template(source_paths['testbench'], source_paths['netlist'], paths['netlist'], seed))
                control = {'native_inputs': {role: _view(path) for role, path in paths.items()},
                    'probe': _probe(project, paths, {**common, 'testbench': str(paths['testbench'])}, fields, seed, 0, root / 'activation/disabled')}
        groups.append({'style': style['style'], 'fingerprint_bindings': fields, 'chips': chips, 'disabled_control': control})
    return {'samples': samples, 'first_seed': first_seed, 'sections': sections, 'model_sources': files,
            'model_copies': [enabled, disabled], 'styles': groups,
            'scope': 'nominal TT27 foundry mismatch; one chip seed across all phases and extraction styles; device noise/jitter not added'}


def _validate_statistics(manifest, requested):
    configuration = manifest.get('statistics')
    if not isinstance(configuration, dict):
        raise ValueError('POST transient statistics input views have not been prepared')
    count, first = configuration['samples'], configuration['first_seed']
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (count, first)) or count < 2:
        raise ValueError('POST chip population count/seeds are invalid')
    if requested is not None and (isinstance(requested, bool) or not isinstance(requested, int) or requested != count):
        raise ValueError('requested POST sample count differs from the complete prepared chip population')
    project, block = Path(manifest['project']), manifest['block']
    sections, files = stats._source_sections(project, Path(manifest['styles'][0]['native_inputs']['netlist']['path']))
    if sections != configuration['sections'] or files != configuration['model_sources']:
        raise ValueError('actual POST mismatch model source closure changed')
    copies = configuration['model_copies']
    if [variant.get('enabled') for variant in copies] != [True, False]:
        raise ValueError('POST mismatch enabled/disabled source copies are required')
    for variant in copies:
        if set(variant['mapping']) != set(files) or len(variant['files']) != len(files):
            raise ValueError('POST mismatch source model closure is incomplete')
        seen = set()
        for row in variant['files']:
            name = row['source']['path']
            if name in seen or row['source'] != files.get(name) or row['copy']['path'] != variant['mapping'][name]:
                raise ValueError('POST mismatch source/copy identity changed')
            seen.add(name)
            text, edits = stats._model_text(project, name, variant['mapping'], variant['enabled'])
            if not _current({'copy': row['copy']}) or Path(row['copy']['path']).read_text() != text or edits != row['switch_edits']:
                raise ValueError('POST mismatch model differs beyond source relocation/mm_ok')
    groups = configuration['styles']
    if [row['style'] for row in groups] != [row['style'] for row in manifest['styles']]:
        raise ValueError('POST statistical styles differ from the actual extraction contexts')
    probes = []
    for group, style in zip(groups, manifest['styles']):
        source_paths = {role: Path(value['path']) for role, value in style['native_inputs'].items()}
        common = _read(style['settings']['path'])
        fields = _fingerprints(project, block, style['extracted_body']['path'], source_paths['netlist'],
                               source_paths['testbench'], sections, copies[0]['mapping'])
        if fields != group['fingerprint_bindings'] or [row['seed'] for row in group['chips']] != list(range(first, first + count)):
            raise ValueError('POST chip fingerprints/seeds differ from the prepared hardware')
        targets = [(chip, copies[0], chip['probes']) for chip in group['chips']]
        targets.append(({'seed': first, 'project': group['disabled_control']['probe']['project'],
                         'native_inputs': group['disabled_control']['native_inputs']}, copies[1], [group['disabled_control']['probe']]))
        for chip, variant, controls in targets:
            root = Path(manifest['destination']) / 'statistics' / a7._style_slug(group['style']) / f'chip-{chip["seed"]:06d}'
            expected_project = root / ('project' if variant['enabled'] else 'disabled-project')
            if Path(chip['project']).resolve() != expected_project.resolve() or ('settings' in chip and
                    (chip['settings']['path'] != str(root / 'common.json') or chip['score'] != str(root / 'series/score.json'))):
                raise ValueError('POST chip project/score does not identify its actual prepared population')
            paths = pvt._paths(Path(chip['project']), block)
            effective = {**common, 'testbench': str(paths['testbench'])}
            if chip['native_inputs'] != {role: _view(path) for role, path in paths.items()} \
                    or any(chip['native_inputs'][role]['sha256'] != manifest['native_inputs'][role]['sha256'] for role in ('spec', 'topology')) \
                    or paths['netlist'].read_text() != stats._dut_text(source_paths['netlist'], sections, variant['mapping']) \
                    or paths['testbench'].read_text() != stats._template(source_paths['testbench'], source_paths['netlist'], paths['netlist'], chip['seed']):
                raise ValueError('POST chip differs beyond actual models and its frozen seed')
            if 'settings' in chip and (not _current({'settings': chip['settings']}) or _read(chip['settings']['path']) != effective):
                raise ValueError('POST chip measurement method changed')
            expected_phases = [0, common['series_length'] // 4] if variant['enabled'] else [0]
            if [row['phase_index'] for row in controls] != expected_phases:
                raise ValueError('POST native same-chip phase controls are incomplete')
            for probe in controls:
                deck = Path(probe['deck']['path'])
                if probe['seed'] != chip['seed'] or probe['project'] != chip['project'] \
                        or probe['receipt'] != str(deck.parent / 'result.json') or not _current({'deck': probe['deck']}) \
                        or deck.read_text() != _probe_text(paths, effective, fields, probe['phase_index'], deck.parent):
                    raise ValueError('POST realized-parameter native control changed')
                probes.append((probe, paths, effective, fields))
    return configuration, probes


def _binary_check(point, selected):
    if selected and (point.get('native_inputs', {}).get('native_binary') != selected or any(
            selected['path'] not in execution.get('argv', []) for execution in point.get('executions') or [])):
        raise ValueError('POST native execution does not bind the selected binary')


def _pvt_binary_gaps(plan):
    selected = plan.get('common_settings', {}).get('native_binary')
    if not selected:
        return []
    gaps = []
    for context in plan['contexts']:
        score = Path(context['score'])
        entries = _read(score).get('points') or [] if score.is_file() else []
        if not entries:
            entries = [_view(path) for path in score.parent.glob('point-[0-9][0-9][0-9]/result.json')]
        for entry in entries:
            try:
                if not _current({'point': entry}):
                    raise ValueError('POST binary point receipt changed')
                _binary_check(_read(entry['path']), selected)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                gaps.append({'point': entry.get('path'), 'detail': str(exc)})
    return gaps


def _score_context(chip, common, image, references):
    score_path = Path(chip['score']); inputs, outputs, observed = {}, [], []
    native_failed = False
    try:
        cached = _read(score_path) if score_path.is_file() else {}
        entries = cached.get('points') or []
        incomplete = not entries
        if incomplete:
            entries = [_view(path) for path in sorted(score_path.parent.glob('point-[0-9][0-9][0-9]/result.json'))]
        phases = set()
        for entry in entries:
            path = Path(entry['path'])
            if not _current({'point': entry}):
                raise ValueError('POST native point receipt is absent or changed')
            point = _read(path); phase = point.get('settings', {}).get('phase_index')
            views = point.get('native_inputs') or {}
            if point.get('settings') != capture.phase_settings(common, phase) or point.get('image') != image \
                    or any(views.get(role) != view for role, view in chip['native_inputs'].items()):
                raise ValueError('POST native point does not belong to this hardware/method')
            if not _current(views) or not bound.validate_consumed_inputs(Path(chip['project']), views)[0] \
                    or not capture.declared_dut_consumed(views):
                raise ValueError('POST native consumed input closure is absent or changed')
            inputs['point:' + str(phase)] = entry
            inputs.update({f'point:{phase}:' + key: value for key, value in views.items()})
            phases.add(phase)
            _binary_check(point, common.get('native_binary'))
            if stats._point_failure(point):
                native_failed = True
                raise ValueError('POST native conversion execution failed')
            for execution in point.get('executions') or []:
                log = Path(execution['log'])
                if not log.is_file() or bound.sha(log) != execution.get('log_sha256'):
                    raise ValueError('POST native transcript changed')
                transcript = log.read_text(errors='replace')
                inputs[f'point:{phase}:log'] = _view(log)
                temperatures = [float(value) for value in re.findall(r'Doing analysis at TEMP\s*=\s*([-+.\deE]+)', transcript)]
                if not temperatures or any(value != 27 for value in temperatures):
                    raise ValueError('POST mismatch native temperature is not nominal27C')
                if references:
                    observed.append(pvt._reference_measurement(point, transcript, references))
        if incomplete:
            raise ValueError('POST full coherent chip score has not completed')
        score_reference = _view(score_path)
        inputs['score'] = score_reference
        replay = capture.replay_score(score_path)
        outputs += replay.get('outputs', [])
        values = dict(replay.get('measurements') or {})
        reference_pass = None
        if references:
            if phases != set(range(common['series_length'])) or len(observed) != len(phases):
                raise ValueError('POST per-phase reference evidence is incomplete')
            reference_pass = not any(row['violation'] for row in observed)
            values['vref'] = observed[0]['value']
        if not _current(inputs):
            raise ValueError('POST chip evidence changed during raw replay')
        status = 'FAIL' if reference_pass is False else replay['status']
        return {'status': status, 'native_failed': False, 'measurements': values,
                'resolution_status': replay['status'], 'reference_pass': reference_pass,
                'native_inputs': inputs, 'outputs': outputs, 'reference_observations': observed}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'FAIL' if native_failed else 'NOT_MEASURED', 'native_failed': native_failed,
                'detail': str(exc), 'native_inputs': inputs, 'outputs': outputs, 'reference_observations': observed}


def _probe_state(probe, fields, image, selected):
    actual = stats._native_probe(probe, fields, image)
    if actual[0] == 'FAIL':
        return actual
    if selected and Path(probe['receipt']).is_file():
        record = _read(probe['receipt'])
        execution = record.get('execution') or {}
        if record.get('native_inputs', {}).get('native_binary') != selected or selected['path'] not in execution.get('argv', []):
            return 'NOT_MEASURED', {}, 'native parameter control did not use the selected binary'
    return actual


def _statistics_collect(manifest, requested):
    configuration, probes = _validate_statistics(manifest, requested)
    source, count = manifest['native_inputs'], configuration['samples']
    inputs, outputs, groups, gaps = dict(source), [], [], []
    failed, activation = False, True
    required = mc._source_yield_coverage(Path(manifest['project']), source['spec']['path'], {}, count)['required']
    canonical_chips = {}
    for variant in configuration['model_copies']:
        inputs.update({'model-copy:' + row['copy']['path']: row['copy'] for row in variant['files']})
    inputs.update({'model-source:' + key: view for key, view in configuration['model_sources'].items()})
    for group in configuration['styles']:
        style, fields = group['style'], group['fingerprint_bindings']
        disabled = group['disabled_control']['probe']
        off_state, off, _detail = _probe_state(disabled, fields, manifest['image'], source.get('native_binary'))
        failed |= off_state == 'FAIL'
        per_model = {field['model'] for field in fields}; fingerprints, rows = {}, []
        for chip in group['chips']:
            states = [_probe_state(probe, fields, manifest['image'], source.get('native_binary')) for probe in chip['probes']]
            failed |= any(state[0] == 'FAIL' for state in states)
            active = off_state == 'PASS' and all(state[0] == 'PASS' for state in states) and states[0][1] == states[1][1]
            if active:
                active = all(any(states[0][1][field['key']] != off[field['key']] for field in fields
                                 if field['model'] == model) for model in per_model)
            if not active:
                activation = False; gaps.append(f'{style}/seed{chip["seed"]}: native mismatch activation is unproven')
            else:
                fingerprint = {(field['model'], field['source_instance'], field['parameter']): states[0][1][field['key']]
                               for field in fields}
                fingerprints[chip['seed']] = fingerprint
                if chip['seed'] in canonical_chips and canonical_chips[chip['seed']] != fingerprint:
                    activation = False; gaps.append(f'{style}/seed{chip["seed"]}: native realized hardware differs between extraction styles')
                canonical_chips.setdefault(chip['seed'], fingerprint)
            result = _score_context(chip, _read(chip['settings']['path']), manifest['image'],
                                    _read(source['pre_pvt_manifest']['path'])['reference_ports'])
            failed |= result['native_failed']
            if result['status'] not in ('PASS', 'FAIL'):
                gaps.append(f'{style}/seed{chip["seed"]}: full native conversion series incomplete')
            rows.append({'seed': chip['seed'], 'activation_proven': active, **result})
            inputs['settings:' + style + ':' + str(chip['seed'])] = chip['settings']
            inputs.update({f'{style}:seed{chip["seed"]}:' + key: value for key, value in result['native_inputs'].items()})
            outputs += result.get('outputs', [])
        if len(fingerprints) == count:
            for model in per_model:
                identities = {tuple(sorted((key, value) for key, value in fp.items() if key[0] == model))
                              for fp in fingerprints.values()}
                if len(identities) != count:
                    activation = False; gaps.append(style + ': different seeds do not realize distinct native ' + model + ' parameters')
        spec_yield = {}
        joint_rows = []
        for metric in required:
            states = [(row.get('resolution_status') == 'PASS' if metric == 'enob' else row.get('reference_pass'))
                      for row in rows if (row.get('resolution_status') in ('PASS', 'FAIL') if metric == 'enob'
                                          else row.get('reference_pass') is not None if metric == 'vref' else False)]
            spec_yield[metric] = {'runs_scored': len(states), 'passed': sum(states),
                                 'yield_pct': 100 * sum(states) / len(states) if states else None}
        for row in rows:
            states = {'enob': row.get('resolution_status') == 'PASS' if row.get('resolution_status') in ('PASS', 'FAIL') else None,
                      'vref': row.get('reference_pass')}
            if required and all(states.get(metric) is not None for metric in required):
                joint_rows.append(all(states[metric] for metric in required))
        joint_pct = 100 * sum(joint_rows) / len(joint_rows) if joint_rows else None
        grade = mc._grade_source_yield(Path(manifest['project']), source['spec']['path'], spec_yield, count)
        # Grade the actually observed joint pass fraction through the same
        # existing source policy; these are explicit conservative lower bounds,
        # not fabricated per-output measured yields.
        joint_bound = {metric: {'runs_scored': len(joint_rows), 'yield_pct': joint_pct,
                               'basis': 'observed fraction passing every required output'} for metric in required}
        joint_grade = mc._grade_source_yield(Path(manifest['project']), source['spec']['path'], joint_bound, count)
        failed |= grade['verdict'] == 'FAIL' or joint_grade['verdict'] == 'FAIL'
        if grade['verdict'] == 'NOT_MEASURED' or joint_grade['verdict'] == 'NOT_MEASURED':
            gaps.append(style + ': source-required full chip population coverage is incomplete')
        groups.append({'style': style, 'chips': rows, 'spec_yield': spec_yield, 'joint_yield_pct': joint_pct,
                       'joint_yield_basis': 'actual chips passing every required source output',
                       'mc_source_coverage': grade['mc_source_coverage'], 'source_policy': grade, 'joint_policy': joint_grade})
    for probe, _paths, _common, _fields in probes:
        if Path(probe['receipt']).is_file():
            inputs['probe:' + probe['receipt']] = _view(probe['receipt'])
            record = _read(probe['receipt'])
            inputs.update({probe['receipt'] + ':' + key: view for key, view in record.get('native_inputs', {}).items()})
            log = Path(record.get('execution', {}).get('log') or '__missing_log__')
            if log.is_file():
                inputs['probe-log:' + str(log)] = _view(log)
    missing = sorted(set(manifest['expected_styles']) - {row['style'] for row in groups})
    if missing:
        gaps.append('unmeasured extraction styles: ' + ', '.join(missing))
    if not _current(inputs):
        gaps.append('consumed POST population source/evidence changed')
    complete = not gaps and activation
    return _result('FAIL' if failed else 'PASS' if complete else 'NOT_MEASURED',
        'actual native POST incremental mismatch populations across extraction styles', sorted(set(outputs)),
        native_inputs=inputs, metrics={'stage': 'POST', 'requested_samples': count,
            'native_activation_proven': activation, 'corners': groups, 'missing_styles': missing, 'gaps': gaps,
            'scope': configuration['scope'], 'mc_runs': count if complete else 0,
            'mc_yield_pct': min(row['joint_yield_pct'] for row in groups) if complete else None})


def _run_probes(manifest, container, image, requested):
    _configuration, probes = _validate_statistics(manifest, requested)
    for probe, paths, common, fields in probes:
        if Path(probe['receipt']).exists() or not _claim(Path(probe['receipt']).parent):
            continue
        directory = Path(probe['receipt']).parent
        inputs = {role: _view(path) for role, path in paths.items()}
        inputs['deck'] = probe['deck']
        inputs.update(bound.consumed_input_views(Path(probe['project']), Path(probe['deck']['path'])))
        if common.get('native_binary'):
            inputs['native_binary'] = common['native_binary']
        execution = _native_runner(Path(probe['project']), directory, container, image, common)(Path(probe['deck']['path']), directory)
        capture.write_json(Path(probe['receipt']), {'operation': 'native_POST_parameter_probe', 'image': image,
            'native_inputs': inputs, 'execution': execution})


def _statistics_run(manifest, container, image, workers, cpus, requested):
    configuration, _probes = _validate_statistics(manifest, requested)
    tasks = [chip for group in configuration['styles'] for chip in group['chips']]
    width, inner, threads = _budget(manifest, workers, cpus, len(tasks))
    _run_probes(manifest, container, image, requested)
    before = collect(manifest, 'statistics', requested)
    if before['status'] in ('PASS', 'FAIL') or not before.get('metrics', {}).get('native_activation_proven'):
        return before
    def one(chip):
        return _series_launch([chip['project'], '--block', manifest['block'], '--settings', chip['settings']['path'],
            '--out', str(Path(chip['score']).parent), '--score', chip['score'], '--container', container,
            '--image', image, '--workers', str(inner), '--cpus', str(inner * threads)])
    with ThreadPoolExecutor(max_workers=width) as executor:
        codes = list(executor.map(one, tasks))
    result = collect(manifest, 'statistics', requested)
    result['metrics']['execution_budget'] = {'chip_workers': width, 'phase_workers_per_chip': inner,
        'total_cpu_ceiling': width * inner * threads, 'series_returncodes': codes}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('project', type=Path); prep.add_argument('--block', required=True)
    for option in ('settings', 'extraction', 'pre-pvt-manifest', 'pre-score', 'out', 'json'):
        prep.add_argument('--' + option, type=Path, required=True)
    prep.add_argument('--image', required=True); prep.add_argument('--technology', type=Path)
    prep.add_argument('--styles', nargs='+'); prep.add_argument('--samples', type=int)
    prep.add_argument('--first-seed', type=int, default=1); prep.add_argument('--max-delta-pct', type=float)
    prep.add_argument('--native-binary', type=Path)
    prep.add_argument('--reset-device', help='explicit source MOS whose retained gate label observes reset')
    for operation in ('collect', 'run'):
        command = commands.add_parser(operation)
        command.add_argument('manifest', type=Path); command.add_argument('--json', type=Path, required=True)
        command.add_argument('--measurement', choices=('resim', 'statistics'), default='resim')
        command.add_argument('--samples', type=int)
        if operation == 'run':
            command.add_argument('--container', required=True); command.add_argument('--image', required=True)
            command.add_argument('--workers', type=int, default=1); command.add_argument('--cpus', type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'prepare':
            result = prepare(args.project, args.block, args.settings, args.extraction, args.pre_pvt_manifest,
                args.pre_score, args.out, args.image, technology=args.technology, styles=args.styles,
                samples=args.samples, first_seed=args.first_seed, max_delta_pct=args.max_delta_pct, native_binary=args.native_binary,
                reset_observation={'device': args.reset_device, 'terminal': 'g'} if args.reset_device else None)
        else:
            manifest = _read(args.manifest)
            result = (run(manifest, args.container, args.image, args.workers, args.cpus, args.measurement, args.samples)
                      if args.operation == 'run' else collect(manifest, args.measurement, args.samples))
            result.setdefault('native_inputs', {})['post_layout_manifest'] = _view(args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = _result('NOT_MEASURED', str(exc), metrics={'stage': 'POST'})
    if args.json.exists():
        raise ValueError('refusing to overwrite an existing POST result/manifest')
    capture.write_json(args.json, result)
    print(json.dumps({'status': result['status'], 'detail': result['detail'], 'report': str(args.json)}))
    return {'PASS': 0, 'FAIL': 1}.get(result['status'], 2)


def _run(manifest, container, image, workers=1, cpus=1, operation='resim', samples=None):
    if operation not in ('resim', 'statistics'):
        raise ValueError('operation must be resim or statistics')
    _validate(manifest)
    if image != manifest.get('image'):
        raise ValueError('POST native runtime differs from the prepared runtime')
    before = collect(manifest, operation, samples)
    if before['status'] in ('PASS', 'FAIL'):
        return before
    try:
        _pre_score(manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        before['detail'] += '; no POST conversion launched: ' + str(exc)
        return before
    if operation == 'statistics':
        return _statistics_run(manifest, container, image, workers, cpus, samples)
    width, inner, threads = _budget(manifest, workers, cpus, len(manifest['styles']))
    def one(context):
        return pvt.run(_read(context['pvt_manifest']['path']), container, image, workers=inner, cpus=inner * threads,
                       launch=_series_launch)
    with ThreadPoolExecutor(max_workers=width) as executor:
        results = list(executor.map(one, manifest['styles']))
    result = collect(manifest, operation, samples)
    result['metrics']['execution_budget'] = {'style_workers': width, 'phase_cpu_budget_per_style': inner * threads,
                                            'total_cpu_ceiling': width * inner * threads}
    result['metrics']['style_run_statuses'] = [row['status'] for row in results]
    return result


def run(manifest, container, image, workers=1, cpus=1, operation='resim', samples=None):
    try:
        return _run(manifest, container, image, workers, cpus, operation, samples)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _result('NOT_MEASURED', str(exc), metrics={'stage': 'POST'})


if __name__ == '__main__':
    raise SystemExit(main())
