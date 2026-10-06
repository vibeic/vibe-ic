"""Value-bearing controls for the step-32 extraction authority.

Only native process file writes are substituted. The real scene resolver,
SDC checks, Tcl generator and slack parser execute on captured SPEF values.
"""
import json
import subprocess
from pathlib import Path
import pytest
import _plugin_tree  # noqa: F401
import _native_postroute_timing as native
import librelane_contract as ll


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def setup_case(tmp_path, monkeypatch, *, cap=30, corruption=None):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    odb=tmp_path/'route.odb'; odb.write_text('native routed database')
    sdc=tmp_path/'route.sdc'; sdc.write_text('create_clock -period 20 [get_ports clk]\n')
    deff=tmp_path/'route.def'; deff.write_text('native routed DEF')
    nl=tmp_path/'route.v'; nl.write_text('module victim; endmodule')
    lib=tmp_path/'cells.lib'; lib.write_text('native cell liberty')
    rules=tmp_path/'rules.rcx'; rules.write_text('PDK extraction rules')
    cfg=put(tmp_path/'rcx.json',{'meta':{'step':'OpenROAD.RCX'},
        'DESIGN_NAME':'victim','STA_CORNERS':['nom_ss'],
        'RCX_RULESETS':{'nom_*':str(rules)},
        'CELL_LIBS':{'*':[str(lib)]},'DEFAULT_CORNER':'nom_ss'})
    state=put(tmp_path/'repair.json',{'odb':str(odb),'sdc':str(sdc),
        'def':str(deff),'nl':str(nl)})
    # Exercise the real Python producer/receipt writer; substitute only the
    # native file-writing boundary, as in the original value-bearing control.
    def rcx_writes(argv,**kwargs):
        folder=Path(argv[argv.index('-o')+1])
        before=json.loads(state.read_text());spef=folder/'native.spef'
        spef.write_text(f'*SPEF "IEEE 1481-1998"\n*DESIGN "victim"\n*C_UNIT 1 PF\n*D_NET victim {cap}\n'
                       f'*CAP\n1 victim:1 victim:2 {cap}\n*RES\n1 victim:1 victim:2 5\n*END\n')
        put(folder/'config.json',json.loads(cfg.read_text()))
        put(folder/'state_in.json',before)
        put(folder/'state_out.json',{**before,'spef':{'nom_*':str(spef)}})
        return subprocess.CompletedProcess(argv,0,'captured RCX boundary INPUT','')
    monkeypatch.setattr(ll,'image_capability',lambda *a,**k:{})
    monkeypatch.setattr(ll,'openroad_home',lambda *a,**k:None)
    monkeypatch.setattr(ll,'run_container',rcx_writes)
    folder=ll.run_chain(tmp_path,'captured native image',
        [('OpenROAD.RCX',cfg,state)],lane='rcx',pdk_root='/pdk')[0]
    spef=folder/'native.spef'
    out=json.loads((folder/'state_out.json').read_text())
    if corruption=='route':
        other=tmp_path/'other.odb';other.write_text('different native route');out['odb']=str(other)
    elif corruption=='missing_spef':spef.unlink()
    elif corruption=='ambiguous':out['spef']['*']=str(spef)
    elif corruption=='ground_only':spef.write_text('*C_UNIT 1 PF\n*D_NET victim 30\n*CAP\n1 victim:1 30\n*RES\n1 victim:1 victim:2 5\n*END\n')
    rcx=put(folder/'state_out.json',out)
    ctx={'project':str(tmp_path),'image':'captured native image','mounts':[],
         'configs':{'OpenROAD.RCX':str(cfg)},'corners':['nom_ss'],
         'derate':[.95,1.05],'rcx_state':str(rcx),'rcx_state_sha256':ll.digest(rcx)}
    seen=[]
    def native_writes(_ctx, script, output):
        body=script.read_text();seen.append(body)
        if script.name.startswith('extract_'):
            # The competing recipe produces an actually different capacitor.
            output.write_text('*C_UNIT 1 PF\n*D_NET victim 3\n*CAP\n1 victim:1 victim:2 3\n*END\n')
        else:
            tool_spef=f'read_spef {{{spef}}}' in body
            hold=-.04 if tool_spef and cap==30 else .2
            output.write_text(f'OCV_BASIS flat_ocv\nworst slack max 1.0\nworst slack min {hold}\n')
    monkeypatch.setattr(native,'_run',native_writes)
    return ctx,state,seen


def test_ss_hold_uses_the_native_rcx_capacitor(tmp_path,monkeypatch):
    ctx,state,seen=setup_case(tmp_path,monkeypatch)
    result=native.measure(ctx,state,tmp_path/'measure')
    assert result['hold_ws_min']==-.04
    assert not any('extract_parasitics' in text for text in seen)


def test_positive_same_input_control(tmp_path,monkeypatch):
    ctx,state,seen=setup_case(tmp_path,monkeypatch,cap=3)
    assert native.measure(ctx,state,tmp_path/'measure')['hold_ws_min']==.2


@pytest.mark.parametrize('corruption',['route','missing_spef','ambiguous','ground_only'])
def test_invalid_native_rcx_cannot_be_replaced_by_a_second_extraction(tmp_path,monkeypatch,corruption):
    ctx,state,seen=setup_case(tmp_path,monkeypatch,corruption=corruption)
    with pytest.raises(ll.Refusal,match='RCX'):
        native.measure(ctx,state,tmp_path/'measure')
    assert seen==[]


@pytest.mark.parametrize('corruption', [None, 'missing_receipt', 'changed_spef',
                                        'changed_route', 'stale_receipt'])
def test_direct_rcx_handoff_requires_the_original_producer_receipt(
        tmp_path, monkeypatch, corruption):
    # setup_case executes the real run_chain receipt writer. Its substituted
    # native file writes are a unit seam, not a new extraction/signoff claim.
    ctx, _, _ = setup_case(tmp_path, monkeypatch)
    state = Path(ctx['rcx_state'])
    payload = json.loads(state.read_text())
    source = Path(payload['spef']['nom_*'])
    if corruption == 'missing_receipt':
        (state.parent / 'vibeic_receipt.json').unlink()
    elif corruption == 'changed_spef':
        source.write_text(source.read_text() + '# changed after production\n')
    elif corruption == 'changed_route':
        Path(payload['odb']).write_text('another route after extraction')
    elif corruption == 'stale_receipt':
        config = state.parent / 'config.json'
        config.write_text(config.read_text() + ' ')
    dest, receipt = tmp_path / 'published.spef', tmp_path / 'handoff.json'
    if corruption is not None:
        with pytest.raises(ll.Refusal, match='LL_RCX_OUTPUT_UNBOUND'):
            ll.handoff_to_direct(state, {'spef:nom_*': dest}, receipt)
        assert not dest.exists()
        assert not receipt.exists()
        return
    result = ll.handoff_to_direct(state, {'spef:nom_*': dest}, receipt)
    producer = json.loads((state.parent / 'vibeic_receipt.json').read_text())
    row = result['views']['spef:nom_*']
    expected = producer['sha256'][str(source.relative_to(state.parent))]
    assert expected and row['source_sha256'] == row['dest_sha256'] == expected
    assert dest.read_bytes() == source.read_bytes()
    assert json.loads(receipt.read_text()) == result
