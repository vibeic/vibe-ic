// manifest_metrics.mjs — required-metric declaration for the result manifest.
//
// WHY THIS EXISTS (measured, not theoretical)
// -------------------------------------------
// `eda_sta` returned success:true and wrote manifest `status:"PASS"` while
// openroad exited 0 having linked NO design at all (read_verilog ORD-2010,
// link_design STA-1570, every report STA-1571). The manifest looked only at
// `result.success`, and the `wns`/`tns` values it recorded were `null` because
// the parse found nothing to parse. A run that measured NOTHING was recorded as
// a proven-good run. `sta_mcorner` has the same shape: with every corner's wns
// null, `timing_met` is null, `overall_pass` is never set false, and the
// manifest records PASS for corners nobody measured.
//
// THE RULE, copied in spirit from OpenROAD-flow-scripts checkMetadata.py
// (a required metric that is ABSENT is a hard stop, not a default): a manifest
// may record `status:"PASS"` only when the metrics that prove the work happened
// are present. Absent -> INCONCLUSIVE. Never PASS.
//
// THREE STATES, and the third one is the whole point:
//   PASS          the work happened and the metrics that prove it are present.
//   FAIL          the work happened and the result is bad.
//   INCONCLUSIVE  we did not measure it. NOT a pass — recording an unproven
//                 result as proven is the defect this file exists to stop. NOT
//                 a fail either — the design may be perfectly fine and we
//                 simply have no measurement; rendering unmeasured as bad is
//                 the same lie pointed the other way, and a manifest that is
//                 all red gets ignored.
//
// NOTE ON WHAT THIS IS NOT: this does not scrape logs for error patterns.
// OpenROAD-flow-scripts, LibreLane and OpenSTA between them contain ZERO log
// error-pattern scrapers; all three gate on an exit code made to tell the truth
// plus the presence of required metrics. Presence of a measurement is the
// signal here — never the absence of a scary word in a log.
//
// HOW A STEP EARNS AN ENTRY IN THIS TABLE: the metric must be (a) the quantity
// the tool exists to produce — the thing a reviewer would look at to believe
// the step ran — and (b) emitted by a code path that can yield null/undefined
// when the tool did no work. A step with no entry here is not gated: silence
// means "no metric has been declared for this step yet", never "this step is
// exempt". Adding a step here is always allowed; removing one is the change
// that needs a reason.

export const INCONCLUSIVE = "INCONCLUSIVE";

// Default presence test. A metric is PRESENT if it is neither null nor
// undefined. Note that `0` and `false` are present — a measured zero is a
// measurement, and treating it as absent would turn a genuinely clean result
// into INCONCLUSIVE.
const present = (v) => v !== null && v !== undefined;

// Every corner of a multi-corner STA must carry a real wns. One corner that
// silently produced nothing is a corner nobody measured, and the aggregate
// `overall_pass` cannot see it (null is not `false`).
const everyCornerMeasured = (v) => {
  if (v === null || v === undefined || typeof v !== "object") return false;
  const corners = Object.values(v);
  if (corners.length === 0) return false;
  return corners.every((c) => c && present(c.wns));
};

export const REQUIRED_METRICS = {
  // The measured bug. `wns`/`tns` null == OpenSTA reported no timing at all.
  sta: [{ key: "wns" }, { key: "tns" }],
  // Same bug, aggregated over corners.
  sta_mcorner: [{ key: "corners", present: everyCornerMeasured }],
  // Yosys cell count — a synthesis that mapped nothing has no cell count.
  synthesis: [{ key: "cells" }],
  // OpenROAD slack; `timing_met` null means the slack line was never found.
  place_and_route: [{ key: "slack_ns" }, { key: "timing_met" }],
  // KLayout cell count of the written stream -- AND the placed-instance count of
  // the design's own top cell. `cells` alone is ~98% PDK library (456 for a real
  // 28-instance chip, 447 for the same DEF with COMPONENTS emptied), so it was
  // satisfied by an EMPTY DIE. `top_insts` is the design-sized quantity; absent
  // it, a gds_generation PASS proves only that KLayout ran.
  gds_generation: [{ key: "cells" }, { key: "top_insts" }],
  // ATPG numbers — a PASS with no coverage number proves no ATPG.
  dft: [{ key: "coverage_pct" }, { key: "scan_chain_length" }, { key: "test_vectors" }],
  // cocotb test count — a run with no tests is not a passing run.
  cocotb: [{ key: "tests_total" }],
  // Magic extraction output size.
  extraction: [{ key: "size_bytes" }],
  // KLayout DRC violation count — a PASS with no count counted nothing.
  drc: [{ key: "violations" }],
};

// Names of the required metrics that are ABSENT from `entry`, in declaration
// order. Empty array == nothing missing (including for a step with no
// declaration, which is not gated).
export function missingRequiredMetrics(entry) {
  if (!entry || typeof entry !== "object") return [];
  const specs = REQUIRED_METRICS[entry.step];
  if (!specs) return [];
  const missing = [];
  for (const spec of specs) {
    const ok = spec.present || present;
    if (!ok(entry[spec.key])) missing.push(spec.key);
  }
  return missing;
}

// Apply the rule. Only `PASS` is downgraded: FAIL stays FAIL, and every other
// status a tool writes (TIMING_VIOLATED, SPEC_FAIL, DEFERRED, ...) is its
// author's own verdict and is passed through untouched.
export function gateManifestEntry(entry) {
  if (!entry || typeof entry !== "object") return entry;
  if (entry.status !== "PASS") return entry;
  const missing = missingRequiredMetrics(entry);
  if (missing.length === 0) return entry;
  return {
    ...entry,
    status: INCONCLUSIVE,
    missing_metrics: missing,
    inconclusive_reason:
      `step "${entry.step}" reported success but the required metric(s) ` +
      `${missing.join(", ")} are absent — the run proves nothing, so it is ` +
      `recorded as INCONCLUSIVE (not PASS, and not FAIL).`,
  };
}
