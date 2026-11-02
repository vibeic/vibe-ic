"""Selected handoff capture ordering with real static producers and consumers.

Neutral subject/upstream readsets are explicit doubles, never native LEC/STA
qualification. The normal gate, capture, stamps, publishers, strict handoff
reader, delivery producer and chain reader execute without substitutes.
Native dispatch is forbidden during this module's fixture and test lifetime.
"""
import ast
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import design_one_shot_runner as design
import flow109
import flow109_metric_acceptance as metrics
import step_output_collector as versions
import execution_backend_gates as gates
import execution_policy
import _path_layout as layout

_native_guard_active = False


def no_native(event, args):
    if event != 'subprocess.Popen' or not _native_guard_active:
        return
    argv = list(map(str, args[1]))
    if Path(argv[0]).name == 'yosys' and argv[1:4] == ['-Q', '-T', '-p']:
        assert len(argv) == 5 and argv[4].startswith('read_verilog ')
        assert '; hierarchy -top ' in argv[4] and '; write_verilog -noattr ' in argv[4]
        assert argv[4].count(';') == 2
        return  # existing structural normalizer; no proof or synthesis
    if Path(argv[0]).name.startswith('python') and len(argv) > 1:
        allowed = {'flow_compliance_check.py', 'yosys_hilomap_required_check.py',
            'yosys_script_template_check.py', 'yosys_tiecell_recipe_order_check.py',
            'flow_step_output_content_check.py', 'stage_on_pass_review.py',
            'step_output_collector.py'}
        if Path(argv[1]).name in allowed:
            return  # only current handoff static producers/consumer/publication
    raise AssertionError('Native/proof/STA/global dispatch forbidden: ' + str(argv))


sys.addaudithook(no_native)


@pytest.fixture(scope='module', autouse=True)
def _native_guard():
    global _native_guard_active
    _native_guard_active = True
    try:
        yield
    finally:
        _native_guard_active = False


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def ref(project, path):
    return {'path': str(path.relative_to(project)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def site_node():
    tree = ast.parse(Path(design.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    return next(n for n in main.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                and n.test.id == '_bounded' and any(isinstance(x, ast.Name)
                    and x.id == 'step_synthesis_handoff' for x in ast.walk(n)))


@pytest.fixture(scope='module')
def captured(tmp_path_factory, _native_guard):
    mp = pytest.MonkeyPatch()
    project = tmp_path_factory.mktemp('neutral-handoff-order')
    synth = project / 'phase2/stage2/synth'
    synth.mkdir(parents=True)
    (synth / 'synth.ys').write_text('read_verilog -sv core.v\nsynth -top spm -flatten\n'
        'techmap\nsetundef -zero\nhilomap -hicell TIEHI Y -locell TIELO Y\nclean\n'
        'write_verilog -noattr netlist.v\n')
    netlist = synth / 'netlist.v'
    netlist.write_text('module spm(input a, output y); assign y = a; endmodule\n')
    (project / 'input').mkdir()
    (project / 'input/spec.md').write_text('Neutral caller-order control, no native qualification.\n')
    write(project / 'phase1/generated_docs/L5_ADI_SPEC.json',
          {'no_analog': True, 'analog_blocks_detected': False, 'analog_blocks': [],
           'scope': 'Explicit neutral fixture, no physical or native qualification'})
    manifest = json.loads(Path(os.environ['D30_ORDER_MANIFEST']).read_text())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'D30', 'D30')
    write(project / 'context.json', context)
    mp.setenv(flow109.CONTEXT_ENV, str(project / 'context.json'))
    attempt = flow109._new_attempt(project, context)
    mp.setenv(flow109.ATTEMPT_ENV, str(attempt))
    profile = {k + '_sha256': flow109.digest(context[k]) for k in ('features', 'step_profiles')}
    nl = ref(project, netlist)
    admission = {'top': 'spm', 'requires_scan': False, 'profile_identity': profile,
        'adopted_netlist': nl, 'normalized_preroute_chain': {
            'status': 'NOT_MEASURED', 'reason': 'D30_DELIVERY_ARTIFACT_UNBOUND',
            'points': {name: {'input': nl} for name in ('D22', 'D25', 'D26')}}}
    # Already-accepted upstream is outside this changed static capture seam.
    # No fabricated model/requirements approval, proof or timing authority.
    mp.setattr(flow109, 'dft_preroute_admission', lambda *_: copy.deepcopy(admission))
    mp.setattr(metrics, 'd30_consumed_timing', lambda *_: {'scope': 'explicit upstream fixture'})
    mp.setattr(metrics, 'd30_consumed_changes', lambda *_: {'scope': 'explicit upstream fixture'})
    original_reader = design._current_phase2_consumer
    mp.setattr(design, '_current_phase2_consumer', lambda p, sid, at:
        original_reader(p, sid, at) if sid == '14' else {'scope': 'unchanged upstream fixture'})
    prelayout = design.StepResult('sdc_validation', 'PASS', 0, 'upstream fixture only',
                                 extras={'post_prelayout': True})
    plan = [prelayout]
    env = dict(vars(design), project=project, plan=plan, _bounded=True,
        _entry_site='synthesis_handoff', _before_entry=lambda *_: False,
        _after_exit=lambda *_: False)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[site_node()], type_ignores=[])),
                 design.__file__, 'exec'), env)
    result = plan[-1]
    # Actual ordinary tail: final stamps, publish report/view, late idempotent
    # sweep, then parent view. These must preserve the same complete owner.
    design.step_stamp_gate_reports(project)
    summary = {'project': str(project), 'steps': [asdict(result)], 'verdict': result.status}
    view, report = layout.publish_report_then_steps_view(project, Path(design.__file__).parent,
        'design_one_shot_runner', summary, 'phase2_one_shot.json', only_steps={'14'})
    design._stamp_gate_report_dirs(project)
    second = layout.emit_steps_view(project, Path(design.__file__).parent,
                                   runner='vibe_ic_one_shot_runner', only_steps={'14'})
    yield SimpleNamespace(project=project, context=context, result=result,
        admission=admission, original_reader=original_reader,
        all_readers=versions.current_acceptance(project, 0), view=view, parent_view=second)
    mp.undo()


def test_actual_selected_owner_keeps_complete_stamped_handoff_through_publication(captured):
    c = captured
    assert c.result.status == 'PASS', asdict(c.result)
    delivery_ref = c.result.extras['d30_delivery_receipt']
    chain = flow109._complete_preroute_chain(c.project, c.context, c.admission,
        delivery_ref, d30_context_sha256=c.context['context_sha256'])
    assert chain['status'] == 'PASS', chain
    accepted = c.original_reader(c.project, '14', 0)
    assert accepted is not None, 'actual complete handoff lost after outer capture/late stamp/publication'
    delivery = json.loads((c.project / delivery_ref['path']).read_text())
    assert delivery['handoff_folder'] == accepted['folder']
    assert len(c.all_readers) == 1, 'selected owner must have one complete canonical capture'
    index = json.loads((versions._versions_root(c.project) / 'index.json').read_text())
    assert next(x for x in index['steps'] if str(x['id']) == '14')['folder'] == accepted['folder']
    for entry in accepted['outputs']:
        p = c.project / entry['rel']
        assert hashlib.sha256(p.read_bytes()).hexdigest() == entry['sha256']
        if '/gates/' in entry['rel']:
            assert json.loads(p.read_text())['design_identity']
    # This is current chain acceptance, not model/metric/native row approval.
    assert chain['flow109_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['stale_input', 'changed_output', 'missing_output',
                                    'wrong_source', 'foreign_folder'])
def test_actual_strict_reader_still_refuses_real_changes(captured, damage):
    c = captured
    delivery_ref = c.result.extras.get('d30_delivery_receipt')
    assert delivery_ref is not None, asdict(c.result)
    original_path = c.project / delivery_ref['path']
    document = json.loads(original_path.read_text())
    restored = None
    if damage in ('stale_input', 'changed_output', 'missing_output'):
        path = c.project / ('phase2/stage2/synth/netlist.v' if damage == 'stale_input'
            else 'reports/phase2/gates/yosys_hilomap.json')
        restored = path, path.read_bytes()
        if damage == 'missing_output':
            path.unlink()
        else:
            path.write_bytes(restored[1] + b'\n')
    else:
        if damage == 'wrong_source':
            document['producer_source_sha256'] = '0' * 64
        else:
            document['handoff_folder'] += '-foreign'
        mutated = original_path.parent / ('fixture-' + damage + '.json')
        write(mutated, document)
        delivery_ref = ref(c.project, mutated)
    try:
        result = flow109._complete_preroute_chain(c.project, c.context, c.admission,
            delivery_ref, d30_context_sha256=c.context['context_sha256'])
        assert result['status'] == 'NOT_MEASURED', result
        assert result['reason'] == 'D30_DELIVERY_BINDING_UNPROVEN', result
    finally:
        if restored:
            restored[0].write_bytes(restored[1])


def test_other_owner_keeps_existing_noncanonical_dispatch(monkeypatch, tmp_path):
    monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
    seen = []
    def gate(*args, **kwargs):
        seen.append(kwargs)
        return design.StepResult('synthesis_handoff', 'NOT_MEASURED', 0,
                                  'dispatch observation only', reason_class='input_absent')
    env = dict(vars(design), project=tmp_path, plan=[], _bounded=True,
        _entry_site='synthesis_handoff', _before_entry=lambda *_: False,
        _after_exit=lambda *_: False,
        _spf=SimpleNamespace(gate=gate))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[site_node()], type_ignores=[])),
                 design.__file__, 'exec'), env)
    assert len(seen) == 1
    assert not seen[0].get('_preflight_canonical_acceptance')
    assert not seen[0].get('owner_capture')


def test_unapproved_dispatch_is_forbidden_during_this_module():
    with pytest.raises(AssertionError, match='Native/proof/STA/global dispatch forbidden'):
        subprocess.run([sys.executable, '-c', "print('must not execute')"],
                       capture_output=True, text=True, timeout=10)
