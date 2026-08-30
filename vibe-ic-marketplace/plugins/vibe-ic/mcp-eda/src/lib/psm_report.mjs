// psm_report.mjs — read the numbers OpenROAD PSM actually prints.
//
// MEASURED emit (image ghcr.io/vibeic/vibeic-eda:latest, OpenROAD
// 26Q3-1887-g24ea077e76, sky130A, analyze_power_grid):
//
//     ########## IR report #################
//     Net              : VDD
//     Corner           : default
//     Total power      : 3.50e-05 W
//     Supply voltage   : 1.80e+00 V
//     Worstcase voltage: 1.80e+00 V
//     Average voltage  : 1.80e+00 V
//     Average IR drop  : 8.95e-06 V
//     Worstcase IR drop: 2.25e-05 V
//     Percentage drop  : 0.00 %
//     ######################################
//
// PSM emits seven numbers, including Total power — the P of PPA. eda_ir_drop
// parsed NONE of them: its only regexes were two advisory instance-count probes,
// and everything else was a substring test for markers the MCP had echoed
// itself. The whole power number was emitted by the tool, sat in the log, and
// was discarded.
//
// EVERY VALUE HERE IS IN SCIENTIFIC NOTATION. A naive `([\d.]+)` capture reads
// `3.50` out of `3.50e-05 W` and silently drops the exponent — a 10^5 error
// arriving as a confident number, which is the exact "W read as mW" hazard. So
// these patterns are whole-line anchored and exponent-aware, the shape
// lib/sta_slack.mjs already uses for wns/tns.
//
// A number that is not printed is null. null means NOT MEASURED and must never
// be defaulted to zero — manifest_metrics.mjs turns absent into INCONCLUSIVE,
// which is the correct third answer.

// A signed decimal with an optional exponent: 0.00 | 3.50e-05 | -1.2E+3 | .5
const NUM = "[-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?";

// `<label> : <number> [unit]` on one whole line. The label is matched literally
// and the line is anchored at both ends, so prose that merely contains the words
// cannot be mistaken for a measurement.
function parseLabelled(output, label, unit) {
  if (typeof output !== "string") return null;
  const lbl = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(
    `^[ \\t]*${lbl}[ \\t]*:[ \\t]*(${NUM})[ \\t]*${unit ? unit : ""}[ \\t]*\\r?$`,
    "gmi");
  let m, first = null;
  while ((m = re.exec(output)) !== null) {
    const v = parseFloat(m[1]);
    if (!Number.isNaN(v) && first === null) first = v;
  }
  return first;
}

// The seven numbers of the PSM IR report, by their printed labels.
export function parseIrReport(output) {
  return {
    total_power_w:        parseLabelled(output, "Total power", "W"),
    supply_voltage_v:     parseLabelled(output, "Supply voltage", "V"),
    worstcase_voltage_v:  parseLabelled(output, "Worstcase voltage", "V"),
    average_voltage_v:    parseLabelled(output, "Average voltage", "V"),
    average_ir_drop_v:    parseLabelled(output, "Average IR drop", "V"),
    worst_ir_drop_v:      parseLabelled(output, "Worstcase IR drop", "V"),
    percentage_drop_pct:  parseLabelled(output, "Percentage drop", "%"),
  };
}

// `report_power` prints a total-power table whose last column is the design
// total. MEASURED shape:
//     Total              1.23e-06   4.56e-06   7.89e-07   6.58e-06 100.0%
// Internal / Switching / Leakage / Total, all in scientific notation.
export function parseReportPower(output) {
  if (typeof output !== "string") return null;
  const re = new RegExp(
    `^[ \\t]*Total[ \\t]+(${NUM})[ \\t]+(${NUM})[ \\t]+(${NUM})[ \\t]+(${NUM})` +
    `(?:[ \\t]+${NUM}%)?[ \\t]*\\r?$`, "gmi");
  const m = re.exec(output);
  if (!m) return null;
  const [internal, switching, leakage, total] = m.slice(1, 5).map(parseFloat);
  if ([internal, switching, leakage, total].some(Number.isNaN)) return null;
  return { internal_w: internal, switching_w: switching, leakage_w: leakage, total_w: total };
}

export { parseLabelled as _parseLabelled, NUM as _NUM };
