#!/usr/bin/env python3
"""latchup_esd_spacing_check.py — the OPEN-SOURCE GEOMETRY-LAYER half of PERC
latch-up / ESD sign-off (v0.2.30), built from the routed DEF, deterministic +
pure + chip-AGNOSTIC.

WHERE THIS SITS IN THE PERC STACK
---------------------------------
`phase3_one_shot_runner.py` already automates the PRESENCE / connectivity /
topology layer:
  * _welltap_presence_check     — latch-up tap PRESENCE (0 taps = conclusive GAP)
  * _esd_pad_ring_presence      — ESD cell PRESENCE on the pad ring
  * _esd_discharge_topology     — ESD C2/C3 connectivity (open loop / dangling clamp)
  * _xdomain_levelshifter_check — cross-voltage-domain crossing presence
Those presence checks deliberately do NOT look at SPATIAL geometry; their
docstrings explicitly defer tap SPACING ("max-tap-distance — DRC deck") and
guard-ring topology to a separate layer. THIS file is that separate geometry
layer. It REUSES the shipped DEF parsers from phase3_one_shot_runner (imported,
never re-implemented) and adds three spatial screens read from the routed DEF:

  _latchup_tap_spacing_check    — parse tap-cell + std-cell placement boxes + DIEAREA;
                                  screen max-tap-distance coverage of the std-cell field.
  _guardring_topology_check     — detect guard-ring cell masters + their proximity to
                                  IO / high-current cells.
  _esd_clamp_netlist_connectivity — (optional) confirm each clamp is tied to BOTH a
                                  power AND a ground net (from an extracted netlist).

⚠️ ANTI-OVER-CLAIM RULE (a 6-agent adversarial panel PROVED spacing-from-DEF-alone
over-claims). The spacing screen is CONCLUSIVE-FAIL-ONLY. It may return only:
  * WELLTAP_SPACING_GAP — a CONCLUSIVE fail: 0 taps, OR a demonstrable std-cell
        region that is provably > the screening max-distance from EVERY tap, on a
        well-formed DIEAREA.
  * INCOMPLETE — degenerate / missing DIEAREA, unrecognised tap cells, or a screening
        pitch that is *looser* than the (unknown, foundry-calibrated) real rule — i.e.
        anything where a clean DEF could still be unsafe. NEVER over-claims.
  * SPACING_OK_NECESSARY_NOT_SUFFICIENT — every std cell is within the *conservative*
        screening distance of a tap. This is EXPLICITLY necessary-but-not-sufficient:
        it does NOT prove the device-physics latch-up criterion. NEVER an automated
        "PASS" that implies latch-up safety.
This mirrors the existing honesty doctrine: the presence checks never auto-PASS
device physics, and neither does this geometry layer.

THE GENUINE FOUNDRY-DATA RESIDUAL (CANNOT be done open-source)
--------------------------------------------------------------
This layer screens GEOMETRY. It still does NOT — and physically CANNOT, without
foundry process data — prove:
  * ESD clamp HBM/CDM device sizing (It2 / clamp W, trigger): needs TLP measurement
    + foundry ESD device models.
  * latch-up holding voltage Vhold > Vdd and the parasitic-SCR npn·pnp beta product:
    needs the foundry's calibrated substrate / well doping + SCR models.
  * guard-ring efficacy under substrate-current injection: needs the foundry-calibrated
    substrate RC network (the open-source ngspice device set does NOT ship it).
That residual is NOT commercial-tool lock-in — it is a real physical need for
foundry-calibrated process models. The open-source flow can screen geometry and
catch conclusive structural exposures; it cannot prove the device physics.

NOTE on the sky130 open-source DRC deck: the KLayout sky130A.lydrc deck ships
only MINIMUM-spacing tap rules (difftap.*, poly.5/6) — there is NO maximum
tap-distance (latch-up) rule in the open deck. So this screen CANNOT cite a
foundry max-tap-distance; it uses a documented *conservative* screening distance
and marks any verdict that leans on a looser-than-real pitch INCOMPLETE.

Usage:
    python3 latchup_esd_spacing_check.py <routed.def>                 # full JSON report
    python3 latchup_esd_spacing_check.py <routed.def> --netlist <f>   # + clamp netlist check
    python3 latchup_esd_spacing_check.py <routed.def> --max-um <d>    # override screen distance
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase3_one_shot_runner as _p  # noqa: E402  (shipped DEF parsers — single source)


# --------------------------------------------------------------------------- #
# CONSERVATIVE screening distance.
#
# We do NOT have the foundry's calibrated max-tap-distance latch-up rule (it is
# not in the open sky130 KLayout deck). A typical industrial digital-logic
# substrate/well-tap pitch is "a tap roughly every 15-25 um of standard-cell
# row" for a low-current digital core. We screen at a DELIBERATELY GENEROUS
# 30 um radius: large enough that a clean SPACING_OK is only emitted when the
# field is comfortably tapped, AND any verdict that would only pass under a
# looser pitch than the real (unknown) rule is forced to INCOMPLETE — never a
# false "OK". The point of the screen is to catch the CONCLUSIVE failure (a
# whole region of logic with no tap anywhere near it), not to certify the pitch.
# --------------------------------------------------------------------------- #
_DEFAULT_SCREEN_UM = 30.0
# Below this many placed std cells, a sparse-tap result is not yet a meaningful
# spacing signal (tiny / floorplan-class block) — INCOMPLETE, never a GAP.
_MIN_STD_FOR_SPACING = 50
# A DIEAREA whose smaller side is below this is treated as degenerate (a
# placeholder / 0-area / 1-point die) → INCOMPLETE, never used to claim a GAP.
_MIN_DIE_SIDE_UM = 1.0

# Guard-ring master tokens (chip-AGNOSTIC substrings). sky130 IO guard structures
# and generic guard-ring / substrate-ring / well-ring cells. Matched on the master
# name only — never on net/instance names.
_GUARDRING_TOKENS = (
    "guard", "_gr_", "_gring", "guardring", "substrate_ring", "subring",
    "well_ring", "wellring", "psub_ring", "nwell_ring", "_dgr", "deepnwell_ring",
)

# COMPONENTS line WITH placement geometry:
#   - <inst> <master> + (PLACED|FIXED|COVER|SOURCE ...) ( <x> <y> ) <ORIENT> ;
# We tolerate an arbitrary run of attribute tokens (e.g. "+ SOURCE DIST + FIXED")
# before the placement coordinate, and capture the FIRST "( x y )" pair.
_COMP_GEOM_RE = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+).*?\(\s*(-?\d+)\s+(-?\d+)\s*\)",
    re.MULTILINE | re.DOTALL,
)
# DIEAREA — accept both "( x1 y1 ) ( x2 y2 )" and the flat "( x1 y1 x2 y2 )" form,
# and a rectilinear polygon DIEAREA (>2 points): take the bounding box of all points.
_DIEAREA_RE = re.compile(r"^\s*DIEAREA\b([^;]*);", re.MULTILINE)
_DIEAREA_NUM_RE = re.compile(r"-?\d+")
_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", re.MULTILINE)


def _read_def_text(def_file: Path) -> Optional[str]:
    try:
        return Path(def_file).read_text(errors="ignore")
    except OSError:
        return None


def _parse_units(def_text: str) -> int:
    """DEF database-units-per-micron. Defaults to 1000 (sky130/OpenLane default)."""
    m = _UNITS_RE.search(def_text)
    return int(m.group(1)) if m else 1000


def _parse_diearea_um(def_text: str, units: int) -> Optional[Tuple[float, float, float, float]]:
    """Return DIEAREA bounding box (x1,y1,x2,y2) in MICRONS, or None if absent /
    unparseable. Handles the two-paren, flat, and rectilinear-polygon forms by
    taking the bounding box of all integer coordinates on the DIEAREA line."""
    m = _DIEAREA_RE.search(def_text)
    if not m:
        return None
    nums = [int(n) for n in _DIEAREA_NUM_RE.findall(m.group(1))]
    if len(nums) < 4 or len(nums) % 2 != 0:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return (min(xs) / units, min(ys) / units, max(xs) / units, max(ys) / units)


def _parse_placed_geometry(def_text: str) -> List[Tuple[str, str, int, int]]:
    """Parse the DEF COMPONENTS block into [(inst, master, x_dbu, y_dbu), ...].

    chip-AGNOSTIC structural parse with placement coordinates (the geometry the
    shipped _parse_def_components intentionally drops). x,y are in DEF database
    units (the lower-left placement point — sufficient for a coverage screen;
    we are not doing exact box-overlap, only nearest-tap distance)."""
    out: List[Tuple[str, str, int, int]] = []
    cm = re.search(r"^COMPONENTS\b.*?^END COMPONENTS",
                   def_text, re.MULTILINE | re.DOTALL)
    if not cm:
        return out
    for g in _COMP_GEOM_RE.finditer(cm.group(0)):
        inst, master, x, y = g.group(1), g.group(2), int(g.group(3)), int(g.group(4))
        if master in (";", "+"):
            continue
        out.append((inst, master, x, y))
    return out


def _is_rated_tap(master: str,
                  extra_masters: Optional[Sequence[str]] = None) -> bool:
    """A rated well/substrate-tap master (reuse the shipped allowlist).

    `extra_masters` is the PDK's OWN configured tap cell(s) (`pdk.tapcell_master`),
    forwarded by the caller so this screen is CHIP-AGNOSTIC. gf180mcu names its
    `CLASS core WELLTAP` cell `gf180mcu_fd_sc_mcu7t5v0__filltie` — no `tap` token
    and not on the sky130-only shipped allowlist — so without this a run that
    inserted 380 real tap cells (DRC DF.13/DF.14 clean) still reported
    "0 rated tap cells" and false-FAILed the latch-up screen."""
    ml = master.lower()
    if any(ml.startswith(r) for r in _p._WELLTAP_RATED):
        return True
    if extra_masters:
        return any(e and ml.startswith(e.lower()) for e in extra_masters)
    return False


def _is_tap_tokened(master: str) -> bool:
    """A 'tap'-token master (may be unrated — used to flag unrecognised taps)."""
    return bool(_p._WELLTAP_TOKEN_RE.search(master.lower()))


def _is_std_cell(master: str) -> bool:
    """Transistor-bearing std cell (same exclusion rule as the shipped presence
    check: drop tap / fill / decap / diode / endcap / boundary / antenna)."""
    ml = master.lower()
    if _p._WELLTAP_TOKEN_RE.search(ml) or _is_rated_tap(master):
        return False
    return not any(t in ml for t in ("decap", "fill", "diode", "tapvpwr",
                                     "_endcap", "boundary", "antenna"))


def _grid_min_dist_exceeds(std_pts: List[Tuple[float, float]],
                           tap_pts: List[Tuple[float, float]],
                           radius_um: float) -> Optional[Tuple[float, float, float]]:
    """Return (x, y, dist) of a std cell whose NEAREST tap is > radius_um away, or
    None if every std cell has a tap within radius_um. Uniform-grid spatial hash so
    we never do the O(N*M) all-pairs scan on large designs. Distances in microns."""
    if not tap_pts:
        return (std_pts[0][0], std_pts[0][1], float("inf")) if std_pts else None
    cell = max(radius_um, 1e-6)
    grid: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for tx, ty in tap_pts:
        grid.setdefault((int(tx // cell), int(ty // cell)), []).append((tx, ty))
    r2 = radius_um * radius_um
    worst: Optional[Tuple[float, float, float]] = None
    for sx, sy in std_pts:
        gx, gy = int(sx // cell), int(sy // cell)
        best2 = None
        # the nearest tap (if within radius) must lie in the 3x3 neighbour cells
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for tx, ty in grid.get((gx + dx, gy + dy), ()):  # noqa: E501
                    d2 = (sx - tx) ** 2 + (sy - ty) ** 2
                    if best2 is None or d2 < best2:
                        best2 = d2
        if best2 is None or best2 > r2:
            # demonstrably > radius from any tap (None means no tap in 3x3 block)
            d = float("inf") if best2 is None else best2 ** 0.5
            if worst is None or d > worst[2]:
                worst = (sx, sy, d)
    return worst


def _count_within(query_pts: List[Tuple[float, float]],
                  anchor_pts: List[Tuple[float, float]],
                  radius_um: float) -> int:
    """How many query points have at least one anchor point within radius_um.
    Same uniform-grid spatial hash as _grid_min_dist_exceeds (no all-pairs scan)."""
    if not anchor_pts or not query_pts:
        return 0
    cell = max(radius_um, 1e-6)
    grid: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for ax, ay in anchor_pts:
        grid.setdefault((int(ax // cell), int(ay // cell)), []).append((ax, ay))
    r2 = radius_um * radius_um
    n = 0
    for qx, qy in query_pts:
        gx, gy = int(qx // cell), int(qy // cell)
        hit = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for ax, ay in grid.get((gx + dx, gy + dy), ()):
                    if (qx - ax) ** 2 + (qy - ay) ** 2 <= r2:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        n += 1 if hit else 0
    return n


# --------------------------------------------------------------------------- #
# 1) latch-up tap-SPACING screen — CONCLUSIVE-FAIL-ONLY                        #
# --------------------------------------------------------------------------- #
def _sparse_die_tap_skip_attested(def_file: Path) -> bool:
    """#684 round-8 — True iff the runner attested a DELIBERATE sparse-die
    tapcell skip for the project owning this DEF. Derives the project dir from
    the canonical DEF path (phase3/stage3/pnr/<def> → 3 levels up) and reads
    reports/phase3/sparse_die_skip.json. Read-only, fail-safe. chip-AGNOSTIC."""
    try:
        # routed.def lives at <project>/phase3/stage3/pnr/<file>. Use the
        # path AS GIVEN (parents[3]) — NOT .resolve() — so the project dir is
        # the one the gate was invoked against (a symlinked DEF must still
        # find the project's own attestation, not the symlink target's).
        cand = []
        if len(def_file.parents) > 3:
            cand.append(def_file.parents[3])
        cand.append(def_file.absolute().parents[3]
                    if len(def_file.absolute().parents) > 3 else None)
        for project in cand:
            if project is None:
                continue
            att = _p._load_sparse_die_skip(project)
            if att and att.get("tapcell_skipped"):
                return True
        return False
    except Exception:
        return False


def _latchup_tap_spacing_check(def_file: Path,
                               screen_um: float = _DEFAULT_SCREEN_UM,
                               rated_tap_masters: Optional[Sequence[str]] = None,
                               tapless_pdk: bool = False
                               ) -> Dict[str, Any]:
    """Screen well/substrate-tap SPATIAL coverage of the std-cell field from the
    routed DEF. CONCLUSIVE-FAIL-ONLY per the anti-over-claim rule.

    status ∈ {
      WELLTAP_SPACING_GAP — CONCLUSIVE fail (0 taps with placed logic, OR a std-cell
          region provably > screen_um from EVERY tap on a well-formed DIEAREA),
      INCOMPLETE          — degenerate/missing DIEAREA, no parseable geometry,
          unrecognised tap cells, too-few std cells, or a screen looser than the
          real (foundry) rule could be → NEVER over-claim,
      SPACING_OK_NECESSARY_NOT_SUFFICIENT — every std cell is within screen_um of a
          tap; EXPLICITLY necessary-but-not-sufficient (device physics unverified).
    }
    Verdict ORDER (load-bearing): ZERO_TAPS is conclusive REGARDLESS of cell count
    (any placed logic with no substrate tie latches up — matches the shipped presence
    doctrine), so it is decided FIRST. The too-few-cells INCOMPLETE guard only
    suppresses the SPARSE-COVERAGE (UNTAPPED_REGION) verdict on a tiny block — it
    never downgrades a genuine ZERO_TAPS gap.
    Never emits an automated PASS implying latch-up safety."""
    base: Dict[str, Any] = {"check": "latchup_tap_spacing", "screen_um": screen_um}
    text = _read_def_text(def_file)
    if text is None:
        return {**base, "status": "INCOMPLETE", "reason": "DEF_UNREADABLE",
                "note": "Routed DEF could not be read — cannot screen tap spacing."}

    units = _parse_units(text)
    die = _parse_diearea_um(text, units)
    geom = _parse_placed_geometry(text)
    std = [(x / units, y / units) for _i, m, x, y in geom if _is_std_cell(m)]
    taps = [(x / units, y / units) for _i, m, x, y in geom
            if _is_rated_tap(m, rated_tap_masters)]
    unknown_taps = sorted({m for _i, m, _x, _y in geom
                           if _is_tap_tokened(m)
                           and not _is_rated_tap(m, rated_tap_masters)})
    base.update({"n_std": len(std), "n_tap": len(taps),
                 "unknown_taps": unknown_taps, "units_per_um": units,
                 "diearea_um": list(die) if die else None})

    if not geom:
        return {**base, "status": "INCOMPLETE", "reason": "NO_PLACED_GEOMETRY",
                "note": ("DEF has no parseable placed COMPONENTS geometry — cannot "
                         "screen tap spacing (not a placed/routed block).")}

    # CONCLUSIVE GAP #1: placed logic but ZERO taps. This is the same conclusive
    # signal the shipped presence check finds — restated here in the spacing layer
    # so the geometry report is self-contained.
    if len(std) >= 1 and not taps:
        extra = (f" ({len(unknown_taps)} 'tap'-token master(s) seen but none rated: "
                 + ", ".join(unknown_taps[:4]) + ")") if unknown_taps else ""
        # #684 round-8 — §4.05 NO-LEAK: a genuine 0-tap break STILL FAILs.
        # Only when the runner ATTESTED a deliberate sparse-die tapcell skip
        # (sparse_die_skip.json) is this downgraded to a documented REVIEW
        # item (non-GAP status) — tap insertion over the occupied region is
        # deferred to the real foundry max-tap-distance rule, not a silent
        # break. A non-sparse design with 0 taps has no attestation → GAP.
        if _sparse_die_tap_skip_attested(def_file):
            return {**base, "status": "WELLTAP_SPARSE_DIE_DEFERRED",
                    "reason": "ZERO_TAPS_SPARSE_DIE_ATTESTED",
                    "note": (f"{len(std)} placed std cell(s) and 0 rated taps, but the "
                             f"runner ATTESTED a deliberate sparse-die tapcell skip "
                             f"(#684){extra} — full-die tapcell tiling was bounded on a "
                             "sub-threshold fixed wrapper. Tap insertion over the "
                             "occupied region is a REVIEW open item against the real "
                             "foundry tap-distance rule, NOT a conclusive structural "
                             "GAP. (A non-sparse 0-tap design still FAILs ZERO_TAPS.)")}
        # TAPLESS-CELL PDK: 0 tap COMPONENTS in the DEF is EXPECTED, not a gap —
        # the well/substrate ties are INSIDE every std cell, so there is no
        # tapcell master to insert and nothing was "skipped". Without this the
        # DEF-component count produces a CONCLUSIVE false FAIL on every such
        # PDK (measured twice on the IHP SG13 family: sg13g2 "452 placed std
        # cell(s) but no well taps" and sg13cmos5l "364 placed std cell(s) but
        # 0 rated well/substrate-tap cell(s)" — both designs' ties are present
        # and measurable in the sign-off GDS).
        #
        # `rated_tap_masters=None` ALONE cannot carry this: it means both "the
        # PDK declares no tapcell" and "the caller passed nothing", which is
        # exactly why the guard could not live here before. `tapless_pdk` is
        # the explicit, caller-supplied signal (pdk.tapcell_master is None).
        #
        # This is INCOMPLETE, never a PASS: presence is confirmed positively by
        # the GDS tap-diffusion measurement (pdk.tap_geom_layers) and real
        # spacing by the foundry DRC deck's latch-up rules. No over-claim.
        if tapless_pdk:
            return {**base, "status": "INCOMPLETE",
                    "reason": "ZERO_TAPS_TAPLESS_PDK",
                    "note": (f"{len(std)} placed std cell(s) and 0 tap COMPONENTS"
                             f"{extra} — but this PDK declares NO tapcell master "
                             "(tapless-cell library: well/substrate ties are "
                             "internal to every std cell), so the DEF-component "
                             "count CANNOT conclude and 0 is the EXPECTED value. "
                             "Confirm the ties positively via the sign-off-GDS "
                             "tap-diffusion measurement (set `tap_geom_layers` in "
                             "the PDK registry entry) and the foundry DRC deck's "
                             "latch-up rules. NOT a conclusive structural GAP.")}
        return {**base, "status": "WELLTAP_SPACING_GAP", "reason": "ZERO_TAPS",
                "note": (f"{len(std)} placed std cell(s) but 0 rated well/substrate-tap "
                         f"cell(s){extra} — every logic transistor is infinitely far "
                         "from any tap = categorical latch-up exposure. CONCLUSIVE "
                         "structural GAP (the tapcell step was skipped).")}

    # Below the meaningful-block threshold, a sparse field is not a spacing signal.
    if len(std) < _MIN_STD_FOR_SPACING:
        return {**base, "status": "INCOMPLETE", "reason": "TOO_FEW_STD_CELLS",
                "note": (f"only {len(std)} placed std cell(s) (< {_MIN_STD_FOR_SPACING}) "
                         "— tiny / floorplan-class block; tap-spacing coverage is not "
                         "yet a meaningful screen here (no over-claim).")}

    # A degenerate / missing DIEAREA cannot anchor a 'well-formed-die' GAP claim.
    if die is None or min(die[2] - die[0], die[3] - die[1]) < _MIN_DIE_SIDE_UM:
        return {**base, "status": "INCOMPLETE", "reason": "DEGENERATE_DIEAREA",
                "note": ("DIEAREA is missing or degenerate (zero/sub-micron side) — "
                         "cannot establish a well-formed die to make a CONCLUSIVE "
                         "spacing GAP claim. Spacing screen withheld (no over-claim).")}

    # CONCLUSIVE GAP #2: a std cell provably > screen_um from EVERY tap. Because
    # the screen is DELIBERATELY GENEROUS (looser than any real rule), a violation
    # here is conclusive regardless of the unknown foundry pitch: if a cell is
    # >30um from any tap, it is >real_pitch from any tap too.
    worst = _grid_min_dist_exceeds(std, taps, screen_um)
    if worst is not None:
        wx, wy, wd = worst
        dstr = "infinitely (no tap in neighbourhood)" if wd == float("inf") else f"{wd:.2f} um"
        return {**base, "status": "WELLTAP_SPACING_GAP", "reason": "UNTAPPED_REGION",
                "worst_std_um": [round(wx, 3), round(wy, 3)],
                "worst_dist_um": (None if wd == float("inf") else round(wd, 3)),
                "note": (f"a placed std cell at ({wx:.2f},{wy:.2f}) um is {dstr} from "
                         f"the nearest tap — beyond even the deliberately-generous "
                         f"{screen_um} um screening radius. Since the screen is LOOSER "
                         "than any real foundry tap-pitch rule, this under-tapped region "
                         "is a CONCLUSIVE latch-up spacing exposure.")}

    # Every std cell is within the GENEROUS screen radius. Necessary-not-sufficient.
    return {**base, "status": "SPACING_OK_NECESSARY_NOT_SUFFICIENT",
            "note": (f"every one of {len(std)} placed std cell(s) is within the "
                     f"conservative {screen_um} um screening radius of a rated tap. "
                     "NECESSARY-BUT-NOT-SUFFICIENT: this screens coverage at a pitch "
                     "LOOSER than (and therefore cannot certify) the real foundry "
                     "max-tap-distance rule, and proves NOTHING about the device-physics "
                     "latch-up criterion (Vhold>Vdd, parasitic-SCR beta product, "
                     "guard-ring efficacy). NOT an automated latch-up PASS.")}


# --------------------------------------------------------------------------- #
# 2) guard-ring topology screen                                               #
# --------------------------------------------------------------------------- #
def _is_guardring(master: str) -> bool:
    return any(t in master.lower() for t in _GUARDRING_TOKENS)


def _guardring_topology_check(def_file: Path,
                              proximity_um: float = 50.0) -> Dict[str, Any]:
    """Detect guard-ring cell masters and screen their PROXIMITY to IO / high-current
    cells, from the routed DEF. chip-AGNOSTIC.

    Latch-up risk concentrates at IO pads and high-current drivers; a guard ring
    should sit near them. This screen reports:
      * PRESENT  — guard-ring masters detected (with how many IO/hi-current cells
                   have a guard ring within proximity_um);
      * ABSENT   — IO / high-current cells exist but NO guard-ring master is placed
                   (a candidate latch-up-robustness gap — MANUAL, not auto-fail,
                   because many digital cores legitimately rely on tap density + the
                   pad-frame's own guard ring rather than core guard rings);
      * NA       — no IO / high-current cells AND no guard-ring cells (pure low-current
                   digital core — core guard rings are not expected).

    HONESTY: guard-ring PRESENCE / proximity is a topology screen only. It does NOT
    prove guard-ring EFFICACY (collection efficiency under substrate-current
    injection) — that needs the foundry-calibrated substrate RC model. Never a PASS."""
    base: Dict[str, Any] = {"check": "guardring_topology", "proximity_um": proximity_um}
    text = _read_def_text(def_file)
    if text is None:
        return {**base, "status": "INCOMPLETE", "reason": "DEF_UNREADABLE",
                "note": "Routed DEF could not be read — cannot screen guard rings."}
    units = _parse_units(text)
    geom = _parse_placed_geometry(text)
    if not geom:
        return {**base, "status": "INCOMPLETE", "reason": "NO_PLACED_GEOMETRY",
                "note": "DEF has no parseable placed COMPONENTS geometry."}

    guard_pts: List[Tuple[float, float]] = []
    guard_masters = set()
    risk_pts: List[Tuple[float, float]] = []   # IO / high-current cells
    risk_masters = set()
    for _i, m, x, y in geom:
        if _is_guardring(m):
            guard_pts.append((x / units, y / units))
            guard_masters.add(m)
            continue
        role = _p._classify_io_cell(m)
        if role in ("esd_pad", "nonesd_pad"):
            risk_pts.append((x / units, y / units))
            risk_masters.add(m)
    base.update({"n_guardring": len(guard_pts),
                 "guardring_masters": sorted(guard_masters),
                 "n_io_or_hicurrent": len(risk_pts),
                 "io_hicurrent_masters_sample": sorted(risk_masters)[:8]})

    if not guard_pts and not risk_pts:
        return {**base, "status": "NA",
                "note": ("No guard-ring cells AND no IO / high-current cells placed — "
                         "a low-current digital core; core guard rings are not expected "
                         "(latch-up robustness rests on tap density, screened separately).")}

    if not guard_pts and risk_pts:
        return {**base, "status": "GUARDRING_ABSENT",
                "note": (f"{len(risk_pts)} IO / high-current cell(s) placed but NO "
                         "guard-ring master detected in the DEF. Candidate latch-up / "
                         "noise-isolation gap around the high-injection cells — MANUAL "
                         "review required (many digital cores legitimately rely on the "
                         "pad-frame's guard ring + tap density rather than core rings; "
                         "this screen cannot tell which, so it never auto-fails).")}

    # Guard rings present — report proximity coverage of the risk cells.
    near = _count_within(risk_pts, guard_pts, proximity_um) if risk_pts else 0
    return {**base, "status": "GUARDRING_PRESENT",
            "io_hicurrent_within_proximity": near,
            "note": (f"{len(guard_pts)} guard-ring cell instance(s) detected "
                     f"({len(guard_masters)} master(s)); "
                     + (f"{near}/{len(risk_pts)} IO/high-current cell(s) have a guard "
                        f"ring within {proximity_um} um. " if risk_pts else "")
                     + "PRESENCE/proximity only — this does NOT prove guard-ring "
                     "EFFICACY (substrate-current collection), which needs the "
                     "foundry-calibrated substrate RC model. Not a PASS.")}


# --------------------------------------------------------------------------- #
# 3) ESD clamp netlist connectivity (optional — needs an extracted netlist)   #
# --------------------------------------------------------------------------- #
# A SPICE subckt instance line: `Xname net1 net2 ... netN subcktname [k=v ...]`.
# The subckt MASTER is the last token that is NOT a `key=value` parameter; every
# token between the instance name and the master is a connected NET. We do not
# assume a fixed pin count (extracted netlists vary), so we classify the master by
# the shipped IO-cell classifier and take all preceding non-param tokens as nets.
_PARAM_RE = re.compile(r"^\S+=\S+$")


def _split_spice_inst(line: str) -> Optional[Tuple[str, str, List[str]]]:
    """Return (inst, subckt_master, [nets]) for an `X...` subckt instance line, or
    None if it is not a subckt instance. Trailing key=value params are dropped; the
    last remaining token is the master, the middle tokens are the nets."""
    toks = line.split()
    if len(toks) < 3 or not toks[0][:1] in ("x", "X"):
        return None
    body = [t for t in toks[1:] if not _PARAM_RE.match(t)]
    if len(body) < 2:
        return None
    master = body[-1]
    nets = body[:-1]
    return (toks[0], master, nets)


def _esd_clamp_netlist_connectivity(netlist_file: Path) -> Dict[str, Any]:
    """OPTIONAL: from an extracted SPICE / Verilog netlist, confirm each ESD clamp
    subckt instance ties to BOTH a power AND a ground net. chip-AGNOSTIC: the clamp
    is identified by the shipped IO-cell classifier on the subckt/master name, and
    rails by the shipped _net_pg_class.

    This is the netlist-domain twin of phase3's DEF-NETS _esd_discharge_topology C3.
    It is OPTIONAL because a routed DEF alone has the NETS terminals already (use the
    shipped check); this fires only when an EXTRACTED netlist is supplied.

    status ∈ {NA (file missing/empty/no clamps), CLAMP_CONNECTIVITY_OK,
              CLAMP_CONNECTIVITY_GAP (a clamp not tied to both rails = dangling)}.

    HONESTY: OK proves connectivity (necessary-not-sufficient) — NOT clamp HBM/CDM
    device sizing. A GAP is conclusive (the discharge path is structurally broken)."""
    base: Dict[str, Any] = {"check": "esd_clamp_netlist_connectivity"}
    try:
        text = Path(netlist_file).read_text(errors="ignore")
    except OSError:
        return {**base, "status": "NA", "reason": "NETLIST_UNREADABLE",
                "note": "Extracted netlist could not be read — clamp connectivity not run."}
    # Join SPICE line continuations ("+ ..." prefix) before tokenising.
    text = re.sub(r"\n\s*\+\s*", " ", text)
    clamps: List[Tuple[str, str, List[str]]] = []   # (inst, subckt, net pins)
    for raw in text.splitlines():
        parsed = _split_spice_inst(raw.strip())
        if parsed is None:
            continue
        inst, master, nets = parsed
        if _p._classify_io_cell(master) == "esd_pad":
            clamps.append((inst, master, nets))
    base["n_clamps"] = len(clamps)
    if not clamps:
        return {**base, "status": "NA",
                "note": ("No ESD-clamp subckt instances recognised in the extracted "
                         "netlist (by the IO-cell classifier) — clamp connectivity N/A. "
                         "Use phase3 _esd_discharge_topology on the DEF NETS instead.")}
    gaps: List[str] = []
    for inst, subckt, pins in clamps:
        classes = {_p._net_pg_class(p) for p in pins}
        if not ("power" in classes and "ground" in classes):
            gaps.append(f"clamp '{inst}' ({subckt}) pins tie to rail classes "
                        f"{sorted(classes) or 'NONE'} — not both power AND ground "
                        "(dangling / broken discharge path).")
    if gaps:
        return {**base, "status": "CLAMP_CONNECTIVITY_GAP", "gaps": gaps,
                "note": (f"{len(gaps)} ESD clamp(s) not tied to both a power and a "
                         "ground net — CONCLUSIVE broken discharge topology (independent "
                         "of clamp device sizing). Fix before sign-off.")}
    return {**base, "status": "CLAMP_CONNECTIVITY_OK",
            "note": (f"all {len(clamps)} ESD clamp instance(s) tie to both a power and "
                     "a ground net. NECESSARY-BUT-NOT-SUFFICIENT — connectivity only; "
                     "does NOT prove clamp HBM/CDM device sizing (TLP / foundry ESD "
                     "models). Not a PASS.")}


# --------------------------------------------------------------------------- #
# top-level aggregator                                                         #
# --------------------------------------------------------------------------- #
# Conclusive-fail statuses across the geometry layer (used by callers to gate).
GAP_STATUSES = frozenset({
    "WELLTAP_SPACING_GAP", "CLAMP_CONNECTIVITY_GAP",
})

# The honest can't-do-open-source residual — emitted verbatim in every report so
# the geometry screen is never mistaken for device-physics sign-off.
FOUNDRY_DATA_RESIDUAL = (
    "This geometry layer screens GEOMETRY from the routed DEF only. It CANNOT prove, "
    "and no open-source tool can prove without foundry process data: (1) ESD clamp "
    "HBM/CDM device sizing (It2 / clamp W / trigger) — needs TLP measurement + foundry "
    "ESD device models; (2) latch-up holding voltage Vhold>Vdd and the parasitic-SCR "
    "npn*pnp beta product — needs foundry-calibrated well/substrate doping + SCR models; "
    "(3) guard-ring efficacy under substrate-current injection — needs the "
    "foundry-calibrated substrate RC network (open-source ngspice does not ship it). "
    "This is NOT commercial-tool lock-in; it is a real physical need for foundry-"
    "calibrated process models. Open-source can screen geometry and catch conclusive "
    "structural exposures; it cannot certify the device physics."
)


def run_geometry_layer(def_file: str,
                       netlist_file: Optional[str] = None,
                       screen_um: float = _DEFAULT_SCREEN_UM,
                       rated_tap_masters: Optional[Sequence[str]] = None,
                       tapless_pdk: bool = False
                       ) -> Dict[str, Any]:
    """Run the open-source PERC GEOMETRY layer on a routed DEF (and optional
    extracted netlist). Returns ONE aggregate report dict.

    This is the public API the phase3 runner should call (integration wired later).
    Returns keys: spacing, guardring, [clamp_netlist], any_conclusive_gap,
    foundry_data_residual."""
    dp = Path(def_file)
    spacing = _latchup_tap_spacing_check(dp, screen_um=screen_um,
                                         rated_tap_masters=rated_tap_masters,
                                         tapless_pdk=tapless_pdk)
    guardring = _guardring_topology_check(dp)
    report: Dict[str, Any] = {
        "def": str(def_file),
        "layer": "perc_geometry_open_source",
        "spacing": spacing,
        "guardring": guardring,
        "foundry_data_residual": FOUNDRY_DATA_RESIDUAL,
    }
    if netlist_file:
        report["clamp_netlist"] = _esd_clamp_netlist_connectivity(Path(netlist_file))
    statuses = {spacing["status"], guardring["status"]}
    if "clamp_netlist" in report:
        statuses.add(report["clamp_netlist"]["status"])
    report["any_conclusive_gap"] = bool(statuses & GAP_STATUSES)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("def_file", help="routed DEF file")
    ap.add_argument("--netlist", default=None,
                    help="optional extracted netlist for ESD clamp connectivity")
    ap.add_argument("--max-um", type=float, default=_DEFAULT_SCREEN_UM,
                    help=f"conservative tap screening radius (um, default {_DEFAULT_SCREEN_UM})")
    args = ap.parse_args(argv)
    if not Path(args.def_file).is_file():
        print(json.dumps({"status": "INCOMPLETE", "reason": "DEF_NOT_FOUND",
                          "def": args.def_file}, indent=2))
        return 2
    report = run_geometry_layer(args.def_file, args.netlist, screen_um=args.max_um)
    print(json.dumps(report, indent=2))
    # exit non-zero ONLY on a conclusive structural gap (CI-friendly)
    return 1 if report["any_conclusive_gap"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
