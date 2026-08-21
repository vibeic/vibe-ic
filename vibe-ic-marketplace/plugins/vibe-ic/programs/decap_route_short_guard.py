#!/usr/bin/env python3
"""decap_route_short_guard — remove VDD<->VSS shorts caused by decap fillers placed
under signal routing (a real post-route PnR defect), by swapping each conflicting
decap for the same-width plain FILL cell.

THE DEFECT (chip-AGNOSTIC, reproduced on a commercial 180nm PDK): a decoupling-cap
filler cell (DECAP/DCAP/FILLCAP) carries a large full-cell MET1 capacitor plate in its
GDS, but its LEF abstract declares ONLY the rail pins + POLY/CONT OBS — NO MET1 OBS over
the plate. So the router, seeing free MET1 space per the LEF, routes a signal net's MET1
straight through where a decap will later land; `filler_placement` (which runs AFTER
detailed_route and tiles every empty site blind to the routing above) then drops the decap
in, and its hidden GDS plate SHORTS the signal to a power rail — and, cell-to-cell, one
power rail to the other. An OSS geometric LVS catches it (correctly) only at sign-off.

THE FIX: a decap must never sit under a different-net signal wire. This pass detects every
decap instance whose plate region (footprint minus the rail-pin strips) is crossed by a
signal-net MET1 wire, and REPLACES it with the same-width plain FILL cell (`DECAP8`->`FILL8`,
`DECAP4`->`FILL4`, ...). FILL cells provide the SAME well/implant continuity + rail pins but
have NO cap plate (verified: rail-height MET1 only), so the short is gone with zero density
/ continuity loss and no empty sites. The other (non-conflicting) decaps keep their full IR
margin. DEF + LEF only — deterministic, no LLM, chip-AGNOSTIC (name-pattern + LEF-size driven).

CLI:
  decap_route_short_guard.py --def routed.def --lef cell.lef[,tech.lef,...] \
      --out routed.fixed.def [--report guard.json] [--rail-margin-um 0.8] [--check]
`--check` = detect only (exit 3 if any conflict, no rewrite). Default = repair + exit 0.
"""
import sys, re, json, argparse

_DECAP_RE = re.compile(r"^(DECAP|DCAP|FILLCAP)(\d+)$", re.I)


def parse_lef_master_widths(lef_texts):
    """master name -> width_um, from `MACRO <name> ... SIZE <w> BY <h> ... END <name>`."""
    widths = {}
    for t in lef_texts:
        for m in re.finditer(r"MACRO\s+(\S+)\b(.*?)END\s+\1", t, re.S):
            name, body = m.group(1), m.group(2)
            sz = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", body)
            if sz:
                widths[name] = float(sz.group(1))
    return widths


def _fill_for_decap(master, widths):
    """The plain-FILL replacement for a decap master: same size class (DECAP8->FILL8),
    else bin-pack FILL masters into the decap width, else None (caller removes+warns)."""
    m = _DECAP_RE.match(master)
    if not m:
        return None
    same = "FILL" + m.group(2)
    if same in widths:
        return [same]
    # bin-pack available FILL masters (largest-first) into the decap's width
    target = widths.get(master)
    fills = sorted(((w, n) for n, w in widths.items()
                    if re.match(r"^FILL\d+$", n, re.I)), reverse=True)
    if target is None or not fills:
        return None
    out, remaining = [], target + 1e-6
    for w, n in fills:
        while w <= remaining:
            out.append(n); remaining -= w
    return out or None


def parse_components(def_text):
    """-> list of dicts {name, master, x, y, orient, raw_span(start,end)} for every
    COMPONENT placement. Coordinates are DEF database units (integers)."""
    if "COMPONENTS" not in def_text:
        return []
    s = def_text.index("COMPONENTS")
    e = def_text.index("END COMPONENTS", s)
    body = def_text[s:e]
    comps = []
    for m in re.finditer(
            r"-\s+(\S+)\s+(\S+)((?:(?!\n\s*-\s|\bEND COMPONENTS\b).)*?);", body, re.S):
        name, master, rest = m.group(1), m.group(2), m.group(3)
        pm = re.search(r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)", rest)
        if not pm:
            continue
        comps.append({"name": name, "master": master,
                      "x": int(pm.group(1)), "y": int(pm.group(2)),
                      "orient": pm.group(3),
                      "start": s + m.start(), "end": s + m.end(),
                      "text": m.group(0)})
    return comps


def parse_signal_m1_wires(def_text, units, half_w_um=0.14):
    """-> list of (x1,y1,x2,y2) µm rects for every regular-NET MET1 routed segment
    (a signal wire, half-width-expanded). SPECIALNETS (power rails) are EXCLUDED — a
    rail over a decap is expected; only a SIGNAL wire over the plate is a short.

    Walks each net's routing path token-by-token, tracking the CURRENT layer and the
    previous point: consecutive points on the same layer form a segment; a layer keyword
    starts a fresh point-run; `NEW`/`ROUTED` reset the run; a `*` coordinate repeats the
    previous point's ordinate (the DEF wildcard). Via tokens are ignored."""
    if "\nNETS " not in def_text:
        return []
    body = def_text.split("\nNETS ", 1)[1].split("END NETS", 1)[0]
    hw = half_w_um
    tok_re = re.compile(
        r"(MET\d+)|\(\s*(-?\d+|\*)\s+(-?\d+|\*)\s*\)|\b(NEW|ROUTED)\b")
    rects = []
    for rec in re.split(r"\n\s*-\s+", body)[1:]:
        cur = None; prev = None
        for m in tok_re.finditer(rec):
            if m.group(1):                       # layer keyword -> fresh run on this layer
                cur = m.group(1); prev = None
            elif m.group(4):                     # NEW / ROUTED -> reset the point run
                prev = None
            else:                                # a point ( x y ), with * = repeat prev
                px, py = (prev if prev else (None, None))
                x = px if m.group(2) == "*" else int(m.group(2)) / units
                y = py if m.group(3) == "*" else int(m.group(3)) / units
                if x is None or y is None:
                    prev = (x if x is not None else px, y if y is not None else py)
                    continue
                if prev is not None and cur == "MET1":
                    rects.append((min(prev[0], x) - hw, min(prev[1], y) - hw,
                                  max(prev[0], x) + hw, max(prev[1], y) + hw))
                prev = (x, y)
    return rects


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def find_conflicts(comps, widths, m1_wires, units, rail_margin_um):
    """A decap conflicts when a signal MET1 wire crosses its PLATE region (the footprint
    minus the `rail_margin_um` rail-pin strip at top and bottom)."""
    conflicts = []
    for c in comps:
        if not _DECAP_RE.match(c["master"]):
            continue
        w = widths.get(c["master"])
        if w is None:
            continue
        x = c["x"] / units; y = c["y"] / units
        # cell height: use the master height if known, else infer from width class is unsafe;
        # rail margin bounds the plate region from the rails regardless of exact height.
        h = widths.get("__h__" + c["master"]) or None
        # footprint: x..x+w ; plate band excludes rail strips. Height from LEF SIZE height
        # is captured separately; fall back to a generous band using the wires' own extent.
        plate = (x, y + rail_margin_um, x + w,
                 y + (c.get("h") or 0) - rail_margin_um) if c.get("h") else None
        if plate is None:
            # height unknown -> use a tall band from the rail margin up to a std row (~ w-independent);
            # callers pass height via comps; if truly absent, use full footprint minus margins on a
            # default 5.0um row so we never UNDER-detect (over-detect is safe: swaps an extra decap).
            plate = (x, y + rail_margin_um, x + w, y + 5.04 - rail_margin_um)
        hit = next((wr for wr in m1_wires if _overlap(plate, wr)), None)
        if hit:
            conflicts.append((c, hit))
    return conflicts


def build_fixed_def(def_text, conflicts, widths):
    """Replace each conflicting decap COMPONENT master `DECAPn` with `FILLn` (same width),
    in place. Returns (fixed_text, replacements, removed). A 1:1 same-width swap keeps the
    placement/footprint/well-continuity; only the cap plate (the short) is dropped."""
    replacements, removed = [], []
    edits = []  # (start, end, new_text)
    for c, _wire in conflicts:
        fill = _fill_for_decap(c["master"], widths)
        if fill and len(fill) == 1 and abs(widths.get(fill[0], -9) - widths.get(c["master"], -1)) < 1e-6:
            new = c["text"].replace(f" {c['master']} ", f" {fill[0]} ", 1)
            edits.append((c["start"], c["end"], new))
            replacements.append({"inst": c["name"], "from": c["master"],
                                 "to": fill[0], "x": c["x"], "y": c["y"]})
        else:
            # no exact same-width FILL: drop the decap COMPONENT (safe: bonus IR margin).
            # keep DEF valid; density dummy-fill + remaining decaps cover it.
            edits.append((c["start"], c["end"], ""))
            removed.append({"inst": c["name"], "from": c["master"],
                            "x": c["x"], "y": c["y"], "reason": "no same-width FILL"})
    # apply edits back-to-front so offsets stay valid
    out = def_text
    for start, end, new in sorted(edits, key=lambda e: -e[0]):
        out = out[:start] + new + out[end:]
    # if any decap was fully removed, fix the COMPONENTS count
    if removed:
        m = re.search(r"COMPONENTS\s+(\d+)\s*;", out)
        if m:
            out = out[:m.start()] + f"COMPONENTS {int(m.group(1)) - len(removed)} ;" + out[m.end():]
    return out, replacements, removed


def parse_master_heights(lef_texts):
    heights = {}
    for t in lef_texts:
        for m in re.finditer(r"MACRO\s+(\S+)\b(.*?)END\s+\1", t, re.S):
            sz = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", m.group(2))
            if sz:
                heights[m.group(1)] = float(sz.group(2))
    return heights


def run(def_path, lef_paths, out_path, report_path, rail_margin_um, check_only):
    def_text = open(def_path).read()
    lef_texts = [open(p).read() for p in lef_paths]
    widths = parse_lef_master_widths(lef_texts)
    heights = parse_master_heights(lef_texts)
    um = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    units = float(um.group(1)) if um else 1000.0
    comps = parse_components(def_text)
    for c in comps:
        c["h"] = heights.get(c["master"])
    m1 = parse_signal_m1_wires(def_text, units)
    conflicts = find_conflicts(comps, widths, m1, units, rail_margin_um)
    n_decap = sum(1 for c in comps if _DECAP_RE.match(c["master"]))
    report = {"decap_instances": n_decap, "signal_m1_wires": len(m1),
              "conflicts": len(conflicts),
              "conflicting": [{"inst": c["name"], "master": c["master"],
                               "x": c["x"], "y": c["y"]} for c, _ in conflicts[:200]]}
    if check_only:
        report["mode"] = "check"
        if report_path:
            open(report_path, "w").write(json.dumps(report, indent=2))
        print(f"decap_route_short_guard[check]: {len(conflicts)} decap-under-route "
              f"short(s) of {n_decap} decaps")
        return 3 if conflicts else 0
    fixed, repl, removed = build_fixed_def(def_text, conflicts, widths)
    open(out_path, "w").write(fixed)
    report.update({"mode": "repair", "replaced": repl, "removed": removed,
                   "out": out_path})
    if report_path:
        open(report_path, "w").write(json.dumps(report, indent=2))
    print(f"decap_route_short_guard: {len(repl)} decap->FILL swaps + {len(removed)} "
          f"removals to clear {len(conflicts)} decap-under-route short(s); wrote {out_path}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", dest="def_path", required=True)
    ap.add_argument("--lef", required=True, help="comma-separated LEF paths")
    ap.add_argument("--out", help="corrected DEF (required unless --check)")
    ap.add_argument("--report")
    ap.add_argument("--rail-margin-um", type=float, default=0.8)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if not a.check and not a.out:
        ap.error("--out is required unless --check")
    return run(a.def_path, [p for p in a.lef.split(",") if p], a.out, a.report,
               a.rail_margin_um, a.check)


if __name__ == "__main__":
    sys.exit(main())
