// Read the selected design's final stat report, not the first leaf's count.
// Yosys can print several stat passes and per-module summaries in one log.
const NUMBER = String.raw`(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?`;
const normalizeName = name => name.trim().replace(/^\\/, "");

function cellCount(body) {
  const modern = new RegExp(String.raw`^\s*(\d+)\s+(?:(?:${NUMBER}|-)\s+)?cells\s*$`, "gm");
  const legacy = /^\s*Number of cells:\s*(\d+)\s*$/gm;
  const matches = [...body.matchAll(modern), ...body.matchAll(legacy)];
  if (matches.length !== 1) return null;
  const count = Number(matches[0][1]);
  return Number.isSafeInteger(count) ? count : null;
}

function areaFor(body, topModule, hierarchical) {
  const kind = hierarchical ? "top module" : "module";
  const pattern = new RegExp(String.raw`^\s*Chip area for ${kind} '([^']+)':\s*(${NUMBER})\s*$`, "gm");
  const matches = [...body.matchAll(pattern)].filter(m => normalizeName(m[1]) === topModule);
  if (matches.length !== 1) return null;
  const area = Number(matches[0][2]);
  return Number.isFinite(area) ? area : null;
}

export function parseYosysSynthStats(output, topModule) {
  const absent = { cells: null, area_um2: null };
  if (typeof output !== "string" || typeof topModule !== "string") return absent;
  // An incomplete final stat must not resurrect an earlier, complete result.
  const passes = [...output.matchAll(/^\s*\d+(?:\.\d+)*\.\s+(?:Printing statistics\.|Executing STAT pass\b[^\n]*)\s*$/gm)];
  const finalStat = passes.length ? output.slice(passes.at(-1).index) : output;
  const headings = [...finalStat.matchAll(/^===\s+(.+?)\s+===\s*$/gm)];
  const sections = headings.map((m, i) => ({
    name: normalizeName(m[1]),
    body: finalStat.slice(m.index + m[0].length, headings[i + 1]?.index ?? finalStat.length),
  }));
  const hierarchy = sections.filter(s => s.name === "design hierarchy").at(-1);
  if (hierarchy) {
    // The first numeric/name row is the root, not a descendant that happens
    // to share the requested name. Do not sum module rows or repeated passes.
    const modernRoot = new RegExp(String.raw`^\s*(\d+)\s+(?:(?:${NUMBER}|-)\s+)?(\S+)\s*$`);
    let root = null;
    for (const line of hierarchy.body.split(/\r?\n/)) {
      const modern = line.match(modernRoot);
      const legacy = line.match(/^\s*(\S+)\s+(\d+)\s*$/);
      if (modern) { root = { name: normalizeName(modern[2]), count: Number(modern[1]) }; break; }
      if (legacy) { root = { name: normalizeName(legacy[1]), count: null }; break; }
    }
    if (!root || root.name !== topModule) return absent;
    let cells = cellCount(hierarchy.body);
    if (root.count !== null && root.count !== cells) cells = null;
    return { cells, area_um2: areaFor(hierarchy.body, topModule, true) };
  }
  const selected = sections.filter(s => s.name === topModule).at(-1);
  if (!selected) return absent;
  // A local report with live submodules is not a full design population.
  if (/^\s*[1-9]\d*\s+(?:\S+\s+)?submodules\s*$/m.test(selected.body)) return absent;
  return { cells: cellCount(selected.body), area_um2: areaFor(selected.body, topModule, false) };
}
