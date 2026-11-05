from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formal_structural_check as fsc


@pytest.mark.parametrize('edge,expected', [('posedge', fsc.PASS), ('negedge', fsc.REFUTED)])
def test_unpacked_sv_structural_read_keeps_native_clock_verdict(tmp_path, edge, expected):
    if shutil.which('yosys') is None:
        pytest.skip('native yosys required')
    rtl = tmp_path / 'm.sv'
    rtl.write_text('module m(input clk,rst,input logic [3:0] d[2],'
                   'output logic [3:0] q[2]); always @(' + edge +
                   ' clk) if(rst) begin q[0]<=0; q[1]<=0; end '
                   'else begin q[0]<=d[0]; q[1]<=d[1]; end endmodule\n')
    result = fsc.check([rtl], 'm',
        [{'rule': 'clock_edge', 'signal': 'clk', 'value': 'posedge'}], tmp_path)
    assert result['verdict'] == expected, result
