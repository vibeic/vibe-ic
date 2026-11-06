"""Step 32's later repairs keep the limits its repair_design set (cmp3 D14).

THE DEFECT. spm x gf180mcuD (D11+D7+D1): prestream_gate failed `sta_record` on
`u_core/wire51/Z` fanout 5 > 4. Inside Vibeic.PostRouteRepair (32-cand01)
repair_design had split net65 to the declared 4 loads; repair_antennas then put
diode ANTENNA_5 on it as its 5th load (a diode's pin is a load), and nothing
re-checked the cap. STAPostPNR saw it (fanout 4 -> 1 per corner), the closure
adopted it anyway because its DRV domain is a sum.

THE RULE. After the antenna phase, a net over MAX_FANOUT_CONSTRAINT that
repair_design had within it gets a bounded repair_design round in the same
step (its buffers legalized alone, their nets routed by the guarded ECO route);
whatever is still over refuses the candidate (LL_PRR_FANOUT_LIMIT_BROKEN). The
limit is never relaxed; with no declared cap nothing is claimed.

These tests run the SCRIPT'S OWN text -- from the post-ECO antenna census to
the end of re-verify, the same markers on main and on the fix -- under tclsh,
on a reduced odb with real pin directions.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
TCL = PROGRAMS / 'librelane_plugins' / 'librelane_plugin_vibeic' / 'postroute_repair.tcl'

START = 'set ::vic_ant_eco [check_antennas]\n'
END = 'if {$::vic_fillers > 0} {'

HARNESS = r'''
# pins: "inst/pin" -> {net io}; wires: net -> 0/1
array set ::PIN {}
array set ::W {}
set ::netnames [list]
set ::insts [list]
proc mknet {name {sig SIGNAL}} {
    lappend ::netnames $name
    set ::SIG($name) $sig
    set ::W($name) 1
    interp alias {} ::net_$name {} netcall $name
}
proc netcall {name method args} {
    switch -- $method {
        getName { return $name }
        getSigType { return $::SIG($name) }
        isSpecial { return [expr {$::SIG($name) in {POWER GROUND}}] }
        isDoNotTouch { return 0 }
        getITerms {
            set out [list]
            foreach k [lsort [array names ::PIN]] {
                if {[lindex $::PIN($k) 0] eq $name} { lappend out ::it_[string map {/ __} $k] }
            }
            return $out
        }
        getBTerms { return {} }
        isConnectedByAbutment { return 0 }
        getWire { return [expr {$::W($name) ? "wire_$name" : "NULL"}] }
        default { error "net $name: $method" }
    }
}
proc mkinst {name master pins} {
    lappend ::insts $name
    set ::MASTER($name) $master
    interp alias {} ::inst_$name {} instcall $name
    interp alias {} ::master_$name {} mastercall $name
    foreach {pin net io} $pins {
        set ::PIN($name/$pin) [list $net $io]
        interp alias {} ::it_${name}__$pin {} itcall $name/$pin
        interp alias {} ::mt_${name}__$pin {} mtcall $name/$pin
    }
}
proc instcall {name method args} {
    switch -- $method {
        getName { return $name }
        getMaster { return ::master_$name }
        getPlacementStatus { return PLACED }
        isDoNotTouch { return 0 }
        setPlacementStatus { return }
        getITerms {
            set out [list]
            foreach k [lsort [array names ::PIN $name/*]] { lappend out ::it_[string map {/ __} $k] }
            return $out
        }
        default { error "inst $name: $method" }
    }
}
proc mastercall {name method args} { return $::MASTER($name) }
proc itcall {key method args} {
    switch -- $method {
        getNet { return ::net_[lindex $::PIN($key) 0] }
        getInst { return ::inst_[lindex [split $key /] 0] }
        getIoType { return [lindex $::PIN($key) 1] }
        getMTerm { return ::mt_[string map {/ __} $key] }
        default { error "iterm $key: $method" }
    }
}
proc mtcall {key method args} { return [lindex $::PIN($key) 1] }
proc get_pins {args} { return [lindex $args end] }
proc get_nets {args} {
    set pin [lindex $args end]
    return ::net_[lindex $::PIN($pin) 0]
}
proc get_name {net} { return [string range $net 6 end] }
proc report_check_types {args} {
    set path [lindex $args end]
    set fh [open $path w]
    if {[info exists ::SLEW_OVER] && $::SLEW_OVER &&
        [lsearch -exact $args -max_slew] >= 0} {
        puts $fh "drv/Z 1.0 2.0 (VIOLATED)"
    }
    if {[info exists ::env(VIBEIC_PRR_MAX_FANOUT)]} {
        set cap $::env(VIBEIC_PRR_MAX_FANOUT)
        foreach net $::netnames {
            if {$::SIG($net) ne "SIGNAL"} { continue }
            set loads 0
            set driver ""
            foreach key [array names ::PIN] {
                if {[lindex $::PIN($key) 0] ne $net} { continue }
                if {[lindex $::PIN($key) 1] eq "OUTPUT"} { set driver $key }
                if {[lindex $::PIN($key) 1] in {INPUT INOUT}} { incr loads }
            }
            if {$driver ne "" && $loads > $cap} {
                puts $fh "$driver $cap $loads (VIOLATED)"
            }
        }
    }
    close $fh
}
proc blk {method args} {
    switch -- $method {
        getNets { return [lmap n $::netnames {set _ ::net_$n}] }
        getInsts { return [lmap i $::insts {set _ ::inst_$i}] }
        findNet {
            set n [lindex $args 0]
            return [expr {$n in $::netnames ? "::net_$n" : "NULL"}]
        }
        default { error "block: $method" }
    }
}
set ::block blk

# net `hot`: one driver, four loads -- at the declared cap of 4.
mknet hot
mknet VDD POWER
mkinst drv buf_4 {Z hot OUTPUT VDD VDD INOUT}
foreach l {l1 l2 l3 l4} { mkinst $l and2 [list A hot INPUT Z out_$l OUTPUT] }
# A switched supply: driven by a header, five consumers -- not STA fanout.
mkinst psw header {VOUT VDD OUTPUT}
foreach c {t1 t2 t3 t4 t5} { mkinst $c tap [list VDD VDD INPUT] }

# repair_antennas: a diode on `hot` (a 5th load); it takes that net's wire.
proc repair_antennas {args} {
    mkinst ANTENNA_1 diode {I hot INPUT}
    set ::W(hot) 0
}
# repair_design, when it can: a buffer that takes two of `hot`'s loads.
proc repair_design {args} {
    incr ::RD_CALLS
    if {!$::FIX} { return }
    mknet hot_b
    mkinst fbuf buf_1 {I hot INPUT Z hot_b OUTPUT}
    set ::PIN(l3/A) {hot_b INPUT}
    set ::PIN(l4/A) {hot_b INPUT}
    set ::W(hot_b) 0
}
set ::RD_CALLS 0
namespace eval grt { proc repaired_net_names {} { return {hot} } }
proc log_cmd {cmd args} {
    switch -- $cmd {
        repair_antennas { repair_antennas {*}$args }
        repair_design { repair_design {*}$args }
        default {}
    }
}
set ::ANT {2 0}
proc check_antennas {} { set v [lindex $::ANT 0]; set ::ANT [lrange $::ANT 1 end]; return $v }
proc append_if_exists_argument {args} {}
proc check_placement {args} {}
proc global_connect {args} {}
namespace eval utl { proc metric_integer {name value} { puts "METRIC $name $value" } }
proc vic_say {line} { puts "PRR: $line" }
proc vic_eco_route {varname tag} {
    upvar #0 $varname dirty
    puts "ROUTED $tag [lsort [dict keys $dirty]]"
    foreach n [dict keys $dirty] { set ::W($n) 1 }
    return 1
}
rename exit _exit
proc exit {{code 0}} { puts "EXIT $code"; _exit $code }

set ::env(DIODE_CELL) diode/I
set ::env(VIBEIC_PRR_ANTENNA_REPAIR) 1
set ::env(PL_MAX_DISPLACEMENT_X) 500
set ::env(PL_MAX_DISPLACEMENT_Y) 100
set ::env(STEP_DIR) [pwd]
set ::vic_ant_before 0
set ::vic_created [list]
set ::vic_unrouted_before [dict create]
set ::vic_fillers 0
set ::vic_changed 0
set ::rd_args [list -verbose]
'''


def _region(text, start, end):
    i = text.find(start)
    return '' if i < 0 else text[i:text.index(end, i)]


def run(tmp_path, *, cap='4', fix=True, baseline_over=False, slew_over=False):
    text = TCL.read_text()
    procs = (_region(text, '# ---- the fanout limit', '# ---- 4. repair')
             # D11's census procs, when the script carries them
             + _region(text, 'proc vic_needs_wire', '\n# ---- 0.'))
    section = text[text.index(START):text.index(END)]
    # LibreLane's MAX_FANOUT_CONSTRAINT is the PDK default (10) whatever the
    # SDC says; the cap the step must keep is the SDC's (VIBEIC_PRR_MAX_FANOUT).
    env = 'set ::env(MAX_FANOUT_CONSTRAINT) 10\n' + (
        '' if cap is None else f'set ::env(VIBEIC_PRR_MAX_FANOUT) {cap}\n')
    script = (HARNESS + env + f'set ::FIX {int(fix)}\n'
              + f'set ::SLEW_OVER {int(slew_over)}\n' + procs
              + ('mkinst l5 and2 {A hot INPUT}\n' if baseline_over else '')
              + ('set ::vic_fo_repaired [vic_fanout_over]\n'
                 if baseline_over else 'set ::vic_fo_repaired [dict create]\n')
              + section + 'puts "EXIT 0"\nputs "RD_CALLS $::RD_CALLS"\n')
    path = tmp_path / 'prr.tcl'
    path.write_text(script)
    return subprocess.run(['tclsh', str(path)], capture_output=True, text=True,
                          cwd=tmp_path, timeout=60)


# ── red on main ──────────────────────────────────────────────────────────────

def test_a_net_the_antenna_diode_pushed_over_the_cap_is_repaired_and_routed(tmp_path):
    out = run(tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert 'RD_CALLS 1' in out.stdout
    assert 'net(s) pushed over max_fanout 4 after repair_design: hot 5' in out.stdout
    routed = [ln for ln in out.stdout.splitlines() if ln.startswith('ROUTED drv_route ')]
    assert routed == ['ROUTED drv_route hot hot_b'], out.stdout
    assert 'METRIC vibeic__prr__fanout__added 0' in out.stdout
    assert 'METRIC vibeic__prr__fanout__rounds 1' in out.stdout


def test_a_candidate_still_over_the_cap_is_refused(tmp_path):
    out = run(tmp_path, fix=False)
    assert out.returncode == 1, out.stdout + out.stderr
    assert 'LL_PRR_FANOUT_LIMIT_BROKEN: 1 net(s) over max_fanout 4' in out.stderr
    assert 'hot 5' in out.stderr
    assert 'METRIC vibeic__prr__fanout__added 1' in out.stdout


def test_an_already_over_cap_net_cannot_gain_another_load(tmp_path):
    # repair_design left five loads on hot; antenna repair adds the sixth.
    # The old name-only comparison discarded this worsening from its dict.
    out = run(tmp_path, fix=False, baseline_over=True)
    assert out.returncode == 1, out.stdout + out.stderr
    assert 'hot 6' in out.stderr
    assert 'METRIC vibeic__prr__fanout__added 1' in out.stdout


def test_without_a_declared_cap_nothing_is_claimed_kept(tmp_path):
    out = run(tmp_path, cap=None)
    assert out.returncode == 0, out.stdout + out.stderr
    assert 'RD_CALLS 0' in out.stdout
    assert 'METRIC vibeic__prr__fanout__added -1' in out.stdout
    assert 'the SDC declares no set_max_fanout; not measured' in out.stdout


def test_without_a_fanout_cap_a_measured_slew_violator_gets_a_repair_round(tmp_path):
    out = run(tmp_path, cap=None, slew_over=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert 'RD_CALLS 1' in out.stdout
    assert 'measured post-antenna slew/capacitance repair' in out.stdout
    assert 'METRIC vibeic__prr__fanout__added -1' in out.stdout


def test_a_load_is_what_sta_counts(tmp_path):
    """The driver is not a load, a supply pin is not a load, a diode is."""
    text = TCL.read_text()
    procs = _region(text, '# ---- the fanout limit', '# ---- 4. repair')
    assert procs, 'the script carries no fanout instrument'
    script = (HARNESS + 'set ::env(VIBEIC_PRR_MAX_FANOUT) 4\n' + procs
              + 'puts "BEFORE [vic_fanout_over]"\n'
              + 'repair_antennas\n'
              + 'puts "AFTER [vic_fanout_over]"\n'
              + 'puts "ADDED [vic_fanout_added [dict create] [vic_fanout_over]]"\n')
    path = tmp_path / 'count.tcl'
    path.write_text(script)
    out = subprocess.run(['tclsh', str(path)], capture_output=True, text=True,
                         cwd=tmp_path, timeout=60)
    assert out.stdout.splitlines()[0].strip() == 'BEFORE', out.stdout + out.stderr
    assert 'AFTER hot 5' in out.stdout, out.stdout + out.stderr
    assert 'ADDED hot 5' in out.stdout




def test_the_repair_config_carries_the_exclusion(tmp_path, monkeypatch, capsys):
    """_prepare hands the step's own resolved repair config EXTRA_EXCLUDED_CELLS,
    which LibreLane turns into the resizer's set_dont_use (_PNR_EXCLUDED_CELLS)."""
    import importlib
    import json
    prr = importlib.import_module('librelane_postroute_repair')
    contract = importlib.import_module('librelane_contract')
    lib = tmp_path / 'pdkroot/pdkA/libs.ref/lib/std.lib'
    lib.parent.mkdir(parents=True)
    lib.write_text('library (std) {\n  cell ("std__buf_1") { }\n  cell ("std__dlyb_1") { }\n}\n')
    folder = tmp_path / 'proj/phase3/librelane/32-config'
    folder.mkdir(parents=True)

    def resolve(project, image, pdk, ids, *, pdk_root, folder, overlay, docker):
        out = {}
        for step in ids:
            path = project / 'phase3/librelane' / folder / f'{step}.json'
            body = {'meta': {'step': step}, 'STA_CORNERS': ['c1'],
                    'CELL_LIBS': {'*_tt': ['/pdk/pdkA/libs.ref/lib/std.lib']}}
            path.write_text(json.dumps(body))
            prr_views = path.with_name(path.stem + '.views.json')
            prr_views.write_text(json.dumps({'step': step, 'inputs': [], 'outputs': []}))
            out[step] = path
        return out
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(prr, 'signoff_scene_sdc', lambda sdc, out, *d: out)
    sdc = tmp_path / 'c.sdc'
    sdc.write_text('create_clock -period 10 clk\n')
    configs, _, _ = prr._prepare(tmp_path / 'proj', image='img', pdk='pdkA',
                                 pdk_root=tmp_path / 'pdkroot', sdc=sdc, derate=(0.95, 1.05),
                                 pg_rules_tcl=None, refill_tcl=None, docker='docker',
                                 dont_use=(lambda text: ['std__dlyb_1'] if 'dlyb' in text else [],
                                           'the rule under test'))
    repair = json.loads(configs[prr.REPAIR_STEP].read_text())
    assert repair['EXTRA_EXCLUDED_CELLS'] == ['std__dlyb_1']

    configs, _, _ = prr._prepare(tmp_path / 'proj', image='img', pdk='pdkA',
                                 pdk_root=tmp_path / 'pdkroot', sdc=sdc,
                                 derate=(0.95, 1.05), pg_rules_tcl=None,
                                 refill_tcl=None, docker='docker',
                                 dont_use=(lambda text: [], 'the rule under test'))
    repair = json.loads(configs[prr.REPAIR_STEP].read_text())
    provenance = json.loads(configs[prr.REPAIR_STEP].with_suffix(
        '.provenance.json').read_text())
    assert repair['EXTRA_EXCLUDED_CELLS'] == []
    assert 'no cell matched' in provenance['keys']['EXTRA_EXCLUDED_CELLS']
    assert 'LL_PRR_DONT_USE_EMPTY:' in capsys.readouterr().out


def test_the_cap_is_the_sdcs_not_librelanes_pdk_default(tmp_path):
    """cmp3 D14 review: L19 declared no MAX_FANOUT_CONSTRAINT, so LibreLane
    carried its PDK default 10, while the sign-off SDC said 4. The diode's
    5th load must be caught against 4."""
    out = run(tmp_path, cap='4')
    assert 'RD_CALLS 1' in out.stdout, out.stdout + out.stderr
    assert 'pushed over max_fanout 4' in out.stdout








def test_the_repair_config_carries_the_sdc_cap(tmp_path, monkeypatch):
    import importlib
    import json
    prr = importlib.import_module('librelane_postroute_repair')
    contract = importlib.import_module('librelane_contract')

    def resolve(project, image, pdk, ids, *, pdk_root, folder, overlay, docker):
        out = {}
        for step in ids:
            path = project / 'phase3/librelane' / folder / f'{step}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'meta': {'step': step}, 'STA_CORNERS': ['c1'],
                                        'MAX_FANOUT_CONSTRAINT': 10}))
            path.with_name(path.stem + '.views.json').write_text(
                json.dumps({'step': step, 'inputs': [], 'outputs': []}))
            out[step] = path
        return out
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(prr, 'signoff_scene_sdc', lambda sdc, out, *d: out)
    sdc = tmp_path / 'c.sdc'
    sdc.write_text('set_max_fanout 4 [current_design]\n')
    configs, _, _ = prr._prepare(tmp_path / 'proj', image='img', pdk='pdkA',
                                 pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                                 pg_rules_tcl=None, refill_tcl=None, docker='docker',
                                 max_fanout=(4, 'c.sdc: strictest of 1'))
    repair = json.loads(configs[prr.REPAIR_STEP].read_text())
    assert repair['VIBEIC_PRR_MAX_FANOUT'] == 4
