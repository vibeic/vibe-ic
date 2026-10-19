"""Native SV configuration and comparison-versus-driver controls."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rtl_hygiene_lint as lint


@pytest.mark.parametrize('read', [
    "wire bounded=(phase<=4'd5);",
    "wire bounded=(phase[0]<=1'b1);",
    "wire bounded=(phase[0]<=1'b1)&&(phase[3:1]>=3'd1);",
])
def test_comparison_after_process_is_not_a_procedural_driver(read):
    source = f'''module sample(input clk, input [3:0] d, output [3:0] y);
    reg [3:0] q;
    always @(posedge clk) q <= d;
    wire [3:0] phase;
    {read}
    assign phase=q;
    assign y=phase & {{4{{bounded}}}};
    endmodule'''
    assert lint.rule_continuous_vs_procedural_driver(source, 'neutral.sv') == []


@pytest.mark.parametrize('write', [
    'phase <= d;', 'phase = d;',
    "if (d <= 4'd5) phase <= d; else phase <= 0;",
])
def test_real_procedural_write_keeps_mixed_driver_error(write):
    source = f'''module sample(input clk, input [3:0] d, output [3:0] y);
    reg [3:0] phase;
    always @(posedge clk) begin {write} end
    assign phase=d;
    assign y=phase;
    endmodule'''
    findings = lint.rule_continuous_vs_procedural_driver(source, 'neutral.sv')
    assert len(findings) == 1
    assert findings[0].symbol == 'phase' and findings[0].severity == 'ERROR'


@pytest.mark.parametrize('header', [
    'phase=0;phase<4;phase=phase+1',
    'q=0;q<4;phase=phase+1',
    'phase=0,q=0;q<4;q=q+1',
    'phase[1:0]=0;q<4;q=q+1',
])
def test_for_initializer_and_update_keep_actual_procedural_writes(header):
    source = f'''module sample(input clk, input [3:0] d, output [3:0] y);
    reg [3:0] phase, q;
    always @(posedge clk) for({header}) begin end
    assign phase=d;
    assign y=phase;
    endmodule'''
    findings = lint.rule_continuous_vs_procedural_driver(source, 'neutral.sv')
    assert any(f.symbol == 'phase' and f.severity == 'ERROR' for f in findings)


@pytest.mark.parametrize('header', [
    "q=0;phase<=4'd5;q=q+1",
    "q=phase<=4'd5;q<4;q=q+1",
    "q=0;q<4;q=phase<=4'd5",
])
def test_for_condition_and_rhs_comparison_are_reads(header):
    source = f'''module sample(input clk, input [3:0] d, output [3:0] y);
    reg [3:0] q;
    always @(posedge clk) for({header}) begin end
    wire [3:0] phase;
    assign phase=d;
    assign y=phase;
    endmodule'''
    assert lint.rule_continuous_vs_procedural_driver(source, 'neutral.sv') == []


@pytest.mark.parametrize('defines,constant', [
    ([], '0'), (['FEATURE'], None), (['SYNTHESIS'], '1'),
])
def test_native_sv_keeps_selected_top_parameter_and_defines(tmp_path, defines, constant):
    source = tmp_path / 'typed.sv'
    source.write_text('''package item_pkg; typedef logic [7:0] item_t; endpackage
    module sample import item_pkg::*; #(parameter int W=8)
      (input item_t a, output logic [W-1:0] y);
    `ifdef SYNTHESIS
      assign y='1;
    `elsif FEATURE
      assign y=W'(a);
    `else
      assign y='0;
    `endif
    endmodule
    ''')
    before = source.read_bytes()
    design = lint._native_driver_view([source], 'sample', defines, ['W=12'], [],
                                      tmp_path / 'native')
    module = design['modules']['sample']
    assert len(module['ports']['y']['bits']) == 12
    # Slang preserves a word-level buffer rather than aliasing output bits.
    # Read its actual input, requiring the exact output port binding.
    buffers = [cell for cell in module['cells'].values()
               if cell['type'] == '$buf'
               and cell['connections']['Y'] == module['ports']['y']['bits']]
    assert len(buffers) == 1
    driven_bits = buffers[0]['connections']['A']
    if constant is not None:
        assert driven_bits == [constant] * 12
    else:
        assert driven_bits[:8] == module['ports']['a']['bits']
        assert driven_bits[8:] == ['0'] * 4
    assert source.read_bytes() == before
    context_path, = (tmp_path / 'native').glob('native-elaboration-*/context.json')
    context = json.loads(context_path.read_text())
    assert context['status'] == 'MEASURED' and context['parameters'] == ['W=12']
    assert context['native_returncode'] == 0


def test_native_sv_syntax_error_stays_unmeasured(tmp_path):
    source = tmp_path / 'typed.sv'
    source.write_text('''package item_pkg; typedef logic [7:0] item_t; endpackage
    module sample import item_pkg::*; (input item_t a, output item_t y);
    assign y = ;
    endmodule
    ''')
    with pytest.raises(ValueError, match='native Yosys elaboration failed'):
        lint._native_driver_view([source], 'sample', [], [], [], tmp_path / 'native')
    context_path, = (tmp_path / 'native').glob('native-elaboration-*/context.json')
    context = json.loads(context_path.read_text())
    assert context['status'] == 'NOT_MEASURED' and context['native_returncode'] != 0


@pytest.mark.parametrize('name', ['has space.sv', 'semi;colon.sv'])
def test_native_sv_unrepresentable_path_refuses_before_launch(tmp_path, monkeypatch, name):
    source = tmp_path / name
    source.write_text('module sample(input a, output y); assign y=a; endmodule\n')
    calls = []
    monkeypatch.setattr(lint, '_native_driver_run', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='path token'):
        lint._native_driver_view([source], 'sample', [], [], [], tmp_path / 'native')
    assert calls == []
