import copy
import hashlib
import json

import pytest

import flow109_metric_acceptance as metrics
import ic_expert_backup_pack as pack
import phase1_base_requirements as producer
import phase1_expert_parse_track as expert
from test_flow109_phase1_metric_completion import approve, case


SCHEMA = 'vibeic.phase1.base-requirements-source.v1'
ORIGINAL = 'The ready output preserves the source contract.\n'


def source_case(project):
    (project / 'input/docs').mkdir(parents=True)
    original = project / 'input/docs/spec.md'
    original.write_text(ORIGINAL)
    reference = {'path': 'input/docs/spec.md',
                 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}
    expectation = {'id': 'derived-ready', 'layer': 'L1_DATASHEET',
        'field_path': '/description', 'requirement': 'DERIVED_EXPECTATION_ONLY',
        'expected_tokens': ['ready'],
        'evidence': [f"input/docs/spec.md:1 sha256:{reference['sha256']} - The ready output"]}
    common = {'required_items': [{'id': 'derived-ready'}],
              'source_documents': [reference], 'expectations': [expectation]}
    return {'schema': SCHEMA,
        'requirements_trace': {**copy.deepcopy(common), 'features': [{
            'feature': 'soft_ip', 'declared': True, 'layer': 'L1_DATASHEET',
            'field_path': '/soft_ip', 'evidence': expectation['evidence']}]},
        'endpoint_delivery_items': {**copy.deepcopy(common), 'assignments': [{
            'id': 'derived-ready', 'endpoint': 'RTL', 'layer': 'L1_DATASHEET',
            'field_path': '/description'}]}}


def write_source(project, payload):
    source = project / producer.SOURCE
    raw = (json.dumps(payload, indent=2) + '\r\n').encode()
    source.write_bytes(raw)
    return source, raw


def frame(project):
    report = expert.input_text_report(project)
    rendered, binding = pack.phase1_frame(report['text'], report['source_frame'])
    return report, rendered, binding


def test_declared_derived_population_is_context_and_retains_exact_reading(tmp_path):
    payload = source_case(tmp_path)
    source, raw = write_source(tmp_path, payload)
    report, rendered, _ = frame(tmp_path)
    member = next(m for m in report['source_frame']['members']
                  if m['path'] == 'base_requirements_candidates.json')
    assert report['text'] == ORIGINAL
    assert member['semantic_text'] == ''
    assert member['qualification_context'] == payload
    assert member['responsibility'] == 'supported-consumer-context-with-remaining-possible-requirements'
    assert member['sha256'] == hashlib.sha256(raw).hexdigest()
    assert member['bytes'] == len(raw)
    assert member['text'] == raw.decode().replace('\r\n', '\n')
    assert source.read_bytes() == raw
    semantic, retained = rendered.split('# Retained original reading', 1)
    assert 'DERIVED_EXPECTATION_ONLY' not in semantic
    assert 'DERIVED_EXPECTATION_ONLY' in retained
    assert ORIGINAL in semantic and ORIGINAL in retained


def test_adding_or_updating_declared_derived_source_preserves_semantic_binding(tmp_path):
    payload = source_case(tmp_path)
    before, _, first = frame(tmp_path)
    source, _ = write_source(tmp_path, payload)
    after, _, second = frame(tmp_path)
    assert second == first
    assert after['source_frame'] != before['source_frame']
    payload['requirements_trace']['expectations'][0]['requirement'] = 'UPDATED_DERIVED_REVIEW'
    source.write_text(json.dumps(payload))
    updated, _, third = frame(tmp_path)
    assert third == first
    assert updated['source_frame'] != after['source_frame']
    original = tmp_path / 'input/docs/spec.md'
    original.write_text(ORIGINAL + 'A new original obligation.\n')
    changed, _, fourth = frame(tmp_path)
    assert fourth != first
    assert 'A new original obligation.' in changed['text']


def test_existing_expert_handoff_consumes_same_answer_after_derived_output(tmp_path):
    payload = source_case(tmp_path)
    before = expert.input_text_report(tmp_path)
    out = tmp_path / 'pack'
    initial = expert.ai_subtrack(tmp_path, before['text'], out,
                                source_frame=before['source_frame'])
    assert initial['status'] == 'HANDOFF_EMITTED'
    answer = out / 'l_doc_expectations.json'
    answer.write_text(json.dumps({'input_frame_sha256': initial['input_frame_sha256'],
        'expectations': [{'id': 'original-ready', 'layer': 'L1_DATASHEET',
                          'field_path': '/description', 'expected_tokens': ['ready']}]}))
    original_answer = answer.read_bytes()
    write_source(tmp_path, payload)
    after = expert.input_text_report(tmp_path)
    resumed = expert.ai_subtrack(tmp_path, after['text'], out,
                                source_frame=after['source_frame'])
    assert resumed['status'] == 'CONSUMED'
    assert resumed['input_frame_sha256'] == initial['input_frame_sha256']
    assert resumed['handoff']['raw_input_frame_sha256'] != initial['handoff']['raw_input_frame_sha256']
    assert answer.read_bytes() == original_answer


def test_descriptor_declares_source_schema_without_approving_population(tmp_path, monkeypatch):
    from test_phase1_requirements_review_handoff import review_case

    result = review_case(tmp_path, monkeypatch)
    descriptor = producer.read_review_action(tmp_path, result['pending_action'])
    assert descriptor['output_contracts'][producer.SOURCE]['schema'] == SCHEMA
    assert not (tmp_path / producer.SOURCE).exists()
    assert not (tmp_path / 'requirements').exists()


@pytest.mark.parametrize('legacy', [False, True], ids=['new-typed', 'existing-untyped'])
def test_physical_publisher_declares_new_sources_and_preserves_legacy_bytes(tmp_path, legacy):
    from test_phase1_base_requirements_publication import owner_case

    owner_case(tmp_path)
    first = producer.publish(tmp_path)
    assert first['status'] == 'PENDING', first
    source = tmp_path / producer.SOURCE
    payload = json.loads(source.read_text())
    assert payload['schema'] == SCHEMA
    if legacy:
        payload.pop('schema')
        raw = json.dumps(payload, separators=(',', ':')).encode() + b'\r\n'
        source.write_bytes(raw)
        reference = {'path': producer.SOURCE, 'sha256': hashlib.sha256(raw).hexdigest()}
        for key, metric in producer.ROWS:
            authority = tmp_path / f'requirements/{key}/{metric}.json'
            record = json.loads(authority.read_text())
            record['approval']['source_reference'] = reference
            authority.write_text(json.dumps(record))
    originals = {p: p.read_bytes() for root in ('input', 'requirements')
                 for p in (tmp_path / root).rglob('*') if p.is_file()}
    second = producer.publish(tmp_path)
    assert second['status'] == 'PENDING', second
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    report = expert.input_text_report(tmp_path)
    member = next(m for m in report['source_frame']['members'] if m['path'] == source.name)
    assert bool(member['semantic_text']) is legacy


def variant_case(project, variant):
    payload = source_case(project)
    layers = project / 'phase1/generated_docs'
    layers.mkdir(parents=True)
    (layers / 'L1_DATASHEET.json').write_text(json.dumps({'description': 'ready'}))
    exp = copy.deepcopy(payload['requirements_trace']['expectations'][0])
    if variant == 'split':
        exp = {k: v for k, v in exp.items() if k in ('id', 'requirement', 'evidence')}
        exp['sub_expectations'] = [
            {'layer': 'L1_DATASHEET', 'field_path': '/description', 'expected_tokens': ['ready']},
            {'layer': 'L1_DATASHEET', 'expected_tokens': ['ready']}]
    elif variant == 'whole-layer':
        exp.pop('field_path')
    elif variant == 'whole-layer-null':
        exp['field_path'] = None
    elif variant == 'withdrawal':
        exp = {k: v for k, v in exp.items() if k in ('id', 'requirement', 'evidence')}
        exp['withdrawn'] = {'reason': 'The independent review withdrew a duplicate.'}
    elif variant == 'qualified-output':
        from _qualified_by_fixture import stage_field

        field = stage_field(project, 'data_o', 'ready_o')
        ports = [{'name': 'data_o', 'direction': 'output', 'width': 8, 'qualified_by': field},
                 {'name': 'ready_o', 'direction': 'output', 'width': 1}]
        (layers / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
            key: ports for key in ('ports', 'top_ports', 'top_module_pins')}))
        exp.update(id='qualified_by:data_o', layer='L9_INTEGRATION_SPEC', field_path='top_ports',
            qualified_by={'output': 'data_o', 'port': 'ready_o', 'active_level': 'high'},
            basis=field['basis'], expected_tokens=['data_o', 'ready_o', 'high'])
    for metric in ('requirements_trace', 'endpoint_delivery_items'):
        payload[metric]['expectations'] = [copy.deepcopy(exp)]
        payload[metric]['required_items'] = [{'id': exp['id']}]
    return payload, exp


@pytest.mark.parametrize('variant', ['split', 'whole-layer', 'whole-layer-null', 'qualified-output'])
def test_established_native_expectation_variants_are_derived_context(tmp_path, variant):
    payload, exp = variant_case(tmp_path, variant)
    compared = expert.converge_ai_expectation(tmp_path, exp)
    assert compared['usable'] is True and compared['met'] is True, compared
    before, _, first = frame(tmp_path)
    write_source(tmp_path, payload)
    after, _, second = frame(tmp_path)
    assert after['text'] == before['text']
    assert second == first


@pytest.mark.parametrize('variant,location', [
    ('split', ('sub_expectations', 1)),
    ('qualified-output', ('qualified_by',)),
    ('qualified-output', ('basis', 0)),
], ids=['split-branch', 'qualified-relation', 'qualified-basis'])
def test_native_variant_nested_extensions_stay_semantic(tmp_path, variant, location):
    payload, _ = variant_case(tmp_path, variant)
    record = payload['requirements_trace']['expectations'][0]
    for key in location:
        record = record[key]
    record['extension'] = {'requirement': 'PRESERVE_VARIANT_EXTENSION'}
    source, _ = write_source(tmp_path, payload)
    report, _, first = frame(tmp_path)
    assert 'PRESERVE_VARIANT_EXTENSION' in report['text']
    assert 'DERIVED_EXPECTATION_ONLY' not in report['text']
    record['extension']['requirement'] = 'CHANGED_VARIANT_EXTENSION'
    source.write_text(json.dumps(payload))
    changed, _, second = frame(tmp_path)
    assert 'CHANGED_VARIANT_EXTENSION' in changed['text']
    assert second != first


def test_native_withdrawal_is_context_and_keeps_nested_extensions(tmp_path):
    payload, exp = variant_case(tmp_path, 'withdrawal')
    compared = expert.converge_ai_expectation(tmp_path, exp)
    assert compared['usable'] is False
    assert compared['withdrawn_reason'] == exp['withdrawn']['reason']
    before, _, first = frame(tmp_path)
    source, _ = write_source(tmp_path, payload)
    after, _, second = frame(tmp_path)
    assert after['text'] == before['text']
    assert second == first
    payload['requirements_trace']['expectations'][0]['withdrawn']['extension'] = {
        'requirement': 'PRESERVE_WITHDRAWAL_EXTENSION'}
    source.write_text(json.dumps(payload))
    extended, _, third = frame(tmp_path)
    assert 'PRESERVE_WITHDRAWAL_EXTENSION' in extended['text']
    assert 'DERIVED_EXPECTATION_ONLY' not in extended['text']
    assert third != first


@pytest.mark.parametrize('variant,field,value', [
    ('split', 'expected_tokens', []), ('split', 'layer', None),
    ('split', 'field_path', None), ('qualified-output', 'expected_tokens', []),
    ('whole-layer', 'expert_source', None), ('whole-layer', 'requirement', None),
    ('withdrawal', 'expected_tokens', []),
])
def test_transport_null_or_empty_metadata_does_not_decide_native_validity(tmp_path, variant, field, value):
    payload, exp = variant_case(tmp_path, variant)
    exp[field] = value
    for metric in ('requirements_trace', 'endpoint_delivery_items'):
        payload[metric]['expectations'] = [copy.deepcopy(exp)]
    compared = expert.converge_ai_expectation(tmp_path, exp)
    if variant == 'withdrawal':
        assert compared['usable'] is False and compared['withdrawn_reason']
    else:
        assert compared['usable'] is True and compared['met'] is True, compared
    before, _, first = frame(tmp_path)
    write_source(tmp_path, payload)
    after, _, second = frame(tmp_path)
    assert after['text'] == before['text']
    assert second == first


@pytest.mark.parametrize('damage', [
    'empty-split', 'ambiguous-split', 'branch-without-tokens',
    'empty-tokens', 'absent-layer',
])
def test_native_invalid_typed_records_remain_context_and_native_refused(tmp_path, damage):
    payload, exp = variant_case(tmp_path, 'split' if damage != 'absent-layer' else 'whole-layer')
    if damage == 'empty-split':
        exp['sub_expectations'] = []
    elif damage == 'ambiguous-split':
        exp['expected_tokens'] = ['PRESERVE_MALFORMED']
    elif damage == 'branch-without-tokens':
        exp['sub_expectations'][0].pop('expected_tokens')
    elif damage == 'empty-tokens':
        exp['sub_expectations'][0]['expected_tokens'] = []
    elif damage == 'absent-layer':
        exp.pop('layer')
    for metric in ('requirements_trace', 'endpoint_delivery_items'):
        payload[metric]['expectations'] = [copy.deepcopy(exp)]
    compared = expert.converge_ai_expectation(tmp_path, exp)
    assert compared['usable'] is False, compared
    before, _, first = frame(tmp_path)
    write_source(tmp_path, payload)
    after, _, second = frame(tmp_path)
    assert after['text'] == before['text']
    assert second == first
    assert expert.converge_ai_expectation(tmp_path, exp) == compared


@pytest.mark.parametrize('declared', [True, False], ids=['typed', 'unknown-schema'])
def test_deep_unsupported_split_content_stays_readable_and_semantic(tmp_path, declared):
    payload = source_case(tmp_path)
    row = {'layer': 'L1_DATASHEET', 'expected_tokens': ['ready'],
           'extension': {'requirement': 'PRESERVE_DEEP_UNSUPPORTED_FACT'}}
    for _ in range(180):
        row = {'sub_expectations': [row]}
    row.update(id='derived-ready', evidence=payload['requirements_trace']['expectations'][0]['evidence'])
    for metric in ('requirements_trace', 'endpoint_delivery_items'):
        payload[metric]['expectations'] = [row]
    if not declared:
        payload['schema'] += '.unknown'
    source = tmp_path / producer.SOURCE
    raw = json.dumps(payload, separators=(',', ':')).encode()
    assert len(raw) < expert._INPUT_TEXT_CAP
    source.write_bytes(raw)
    assert json.loads(raw)['schema'] == payload['schema']
    compared = expert.converge_ai_expectation(tmp_path, row)
    assert compared['usable'] is False
    report = expert.input_text_report(tmp_path)
    assert report['status'] == 'READ'
    member = next(m for m in report['source_frame']['members'] if m['path'] == source.name)
    assert 'PRESERVE_DEEP_UNSUPPORTED_FACT' in member['semantic_text']
    assert member['sha256'] == hashlib.sha256(raw).hexdigest()
    semantic = json.loads(member['semantic_text'])
    assert semantic['requirements_trace']['expectations'][0]['sub_expectations'][0]['sub_expectations'] == row['sub_expectations'][0]['sub_expectations']
    if not declared:
        assert member['semantic_text'] == source.read_text()


@pytest.mark.parametrize('variant,location', [
    ('split', ('sub_expectations',)),
    ('qualified-output', ('qualified_by', 'active_level')),
    ('qualified-output', ('basis', 0, 'line')),
    ('whole-layer', ('expected_tokens',)), ('whole-layer', ('requirement',)),
    ('whole-layer', ('layer',)),
], ids=['split-container', 'qualifier-field', 'citation-field', 'token-container', 'prose-field', 'layer-field'])
def test_malformed_structured_fields_stay_semantic_at_their_paths(tmp_path, variant, location):
    payload, _ = variant_case(tmp_path, variant)
    record = payload['requirements_trace']['expectations'][0]
    for key in location[:-1]:
        record = record[key]
    malformed = {'requirement': 'PRESERVE_MALFORMED_FACT'}
    record[location[-1]] = malformed
    source, _ = write_source(tmp_path, payload)
    report, _, first = frame(tmp_path)
    member = next(m for m in report['source_frame']['members'] if m['path'] == source.name)
    semantic = json.loads(member['semantic_text'])['requirements_trace']['expectations'][0]
    for key in location:
        semantic = semantic[key]
    assert semantic == malformed
    assert 'PRESERVE_MALFORMED_FACT' in report['text']
    malformed['requirement'] = 'CHANGED_MALFORMED_FACT'
    source.write_text(json.dumps(payload))
    changed, _, second = frame(tmp_path)
    assert 'CHANGED_MALFORMED_FACT' in changed['text']
    assert second != first


@pytest.mark.parametrize('field', ['id', 'withdrawn', 'qualified_by', 'basis'])
def test_fields_ignored_by_native_split_child_remain_possible_requirements(tmp_path, field):
    payload, exp = variant_case(tmp_path, 'split')
    extension = {'requirement': 'PRESERVE_IGNORED_BRANCH_FACT'}
    exp['sub_expectations'][1][field] = extension
    compared = expert.converge_ai_expectation(tmp_path, exp)
    assert compared['usable'] is True and compared['met'] is True, compared
    payload['requirements_trace']['expectations'] = [exp]
    source, _ = write_source(tmp_path, payload)
    report, _, first = frame(tmp_path)
    member = next(m for m in report['source_frame']['members'] if m['path'] == source.name)
    semantic = json.loads(member['semantic_text'])
    assert semantic['requirements_trace']['expectations'][0]['sub_expectations'][1][field] == extension
    extension['requirement'] = 'CHANGED_IGNORED_BRANCH_FACT'
    source.write_text(json.dumps(payload))
    changed, _, second = frame(tmp_path)
    assert 'CHANGED_IGNORED_BRANCH_FACT' in changed['text']
    assert second != first


@pytest.mark.parametrize('location', [
    ('requirements_trace', 'features', 0, 'declared'),
    ('endpoint_delivery_items', 'assignments', 0, 'endpoint'),
], ids=['feature-value', 'assignment-value'])
def test_malformed_population_fields_preserve_structured_facts(tmp_path, location):
    payload = source_case(tmp_path)
    record = payload
    for key in location[:-1]:
        record = record[key]
    fact = {'requirement': 'PRESERVE_STRUCTURED_POPULATION_FACT'}
    record[location[-1]] = fact
    source, _ = write_source(tmp_path, payload)
    report, _, _ = frame(tmp_path)
    member = next(m for m in report['source_frame']['members'] if m['path'] == source.name)
    semantic = json.loads(member['semantic_text'])
    for key in location:
        semantic = semantic[key]
    assert semantic == fact


@pytest.mark.parametrize('location', [
    (), ('requirements_trace',), ('requirements_trace', 'required_items', 0),
    ('requirements_trace', 'source_documents', 0),
    ('requirements_trace', 'expectations', 0), ('requirements_trace', 'features', 0),
    ('endpoint_delivery_items', 'assignments', 0),
], ids=['top', 'population', 'required-item', 'source-reference', 'expectation', 'feature', 'assignment'])
def test_unknown_extensions_stay_semantic_and_change_binding(tmp_path, location):
    payload = source_case(tmp_path)
    record = payload
    for key in location:
        record = record[key]
    record['extension'] = {'nested': ['PRESERVE_UNKNOWN_REQUIREMENT']}
    source, _ = write_source(tmp_path, payload)
    report, _, first = frame(tmp_path)
    assert 'PRESERVE_UNKNOWN_REQUIREMENT' in report['text']
    record['extension']['nested'][0] = 'CHANGED_UNKNOWN_REQUIREMENT'
    source.write_text(json.dumps(payload))
    changed, _, second = frame(tmp_path)
    assert 'CHANGED_UNKNOWN_REQUIREMENT' in changed['text']
    assert second != first


@pytest.mark.parametrize('damage', [
    'untagged', 'unknown-schema', 'absent-population', 'invalid-container',
    'invalid-id', 'invalid-reference', 'duplicate-key', 'invalid-json',
])
def test_untagged_or_malformed_payload_stays_entirely_semantic(tmp_path, damage):
    payload = source_case(tmp_path)
    if damage == 'untagged':
        payload.pop('schema')
    elif damage == 'unknown-schema':
        payload['schema'] += '.unknown'
    elif damage == 'absent-population':
        payload.pop('endpoint_delivery_items')
    elif damage == 'invalid-container':
        payload['requirements_trace']['expectations'] = 'PRESERVE_MALFORMED'
    elif damage == 'invalid-id':
        payload['requirements_trace']['required_items'][0]['id'] = {'requirement': 'PRESERVE_MALFORMED'}
    elif damage == 'invalid-reference':
        payload['requirements_trace']['source_documents'][0]['sha256'] = 'PRESERVE_MALFORMED'
    raw = json.dumps(payload)
    if damage == 'duplicate-key':
        raw = raw[:-1] + ', "requirements_trace": {"requirement": "PRESERVE_DUPLICATE"}}'
    elif damage == 'invalid-json':
        raw += ' PRESERVE_UNPARSED'
    source = tmp_path / producer.SOURCE
    source.write_text(raw)
    report, _, _ = frame(tmp_path)
    member = next(m for m in report['source_frame']['members']
                  if m['path'] == source.name)
    assert member['semantic_text'] == raw
    assert member['qualification_context'] == {}
    assert member['responsibility'] == 'unresolved-possible-requirements'


def test_native_population_reads_typed_source_and_still_rejects_changed_bytes(tmp_path, monkeypatch):
    payload, _ = case(tmp_path, monkeypatch)
    payload['schema'] = SCHEMA
    approve(tmp_path, payload)
    for key, metric in producer.ROWS:
        _, actual = metrics._d0102_population(tmp_path, key, metric, {})
        assert actual == payload[metric]
    source = tmp_path / 'input/approved-requirements.json'
    source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(metrics.MetricRefusal, match='METRIC_AUTHORITY_STALE'):
        metrics._d0102_population(tmp_path, 'base_01', 'requirements_trace', {})


def test_derived_role_does_not_accept_native_incomplete_population(tmp_path, monkeypatch):
    payload, _ = case(tmp_path, monkeypatch)
    payload['schema'] = SCHEMA
    payload['requirements_trace']['features'] = []
    approve(tmp_path, payload)
    report = expert.input_text_report(tmp_path)
    member = next(m for m in report['source_frame']['members']
                  if m['path'] == 'approved-requirements.json')
    assert member['semantic_text'] == ''
    with pytest.raises(metrics.MetricRefusal, match='D0102_FEATURE_POPULATION_ABSENT'):
        metrics._d0102_population(tmp_path, 'base_01', 'requirements_trace', {})
