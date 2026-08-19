"""A tool's WORDING may not decide a gate's verdict. W5 acceptance.

THE DEFECT, MEASURED
--------------------
`eda_report_audit._check_drc` reads two PROSE sources: a runner-written summary
line and the router's own end-of-iteration tally. Both are regexes over a log.
When a tool renames its tally — a version bump, nothing more — the regex stops
matching, and a regex that stops matching does not report "I can no longer see":
it reports nothing found, and the caller reads that as nothing wrong.

Measured on `tests/fixtures/w5_drc_wording/`, on origin/main 8e60dd954, with the
SAME twelve unfixed violations in both files and the tally wording as the only
difference between them:

    known/     drc_report_check ... -> rc=1  FAIL  tool_corroborated_files: 1
    reworded/  drc_report_check ... -> rc=0  PASS  tool_corroborated_files: 0

A wording change alone turned a failing sign-off green, and the corroboration
that vanished did so silently — no finding at any severity named it.

WHAT THIS FILE PINS
-------------------
1. The fixtures still differ ONLY in wording, and the reworded one really is
   invisible to every grammar this repo has. If a future parser learns the new
   spelling, `test_the_two_fixtures_differ_only_in_wording` still holds but
   `test_the_reworded_tally_is_invisible_to_every_grammar` fails loudly — which
   is the correct outcome, because the demonstration would no longer be one.
2. With the tool's own metric present, the verdict follows the METRIC:
   12 -> FAIL, 0 -> PASS, and the wording is irrelevant to both.
3. A metric and a parser that disagree FAIL. Neither side is preferred, and the
   refusal is structural: `step_metrics.authoritative` has no code path that
   returns a value for `disagree`.
4. No metric at all leaves the old behaviour intact and SAYS SO. A parser
   speaking alone is UNCORROBORATED, never agreement; and neither source
   speaking is NOT MEASURED, which used to produce no finding at all — the
   quietest state being the worst one. That branch was found by a test whose
   expectation was wrong, and it is pinned here so it cannot go quiet again.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

#: Each call runs one wrapper over a 2.8 KB fixture. Measured worst case in this
#: module is well under a second; 30s is the same bound the sibling metrics
#: tests use and half the per-call harness ceiling.
_SUBPROC_S = 30

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
FIXTURES = PROGRAMS / "tests" / "fixtures" / "w5_drc_wording"

sys.path.insert(0, str(PROGRAMS))
import openroad_metrics as om  # noqa: E402
import step_metrics as sm  # noqa: E402

#: What OpenROAD writes when `-metrics` is on its command line. Flat, namespaced
#: by the stage that computed it, and containing no prose at all.
TOOL_METRICS = {
    "detailedroute__route__wirelength": 1284310,
    "detailedroute__route__vias": 39142,
    "detailedroute__route__drc_errors": None,   # filled per case
    "detailedroute__antenna__violating__nets": 0,
}


def _project(tmp_path, variant, drc_errors=None):
    """A copy of one fixture, optionally carrying the tool's own metrics."""
    proj = tmp_path / variant
    shutil.copytree(FIXTURES / variant, proj)
    if drc_errors is not None:
        doc = dict(TOOL_METRICS)
        doc["detailedroute__route__drc_errors"] = drc_errors
        src = proj / "reports/phase3/drc_router.metrics.json"
        src.write_text(json.dumps(doc), encoding="utf-8")
        out, prov = om.ingest(proj, "21", src)
        assert prov["status"] == "emitted", prov
        assert out.is_file()
    return proj


def _gate(proj):
    """Step 21's own gate command, verbatim from the flow file."""
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "drc_report_check.py"), ".",
         "--mode", "drc", "--under", "reports/phase3/drc_router.rpt",
         "--json", "reports/phase3/drc_router.json"],
        cwd=str(proj), capture_output=True, text=True, timeout=_SUBPROC_S)
    audit = json.loads((proj / "reports/phase3/drc_router.json").read_text())
    return r.returncode, audit


def _rules(audit, severity):
    return [f["rule"] for f in audit["findings"] if f["severity"] == severity]


# ---------------------------------------------------------------------------
# the fixtures themselves
# ---------------------------------------------------------------------------
def test_the_two_fixtures_differ_only_in_wording():
    known = (FIXTURES / "known/reports/phase3/drc_router.rpt").read_text()
    reworded = (FIXTURES / "reworded/reports/phase3/drc_router.rpt").read_text()
    normalise = lambda s: s.replace("design rule errors remaining",  # noqa: E731
                                    "Number of violations")
    assert normalise(reworded) == known, \
        "the fixtures diverged in something other than the tally's wording"


def test_the_reworded_tally_is_invisible_to_every_grammar():
    """The demonstration is only a demonstration while this holds."""
    import _signoff_drc_format as sdf  # noqa: PLC0415
    text = (FIXTURES / "reworded/reports/phase3/drc_router.rpt").read_text()
    assert sdf.router_iter_last_count(text) is None, \
        "a grammar learned the new spelling; this fixture no longer isolates it"
    assert "12" in text, "the fixture must still contain the tool's real count"


def test_the_known_tally_is_read_and_the_design_is_dirty():
    import _signoff_drc_format as sdf  # noqa: PLC0415
    text = (FIXTURES / "known/reports/phase3/drc_router.rpt").read_text()
    assert sdf.router_iter_last_count(text) == 12


# ---------------------------------------------------------------------------
# the verdict follows the METRIC, not the wording
# ---------------------------------------------------------------------------
def test_a_reworded_log_with_a_dirty_metric_fails(tmp_path):
    rc, audit = _gate(_project(tmp_path, "reworded", drc_errors=12))
    assert rc == 1, audit["summary"]
    assert audit["passed"] is False
    assert "DRC_REAL_VIOLATIONS_FOUND_BY_TOOL_METRIC" in _rules(audit, "ERROR")
    assert audit["summary"]["metric_gating_total"] == 12
    # and the blindness is NAMED rather than left as a silence
    assert "DRC_LOG_PARSER_BLIND" in _rules(audit, "WARNING")


def test_a_reworded_log_with_a_clean_metric_passes(tmp_path):
    """`unaffected`: the wording changed, the measurement did not, and neither
    did the verdict."""
    rc, audit = _gate(_project(tmp_path, "reworded", drc_errors=0))
    assert rc == 0, audit["summary"]
    assert audit["passed"] is True
    assert audit["summary"]["metric_vs_log"]["verdict"] == sm.METRIC_ONLY
    assert "DRC_LOG_PARSER_BLIND" in _rules(audit, "WARNING")


def test_a_metric_and_a_parser_that_disagree_certify_nothing(tmp_path):
    rc, audit = _gate(_project(tmp_path, "known", drc_errors=0))
    assert rc == 1, audit["summary"]
    assert audit["passed"] is False
    assert "DRC_METRIC_CONTRADICTS_LOG" in _rules(audit, "ERROR")
    assert audit["summary"]["metric_vs_log"]["verdict"] == sm.DISAGREE
    # NEITHER side became the number. A gating total here would BE the silent
    # preference this rule exists to prevent.
    assert audit["summary"]["metric_gating_total"] is None


def test_a_metric_and_a_parser_that_agree_are_corroborated(tmp_path):
    rc, audit = _gate(_project(tmp_path, "known", drc_errors=12))
    assert audit["summary"]["metric_vs_log"]["verdict"] == sm.AGREE
    assert rc == 1, "twelve violations is still twelve violations"


# ---------------------------------------------------------------------------
# with no metric, the old behaviour stands — and is labelled
# ---------------------------------------------------------------------------
def test_a_parser_alone_is_reported_as_uncorroborated_not_agreed(tmp_path):
    """`known` wording, no metric: the parser read 12 and nothing checked it."""
    _rc, audit = _gate(_project(tmp_path, "known"))
    assert audit["summary"]["metric_violation_total"] is None
    assert audit["summary"]["metric_vs_log"]["verdict"] == sm.PROSE_ONLY
    assert ("DRC_COUNT_UNCORROBORATED_BY_TOOL_METRIC"
            in _rules(audit, "WARNING")), _rules(audit, "WARNING")


def test_neither_source_speaking_is_said_out_loud(tmp_path):
    """`reworded` wording, no metric — the worst case, and the one that used to
    be the quietest: the tool was never asked, no grammar matched, and the run
    still went green with no finding of any severity naming the silence."""
    rc, audit = _gate(_project(tmp_path, "reworded"))
    assert rc == 0, "unchanged: this is the state the migration starts from"
    assert audit["summary"]["metric_vs_log"]["verdict"] == sm.NEITHER
    assert "DRC_TOOL_COUNT_NOT_MEASURED" in _rules(audit, "WARNING"), \
        _rules(audit, "WARNING")


def test_the_pre_change_defect_is_reproduced_by_the_fixtures(tmp_path):
    """Both halves of the measurement in this module's docstring, in one test,
    so the claim cannot go stale without a failure."""
    rc_known, _ = _gate(_project(tmp_path, "known"))
    rc_reworded, audit = _gate(_project(tmp_path, "reworded"))
    assert rc_known == 1, "the known wording must still redden"
    assert rc_reworded == 0, "the reworded wording must still go green"
    assert audit["summary"]["tool_corroborated_files"] == 0, \
        "the corroboration that silently vanished is the defect"
