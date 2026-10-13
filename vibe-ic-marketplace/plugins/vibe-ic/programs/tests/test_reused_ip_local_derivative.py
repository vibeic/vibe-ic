"""Source admission of a finite local correction, through the ordinary consumer.

Neutral locally versioned IP exercises real independent official pulls. Fixture
challenge receipts are source-contract data, never credited as native proof.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_versioned_reused_ip_fetch import _upstream, _match, _project, _git
import design_one_shot_runner as runner
import ip_catalog_pull as pull
import ip_catalog_query as query


def _h(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def _fixture(tmp_path, monkeypatch):
    repo, erratum = _upstream(tmp_path)
    # A second official file must not escape the derivative's complete inventory.
    (repo / 'rtl/helper.v').write_text('module helper; endmodule\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'second official file')
    _git(repo, 'tag', '-f', '2.3.4')
    match = _match(repo, erratum)
    # This fixture's tag already contains the older corrected bytes; no claim
    # that a fix predates its declared parent is needed for this local contract.
    match.errata = []
    match.rtl_files.append('rtl/helper.v')
    monkeypatch.setattr(query, 'query_catalog', lambda *a, **kw: [match])
    monkeypatch.setattr(pull, 'CACHE_ROOT', tmp_path/'cache')
    project = _project(tmp_path, 'Reuse leaf from vendor:reusable:leaf:2.3.4.')
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    rtl = project/'phase2/stage1/rtl'
    support = project/'local'
    parent = support/'parent'
    shutil.copytree(rtl, parent/'phase2/stage1/rtl')
    shutil.copy2(project/'provenance.jsonl', parent/'provenance.jsonl')
    old = (rtl/'leaf.v').read_text()
    new = old.replace("1'b1", "1'bx")
    before = {p.name: _h(p) for p in rtl.glob('*.v')}
    after = {**before, 'leaf.v': hashlib.sha256(new.encode()).hexdigest()}
    patch = {'format': 'exact_utf8_replacements.v1', 'files': [{
        'path': 'leaf.v', 'sha256_before': before['leaf.v'],
        'sha256_after': after['leaf.v'],
        'edits': [{'before': old, 'after': new}]}]}
    _json(support/'patch.json', patch)
    (support/'challenge.v').write_text('module challenge; endmodule\n')
    input_path = project/'input/docs/contract.md'
    input_path.parent.mkdir(parents=True)
    input_path.write_text('Reset is synchronous at the rising clock edge.\n')
    for name, code, inventory in [('red', 1, before), ('green', 0, after)]:
        _json(support/(name+'.json'), {
            'results': [{'name': 'compile', 'rc': 0}, {'name': 'run', 'rc': code}],
            'tb_sha256': _h(support/'challenge.v'), 'rtl': inventory})
    def ref(path):
        return {'path': path.relative_to(project).as_posix(), 'sha256': _h(path)}
    record = {
        'schema': 'vibeic.reused_ip_local_derivative.v1', 'kind': 'LOCAL_DERIVATIVE',
        'parent_project': 'local/parent',
        'parent_manifest': ref(parent/'phase2/stage1/rtl/SOURCE_MANIFEST.json'),
        'parent_provenance': ref(parent/'provenance.jsonl'),
        'patch': ref(support/'patch.json'), 'current_inventory': after,
        'local_provenance': {'actor': 'fixture author', 'reason': 'contract correction', 'owner_ruling': 'explicit fixture authorization'},
        'input_obligations': [{**ref(input_path), 'quote': 'Reset is synchronous at the rising clock edge.'}],
        'proof': {'challenge': ref(support/'challenge.v'), 'parent_red': ref(support/'red.json'), 'candidate_green': ref(support/'green.json')},
    }
    _json(support/'record.json', record)
    return project, match, ref(support/'record.json'), record


def _apply(project, match, ref):
    return pull.apply_local_derivative(project, [match], ref)


def _authored_glue_fixture(tmp_path, monkeypatch):
    project, match, ref, record = _fixture(tmp_path, monkeypatch)
    rtl = project/'phase2/stage1/rtl'
    (rtl/'top_wrapper.v').write_text('module top_wrapper; leaf core(); endmodule\n')
    digest = _h(rtl/'top_wrapper.v')
    record['current_inventory']['top_wrapper.v'] = digest
    for key in ('parent_red', 'candidate_green'):
        path = project/record['proof'][key]['path']
        receipt = json.loads(path.read_text())
        receipt['rtl']['top_wrapper.v'] = digest
        _json(path, receipt)
        record['proof'][key]['sha256'] = _h(path)
    _json(project/ref['path'], record)
    ref['sha256'] = _h(project/ref['path'])
    return project, match, ref


def _authored_metadata_bytes(project):
    paths = ('phase2/stage1/rtl/SOURCE_MANIFEST.json',
             'plugin_output/declaration.json', 'provenance.jsonl')
    return {name: (project/name).read_bytes() if (project/name).is_file() else None
            for name in paths}


def test_authored_glue_producer_then_actual_derivative_and_ordinary_consumer(tmp_path, monkeypatch):
    project, match, ref = _authored_glue_fixture(tmp_path, monkeypatch)
    # The existing consumer actually refuses a genuine extra glue file before
    # the new writer. This is not a missing-new-API baseline assertion.
    failed = _apply(project, match, ref)
    assert failed['status'] == pull.PIN_MISMATCH
    assert 'declared complete current inventory' in failed['reason']
    emitted = pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert emitted['status'] == pull.PIN_VERIFIED
    assert emitted['ai_authored_files'] == [
        {'path': 'top_wrapper.v', 'sha256': _h(project/'phase2/stage1/rtl/top_wrapper.v')}]
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    consumed = runner.step_rtl_gen(project, 'processor_cpu')
    assert consumed.status == 'PASS_WITH_WAIVERS', consumed.detail
    assert consumed.extras['ip_fetch']['reuse_kind'] == 'LOCAL_DERIVATIVE'


def test_authored_glue_legacy_caller_rows_remain_admitted(tmp_path, monkeypatch):
    project, match, ref = _authored_glue_fixture(tmp_path, monkeypatch)
    path = project/'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    manifest = json.loads(path.read_text())
    manifest['ai_authored_files'] = [
        {'path': 'top_wrapper.v', 'sha256': _h(path.parent/'top_wrapper.v')}]
    _json(path, manifest)
    # Historical valid caller metadata and actual official-parent reproduction
    # remain valid without a newly imposed authored-inventory event requirement.
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    assert runner.step_rtl_gen(project, 'processor_cpu').status == 'PASS_WITH_WAIVERS'


def test_authored_glue_repeat_is_byte_idempotent_and_no_duplicate_event(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    assert pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])['status'] == pull.PIN_VERIFIED
    before = _authored_metadata_bytes(project)
    again = pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert again['already_current'] is True and again['outputs'] == {}
    assert _authored_metadata_bytes(project) == before
    events = [json.loads(x) for x in (project/'provenance.jsonl').read_text().splitlines()]
    assert sum(x.get('event') == 'ip_catalog_authored_glue_inventory' for x in events) == 1


def test_authored_glue_append_preserves_valid_last_line_without_newline(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    path = project/'provenance.jsonl'
    previous = path.read_bytes().rstrip(b'\n')
    path.write_bytes(previous)
    assert pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])['status'] == pull.PIN_VERIFIED
    assert path.read_bytes().startswith(previous + b'\n')
    events = [json.loads(x) for x in path.read_text().splitlines()]
    assert events[-1]['event'] == 'ip_catalog_authored_glue_inventory'


@pytest.mark.parametrize('names', [[], ['../top_wrapper.v'], ['/top_wrapper.v'],
    ['nested/top_wrapper.v'], ['nested\\top_wrapper.v'], ['leaf.v'],
    ['top_wrapper.v', 'top_wrapper.v'], ['missing.v']])
def test_authored_glue_invalid_declared_paths_never_publish(tmp_path, monkeypatch, names):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    before = _authored_metadata_bytes(project)
    with pytest.raises((ValueError, OSError)):
        pull.emit_authored_glue_inventory(project, [match], names)
    assert _authored_metadata_bytes(project) == before


@pytest.mark.parametrize('name', ['extra.v', 'extra.svh', 'notes.txt'])
def test_authored_glue_unlisted_inventory_never_publish(tmp_path, monkeypatch, name):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    (project/'phase2/stage1/rtl'/name).write_text('unlisted data\n')
    before = _authored_metadata_bytes(project)
    with pytest.raises(ValueError, match='undeclared'):
        pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert _authored_metadata_bytes(project) == before


@pytest.mark.parametrize('name', ['named.vh', 'named.svh'])
def test_authored_glue_named_regular_headers_are_explicit_inputs(tmp_path, monkeypatch, name):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    (project/'phase2/stage1/rtl'/name).write_text('`define LOCAL_WIDTH 3\n')
    out = pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v', name])
    assert out['status'] == pull.PIN_VERIFIED
    assert {x['path'] for x in out['ai_authored_files']} == {'top_wrapper.v', name}


def test_authored_glue_source_symlink_refused_before_publication(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    path = project/'phase2/stage1/rtl/top_wrapper.v'
    outside = tmp_path/'outside.v'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    before = _authored_metadata_bytes(project)
    with pytest.raises(ValueError, match='symlink'):
        pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert _authored_metadata_bytes(project) == before


def test_authored_glue_source_ancestor_symlink_never_publishes(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    path = project/'phase2/stage1/rtl'
    outside = tmp_path/'outside-rtl'
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=True)
    before = _authored_metadata_bytes(project)
    with pytest.raises(ValueError, match='symlink'):
        pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert _authored_metadata_bytes(project) == before


def test_authored_glue_metadata_ancestor_symlink_never_publishes(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    path = project/'plugin_output'
    outside = tmp_path/'outside-metadata'
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=True)
    before = _authored_metadata_bytes(project)
    with pytest.raises(ValueError, match='escapes'):
        pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert _authored_metadata_bytes(project) == before


def test_authored_glue_non_source_input_refused_before_publication(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    (project/'phase2/stage1/rtl/notes.txt').write_text('caller metadata\n')
    before = _authored_metadata_bytes(project)
    with pytest.raises(ValueError, match='RTL or a source header'):
        pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v', 'notes.txt'])
    assert _authored_metadata_bytes(project) == before


def test_authored_glue_independent_pin_failure_never_publishes(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    # A fresh independent upstream pull, not local consistent hashes, wins.
    upstream = Path(match.canonical_url)
    (upstream/'rtl/leaf.v').write_text('module leaf; wire changed; endmodule\n')
    _git(upstream, 'add', '.')
    _git(upstream, 'commit', '-qm', 'replace pinned source')
    _git(upstream, 'tag', '-f', '2.3.4')
    before = _authored_metadata_bytes(project)
    refused = pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert refused['status'] == pull.PIN_MISMATCH, refused
    assert _authored_metadata_bytes(project) == before


def test_authored_glue_independent_pin_unavailable_never_publishes(tmp_path, monkeypatch):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    Path(match.canonical_url).rename(tmp_path/'unreachable-source')
    before = _authored_metadata_bytes(project)
    refused = pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert refused['status'] == pull.PIN_UNAVAILABLE, refused
    assert _authored_metadata_bytes(project) == before


@pytest.mark.parametrize('which', ['source', 'manifest', 'declaration', 'provenance'])
def test_authored_glue_actual_fetch_then_concurrent_drift_never_overwrites(tmp_path, monkeypatch, which):
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    verifier = pull.verify_existing_official_pins_outcome
    at_refusal = {}
    def real_fetch_then_drift(*args, **kwargs):
        state = verifier(*args, **kwargs)
        assert state[0] == pull.PIN_VERIFIED
        paths = {'source': project/'phase2/stage1/rtl/top_wrapper.v',
                 'manifest': project/'phase2/stage1/rtl/SOURCE_MANIFEST.json',
                 'declaration': project/'plugin_output/declaration.json',
                 'provenance': project/'provenance.jsonl'}
        path = paths[which]
        path.write_bytes(path.read_bytes() + b'\n')
        at_refusal.update(_authored_metadata_bytes(project))
        return state
    monkeypatch.setattr(pull, 'verify_existing_official_pins_outcome', real_fetch_then_drift)
    with pytest.raises(ValueError, match='changed before authored publication'):
        pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert _authored_metadata_bytes(project) == at_refusal


def test_authored_glue_cli_dry_run_refuses_without_writes(tmp_path, monkeypatch):
    project, _, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    before = _authored_metadata_bytes(project)
    with pytest.raises(SystemExit) as refused:
        pull.main([str(project), '--authored-glue', 'top_wrapper.v', '--dry-run'])
    assert refused.value.code == 2
    assert _authored_metadata_bytes(project) == before


def test_normal_consumer_admits_complete_declared_local_derivative(tmp_path, monkeypatch):
    # Same supplied derivative bytes/receipts reach the old and new ordinary
    # runner. The pre-fix failure is its observed FAIL verdict, not a missing API.
    project, _, ref, record = _fixture(tmp_path, monkeypatch)
    patch = json.loads((project/'local/patch.json').read_text())
    (project/'phase2/stage1/rtl/leaf.v').write_text(patch['files'][0]['edits'][0]['after'])
    mf_path=project/'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    mf=json.loads(mf_path.read_text());mf['local_derivative']=ref;_json(mf_path,mf)
    event={'event':'ip_catalog_local_derivative','kind':'LOCAL_DERIVATIVE',
           'record':ref,'current_inventory':record['current_inventory'],
           'exit_code':0,'outputs':{'phase2/stage1/rtl/leaf.v':'sha256:'+record['current_inventory']['leaf.v']},
           'official_unmodified_files':1,'locally_adapted_reused_files':1,
           'separately_authored_files':[]}
    with (project/'provenance.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')
    result=runner.step_rtl_gen(project,'processor_cpu')
    assert result.status=='PASS_WITH_WAIVERS', result.detail
    assert result.extras['ip_fetch']['reuse_kind']=='LOCAL_DERIVATIVE'


def test_declared_derivative_runs_through_producer_and_normal_consumer(tmp_path, monkeypatch):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    outcome = _apply(project, match, ref)
    assert outcome['status'] == pull.PIN_VERIFIED
    assert outcome['official_unmodified_files'] == 1
    assert outcome['locally_adapted_reused_files'] == 1
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS'
    assert result.extras['ip_fetch']['reuse_kind'] == 'LOCAL_DERIVATIVE'
    assert 'Admitted LOCAL DERIVATIVE' in result.detail
    mf = json.loads((project/'phase2/stage1/rtl/SOURCE_MANIFEST.json').read_text())
    assert pull.verify_existing_official_pins_outcome(project, [match], mf)[0] == pull.PIN_MISMATCH
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED


def _replace_last_derivative_event(provenance, transform):
    lines = provenance.read_bytes().splitlines(keepends=True)
    event = json.loads(lines[-1])
    assert event['event'] == 'ip_catalog_local_derivative'
    lines[-1] = (json.dumps(transform(event), sort_keys=True) + '\n').encode()
    provenance.write_bytes(b''.join(lines))


def test_producer_recovers_exact_legacy_outputless_event_and_preserves_history(tmp_path, monkeypatch):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    provenance = project/'provenance.jsonl'
    _replace_last_derivative_event(provenance, lambda event: {k:v for k,v in event.items() if k not in ('exit_code', 'outputs')})
    legacy_bytes = provenance.read_bytes()

    recovered = _apply(project, match, ref)
    assert recovered['status'] == pull.PIN_VERIFIED, recovered
    assert provenance.read_bytes().startswith(legacy_bytes)
    current = json.loads(provenance.read_bytes().splitlines()[-1])
    assert current['event'] == 'ip_catalog_local_derivative'
    assert current['outputs'] == {
        'phase2/stage1/rtl/leaf.v': 'sha256:'+_h(project/'phase2/stage1/rtl/leaf.v')}
    assert current != json.loads(legacy_bytes.splitlines()[-1])
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['ip_fetch']['reuse_kind'] == 'LOCAL_DERIVATIVE'


def test_recovered_current_producer_event_is_idempotent(tmp_path, monkeypatch):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    provenance = project/'provenance.jsonl'
    _replace_last_derivative_event(provenance, lambda event: {k:v for k,v in event.items() if k not in ('exit_code', 'outputs')})
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    before = provenance.read_bytes()
    result = _apply(project, match, ref)
    assert result['status'] == pull.PIN_VERIFIED, result
    assert provenance.read_bytes() == before


@pytest.mark.parametrize('mutation', ['changed_event', 'changed_output_digest',
                                      'missing_event', 'current_bytes'])
def test_legacy_output_recovery_refuses_nonlegacy_or_drift(tmp_path, monkeypatch, mutation):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    provenance = project/'provenance.jsonl'
    lines = provenance.read_bytes().splitlines(keepends=True)
    event = json.loads(lines[-1])
    if mutation == 'missing_event':
        lines.pop()
    elif mutation == 'changed_event':
        event.pop('outputs')
        event['exit_code'] = 7
        lines[-1] = (json.dumps(event, sort_keys=True) + '\n').encode()
    elif mutation == 'changed_output_digest':
        event['outputs']['phase2/stage1/rtl/leaf.v'] = 'sha256:'+'0'*64
        lines[-1] = (json.dumps(event, sort_keys=True) + '\n').encode()
    else:
        (project/'phase2/stage1/rtl/leaf.v').write_text('module leaf; wire drift; endmodule\n')
        event.pop('outputs')
        event.pop('exit_code')
        lines[-1] = (json.dumps(event, sort_keys=True) + '\n').encode()
    provenance.write_bytes(b''.join(lines))
    before = provenance.read_bytes()
    rtl = project/'phase2/stage1/rtl'
    before_rtl = {p.name: p.read_bytes() for p in rtl.iterdir() if p.is_file()}
    result = _apply(project, match, ref)
    assert result['status'] == pull.PIN_MISMATCH, result
    assert provenance.read_bytes() == before
    assert {p.name: p.read_bytes() for p in rtl.iterdir() if p.is_file()} == before_rtl


@pytest.mark.parametrize('mutation', ['adapted_drift', 'extra_file', 'undeclared_change',
    'missing_parent', 'missing_patch', 'missing_evidence', 'missing_input',
    'producer_receipt', 'forged_parent', 'patch_context', 'symlink', 'record_drift'])
def test_normal_consumer_blocks_local_derivative_drift(tmp_path, monkeypatch, mutation):
    project, match, ref, record = _fixture(tmp_path, monkeypatch)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    rtl = project/'phase2/stage1/rtl'
    if mutation == 'adapted_drift':
        (rtl/'leaf.v').write_text('module leaf; endmodule\n')
    elif mutation == 'extra_file':
        (rtl/'extra.vh').write_text('`define extra 1\n')
    elif mutation == 'undeclared_change':
        (rtl/'helper.v').write_text('module helper; wire x; endmodule\n')
    elif mutation == 'missing_parent':
        (project/'local/parent/phase2/stage1/rtl/helper.v').unlink()
    elif mutation == 'missing_patch':
        (project/'local/patch.json').unlink()
    elif mutation == 'missing_evidence':
        (project/'local/red.json').unlink()
    elif mutation == 'missing_input':
        (project/'input/docs/contract.md').unlink()
    elif mutation == 'producer_receipt':
        events = [json.loads(l) for l in (project/'provenance.jsonl').read_text().splitlines()]
        (project/'provenance.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events if e['event'] != 'ip_catalog_local_derivative'))
    elif mutation == 'forged_parent':
        # Rewrite ALL local hashes to agree with forged parent bytes. The fresh
        # independent official pull must still defeat this receipt laundering.
        p = project/'local/parent/phase2/stage1/rtl/helper.v'
        p.write_text('module helper; wire forged; endmodule\n')
        (rtl/'helper.v').write_bytes(p.read_bytes())
        digest = _h(p)
        for mf_path in [project/'local/parent/phase2/stage1/rtl/SOURCE_MANIFEST.json', rtl/'SOURCE_MANIFEST.json']:
            mf = json.loads(mf_path.read_text());mf['source_pins'][0]['files_sha256']['rtl/helper.v'] = digest;_json(mf_path,mf)
        for prov in [project/'local/parent/provenance.jsonl',project/'provenance.jsonl']:
            events = [json.loads(l) for l in prov.read_text().splitlines()]
            for e in events:
                if e['event']=='ip_catalog_pull':
                    e['outputs']['phase2/stage1/rtl/helper.v']='sha256:'+digest
                    e['outputs_sha256']=[e['outputs'][k][7:] for k in e['outputs']]
            prov.write_text(''.join(json.dumps(e)+'\n' for e in events))
        for key in ['parent_manifest','parent_provenance']:
            record[key]['sha256'] = _h(project/record[key]['path'])
        record['current_inventory']['helper.v'] = digest
        for key in ['parent_red','candidate_green']:
            p=project/record['proof'][key]['path'];receipt=json.loads(p.read_text());receipt['rtl']['helper.v']=digest;_json(p,receipt);record['proof'][key]['sha256']=_h(p)
        _json(project/'local/record.json',record)
        mf=json.loads((rtl/'SOURCE_MANIFEST.json').read_text());mf['local_derivative']['sha256']=_h(project/'local/record.json');_json(rtl/'SOURCE_MANIFEST.json',mf)
    elif mutation == 'patch_context':
        p=project/'local/patch.json';patch=json.loads(p.read_text());patch['files'][0]['edits'][0]['before']='absent exact context';_json(p,patch)
        record['patch']['sha256']=_h(p);_json(project/'local/record.json',record)
        mf=json.loads((rtl/'SOURCE_MANIFEST.json').read_text());mf['local_derivative']['sha256']=_h(project/'local/record.json');_json(rtl/'SOURCE_MANIFEST.json',mf)
    elif mutation == 'symlink':
        p=rtl/'helper.v';p.unlink();p.symlink_to(project/'local/parent/phase2/stage1/rtl/helper.v')
    elif mutation == 'record_drift':
        (project/'local/record.json').write_text('{}\n')
    result = runner.step_rtl_gen(project, 'processor_cpu')
    if mutation == 'symlink':
        # The unchanged earlier staged-closure guard stops the normal runner
        # before pin admission; source admission itself must still refuse it.
        assert result.status == 'NOT_MEASURED'
        mf = json.loads((rtl/'SOURCE_MANIFEST.json').read_text())
        assert pull.verify_existing_reused_pins_outcome(project, [match], mf)[0] == pull.PIN_MISMATCH
        return
    assert result.status == 'FAIL'
    assert 'LOCAL_DERIVATIVE_REFUSED' in result.detail or 'official parent:' in result.detail


def test_missing_local_inputs_refuse_before_producer_mutation(tmp_path, monkeypatch):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    path=project/'phase2/stage1/rtl/leaf.v';before=path.read_bytes()
    (project/'local/green.json').unlink()
    assert _apply(project, match, ref)['status']==pull.PIN_MISMATCH
    assert path.read_bytes()==before


def test_unavailable_parent_cannot_hide_proven_current_drift(tmp_path, monkeypatch):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    (project/'phase2/stage1/rtl/helper.v').write_text('module helper; wire changed; endmodule\n')
    monkeypatch.setattr(pull, 'verify_existing_official_pins_outcome',
                        lambda *a, **kw: (pull.PIN_UNAVAILABLE, 'unreachable'))
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'FAIL'
    assert 'current full inventory drift' in result.detail
