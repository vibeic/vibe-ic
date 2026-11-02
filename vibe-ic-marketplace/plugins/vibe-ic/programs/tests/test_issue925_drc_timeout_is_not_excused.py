#!/usr/bin/env python3
"""vibe-ic#925 — a DRC wall-clock timeout must not be EXCUSED.

WHAT WAS WRONG. `_try_svrf_native_drc` bounds the commercial sign-off DRC at a
wall-clock budget. When the engine was killed at that budget the step returned
the word `SKIPPED-CONDITION`. The prose beside it was already honest — it
refuses to call a timeout a violation and refuses to sign off from a partial
report. The WORD was not:

  * `SKIPPED-CONDITION` is `flow_compliance_check`'s vocabulary, not this
    runner's (`_VERDICT_TIERS`), and `_aggregate_verdict` enumerates its own
    vocabulary and lets anything else fall through to the catch-all
    `return "PASS"`.  MEASURED on the unfixed tree: a plan whose only non-PASS
    step was a timed-out sign-off DRC aggregated to a plain green `"PASS"` —
    not even PASS_WITH_WAIVERS.
  * `verdict.is_excused("NOT_APPLICABLE")` is True, so wherever
    the word IS adjudicated the step is subtracted from `total_required`: a DRC
    that ran out of time stopped being owed an answer at all.

The tests below ASK THE PROGRAMS — the real `_try_svrf_native_drc`, the real
`_aggregate_verdict`, the real `verdict` — and never recompute a
rule locally.

TWO ARMS, both required by the issue's acceptance criteria:

  ARM 1 (`test_timeout_*`)  a DRC that timed out must stay owed and must keep
        the run from being green.  These FAIL on the unfixed program.
  ARM 2 (`test_guard_*`)    a DRC that genuinely does not apply to a design,
        or whose tool is genuinely absent, must STILL be excusable, and the
        shared tier vocabulary must be untouched.  These PASS on BOTH arms —
        they exist so a future fix cannot satisfy ARM 1 by breaking the
        legitimate skip, or by relabelling the vocabulary so the finding
        disappears.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R   # noqa: E402
import verdict as T      # noqa: E402
from _finished_gds_fixture import publish_finished_gds


def _state_inputs(project, top):
    views = {}
    for view in ("gds", "def", "nl"):
        path = project / ("selected." + view)
        path.write_text("DESIGN " + top + " ;\nEND DESIGN\n" if view == "def" else view)
        views[view] = str(path)
    (project / "state_out.json").write_text(json.dumps(views))
    publish_finished_gds(project)


def _pdk(**kw):
    base = dict(name="custom:x", liberty="x", tech_lef="x", cell_lef="x",
                cell_gds=None, site="unit", drc_deck=None,
                calibre_drc="/x/DRC.rule")
    base.update(kw)
    return R.PdkConfig(**base)


def _headline(step) -> str:
    """The runner's OWN headline for a plan whose only non-PASS row is
    `step`."""
    return R._aggregate_verdict(
        [R.StepResult("synth", "PASS"), R.StepResult("pnr", "PASS"), step])


def _is_green(verdict: str) -> bool:
    """Derived from the runner's own rank table, not from a typed list of
    words: anything ranked at or below PASS_WITH_WAIVERS is a verdict the
    project may ship on (CLAUDE.md recognises PASS_WITH_WAIVERS as real)."""
    return (R._VERDICT_RANK.get(verdict, R._VERDICT_RANK["FAIL"])
            <= R._VERDICT_RANK["PASS_WITH_WAIVERS"])


def _timed_out_drc(tmp_path, monkeypatch, rc, write_partial=False):
    """Drive the REAL `_try_svrf_native_drc` into its wall-clock kill path."""
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: "svrfdrc")
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.delenv("VIBE_IC_DRC_BUDGET_S", raising=False)
    rpt = tmp_path / "phase3" / "reports" / "drc_svrf_calibre.rpt"

    def _fake_exec(c, cmd, **k):
        if write_partial:
            # what a killed engine leaves behind: a half-written report whose
            # header parses but whose rule list stopped mid-run.
            rpt.parent.mkdir(parents=True, exist_ok=True)
            rpt.write_text("# SVRF-native DRC via KLayout\n"
                           "PASS  SPACE.M1.1  EXTERNAL M1 < 0.23 -> 0\n")
        return (rc, "", "")

    monkeypatch.setattr(R, "_docker_exec", _fake_exec)
    gds = R._pl.pnr_dir(tmp_path) / "top.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_text("gds")
    res = R._try_svrf_native_drc(tmp_path, "top", _pdk(), "img", gds=gds, routed_def=tmp_path / "selected.def")
    return res, rpt


# ── ARM 1 — the timeout must remain outstanding and must hold the run back ──
def test_timeout_is_not_excused_by_the_shared_tier_module(tmp_path,
                                                          monkeypatch):
    """EXCUSED is precisely what `total_required` subtracts. A sign-off DRC
    that ran out of time must not be subtracted."""
    for rc in (124, R._RC_STALLED):
        mp = monkeypatch
        res, _ = _timed_out_drc(tmp_path / f"rc{rc}", mp, rc)
        assert res is not None
        assert not T.is_excused(res.status), (
            f"rc={rc}: a timed-out sign-off DRC is EXCUSED "
            f"(status={res.status!r}) — it leaves total_required")
        # ...and it must reach the verdict rather than vanish from its scope.
        assert T.scoped_into_verdict(
            {"status": res.status, "stage": "stage4"}), (
            f"rc={rc}: status={res.status!r} is scoped OUT of the verdict")


def test_timeout_keeps_the_run_from_being_green(tmp_path, monkeypatch):
    """The runner's own headline, from the runner's own aggregator."""
    for rc in (124, R._RC_STALLED):
        res, _ = _timed_out_drc(tmp_path / f"g{rc}", monkeypatch, rc)
        verdict = _headline(res)
        assert not _is_green(verdict), (
            f"rc={rc}: a run whose sign-off DRC never completed reports "
            f"{verdict!r} — a green verdict with no DRC answer behind it")


def test_timeout_isolates_the_partial_report(tmp_path, monkeypatch):
    """ORGANIC #570 — a killed engine's half-written report must not
    survive at the canonical path, or the next reader signs off from it."""
    res, rpt = _timed_out_drc(tmp_path, monkeypatch, 124, write_partial=True)
    assert res.status is not None
    assert not rpt.is_file(), (
        f"the partial report a killed engine left behind is still readable at "
        f"the canonical path {rpt}")
    # DISCOVERED, not re-derived: whatever the program renamed it to, it must
    # still be beside the canonical path for triage and must not BE it.
    survivors = [q for q in rpt.parent.glob(rpt.name + "*") if q != rpt]
    assert survivors, (
        "the partial report was neither isolated nor preserved for triage")


# ── ARM 2 — PAIRED GUARDS: these must NOT change ───────────────────────────
def test_guard_shared_tier_vocabulary_is_untouched():
    """The fix must NOT be achieved by relabelling the shared vocabulary.

    `SKIPPED-CONDITION` means "this design legitimately has none", and the
    whole analog track resolves to it on a pure-digital design. Moving that
    word out of EXCUSED would make every such run non-green — laundering the
    #925 finding away by breaking the tier it was introduced for."""
    assert T.is_excused("NOT_APPLICABLE") is True
    assert T.is_non_green("NOT_APPLICABLE") is False
    assert T.scoped_into_verdict(
        {"status": "NOT_APPLICABLE", "stage": T.ANALOG_STAGE}) is False
    # R-0915-85 — the word is `NOT_APPLICABLE` and `EXCUSED` holds it alone.
    # `SKIPPED-CONDITION` is refused at `parse`, which is a STRONGER guard than
    # the membership this line used to assert: the word cannot re-enter the
    # register by being written somewhere, because it cannot be written.
    assert T.EXCUSED == frozenset({"NOT_APPLICABLE"}), T.EXCUSED
    with pytest.raises(T.UnknownVerdictWord):
        T.parse("SKIPPED-CONDITION")


def test_guard_a_design_dependent_or_env_absence_is_NOT_a_failure(tmp_path,
                                                                  monkeypatch):
    """Every OTHER way `step_drc` can decline keeps its own tier, is NOT a
    FAIL, and NAMES what stopped it. Driven down each real branch.

    R-0915-85 CHANGED THE SECOND HALF OF THIS GUARD, and says so here. It used
    to read "…and must keep the run shippable", which was true while these
    branches wore `SKIP` — a word inside EXCUSED, so a run whose DRC never
    executed exited 0. The ruling refuses that: nothing about DRC was measured
    on any of these three branches, and a green a run cannot support is not a
    success. They are NOT_MEASURED, each with the reason that separates it from
    the #925 TIMEOUT, and the run is off PASS.

    #925's own finding is untouched and is asserted above: a DRC that was
    KILLED is not excused. What this guard still forbids is the other failure
    mode — turning a design/env absence into a FAIL, which would report a
    finding about a design nothing looked at.
    """
    # (a) the PDK ships no DRC deck at all — a design/PDK property.
    _state_inputs(tmp_path, "top")
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    res = R.step_drc(tmp_path, "top", _pdk(drc_deck=None, calibre_drc=None),
                     "img")
    assert res.status == "NOT_MEASURED" and res.reason_class == "tool_absent", (
        res.status, res.reason_class, res.detail)

    # (b) a Calibre deck AND the calibre binary — the runner defers to an
    #     offline sign-off run rather than invoking it. THIS one is a real
    #     deferral: somebody owns the row, so it is the waiver tier.
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    res = R.step_drc(tmp_path, "top", _pdk(), "img")
    assert _is_green(_headline(res)), (res.status, res.detail)

    # (c) the native engine is genuinely absent from the image — an ENV gap.
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: None)
    res = R.step_drc(tmp_path, "top", _pdk(), "img")
    assert res.status == "NOT_MEASURED", (res.status, res.detail)
    assert res.reason_class, "an env gap must name what stopped it"

    # NONE of them is a FAIL — that is the half of this guard that stands.
    assert res.status != "FAIL"


def test_guard_a_completed_clean_drc_is_still_a_full_pass(tmp_path,
                                                          monkeypatch):
    """The engine ran to completion with zero firing rules: still a full PASS
    and still a green run. A fix that made every DRC non-green would satisfy
    ARM 1 and be worthless."""
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda c: "svrfdrc")
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    rpt = tmp_path / "phase3" / "reports" / "drc_svrf_calibre.rpt"

    def _fake_exec(c, cmd, **k):
        rpt.parent.mkdir(parents=True, exist_ok=True)
        rpt.write_text("# SVRF-native DRC via KLayout\n"
                       "PASS  SPACE.M1.1  EXTERNAL M1 < 0.23 -> 0\n"
                       "PASS  WIDTH.M2.1  INTERNAL M2 < 0.28 -> 0\n")
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", _fake_exec)
    gds = R._pl.pnr_dir(tmp_path) / "top.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_text("gds")
    res = R._try_svrf_native_drc(tmp_path, "top", _pdk(), "img", gds=gds, routed_def=tmp_path / "selected.def")
    assert R._aggregate_verdict([R.StepResult("pnr", "PASS"), res]) == "PASS"
    assert rpt.is_file(), "a COMPLETED run's report must not be isolated"
    assert R._parse_svrf_tally(rpt)[0] == 0, \
        "the report the step signed off on"
