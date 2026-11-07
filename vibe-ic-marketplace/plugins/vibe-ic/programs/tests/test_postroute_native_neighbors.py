import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('outcome', ['clear', 'violations', 'tool_error'])
def test_native_repair_can_route_neighbors_and_still_requires_zero_drc(tmp_path, outcome):
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        pytest.skip('Tcl interpreter is required')
    source = (Path(__file__).parents[1] / 'librelane_plugins/librelane_plugin_vibeic/'
              'postroute_repair.tcl').read_text()
    body = source[source.index('proc vic_violation_neighbours '):
                  source.index('\nset ::vic_eco_attempts 0\n')]
    prefix = r'''
proc vic_say {message} {puts $message}
proc vic_routed_nets {} {return [dict create signal 1]}
proc vic_lost_routes {before} {return [dict create]}
proc vic_needs_wire {net} {return 0}
proc set_thread_count {threads} {puts "THREADS $threads"}
proc source {path} {puts "GLOBAL_SCRIPT $path"}
proc signal {method} {return wire}
namespace eval odb {proc dbWire_destroy {wire} {puts "REMOVE $wire"}}
proc log_cmd {command args} {
    puts "NATIVE $command $args"
    set index [lsearch -exact $args -output_drc]
    set path [lindex $args [expr {$index+1}]]
    set output [open $path w]
    # A fixed neighboring wire prevents closure in the scoped backend.
    if {$::env(OUTCOME) eq "violations" || [lsearch -exact $args -nets] >= 0} {
        puts $output "violation type: Spacing"
    }
    close $output
    if {$::env(OUTCOME) eq "tool_error"} {error "Native route refused"}
}
set ::env(SCRIPTS_DIR) scripts
set ::env(DRT_THREADS) 4
set ::env(DRT_OPT_ITERS) 64
set ::env(VIBEIC_PRR_ECO_EXPANSIONS) 2
set ::vic_routed_before [dict create signal 1]
set ::dirty [dict create signal signal]
set ::vic_eco_attempts 0
'''
    script = tmp_path / 'repair.tcl'
    script.write_text(prefix + body + '\nputs "ACCEPTED [vic_eco_route ::dirty repair]"\n')
    result = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
        env={**os.environ, 'OUTCOME': outcome, 'STEP_DIR': str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert f'ACCEPTED {int(outcome == "clear")}' in result.stdout
    native = next(line for line in result.stdout.splitlines() if line.startswith('NATIVE '))
    assert '-droute_end_iter 64' in native
    assert '-or_seed 42' in native
    assert '-nets' not in native
