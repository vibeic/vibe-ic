"""A REUSED corner report must not be published under a basis it does not carry.

MEASURED DEFECT (a CPU core on a closed-source PDK, plugin v1.9.79; the
mechanism is chip- and PDK-AGNOSTIC and is reproduced here on synthetic files
with no PDK at all).

`_emit_multi_corner_sta` is called TWICE into the SAME `per_corner/` directory:
once for the PRE-layout multi-corner STA and again, after PnR, for the
post-route one. Its reuse guard is

    rpt = out_dir / f"sta_{corner}.rpt"
    if rpt.is_file():
        any_emitted = True
        continue

— keyed on the FILENAME and blind to the report's own `STA_BASIS` stamp. The
first call's files are always on disk when the second runs, so the second call
emits NOTHING, returns True, and the run appends

    "multi-corner STA basis=POST_ROUTE_SPEF: routed netlist <top>_pnr.v +
     extracted parasitics — post-route multi-corner timing …"

over a directory whose three reports each stamp `STA_BASIS:
PRE_LAYOUT_ESTIMATE`. Observed on the affected run, calling the SHIPPED function
against the real project tree:

    RESOLVED BASIS      : POST_ROUTE_SPEF
    EXISTING IN out_dir : ['sta_FF.rpt', 'sta_SS.rpt', 'sta_TT.rpt']
    _emit_multi_corner_sta RETURNED: True
    AFTER, out_dir      : ['sta_FF.rpt', 'sta_SS.rpt', 'sta_TT.rpt']
       sta_FF.rpt: STA_BASIS: PRE_LAYOUT_ESTIMATE   <- all three unchanged
    real  0m1.989s   (the same call into an EMPTY dir emitted all three
                      POST_ROUTE_SPEF reports in 2 s — nothing prevented it)

That matters because `eda_report_audit` and
`sta_corner_record_completeness_check` consume this tree as the multi-corner
SIGN-OFF claim, and the affected run's post-route SS corner was 1.35 ns worse
than the pre-layout report standing in for it — the mislabel reads OPTIMISTIC,
which is the direction that produces a false certificate.

SCOPE OF THE FIX, deliberately narrow: it changes NO file that is written and NO
return value. Reuse is still reuse; a stale report is never silently deleted or
overwritten, and no verdict can move. It only stops the run CLAIMING a basis its
reports do not carry. The reverse cases below pin that narrowness — in
particular that a report whose basis AGREES produces no disclosure, so this
cannot become a warning that fires on every reuse and is therefore ignored.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

TOP = "my_core"
# Names chosen so `_classify_corner_from_name` resolves each to a distinct
# corner (it matches on "_ss" / "_ff" / "typ"). Generic — no PDK, no vendor.
CORNERS = {"corner_ss.lib": "SS", "corner_ff.lib": "FF", "corner_typ.lib": "TT"}


def _mk_project(project: Path, *, routed=True, synth=True, spef=True):
    """Minimal tree. `routed + spef` resolves the basis to POST_ROUTE_SPEF."""
    pnr = R._pl.pnr_dir(project)
    syn = R._pl.synth_dir(project)
    pnr.mkdir(parents=True, exist_ok=True)
    syn.mkdir(parents=True, exist_ok=True)
    (pnr / "constraint.sdc").write_text(
        "create_clock -period 10 [get_ports clk]\n")
    if routed:
        (pnr / f"{TOP}_pnr.v").write_text("// routed\n")
    if synth:
        (syn / f"{TOP}_synth.v").write_text("// synth\n")
    if spef:
        ex = project / "phase3/stage3/extracted"
        ex.mkdir(parents=True, exist_ok=True)
        (ex / f"{TOP}.spef").write_text("*SPEF\n")
    return project


def _mk_libs(project: Path):
    libdir = project / "libs"
    libdir.mkdir(parents=True, exist_ok=True)
    out = []
    for name in CORNERS:
        p = libdir / name
        p.write_text("/* liberty */\n")
        out.append(p)
    return sorted(out)


def _stamp(rpt: Path, basis: str):
    """Write a corner report stamped exactly as the producer stamps its own."""
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text(
        "Startpoint: a\nEndpoint: b\n   1.00   slack (MET)\n"
        "tns max 0.00\nwns max 0.00\n"
        f"STA_BASIS: {basis}\n"
        "STA_BASIS_NOTE: fixture\n")


def _run(project: Path, out_dir: Path, notes=None, emitter=None):
    """Call the producer with the container hop stubbed out.

    `_docker_exec` is replaced so the test never needs Docker or OpenSTA. The
    default stub FAILS the tool call, which is the strictest setting for the
    forward cases: nothing the stub does can create a report, so any disclosure
    must come from the reuse accounting rather than from a freshly written file.
    """
    notes = [] if notes is None else notes
    calls = []

    def _fake_docker_exec(container, cmd, *a, **kw):
        calls.append(cmd)
        if emitter is not None:
            emitter(cmd)
        return (0, "", "") if emitter is not None else (1, "", "stub: no tool")

    orig = R._docker_exec
    R._docker_exec = _fake_docker_exec
    try:
        ok = R._emit_multi_corner_sta(
            project, TOP, _Pdk(), "no-such-container",
            _mk_libs(project), out_dir, notes)
    finally:
        R._docker_exec = orig
    return ok, notes, calls


class _Pdk:
    macro_libs: list = []


def _joined(notes):
    return "\n".join(notes)


# ── FORWARD: fail against the byte-identical pre-fix file, on the WRONG ANSWER ─
# These assert on the RUN'S OWN NOTES, not on the existence of a new symbol, so
# pre-fix they fail because the answer is wrong rather than because a name is
# missing.

def test_reused_prelayout_reports_are_not_published_as_post_route(tmp_path):
    """THE DEFECT. Inputs resolve POST_ROUTE_SPEF; the directory already holds
    PRE_LAYOUT_ESTIMATE reports from the earlier pre-layout call. The run must
    not leave "post-route multi-corner timing" as its only word on them."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    for corner in CORNERS.values():
        _stamp(out_dir / f"sta_{corner}.rpt", "PRE_LAYOUT_ESTIMATE")

    _, _, basis, _ = R._multi_corner_sta_inputs(project, TOP)
    assert basis == "POST_ROUTE_SPEF", "fixture no longer reproduces the setup"

    ok, notes, calls = _run(project, out_dir)
    assert ok is True
    assert not calls, "reuse path must not invoke the tool"

    text = _joined(notes)
    assert "PRE_LAYOUT_ESTIMATE" in text, (
        "the run reused three PRE_LAYOUT_ESTIMATE reports while announcing "
        "basis=POST_ROUTE_SPEF and never said so — a pre-layout number is "
        "standing in for post-route sign-off evidence")
    assert "REUSED" in text


def test_disclosure_names_every_stale_corner_report(tmp_path):
    """All three corners are stale, so all three must be named — a disclosure
    that mentions one and silently drops two is not a disclosure."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    for corner in CORNERS.values():
        _stamp(out_dir / f"sta_{corner}.rpt", "PRE_LAYOUT_ESTIMATE")

    _, notes, _ = _run(project, out_dir)
    text = _joined(notes)
    for corner in CORNERS.values():
        assert f"sta_{corner}.rpt" in text, f"sta_{corner}.rpt not disclosed"


def test_unstamped_reused_report_is_unverified_not_assumed_to_agree(tmp_path):
    """FAIL-SAFE. A report with no STA_BASIS cannot be confirmed to match, and
    "unknown" must not be silently rendered as "agrees"."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sta_SS.rpt").write_text("Startpoint: a\nwns max 0.00\n")
    _stamp(out_dir / "sta_FF.rpt", "POST_ROUTE_SPEF")
    _stamp(out_dir / "sta_TT.rpt", "POST_ROUTE_SPEF")

    _, notes, _ = _run(project, out_dir)
    text = _joined(notes)
    assert "sta_SS.rpt" in text
    assert "UNVERIFIED" in text.upper()


# ── REVERSE: must STILL pass. These pin the fix's narrowness. ─────────────────
# None of them references the new helper, so each is meaningful against the
# pre-fix tree too: together they prove the change did not tighten a filter
# until the count reached zero, and did not alter what gets written.

def test_matching_basis_produces_NO_staleness_disclosure(tmp_path):
    """THE LOAD-BEARING REVERSE CASE. Reports whose stamp AGREES with the
    resolved basis are ordinary, correct reuse. If this fired here the warning
    would appear on every re-run and be trained away, which would swallow the
    real defect underneath."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    for corner in CORNERS.values():
        _stamp(out_dir / f"sta_{corner}.rpt", "POST_ROUTE_SPEF")

    ok, notes, calls = _run(project, out_dir)
    assert ok is True
    assert not calls
    text = _joined(notes)
    assert "REUSED" not in text, (
        "agreeing reports must not be reported as stale")
    assert "DISAGREES" not in text


def test_empty_out_dir_still_emits_every_corner_report(tmp_path):
    """Behaviour on the normal path is untouched: an empty directory still gets
    one report per corner, written by the tool, with the basis stamped in."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _emit(cmd):
        # Mimic the deck: the tcl names the report it writes.
        for corner in CORNERS.values():
            if f"sta_{corner}.tcl" in cmd:
                _stamp(out_dir / f"sta_{corner}.rpt", "POST_ROUTE_SPEF")

    ok, notes, calls = _run(project, out_dir, emitter=_emit)
    assert ok is True
    assert len(calls) == len(CORNERS), "one tool invocation per corner"
    for corner in CORNERS.values():
        assert (out_dir / f"sta_{corner}.rpt").is_file()
    assert "REUSED" not in _joined(notes)


def test_basis_line_still_reports_the_resolved_basis(tmp_path):
    """The run must still say which basis its inputs resolve to — the fix
    qualifies that line, it does not remove the information."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    for corner in CORNERS.values():
        _stamp(out_dir / f"sta_{corner}.rpt", "PRE_LAYOUT_ESTIMATE")

    _, notes, _ = _run(project, out_dir)
    text = _joined(notes)
    assert "POST_ROUTE_SPEF" in text
    assert f"{TOP}_pnr.v" in text


def test_reuse_never_deletes_or_rewrites_the_existing_report(tmp_path):
    """The fix is disclosure-only: a stale report keeps its exact bytes, so no
    evidence is destroyed and no verdict can move because of this change."""
    project = _mk_project(tmp_path)
    out_dir = project / "phase3/stage3/sta/per_corner"
    for corner in CORNERS.values():
        _stamp(out_dir / f"sta_{corner}.rpt", "PRE_LAYOUT_ESTIMATE")
    before = {p.name: p.read_bytes() for p in out_dir.glob("sta_*.rpt")}

    _run(project, out_dir)

    after = {p.name: p.read_bytes() for p in out_dir.glob("sta_*.rpt")}
    assert after == before, "reuse must be byte-preserving"


def test_prelayout_run_with_prelayout_reports_is_silent(tmp_path):
    """The pre-layout call itself (no routed netlist) reusing its own
    pre-layout reports is correct and must stay quiet."""
    project = _mk_project(tmp_path, routed=False, spef=False)
    out_dir = project / "phase3/stage3/sta/per_corner"
    for corner in CORNERS.values():
        _stamp(out_dir / f"sta_{corner}.rpt", "PRE_LAYOUT_ESTIMATE")

    _, _, basis, _ = R._multi_corner_sta_inputs(project, TOP)
    assert basis == "PRE_LAYOUT_ESTIMATE"

    _, notes, _ = _run(project, out_dir)
    assert "REUSED" not in _joined(notes)
