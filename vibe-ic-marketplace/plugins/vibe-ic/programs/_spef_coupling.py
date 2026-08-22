#!/usr/bin/env python3
"""Analytical lateral-coupling parasitic augmentation for a grounded SPEF.

HONEST DISCLOSURE
-----------------
This does NOT use a foundry field-solver rules deck (Calibre-XRC ``rules.C`` /
StarRC ``.nxtgrd``) — that coupling + 3D-dielectric deliverable is a separate
foundry file, absent from PDK snapshots that ship only per-metal R + THICKNESS +
area-cap + fringe-cap (LEF/.tf).  It computes the LATERAL (same-layer,
side-to-side) coupling capacitance ANALYTICALLY from REAL routed geometry:

    * wire spacing  S  : measured edge-to-edge from the routed DEF
    * metal thickness T: read from the tech LEF (THICKNESS)
    * overlap length L : measured parallel-run length from the routed DEF
    * dielectric  eps_r: a DISCLOSED generic-180nm SiO2 assumption (default 4.0)

    C_couple = eps_r * eps0 * (T * L) / S       (parallel-plate lateral)

eps0 = 8.854e-6 pF/um.  The result is a coupling-aware SPEF that is strictly
BETTER than grounded-cap-only, but is "analytical, generic-dielectric, NOT
foundry-calibrated" — it is NOT a substitute for a foundry field-solver run and
is NOT crosstalk-sign-off-grade.  Every emitted SPEF carries this disclosure as
a header banner.

Why a POST-PASS (not OpenRCX): OpenRCX's ``bench_wires`` / ``write_rules`` can
build a captable ONLY if an external field solver fills in the pattern
capacitances; ``extract_parasitics -lef_rc`` (the no-captable path) produces
GROUNDED caps only — it has no coupling model.  So coupling has to come from an
analytical model applied to the routed geometry, which is exactly this pass.

All extraction functions here are PURE (text in / data out) so they are
unit-testable and chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

# Vacuum permittivity in pF/um : 8.854e-12 F/m / 1e6 um/m * 1e12 pF/F = 8.854e-6
EPS0_PF_PER_UM = 8.854e-6
# Generic 180nm inter-metal dielectric (SiO2-like). DISCLOSED assumption, NOT
# foundry data.  Undoped SiO2 ~3.9-4.0; 180nm IMD stacks often 4.0-4.2.
DEFAULT_EPS_R = 4.0
# Default lateral coupling search window (um): pairs farther apart than this
# contribute negligibly (C ~ 1/S) and are ignored to bound the O(n^2) scan.
DEFAULT_WINDOW_UM = 2.0


# ── LEF: per-layer geometry / RC ──────────────────────────────────────────────
class LayerInfo:
    __slots__ = ("name", "width", "spacing", "thickness", "direction")

    def __init__(self, name: str, width: float, spacing: float,
                 thickness: float, direction: str):
        self.name = name
        self.width = width
        self.spacing = spacing
        self.thickness = thickness
        self.direction = direction

    def __repr__(self):
        return (f"LayerInfo({self.name}, W={self.width}, SP={self.spacing}, "
                f"T={self.thickness}, {self.direction})")


def parse_lef_layers(lef_text: str) -> Dict[str, LayerInfo]:
    """Return {layer_name: LayerInfo} for every TYPE ROUTING layer."""
    out: Dict[str, LayerInfo] = {}
    for m in re.finditer(r"\bLAYER\s+(\S+)\s(.*?)\bEND\s+\1\b", lef_text,
                         re.DOTALL):
        name, body = m.group(1), m.group(2)
        if not re.search(r"TYPE\s+ROUTING", body):
            continue

        def g(pat: str) -> Optional[str]:
            mm = re.search(pat, body)
            return mm.group(1) if mm else None

        w = g(r"\bWIDTH\s+([\d.]+)")
        sp = g(r"\bSPACING\s+([\d.]+)")
        th = g(r"\bTHICKNESS\s+([\d.]+)")
        dr = g(r"\bDIRECTION\s+(\w+)")
        if w is None or th is None:
            continue
        out[name] = LayerInfo(
            name=name,
            width=float(w),
            spacing=float(sp) if sp else float(w),
            thickness=float(th),
            direction=(dr or "").upper(),
        )
    return out


# ── DEF: routed wire segments as rectangles ───────────────────────────────────
class Segment:
    __slots__ = ("net", "layer", "xlo", "ylo", "xhi", "yhi", "horizontal")

    def __init__(self, net, layer, xlo, ylo, xhi, yhi, horizontal):
        self.net = net
        self.layer = layer
        self.xlo = xlo
        self.ylo = ylo
        self.xhi = xhi
        self.yhi = yhi
        self.horizontal = horizontal


def parse_def_units(def_text: str) -> int:
    m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    return int(m.group(1)) if m else 1000


def _iter_net_bodies(def_text: str):
    """Yield (net_name, body_text) for each regular NET in the NETS section."""
    ns = def_text.find("\nNETS ")
    if ns < 0:
        return
    ne = def_text.find("\nEND NETS", ns)
    section = def_text[ns:ne if ne > 0 else len(def_text)]
    # Each net starts with "    - <name> ..." and ends at " ;"
    for m in re.finditer(r"^\s*-\s+(\S+)\s(.*?);\s*$", section,
                         re.DOTALL | re.MULTILINE):
        yield m.group(1), m.group(2)


def parse_def_wires(def_text: str, layers: Dict[str, LayerInfo],
                    units: Optional[int] = None) -> List[Segment]:
    """Extract routed wire segments as width-inflated rectangles (in DBU).

    Handles the DEF continuation syntax ``( x * )`` / ``( * y )`` (reuse the
    previous point's coordinate).  Only real metal runs (two explicit points on
    the same routing layer) become segments; via / RECT-only entries are
    skipped."""
    if units is None:
        units = parse_def_units(def_text)
    segs: List[Segment] = []
    point_re = re.compile(r"\(\s*([\d\-]+|\*)\s+([\d\-]+|\*)\s*\)")
    for net, body in _iter_net_bodies(def_text):
        # A route path is: <ROUTED|NEW> <LAYER> ( x y ) ( x y ) ...
        chunks = re.split(r"\b(?:ROUTED|NEW)\b", body)
        for ch in chunks:
            lm = re.search(r"\b(MET\d+|metal\d+|M\d+)\b", ch)
            if not lm:
                continue
            layer = lm.group(1)
            if layer not in layers:
                continue
            # Only the geometry before a VIA / RECT keyword is a wire run.
            seg_text = re.split(r"\bVIA\w*|\bRECT\b", ch)[0]
            pts: List[Tuple[Optional[int], Optional[int]]] = []
            prev: Tuple[Optional[int], Optional[int]] = (None, None)
            for pm in point_re.finditer(seg_text):
                sx, sy = pm.group(1), pm.group(2)
                x = prev[0] if sx == "*" else int(sx)
                y = prev[1] if sy == "*" else int(sy)
                pts.append((x, y))
                prev = (x, y)
            w_dbu = layers[layer].width * units
            half = w_dbu / 2.0
            for i in range(len(pts) - 1):
                (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                if x1 is None or y1 is None or x2 is None or y2 is None:
                    continue
                if x1 == x2 and y1 == y2:
                    continue
                if y1 == y2:  # horizontal run
                    xlo, xhi = sorted((x1, x2))
                    segs.append(Segment(net, layer, xlo, y1 - half,
                                        xhi, y1 + half, True))
                elif x1 == x2:  # vertical run
                    ylo, yhi = sorted((y1, y2))
                    segs.append(Segment(net, layer, x1 - half, ylo,
                                        x1 + half, yhi, False))
    return segs


# ── analytical coupling formula (PURE) ────────────────────────────────────────
def coupling_cap_pf(thickness_um: float, overlap_um: float, spacing_um: float,
                    eps_r: float = DEFAULT_EPS_R) -> float:
    """Parallel-plate lateral coupling cap (pF).  DISCLOSED generic model.

    C = eps_r * eps0 * (T * L) / S.  Returns 0 for non-positive geometry."""
    if spacing_um <= 0 or overlap_um <= 0 or thickness_um <= 0:
        return 0.0
    return eps_r * EPS0_PF_PER_UM * (thickness_um * overlap_um) / spacing_um


# ── adjacency finder (PURE) ───────────────────────────────────────────────────
def find_adjacent_pairs(segments: List[Segment], layers: Dict[str, LayerInfo],
                        units: int, window_um: float = DEFAULT_WINDOW_UM,
                        eps_r: float = DEFAULT_EPS_R
                        ) -> Dict[Tuple[str, str], float]:
    """Return {(netA,netB): coupling_pF} accumulated over every laterally
    adjacent same-layer parallel segment pair from DIFFERENT nets whose
    edge-to-edge spacing is within ``window_um``.  Keys are in canonical
    netA<netB order.

    Two parallel segments couple if (a) same layer, (b) same orientation,
    (c) their along-wire spans overlap (overlap length L>0), (d) their
    perpendicular edge-to-edge gap S is in (0, window_um].  Segments are sorted
    by their perpendicular coordinate so the inner loop can break early."""
    window_dbu = window_um * units
    out: Dict[Tuple[str, str], float] = {}
    buckets: Dict[Tuple[str, bool], List[Segment]] = {}
    for s in segments:
        buckets.setdefault((s.layer, s.horizontal), []).append(s)
    for (layer, horiz), segs in buckets.items():
        T = layers[layer].thickness
        segs.sort(key=(lambda s: s.ylo) if horiz else (lambda s: s.xlo))
        n = len(segs)
        for i in range(n):
            a = segs[i]
            for j in range(i + 1, n):
                b = segs[j]
                if a.net == b.net:
                    continue
                if horiz:
                    gap_dbu = max(b.ylo - a.yhi, a.ylo - b.yhi)
                    if gap_dbu <= 0:
                        # overlap/touch in y (via stack, same-net heal) — not a
                        # lateral pair; only break once b is fully past window.
                        if b.ylo - a.yhi > window_dbu:
                            break
                        continue
                    if gap_dbu > window_dbu:
                        break  # sorted by ylo → all further j also out of window
                    ov = min(a.xhi, b.xhi) - max(a.xlo, b.xlo)
                else:
                    gap_dbu = max(b.xlo - a.xhi, a.xlo - b.xhi)
                    if gap_dbu <= 0:
                        if b.xlo - a.xhi > window_dbu:
                            break
                        continue
                    if gap_dbu > window_dbu:
                        break
                    ov = min(a.yhi, b.yhi) - max(a.ylo, b.ylo)
                if ov <= 0:
                    continue
                c = coupling_cap_pf(T, ov / units, gap_dbu / units, eps_r)
                if c <= 0:
                    continue
                key = (a.net, b.net) if a.net < b.net else (b.net, a.net)
                out[key] = out.get(key, 0.0) + c
    return out


# ── SPEF injection ────────────────────────────────────────────────────────────
def parse_spef_name_map(spef_text: str) -> Dict[str, str]:
    """Return {net_name: '*id'} from the SPEF *NAME_MAP section."""
    out: Dict[str, str] = {}
    m = re.search(r"\*NAME_MAP(.*?)(?:\n\*[A-Z]|\Z)", spef_text, re.DOTALL)
    body = m.group(1) if m else spef_text
    for mm in re.finditer(r"^\s*(\*\d+)\s+(\S+)\s*$", body, re.MULTILINE):
        out[mm.group(2)] = mm.group(1)
    return out


def representative_nodes(spef_text: str) -> Dict[str, str]:
    """Map each net id (``*39``) to a representative NODE that already exists in
    its SPEF block — the first grounded *CAP node (an instance pin such as
    ``*875:D``).  A SPEF coupling cap must reference real nodes on each net, not
    the bare net id, or read_spef raises STA-1656 (pin not found)."""
    rep: Dict[str, str] = {}
    cur: Optional[str] = None
    in_cap = False
    for line in spef_text.splitlines():
        m = re.match(r"\*D_NET\s+(\*\d+)", line)
        if m:
            cur = m.group(1)
            in_cap = False
            continue
        if line.startswith("*CAP"):
            in_cap = True
            continue
        if line.startswith("*RES") or line.startswith("*END"):
            in_cap = False
            continue
        if in_cap and cur and cur not in rep:
            cm = re.match(r"\s*\d+\s+(\S+)\s+([\d.eE+-]+)\s*$", line)
            if cm:  # a 2-field (grounded) cap entry: id node value
                rep[cur] = cm.group(1)
    return rep


def disclosure_banner(eps_r: float = DEFAULT_EPS_R) -> str:
    """The mandatory in-SPEF honesty banner (// comment lines)."""
    return (
        '// COUPLING-AWARE AUGMENTATION (analytical, generic-180nm dielectric)\n'
        f'// eps_r={eps_r} (SiO2 generic assumption, NOT foundry-calibrated)\n'
        '// model: C_couple = eps_r*eps0*T*L/S  (parallel-plate lateral)\n'
        '// geometry: spacing/overlap from routed DEF, thickness from tech LEF\n'
        '// NOTE: NOT a foundry field-solver (no rules.C/.nxtgrd) extraction\n')


def inject_coupling_into_spef(spef_text: str,
                              coupling: Dict[Tuple[str, str], float],
                              eps_r: float = DEFAULT_EPS_R,
                              min_cc_pf: float = 1e-7) -> Tuple[str, int]:
    """Insert coupling caps into a grounded SPEF's *D_NET / *CAP blocks.

    For each net-pair (A,B) the coupling cap is written ONCE, in the *D_NET
    block of A, as a 3-field *CAP entry ``<id> <nodeA> <nodeB> <value>`` where
    nodeA/nodeB are REAL nodes harvested from each net's own block (IEEE-1481
    coupling cap).  Cap ids continue after the block's existing grounded ids and
    the *D_NET header total for A is increased by the added coupling.  Grounded
    caps are left intact (coupling is ADDED, disclosed as analytical).

    Returns (new_spef_text, n_coupling_caps_written).  Only net-pairs whose
    coupling >= ``min_cc_pf`` and whose BOTH nets have a representative node are
    written.  A disclosure banner is inserted after the *VERSION line."""
    name2id = parse_spef_name_map(spef_text)
    rep = representative_nodes(spef_text)

    # owner-net-id -> list of (nodeA, nodeB, value_pF)
    by_owner: Dict[str, List[Tuple[str, str, float]]] = {}
    for (na, nb), val in coupling.items():
        if val < min_cc_pf:
            continue
        ida, idb = name2id.get(na), name2id.get(nb)
        if not ida or not idb:
            continue
        node_a, node_b = rep.get(ida), rep.get(idb)
        if not node_a or not node_b:
            continue
        by_owner.setdefault(ida, []).append((node_a, node_b, val))

    banner = disclosure_banner(eps_r)
    lines = spef_text.splitlines(keepends=True)
    out_lines: List[str] = []
    written = 0
    i = 0
    n = len(lines)
    inserted_banner = False
    while i < n:
        line = lines[i]
        if not inserted_banner and line.startswith("*VERSION"):
            out_lines.append(line)
            out_lines.append(banner)
            inserted_banner = True
            i += 1
            continue
        m = re.match(r"\*D_NET\s+(\*\d+)\s+([\d.eE+-]+)", line)
        if not m:
            out_lines.append(line)
            i += 1
            continue
        owner = m.group(1)
        extra = by_owner.get(owner)
        if not extra:
            out_lines.append(line)
            i += 1
            continue
        # rewrite header total (grounded + added coupling)
        total = float(m.group(2))
        cc_sum = sum(v for _, _, v in extra)
        out_lines.append(f"*D_NET {owner} {total + cc_sum:.6g}\n")
        i += 1
        # gather this net's block up to *END; track the *CAP max id
        block: List[str] = []
        max_cap_id = 0
        in_cap = False
        while i < n and not lines[i].startswith("*END"):
            bl = lines[i]
            if bl.startswith("*CAP"):
                in_cap = True
            elif bl.startswith("*RES"):
                in_cap = False
            elif in_cap:
                cm = re.match(r"\s*(\d+)\s+", bl)
                if cm:
                    max_cap_id = max(max_cap_id, int(cm.group(1)))
            block.append(bl)
            i += 1
        # coupling entries as a text block, ids continuing after the grounded ids
        cc_lines: List[str] = []
        cid = max_cap_id
        for na, nb, v in extra:
            cid += 1
            cc_lines.append(f"{cid} {na} {nb} {v:.6g}\n")
        # rebuild: insert the coupling entries just before *RES (inside *CAP);
        # if the net has no *RES section, append at the end of the *CAP block.
        cap_seen = False
        inserted_cc = False
        for bl in block:
            if bl.startswith("*RES") and cap_seen and not inserted_cc:
                out_lines.extend(cc_lines)
                written += len(cc_lines)
                inserted_cc = True
            if bl.startswith("*CAP"):
                cap_seen = True
            out_lines.append(bl)
        if cap_seen and not inserted_cc:
            out_lines.extend(cc_lines)
            written += len(cc_lines)
        if i < n:  # the *END line
            out_lines.append(lines[i])
            i += 1
    return "".join(out_lines), written


# ── end-to-end drivers ────────────────────────────────────────────────────────
def build_coupling(def_text: str, lef_text: str, spef_text: str,
                   window_um: float = DEFAULT_WINDOW_UM,
                   eps_r: float = DEFAULT_EPS_R) -> Dict:
    """Pure text-in / data-out driver.  Returns a dict with the augmented SPEF
    text, the per-net-pair coupling, and stats."""
    layers = parse_lef_layers(lef_text)
    units = parse_def_units(def_text)
    segs = parse_def_wires(def_text, layers, units)
    pairs = find_adjacent_pairs(segs, layers, units, window_um, eps_r)
    new_spef, n = inject_coupling_into_spef(spef_text, pairs, eps_r)
    fF = sorted(v * 1000.0 for v in pairs.values())
    stats = {
        "n_layers": len(layers), "units": units, "n_segments": len(segs),
        "n_net_pairs": len(pairs), "n_cc_written": n,
        "total_coupling_fF": round(sum(fF), 4),
        "min_fF": round(fF[0], 6) if fF else 0.0,
        "max_fF": round(fF[-1], 6) if fF else 0.0,
        "median_fF": round(fF[len(fF) // 2], 6) if fF else 0.0,
        "eps_r": eps_r, "window_um": window_um,
    }
    return {"layers": layers, "coupling": pairs, "new_spef": new_spef,
            "n_cc_written": n, "stats": stats}


def augment_spef_file(def_path: str, lef_path: str, spef_path: str,
                      out_path: Optional[str] = None,
                      window_um: float = DEFAULT_WINDOW_UM,
                      eps_r: float = DEFAULT_EPS_R) -> Dict:
    """Read the grounded SPEF + routed DEF + tech LEF from disk, compute the
    analytical coupling, and write the coupling-aware SPEF.

    ``out_path`` defaults to overwriting ``spef_path`` in place (the grounded
    caps are preserved; coupling is added).  Returns build_coupling()'s dict
    plus ``out_path``.  On zero coupling (e.g. an unrouted DEF) the SPEF is
    left byte-identical except for the disclosure banner and 0 is reported —
    the caller keeps the honest grounded-cap fallback."""
    with open(def_path) as f:
        def_text = f.read()
    with open(lef_path) as f:
        lef_text = f.read()
    with open(spef_path) as f:
        spef_text = f.read()
    res = build_coupling(def_text, lef_text, spef_text, window_um, eps_r)
    dst = out_path or spef_path
    with atomic_writing(dst) as f:
        f.write(res["new_spef"])
    res["out_path"] = dst
    return res


def summarize(stats: Dict) -> str:
    """One-line human note for the runner's notes[]/log."""
    return ("coupling-aware SPEF (analytical, generic-180nm dielectric "
            f"eps_r={stats['eps_r']}, NOT foundry-calibrated): "
            f"{stats['n_cc_written']} coupling caps over {stats['n_net_pairs']} "
            f"net-pairs, {stats['min_fF']:.4f}-{stats['max_fF']:.4f} fF "
            f"(total {stats['total_coupling_fF']:.2f} fF); "
            f"window={stats['window_um']}um, {stats['n_segments']} wire segments")


# ── CLI ───────────────────────────────────────────────────────────────────────
def _main(argv: List[str]) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(
        description="Augment a grounded SPEF with analytical lateral coupling "
                    "caps (generic-180nm dielectric; NOT foundry-calibrated).")
    ap.add_argument("--def", dest="def_path", required=True)
    ap.add_argument("--lef", dest="lef_path", required=True)
    ap.add_argument("--spef", dest="spef_path", required=True)
    ap.add_argument("--out", dest="out_path", default=None,
                    help="output SPEF (default: overwrite --spef in place)")
    ap.add_argument("--eps-r", type=float, default=DEFAULT_EPS_R)
    ap.add_argument("--window-um", type=float, default=DEFAULT_WINDOW_UM)
    a = ap.parse_args(argv)
    res = augment_spef_file(a.def_path, a.lef_path, a.spef_path, a.out_path,
                            a.window_um, a.eps_r)
    print(json.dumps(res["stats"], indent=2))
    print(summarize(res["stats"]))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
