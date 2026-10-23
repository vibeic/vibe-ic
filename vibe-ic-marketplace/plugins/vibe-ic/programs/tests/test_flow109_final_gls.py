"""D71 actual Icarus/vvp final-SDF component controls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from flow109_admission import AdmissionRefusal

import flow109
import flow109_admission as admission
import flow109_final_gls as final_gls
import flow109_final_lec as final_lec
import flow109_final_extract as final_extract
import flow109_final_electrical as final_electrical


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return final_gls._record(project, path)


NETLIST = '''
module final_gls_dut(input a, output y);
  delay_cell u0(.A(a), .Z(y));
endmodule
'''

MODEL = '''
`timescale 1ns/1ps
module delay_cell(input A, output Z);
  buf (Z, A);
  specify
    (A => Z) = (1, 1);
  endspecify
endmodule
'''

SDF = '''
(DELAYFILE
 (SDFVERSION "3.0")
 (DESIGN "final_gls_dut")
 (DATE "neutral D71 component control")
 (VENDOR "source fixture")
 (PROGRAM "OpenSTA write_sdf compatible subset")
 (VERSION "1")
 (DIVIDER /)
 (TIMESCALE 1ns)
 (CELL
  (CELLTYPE "final_gls_dut")
  (INSTANCE)
  (DELAY (ABSOLUTE (INTERCONNECT a u0/A (1:1:1))))
 )
 (CELL
  (CELLTYPE "delay_cell")
  (INSTANCE u0)
  (DELAY (ABSOLUTE (IOPATH A Z (1:1:1) (1:1:1))))
 )
)
'''

BENCH = '''
`timescale 1ns/1ps
module d71_functional;
  reg a = 0;
  wire y;
  final_gls_dut dut(.a(a), .y(y));
  initial begin
    $sdf_annotate("@@VIBEIC_SDF_FILE@@", dut);
    #3 a = 1;
    #3;
    if (y !== 1'b1) begin
      $display("[TB functional] FAIL");
      $finish_and_return(1);
    end
    $display("[TB functional] PASS");
    $finish;
  end
endmodule
'''


def _case(project):
    netlist = _put(project, 'inputs/final.v', NETLIST)
    model = _put(project, 'inputs/cells.v', MODEL)
    sdc = _put(project, 'inputs/final.sdc', 'set_input_delay 0 [get_ports a]\n')
    sdf = _put(project, 'inputs/final_tt.sdf', SDF)
    bench = _put(project, 'inputs/d71_tb.v', BENCH)
    spef = _put(project, 'inputs/final_tt.spef', '*SPEF "IEEE 1481-1998"\n*DESIGN "final_gls_dut"\n')
    geometry = _put(project, 'inputs/final-geometry.json',
                    {'producer': 'D64', 'scope': 'neutral component control'})

    proof = _put(project, 'reports/flow109/D44/proof.json', {'verdict': 'PASS',
        'declared_partitions': ['final_gls_dut'], 'partitions': {'final_gls_dut': {'status': 'PASS'}},
        'non_equivalent_points': [], 'unproven_points': [], 'xbits_partitions': []})
    baseline = {'schema': 'vibeic.flow109.final-lec.v1', 'producer': 'flow109_final_lec',
        'context_sha256': 'neutral-d44-control', 'source_sha256': {}, 'rtl': [netlist],
        'adopted_netlist': netlist,
        'consumer_netlists': {role: copy.deepcopy(netlist) for role in ('sta', 'lvs_reference', 'release')},
        'transformations': [], 'mapping': 'same_logical_bytes',
        'consumer_adoption': 'NOT_MEASURED', 'proof': proof}
    baseline_record = _put(project, final_gls.D44_BASELINE, baseline)
    d44 = _put(project, 'reports/flow109/D44/component.json',
        {'schema': 'vibeic.flow109.final-lec.v1', 'step_id': 'D44', 'component_status': 'PASS',
         'flow109_acceptance': 'NOT_MEASURED', 'common_baseline': baseline_record,
         'proof': json.loads((project / proof['path']).read_text()), 'proof_receipt': proof})
    d69 = _put(project, 'reports/flow109/D69/component.json',
        {'schema': 'vibeic.flow109.final-extract.v1', 'step_id': 'D69',
         'producer': 'flow109_final_extract', 'component_status': 'PASS',
         'flow109_acceptance': 'NOT_MEASURED', 'final_geometry': geometry,
         'final_spefs': {'tt': spef}})
    d70_doc = {'schema': final_gls.D70_SCHEMA, 'step_id': 'D70',
        'producer': 'flow109_final_electrical', 'component_status': 'PASS',
        'flow109_acceptance': 'NOT_MEASURED', 'sdf_role': 'final',
        'netlist': netlist, 'sdc': sdc, 'required_corners': ['tt'],
        'final_sdfs': {'tt': sdf}, 'd69_receipt': d69,
        'sdf_provenance': {'basis': 'D69_final_parasitics', 'd69_receipt': d69,
                           'declared_corners': ['tt'],
                           'spef_by_rc_scene': {'tt': spef}}}
    state = _put(project, 'reports/flow109/D70/state_out.json', {
        'nl': str((project / netlist['path']).resolve()),
        'sdc': str((project / sdc['path']).resolve()),
        'spef': {'tt': str((project / spef['path']).resolve())},
        'sdf': {'tt': str((project / sdf['path']).resolve())}})
    d70_doc['sta_state'] = state
    d70_doc['sdf_provenance']['sta_state'] = state
    d70 = _put(project, 'reports/flow109/D70/component.json', d70_doc)
    requirements = _put(project, 'requirements/final_gls.json', {
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': 'neutral D71 native component contract'},
        'required_corners': ['tt'], 'required_scenarios': ['functional'],
        'required_timing_behaviors': ['sdf_delay_annotation', 'functional_self_check']})
    operation = _put(project, 'input/flow109/D71-operation.json', {
        'schema': final_gls.SCHEMA, 'operation': 'Vibeic.GateLevelSim',
        'compile_flags': '-g2012 -ginterconnect -gspecify', 'runtime_flags': ['-sdf-info']})
    bundle = _put(project, 'input/flow109/D71-models.json',
                  {'models': [model], 'model_closure': 'exact'})
    manifest = {'schema': final_gls.SCHEMA, 'top': 'final_gls_dut',
        'd44_baseline': baseline_record, 'd44_component': d44, 'd70_receipt': d70,
        'requirements': requirements, 'models': [model],
        'scenarios': {'functional': {'module': 'd71_functional', 'testbench': bench}},
        'operation_config': operation, 'model_bundle': bundle}
    _put(project, final_gls.INPUT, manifest)

    features = next(item['features'] for item in flow109.load_registry()['reference_profiles']
                    if item['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(features)
    references = [_put(project, 'input/D71-qualification-control.json',
                       {'scope': 'native D71 developer control; not final qualification'})]
    uses, records = [], []
    for use in flow109.resolve_step(plan, 'D71')['tool_uses']:
        binary = Path(shutil.which(use['executable_name'])).resolve()
        executable = final_gls._record(project, binary)
        identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'],
            'version': subprocess.run([str(binary), '-V'], capture_output=True, text=True).stdout.strip()[:120] or 'native',
            'build_sha256': executable['sha256'], 'executable': executable,
            'config': operation, 'pdk': bundle, 'deck': requirements, 'corner': 'tt',
            'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                          'operation_sources': final_gls.operation_sources()}}
        record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                  'reference_evidence': references}
        records.append(record)
        uses.append({**identity, 'qualification_sha256': admission.canonical_sha(record)})
    _put(project, 'D71-qualifications.json',
         {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records})
    selection = {'features': features, 'runtime_tool_uses': uses,
                 'qualification_registry': 'D71-qualifications.json'}
    _put(project, 'D71-selection.json', selection)
    return selection


def _admit_substrate_only(project, monkeypatch):
    """Keep native Icarus controls separate from canonical upstream authority."""
    manifest = json.loads((project / final_gls.INPUT).read_text())
    monkeypatch.setattr(final_gls.final_lec, 'validate_common_baseline',
        lambda *_: {'baseline': manifest['d44_baseline'], 'component_current': True})
    def parasitics(_project, receipt):
        d69 = json.loads((project / receipt['path']).read_text())
        return {'final_geometry': d69['final_geometry'], 'final_spefs': d69['final_spefs'],
                'component_parasitics_current': True}
    def electrical(_project, receipt):
        d70 = json.loads((project / receipt['path']).read_text())
        return {'sta_state': d70['sta_state'], 'final_sdfs': d70['final_sdfs'],
                'required_corners': d70['required_corners'],
                'component_electrical_current': True}
    monkeypatch.setattr(final_gls.final_extract, 'validate_final_parasitics', parasitics)
    monkeypatch.setattr(final_gls.final_electrical, 'validate_final_electrical', electrical)


def _replace_with_owning_producer_receipts(project, monkeypatch, corners=('tt',)):
    """Emit D44/D69/D70 receipts through their real row-local producers.

    Heavy EQY/RCX/STA subprocesses are bounded source controls here; the actual
    Icarus substrate remains exercised separately.  Their owning producers and
    validators, receipt construction, source checks and consumers are real.
    """
    manifest_path = project / final_gls.INPUT
    manifest = json.loads(manifest_path.read_text())
    netlist = manifest['d44_baseline']
    old_baseline = json.loads((project / netlist['path']).read_text())
    adopted = old_baseline['adopted_netlist']
    liberty = _put(project, 'inputs/owner-control.lib', 'library(owner_control) { }\n')
    pdk_root = project / 'inputs/pdk'; pdk_root.mkdir()
    d44_manifest = {'schema': final_lec.SCHEMA, 'top': 'final_gls_dut',
        'rtl': [adopted], 'adopted_netlist': adopted, 'liberty': liberty,
        'librelane': {'PDK': 'neutral', 'STD_CELL_LIBRARY': 'neutral',
                     'pdk_root': str(pdk_root)}, 'transformations': [],
        'consumer_netlists': {role: copy.deepcopy(adopted)
                              for role in ('sta', 'lvs_reference', 'release')}}
    _put(project, final_lec.INPUT, d44_manifest)
    d44_config = _put(project, 'input/flow109/D44-owner-operation.json',
        {'schema': final_lec.SCHEMA, 'operation': 'Yosys.EQY', 'transformations': []})
    d44_pdk = _put(project, 'input/flow109/D44-owner-pdk.json',
        {'librelane': d44_manifest['librelane'], 'liberty': liberty})
    features = next(item['features'] for item in flow109.load_registry()['reference_profiles']
                    if item['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(features)
    executable = {'path': '/bin/true', 'sha256': final_gls._sha('/bin/true')}
    d44_uses = [{'use_id': use['use_id'], 'tool_id': use['tool_id'],
        'version': 'owner source control', 'build_sha256': executable['sha256'],
        'executable': executable, 'qualification_sha256': executable['sha256'],
        'config': d44_config, 'pdk': d44_pdk, 'deck': liberty,
        'semantics': {'operation_sources': final_lec.operation_sources()}}
        for use in flow109.resolve_step(plan, 'D44')['tool_uses']]
    d44_context = flow109.execution_context(plan, 'D44', 'D44', runtime_tool_uses=d44_uses,
                                             qualification_registry='owner-control')
    monkeypatch.setattr(final_lec, 'require_launch_admission', lambda *args, **kwargs: None)
    monkeypatch.setattr(final_lec, '_model_census',
                        lambda *args, **kwargs: {'gold': {'modules': ['final_gls_dut']},
                                                'gate': {'modules': ['final_gls_dut']}})
    monkeypatch.setattr(final_lec, '_native_eqy', lambda *args, **kwargs: (None, {}))
    def proof_control(_folder, output):
        proof = {'verdict': 'PASS', 'declared_partitions': ['final_gls_dut'],
                 'partitions': {'final_gls_dut': {'owner_control': 'PASS'}},
                 'compared_points': 1, 'proven_points': 1,
                 'non_equivalent_points': [], 'unproven_points': [], 'xbits_partitions': []}
        output.write_text(json.dumps(proof))
        return proof
    monkeypatch.setattr(final_lec, 'consume_eqy', proof_control)
    d44 = final_lec.execute(project, d44_context)
    assert d44['component_status'] == 'PASS', d44
    d44_receipt = final_gls._record(project, project / d44['receipt']['path'])
    baseline = final_gls._record(project, project / final_lec.BASELINE)

    geometry = _put(project, 'inputs/owner-filled.odb', 'owner filled ODB control\n')
    routed_def = _put(project, 'inputs/owner-filled.def', 'VERSION 5.8 ; DESIGN final_gls_dut ; END DESIGN\n')
    sdc = manifest['d70_receipt']
    old_d70 = json.loads((project / sdc['path']).read_text())
    sdc = old_d70['sdc']
    d62_doc = {'outputs': {'filled.def': routed_def, 'filled.odb': geometry}}
    d62 = _put(project, 'reports/flow109/D62/owner-component.json', d62_doc)
    bridge = _put(project, 'reports/flow109/D64/owner-bridge.json', {'scope': 'owner control'})
    monkeypatch.setattr(final_extract, 'require_launch_admission', lambda *args, **kwargs: None)
    monkeypatch.setattr(final_extract.density, 'validate_filled_odb',
                        lambda *_: {'odb': geometry})
    monkeypatch.setattr(final_extract.files, 'validate_bridge',
                        lambda *_: {'d62_receipt': d62, 'odb': geometry})
    spef_paths = {scene: project / f'inputs/owner-{scene}.spef'
                  for scene in ('nom', 'min', 'max')}
    for path in spef_paths.values():
        path.write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "final_gls_dut"\n')
    rcx = project / 'reports/owner-rcx'; rcx.mkdir(parents=True)
    (rcx / 'state_in.json').write_text('{}')
    (rcx / 'state_out.json').write_text(json.dumps(
        {'spef': {f'{scene}_*': str(path.resolve()) for scene, path in spef_paths.items()}}))
    (rcx / 'vibeic_receipt.json').write_text('{}')
    monkeypatch.setattr(final_extract.signoff, 'run', lambda *args, **kwargs:
        {'rcx': rcx, 'spef': {f'{scene}_*': path for scene, path in spef_paths.items()}})
    monkeypatch.setattr(final_extract.signoff, 'bind_rcx_spefs', lambda *args, **kwargs: {'bound': True})
    spef_facts = {'has_header': True, 'has_design': True, 'd_nets': 1, 'r_nets': 0,
                  'negative_caps': [], 'negative_net_totals': []}
    monkeypatch.setattr(final_extract, 'scan_spef', lambda _path: spef_facts)
    _put(project, final_extract.INPUT, {'schema': final_extract.SCHEMA,
        'd62_receipt': d62, 'stream_bridge': bridge,
        'adopted_views': {'netlist': adopted, 'sdc': sdc},
        'librelane': {'image': 'owner-control', 'pdk_root': str(pdk_root), 'pdk': 'neutral'}})
    d69 = final_extract.execute(project, {'context_sha256': 'owner-d69'})
    assert d69['component_status'] == 'PASS', d69
    d69_receipt = d69['receipt']

    sdf_paths = {}
    for corner in corners:
        path = project / f'inputs/owner-{corner}.sdf'
        path.write_text(SDF)
        sdf_paths[corner] = path
    sta = project / 'reports/owner-sta'; sta.mkdir(parents=True)
    state = {'nl': str((project / adopted['path']).resolve()),
             'sdc': str((project / sdc['path']).resolve()),
             'spef': {f'{scene}_*': str(path.resolve()) for scene, path in spef_paths.items()},
             'sdf': {corner: str(path.resolve()) for corner, path in sdf_paths.items()}}
    (sta / 'state_out.json').write_text(json.dumps(state))
    timing_rows = {corner: {'setup_vio': 0, 'hold_vio': 0, 'max_slew_vio': 0,
                            'max_cap_vio': 0, 'max_fanout_vio': 0} for corner in corners}
    monkeypatch.setattr(final_electrical, 'require_launch_admission', lambda *args, **kwargs: None)
    monkeypatch.setattr(final_electrical.signoff, 'run', lambda *args, **kwargs: {'sta': sta})
    monkeypatch.setattr(final_electrical.signoff, 'corner_timing', lambda _folder: timing_rows)
    monkeypatch.setattr(final_electrical.signoff, 'judge_timing',
                        lambda _rows: {'verdict': 'PASS', 'failing_corners': []})
    monkeypatch.setattr(final_electrical.postroute, 'stapostpnr_state', lambda _project: (sta, state))
    monkeypatch.setattr(final_electrical.postroute, 'corner_sdfs',
                        lambda _state: dict(sdf_paths))
    _put(project, final_electrical.INPUT, {'schema': final_electrical.SCHEMA,
        'final_parasitics_receipt': d69_receipt, 'required_corners': list(corners),
        'librelane': {'image': 'owner-control', 'pdk_root': str(pdk_root), 'pdk': 'neutral'}})
    d70 = final_electrical.execute(project, {'context_sha256': 'owner-d70'})
    assert d70['component_status'] == 'PASS', d70
    d70_receipt = d70['receipt']

    manifest.update(d44_baseline=baseline, d44_component=d44_receipt,
                    d70_receipt=d70_receipt)
    requirements_path = project / manifest['requirements']['path']
    requirements = json.loads(requirements_path.read_text())
    requirements['required_corners'] = list(corners)
    requirements_path.write_text(json.dumps(requirements))
    manifest['requirements'] = final_gls._record(project, requirements_path)
    manifest_path.write_text(json.dumps(manifest))
    return d44_receipt, d69_receipt, d70_receipt


def _execute_substrate(project, selection):
    plan = flow109.resolve_plan(selection['features'])
    context = flow109.execution_context(
        plan, 'D71', 'D71', runtime_tool_uses=selection['runtime_tool_uses'],
        qualification_registry=selection['qualification_registry'])
    context = flow109.component_context(context, native_step_id='flow109.D71')
    return final_gls.execute(project, context)


def _prepare_context():
    return {'requested_step': 'D71', 'native_step_id': 'flow109.D71',
            'runtime_tool_uses': []}


def test_registry_routes_only_the_existing_default_icarus_component():
    features = next(item['features'] for item in flow109.load_registry()['reference_profiles']
                    if item['name'] == 'Small digital IC without DFT')
    row = flow109.resolve_step(flow109.resolve_plan(features), 'D71')
    assert row['profile']['dispatch']['adapter'] == 'flow109_final_gls'
    assert row['profile']['dispatch']['native_step_id'] == 'flow109.D71'
    assert set(row['profile']['dispatch']['engine_families']) == {'iverilog', 'vvp'}
    assert row['metric_acceptance_status'] == 'IMPLEMENTED_D71_RUNTIME'
    assert all(item['status'] == 'IMPLEMENTED_D71_RUNTIME_BINDING'
               for item in row['obligations'])


def test_caller_authored_upstream_pass_receipts_are_not_native_authority(tmp_path):
    _case(tmp_path)
    with pytest.raises(admission.AdmissionRefusal) as caught:
        final_gls.prepare(tmp_path, _prepare_context())
    assert caught.value.code == 'D44_CURRENT_COMPONENT_REQUIRED'


def test_canonical_prepare_reopens_all_three_owning_producers(tmp_path, monkeypatch):
    _case(tmp_path)
    _d44, d69, d70 = _replace_with_owning_producer_receipts(tmp_path, monkeypatch)
    prepared = final_gls.prepare(tmp_path, _prepare_context())
    assert prepared['d44_baseline'] == json.loads(
        (tmp_path / final_gls.INPUT).read_text())['d44_baseline']
    assert prepared['d69_receipt'] == d69
    assert prepared['d70_receipt'] == d70
    assert set(prepared['sdfs']) == {'tt'}


def test_equivalent_corner_population_order_is_not_semantic(tmp_path, monkeypatch):
    _case(tmp_path)
    _replace_with_owning_producer_receipts(tmp_path, monkeypatch, corners=('tt', 'ss'))
    manifest = json.loads((tmp_path / final_gls.INPUT).read_text())
    requirements_path = tmp_path / manifest['requirements']['path']
    requirements = json.loads(requirements_path.read_text())
    requirements['required_corners'] = ['ss', 'tt']
    requirements_path.write_text(json.dumps(requirements))
    manifest['requirements'] = final_gls._record(tmp_path, requirements_path)
    (tmp_path / final_gls.INPUT).write_text(json.dumps(manifest))
    prepared = final_gls.prepare(tmp_path, _prepare_context())
    assert set(prepared['sdfs']) == {'tt', 'ss'}


@pytest.mark.parametrize('damage,reason', [
    ('d44_source', 'D44_OPERATION_SOURCE_CHANGED'),
    ('d69_source', 'D69_OPERATION_SOURCE_CHANGED'),
    ('d70_source', 'D70_OPERATION_SOURCE_CHANGED'),
    ('missing_d69', 'D71_INPUT_UNBOUND'),
])
def test_current_owner_source_or_producer_loss_refuses(tmp_path, monkeypatch, damage, reason):
    _case(tmp_path)
    d44_ref, d69_ref, d70_ref = _replace_with_owning_producer_receipts(tmp_path, monkeypatch)
    manifest_path = tmp_path / final_gls.INPUT
    manifest = json.loads(manifest_path.read_text())
    if damage == 'd44_source':
        path = tmp_path / d44_ref['path']
        value = json.loads(path.read_text()); value['source_sha256'] = {'stale': 'source'}
        path.write_text(json.dumps(value)); manifest['d44_component'] = final_gls._record(tmp_path, path)
    else:
        d70_path = tmp_path / d70_ref['path']
        d70 = json.loads(d70_path.read_text())
        d69_path = tmp_path / d69_ref['path']
        if damage == 'missing_d69':
            d69_path.unlink()
        elif damage == 'd69_source':
            d69 = json.loads(d69_path.read_text()); d69['operation_sources'] = {'stale': 'source'}
            d69_path.write_text(json.dumps(d69))
            fresh = final_gls._record(tmp_path, d69_path)
            d70['d69_receipt'] = d70['final_parasitics_receipt'] = fresh
            d70['sdf_provenance']['d69_receipt'] = fresh
            d70_path.write_text(json.dumps(d70))
            manifest['d70_receipt'] = final_gls._record(tmp_path, d70_path)
        else:
            d70['operation_sources'] = {'stale': 'source'}
            d70_path.write_text(json.dumps(d70))
            manifest['d70_receipt'] = final_gls._record(tmp_path, d70_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(admission.AdmissionRefusal) as caught:
        final_gls.prepare(tmp_path, _prepare_context())
    assert caught.value.code == reason


def test_substrate_actual_default_final_sdf_gls_and_checker_readback(tmp_path, monkeypatch):
    selection = _case(tmp_path)
    _admit_substrate_only(tmp_path, monkeypatch)
    record = _execute_substrate(tmp_path, selection)
    assert record['component_status'] == 'PASS', record
    assert record['flow109_acceptance'] == 'NOT_MEASURED'
    assert record['metric_acceptance_status'] == 'UNIMPLEMENTED'
    assert record['native_started'] is True
    population = record['result']['annotation_population']
    assert population['missing'] == []
    assert population['all_functional_pass'] is True
    assert population['all_corners_annotated'] is True
    assert record['checker']['verdict'] == 'PASS'
    runs = json.loads((tmp_path / record['native']['runs']['path']).read_text())['runs']
    assert len(runs) == 1 and runs[0]['compile_rc'] == runs[0]['sim_rc'] == 0
    transcript = Path(runs[0]['stdout']).read_text()
    assert 'Putting delay' in transcript and '[TB functional] PASS' in transcript
    assert any('timing checks' in item for item in record['limitations'])


@pytest.mark.parametrize('damage,reason', [
    ('functional_output', 'D71_NATIVE_GLS_FAILED'),
    ('annotation', 'D71_NATIVE_GLS_FAILED'),
])
def test_substrate_actual_native_negative_output_and_annotation_are_preserved(
        tmp_path, monkeypatch, damage, reason):
    selection = _case(tmp_path)
    _admit_substrate_only(tmp_path, monkeypatch)
    manifest_path = tmp_path / final_gls.INPUT
    manifest = json.loads(manifest_path.read_text())
    if damage == 'functional_output':
        bench = tmp_path / manifest['scenarios']['functional']['testbench']['path']
        bench.write_text(bench.read_text().replace("if (y !== 1'b1)", "if (y === 1'b1)"))
        manifest['scenarios']['functional']['testbench'] = final_gls._record(tmp_path, bench)
        manifest_path.write_text(json.dumps(manifest))
    else:
        d70_path = tmp_path / manifest['d70_receipt']['path']
        d70 = json.loads(d70_path.read_text())
        sdf = tmp_path / d70['final_sdfs']['tt']['path']
        sdf.write_text(sdf.read_text().replace('u0/A', 'missing_u0/A'))
        d70['final_sdfs']['tt'] = final_gls._record(tmp_path, sdf)
        d70_path.write_text(json.dumps(d70))
        manifest['d70_receipt'] = final_gls._record(tmp_path, d70_path)
        manifest_path.write_text(json.dumps(manifest))
    record = _execute_substrate(tmp_path, selection)
    assert record['component_status'] == 'FAIL' and record['reason'] == reason
    assert record['checker']['verdict'] == 'FAIL'
    corner = record['result']['judge']['corners']['tt']
    if damage == 'functional_output':
        assert 'CASE_FAIL' in corner['reasons']
    else:
        assert 'SDF_NOT_ANNOTATED' in corner['reasons']
    assert not (tmp_path / 'phase3/stage3/sim_postlayout/pass.flag').exists()


@pytest.mark.parametrize('damage,reason', [
    ('candidate', 'D71_FINAL_TIMING_RECEIPT_REQUIRED'),
    ('unsupported_timing', 'D71_REQUIRED_TIMING_BEHAVIOR_UNSUPPORTED'),
    ('missing_corner', 'D71_FINAL_CORNER_BINDING_MISMATCH'),
    ('stale_sdf', 'D71_INPUT_UNBOUND'),
    ('wrong_netlist', 'D71_D70_NETLIST_DIFFERS_FROM_D44'),
    ('wrong_state_sdf', 'D71_FINAL_STATE_IDENTITY_MISMATCH'),
])
def test_substrate_invalid_final_source_or_required_semantics_refuses_before_native(
        tmp_path, monkeypatch, damage, reason):
    selection = _case(tmp_path)
    _admit_substrate_only(tmp_path, monkeypatch)
    manifest_path = tmp_path / final_gls.INPUT
    manifest = json.loads(manifest_path.read_text())
    if damage in ('candidate', 'wrong_netlist', 'wrong_state_sdf'):
        d70_path = tmp_path / manifest['d70_receipt']['path']
        d70 = json.loads(d70_path.read_text())
        if damage == 'candidate':
            d70.update(schema='vibeic.flow109.candidate-timing.v1', step_id='D49', sdf_role='candidate')
        elif damage == 'wrong_netlist':
            d70['netlist'] = _put(tmp_path, 'inputs/not-adopted.v',
                                  NETLIST.replace('delay_cell u0', 'delay_cell changed_instance'))
        else:
            state_path = tmp_path / d70['sta_state']['path']
            state = json.loads(state_path.read_text())
            state['sdf']['tt'] = str((tmp_path / 'inputs/not-the-final.sdf').resolve())
            state_path.write_text(json.dumps(state))
            d70['sta_state'] = final_gls._record(tmp_path, state_path)
            d70['sdf_provenance']['sta_state'] = d70['sta_state']
        d70_path.write_text(json.dumps(d70))
        manifest['d70_receipt'] = final_gls._record(tmp_path, d70_path)
        manifest_path.write_text(json.dumps(manifest))
    elif damage == 'stale_sdf':
        d70 = json.loads((tmp_path / manifest['d70_receipt']['path']).read_text())
        sdf = tmp_path / d70['final_sdfs']['tt']['path']
        sdf.write_text(sdf.read_text() + '\n// changed after D70 publication\n')
    else:
        req_path = tmp_path / manifest['requirements']['path']
        req = json.loads(req_path.read_text())
        if damage == 'unsupported_timing':
            req['required_timing_behaviors'].append('setup_hold_timing_checks')
        else:
            req['required_corners'].append('ss')
        req_path.write_text(json.dumps(req))
        # Keep per-use deck identities current so the refusal comes from the
        # D71 semantic binding rather than admission's stale-file guard.
        new_req = final_gls._record(tmp_path, req_path)
        manifest['requirements'] = new_req
        manifest_path.write_text(json.dumps(manifest))
        qualifications = tmp_path / 'D71-qualifications.json'
        qdoc = json.loads(qualifications.read_text())
        selection = json.loads((tmp_path / 'D71-selection.json').read_text())
        for qitem, use in zip(qdoc['uses'], selection['runtime_tool_uses']):
            qitem['identity']['deck'] = new_req
            use['deck'] = new_req
            use['qualification_sha256'] = admission.canonical_sha(qitem)
        qualifications.write_text(json.dumps(qdoc))
        (tmp_path / 'D71-selection.json').write_text(json.dumps(selection))
    # Reload when the control deliberately rebounded the qualification deck.
    selection = json.loads((tmp_path / 'D71-selection.json').read_text())
    record = _execute_substrate(tmp_path, selection)
    assert record['component_status'] == 'NOT_MEASURED' and record['reason'] == reason
    assert record['native_started'] is False
    assert not list((tmp_path / 'reports/flow109/D71').rglob('gls_runs.json'))


def test_engineering_admission_is_source_owned_and_cannot_rescue_qualification_claim():
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D71', 'D71')
    request = {'execution_scope': final_gls.ENGINEERING_SCOPE}
    assert final_gls._engineering_admission(context, request)
    assert not final_gls._engineering_admission(context, {})
    with pytest.raises(AdmissionRefusal, match='D71_ENGINEERING_OWNER_REQUIRED'):
        final_gls._engineering_admission({**context, 'runtime_tool_uses': []}, request)


@pytest.mark.parametrize('damage', [None, 'source', 'derived', 'catalog'])
def test_engineering_bench_reuses_exact_existing_source_and_annotation_only(tmp_path, damage):
    text = 'module bench; wire y; final_gls_dut dut(.y(y)); initial begin $display("[TB functional] PASS"); $finish; end endmodule\n'
    # The native source locator uses a line-anchored instance declaration.
    text = text.replace('final_gls_dut dut', '\nfinal_gls_dut dut')
    source = _put(tmp_path, 'source/functional.v', text)
    derived = final_gls.sgs.inject_sdf_annotation(text, 'bench', 'dut', final_gls.sgs.SDF_PLACEHOLDER)
    target = _put(tmp_path, 'derived/functional.v', derived)
    catalog = _put(tmp_path, 'source/catalog.json', {'schema': 'vibeic.full_stack_functional.v1',
        'program': 'full_stack_functional_tb', 'cases': [{'name': 'functional', 'state': 'passed',
        'tb': 'source/functional.v', 'tb_sha256': source['sha256']}]})
    item = {'module': 'bench', 'source_testbench': source, 'testbench': target}
    if damage == 'source': (tmp_path / source['path']).write_text(text + '// changed')
    if damage == 'derived':
        (tmp_path / target['path']).write_text(derived.replace('PASS', 'different oracle'))
        item['testbench'] = final_gls._record(tmp_path, tmp_path / target['path'])
    if damage == 'catalog': (tmp_path / catalog['path']).write_text('{}')
    if damage:
        with pytest.raises(AdmissionRefusal):
            final_gls._engineering_bench(tmp_path, {'source_catalog': catalog}, 'functional', item, 'final_gls_dut')
    else:
        assert len(final_gls._engineering_bench(tmp_path, {'source_catalog': catalog}, 'functional', item, 'final_gls_dut')) == 2


def test_engineering_readback_preserves_measured_error_count_without_tb_fail_marker(tmp_path):
    stdout = tmp_path / 'stdout.log'
    stdout.write_text('SDF INFO: Putting delay 1\nFAIL: functional fixed-window bit=0\n'
                      'ARITH_SCENARIO_DONE transactions=25 comparisons=800 errors=24 held_edges=26\n'
                      'FATAL: scenario comparator\n')
    (tmp_path / 'gls_runs.json').write_text(json.dumps({'runs': [{'corner': 'tt', 'case': 'functional',
        'stdout': str(stdout), 'sim_rc': 1}]}))
    judged = {'verdict': 'NOT_EXECUTED', 'corners': {'tt': {'verdict': 'NOT_EXECUTED',
        'reasons': ['NOT_EXECUTED'], 'cases': [{'id': 'functional', 'verdict': None}]}}}
    result = final_gls.engineering_transcript_readback(tmp_path, judged)
    assert result['verdict'] == 'FAIL'
    checks = result['existing_case_readback'][0]['source_self_check']['checks']
    assert checks == {'total': 25, 'comparisons': 800, 'errors': 24}
    assert result['corners']['tt']['cases'][0]['verdict'] == 'FAIL'


def test_final_sampling_cannot_accept_an_arbitrary_delay_or_untyped_tb(tmp_path):
    source = tmp_path / 'bench.v'
    source.write_text('module bench; wire y;\nfinal_gls_dut dut(.y(y)); endmodule\n')
    with pytest.raises(AdmissionRefusal, match='D71_OBSERVATION_UNSUPPORTED'):
        final_gls.engineering_bench_text(tmp_path, source, 'bench', 'final_gls_dut',
                                       observation_schedule='choose_a_passing_delay')
    with pytest.raises(AdmissionRefusal, match='D71_EXISTING_ARITHMETIC_PRODUCER_REQUIRED'):
        final_gls.engineering_bench_text(tmp_path, source, 'bench', 'final_gls_dut',
                                       observation_schedule='native_sta_output_deadline')


def test_bounded_native_cases_overlap_isolate_outputs_and_preserve_failures(tmp_path):
    import threading
    from types import SimpleNamespace
    import sys
    sys.path.insert(0, str(final_gls.HERE / 'librelane_plugins'))
    from librelane.state import DesignFormat
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    active = peak = 0
    cwd = Path.cwd()
    def native(child, state):
        nonlocal active, peak
        manifest = json.loads(Path(child.config['VIBEIC_GLS_MANIFEST']).read_text())
        case = manifest['cases'][0]['id']
        corner = next(iter(state[DesignFormat.SDF]))
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait(timeout=10)
            assert Path.cwd() == cwd
            if corner == 'zz' and case == 'b':
                raise RuntimeError('independent native failure')
            root = Path(child.step_dir)
            child._run(['actual-native-boundary', case], str(root/'compile.log'), 900, cwd=str(root))
            (root/'gls_runs.json').write_text(json.dumps({'runs': [{
                'corner': corner, 'case': case, 'sdf': state[DesignFormat.SDF][corner],
                'compile_rc': 0, 'sim_rc': 1 if case == 'a' else 0,
                'stdout': str(root/'stdout.log'), 'compile_log': str(root/'compile.log')}]}))
        finally:
            with lock: active -= 1
    manifest = {'cases': [{'id': n} for n in ['d','c','b','a']]}
    step = SimpleNamespace(step_dir=str(tmp_path), config={'VIBEIC_GLS_MANIFEST':'full.json'},
        _run=lambda argv,log,limit,cwd=None: 0)
    rows = final_gls.run_native_cases(step, {DesignFormat.NETLIST:'actual.v',
        DesignFormat.SDF:{'zz':'zz.sdf','aa':'aa.sdf'}}, manifest, workers=4, native_run=native)
    assert peak == 4
    assert [(r['corner'],r['case']) for r in rows] == sorted((c,n) for c in ['aa','zz'] for n in ['a','b','c','d'])
    assert len({r['execution']['worker_output'] for r in rows}) == 8
    assert [r['sim_rc'] for r in rows if r['case']=='a'] == [1,1]
    assert next(r for r in rows if (r['corner'],r['case'])==('zz','b'))['compile_rc'] == 125
    assert len(json.loads((tmp_path/'gls_runs.json').read_text())['runs']) == 8
    assert Path.cwd() == cwd


@pytest.mark.parametrize('workers', [0, 5, True, '4'])
def test_native_case_worker_budget_cannot_expand(workers, tmp_path):
    from types import SimpleNamespace
    with pytest.raises(AdmissionRefusal, match='D71_CASE_WORKERS_INVALID'):
        final_gls.run_native_cases(SimpleNamespace(step_dir=str(tmp_path)), {}, {}, workers=workers)
