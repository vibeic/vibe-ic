"""A Tcl `catch` cannot catch a SIGSEGV, and the runner could not tell a tool
CRASH from a tool ERROR.

MEASURED, twice, on independent runs of the same cell (WNS -12.258 and
-12.771, 1081 violating endpoints both times): detailed routing COMPLETED and
converged —

    [INFO DRT-0199]   Number of violations = 0.
    [INFO DRT-0198] Complete detail routing.

— and OpenROAD was then killed by Signal 11 inside the post-route DRV-repair
loop, several hundred lines BEFORE `write_def routed.def`. That loop's every
step is wrapped in `if {[catch {...} e]} { puts "..._NONFATAL: $e" }`, a guard
that is structurally incapable of guarding: the signal kills the process, so
the interpreter never reaches the failure branch. `set -o pipefail` surfaced
the death to the runner as rc=139, and the runner's whole verdict was

    pnr FAIL  rc=139 log_tail=<2000 characters of transcript>

which reads as "routing failed". Routing did not fail. Seven downstream steps
then failed on the missing routed.def, and nothing in the verdict said why.

The checkpoint `routed_preantenna.def` survived the crash, and the flow's own
note said to "resume from the checkpoint; a from-scratch re-run is NOT
required" — advice with no mechanism behind it: there was no resume flag and
no resume code path anywhere in the runner.

WHAT THESE TESTS PIN, and deliberately how: they assert OBSERVABLE PROPERTIES
of the step result and of the commands the runner issues, not the shape of any
particular implementation. A different correct fix — different function names,
different message wording, a differently-built resume script — passes them.
Every test below FAILS against the byte-identical pre-fix runner EXCEPT the
two marked as over-breadth guards and the one that measures the signal path
itself — those pass on both sides by design, and exist to stop an
over-broad fix from calling every non-zero exit a crash.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")

tclsh = shutil.which("tclsh")

# The harness must run identically against the PRE-fix runner, or the
# negative control degenerates into "the new symbol does not exist yet".
# Every fixture below is written in terms of the tool's own output, with
# the breadcrumb defaulting to the literal the fix emits.
_MARKER = getattr(mod, "_PNR_STAGE_MARKER", "PNR_STAGE:")


# ---------------------------------------------------------------------------
# Fixtures — a PnR project and a fake OpenROAD that can die on a signal
# ---------------------------------------------------------------------------
def _sky130_pdk():
    return mod.PdkConfig(
        name="sky130A",
        liberty="/placeholder/sky130_fd_sc_hd__tt.lib",
        tech_lef="/placeholder/sky130_fd_sc_hd.tlef",
        cell_lef="/placeholder/sky130_fd_sc_hd.lef",
        cell_gds="/placeholder/sky130_fd_sc_hd.gds",
        site="unithd", drc_deck="/placeholder/x.drc", metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        tapcell_distance_um=14.0)


def _build_project(tmp_path: Path, top: str, n_cells: int = 300) -> Path:
    project = tmp_path / "proj"
    synth = mod._pl.synth_dir(project)
    synth.mkdir(parents=True, exist_ok=True)
    lines = [f"module {top}(input clk, input a, output y);"]
    for i in range(n_cells):
        lines.append(f"sky130_fd_sc_hd__inv_1 u{i} (.A(n{i}), .Y(n{i + 1}));")
    lines.append("endmodule")
    (synth / f"{top}_synth.v").write_text("\n".join(lines))
    return project


_PG_OK = "PG_NET_OWNERSHIP_AUDIT: total=600 no_net=0 masters=\n"

# The router's own completion evidence, followed by MORE than the 2000
# characters the pre-fix message quoted as `log_tail` — exactly as on the real
# run, where the completion line sat ~1800 lines above the crash. A verdict
# that only quotes the tail therefore cannot accidentally carry the proof that
# routing finished; it has to be ASSERTED by the runner.
_ROUTE_OK = (
    "[INFO DRT-0199]   Number of violations = 0.\n"
    "[INFO DRT-0198] Complete detail routing.\n"
    + "[INFO DRT-0267] cpu time = 01:27:42, elapsed = 00:10:56\n" * 60
)

_CRASH_TAIL = (
    "[INFO RSZ-0094] Found 1081 endpoints with setup violations.\n"
    "[INFO RSZ-0099] Repairing 1081 out of 1081 (100.00%) violating "
    "endpoints...\n"
    "       0* |       0 |       0 |        0 |      0 |     0 |    +0.0% |  "
    "-12.771 |    -6377.6 |    -8253.8 |   1081 | u123/D\n"
    "Signal 11 received\n"
    "Stack trace:\n 0# 0x00000000020E1F75 in openroad\n"
)


# The same converged route, but the tool RETURNED an error instead of dying.
# A log that carries a segfault trace while the process exits 1 is not a state
# any tool produces, so the ordinary-error fixture must not borrow one — else
# the over-breadth guard below passes on a quoted string rather than on the
# runner's own classification.
_ERROR_TAIL = (
    "[ERROR RSZ-0089] Could not find a resistance value for any corner.\n"
    "Error: pnr.tcl, 1182 RSZ-0089\n"
)


# A death whose transcript says NOTHING about a signal. OpenROAD's crash
# handler printed a trace on the two measured runs, but a handler is not
# guaranteed to run — SIGKILL never reaches one, and a crash inside the
# handler's own path prints nothing either. The signal has to be read from the
# EXIT STATUS, which is always there, not scraped out of the transcript, which
# is not. This fixture is what separates the two.
_SILENT_TAIL = (
    "[INFO RSZ-0094] Found 1081 endpoints with setup violations.\n"
    "[INFO RSZ-0099] Repairing 1081 out of 1081 (100.00%) violating "
    "endpoints...\n"
)


def _crash_log(stage: str, *, signal_death: bool = True,
               tool_printed_trace: bool = True) -> str:
    """An OpenROAD transcript that converged in detailed route and then either
    died inside `stage` — with or without its crash handler getting a word in
    — or returned an ordinary error there."""
    tail = ((_CRASH_TAIL if tool_printed_trace else _SILENT_TAIL)
            if signal_death else _ERROR_TAIL)
    return (f"{_MARKER} detailed_route\n"
            + _ROUTE_OK
            + (f"{_MARKER} {stage}\n"
               if stage != "detailed_route" else "")
            + tail)


def _drive(tmp_path, monkeypatch, *, first_rc, stage,
           write_checkpoint=True, resume_rc=0, resume_writes_def=True,
           tool_printed_trace=True, top="widget"):
    """Run step_pnr against a fake OpenROAD.

    The FIRST `openroad` invocation writes the route checkpoint and the log,
    then returns `first_rc` WITHOUT writing the final DEF — the measured
    shape of a mid-tcl death after a completed route. Any SECOND invocation
    is whatever the runner decided to do about that; the fake records the
    script it was pointed at so the test can inspect it.
    """
    project = _build_project(tmp_path, top)
    calls: list = []
    # The measured crash happened on an OpenROAD the runner's own probe
    # declared CAPABLE of post-route SPEF repair (image 0.2.58 probed capable
    # and took Signal 11 anyway). That is the configuration under test, so the
    # probe is pinned to it rather than left to whatever the test host has.
    monkeypatch.setattr(mod, "_openroad_supports_postroute_spef_repair",
                        lambda *_a, **_k: True)

    def fake_docker_exec(container, cmd, timeout=None, **kw):
        if "openroad -no_init" in cmd:
            out_dir = mod._pl.pnr_dir(project)
            out_dir.mkdir(parents=True, exist_ok=True)
            script = None
            for tok in cmd.split():
                if tok.endswith(".tcl"):
                    script = Path(tok)
            body = script.read_text() if script and script.is_file() else ""
            calls.append({"script": str(script), "body": body})
            if len(calls) == 1:
                if write_checkpoint:
                    (out_dir / "floorplan.def").write_text("DESIGN x ;\n")
                    (out_dir / "placed.def").write_text("DESIGN x ;\n")
                    (out_dir / "post_cts.def").write_text("DESIGN x ;\n")
                    (out_dir / "post_hold.def").write_text("DESIGN x ;\n")
                    (out_dir / "routed_preantenna.def").write_text(
                        "VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
                log = _crash_log(stage, signal_death=first_rc == 139,
                                 tool_printed_trace=tool_printed_trace)
                (out_dir / "openroad.log").write_text(log)
                return (first_rc, log, "")
            # second and later invocations
            log = _ROUTE_OK + _PG_OK
            if resume_writes_def:
                (out_dir / "routed.def").write_text(
                    "VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
                (out_dir / f"{top}.def").write_text(
                    "VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
            lp = kw.get("log_path")
            if lp:
                Path(lp).write_text(log)
            return (resume_rc, log, "")
        return (0, "", "")

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod.step_pnr(project, top, _sky130_pdk(), "iic", "200x200", 0.30)
    return res, calls, project


def _says_signal(text: str) -> bool:
    t = (text or "").lower()
    return "sigsegv" in t or "signal 11" in t


# ---------------------------------------------------------------------------
# THE SIGNAL PATH — measured, not assumed
# ---------------------------------------------------------------------------
def test_a_process_killed_by_a_signal_reaches_the_runner_as_128_plus_n():
    """The premise the whole fix rests on, EXERCISED rather than described: a
    real process that dies on SIGSEGV inside the exact pipeline shape
    `_docker_exec` builds (`<tool> 2>&1 | tee <log>` under `set -o pipefail`)
    is reported to the caller as 128+11.

    This one is true of the pre-fix runner too — that is the point. The signal
    was always arriving as 139; nothing was reading it as a signal."""
    inner = "bash -c 'kill -SEGV $$' 2>&1 | tee /dev/null"
    wrapped = mod._tool_status_not_the_log_sinks(inner)
    assert wrapped.startswith("set -o pipefail")
    rc = subprocess.run(["bash", "-lc", wrapped],
                        capture_output=True).returncode
    assert rc == 139, "a SIGSEGV in the tee pipeline must surface as 128+11"


def test_a_watchdog_kill_is_not_reported_as_a_tool_crash(
        tmp_path, monkeypatch):
    """OVER-BREADTH GUARD — passes before AND after. The watchdog's stall
    sentinel also lands in the 128..255 band, but it is the RUNNER killing the
    tool, not the tool crashing. Calling it a segfault would send the next
    reader hunting an OpenROAD bug that is not there."""
    import _watchdog as W
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=W.RC_STALLED,
                            stage="postroute_drv_repair")
    assert res.status != "PASS"
    assert not _says_signal(res.detail or "")
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# THE VERDICT — what the next reader is told
# ---------------------------------------------------------------------------
def test_signal_death_verdict_names_the_signal_not_just_the_exit_code(
        tmp_path, monkeypatch):
    """`rc=139` is not a diagnosis. The verdict has to name what killed the
    tool, or the reader has to know the 128+N convention by heart to even
    start.

    Driven with a transcript that says NOTHING about a signal, deliberately:
    quoting a log tail that happens to contain the tool's own stack trace is
    not classification, and a verdict built that way says nothing at all when
    the tool dies without printing one."""
    res, _calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                             stage="detailed_route",
                             tool_printed_trace=False)
    assert res.status != "PASS"
    assert not _says_signal(_crash_log("detailed_route",
                                       tool_printed_trace=False)), \
        "fixture invalid: the transcript must not mention the signal"
    assert _says_signal(res.detail), \
        f"verdict does not name the signal: {res.detail[:400]!r}"


def test_signal_death_verdict_does_not_present_a_completed_route_as_failed(
        tmp_path, monkeypatch):
    """The router printed `Complete detail routing` with 0 violations. A
    verdict that lets the reader conclude routing failed costs exactly the
    hours this defect cost. The completion has to be ASSERTED — quoting a
    2000-character tail that no longer contains the line does not count."""
    res, _calls, _p = _drive(tmp_path, monkeypatch,
                             first_rc=139, stage="detailed_route")
    d = res.detail or ""
    assert "Complete detail routing" not in _CRASH_TAIL[-2000:], \
        "fixture invalid: the completion line must be outside the quoted tail"
    assert ("Complete detail routing" in d
            or "routing SUCCEEDED" in d
            or "route completed" in d.lower()), \
        f"verdict does not state that routing completed: {d[:400]!r}"


def test_signal_death_verdict_names_the_surviving_checkpoint(
        tmp_path, monkeypatch):
    """When the runner does NOT resume, the checkpoint that survived the crash
    has to be named in the verdict — a path the reader can act on, instead of
    advice pointing at a mechanism they then have to go looking for."""
    res, calls, project = _drive(tmp_path, monkeypatch,
                                 first_rc=139, stage="detailed_route")
    ckpt = mod._pl.pnr_dir(project) / "routed_preantenna.def"
    assert ckpt.is_file()
    assert len(calls) == 1, "a load-bearing crash must not be resumed past"
    assert str(ckpt) in (res.detail or ""), \
        f"verdict does not name the checkpoint: {(res.detail or '')[:400]!r}"


def test_an_ordinary_nonzero_exit_is_not_dressed_up_as_a_crash(
        tmp_path, monkeypatch):
    """Over-breadth guard (passes before AND after): the same log, the same
    missing DEF, but the tool RETURNED 1 instead of dying. Nothing may claim a
    signal killed it."""
    res, calls, _p = _drive(tmp_path, monkeypatch,
                            first_rc=1, stage="postroute_drv_repair")
    assert res.status != "PASS"
    assert not _says_signal(res.detail or ""), \
        f"an ordinary error exit was described as a crash: {res.detail[:300]!r}"
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# THE RESUME — the mechanism the advice promised
# ---------------------------------------------------------------------------
def test_crash_in_a_best_effort_stage_resumes_from_the_checkpoint(
        tmp_path, monkeypatch):
    """The headline property, and the one the pre-fix runner cannot satisfy at
    all: when the tool is killed in a stage pnr.tcl itself declares
    best-effort and a route checkpoint survives, the runner must finish the
    job FROM THE CHECKPOINT — not re-run from scratch, and not give up.

    Asserted on what the runner DOES (a second tool invocation, pointed at a
    script that loads the checkpoint and does not rebuild the design), not on
    how it builds it."""
    res, calls, project = _drive(tmp_path, monkeypatch,
                                 first_rc=139, stage="postroute_drv_repair")
    ckpt = mod._pl.pnr_dir(project) / "routed_preantenna.def"
    assert len(calls) == 2, \
        "no second attempt was made — the checkpoint was left unused"
    body = calls[1]["body"]
    assert f"read_def {ckpt}" in body, \
        "the second attempt does not load the surviving checkpoint"
    assert "initialize_floorplan" not in body, \
        "the second attempt rebuilds the floorplan — that is a from-scratch " \
        "re-run, which is exactly what the checkpoint exists to avoid"
    assert "read_verilog" not in body, \
        "the second attempt re-elaborates the netlist instead of reading the " \
        "routed database"
    assert res.status != "FAIL"


def test_the_resumed_run_does_not_repeat_the_stage_that_killed_it(
        tmp_path, monkeypatch):
    """Resuming into the same crash is not a resume. The stage the tool died
    in must be absent from the script the second attempt runs, and its absence
    must be visible in the script rather than inferred."""
    _res, calls, _p = _drive(tmp_path, monkeypatch,
                             first_rc=139, stage="postroute_drv_repair")
    first, second = calls[0]["body"], calls[1]["body"]
    assert first.count("SDR_DRV_PASS") == 2, \
        "fixture invalid: the emitted pnr.tcl should carry both DRV loops"
    assert second.count("SDR_DRV_PASS") == 1, \
        "the stage that crashed was re-emitted into the resumed script"
    assert "PNR_STAGE_OMITTED" in second


def test_the_resume_keeps_the_signoff_spef_extraction(tmp_path, monkeypatch):
    """Narrowness, as a property: omitting the crashing loop must not also
    drop the sign-off parasitic extraction that the post-route STA is judged
    on, nor the antenna repair the shipped geometry depends on. A resume that
    quietly drops load-bearing work would trade one silent defect for
    another."""
    _res, calls, _p = _drive(tmp_path, monkeypatch,
                             first_rc=139, stage="postroute_drv_repair")
    second = calls[1]["body"]
    assert "write_spef" in second
    assert "repair_antennas" in second
    assert "/routed.def" in second


def test_a_crash_the_runner_resumed_past_is_still_recorded(
        tmp_path, monkeypatch):
    """A resume must not launder the crash. Whatever the final verdict, the
    signal, the stage and the fact that a stage did not run have to remain
    readable — both on the step result and durably on disk, because a step
    detail is overwritten by the next run and an audit trail is not."""
    res, _calls, project = _drive(tmp_path, monkeypatch,
                                  first_rc=139, stage="postroute_drv_repair")
    assert _says_signal(res.detail or ""), \
        "the resumed verdict reads like an ordinary PnR result"
    att = mod._pl.reports_dir(project) / "phase3" / "pnr_fatal_signal.json"
    assert att.is_file(), "no durable record of the crash was written"
    txt = att.read_text()
    assert "11" in txt and "postroute_drv_repair" in txt


def test_a_stale_def_does_not_launder_a_crash(tmp_path, monkeypatch):
    """The most dangerous shape: the tool crashed BEFORE writing the final
    DEF, but a DEF from an earlier run is still sitting in the output
    directory. The pre-fix gate was "non-zero exit OR no final DEF" — the
    stale file satisfied half of it, and only the exit code was left to notice
    anything was wrong. A file that cannot have come from this session must
    never be handed downstream as if it had."""
    project = _build_project(tmp_path, "widget")
    out_dir = mod._pl.pnr_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "widget.def").write_text("VERSION 5.8 ;\nDESIGN stale ;\n")
    monkeypatch.setattr(mod, "_openroad_supports_postroute_spef_repair",
                        lambda *_a, **_k: True)

    def fake_docker_exec(container, cmd, timeout=None, **kw):
        if "openroad -no_init" in cmd:
            log = _crash_log("postroute_drv_repair", tool_printed_trace=False)
            (out_dir / "openroad.log").write_text(log)
            return (139, log, "")
        return (0, "", "")

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod.step_pnr(project, "widget", _sky130_pdk(), "iic", "200x200",
                       0.30)
    assert res.status != "PASS"
    assert _says_signal(res.detail or ""), \
        f"the crash was not named: {(res.detail or '')[:300]!r}"


def test_a_resume_that_also_crashes_is_not_retried(tmp_path, monkeypatch):
    """Bounded, by construction: one attempt. A resume loop that kept
    re-entering a reproducible segfault would burn a machine instead of
    reporting a defect."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair", resume_rc=139,
                            resume_writes_def=False)
    assert len(calls) == 2
    assert res.status == "FAIL"


def test_no_checkpoint_means_no_resume_and_the_verdict_says_so(
        tmp_path, monkeypatch):
    """A crash before any stage completed leaves nothing to resume from. The
    runner must say that rather than attempt one — and must still name the
    signal."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair",
                            write_checkpoint=False,
                            tool_printed_trace=False)
    assert len(calls) == 1
    assert res.status == "FAIL"
    assert _says_signal(res.detail or "")


@pytest.mark.skipif(tclsh is None, reason="tclsh not installed")
def test_the_script_the_resume_runs_is_valid_tcl(tmp_path, monkeypatch):
    """Whatever the runner hands OpenROAD has to parse. A resume script built
    by cutting regions out of a working one is only safe if every cut removes
    a brace-balanced region; this proves it on the real emission rather than
    asserting it."""
    _res, calls, _p = _drive(tmp_path, monkeypatch,
                             first_rc=139, stage="postroute_drv_repair")
    script = tmp_path / "resume_check.tcl"
    body = calls[1]["body"].replace("\nexit\n", "\nputs PNR_RESUME_END\n")
    script.write_text('proc unknown {args} { return "" }\n' + body)
    r = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert "PNR_RESUME_END" in r.stdout


# ---------------------------------------------------------------------------
# The emitted pnr.tcl must carry what the resume needs to find
# ---------------------------------------------------------------------------
def test_the_emitted_pnr_tcl_breadcrumbs_the_stage_it_is_in(
        tmp_path, monkeypatch):
    """Without a breadcrumb the runner cannot name the stage that died, and
    everything above degrades to quoting a log tail again."""
    _res, calls, _p = _drive(tmp_path, monkeypatch,
                             first_rc=139, stage="postroute_drv_repair")
    body = calls[0]["body"]
    for stage in ("detailed_route", "postroute_drv_repair",
                  "postroute_antenna_repair"):
        assert f"{_MARKER} {stage}" in body, \
            f"pnr.tcl does not breadcrumb {stage}"


def test_stage_breadcrumb_parsing_reports_the_last_stage_entered():
    """IMPLEMENTATION-LEVEL (named helpers), unlike everything above: the
    parse itself. Kept because the property tests exercise this through
    step_pnr and a direct unit here localises a parse regression."""
    log = ("PNR_STAGE: detailed_route\n"
           "[INFO DRT-0198] Complete detail routing.\n"
           "PNR_STAGE: postroute_drv_repair\n"
           "Signal 11 received\n")
    assert mod._pnr_stage_from_log(log) == "postroute_drv_repair"
    assert mod._detail_route_completed(log) is True
    assert mod._pnr_stage_from_log("no breadcrumbs here") is None


# ---------------------------------------------------------------------------
# The advice must not outrun the mechanism
# ---------------------------------------------------------------------------
def test_the_checkpoint_advice_points_at_a_mechanism_that_exists():
    """The note the canonicalize step emits used to say "resume from the
    checkpoint; a from-scratch re-run is NOT required" while no resume flag
    and no resume code path existed anywhere in the runner. A comment that
    describes a capability nobody wrote is worse than no comment: it sends
    the reader looking for a flag that was never there."""
    import inspect
    src = inspect.getsource(mod.step_canonicalize_artefacts)
    if "re-run is NOT required" not in src and \
            "from-scratch re-run" not in src:
        pytest.skip("the note no longer promises a resume")
    entry = [n for n in dir(mod)
             if "resume" in n.lower() and callable(getattr(mod, n, None))]
    assert entry, \
        ("the flow advises resuming from the checkpoint but the runner "
         "exposes no resume entry point at all")
