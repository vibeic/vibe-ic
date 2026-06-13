// ─── Netgen LVS verdict parser (real verdict + DID-NOT-RUN guard) ───
//
// Closes ORGANIC-20260531-eda-lvs-netgen-false-positive-and-no-stdcell-lib.
//
// BEFORE this module the eda_lvs netgen branch derived its verdict from a
// naive `output.match(/uniquely/i) || output.match(/match/i)` boolean and a
// `output.match(/mismatch|NOT match|FAIL/i)` failure regex. Two fatal classes
// of bug:
//
//   1. SILENT FALSE-POSITIVE. The `/match/i` token matches the substring
//      "match" inside phrases like "Top level cell FAILED PIN MATCHING" and
//      "Netlists match uniquely WITH PROPERTY ERRORS" — both of which are
//      FAILS — and the failure regex `/mismatch|NOT match|FAIL/i` does NOT
//      fire on "Property errors were found" / "with property errors". So a
//      property-error mismatch (e.g. a transistor W delta) returned
//      `matched:true`. Empirically confirmed in-container (netgen 1.5.316,
//      sky130A): a 2x-wide pfet pair emits
//        "Netlists match uniquely with property errors."
//        "Final result: Circuits match uniquely."
//        "Property errors were found."
//      which the old code scored as PASS.
//
//   2. DID-NOT-RUN scored as a verdict. When Magic's ext2spice named the top
//      `<top>_flat` (it appends `_flat`) and the caller passed `<top>`, netgen
//      printed "Cannot find cell <top> in file ..." and EXITED WITHOUT WRITING
//      A REPORT or a "Final result:" line — yet the old code still returned a
//      non-null `matched`. A LVS tool that reports a verdict when it never
//      compared is the most dangerous possible failure.
//
// This parser returns an explicit { verdict, matched, parse_error, reason,
// property_errors, did_not_run } classification. matched is NEVER true unless
// netgen printed a real "Circuits/Netlists match uniquely" Final result AND no
// fail signal is present. matched is null (parse_error / did_not_run) — never
// true — when netgen could not have compared.
//
// chip-AGNOSTIC: pure phrase classification over netgen stdout/report text; no
// design-specific cell names. Pure (no I/O) so it is unit-testable in isolation.

// Phrases that mean netgen NEVER actually compared the two circuits. Presence
// of ANY of these => did_not_run (matched := null), regardless of any later
// "match" token. Order: these are checked BEFORE the positive verdict.
const DID_NOT_RUN_PHRASES = [
  /cannot find cell/i,                 // wrong top name / `_flat` mismatch
  /no such file or directory/i,        // a netlist path didn't exist
  /file .* couldn'?t be read/i,        // setup / netlist unreadable
  /circuit .* contains no devices/i,   // one side parsed to an empty circuit
  /both cells are in the same netlist/i,  // self-compare guard — netgen refuses
  /cannot compare/i,                   // generic netgen "Cannot compare!" abort
  /no circuit (?:has been )?(?:declared|loaded)/i, // nothing to compare
];

// Explicit FAIL phrases. ANY present => verdict FAIL even if a "match" token is
// also present (netgen prints "Circuits match uniquely." on the topology line
// and THEN "Property errors were found." — the property error is the real
// verdict). Anchored on whole phrases, NOT the bare substring "match".
const FAIL_PHRASES = [
  /netlists?\s+do\s+not\s+match/i,
  /circuits?\s+do\s+not\s+match/i,
  /failed\s+pin\s+matching/i,
  /property\s+errors?\s+were\s+found/i,
  /match\s+uniquely\s+with\s+property\s+errors/i,
  /\*\*\*\s*mismatch\s*\*\*\*/i,
  /\*\*mismatch\*\*/i,
];

// Genuine clean-match phrases. Only counted when NO fail / did-not-run phrase
// is present. Must be the netgen "match uniquely" wording — NOT the bare
// substring "match".
const MATCH_PHRASES = [
  /circuits?\s+match\s+uniquely/i,
  /netlists?\s+match\s+uniquely/i,
];

/**
 * Classify a netgen LVS run.
 *
 * @param {string} output         Combined netgen stdout (+ tailed report).
 * @param {object} [opts]
 * @param {boolean} [opts.reportWritten]  Whether the report file was actually
 *        written (a netgen run that exits on "Cannot find cell" writes none).
 *        When explicitly false, a run with no "Final result:" line is treated
 *        as did-not-run even absent an explicit DID_NOT_RUN phrase.
 * @returns {{
 *   verdict: "MATCH"|"FAIL"|"DID_NOT_RUN"|"PARSE_ERROR",
 *   matched: boolean|null,
 *   parse_error: boolean,
 *   did_not_run: boolean,
 *   property_errors: boolean,
 *   reason: string
 * }}
 */
export function classifyNetgenVerdict(output, opts = {}) {
  const text = String(output || "");
  const reportWritten = opts.reportWritten;
  const hasFinalResult = /final result\s*:/i.test(text);

  // 1) DID-NOT-RUN guard FIRST — a run that never compared can never be a PASS.
  const dnrHit = DID_NOT_RUN_PHRASES.find((re) => re.test(text));
  if (dnrHit) {
    return {
      verdict: "DID_NOT_RUN",
      matched: null,
      parse_error: true,
      did_not_run: true,
      property_errors: false,
      reason:
        "netgen never compared the two circuits (e.g. 'Cannot find cell' — " +
        "top subckt name mismatch, missing netlist, or empty circuit). NOT a pass.",
    };
  }
  // If the caller knows no report was written and there is no Final result
  // line, the run aborted before comparing — treat as did-not-run.
  if (reportWritten === false && !hasFinalResult) {
    return {
      verdict: "DID_NOT_RUN",
      matched: null,
      parse_error: true,
      did_not_run: true,
      property_errors: false,
      reason:
        "netgen wrote no report and emitted no 'Final result:' line — the LVS " +
        "did not run to a verdict. NOT a pass.",
    };
  }

  // 2) Explicit FAIL phrases override any co-present 'match uniquely' token.
  const propErr = /property\s+errors?\s+were\s+found/i.test(text) ||
                  /match\s+uniquely\s+with\s+property\s+errors/i.test(text);
  const failHit = FAIL_PHRASES.find((re) => re.test(text));
  if (failHit) {
    return {
      verdict: "FAIL",
      matched: false,
      parse_error: false,
      did_not_run: false,
      property_errors: propErr,
      reason: propErr
        ? "netgen reported property errors (e.g. device-parameter mismatch) — " +
          "topology may match but the netlists are NOT equivalent."
        : "netgen reported a mismatch / failed pin matching — netlists differ.",
    };
  }

  // 3) Genuine clean match — only when NO fail / did-not-run signal is present.
  const matchHit = MATCH_PHRASES.find((re) => re.test(text));
  if (matchHit && hasFinalResult) {
    return {
      verdict: "MATCH",
      matched: true,
      parse_error: false,
      did_not_run: false,
      property_errors: false,
      reason: "netgen Final result: Circuits/Netlists match uniquely (no property errors).",
    };
  }
  // A 'match uniquely' token without a 'Final result:' line is suspicious
  // (e.g. it appeared only in a per-subcircuit summary while the run aborted).
  if (matchHit && !hasFinalResult) {
    return {
      verdict: "PARSE_ERROR",
      matched: null,
      parse_error: true,
      did_not_run: false,
      property_errors: false,
      reason:
        "saw a 'match uniquely' token but no 'Final result:' line — cannot " +
        "confirm netgen ran to a top-level verdict. Refuse to claim a pass.",
    };
  }

  // 4) Nothing recognizable — never default to matched.
  return {
    verdict: "PARSE_ERROR",
    matched: null,
    parse_error: true,
    did_not_run: false,
    property_errors: false,
    reason:
      "netgen output has neither a recognizable match verdict nor a fail/abort " +
      "signal — cannot classify as PASS or FAIL; see `output` for the tool log.",
  };
}

// Per-PDK std-cell SPICE library (transistor-level model of every gate). When
// the SCHEMATIC side is a post-PnR Verilog/SPICE GATE netlist (cells stay as
// empty placeholders), netgen device-level LVS needs this loaded so each gate
// expands to transistors. Mirrors the pilot's hand-driven `readnet spice` load.
export function stdcellSpicePath(pdk, pdkRoot = "/foss/pdks") {
  const root = String(pdkRoot || "/foss/pdks").replace(/\/+$/, "");
  if (pdk === "sky130") {
    return `${root}/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice`;
  }
  if (pdk === "gf180") {
    return `${root}/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/spice/gf180mcu_fd_sc_mcu7t5v0.spice`;
  }
  return null;
}

/**
 * Resolve which top-subckt name actually exists in a layout SPICE netlist.
 *
 * Magic's ext2spice appends `_flat` to the top subckt when the design was
 * flattened (`flatten <top>` -> `.subckt <top>_flat ...`). When the caller
 * asks for `<top>` but only `<top>_flat` exists, netgen aborts with "Cannot
 * find cell <top>" and never compares. This returns the name to feed netgen:
 *   - `<top>` if `.subckt <top>` is present,
 *   - else `<top>_flat` if THAT is present,
 *   - else `<top>` unchanged (let netgen surface the real error).
 * Pure (caller supplies the netlist text); chip-AGNOSTIC.
 *
 * @param {string} layoutSpiceText  Contents of the layout SPICE netlist.
 * @param {string} topModule        Requested top module name.
 * @returns {{ name: string, aligned: boolean }}
 */
export function resolveLayoutTop(layoutSpiceText, topModule) {
  const text = String(layoutSpiceText || "");
  const esc = String(topModule).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const exact = new RegExp(`^\\s*\\.subckt\\s+${esc}(\\s|$)`, "im");
  if (exact.test(text)) {
    return { name: topModule, aligned: false };
  }
  const flat = new RegExp(`^\\s*\\.subckt\\s+${esc}_flat(\\s|$)`, "im");
  if (flat.test(text)) {
    return { name: `${topModule}_flat`, aligned: true };
  }
  return { name: topModule, aligned: false };
}

/**
 * Build a netgen `source` TCL that:
 *   - optionally loads the PDK std-cell SPICE library INTO the schematic
 *     circuit (readnet spice <stdcell> <ckt>) so a post-PnR gate netlist's
 *     empty cell placeholders expand to transistors for a true device-level
 *     compare, then
 *   - runs `lvs` against the foundry setup, writing a report.
 *
 * The layout-top name is passed pre-resolved (see resolveLayoutTop) so a
 * Magic `<top>_flat` is matched instead of aborting on "Cannot find cell".
 *
 * Mirrors the pilot's hand-driven `lvs_device_level.tcl` driver referenced in
 * the backlog. Pure string builder (no I/O); chip-AGNOSTIC.
 *
 * @returns {string} TCL script body for `netgen -batch source <tcl>`.
 */
export function buildNetgenLvsTcl({
  layoutNetlist,
  schematicNetlist,
  layoutTop,
  schematicTop,
  setupFile,
  reportPath,
  stdcellSpice = null,
}) {
  const lines = [];
  lines.push("# Vibe-IC mcp-eda — device-level netgen LVS driver");
  lines.push("# Generated by lib/netgen_verdict.mjs buildNetgenLvsTcl()");
  // NOTE: the foundry setup is NOT sourced at top level — it runs
  // `cells list -all -circuit1` which requires circuits to already exist;
  // it is consumed by netgen as the 3rd argument of `lvs`. We only pre-read
  // the netlists (so we can load the std-cell lib into the schematic side).
  if (stdcellSpice) {
    lines.push("# Expand gate placeholders on the SCHEMATIC side to transistors");
    lines.push("# by loading the PDK std-cell SPICE library into that circuit");
    lines.push("# (a post-PnR Verilog/SPICE gate netlist has empty cell stubs).");
    lines.push(`set schCkt [readnet spice ${schematicNetlist}]`);
    lines.push(`readnet spice ${stdcellSpice} $schCkt`);
    lines.push(`set layCkt [readnet spice ${layoutNetlist}]`);
    // Compare the two pre-built circuits (cell handles), not file specs, so the
    // schematic side keeps the std-cell expansion we just loaded into it.
    lines.push(
      `lvs "$layCkt ${layoutTop}" "$schCkt ${schematicTop}" ` +
      `${setupFile} ${reportPath}`
    );
  } else {
    lines.push("# Run LVS: layout-top vs schematic-top against the foundry setup.");
    lines.push(
      `lvs "${layoutNetlist} ${layoutTop}" "${schematicNetlist} ${schematicTop}" ` +
      `${setupFile} ${reportPath}`
    );
  }
  return lines.join("\n") + "\n";
}
