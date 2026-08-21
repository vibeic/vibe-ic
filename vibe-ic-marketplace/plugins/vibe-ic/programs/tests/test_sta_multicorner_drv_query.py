"""The multicorner SPEF STA emit (`_emit_corner_spef_sta._stanza`) must query
DRV (report_check_types) and must not let a report_checks hiccup suppress it.

caravel_user_project x sky130A: the stanza ran
`report_checks {flag} -group_count 3 >> rpt` UNGUARDED. `-group_count` was
removed from OpenSTA (now `-group_path_count`), so the stale flag raised a Tcl
error that aborted the script BEFORE `report_check_types` ran. The resulting
sta_spef_multicorner.rpt carried sign-off timing but NO DRV query and no
SIGNOFF_CHECK_TYPES marker — an unqueried max_slew/max_cap limit is
indistinguishable from a met one, so `sta_corner_record_completeness_check`
FAILed Step 23.

Guard the emitted stanza source: the report_checks call is `catch`-guarded and
uses `-group_path_count`, and the DRV query still follows it.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as P  # noqa: E402


def _stanza_source() -> str:
    return inspect.getsource(P._emit_corner_spef_sta)


def _code_lines(src: str) -> str:
    """The source with whole-line `#` comments dropped, so assertions key on the
    emitted Tcl, not on explanatory prose."""
    return "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#")
                     and not l.lstrip().startswith('f"#'))


def test_multicorner_stanza_guards_report_checks_and_queries_drv():
    code = _code_lines(_stanza_source())
    # ORGANIC #540 — the report_checks call moved into the shared
    # `_report_worst_paths_tcl` helper (the flag needed translating, and the
    # same bug was at both corner emitters). Assert on the helper's real
    # OUTPUT, not on the emitter's source text: the previous form of this
    # assertion matched a `catch {report_checks {flag} ...}` that OpenSTA
    # rejected on every run, so the stanza it was guarding never executed.
    assert "_report_worst_paths_tcl" in code
    tcl = P._report_worst_paths_tcl("/x/out.rpt", "-max")
    assert "catch {report_checks" in tcl
    assert "-group_path_count" in tcl
    # The DRV sign-off query still follows.
    assert "report_check_types" in code


def test_multicorner_stanza_has_no_unguarded_removed_group_count_flag():
    code = _code_lines(_stanza_source())
    # The removed flag must not appear as an emitted report_checks argument.
    assert "-group_count" not in code
    assert "-group_count" not in P._report_worst_paths_tcl("/x/out.rpt", "-max")
