"""Actual retention bytes use the selected synchronous read and enable timing."""
import json
import pytest
import test_r48_the_reset_invariants_get_a_real_oracle as base

@pytest.mark.parametrize('good', [True, False], ids=['retained', 'first-edge-corruption'])
@pytest.mark.parametrize('protocol', ['sdp8_waddr_raddr_wdata_rdata_wen_ren_sync1r',
                                     'sdp8_waddr_raddr_wen_ren_sync1r',
                                     'sdp8_waddr_wdata_wen_raddr_rdata_sync1r'])
@pytest.mark.parametrize('role_style', ['long', 'short'])
def test_native_retention_selected_sync_read_enable(tmp_path, monkeypatch, good, protocol, role_style):
    original = base.prepare
    def prepare(project, good=False):
        rtl = original(project, good)
        rtl.write_text("""module sample_store(input i_clk, i_rst, input [7:0] i_store_rdata,
 output wire [2:0] o_store_raddr, o_store_waddr,
 output wire [7:0] o_store_wdata, output wire o_store_we, o_store_ren);
 reg [2:0] phase;
 reg pending;
 assign o_store_raddr = phase == 1 ? 3'd2 : 3'd3;
 assign o_store_waddr = 3'd2;
 assign o_store_wdata = 8'h3c;
 assign o_store_ren = phase == 1;
 assign o_store_we = pending MASK;
 always @(posedge i_clk) begin
   if(i_rst) begin phase <= 0; pending <= 0; end
   else begin
     phase <= phase + 1;
     pending <= phase == 2 && i_store_rdata == 8'hc7;
   end
 end
 endmodule
""".replace('MASK', '&& !i_rst' if good else ''))
        path = project / 'plugin_output/declaration.json'
        decl = json.loads(path.read_text())
        decl['sram_interface_protocol'] = protocol
        decl['sram_interface'].update(read_latency_cycles=1)
        if '_ren_' in protocol:
            decl['sram_interface']['read_enable'] = 'o_store_ren'
        if role_style == 'short':
            aliases = dict(read_address='raddr', write_address='waddr', read_data='rdata',
                           write_data='wdata', write_enable='we', read_enable='ren')
            decl['sram_interface'] = {aliases.get(key, key): value
                                      for key, value in decl['sram_interface'].items()}
        path.write_text(json.dumps(decl))
        l9 = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
        doc = json.loads(l9.read_text())
        doc['top_ports'].append({'name':'o_store_ren','direction':'output','width':1})
        l9.write_text(json.dumps(doc))
        return rtl
    monkeypatch.setattr(base, 'prepare', prepare)
    _, result = base._retention_native(tmp_path, good=good, diagnostic=False)
    case = result['execution']['cases'][0]
    assert case['state'] == ('passed' if good else 'failed'), result
    measured = case['reset_retention']['measurement']
    assert measured['complete'] and bool(measured['changed']) is not good
    assert measured['pending'] == {'address':2, 'before':'c7', 'data':'3c'}
    base._debt_stays_owed(result['consumer'])
