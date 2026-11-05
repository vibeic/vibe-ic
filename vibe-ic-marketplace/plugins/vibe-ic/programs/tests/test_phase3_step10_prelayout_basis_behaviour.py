"""Explicit Step10 must measure the current mapped design and compose fresh STA.

Native transport is substituted here; no device timing is claimed. Prior
reports remain available as history. A failed remeasurement, including a
partially written report, cannot reuse an earlier clean result. The shared
post-route caller keeps its existing reuse behavior.
"""
from __future__ import annotations

import json
import re
import sys
import pytest
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402
import _sta_basis  # noqa: E402  (the ONE stamp reader — the test reads it too)

TOP = "widget"

_STALE_POST_ROUTE = (
    "Startpoint: reg_a (rising edge-triggered flip-flop)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop)\n"
    "  0.11   slack (MET)\n"
    "tns 0.00\n"
    "wns 0.00\n"
    "STA_BASIS: POST_ROUTE_SPEF\n"
    "STA_BASIS_NOTE: routed netlist + extracted SPEF (earlier round)\n"
)

_PRE_LAYOUT_HEADER = (
    "# PRE-LAYOUT STA (Step 10) — genuine OpenSTA on the synth\n"
    "# netlist + SDC, emitted BEFORE PnR. STA_BASIS is stamped in\n"
    "# the report body; interconnect is a pre-floorplan estimate.\n"
    "# corner source: sta_SS.rpt\n"
)


class _Pdk:
    """Minimal PdkConfig stand-in: the fields this step actually reads.

    The run supplies its real neutral staged Liberty to the SDC reader;
    no image PDK or native measurement is used by this direct-process unit.
    Nothing here depends on which PDK is mounted."""
    name = "harness-pdk"
    liberty = "/foss/pdks/harness-pdk/lib/x__tt.lib"
    macro_libs: list = []


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _fake_opensta(calls: list, fail_corners=()):
    """A faithful OpenSTA stand-in.

    It stamps into the report the basis the RUNNER told it to stamp — parsed
    out of the tcl the runner itself just wrote — so every basis this file
    observes is the runner's own decision, never a value the test supplied.
    `fail_corners` reproduces the measured failure: that corner's run returns
    rc != 0 and writes nothing.
    """
    def _run(container, cmd, timeout=1800, *, marker=None, log_path=None,
             stall_grace_s=None, hard_ceiling_s=None, poll_s=None,
             outputs=None):
        # vibe-ic#1330 — THE REPORT IS NO LONGER DECLARED ON THE CALL. This one
        # call site may DESTROY its own output (the black-box `_bb` branch), so
        # `_emit_multi_corner_sta` now runs with `marker=` only and declares the
        # report afterwards, on the surviving path, via `_log_surviving_artefact`.
        # This stand-in read `outputs[0]` unconditionally and died on `None`.
        #
        # `marker` is the tcl the runner just wrote for THIS corner, and
        # `_to_container_path` is patched to identity here, so it names the same
        # directory and the same corner the report belongs to — the fake still
        # learns the corner from the RUNNER's own artefact, never from the test.
        # `outputs` is still honoured when a call site supplies it, because the
        # other ~17 sites do and this fake stands in for the same function.
        if outputs:
            rpt = Path(outputs[0])
        elif marker:
            _tcl = Path(marker)
            rpt = _tcl.with_suffix(".rpt")
        else:                                                # pragma: no cover
            raise AssertionError(
                "_docker_exec called with neither `outputs` nor `marker`: this "
                "stand-in cannot tell which corner it is being asked to run")
        corner = rpt.stem[len("sta_"):]
        calls.append(corner)
        if corner in fail_corners:
            return (1, "", f"OpenSTA: {corner} run did not converge")
        tcl = rpt.parent / f"sta_{corner}.tcl"
        m = re.search(r'puts \$_bf "STA_BASIS: ([A-Z_]+)"', tcl.read_text())
        assert m, f"runner emitted no STA_BASIS stamp for {corner}"
        _write(rpt, _healthy_body(f"STA_BASIS: {m.group(1)}",
                                 slack=dict(SS=0.42, TT=0.52, FF=0.62)[corner]))
        return (0, "", "")
    return _run


def _rerun_project(root: Path, *, per_corner_bodies: dict,
                   pre_pnr_body: str | None) -> Path:
    """The measured re-run state: a routed netlist + SPEF from an earlier round
    sitting beside the synth netlist, with whatever STA artefacts that round
    left behind."""
    proj = root / "proj"
    # This module substitutes the direct OpenSTA edge, not a native LL run.
    _write(proj / 'phase3/librelane_switch.json', json.dumps({
        'steps': {sid: 'direct' for sid in ('7', '8', '10')}}))
    # two staged corners -> the step uses them directly (no container probe)
    _write(proj / "input" / "pdk" / "liberty" / "x__ss.lib",
           'library(ss) { time_unit : "1ns"; }\n')
    _write(proj / "input" / "pdk" / "liberty" / "x__tt.lib",
           'library(tt) { time_unit : "1ns"; }\n')
    # Preserve the existing working deck while Step7 binds its selected input.
    _write(R._pl.pnr_dir(proj) / "constraint.sdc",
           "create_clock -name core_clk -period 10.0 [get_ports clk]\n")
    _write(R._pl.synth_dir(proj) / f"{TOP}_synth.v", "// synth netlist\n")
    _write(R._pl.pnr_dir(proj) / f"{TOP}_pnr.v", "// routed netlist\n")
    _write(proj / "phase3/stage3/extracted" / f"{TOP}.spef", "*SPEF\n")
    for name, body in per_corner_bodies.items():
        _write(R._pl.sta_dir(proj) / R.STEP10_CORNER_DIR / name, body)
    if pre_pnr_body is not None:
        _write(R._pl.sta_dir(proj) / "pre_pnr_timing.rpt", pre_pnr_body)
    return proj


def _hermetic(monkeypatch, calls, fail_corners=()):
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "_docker_exec",
                        _fake_opensta(calls, fail_corners))


def _run_step(proj):
    pdk = _Pdk()
    pdk.liberty = str(proj / 'input/pdk/liberty/x__tt.lib')
    return R.step_prelayout_signoff(proj, TOP, pdk, "harness-container")


# ---------------------------------------------------------------------------
# BLOCKING 1 — a corner whose forced re-emit FAILS
# ---------------------------------------------------------------------------

def test_failed_corner_reemit_cannot_supply_the_pre_layout_body(tmp_path,
                                                                monkeypatch):
    """SS's forced re-emit fails; TT's succeeds.

    OBSERVED VALUE: the basis `pre_pnr_timing.rpt` declares about itself.
      pre-fix  -> POST_ROUTE  (stale SS report reused, then composed verbatim)
      post-fix -> PRE_LAYOUT  (stale SS quarantined, TT is the only legal src)
    No symbol is referenced that the pre-fix file lacks.
    """
    calls: list = []
    proj = _rerun_project(
        tmp_path,
        per_corner_bodies={"sta_SS.rpt": _STALE_POST_ROUTE,
                           "sta_TT.rpt": _STALE_POST_ROUTE},
        pre_pnr_body=_PRE_LAYOUT_HEADER + _STALE_POST_ROUTE)
    # Keep a second genuinely distinct pre-layout corner available while SS
    # fails. The new summary consumer must still measure two legal corners.
    _write(proj / "input/pdk/liberty/x__ff.lib", "library(ff){}")
    _write(R._pl.sta_dir(proj) / R.STEP10_CORNER_DIR / "sta_FF.rpt",
           _healthy_body("STA_BASIS: PRE_LAYOUT_ESTIMATE", slack=0.62))
    _hermetic(monkeypatch, calls, fail_corners=("SS",))

    res = _run_step(proj)

    sta = R._pl.sta_dir(proj)
    pre_pnr = sta / "pre_pnr_timing.rpt"
    assert pre_pnr.is_file(), res.detail
    assert _sta_basis.declared_basis(pre_pnr.read_text()) == "PRE_LAYOUT", (
        "the PRE-LAYOUT header is published over a body declaring "
        f"{_sta_basis.declared_basis(pre_pnr.read_text())!r}: "
        + pre_pnr.read_text())
    # the failed corner leaves NO report — never a mislabelled one
    assert not (sta / R.STEP10_CORNER_DIR / "sta_SS.rpt").is_file(), (
        "the stale POST_ROUTE SS report survived its failed re-emit")
    # ...and the quarantine decision point was actually ENTERED (not merely
    # an outcome that some other branch could have produced)
    assert (sta / R.STEP10_CORNER_DIR / "sta_SS.rpt.stale_basis").is_file()
    assert res.status == "PASS", (res.status, res.detail)


def test_every_corner_failing_is_a_warn_not_a_pass(tmp_path, monkeypatch):
    """Both forced re-emits fail, so NOTHING pre-layout can be substantiated.

    OBSERVED VALUE: StepResult.status.
      pre-fix  -> PASS, with a POST_ROUTE body still published at the
                  pre-layout path (could-not-measure -> measured-clean)
      post-fix -> WARN, and the contradiction is no longer published
    """
    calls: list = []
    proj = _rerun_project(
        tmp_path,
        per_corner_bodies={"sta_SS.rpt": _STALE_POST_ROUTE,
                           "sta_TT.rpt": _STALE_POST_ROUTE},
        pre_pnr_body=_PRE_LAYOUT_HEADER + _STALE_POST_ROUTE)
    _hermetic(monkeypatch, calls, fail_corners=("SS", "TT"))

    res = _run_step(proj)

    pre_pnr = R._pl.sta_dir(proj) / "pre_pnr_timing.rpt"
    published = pre_pnr.read_text() if pre_pnr.is_file() else ""
    assert _sta_basis.declared_basis(published) != "POST_ROUTE", (
        "a POST_ROUTE body is published under the PRE-LAYOUT header: "
        + published)
    assert res.status == "NOT_MEASURED", (
        "the step could not substantiate its pre-layout artefact and still "
        f"reported {res.status}: {res.detail}")
    assert "REPORT_ABSENT" in res.detail, res.detail
    # degrade LOUDLY: the displaced bytes are kept, under a non-.rpt suffix so
    # nothing globbing sta/*.rpt can re-adopt them
    assert (R._pl.sta_dir(proj) / "pre_pnr_timing.rpt.stale_basis").is_file()


def test_composer_refuses_a_post_route_corner_report_by_name(tmp_path,
                                                             monkeypatch):
    """A POST_ROUTE report sitting at `sta_SS.rpt` must never be the source,
    even when it is the first name the composer reaches for and the tool is
    entirely unavailable.

    Here the stale corner report is ALSO the only file present and no
    `pre_pnr_timing.rpt` exists yet, so the ONLY thing under test is the
    compose-source choice.
      pre-fix  -> pre_pnr_timing.rpt written, declaring POST_ROUTE
      post-fix -> not written at all; the refusal is stated in the notes
    """
    calls: list = []
    proj = _rerun_project(
        tmp_path,
        per_corner_bodies={"sta_SS.rpt": _STALE_POST_ROUTE},
        pre_pnr_body=None)
    _hermetic(monkeypatch, calls, fail_corners=("SS", "TT"))

    res = _run_step(proj)

    pre_pnr = R._pl.sta_dir(proj) / "pre_pnr_timing.rpt"
    if pre_pnr.is_file():
        assert _sta_basis.declared_basis(pre_pnr.read_text()) == "PRE_LAYOUT", (
            "composed the pre-layout report from a POST_ROUTE corner report: "
            + pre_pnr.read_text())
    assert "REFUS" in res.detail or not pre_pnr.is_file(), res.detail


# ---------------------------------------------------------------------------
# The policy word, and the destructive/non-destructive split
# ---------------------------------------------------------------------------

def test_undeclared_pre_pnr_is_reported_not_deleted(tmp_path, monkeypatch):
    """A `pre_pnr_timing.rpt` carrying NO recognised stamp.

    `_sta_basis` states that `None` is neither basis — it is "the report
    declared no side of PnR". So:
      * it must NOT be quarantined (deleting on an unanswered question), and
      * it must NOT count as clean either.
    This is the test that fails if `ok`'s policy word is flipped from
    "the basis IS PRE_LAYOUT" to "the basis is NOT POST_ROUTE".
    """
    calls: list = []
    undeclared = _PRE_LAYOUT_HEADER + "  0.11   slack (MET)\ntns 0.00\n"
    proj = _rerun_project(tmp_path, per_corner_bodies={},
                          pre_pnr_body=undeclared)
    _hermetic(monkeypatch, calls, fail_corners=("SS", "TT"))

    res = _run_step(proj)

    pre_pnr = R._pl.sta_dir(proj) / "pre_pnr_timing.rpt"
    assert not pre_pnr.exists()
    assert pre_pnr.with_name(pre_pnr.name + '.stale_basis').read_text() == undeclared
    assert res.status == "NOT_MEASURED", (res.status, res.detail)



# ---------------------------------------------------------------------------
# REVERSE cases — these must STILL pass
# ---------------------------------------------------------------------------

def _healthy_body(stamp_line: str, *, slack=0.42) -> str:
    # Source-control process output, including both path types required by
    # the real summary reader. The runner still determines the basis stamp.
    sections = [f"{stamp_line}\nSTA_TIME_UNIT: ns\nOpenSTA report_checks\n"]
    for kind, arrival, required, value in (
            ('max', 2.5, 2.5 + slack, slack), ('min', .35, .10, .25)):
        sections.append(
            "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
            "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
            f"Path Group: clk\nPath Type: {kind}\n\n"
            "  Delay    Time   Description\n"
            "---------------------------------------------------------\n"
            "   0.00    0.00   clock clk (rise edge)\n"
            "   0.00    0.00   clock network delay (ideal)\n"
            f"   {arrival:.2f}    {arrival:.2f}   reg_a/Q -> reg_b/D\n"
            f"           {arrival:.2f}   data arrival time\n"
            f"           {required:.2f}   data required time\n"
            "---------------------------------------------------------\n"
            f"           {value:.2f}   slack (MET)\n\n")
    sections.append(f"wns max {slack:.2f}\ntns max 0.00\nwns min 0.25\ntns min 0.00\n"
                    "STA_BASIS_NOTE: software fixture, not native STA measurement\n")
    return ''.join(sections)


@pytest.mark.parametrize('failed', [False, True])
def test_explicit_prelayout_rerun_remeasures_changed_mapped_logic(tmp_path, monkeypatch, failed):
    calls = []
    body = _healthy_body("STA_BASIS: PRE_LAYOUT_ESTIMATE", slack=0.52)
    pre = _PRE_LAYOUT_HEADER + body
    proj = _rerun_project(tmp_path,
        per_corner_bodies={"sta_SS.rpt": body, "sta_TT.rpt": body}, pre_pnr_body=pre)
    _write(R._pl.synth_dir(proj) / f"{TOP}_synth.v", "// changed mapped logic\n")
    _hermetic(monkeypatch, calls, fail_corners=("SS", "TT") if failed else ())
    transport = R._docker_exec
    def failed_partial(*args, **kwargs):
        result = transport(*args, **kwargs)
        if failed and result[0] != 0:
            Path(kwargs['marker']).with_suffix('.rpt').write_text(body)
        return result
    monkeypatch.setattr(R, '_docker_exec', failed_partial)
    result = _run_step(proj)
    sta = R._pl.sta_dir(proj)
    assert sorted(calls) == ['SS', 'TT']
    assert (sta / 'pre_pnr_timing.rpt.stale_basis').read_text() == pre
    for corner in ['SS', 'TT']:
        assert (sta / R.STEP10_CORNER_DIR / f'sta_{corner}.rpt.stale_basis').read_text() == body
    if failed:
        assert not (sta / 'pre_pnr_timing.rpt').exists()
        assert len(list((sta / R.STEP10_CORNER_DIR).glob('*.rpt.failed'))) == 2
        assert result.status != 'PASS'
    else:
        assert (sta / 'pre_pnr_timing.rpt').read_text() != pre
        assert result.status == 'PASS', result.detail


def test_reverse_post_route_caller_is_untouched(tmp_path, monkeypatch):
    """The DEFAULT (post-route, Step 23) producer must be byte-unchanged.

    It reuses an existing corner report by EXISTENCE alone and never
    quarantines one — post-route reports are real sign-off data. A tightening
    that reached this caller would destroy it.
    """
    calls: list = []
    proj = _rerun_project(
        tmp_path,
        per_corner_bodies={"sta_SS.rpt": _STALE_POST_ROUTE,
                           "sta_TT.rpt": _STALE_POST_ROUTE},
        pre_pnr_body=None)
    _hermetic(monkeypatch, calls)
    per_corner = R._pl.sta_dir(proj) / R.STEP10_CORNER_DIR
    libs = sorted((proj / "input" / "pdk" / "liberty").glob("*.lib"))
    notes: list = []

    emitted = R._emit_multi_corner_sta(proj, TOP, _Pdk(), "harness-container",
                                       libs, per_corner, notes)

    assert emitted is True, notes
    assert calls == [], f"post-route caller re-ran an existing report: {calls}"
    assert (per_corner / "sta_SS.rpt").read_text() == _STALE_POST_ROUTE
    assert (per_corner / "sta_TT.rpt").read_text() == _STALE_POST_ROUTE
    assert not list(per_corner.glob("*.stale_basis")), (
        "quarantined a post-route sign-off report")


# ---------------------------------------------------------------------------
# THE HEADLINE DEFECT, driven through the REAL step
#
# The sibling unit spec asserts this by CALLING `_multi_corner_sta_inputs` with
# the new `force_prelayout=` kwarg, so its pre-fix failure is a `TypeError` for
# a symbol this change introduces — TAUTOLOGICAL. The case below reaches the
# same defect through `step_prelayout_signoff`, whose signature is identical on
# both sides, so its pre-fix failure is an assertion about the OBSERVED basis of
# a published artefact.
# ---------------------------------------------------------------------------

def test_rerun_with_a_routed_netlist_still_publishes_a_pre_layout_report(
        tmp_path, monkeypatch):
    """The measured re-run: a routed netlist + SPEF from an earlier round sit
    beside the synth netlist, and Step 10 runs into an EMPTY `per_corner/`.

    Nothing is stale here and no corner run fails — this is the plain
    idempotency case. Pre-fix, the file-existence precedence hands the routed
    netlist + SPEF to the pre-layout step, so every corner report is stamped
    `POST_ROUTE_SPEF` and the composer wraps one in the PRE-LAYOUT header:

      pre-fix  -> pre_pnr_timing.rpt declares POST_ROUTE  (the contradiction
                  `sta_report_check --mode sta` flags, which FAILs Step 10 and
                  PASS-VOIDS the whole mid-chain behind it)
      post-fix -> PRE_LAYOUT, timed on the synth netlist with no SPEF

    Asserts on three observed values, not on the presence of a symbol: what the
    published report DECLARES about itself, what the corner reports declare, and
    which netlist the deck the tool actually ran READ.
    """
    calls: list = []
    proj = _rerun_project(tmp_path, per_corner_bodies={}, pre_pnr_body=None)
    _hermetic(monkeypatch, calls)

    res = _run_step(proj)

    pre_pnr = R._pl.sta_dir(proj) / "pre_pnr_timing.rpt"
    assert pre_pnr.is_file(), "Step 10 published no pre-layout report"
    assert _sta_basis.declared_basis(pre_pnr.read_text()) == "PRE_LAYOUT", (
        "the PRE-LAYOUT header is published over a body declaring "
        f"{_sta_basis.declared_basis(pre_pnr.read_text())!r}: "
        f"{pre_pnr.read_text()}")

    per_corner = R._pl.sta_dir(proj) / R.STEP10_CORNER_DIR
    corner_rpts = sorted(per_corner.glob("sta_*.rpt"))
    assert corner_rpts, "no corner report was produced"
    for rpt in corner_rpts:
        assert _sta_basis.declared_basis(rpt.read_text()) == "PRE_LAYOUT", (
            f"{rpt.name} was timed on a post-route basis by the PRE-layout "
            f"step: {rpt.read_text()}")

    # What was actually TIMED — the stamp is only honest if the deck agrees.
    for tcl in sorted(per_corner.glob("sta_*.tcl")):
        deck = tcl.read_text()
        assert f"{TOP}_synth.v" in deck, (
            f"{tcl.name} did not read the pre-PnR synth netlist: {deck}")
        assert f"{TOP}_pnr.v" not in deck, (
            f"{tcl.name} timed the ROUTED netlist under the pre-layout step: "
            f"{deck}")
        assert "read_spef" not in deck, (
            f"{tcl.name} annotated post-route parasitics into a pre-layout "
            f"estimate: {deck}")

    assert res.status == "PASS", (res.status, res.detail)
