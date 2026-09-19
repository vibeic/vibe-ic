"""Neutral Tcl execution controls for actual owning emitter, no design/native STA."""
from pathlib import Path
import subprocess
import pytest
from test_declared_process_sta_producer import scene,p3

@pytest.fixture
def census(scene,monkeypatch):
 s=scene;state={'unlinked':False,'missing':0,'partial':0,'silent':False,'empty':False,'api_error':False}
 def run(container,cmd,**kw):
  path=Path(kw['marker']);tcl=path.read_text();s['calls'].append(tcl)
  pre='''
proc read_liberty {args} {}
proc read_verilog {args} {}
proc link_design {args} {}
proc read_sdc {args} {}
proc read_spef {args} {}
proc all_clocks {} {return clk}
proc set_propagated_clock {args} {}
proc set_timing_derate {args} {}
proc report_checks {args} {}
proc report_check_types {args} {}
proc get_cells {args} {if {$::empty} {return {}};return {core_inst io_inst}}
proc core_inst {method} {if {$method eq "is_leaf"} {return 1};if {$method eq "pin_iterator"} {return neutral_iterator};return core_master}
proc io_inst {method} {if {$method eq "is_leaf"} {return 1};if {$method eq "pin_iterator"} {return neutral_iterator};if {$::unlinked} {return NULL};return io_master}
proc neutral_iterator {method} {if {$method eq "has_next"} {return 0};return ""}
proc get_full_name {obj} {return $obj}
proc report_parasitic_annotation {args} {
 if {$::api_error} {error "annotation command failed"}
 set f [open [lindex $args end] a]
 puts $f "Found $::missing unannotated drivers."
 if {!$::silent} {puts $f "Found $::partial partially unannotated drivers."}
 close $f
}
proc report_tns {args} {
 set f [open [lindex $args end] a]
 if {[lindex $args 0] eq "-min"} {puts $f "tns min -0.25"} else {puts $f "tns max 0.00"}
 close $f
}
proc report_worst_slack {flag redirect path} {
 set f [open $path a];puts $f "worst slack [string range $flag 1 end] 0.5";close $f
}
'''
  pre='\n'.join('set '+k+' '+str(int(v)) for k,v in state.items())+'\n'+pre
  fixture=path.with_suffix('.stub.tcl');fixture.write_text(pre+tcl)
  p=subprocess.run(['tclsh',str(fixture)],capture_output=True,text=True)
  return p.returncode,p.stdout,p.stderr
 monkeypatch.setattr(p3,'_docker_exec',run)
 return s,state

def test_complete_census_and_hold_tns(census):
 s,state=census;assert s['emit']()
 text=s['rpt'].read_text()
 assert text.count('STA_LINK_CENSUS total=2 linked=2 missing=0')==3
 assert text.count('Found 0 unannotated drivers.')==3
 assert text.count('tns min -0.25')==3
 assert text.count('worst slack min 0.5')==3

@pytest.mark.parametrize('defect',['unlinked','missing','partial','silent','empty','api_error'])
def test_incomplete_coverage_refuses_publish(census,defect):
 s,state=census;state[defect]=1
 assert not s['emit']()
 assert not s['rpt'].exists()

def test_hold_query_is_explicit_min(census):
 s,state=census;assert s['emit']()
 for t in s['calls']:
  assert 'report_tns -min ' in t and 'report_tns -max ' in t
