"""Neutral SOFTWARE CONTRACT controls; scalar values confer no ADC qualification."""

import pytest
import analog_declared_pvt as declared


SECTIONS = ['neutral_ss', 'neutral_tt', 'neutral_ff']














@pytest.mark.parametrize('markers, expected', [('', False), ('27', False), ('-40', True),
    ('-40\nDoing analysis at TEMP = -40', True), ('-40\nDoing analysis at TEMP = 27', False), ('nan', False), ('inf', False)])
def test_actual_temperature_markers(markers, expected):
    assert declared.temperature_matches('Doing analysis at TEMP = ' + markers if markers else '', -40) is expected
