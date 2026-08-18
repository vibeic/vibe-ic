#!/usr/bin/env python3
"""Real 3D field-solved coupling extraction via FasterCap on the routed geometry.

WHY (the gap this closes vs the analytical pass)
------------------------------------------------
``_spef_coupling`` adds LATERAL coupling caps ANALYTICALLY with a parallel-plate
formula ``C = eps_r*eps0*T*L/S``.  That model MISSES the 3D fringe field and the
INTER-LAYER crossover coupling that a real field solver captures — and that a
foundry field-solver (Calibre-xRC / StarRC / QRC, driven by ``rules.C`` /
``.nxtgrd``) would compute.  Those foundry decks are not in the PDK snapshot.

This pass closes most of that gap WITHOUT the foundry deck by:
  1. INVERTING the PDK's own per-layer area+fringe caps into a fitted dielectric
     stack (``pdk_dielectric_fit`` — grounded per-layer heights + physical eps_r);
  2. building real 3D conductor geometry (width-inflated wire boxes at the fitted
     per-layer z-heights) for a bounded net cluster from the routed DEF;
  3. running the OSS BEM field solver **FasterCap** (github.com/ediloren/FasterCap,
     LGPL) on that geometry to get the true multi-conductor Maxwell capacitance
     matrix — LATERAL **and** inter-layer CROSSOVER coupling;
  4. injecting the field-solved coupling into the SPEF (reusing
     ``_spef_coupling.inject_coupling_into_spef`` so the SPEF format matches).

HONEST behaviour
----------------
  * If the FasterCap binary is ABSENT, or its output is empty/corrupt, this
    reports ``status="NOT_APPLICABLE"`` with the missing wiring step NAMED — it
    NEVER fabricates a capacitance matrix.  (The fitted dielectric stack is still
    returned, since that part is real.)
  * Only a bounded representative cluster is field-solved (a full-chip BEM solve
    is O(n^2) and infeasible) — DISCLOSED; the whole-chip field solve is the
    named remaining wiring step.
  * Uniform-dielectric per solve (the fitted eps_r), not the foundry's true
    multi-dielectric ILD — DISCLOSED.  Strictly better than analytical
    parallel-plate; NOT crosstalk-SI-signoff-grade; NOT silicon-proven.

Pure helpers (geometry build, matrix parse, coupling conversion, SPEF strip) are
unit-tested with NO container / filesystem side effects.  Chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

import _spef_coupling as SC
import pdk_dielectric_fit as PF
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

UM_TO_M = 1e-6
DEFAULT_CONTAINER = os.environ.get("VIBEIC_EDA_CONTAINER", "vibeic-eda")
DEFAULT_WINDOW_UM = 2.0
DEFAULT_MAX_AGGRESSORS = 6
DEFAULT_MAX_BOXES = 48
DEFAULT_REL_ERR = 0.05


# ── geometry build (PURE) ─────────────────────────────────────────────────────
def box_quads(cond: int, x0: float, y0: float, z0: float,
              x1: float, y1: float, z1: float) -> List[str]:
    """Return the 6 quadrilateral FastCap/FasterCap panels of an axis-aligned box
    (coordinates already in solver units — meters).  All panels carry conductor
    number ``cond``."""
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]

    def Q(a, b, d, e):
        return ("Q %d %.10g %.10g %.10g %.10g %.10g %.10g "
                "%.10g %.10g %.10g %.10g %.10g %.10g\n"
                % (cond, *a, *b, *d, *e))
    return [
        Q(c[0], c[1], c[2], c[3]),  # bottom (z0)
        Q(c[4], c[5], c[6], c[7]),  # top    (z1)
        Q(c[0], c[1], c[5], c[4]),  # y0 side
        Q(c[3], c[2], c[6], c[7]),  # y1 side
        Q(c[0], c[3], c[7], c[4]),  # x0 side
        Q(c[1], c[2], c[6], c[5]),  # x1 side
    ]


def stack_z_map(stack: Dict) -> Dict[str, Tuple[float, float]]:
    """{layer: (z_bottom_um, z_top_um)} from a pdk_dielectric_fit stack dict."""
    return {L["layer"]: (L["z_bottom_um"], L["z_top_um"])
            for L in stack.get("layers", [])}


def build_fastercap_geometry(cluster: Dict[str, List["SC.Segment"]],
                             z_map: Dict[str, Tuple[float, float]],
                             units: int, eps_r: float
                             ) -> Tuple[str, Dict[str, str], Dict[int, str]]:
    """Build FasterCap input for a net cluster.

    ``cluster`` maps net_name -> list of Segments (DBU rects, width-inflated).
    Returns (lst_text, {geo_filename: geo_text}, {cond#: net_name}).  Each net is
    ONE conductor with a unique cond# = its 1-based list index (so the solver row
    label ``g<k>_<k>`` maps back to the net).  Coordinates are converted DBU ->
    um -> meters so the solver returns Farads."""
    geo_files: Dict[str, str] = {}
    cond2net: Dict[int, str] = {}
    lst = ["* FasterCap coupling cluster (fitted dielectric eps_r=%.4g)\n" % eps_r]
    k = 0
    for net, segs in cluster.items():
        cond = k + 1                       # tentative conductor number
        panels: List[str] = []
        for s in segs:
            zb, zt = z_map.get(s.layer, (None, None))
            if zb is None:
                continue
            x0 = (s.xlo / units) * UM_TO_M
            x1 = (s.xhi / units) * UM_TO_M
            y0 = (s.ylo / units) * UM_TO_M
            y1 = (s.yhi / units) * UM_TO_M
            if x1 <= x0 or y1 <= y0:
                continue
            panels += box_quads(cond, x0, y0, zb * UM_TO_M, x1, y1, zt * UM_TO_M)
        if not panels:
            continue                       # net contributed nothing; skip cond#
        k = cond                           # commit the conductor number
        cond2net[k] = net
        fname = "n%d.geo" % k
        geo_files[fname] = ("* %s\n" % net) + "".join(panels)
        lst.append("C %s %.6g 0 0 0\n" % (fname, eps_r))
    return "".join(lst), geo_files, cond2net


# ── cluster selection (PURE) ──────────────────────────────────────────────────
def _seg_bbox(segs: List["SC.Segment"]) -> Tuple[int, int, int, int]:
    xlo = min(s.xlo for s in segs)
    ylo = min(s.ylo for s in segs)
    xhi = max(s.xhi for s in segs)
    yhi = max(s.yhi for s in segs)
    return xlo, ylo, xhi, yhi


def _bbox_gap_dbu(a: "SC.Segment", b: "SC.Segment") -> int:
    """Chebyshev-ish edge gap between two segment bboxes (0 if overlapping)."""
    dx = max(a.xlo - b.xhi, b.xlo - a.xhi, 0)
    dy = max(a.ylo - b.yhi, b.ylo - a.yhi, 0)
    return max(dx, dy)


def _near_any(s: "SC.Segment", others: List["SC.Segment"], win: int) -> bool:
    return any(_bbox_gap_dbu(s, o) <= win for o in others)


def _clip_cluster(segments: List["SC.Segment"], victim: str,
                  aggr_nets: List[str], units: int,
                  window_um: float = DEFAULT_WINDOW_UM,
                  max_boxes: int = DEFAULT_MAX_BOXES,
                  per_net_max: int = 12) -> Dict[str, List["SC.Segment"]]:
    """Build a bounded, box-budgeted geometry cluster around ``victim`` with the
    given ``aggr_nets``.  The victim is shrunk to the segments that actually
    couple to an aggressor; each aggressor is shrunk to the segments near the
    victim; each net is capped to ``per_net_max`` segments; and the weakest
    aggressor nets (last in ``aggr_nets``) are dropped until the total box count
    is within ``max_boxes``.  Returns {net: [Segments]} with >=2 nets, or {} if
    the victim has no segments / no aggressor survives.  PURE (no solver / I/O)."""
    if not aggr_nets:
        return {}
    want = set([victim] + list(aggr_nets))
    segs_by_net: Dict[str, List["SC.Segment"]] = {}
    for s in segments:
        if s.net in want:
            segs_by_net.setdefault(s.net, []).append(s)
    if victim not in segs_by_net:
        return {}

    win = int(window_um * units)
    aggr_segs = [s for n in aggr_nets for s in segs_by_net.get(n, [])]
    # shrink the victim to segments that actually couple to an aggressor
    vic = [s for s in segs_by_net[victim] if _near_any(s, aggr_segs, win)]
    if not vic:
        vic = segs_by_net[victim]
    vic = vic[:per_net_max]

    cluster: Dict[str, List["SC.Segment"]] = {victim: vic}
    for net in aggr_nets:                 # keep aggressor segs near the victim
        kept = [s for s in segs_by_net.get(net, []) if _near_any(s, vic, win)]
        if kept:
            cluster[net] = kept[:per_net_max]

    # bound total boxes: drop the weakest aggressor nets until under budget
    def total_boxes(c):
        return sum(len(v) for v in c.values())
    for net in reversed(list(aggr_nets)):  # weakest first
        if total_boxes(cluster) <= max_boxes or len(cluster) <= 2:
            break
        cluster.pop(net, None)

    return cluster if len(cluster) >= 2 else {}


def select_cluster(segments: List["SC.Segment"],
                   layers: Dict[str, "SC.LayerInfo"], units: int,
                   window_um: float = DEFAULT_WINDOW_UM,
                   max_aggressors: int = DEFAULT_MAX_AGGRESSORS,
                   max_boxes: int = DEFAULT_MAX_BOXES,
                   victim: Optional[str] = None,
                   per_net_max: int = 12
                   ) -> Tuple[Optional[str], Dict[str, List["SC.Segment"]],
                              Dict[Tuple[str, str], float]]:
    """Pick a bounded, representative coupling cluster around a victim net.

    Returns (victim, {net: clipped_segments}, analytical_pairs_in_cluster).  The
    victim is a net from the STRONGEST analytical lateral pair (so the field
    solve has a real lateral value to compare against) unless specified; its
    top-``max_aggressors`` analytical aggressors join it.  A huge victim net is
    shrunk to the segments that actually couple (near an aggressor or overlapping
    for crossover); each net is capped to ``per_net_max`` segments and the total
    to ``max_boxes``, so the BEM problem stays small/fast.  Empty victim or <1
    aggressor -> (victim, {}, {})."""
    pairs = SC.find_adjacent_pairs(segments, layers, units, window_um)
    if not pairs:
        return None, {}, {}
    if victim is None:
        # net from the single strongest analytical pair -> guarantees a lateral
        # field-vs-analytical comparison exists
        (na, nb), _ = max(pairs.items(), key=lambda kv: kv[1])
        victim = na
    # aggressors coupling to the victim, strongest first
    aggr: List[Tuple[str, float]] = []
    for (a, b), v in pairs.items():
        if a == victim:
            aggr.append((b, v))
        elif b == victim:
            aggr.append((a, v))
    aggr.sort(key=lambda t: -t[1])
    aggr_nets = [n for n, _ in aggr[:max_aggressors]]
    if not aggr_nets:
        return victim, {}, {}

    cluster = _clip_cluster(segments, victim, aggr_nets, units, window_um,
                            max_boxes, per_net_max)
    if len(cluster) < 2:
        return victim, {}, {}

    # analytical pairs restricted to the final cluster segments
    cl_segs = [s for segs in cluster.values() for s in segs]
    cl_pairs = SC.find_adjacent_pairs(cl_segs, layers, units, window_um)
    cl_pairs = {k: v for k, v in cl_pairs.items()
                if k[0] in cluster and k[1] in cluster}
    return victim, cluster, cl_pairs


# ── whole-design coverage plan (PURE) ─────────────────────────────────────────
def plan_coverage(pairs: Dict[Tuple[str, str], float],
                  max_aggressors: int = DEFAULT_MAX_AGGRESSORS
                  ) -> List[Tuple[str, List[str]]]:
    """Tile the WHOLE coupling graph into a deterministic sequence of bounded
    ``(victim, [aggressor_nets])`` cluster plans that COVER every analytical
    net-pair (each pair lies inside at least one plan's victim+aggressor set).

    This is the net-windowing that turns the single bounded-cluster solve into a
    whole-design sweep while keeping every individual BEM problem small (each
    plan has <= ``max_aggressors``+1 conductors, so the O(n^2) cost is bounded by
    the local neighbourhood, not the whole chip).

    Greedy set-cover: repeatedly seed on the strongest still-uncovered pair,
    centre on its endpoint with the most still-uncovered neighbours, and attach
    that victim's still-uncovered neighbours (strongest first — the seed's other
    endpoint guaranteed included) up to ``max_aggressors``; if space remains,
    top up with already-covered neighbours (real screening context). Every plan
    covers at least its seed pair, so the loop strictly shrinks the uncovered set
    and terminates. Deterministic (ties broken by coupling then net name).

    ``pairs`` keys are canonical (a<b); PURE, no geometry / solver."""
    if not pairs:
        return []
    nbr: Dict[str, List[Tuple[str, float]]] = {}
    for (a, b), cc in pairs.items():
        nbr.setdefault(a, []).append((b, cc))
        nbr.setdefault(b, []).append((a, cc))
    for n in nbr:
        nbr[n].sort(key=lambda t: (-t[1], t[0]))

    def canon(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a < b else (b, a)

    remaining = set(pairs)
    plans: List[Tuple[str, List[str]]] = []

    def rem_deg(n: str) -> int:
        return sum(1 for (o, _) in nbr.get(n, []) if canon(n, o) in remaining)

    while remaining:
        seed = max(remaining, key=lambda p: (pairs[p], p))
        a, b = seed
        # centre on the endpoint with the most still-uncovered neighbours
        victim, other = ((a, b) if (rem_deg(a), a) >= (rem_deg(b), b)
                         else (b, a))
        rem_aggr = [o for (o, _) in nbr[victim] if canon(victim, o) in remaining]
        cov_aggr = [o for (o, _) in nbr[victim]
                    if canon(victim, o) not in remaining]
        # seed's other endpoint first so the seed is always covered this plan
        ordered = [other] + [o for o in rem_aggr if o != other]
        aggr = ordered[:max_aggressors]
        if len(aggr) < max_aggressors:
            seen = set(aggr)
            for o in cov_aggr:
                if o not in seen:
                    aggr.append(o)
                    seen.add(o)
                if len(aggr) >= max_aggressors:
                    break
        plans.append((victim, aggr))
        clust = set([victim] + aggr)
        for p in [p for p in remaining if p[0] in clust and p[1] in clust]:
            remaining.discard(p)
    return plans


# ── capacitance-matrix parse (PURE) ───────────────────────────────────────────
_FLOAT = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"


def parse_capacitance_matrix(log_text: str
                             ) -> Optional[Tuple[List[str], List[List[float]]]]:
    """Parse the LAST 'Capacitance matrix is:' block from FasterCap console output.

    FasterCap with the -a auto option prints one matrix per refinement iteration;
    the last is the converged one.  Returns (row_labels, NxN float matrix) or
    None if no well-formed matrix is present (empty/corrupt output)."""
    if not log_text:
        return None
    idxs = [m.start() for m in re.finditer(r"Capacitance matrix is:", log_text)]
    if not idxs:
        return None
    block = log_text[idxs[-1]:]
    dm = re.search(r"Dimension\s+(\d+)\s*x\s*(\d+)", block)
    if not dm:
        return None
    n = int(dm.group(1))
    if n < 1 or n != int(dm.group(2)):
        return None
    rows_txt = block[dm.end():].splitlines()
    labels: List[str] = []
    mat: List[List[float]] = []
    row_re = re.compile(r"^\s*(\S+)\s+((?:" + _FLOAT + r"\s*){" + str(n) + r"})\s*$")
    for line in rows_txt:
        if not line.strip():
            if labels:
                break          # matrix ended
            continue
        m = row_re.match(line)
        if not m:
            if labels:
                break
            continue
        vals = re.findall(_FLOAT, m.group(2))
        if len(vals) != n:
            return None
        labels.append(m.group(1))
        mat.append([float(v) for v in vals])
        if len(mat) == n:
            break
    if len(mat) != n or any(len(r) != n for r in mat):
        return None
    return labels, mat


def _label_cond(label: str) -> Optional[int]:
    """FasterCap row label 'g<k>_<cond>' -> the leading conductor-file index k."""
    m = re.match(r"g(\d+)_", label)
    return int(m.group(1)) if m else None


def matrix_to_coupling(labels: List[str], matrix: List[List[float]],
                       cond2net: Dict[int, str]
                       ) -> Dict[Tuple[str, str], float]:
    """Convert a Maxwell capacitance matrix (Farads) to SPICE coupling caps (pF)
    keyed by net-pair.  Coupling cap = -0.5*(C_ij + C_ji) (symmetrized), skipping
    non-positive (numerical-noise) entries.  Off-diagonals only."""
    n = len(matrix)
    idx2net: Dict[int, str] = {}
    for i, lab in enumerate(labels):
        k = _label_cond(lab)
        if k is not None and k in cond2net:
            idx2net[i] = cond2net[k]
    out: Dict[Tuple[str, str], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            na, nb = idx2net.get(i), idx2net.get(j)
            if not na or not nb or na == nb:
                continue
            cc_f = -0.5 * (matrix[i][j] + matrix[j][i])   # Farads
            if cc_f <= 0:
                continue
            cc_pf = cc_f * 1e12
            key = (na, nb) if na < nb else (nb, na)
            out[key] = out.get(key, 0.0) + cc_pf
    return out


# ── SPEF grounded strip (PURE) — avoid double-counting analytical coupling ─────
def strip_coupling_caps(spef_text: str) -> str:
    """Return the SPEF with every 3-field (coupling) *CAP entry removed and each
    *D_NET header total reduced by the removed coupling, leaving a grounded-only
    SPEF.  2-field grounded caps are preserved.  Idempotent on an already-grounded
    SPEF."""
    lines = spef_text.splitlines(keepends=True)
    out: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r"\*D_NET\s+(\*\d+)\s+(" + _FLOAT + r")", line)
        if not m:
            out.append(line)
            i += 1
            continue
        owner, total = m.group(1), float(m.group(2))
        # gather the block, dropping 3-field coupling caps
        block: List[str] = []
        removed = 0.0
        in_cap = False
        i += 1
        while i < n and not lines[i].startswith("*END"):
            bl = lines[i]
            if bl.startswith("*CAP"):
                in_cap = True
                block.append(bl)
            elif bl.startswith("*RES") or bl.startswith("*D_NET"):
                in_cap = False
                block.append(bl)
            elif in_cap:
                # a 4-token *CAP entry "id nodeA nodeB value" is a coupling cap;
                # grounded caps have only 3 tokens "id node value" and cannot match
                cm = re.match(r"\s*\d+\s+\S+\s+\S+\s+(" + _FLOAT + r")\s*$", bl)
                if cm:
                    removed += float(cm.group(1))   # drop coupling entry
                else:
                    block.append(bl)                # keep grounded cap
            else:
                block.append(bl)
            i += 1
        out.append("*D_NET %s %.6g\n" % (owner, max(0.0, total - removed)))
        out.extend(block)
        if i < n:
            out.append(lines[i])   # *END
            i += 1
    return "".join(out)


# ── disclosure banner (field-solve) ───────────────────────────────────────────
def field_solve_banner(eps_r: float, n_pairs: int) -> str:
    return (
        '// FIELD-SOLVED COUPLING (FasterCap BEM, fitted PDK dielectric stack)\n'
        f'// eps_r={eps_r} (fitted from PDK area+fringe; NOT foundry rules.C)\n'
        '// engine: FasterCap 3D BEM on routed geometry; lateral + inter-layer\n'
        f'// scope: representative cluster ({n_pairs} field-solved net-pairs)\n'
        '// NOTE: NOT foundry field-solver; NOT crosstalk-SI-signoff-grade\n')


def whole_design_field_banner(eps_r: float, n_covered: int,
                              coverage_fraction: float,
                              n_fallback: int) -> str:
    pct = coverage_fraction * 100.0
    fb = (f'; {n_fallback} uncovered pair(s) kept at analytical value\n'
          if n_fallback else '\n')
    return (
        '// FIELD-SOLVED COUPLING — WHOLE-DESIGN (FasterCap BEM, fitted PDK stack)\n'
        f'// eps_r={eps_r} (fitted from PDK area+fringe; NOT foundry rules.C/.nxtgrd)\n'
        '// engine: FasterCap 3D BEM tiled per net-neighbourhood cluster; '
        'lateral + inter-layer crossover\n'
        f'// coverage: {n_covered} net-pairs field-solved '
        f'({pct:.1f}% of analytical pairs)' + fb +
        '// merge: each pair from its strongest-victim neighbourhood cluster '
        '(bounded screening => upper envelope vs fully-screened whole-chip)\n'
        '// NOTE: NOT foundry field-solver; NOT crosstalk-SI-signoff-grade; '
        'NOT silicon-proven\n')


def _default_out_path(spef_path: str) -> str:
    """Default location for a DERIVED coupling SPEF: a ``fastercap/`` SUBDIR
    beside the base extraction SPEF.

    A FasterCap coupling overlay carries FasterCap provenance, NOT the base
    RC-extraction tool's (magic/openroad).  If it is written as a sibling of the
    base SPEF it lands in the ``extracted/*.spef`` glob that the RC-extraction
    PROVENANCE gate scans, and that gate false-trips on the derived file (no
    magic/openroad log entry).  Writing it into a ``fastercap/`` subdirectory
    (a level the base glob does not match) keeps the derived overlay reproducible
    on disk WITHOUT polluting the base-extraction provenance check.  Chip/PDK-
    AGNOSTIC."""
    d = os.path.dirname(os.path.abspath(spef_path))
    stem = os.path.basename(spef_path).rsplit(".spef", 1)[0]
    return os.path.join(d, "fastercap", stem + ".fastercap.spef")


# ── container / solver execution ──────────────────────────────────────────────
def _fastercap_available(runner: str, container: str) -> Tuple[bool, str]:
    """Return (available, mode) where mode in {'native','docker'}."""
    if runner in ("auto", "native") and shutil.which("FasterCap"):
        return True, "native"
    if runner in ("auto", "docker"):
        try:
            r = subprocess.run(
                ["docker", "exec", container, "bash", "-lc",
                 "command -v FasterCap"],
                capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return True, "docker"
        except Exception:
            pass
    return False, runner


def _run_fastercap(workdir: str, lst_name: str, mode: str, container: str,
                   rel_err: float, galerkin: bool, timeout: int) -> Optional[str]:
    g = "-g " if galerkin else ""
    inner = "cd '%s' && FasterCap -b %s %s-a%g 2>&1" % (
        workdir, lst_name, g, rel_err)
    try:
        if mode == "native":
            r = subprocess.run(["bash", "-lc", inner],
                               capture_output=True, text=True, timeout=timeout)
        else:
            r = subprocess.run(["docker", "exec", container, "bash", "-lc", inner],
                               capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return None


# ── end-to-end driver ─────────────────────────────────────────────────────────
def extract(def_path: str, lef_path: str, spef_path: str,
            out_path: Optional[str] = None, eps_r: float = PF.DEFAULT_EPS_R_PHYS,
            window_um: float = DEFAULT_WINDOW_UM,
            max_aggressors: int = DEFAULT_MAX_AGGRESSORS,
            max_boxes: int = DEFAULT_MAX_BOXES, victim: Optional[str] = None,
            per_net_max: int = 12,
            rel_err: float = DEFAULT_REL_ERR, galerkin: bool = True,
            runner: str = "auto", container: str = DEFAULT_CONTAINER,
            workdir: Optional[str] = None, do_inject: bool = True,
            keep_work: bool = False, timeout: int = 600) -> Dict:
    """Fit the stack, build a cluster, field-solve with FasterCap, compare vs the
    analytical parallel-plate value, and (optionally) inject into the SPEF.

    Returns a dict with status ``PASS`` or ``NOT_APPLICABLE`` (with the wiring gap
    named).  NEVER fabricates a matrix when the solver is absent/failed."""
    with open(def_path) as f:
        def_text = f.read()
    with open(lef_path) as f:
        lef_text = f.read()
    with open(spef_path) as f:
        spef_text = f.read()

    stack = PF.fit_stack(lef_text, eps_r)
    z_map = stack_z_map(stack)
    layers = SC.parse_lef_layers(lef_text)
    units = SC.parse_def_units(def_text)
    segs = SC.parse_def_wires(def_text, layers, units)

    result: Dict = {
        "tool": "fastercap_extract",
        "def_path": def_path, "lef_path": lef_path, "spef_path": spef_path,
        "eps_r": eps_r, "n_segments": len(segs),
        "dielectric_stack": stack,
        "disclosure": [
            "Field-solved coupling on a fitted PDK dielectric stack (DISCLOSED, "
            "not foundry rules.C/.nxtgrd).",
            "Only a bounded representative cluster is field-solved (full-chip BEM "
            "is O(n^2)); whole-chip field solve is the named remaining wiring step.",
            "Uniform dielectric per solve (fitted eps_r); NOT the true multi-layer "
            "ILD profile.",
            "Strictly better than analytical parallel-plate (adds 3D fringe + "
            "inter-layer crossover); NOT crosstalk-SI-signoff-grade; NOT "
            "silicon-proven.",
        ],
    }

    if not segs:
        result.update(status="NOT_APPLICABLE",
                      reason="unrouted DEF (no wire segments to field-solve)")
        return result

    victim, cluster, cl_pairs = select_cluster(
        segs, layers, units, window_um, max_aggressors, max_boxes, victim,
        per_net_max)
    if len(cluster) < 2:
        result.update(status="NOT_APPLICABLE", victim=victim,
                      reason="no bounded coupling cluster (need >=2 coupled nets)")
        return result
    result["victim"] = victim
    result["cluster_nets"] = list(cluster)
    result["cluster_boxes"] = sum(len(v) for v in cluster.values())

    avail, mode = _fastercap_available(runner, container)
    if not avail:
        result.update(
            status="NOT_APPLICABLE", solver_available=False,
            reason="FasterCap binary not found (runner=%s, container=%s) — "
                   "WIRING GAP: build/install FasterCap (LGPL, "
                   "github.com/ediloren/FasterCap) or point --container at the "
                   "vibeic-eda image; the fitted dielectric stack above is real "
                   "and usable." % (runner, container))
        return result
    result["solver_mode"] = mode

    lst_text, geo_files, cond2net = build_fastercap_geometry(
        cluster, z_map, units, eps_r)
    if len(cond2net) < 2:
        result.update(status="NOT_APPLICABLE",
                      reason="cluster geometry degenerate (<2 conductors built)")
        return result

    wd = workdir or os.path.join(os.path.dirname(os.path.abspath(spef_path)),
                                 ".fastercap_work")
    os.makedirs(wd, exist_ok=True)
    try:
        for fn, txt in geo_files.items():
            with open(os.path.join(wd, fn), "w") as f:
                f.write(txt)
        with open(os.path.join(wd, "wires.lst"), "w") as f:
            f.write(lst_text)

        log = _run_fastercap(wd, "wires.lst", mode, container, rel_err,
                             galerkin, timeout)
        parsed = parse_capacitance_matrix(log or "")
        if parsed is None:
            result.update(
                status="NOT_APPLICABLE", solver_available=True,
                reason="FasterCap produced no well-formed capacitance matrix "
                       "(empty/corrupt output) — NOT fabricating a matrix. "
                       "WIRING GAP: inspect solver log.",
                solver_log_tail=(log or "")[-800:])
            return result

        labels, matrix = parsed
        field_cc = matrix_to_coupling(labels, matrix, cond2net)
        if not field_cc:
            result.update(status="NOT_APPLICABLE", solver_available=True,
                          reason="field solve yielded no positive coupling entries")
            return result
    finally:
        if not keep_work:
            shutil.rmtree(wd, ignore_errors=True)

    # analytical parallel-plate for the SAME pairs (fresh, from geometry)
    comparison = []
    ratios = []
    for (a, b), cc_field in sorted(field_cc.items(), key=lambda kv: -kv[1]):
        cc_anal = cl_pairs.get((a, b), 0.0)
        row = {"net_a": a, "net_b": b,
               "cc_field_ff": round(cc_field * 1000.0, 6),
               "cc_analytical_ff": round(cc_anal * 1000.0, 6),
               "field_over_analytical": (round(cc_field / cc_anal, 4)
                                         if cc_anal > 0 else None),
               "crossover_only": cc_anal == 0.0}
        comparison.append(row)
        if cc_anal > 0:
            ratios.append(cc_field / cc_anal)
    ratios.sort()
    result["field_solved_pairs"] = len(field_cc)
    result["total_field_cc_ff"] = round(sum(field_cc.values()) * 1000.0, 6)
    result["total_analytical_cc_ff"] = round(sum(cl_pairs.values()) * 1000.0, 6)
    result["crossover_pairs"] = sum(1 for r in comparison if r["crossover_only"])
    result["field_over_analytical_median"] = (round(ratios[len(ratios) // 2], 4)
                                              if ratios else None)
    result["comparison"] = comparison

    if do_inject:
        grounded = strip_coupling_caps(spef_text)
        # drop any pre-existing analytical banner so we don't end up with two
        grounded = grounded.replace(SC.disclosure_banner(eps_r), "")
        new_spef, n = SC.inject_coupling_into_spef(grounded, field_cc, eps_r)
        # relabel the analytical banner _spef_coupling inserts -> field-solve banner
        new_spef = new_spef.replace(SC.disclosure_banner(eps_r),
                                    field_solve_banner(eps_r, len(field_cc)))
        dst = out_path or _default_out_path(spef_path)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        with atomic_writing(dst) as f:
            f.write(new_spef)
        result["out_path"] = dst
        result["cc_written"] = n

    result["status"] = "PASS"
    return result


def summarize(res: Dict) -> str:
    if res.get("status") != "PASS":
        return "fastercap_extract: %s — %s" % (res.get("status"), res.get("reason"))
    if res.get("mode") == "whole_design":
        return summarize_whole_design(res)
    return ("field-solved coupling (FasterCap, fitted PDK stack): victim=%s, "
            "%d net-pairs (%d crossover), total %.3f fF (analytical %.3f fF), "
            "field/analytical median=%s" % (
                res.get("victim"), res.get("field_solved_pairs"),
                res.get("crossover_pairs"), res.get("total_field_cc_ff", 0.0),
                res.get("total_analytical_cc_ff", 0.0),
                res.get("field_over_analytical_median")))


# ── whole-design driver ───────────────────────────────────────────────────────
def _solve_cluster(cluster: Dict[str, List["SC.Segment"]],
                   z_map: Dict[str, Tuple[float, float]], units: int,
                   eps_r: float, wd: str, mode: str, container: str,
                   rel_err: float, galerkin: bool, timeout: int
                   ) -> Tuple[Dict[int, str], Optional[Dict[Tuple[str, str],
                                                             float]]]:
    """Field-solve ONE geometry cluster with FasterCap.

    Returns ``(cond2net, coupling_or_None)``.  ``coupling`` is None ONLY when the
    solver produced no well-formed matrix (empty/corrupt) — NEVER a fabricated
    matrix.  ``cond2net`` is the built conductor->net map (its VALUES are the nets
    actually field-solved, so the caller can mark their pairs covered even when
    the solved coupling is ~0, i.e. screened)."""
    lst_text, geo_files, cond2net = build_fastercap_geometry(
        cluster, z_map, units, eps_r)
    if len(cond2net) < 2:
        return cond2net, None
    os.makedirs(wd, exist_ok=True)
    for fn, txt in geo_files.items():
        with open(os.path.join(wd, fn), "w") as f:
            f.write(txt)
    with open(os.path.join(wd, "wires.lst"), "w") as f:
        f.write(lst_text)
    log = _run_fastercap(wd, "wires.lst", mode, container, rel_err, galerkin,
                         timeout)
    parsed = parse_capacitance_matrix(log or "")
    if parsed is None:
        return cond2net, None
    labels, matrix = parsed
    return cond2net, matrix_to_coupling(labels, matrix, cond2net)


def extract_whole_design(
        def_path: str, lef_path: str, spef_path: str,
        out_path: Optional[str] = None, eps_r: float = PF.DEFAULT_EPS_R_PHYS,
        window_um: float = DEFAULT_WINDOW_UM,
        max_aggressors: int = 12, max_boxes: int = 200, per_net_max: int = 16,
        rel_err: float = DEFAULT_REL_ERR, galerkin: bool = True,
        runner: str = "auto", container: str = DEFAULT_CONTAINER,
        workdir: Optional[str] = None, do_inject: bool = True,
        keep_work: bool = False, timeout: int = 180, max_solves: int = 800,
        progress=None) -> Dict:
    """WHOLE-DESIGN field-solved coupling: tile the entire coupling graph into
    bounded per-net-neighbourhood clusters (``plan_coverage``), FasterCap-solve
    each, and merge the field-solved Cc for EVERY analytical net-pair (plus the
    inter-layer crossover pairs the analytical model misses) into the SPEF.

    This removes the single-bounded-cluster limitation of ``extract`` (which
    field-solved only ONE victim's neighbourhood): here the O(n^2) BEM cost is
    bounded per LOCAL neighbourhood while COVERAGE spans all coupled pairs, so
    the coupling SPEF — and any SI STA built on it — rests on field-solved rather
    than analytical parallel-plate coupling across the whole design.

    Honest as ``extract``: fitted PDK dielectric (NOT foundry rules.C/.nxtgrd),
    uniform-εr per solve, an UPPER envelope vs the fully-screened whole-chip
    solve (each pair taken from its strongest-victim neighbourhood).  NEVER
    fabricates a matrix; reports the exact ``coverage_fraction`` and keeps the
    analytical value for any pair the sweep could not field-solve.  Chip/PDK-
    AGNOSTIC."""
    with open(def_path) as f:
        def_text = f.read()
    with open(lef_path) as f:
        lef_text = f.read()
    with open(spef_path) as f:
        spef_text = f.read()

    stack = PF.fit_stack(lef_text, eps_r)
    z_map = stack_z_map(stack)
    layers = SC.parse_lef_layers(lef_text)
    units = SC.parse_def_units(def_text)
    segs = SC.parse_def_wires(def_text, layers, units)

    result: Dict = {
        "tool": "fastercap_extract", "mode": "whole_design",
        "def_path": def_path, "lef_path": lef_path, "spef_path": spef_path,
        "eps_r": eps_r, "n_segments": len(segs),
        "dielectric_stack": stack,
        "disclosure": [
            "WHOLE-DESIGN field-solved coupling: every analytical net-pair is "
            "field-solved in a bounded per-net-neighbourhood cluster (tiled "
            "coverage), not a single representative cluster.",
            "Field-solved on a fitted PDK dielectric stack (DISCLOSED, not "
            "foundry rules.C/.nxtgrd).",
            "Uniform dielectric per solve (fitted eps_r); NOT the true "
            "multi-layer ILD profile.",
            "Each pair is taken from its strongest-victim neighbourhood cluster "
            "(bounded screening) — an UPPER envelope vs the fully-screened "
            "whole-chip solve; strictly better than analytical parallel-plate "
            "(adds 3D fringe + inter-layer crossover); NOT "
            "crosstalk-SI-signoff-grade; NOT silicon-proven.",
        ],
    }

    if not segs:
        result.update(status="NOT_APPLICABLE",
                      reason="unrouted DEF (no wire segments to field-solve)")
        return result

    all_pairs = SC.find_adjacent_pairs(segs, layers, units, window_um, eps_r)
    if not all_pairs:
        result.update(status="NOT_APPLICABLE",
                      reason="no analytical coupling pairs (isolated routing)")
        return result
    result["n_analytical_pairs"] = len(all_pairs)
    result["total_analytical_cc_ff_all"] = round(sum(all_pairs.values()) * 1000.0,
                                                  6)

    avail, mode = _fastercap_available(runner, container)
    if not avail:
        result.update(
            status="NOT_APPLICABLE", solver_available=False,
            reason="FasterCap binary not found (runner=%s, container=%s) — "
                   "WIRING GAP: build/install FasterCap (LGPL) or point "
                   "--container at the vibeic-eda image; the fitted dielectric "
                   "stack above is real and usable." % (runner, container))
        return result
    result["solver_mode"] = mode

    plans = plan_coverage(all_pairs, max_aggressors)
    wdroot = workdir or os.path.join(os.path.dirname(os.path.abspath(spef_path)),
                                     ".fastercap_whole_work")

    field_cc: Dict[Tuple[str, str], float] = {}     # analytical pair -> field Cc
    crossover_cc: Dict[Tuple[str, str], float] = {}  # crossover pair -> field Cc
    solved_pairs: set = set()                        # analytical pairs solved
    solves = failed_solves = boxes_total = 0

    def _merge(cond2net: Dict[int, str],
               cc: Optional[Dict[Tuple[str, str], float]]) -> None:
        nonlocal failed_solves
        if cc is None:
            # SOLVER FAILURE (no well-formed matrix) — NOT a screened-to-zero
            # result. Do NOT mark these pairs solved: leaving them uncovered lets
            # the reconciliation retry them (and, failing that, keep their
            # analytical value) instead of silently DROPPING real coupling (which
            # would make the SI bound optimistic — a false-clean). Never fabricate.
            failed_solves += 1
            return
        cond_nets = set(cond2net.values())
        for p in all_pairs:                          # geometry genuinely solved
            if p[0] in cond_nets and p[1] in cond_nets:
                solved_pairs.add(p)                  # a pair absent from cc here
                #                                      is a real screen-to-~0
        for pr, val in cc.items():
            if pr in all_pairs:
                field_cc.setdefault(pr, val)         # first-wins (strongest vic)
            else:
                crossover_cc.setdefault(pr, val)

    try:
        for idx, (victim, aggr) in enumerate(plans):
            if solves >= max_solves:
                break
            cluster = _clip_cluster(segs, victim, aggr, units, window_um,
                                    max_boxes, per_net_max)
            if len(cluster) < 2:
                continue
            wd = os.path.join(wdroot, "s%d" % idx)
            cond2net, cc = _solve_cluster(cluster, z_map, units, eps_r, wd, mode,
                                          container, rel_err, galerkin, timeout)
            if not keep_work:
                shutil.rmtree(wd, ignore_errors=True)
            solves += 1
            boxes_total += sum(len(v) for v in cluster.values())
            _merge(cond2net, cc)
            if progress:
                progress(idx, len(plans), solves, len(solved_pairs),
                         len(all_pairs))

        # reconciliation: analytical pairs clipping dropped from every plan get a
        # minimal 2-net solve so coverage is honest (upper-bounded by max_solves).
        recon = 0
        for (a, b) in [p for p in all_pairs if p not in solved_pairs]:
            if solves >= max_solves:
                break
            cluster = _clip_cluster(segs, a, [b], units, window_um, max_boxes,
                                    per_net_max)
            if len(cluster) < 2:
                cluster = _clip_cluster(segs, b, [a], units, window_um,
                                        max_boxes, per_net_max)
            if len(cluster) < 2:
                continue                              # geometrically degenerate
            wd = os.path.join(wdroot, "r%d" % recon)
            cond2net, cc = _solve_cluster(cluster, z_map, units, eps_r, wd, mode,
                                          container, rel_err, galerkin, timeout)
            if not keep_work:
                shutil.rmtree(wd, ignore_errors=True)
            solves += 1
            recon += 1
            boxes_total += sum(len(v) for v in cluster.values())
            _merge(cond2net, cc)
        result["reconciliation_solves"] = recon
    finally:
        if not keep_work:
            shutil.rmtree(wdroot, ignore_errors=True)

    covered = solved_pairs
    uncovered = [p for p in all_pairs if p not in covered]
    total_field = sum(field_cc.get(p, 0.0) for p in covered)
    total_anal_covered = sum(all_pairs[p] for p in covered)
    ratios = sorted(field_cc[p] / all_pairs[p] for p in covered
                    if p in field_cc and all_pairs[p] > 0)

    result.update(
        planned_clusters=len(plans), solves=solves,
        failed_solves=failed_solves, cluster_boxes_total=boxes_total,
        pairs_field_solved=len(covered),
        coverage_fraction=round(len(covered) / len(all_pairs), 4),
        pairs_positive_field=len(field_cc),
        pairs_screened_to_zero=len(covered) - len(field_cc),
        crossover_pairs=len(crossover_cc),
        uncovered_pairs=len(uncovered),
        total_field_cc_ff=round(total_field * 1000.0, 6),
        total_analytical_cc_ff_covered=round(total_anal_covered * 1000.0, 6),
        total_crossover_cc_ff=round(sum(crossover_cc.values()) * 1000.0, 6),
        field_over_analytical_total=(round(total_field / total_anal_covered, 4)
                                     if total_anal_covered > 0 else None),
        field_over_analytical_median=(round(ratios[len(ratios) // 2], 4)
                                      if ratios else None),
    )

    if do_inject:
        grounded = strip_coupling_caps(spef_text)
        grounded = grounded.replace(SC.disclosure_banner(eps_r), "")
        inj: Dict[Tuple[str, str], float] = dict(field_cc)
        inj.update(crossover_cc)
        for p in uncovered:                          # honest analytical fallback
            inj.setdefault(p, all_pairs[p])
        new_spef, n = SC.inject_coupling_into_spef(grounded, inj, eps_r)
        new_spef = new_spef.replace(
            SC.disclosure_banner(eps_r),
            whole_design_field_banner(eps_r, len(covered),
                                      len(covered) / len(all_pairs),
                                      len(uncovered)))
        dst = out_path or _default_out_path(spef_path)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        with atomic_writing(dst) as f:
            f.write(new_spef)
        result["out_path"] = dst
        result["cc_written"] = n
        result["uncovered_fallback_analytical"] = len(uncovered)

    result["status"] = "PASS"
    return result


def summarize_whole_design(res: Dict) -> str:
    return ("WHOLE-DESIGN field-solved coupling (FasterCap, fitted PDK stack): "
            "%d/%d pairs (%.1f%% coverage, %d solves, %d crossover), total "
            "%.3f fF (analytical %.3f fF over covered) => field/analytical "
            "total=%s median=%s" % (
                res.get("pairs_field_solved", 0),
                res.get("n_analytical_pairs", 0),
                100.0 * res.get("coverage_fraction", 0.0),
                res.get("solves", 0), res.get("crossover_pairs", 0),
                res.get("total_field_cc_ff", 0.0),
                res.get("total_analytical_cc_ff_covered", 0.0),
                res.get("field_over_analytical_total"),
                res.get("field_over_analytical_median")))


# ── CLI ───────────────────────────────────────────────────────────────────────
def _main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Field-solved (FasterCap) coupling extraction on the routed "
                    "geometry with a fitted PDK dielectric stack. NONFATAL; "
                    "NOT_APPLICABLE (not fabricated) if the solver is absent.")
    ap.add_argument("--def", dest="def_path", required=True)
    ap.add_argument("--lef", dest="lef_path", required=True)
    ap.add_argument("--spef", dest="spef_path", required=True)
    ap.add_argument("--out", dest="out_path", default=None)
    ap.add_argument("--eps-r", type=float, default=PF.DEFAULT_EPS_R_PHYS)
    ap.add_argument("--window-um", type=float, default=DEFAULT_WINDOW_UM)
    ap.add_argument("--max-aggressors", type=int, default=DEFAULT_MAX_AGGRESSORS)
    ap.add_argument("--max-boxes", type=int, default=DEFAULT_MAX_BOXES)
    ap.add_argument("--per-net-max", type=int, default=12)
    ap.add_argument("--victim", default=None)
    ap.add_argument("--rel-err", type=float, default=DEFAULT_REL_ERR)
    ap.add_argument("--no-galerkin", action="store_true")
    ap.add_argument("--runner", choices=["auto", "native", "docker"],
                    default="auto")
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--no-inject", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--whole-design", action="store_true",
                    help="tile the WHOLE coupling graph (all net-pairs) into "
                         "bounded per-neighbourhood FasterCap solves instead of "
                         "a single representative cluster")
    ap.add_argument("--max-solves", type=int, default=800,
                    help="cap on tiled solves for --whole-design (coverage is "
                         "reported honestly if the cap is hit)")
    ap.add_argument("--progress", action="store_true",
                    help="print per-solve coverage progress to stderr "
                         "(--whole-design)")
    ap.add_argument("--stack-json", default=None,
                    help="also write the fitted dielectric_stack.json here")
    a = ap.parse_args(argv)
    if a.whole_design:
        import sys as _sys

        def _prog(idx, nplans, solves, ncov, npairs):
            _sys.stderr.write(
                "[fastercap whole-design] plan %d/%d  solves=%d  "
                "covered=%d/%d\n" % (idx + 1, nplans, solves, ncov, npairs))
            _sys.stderr.flush()

        res = extract_whole_design(
            a.def_path, a.lef_path, a.spef_path, out_path=a.out_path,
            eps_r=a.eps_r, window_um=a.window_um,
            max_aggressors=(a.max_aggressors if a.max_aggressors != DEFAULT_MAX_AGGRESSORS
                            else 12),
            max_boxes=a.max_boxes, per_net_max=a.per_net_max, rel_err=a.rel_err,
            galerkin=not a.no_galerkin, runner=a.runner, container=a.container,
            workdir=a.workdir, do_inject=not a.no_inject, keep_work=a.keep_work,
            timeout=(a.timeout if a.timeout != 600 else 180),
            max_solves=a.max_solves, progress=_prog if a.progress else None)
    else:
        res = extract(a.def_path, a.lef_path, a.spef_path, out_path=a.out_path,
                      eps_r=a.eps_r, window_um=a.window_um,
                      max_aggressors=a.max_aggressors, max_boxes=a.max_boxes,
                      victim=a.victim, per_net_max=a.per_net_max,
                      rel_err=a.rel_err, galerkin=not a.no_galerkin,
                      runner=a.runner, container=a.container, workdir=a.workdir,
                      do_inject=not a.no_inject, keep_work=a.keep_work,
                      timeout=a.timeout)
    if a.stack_json:
        with open(a.stack_json, "w") as f:
            json.dump(res["dielectric_stack"], f, indent=2)
    slim = {k: v for k, v in res.items()
            if k not in ("dielectric_stack", "comparison")}
    print(json.dumps(slim, indent=2))
    print(summarize(res))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
