"""Phase-3 DRC honesty fixes (ORGANIC 2026-07-11, commercial commercial PDK run):

  1. routed.drc.rpt router-DRC count — must be the FINAL converged
     `[INFO DRT-0199] Number of violations = N`, NOT the number of log LINES
     containing the word "violation". The old line-count reported a route that
     CONVERGED to 0 as dozens ("DRC clean: NO"), contradicting the pnr verdict.

  2. Commercial SVRF-DRC FAIL classifier — splits firing rules into
     {GEOMETRY (real, keeps gate FAIL), MARKER_ABSENT (provable empty-exclusion-
     marker artifact), DENSITY_FILL (test-chip sparsity)} PROVABLY and
     CONSERVATIVELY, without ever downgrading a genuine geometry violation.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as P  # noqa: E402


# ------------------------------------------------ 1) router DRC final count ---
_ROUTER_LOG = """\
[INFO DRT-0195] Start 1st optimization iteration.
    Completing 10% with 67 violations.
    Completing 50% with 63 violations.
    Completing 100% with 19 violations.
[INFO DRT-0199]   Number of violations = 19.
[INFO DRT-0195] Start 2nd optimization iteration.
    Completing 90% with 18 violations.
    Completing 100% with 0 violations.
[INFO DRT-0199]   Number of violations = 0.
[INFO DRT-0198] Complete detail routing.
"""


def test_drt_final_is_last_converged_count_not_line_count():
    # authoritative final count is 0 (converged), NOT the ~6 "violation" lines
    assert P._drt_final_violations(_ROUTER_LOG) == 0
    # the OLD buggy method (count log lines mentioning "violation") would be > 0
    buggy = sum(1 for ln in _ROUTER_LOG.splitlines()
                if "violation" in ln.lower())
    assert buggy >= 6 and buggy != 0        # proves the two methods disagree


def test_drt_final_reports_nonzero_when_route_stalls():
    log = ("Completing 100% with 4 violations.\n"
           "[INFO DRT-0199]   Number of violations = 4.\n")
    assert P._drt_final_violations(log) == 4      # a stalled route is NOT clean


def test_drt_final_none_when_no_drt_output():
    assert P._drt_final_violations("global route only, no detail route\n") is None


# ------------------------------------------- 2) commercial SVRF classifier ---
# A faithful miniature of the real commercial-PDK report shape: an EMPTY exclusion
# marker (`COPY __artisan__ … -> 0`), a `_not_artisan` min-area FAIL (artifact),
# density FAILs (fill), and a wide-metal spacing FAIL with an opaque derived
# layer (real geometry — must stay FAILing).
_SVRF_RPT = """\
# SVRF-native DRC via KLayout  |  {'PASS': 3, 'FAIL': 4}
PASS  Artisan.CHECK      COPY __artisan__  0.0 [COPY] -> 0
PASS  Mx.A.1             AREA backend__met2_not_artisan < 0.202 [metrics=euclidian] -> 0
FAIL  M1.A.1             AREA backend__met1_not_artisan < 0.202 [metrics=euclidian] -> 906
FAIL  M1.S.2             EXTERNAL L72974 < 0.6 [metrics=euclidian,ignore_angle=90.0] -> 176
FAIL  PDF.D.4.1          DENSITY MET1_DUD < 0.3 [metrics=euclidian] -> 1
FAIL  PDF.D.6.1          DENSITY MET2_DUD < 0.3 [metrics=euclidian] -> 1
"""


def _write(tmp_path):
    r = tmp_path / "drc_svrf_calibre.rpt"
    r.write_text(_SVRF_RPT)
    return r


def test_classifier_splits_provably(tmp_path):
    cls = P._classify_svrf_fails(_write(tmp_path))
    assert "artisan" in cls["empty_markers"]
    # M1.A.1 references _not_artisan and artisan is EMPTY → marker-absent artifact
    assert cls["marker_absent"] == ["M1.A.1"]
    # the two DENSITY rules → fill gap
    assert cls["density_fill"] == ["PDF.D.4.1", "PDF.D.6.1"]
    # the opaque wide-metal spacing FAIL is NOT provably an artifact → GEOMETRY
    assert cls["geometry"] == ["M1.S.2"]


def test_classifier_total_is_conserved(tmp_path):
    r = _write(tmp_path)
    fails, _p, _s, _f = P._parse_svrf_tally(r)
    cls = P._classify_svrf_fails(r)
    assert (cls["n_geometry"] + cls["n_marker_absent"]
            + cls["n_density_fill"]) == fails       # every FAIL classified once


def test_classifier_never_downgrades_unknown(tmp_path):
    # A FAIL that references NO empty marker and is NOT density must stay GEOMETRY
    # (keeps the gate FAIL) — the no-cheat invariant.
    r = tmp_path / "r.rpt"
    r.write_text("FAIL  MET1.SP.1  EXTERNAL L999 < 0.23 [m] -> 12\n")
    cls = P._classify_svrf_fails(r)
    assert cls["geometry"] == ["MET1.SP.1"]
    assert cls["n_marker_absent"] == 0 and cls["n_density_fill"] == 0


def test_marker_absent_needs_the_marker_to_be_empty(tmp_path):
    # Same _not_artisan rule but artisan is NON-empty (COPY -> 5) → the exclusion
    # marker is present, so the FAIL is real geometry, NOT an artifact.
    r = tmp_path / "r.rpt"
    r.write_text(
        "PASS  Artisan.CHECK  COPY __artisan__ 0.0 [COPY] -> 5\n"
        "FAIL  M1.A.1  AREA backend__met1_not_artisan < 0.202 [m] -> 900\n")
    cls = P._classify_svrf_fails(r)
    assert cls["empty_markers"] == []          # artisan is populated
    assert cls["marker_absent"] == []          # → not an artifact
    assert cls["geometry"] == ["M1.A.1"]       # → real, keeps FAIL
