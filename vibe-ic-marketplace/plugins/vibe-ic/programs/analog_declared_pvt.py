#!/usr/bin/env python3
"""Declared scalar PVT producer; callers block dependent work on non-PASS.

Derive only process section and temperature from the delivered declared bench.
This path supplies no sampled dynamic method or tool/IC qualification.
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path
import re
import shlex

import analog_bound_measurements as bound
import analog_incremental_pvt as pvt
import analog_native_sim as sim
import analog_real_corner_sweep as sweep


def coordinates(declaration):
    """Exactly one TT/SS/FF section crossed with the existing three temperatures."""
    sections = declaration.get('process_sections')
    if not isinstance(sections, list):
        raise ValueError('process_sections must list the declared TT/SS/FF sections')
    process = pvt._coordinates(sections)
    return [(section, temperature)
            for section, (_label, temperature, _offset) in itertools.product(process, sweep.PVT_TEMPS)]


def corner_label(section, temperature):
    return section + '_' + str(temperature).replace('-', 'm')


def temperature_matches(text, temperature):
    """Every native analysis must report the requested finite temperature."""
    markers = re.findall(r'(?im)^\s*Doing analysis at TEMP\s*=\s*(\S+)', text)
    try:
        return bool(markers) and all(math.isfinite(float(v)) and math.isclose(
            float(v), temperature, rel_tol=0, abs_tol=1e-6) for v in markers)
    except ValueError:
        return False


def measurement_state(required, limits, measured):
    """Missing/invalid data removes PASS; a valid individual breach retains FAIL."""
    def finite(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    missing, malformed, breach = [], [], []
    for key in required:
        value = measured.get(key)
        valid_value = finite(value)
        if not valid_value:
            missing.append(key)
        limits_for_key = limits.get(key)
        if not isinstance(limits_for_key, dict):
            malformed.append(key)
            continue
        edges = {edge: limits_for_key[edge] for edge in ('min', 'max') if limits_for_key.get(edge) is not None}
        if (not edges or any(not finite(value) for value in edges.values())
                or ('min' in edges and 'max' in edges and edges['min'] > edges['max'])):
            malformed.append(key)
            continue
        if valid_value and any(value < v if edge == 'min' else value > v for edge, v in edges.items()):
            breach.append(key)
    return missing, malformed, breach


def render_corner(project, name, config, destination, sections, section, temperature):
    """Read sources and return deck/DUT text plus their source views; never write."""
    from analog_mc_yield_run import _statistical_closure
    destination = Path(destination).resolve()
    netlist = sim._inputs(project, name, config)[0]
    process = pvt._coordinates(sections)
    _signature, original, _cards = pvt._net_signature(netlist)
    if len(_cards) != 1:
        raise ValueError('DECLARED_PVT_PROCESS_CARD_NOT_SINGLE')
    if original != 'tt':
        raise ValueError('DECLARED_PVT_NOMINAL_PROCESS_NOT_TT')
    lines, moved, model_views = [], 0, {}
    for line in bound.contextual_template(netlist.read_text(), netlist.parent).splitlines():
        tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith('*') else []
        if tokens and tokens[0].casefold() == '.lib' and len(tokens) == 3 and tokens[2] in process:
            if process[tokens[2]] != 'tt':
                raise ValueError('DECLARED_PVT_NOMINAL_PROCESS_NOT_TT')
            model = Path(tokens[1])
            # Check every declared section and its transitive includes before any launch.
            for selected in sections:
                _text, files = _statistical_closure(Path(project).resolve(), model, selected)
                for view in files:
                    model_views['include:' + view['path']] = {k: view[k] for k in ('path', 'sha256')}
            line = '.lib "' + str(model) + '" ' + section
            moved += 1
        lines.append(line)
    if moved != 1:
        raise ValueError('DECLARED_PVT_PROCESS_CARD_NOT_SINGLE: ' + str(moved))
    dut_text = '\n'.join(lines) + '\n'
    text, views = sim._declared_testbench(project, name, config, destination)
    if text is None:
        raise ValueError('DECLARED_PVT_TESTBENCH_ABSENT: ' + name)
    lines, included = [], 0
    for line in bound.contextual_template(text, destination).splitlines():
        tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith('*') else []
        if (tokens and tokens[0].casefold() in ('.include', '.inc') and len(tokens) == 2
                and Path(tokens[1]).resolve() == netlist.resolve()):
            line = '.include "' + str(destination / (name + '.sp')) + '"'
            included += 1
        lines.append(line)
    if included != 1:
        raise ValueError('source testbench must include the exact declared DUT once')
    deck_text, applied = sweep.stamp_temp_card('\n'.join(lines) + '\n', temperature)
    if applied.get('temp_c') != temperature:
        raise ValueError('native corner temperature could not be stamped')
    views.update(model_views)
    views['netlist'] = {'path': str(netlist.resolve()), 'sha256': bound.sha(netlist)}
    return deck_text, dut_text, views


def run(project, name, config, declaration, attempt, native):
    """Execute each corner once; an incomplete later corner cannot erase FAIL."""
    pairs = coordinates(declaration)
    sections = list(declaration['process_sections'])
    spec_path = sim._inputs(project, name, config)[2]
    required = sim._source_measurement_coverage(spec_path, [])['required']
    if set(required) & {'enob', 'snr', 'sinad', 'sndr'}:
        raise ValueError('A08_COMPLETE_SAMPLED_DYNAMIC_METHOD_REQUIRED')
    limits = sim._bounds(spec_path, config, required)
    first_section, first_temperature = pairs[0]
    _deck, _dut, source_views = render_corner(project, name, config,
        attempt / corner_label(first_section, first_temperature), sections, first_section, first_temperature)
    corners, executions, outputs, inputs, violated = [], [], [], {}, []
    for section, temperature in pairs:
        label = corner_label(section, temperature)
        directory = attempt / label
        corner = {'name': label, 'process': section, 'temperature_c': temperature,
                  'status': 'NOT_MEASURED', 'measurements': {}, 'missing': list(required)}
        try:
            deck_text, dut_text, views = render_corner(project, name, config, directory, sections, section, temperature)
            if views != source_views:
                raise ValueError('DECLARED_PVT_SOURCE_CHANGED_AFTER_PREFLIGHT')
            directory.mkdir(parents=True, exist_ok=True)
            deck, dut, log = directory / ('tb_' + name + '.sp'), directory / (name + '.sp'), directory / 'ngspice.log'
            deck.write_text(deck_text); dut.write_text(dut_text)
            views.update(bound.consumed_input_views(project, deck))
            views['deck'] = {'path': str(deck), 'sha256': bound.sha(deck)}
            inputs.update({label + ':' + role: view for role, view in views.items()})
            corner.update(deck=str(deck), netlist=str(dut))
            outputs += [str(deck), str(dut), str(log)]
            execution = {**native('@ngspice', ['-b', str(deck), '-o', str(log)], cwd=directory, outputs=[str(log)]),
                         'stdout_path': str(log)}
            executions.append(execution)
            corner['execution'] = execution
            text = log.read_text(errors='replace') if log.is_file() else ''
            measured = {key.casefold(): value for key, value in sweep.native_meas_rows(text).items()}
            for match in sweep._MEAS_LINE_RE.finditer(text):
                for key, value in sweep._KV_RE.findall(match.group(1)):
                    measured.setdefault(key.casefold(), float(value))
            missing, malformed, breach = measurement_state(required, limits, measured)
            corner.update(measurements=measured, missing=missing, malformed_limits=malformed)
            if sim._changed_native_inputs(views):
                corner['detail'] = 'DECLARED_PVT_INPUT_CHANGED_DURING_EXECUTION'
            else:
                failed = execution.get('returncode') != 0 or any(sweep._scan_analysis_failures(text))
                interrupted = execution.get('returncode') in (-9, -15, 130, 137, 143)
                if failed and not interrupted:
                    corner['status'] = 'FAIL'
                elif not temperature_matches(text, temperature):
                    corner['detail'] = 'DECLARED_PVT_NATIVE_TEMPERATURE_MISMATCH'
                else:
                    corner['status'] = ('FAIL' if breach else
                        'NOT_MEASURED' if missing or malformed or not required or interrupted else 'PASS')
                    violated += [label + ':' + key for key in breach]
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            corner['detail'] = str(exc)
        corners.append(corner)
    states = [corner['status'] for corner in corners]
    status = 'FAIL' if 'FAIL' in states else 'PASS' if states and all(s == 'PASS' for s in states) else 'NOT_MEASURED'
    return {'status': status, 'detail': ('declared bench measured at every process/temperature corner' if status == 'PASS'
        else 'declared bench corners: ' + ', '.join(violated or [c['name'] + '=' + c['status'] for c in corners if c['status'] != 'PASS'])),
        'outputs': outputs, 'executions': executions, 'native_inputs': inputs,
        'metrics': {'stage': 'PRE', 'kind': 'declared_testbench', 'required': required, 'corners': corners,
                    'total_corners': len(pairs), 'corners_executed': len(executions)}}
