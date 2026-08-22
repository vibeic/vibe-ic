#!/usr/bin/env python3
"""Every arithmetic claim in RESULT.md, re-derived from the cell geometry.

WHY: a prose number is not self-checking. The defect this branch fixes was a
WRONG SENTENCE IN A DOCSTRING that nothing re-checked, and the branch later
shipped a header whose own counts summed to 19 of 20. Numbers a reader cannot
re-derive are the ones that rot. These can now be re-derived by running this.

Geometry, MEASURED on the installed gf180mcuD, not asserted here. A self-check
whose own inputs are guesses is consistently wrong rather than right, so each
constant below names where it was read from:

  PAD    =  75 um   pad cell WIDTH -- the along-the-row extent, and the only
                    dimension that belongs in a per-side fit. Every CLASS PAD
                    master in the 15 IO LEFs discovered by
                    _pad_ring.discover_io_lefs is 75 um wide (distinct widths in
                    the library: 0.1, 1, 2, 5, 10 = fillers, 75 = pads,
                    355 = the corner).
  DEPTH  = 350 um   the SAME cell's HEIGHT -- how far the ring reaches INTO the
                    die. Never an along-the-row term. NAMED HERE BECAUSE
                    CONFUSING IT WITH THE WIDTH IS THE SECOND DEFECT THIS BRANCH
                    FIXED: _place took the along-row extent from the master's
                    height, and the flow owner's ruling was that the WIDTH is
                    the along-row extent on all four sides. Two dimensions of
                    one cell, both load-bearing, and a reader who sees only one
                    of them cannot tell which figure is which.
  CORNER = 355 um   gf180mcu_fd_io__cor, SIZE 355 BY 355. NOTE 355 and 350 are
                    five apart and are different cells' different dimensions;
                    a transposition between them looks like a rounding error.
  EDGE   =  26 um   set ::env(PAD_EDGE_SPACING) "26" in
                    gf180mcuD/libs.tech/librelane/gf180mcu_fd_io/config.tcl
                    (and identically in gf180mcu_ocd_io). NOTE: that is the
                    libs.tech view -- the very view whose omission is the defect
                    this branch fixes. The geometry needed to check the numbers
                    lives where the site declaration lives.

A side's usable extent is  die - 2*corner - 2*edge_spacing.

THE THREE STATES, each GRADED by running it, not asserted here:
    rc=0  ALL CHECKS PASS      the report's numbers re-derive
    rc=1  n FAILED             a figure in the report does not re-derive.
                               MEASURED: changing the die to 2.300 mm produces
                               4 failures, each naming the computed value
                               against the published one.
    rc=2  NOT VERIFIED         a pattern stopped matching, or there is no
                               RESULT.md beside this file. MEASURED both ways.
                               NEVER rc=0 on an empty read -- that is the
                               repo's own rule (#564), and it is the same shape
                               the flow owner required of PAD_ROTATION_VERTICAL:
                               refuse, do not pass quietly.
"""
PAD, DEPTH, CORNER, EDGE = 75, 350, 355, 26
def usable(die): return die - 2 * CORNER - 2 * EDGE
def need(n):     return n * PAD
def need_depth(n): return n * DEPTH   # what the pre-ruling code computed

import pathlib, re, sys

REPORT = pathlib.Path(__file__).resolve().parent.parent / "RESULT.md"
TEXT = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""

FAIL = 0
UNVERIFIED = 0
def check(label, got, want):
    global FAIL
    ok = got == want
    if not ok: FAIL += 1
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got} (expected {want})")

# --------------------------------------------------------------------------
# The numbers are READ OUT OF THE REPORT, not retyped here. An earlier draft of
# this file asserted 2262 and the rest as literals -- which checks that the
# geometry is self-consistent and NOT that the document says the same thing.
# Editing a figure in RESULT.md would have left this passing. It is the same
# defect as the module header it was written in response to: a check that does
# not bind to the artefact it is about.
#
# A ZERO DENOMINATOR REFUSES. If a pattern below stops matching -- because the
# report was reworded -- this exits NOT VERIFIED rather than reporting success
# over an empty set. That rule is the repo's own
# (gate_zero_denominator_refuses_check, #564).
# --------------------------------------------------------------------------
def one(pattern, what, cast=int):
    m = re.search(pattern, TEXT)
    if not m:
        print(f"  [NOT VERIFIED] the report no longer states {what} "
              f"in a form this file can read ({pattern})")
        return None
    return cast(m.group(1))

if not TEXT:
    print(f"NOT VERIFIED: no RESULT.md beside this file at {REPORT}")
    raise SystemExit(2)

die      = one(r"DEFAULT_ROTATION_RERUN: \w+ pads=\d+ die=(\d\.\d\d\d) mm", "the die", lambda v: int(round(float(v) * 1000)))
pads     = one(r"DEFAULT_ROTATION_RERUN: \w+ pads=(\d+)", "the pad count")
bal      = re.search(r"BALANCED (\d+)/(\d+)/(\d+)/(\d+) split", TEXT)
decl     = re.search(r"DECLARES\s*\n?(\d+)/(\d+)/(\d+)/(\d+)", TEXT)
over_n   = one(r"N over\s*\n?\s*by (\d+)", "the N overage")
over_s   = one(r"S by (\d+)", "the S overage")
needs    = one(r"needs a (\d)\.(\d\d\d) mm die", "the die the declared split needs",
               lambda v: v) if False else None
m_needs  = re.search(r"needs a (\d\.\d\d\d) mm die", TEXT)
dies     = re.search(r"(\d+), (\d+), (\d+), (\d+) and (\d+) um", TEXT)

missing = [n for n, v in (("die", die), ("pads", pads), ("balanced split", bal),
                          ("declared split", decl), ("N overage", over_n),
                          ("S overage", over_s), ("required die", m_needs),
                          ("the five dies", dies)) if v is None]
if missing:
    print("\nNOT VERIFIED -- the report no longer states: " + ", ".join(missing))
    print("This is a refusal, not a pass. Re-read the report and fix the patterns.")
    raise SystemExit(2)

bal = [int(g) for g in bal.groups()]
decl = [int(g) for g in decl.groups()]
needs = int(round(float(m_needs.group(1)) * 1000))
five = [int(g) for g in dies.groups()]

print(f"READ FROM {REPORT.name}: die={die} pads={pads} balanced={bal} "
      f"declared={decl} needs={needs} dies={five}")

print("\nTHE PUBLISHED DIE AND THE BALANCED SPLIT")
check("the balanced split sums to the pad count", sum(bal), pads)
check("the die is the minimum for the largest side",
      need(max(bal)) + 2 * CORNER + 2 * EDGE, die)
check("usable side at the published die", usable(die), need(max(bal)))

print("\nTHE SPLIT THE DESIGN DECLARES")
check("the declared split sums to the pad count", sum(decl), pads)
check("N overage, in DBU", (need(decl[0]) - usable(die)) * 1000, over_n)
check("S overage, in DBU", (need(decl[1]) - usable(die)) * 1000, over_s)
check("the die the declared split needs",
      need(max(decl)) + 2 * CORNER + 2 * EDGE, needs)

print("\nEVERY DIE A RUN ACTUALLY PRODUCED (five, across two hosts)")
for d in five:
    side = usable(d)
    print(f"  [ok] usable side at {d} um: {side} "
          f"({'no ring fits' if side < PAD else str(side // PAD) + ' pad/side'})")
check("only the largest die fits any pad at all",
      sum(1 for d in five if usable(d) >= PAD), 1)
check("the two corner cells alone exceed the four smallest dies",
      sum(1 for d in five if d < 2 * CORNER), 4)

print("\nTHE TWO DIMENSIONS OF THE PAD CELL ARE NOT INTERCHANGEABLE")
# Raised by the publishing agent, who hit the same ambiguity in their own record:
# a ring term built from the HEIGHT sitting three sections from per-side figures
# built from the WIDTH, with nothing naming them as different quantities.
# NOT `check(PAD != DEPTH, True)`. That compares two literals defined at the top
# of this file and cannot fail whatever the PDK or the artefacts say -- the same
# tautology already removed from the ratio section once. The constants are
# DERIVED FROM THE ARTEFACT here, so a PDK whose cells differ makes this red.
import json as _json
_ev = pathlib.Path(__file__).resolve().parent
_ring_f = _ev / "sha256_gf180_padring_DEFAULT_R0.json"
if not _ring_f.exists():
    print("  [NOT VERIFIED] the default-R0 ring artefact is missing -- cannot judge")
    UNVERIFIED += 1
    _b = {}
else:
    _b = _json.loads(_ring_f.read_text()).get("producer", {})
_pad_w = {p["width_dbu"] for p in _b.get("pads", []) if p["side"] in ("N","S")}
_pad_h = {p["height_dbu"] for p in _b.get("pads", []) if p["side"] in ("N","S")}
_cor_w = {c["width_dbu"] for c in _b.get("corners", [])}
check("PAD is the pad master's width, as placed", _pad_w, {PAD * 1000})
check("DEPTH is the SAME master's height, as placed", _pad_h, {DEPTH * 1000})
check("CORNER is the corner master's width, as placed", _cor_w, {CORNER * 1000})
check("and the vertical pads are the same cell, rotated",
      {(p["width_dbu"], p["height_dbu"]) for p in _b.get("pads", []) if p["side"] in ("E","W")},
      {(DEPTH * 1000, PAD * 1000)})
check("using DEPTH as the along-row extent would break the published die",
      need_depth(max(bal)) + 2 * CORNER + 2 * EDGE > die, True)
print(f"  had _place kept using the height: {DEPTH} um per pad, so the "
      f"{max(bal)}-pad side alone would need "
      f"{need_depth(max(bal)) + 2 * CORNER + 2 * EDGE} um, not {die}")
# 355 and 350 are five apart and belong to DIFFERENT cells -- checked against
# the artefact above, not against each other.

print("\nTHE DIE TABLE, WHICH WAS PUBLISHED AS ARITHMETIC AND NOT BOUND")
# Added after MEASURING how much of the report these checks actually cover:
# 27 of 66 distinct figures. This cluster was derivable all along and simply
# had no check, which is a different thing from being unverifiable.
RING = DEPTH + EDGE                      # 376 um, into the die, per side
inner = one(r"inner region\s+(\d+) x", "the inner region side")
if inner is not None:
    ring_stated = one(r"ring depth/side\s+(\d+) \+ (\d+) = (\d+) um", "the ring depth",
                      lambda v: int(v))
    m_ring = re.search(r"ring depth/side\s+(\d+) \+ (\d+) = (\d+) um", TEXT)
    if m_ring:
        e_s, d_s, r_s = (int(g) for g in m_ring.groups())
        check("the report's ring depth is edge + pad height", e_s + d_s, r_s)
        check("and those are the measured EDGE and DEPTH", (e_s, d_s), (EDGE, DEPTH))
        check("ring depth per side", RING, r_s)
    check("inner region = die - 2*ring", die - 2 * RING, inner)
    area = one(r"inner region\s+\d+ x \d+ um\s+= (\d\.\d\d\d) mm", "the inner area",
               lambda v: float(v))
    if area is not None:
        check("inner area", round(inner * inner / 1e6, 3), area)
    darea = one(r"die\s+\d+ x \d+ um\s+= (\d\.\d\d\d) mm", "the die area",
                lambda v: float(v))
    if darea is not None:
        check("die area", round(die * die / 1e6, 3), darea)

cells = one(r"cells\s+(\d\.\d\d\d) mm", "the reported cell area", lambda v: float(v))
core  = one(r"gives a (\d\.\d\d\d) mm\^2 core", "the derived core area", lambda v: float(v))
side  = one(r"core, side\n?(\d+) um", "the derived core side")
if None not in (cells, core):
    check("core at 20% utilisation", round(cells / 0.20, 3), core)
if side is not None and core is not None:
    check("core side", round((core * 1e6) ** 0.5), side)
    cderived = one(r"of ring = (\d+) um", "the core-derived die")
    if cderived is not None:
        check("core-derived die = side + 2*ring", side + 2 * RING, cderived)

print("\nTHE sky130A MEASUREMENTS, BOUND TO THEIR OWN EVIDENCE JSONs")
# sky130A cells, quoted in the report from the installed PDK:
#   pad 80.0 wide;  corner 200 x 204, NOT SQUARE, so a ROTATED corner presents
#   204 along the north side;  PAD_EDGE_SPACING 0.
# The non-squareness is why the closed form under-predicted by 12 um, so a check
# that used 200 on both axes would reproduce the original mistake.
SKY_PAD, SKY_CORNER_ALONG, SKY_CORNER_ACROSS, SKY_EDGE = 80, 204, 200, 0
sky_avail = die - 2 * SKY_CORNER_ACROSS - 2 * SKY_EDGE
check("sky130A usable side at the published die", sky_avail * 1000, 1862000)
check("sky130A N need, in DBU", decl[0] * SKY_PAD * 1000, 3200000)
check("sky130A N overage", (decl[0] * SKY_PAD - sky_avail) * 1000, 1338000)
check("sky130A S need, in DBU", decl[1] * SKY_PAD * 1000, 2640000)
check("sky130A S overage", (decl[1] * SKY_PAD - sky_avail) * 1000, 778000)
check("the closed form with the ROTATED corner (204, not 200)",
      decl[0] * SKY_PAD + 2 * SKY_CORNER_ALONG, 3608)
check("and with the wrong corner axis it under-predicts by 12",
      3612 - (decl[0] * SKY_PAD + 2 * SKY_CORNER_ACROSS), 12)

import json
_here = _ev / "declared_grouping"
for fn, want_verdict, want_die in (
        ("sky130_DECLARED_on_2262_FAILS.json",  "FAIL", 2262000),
        ("sky130_DECLARED_on_3612_PASSES.json", "PASS", 3612000)):
    f = _here / fn
    if not f.exists():
        # rc=2, NOT rc=1. "I could not look" and "the numbers disagree" are
        # different outcomes and an earlier version of this file conflated them
        # by counting a missing artefact as a FAILURE. That is exactly the
        # conflation #492 records in flow_compliance_check.py:7220 -- recording
        # "you called me wrongly" as the same thing as a verdict "is what let 39
        # registered gates be permanently silent". Caught here by grading the
        # refusal path instead of only the pass path.
        print(f"  [NOT VERIFIED] {fn} is missing -- cannot judge, not a failure")
        UNVERIFIED += 1
        continue
    d = json.loads(f.read_text())
    check(f"{fn} verdict", d["verdict"], want_verdict)
    check(f"{fn} die (DBU)", d["die"]["diearea"][1][0], want_die)
    check(f"{fn} grouping", [d["config"]["pads_per_side"][k] for k in
                             ("PAD_NORTH","PAD_SOUTH","PAD_EAST","PAD_WEST")], decl)
sky_pass = one(r"(\d\.\d\d\d) mm on sky130A", "the sky130A minimum",
               lambda v: int(round(float(v) * 1000)))
if sky_pass is not None:
    check("the report's sky130A minimum matches the PASSING run's die",
          sky_pass * 1000, 3612000)

print("\nTHE ORIENTATION FIX MOVED NOTHING -- PRE/POST, SAME NETLIST")
# A/B regenerated 2026-08-22 from ONE netlist and ONE builder, with only the
# PROGRAMS swapped (main's vs this branch's). The earlier pair could not be
# compared this way: its two halves came from different netlists, so the pad
# positions differed for reasons that had nothing to do with the fix, and this
# check reported "positions changed" when the real answer was "you compared
# two different rings".
_pre_f, _post_f = _ev / "orient_AB_PRE_fix.json", _ev / "orient_AB_POST_fix.json"
if not (_pre_f.exists() and _post_f.exists()):
    print("  [NOT VERIFIED] an orientation A/B artefact is missing")
    UNVERIFIED += 1
    _b = {}
else:
    _a = json.loads(_pre_f.read_text())
    _a = _a.get("producer", _a)
    _b = json.loads(_post_f.read_text())
    _b = _b.get("producer", _b)
    xy = lambda d, k: {(x["instance"], x["x"], x["y"]) for x in d.get(k, [])}
    check("pad positions unchanged by the orientation fix",
          xy(_a, "pads") == xy(_b, "pads"), True)
    check("corner positions unchanged", xy(_a, "corners") == xy(_b, "corners"), True)
    check("die unchanged", _a["die"]["diearea"] == _b["die"]["diearea"], True)
    _o = lambda d: {(p["instance"], p["orient"]) for p in d["pads"]}
    _chg = {i for i, _ in _o(_a) - _o(_b)}
    _side = {p["instance"]: p["side"] for p in _b["pads"]}
    check("every pad whose orientation changed is on the NORTH side",
          {_side[i] for i in _chg}, {"N"})
    check("and that is every north pad",
          len(_chg), sum(1 for p in _b["pads"] if p["side"] == "N"))
    check("NORTH was a rotation and is now the placer's mirror",
          (sorted({p["orient"] for p in _a["pads"] if p["side"] == "N"}),
           sorted({p["orient"] for p in _b["pads"] if p["side"] == "N"})),
          (["S"], ["FS"]))
    check("the two corners the tool mirrors were rotated before",
          ({c["position"]: c["orient"] for c in _a["corners"]},
           {c["position"]: c["orient"] for c in _b["corners"]}),
          ({"SW": "N", "SE": "E",  "NE": "S", "NW": "W"},
           {"SW": "N", "SE": "FN", "NE": "S", "NW": "FS"}))

print("\nPART 3 OF THE RULING, READ OUT OF THE DEF THE TOOL WROTE")
# "The DEF must not contradict itself": the vertical sides must carry the
# orientation the placer actually produces, MXR90/R90 -> DEF FW/W. Counted in
# the DEF rather than in the JSON, because the DEF is the artefact a downstream
# reader parses and the one the ruling is about.
_pre_def  = _ev / "sha256_gf180_padring.def"
_post_def = _ev / "sha256_gf180_padring_DEFAULT_R0.def"
if not (_pre_def.exists() and _post_def.exists()):
    print("  [NOT VERIFIED] a padring DEF is missing -- cannot judge")
    UNVERIFIED += 1
else:
    def orients(path):
        out = {}
        for m in re.finditer(r"\b(FN|FS|FE|FW|N|S|E|W)\s*;", path.read_text()):
            out[m.group(1)] = out.get(m.group(1), 0) + 1
        return out
    pre, post = orients(_pre_def), orients(_post_def)
    n_w = sum(1 for p in _b.get("pads", []) if p["side"] == "W")
    n_e = sum(1 for p in _b.get("pads", []) if p["side"] == "E")
    check("the PRE-ruling DEF contains no FW at all", pre.get("FW", 0), 0)
    check("the current DEF carries FW once per WEST pad", post.get("FW", 0), n_w)
    check("west pad count matches the balanced split", n_w, bal[3])
    check("east pad count matches the balanced split", n_e, bal[2])
    check("both DEFs still hold 81 components",
          [len(re.findall(r"^\s*- ", f.read_text(), re.M)) for f in (_pre_def, _post_def)],
          [81, 81])

print("\nTHE SHIPPED HEADER'S CORPUS CLAIM, BOUND TO THE SWEEP THAT MEASURED IT")
# The module header states a 7/4/3/2/2/0/0 breakdown of the PDK corpus. It was
# CORRECT when checked -- and so was the variable count, right up until it was
# not. The count shipped wrong because nothing bound it; this binds the other
# one, against the sweep's own rows rather than against the prose.
_sweep = _ev / "flow_change_acceptance" / "corpus_sweep.txt"
if not _sweep.exists():
    print("  [NOT VERIFIED] corpus_sweep.txt is missing -- cannot judge")
    UNVERIFIED += 1
else:
    _t = _sweep.read_text()
    _rows = json.loads(_t[:_t.rindex("}") + 1])["rows"]
    _io   = [r for r in _rows if r["n_io_lefs"] > 0]
    _lef  = [r for r in _io if r["lef_pad_class_sites"]]
    _tech = [r for r in _io if r["declared_sites"] and not r["lef_pad_class_sites"]]
    check("trees swept", len(_rows), 7)
    check("carry an IO cell library", len(_io), 4)
    check("carry none", len(_rows) - len(_io), 3)
    check("declare via LEF SITE records", len(_lef), 2)
    check("declare via the TECH view", len(_tech), 2)
    check("declare in neither",
          len([r for r in _io if not r["lef_pad_class_sites"] and not r["declared_sites"]]), 0)
    check("declare one site at two sizes", len([r for r in _rows if r["conflicts"]]), 0)
    check("the two halves account for every IO tree", len(_lef) + len(_tech), len(_io))

print("\nRATIOS AGAINST THE LARGEST DIE EVER PRODUCED")
big = max(five)
# NOT check(x, round(die/big,3), round(die/big,3)) -- an earlier draft of this
# file compared a value to ITSELF, which passes whatever the report says. The
# only non-vacuous form is comparing the computed ratio against the STRING the
# report publishes, which is what the two checks below do.
print(f"  computed: {die}/{big} = {die/big:.3f}, {needs}/{big} = {needs/big:.3f}")
check("the report quotes the die ratio to 2dp",
      f"{die/big:.2f}x" in TEXT, True)
check("the report quotes the required-die ratio to 2dp",
      f"{needs/big:.2f}x" in TEXT, True)

if FAIL:
    print(f"\n{FAIL} FAILED" + (f", {UNVERIFIED} NOT VERIFIED" if UNVERIFIED else ""))
    raise SystemExit(1)
if UNVERIFIED:
    print(f"\nNOT VERIFIED: {UNVERIFIED} check(s) could not see their subject. "
          "This is rc=2 -- a refusal, not a pass and not a failure.")
    raise SystemExit(2)
print("\nALL CHECKS PASS")
raise SystemExit(0)
