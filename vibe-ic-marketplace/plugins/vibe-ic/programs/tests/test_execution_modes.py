"""Neutral finite tools test the actual standalone controller API, never EDA.

Planner priority labels are exercised without invoking those EDA tools. Runtime
fixtures use neutral tool/family IDs and a text-transform objective exclusively.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_modes as em
from programs.tests._hostpaths import require_repo

BASE = subprocess.check_output(
    ['git', '-C', str(require_repo()), 'rev-parse', 'HEAD'], text=True).strip()
TOOL = Path(__file__).parent / 'fixtures/execution_modes_tool.py'
VARIANTS = Path(__file__).parent / 'fixtures/provider_variants'
OBJECTIVE = {'goal': 'uppercase', 'metric': 'cost', 'direction': 'min'}


def validate_text(outputs, binding):
    report = json.loads((outputs / 'measurement.json').read_text())
    actual = (outputs / 'value.txt').read_text()
    expected = (outputs.parent / 'inputs/text.txt').read_text().upper()
    gates = dict(report['gates'])
    if actual != expected or report['value'] != actual:
        gates['transform'] = 'FAIL'
    return em.Evidence(report['binding'], report['verdict'], gates,
                       {n: em.digest(outputs / n) for n in ('value.txt', 'measurement.json')},
                       report['metrics'])


def adapter(arm='a', *, fault='none', duration=.02, cost=5, **kw):
    # Each named neutral arm is an explicit source fixture.  This keeps the
    # test's two independent producers distinct by source bytes while the
    # production controller remains immune to tool_id relabeling.
    source = {str(p.resolve()): em.digest(p.resolve()) for p in
              (Path(sys.executable), TOOL, Path(__file__))}
    variant = VARIANTS / f'{arm}.py'
    selected_tool = variant if variant.is_file() else TOOL
    source[str(selected_tool.resolve())] = em.digest(selected_tool)
    source.update({str(p): em.digest(p) for p in em._source_closure(source)})
    components = tuple(em.Component(action, (
        str(Path(sys.executable).resolve()), str(selected_tool.resolve()), '{inputs}',
        '{outputs}', action, fault, str(duration), str(cost)), timeout_s=2)
        for action in ('transform', 'measure'))
    return em.Adapter(arm, 'neutral_' + arm, '1', BASE, source, sys.version,
                      ('neutral_' + arm,), components, validate_text,
                      ('value.txt', 'measurement.json'), OBJECTIVE,
                      qualification_evidence='Finite neutral text tool and its actual output consumer',
                      output_contract={'value.txt': ('value.txt',),
                                       'measurement.json': ('measurement.json',)}, **kw)


class NeutralContext(em.Context):
    """Protocol-only fixture boundary; absent from production authority."""
    def binding(self):
        if self.route_receipt.get('kind') != 'neutral-test':
            return super().binding()
        if self.native_mode not in ('direct', 'librelane', 'dual'):
            raise em.Refusal('AMBIGUOUS_NATIVE_IDENTITY', self.native_mode)
        if self.ic_ip_path != self.route_receipt.get('ic_ip_path'):
            raise em.Refusal('IC_IP_ROUTE_MISMATCH', self.step_id)
        if not re.fullmatch(r'[0-9a-f]{40}', self.source_sha):
            raise em.Refusal('INVALID_SOURCE_SHA', self.source_sha)
        return dict(step_id=self.step_id, source_sha=self.source_sha,
                    controller_sha256=em.digest(Path(em.__file__)),
                    inputs={n: em.digest(Path(p)) for n,p in self.inputs.items()},
                    objective=dict(self.objective), required_gates=list(self.required_gates),
                    native_mode=self.native_mode, ic_ip_path=self.ic_ip_path,
                    route_receipt=dict(self.route_receipt), project_digest=self.project_digest,
                    route_receipt_sha256=em._hash(self.route_receipt),
                    intent_label=self.intent_label, request_digest=self.request_digest)


def context(tmp_path):
    p = tmp_path / 'original.txt'
    p.write_text('one input\n')
    return NeutralContext('1', BASE, {'text.txt': p}, OBJECTIVE, ('transform',),
                         ic_ip_path='IC', route_receipt={'kind': 'neutral-test', 'ic_ip_path': 'IC'})


def controller(*arms, budget=None):
    registry = em.Registry()
    for a in arms:
        registry.register(a)
    # Explicit test-only contract: no synthetic gate is presented as a
    # canonical EDA obligation. The real portfolio is separately consumed below.
    portfolio = {'meta': {'test_only': True}, 'steps': [
        {'id': '1', 'mandatory_gate_programs': ['transform'],
         'required_output_contract': ['value.txt', 'measurement.json']}]}
    return em.Controller(registry, budget or em.Budget(2, 512), portfolio)


def read(root, arm='a'):
    return json.loads((root / arm / 'receipt.json').read_text())


def choice(ctx, root, arm='a'):
    # A refused run has no arm receipt to choose. Keep the staged independent
    # caller's run/adopt sequence meaningful without inventing missing evidence.
    refusal = root / 'refusal.json'
    if refusal.is_file() and not (root / arm / 'receipt.json').exists():
        return None
    return {'arm_id': arm, 'binding': ctx.binding(),
            'receipt_sha256': em.digest(root / arm / 'receipt.json'),
            'reviewer': 'test AI decision consumer',
            'rationale': 'Complete current-input output and measured transform gate; lowest declared cost.'}


@pytest.mark.parametrize('value,expected', [(None, 'default-mode'),
                         ('default-mode', 'default-mode'), ('ultra-mode', 'ultra-mode')])
def test_mode_aliases(value, expected):
    assert em.mode(value) == expected


@pytest.mark.parametrize('value', ['', 'default', 'ultra', 'direct', 'dual', 'librelane', 'ULTRA-MODE'])
def test_invalid_alias_refused(value):
    with pytest.raises(em.Refusal, match='INVALID_EXECUTION_MODE'):
        em.mode(value)


def test_default_picks_exactly_one_ranked_available_applicable_primary(tmp_path):
    ctx = context(tmp_path)
    # A caller cannot relabel the Python fixture as a known EDA tool.  The
    # production registry refuses those labels before planning; neutral tools
    # remain deterministic by arm order.
    ll = replace(adapter('ll'), tool_id='librelane')
    with pytest.raises(em.Refusal, match='TOOL_ID_UNBOUND'):
        controller(ll)
    assert controller(adapter('other')).plan(ctx)['arms'] == ['other']


@pytest.mark.parametrize('state', ['unavailable', 'unknown', 'applicable'])
def test_external_unavailability_never_justifies_own_tool(tmp_path, state):
    ctx = context(tmp_path)
    external = replace(adapter('external'), available=state != 'unavailable',
                       availability_reason='Missing executable' if state == 'unavailable' else '',
                       applicability='unknown' if state == 'unknown' else 'applicable',
                       applicability_reason='Unresolved input compatibility' if state == 'unknown' else '')
    own = replace(adapter('own'), tool_id='vibeic', own_no_tool_reason='No external tool')
    p = controller(external, own).plan(ctx)
    assert 'own' not in p['arms']
    assert next(r for r in p['portfolio'] if r['arm_id'] == 'own')['admission'] == 'OWN_TOOL_NOT_JUSTIFIED'


def test_own_requires_explicit_reason_and_inapplicable_external(tmp_path):
    ctx = context(tmp_path)
    external = replace(adapter('external'), applicability='inapplicable',
                       applicability_reason='This finite tool cannot accept text')
    own = replace(adapter('own'), tool_id='vibeic')
    assert controller(external, own).plan(ctx)['status'] == 'NOT_MEASURED'
    own = replace(own, own_no_tool_reason='Source-scoped text conversion; declared external cannot accept text')
    assert controller(external, own).plan(ctx)['arms'] == ['own']


def test_checker_is_not_alternate_producer_and_same_family_disclosed(tmp_path):
    ctx = context(tmp_path)
    a = adapter('a')
    b = replace(adapter('b'), engine_families=a.engine_families)
    checker = replace(adapter('checker'), role='checker')
    plan = controller(a, b, checker).plan(ctx, 'ultra-mode')
    assert plan['arms'] == ['a']
    assert {r['arm_id']: r['admission'] for r in plan['portfolio']} == {
        'a': 'READY', 'b': 'SAME_ENGINE_FAMILY', 'checker': 'COMPLEMENTARY_CHECKER'}


def test_ultra_deduplicates_same_implementation_after_tool_relabel(tmp_path):
    ctx = context(tmp_path)
    first = adapter('same-implementation')
    relabelled = replace(first, arm_id='relabelled', tool_id='invented-tool',
                         engine_families=('invented-family',))
    plan = controller(first, relabelled).plan(ctx, 'ultra-mode')
    assert len(plan['arms']) == 1
    discarded = next(row for row in plan['portfolio'] if row['arm_id'] not in plan['arms'])
    assert discarded['admission'] == 'SAME_ENGINE_FAMILY'


def test_license_unavailable_is_named_and_not_runnable(tmp_path):
    ctx = context(tmp_path)
    licensed = adapter(license_id='neutral_license')
    c = controller(licensed)
    root = tmp_path / 'run'
    result = c.run(ctx, root, 'ultra-mode')
    assert result['status'] == 'NOT_MEASURED'
    assert result['portfolio'][0]['admission'] == 'LICENSE_UNAVAILABLE'
    assert not (root / 'a').exists()
    assert json.loads((root / 'plan.json').read_text())['public_portfolio']['meta']['test_only']


@pytest.mark.parametrize('field', ['cpus', 'ram_mb'])
def test_budget_decline_is_named(tmp_path, field):
    ctx = context(tmp_path)
    arm = replace(adapter(), **{field: 1000000})
    assert controller(arm).plan(ctx)['portfolio'][0]['admission'] == 'BUDGET_UNAVAILABLE'


def test_source_mismatch_cannot_register(tmp_path):
    a = adapter()
    source = dict(a.source_files)
    source[str(TOOL.resolve())] = '0' * 64
    with pytest.raises(em.Refusal, match='ADAPTER_SOURCE_MISMATCH'):
        em.Registry().register(replace(a, source_files=source))


def test_wrong_source_is_not_admitted(tmp_path):
    ctx = context(tmp_path)
    with pytest.raises(em.Refusal, match='SOURCE_AUTHORITY_UNAVAILABLE'):
        controller(replace(adapter(), source_sha='0' * 40))


def test_unequal_objective_and_ambiguous_native_identity_fail_closed(tmp_path):
    ctx = context(tmp_path)
    with pytest.raises(em.Refusal, match='UNEQUAL_OBJECTIVES'):
        controller(adapter(), replace(adapter('b'), objective={'goal': 'other'})).plan(ctx, 'ultra-mode')
    with pytest.raises(em.Refusal, match='AMBIGUOUS_NATIVE_IDENTITY'):
        controller(adapter()).plan(replace(ctx, native_mode='unknown'))


def test_required_gates_cannot_be_dropped(tmp_path):
    ctx = context(tmp_path)
    with pytest.raises(em.Refusal, match='REQUIRED_GATES_DROPPED'):
        controller(adapter()).plan(replace(ctx, required_gates=('unrelated_gate',)))


def test_required_output_contract_cannot_be_dropped(tmp_path):
    ctx = context(tmp_path)
    a = replace(adapter(), output_contract={'value.txt': ('value.txt',)})
    with pytest.raises(em.Refusal, match='OUTPUT_CONTRACT_UNBOUND'):
        controller(a).plan(ctx)


def test_real_ram_limit_refuses_allocation_and_keeps_partial_output(tmp_path):
    ctx = context(tmp_path)
    c = controller(adapter(fault='ram_exceed'))
    root = tmp_path / 'run'
    c.run(ctx, root)
    r = read(root)
    assert r['status'] == 'NOT_MEASURED'
    assert r['reason'] == 'PROCESS_ERROR'
    assert r['processes'][0]['rc'] == 1
    assert 'MemoryError' in Path(r['processes'][0]['stderr']).read_text()
    assert (root / 'a/outputs/value.txt').read_text() == 'ONE INPUT\n'


def test_concurrent_isolated_outputs_ordered_components_and_ai_adoption(tmp_path):
    ctx = context(tmp_path)
    c = controller(adapter('a', duration=.15, cost=8), adapter('b', duration=.15, cost=3))
    root = tmp_path / 'run'
    assert c.run(ctx, root, 'ultra-mode')['status'] == 'AWAITING_AI_SELECTION'
    a, b = read(root, 'a'), read(root, 'b')
    assert a['status'] == b['status'] == 'ELIGIBLE'
    # Actual monotonic process intervals overlap; no elapsed-time speed assertion.
    assert max(a['processes'][0]['started_ns'], b['processes'][0]['started_ns']) < min(
        a['processes'][0]['ended_ns'], b['processes'][0]['ended_ns'])
    assert a['output_root'] != b['output_root']
    assert a['input_root'] != b['input_root']
    for r in (a, b):
        assert r['processes'][0]['ended_ns'] <= r['processes'][1]['started_ns']
        assert [p['rc'] for p in r['processes']] == [0, 0]
        assert all(p['pid'] > 0 and p['stdout_sha256'] for p in r['processes'])
    runtime = [json.loads((root / i / 'outputs/measurement.json').read_text()) for i in ('a', 'b')]
    assert all(len(r['affinity']) == 1 and r['address_space_limit'] == 128 * 1024 * 1024 for r in runtime)
    assert set(runtime[0]['affinity']).isdisjoint(runtime[1]['affinity'])
    assert c.adopt(ctx, root, choice(ctx, root, 'b'))['selected'] == 'b'
    assert json.loads((root / 'adoption.json').read_text())['status'] == 'ADOPTED'
    assert ctx.inputs['text.txt'].read_text() == 'one input\n'


@pytest.mark.parametrize('constraint', ['cpu', 'ram', 'license'])
def test_budget_serializes_actual_process_intervals(tmp_path, constraint):
    ctx = context(tmp_path)
    kw = {'license_id': 'seat'} if constraint == 'license' else {}
    budget = em.Budget(1 if constraint == 'cpu' else 2,
                       128 if constraint == 'ram' else 512,
                       licenses={'seat': 1} if constraint == 'license' else {})
    c = controller(adapter('a', duration=.06, **kw), adapter('b', duration=.06, **kw), budget=budget)
    root = tmp_path / 'run'
    c.run(ctx, root, 'ultra-mode')
    a, b = read(root, 'a'), read(root, 'b')
    assert a['status'] == b['status'] == 'ELIGIBLE'
    assert (a['processes'][-1]['ended_ns'] <= b['processes'][0]['started_ns'] or
            b['processes'][-1]['ended_ns'] <= a['processes'][0]['started_ns'])


@pytest.mark.parametrize('fault,status,reason', [
    ('process_error', 'NOT_MEASURED', 'PROCESS_ERROR'),
    ('no_report', 'NOT_MEASURED', 'ADAPTER_ERROR'),
    ('wrong_source', 'NOT_MEASURED', 'EVIDENCE_UNBOUND'),
    ('stale_input', 'NOT_MEASURED', 'EVIDENCE_UNBOUND'),
    ('wrong_objective', 'NOT_MEASURED', 'EVIDENCE_UNBOUND'),
    ('mutate_frozen', 'NOT_MEASURED', 'FROZEN_INPUT_CHANGED'),
    ('fail_gate', 'FAIL', 'GATE_FAIL'),
    ('unmeasured', 'NOT_MEASURED', 'GATE_NOT_MEASURED')])
def test_program_gate_actual_outputs_fail_closed(tmp_path, fault, status, reason):
    ctx = context(tmp_path)
    c = controller(adapter(fault=fault))
    root = tmp_path / 'run'
    c.run(ctx, root)
    r = read(root)
    assert r['status'] == status
    assert r['reason'] == reason
    with pytest.raises(em.Refusal, match='AI_CHOICE_INELIGIBLE'):
        c.adopt(ctx, root, choice(ctx, root))
    if fault == 'fail_gate':
        missing_observation = dict(r, gate_receipts={})
        with pytest.raises(em.Refusal, match='GATE_FAIL'):
            c._eligible(missing_observation, ctx, c.registry.adapters(ctx.step_id)[0])
    if fault == 'process_error':
        assert r['processes'][0]['rc'] == 7
        assert len(r['processes']) == 1


def test_missing_or_unbound_ai_choice_refused_and_persisted(tmp_path):
    ctx = context(tmp_path)
    c = controller(adapter())
    root = tmp_path / 'run'
    c.run(ctx, root)
    with pytest.raises(em.Refusal, match='AI_CHOICE_MISSING'):
        c.adopt(ctx, root, None)
    assert json.loads((root / 'adoption.json').read_text())['reason'] == 'AI_CHOICE_MISSING'
    unbound = choice(ctx, root)
    unbound['binding']['source_sha'] = '0' * 40
    with pytest.raises(em.Refusal, match='AI_CHOICE_UNBOUND'):
        c.adopt(ctx, root, unbound)


@pytest.mark.parametrize('target,reason', [('output', 'OUTPUT_DIGEST_MISMATCH'),
                                         ('frozen', 'FROZEN_INPUT_CHANGED'),
                                         ('original', 'AI_CHOICE_UNBOUND'),
                                         ('receipt', 'AI_RECEIPT_DIGEST_MISMATCH')])
def test_adoption_rechecks_current_input_digests_and_receipt(tmp_path, target, reason):
    ctx = context(tmp_path)
    c = controller(adapter())
    root = tmp_path / 'run'
    c.run(ctx, root)
    chosen = choice(ctx, root)
    paths = {'output': root / 'a/outputs/value.txt', 'frozen': root / 'a/inputs/text.txt',
             'original': ctx.inputs['text.txt'], 'receipt': root / 'a/receipt.json'}
    paths[target].chmod(0o644)
    paths[target].write_text('changed')
    with pytest.raises(em.Refusal, match=reason):
        c.adopt(ctx, root, chosen)


def test_receipt_rewrite_cannot_turn_unmeasured_gate_into_adoptable_pass(tmp_path):
    ctx = context(tmp_path)
    c = controller(adapter(fault='unmeasured'))
    root = tmp_path / 'run'
    c.run(ctx, root)
    r = read(root)
    r['status'] = 'ELIGIBLE'
    r['evidence']['verdict'] = 'PASS'
    r['evidence']['gates']['transform'] = 'PASS'
    (root / 'a/receipt.json').write_text(json.dumps(r))
    try:
        observed = c.adopt(ctx, root, choice(ctx, root))['status']
    except em.Refusal as exc:
        observed = 'REFUSED:' + exc.code
    assert observed == 'REFUSED:EVIDENCE_CHANGED'


@pytest.mark.parametrize('stop', ['cancel', 'deadline'])
def test_cancel_deadline_actual_rc_partial_logs_reaped(tmp_path, stop, monkeypatch):
    ctx = context(tmp_path)
    a = adapter(fault='partial', duration=.01)
    a = replace(a, components=(replace(a.components[0], timeout_s=.2), a.components[1]))
    c = controller(a)
    root = tmp_path / 'run'
    cancel = threading.Event()
    timer = None
    real_popen = em.subprocess.Popen

    def ready_partial_process(argv, *args, **kwargs):
        nonlocal timer
        process = real_popen(argv, *args, **kwargs)
        if list(argv[-4:-2]) != ['transform', 'partial']:
            return process
        # This stop/reap control starts with a real child that has already
        # written partial output. Admission and interpreter startup precede
        # the unchanged controller's .2-second supervision interval.
        stdout = root / 'a/transform.stdout'
        ready_deadline = time.monotonic() + 2
        while process.poll() is None and time.monotonic() < ready_deadline:
            if ('partial output preserved' in stdout.read_text()
                    and (root / 'a/outputs/value.txt').is_file()):
                if stop == 'cancel':
                    timer = threading.Timer(.12, cancel.set)
                    timer.start()
                return process
            time.sleep(.001)
        try:
            os.killpg(process.pid, 9)
        except ProcessLookupError:
            pass
        process.wait()
        pytest.fail('partial tool did not reach the required ready state')

    monkeypatch.setattr(em.subprocess, 'Popen', ready_partial_process)
    try:
        c.run(ctx, root, cancel=cancel)
    finally:
        if timer:
            timer.join()
    r = read(root)
    assert r['status'] == 'NOT_MEASURED'
    assert r['reason'] == ('CANCELLED' if stop == 'cancel' else 'DEADLINE')
    process = r['processes'][0]
    assert process['rc'] == -9
    assert 'partial output preserved' in Path(process['stdout']).read_text()
    assert (root / 'a/outputs/value.txt').read_text() == 'ONE INPUT\n'
    with pytest.raises(ProcessLookupError):
        os.kill(process['pid'], 0)


def test_no_fallback_to_own_when_primary_process_fails(tmp_path):
    ctx = context(tmp_path)
    external = adapter('external', fault='process_error')
    own = replace(adapter('own'), tool_id='vibeic', own_no_tool_reason='Tool failed')
    c = controller(external, own)
    root = tmp_path / 'run'
    c.run(ctx, root)
    assert read(root, 'external')['reason'] == 'PROCESS_ERROR'
    assert not (root / 'own').exists()


def test_superiority_requires_exact_measured_input_version_and_objective(tmp_path):
    ctx = context(tmp_path)
    # Produce measurements with neutral tools first. Only the separate planner
    # test changes priority labels; runtime never claims an EDA result.
    a, b = adapter('a', cost=9), adapter('b', cost=3)
    c = controller(a, b)
    root = tmp_path / 'measurements'
    c.run(ctx, root, 'ultra-mode')
    evidence = em.Superiority(ctx.binding(), 'b', 'a', 'cost', 'min',
                             {i: root / i / 'receipt.json' for i in ('a', 'b')})
    assert c.plan(ctx, superiority=evidence)['arms'] == ['b']
    assert c.plan(ctx, superiority=evidence)['reason'] == 'CURRENT_INPUT_MEASURED_SUPERIORITY'
    changed = replace(b, tool_version='different version')
    with pytest.raises(em.Refusal, match='SUPERIORITY_STALE'):
        controller(a, changed).plan(ctx, superiority=evidence)
    with pytest.raises(em.Refusal, match='SUPERIORITY_UNBOUND'):
        c.plan(ctx, superiority=replace(evidence, direction='max'))
    with pytest.raises(em.Refusal, match='SUPERIORITY_NOT_PROVEN'):
        c.plan(ctx, superiority=replace(evidence, preferred='a'))
    ctx.inputs['text.txt'].write_text('new input')
    with pytest.raises(em.Refusal, match='SUPERIORITY_UNBOUND'):
        c.plan(ctx, superiority=evidence)


def test_real_canonical_portfolio_preserves_final_source_policy_and_blocks_unregistered(tmp_path):
    p = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                     'programs', 'data', 'execution_modes_portfolio.json')
    data = em.load_portfolio(p)
    yaml = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                        'flow', 'phase1_phase2_phase3.yaml').read_text()
    ids = re.findall(r'^  - id:\s*["\x27]?([^\s"\x27#]+)', yaml.split('\nsteps:\n')[1], re.M)
    assert [s['id'] for s in data['steps']] == ids
    assert len(data['tools']) == 63
    assert sum(len(s['ultra_tools']) for s in data['steps']) == 333
    assert data['meta']['inventory_sha256'] == 'd364f39fc37b77f5ba711cea7cab879345de56c157784cf847a66108ebc518bc'
    assert data['meta']['canonical_flow_git_blob'] == subprocess.check_output(
        ['git', '-C', str(require_repo()), 'hash-object', str(em._canonical_flow_path())], text=True).strip()
    assert data['meta']['policy_globally_implemented'] is False
    a9 = next(s for s in data['steps'] if s['id'] == 'A9')
    assert a9['policy_default']['tool_ids'] == ['ngspice']
    assert 'd_cosim' in a9['current_default']['source_note_en']
    assert next(s for s in data['steps'] if s['id'] == 'A4')['policy_default']['tool_ids'] == ['ngspice']
    assert all(not a['controller_runnable'] for s in data['steps'] for a in s['ultra_tools'])
    ctx = replace(context(tmp_path), required_gates=tuple(data['steps'][2]['mandatory_gate_programs']))
    c = em.Controller(em.Registry(), em.Budget(1, 128), data)
    assert c.plan(ctx)['status'] == 'NOT_MEASURED'
    assert c.plan(ctx)['reason'] == 'NO_RUNNABLE_ADAPTER'


def test_public_resource_has_no_private_paths_or_chinese_fields():
    text = (Path(em.__file__).parent / 'data/execution_modes_portfolio.json').read_text()
    assert 'title_zh' not in text
    assert not re.search(r'(?<![A-Za-z0-9_])/(?:home/reyerchu|mnt/ssd|tmp)/', text)
    assert not re.search(r'\\u[49a][0-9a-f]{3}', text)
