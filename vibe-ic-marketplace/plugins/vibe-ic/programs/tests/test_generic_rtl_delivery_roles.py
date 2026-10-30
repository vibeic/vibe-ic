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
