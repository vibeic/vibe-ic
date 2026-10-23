"""Source inventory audit: engine scope is not native qualification."""
import flow109


def digital_plan(*, requires_spice=False):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    return flow109.resolve_plan({**features, 'requires_spice': requires_spice})


def uses(step):
    return {u['tool_id']: u for u in flow109.resolve_step(digital_plan(requires_spice=step == 'D54'), step)['tool_uses']}


def test_spice_path_requires_extraction_sta_and_simulation_independently():
    actual = uses('D54')
    assert set(actual) == {'opensta', 'magic', 'ngspice'}
    assert actual['opensta']['executable_name'] == 'sta'
    assert actual['opensta']['native_steps'] == ['OpenSTA.WritePathSpice']
    assert actual['magic']['native_steps'] == ['Magic.ExtractCells']
    assert actual['ngspice']['native_steps'] == ['Ngspice.PathCorrelation']
    assert len({u['use_id'] for u in actual.values()}) == 3


def test_final_physical_verification_includes_current_openroad_erc():
    actual = uses('D65')
    assert set(actual) == {'magic', 'klayout', 'netgen', 'openroad'}
    assert actual['openroad']['native_steps'] == ['OpenROAD.ERC']
    assert actual['netgen']['native_steps'] == ['Netgen.LVS']
    assert 'Magic.SpiceExtraction' not in actual['klayout']['native_steps']


def test_stapostpnr_embedded_sta_is_not_a_second_standalone_sta_launch():
    actual = uses('D49')
    assert set(actual) == {'openroad'}
    assert actual['openroad']['native_steps'] == ['OpenROAD.STAPostPNR']


def test_native_and_retained_consumers_have_distinct_tool_uses():
    assert set(uses('D31')) == {'yosys', 'openroad'}
    for step in ('D32', 'D56', 'D59'):
        assert set(uses(step)) == {'python3'}
    assert uses('D56')['python3']['native_steps'] == ['Vibeic.AdoptSTAPostPNRPower']


def test_router_antenna_does_not_claim_future_gds_check():
    assert set(uses('D43')) == {'openroad'}
    assert 'KLayout.Antenna' not in uses('D43')['openroad']['native_steps']
    assert 'KLayout.Antenna' in uses('D60')['klayout']['native_steps']
    assert set(uses('D61')) == {'klayout'}


def test_gls_qualifies_both_compile_and_runtime():
    actual = uses('D53')
    assert set(actual) == {'iverilog', 'vvp'}
    assert actual['iverilog']['native_steps'] == ['Icarus.Compile']
    assert actual['vvp']['native_steps'] == ['Icarus.Simulate']


def test_all_dispatchable_profiles_cover_each_declared_operation_once():
    registry = flow109.load_registry()
    backend_owners = {}
    for row in registry['rows']:
        for profile in row['profiles']:
            dispatch = profile.get('dispatch')
            if not dispatch:
                continue
            if dispatch.get('kind') == 'canonical_owner_window':
                # This route delegates to an existing runner, including its
                # selected native tools; it does not enroll a generic arm.
                assert dispatch['engine_families'] == []
                assert flow109._canonical_owner_dispatch({**row, 'profile': profile})
                assert dispatch['acceptance_scope'] == 'existing_native_component_only'
                continue
            if not dispatch.get('adapter'):
                backend_owners[(row['id'], profile['id'])] = dispatch['native_step_id']
            engines = dispatch['engine_families']
            assert set(dispatch['engine_steps']) == set(engines)
            assert set(dispatch['engine_executables']) == set(engines)
            operations = [operation for engine in engines for operation in dispatch['engine_steps'][engine]]
            assert sorted(operations) == sorted(profile['native_steps']), row['id']
            assert all(dispatch['engine_executables'][engine] for engine in engines)
    # Check the actual stable-ID/native-owner mapping rather than a total
    # that misses swapped owners and becomes stale when D63 is exposed.
    expected = {
        'D31': '15', 'D32': '15.5ic', 'D35': '17', 'D37': '18',
        'D38': '19', 'D39': '20', 'D40': '21', 'D41': '32',
        'D43': '26', 'D47': '22', 'D48': '27', 'D49': '23',
        'D53': '29', 'D54': '30', 'D56': '33', 'D57': '24',
        'D58': '25', 'D59': '28', 'D60': '37', 'D61': '26.5ic',
        'D63': '35', 'D64': '37.3', 'D65': '31', 'D77': '37.4',
        'D78': '36', 'D80': '37.5ic', 'D81': '38',
    }
    assert backend_owners == {(step, 'default'): native for step, native in expected.items()}


def test_explicit_fill_streaming_is_a_distinct_required_native_tool_purpose():
    actual = uses('D60')['klayout']
    assert 'Vibeic.FillAwareStreamOut' in actual['native_steps']
    assert 'KLayout.StreamOut' in actual['native_steps']
