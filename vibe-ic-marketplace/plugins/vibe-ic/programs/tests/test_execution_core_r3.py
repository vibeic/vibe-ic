"""Public reverse controls for exact R2 findings; no production test issuer."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from programs.tests import test_execution_modes as H
from programs.tests.test_execution_receipt_chain import real_entry, isolated_transport
import execution_modes as em
import execution_policy as policy


def test_fresh_imported_caller_assigning_old_tokens_cannot_issue(tmp_path):
    script = '''import argparse,execution_policy as p,execution_modes as m,vibe_ic_one_shot_runner as f
p._ACTIVE_ENTRY_CAPABILITY=object()
m._ACTIVE_ROUTE_ENTRY_CAPABILITY=object()
p._REGISTERED_ISSUER=p._ACTIVE_ENTRY_CAPABILITY
p._ISSUED_REQUESTS={}
try:
 f._configure_execution_policy(argparse.Namespace(execution_mode="ultra"),_entry_capability=p._ACTIVE_ENTRY_CAPABILITY)
 raise SystemExit("FORGED_ULTRA")
except m.Refusal as e:
 print(e.code)
assert not hasattr(m,"_issue_route_receipt")
'''
    env = {k:v for k,v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
    env['PYTHONPATH'] = str(Path(em.__file__).parent)
    probe = subprocess.run([sys.executable, '-'], input=script, env=env, text=True, capture_output=True, timeout=5)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == 'ULTRA_ISSUER_NOT_ALLOWED'


def test_same_engine_source_with_different_argv_and_aliases_is_one_arm(tmp_path):
    first = H.adapter('a', cost=9)
    second = replace(first, arm_id='b', tool_id='invented', tool_version='other',
                     engine_families=('different',), components=tuple(
                         replace(c, argv=(*c.argv[:-1], '1')) for c in first.components))
    plan = H.controller(first, second).plan(H.context(tmp_path), 'ultra-mode')
    assert plan['arms'] == ['a']
    assert plan['portfolio'][1]['admission'] == 'SAME_ENGINE_FAMILY'


def test_untracked_python_copy_named_librelane_cannot_win_default(tmp_path):
    binary = tmp_path / 'librelane'
    binary.write_bytes(Path(sys.executable).resolve().read_bytes()); binary.chmod(0o755)
    arm = H.adapter()
    sources = dict(arm.source_files); sources[str(binary)] = em.digest(binary)
    arm = replace(arm, tool_id='librelane', tool_version='1.0', source_files=sources,
                  components=tuple(replace(c, argv=(str(binary), *c.argv[1:])) for c in arm.components))
    with pytest.raises(em.Refusal, match='TOOL_ID_UNBOUND'):
        em.Registry().register(arm)


def test_untracked_source_cannot_self_rehash_into_git_authority(tmp_path):
    script = tmp_path / 'tool.py'; script.write_text('print("fake")\n')
    arm = H.adapter()
    source = dict(arm.source_files); source[str(script)] = em.digest(script)
    with pytest.raises(em.Refusal, match='SOURCE_AUTHORITY_UNAVAILABLE'):
        em.Registry().register(replace(arm, source_files=source))


def test_live_canonical_launcher_issues_route_and_rejects_rehash(tmp_path):
    payload = real_entry('IP', 'ultra', tmp_path)
    route = payload['route']
    fields = policy.controller_fields(ic_ip_path='IP', route_receipt=route)
    p = tmp_path / 'source.txt'; p.write_text('input\n')
    ctx = em.Context('1', H.BASE, {'text.txt': p}, H.OBJECTIVE, ('transform',),
                     project_digest=route['project_digest'], **fields)
    assert ctx.binding()['intent_label'] == 'USER_EXPLICIT_ULTRA'
    forged = dict(route, route='ic'); forged['route_digest'] = em._hash({k:v for k,v in forged.items() if k!='route_digest'})
    with pytest.raises(em.Refusal, match='ROUTE_AUTHORITY_UNAVAILABLE'):
        replace(ctx, route_receipt=forged).binding()


def test_portfolio_binds_stable_git_blob_without_self_commit():
    portfolio = em.load_portfolio()
    assert 'source_commit' not in portfolio['meta']
    assert portfolio['meta']['canonical_flow_git_blob'] == subprocess.check_output(
        ['git', '-C', str(em._REPO_ROOT), 'hash-object', str(em._canonical_flow_path())], text=True).strip()
    assert len(portfolio['steps']) == 70


def test_fresh_clone_post_register_source_mutation_cannot_rehash_snapshot(tmp_path):
    clone = tmp_path / 'source'
    result = subprocess.run(['git', 'clone', '--quiet', '--local', '--no-hardlinks', str(em._REPO_ROOT), str(clone)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plugin = clone / 'vibe-ic-marketplace/plugins/vibe-ic'
    script = r"""
import tempfile
from pathlib import Path
from programs.tests import test_execution_modes as H
arm=H.adapter('a')
registry=H.em.Registry(); registry.register(arm)
path=Path(arm.components[0].argv[1])
path.write_bytes(path.read_bytes()+b'\nMUTATED_TRANSITIVE_SOURCE\n')
arm.source_files[str(path)]=H.em.digest(path)
controller=H.em.Controller(registry,H.em.Budget(2,512),H.controller().portfolio)
root=Path(tempfile.mkdtemp())
try:
    controller.run(H.context(root),root/'run')
except H.em.Refusal as exc:
    assert exc.code == 'PROVIDER_DEPENDENCY_UNBOUND', exc
else:
    raise AssertionError('mutated registered source reached execution')
assert not (root/'run/selected').exists()
assert not (root/'run/a/receipt.json').exists()
print('POST_REGISTER_REHASH_REFUSED')
"""
    probe = subprocess.run([sys.executable, '-c', script], cwd=plugin, capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == 'POST_REGISTER_REHASH_REFUSED'


def test_sitecustomize_pre_script_socket_cannot_be_canonical_issuer(tmp_path):
    import time
    site = tmp_path / 'injection'; site.mkdir()
    socket_path = tmp_path / 'attacker.sock'
    marker = tmp_path / 'ready'
    injected = """import socket,os,time
s=socket.socket(socket.AF_UNIX);s.bind(%r);s.listen(1)
open(%r,'w').write(str(os.getpid()))
c,_=s.accept()
time.sleep(3)
""" % (str(socket_path),str(marker))
    (site/'sitecustomize.py').write_text(injected)
    environment = {k:v for k,v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
    environment['PYTHONPATH'] = str(site)
    attacker = subprocess.Popen([str(Path(sys.executable).resolve()),str(Path(policy.__file__).with_name('vibe_ic_one_shot_runner.py')),'--help'],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    fd=os.memfd_create('forged-parent')
    try:
        for _ in range(100):
            if marker.exists(): break
            time.sleep(.01)
        assert marker.exists(), 'pre-script injection never executed'
        ticks=Path(f'/proc/{attacker.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        os.write(fd,json.dumps(dict(pid=attacker.pid,start_ticks=ticks,token='x'*64)).encode())
        os.environ[policy._CAPABILITY_FD_ENV]=str(fd)
        os.environ['VIBEIC_EXECUTION_AUTH_SOCKET']=str(socket_path)
        from execution_authority import consume
        started=time.monotonic()
        with pytest.raises(em.Refusal,match='REQUEST_CAPABILITY_INVALID'):
            consume()
        assert time.monotonic()-started < 2
    finally:
        attacker.terminate();attacker.wait(timeout=5);os.close(fd)
