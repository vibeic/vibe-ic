"""The early package row reports native pad placement after RTL authoring."""
import json

import pytest

import flow_engine as engine
import flow_engine_frontend as frontend
import pad_assignment_gen
import io_pad_chip_top_gen


@pytest.mark.parametrize('status,code,ran', [('PASS', 0, True), ('FAIL', 1, True),
                                           ('NOT_MEASURED', None, False)])
def test_early_package_row_defers_to_native_pad_placement(tmp_path, monkeypatch, status, code, ran):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'no_package_in_input': True}))
    (docs / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {'pdk_target': 'gf180mcuD'}}))
    calls = []
    names = {'package_load_and_test_interface_feasibility', 'rtl_authoring',
             'structural_rtl_preflight', 'die_floorplan_and_macros'}
    select = engine.select_steps
    monkeypatch.setattr(engine, 'select_steps', lambda *args: [row for row in select(*args) if row['name'] in names])

    def author(self, directory, action):
        assert action == 'rtl_gen'
        assert not (tmp_path / 'phase2/stage1/rtl').exists()
        calls.append('author')
        rtl = tmp_path / 'phase2/stage1/rtl/core.v'
        rtl.parent.mkdir(parents=True)
        rtl.write_text('module core(input clk, output q); assign q=clk; endmodule\n')
        return {'ran': True, 'exit_code': 0}

    def native(self, directory, tool):
        assert (tmp_path / 'phase2/stage1/rtl/core.v').is_file()
        calls.append(tool['steps'][0])
        if 'OpenROAD.PadRing' in tool['steps']:
            return engine.ToolResult(ran, code, {'native_pad_count': 7}, ['native-pad-ring.log'])
        assert tool['steps'] == ['Yosys.JsonHeader']
        return engine.ToolResult(True, 0)

    def forbidden(*args, **kwargs):
        raise AssertionError('Step 6 must report native placement, not run document or IO producers')

    monkeypatch.setattr(frontend.OwnerSession, 'result', author)
    monkeypatch.setattr(engine.NativeChain, 'execute', native)
    monkeypatch.setattr(pad_assignment_gen, 'main', forbidden)
    monkeypatch.setattr(io_pad_chip_top_gen, 'main', forbidden)
    table = engine.read_json(engine.TABLE)
    row = table['steps'][5]
    assert row['tool'] == {'kind': 'native_report', 'from': 'die_floorplan_and_macros'}
    route = {'entry_step': row['name'], 'verify_through': 'die_floorplan_and_macros',
             'delivery_target': 'gds', 'input_contract': 'structured'}
    result = engine.run(tmp_path, table=table, route=route,
                        from_name=row['name'], to_name='die_floorplan_and_macros')
    rows = {row['name']: row for row in result['steps']}
    package = rows['package_load_and_test_interface_feasibility']
    assert calls == ['author', 'Yosys.JsonHeader', 'OpenROAD.Floorplan']
    assert rows['structural_rtl_preflight']['status'] == 'PASS'
    assert package['status'] == status
    assert package['native_metrics'] == {'native_pad_count': 7}
    assert package['reports'] == ['native-pad-ring.log']
    if ran:
        assert package['review_from'] == 'die_floorplan_and_macros'
    else:
        assert package['ai_review'] == 'NO_NATIVE_RESULT'
