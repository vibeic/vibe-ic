import subprocess
import pytest
import phase3_one_shot_runner as p3

@pytest.mark.parametrize('net,load,lib,expected',[('NULL',0,'libpin',True),('wire',0,'libpin',False),('NULL',1,'libpin',False),('NULL',0,'NULL',False),('NULL',0,'',False)])
def test_native_object_evidence_is_required(tmp_path,net,load,lib,expected):
    report=tmp_path/'report';tcl=tmp_path/'query.tcl'
    tcl.write_text(f'set _f [open {{{report}}} w]\nset net {net}\nset load {load}\nset lib {{{lib}}}\n'+'''
proc get_cells {args} {return inst}
proc inst {method} {
 switch $method {is_leaf {return 1} liberty_cell {return master} pin_iterator {return iter}}
}
set emitted 0
proc iter {method} {
 switch $method {has_next {return [expr {!$::emitted}]} next {set ::emitted 1;return pin} finish {}}
}
proc pin {method} {
 switch $method {net {return $::net} is_driver {return 1} is_load {return $::load} liberty_port {return $::lib}}
}
proc get_full_name {obj} {return $obj}
'''+p3._sta_link_census_tcl()+'close $_f\n')
    p=subprocess.run(['tclsh',str(tcl)],capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    assert ('STA_UNCONNECTED_OUTPUT pin' in report.read_text())==expected
