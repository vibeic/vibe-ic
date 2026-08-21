"""ORGANIC #624 [MEDIUM] — def_stage_progression_check's `identical-def-fraud`
guard rejected post_hold.def == post_cts.def (identical sha256) as "a copy/stub,
not a real PnR output". But when a design is hold-CLEAN after CTS (the resizer
reports 0 hold violations to repair), the hold-fix step legitimately makes NO
geometry change, so post_hold.def is byte-identical to post_cts.def BY
CONSTRUCTION. The fraud heuristic mistook a correct no-op hold-fix for a
fabricated stub and false-FAILed Step-21 Routing for any hold-clean design.

OBSERVED (a minimal RISC-V SoC): post_cts.def and post_hold.def share sha256
(6d47399c...), and the design was hold-clean after CTS (RSZ-0033 no hold
violations). A datapath multiplier whose hold-fix DID change the DEF has
DISTINCT sha256 — the differentiator is whether hold-fix had work to do.

Fix: exempt the EXACT {post_cts, post_hold} identical pair ONLY when the hold
report (pnr/post_hold_timing.rpt) proves the design is hold-clean (worst hold
slack >= 0 / INF). Fail-closed otherwise.

POSITIVE (#624): post_cts == post_hold + hold-clean report → no fraud.

NEGATIVE no-leak (issue-mandated):
  - post_cts == post_hold WITH unrepaired hold violations (negative slack) →
    STILL FAIL.
  - post_cts == post_hold with NO hold report → fail-closed → STILL FAIL.
  - a genuinely copied/stale pair (e.g. placed == post_cts) even with a clean
    hold report → STILL FAIL (only the post_cts/post_hold pair is exempt).

chip-AGNOSTIC: keyed on OpenROAD's own hold-slack number + the exact stage
pair, no chip literal.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import def_stage_progression_check as D  # noqa: E402
import _path_layout as _pl  # noqa: E402

_CTS = "COMPONENTS 3 ;\ninst a\ninst b\ninst c\nEND COMPONENTS\n"
_ROUTED = (_CTS.replace("3 ;", "4 ;") +
           "SPECIALNETS 1 ;\n- VDD + ROUTED\nEND SPECIALNETS\n")


def _mk(tmp_path, hold_rpt, cts_eq_hold=True, placed_eq_cts=False):
    pnr = _pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "floorplan.def").write_text("COMPONENTS 1 ;\ninst a\nEND COMPONENTS\n")
    (pnr / "placed.def").write_text(
        _CTS if placed_eq_cts else
        "COMPONENTS 2 ;\ninst a\ninst b\nEND COMPONENTS\n")
    (pnr / "post_cts.def").write_text(_CTS)
    (pnr / "post_hold.def").write_text(_CTS if cts_eq_hold else _CTS + "inst d\n")
    (pnr / "routed.def").write_text(_ROUTED)
    if hold_rpt is not None:
        (pnr / "post_hold_timing.rpt").write_text(hold_rpt)
    return tmp_path


def _fraud(tmp_path):
    _infos, finds = D.inspect(tmp_path)
    return [f for f in finds if f.rule == "identical-def-fraud"]


def test_hold_clean_noop_pair_is_not_fraud(tmp_path):
    _mk(tmp_path, "worst hold slack 0.123\nhold WNS 0.123\n")
    assert _fraud(tmp_path) == []


def test_inf_slack_no_hold_paths_is_not_fraud(tmp_path):
    _mk(tmp_path, "worst hold slack inf\n")
    assert _fraud(tmp_path) == []


def test_unrepaired_hold_violations_still_fraud(tmp_path):
    _mk(tmp_path, "worst hold slack -0.045\nhold WNS -0.045\n")
    assert _fraud(tmp_path), "negative hold slack → not a legitimate no-op"


def test_no_hold_report_fail_closed(tmp_path):
    _mk(tmp_path, None)
    assert _fraud(tmp_path), "no hold report → cannot prove clean → still fraud"


def test_other_identical_pair_still_fraud(tmp_path):
    # placed == post_cts is a genuine stale-stage copy; a clean hold report for
    # the post_hold pair must NOT exempt it.
    _mk(tmp_path, "worst hold slack 0.5\n", cts_eq_hold=False, placed_eq_cts=True)
    assert _fraud(tmp_path)


def test_hold_fix_changed_def_passes(tmp_path):
    # the normal case: hold-fix had work → distinct sha256 → no fraud anyway.
    _mk(tmp_path, "worst hold slack -0.01\n", cts_eq_hold=False)
    assert _fraud(tmp_path) == []


def test_helper_parses_slack():
    import tempfile
    p = Path(tempfile.mkdtemp())
    pnr = _pl.pnr_dir(p)
    pnr.mkdir(parents=True)
    (pnr / "post_hold_timing.rpt").write_text("worst hold slack 0.0\n")
    assert D._hold_clean_noop_ok(p) is True
    (pnr / "post_hold_timing.rpt").write_text("worst hold slack -1e-3\n")
    assert D._hold_clean_noop_ok(p) is False
    assert D._hold_clean_noop_ok(Path(tempfile.mkdtemp())) is False  # no report
