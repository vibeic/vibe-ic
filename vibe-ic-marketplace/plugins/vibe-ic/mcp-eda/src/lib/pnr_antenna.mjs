// pnr_antenna.mjs — MCP-side port of phase3_one_shot_runner.py
// `_antenna_repair_tcl` (v1.3.46). The MCP `eda_pnr` tool is the SECONDARY
// (agentic) PnR path and emits its OWN OpenROAD Tcl; before v1.3.53 it ran a
// bare `detailed_route` with NO antenna repair, so it lacked the incremental
// repair->reroute->repair loop the phase3 runner already ships. This module
// closes that PARITY gap: it returns the SAME loop shape so both PnR paths
// behave identically.
//
// The exact sequence (mirrors phase3, do NOT drift):
//   (1) `repair_antennas` (the `grt` module command) CANNOT itself re-route to
//       realize its jumpers/diodes. Asking it to iterate (`-iterations N` with
//       N>1) trips GRT-0121 ("repair_antennas can only be run once; you must
//       re-route detailed and repeat"). So exactly ONE repair pass per turn
//       (`-iterations 1`) and WE re-route between passes.
//   (2) A FULL global_route before that reroute rebuilds the whole route graph
//       and forces the following detailed_route to re-route EVERY net
//       (~1900 nets on a large design -> timeout). It is therefore DROPPED. A
//       bare `repair_antennas -iterations 1` marks ONLY the nets it touched
//       (diode/jumper nets) dirty, so the incremental `detailed_route` re-routes
//       ONLY those dirty nets.
//   (3) The only faithful antenna measurement is IN-SESSION on the realized
//       routing (a re-read_def loses the routing -> ANT-0008). So `check_antennas`
//       runs directly on the live detailed route each turn.
//
// The diode master is supplied by the caller from the PDK config (chip-AGNOSTIC,
// NOT hardcoded here); when the PDK declares no antenna diode cell the step is
// SKIPPED (the design is left for a manual diode ECO rather than silently
// "passing").

/**
 * Emit the OpenROAD Tcl block that repairs process-antenna violations after the
 * main detailed_route, as a pure string so the silicon-critical sequence is
 * pinned by a regression test (same doctrine as the phase3 runner).
 *
 * @param {string|null|undefined} diodeCell  Antenna diode master from the PDK
 *   config (e.g. sky130_fd_sc_hd__diode_2). Falsy -> emit the SKIP marker.
 * @returns {string} Tcl block ending in `puts "ANTENNA_POSTROUTE_DONE"`.
 */
export function antennaRepairTcl(diodeCell) {
  if (!diodeCell) {
    return 'puts "ANTENNA_REPAIR_SKIPPED: no diode cell for this PDK; ' +
           'antenna violations need manual diode ECO"';
  }
  return `# Cheap read-only precheck on the realized main route (no full reroute):
set _ant_pre -1
if {[catch {set _ant_pre [check_antennas]} _ape]} { puts "ANTENNA_PRECHECK_NONFATAL: $_ape" }
if {$_ant_pre == 0} {
  # Already antenna-clean after the main route — skip the expensive
  # repair+reroute. The precheck's own ANT-0002/ANT-0001 (0/0) are the
  # shippable result; no reroute ran, so the main route is untouched.
  puts "ANTENNA_ALREADY_CLEAN: 0 net violations, skipping repair+reroute"
} else {
  # v1.3.53 R9 (mirror of phase3 _antenna_repair_tcl v1.3.46) — INCREMENTAL
  # repair->reroute->repair OUTER loop with NO full global_route:
  #   (a) repair_antennas in the grt module CANNOT itself re-route; asking it
  #       to (\`-iterations N>1\`) trips GRT-0121. So ONE repair pass at a time
  #       (-iterations 1) and re-route between passes OURSELVES.
  #   (b) a FULL global_route here rebuilds the whole route graph and forces the
  #       next detailed_route to re-route EVERY net (timeout). We DROP it:
  #       repair_antennas marks ONLY the diode/jumper nets dirty, and
  #       detailed_route (hasInitialRouting) then re-routes ONLY those dirty
  #       nets (incremental). The loop converges the residual, never full-reroutes.
  set _ant_cap 6
  for {set _i 0} {$_i < $_ant_cap} {incr _i} {
    set _nv -1
    if {[catch {set _nv [check_antennas]} _ac]} {
      puts "ANTENNA_LOOP_CHECK_NONFATAL: $_ac"
      break
    }
    if {$_nv == 0} {
      puts "ANTENNA_LOOP_CONVERGED: iter=$_i"
      break
    }
    # -iterations 1: ONE repair pass (no GRT-0121); diode nets marked dirty.
    if {[catch {repair_antennas ${diodeCell} -iterations 1} _ra_err]} {
      puts "REPAIR_ANTENNA_NONFATAL: $_ra_err"
      break
    }
    puts "REPAIR_ANTENNA_DONE: diode=${diodeCell} iter=$_i"
    # INCREMENTAL reroute — re-routes ONLY the dirty nets, not the whole design.
    if {[catch {detailed_route -verbose 0} _ra_dr]} {
      puts "REPAIR_ANTENNA_REROUTE_NONFATAL: $_ra_dr"
      break
    }
  }
  # Authoritative in-session post-repair antenna check.
  if {[catch {check_antennas} _ra_chk]} { puts "ANTENNA_POSTROUTE_CHECK_NONFATAL: $_ra_chk" }
}
puts "ANTENNA_POSTROUTE_DONE"`;
}
