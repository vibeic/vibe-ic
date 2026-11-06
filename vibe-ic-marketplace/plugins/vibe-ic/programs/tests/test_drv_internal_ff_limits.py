"""Keep FF state rows and resolve their declared limit through their cell."""
from __future__ import annotations


import pytest



_LIB = '''library (lib) {
 time_unit : "1ns"; capacitive_load_unit (1, pf);
 nom_process : 1; nom_voltage : 5; nom_temperature : 25;
 default_fanout_load : 1;
 cell (reg) {
  ff (IQ1, IQN1) { clocked_on : "CLK"; next_state : "D"; }
  pin (CLK) { direction : input; max_transition : 4; max_capacitance : 20; }
  pin (D) { direction : input; max_transition : 4; max_capacitance : 20; }
  pin (Q) { direction : output; function : "IQ1";
            max_transition : 4; max_capacitance : 20; }
 }
}'''








@pytest.mark.parametrize("case", ["quoted_ff", "description_latch"])
def test_ff_state_membership_requires_a_real_cell_group(tmp_path, monkeypatch, case):
    if case == "quoted_ff":
        model = _LIB.replace("ff (IQ1, IQN1)", 'ff ("IQ1", "IQN1")')
    else:
        model = _LIB.replace('ff (IQ1, IQN1) { clocked_on : "CLK"; next_state : "D"; }',
            'description : "example \\"quoted\\" ff (IQ1, IQN1) { ... } and {";\n'
            '  latch (IQ1, IQN1) { enable : "CLK"; data_in : "D"; }')
    from _drv_row_class import _liberty_limits
    states = _liberty_limits(model)["ff_states"]["reg"]
    if case == "quoted_ff":
        assert states == {"IQ1", "IQN1"}
    else:
        assert states == set()
