#!/usr/bin/env python3
"""The four residuals #778 + #779 left behind, each measured and named.

#778 gave the STA gates a per-step `--under` scope; #779 made step 10 run a
genuine pre-layout STA so it has its own report. Neither reached the corner
evidence, and firing #779 turned a latent overclaim into the default.

1  `--under` NEVER REACHED THE CORNER-DIRECTORY SCAN. `_check_sta`'s
   `corner_dirs` is a raw project-wide `glob.glob(...per_corner)`, so a
   POST-ROUTE summary was substantiated by PRE-LAYOUT evidence. MEASURED on a
   project with three distinct `STA_BASIS: PRE_LAYOUT_ESTIMATE` corner
   reports::

       UNSCOPED     rc=0 multi_corner_executed=True corner_reports_distinct=3
       step-23 scope rc=0 multi_corner_executed=True corner_reports_distinct=3
                     scoped_under=['phase3/stage3/sta/post_route_timing.rpt']

   This is not hypothetical after #779: `phase3/stage3/sta/per_corner/` is ONE
   directory written by TWO producers — `step_prelayout_signoff` before PnR
   and `step_canonicalize_artefacts` after route — and
   `_emit_multi_corner_sta` SKIPS a corner whose report already exists
   (`test_the_shared_corner_directory_keeps_whichever_basis_wrote_it_first`
   runs that code). So on every project where the pre-layout producer runs
   first the directory holds PRE-LAYOUT reports forever, and the post-route
   sign-off gate counted them as its own.

   Repair: `--under` reaches the scan as a BASIS DECLARATION rather than a
   path filter, and the counter is SPLIT by the basis each report discloses.
   (Routing `corner_dirs` through `_in_scope` is the wrong repair: under the
   single-file scopes it zeroes the corner evidence for step 10 AND step 23.)

2  STEP 10'S `STA_SINGLE_CORNER_ONLY` WAS ON EVERYWHERE. Measured over the 54
   tracked phase-3 roots: all 7 that resolve a step-10 report emitted it, on
   `corner_dirs_found: 0`. Step 10 is named "Pre-layout STA (multi-corner)"
   and, unlike step 23, has no dedicated corner gate — that advisory is its
   only multi-corner statement. Its scope now names its own `per_corner/`
   directory beside its summary report, and the counter is basis-split, so a
   genuine pre-layout multi-corner run silences it.

3  `_in_scope` ADMITTED A DANGLING SYMLINK AND CRASHED ON A LOOP. On
   `benchmark-data/ic/edge_llm_accel` the scoped step-10 gate reported
   `files_found: 1` while `scoped_under_missing` named the only scope and no
   finding cited a file. The path is a dangling symlink, so it resolves to
   exactly the scope root. It stays DISCOVERABLE on purpose — dropping it in
   `_in_scope` flips `edge_llm_accel --mode drc` from rc 1 to rc 0, deleting
   a landed gate — and is instead NAMED at ERROR, exactly as `_check_drc`
   names it, with `readable_files` published beside `files_found`.
   Separately, `Path.resolve()` raises **RuntimeError** on a symlink loop on
   Python 3.12; the `except OSError` guard did not fire and the program died
   with a traceback and no verdict.

4  NOTHING REFUSED TO CERTIFY STEP 10 ON A POST-PnR-DERIVED REPORT. All 8
   tracked corpus roots carrying a `phase3/stage3/sta/pre_pnr_timing.rpt`
   carry this header::

       # Auto-staged by phase3_one_shot_runner v1.6.36
       # Source: OpenROAD report_checks (post-link, pre-floorplan slack
       # is approximated by the unconstrained slack in the post-PnR
       # report below — ...

   7 of them returned rc 0. The predicate keys on the SELF-DISCLOSURE — a
   derivation verb plus a post-layout source in the report's own leading
   comment block — never on the emitter's version string.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_AUDIT = _PROGRAMS / "eda_report_audit.py"
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eda_report_audit as ERA                                   # noqa: E402

_PAD = "# " + ("=" * 78 + "\n") * 20                             # ~1.6 KB

_BODY = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\n"
    "data arrival time: 2.34 ns\ndata required time: 2.49 ns\n"
    "WNS = 0.15 ns\nTNS = 0.0 ns\n"
    "0.15   slack (MET)\n"
    "setup check: PASS\nhold check: PASS\n" + _PAD
)
_VIOLATED_BODY = _BODY.replace("0.15   slack (MET)", "-7.41  slack (VIOLATED)")

# The v1.6.36 header, verbatim from the corpus.
_AUTOSTAGED_HEADER = (
    "# Auto-staged by phase3_one_shot_runner v1.6.36\n"
    "# Source: OpenROAD report_checks (post-link, pre-floorplan slack\n"
    "# is approximated by the unconstrained slack in the post-PnR\n"
    "# report below — for production sign-off, run a separate\n"
    "# pre-floorplan STA pass).\n"
)
# The step-23 header, verbatim from `step_canonicalize_artefacts`. It names
# "post-route" with NO derivation claim and must NOT trip the predicate.
_POST_ROUTE_HEADER = (
    "# post_route_timing.rpt — SPEF-BASED post-route STA (canonical, #527).\n"
    "# Basis: extracted parasitics (read_spef extracted/top.spef).\n"
    "# The estimate-based report_checks is retained at "
    "phase3/stage3/pnr/sta.rpt for comparison.\n"
)

_STEP10_REL = "phase3/stage3/sta/pre_pnr_timing.rpt"
_STEP23_REL = "phase3/stage3/sta/post_route_timing.rpt"
_CORNER_REL = "phase3/stage3/sta/per_corner"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _project(tmp_path: Path, *, corners=(), corner_basis="PRE_LAYOUT_ESTIMATE",
             step10_header="", step10_basis="PRE_LAYOUT_ESTIMATE") -> Path:
    """A phase-3 tree with both summary reports and an optional per_corner set."""
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True, exist_ok=True)
    (sta / "pre_pnr_timing.rpt").write_text(
        (step10_header or "# PRE-LAYOUT STA (Step 10) — genuine OpenSTA on the\n"
                          "# synth netlist + SDC, emitted BEFORE PnR.\n")
        + _BODY + (f"STA_BASIS: {step10_basis}\n" if step10_basis else ""))
    (sta / "post_route_timing.rpt").write_text(
        _POST_ROUTE_HEADER + _BODY + "STA_BASIS: POST_ROUTE_SPEF\n")
    if corners:
        pc = sta / "per_corner"
        pc.mkdir(exist_ok=True)
        for name in corners:
            (pc / f"sta_{name}.rpt").write_text(
                _BODY + f"corner {name}\nSTA_BASIS: {corner_basis}\n")
    return tmp_path


def _scoped(project: Path, rels):
    return ERA.scoped_discovery([project / r for r in rels])


def _rules(res):
    return sorted({f.rule for f in res.findings})


def _run_cli(project: Path, *unders, extra=()):
    """Drive `main()` the way the flow does; returns (rc, parsed report)."""
    argv = [sys.executable, str(_AUDIT), str(project), "--mode", "sta"]
    for u in unders:
        argv += ["--under", u]
    argv += list(extra)
    cp = subprocess.run(argv, capture_output=True, text=True)
    doc = {}
    try:
        doc = json.loads(cp.stdout)
    except ValueError:
        pass
    return cp, doc


def _flow_sta_invocations():
    return re.findall(r'"(sta_report_check [^"]*)"',
                      _FLOW.read_text(errors="replace"))


def _unders(cmd: str):
    toks = cmd.split()
    return [toks[i + 1] for i, t in enumerate(toks)
            if t == "--under" and i + 1 < len(toks)]


# ---------------------------------------------------------------------------
# 1 — a POST-ROUTE summary must not be substantiated by PRE-LAYOUT evidence
# ---------------------------------------------------------------------------
def test_post_route_scope_is_not_substantiated_by_pre_layout_corners(tmp_path):
    proj = _project(tmp_path, corners=("SS", "TT", "FF"),
                    corner_basis="PRE_LAYOUT_ESTIMATE")
    with _scoped(proj, [_STEP23_REL]):
        res = ERA._check_sta(proj)
    s = res.summary
    assert s["declared_sta_basis"] == "POST_ROUTE"
    assert s["corner_reports_distinct"] == 3, "the raw corner scan still ran"
    assert s["corner_reports_distinct_by_basis"]["PRE_LAYOUT"] == 3
    assert s["corner_reports_distinct_of_declared_basis"] == 0
    assert s["multi_corner_executed"] is False, (
        "a post-route summary is still substantiated by pre-layout reports: "
        f"{s}")
    assert "STA_CORNER_BASIS_MISMATCH" in _rules(res)
    assert res.passed is False


# vibe-ic — real post-route sign-off evidence OUTSIDE per_corner/ substantiates
# the claim per_corner/ alone cannot. MEASURED (spm x sky130A, 2026-08-07): a
# real run whose own `sta_corner: all analyzed sign-off corners MET` verdict
# passed still failed THIS gate, because `_emit_multi_corner_sta`'s post-route
# call only refreshes per_corner/ when the project stages its own
# `input/pdk/liberty/*.lib` — no default run does — while the real post-route
# multi-corner sign-off (`_emit_mcorner_ocv_sta`, resolved via
# `_resolve_signoff_corner_libs` against the container's OWN PDK corners, no
# staging required) lands in `sta_mcorner_ocv.rpt` instead and per_corner/ is
# never touched again. `mcorner_ocv_stance.json` and `sta_mcorner_ocv.rpt`
# below are byte-for-byte a real run's output (public sky130A grammar).
_REAL_MCORNER_OCV_STANCE = """{
  "signoff_dimension": "multi_corner_ocv_process",
  "setup_process_corner": "SS",
  "hold_process_corner": "FF",
  "multi_process_corner": true,
  "ocv_derate": {"early": 0.95, "late": 1.05, "mode": "flat-OCV"},
  "report": "phase3/stage3/sta/sta_mcorner_ocv.rpt",
  "setup_worst_slack_ns": 4.56,
  "hold_worst_slack_ns": 0.38,
  "violated_corners": [],
  "corner_library_resolution": {
    "axis": "process",
    "liberty_by_corner": {
      "FF": "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v95_ccsnoise.lib",
      "SS": "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_100C_1v60.lib"
    },
    "distinct_library_count": 2,
    "reported_corner_count": 2,
    "collapsed": false,
    "unresolved_corners": [],
    "unresolved_reason": null,
    "degradation_disclosure": null
  },
  "timing_closed_multi_corner": true,
  "disclosure": "Multi-corner OCV sign-off: SETUP @ SS process (slow) + max-RC, HOLD @ FF process (fast) + min-RC, flat-OCV \\u00b15% + recovery/removal/MPW."
}
"""

_REAL_MCORNER_OCV_RPT = """\
=== SETUP corner: process=SS liberty=/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_100C_1v60.lib, SPEF=chip_top.max.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack max 4.56
tns max 0.00
Startpoint: test (input port clocked by clk)
Endpoint: __uuf__._470_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

    Cap    Slew   Delay    Time   Description
-----------------------------------------------------------------------
                   0.00    0.00   clock clk (rise edge)
                          11.00 ^ __uuf__._470_/CLK (sky130_fd_sc_hd__dfxtp_1)
                          10.73   data required time
-----------------------------------------------------------------------
                          10.73   data required time
                          -6.17   data arrival time
-----------------------------------------------------------------------
                           4.56   slack (MET)


SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3
Group                                  Slack
--------------------------------------------
No paths found.

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance max_fanout
=== HOLD corner: process=FF liberty=/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v95_ccsnoise.lib, SPEF=chip_top.min.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack min 0.38
tns max 0.00
Startpoint: __uuf__._506_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: __uuf__._507_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: min

    Cap    Slew   Delay    Time   Description
-----------------------------------------------------------------------
                   0.00    0.00   clock clk (rise edge)
                           0.37 ^ __uuf__._507_/CLK (sky130_fd_sc_hd__dfxtp_1)
                           0.36   data required time
-----------------------------------------------------------------------
                           0.36   data required time
                          -0.73   data arrival time
-----------------------------------------------------------------------
                           0.38   slack (MET)


SIGNOFF_WORST_PATHS_REPORTED path_delay=min group_path_count=3
Group                                  Slack
--------------------------------------------
No paths found.

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance max_fanout
"""


def test_real_post_route_signoff_elsewhere_substantiates_the_claim(tmp_path):
    """THE FIX. Same fixture as the test above (per_corner/ is pre-layout-only)
    PLUS the real evidence a default run actually produces post-route. Must
    now PASS — the claim is substantiated, just not by per_corner/ alone."""
    proj = _project(tmp_path, corners=("SS", "TT", "FF"),
                    corner_basis="PRE_LAYOUT_ESTIMATE")
    rp3 = proj / "reports" / "phase3"
    rp3.mkdir(parents=True, exist_ok=True)
    (rp3 / "mcorner_ocv_stance.json").write_text(_REAL_MCORNER_OCV_STANCE)
    sta_dir = proj / "phase3" / "stage3" / "sta"
    (sta_dir / "sta_mcorner_ocv.rpt").write_text(_REAL_MCORNER_OCV_RPT)
    with _scoped(proj, [_STEP23_REL]):
        res = ERA._check_sta(proj)
    assert "STA_CORNER_BASIS_MISMATCH" not in _rules(res), res.findings
    assert res.passed is True


def test_signoff_basis_corners_elsewhere_returns_zero_without_the_evidence(tmp_path):
    """The helper itself, isolated: no mcorner_ocv/multicorner report at all
    -> 0 SIGNOFF-basis corners, never a guess. This is what keeps the fix from
    being an unconditional escape hatch — remove the evidence added by the
    test above and POST_ROUTE substantiation returns to 0.

    PRE_LAYOUT is NOT asserted at 0 here: `read_records` also reads
    per_corner/ itself (that IS its per-corner sweep), and this fixture's
    per_corner/ genuinely holds 3 PRE_LAYOUT_ESTIMATE reports — 3 is the
    honest count for that basis, not a gap in the helper."""
    proj = _project(tmp_path, corners=("SS", "TT", "FF"),
                    corner_basis="PRE_LAYOUT_ESTIMATE")
    assert ERA._signoff_basis_corners_elsewhere(proj, "POST_ROUTE") == 0
    assert ERA._signoff_basis_corners_elsewhere(proj, "NOT_A_REAL_BASIS") == 0


def test_pre_layout_scope_is_not_substantiated_by_post_route_corners(tmp_path):
    """THE MIRROR. The rule is symmetric or it is a special case."""
    proj = _project(tmp_path, corners=("SS", "TT", "FF"),
                    corner_basis="POST_ROUTE_SPEF")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert res.summary["corner_reports_distinct_of_declared_basis"] == 0
    assert res.summary["multi_corner_executed"] is False
    assert "STA_CORNER_BASIS_MISMATCH" in _rules(res)
    assert res.passed is False


def test_matching_basis_corners_do_substantiate(tmp_path):
    """POSITIVE CONTROL — the split counter must not simply refuse everything."""
    proj = _project(tmp_path, corners=("SS", "TT", "FF"),
                    corner_basis="PRE_LAYOUT_ESTIMATE")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert res.summary["corner_reports_distinct_of_declared_basis"] == 3
    assert res.summary["multi_corner_executed"] is True
    assert "STA_CORNER_BASIS_MISMATCH" not in _rules(res)
    assert res.passed is True, _rules(res)


def test_unstamped_corner_reports_neither_substantiate_nor_fail(tmp_path):
    """THE THIRD TIER. A corner report that discloses no basis does not say
    which side of PnR it came from, so it cannot substantiate a basis-specific
    claim — but it is not a CONTRADICTION either. Fail-safe: warn, do not
    certify, do not hard-fail."""
    proj = _project(tmp_path, corners=("SS", "TT"), corner_basis="")
    # `corner_basis=""` still writes "STA_BASIS: " with no value -> unparsed.
    pc = proj / "phase3" / "stage3" / "sta" / "per_corner"
    for f in pc.glob("*.rpt"):
        f.write_text(f.read_text().replace("STA_BASIS: \n", ""))
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    s = res.summary
    assert s["corner_reports_distinct_by_basis"]["UNDECLARED"] == 2
    assert s["corner_reports_distinct_of_declared_basis"] == 0
    assert s["multi_corner_executed"] is False
    assert "STA_CORNER_BASIS_MISMATCH" not in _rules(res)
    assert "STA_SINGLE_CORNER_ONLY" in _rules(res)
    assert res.passed is True


def test_d1_unscoped_discovery_is_byte_for_byte_the_old_behaviour(tmp_path):
    """DIRECTION-1 GUARD. A caller that declares no scope declares no basis,
    so every basis-aware branch is a no-op and the old counters stand. This
    test holds on the pre-fix tree too."""
    proj = _project(tmp_path, corners=("SS", "TT", "FF"),
                    corner_basis="PRE_LAYOUT_ESTIMATE")
    res = ERA._check_sta(proj)
    assert res.summary["corner_reports_distinct"] == 3
    assert res.summary["multi_corner_executed"] is True
    assert res.passed is True
    assert "STA_CORNER_BASIS_MISMATCH" not in _rules(res)


def test_the_shared_corner_directory_keeps_whichever_basis_wrote_it_first(
        tmp_path, monkeypatch):
    """THE MECHANISM, RUN — not asserted from prose.

    `phase3/stage3/sta/per_corner/` has two producers at two bases, and
    `_emit_multi_corner_sta` skips a corner whose report already exists. So a
    directory the PRE-layout producer filled first stays PRE-layout even when
    the POST-route producer runs afterwards on a routed netlist — which is
    exactly the state test 1 above refuses to certify as post-route evidence.
    """
    import phase3_one_shot_runner as R

    top = "my_core"
    pnr = R._pl.pnr_dir(tmp_path)
    syn = R._pl.synth_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    syn.mkdir(parents=True, exist_ok=True)
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    (pnr / f"{top}_pnr.v").write_text("// routed\n")     # -> POST_ROUTE basis
    (syn / f"{top}_synth.v").write_text("// synth\n")

    out = tmp_path / "phase3" / "stage3" / "sta" / "per_corner"
    out.mkdir(parents=True, exist_ok=True)
    lib = tmp_path / "ss_corner.lib"
    lib.write_text("library(ss){}\n")
    pre_existing = out / f"sta_{R._classify_corner_from_name(lib.name)}.rpt"
    pre_existing.write_text(_BODY + "STA_BASIS: PRE_LAYOUT_ESTIMATE\n")
    before = pre_existing.read_bytes()

    # Confirm the emitter really is on the POST_ROUTE branch for this tree.
    _, _, basis, _ = R._multi_corner_sta_inputs(tmp_path, top)
    assert basis.startswith("POST_ROUTE"), basis

    called = []

    def _never(*a, **kw):                       # pragma: no cover - guard
        called.append(a)
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", _never)

    class _Pdk:
        name, liberty, macro_libs = "testpdk", str(lib), []

    notes: list = []
    ok = R._emit_multi_corner_sta(tmp_path, top, _Pdk(), "c", [lib], out, notes)

    assert ok is True
    assert called == [], "the emitter re-ran a corner whose report existed"
    assert pre_existing.read_bytes() == before
    assert "PRE_LAYOUT_ESTIMATE" in pre_existing.read_text(), (
        "a post-route emitter run rewrote the corner report; the shared "
        "directory would then be self-consistent and this whole class of "
        "defect could not occur")


# ---------------------------------------------------------------------------
# 2 — STA_SINGLE_CORNER_ONLY must mean something
# ---------------------------------------------------------------------------
def test_single_corner_warning_is_silent_on_a_real_pre_layout_corner_run(tmp_path):
    proj = _project(tmp_path, corners=("SS", "TT"),
                    corner_basis="PRE_LAYOUT_ESTIMATE")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_SINGLE_CORNER_ONLY" not in _rules(res), (
        "the advisory fires on a project that DID run multi-corner pre-layout "
        "STA — a warning that is always on is a warning nobody reads")


def test_single_corner_warning_still_fires_with_no_corner_evidence(tmp_path):
    """NEGATIVE CONTROL — silencing it must not have removed it."""
    proj = _project(tmp_path)
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_SINGLE_CORNER_ONLY" in _rules(res)
    assert res.summary["multi_corner_executed"] is False


def test_the_warning_names_the_basis_it_could_not_find(tmp_path):
    proj = _project(tmp_path)
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    msg = [f.message for f in res.findings
           if f.rule == "STA_SINGLE_CORNER_ONLY"][0]
    assert "PRE_LAYOUT" in msg, msg


def test_step10_scope_declares_its_own_corner_directory(tmp_path):
    """The flow must ASK for the evidence the step is named after."""
    cmds = [c for c in _flow_sta_invocations() if "pre_pnr_summary.json" in c]
    assert len(cmds) == 1, cmds
    scopes = _unders(cmds[0])
    assert _STEP10_REL in scopes, scopes
    assert _CORNER_REL in scopes, (
        "step 10 is named 'Pre-layout STA (multi-corner)' and its declared "
        f"scope names no corner directory: {scopes}")


def test_step23_scope_is_deliberately_not_widened_the_same_way():
    """Adding per_corner/ to step 23 would let a PRE-layout corner report's
    negative slack fail the post-route clause — the cross-step contamination
    #778 exists to prevent. Its corner responsibility is on the two dedicated
    gates, not here."""
    cmds = [c for c in _flow_sta_invocations() if "post_route_summary.json" in c]
    assert len(cmds) == 1, cmds
    assert _unders(cmds[0]) == [_STEP23_REL], _unders(cmds[0])


def test_widening_step10_does_not_buy_a_green(tmp_path):
    """A VIOLATED corner report inside the widened scope must FAIL step 10.
    The scope is the perfect instrument for buying a green; it may not."""
    proj = _project(tmp_path, corners=("TT",))
    pc = proj / "phase3" / "stage3" / "sta" / "per_corner"
    (pc / "sta_SS.rpt").write_text(
        _VIOLATED_BODY + "corner SS\nSTA_BASIS: PRE_LAYOUT_ESTIMATE\n")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_REAL_VIOLATION_FOUND" in _rules(res)
    assert res.passed is False


# ---------------------------------------------------------------------------
# 3 — "I found a file" must mean a file that can be read
# ---------------------------------------------------------------------------
def test_a_dangling_symlink_is_not_readable_evidence(tmp_path):
    """The `edge_llm_accel` shape: a per-step mirror pointing at a canonical
    path that was never written. It resolves to exactly the scope root, so it
    IS in scope — and must be named, not silently counted."""
    proj = tmp_path
    sta = proj / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    step = proj / "steps" / "10_pre_layout_sta_multi_corner"
    step.mkdir(parents=True)
    (step / "pre_pnr_timing.rpt").symlink_to(sta / "pre_pnr_timing.rpt")

    with _scoped(proj, [_STEP10_REL]):
        res = ERA._check_sta(proj)
    s = res.summary
    assert s["files_found"] == 1, "the discovery contract changed"
    assert s["readable_files"] == 0, (
        f"a summary claims readable evidence it does not have: {s}")
    assert s["unreadable_files"] == 1
    assert "STA_REPORT_NOT_READABLE" in _rules(res)
    assert res.passed is False
    named = [f.file for f in res.findings if f.rule == "STA_REPORT_NOT_READABLE"]
    assert named and named[0].endswith("pre_pnr_timing.rpt"), named


def test_an_unreadable_report_beside_a_good_one_does_not_pass(tmp_path):
    """THE GATING PROPERTY, isolated. In the fixture above the report is
    missing every other way too, so `passed is False` there proves nothing
    about the unreadable path. Here the scope holds one PERFECT report and one
    that cannot be opened: everything else the gate measures is green, so only
    `not unreadable` can hold the verdict red. (A mutation run caught this —
    deleting `and not unreadable` from the verdict turned nothing red.)"""
    proj = _project(tmp_path)
    sta = proj / "phase3" / "stage3" / "sta"
    (sta / "pre_pnr_timing_mirror.rpt").symlink_to(sta / "never_written.rpt")

    with _scoped(proj, ["phase3/stage3/sta"]):
        res = ERA._check_sta(proj)
    s = res.summary
    assert s["files_found"] == 3 and s["readable_files"] == 2
    assert s["has_wns_tns"] and s["has_setup_hold"] and s["tool_authentic"]
    assert s["any_verdict_determined"] and not s["real_violation_found"]
    assert "STA_REPORT_NOT_READABLE" in _rules(res)
    assert res.passed is False, (
        "every measured property is green and one discovered path could not "
        f"be opened, yet the gate certified the step: {s}")


def test_a_readable_report_still_reads_as_readable(tmp_path):
    """NEGATIVE CONTROL — the counter must not read 0 for everyone."""
    proj = _project(tmp_path)
    with _scoped(proj, [_STEP10_REL]):
        res = ERA._check_sta(proj)
    assert res.summary["readable_files"] == res.summary["files_found"] == 1
    assert "STA_REPORT_NOT_READABLE" not in _rules(res)


def test_a_symlink_loop_under_a_scope_does_not_kill_the_program(tmp_path):
    """`Path.resolve()` raises RuntimeError — NOT OSError — on a symlink loop
    on Python 3.12. The guard that stood here was `except OSError`, so the
    program died with a traceback and produced no verdict at all."""
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "sta_a.rpt").symlink_to(sta / "sta_b.rpt")
    (sta / "sta_b.rpt").symlink_to(sta / "sta_a.rpt")

    cp, doc = _run_cli(tmp_path, "phase3/stage3/sta")
    assert "Traceback" not in cp.stderr, cp.stderr[-800:]
    assert "RuntimeError" not in cp.stderr, cp.stderr[-800:]
    assert doc, "no JSON verdict was produced"
    assert doc["passed"] is False
    assert cp.returncode == 1


def test_the_landed_drc_gate_on_an_unopenable_certificate_still_fires(tmp_path):
    """CROSS-CHECK. Making unreadable paths undiscoverable would have deleted
    #776's gate: measured, it flipped `edge_llm_accel --mode drc` from rc 1 to
    rc 0 — a green DRC verdict over a sign-off certificate that does not
    exist. This pins that it did not happen."""
    proj = tmp_path / "proj"
    steps = proj / "steps" / "31_physical_verification"
    steps.mkdir(parents=True)
    (proj / "reports").mkdir()
    (proj / "reports" / "drc_router.rpt").write_text(
        "[INFO drt-0012] OpenROAD detailed_route\n"
        "spacing / width / density / antenna / via / enclosure checked\n"
        "violation count summary: 0 violation(s) found\n" + _PAD)
    (steps / "drc_signoff.rpt").symlink_to(proj / "reports" / "gone.rpt")
    res = ERA._check_drc(proj)
    assert "DRC_REPORT_NOT_READABLE" in [f.rule for f in res.findings
                                         if f.severity == "ERROR"]
    assert res.passed is False


# ---------------------------------------------------------------------------
# 4 — step 10 must not certify a report that self-discloses as post-PnR-derived
# ---------------------------------------------------------------------------
def test_step10_refuses_a_report_that_says_it_came_from_the_post_pnr_run(tmp_path):
    proj = _project(tmp_path, step10_header=_AUTOSTAGED_HEADER,
                    step10_basis="")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_BASIS_CONTRADICTS_SCOPE" in _rules(res), _rules(res)
    assert res.summary["reports_contradicting_declared_basis"] == 1
    assert res.passed is False


def test_the_predicate_keys_on_the_disclosure_not_the_version_string(tmp_path):
    """The literal `v1.6.36` must be irrelevant: the check has to survive the
    emitter's next version bump and has to fire on any other producer that
    discloses the same thing."""
    moved = _AUTOSTAGED_HEADER.replace("v1.6.36", "v9.9.99")
    proj = _project(tmp_path, step10_header=moved, step10_basis="")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_BASIS_CONTRADICTS_SCOPE" in _rules(res)

    other = ("# staged from the post-route sign-off report by a different\n"
             "# producer entirely\n")
    proj2 = _project(tmp_path / "b", step10_header=other, step10_basis="")
    with _scoped(proj2, [_STEP10_REL, _CORNER_REL]):
        res2 = ERA._check_sta(proj2)
    assert "STA_BASIS_CONTRADICTS_SCOPE" in _rules(res2)

    assert "1.6.36" not in ERA._STA_DERIVATION_VERBS
    assert "1.6.36" not in "".join(ERA._STA_POST_LAYOUT_SOURCES)


def test_a_stamped_post_route_report_under_a_pre_layout_scope_is_refused(tmp_path):
    """The stamp is authoritative; the prose predicate is the fallback for
    producers that write no stamp."""
    proj = _project(tmp_path, step10_basis="POST_ROUTE_SPEF")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_BASIS_CONTRADICTS_SCOPE" in _rules(res)
    msg = [f.message for f in res.findings
           if f.rule == "STA_BASIS_CONTRADICTS_SCOPE"][0]
    assert "STA_BASIS stamp says POST_ROUTE" in msg, msg
    assert res.passed is False, (
        "an ERROR finding was emitted and the gate still returned rc 0")


def test_step23s_own_post_route_header_does_not_trip_the_predicate(tmp_path):
    """NEGATIVE CONTROL. `post_route_timing.rpt`'s header names "post-route"
    and "the estimate-based report_checks" — a prose screen looking for either
    token alone would fire on the report the step is supposed to sign off."""
    proj = _project(tmp_path)
    with _scoped(proj, [_STEP23_REL]):
        res = ERA._check_sta(proj)
    assert "STA_BASIS_CONTRADICTS_SCOPE" not in _rules(res), _rules(res)
    assert res.summary["reports_contradicting_declared_basis"] == 0
    assert res.passed is True, _rules(res)


def test_a_genuine_pre_layout_report_is_still_certified(tmp_path):
    """POSITIVE CONTROL — #779's own artefact must keep passing."""
    proj = _project(tmp_path,
                    step10_header="# PRE-LAYOUT STA (Step 10) — genuine "
                                  "OpenSTA on the synth\n# netlist + SDC, "
                                  "emitted BEFORE PnR.\n# corner source: "
                                  "sta_SS.rpt\n",
                    step10_basis="PRE_LAYOUT_ESTIMATE")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert "STA_BASIS_CONTRADICTS_SCOPE" not in _rules(res), _rules(res)
    assert res.passed is True, _rules(res)


def test_an_unscoped_caller_never_sees_the_provenance_predicate(tmp_path):
    """DIRECTION-1 GUARD for item 4: no declared basis, no contradiction."""
    proj = _project(tmp_path, step10_header=_AUTOSTAGED_HEADER,
                    step10_basis="")
    res = ERA._check_sta(proj)
    assert "STA_BASIS_CONTRADICTS_SCOPE" not in _rules(res)
    assert res.summary["declared_sta_basis"] is None


# ---------------------------------------------------------------------------
# the basis is read from the DECLARED scope, not from where the run happens
# to be checked out
# ---------------------------------------------------------------------------
def test_the_project_directory_name_cannot_decide_the_basis(tmp_path):
    """`_SCOPE_ROOTS` holds resolved ABSOLUTE paths. Matching tokens against
    those lets the enclosing directory name answer the question — a run
    checked out under `post_route_backup/` made a PRE_LAYOUT scope ambiguous
    and silently degraded it to "no basis declared", which switches every
    basis-aware branch off. Found by this test suite's own tmp_path names."""
    proj = _project(tmp_path / "post_route_backup" / "pre_layout_archive")
    with _scoped(proj, [_STEP10_REL, _CORNER_REL]):
        res = ERA._check_sta(proj)
    assert res.summary["declared_sta_basis"] == "PRE_LAYOUT", (
        "the enclosing directory names decided the basis instead of the "
        f"declared scope: {res.summary}")
    with _scoped(proj, [_STEP23_REL]):
        res23 = ERA._check_sta(proj)
    assert res23.summary["declared_sta_basis"] == "POST_ROUTE"
