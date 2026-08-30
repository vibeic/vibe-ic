#!/usr/bin/env python3
"""J99 — the mechanism linking POST_HOLD_LEGALIZE_FAILED to DRT-0073.

The die-3300 arm printed `POST_HOLD_LEGALIZE_FAILED` (274 instances with no legal
site) and then the DETAILED ROUTER aborted at pin access with four
`[ERROR DRT-0073] No access point for <inst>/I`.  Two events, and "the second is
caused by the first" is a story until it is measured.

The measurable form: a standard cell can only be routed if it sits ON the site grid
the DEF's own ROW statements define.  So read the grid from the DEF, and ask of each
instance whether its PLACED origin lands on it.

CONTROL is the point of this file, not decoration.  The same predicate is asked of:
  * the four instances the ROUTER named            -> expected OFF grid
  * a sample of instances it did NOT name          -> expected ON grid
If the second group is also off-grid, the predicate is measuring the parser rather
than the placement, and the finding is withdrawn.  Exit 2 says exactly that.

chip-AGNOSTIC: reads ROW/UNITS/COMPONENTS from any DEF.  No chip, PDK or cell
literal anywhere -- the four names come in on argv.
"""
import re
import sys


def read_grid(def_path):
    """(x0, site_w, y0, row_pitch) in DBU, from the DEF's own ROW statements."""
    units = None
    xs, ys, steps = [], [], []
    with open(def_path, errors="replace") as f:
        for line in f:
            if units is None:
                m = re.match(r"\s*UNITS DISTANCE MICRONS (\d+)", line)
                if m:
                    units = int(m.group(1))
                    continue
            m = re.match(r"\s*ROW \S+ \S+ (-?\d+) (-?\d+) \S+ DO (\d+) BY (\d+) "
                         r"STEP (\d+) (\d+)", line)
            if m:
                x, y, _do, _by, sx, _sy = (int(g) for g in m.groups())
                xs.append(x)
                ys.append(y)
                steps.append(sx)
            elif line.startswith("COMPONENTS"):
                break          # ROWs precede COMPONENTS; stop before the big section
    if units is None or not xs:
        raise SystemExit(f"{def_path}: no UNITS/ROW found")
    ys_sorted = sorted(set(ys))
    pitch = min(b - a for a, b in zip(ys_sorted, ys_sorted[1:]))
    return min(xs), steps[0], min(ys_sorted), pitch, units


def placements(def_path, wanted=None, sample=0, control_re=None):
    """{inst: (x, y)}.  `wanted` selects by name; `sample` takes N instances NOT in
    `wanted` as the control group.

    `control_re` is load-bearing.  A control drawn from whatever the DEF happens to
    list first is a control of FILLER cells in row 0 -- always on grid, and so unable
    to fail.  Restricting it to the SAME cell class as the named instances asks the
    predicate to separate two groups that differ only in whether the router named
    them."""
    want = set(wanted or ())
    crx = re.compile(control_re) if control_re else None
    got, ctrl = {}, {}
    pat = re.compile(r"^\s*- (\S+) \S+ .*?\+ PLACED \( (-?\d+) (-?\d+) \)")
    with open(def_path, errors="replace") as f:
        for line in f:
            m = pat.match(line)
            if not m:
                continue
            name, x, y = m.group(1), int(m.group(2)), int(m.group(3))
            if name in want:
                got[name] = (x, y)
            elif len(ctrl) < sample and (crx is None or crx.match(name)):
                ctrl[name] = (x, y)
            if len(got) == len(want) and len(ctrl) >= sample:
                break
    return got, ctrl


def main(argv):
    if len(argv) < 3:
        raise SystemExit("usage: offsite_cells.py <routed.def> [--control-re RE] "
                         "<inst> [inst...]")
    def_path, rest = argv[1], argv[2:]
    control_re = None
    if rest and rest[0] == "--control-re":
        control_re, rest = rest[1], rest[2:]
    names = rest
    x0, site_w, y0, pitch, units = read_grid(def_path)
    print(f"grid from {def_path}'s own ROW statements:")
    print(f"  UNITS  {units} DBU/um")
    print(f"  x: origin {x0}, site width {site_w} DBU ({site_w/units:g} um)")
    print(f"  y: origin {y0}, row pitch  {pitch} DBU ({pitch/units:g} um)")
    print()
    named, control = placements(def_path, names, sample=8, control_re=control_re)
    print(f"control drawn from: {control_re or 'ANY instance (weak: filler cells)'}")
    print()

    def judge(group, label):
        offs = 0
        for n in sorted(group):
            x, y = group[n]
            dx, dy = (x - x0) % site_w, (y - y0) % pitch
            ok = (dx == 0 and dy == 0)
            offs += (not ok)
            print(f"  {label:8s} {n:22s} ({x:>9d},{y:>9d})  "
                  f"x%site={dx:<5d} y%row={dy:<5d}  "
                  f"{'ON GRID' if ok else 'OFF GRID'}")
        return offs

    print("ROUTER-NAMED (DRT-0073) — expected OFF grid:")
    off_named = judge(named, "named")
    missing = [n for n in names if n not in named]
    if missing:
        print(f"  !! not found in DEF: {missing}")
    print()
    print("CONTROL, same class, instances the router did NOT name — expected ON grid:")
    off_ctrl = judge(control, "control")
    print()

    if not named or missing:
        print("INCONCLUSIVE: a named instance is absent from this DEF.")
        return 2
    if len(control) < 4:
        print(f"INCONCLUSIVE: only {len(control)} control instance(s) matched; a "
              f"control that small cannot separate the groups.")
        return 2
    if off_ctrl:
        print(f"WITHDRAWN: {off_ctrl}/{len(control)} CONTROL instances are also off "
              f"grid, so this predicate is not separating the two groups.")
        return 2
    if off_named != len(named):
        print(f"NOT CONFIRMED: only {off_named}/{len(named)} router-named instances "
              f"are off grid.")
        return 1
    print(f"CONFIRMED: {off_named}/{len(named)} router-named instances are OFF the "
          f"site grid; 0/{len(control)} control instances are.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
