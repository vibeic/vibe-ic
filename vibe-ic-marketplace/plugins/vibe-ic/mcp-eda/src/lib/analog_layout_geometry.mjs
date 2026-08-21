// ─── Analog layout geometry-emptiness detector (ORGANIC #144) ───
//
// Closes the "empty-geometry stream reported as success" hole in
// `eda_analog_layout`. BEFORE this module the tool ran a Magic TCL that is
// `readspice <netlist>` + `gds write` + `puts INFO` comments — no placement,
// no paint, no PCell instantiation, no guard-ring geometry — and returned
// `success: exitCode === 0` (magic exits 0 even though nothing was placed).
// The streamed GDS/LEF was an empty / degenerate cell yet the caller (and the
// A5 gate) treated it as a real layout.
//
// This module walks the streamed GDS (and, as a fallback, the Magic .mag
// text) and reports whether ANY real placed geometry exists, so the tool can
// return an honest `SCAFFOLD` status ("netlist loaded, NO geometry placed")
// instead of a fake DONE. Pure JS — no KLayout dependency — so it is testable
// under node without a container.

import fs from "fs";

// GDS-II record types that carry geometry / placement (not header/struct
// bookkeeping): BOUNDARY 0x08, PATH 0x09, SREF 0x0A, AREF 0x0B, BOX 0x2D.
const GDS_GEOMETRY_RECORD_TYPES = new Set([0x08, 0x09, 0x0a, 0x0b, 0x2d]);

// Magic .mag paint (`rect xbot ybot xtop ytop`) + instance (`use <cell> <id>`)
// lines. Real placed geometry = at least one of either.
const MAG_RECT_RE = /^\s*rect\s+-?\d+\s+-?\d+\s+-?\d+\s+-?\d+\s*$/gm;
const MAG_USE_RE = /^\s*use\s+\S+/gm;

/**
 * Count geometry/placement records in a binary GDS-II record stream.
 * A well-formed record is `[2-byte len][1-byte type][1-byte datatype][data]`.
 * A malformed / truncated stream stops the walk (count stays honest).
 * @param {Buffer|Uint8Array} data
 * @returns {number}
 */
export function gdsGeometryCount(data) {
  if (!data || data.length < 4) return 0;
  let i = 0;
  let count = 0;
  const n = data.length;
  while (i + 4 <= n) {
    const rlen = (data[i] << 8) | data[i + 1];
    const rtype = data[i + 2];
    if (rlen < 4) break; // a valid record is at least the 4-byte header
    if (GDS_GEOMETRY_RECORD_TYPES.has(rtype)) count += 1;
    i += rlen;
  }
  return count;
}

/**
 * Count placed geometry in a Magic .mag source: paint `rect` lines + cell
 * instance `use` lines.
 * @param {string} text
 * @returns {number}
 */
export function magGeometryCount(text) {
  if (!text) return 0;
  const rects = (text.match(MAG_RECT_RE) || []).length;
  const uses = (text.match(MAG_USE_RE) || []).length;
  return rects + uses;
}

/**
 * Decide whether an emitted analog layout carries real placed geometry.
 * Prefers the GDS (what the tool streams); falls back to a .mag text scan.
 * @param {{gdsPath?: string, magPath?: string}} paths
 * @returns {{hasGeometry: boolean, gdsRecords: number, magLines: number,
 *            status: string, detail: string}}
 */
export function layoutHasGeometry({ gdsPath, magPath } = {}) {
  let gdsRecords = 0;
  let magLines = 0;
  let inspected = false;

  if (gdsPath && fs.existsSync(gdsPath)) {
    inspected = true;
    try {
      gdsRecords = gdsGeometryCount(fs.readFileSync(gdsPath));
    } catch {
      gdsRecords = 0;
    }
  }
  if (magPath && fs.existsSync(magPath)) {
    inspected = true;
    try {
      magLines = magGeometryCount(fs.readFileSync(magPath, "utf8"));
    } catch {
      magLines = 0;
    }
  }

  const hasGeometry = gdsRecords > 0 || magLines > 0;
  if (!inspected) {
    return {
      hasGeometry: false,
      gdsRecords,
      magLines,
      status: "SCAFFOLD",
      detail:
        "no layout artefact was streamed (no GDS / .mag on disk) — netlist " +
        "loaded, NO geometry placed. Manual layout or an auto-layout tool " +
        "(place + paint + guard-ring) is required.",
    };
  }
  if (hasGeometry) {
    return {
      hasGeometry: true,
      gdsRecords,
      magLines,
      status: "DONE",
      detail:
        `layout carries real placed geometry ` +
        `(${gdsRecords} GDS geometry record(s), ${magLines} .mag paint/use line(s)).`,
    };
  }
  return {
    hasGeometry: false,
    gdsRecords,
    magLines,
    status: "SCAFFOLD",
    detail:
      "netlist loaded, NO geometry placed — the streamed GDS/.mag carries no " +
      "BOUNDARY/PATH/SREF/AREF/BOX record and no rect/use line. This is a " +
      "scaffold, not a placed layout. Manual layout or an auto-layout tool " +
      "(place + paint + guard-ring) is required.",
  };
}
