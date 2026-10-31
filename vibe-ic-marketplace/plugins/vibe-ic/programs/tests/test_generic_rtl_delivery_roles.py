"""Synthetic public API contracts for artifact, background and delivery roles."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_nature_route as route


@pytest.mark.parametrize('prompt', [
    pytest.param('The reference chip has two gates. Write a module implementing XOR.', id='background'),
    pytest.param('A chip contains two gates. Write a module implementing XOR.', id='narrated-background'),
    pytest.param('Write a module named chip with one input and one output.', id='module-name'),
    pytest.param('Write a module with a chip output port. It has one input and one output.', id='port-name'),
    pytest.param('Complete this RTL module.\nmodule CoreBlock(output chip', id='partial-header'),
    pytest.param('Implement a Verilog module.\nmodule CoreBlock(output chip /* enable */); endmodule', id='commented-port'),
    pytest.param('Write a module that models a chip. Deliver only the Verilog source.', id='source-delivery'),
    pytest.param('Write a module that models a chip. Produce SystemVerilog source files.', id='source-production'),
    pytest.param('Write a module that models a chip. It has two inputs and one output.', id='model-io'),
    pytest.param('The RefA device is a chip. Write a module with the same functionality as the RefA device.', id='same-reference'),
])
def test_rtl_artifact_does_not_inherit_a_background_or_identifier(prompt):
    requirements = route.prompt_delivery_requirements(prompt)
    resolved = route.resolve_prompt_delivery_target(requirements, 'rtl')
    assert resolved['ok'] is True, resolved
    actual = route.delivery_route_for_target(resolved['target'], resolved['route_family'])
    assert actual == 'ip', requirements
    assert requirements['minimum_target'] is None
    assert not route.resolve_prompt_delivery_target(requirements, 'gds')['ok']


@pytest.mark.parametrize('prompt', [
    pytest.param('Write a module that models a chip. Deliver the modeled device in a physical package.', id='modeled-device'),
    pytest.param('Write a module for a chip. Deliver that device in a physical package.', id='that-device'),
    pytest.param('Write a module that models a chip and physically package the modeled device.', id='coordinated-package'),
    pytest.param('Write a module for a chip and deliver that device in a physical package.', id='coordinated-delivery'),
    pytest.param('Write a module that models a chip and the modeled device must be physically packaged.', id='coordinated-passive'),
    pytest.param('Write a module for a chip, then place that device in a physical package.', id='then-package'),
    pytest.param('Write a module for a chip and ship the device in a physical package, not the accessory.', id='unrelated-negation'),
])
def test_independent_package_predicate_keeps_the_physical_floor(prompt):
    requirements = route.prompt_delivery_requirements(prompt)
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is False
    assert route.resolve_prompt_delivery_target(requirements, 'ip_hardmacro')['ok'] is False
    assert requirements['minimum_target'] == 'gds', requirements
    assert requirements['route_family'] == 'DIE'
    resolved = route.resolve_prompt_delivery_target(requirements, None)
    assert resolved['ok'] is True
    assert route.delivery_route_for_target(resolved['target'], resolved['route_family']) == 'ic'


@pytest.mark.parametrize('prompt', [
    'Write a module that models a chip in a physical package.',
    'Write a module that models a chip with two inputs and two outputs in a physical package.',
    'Write a module that models a chip and do not physically package the modeled device.',
    'Write a module that models a chip and the modeled device must not be physically packaged.',
])
def test_model_description_or_denied_package_does_not_invent_a_floor(prompt):
    requirements = route.prompt_delivery_requirements(prompt)
    assert requirements['minimum_target'] is None, requirements
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is True


@pytest.mark.parametrize('prompt,target,family,minimum', [
    ('Write a module for a chip. Deliver the modeled device.', 'rtl', 'DIE', None),
    ('Write a module for a chip. The modeled device must be delivered.', 'rtl', 'DIE', None),
    ('Write a module for a chip. Production of the modeled device is required.', 'rtl', 'DIE', None),
    ('The RefA device is a chip. Write a module with the same functionality as the RefB device.', 'rtl', 'DIE', None),
    ('Write a module for a chip. Fabricate it.', 'rtl', 'DIE', None),
    ('Deliver the final chip. Write its module.', 'rtl', 'DIE', None),
    ('Write a module for a chip. The chip is the final deliverable.', 'rtl', 'DIE', None),
    ('Complete this RTL module.\nmodule CoreBlock(output chip\nDeliver the final chip.', 'rtl', 'DIE', None),
    ('Complete this RTL module.\nmodule CoreBlock(output chip\nDeliver the final chip.\nmodule helper; endmodule', 'rtl', 'DIE', None),
    ('Write RTL.\nmodule must be integrated into the final chip;', 'rtl', 'DIE', None),
    ('Write a module for a chip. See https://example.invalid/spec. Fabricate the device.', 'rtl', 'DIE', None),
    ('Write a module for a chip and deliver GDS.', 'gds', 'DIE', 'gds'),
    ('Write a module for a chip and deliver shippable GDS.', 'shippable_gds', 'DIE', 'shippable_gds'),
    ('Write a module for a chip. Foundry handoff is required.', 'foundry_handoff', 'DIE', 'foundry_handoff'),
    ('Write a module that models a chip for tapeout.', 'shippable_gds', 'DIE', 'shippable_gds'),
    ('Write a module that models a chip for a shuttle.', 'rtl', 'DIE', None),
    ('Deliver a standalone IP hardmacro for use inside a customer chip.', 'ip_hardmacro', 'HARDMACRO', 'ip_hardmacro'),
])
def test_explicit_or_unresolved_delivery_keeps_its_public_contract(prompt, target, family, minimum):
    requirements = route.prompt_delivery_requirements(prompt)
    assert requirements['route_family'] == family, requirements
    assert requirements['minimum_target'] == minimum
    resolved = route.resolve_prompt_delivery_target(requirements, target)
    assert resolved['ok'] is True, resolved
    assert route.delivery_route_for_target(resolved['target'], resolved['route_family']) == (
        'ip' if family == 'HARDMACRO' else 'ic')
    opposite = 'rtl' if family == 'HARDMACRO' else 'ip_hardmacro'
    assert route.resolve_prompt_delivery_target(requirements, opposite)['ok'] is False


def test_separate_die_and_hardmacro_remain_a_conflict():
    requirements = route.prompt_delivery_requirements(
        'Deliver a complete chip and a separate standalone IP hardmacro. Write RTL.')
    assert requirements['status'] == 'CONFLICT'
    for target in (None, 'rtl', 'gds', 'ip_hardmacro'):
        assert route.resolve_prompt_delivery_target(requirements, target)['ok'] is False


def test_requirement_mutation_is_refused_before_resolution():
    requirements = route.prompt_delivery_requirements(
        'Write a module for a chip. Deliver that device in a physical package.')
    mutated = copy.deepcopy(requirements)
    mutated['minimum_target'] = None
    assert route.resolve_prompt_delivery_target(mutated, 'rtl')['ok'] is False


def test_generic_proposal_still_requires_ai_routing_authority():
    proposal = route.classify_task_nature('Write a module that implements XOR.', False)
    assert proposal['needs_ai_parse'] is True


@pytest.mark.parametrize('header', [
    pytest.param('module Core(input clk, output q)', id='balanced-no-semicolon'),
    pytest.param('module Core(input clk, output q)\n', id='following-line'),
    pytest.param('module Core #(parameter W = (2)) (input clk, output q)', id='parameterized'),
    pytest.param('module Core(input clk, /* ) */ output q)', id='comment-parenthesis'),
])
def test_delivery_after_balanced_interface_keeps_explicit_family_and_floor(header):
    prompt = ('Write a module that models a chip.\n' + header
              + ' Deliver the modeled device in a physical package.')
    requirements = route.prompt_delivery_requirements(prompt)
    assert requirements['status'] == 'EXPLICIT_ROUTE', requirements
    assert requirements['route_family'] == 'DIE'
    assert requirements['minimum_target'] == 'gds'
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is False
    assert route.resolve_prompt_delivery_target(requirements, 'ip_hardmacro')['ok'] is False
    resolved = route.resolve_prompt_delivery_target(requirements, None)
    assert resolved['ok'] is True
    assert resolved['target'] == 'gds'
    assert route.delivery_route_for_target(resolved['target'], resolved['route_family']) == 'ic'


@pytest.mark.parametrize('prompt,family,target', [
    ('Implement the RTL module and deliver its LEF and Liberty views.', 'HARDMACRO', 'ip_hardmacro'),
    ('Implement the RTL module. Its LEF and Liberty views must be delivered.', 'HARDMACRO', 'ip_hardmacro'),
    ('Implement the RTL module. LEF and Liberty views are required.', 'HARDMACRO', 'ip_hardmacro'),
    ('請設計晶片並交付可投片的實體版圖，完成製造與封裝。', 'DIE', 'shippable_gds'),
    ('請交付完整硬巨集。', 'HARDMACRO', 'ip_hardmacro'),
])
def test_physical_views_and_chinese_delivery_keep_their_owner_floor(prompt, family, target):
    requirements = route.prompt_delivery_requirements(prompt)
    assert requirements['route_family'] == family
    assert requirements['minimum_target'] == target
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is False


@pytest.mark.parametrize('prompt', [
    'Write a module that models a chip. Do not deliver GDS, LEF or Liberty.',
    'Implement the RTL module and do not deliver its LEF and Liberty views.',
    'Implement the RTL module. LEF and Liberty views are not required.',
    '請設計晶片功能的 RTL，不需要投片、製造或封裝。',
    '請設計晶片的 RTL，不需要交付可投片的實體版圖。',
    '請設計晶片內的 RTL 模組，只交付 Verilog。',
    '請設計晶片的數位模組，只交付 RTL。',
    '請設計晶片內部的可合成模組，只交付 RTL。',
])
def test_denied_physical_delivery_does_not_override_an_rtl_request(prompt):
    requirements = route.prompt_delivery_requirements(prompt)
    assert requirements['route_family'] is None
    assert requirements['minimum_target'] is None
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is True


def test_unchanged_delivery_payload_retains_issued_r5_identity():
    requirements = route.prompt_delivery_requirements('Debug the supplied RTL; return corrected Verilog.')
    assert requirements['rules_version'] == 'r5'
    assert requirements['requirements_sha256'] == '07c41201e7ecb110bef04f6d3632399c3023f4b71101ce00a2368aee60aa457d'


@pytest.mark.parametrize('prompt,family', [
    ('Implement RTL. No GDS is required, deliver LEF and Liberty views.', 'HARDMACRO'),
    ('Implement RTL. LEF and Liberty views are not required and deliver GDS.', 'DIE'),
])
def test_a_denied_artifact_cannot_hide_an_independent_positive_delivery(prompt, family):
    requirements = route.prompt_delivery_requirements(prompt)
    resolved = route.resolve_prompt_delivery_target(requirements, None)
    assert resolved['ok'] is True
    assert resolved['route_family'] == family
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is False


def _source_scope_request(tmp_path, monkeypatch, text):
    from test_flow109_rtl_scope import _request
    args = _request(tmp_path, monkeypatch)
    context = tmp_path / 'input/docs/context.md'
    context.parent.mkdir(parents=True, exist_ok=True)
    context.write_text(text)
    return args, context


_NATIVE_HEADER = '_IC: **sample**  •  Class: `any-ic`  •  Source-of-truth: `L1_DATASHEET.json`_'


@pytest.mark.parametrize('context', [
    pytest.param(_NATIVE_HEADER, id='renderer-identity'),
    pytest.param(_NATIVE_HEADER + '\n- **design_scope**: Existing bounded RTL simulation carrier; physical IC implementation is not specified by these source files.', id='renderer-unspecified'),
    pytest.param('Physical IC implementation is not specified by these source files.', id='unspecified-implementation'),
    pytest.param('Physical IC implementation\n    is not specified by these source files.', id='wrapped-unspecified'),
    pytest.param('class_path: any-ic', id='native-class-identifier'),
    pytest.param('ic: false', id='native-negative-feature'),
    pytest.param('class_path: any-ic\nmetadata:\n  features:\n    ic: false\nfacts:\n- path: L1.design_scope\n  value: Existing bounded RTL simulation carrier; physical IC implementation\n    is not specified by these source files.', id='native-folded-fact'),
])
def test_native_input_identity_and_unspecified_implementation_are_not_delivery(context, tmp_path, monkeypatch):
    import flow109
    args, source = _source_scope_request(tmp_path, monkeypatch, context)
    before = source.read_bytes()
    try:
        flow109.prepare_front_door(args, tmp_path)
        issuance = 'ISSUED'
    except flow109.Flow109Error as exc:
        issuance = exc.code
    assert issuance == 'ISSUED'
    requirements = route.prompt_delivery_requirements(context)
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is True
    assert requirements['route_family'] is None
    assert requirements['minimum_target'] is None
    assert flow109.active_rtl_scope(tmp_path)['project'] == str(tmp_path.resolve())
    assert source.read_bytes() == before


@pytest.mark.parametrize('physical_request,family', [
    pytest.param('Deliver GDS.', 'DIE', id='later-gds'),
    pytest.param('Design a complete chip.', 'DIE', id='later-chip'),
    pytest.param('Deliver a hard macro.', 'HARDMACRO', id='later-hardmacro'),
    pytest.param('The chip is for tapeout.', 'DIE', id='later-tapeout'),
    pytest.param('Deliver LEF and Liberty views.', 'HARDMACRO', id='later-physical-views'),
])
@pytest.mark.parametrize('position', ['before', 'after'])
def test_positive_physical_request_survives_native_metadata_and_absence(physical_request, family, position, tmp_path, monkeypatch):
    context = _NATIVE_HEADER + '\nPhysical IC implementation is not specified by the reference source.'
    prompt = physical_request + '\n' + context if position == 'before' else context + '\n' + physical_request
    requirements = route.prompt_delivery_requirements(prompt)
    resolved = route.resolve_prompt_delivery_target(requirements, None)
    assert resolved['ok'] is True
    assert resolved['route_family'] == family
    import flow109
    args, source = _source_scope_request(tmp_path, monkeypatch, prompt)
    before = source.read_bytes()
    with pytest.raises(flow109.Flow109Error, match='FLOW109_RTL_SCOPE_CONFLICT'):
        flow109.prepare_front_door(args, tmp_path)
    assert source.read_bytes() == before


def test_native_false_feature_does_not_override_a_physical_request():
    requirements = route.prompt_delivery_requirements('class_path: any-ic\nic: false\nProduce GDS.')
    assert route.resolve_prompt_delivery_target(requirements, None)['route_family'] == 'DIE'
    assert requirements['minimum_target'] == 'gds'
    assert route.resolve_prompt_delivery_target(requirements, 'rtl')['ok'] is False
