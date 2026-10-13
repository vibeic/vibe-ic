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


def test_actual_glue_then_derivative_preserves_history_and_verifies_manifest_output(tmp_path, monkeypatch):
    import provenance_output_hash_completeness_check as provenance
    project, match, ref = _authored_glue_fixture(tmp_path, monkeypatch)
    assert pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])['status'] == pull.PIN_VERIFIED
    ledger = project/'provenance.jsonl'
    old_history = ledger.read_bytes()
    old_manifest = _h(project/'phase2/stage1/rtl/SOURCE_MANIFEST.json')
    emitted = _apply(project, match, ref)
    assert emitted['status'] == pull.PIN_VERIFIED
    # Grade the same existing audit's observed verdict on base and candidate;
    # a missing new output field alone would not be a substantive control.
    verdict, findings, _ = provenance.audit_counted(project)
    assert verdict == 'PASS', [(f.rule, f.detail) for f in findings]
    assert ledger.read_bytes().startswith(old_history)
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert rows[-2]['outputs']['phase2/stage1/rtl/SOURCE_MANIFEST.json'] == 'sha256:'+old_manifest
    assert emitted['outputs']['phase2/stage1/rtl/SOURCE_MANIFEST.json'] == (
        'sha256:'+_h(project/'phase2/stage1/rtl/SOURCE_MANIFEST.json'))
    before = _authored_metadata_bytes(project)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    assert _authored_metadata_bytes(project) == before


@pytest.mark.parametrize('mutation', ['manifest_bytes', 'stale_latest_output', 'extra_inventory', 'stale_record'])
def test_derivative_manifest_lineage_refusals_never_republish_bad_state(tmp_path, monkeypatch, mutation):
    import provenance_output_hash_completeness_check as provenance
    project, match, ref = _authored_glue_fixture(tmp_path, monkeypatch)
    assert pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])['status'] == pull.PIN_VERIFIED
    old_manifest = _h(project/'phase2/stage1/rtl/SOURCE_MANIFEST.json')
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    mf = project/'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    if mutation == 'manifest_bytes':
        mf.write_bytes(mf.read_bytes()+b'\n')  # valid same JSON; genuinely different bytes
    elif mutation == 'stale_latest_output':
        _replace_last_derivative_event(project/'provenance.jsonl', lambda event: {
            **event, 'outputs': {**event['outputs'],
                'phase2/stage1/rtl/SOURCE_MANIFEST.json': 'sha256:'+old_manifest}})
    elif mutation == 'extra_inventory':
        (mf.parent/'notes.txt').write_text('unexpected current source report\n')
    else:
        record = project/ref['path']
        record.write_bytes(record.read_bytes()+b'\n')
    before = _authored_metadata_bytes(project)
    before_rtl = {p.name: p.read_bytes() for p in mf.parent.iterdir() if p.is_file()}
    state, reason = pull.verify_existing_reused_pins_outcome(project, [match], json.loads(mf.read_text()))
    assert state == pull.PIN_MISMATCH, reason
    refused = _apply(project, match, ref)
    assert refused['status'] == pull.PIN_MISMATCH, refused
    assert _authored_metadata_bytes(project) == before
    assert {p.name: p.read_bytes() for p in mf.parent.iterdir() if p.is_file()} == before_rtl
    if mutation in ('manifest_bytes', 'stale_latest_output'):
        verdict, findings, _ = provenance.audit_counted(project)
        assert verdict == 'FAIL'
        assert any(f.rule == 'PROVENANCE_HASH_MISMATCH' for f in findings)


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


def _interface_fixture(tmp_path, monkeypatch):
    """Neutral input choice with real official pull and real selected consumer."""
    project, match, _ = _authored_glue_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(pull, 'query_catalog', lambda *a, **kw: [match])
    rel, contract = _prepare_interface_inputs(project)
    return project, match, rel, contract


def _prepare_interface_inputs(project):
    source = project/'phase2/stage1/rtl/top_wrapper.v'
    source.write_text('module top_wrapper(input clk, output [3:0] o_memory_raddr, '
                      'output [3:0] o_memory_waddr);\n'
                      'assign o_memory_raddr = 4\'b0010;\n'
                      'assign o_memory_waddr = 4\'b0011;\nendmodule\n')
    doc = project/'input/docs/L3_external_interface.md'
    doc.write_text('''# External interface
Reuse leaf from vendor:reusable:leaf:2.3.4.
Memory names are illustrative; declare the selected protocol.
| Signal | Width | Direction | Description |
|---|---|---|---|
| `clk` | 1 | input | clock |
| `o_memory_addr` | 4 | output | address (typical) |

The Plugin MUST declare `plugin_output/declaration.json` before authoring:
| Field | Required | Example |
|---|---|---|
| `top_module` | Yes | `"top_wrapper"` |
| `memory_interface_protocol` | Yes | `"split_read_write"` |
''')
    import spec_declaration_emit as declaration
    assert declaration.main([str(project), '--set', 'top_module=top_wrapper',
                             '--set', 'memory_interface_protocol=split_read_write']) == 0
    from l_doc_generator_stamp import dump
    ports = [{'name': 'clk', 'direction': 'input', 'width': 1, 'evidence': str(doc.relative_to(project))},
             {'name': 'o_memory_addr', 'direction': 'output', 'width': 4,
              'evidence': str(doc.relative_to(project))}]
    dump(project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json',
         {'top_module': 'top_wrapper', 'top_ports': ports}, emitter='neutral-test-input')
    rel = 'plugin_input/interface.json'
    contract = {'schema': 'vibeic.authored_interface_renames.v1',
                'top_module': 'top_wrapper', 'actor': 'neutral fixture author',
                'rationale': 'The delegated address interface is split into read and write roles.',
                'renamed_interfaces': [{'l9': ['o_memory_addr'],
                                       'rtl': ['o_memory_raddr', 'o_memory_waddr']}],
                'input_obligations': [{'path': str(doc.relative_to(project)),
                                       'quote': 'Memory names are illustrative; declare the selected protocol.'}]}
    _json(project/rel, contract)
    return rel, contract


def _selected_interface(project):
    from _staged_top_module import selected_interface_ports
    return selected_interface_ports(project, json.loads(
        (project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json').read_text()))


def _assert_selected_interface_accepts(project):
    # Observe the actual unchanged consumer's verdict, including its refusal,
    # before comparing it. Baseline grading must reach a value assertion rather
    # than terminate on an uncaught exception or a newly absent manifest key.
    try:
        ports = _selected_interface(project)
        observation = {'accepted': True, 'ports': ports}
    except ValueError as exc:
        if str(exc) != 'selected interface rename is not declared in current manifest':
            raise
        observation = {'accepted': False, 'reason': str(exc)}
    assert observation['accepted'] is True, observation
    assert {port['name'] for port in observation['ports']} == {'clk', 'o_memory_raddr', 'o_memory_waddr'}


def _publish_interface(project, match, rel):
    # The baseline uses its real old producer rather than failing on new API
    # absence; the control's failure is the real consumer's measured refusal.
    import inspect
    kwargs = ({'authored_interface': rel}
              if 'authored_interface' in inspect.signature(pull.emit_authored_glue_inventory).parameters else {})
    return pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'], **kwargs)


def test_authored_interface_public_producer_changes_real_consumer_verdict(tmp_path, monkeypatch):
    project, match, rel, contract = _interface_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='rename is not declared'):
        _selected_interface(project)
    assert _publish_interface(project, match, rel)['status'] == pull.PIN_VERIFIED
    _assert_selected_interface_accepts(project)
    mf = project/'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    manifest = json.loads(mf.read_text())
    assert manifest['renamed_interfaces'] == contract['renamed_interfaces']
    event = json.loads((project/'provenance.jsonl').read_text().splitlines()[-1])
    assert event['inputs'][rel] == 'sha256:' + _h(project/rel)
    assert event['outputs']['phase2/stage1/rtl/SOURCE_MANIFEST.json'] == 'sha256:' + _h(mf)
    before = _authored_metadata_bytes(project)
    again = _publish_interface(project, match, rel)
    assert again['already_current'] and again['outputs'] == {}
    assert _authored_metadata_bytes(project) == before
    assert pull.verify_existing_reused_pins_outcome(project, [match], manifest)[0] == pull.PIN_VERIFIED


@pytest.mark.parametrize('control', ['subset', 'unknown_source', 'unknown_target', 'wrong_width',
    'wrong_direction', 'unknown_width', 'required', 'fixed', 'no_delegation', 'wrong_top',
    'wrong_schema', 'unknown_field', 'bad_quote', 'duplicate_name', 'duplicate_json_key',
    'corrupt_json', 'malformed_roster', 'malformed_port', 'duplicate_doc_port'])
def test_authored_interface_invalid_input_never_changes_owned_metadata(tmp_path, monkeypatch, control):
    project, match, rel, contract = _interface_fixture(tmp_path, monkeypatch)
    l9 = project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    doc = project/'input/docs/L3_external_interface.md'
    model = json.loads(l9.read_text())
    if control == 'subset': contract['renamed_interfaces'][0]['rtl'].pop()
    elif control == 'unknown_source': contract['renamed_interfaces'][0]['l9'] = ['o_memory_missing']
    elif control == 'unknown_target': contract['renamed_interfaces'][0]['rtl'].append('o_memory_missing')
    elif control == 'wrong_width': model['top_ports'][1]['width'] = 3
    elif control == 'wrong_direction': model['top_ports'][1]['direction'] = 'input'
    elif control == 'unknown_width': model['top_ports'][1].pop('width')
    elif control == 'required': model['top_ports'][1]['required'] = True
    elif control == 'fixed': doc.write_text(doc.read_text().replace('address (typical)', 'mandatory fixed name o_memory_addr'))
    elif control == 'no_delegation': doc.write_text(doc.read_text().replace('illustrative', 'concrete').replace('(typical)', ''))
    elif control == 'wrong_top': contract['top_module'] = 'another_top'
    elif control == 'wrong_schema': contract['schema'] = 'arbitrary'
    elif control == 'unknown_field': contract['derived_pad_pairs'] = contract['renamed_interfaces']
    elif control == 'bad_quote': contract['input_obligations'][0]['quote'] = 'invented authority'
    elif control == 'duplicate_name': contract['renamed_interfaces'][0]['rtl'].append('o_memory_raddr')
    elif control == 'malformed_roster': model['ports'] = []
    elif control == 'malformed_port': model['top_ports'].append('invalid port')
    elif control == 'duplicate_doc_port': model['top_ports'].append(dict(model['top_ports'][1]))
    _json(l9, model)
    _json(project/rel, contract)
    if control == 'duplicate_json_key':
        path = project/rel; path.write_text(path.read_text().replace('"actor":', '"actor": "other", "actor":'))
    elif control == 'corrupt_json': (project/rel).write_text('{invalid JSON')
    before = _authored_metadata_bytes(project)
    with pytest.raises((ValueError, OSError)):
        _publish_interface(project, match, rel)
    assert _authored_metadata_bytes(project) == before


@pytest.mark.parametrize('change', ['contract', 'input_authority', 'selected_width'])
def test_authored_interface_ordinary_source_consumer_rechecks_authority(tmp_path, monkeypatch, change):
    project, match, rel, _ = _interface_fixture(tmp_path, monkeypatch)
    assert _publish_interface(project, match, rel)['status'] == pull.PIN_VERIFIED
    if change == 'contract': (project/rel).write_bytes((project/rel).read_bytes() + b'\n')
    elif change == 'input_authority':
        doc = project/'input/docs/L3_external_interface.md'
        doc.write_text(doc.read_text().replace('illustrative', 'concrete').replace('(typical)', ''))
    else:
        source = project/'phase2/stage1/rtl/top_wrapper.v'
        source.write_text(source.read_text().replace('[3:0]', '[2:0]'))
    manifest = json.loads((project/'phase2/stage1/rtl/SOURCE_MANIFEST.json').read_text())
    before = _authored_metadata_bytes(project)
    state, why = pull.verify_existing_reused_pins_outcome(project, [match], manifest)
    assert state == pull.PIN_MISMATCH and 'AUTHORED_INTERFACE_REFUSED' in why
    assert _authored_metadata_bytes(project) == before


@pytest.mark.parametrize('rel', ['', 'plugin_input//interface.json',
                                  'plugin_input/./interface.json', 'input/docs/L3_external_interface.md'])
def test_authored_interface_noncanonical_or_empty_path_never_publishes(tmp_path, monkeypatch, rel):
    project, match, _, _ = _interface_fixture(tmp_path, monkeypatch)
    before = _authored_metadata_bytes(project)
    with pytest.raises(ValueError):
        _publish_interface(project, match, rel)
    assert _authored_metadata_bytes(project) == before


def test_authored_interface_cli_uses_same_real_producer_and_consumer(tmp_path, monkeypatch, capsys):
    project, _, rel, _ = _interface_fixture(tmp_path, monkeypatch)
    assert pull.main([str(project), '--authored-glue', 'top_wrapper.v',
                      '--authored-interface', rel]) == 0
    capsys.readouterr()
    _assert_selected_interface_accepts(project)


@pytest.mark.parametrize('order', ['glue_then_derivative', 'derivative_then_glue'])
def test_authored_interface_native_two_orders_close_current_manifest_ledger(public_mapper_project, order):
    project, match, _ = public_mapper_project
    pull.pull_all_catalog_matches(project, [match], official_only=True,
                                  apply_corrections=order == 'derivative_then_glue')
    previous = (project/'provenance.jsonl').read_bytes()
    previous_ref = json.loads((project/'phase2/stage1/rtl/SOURCE_MANIFEST.json').read_text()).get('local_derivative')
    rel, contract = _prepare_interface_inputs(project)
    assert _publish_interface(project, match, rel)['status'] == pull.PIN_VERIFIED
    if order == 'glue_then_derivative':
        outcome = pull.adopt_catalog_local_correction(project, [match])
        assert outcome['status'] == pull.PIN_VERIFIED, outcome
    _assert_selected_interface_accepts(project)
    manifest_path = project/'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['renamed_interfaces'] == contract['renamed_interfaces']
    record = json.loads((project/manifest['local_derivative']['path']).read_text())
    if previous_ref:
        assert record['previous_local_derivative'] == previous_ref
    for name in ('parent_red', 'candidate_green'):
        receipt = json.loads((project/record['proof'][name]['path']).read_text())
        assert receipt['rtl']['top_wrapper.v'] == _h(manifest_path.parent/'top_wrapper.v')
        assert len(receipt['native_measurements']['case_rows']) == 12
        assert all('top_wrapper.v' in row['compile_argv'] for row in receipt['native_measurements']['case_rows'])
    assert (project/'provenance.jsonl').read_bytes().startswith(previous)
    assert pull.verify_existing_reused_pins_outcome(project, [match], manifest)[0] == pull.PIN_VERIFIED
    before_repeat = _authored_metadata_bytes(project)
    again = _publish_interface(project, match, rel)
    assert again['status'] == pull.PIN_VERIFIED and again['already_current'] and again['outputs'] == {}
    assert _authored_metadata_bytes(project) == before_repeat
    assert pull.verify_existing_reused_pins_outcome(project, [match], manifest)[0] == pull.PIN_VERIFIED
    from test_local_derivative_written_output_provenance import _gate
    result, report = _gate(project, 'interface-' + order)
    assert result.returncode == 0 and report['verdict'] == 'PASS', result.stdout + result.stderr
    positive = project.parent/('positive-interface-' + order)
    shutil.copytree(project, positive)
    assert (positive/'phase2/stage1/rtl/SOURCE_MANIFEST.json').read_bytes() == manifest_path.read_bytes()
    # A native negative uses the same actual writer/consumer ledger, with no
    # test-owned repaired hash. The latest real manifest binding must bite.
    manifest_path.write_bytes(manifest_path.read_bytes() + b'\n')
    result, report = _gate(project, 'interface-drift-' + order)
    assert result.returncode == 1 and report['verdict'] == 'FAIL', result.stdout + result.stderr
    assert any(row['rule'] == 'PROVENANCE_HASH_MISMATCH' and 'SOURCE_MANIFEST.json' in row['detail']
               for row in report['findings'])
    corrupted = _authored_metadata_bytes(project)
    with pytest.raises(ValueError, match='current native derivative manifest binding'):
        _publish_interface(project, match, rel)
    assert _authored_metadata_bytes(project) == corrupted


def test_authored_interface_bad_input_blocks_before_native_derivative_successor(public_mapper_project):
    project, match, _ = public_mapper_project
    pull.pull_all_catalog_matches(project, [match], official_only=True)
    rel, contract = _prepare_interface_inputs(project)
    contract['renamed_interfaces'][0]['rtl'].pop()
    _json(project/rel, contract)
    before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='do not cover'):
        _publish_interface(project, match, rel)
    assert {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()} == before


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
           'exit_code':0,'outputs':{'phase2/stage1/rtl/leaf.v':'sha256:'+record['current_inventory']['leaf.v'],
                                  'phase2/stage1/rtl/SOURCE_MANIFEST.json':'sha256:'+_h(mf_path)},
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
        'phase2/stage1/rtl/leaf.v': 'sha256:'+_h(project/'phase2/stage1/rtl/leaf.v'),
        'phase2/stage1/rtl/SOURCE_MANIFEST.json': 'sha256:'+_h(project/'phase2/stage1/rtl/SOURCE_MANIFEST.json')}
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


# Public #3096 fixture: only the verbatim neutral direct-module TB and public
# source are used. Local git transport supplies controlled official ancestors;
# native Icarus executes the real mapper. This is not a whole CPU/IC proof.
@pytest.fixture
def public_mapper_project(tmp_path, monkeypatch):
    import os
    import subprocess
    import yaml
    plugin = Path(pull.__file__).resolve().parent.parent
    catalog = plugin / 'ip-catalog/cpu/serv'
    public = os.environ.get('VIBEIC_TEST_PUBLIC_SERV_REPO')
    upstream = tmp_path / 'serv'
    if public:
        shutil.copytree(public, upstream)
    else:
        subprocess.run(['git', 'clone', '-q', 'https://github.com/olofk/serv',
                        str(upstream)], check=True, timeout=120)
    # A local source transport fixture with genuine pinned public git objects.
    # Its origin is disclosed as local; it does not pretend to refetch GitHub.
    manifest = yaml.safe_load((catalog / 'manifest.yaml').read_text())
    manifest['canonical_url'] = str(upstream)
    manifest['local_derivative'] = 'local_derivatives/wb_read_owner.json'
    manifest['_category'] = 'cpu'
    registered = tmp_path / 'catalog/serv'
    registered.mkdir(parents=True)
    shutil.copytree(catalog / 'local_derivatives', registered / 'local_derivatives')
    manifest['_manifest_path'] = str(registered / 'manifest.yaml')
    (registered / 'manifest.yaml').write_text(yaml.safe_dump(manifest))
    match = query._manifest_to_match(manifest, 'declared public source component', 1.0)
    monkeypatch.setattr(query, 'query_catalog', lambda *a, **kw: [match])
    monkeypatch.setattr(pull, 'query_catalog', lambda *a, **kw: [match])
    monkeypatch.setattr(pull, 'CACHE_ROOT', tmp_path / 'cache')
    project = _project(tmp_path, 'Reuse SERV from neutral:serv:servile:1.4.0.')
    path = project / 'input/docs/L2_FRS.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('Reuse SERV from neutral:serv:servile:1.4.0.\n'
                    'Shared byte SRAM registers its address for one clock edge; '
                    'read return is asynchronous. RF priority may pause WB bytes.\n')
    return project, match, registered


def _mapper_native(project, registered, name, parameters):
    import subprocess
    work = project / 'mapper_native' / name
    work.mkdir(parents=True)
    tb = registered / 'local_derivatives/mapper_direct_tb.sv'
    mapper = project / 'phase2/stage1/rtl/servile_rf_mem_if.v'
    binary = work / 'challenge.vvp'
    argv = ['iverilog', '-g2012', '-s', 'mapper_direct_tb',
            *[f'-Pmapper_direct_tb.{key}={value}' for key, value in parameters.items()],
            '-o', str(binary), str(tb), str(mapper)]
    cc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert cc.returncode == 0, cc.stdout + cc.stderr
    run = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, timeout=30)
    _json(work / 'observed.json', {'compile_argv': argv, 'compile_rc': cc.returncode,
                                 'native_rc': run.returncode, 'stdout': run.stdout,
                                 'stderr': run.stderr, 'tb_sha256': _h(tb),
                                 'mapper_sha256': _h(mapper), 'vvp_sha256': _h(binary)})
    return run


@pytest.mark.parametrize('case,parameters,want', [
    *[(f'case{i}', {'CASE_ID': i, 'RF_REGS': 36}, 0) for i in range(8)],
    ('rf32_contiguous', {'CASE_ID': 0, 'RF_REGS': 32}, 0),
    ('rf32_x0', {'CASE_ID': 7, 'RF_REGS': 32}, 0),
    ('corrupt_return', {'CASE_ID': 0, 'RF_REGS': 36, 'CORRUPT_RETURN': 1}, 1),
    ('suppress_pause', {'CASE_ID': 1, 'RF_REGS': 36, 'SUPPRESS_PAUSE': 1}, 1),
])
def test_catalog_mapper_preserves_public_byte_sram_contract(public_mapper_project,
                                                           case, parameters, want):
    project, match, registered = public_mapper_project
    # The actual unchanged public challenge runs on the producer's output;
    # old source produces the four wrong words rather than a missing-API error.
    audit = pull.pull_all_catalog_matches(project, [match], official_only=True)
    run = _mapper_native(project, registered, case, parameters)
    assert run.returncode == want, run.stdout + run.stderr
    if want == 0:
        assert 'MAPPER_DIRECT_PASS' in run.stdout
    elif case == 'corrupt_return':
        assert 'WHOLE_WORD_VALUE' in run.stdout
    else:
        assert 'CHALLENGE_NOT_TRIGGERED' in run.stdout


def test_registered_mapper_reaches_ordinary_step1_and_strict_consumer(public_mapper_project):
    project, match, registered = public_mapper_project
    result = runner.step_rtl_gen(project, 'processor_cpu')
    run = _mapper_native(project, registered, 'current_component', {'CASE_ID': 4, 'RF_REGS': 36})
    assert run.returncode == 0, run.stdout + run.stderr
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['ip_fetch']['reuse_kind'] == 'LOCAL_DERIVATIVE'
    manifest = json.loads((project / 'phase2/stage1/rtl/SOURCE_MANIFEST.json').read_text())
    record = json.loads((project / manifest['local_derivative']['path']).read_text())
    assert len(record['current_inventory']) == 22
    event = json.loads((project / 'provenance.jsonl').read_text().splitlines()[-1])
    assert event['official_unmodified_files'] == 21
    assert event['locally_adapted_reused_files'] == 1
    assert pull.verify_existing_reused_pins_outcome(project, [match], manifest)[0] == pull.PIN_VERIFIED
    assert pull.verify_existing_official_pins_outcome(project, [match], manifest)[0] == pull.PIN_MISMATCH


def test_registered_mapper_repeat_preserves_current_choice_and_parent_history(public_mapper_project):
    project, match, registered = public_mapper_project
    first = pull.pull_all_catalog_matches(project, [match], official_only=True)
    run = _mapper_native(project, registered, 'first', {'CASE_ID': 1, 'RF_REGS': 36})
    assert run.returncode == 0, run.stdout + run.stderr
    mf = project / 'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    before_manifest = mf.read_bytes()
    before_history = (project / 'provenance.jsonl').read_bytes()
    before_inventory = {p.name: p.read_bytes() for p in mf.parent.iterdir()}
    # The ordinary CLI reaches the same current derivative producer; it must
    # preserve the source choice and history already measured above.
    assert pull.main([str(project)]) == 0
    again = pull.pull_all_catalog_matches(project, [match], official_only=True)
    assert again['catalog_correction']['status'] == pull.PIN_VERIFIED
    assert mf.read_bytes() == before_manifest
    assert (project / 'provenance.jsonl').read_bytes() == before_history
    assert {p.name: p.read_bytes() for p in mf.parent.iterdir()} == before_inventory
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert mf.read_bytes() == before_manifest
    assert (project / 'provenance.jsonl').read_bytes() == before_history


@pytest.mark.parametrize('mutation', ['missing_green', 'wrong_inventory', 'failed_native'])
def test_registered_mapper_missing_or_failed_proof_cannot_admit(public_mapper_project, mutation):
    project, match, registered = public_mapper_project
    data = registered / 'local_derivatives'
    if mutation == 'missing_green':
        (data / 'candidate-green.json').unlink()
    elif mutation == 'wrong_inventory':
        recipe = json.loads((data / 'wb_read_owner.json').read_text())
        recipe['current_inventory'].pop('serv_alu.v')
        _json(data / 'wb_read_owner.json', recipe)
    else:
        receipt = json.loads((data / 'candidate-green.json').read_text())
        receipt['results'][1]['rc'] = 1
        _json(data / 'candidate-green.json', receipt)
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status in ('FAIL', 'NOT_MEASURED'), result.detail
    # A failing held Step1 may roll back the complete new source transaction.
    # If it publishes a deferred official parent, it must stay unmodified.
    mapper = project / 'phase2/stage1/rtl/servile_rf_mem_if.v'
    if mapper.is_file():
        assert _h(mapper) == '6829a9a568b00df2c4905b35a916c14dd747538ad1091c3852ebf43cfded408d'
    else:
        assert not (project / 'phase2/stage1/rtl/SOURCE_MANIFEST.json').exists()


def test_registered_mapper_current_drift_stays_measured_failure(public_mapper_project):
    project, match, registered = public_mapper_project
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    mapper = project / 'phase2/stage1/rtl/servile_rf_mem_if.v'
    mapper.write_text(mapper.read_text() + '\n// undeclared current source drift\n')
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'FAIL', result.detail



def _publish_mapper_glue(project, match):
    path = project / 'phase2/stage1/rtl/top_wrapper.v'
    path.write_text('module top_wrapper; wire declared_glue = 1\'b0; endmodule\n')
    try:
        return pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    except ValueError as exc:
        # A refusal from the owning source API is the observed counterexample,
        # not a fixture setup error or a missing-new-method exception.
        return {'status': pull.PIN_MISMATCH, 'reason': str(exc)}


def test_registered_mapper_accepts_previously_published_official_glue(public_mapper_project):
    import inspect
    project, match, registered = public_mapper_project
    optional = ({'apply_corrections': False}
                if 'apply_corrections' in inspect.signature(pull.pull_all_catalog_matches).parameters else {})
    pull.pull_all_catalog_matches(project, [match], official_only=True, **optional)
    glue = _publish_mapper_glue(project, match)
    assert glue['status'] == pull.PIN_VERIFIED, glue
    previous = (project / 'provenance.jsonl').read_bytes()
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['ip_fetch'].get('reuse_kind') == 'LOCAL_DERIVATIVE'
    assert (project / 'provenance.jsonl').read_bytes().startswith(previous)
    manifest = json.loads((project / 'phase2/stage1/rtl/SOURCE_MANIFEST.json').read_text())
    record = json.loads((project / manifest['local_derivative']['path']).read_text())
    assert len(record['current_inventory']) == 23
    assert len(pull._local_inventory(project / record['parent_project'] / 'phase2/stage1/rtl')) == 22
    assert pull.verify_existing_reused_pins_outcome(project, [match], manifest)[0] == pull.PIN_VERIFIED
    run = _mapper_native(project, registered, 'prior_glue', {'CASE_ID': 4, 'RF_REGS': 36})
    assert run.returncode == 0, run.stdout + run.stderr


def test_registered_mapper_publishes_glue_after_automatic_correction(public_mapper_project):
    project, match, registered = public_mapper_project
    pull.pull_all_catalog_matches(project, [match], official_only=True)
    mf = project / 'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    first_manifest = json.loads(mf.read_text())
    first_record = first_manifest.get('local_derivative')
    previous = (project / 'provenance.jsonl').read_bytes()
    glue = _publish_mapper_glue(project, match)
    assert glue['status'] == pull.PIN_VERIFIED, glue
    manifest = json.loads(mf.read_text())
    assert manifest.get('local_derivative') and manifest['local_derivative'] != first_record
    assert (project / first_record['path']).is_file()
    assert (project / 'provenance.jsonl').read_bytes().startswith(previous)
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    record = json.loads((project / manifest['local_derivative']['path']).read_text())
    assert len(record['current_inventory']) == 23
    for name in ['parent_red', 'candidate_green']:
        receipt = json.loads((project / record['proof'][name]['path']).read_text())
        assert receipt['rtl']['top_wrapper.v'] == _h(mf.parent / 'top_wrapper.v')
        assert all('top_wrapper.v' in r['compile_argv'] for r in receipt['native_measurements']['case_rows'])
    before = _authored_metadata_bytes(project)
    again = pull.emit_authored_glue_inventory(project, [match], ['top_wrapper.v'])
    assert again['already_current'] and _authored_metadata_bytes(project) == before
    run = _mapper_native(project, registered, 'after_glue', {'CASE_ID': 2, 'RF_REGS': 36})
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize('mutation', ['undeclared_extra', 'changed_reused'])
def test_registered_mapper_glue_cannot_hide_other_source_drift(public_mapper_project, mutation):
    project, match, registered = public_mapper_project
    pull.pull_all_catalog_matches(project, [match], official_only=True)
    rtl = project / 'phase2/stage1/rtl'
    if mutation == 'undeclared_extra':
        (rtl / 'unnamed_extra.v').write_text('module unnamed_extra; endmodule\n')
    else:
        (rtl / 'serv_alu.v').write_text((rtl / 'serv_alu.v').read_text() + '\n// drift\n')
    before = _authored_metadata_bytes(project)
    result = _publish_mapper_glue(project, match)
    assert result['status'] != pull.PIN_VERIFIED
    assert _authored_metadata_bytes(project) == before
