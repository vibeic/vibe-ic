"""The early package row reads documents without starting the native chain."""
import copy
import json
from pathlib import Path

import pytest

import flow_engine as engine
import io_pad_chip_top_gen
import pad_assignment_gen


@pytest.mark.parametrize('code,expected', [(0, 'PASS'), (1, 'FAIL'), (2, 'NOT_MEASURED')])
def test_document_plan_runs_without_native_chain_or_rtl(tmp_path, monkeypatch, code, expected):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {'pdk_target': 'GF180MCUD'}}))
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(tmp_path / 'pdk'))
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError('The document plan cannot initialize the native chain or generate IO RTL')

    def assignment(argv):
        calls.append(argv)
        output = Path(argv[argv.index('--json') + 1])
        output.write_text(json.dumps({'verdict': 'WROTE' if code == 0 else 'REFUSE' if code == 1 else 'NOT_ASKED',
            'reason': 'native assignment result', 'questions_answered': 8 if code == 0 else 3,
            'questions_unanswered': [] if code == 0 else ['physical placement']}))
        return code

    monkeypatch.setattr(engine.NativeChain, 'initialize', forbidden)
    monkeypatch.setattr(io_pad_chip_top_gen, 'main', forbidden)
    monkeypatch.setattr(pad_assignment_gen, 'main', assignment)
    table = copy.deepcopy(engine.read_json(engine.TABLE))
    row = next(row for row in table['steps'] if row['name'] == 'package_load_and_test_interface_feasibility')
    route = {'entry_step': row['name'], 'verify_through': row['name'], 'delivery_target': 'gds',
             'input_contract': 'structured'}
    result = engine.run(tmp_path, table=table, route=route,
                        from_name=row['name'], to_name=row['name'])
    assert len(calls) == 1
    assert calls[0][calls[0].index('--pdk') + 1] == 'gf180mcuD'
    assert calls[0][calls[0].index('--pdk-root') + 1] == str(tmp_path / 'pdk')
    assert result['steps'][0]['status'] == expected
    assert not (tmp_path / 'phase2/stage1/rtl').exists()
    assert not (tmp_path / 'reports/phase3/io_pad_chip_top.json').exists()
