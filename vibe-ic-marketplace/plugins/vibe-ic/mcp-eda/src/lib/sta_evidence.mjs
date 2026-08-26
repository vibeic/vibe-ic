// sta_evidence.mjs — decide whether an OpenSTA/OpenROAD run produced EVIDENCE
// of a real timing analysis, rather than merely failing to say otherwise.
//
// WHY THIS FILE EXISTS — two measured bugs
// ----------------------------------------
// (1) `eda_sta` returned success:true and wrote a manifest status:"PASS" while
//     openroad exited 0 having linked NO design at all (read_verilog ORD-2010,
//     link_design STA-1570, every report STA-1571).
// (2) On a clockless netlist the tool synthesises `create_clock -name clk
//     [get_ports clk]`; OpenSTA only WARNS (STA-0366), still builds a
//     source-less clock, and prints `wns max 0.00` — byte-identical to a
//     genuinely clean result.
//
// This module is the SECOND and THIRD independent channel of evidence. It is
// deliberately NOT the primary one: the primary gate is an exit code that has
// been made to tell the truth (script written to a FILE so `-exit` applies)
// plus a positive assertion trio. Each channel here was measured to be
// individually insufficient, which is exactly why they are conjoined.
//
// WHAT THIS MODULE DELIBERATELY DOES NOT DO
// -----------------------------------------
// It does not scrape the log for error patterns. OpenROAD-flow-scripts,
// LibreLane and OpenSTA were all read end to end and NONE of them does that —
// zero occurrences across all three trees. Log scraping is the wrong answer
// that looks right. Every term below is a structured value: a process exit
// code, or a number the tool itself wrote into a machine-readable metrics file.
//
// ═════════════════════════════════════════════════════════════════════════
// MEASURED EVIDENCE (openroad 26Q3-1797-g1c09d62b96, image digest
// sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16)
// ═════════════════════════════════════════════════════════════════════════
//
// A. THE EXIT CODE AND THE ERROR COUNT DISAGREE, IN BOTH DIRECTIONS.
//
//    openroad -exit -metrics a.json bad.tcl      -> rc=1, flow__errors__count=0
//    openroad -exit -metrics b.json < bad.tcl    -> rc=0, flow__errors__count=4
//
//    The file-script form aborts Tcl at the first error, so the error counter
//    never accumulates and reports 0 on a run that plainly failed. The stdin
//    form keeps going, so it accumulates a truthful error count but `-exit`
//    never applies and the process exits 0.
//
//    Neither number is trustworthy alone. `exitCodeOk` alone would pass case B;
//    `errors == 0` alone would pass case A. Only the conjunction rejects both.
//    THIS IS WHY `evaluateStaEvidence` REQUIRES EVERY TERM, AND WHY
//    `test_sta_evidence_and_conjunction.py` fails if any term is dropped.
//
// B. THE METRICS FILE CAN BE ABSENT, AND ABSENT IS NOT "ZERO ERRORS".
//
//    It was an open question whether OpenROAD flushes the `-metrics` JSON when
//    a run aborts mid-stage. Measured answer: on an ordinary Tcl abort it DOES
//    — the file is present and is complete, valid JSON (92 bytes) even though
//    the script died on its first command. But the file is genuinely ABSENT in
//    at least two real situations:
//
//      unwritable metrics path -> rc=1, [WARNING UTL-0010], no file
//      SIGKILL mid-run         -> rc=137,                   no file
//
//    So a missing metrics file means UNMEASURED. It must never be read as
//    "zero errors". This follows ORFS `checkMetadata.py:103-111`, which
//    `sys.exit(1)`s immediately on a missing required metric. It deliberately
//    does NOT follow LibreLane's `checker.py:130-135`, which only warns on a
//    missing metric — that is the anti-pattern, not the model.
//
// C. THE LINKAGE QUANTITY: WHY PORT COUNT AND NOT INSTANCE COUNT.
//
//    ORFS has `constraints__clocks__count` with `"compare": "=="`, but
//    `genMetrics.py:145-168` TEXT-PARSES `create_clock` lines out of the SDC
//    file. A `create_clock` matching no port still counts as 1, so ORFS would
//    NOT catch bug (2). The rule therefore has to sit on a quantity that only
//    a genuinely LINKED design can produce, never an SDC-derived one.
//
//    Four candidates were measured on three designs. The third design is the
//    control: a legitimately tiny but completely real block whose outputs are
//    constants, which must NOT be flagged.
//
//      quantity          real flop design   constant-output block   unlinked
//      ----------------  -----------------  ----------------------  --------
//      instance count            2                    0             absent
//      pin count                 6                    0             absent
//      register count            1                    0             absent
//      endpoint count            1                    0             absent
//      PORT COUNT                4                    2             absent
//
//    Instance, pin, register and endpoint counts are all 0 for the constant
//    block. A rule on any of them is not a linkage test, it is a SIZE test,
//    and it red-flags a real design. Port count is the only candidate that is
//    >= 1 for every linkable top module — a top module with no ports is not a
//    design — while still being unobtainable without a link: on the unlinked
//    run `get_ports *` itself raises, the `utl::metric_integer` call never
//    executes, and the metric is simply ABSENT from the JSON. Absent is a
//    FAIL by rule B, so the vacuous run is rejected.
//
//    Port count is also structurally immune to bug (2): nothing an SDC does
//    can create a port.
//
// D. THE GUARD ON sta_continue_on_error.
//
//    Measured: the current tree leaves `::sta_continue_on_error` at 0. With it
//    set to 1, a FILE script whose link fails exits rc=0 — i.e. even a correct
//    `-exit` would report success. That is why it is guarded at the source by
//    `programs/sta_continue_on_error_guard.py` rather than only here.

/**
 * The metric the tool asks OpenROAD to count errors with. OpenROAD writes this
 * itself; we never compute it.
 */
export const STA_ERROR_METRIC = "flow__errors__count";

/**
 * The linkage-derived metric. See note C for why this quantity and not another.
 * Emitted by `staEvidenceTcl()` below.
 */
export const STA_LINKAGE_METRIC = "sta__design__port__count";

/**
 * Metric rules, in the declarative shape ORFS `checkMetadata.py` uses.
 *
 * `required: true` means an ABSENT metric is a FAILURE, not a pass and not a
 * warning (note B). There is no `required: false` rule here on purpose: a rule
 * that tolerates its own absence cannot fail on the run that skipped it.
 */
export const STA_METRIC_RULES = Object.freeze([
  Object.freeze({
    metric: STA_ERROR_METRIC,
    compare: "==",
    value: 0,
    required: true,
    why: "OpenROAD's own error tally. Untrustworthy alone (note A) — AND term only.",
  }),
  Object.freeze({
    metric: STA_LINKAGE_METRIC,
    compare: ">=",
    value: 1,
    required: true,
    why: "Linkage-derived, not SDC-derived (note C). Absent on an unlinked run.",
  }),
]);

/**
 * The complete set of terms that must ALL hold for a PASS.
 *
 * Every member was measured to be necessary: for each one there is a real run
 * that only that term rejects (note A for the first two, note B for
 * metrics_file_present, note C for the linkage rule). Removing any member
 * re-opens a measured bug. `test_sta_evidence_and_conjunction.py` pins this
 * membership and independently proves each term can single-handedly fail a
 * run, so a later demotion of the conjunction to a sole check goes red.
 */
export const STA_EVIDENCE_TERMS = Object.freeze([
  "exit_code_zero",
  "metrics_file_present",
  `metric:${STA_ERROR_METRIC}`,
  `metric:${STA_LINKAGE_METRIC}`,
]);

function compareOk(actual, compare, expected) {
  switch (compare) {
    case "==": return actual === expected;
    case ">=": return actual >= expected;
    case "<=": return actual <= expected;
    case ">":  return actual > expected;
    case "<":  return actual < expected;
    default:   return false;
  }
}

/**
 * The Tcl that emits the linkage metric. Intentionally NOT wrapped in a
 * `[info commands utl::metric_integer]` existence test: if the command is
 * missing the metric is absent, absent is UNMEASURED, and UNMEASURED fails.
 * That is the fail-closed direction. A guarded emission would silently
 * degrade to "no evidence, therefore fine".
 *
 * Placed AFTER link_design and BEFORE the reports, so that on an unlinked
 * network `get_ports` raises here and the metric never reaches the JSON.
 */
export function staEvidenceTcl() {
  return `utl::metric_integer "${STA_LINKAGE_METRIC}" [llength [get_ports *]]`;
}

/**
 * Evaluate the conjunction.
 *
 * @param {object} a
 * @param {number|null} a.exitCode        process exit status of openroad
 * @param {boolean} a.metricsFileExists   did the -metrics file get written
 * @param {string|null} a.metricsRaw      raw file contents, or null
 * @returns {{pass:boolean, verdict:string, terms:object, failedTerms:string[],
 *            reasons:string[], metrics:object|null}}
 */
export function evaluateStaEvidence({ exitCode, metricsFileExists, metricsRaw }) {
  const terms = {};
  const reasons = [];

  // ── term 1: the exit code ────────────────────────────────────────────────
  // Only meaningful once the script is fed as a FILE so that `-exit` applies
  // (Main.cc:467 `exit_after_cmd_file`). Even then it is only one term: the
  // measured file-script abort reports rc=1 with an error count of 0, and a
  // tree with sta_continue_on_error set would report rc=0 on a failed link.
  terms.exit_code_zero = { ok: exitCode === 0, actual: exitCode, expected: 0 };
  if (!terms.exit_code_zero.ok) reasons.push(`openroad exited ${exitCode}`);

  // ── term 2: the metrics file exists at all ───────────────────────────────
  // Note B: absent means UNMEASURED, never "zero errors".
  terms.metrics_file_present = { ok: metricsFileExists === true, actual: metricsFileExists === true, expected: true };

  let metrics = null;
  let parseError = null;
  if (metricsFileExists && typeof metricsRaw === "string") {
    try {
      const parsed = JSON.parse(metricsRaw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) metrics = parsed;
      else parseError = "metrics JSON is not an object";
    } catch (e) {
      parseError = `metrics JSON unparseable: ${e.message}`;
    }
  }
  if (!terms.metrics_file_present.ok) {
    reasons.push("metrics file absent — run is UNMEASURED, not clean");
  } else if (parseError) {
    // An unparseable file is no better evidence than a missing one.
    terms.metrics_file_present.ok = false;
    terms.metrics_file_present.actual = false;
    reasons.push(parseError);
  }

  // ── terms 3..n: the metric rules ─────────────────────────────────────────
  for (const rule of STA_METRIC_RULES) {
    const key = `metric:${rule.metric}`;
    const present = metrics != null && Object.prototype.hasOwnProperty.call(metrics, rule.metric)
      && typeof metrics[rule.metric] === "number" && Number.isFinite(metrics[rule.metric]);
    const actual = present ? metrics[rule.metric] : null;
    const ok = present && compareOk(actual, rule.compare, rule.value);
    terms[key] = { ok, actual, expected: `${rule.compare} ${rule.value}`, present };
    if (!present) {
      reasons.push(`required metric ${rule.metric} ABSENT — UNMEASURED (never read as satisfied)`);
    } else if (!ok) {
      reasons.push(`${rule.metric} = ${actual}, required ${rule.compare} ${rule.value}`);
    }
  }

  // ── the conjunction ──────────────────────────────────────────────────────
  // Every declared term, no exceptions. Do not weaken this to an `||`, to a
  // subset, or to a single term: each of the four rejects a run the others let
  // through, and the measured pairs in note A prove two of them disagree in
  // opposite directions on the same broken input.
  const failedTerms = STA_EVIDENCE_TERMS.filter((t) => !(terms[t] && terms[t].ok));
  const pass = failedTerms.length === 0;

  // UNMEASURED is reported distinctly from FAIL so that a run that produced no
  // evidence is never filed alongside runs that produced disqualifying
  // evidence. Both are `pass:false`.
  const unmeasured = !terms.metrics_file_present.ok
    || STA_METRIC_RULES.some((r) => terms[`metric:${r.metric}`] && !terms[`metric:${r.metric}`].present);

  return {
    pass,
    verdict: pass ? "PASS" : (unmeasured ? "UNMEASURED" : "FAIL"),
    terms,
    failedTerms,
    reasons,
    metrics,
  };
}
