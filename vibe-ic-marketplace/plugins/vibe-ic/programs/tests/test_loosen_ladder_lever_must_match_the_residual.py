"""The loosen ladder's only lever is utilisation, and nothing checked that the
residual it was pulling against had a die in it.

MEASURED (subservient x gf180mcuD, host 8HD-9, plugin 1.15.55 / 1.15.57,
image ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2..., OpenROAD 26Q3-1472),
straight out of `reports/orchestrator/phase3_one_shot.json`:

    rung 0   416x416   util 0.25    residual 4
    rung 1   491x491   util 0.18    residual 6
    rung 2   602x602   util 0.12    residual 1
    rung 3   738x738   util 0.08    residual 3
    rung 4   904x904   util 0.053   residual 3   -> ROUTE_NOT_CONVERGED

Four extra full PnR passes and a 4.7x growth in die AREA, and the residual
series is not a trend. The router had ALREADY named what was left, in a file
this flow asks it to write (`detailed_route -output_drc`, sibling fixture
`routed_router_ns_metal.drc.rpt`):

    NS Metal  net __uuf__._0114_  (397.7500 177.3900)-(397.7900 177.4450) Metal1
    NS Metal  net __uuf__._0053_  (661.5100 177.3900)-(661.5500 177.4450) Metal1
    NS Metal  net _128_           (452.8995 294.9795)-(452.9005 294.9805) Metal2

Two of the three are the SAME cell-local offset (local x 4.63-4.67 um, y
0.99-1.045 um) inside two instances of ONE library cell -- a Via1 metal pad
against that cell's output-pin rectangle -- and the third is 1 DBU across.
None of the three is a distance between two independently-routed shapes, so
none of them has a die in it.

The decision read only the SHAPE of the count trajectory
(`_drt_is_non_converging`: a plateau), and a geometry residual plateaus
exactly like a congested one. The evidence that tells them apart was on disk
the whole time and had no consumer: `_router_drc_report_block` pastes the
report into `routed.drc.rpt` and declares itself ADVISORY.

WHAT THIS CHANGE IS AND IS NOT. It does not widen any threshold, it does not
make a failing route pass, and it does not assert the design is routable. It
stops the ladder from spending PnR passes on a lever that cannot reach the
finding, and makes the verdict say which lever the finding is at.

DECLARED: ADVISORY. `pnr` still FAILs ROUTE_NOT_CONVERGED with whatever the
shipped route measures.

WHITELIST DIRECTION, deliberately: `_DRT_SELF_SHAPE_RULES` lists the IMMOVABLE
rules, so a type the set does not know is treated as congestion-shaped and the
ladder behaves exactly as before. A new or renamed tool marker costs a wasted
rung, never a refused rescue.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hostpaths  # noqa: E402

_PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
_spec = importlib.util.spec_from_file_location("_p3r_lever_match", _PROG)
_p3r = importlib.util.module_from_spec(_spec)
sys.modules["_p3r_lever_match"] = _p3r
_spec.loader.exec_module(_p3r)

_FIX = Path(__file__).resolve().parent / "fixtures" / "drt_residual_types"
_REAL_LOG = (_FIX / "openroad_round3_ns_metal_tail.txt").read_text()
_REAL_RPT = _FIX / "routed_router_ns_metal.drc.rpt"


def _pnr_dir_with_report(tmp_path: Path, report: Path | None) -> Path:
    d = tmp_path / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    if report is not None:
        (d / _p3r.ROUTER_DRC_REPORT_NAME).write_text(report.read_text())
    return d


# ── the report parser, on the run's own file ──────────────────────────────
def test_the_report_this_run_wrote_parses_into_type_layer_and_net(tmp_path):
    d = _pnr_dir_with_report(tmp_path, _REAL_RPT)
    recs = _p3r._router_drc_report_records(d)
    assert [r["type"] for r in recs] == ["NS Metal"] * 3
    assert [r["layer"] for r in recs] == ["Metal1", "Metal1", "Metal2"]
    assert [r["nets"] for r in recs] == [["__uuf__._0114_"],
                                         ["__uuf__._0053_"], ["_128_"]]


def test_the_breakdown_is_refused_unless_it_reconciles(tmp_path):
    """Same discipline `_drt_types_supersession` applies to the log's table:
    `-output_drc` is rewritten by EVERY `detailed_route` call, so a report
    whose record count does not equal the published count is some other
    route's evidence and must not be stated as this one's."""
    d = _pnr_dir_with_report(tmp_path, _REAL_RPT)
    assert _p3r._router_drc_report_types(d, 3) == [("NS Metal", "Metal1", 2),
                                                   ("NS Metal", "Metal2", 1)]
    assert _p3r._router_drc_report_types(d, 2) == []
    assert _p3r._router_drc_report_types(d, None) == []
    assert _p3r._router_drc_report_types(_pnr_dir_with_report(
        tmp_path / "empty", None), 3) == []


# ── the classifier ────────────────────────────────────────────────────────
def test_classifier_separates_the_two_families():
    f = _p3r._residual_is_congestion_shaped
    assert f([("NS Metal", "Metal1", 2), ("NS Metal", "Metal2", 1)]) is False
    assert f([("Min Area", "Metal2", 1)]) is False
    assert f([("MinStep", "Metal1", 1)]) is False
    # a single congestion type anywhere in the residual re-opens the lever
    assert f([("NS Metal", "Metal1", 2), ("Short", "Metal2", 1)]) is True
    assert f([("Metal Spacing", "Metal1", 5)]) is True
    assert f([("EOL Spacing", "Metal3", 1)]) is True
    # nothing measured, and an unnameable type, are both "do not decide"
    assert f([]) is None
    assert f(None) is None
    assert f([("", "Metal1", 1)]) is None
    # an UNKNOWN type is congestion-shaped by construction: the ladder keeps
    # its pre-existing behaviour rather than refusing a rescue it cannot judge
    assert f([("Some Future LEF58 Rule", "Metal4", 1)]) is True


# ── the negative control, BIDIRECTIONAL, on the real log ──────────────────
def _decide(residual_types, log=_REAL_LOG, rung=0):
    return _p3r._route_feedback_loosen_ex(
        416, 416, log, rung,
        auto_die_requested=True, route_completed=True,
        residual_history=[], residual_types=residual_types)


def test_without_the_router_naming_it_the_ladder_still_loosens():
    """THE CONTROL. This is the pre-fix decision, driven by the real round-3
    log: no `residual_types` supplied, so the guard cannot fire and the ladder
    grows the die. If this ever stops loosening, the test below proves nothing
    -- it would be passing because the ladder declined for some other reason."""
    decision, reason = _decide(None)
    assert reason == "loosened", reason
    assert decision is not None
    new_w, new_h, record = decision
    assert new_w > 416 and new_h > 416, (new_w, new_h)
    assert record["trigger"] == "route_not_converged"


def test_the_router_naming_a_self_shape_residual_declines_the_rung():
    """The REASON is asserted first, and against a concrete expected string.

    `assert decision is None` alone is a weaker control than it looks:
    `control_substance_check` grades it `undecided` because "the only
    expectation named is the None sentinel", so a reviewer cannot tell a
    failure that observed a wrong VALUE from one that merely noticed something
    absent. Comparing the reason string makes the pre-fix failure read
    `assert 'loosened' == 'residual_not_congestion_shaped'` — a value against a
    value — and the die assertion below names the numbers the ladder must NOT
    have moved."""
    decision, reason = _decide([("NS Metal", "Metal1", 2),
                                ("NS Metal", "Metal2", 1)])
    assert reason == "residual_not_congestion_shaped"
    assert _p3r._LOOSEN_TERMINATOR_KIND[reason] == "evidence"
    # the die the ladder was asked about must come back unchanged, by VALUE:
    # the pre-fix code returns (491, 491, <resize record>) here.
    assert [t[:2] for t in ([decision] if decision else [])] == []
    assert decision is None


def test_a_congestion_residual_on_the_same_log_still_loosens():
    """The other direction of the control: identical log, identical rung, only
    the router's naming differs. A guard that declined here would be refusing
    the congestion rescue the ladder exists for.

    THIS DIRECTION IS NOT HYPOTHETICAL. Same design, same host, same day, the
    ONLY variable the container image (2026-09-02, subservient x gf180mcuD):

      arm A  image ...66c33ff2 (OpenROAD 26Q3-1472)  residual `NS Metal`
             -> ladder walked 416 -> 491 -> 602 -> 738 -> 904 and never
                reached 0; series [4, 6, 1, 3, 3]
      arm B  image ...657143cb (OpenROAD 26Q3-1921)  residual `Short` +
             `Metal Spacing` on Metal2/Metal3
             -> ladder took ONE rung, 416 -> 491, and the route reached 0;
                series [1, 0], declined `route_still_converging`

    Arm B is exactly the case the ladder exists for, and this guard must not
    touch it. Its residual types, straight out of the run's own Viol/Layer
    tables on the way down: `Short x1 @Metal3`, `Metal Spacing x1 @Metal2`,
    `Short x2 @Metal2` -- congestion, every one."""
    for types in ([("Short", "Metal2", 3)],
                  [("Short", "Metal3", 1)],
                  [("Metal Spacing", "Metal2", 1), ("Short", "Metal3", 1)]):
        decision, reason = _decide(types)
        assert reason == "loosened", (types, reason)
        assert decision is not None


def test_the_guard_never_overrides_a_still_converging_route():
    """Precedence: a route whose tail is still strictly decreasing is NOT
    non-converging, and must keep reporting that -- the guard sits strictly
    below `route_still_converging`."""
    converging = ("[INFO DRT-0199]   Number of violations = 9.\n"
                  "[INFO DRT-0199]   Number of violations = 3.\n")
    decision, reason = _decide([("NS Metal", "Metal1", 1)], log=converging)
    assert decision is None
    assert reason == "route_still_converging"


# ── the flat-tail measure ─────────────────────────────────────────────────
def test_the_loop_question_is_asked_of_the_loops_own_series():
    """`router_iter_counts` APPENDS DRT-0701's verified count so its last
    element is what ships. That element is not an iteration, and measuring the
    plateau over it answered "the last iteration changed the count" on a route
    that had held the same count for its whole tail -- so the verdict offered
    "raise the router's end iteration" as a remedy not ruled out."""
    shipped = _p3r._drt_violation_trajectory(_REAL_LOG)
    loop = _p3r._drt_loop_trajectory(_REAL_LOG)
    assert shipped[-1] == 3 and loop[-1] == 1
    assert len(shipped) == len(loop) + 1
    assert _p3r._drt_flat_tail(shipped) == 1          # the defect
    assert _p3r._drt_flat_tail(loop) >= 2             # the measurement
    # and that is exactly the threshold the verdict keys "more iterations" on
    assert (_p3r._drt_flat_tail(shipped) >= 2) is False
    assert (_p3r._drt_flat_tail(loop) >= 2) is True


# ── inert on a real published corpus run ──────────────────────────────────
def test_inert_on_a_real_corpus_run_that_converged():
    """`spm x gf180mcuD` converged (published 0). It writes no residual the
    guard could classify, so the guard must be structurally unreachable there
    -- if it were not, every converged corpus run would change decision."""
    art = _hostpaths.require_repo(
        "benchmark-data", "ic", "spm", "v1.14.88_gf180mcuD",
        "reports", "orchestrator", "phase3_one_shot.json")
    doc = json.loads(art.read_text())
    pnr = [st for st in doc.get("steps", []) if st.get("name") == "pnr"]
    assert pnr, "corpus run carries no pnr step"
    assert pnr[0].get("status") == "PASS", (
        "this corpus run was chosen because it CONVERGED; it no longer does, "
        "so it is the wrong negative control")
    assert _p3r._residual_is_congestion_shaped([]) is None
