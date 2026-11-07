"""Run the production ECO loop on native OpenDB objects, with controlled routing."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('restore_wire', [True, False])
def test_native_odb_eco_wire_lifecycle(tmp_path, restore_wire):
    tool = shutil.which('openroad')
    if not tool:
        pytest.skip('native OpenROAD required')
    source = (Path(__file__).parents[1] / 'librelane_plugins' /
              'librelane_plugin_vibeic/postroute_repair.tcl').read_text()
    start = source.index('proc vic_eco_route {')
    procedure = source[start:source.index('\n}\n', start) + 3]
    common = tmp_path / 'openroad/common'
    common.mkdir(parents=True)
    (common / 'grt.tcl').write_text('# Controlled global router transport\n')
    script = tmp_path / 'exercise.tcl'
    script.write_text(procedure + r'''
set db [ord::get_db]
set tech [odb::dbTech_create $db neutral]
set chip [odb::dbChip_create $db $tech]
set block [odb::dbBlock_create $chip neutral]
set ::net [odb::dbNet_create $block changed]
set retained [odb::dbNet_create $block retained]
odb::dbWire_create $::net
set retained_wire [odb::dbWire_create $retained]
set ::vic_routed_before [dict create changed $::net retained $retained]
set ::dirty [dict create changed $::net]
set ::vic_eco_attempts 0
set ::env(DRT_THREADS) 1
set ::env(DRT_OPT_ITERS) 1
set ::env(VIBEIC_PRR_ECO_EXPANSIONS) 0
set ::env(SCRIPTS_DIR) [file dirname [info script]]
set ::env(STEP_DIR) [file dirname [info script]]
proc vic_routed_nets {} { return $::vic_routed_before }
proc vic_lost_routes {expected} {
    set lost {}
    dict for {name net} $expected {
        if {[$net getWire] eq "NULL"} { dict set lost $name $net }
    }
    return $lost
}
proc vic_needs_wire {net} { return 1 }
proc vic_say {message} { puts $message }
proc vic_drc_count {path} { return 0 }
proc log_cmd {cmd args} {
    if {$cmd ne "detailed_route"} { error "unexpected command" }
    if {[$::net getWire] ne "NULL"} { error "old wire was not removed" }
    if {[lsearch -exact $args -nets] >= 0} {
        error "native detailed router must be able to repair neighboring geometry"
    }
    if {$::restore_wire} { odb::dbWire_create $::net }
    set path [lindex $args [expr {[lsearch $args -output_drc]+1}]]
    close [open $path w]
}
''' + f'\nset ::restore_wire {int(restore_wire)}\n' + r'''
set outcome [vic_eco_route ::dirty eco_route]
if {$outcome != $::restore_wire} { error "wrong route verdict: $outcome" }
if {[$retained getWire] ne $retained_wire} { error "untouched route changed" }
if {$::vic_eco_attempts != 1} { error "unexpected retries" }
puts "NATIVE_ECO_LIFECYCLE_OK"
exit
''')
    result = subprocess.run([tool, '-exit', '-no_splash', str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'NATIVE_ECO_LIFECYCLE_OK' in result.stdout
