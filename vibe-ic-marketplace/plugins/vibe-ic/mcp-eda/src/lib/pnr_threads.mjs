// pnr_threads.mjs — MCP-side port of phase3_one_shot_runner.py
// `_openroad_thread_count` (G-ANTENNA-REROUTE). OpenROAD DEFAULTS TO 1 THREAD,
// so a PnR Tcl with no `set_thread_count` runs `global_route` + `detailed_route`
// + EVERY antenna-diode reroute round SINGLE-THREADED on a many-core host — the
// measured wall that blew the per-step cap before GDS (subservient/commercial PDK: main
// detailed_route ~858 s + ~394 s PER antenna reroute round single-threaded; the
// same steps at 8 threads: 211 s + 74 s/round). The reroute was ALREADY dirty-net
// incremental; the wall was purely single-threaded execution.
//
// Machine property only (host CPUs) — chip/PDK-AGNOSTIC. Mirrors the Python
// helper so the primary (phase3 runner) and secondary (MCP eda_pnr) PnR paths
// parallelize identically. `VIBEIC_OPENROAD_THREADS` (positive int, or "max")
// overrides — e.g. to bound oversubscription on a shared CI box.

import { cpus } from "node:os";

/**
 * Resolve the OpenROAD PnR thread count: all host CPUs by default, overridable
 * via the VIBEIC_OPENROAD_THREADS env var (a positive integer, or "max").
 * @returns {number} a positive integer thread count.
 */
export function openroadThreadCount() {
  const env = (process.env.VIBEIC_OPENROAD_THREADS || "").trim();
  if (env) {
    if (env.toLowerCase() === "max") {
      return (cpus() || []).length || 4;
    }
    const n = parseInt(env, 10);
    if (Number.isInteger(n) && n > 0) {
      return n;
    }
  }
  return (cpus() || []).length || 4;
}

/**
 * Emit the `set_thread_count N` Tcl line (with trailing newline) that MUST lead
 * a PnR Tcl so it governs the whole routing session. Never empty (unlike the
 * phase3 legacy test-default): the MCP path always parallelizes.
 * @returns {string}
 */
export function threadCountTcl() {
  return `set_thread_count ${openroadThreadCount()}\n`;
}
