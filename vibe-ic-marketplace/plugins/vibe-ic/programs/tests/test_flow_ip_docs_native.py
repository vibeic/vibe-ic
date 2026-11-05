from pathlib import Path

import pytest

pytest.importorskip('librelane')

import _release_kit as kit_fixture
from _release_docs_contract import IP_DOCS, MANIFEST_NAME, doc_dir
import flow_native_adapters as adapters
import flow_engine as engine
import ip_release_docs_gen as generator
import release_docs_check as checker


from librelane.state import State


def native_release(tmp_path, monkeypatch):
    monkeypatch.setattr(kit_fixture, '_write_current_kit', lambda *args: None)
    project = kit_fixture.build_project(tmp_path / 'project', packages=(kit_fixture.SUBJECT,))
    name = kit_fixture.SUBJECT
    source = project / 'phase3/stage4/hardmacro'
    state = {key: str(source / (name + extension)) for key, extension in
                           {'lef': '.lef', 'gds': '.gds', 'nl': '.v'}.items()}
    state['lib'] = {'nominal': str(source / (name + '.lib'))}
    tool = {'adapter': 'ip_release_docs', 'destination': 'phase3/stage4/exported',
            'formats': {'lef': '.lef', 'lib': '.lib', 'gds': '.gds', 'nl': '.v'}}
    return project, name, State.load(state), tool


def test_current_views_produce_documents_without_old_records(tmp_path, monkeypatch):
    project, name, state, tool = native_release(tmp_path, monkeypatch)

    def obsolete(*args, **kwargs):
        raise AssertionError('Release documents do not require tree or digest records.')

    monkeypatch.setattr(generator, 'tree_sha', obsolete, raising=False)
    monkeypatch.setattr(generator, 'sha256_of', obsolete, raising=False)
    result = adapters.execute(project, project / 'step', tool,
        {'delivery_target': 'ip_hardmacro'}, state=state,
        config={'DESIGN_NAME': name, 'DEFAULT_CORNER': 'nominal'})
    assert result['ran'], result
    assert result['exit_code'] == 0, result
    assert engine.evaluate(engine.ToolResult(**result), []) == 'PASS', result
    documents = project / doc_dir('ip') / name
    for spec in IP_DOCS:
        if spec.requirement == 'required':
            assert (documents / spec.filename).is_file()
    assert not (documents / MANIFEST_NAME).exists()
    assert result['metrics']['release_document_errors'] == 0
    assert result['metrics']['release_documents'] >= 6
    views = {extension: project / tool['destination'] / (name + extension)
             for extension in tool['formats'].values()}
    views['.v'].write_text(views['.v'].read_text().replace('output wire dout',
                                                       'output wire extra, output wire dout'))
    findings, _ = checker.check_release(project, 'ip', documents, name, ip_views=views)
    assert 'PIN_COUNT_DISAGREES_WITH_NETLIST' in {finding.rule for finding in findings}


@pytest.mark.parametrize('supply_metadata', ['missing', 'wrong_ground'])
def test_export_uses_existing_def_supply_writer_without_overriding_explicit_polarity(
        tmp_path, monkeypatch, supply_metadata):
    import re

    project, name, state, tool = native_release(tmp_path, monkeypatch)
    library = project / 'phase3/stage4/hardmacro' / (name + '.lib')
    text = library.read_text()
    if supply_metadata == 'missing':
        text = re.sub(r'\s*pg_pin\s*\([^)]+\)\s*\{[^}]*\}', '', text)
    else:
        text = text.replace('pg_type : primary_ground', 'pg_type : primary_power')
    library.write_text(text)
    routed = project / 'routed.def'
    routed.write_text('''VERSION 5.8 ;
DESIGN block_a ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 120000 80000 ) ;
PINS 2 ;
- VPWR + NET VPWR + DIRECTION INOUT + USE POWER + LAYER met4 ( 0 0 ) ( 100 100 ) + PLACED ( 0 0 ) N ;
- VGND + NET VGND + DIRECTION INOUT + USE GROUND + LAYER met4 ( 0 0 ) ( 100 100 ) + PLACED ( 0 0 ) N ;
END PINS
END DESIGN
''')
    raw = state.to_raw_dict()
    raw['def'] = str(routed)
    result = adapters.execute(project, project / 'step', tool,
        {'delivery_target': 'ip_hardmacro'}, state=State.load(raw),
        config={'DESIGN_NAME': name, 'DEFAULT_CORNER': 'nominal'})
    expected = 'PASS' if supply_metadata == 'missing' else 'FAIL'
    assert engine.evaluate(engine.ToolResult(**result), []) == expected, result
    if supply_metadata == 'missing':
        exported = (project / tool['destination'] / (name + '.lib')).read_text()
        assert 'pg_pin (VPWR) { pg_type : primary_power' in exported
        assert 'pg_pin (VGND) { pg_type : primary_ground' in exported
    else:
        assert result['metrics']['release_document_errors'] > 0


def test_missing_current_view_does_not_document_retained_export(tmp_path, monkeypatch):
    from librelane.state import DesignFormat

    project, name, state, tool = native_release(tmp_path, monkeypatch)
    retained = project / tool['destination'] / (name + '.v')
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_text('module retained; endmodule\n')
    state = State(state, overrides={DesignFormat.NETLIST: None})
    result = adapters.execute(project, project / 'step', tool,
        {'delivery_target': 'ip_hardmacro'}, state=state,
        config={'DESIGN_NAME': name, 'DEFAULT_CORNER': 'nominal'})
    assert engine.evaluate(engine.ToolResult(**result), []) == 'NOT_MEASURED'
    assert not (project / doc_dir('ip') / name).exists()
    assert retained.read_text() == 'module retained; endmodule\n'
