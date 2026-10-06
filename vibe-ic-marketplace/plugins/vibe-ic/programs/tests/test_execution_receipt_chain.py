"""Pure neutral controls for the existing execution_modes receipt chain."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import subprocess
import socket

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_modes as em
import execution_policy as policy
import _delivery_route
from programs.tests._route_fixture import stage_owner_route
from programs.tests import test_execution_modes as H


_launchers = []

@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch):
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    for name in (policy.ENV, policy._CAPABILITY_FD_ENV, 'VIBEIC_EXECUTION_AUTH_SOCKET'):
        # real_entry writes these locators directly. Record even an absent
        # original key so monkeypatch restores it after the issuer FD closes.
        monkeypatch.setenv(name, os.environ.get(name, ''))
        monkeypatch.delenv(name)
    yield
    for proc, fd, channel in _launchers:
        channel.close(); proc.wait(timeout=10)
        try: os.close(fd)
        except OSError: pass
    _launchers.clear()


@pytest.mark.parametrize('previous', [None, 'preexisting-locator'])
def test_isolated_transport_restores_direct_locator_writes(previous):
    names = (policy.ENV, policy._CAPABILITY_FD_ENV, 'VIBEIC_EXECUTION_AUTH_SOCKET')
    with pytest.MonkeyPatch.context() as outer:
        prior_runtime = object()
        outer.setattr(policy, '_ordinary_runtime', prior_runtime)
        for name in names:
            if previous is None:
                outer.delenv(name, raising=False)
            else:
                outer.setenv(name, previous)
        with pytest.MonkeyPatch.context() as patch:
            transport = isolated_transport.__wrapped__(patch)
            next(transport)
            assert policy._ordinary_runtime is None
            policy._ordinary_runtime = object()
            assert all(name not in os.environ for name in names)
            for name in names:
                os.environ[name] = 'closed-test-locator'
            with pytest.raises(StopIteration):
                next(transport)
        assert {name: os.environ.get(name) for name in names} == dict.fromkeys(names, previous)
        assert policy._ordinary_runtime is prior_runtime


@pytest.mark.parametrize('damage', ['closed', 'invalid_json'])
def test_default_bootstrap_refuses_invalid_capability_locator(tmp_path, monkeypatch, damage):
    fd = os.memfd_create('invalid-capability-control')
    os.write(fd, b'not an authority credential')
    monkeypatch.setenv(policy._CAPABILITY_FD_ENV, str(fd))
    if damage == 'closed':
        os.close(fd)
    try:
        with pytest.raises(em.Refusal, match='REQUEST_CAPABILITY_INVALID'):
            policy.bootstrap(tmp_path, parameters={'skip_analog': True})
    finally:
        if damage != 'closed':
            os.close(fd)


def test_real_issuer_fixture_teardown_leaves_unissued_default_inert(tmp_path):
    with pytest.MonkeyPatch.context() as patch:
        transport = isolated_transport.__wrapped__(patch)
        next(transport)
        issued = real_entry('IC', 'default', tmp_path)
        assert issued['route']['project'] == str(tmp_path)
        fd = int(os.environ[policy._CAPABILITY_FD_ENV])
        os.fstat(fd)
        with pytest.raises(StopIteration):
            next(transport)
    with pytest.raises(OSError):
        os.fstat(fd)
    assert policy._CAPABILITY_FD_ENV not in os.environ
    assert 'VIBEIC_EXECUTION_AUTH_SOCKET' not in os.environ
    assert policy._ordinary_runtime is None
    assert policy.bootstrap(tmp_path) is None


def real_entry(path='IC', execution_mode='default', project=None):
    import tempfile, struct, time
    project = Path(project or tempfile.mkdtemp())
    stage_owner_route(project, path.lower())
    parent, channel = socket.socketpair()
    channel.set_inheritable(True)
    command = [sys.executable, '-I', str(Path(policy.__file__).with_name('vibe_ic_one_shot_runner.py')),
               str(project), '--route', path.lower(), '--execution-mode', execution_mode,
               '--route-authority-only', '--receipt-channel-fd', str(channel.fileno())]
    environment = {k:v for k,v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
    # This wait admits the real isolated issuer and its verified source closure.
    # It is startup readiness, separate from each Controller component deadline.
    started = time.monotonic()
    ready = False
    with tempfile.NamedTemporaryFile(prefix='canonical-entry-', suffix='.stderr',
                                     dir=project.parent, delete=False) as stderr:
        stderr_path = Path(stderr.name)
        proc = subprocess.Popen(command, pass_fds=(channel.fileno(),), stderr=stderr, env=environment)
    channel.close(); parent.settimeout(120)
    try:
        data, ancillary, _, _ = parent.recvmsg(131072, socket.CMSG_SPACE(4))
        if not data: raise AssertionError(stderr_path.read_text()[-8192:])
        while b'\n' not in data:
            chunk = parent.recv(4096)
            if not chunk: raise AssertionError('canonical receipt channel EOF')
            data += chunk
            if len(data) > 131072: raise AssertionError('canonical receipt bound exceeded')
        fd = struct.unpack('i', ancillary[0][2][:4])[0]
        os.set_inheritable(fd, True)
        payload = json.loads(data)
        # Discover the issuer-owned listener from the inherited worker's env;
        # locator is transport only, independently verified by consume().
        credential = json.loads(os.pread(fd,4096,0))
        process_env = Path(f"/proc/{credential['pid']}/environ").read_bytes()
        # Socket path is sent as a locator by the real consumer CLI.
        os.environ[policy._CAPABILITY_FD_ENV] = str(fd)
        os.environ['VIBEIC_EXECUTION_AUTH_SOCKET'] = payload.pop('socket')
        _launchers.append((proc,fd,parent))
        ready = True
        return payload
    except BaseException:
        proc.terminate(); proc.wait(timeout=5); parent.close(); raise
    finally:
        stderr_path.with_suffix('.json').write_text(json.dumps({
            'argv': command, 'pid': proc.pid, 'ready': ready,
            'startup_elapsed_s': time.monotonic() - started,
            'startup_timeout_s': 120, 'returncode': proc.poll(),
            'stderr_path': str(stderr_path)}, indent=2) + '\n')


def _live_frontdoor_fixture(front, args):
    payload = real_entry(execution_mode='ultra')
    return front._configure_execution_policy(args)


def issued_route(*, path, source_sha, project_digest, request_digest, route='macro'):
    return real_entry(path)['route']


def test_default_omitted_is_one_existing_controller_plan(tmp_path):
    policy_value = policy.request()
    assert policy_value['intent_label'] == 'PROGRAM_DEFAULT'
    assert policy_value['mode_label'] == 'default-mode'
    assert policy_value['ultra_match'] is False
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    plan = controller.plan(ctx)
    assert plan['mode'] == 'default-mode'
    assert plan['arms'] == ['a']
    assert plan['mode_intent'] == 'default'


def test_frontdoor_default_omission_preserves_neutral_child_trace(tmp_path, monkeypatch):
    """Mode transport is observational: canonical child work sees the same trace."""
    import vibe_ic_one_shot_runner as front
    child = tmp_path / 'child.py'
    output = tmp_path / 'trace.json'
    child.write_text(
        'import json, os, pathlib, sys\n'
        'pathlib.Path(sys.argv[1]).write_text(json.dumps({"argv": sys.argv[1:],\n'
        '  "execution_env": os.environ.get("VIBEIC_EXECUTION_REQUEST"),\n'
        '  "cap_fd": os.environ.get("VIBEIC_EXECUTION_CAP_FD")}))\n')
    monkeypatch.delenv(policy.ENV, raising=False)
    assert front._run_phase('baseline', child, [str(output)]) == 0
    baseline = json.loads(output.read_text())
    assert front._run_phase('default-omitted', child, [str(output)]) == 0
    omitted = json.loads(output.read_text())
    assert omitted == baseline == {
        'argv': [str(output)], 'execution_env': None, 'cap_fd': None}

    args = type('Args', (), dict(execution_mode='default', execution_cpus=None,
                                 execution_ram_mb=None, execution_workers=None,
                                 execution_licenses=None, execution_choice=None,
                                 execution_choice_wait_s=None))()
    policy.configure(args)
    assert front._run_phase('default-explicit', child, [str(output)]) == 0
    explicit = json.loads(output.read_text())
    assert omitted == explicit == {
        'argv': [str(output)], 'execution_env': None, 'cap_fd': None}


def test_omitted_mode_keeps_each_canonical_phase_subprocess_boundary_exact(monkeypatch):
    import types
    import vibe_ic_one_shot_runner as front
    monkeypatch.delenv(policy.ENV, raising=False)
    monkeypatch.delenv(policy._CAPABILITY_FD_ENV, raising=False)
    baseline_env = dict(os.environ)
    observed = []

    def spy_run(command, *, env=None, pass_fds=(), **kwargs):
        observed.append((list(command), None if env is None else dict(env), tuple(pass_fds)))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(front.subprocess, 'run', spy_run)
    labels = ('PHASE 1', 'PHASE 2', 'PHASE 3', 'ANALOG')
    for label in labels:
        front._run_phase(label, Path('/tmp/runner.py'), ['--project', 'design'],
                         env=dict(baseline_env))
    assert len(observed) == len(labels)
    for command, env, pass_fds in observed:
        assert command == [sys.executable, '/tmp/runner.py', '--project', 'design']
        assert env == baseline_env
        assert policy.ENV not in env and policy._CAPABILITY_FD_ENV not in env
        assert pass_fds == ()


def test_phase3_enclosing_supervised_child_inherits_live_request_capability(
        tmp_path, monkeypatch):
    """The watchdog-launched enclosing Phase-3 child must use the existing
    canonical request FD, just like children started through _run_phase."""
    import argparse
    import phase3_one_shot_runner as phase3

    project = tmp_path / 'subservient'
    project.mkdir()
    route = real_entry('IC', 'default', project)['route']
    args = argparse.Namespace(execution_mode='default', execution_cpus=None,
                              execution_ram_mb=None, execution_workers=None,
                              execution_licenses=None, execution_choice=None,
                              execution_choice_wait_s=None)
    parent_request = policy.configure(args)
    assert parent_request['authority'] == policy.PROGRAM_DEFAULT
    assert route['request_digest'] == parent_request['request_digest']

    programs = str(Path(policy.__file__).parent)
    child = (
        'import argparse,json,sys\n'
        f'sys.path.insert(0, {programs!r})\n'
        'import execution_policy as p\n'
        'a=argparse.Namespace(execution_mode="default", execution_cpus=None, '
        'execution_ram_mb=None, execution_workers=None, execution_licenses=None, '
        'execution_choice=None, execution_choice_wait_s=None)\n'
        'r=p.configure(a)\n'
        'print(json.dumps({"request_digest":r["request_digest"], '
        '"authority":r["authority"], "mode":r["mode"]}, sort_keys=True))\n'
    )
    monkeypatch.setenv('VIBEIC_PHASE3_WINDOW_RUN_ID', 'request-capability-child-control')
    result, _log = phase3._phase3_enclosing_supervised(
        project, tmp_path / 'isolated', [sys.executable, '-c', child])
    assert result.rc == 0, result.err
    assert json.loads(result.out) == {
        'request_digest': parent_request['request_digest'],
        'authority': policy.PROGRAM_DEFAULT,
        'mode': 'default',
    }


def test_postfix_chain_passes_and_records_all_links(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    assert (root / 'frozen-work.json').is_file()
    assert (root / 'issued-comparison.json').is_file()
    comparison = json.loads((root / 'comparison.json').read_text())
    assert [row['arm_id'] for row in comparison['arm_receipts']] == ['a', 'b']
    assert len(comparison['eligible_arms']) == 2
    adopted = controller.adopt(ctx, root, H.choice(ctx, root, 'a'))
    assert adopted['status'] == 'ADOPTED'
    assert adopted['frozen_work_digest'] == json.loads((root / 'plan.json').read_text())['frozen_work_digest']
    assert adopted['comparison_digest']
    assert adopted['acceptance_rerun']['status'] == 'PASS'
    assert controller.verify_adoption(ctx, root)['selected'] == 'a'


def test_final_validator_failure_cannot_publish_adopted_pass(tmp_path):
    ctx = H.context(tmp_path)
    calls = {'count': 0}

    def late_failure(outputs, binding):
        calls['count'] += 1
        evidence = H.validate_text(outputs, binding)
        if calls['count'] == 3:
            gates = dict(evidence.gates)
            gates['transform'] = 'FAIL'
            return em.Evidence(evidence.binding, 'FAIL', gates,
                               evidence.outputs, evidence.metrics,
                               'late transform validator failure')
        return evidence

    source_files = dict(H.adapter('a').source_files)
    source_files[str(Path(__file__).resolve())] = em.digest(Path(__file__).resolve())
    source_files.update({str(p): em.digest(p) for p in em._source_closure(source_files)})
    arm = replace(H.adapter('a'), validate=late_failure, source_files=source_files)
    controller = H.controller(arm)
    root = tmp_path / 'run'
    result = controller.run(ctx, root)
    assert result['status'] == 'REFUSED'
    adoption = json.loads((root / 'adoption.json').read_text())
    assert adoption['status'] == 'REFUSED'
    assert adoption['reason'] == 'FINAL_EVIDENCE_CHANGED'
    assert adoption.get('acceptance_rerun') is None


def test_verify_adoption_rehashes_selected_artifacts(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    controller.adopt(ctx, root, H.choice(ctx, root))
    generation = json.loads((root / 'adoption.json').read_text())['selected_generation']
    artifact = Path(generation['directory']) / 'value.txt'
    artifact.chmod(0o644)
    artifact.write_text('mutated after adoption\n')
    with pytest.raises(em.Refusal, match='SELECTED_GENERATION_CHANGED'):
        controller.verify_adoption(ctx, root)


def test_resealed_selected_generation_cannot_replace_original_producer_evidence(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'))
    root = tmp_path / 'run'
    controller.run(ctx, root)
    adopted = controller.adopt(ctx, root, H.choice(ctx, root))
    generation = dict(adopted['selected_generation'])
    selected = Path(generation['directory']) / 'value.txt'
    selected.chmod(0o644)
    selected.write_text('forged selected bytes\n')
    generation['outputs']['value.txt'] = em.digest(selected)
    manifest_path = Path(generation['directory']) / 'manifest.json'
    with pytest.raises(em.Refusal, match='ISSUED_AUTHORITY_REISSUE'):
        em._issue_sealed(manifest_path, generation)
    forged = dict(adopted)
    forged['selected_generation'] = generation
    forged['winner'] = dict(forged['winner'], artifact_outputs=dict(generation['outputs']))
    # The production writer is intentionally not importable.  Co-updating the
    # two public adoption documents leaves the original sealed issuer record
    # untouched and must be rejected before the winner can be consumed.
    (root / 'adoption.json').write_text(json.dumps(forged))
    (root / 'program_adoption.json').write_text(json.dumps(forged))
    with pytest.raises(em.Refusal, match='PROGRAM_ADOPTION_CHANGED'):
        controller.verify_adoption(ctx, root)


def test_legacy_seal_and_imported_adoption_writer_cannot_issue_authority():
    # The former mutable authority globals and writer were the exact seam used
    # to co-update a selected generation, winner and adoption receipt.
    assert not hasattr(em, '_ISSUED_AUTHORITY')
    assert not hasattr(em, '_seal')
    assert not hasattr(em.Controller, '_write_adoption')


def test_reverse_mutation_of_frozen_work_is_refused(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'))
    root = tmp_path / 'run'
    controller.run(ctx, root)
    frozen = json.loads((root / 'frozen-work.json').read_text())
    frozen['mode_intent'] = 'ultra'
    (root / 'frozen-work.json').write_text(json.dumps(frozen))
    with pytest.raises(em.Refusal, match='FROZEN_WORK_DIGEST_MISMATCH'):
        controller.adopt(ctx, root, H.choice(ctx, root))


def test_reverse_mutation_of_issued_arm_is_refused(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    receipt = json.loads((root / 'a/receipt.json').read_text())
    receipt['honest_verdict'] = 'PASS'
    (root / 'a/receipt.json').write_text(json.dumps(receipt))
    choice = H.choice(ctx, root, 'a')
    choice['receipt_sha256'] = em.digest(root / 'a/receipt.json')
    with pytest.raises(em.Refusal, match='ARM_RECEIPT_DIGEST_MISMATCH'):
        controller.adopt(ctx, root, choice)


def test_reverse_mutation_of_ai_comparison_is_refused(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'))
    root = tmp_path / 'run'
    controller.run(ctx, root)
    comparison = json.loads((root / 'comparison.json').read_text())
    comparison['selection_criterion']['ordered_by'] = 'attacker'
    (root / 'comparison.json').write_text(json.dumps(comparison))
    with pytest.raises(em.Refusal, match='COMPARISON_AUTHORITY'):
        controller.adopt(ctx, root, H.choice(ctx, root))


def test_reverse_mutation_of_program_adoption_is_refused(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'))
    root = tmp_path / 'run'
    controller.run(ctx, root)
    controller.adopt(ctx, root, H.choice(ctx, root))
    adoption = json.loads((root / 'program_adoption.json').read_text())
    adoption['winner']['arm_id'] = 'wrong'
    (root / 'program_adoption.json').write_text(json.dumps(adoption))
    with pytest.raises(em.Refusal, match='PROGRAM_ADOPTION_CHANGED'):
        controller.verify_adoption(ctx, root)


def test_swapped_winner_artifact_and_changed_acceptance_refuse(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    choice = H.choice(ctx, root, 'b')
    choice['receipt_sha256'] = em.digest(root / 'a/receipt.json')
    with pytest.raises(em.Refusal, match='AI_RECEIPT_DIGEST_MISMATCH'):
        controller.adopt(ctx, root, choice)

    changed = replace(ctx, objective={'goal': 'different', 'metric': 'cost', 'direction': 'min'})
    with pytest.raises(em.Refusal, match='AI_CHOICE_UNBOUND'):
        controller.adopt(changed, root, H.choice(ctx, root, 'b'))


def test_incomplete_arm_set_and_failing_arm_cannot_be_adopted(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    (root / 'b/receipt.json').unlink()
    with pytest.raises(em.Refusal, match='INCOMPLETE_ARM_SET'):
        controller.adopt(ctx, root, H.choice(ctx, root, 'a'))

    failing = tmp_path / 'failing'
    failed_controller = H.controller(H.adapter('a', fault='fail_gate'))
    failed_controller.run(ctx, failing)
    assert json.loads((failing / 'a/receipt.json').read_text())['status'] == 'FAIL'
    with pytest.raises(em.Refusal, match='AI_CHOICE_INELIGIBLE'):
        failed_controller.adopt(ctx, failing, H.choice(ctx, failing))


def test_ultra_requires_explicit_user_evidence_and_children_preserve_it(monkeypatch):
    monkeypatch.setenv(policy.ENV, json.dumps({'mode': 'ultra', 'cpus': 1, 'ram_mb': 128}))
    with pytest.raises(em.Refusal, match='REQUEST_RECEIPT|ULTRA_INTENT'):
        policy.request()
    monkeypatch.delenv(policy.ENV)
    args = type('Args', (), dict(execution_mode='ultra', execution_cpus=1,
                                 execution_ram_mb=128, execution_workers=1,
                                 execution_licenses=None, execution_choice=None,
                                 execution_choice_wait_s=0))()
    import vibe_ic_one_shot_runner as front
    with pytest.raises(em.Refusal, match='ULTRA_ISSUER_NOT_ALLOWED'):
        front._configure_execution_policy(args)
    value = _live_frontdoor_fixture(front, args)
    assert value['authority'] == 'USER_EXPLICIT_ULTRA'
    assert '--execution-mode' in policy.child_arguments(['project'])
    assert policy.require_explicit_ultra()['authority'] == 'USER_EXPLICIT_ULTRA'


@pytest.mark.parametrize('payload', [
    {'mode': 'ultra', 'authority': 'USER_EXPLICIT_ULTRA'},
    {'mode': 'ultra', 'category': 'ultra', 'intent_label': 'USER_EXPLICIT_ULTRA'},
])
def test_untrusted_environment_and_metadata_cannot_issue_ultra(monkeypatch, payload):
    monkeypatch.setenv(policy.ENV, json.dumps(payload))
    with pytest.raises(em.Refusal, match='REQUEST_RECEIPT|ULTRA_INTENT'):
        policy.request()


def test_unregistered_caller_cannot_install_frontdoor_issuer():
    assert not hasattr(policy, '_register_frontdoor_issuer')


def test_recomputed_receipt_with_valid_looking_process_identity_is_not_authority(monkeypatch):
    monkeypatch.delenv(policy._CAPABILITY_FD_ENV, raising=False)
    forged = dict(schema=1, mode='ultra', mode_label='ultra-mode',
                  intent_label='USER_EXPLICIT_ULTRA', ultra_match=True,
                  issuer='live-frontdoor', issuer_pid=os.getppid(),
                  issuer_start_ticks='valid-looking-but-untrusted')
    forged['request_digest'] = policy._digest(forged)
    monkeypatch.setenv(policy.ENV, json.dumps({
        'mode': 'ultra', 'request_digest': forged['request_digest'],
        'request_receipt': forged}))
    with pytest.raises(em.Refusal, match='REQUEST_CAPABILITY_(REQUIRED|INVALID)'):
        policy.request()


def test_child_cannot_upgrade_digest_bound_program_default(monkeypatch):
    monkeypatch.delenv(policy.ENV, raising=False)
    args = type('Args', (), dict(execution_mode='default', execution_cpus=1,
                                 execution_ram_mb=128, execution_workers=1,
                                 execution_licenses=None, execution_choice=None,
                                 execution_choice_wait_s=0))()
    policy.configure(args)
    ultra = type('Args', (), dict(execution_mode='ultra', execution_cpus=1,
                                  execution_ram_mb=128, execution_workers=1,
                                  execution_licenses=None, execution_choice=None,
                                  execution_choice_wait_s=0))()
    with pytest.raises(em.Refusal, match='ULTRA_ISSUER_NOT_ALLOWED|PARENT_REQUEST_CONFLICT'):
        policy.configure(ultra)


def test_child_parent_digest_and_receipt_must_travel_as_a_pair(monkeypatch):
    monkeypatch.delenv(policy.ENV, raising=False)
    args = type('Args', (), dict(execution_mode='ultra', execution_cpus=1,
                                 execution_ram_mb=128, execution_workers=1,
                                 execution_licenses=None, execution_choice=None,
                                 execution_choice_wait_s=0,
                                 execution_request_digest='a' * 64,
                                 execution_request_receipt=None))()
    with pytest.raises(em.Refusal, match='PARENT_REQUEST_MISSING'):
        policy.configure(args)


def test_issued_ultra_receipt_preserves_authority_and_tamper_refuses(monkeypatch, tmp_path):
    monkeypatch.delenv(policy.ENV, raising=False)
    top = type('Args', (), dict(execution_mode='ultra', execution_cpus=1,
                                execution_ram_mb=128, execution_workers=1,
                                execution_licenses=None, execution_choice=None,
                                execution_choice_wait_s=0))()
    import vibe_ic_one_shot_runner as front
    issued = _live_frontdoor_fixture(front, top)
    assert issued['request_digest']
    env = dict(os.environ)
    env[policy.ENV] = json.dumps(issued, sort_keys=True)
    monkeypatch.setattr(os, 'environ', env)
    assert policy.request()['authority'] == 'USER_EXPLICIT_ULTRA'
    receipt = tmp_path / 'forged-request.json'
    receipt.write_text('{}')
    env[policy.ENV] = json.dumps(dict(issued, request_receipt_path=str(receipt), request_receipt_sha256=em.digest(receipt)))
    with pytest.raises(em.Refusal, match='REQUEST_RECEIPT_INVALID'):
        policy.request()


def test_unregistered_parent_socket_cannot_forge_child_ultra(tmp_path):
    issuer_process = dict(
        pid=os.getpid(),
        start_ticks=policy._process_start_ticks(os.getpid()),
        source_path=str(policy._CANONICAL_FRONTDOOR),
        source_sha256=policy._canonical_source_sha256())
    receipt = dict(schema=1, mode='ultra', mode_label='ultra-mode',
                   intent_label='USER_EXPLICIT_ULTRA', ultra_match=True,
                   issuer='live-frontdoor', issuer_role='canonical-frontdoor',
                   issuer_process=issuer_process,
                   invocation_id='forged-invocation-' + ('x' * 16), nonce='forged')
    receipt['request_digest'] = policy._digest(receipt)
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    def echo():
        try:
            raw = parent.recv(4096)
            if not raw:
                return
            request = json.loads(raw.split(b'\n', 1)[0].decode())
            parent.sendall(json.dumps({
                'ok': True, 'request_digest': request['request_digest'],
                'nonce': request['nonce'],
                'invocation_id': receipt['invocation_id'],
                'issuer_process': issuer_process}).encode() + b'\n')
        except (OSError, ValueError, KeyError):
            return
        finally:
            parent.close()

    import threading
    threading.Thread(target=echo, daemon=True).start()
    child_script = tmp_path / 'child.py'
    child_script.write_text('import execution_policy as p; print(p.request()["authority"])\n')
    env = {**os.environ, policy.ENV: json.dumps({
        'mode': 'ultra', 'request_digest': receipt['request_digest'],
        'request_receipt': receipt}),
        policy._CAPABILITY_FD_ENV: str(child.fileno()),
        'PYTHONPATH': str(Path(policy.__file__).parent)}
    result = subprocess.run([sys.executable, str(child_script)], env=env,
                            pass_fds=(child.fileno(),), capture_output=True, text=True)
    child.close()
    assert result.returncode != 0
    assert 'REQUEST_CAPABILITY_INVALID' in result.stderr


def test_ip_context_requires_and_binds_distinct_route_receipt(tmp_path):
    source = tmp_path / 'input.txt'
    source.write_text('ip input\n')
    with pytest.raises(em.Refusal, match='ROUTE_RECEIPT_REQUIRED'):
        em.Context('ip', H.BASE, {'text.txt': source}, H.OBJECTIVE, ('transform',),
                   ic_ip_path='IP').binding()
    request_digest = 'd' * 64
    project_digest = 'e' * 64
    route = issued_route(path='IP', source_sha=H.BASE, project_digest=project_digest,
                         request_digest=request_digest)
    project_digest, request_digest = route['project_digest'], route['request_digest']
    ctx = em.Context('ip', H.BASE, {'text.txt': source}, H.OBJECTIVE, ('transform',),
                     ic_ip_path='IP', route_receipt=route,
                     project_digest=project_digest, request_digest=request_digest)
    assert ctx.binding()['ic_ip_path'] == 'IP'
    with pytest.raises(em.Refusal, match='IC_IP_ROUTE_MISMATCH'):
        replace(ctx, route_receipt={**route, 'ic_ip_path': 'IC'}).binding()


def test_ic_context_also_requires_and_binds_an_issued_route_receipt(tmp_path):
    ctx = H.context(tmp_path)
    with pytest.raises(em.Refusal, match='ROUTE_RECEIPT_REQUIRED'):
        replace(ctx, route_receipt={}).binding()
    project_digest = 'f' * 64
    request_digest = '1' * 64
    route = issued_route(path='IC', source_sha=H.BASE, project_digest=project_digest,
                         request_digest=request_digest)
    project_digest, request_digest = route['project_digest'], route['request_digest']
    production = replace(ctx, route_receipt=route, project_digest=project_digest,
                         request_digest=request_digest)
    assert production.binding()['ic_ip_path'] == 'IC'
    with pytest.raises(em.Refusal, match='ROUTE_RECEIPT_DIGEST_MISMATCH'):
        replace(production, route_receipt={**route, 'route': 'tampered'}).binding()
    wrong_source = {**route, 'source_sha': '0' * 40}
    wrong_source['route_digest'] = em._hash({k: v for k, v in wrong_source.items()
                                             if k != 'route_digest'})
    with pytest.raises(em.Refusal, match='ROUTE_SOURCE_MISMATCH'):
        replace(production, route_receipt=wrong_source).binding()
    wrong_request = {**route, 'request_digest': '4' * 64}
    wrong_request['route_digest'] = em._hash({k: v for k, v in wrong_request.items()
                                              if k != 'route_digest'})
    with pytest.raises(em.Refusal, match='ROUTE_REQUEST_MISMATCH'):
        replace(production, route_receipt=wrong_request).binding()


@pytest.mark.parametrize('frontdoor', [
    'phase1_one_shot_runner.py', 'design_one_shot_runner.py',
    'phase23_one_shot_runner.py', 'phase3_one_shot_runner.py',
])
def test_child_frontdoors_cannot_issue_ultra(frontdoor, monkeypatch):
    monkeypatch.delenv(policy.ENV, raising=False)
    args = type('Args', (), dict(execution_mode='ultra', execution_cpus=1,
                                 execution_ram_mb=128, execution_workers=1,
                                 execution_licenses=None, execution_choice=None,
                                 execution_choice_wait_s=0))()
    with pytest.raises(em.Refusal, match='ULTRA_ISSUER_NOT_ALLOWED'):
        policy.configure(args)
    source = (Path(policy.__file__).parent / frontdoor).read_text()
    assert '_execution.configure(args)' in source
    assert 'can_issue=' not in source


def test_controller_fields_requires_resolved_route_and_preserves_ip(monkeypatch):
    monkeypatch.delenv(policy.ENV, raising=False)
    with pytest.raises(em.Refusal, match='PRODUCTION_ROUTE_REQUIRED'):
        policy.controller_fields()
    fields_route = issued_route(
        path='IP', source_sha=H.BASE, project_digest='b' * 64,
        request_digest=policy.request()['request_digest'], route='macro-v1')
    fields = policy.controller_fields(ic_ip_path='IP', route_receipt=fields_route)
    assert fields['ic_ip_path'] == 'IP'
    assert fields['route_receipt']['ic_ip_path'] == 'IP'
    assert fields['intent_label'] == 'PROGRAM_DEFAULT'


def test_controller_fields_rejects_silent_ic_route_for_ip(monkeypatch):
    monkeypatch.delenv(policy.ENV, raising=False)
    fields_route = issued_route(
        path='IP', source_sha=H.BASE, project_digest='b' * 64,
        request_digest=policy.request()['request_digest'], route='macro-v1')
    with pytest.raises(em.Refusal, match='IC_IP_ROUTE_MISMATCH'):
        policy.controller_fields(
            ic_ip_path='IP', route_receipt={**fields_route, 'ic_ip_path': 'IC'})


def test_routed_production_context_cannot_bypass_explicit_ultra_intent(tmp_path):
    ctx = H.context(tmp_path)
    request_digest = '2' * 64
    project_digest = '3' * 64
    route = issued_route(path='IC', source_sha=H.BASE, project_digest=project_digest,
                         request_digest=request_digest, route='resolved')
    project_digest, request_digest = route['project_digest'], route['request_digest']
    routed = replace(ctx, route_receipt=route, project_digest=project_digest,
                     request_digest=request_digest)
    with pytest.raises(em.Refusal, match='ULTRA_INTENT_MISSING'):
        H.controller(H.adapter('a'), H.adapter('b')).plan(routed, 'ultra-mode')


def test_self_hashed_unregistered_route_cannot_make_a_production_context(tmp_path):
    ctx = H.context(tmp_path)
    receipt = dict(schema=1, kind='issued-route',
                   authority='canonical-route-authority',
                   issuer='vibeic-route-frontdoor', ic_ip_path='IC',
                   source_sha=H.BASE, project_digest='a' * 64,
                   request_digest='b' * 64, route='attacker')
    receipt['current_pointer'] = em._route_pointer(receipt)
    receipt['route_digest'] = em._hash(receipt)
    routed = replace(ctx, route_receipt=receipt,
                     project_digest=receipt['project_digest'],
                     request_digest=receipt['request_digest'])
    with pytest.raises(em.Refusal, match='ROUTE_AUTHORITY_UNAVAILABLE'):
        routed.binding()
    with pytest.raises(em.Refusal, match='ROUTE_AUTHORITY_UNAVAILABLE'):
        policy.controller_fields(ic_ip_path='IC', route_receipt=receipt)


def test_route_receipt_must_remain_the_current_authority_pointer(tmp_path):
    first = issued_route(path='IC', source_sha=H.BASE,
                         project_digest='c' * 64, request_digest='d' * 64,
                         route='first')
    second = issued_route(path='IC', source_sha=H.BASE,
                          project_digest='c' * 64, request_digest='d' * 64,
                          route='second')
    source = tmp_path / 'input.txt'
    source.write_text('route input\n')
    stale = em.Context('1', H.BASE, {'text.txt': source}, H.OBJECTIVE,
                        ('transform',), ic_ip_path='IC', route_receipt=first,
                        project_digest=first['project_digest'], request_digest=first['request_digest'])
    assert second['route_digest'] != first['route_digest']
    with pytest.raises(em.Refusal, match='ROUTE_AUTHORITY_UNAVAILABLE'):
        stale.binding()


def test_capability_peer_eof_refuses_without_an_empty_read_loop(monkeypatch):
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    child.close()
    process = dict(pid=os.getpid(),
                   start_ticks=policy._process_start_ticks(os.getpid()),
                   source_path=str(policy._CANONICAL_FRONTDOOR),
                   source_sha256=policy._canonical_source_sha256())
    receipt = dict(issuer_role='canonical-frontdoor', issuer_process=process,
                   invocation_id='invocation-' + ('x' * 20))
    monkeypatch.setenv(policy._CAPABILITY_FD_ENV, str(parent.fileno()))
    monkeypatch.setattr(policy, '_canonical_process_cmdline',
                        lambda pid: str(policy._CANONICAL_FRONTDOOR))
    with pytest.raises(em.Refusal, match='REQUEST_CAPABILITY_INVALID'):
        policy._verify_parent_capability('e' * 64, receipt)
    parent.close()


def test_unsupported_analog_leaf_keeps_argv_without_policy_flags(monkeypatch):
    import types
    import vibe_ic_one_shot_runner as front
    monkeypatch.setenv(policy.ENV, json.dumps({'mode': 'ultra'}))
    argv = ['--project', 'design']
    assert policy.child_arguments(argv, supports_execution_policy=False) == argv
    observed = []

    def spy_run(command, *, env=None, pass_fds=(), **kwargs):
        observed.append((list(command), tuple(pass_fds)))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(front.subprocess, 'run', spy_run)
    runner = Path('/tmp/analog_a8_hardmacro_emit.py')
    assert front._run_phase('ANALOG', runner, argv, env=dict(os.environ)) == 0
    assert observed == [([sys.executable, str(runner), *argv], ())]


def test_explicit_ultra_keeps_mixed_child_argv_and_live_capability(monkeypatch, tmp_path):
    import types
    import vibe_ic_one_shot_runner as front
    real_entry('IC', 'ultra', tmp_path / 'project')
    front._configure_execution_policy(types.SimpleNamespace())
    argv = ['--project', 'design']
    observed = []

    def spy_run(command, *, env=None, pass_fds=(), **kwargs):
        observed.append((list(command), None if env is None else dict(env), tuple(pass_fds)))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(front.subprocess, 'run', spy_run)
    runner = Path('/tmp/mixed_signal_m3_run.py')
    assert front._run_phase('M3', runner, argv, env=dict(os.environ)) == 0
    command, child_env, pass_fds = observed[0]
    assert command == [sys.executable, str(runner), *argv]
    assert child_env[policy.ENV]
    assert pass_fds == ()


@pytest.mark.parametrize('parent,child', [
    ('phase23', 'design_one_shot_runner.py'),
    ('phase23', 'analog_one_shot_runner.py'),
    ('front', 'analog_one_shot_runner.py'),
    ('front', 'phase2_one_shot_runner.py'),
])
def test_phase23_preserves_capability_for_parser_capable_phase_child(monkeypatch,
                                                                   tmp_path,
                                                                   parent, child):
    import types
    import phase23_one_shot_runner as chain
    import vibe_ic_one_shot_runner as front
    caller = chain if parent == 'phase23' else front
    # Use the canonical resolver for Phase 2: the production regression was
    # caused by this public-name shim being omitted from the capability-FD
    # allowlist even though it re-exports design_one_shot_runner.main.
    runner = (front._phase_runner('phase2')
              if parent == 'front' and child == 'phase2_one_shot_runner.py'
              else Path('/tmp') / child)
    original_run = chain.subprocess.run
    real_entry('IC', 'ultra', tmp_path / 'project')
    policy.configure(types.SimpleNamespace())
    observed = []

    def spy_run(command, *, pass_fds=(), **kwargs):
        if command[0] != sys.executable or command[1] != str(runner):
            return original_run(command, pass_fds=pass_fds, **kwargs)
        observed.append((list(command), tuple(pass_fds)))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(caller.subprocess, 'run', spy_run)
    argv = ['project']
    result = caller._run_phase('CHILD', runner, argv)
    rc = result[0] if parent == 'phase23' else result
    assert rc == 0
    command, pass_fds = observed[0]
    assert command[:4] == [sys.executable, str(runner), 'project', '--execution-mode']
    assert policy.child_pass_fds() == pass_fds


def test_step8_callback_imports_dispatcher_for_unbound_context(monkeypatch,
                                                              tmp_path):
    import design_one_shot_runner as design
    project = tmp_path
    expected = dict(status='NOT_MEASURED', reason='FOCUSED_CALLBACK_PROBE')
    calls = []
    monkeypatch.setattr(policy, 'dispatch_fixed_step',
                        lambda path, step: calls.append((path, step)) or expected)
    result = design.step_sdc_validation(project)
    assert calls == [(project, '8')]
    assert result.status == 'NOT_MEASURED'
    assert result.extras['execution_result'] is expected


def test_default_run_auto_adopts_sole_eligible_without_choice_file(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'default'
    result = controller.run(ctx, root)
    assert result['status'] == 'ADOPTED'
    assert result['selected'] == 'a'
    assert not (root / 'choice.json').exists()
    assert json.loads((root / 'result.json').read_text())['status'] == 'ADOPTED'
    assert json.loads((root / 'adoption.json').read_text())['status'] == 'ADOPTED'
    assert [p.name for p in root.iterdir() if p.is_dir() and p.name in ('a', 'b')] == ['a']


@pytest.mark.parametrize('fault,expected', [
    ('fail_gate', 'FAIL'), ('unmeasured', 'NOT_MEASURED'),
])
def test_default_failure_or_unmeasured_result_is_not_auto_adopted(tmp_path, fault, expected):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a', fault=fault))
    root = tmp_path / fault
    result = controller.run(ctx, root)
    assert result['status'] == expected
    assert result['selected'] is None
    assert not (root / 'adoption.json').exists()


def test_ultra_waits_for_digest_bound_choice_and_rejects_ineligible_arm(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b', fault='fail_gate'))
    root = tmp_path / 'ultra'
    result = controller.run(ctx, root, 'ultra-mode')
    assert result['status'] == 'FAIL'
    with pytest.raises(em.Refusal, match='AI_CHOICE_INELIGIBLE'):
        controller.adopt(ctx, root, H.choice(ctx, root, 'b'))


def test_ultra_fail_precedes_unmeasured_when_no_arm_is_eligible(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a', fault='fail_gate'),
                              H.adapter('b', fault='process_error'))
    result = controller.run(ctx, tmp_path / 'ultra', 'ultra-mode')
    assert result['candidate_statuses'] == {'a': 'FAIL', 'b': 'NOT_MEASURED'}
    assert result['status'] == 'FAIL'
    comparison = json.loads((tmp_path / 'ultra/comparison.json').read_text())
    issued = json.loads((tmp_path / 'ultra/issued-comparison.json').read_text())
    assert comparison['status'] == issued['payload']['status'] == 'FAIL'


def test_stdin_runner_cmdline_cannot_answer_canonical_capability(tmp_path):
    """A process mentioning the runner path but executing stdin is not the issuer."""
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    script = (
        'import os,sys,json,socket\n'
        'import execution_policy as p\n'
        'fd=int(sys.argv[2])\n'
        's=socket.socket(fileno=fd)\n'
        'line=s.recv(4096)\n'
        'req=json.loads(line.split(b"\\n",1)[0])\n'
        'proc=p._process_identity(os.getpid())\n'
        's.sendall((json.dumps({"ok":True,"request_digest":req["request_digest"],'
        '"nonce":req["nonce"],"invocation_id":"forged-invocation-xxxxxxxx",'
        '"issuer_process":proc}).encode()+b"\\n"))\n'
    )
    # The fake process advertises the canonical source in argv, but argv[1] is
    # '-' and the executable is running stdin rather than the script object.
    result = subprocess.Popen(
        [sys.executable, '-', str(policy._CANONICAL_FRONTDOOR), str(child.fileno())],
        stdin=subprocess.PIPE, pass_fds=(child.fileno(),), text=True,
        env={**os.environ, 'PYTHONPATH': str(Path(policy.__file__).parent)},
    )
    result.stdin.write(script)
    result.stdin.close()
    child.close()
    # The verifier only needs the receipt's process identity; obtain it while
    # the fake process is live from /proc through its known PID.
    process = policy._process_identity(result.pid)
    receipt = dict(issuer_role='canonical-frontdoor', issuer_process=process,
                   invocation_id='forged-invocation-' + ('x' * 16))
    old_fd = os.environ.get(policy._CAPABILITY_FD_ENV)
    os.environ[policy._CAPABILITY_FD_ENV] = str(parent.fileno())
    try:
        with pytest.raises(policy.Refusal, match='REQUEST_CAPABILITY_INVALID'):
            policy._verify_parent_capability('e' * 64, receipt)
    finally:
        if old_fd is None:
            os.environ.pop(policy._CAPABILITY_FD_ENV, None)
        else:
            os.environ[policy._CAPABILITY_FD_ENV] = old_fd
        parent.close()
        result.kill()
        result.wait()


def test_route_issuer_api_cannot_be_called_by_an_arbitrary_caller():
    assert not hasattr(em, '_issue_route_receipt')
    assert not hasattr(em, '_register_route_issuer')


def test_compiled_route_frame_spoof_cannot_register_or_issue(tmp_path):
    script = (
        'import execution_modes as p\n'
        'a=object()\n'
        'try:\n'
        ' exec(compile("p._register_route_issuer(a)", str(p.__file__), "exec"), {"p":p,"a":a})\n'
        ' print("ISSUED")\n'
        'except Exception as e:\n'
        ' print(type(e).__name__+":"+getattr(e,"code",""))\n')
    result = subprocess.run([sys.executable, '-'], input=script, text=True,
                            capture_output=True,
                            env={**os.environ, 'PYTHONPATH': str(Path(em.__file__).parent)})
    assert 'AttributeError' in result.stdout
    assert 'ISSUED' not in result.stdout


def test_real_owner_route_entry_issues_typed_receipt_after_admission(tmp_path):
    stage_owner_route(tmp_path, 'ic')
    assert _delivery_route.admit(tmp_path) is None
    receipt = real_entry(project=tmp_path)['route']
    assert receipt['kind'] == 'issued-route'
    assert receipt['ic_ip_path'] == 'IC'


def test_public_neutral_test_sentinel_without_fixture_boundary_refuses(tmp_path):
    source = tmp_path / 'input.txt'
    source.write_text('input\n')
    context = em.Context('1', H.BASE, {'text.txt': source}, H.OBJECTIVE,
                         ('transform',), ic_ip_path='IC',
                         route_receipt={'kind': 'neutral-test', 'ic_ip_path': 'IC'})
    with pytest.raises(em.Refusal, match='ROUTE_RECEIPT_INVALID'):
        context.binding()


def test_route_issuer_rejects_none_digest_fields():
    assert not hasattr(em, '_issue_route_receipt')
    with pytest.raises(em.Refusal, match='PRODUCTION_ROUTE_REQUIRED'):
        policy.controller_fields(ic_ip_path=None, route_receipt=None)


def test_unexecuted_canonical_gate_names_cannot_be_validator_pass(tmp_path):
    source = tmp_path / 'input.txt'
    source.write_text('input\n')
    gates = ('flow_step_output_content_check', 'catalog_synth_safe_params_check')
    ctx = replace(H.context(tmp_path), required_gates=gates)
    arm = H.adapter('gatefake')
    source_files = dict(arm.source_files)
    source_files[str(Path(__file__).resolve())] = em.digest(Path(__file__).resolve())
    source_files.update({str(p): em.digest(p) for p in em._source_closure(source_files)})

    def dishonest(outputs, binding):
        evidence = H.validate_text(outputs, binding)
        return em.Evidence(evidence.binding, 'PASS', {gate: 'PASS' for gate in gates},
                           evidence.outputs, {'cost': 1})

    arm = replace(arm, validate=dishonest, source_files=source_files)
    registry = em.Registry(); registry.register(arm)
    portfolio = {'meta': {'test_only': True}, 'steps': [
        {'id': '1', 'mandatory_gate_programs': list(gates),
         'required_output_contract': ['value.txt', 'measurement.json']} ]}
    controller = em.Controller(registry, em.Budget(2, 512), portfolio)
    result = controller.run(ctx, tmp_path / 'run')
    assert result['status'] == 'NOT_MEASURED'
    assert result['candidate_statuses']['gatefake'] == 'NOT_MEASURED'


def test_imported_frontdoor_wrapper_cannot_mint_ultra(tmp_path):
    script = (
        'import argparse, vibe_ic_one_shot_runner as f\n'
        'a=argparse.Namespace(execution_mode="ultra", execution_cpus=1, '
        'execution_ram_mb=128, execution_workers=1, execution_licenses=None, '
        'execution_choice=None, execution_choice_wait_s=0)\n'
        'try: f._configure_execution_policy(a)\n'
        'except Exception as e: print(getattr(e,"code",""))\n')
    result = subprocess.run([sys.executable, '-'], input=script, text=True,
                            capture_output=True,
                            env={**os.environ, 'PYTHONPATH': str(Path(em.__file__).parent)})
    assert result.returncode == 0
    assert 'ULTRA_ISSUER_NOT_ALLOWED' in result.stdout


def test_selected_generation_mutation_during_publish_refuses(tmp_path, monkeypatch):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    original = em.Controller._selected_generation

    def mutate_after_copy(run_root, receipt, issue):
        generation = original(run_root, receipt, issue)
        artifact = Path(generation['directory']) / 'value.txt'
        artifact.chmod(0o644)
        artifact.write_text('late selected mutation\n')
        return generation

    monkeypatch.setattr(em.Controller, '_selected_generation', staticmethod(mutate_after_copy))
    with pytest.raises(em.Refusal, match='SELECTED_GENERATION_CHANGED'):
        controller.adopt(ctx, root, H.choice(ctx, root))
    assert json.loads((root / 'adoption.json').read_text())['status'] == 'REFUSED'


def test_portfolio_snapshot_missing_current_yaml_gate_is_refused():
    portfolio = em.load_portfolio()
    row = next(row for row in portfolio['steps'] if str(row['id']) == '2')
    row['mandatory_gate_programs'].remove('rtl_bug_report_schema_check')
    with pytest.raises(em.Refusal, match='PORTFOLIO_GATES_STALE'):
        em.Controller(em.Registry(), em.Budget(1, 128), portfolio)


def test_rehashed_portfolio_source_sha_cannot_authenticate_canonical_yaml(tmp_path):
    portfolio = em.load_portfolio()
    row = portfolio['steps'][0]
    row['current_default']['source']['sha'] = '0' * 40
    path = tmp_path / 'portfolio.json'
    path.write_text(json.dumps(portfolio))
    with pytest.raises(em.Refusal, match='PORTFOLIO_SOURCE_UNBOUND'):
        em.load_portfolio(path)


def test_route_ultra_intent_cannot_be_omitted_or_downgraded(tmp_path):
    project_digest = 'a' * 64
    request_digest = 'b' * 64
    route = real_entry(execution_mode='ultra')['route']
    project_digest, request_digest = route['project_digest'], route['request_digest']
    ctx = replace(H.context(tmp_path), route_receipt=route,
                  project_digest=project_digest, request_digest=request_digest,
                  intent_label='USER_EXPLICIT_ULTRA')
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    assert controller.plan(ctx)['mode'] == 'ultra-mode'
    with pytest.raises(em.Refusal, match='ROUTE_INTENT_MISMATCH'):
        controller.plan(ctx, 'default-mode')
    with pytest.raises(em.Refusal, match='ROUTE_INTENT_MISMATCH'):
        replace(ctx, intent_label='PROGRAM_DEFAULT').binding()


def test_ultra_worse_objective_recommendation_is_refused(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a', cost=9), H.adapter('b', cost=1))
    root = tmp_path / 'run'
    assert controller.run(ctx, root, 'ultra-mode')['status'] == 'AWAITING_AI_SELECTION'
    with pytest.raises(em.Refusal, match='AI_CHOICE_WORSE_OBJECTIVE'):
        controller.adopt(ctx, root, H.choice(ctx, root, 'a'))
    assert json.loads((root / 'adoption.json').read_text())['status'] == 'REFUSED'


def test_ultra_diversity_ignores_arm_labels_when_provider_identity_matches(tmp_path):
    first = H.adapter('neutral_a')
    second = replace(H.adapter('neutral_a'), arm_id='neutral_b', tool_id=first.tool_id,
                     engine_families=('caller_label_b',))
    plan = H.controller(first, second).plan(H.context(tmp_path), 'ultra-mode')
    assert plan['arms'] == ['neutral_a']
    assert next(row for row in plan['portfolio'] if row['arm_id'] == 'neutral_b')['admission'] == 'SAME_ENGINE_FAMILY'


def test_fabricated_known_tool_identity_cannot_register(tmp_path):
    forged = replace(H.adapter('fake'), tool_id='librelane',
                     tool_version='fabricated-999')
    with pytest.raises(em.Refusal, match='TOOL_ID_UNBOUND|TOOL_VERSION_UNBOUND'):
        em.Registry().register(forged)


def test_unrelated_git_source_commit_cannot_authenticate_fixture_bytes():
    forged = replace(H.adapter('fake'),
                     source_sha='f88175263d96c3a76b4cb18f72c7714c68ec6627')
    with pytest.raises(em.Refusal, match='SOURCE_AUTHORITY_STALE'):
        em.Registry().register(forged)
