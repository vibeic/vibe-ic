"""Source admission tests; native CLI/JUnit/activity proof is measured separately.

No runtime mock, template patch, benchmark source or oracle is used here.
"""
import json
from pathlib import Path
import shutil

import pytest
import professional_tb_gen as producer
import verilator_coverage_measure as coverage

FIXTURE = Path(__file__).parent / 'fixtures/professional_helper_observation'


def project(tmp_path, variant='sibling'):
    root = tmp_path / 'project'
    gd = root / 'phase1/generated_docs'
    rtl = root / 'phase2/stage1/rtl'
    bundle = root / 'phase2/stage1/sim_professional/port_frame'
    for path in [gd, rtl, bundle]:
        path.mkdir(parents=True)
    shutil.copyfile(FIXTURE / 'L9_INTEGRATION_SPEC.json', gd / 'L9_INTEGRATION_SPEC.json')
    shutil.copyfile(FIXTURE / 'port_frame.sv', rtl / 'port_frame.sv')
    source = (FIXTURE / 'expert_reference_tb.py').read_text()
    helper = (FIXTURE / 'wire_bfm.py').read_text()
    if variant.startswith('multi_hop'):
        source = (FIXTURE / 'deep_reference_tb.py').read_text()
        helper = (FIXTURE / 'deep_wire_bfm.py').read_text()
        changes = {
            'multi_hop': None,
            'multi_hop_constant_return': ('return result', 'return b"\\x3a\\x3a"'),
            'multi_hop_unasserted_result': ('assert actual == expected', 'assert expected == expected'),
            'multi_hop_constant_drive': ('d.data_i.value = value', 'd.data_i.value = 0'),
            'multi_hop_no_await': ('actual = await block_value(env)', 'actual = block_value(env)'),
            'multi_hop_dead_loop': ('for _ in range(2):', 'for _ in range(0):'),
        }
        change = changes[variant]
        if change:
            source, helper = source.replace(*change), helper.replace(*change)
    elif variant == 'module_alias':
        source = source.replace('from wire_bfm import WireEnvironment', 'import wire_bfm as local_wire').replace('env = WireEnvironment(dut)', 'env = local_wire.WireEnvironment(dut)')
    elif variant == 'async_function':
        source = source.replace('from wire_bfm import WireEnvironment', 'from wire_bfm import output_value').replace('    env = WireEnvironment(dut)\n', '').replace('actual = await block_value(env)', 'actual = await output_value(dut)')
        helper = 'from cocotb.triggers import Timer\nasync def output_value(handle):\n    await Timer(1, units="ns")\n    return int(handle.out_o.value)\n'
    elif variant == 'same_file_async':
        source = source.replace('from wire_bfm import WireEnvironment', 'async def output_value(handle):\n    await Timer(1, units="ns")\n    return int(handle.out_o.value)').replace('    env = WireEnvironment(dut)\n', '').replace('actual = await block_value(env)', 'actual = await output_value(dut)')
    elif variant == 'legacy_sync':
        source = source.replace('from wire_bfm import WireEnvironment', 'def output_value(port):\n    return int(port.value)').replace('    env = WireEnvironment(dut)\n', '').replace('actual = await block_value(env)', 'actual = output_value(dut.out_o)')
    elif variant == 'direct':
        source = source.replace('from wire_bfm import WireEnvironment\n', '').replace('    env = WireEnvironment(dut)\n', '').replace('actual = await block_value(env)', 'actual = int(dut.out_o.value)')
    elif variant == 'constant':
        helper = helper.replace('int(self.dut.out_o.value)', '0x3a')
    elif variant == 'unused_observation':
        helper = helper.replace('return int(self.dut.out_o.value)', '_unused = int(self.dut.out_o.value)\n        return 0x3a')
    elif variant == 'unasserted_result':
        source = source.replace('assert actual == expected', 'assert expected == expected')
    elif variant == 'no_assertion':
        source = source.replace('assert actual == expected', '_comparison = actual == expected')
    elif variant == 'unresolved':
        helper = None
    elif variant == 'outside':
        source = source.replace('from wire_bfm import', 'from ..outside_bfm import')
        (bundle.parent / 'outside_bfm.py').write_text(helper)
        helper = None
    elif variant == 'symlink_outside':
        outside = tmp_path / 'outside_bfm.py'
        outside.write_text(helper)
        (bundle / 'wire_bfm.py').symlink_to(outside)
        helper = None
    elif variant == 'ambiguous_symbol':
        helper += helper[helper.index('class WireEnvironment:'):]
    elif variant == 'constructor_not_dut':
        helper = helper.replace('self.dut = dut', 'self.dut = None')
    elif variant == 'constructor_rebound':
        source = source.replace('@cocotb.test()', 'WireEnvironment = None\n@cocotb.test()')
    elif variant == 'method_alias_rebound':
        helper = helper.replace('await Timer(1, units="ns")', 'self.dut = None\n        await Timer(1, units="ns")')
    elif variant == 'not_awaited':
        source = source.replace('actual = await block_value(env)', 'actual = block_value(env)')
    elif variant == 'uncalled':
        source = source.replace('actual = await block_value(env)', 'actual = 0x3a')
    elif variant == 'star_import':
        source = source.replace('from wire_bfm import WireEnvironment', 'from wire_bfm import *')
    elif variant == 'inherited_class':
        helper = helper.replace('class WireEnvironment:', 'class WireEnvironment(object):')
    elif variant == 'dead_read':
        helper = helper.replace('return int(self.dut.out_o.value)', 'return 0x3a\n        _dead = int(self.dut.out_o.value)')
    elif variant == 'conditional_constant':
        helper = helper.replace('return int(self.dut.out_o.value)', 'return int(self.dut.out_o.value) if self.dut else 0x3a')
    elif variant == 'dynamic_attribute':
        helper = helper.replace('return int(self.dut.out_o.value)', 'return int(getattr(self.dut, "out_o").value)')
    elif variant == 'short_circuit':
        source = source.replace('actual = await block_value(env)', 'actual = False and await block_value(env)')
    elif variant == 'constant_condition':
        source = source.replace('actual = await block_value(env)', 'actual = 0 if True else await block_value(env)')
    elif variant == 'dead_assertion':
        source = source.replace('        assert actual == expected', '        if False:\n            assert actual == expected')
    elif variant == 'caller_late_binding':
        source += '    WireEnvironment = None\n'
    elif variant == 'caller_dead_binding':
        source = source.replace('    env = WireEnvironment(dut)', '    if False:\n        WireEnvironment = None\n    env = WireEnvironment(dut)')
    elif variant == 'dynamic_constructor':
        helper = helper.replace('self.dut = dut', 'setattr(self, "dut", dut)')
    elif variant == 'dynamic_alias_write':
        helper = helper.replace('await Timer(1, units="ns")', 'setattr(self, "dut", None)\n        await Timer(1, units="ns")')
    elif variant == 'shadowed_conversion':
        helper = 'int = lambda value: 0\n' + helper
    elif variant == 'posonly_constructor_keyword':
        helper = helper.replace('__init__(self, dut)', '__init__(self, dut, /)')
        source = source.replace('WireEnvironment(dut)', 'WireEnvironment(dut=dut)')
    elif variant == 'unresolved_mutator':
        source = source.replace('from wire_bfm import WireEnvironment', 'from wire_bfm import WireEnvironment\nfrom unavailable import mutate').replace('    env = WireEnvironment(dut)', '    env = WireEnvironment(dut)\n    mutate(env)')
    elif variant == 'presence':
        source = source.replace('    env = WireEnvironment(dut)', '    assert hasattr(dut, "out_o")\n    env = WireEnvironment(dut)')
    elif variant == 'presence_only':
        helper = helper.replace('int(self.dut.out_o.value)', 'hasattr(self.dut, "out_o")')
    elif variant == 'shadowed_presence':
        source = source.replace('    env = WireEnvironment(dut)', '    hasattr = unknown_mutator\n    hasattr(dut, "out_o")\n    env = WireEnvironment(dut)')
    elif variant in {'cleanup_finally', 'finally_swallow_return', 'except_swallow'}:
        begin = source.index('    for value in range(256):')
        body = source[begin:]
        cleanup = '    finally:\n        env.stop()\n'
        helper += '\n    def stop(self):\n        pass\n'
        if variant == 'finally_swallow_return':
            cleanup = '    finally:\n        return\n'
        if variant == 'except_swallow':
            cleanup = '    except AssertionError:\n        pass\n'
        source = source[:begin] + '    try:\n' + ''.join('    ' + line + '\n' for line in body.splitlines()) + cleanup
    elif variant == 'repeated_explicit_calls':
        source = source.replace('actual = await block_value(env)', '\n'.join(['actual = await block_value(env)'] + ['        actual = await block_value(env)'] * 119))
    elif variant == 'recursive_helper':
        helper = helper.replace('return int(self.dut.out_o.value)', 'return await self.output()')
    elif variant == 'depth_overflow':
        helper += '\n' + '\n'.join('def layer_%d(handle):\n    return %s' % (n, 'int(handle.out_o.value)' if n == 25 else 'layer_%d(handle)' % (n + 1)) for n in range(26)) + '\n'
        helper = helper.replace('return int(self.dut.out_o.value)', 'return layer_0(self.dut)')
    elif variant == 'large_unrelated_tail':
        source += ''.join('    unrelated_%d = %d\n' % (n, n) for n in range(10000))
    elif variant == 'memo_field_changed':
        helper = helper.replace('self.dut = dut', 'self.dut = dut\n        self.constant = False').replace('return int(self.dut.out_o.value)', 'if self.constant:\n            return 0x3a\n        return int(self.dut.out_o.value)')
        source = source.replace('actual = await block_value(env)', '_first = await block_value(env)\n        env.constant = True\n        actual = await block_value(env)')
    elif variant in {'keyword_mutator', 'aggregate_mutator'}:
        source = source.replace('from wire_bfm import WireEnvironment', 'from wire_bfm import WireEnvironment\nfrom unavailable import mutate').replace('    env = WireEnvironment(dut)', '    env = WireEnvironment(dut)\n    ' + ('mutate(binding=env)' if variant == 'keyword_mutator' else 'mutate([env])'))
    elif variant != 'sibling':
        raise AssertionError(variant)
    (bundle / 'expert_reference_tb.py').write_text(source)
    if helper is not None:
        (bundle / 'wire_bfm.py').write_text(helper)
    result = producer.generate(root)
    assert result['status'] == 'PASS', result
    return bundle / 'tb_port_frame.py'


@pytest.mark.parametrize('variant', ['sibling', 'module_alias', 'async_function', 'same_file_async', 'legacy_sync', 'direct', 'presence', 'cleanup_finally', 'repeated_explicit_calls', 'large_unrelated_tail'])
def test_reachable_asserted_observation_is_admitted(tmp_path, variant):
    audit = coverage.functional_stimulus_audit(project(tmp_path, variant))
    assert audit['decidable'] is True, audit
    assert audit['driven'] == ['data_i'], audit


@pytest.mark.parametrize('variant', [
    'constant', 'unused_observation', 'unasserted_result', 'no_assertion',
    'unresolved', 'outside', 'symlink_outside', 'ambiguous_symbol',
    'constructor_not_dut', 'constructor_rebound', 'method_alias_rebound',
    'not_awaited', 'uncalled', 'star_import', 'inherited_class', 'dead_read',
    'conditional_constant', 'dynamic_attribute',
    'short_circuit', 'constant_condition', 'dead_assertion',
    'caller_late_binding', 'caller_dead_binding', 'dynamic_constructor',
    'dynamic_alias_write', 'shadowed_conversion', 'posonly_constructor_keyword',
    'unresolved_mutator', 'presence_only', 'shadowed_presence', 'finally_swallow_return', 'except_swallow', 'recursive_helper', 'depth_overflow', 'memo_field_changed', 'keyword_mutator', 'aggregate_mutator',
])
def test_unestablished_or_unasserted_helper_observation_stays_refused(tmp_path, variant):
    audit = coverage.functional_stimulus_audit(project(tmp_path, variant))
    assert audit['decidable'] is False or not audit['driven'], audit


@pytest.mark.parametrize('variant', ['multi_hop', 'multi_hop_constant_return',
    'multi_hop_unasserted_result', 'multi_hop_constant_drive',
    'multi_hop_no_await', 'multi_hop_dead_loop'])
def test_multihop_return_assertion_and_reachable_input_drive(tmp_path, variant):
    audit = coverage.functional_stimulus_audit(project(tmp_path, variant))
    established = audit['decidable'] and bool(audit['driven'])
    assert established == (variant == 'multi_hop'), audit
    if established:
        assert audit['driven'] == ['data_i']
        assert len(audit['helper_sources']) == 1
