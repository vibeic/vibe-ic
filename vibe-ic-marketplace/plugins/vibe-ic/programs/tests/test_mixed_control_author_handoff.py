"""A generic mixed controller is authored from its own declared interface."""

import design_one_shot_runner as runner




def test_protocol_specific_generator_remains_registered():
    entry = runner._lookup_class('aid_class_half_duplex_single_wire')
    assert entry['rtl_gen'] == 'aid_class_rtl_gen.py'


def test_generic_controller_uses_its_authored_reference():
    uses_fixed, reason = runner._class_uses_aid_reference_tb('mixed_signal_otp')
    assert uses_fixed is False, reason
    uses_fixed, reason = runner._class_uses_aid_reference_tb('aid_class_half_duplex_single_wire')
    assert uses_fixed is True, reason
