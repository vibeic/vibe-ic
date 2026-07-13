#!/usr/bin/env python3
"""Unit tests for fastercap_extract — the pure (no-container) helpers.

Covers: box geometry emit, cluster selection from routed DEF, capacitance-matrix
parse (incl. taking the LAST/converged block), Maxwell->coupling conversion with
symmetrization, SPEF grounded-strip (double-count avoidance), and the
false-clean guards: an empty/corrupt solver output must yield None (never a
fabricated matrix), and a NOT_APPLICABLE status when the solver is absent.
"""
from __future__ import annotations

import math
import os

import _spef_coupling as SC
import fastercap_extract as FE


# ── derived-SPEF default location (must NOT pollute extracted/*.spef glob) ─────
def test_default_out_path_is_fastercap_subdir():
    p = FE._default_out_path("/proj/phase3/stage3/extracted/spm.spef")
    # a `fastercap/` subdir beside the base SPEF, not a sibling of it (a sibling
    # would land in the base extracted/*.spef provenance glob and false-trip it)
    assert os.path.dirname(p).endswith(os.path.join("extracted", "fastercap"))
    assert os.path.basename(p) == "spm.fastercap.spef"
    # NOT directly in the extracted/ dir
    assert os.path.basename(os.path.dirname(p)) == "fastercap"


# ── box geometry ──────────────────────────────────────────────────────────────
def test_box_quads_shape():
    q = FE.box_quads(3, 0, 0, 0, 1e-6, 2e-6, 0.5e-6)
    assert len(q) == 6                       # 6 faces
    assert all(line.startswith("Q 3 ") for line in q)
    # every panel has 12 coordinate numbers after 'Q <cond>'
    for line in q:
        toks = line.split()
        assert toks[0] == "Q" and toks[1] == "3"
        assert len(toks) == 2 + 12


def test_stack_z_map():
    stack = {"layers": [{"layer": "MET1", "z_bottom_um": 1.1, "z_top_um": 1.6},
                        {"layer": "MET2", "z_bottom_um": 2.5, "z_top_um": 3.0}]}
    z = FE.stack_z_map(stack)
    assert z["MET1"] == (1.1, 1.6) and z["MET2"] == (2.5, 3.0)


# ── geometry build: unique conductor per net, predictable labels ──────────────
def _seg(net, layer, xlo, ylo, xhi, yhi, horiz):
    return SC.Segment(net, layer, xlo, ylo, xhi, yhi, horiz)


def test_build_geometry_one_conductor_per_net():
    z_map = {"MET1": (1.0, 1.5), "MET2": (2.0, 2.5)}
    cluster = {
        "netA": [_seg("netA", "MET1", 0, 0, 1000, 200, True)],
        "netB": [_seg("netB", "MET1", 0, 400, 1000, 600, True),
                 _seg("netB", "MET2", 500, 0, 700, 1000, False)],
    }
    lst, geo, cond2net = FE.build_fastercap_geometry(cluster, z_map, 1000, 4.0)
    assert cond2net == {1: "netA", 2: "netB"}
    assert set(geo) == {"n1.geo", "n2.geo"}
    assert lst.count("C n") == 2
    # netB has two segments -> two boxes -> 12 panels, all cond 2
    assert geo["n2.geo"].count("Q 2 ") == 12
    assert geo["n1.geo"].count("Q 1 ") == 6


def test_build_geometry_skips_net_with_no_mapped_layer():
    z_map = {"MET1": (1.0, 1.5)}
    cluster = {
        "netA": [_seg("netA", "MET1", 0, 0, 1000, 200, True)],
        "netB": [_seg("netB", "MET9", 0, 400, 1000, 600, True)],  # layer not in map
    }
    lst, geo, cond2net = FE.build_fastercap_geometry(cluster, z_map, 1000, 4.0)
    assert cond2net == {1: "netA"}            # netB dropped, no cond# gap
    assert set(geo) == {"n1.geo"}


# ── cluster selection from a routed DEF ───────────────────────────────────────
_LEF = """
LAYER MET1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 0.20 ;
  SPACING 0.20 ;
  CAPACITANCE   CPERSQDIST 0.03058e-3 ;
  EDGECAPACITANCE   0.00817e-3 ;
  THICKNESS 0.53 ;
END MET1
LAYER MET2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  WIDTH 0.20 ;
  SPACING 0.20 ;
  CAPACITANCE   CPERSQDIST 0.01406e-3 ;
  EDGECAPACITANCE   0.00684e-3 ;
  THICKNESS 0.53 ;
END MET2
"""

_DEF = """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
NETS 3 ;
- na ( PIN a ) + ROUTED MET1 ( 0 0 ) ( 10000 0 ) ;
- nb ( PIN b ) + ROUTED MET1 ( 0 300 ) ( 10000 300 ) ;
- nc ( PIN c ) + ROUTED MET1 ( 0 600 ) ( 10000 600 ) ;
END NETS
END DESIGN
"""


def test_select_cluster_picks_victim_and_aggressors():
    layers = SC.parse_lef_layers(_LEF)
    units = SC.parse_def_units(_DEF)
    segs = SC.parse_def_wires(_DEF, layers, units)
    assert segs, "fixture must route some wire"
    victim, cluster, pairs = FE.select_cluster(segs, layers, units,
                                               window_um=2.0, max_aggressors=6)
    # victim is drawn from the strongest analytical pair
    assert victim in {"na", "nb", "nc"}
    assert len(cluster) >= 2
    assert all(k[0] in cluster and k[1] in cluster for k in pairs)
    # a real lateral pair (analytical>0) is present for the field-vs-analytical
    # comparison
    assert any(v > 0 for v in pairs.values())


def test_select_cluster_no_coupling_returns_empty():
    # single isolated net -> no pairs
    def1 = """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
NETS 1 ;
- na ( PIN a ) + ROUTED MET1 ( 0 0 ) ( 10000 0 ) ;
END NETS
END DESIGN
"""
    layers = SC.parse_lef_layers(_LEF)
    segs = SC.parse_def_wires(def1, layers, 1000)
    victim, cluster, pairs = FE.select_cluster(segs, layers, 1000)
    assert cluster == {} and pairs == {}


# ── capacitance-matrix parse ──────────────────────────────────────────────────
_LOG_TWO_ITERS = """
Computing links...
Capacitance matrix is:
Dimension 3 x 3
g1_1  1.0e-15 -2.0e-16 -3.0e-17
g2_2  -2.0e-16 1.1e-15 -4.0e-17
g3_3  -3.0e-17 -4.0e-17 5.0e-16
Weighted Frobenius norm ... 0.2

Refining...
Capacitance matrix is:
Dimension 3 x 3
g1_1  9.0e-16 -5.0e-16 -9.0e-17
g2_2  -5.1e-16 9.2e-16 -9.5e-17
g3_3  -9.1e-17 -9.4e-17 3.6e-16
Weighted Frobenius norm ... 0.004

Solve statistics:
"""


def test_parse_matrix_takes_last_block():
    labels, mat = FE.parse_capacitance_matrix(_LOG_TWO_ITERS)
    assert labels == ["g1_1", "g2_2", "g3_3"]
    assert len(mat) == 3 and all(len(r) == 3 for r in mat)
    # last (converged) block, not the first
    assert math.isclose(mat[0][0], 9.0e-16)
    assert math.isclose(mat[0][1], -5.0e-16)


def test_parse_matrix_empty_or_corrupt_returns_none():
    assert FE.parse_capacitance_matrix("") is None
    assert FE.parse_capacitance_matrix("no matrix here at all") is None
    # header present but rows missing -> None (never a fabricated matrix)
    bad = "Capacitance matrix is:\nDimension 2 x 2\n"
    assert FE.parse_capacitance_matrix(bad) is None
    # dimension mismatch row -> None
    bad2 = ("Capacitance matrix is:\nDimension 2 x 2\n"
            "g1_1 1.0e-15 -2.0e-16\n")   # only 1 data row for a 2x2
    assert FE.parse_capacitance_matrix(bad2) is None


# ── Maxwell matrix -> coupling ─────────────────────────────────────────────────
def test_matrix_to_coupling_symmetrized_pF():
    labels = ["g1_1", "g2_2", "g3_3"]
    # off-diagonals in F; coupling = -0.5*(Cij+Cji)
    mat = [[9.0e-16, -5.0e-16, -9.0e-17],
           [-5.1e-16, 9.2e-16, -9.5e-17],
           [-9.1e-17, -9.4e-17, 3.6e-16]]
    cond2net = {1: "na", 2: "nb", 3: "nc"}
    cc = FE.matrix_to_coupling(labels, mat, cond2net)
    # na-nb coupling = -0.5*(-5.0e-16 + -5.1e-16) = 5.05e-16 F = 5.05e-4 pF
    assert math.isclose(cc[("na", "nb")], 5.05e-16 * 1e12, rel_tol=1e-9)
    # na-nc crossover present too
    assert ("na", "nc") in cc and cc[("na", "nc")] > 0


def test_matrix_to_coupling_drops_nonpositive():
    labels = ["g1_1", "g2_2"]
    mat = [[1e-15, 2e-16], [2e-16, 1e-15]]   # POSITIVE off-diag -> not a coupling
    cc = FE.matrix_to_coupling(labels, mat, {1: "na", 2: "nb"})
    assert cc == {}


# ── SPEF grounded strip (double-count avoidance) ──────────────────────────────
_SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*VERSION "x"
*D_NET *1 0.005
*CONN
*I *1:A I
*CAP
1 *1:A 0.002
2 *1:A *2:A 0.001
3 *1:A 0.002
*END
*D_NET *2 0.003
*CONN
*I *2:A I
*CAP
1 *2:A 0.003
*END
"""


def test_strip_coupling_caps_removes_3field_and_fixes_total():
    g = FE.strip_coupling_caps(_SPEF)
    # coupling entry gone
    assert "*2:A" not in g.split("*D_NET *2")[0]  # no coupling ref in net1 block
    assert "0.001" not in g
    # grounded caps preserved
    assert g.count("1 *1:A 0.002") == 1
    assert "1 *2:A 0.003" in g
    # net1 total reduced by the 0.001 coupling: 0.005 -> 0.004
    assert "*D_NET *1 0.004" in g
    assert "*D_NET *2 0.003" in g


def test_strip_coupling_idempotent_on_grounded():
    g1 = FE.strip_coupling_caps(_SPEF)
    g2 = FE.strip_coupling_caps(g1)
    assert g1 == g2


# ── driver false-clean guards (no container) ──────────────────────────────────
def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_extract_solver_absent_is_not_applicable(tmp_path):
    dp = _write(tmp_path, "d.def", _DEF)
    lp = _write(tmp_path, "t.lef", _LEF)
    sp = _write(tmp_path, "s.spef", _SPEF)
    # force both runners to miss the binary
    res = FE.extract(dp, lp, sp, runner="docker",
                     container="definitely-no-such-container-xyz", do_inject=False)
    assert res["status"] == "NOT_APPLICABLE"
    assert res["solver_available"] is False
    assert "FasterCap" in res["reason"]
    # fitted stack is still real + returned
    assert res["dielectric_stack"]["n_layers"] >= 1


def test_extract_unrouted_def_is_not_applicable(tmp_path):
    empty_def = "VERSION 5.8 ;\nUNITS DISTANCE MICRONS 1000 ;\nNETS 0 ;\nEND NETS\n"
    dp = _write(tmp_path, "d.def", empty_def)
    lp = _write(tmp_path, "t.lef", _LEF)
    sp = _write(tmp_path, "s.spef", _SPEF)
    res = FE.extract(dp, lp, sp, do_inject=False)
    assert res["status"] == "NOT_APPLICABLE"
    assert "unrouted" in res["reason"]


# ── _clip_cluster (extracted from select_cluster; whole-design reuses it) ──────
def test_clip_cluster_builds_bounded_cluster():
    layers = SC.parse_lef_layers(_LEF)
    units = SC.parse_def_units(_DEF)
    segs = SC.parse_def_wires(_DEF, layers, units)
    # victim na, aggressors nb+nc -> all three lie within 2um -> >=2 nets clipped
    cluster = FE._clip_cluster(segs, "na", ["nb", "nc"], units, window_um=2.0)
    assert len(cluster) >= 2
    assert "na" in cluster
    assert all(len(v) >= 1 for v in cluster.values())


def test_clip_cluster_no_aggressors_is_empty():
    layers = SC.parse_lef_layers(_LEF)
    segs = SC.parse_def_wires(_DEF, layers, 1000)
    assert FE._clip_cluster(segs, "na", [], 1000) == {}


def test_clip_cluster_absent_victim_is_empty():
    layers = SC.parse_lef_layers(_LEF)
    segs = SC.parse_def_wires(_DEF, layers, 1000)
    assert FE._clip_cluster(segs, "no_such_net", ["nb"], 1000) == {}


def test_select_cluster_still_matches_after_refactor():
    # select_cluster now delegates the clip to _clip_cluster; its contract is
    # unchanged: victim from strongest pair, >=2 nets, restricted analytical pairs
    layers = SC.parse_lef_layers(_LEF)
    units = SC.parse_def_units(_DEF)
    segs = SC.parse_def_wires(_DEF, layers, units)
    victim, cluster, pairs = FE.select_cluster(segs, layers, units,
                                               window_um=2.0, max_aggressors=6)
    assert victim in cluster and len(cluster) >= 2
    assert all(k[0] in cluster and k[1] in cluster for k in pairs)


# ── plan_coverage (whole-design tiling; PURE) ─────────────────────────────────
def _covers_all(pairs, plans):
    """Every analytical pair must lie inside at least one plan's net set."""
    for (a, b) in pairs:
        ok = any(a in set([v] + ag) and b in set([v] + ag) for v, ag in plans)
        if not ok:
            return False
    return True


def test_plan_coverage_empty():
    assert FE.plan_coverage({}) == []


def test_plan_coverage_covers_every_pair_small():
    pairs = {("a", "b"): 3.0, ("b", "c"): 2.0, ("a", "c"): 1.0,
             ("c", "d"): 0.5}
    plans = FE.plan_coverage(pairs, max_aggressors=6)
    assert plans, "must emit at least one plan"
    assert _covers_all(pairs, plans)


def test_plan_coverage_star_needs_multiple_plans_but_covers_all():
    # a hub 'h' coupled to 20 spokes; max_aggressors=4 forces several plans,
    # yet EVERY hub-spoke pair must still be covered (no pair silently dropped)
    pairs = {(("h", "s%02d" % k) if "h" < "s%02d" % k
              else ("s%02d" % k, "h")): float(20 - k) for k in range(20)}
    plans = FE.plan_coverage(pairs, max_aggressors=4)
    assert _covers_all(pairs, plans)
    # each plan is bounded to <= max_aggressors+1 conductors
    assert all(len([v] + ag) <= 5 for v, ag in plans)
    # a 20-edge star at 4 aggressors/plan needs several plans
    assert len(plans) >= 5


def test_plan_coverage_deterministic():
    pairs = {("a", "b"): 3.0, ("b", "c"): 2.0, ("a", "c"): 1.0,
             ("c", "d"): 0.5, ("d", "e"): 0.9}
    assert FE.plan_coverage(pairs, 3) == FE.plan_coverage(pairs, 3)


def test_plan_coverage_dense_clique_covers_all():
    nets = ["n%d" % k for k in range(8)]
    pairs = {}
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            pairs[(nets[i], nets[j])] = 1.0 / (i + j + 1)
    plans = FE.plan_coverage(pairs, max_aggressors=4)
    assert _covers_all(pairs, plans)


# ── whole-design driver false-clean guards (no container) ─────────────────────
def test_whole_design_solver_absent_is_not_applicable(tmp_path):
    dp = _write(tmp_path, "d.def", _DEF)
    lp = _write(tmp_path, "t.lef", _LEF)
    sp = _write(tmp_path, "s.spef", _SPEF)
    res = FE.extract_whole_design(
        dp, lp, sp, runner="docker",
        container="definitely-no-such-container-xyz", do_inject=False)
    assert res["status"] == "NOT_APPLICABLE"
    assert res["solver_available"] is False
    assert res["mode"] == "whole_design"
    # the analytical pair universe + fitted stack are real even with no solver
    assert res["n_analytical_pairs"] >= 1
    assert res["dielectric_stack"]["n_layers"] >= 1


def test_whole_design_unrouted_is_not_applicable(tmp_path):
    empty_def = "VERSION 5.8 ;\nUNITS DISTANCE MICRONS 1000 ;\nNETS 0 ;\nEND NETS\n"
    dp = _write(tmp_path, "d.def", empty_def)
    lp = _write(tmp_path, "t.lef", _LEF)
    sp = _write(tmp_path, "s.spef", _SPEF)
    res = FE.extract_whole_design(dp, lp, sp, do_inject=False)
    assert res["status"] == "NOT_APPLICABLE"
    assert "unrouted" in res["reason"]


def test_whole_design_solver_failure_does_not_drop_coupling(tmp_path,
                                                            monkeypatch):
    # A per-cluster SOLVER FAILURE (no well-formed matrix) must NOT be recorded
    # as a screened-to-zero coverage: doing so would SILENTLY DROP real coupling
    # (making the downstream SI bound optimistic — a false-clean). It must leave
    # the pair uncovered so it keeps its analytical value.
    dp = _write(tmp_path, "d.def", _DEF)
    lp = _write(tmp_path, "t.lef", _LEF)
    sp = _write(tmp_path, "s.spef", _SPEF)
    monkeypatch.setattr(FE, "_fastercap_available",
                        lambda runner, container: (True, "native"))
    # solver "runs" but never emits a capacitance matrix
    monkeypatch.setattr(FE, "_run_fastercap",
                        lambda *a, **k: "Computing links...\n(no matrix)\n")
    res = FE.extract_whole_design(dp, lp, sp, do_inject=False, runner="native")
    assert res["status"] == "PASS"          # the pass ran; it just found nothing
    assert res["n_analytical_pairs"] >= 1
    assert res["failed_solves"] > 0
    # NOTHING is marked field-solved on a failed matrix (no fabricated coverage)
    assert res["pairs_field_solved"] == 0
    assert res["coverage_fraction"] == 0.0
    # every analytical pair stays uncovered -> injection keeps its analytical Cc
    assert res["uncovered_pairs"] == res["n_analytical_pairs"]
