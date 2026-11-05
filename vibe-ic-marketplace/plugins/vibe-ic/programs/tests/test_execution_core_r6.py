"""Defensive issuer controls use the real isolated entry and production Context."""
import importlib
import json
import os
import socket
import sys
from types import ModuleType

import pytest
import execution_authority as authority
from programs.tests import test_execution_modes as H
from programs.tests.test_execution_core_r4 import issued_context
from programs.tests.test_execution_receipt_chain import real_entry


def refused(controller, ctx, root):
    result = controller.run(ctx, root)
    assert result['status'] == 'REFUSED'
    assert result['selected'] is None
    assert result['candidate_statuses'] == {}
    assert controller.adopt(ctx, root, None)['status'] == 'REFUSED'
    for name in ('selected', 'issued-plan.json', 'adoption.json', 'a'):
        assert not (root / name).exists()
    assert json.loads((root / 'result.json').read_text())['status'] == 'REFUSED'
    return result




@pytest.mark.parametrize('slot', ['consume', 'read_line', 'tracked', 'validate_payload', 'source_closure'])
def test_ISSUER_CALLABLE_REPLACEMENT_REFUSED(tmp_path, monkeypatch, slot):
    ctx = issued_context(tmp_path, 'default')
    calls = []
    def substituted(*args, **kwargs):
        calls.append(slot)
        raise AssertionError('a replaced issuer callable must never run')
    monkeypatch.setattr(authority, slot, substituted)
    result = refused(H.controller(H.adapter('a')), ctx, tmp_path / 'run')
    assert result['reason'] == 'CONTROLLER_ISSUANCE_REQUIRED'
    assert 'ISSUER_IMPLEMENTATION_UNTRUSTED' in result['detail']
    assert calls == []


@pytest.mark.parametrize('replacement', ['missing', 'substitute', 'reload'])
def test_ISSUER_MODULE_SLOT_REFUSED(tmp_path, monkeypatch, replacement):
    ctx = issued_context(tmp_path, 'default')
    original = dict(vars(authority))
    try:
        if replacement == 'missing':
            monkeypatch.delitem(sys.modules, 'execution_authority')
        elif replacement == 'substitute':
            substitute = ModuleType('execution_authority')
            substitute.__dict__.update(original)
            monkeypatch.setitem(sys.modules, 'execution_authority', substitute)
        else:
            importlib.reload(authority)
        result = refused(H.controller(H.adapter('a')), ctx, tmp_path / 'run')
        assert 'ISSUER_IMPLEMENTATION_UNTRUSTED' in result['detail']
    finally:
        if replacement == 'reload':
            authority.__dict__.clear()
            authority.__dict__.update(original)


@pytest.mark.parametrize('descriptor', ['missing', 'negative', 'closed', 'text', 'ordinary-file', 'copied-sealed'])
def test_CAPABILITY_DESCRIPTOR_REFUSED(tmp_path, monkeypatch, descriptor):
    ctx = issued_context(tmp_path, 'default')
    opened = None
    if descriptor == 'missing':
        monkeypatch.delenv(authority.FD_ENV)
    elif descriptor in ('negative', 'closed', 'text'):
        monkeypatch.setenv(authority.FD_ENV, {'negative': '-1', 'closed': '999999', 'text': 'invalid'}[descriptor])
    elif descriptor == 'ordinary-file':
        opened = os.open(ctx.inputs['text.txt'], os.O_RDONLY)
        monkeypatch.setenv(authority.FD_ENV, str(opened))
    else:
        import fcntl
        opened = os.memfd_create('defensive-capability-copy', os.MFD_ALLOW_SEALING)
        os.write(opened, os.pread(int(os.environ[authority.FD_ENV]), 4096, 0))
        fcntl.fcntl(opened, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        monkeypatch.setenv(authority.FD_ENV, str(opened))
    try:
        result = refused(H.controller(H.adapter('a')), ctx, tmp_path / 'run')
        assert 'REQUEST_CAPABILITY_INVALID' in result['detail']
    finally:
        if opened is not None:
            os.close(opened)






@pytest.mark.parametrize('field', ['token', 'nonce', 'invocation_id', 'request_digest', 'route_digest'])
def test_LIVE_CHALLENGE_INVALID_FIELD_REFUSED(tmp_path, field):
    real_entry('IC', 'default', tmp_path)
    credential = json.loads(os.pread(int(os.environ[authority.FD_ENV]), 4096, 0))
    challenge = {name: credential[name] for name in ('token', 'invocation_id', 'request_digest', 'route_digest')}
    challenge['nonce'] = 'a' * 64
    challenge[field] = 'invalid'
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(os.environ[authority.SOCKET_ENV])
        client.sendall(json.dumps(challenge).encode() + b'\n')
        response = authority.read_line(client)
    assert response['ok'] is False
    assert response['payload'] is None
    assert not (tmp_path / 'selected').exists()


@pytest.mark.parametrize('field', ['request_digest', 'route_digest', 'invocation_id', 'source_sha', 'source_tree',
                                 'empty-blobs', 'missing-blobs', 'null-issuer', 'wrong-blob'])
def test_ISSUER_PAYLOAD_MISSING_OR_CHANGED_IDENTITY_REFUSED(tmp_path, field):
    payload = real_entry('IC', 'default', tmp_path)
    credential = json.loads(os.pread(int(os.environ[authority.FD_ENV]), 4096, 0))
    if field == 'empty-blobs':
        payload['source_blobs'] = {}
    elif field == 'missing-blobs':
        payload.pop('source_blobs')
    elif field == 'null-issuer':
        payload['issuer_blob'] = None
    elif field == 'wrong-blob':
        payload['source_blobs'][next(iter(payload['source_blobs']))] = '0' * 40
    elif field == 'request_digest':
        payload['request'][field] = None
        payload['route'][field] = None
        credential[field] = None
    else:
        payload['route'][field] = None
    with pytest.raises(ValueError):
        authority.validate_payload(payload, credential)
    assert not (tmp_path / 'selected').exists()
