"""Real D55 GLS -> scoped VCD -> OpenSTA vector-power component controls.

Developer controls are not production PDK qualification or final power signoff.
All source inputs are neutral fixtures, independent of any benchmark IC.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import flow109
import flow109_admission as admission
import flow109_functional_activity as activity
from programs.tests._hostpaths import require_repo


@pytest.mark.parametrize('values, accepted', [
    ('0!\n#2\n1!\n', True),
    ('1!\n#2\n0!\n', True),
    ('not 0!\n#2\nnot 1!\n', False),
    ('0! is not low\n#2\n1! is not high\n', False),
    ('signal is 0!\n#2\nsignal is 1!\n', False),
    ('x!\n#2\n1!\n', False),
    ('0!\n#2\nz!\n', False),
])
def test_vcd_census_consumes_formal_records_not_prose(tmp_path, values, accepted):
    vcd = tmp_path / 'grammar.vcd'
    vcd.write_text('$timescale 1ps $end\n$scope module dut $end\n'
                   '$var wire 1 ! signal $end\n$upscope $end\n'
                   '$enddefinitions $end\n#0\n' + values)
    spec = {'required_ports': ['signal'],
            'window': {'start_tick': 0, 'end_tick': 2, 'timescale': '1ps'}}
    if accepted:
        result = activity.waveform_census(vcd, 'dut', spec)
        assert result['ports']['signal']['observations'] == 2
        assert result['ports']['signal']['transitions'] == 1
    else:
        with pytest.raises(admission.AdmissionRefusal,
                           match='D55_VCD_UNKNOWN_OR_UNOBSERVED_SIGNAL'):
            activity.waveform_census(vcd, 'dut', spec)


def test_measured_vcd_census_consumes_scalar_and_vector_top_ports(tmp_path):
    vcd = tmp_path / 'vector.vcd'
    vcd.write_text('$timescale 1ns $end\n$scope module tb $end\n$scope module dut $end\n'
                   '$var wire 1 ! clk $end\n$var wire 4 " x [3:0] $end\n'
                   '$var wire 1 # internal_net $end\n'
                   '$upscope $end\n$upscope $end\n$enddefinitions $end\n'
                   '#0\nx!\nb0000 "\n0#\n#1\n0!\n#2\n1!\nb1010 "\n1#\n')
    ports = [{'name': 'clk', 'direction': 'input', 'width': 1},
             {'name': 'x', 'direction': 'input', 'width': 4}]
    result = activity.measured_waveform_census(vcd, 'tb/dut', ports)
    assert result['window'] == {'start_tick': 0, 'end_tick': 2, 'timescale': '1ns',
                                'authority': 'measured complete self-checking testbench VCD'}
    assert result['ports']['x']['width'] == 4
    assert result['ports']['x']['transitions'] == 1
    assert result['ports']['clk']['initial_unknown_observations'] == 1
    assert 'internal_net' not in result['ports']


def test_measured_vcd_census_refuses_unknown_after_activity_started(tmp_path):
    vcd = tmp_path / 'late-x.vcd'
    vcd.write_text('$timescale 1ns $end\n$scope module dut $end\n'
                   '$var wire 1 ! clk $end\n$upscope $end\n$enddefinitions $end\n'
                   '#0\n0!\n#1\nx!\n')
    with pytest.raises(admission.AdmissionRefusal,
                       match='D55_VCD_UNKNOWN_OR_UNOBSERVED_SIGNAL'):
        activity.measured_waveform_census(
            vcd, 'dut', [{'name': 'clk', 'direction': 'input', 'width': 1}])


def test_activity_dump_maps_logical_testbench_top_to_exact_adopted_top(tmp_path):
    adopted = tmp_path / 'adopted.v'
    adopted.write_text('module physical (a, y); input a; output y; assign y = a; endmodule\n')
    tb = tmp_path / 'tb.v'
    tb.write_text('module tb; reg a; wire y; logical dut(.a(a), .y(y)); '
                  'initial begin a=0; #2 a=1; #1 $finish; end endmodule\n')
    calls = []
    def fake(argv, cwd):
        calls.append(argv)
        if argv[0] == 'vvp':
            (Path(cwd) / 'tb.vcd').write_text(
                '$scope module tb $end\n$scope module dut $end\n'
                '$scope module vibeic_adopted $end\n$upscope $end\n'
                '$upscope $end\n$upscope $end\n$enddefinitions $end\n#0\n')
        return 0, '', ''
    result = activity.dump.dump([str(adopted)], [str(tb)], 'physical', tmp_path / 'out',
                                fake, testbench_dut_module='logical')
    assert result['status'] == 'PASS'
    assert result['scope'] == 'tb/dut/vibeic_adopted'
    mapping = result['logical_to_adopted_mapping']
    assert mapping['logical_module'] == 'logical' and mapping['adopted_module'] == 'physical'
    assert str(adopted) in calls[0]
    wrapper = Path(mapping['wrapper']).read_text()
    assert 'physical vibeic_adopted (.a(a), .y(y));' in wrapper


def test_generated_oracle_stages_only_positive_edge_sample_delay(tmp_path):
    source = tmp_path / 'oracle.v'
    source.write_text('// VIBEIC_TB_ORACLE: GENERATED\nmodule tb;\n'
                      'initial begin #7 stimulus = 1; @(posedge clk); #1; '
                      'if (actual !== expected) $fatal; end\n'
                      'always @(posedge clk); #1; sample_count = sample_count + 1;\nendmodule\n')
    staged = tmp_path / 'oracle.gls.v'
    receipt = activity.dump._settled_testbench(source, staged, 'clk', 4.8)
    assert source.read_text().count('@(posedge clk); #1;') == 2
    assert staged.read_text().count('@(posedge clk); #4.8;') == 2
    assert '#7 stimulus = 1' in staged.read_text()
    assert 'actual !== expected' in staged.read_text()
    assert receipt['adjusted_sites'] == 2
    assert receipt['original_sha256'] == activity._sha(source)
    assert receipt['staged_sha256'] == activity._sha(staged)


@pytest.mark.parametrize('text, reason', [
    ('module tb; @(posedge clk); #1; endmodule\n', 'generated oracle'),
    ('// VIBEIC_TB_ORACLE: GENERATED\nmodule tb; @(posedge clk); #1; '
     '@(posedge clk); #2; endmodule\n', 'unique positive-edge sample offset'),
])
def test_gls_sample_staging_refuses_unowned_or_ambiguous_driver(tmp_path, text, reason):
    source = tmp_path / 'oracle.v'; source.write_text(text)
    with pytest.raises(ValueError, match=reason):
        activity.dump._settled_testbench(source, tmp_path / 'staged.v', 'clk', 4.8)
    assert not (tmp_path / 'staged.v').exists()


def _scenario_authority_files(tmp_path, *, pad_voltage='5.0'):
    paths = {}
    paths['sdc'] = tmp_path / 'constraints.sdc'
    paths['sdc'].write_text('create_clock -name clk -period 24.0 [get_ports clk]\n'
                            'set_output_delay 4.8 -clock clk [all_outputs]\n'
                            'set_load 0.07291 [all_outputs]\n')
    paths['liberty'] = tmp_path / 'cells.lib'
    paths['liberty'].write_text('library(cells) {\n nom_voltage : 5;\n'
                                ' capacitive_load_unit(1, pf);\n}\n')
    paths['pad_liberty'] = tmp_path / 'pads.lib'
    paths['pad_liberty'].write_text(
        f'library(pads) {{\n nom_voltage : {pad_voltage};\n'
        ' default_power_rail : "VDD";\n power_rail("VDD", 5.0);\n}\n')
    paths['io_connectivity'] = tmp_path / 'chip_top_io.v'
    paths['io_connectivity'].write_text(
        'module chip_top_io(input clk, output p, input VDD, input VSS);\n'
        '  output_pad u_pad_p (.PAD(p), .VDD(VDD), .VSS(VSS));\nendmodule\n')
    return paths


def test_scenario_authority_derives_existing_sdc_liberty_and_pad_connectivity(tmp_path):
    paths = _scenario_authority_files(tmp_path)
    result = activity._derive_scenario_authority(paths, [
        {'name': 'clk', 'direction': 'input', 'width': 1},
        {'name': 'p', 'direction': 'output', 'width': 1}])
    assert result['clock'] == 'clk'
    assert result['period_ns'] == 24.0
    assert result['gls_sample_offset_ns'] == 4.8
    assert result['external_loads'] == {
        'rails': {'VDD': {'voltage_v': 5.0}},
        'ports': {'p': {'rail': 'VDD', 'capacitance_library_units': 0.07291}}}
    assert result['quotes']['capacitance_unit'] == {'scale': 1.0, 'unit': 'pf'}
    assert all(item['sha256'] == activity._sha(item['path'])
               for item in result['source_records'].values())


@pytest.mark.parametrize('command,replacement', [
    ('create_clock', 'do not create_clock'),
    ('set_output_delay', 'please do not infer set_output_delay'),
    ('set_load', 'the instruction is not to set_load'),
])
def test_scenario_authority_rejects_prose_about_formal_commands(
        tmp_path, command, replacement):
    paths = _scenario_authority_files(tmp_path)
    canonical = paths['sdc'].read_text()
    paths['sdc'].write_text(canonical.replace(command, replacement, 1))
    with pytest.raises(admission.AdmissionRefusal,
                       match='D55_SDC_ACTIVITY_AUTHORITY_UNIMPLEMENTED'):
        activity._derive_scenario_authority(paths, [
            {'name': 'clk', 'direction': 'input', 'width': 1},
            {'name': 'p', 'direction': 'output', 'width': 1}])


@pytest.mark.parametrize('prose', [
    'Do not declare module adopted with input a and output y.\n',
    'Please use a module named adopted, but do not state its ports here.\n',
])
def test_module_port_census_rejects_prose_about_formal_declarations(
        tmp_path, prose):
    canonical = tmp_path / 'canonical.v'
    canonical.write_text(
        '// do not treat module denied(input fake) as a declaration\n'
        'module adopted (a, y); input a; output y; endmodule\n')
    assert activity.dump.module_ports(canonical, 'adopted') == [
        {'name': 'a', 'direction': 'input', 'width': 1, 'packed': ''},
        {'name': 'y', 'direction': 'output', 'width': 1, 'packed': ''}]
    discussed = tmp_path / 'discussed.v'
    discussed.write_text(prose)
    with pytest.raises(ValueError, match='module adopted not found'):
        activity.dump.module_ports(discussed, 'adopted')


@pytest.mark.parametrize('clock_command,clock_name', [
    ('create_clock -name core_clock -period 24 [get_ports clk]', 'core_clock'),
    ('create_clock -period 24 -name core_clock [get_ports clk]', 'core_clock'),
    ('create_clock -period 24 [get_ports clk]', 'clk'),
], ids=['named-before-period', 'named-after-period', 'unnamed'])
def test_scenario_authority_resolves_clock_name_to_input_port(
        tmp_path, clock_command, clock_name):
    paths = _scenario_authority_files(tmp_path)
    # Neutral control load only; this is not an adopted case constraint.
    paths['sdc'].write_text(
        f'{clock_command}\nset_output_delay 4.8 -clock {clock_name} [all_outputs]\n'
        'set_load 0.125 [all_outputs]\n')
    result = activity._derive_scenario_authority(paths, [
        {'name': 'clk', 'direction': 'input', 'width': 1},
        {'name': 'p', 'direction': 'output', 'width': 1}])
    assert result['clock'] == 'clk'
    assert result['period_ns'] == 24.0
    assert result['gls_sample_offset_ns'] == 4.8
    assert result['quotes']['clock'] == clock_command
    assert result['external_loads']['ports']['p']['capacitance_library_units'] == 0.125
    assert result['source_records']['sdc']['sha256'] == activity._sha(paths['sdc'])


@pytest.mark.parametrize('clock_command,delay_clock,load_command', [
    ('create_clock -name core_clock -period 24 [get_ports absent]', 'core_clock',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports p]', 'core_clock',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports x]', 'core_clock',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports clk]', 'unknown_clock',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports clk]', 'clk',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 -name core_clock [get_ports clk]',
     'core_clock', 'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports clk]\n'
     'create_clock -period 24 [get_ports clk]', 'core_clock',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -waveform {0 12} -name core_clock -period 24 [get_ports clk]',
     'core_clock', 'set_load 0.125 [all_outputs]'),
    ('create_clock -name -period 24 [get_ports clk]', 'clk',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports clk*]', 'core_clock',
     'set_load 0.125 [all_outputs]'),
    ('create_clock -name core_clock -period 24 [get_ports clk]', 'core_clock',
     '# no adopted external load'),
], ids=['absent-port', 'output-port', 'vector-port', 'unknown-clock', 'port-as-clock-name',
        'duplicate-name', 'duplicate-clock', 'unsupported-option', 'missing-name',
        'wildcard-port', 'missing-load'])
def test_scenario_authority_refuses_unresolved_named_clock(
        tmp_path, clock_command, delay_clock, load_command):
    paths = _scenario_authority_files(tmp_path)
    paths['sdc'].write_text(
        f'{clock_command}\nset_output_delay 4.8 -clock {delay_clock} [all_outputs]\n'
        f'{load_command}\n')
    with pytest.raises(admission.AdmissionRefusal,
                       match='D55_SDC_ACTIVITY_AUTHORITY_UNIMPLEMENTED'):
        activity._derive_scenario_authority(paths, [
            {'name': 'clk', 'direction': 'input', 'width': 1},
            {'name': 'x', 'direction': 'input', 'width': 2},
            {'name': 'p', 'direction': 'output', 'width': 1}])


def test_scenario_authority_refuses_cell_pad_corner_mismatch(tmp_path):
    paths = _scenario_authority_files(tmp_path, pad_voltage='3.3')
    with pytest.raises(admission.AdmissionRefusal, match='D55_RAIL_LIBRARY_MISMATCH'):
        activity._derive_scenario_authority(paths, [
            {'name': 'p', 'direction': 'output', 'width': 1}])


def test_native_port_census_expands_vector_bits_without_weakening_scalars():
    assert activity._native_port_names([
        {'name': 'clk', 'width': 1, 'packed': ''},
        {'name': 'x', 'width': 4, 'packed': '[3:0]'},
        {'name': 'y', 'width': 3, 'packed': '[0:2]'}]) == [
            'clk', 'x[3]', 'x[2]', 'x[1]', 'x[0]', 'y[0]', 'y[1]', 'y[2]']


def test_canonical_d55_engineering_route_needs_no_generic_qualification(tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, 'ic') is None
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ''))
        monkeypatch.delenv(name)
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': features}))
    observed = []
    monkeypatch.setitem(sys.modules, 'flow109_functional_activity', SimpleNamespace(
        execute=lambda project, context: observed.append(context) or {
            'component_status': 'NOT_MEASURED', 'flow109_acceptance': 'NOT_MEASURED'}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode='default', entry_step='D55', exit_step='D55')
    assert flow109.prepare_front_door(args, tmp_path) == 2
    assert observed[0]['requested_step'] == 'D55'
    assert observed[0]['runtime_tool_uses'] is None
    assert observed[0]['qualification_registry'] is None
    admitted = json.loads(
        (tmp_path / 'reports/flow109/admission.json').read_text())
    assert admitted['status'] == 'NOT_APPLICABLE'
    assert admitted['reason'] == 'SOURCE_OWNED_EXISTING_NATIVE_COMPONENT'
    assert admitted['qualification_status'] == 'NOT_CLAIMED'
    assert admitted['acceptance_scope'] == 'existing_native_component_only'
    assert admitted['native_step_id'] == 'flow109.D55'
    assert admitted['flow109_acceptance'] == 'NOT_MEASURED'
    assert admitted['whole_flow_acceptance'] == 'NOT_MEASURED'


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return activity._record(project, path)


def _case(project):
    from librelane.config import Config
    from librelane.steps.yosys import EQY
    config, _ = Config.load({'DESIGN_NAME': 'activity_beta', 'PDK': 'gf180mcuD',
        'STD_CELL_LIBRARY': 'gf180mcu_fd_sc_mcu7t5v0', 'VERILOG_FILES': []},
        EQY.get_all_config_variables(), design_dir=str(project), pdk_root='/foss/pdks')
    library = Path(next(iter(next(group for pattern, group in config['CELL_LIBS'].items()
                        if fnmatch.fnmatch(config['DEFAULT_CORNER'], pattern)))))
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                           'fixtures', 'flow109_functional_activity')
    _put(project, 'inputs/reference.v', (fixture / 'rtl.v').read_text())
    script = project / 'map.ys'
    script.write_text('read_verilog inputs/reference.v\nsynth -top activity_beta\n'
                     f'abc -liberty {library}\nclean\nwrite_verilog -noattr inputs/adopted.v\n')
    result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    tb = _put(project, 'inputs/workload.v', (fixture / 'tb.v').read_text())
    loads = {'rails': {'core': {'voltage_v': 5.0}}, 'ports': {
        'y': {'rail': 'core', 'capacitance_library_units': 0.05},
        'z': {'rail': 'core', 'capacitance_library_units': 0.07}}}
    requirement = _put(project, 'inputs/requirements.json', {
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
                     'source_reference': 'neutral developer fixture, not a product requirement'},
        'modes': {'mission': {'required_ports': ['a', 'b', 'c', 'y', 'z'],
                             'window': {'start_tick': 0, 'end_tick': 45008, 'timescale': '1ps'}}},
        'external_loads': loads})
    load = _put(project, 'inputs/loads.json', {**loads, 'requirements_sha256': requirement['sha256']})
    liberty = activity._record(project, library)
    models = [activity._record(project, Path(p)) for p in config['CELL_VERILOG_MODELS']]
    manifest = {'schema': activity.SCHEMA, 'basis': 'adopted_netlist_gls', 'top': 'activity_beta',
        'adopted_netlist': activity._record(project, project / 'inputs/adopted.v'),
        'liberty': liberty, 'simulation_models': models, 'requirements': requirement, 'loads': load,
        'sdc': _put(project, 'inputs/constraints.sdc', 'create_clock -name virtual -period 10\n'),
        'modes': {'mission': {'testbench': tb}}}
    _put(project, activity.INPUT, manifest)
    operation = _put(project, 'input/flow109/D55-operation.json',
        {'schema': activity.SCHEMA, 'basis': 'adopted_netlist_gls', 'window': 'full_vcd', 'rail_count': 1})
    pdk = _put(project, 'input/flow109/D55-pdk.json', {'liberty': liberty, 'simulation_models': models})
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(features)
    references = [_put(project, 'qualification-control.json',
        {'scope': 'native developer contract control; not a production qualification'})]
    uses, records = [], []
    for use in flow109.resolve_step(plan, 'D55')['tool_uses']:
        executable = activity._record(project, Path(shutil.which(use['executable_name'])).resolve())
        identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'],
            'version': 'native developer control (executable hash bound)', 'build_sha256': executable['sha256'],
            'executable': executable, 'config': operation, 'pdk': pdk, 'deck': liberty,
            'corner': config['DEFAULT_CORNER'], 'semantics': {'purpose': use['purpose'],
                'native_steps': use['native_steps'], 'operation_sources': activity.operation_sources()}}
        record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                  'reference_evidence': references}
        records.append(record)
        uses.append({**identity, 'qualification_sha256': admission.canonical_sha(record)})
    _put(project, 'qualifications.json', {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records})
    _put(project, 'manifest.json', {'features': features, 'runtime_tool_uses': uses,
                                  'qualification_registry': 'qualifications.json'})
    return flow109.execution_context(plan, 'D55', 'D55', runtime_tool_uses=uses,
                                      qualification_registry='qualifications.json')


def test_actual_front_door_runs_gls_and_consumes_all_data_ports_not_only_clock(tmp_path):
    _case(tmp_path)
    old = _put(tmp_path, 'reports/phase3/power.rpt', 'untouched legacy vectorless power')
    main = activity.HERE / 'vibe_ic_one_shot_runner.py'
    result = subprocess.run([sys.executable, str(main), str(tmp_path), '--flow', '109',
        '--flow109-manifest', str(tmp_path / 'manifest.json'), '--entry-step', 'D55', '--exit-step', 'D55',
        '--route', 'ic', '--no-dashboard'], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads((tmp_path / 'reports/flow109/components/D55.json').read_text())
    assert record['component_status'] == 'PASS', record
    assert record['flow109_acceptance'] == record['final_power_adoption'] == 'NOT_MEASURED'
    mode = record['modes']['mission']
    assert mode['consumption']['activity_provenance']['annotated_pin_activities'] > 0
    assert set(mode['consumption']['ports']) == {'a', 'b', 'c', 'y', 'z'}
    assert all(v['origin'] == 'vcd' for v in mode['consumption']['ports'].values())
    assert mode['census']['ports']['c']['transitions'] > 0
    assert mode['consumption']['power']['total_w'] > 0
    assert len(record['commands']) == 3
    assert activity._record(tmp_path, tmp_path / old['path']) == old
    frozen = json.loads((tmp_path / activity.FREEZE).read_text())
    assert frozen['adopted_netlist']['sha256'] == activity._sha(tmp_path / 'inputs/adopted.v')


@pytest.mark.parametrize('damage, reason', [
    ('mode', 'D55_REQUIRED_MODE_COVERAGE'), ('rtl', 'D55_ACTIVITY_BASIS_UNIMPLEMENTED'),
    ('load', 'D55_LOAD_REQUIREMENT_MISMATCH'), ('source', 'D55_OPERATION_SOURCE_CHANGED'),
    ('stale', 'D55_STALE_OR_MISSING_INPUT'), ('approval', 'D55_REQUIREMENTS_NOT_APPROVED'),
    ('unsupported', 'QUALIFICATION_UNSUPPORTED')])
def test_bad_scope_or_unqualified_inputs_never_launch_native(tmp_path, monkeypatch, damage, reason):
    context = _case(tmp_path)
    manifest = json.loads((tmp_path / activity.INPUT).read_text())
    if damage == 'mode':
        manifest['modes'] = {}
    elif damage == 'rtl':
        manifest['basis'] = 'rtl_vcd'
    elif damage == 'load':
        manifest['loads'] = _put(tmp_path, 'inputs/wrong-load.json', {'ports': {}, 'rails': {}})
    elif damage == 'source':
        monkeypatch.setattr(activity, 'operation_sources', lambda: {'changed': 'source'})
    elif damage == 'stale':
        (tmp_path / 'inputs/adopted.v').write_text('module stale; endmodule')
    elif damage == 'approval':
        requirement = json.loads((tmp_path / 'inputs/requirements.json').read_text())
        requirement['approval']['authority'] = 'AI'
        manifest['requirements'] = _put(tmp_path, 'inputs/requirements.json', requirement)
    else:
        registry = json.loads((tmp_path / 'qualifications.json').read_text())
        registry['uses'][0]['status'] = 'UNSUPPORTED'
        (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    _put(tmp_path, activity.INPUT, manifest)
    calls = []
    monkeypatch.setattr(activity.dump, 'dump', lambda *a: calls.append('native'))
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED', record
    assert reason in record['reason'], record
    assert calls == [] and not record['native_started']
    assert not (tmp_path / activity.FREEZE).exists()


def test_simulator_failure_with_partial_vcd_cannot_freeze_activity(tmp_path):
    context = _case(tmp_path)
    path = tmp_path / activity.INPUT
    manifest = json.loads(path.read_text())
    text = (tmp_path / 'inputs/workload.v').read_text().replace('#5; $finish;', '#5; $fatal(1, "late failure");')
    manifest['modes']['mission']['testbench'] = _put(tmp_path, 'inputs/workload.v', text)
    _put(tmp_path, activity.INPUT, manifest)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'FAIL'
    assert record['reason'] == 'D55_NATIVE_TOOL_FAILED'
    assert record['native_started'] and not (tmp_path / activity.FREEZE).exists()


def test_native_wrong_vcd_scope_does_not_pass_on_vectorless_nonzero_power(tmp_path, monkeypatch):
    context = _case(tmp_path)
    original = activity.dump.dump
    def wrong(*args):
        result = original(*args)
        result['scope'] = 'workload/wrong_dut'
        return result
    monkeypatch.setattr(activity.dump, 'dump', wrong)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert record['reason'] == 'D55_VCD_REQUIRED_SIGNAL_MISSING'
    assert len(record['commands']) == 2


def test_actual_power_rejects_clock_only_or_fallback_data_annotation(tmp_path):
    context = _case(tmp_path)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'PASS', record
    path = tmp_path / record['modes']['mission']['power_report']['path']
    text = path.read_text()
    assert 'D55_ACTIVITY c ' in text
    # All waveforms and nonzero power remain; only a required DATA port's
    # native origin changes to vectorless fallback.
    import re
    changed = re.sub(r'(^D55_ACTIVITY c .*?) vcd$', r'\1 input', text, flags=re.M)
    assert changed != text
    path.write_text(changed)
    spec = json.loads((tmp_path / 'inputs/requirements.json').read_text())['modes']['mission']
    loads = json.loads((tmp_path / 'inputs/loads.json').read_text())
    with pytest.raises(admission.AdmissionRefusal, match='D55_REQUIRED_PORT_NOT_VCD_ANNOTATED'):
        activity.consume_power(path, spec, loads, Path(record['receipt']['path']).parent.name)


def test_actual_launch_rechecks_d03_after_preparation(tmp_path, monkeypatch):
    context = _case(tmp_path)
    original = activity.prepare
    def drift(*args):
        result = original(*args)
        path = tmp_path / 'qualifications.json'
        registry = json.loads(path.read_text())
        registry['uses'][0]['status'] = 'UNSUPPORTED'
        path.write_text(json.dumps(registry))
        return result
    monkeypatch.setattr(activity, 'prepare', drift)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert not record['native_started'] and not record['commands']


def test_pinned_librelane_has_no_native_vcd_configuration_and_component_is_not_final_power():
    from librelane.steps.openroad import STAPostPNR
    assert not any('VCD' in v.name or 'SAIF' in v.name for v in STAPostPNR.get_all_config_variables())
    row = next(r for r in flow109.load_registry()['rows'] if r['id'] == 'D55')
    assert row['when'] == 'physical'
    assert row['metric_acceptance_status'] == 'IMPLEMENTED_SOURCE_BOUND'
    assert {o['status'] for o in row['obligations']} == {'IMPLEMENTED_SOURCE_BOUND'}
    assert {o['id']: o['expectation'] for o in row['obligations']} == {
        oid: {**spec, **({'empty_set_policy': 'requires validated absence/applicability evidence'}
                         if spec['operator'] == 'covers_all' else {})}
        for oid, spec in activity.D55_SPECS.items()}


def test_native_power_wrong_scope_rejects_nonzero_vectorless_fallback(tmp_path, monkeypatch):
    context = _case(tmp_path)
    original = activity._power_script
    def wrong(prepared, vcd, scope, *rest):
        return original(prepared, vcd, 'workload/wrong_dut', *rest)
    monkeypatch.setattr(activity, '_power_script', wrong)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert record['reason'] == 'D55_POWER_ANNOTATION_NOT_MEASURED'
    assert len(record['commands']) == 3
    logs = [tmp_path / command['log']['path'] for command in record['commands']]
    assert 'Annotated 0 pin activities' in logs[-1].read_text()
    assert not (tmp_path / activity.FREEZE).exists()


def test_generated_waveform_drift_stops_before_actual_power_launch(tmp_path, monkeypatch):
    context = _case(tmp_path)
    original = activity._power_script
    def drift(prepared, vcd, *rest):
        text = original(prepared, vcd, *rest)
        vcd.write_text(vcd.read_text() + '\n#999999\n')
        return text
    monkeypatch.setattr(activity, '_power_script', drift)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert record['reason'] == 'D55_STALE_OR_MISSING_INPUT'
    assert len(record['commands']) == 2
    assert not (tmp_path / activity.FREEZE).exists()


def test_missing_output_load_is_rejected_by_actual_native_port_census(tmp_path):
    context = _case(tmp_path)
    manifest = json.loads((tmp_path / activity.INPUT).read_text())
    req = json.loads((tmp_path / 'inputs/requirements.json').read_text())
    del req['external_loads']['ports']['z']
    manifest['requirements'] = _put(tmp_path, 'inputs/requirements.json', req)
    manifest['loads'] = _put(tmp_path, 'inputs/loads.json',
        {**req['external_loads'], 'requirements_sha256': manifest['requirements']['sha256']})
    _put(tmp_path, activity.INPUT, manifest)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert record['reason'] == 'D55_OUTPUT_LOAD_COVERAGE'
    assert len(record['commands']) == 3
    assert not (tmp_path / activity.FREEZE).exists()


@pytest.mark.parametrize('kind', ['sdc', 'simulation'])
def test_unbound_transitive_file_inputs_are_rejected_before_native(tmp_path, monkeypatch, kind):
    context = _case(tmp_path)
    manifest = json.loads((tmp_path / activity.INPUT).read_text())
    if kind == 'sdc':
        manifest['sdc'] = _put(tmp_path, 'inputs/constraints.sdc', 'source unbound.sdc\n')
        reason = 'D55_SDC_SCOPE_UNIMPLEMENTED'
    else:
        text = (tmp_path / 'inputs/workload.v').read_text().replace('integer i;',
            'integer i; reg [7:0] memory [0:7]; initial $readmemh("unbound.hex", memory);')
        manifest['modes']['mission']['testbench'] = _put(tmp_path, 'inputs/workload.v', text)
        reason = 'D55_TRANSITIVE_SIMULATION_INPUT_UNIMPLEMENTED'
    _put(tmp_path, activity.INPUT, manifest)
    calls = []
    monkeypatch.setattr(activity.dump, 'dump', lambda *a: calls.append('native'))
    record = activity.execute(tmp_path, context)
    assert record['reason'] == reason, record
    assert record['component_status'] == 'NOT_MEASURED'
    assert not calls and not record['native_started']



def test_native_lifetime_uses_owner_supervision_not_fixed_wall_clock_kill(tmp_path, monkeypatch):
    context = _case(tmp_path)
    original = subprocess.run
    launched = []
    def supervised(argv, *args, **kwargs):
        assert 'timeout' not in kwargs
        launched.append(argv)
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(activity.subprocess, 'run', supervised)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'PASS', record
    assert len(launched) == len(record['commands']) == 3
    assert record['flow109_acceptance'] == record['final_power_adoption'] == 'NOT_MEASURED'


def test_unknown_engine_from_producer_has_no_raw_argv_fallback(tmp_path, monkeypatch):
    context = _case(tmp_path)
    def undeclared(*args):
        return args[-1](['unqualified-engine', 'do-not-start'], str(tmp_path))
    monkeypatch.setattr(activity.dump, 'dump', undeclared)
    record = activity.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert record['reason'] == 'D55_UNDECLARED_ENGINE'
    assert not record['native_started'] and not record['commands']
    assert not (tmp_path / activity.FREEZE).exists()


def _row_context():
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    return flow109.execution_context(flow109.resolve_plan(features), 'D55', 'D55')


def _sealed_row_command_failure(project):
    producer = project / 'producer'
    consumer = project / 'consumer'
    producer.mkdir(); consumer.mkdir()
    freeze = {'schema': activity.SCHEMA, 'context_sha256': 'producer-context',
        'flow109_acceptance': 'NOT_MEASURED', 'final_power_adoption': 'NOT_MEASURED',
        'modes': {}, 'inputs': {}, 'operation_sources': {}}
    frozen = _put(producer, activity.FREEZE, freeze)
    component = {'schema': activity.SCHEMA, 'step_id': 'D55',
        'component_status': 'PASS', 'native_started': True,
        'context_sha256': 'producer-context', 'flow109_acceptance': 'NOT_MEASURED',
        'final_power_adoption': 'NOT_MEASURED', 'modes': {}, 'inputs': {},
        'operation_sources': {}, 'reason': 'D55_GLS_VECTOR_POWER_COMPONENT_MEASURED',
        'commands': [{'argv': ['/tools/vvp'], 'rc': 9}],
        'freeze': {'path': frozen['path'], 'sha256': frozen['sha256']},
        'receipt': {'path': 'reports/flow109/D55/attempt/component.json'}}
    _put(producer, component['receipt']['path'], component)
    canonical = _put(producer, 'reports/flow109/components/D55.json', component)
    inspect = _put(producer, 'native/container-inspect.json', {'sealed': True})
    row_input = {'schema': activity.ROW_INPUT_SCHEMA,
        'producer_project': str(producer), 'producer_source_head': 'producer-head',
        'producer_adapter_sha256': 'producer-adapter',
        'component': canonical, 'freeze': frozen, 'container_inspect': inspect}
    _put(consumer, activity.ROW_INPUT, row_input)
    return producer, consumer


def test_sealed_native_command_failure_remains_failed_row_without_launch(tmp_path, monkeypatch):
    _producer, consumer = _sealed_row_command_failure(tmp_path)
    monkeypatch.setattr(activity.subprocess, 'run',
                        lambda *_a, **_k: pytest.fail('sealed consumer must not launch native'))
    result = activity.consume_sealed_default_row(consumer, _row_context())
    assert (result['default_row_status'], result['reason'], result['native_started']) == (
        'FAIL', 'D55_ROW_NATIVE_COMMAND_FAILED', False)


def test_sealed_authority_mount_relocation_keeps_hash_and_values_strict():
    first = {'clock': 'clk', 'period_ns': 24.0,
        'source_records': {'sdc': {'path': '/work/project/current.sdc', 'sha256': 'a' * 64}}}
    relocated = copy.deepcopy(first)
    relocated['source_records']['sdc']['path'] = '/producer/current.sdc'
    assert activity._authority_identity(first) == activity._authority_identity(relocated)
    relocated['source_records']['sdc']['sha256'] = 'b' * 64
    assert activity._authority_identity(first) != activity._authority_identity(relocated)


@pytest.mark.parametrize('damage, reason', [
    ('missing', 'D55_ROW_EVIDENCE_STALE'),
    ('changed', 'D55_ROW_EVIDENCE_STALE'),
])
def test_missing_or_changed_sealed_component_refuses_before_launch(
        tmp_path, monkeypatch, damage, reason):
    producer, consumer = _sealed_row_command_failure(tmp_path)
    component = producer / 'reports/flow109/components/D55.json'
    if damage == 'missing':
        component.unlink()
    else:
        component.write_text(component.read_text() + '\n')
    monkeypatch.setattr(activity.subprocess, 'run',
                        lambda *_a, **_k: pytest.fail('refusal must precede native launch'))
    result = activity.consume_sealed_default_row(consumer, _row_context())
    assert (result['default_row_status'], result['reason'], result['native_started']) == (
        'NOT_MEASURED', reason, False)


# --- D55 registry obligations: judged against approved, independent authorities ---

def _sha_of(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity():
    return {'producer': {'name': 'p'}, 'checker': {'name': 'c'}, 'tool_execution': {'cid': 'x'},
            'consumed_inputs': {'n': 'a' * 64}, 'requirements': {'r': 'x'}, 'configuration': {'c': 'x'}}


_WAVE = {'netlist_sha256': 'a' * 64, 'top': 'activity_beta', 'scope': 'tb/dut',
         'ports': {'a': 1, 'y': 1, 'bus': 4}, 'timescale': '1ps'}
_LOADS = {'rails': {'DVDD': {'voltage_v': 5.0}},
          'ports': {'y': {'rail': 'DVDD', 'capacitance_pf': 5.0}}}


def _approved(project, relative, schema, body, source_relative, source_key=None):
    source_body = ({source_key: body} if source_key else {'doc': 'L-layer requirement excerpt'})
    source = _put(project, source_relative, source_body)
    _put(project, relative, {'schema': schema, 'approval': {
        'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
        'source_reference': {'path': source['path'], 'sha256': source['sha256']}}, **body})


def _authorities(project, modes=('mission',), wave=None, loads=None):
    import flow109_metric_acceptance as metrics
    _approved(project, activity.MISSION_MODES, metrics.AUTHORITY_SCHEMA,
              {'required_items': [{'name': m} for m in modes]}, 'input/docs/L5_modes.json')
    for relative, source, key, reference in (
            (activity.WAVEFORM_REFERENCE, activity.WAVEFORM_SOURCE, 'activity_waveform_bound_identity',
             wave or {m: dict(_WAVE) for m in modes}),
            (activity.LOAD_REFERENCE, activity.LOAD_SOURCE, 'load_rail_mapping', loads or _LOADS)):
        _approved(project, relative, activity.ADOPTED_SCHEMA,
                  {'reference': reference, 'reference_identity': _identity()}, source, key)


def _measured(modes=('mission',), wave=None, loads=None):
    return {'modes': sorted(modes), 'waveforms': wave or {m: dict(_WAVE) for m in modes},
            'loads': loads or copy.deepcopy(_LOADS)}


def _statuses(project, measured):
    result = activity.accept_d55_obligations(project, _row_context(), measured, _identity())
    return {item['id'].split('.')[-1]: (item['status'], item.get('reason')) for item in result}, result


def test_d55_obligations_pass_only_against_approved_independent_authorities(tmp_path):
    _authorities(tmp_path)
    statuses, _ = _statuses(tmp_path, _measured())
    assert {k: v[0] for k, v in statuses.items()} == {
        'functional_mission_modes': 'PASS', 'activity_waveform_bound_identity': 'PASS',
        'load_rail_mapping': 'PASS'}


def test_d55_sealed_evidence_without_authorities_is_never_a_pass(tmp_path):
    # The pre-binding row consumer returned PASS here from the producer's own
    # scenario list and freeze; no authority means no expectation was checked.
    statuses, _ = _statuses(tmp_path, _measured())
    assert statuses == {
        'functional_mission_modes': ('NOT_MEASURED', 'METRIC_AUTHORITY_ABSENT'),
        'activity_waveform_bound_identity': ('NOT_MEASURED', 'METRIC_AUTHORITY_ABSENT'),
        'load_rail_mapping': ('NOT_MEASURED', 'METRIC_AUTHORITY_ABSENT')}


def test_d55_unexercised_mission_mode_fails(tmp_path):
    _authorities(tmp_path, modes=('mission', 'standby'))
    statuses, result = _statuses(tmp_path, _measured(modes=('mission',),
        wave={'mission': dict(_WAVE), 'standby': dict(_WAVE)}))
    assert statuses['functional_mission_modes'][0] == 'FAIL'
    assert result[0]['missing_modes'] == ['standby']


@pytest.mark.parametrize('field, value', [
    ('netlist_sha256', 'b' * 64),     # activity from a different netlist
    ('scope', 'tb/other'),            # waveform of another instance
    ('ports', {'a': 1, 'y': 1}),      # a top port absent from the waveform
    ('timescale', '1ns'),
])
def test_d55_waveform_bound_to_another_identity_fails(tmp_path, field, value):
    _authorities(tmp_path)
    wave = {'mission': {**_WAVE, field: value}}
    statuses, result = _statuses(tmp_path, _measured(wave=wave))
    assert statuses['activity_waveform_bound_identity'][0] == 'FAIL'
    assert result[1]['differing_modes'] == ['mission']


@pytest.mark.parametrize('loads', [
    {'rails': {'DVDD': {'voltage_v': 5.0}}, 'ports': {'y': {'rail': 'DVDD', 'capacitance_pf': 0.05}}},
    {'rails': {'VDD': {'voltage_v': 5.0}}, 'ports': {'y': {'rail': 'VDD', 'capacitance_pf': 5.0}}},
    {'rails': {'DVDD': {'voltage_v': 3.3}}, 'ports': {'y': {'rail': 'DVDD', 'capacitance_pf': 5.0}}},
])
def test_d55_load_or_rail_differing_from_adopted_reference_fails(tmp_path, loads):
    _authorities(tmp_path)
    statuses, _ = _statuses(tmp_path, _measured(loads=loads))
    assert statuses['load_rail_mapping'][0] == 'FAIL'


def test_d55_integer_reference_numbers_compare_as_numbers(tmp_path):
    _authorities(tmp_path, loads={'rails': {'DVDD': {'voltage_v': 5}},
                                  'ports': {'y': {'rail': 'DVDD', 'capacitance_pf': 5}}})
    statuses, _ = _statuses(tmp_path, _measured())
    assert statuses['load_rail_mapping'][0] == 'PASS'


def test_d55_reference_not_sourced_from_its_input_is_not_measured(tmp_path):
    _authorities(tmp_path)
    source = tmp_path / activity.LOAD_SOURCE
    body = json.loads(source.read_text())
    body['load_rail_mapping']['reference']['ports']['y']['capacitance_pf'] = 0.05
    source.write_text(json.dumps(body))
    statuses, _ = _statuses(tmp_path, _measured())
    assert statuses['load_rail_mapping'][0] == 'NOT_MEASURED'
    # Re-approving the edited source while the published body still differs.
    reference = json.loads((tmp_path / activity.LOAD_REFERENCE).read_text())
    reference['approval']['source_reference']['sha256'] = _sha_of(source)
    (tmp_path / activity.LOAD_REFERENCE).write_text(json.dumps(reference))
    statuses, _ = _statuses(tmp_path, _measured())
    assert statuses['load_rail_mapping'] == ('NOT_MEASURED', 'D55_REFERENCE_SOURCE_UNBOUND')


def test_d55_unapproved_mission_modes_are_not_measured(tmp_path):
    _authorities(tmp_path)
    path = tmp_path / activity.MISSION_MODES
    body = json.loads(path.read_text())
    body['approval']['status'] = 'PROPOSED'
    path.write_text(json.dumps(body))
    statuses, _ = _statuses(tmp_path, _measured())
    assert statuses['functional_mission_modes'] == ('NOT_MEASURED', 'METRIC_AUTHORITY_UNAPPROVED')


@pytest.mark.parametrize('scale, unit, expected', [
    (1.0, 'pf', 0.05), (1.0, 'ff', 0.00005), (1000.0, 'ff', 0.05)])
def test_d55_measured_loads_are_scaled_by_the_liberty_capacitance_unit(scale, unit, expected):
    authority = {'quotes': {'capacitance_unit': {'scale': scale, 'unit': unit}},
                 'external_loads': {'rails': {'DVDD': {'voltage_v': 5.0}},
                                    'ports': {'y': {'rail': 'DVDD', 'capacitance_library_units': 0.05}}}}
    assert activity.measured_load_rail_mapping(authority)['ports']['y'] == {
        'rail': 'DVDD', 'capacitance_pf': expected}


def test_d55_unknown_capacitance_unit_is_refused():
    authority = {'quotes': {'capacitance_unit': {'scale': 1.0, 'unit': 'kf'}},
                 'external_loads': {'rails': {}, 'ports': {}}}
    with pytest.raises(ValueError, match='D55_LOAD_UNIT_UNSUPPORTED'):
        activity.measured_load_rail_mapping(authority)


def _inspect(tmp_path, image):
    path = tmp_path / 'inspect.json'
    path.write_text(json.dumps([{'Id': 'c' * 64, 'Config': {'Image': image},
        'State': {'ExitCode': 0, 'OOMKilled': False},
        'HostConfig': {'NetworkMode': 'none', 'NanoCpus': 4_000_000_000,
                       'Memory': 8 * 1024 ** 3, 'ReadonlyRootfs': True}}]))
    return path


def test_d55_container_image_is_the_runtime_resolved_identity(tmp_path, monkeypatch):
    import _eda_pin
    current, older = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest', lambda *a, **k: current)
    assert activity._container_identity(_inspect(tmp_path, 'ghcr.io/vibeic/vibeic-eda@' + current))['image'].endswith(current)
    with pytest.raises(admission.AdmissionRefusal, match='D55_ROW_NATIVE_AUTHORITY_INVALID'):
        activity._container_identity(_inspect(tmp_path, 'ghcr.io/vibeic/vibeic-eda@' + older))

    def unresolvable(*_a, **_k):
        raise _eda_pin.ImageNotResolvable(['no image on this host'])
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest', unresolvable)
    with pytest.raises(admission.AdmissionRefusal, match='D55_ROW_IMAGE_NOT_RESOLVABLE'):
        activity._container_identity(_inspect(tmp_path, 'ghcr.io/vibeic/vibeic-eda@' + current))


def test_d55_source_stores_no_image_digest():
    import re as _re
    text = Path(activity.__file__).read_text()
    joined = _re.sub(r"'\s*\n\s*'", '', text)
    assert not _re.search(r'sha256:[0-9a-f]{64}', joined)


def test_d55_waveform_proposal_reads_netlist_ports_for_every_approved_mode(tmp_path):
    _authorities(tmp_path, modes=('mission', 'standby'))
    for path in (tmp_path / activity.WAVEFORM_SOURCE, tmp_path / activity.WAVEFORM_REFERENCE):
        path.unlink()
    netlist = tmp_path / 'adopted.v'
    netlist.write_text('module activity_beta(a, bus, y);\n  input a;\n  input [3:0] bus;\n'
                       '  output y;\n  assign y = a;\nendmodule\n')
    proposed = activity.propose_waveform_reference(tmp_path, netlist, 'activity_beta', 'tb/dut', '1ps')
    assert proposed['modes'] == ['mission', 'standby']
    body = json.loads((tmp_path / activity.WAVEFORM_SOURCE).read_text())
    reference = body['activity_waveform_bound_identity']['reference']
    assert reference['mission'] == {**_WAVE, 'netlist_sha256': _sha_of(netlist)}
    with pytest.raises(ValueError, match='D55_WAVEFORM_SOURCE_EXISTS'):
        activity.propose_waveform_reference(tmp_path, netlist, 'activity_beta', 'tb/dut', '1ps')
