"""Selected CPU ISA responsibilities stay instruction tests, with no fabricated vectors."""
import json
import pytest
import phase1_doc_one_shot_runner as runner


def emit(project, class_path, isa, no_wake=True):
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    l1 = {'class_path': class_path}
    if isa:
        l1['isa_base'] = ['RV32I']
    (docs / 'L1_DATASHEET.json').write_text(json.dumps(l1))
    l3 = {'opcode_synthesis_skipped_reason': 'source HDL instruction enum' if no_wake else None,
        'opcodes': [{'name':'OP_ALPHA', 'hex':'0x13', 'width_bits':7},
                    {'name':'OP_BETA', 'hex':'0x33', 'width_bits':7}]}
    runner.gen_l10_test_cases(project, {'spec.md':'Selected implementation executes the declared ISA through its instruction interface.'}, l3)
    return json.loads((docs / 'L10_TEST_CASES.json').read_text())['test_cases']


def test_selected_cpu_isa_cases_keep_identity_and_architectural_obligations(tmp_path):
    cases = emit(tmp_path, 'processor_cpu', True)
    assert [c['name'] for c in cases] == ['send_op_alpha_happy','send_op_beta_happy']
    assert [c['opcode_hex'] for c in cases] == ['0x13','0x33']
    assert all(c['evidence'] == 'L3.opcodes' for c in cases)
    assert all(c['kind'] == 'functional_vector' for c in cases)
    assert all('instruction interface' in c['stimulus'] for c in cases)
    assert all('architectural' in c['expected'] for c in cases)
    assert all('host sends' not in c['stimulus'] and 'response_payload' not in c['expected'] for c in cases)


@pytest.mark.parametrize('class_path,isa,no_wake', [('uart',True,True),('processor_cpu',False,True),('processor_cpu',True,False)])
def test_other_protocols_and_missing_isa_facts_keep_existing_scope(tmp_path, class_path, isa, no_wake):
    cases = emit(tmp_path, class_path, isa, no_wake)
    happy = [c for c in cases if c['name'].endswith('_happy')]
    assert len(happy) == 2
    assert all(c['kind'] == 'happy_path' for c in happy)
    assert all(c['stimulus'].startswith('host sends') for c in happy)
