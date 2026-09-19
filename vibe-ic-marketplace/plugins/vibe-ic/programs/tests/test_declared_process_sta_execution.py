import subprocess
from pathlib import Path
from test_declared_process_sta_producer import scene, p3


def test_stale_report_cannot_supply_missing_execution(scene,monkeypatch):
    s=scene;assert s['emit']()
    monkeypatch.setattr(p3,'_docker_exec',lambda *a,**k:(0,'',''))
    assert not s['emit']()


def test_error_diagnostic_with_zero_rc_refused(scene,monkeypatch):
    original=p3._docker_exec
    def run(*a,**k):
        original(*a,**k);return 0,'Error: link failed',''
    monkeypatch.setattr(p3,'_docker_exec',run)
    assert not scene['emit']()


def test_tcl_execution_with_neutral_command_stubs(scene,monkeypatch):
    s=scene
    prelude='''
proc read_liberty {args} {}
proc read_verilog {args} {}
proc link_design {args} {}
proc read_sdc {args} {}
proc read_spef {args} {}
proc all_clocks {} {return clk}
proc set_propagated_clock {args} {}
proc set_timing_derate {args} {}
proc get_cells {args} {return {neutral_cell}}
proc neutral_cell {method} {
 if {$method eq "is_leaf"} {return 1}
 if {$method eq "pin_iterator"} {return neutral_iterator}
 return neutral_master
}
proc neutral_iterator {method} {
 if {$method eq "has_next"} {return 0}
 return ""
}
proc get_full_name {obj} {return $obj}
proc report_parasitic_annotation {args} {
 set f [open [lindex $args end] a]
 puts $f "Found 0 unannotated drivers."
 puts $f "Found 0 partially unannotated drivers."
 close $f
}
proc report_checks {args} {}
proc report_check_types {args} {}
proc report_tns {args} {set f [open [lindex $args end] a]; puts $f "tns 0.0"; close $f}
proc report_worst_slack {flag redirect path} {
 set f [open $path a]; puts $f "worst slack [string range $flag 1 end] 0.5"; close $f
}
'''
    def run(container,cmd,**kw):
        script=Path(kw['marker']);wrapped=script.with_suffix('.fixture.tcl')
        wrapped.write_text(prelude+'\n'+script.read_text())
        p=subprocess.run(['tclsh',str(wrapped)],capture_output=True,text=True)
        return p.returncode,p.stdout,p.stderr
    monkeypatch.setattr(p3,'_docker_exec',run)
    assert s['emit']()
    text=s['rpt'].read_text()
    for c in ['SS','TT','FF']:
        for role in ['SETUP','HOLD']:assert f'=== {role} corner: process={c}' in text


def test_caller_refuses_failed_attempt_with_old_report(scene):
    import inspect,textwrap
    s=scene;s['rpt'].parent.mkdir(parents=True,exist_ok=True);s['rpt'].write_text('old report')
    source=Path(p3.__file__).read_text()
    block=source.split('    # --- Step 23: SPEF-based post-route STA (#527)')[1].split('    # --- TAPEOUT-SIGNOFF P1: multi-corner SPEF')[0]
    block=block[block.index('    spef_sta_rpt ='):]
    scope=dict(sta_out=s['rpt'].parent,spef_out=s['spef'],primary_def=s['spef'],project=s['tmp_path'],top='dut',pdk=s['pdk'],container='fixture',notes=[],written=[],rpt_phase3=s['tmp_path'],_signoff_regen=lambda *a:True,_emit_spef_sta=lambda *a:False)
    exec(textwrap.dedent(block),scope)
    assert not scope['spef_sta_ok']


def test_declared_aocv_not_silently_downgraded(scene,monkeypatch):
    monkeypatch.setattr(p3,'_discover_aocv_table',lambda *a:'declared.aocv')
    assert not scene['emit']()
    assert not scene['calls']


def test_execution_receipt_hashes_its_own_process_inputs(scene,monkeypatch):
    original=p3._docker_exec
    def run(*a,**k):
        c=Path(k['marker']).stem.rsplit('_',1)[1].upper()
        inputs={str(p) for p in k['inputs']}
        assert scene['by'][c] in inputs
        assert str(scene['tmp_path']/f'io__{c.lower()}_25C_1v00.lib') in inputs
        return original(*a,**k)
    monkeypatch.setattr(p3,'_docker_exec',run)
    assert scene['emit']()


import pytest
@pytest.mark.parametrize('success',[False,True])
def test_canonical_alias_tracks_current_attempt(scene,success):
    import textwrap
    s=scene;sta=s['rpt'].parent;sta.mkdir(parents=True,exist_ok=True)
    alias=sta/'post_route_timing.rpt';alias.write_text('# SPEF-BASED old complete')
    s['rpt'].write_text('fresh measured bytes')
    source=Path(p3.__file__).read_text()
    block=source.split('    # --- Step 23: post-route STA report (canonical)')[1].split('    # --- #527: estimate-vs-SPEF discrepancy')[0]
    block=block[block.index('    post_route_rpt ='):]
    scope=dict(sta_out=sta,spef_sta_attempt_ok=success,spef_sta_ok=success,spef_sta_rpt=s['rpt'],postroute_timing_repair_out=sta,spef_out=s['spef'],project=s['tmp_path'],primary_sta=sta/'absent',written=[],notes=[])
    exec(textwrap.dedent(block),scope)
    if success:assert 'fresh measured bytes' in alias.read_text()
    else:assert not alias.exists()
