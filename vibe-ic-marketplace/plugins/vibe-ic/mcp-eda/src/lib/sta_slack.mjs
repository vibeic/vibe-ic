// sta_slack.mjs — read wns/tns out of what OpenSTA actually prints.
//
// MEASURED (pinned image ghcr.io/vibeic/vibeic-eda@sha256:4ece6c01cddc9990...,
// sky130 counter, openroad -exit): `report_wns` / `report_tns` print
//
//     tns max 0.00
//     wns max 0.00
//
// The regex this module replaces was `/wns\s+([\d.-]+)/i`, which requires a
// digit straight after the whitespace and so never matched that line — not in
// the clean case, not in the violating case (`wns max -0.65`), not ever. It
// returned null for every run, and the manifest recorded `wns: null` next to
// `status: "PASS"`. A run that linked nothing and a genuinely clean run then
// produced byte-identical manifests, which is what made the whole defect
// invisible.
//
// A metric that cannot be read is ABSENT, and absent is exactly what
// manifest_metrics.mjs turns into INCONCLUSIVE. So this parser and that gate
// are two halves of one thing: without the parser the gate would refuse every
// run including the good ones, and without the gate the parser would let an
// unlinked run keep its PASS.

// One line, whole line: `<metric> [max|min] <number>`. Anchored to line start
// and end so prose that merely contains the word cannot be mistaken for a
// measurement. Returns a Number, or null when the tool printed no such line —
// null means NOT MEASURED and must never be defaulted to zero.
export function parseSlackMetric(output, metric) {
  if (typeof output !== "string" || !/^[a-z_]+$/.test(metric)) return null;
  const re = new RegExp(
    `^[ \\t]*${metric}[ \\t]+(?:(max|min)[ \\t]+)?` +
    `(-?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][+-]?\\d+)?)[ \\t]*\\r?$`,
    "gmi");
  let m;
  let first = null;
  let setup = null;
  while ((m = re.exec(output)) !== null) {
    const v = parseFloat(m[2]);
    if (Number.isNaN(v)) continue;
    if (first === null) first = v;
    // `max` is the setup (late) corner — the one eda_sta reports on. A bare
    // `wns <n>` with no qualifier is the same number under an older format.
    const qual = m[1] ? m[1].toLowerCase() : "max";
    if (qual === "max" && setup === null) setup = v;
  }
  return setup !== null ? setup : first;
}

export const parseWns = (output) => parseSlackMetric(output, "wns");
export const parseTns = (output) => parseSlackMetric(output, "tns");
