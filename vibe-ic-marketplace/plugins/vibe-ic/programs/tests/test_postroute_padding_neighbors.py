"""Exercise production legalization and ECO collection with a movable neighbor."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_padding_can_move_neighbor_and_reroutes_its_signal_net(tmp_path):
    tclsh = shutil.which('tclsh')
    if not tclsh:
        pytest.skip('Tcl interpreter required')
    source = (Path(__file__).parents[1] / 'librelane_plugins' /
              'librelane_plugin_vibeic/postroute_repair.tcl').read_text()
    section = source[source.index('# ---- 6. legalize'):source.index('# The nets that share a violation')]
    setup = r'''
proc source {args} {}
set ::env(SCRIPTS_DIR) unused
set ::env(PL_MAX_DISPLACEMENT_X) 500
set ::env(PL_MAX_DISPLACEMENT_Y) 100
set ::locked 0
set ::moved 0
set ::block block
set ::vic_created {created}
set ::vic_resized {}
set ::vic_at [dict create neighbor {0 0 R0} fixed {0 0 R0}]
proc block {method} {return {created neighbor fixed}}
proc created {method} {
    switch $method {
        getName {return created}
        getITerms {return created_it}
    }
}
proc fixed {method args} {
    switch $method {
        getName {return fixed}
        getPlacementStatus {return LOCKED}
        setPlacementStatus {error "genuinely fixed instance must stay fixed"}
        getLocation {return {0 0}}
        getOrient {return R0}
    }
}
proc neighbor {method args} {
    switch $method {
        getName {return neighbor}
        getPlacementStatus {return [expr {$::locked ? "LOCKED" : "PLACED"}]}
        setPlacementStatus {set ::locked [expr {[lindex $args 0] eq "LOCKED"}]}
        getLocation {return [list $::moved 0]}
        getOrient {return R0}
        getITerms {return neighbor_it}
    }
}
foreach name {created neighbor} {
    proc ${name}_it {method} [string map [list NAME $name] {
        if {$method eq "getNet"} {return NAME_net}
        if {$method eq "getSigType"} {return SIGNAL}
    }]
    proc ${name}_net {method} [string map [list NAME $name] {
        if {$method eq "getName"} {return NAME_net}
        if {$method eq "getSigType"} {return SIGNAL}
    }]
}
proc log_cmd {command args} {
    if {$command ne "detailed_placement"} {error "unexpected command"}
    if {[lindex [lindex $args 1] 0] != 500 || [lindex [lindex $args 1] 1] != 100} {
        error "placement limits changed"
    }
    if {!$::locked} {set ::moved 1}
}
proc check_placement {args} {if {!$::moved} {error "DPL-0033 padding check failed"}}
namespace eval utl {proc metric_integer {args} {}}
proc set_global_connections {} {}
proc global_connect {} {}
proc vic_say {args} {}
'''
    checks = r'''
if {$::vic_moved ne "neighbor"} {error "movable neighbor was not recorded"}
if {[lsort [dict keys $::vic_dirty]] ne "created_net neighbor_net"} {
    error "the moved neighbor's route was not included"
}
puts PADDING_AND_ECO_NEIGHBOR_OK
'''
    script = tmp_path / 'exercise.tcl'
    script.write_text(setup + section + checks)
    result = subprocess.run([tclsh, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PADDING_AND_ECO_NEIGHBOR_OK' in result.stdout
