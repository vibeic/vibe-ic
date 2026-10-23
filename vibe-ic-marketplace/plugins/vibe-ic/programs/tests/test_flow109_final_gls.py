"""D71 actual Icarus/vvp final-SDF component controls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import flow109
import flow109_admission as admission
import flow109_final_gls as final_gls


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


def _run(project):
    return subprocess.run([sys.executable, str(final_gls.HERE / 'vibe_ic_one_shot_runner.py'),
        str(project), '--flow', '109', '--flow109-manifest', str(project / 'D71-selection.json'),
        '--entry-step', 'D71', '--exit-step', 'D71', '--route', 'ic', '--no-dashboard'],
        capture_output=True, text=True)


def _component(project):
    return json.loads((project / 'reports/flow109/components/D71.json').read_text())


def test_registry_routes_only_the_existing_default_icarus_component():
    features = next(item['features'] for item in flow109.load_registry()['reference_profiles']
                    if item['name'] == 'Small digital IC without DFT')
    row = flow109.resolve_step(flow109.resolve_plan(features), 'D71')
    assert row['profile']['dispatch']['adapter'] == 'flow109_final_gls'
    assert row['profile']['dispatch']['native_step_id'] == 'flow109.D71'
    assert set(row['profile']['dispatch']['engine_families']) == {'iverilog', 'vvp'}
    assert row['metric_acceptance_status'] == 'UNIMPLEMENTED'
    assert all(item['status'] == 'UNIMPLEMENTED_METRIC_BINDING' for item in row['obligations'])


def test_actual_default_final_sdf_gls_and_checker_readback(tmp_path):
    _case(tmp_path)
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    record = _component(tmp_path)
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
def test_actual_native_negative_output_and_annotation_are_preserved(tmp_path, damage, reason):
    _case(tmp_path)
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
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    record = _component(tmp_path)
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
def test_invalid_final_source_or_required_semantics_refuses_before_native(tmp_path, damage, reason):
    _case(tmp_path)
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
    proc = _run(tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    record = _component(tmp_path)
    assert record['component_status'] == 'NOT_MEASURED' and record['reason'] == reason
    assert record['native_started'] is False
    assert not list((tmp_path / 'reports/flow109/D71').rglob('gls_runs.json'))
