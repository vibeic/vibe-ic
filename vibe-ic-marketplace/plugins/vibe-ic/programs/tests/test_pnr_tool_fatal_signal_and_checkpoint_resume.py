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
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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


def _def_text_no_nets_section() -> str:
    """A DEF the routing predicate CANNOT classify: well-formed, non-empty,
    and carrying no `NETS` header at all — which is what a write cut short
    before the NETS section leaves behind. `_def_signal_routing_stats` has one
    scan and two policies for this shape, and the resume sites are the callers
    that pass `unknown_is_routed=False` ("could not tell" = "not proven")."""
    return ("VERSION 5.8 ;\nDIVIDERCHAR \"/\" ;\nDESIGN widget ;\n"
            "UNITS DISTANCE MICRONS 1000 ;\n"
            "COMPONENTS 2 ;\n- u0 sky130_fd_sc_hd__inv_1 + PLACED ( 0 0 ) N ;\n"
            "- u1 sky130_fd_sc_hd__inv_1 + PLACED ( 460 0 ) N ;\n"
            "END COMPONENTS\nEND DESIGN\n")


def _def_text(nets: int = 40, *, routed: bool) -> str:
    """A minimally-real DEF, because the question every gate below asks is a
    question about DEF CONTENT.

    `routed=True` gives each signal net the `+ ROUTED` wiring a completed
    detailed route writes. `routed=False` gives the SAME connectivity with no
    geometry at all — which is exactly what `write_def` emits for a design
    that was placed but never routed, and is the state a resume must be able
    to see rather than infer from a filename."""
    out = ["VERSION 5.8 ;", "DIVIDERCHAR \"/\" ;", "BUSBITCHARS \"[]\" ;",
           "DESIGN widget ;", "UNITS DISTANCE MICRONS 1000 ;",
           f"NETS {nets} ;"]
    for i in range(nets):
        out.append(f"- n{i} ( u{i} Y ) ( u{i + 1} A )")
        if routed:
            out.append(f"  + ROUTED met1 ( {1000 + i * 20} 2000 ) "
                       f"( {1400 + i * 20} 2000 )")
        out.append("  ;")
    out += ["END NETS", "END DESIGN"]
    return "\n".join(out) + "\n"

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
           tool_printed_trace=True, top="widget",
           route_checkpoint="routed", resume_def_routed=True,
           preroute_routed=False, first_signoff=(),
           resume_def_classifiable=True, probe=True):
    """Run step_pnr against a fake OpenROAD.

    The FIRST `openroad` invocation writes the route checkpoint and the log,
    then returns `first_rc` WITHOUT writing the final DEF — the measured
    shape of a mid-tcl death after a completed route. Any SECOND invocation
    is whatever the runner decided to do about that; the fake records the
    script it was pointed at so the test can inspect it.

    `route_checkpoint` selects what the LAST checkpoint write left behind:

      "routed"    the normal case — routed_preantenna.def with real routing;
      "zero_byte" the write was attempted and produced an empty file. This is
                  reachable in the shipped flow because `write_def
                  routed_preantenna.def` is itself inside a Tcl `catch`
                  (ROUTED_CHECKPOINT_NONFATAL), so a failed checkpoint write
                  does NOT stop the run — it continues into the post-route
                  tail where the measured Signal 11 happens;
      "unrouted"  the file exists and is well-formed but carries no `+ ROUTED`
                  geometry, i.e. the write was cut short mid-design;
      "unclassifiable" the file exists and is well-formed but has no NETS
                  section at all, so the routing question cannot be ANSWERED
                  from it — the third outcome the predicate has, and the one
                  its `unknown_is_routed` policy exists for.

    `resume_def_routed` selects whether the resumed session's final DEF
    carries routing, which is the OUTPUT-side half of the same question;
    `resume_def_classifiable=False` makes that DEF unclassifiable instead,
    which is the OUTPUT-side half of the `unknown_is_routed` question.

    `first_signoff` names the sign-off artifacts the FIRST session wrote
    before it died. Empty (the default) is a crash BEFORE the writes. Naming
    them is a crash AFTER them — the shape pnr.tcl's own last stage, the #147
    ESTIMATE block, produces, because the template puts it below every
    `write_def`/`write_verilog` precisely so it cannot touch them.

    `preroute_routed` makes the PRE-route checkpoints carry routed geometry.
    In a single clean run they never would — hold repair precedes routing —
    but the pnr output directory is not cleaned between runs, so a
    `post_hold.def` sitting there may be a LEFTOVER from an earlier session
    whose content has nothing to do with this one. That is the same
    stale-artifact hazard `test_a_stale_def_does_not_launder_a_crash` covers
    for the final DEF, and it is what isolates the resume-POINT rule from the
    routed-geometry rule.
    """
    project = _build_project(tmp_path, top)
    calls: list = []
    # The measured crash happened on an OpenROAD the runner's own probe
    # declared CAPABLE of post-route SPEF repair (image 0.2.58 probed capable
    # and took Signal 11 anyway). That is the configuration under test, so the
    # probe is pinned to it rather than left to whatever the test host has.
    # `probe=False` is the stock-upstream OpenROAD build, on which whole
    # template blocks collapse to nothing — a different emitted script, and so
    # a different resume, which the Tcl-parse test exercises both sides of.
    monkeypatch.setattr(mod, "_openroad_supports_postroute_spef_repair",
                        lambda *_a, **_k: probe)

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
                    # The four PRE-route checkpoints: placed connectivity, no
                    # routing — which is what they genuinely contain.
                    for pre in ("floorplan.def", "placed.def",
                                "post_cts.def", "post_hold.def"):
                        (out_dir / pre).write_text(
                            _def_text(routed=preroute_routed))
                    ck = out_dir / "routed_preantenna.def"
                    if route_checkpoint == "zero_byte":
                        ck.write_bytes(b"")
                    elif route_checkpoint == "unrouted":
                        ck.write_text(_def_text(routed=False))
                    elif route_checkpoint == "unclassifiable":
                        ck.write_text(_def_text_no_nets_section())
                    else:
                        ck.write_text(_def_text(routed=True))
                for name in first_signoff:
                    if name.endswith(".def"):
                        (out_dir / name).write_text(_def_text(routed=True))
                    elif name.endswith(".v"):
                        (out_dir / name).write_text(
                            f"module {top}(); endmodule\n")
                    else:
                        (out_dir / name).write_text("worst slack 0.42\n")
                log = _crash_log(stage, signal_death=first_rc == 139,
                                 tool_printed_trace=tool_printed_trace)
                if first_signoff:
                    log += _PG_OK
                (out_dir / "openroad.log").write_text(log)
                return (first_rc, log, "")
            # second and later invocations
            log = _ROUTE_OK + _PG_OK
            if resume_writes_def:
                _body = (_def_text(routed=resume_def_routed)
                         if resume_def_classifiable
                         else _def_text_no_nets_section())
                (out_dir / "routed.def").write_text(_body)
                (out_dir / f"{top}.def").write_text(_body)
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


# ---------------------------------------------------------------------------
# ...AND A CRASH THAT LANDED *AFTER* THE WRITES MUST NOT BE LAUNDERED EITHER
# ---------------------------------------------------------------------------
# The stale-DEF refusal above states a FACT — "this DEF predates the crash" —
# and pnr.tcl has a stage for which that fact is false. The #147 setup-repair
# ESTIMATE block is the LAST thing in the template, placed there deliberately
# ("runs AFTER all shipped artifacts + the clean sta.rpt, so it never modifies
# routed.def/<top>.def/<top>_pnr.v"), and it runs `repair_timing -setup` — the
# command this whole file's evidence shows segfaulting. A crash there met the
# stale-DEF branch's only condition (a DEF is on disk), so the runner FAILed a
# COMPLETE run, published a correct sign-off DEF as `non_signoff_outputs`, and
# wrote both false claims into the durable attestation.
_SIGNOFF_SET = ("routed.def", "widget.def", "widget_pnr.v", "sta.rpt")


def test_a_crash_after_the_signoff_writes_is_not_called_a_stale_def(
        tmp_path, monkeypatch):
    """THE INVERSION. Same signal, same message machinery, other side of the
    writes: the artifacts on disk ARE this session's, and the stage that died
    is one pnr.tcl declares best-effort and that modifies none of them.

    The verdict must judge those artifacts instead of refusing them, and must
    not state that `write_def routed.def` never ran."""
    res, calls, project = _drive(tmp_path, monkeypatch, first_rc=139,
                                 stage="postroute_setup_repair_estimate",
                                 first_signoff=_SIGNOFF_SET)
    assert len(calls) == 1, "no resume is needed — the artifacts are on disk"
    assert res.status == "PASS", \
        (f"a completed run was reported {res.status} because the tool died "
         f"in a block that runs after every write: {(res.detail or '')[:400]!r}")
    detail = res.detail or ""
    # the crash is RECORDED, not dropped
    assert _says_signal(detail), (
        "a PASS that only holds because the crash came after the writes must "
        "still name the crash")
    assert "postroute_setup_repair_estimate" in detail
    # and the false claim is gone
    assert "predates the crash" not in detail
    assert not (res.extras or {}).get("non_signoff_outputs"), \
        (f"a complete sign-off DEF was published as non-sign-off: "
         f"{(res.extras or {}).get('non_signoff_outputs')!r}")
    assert (mod._pl.pnr_dir(project) / "widget.def").is_file()
    # ...and the durable record says which side of the writes it was on
    att = mod._pl.reports_dir(project) / "phase3" / "pnr_fatal_signal.json"
    rec = json.loads(att.read_text())
    assert rec.get("crashed_after_signoff_writes") is True
    assert "predates the crash" not in att.read_text()


def test_a_post_write_crash_in_a_load_bearing_stage_is_still_a_failure(
        tmp_path, monkeypatch):
    """"After the writes" is NOT on its own a licence to pass. The template
    declares which stages are best-effort, and only those. A stage added below
    the writes one day whose output IS load-bearing must fail — this is the
    same `_PNR_NONFATAL_STAGES` rule the resume applies, on the other branch,
    and without this test dropping the estimate stage out of that frozenset
    changed no answer at all."""
    monkeypatch.setattr(
        mod, "_PNR_NONFATAL_STAGES",
        frozenset(s for s in mod._PNR_NONFATAL_STAGES
                  if s != "postroute_setup_repair_estimate"))
    res, _calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                             stage="postroute_setup_repair_estimate",
                             first_signoff=_SIGNOFF_SET)
    assert res.status == "FAIL", \
        "a crash in a LOAD-BEARING post-write stage was signed off"
    detail = res.detail or ""
    assert "load-bearing" in detail and "postroute_setup_repair_estimate" in detail
    # the reason must be the stage's role, never a false claim about the DEF
    assert "predates the crash" not in detail


def test_a_post_write_crash_with_a_missing_artifact_is_still_a_failure(
        tmp_path, monkeypatch):
    """The stage's POSITION says the writes were reached. Only the filesystem
    says they landed. A crash between two of them — `write_verilog` after
    `write_def`, say — leaves a partial set, and a verdict that read the
    position alone would sign that off."""
    res, _calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                             stage="postroute_setup_repair_estimate",
                             first_signoff=("routed.def", "widget.def"))
    assert res.status == "FAIL", \
        "a partial sign-off write set was accepted because the stage sat low"
    detail = res.detail or ""
    assert "widget_pnr.v" in detail, \
        f"the verdict does not name what is missing: {detail[:400]!r}"


def test_stage_position_is_read_off_the_script_that_actually_ran():
    """IMPLEMENTATION-LEVEL, deliberately: the position predicate itself, on
    hand-built scripts, so its three refusal shapes are driven directly rather
    than only through the one template this repo happens to emit."""
    tcl = ('puts "PNR_STAGE: detailed_route"\n'
           'detailed_route\n'
           'puts "PNR_STAGE: write_routed"\n'
           'write_def /o/routed.def\n'
           'write_def /o/top.def\n'
           'write_verilog /o/top_pnr.v\n'
           'report_checks > /o/sta.rpt\n'
           'puts "PNR_STAGE: postroute_setup_repair_estimate"\n'
           '  catch {report_checks > /o/sta_spef_repaired.rpt}\n')
    after = mod._pnr_stages_after_signoff_writes(tcl)
    assert after == {"postroute_setup_repair_estimate"}, after
    # fail-safe: nothing is post-sign-off when the script cannot say so
    assert mod._pnr_stages_after_signoff_writes("") == frozenset()
    assert mod._pnr_stages_after_signoff_writes(
        'puts "PNR_STAGE: floorplan"\ninitialize_floorplan\n') == frozenset()


def test_the_emitted_template_puts_the_estimate_block_below_every_write(
        tmp_path, monkeypatch):
    """...and the predicate above is only worth anything if the SHIPPED
    template still has that shape. Measured on the real emission."""
    _res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                             stage="postroute_drv_repair")
    body = calls[0]["body"]
    after = mod._pnr_stages_after_signoff_writes(body)
    assert "postroute_setup_repair_estimate" in after, \
        ("the emitted pnr.tcl no longer runs the ESTIMATE block below its "
         "sign-off writes — the crash-survivability verdict depends on it")
    assert "write_routed" not in after and "postroute_drv_repair" not in after


# ---------------------------------------------------------------------------
# A FAILED RESUME LEAVES NOTHING ON A CANONICAL PATH
# ---------------------------------------------------------------------------
# The resume runs the post-route TAIL, whose last commands are the writes. So a
# resume that dies late, or exits 0 having produced an UNROUTED DEF, can leave
# `<top>.def` and `routed.def` sitting on the paths seven downstream steps key
# on — files that exist ONLY because the resume put them there, from a session
# the runner has just declared failed. This is the identical hazard
# `_docker_timeout_isolate` was written for on the stall path (#570).
@pytest.mark.parametrize("resume_rc,routed,classifiable,why", [
    (0, False, True, "exited 0 with an unrouted DEF"),
    (5, True, True, "exited non-zero"),
    (139, True, True, "was killed by a signal too"),
    (0, True, False, "exited 0 with an unclassifiable DEF"),
])
def test_a_failed_resume_leaves_no_artifact_on_a_canonical_path(
        tmp_path, monkeypatch, resume_rc, routed, classifiable, why):
    res, calls, project = _drive(
        tmp_path, monkeypatch, first_rc=139, stage="postroute_drv_repair",
        resume_rc=resume_rc, resume_def_routed=routed,
        resume_def_classifiable=classifiable)
    assert len(calls) == 2, "fixture invalid: the resume must have been tried"
    assert res.status == "FAIL", f"a resume that {why} was accepted"
    out_dir = mod._pl.pnr_dir(project)
    for name in ("widget.def", "routed.def"):
        assert not (out_dir / name).is_file(), (
            f"a resume that {why} left {name} on its canonical path — the "
            f"next step reads that file to decide the design is there")
    named = (res.extras or {}).get("non_signoff_outputs") or []
    assert any(n.endswith("widget.def") for n in named), \
        f"the half-run outputs are not named in the verdict: {named!r}"
    # the route checkpoint is EVIDENCE and must survive
    assert (out_dir / "routed_preantenna.def").is_file()


def test_a_resume_that_never_ran_isolates_nothing(tmp_path, monkeypatch):
    """The over-breadth guard for the isolation above. A NOT_ATTEMPTED resume
    started no session and wrote no file, so there is nothing of this run's to
    rename — and a rule that renamed on every failed-resume verdict would
    start moving unrelated leftovers around."""
    out_dir_leftover = "routed.def"
    res, calls, project = _drive(tmp_path, monkeypatch, first_rc=139,
                                 stage="postroute_antenna_repair")
    assert len(calls) == 1
    assert res.status == "FAIL"
    assert not (mod._pl.pnr_dir(project)
                / f"{out_dir_leftover}.timeout.partial").is_file()
    assert not (res.extras or {}).get("non_signoff_outputs")


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


# ---------------------------------------------------------------------------
# A RESUME MUST PROVE IT IS RESUMING FROM A ROUTED DESIGN
# ---------------------------------------------------------------------------
# The resume Tcl DELETES floorplan..detailed_route, on the premise that the
# checkpoint it reads already contains that work. Nothing used to check the
# premise: `_pnr_last_checkpoint_file` returns the last EXISTING DEF, so a
# missing or zero-byte `routed_preantenna.def` silently demoted the resume
# point to `post_hold.def` — a PRE-ROUTE checkpoint — and the post-route tail
# then ran over a design that had never been routed, wrote it out as the final
# DEF, and the step returned PASS with the message "routing SUCCEEDED".
def test_a_pre_route_checkpoint_is_refused_as_a_resume_point(
        tmp_path, monkeypatch):
    """THE DEFECT. The route checkpoint write failed (its own `catch` let the
    run continue), so the newest DEF on disk is post_hold.def. Resuming from
    it would elide every routing command and sign off an unrouted design.

    The runner must refuse, say why, and not start a second tool session."""
    res, calls, project = _drive(tmp_path, monkeypatch, first_rc=139,
                                 stage="postroute_drv_repair",
                                 route_checkpoint="zero_byte")
    assert len(calls) == 1, \
        "a second OpenROAD session was started from a PRE-ROUTE checkpoint"
    assert res.status == "FAIL", \
        f"an unrouted design was signed off as {res.status}"
    detail = (res.detail or "")
    assert "NOT_ATTEMPTED" in detail
    assert "post_hold" in detail, \
        f"the refusal does not name the checkpoint it refused: {detail[:400]!r}"
    # and the design was never handed to the tail
    assert not (mod._pl.pnr_dir(project) / "widget.def").is_file()


def test_a_pre_route_checkpoint_that_looks_routed_is_still_refused(
        tmp_path, monkeypatch):
    """The resume POINT rule, isolated from the routed-geometry rule.

    The pnr output directory is not cleaned between runs, so the
    `post_hold.def` on disk may be a leftover from an EARLIER session and can
    carry anything — here, routing. Its geometry therefore proves nothing
    about THIS design, and the resume Tcl would still elide
    floorplan..detailed_route on the strength of a file that is not the
    checkpoint that region ends at.

    Only the resume-point rule can refuse this one: with routing present, the
    geometry check has nothing to object to."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair",
                            route_checkpoint="zero_byte",
                            preroute_routed=True)
    assert len(calls) == 1, \
        ("resumed from post_hold.def because it happened to contain routing "
         "— the resume point must be the ROUTE checkpoint, not merely a DEF "
         "with wires in it")
    assert res.status == "FAIL"
    assert "post_hold" in (res.detail or "")


def test_a_route_checkpoint_with_no_routing_in_it_is_refused(
        tmp_path, monkeypatch):
    """The filename is not the evidence; the geometry is. A
    `routed_preantenna.def` whose write was cut short by the same crash exists
    and is non-empty, but carries no `+ ROUTED` wiring. Resuming from it is
    the identical defect wearing the right filename."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair",
                            route_checkpoint="unrouted")
    assert len(calls) == 1, \
        "resumed from a route checkpoint that contains no routing"
    assert res.status == "FAIL"
    assert "no routed signal geometry" in (res.detail or "").lower(), \
        f"the refusal does not name the reason: {(res.detail or '')[:400]!r}"


def test_a_checkpoint_that_cannot_be_classified_is_refused(
        tmp_path, monkeypatch):
    """"Could not tell" is not "fine". `_def_signal_routing_stats` has ONE
    scan and TWO policies, selected by `unknown_is_routed`, and both resume
    sites pass False because they are asking for POSITIVE proof of routing.
    Nothing drove that: with no test creating an UNCLASSIFIABLE DEF, flipping
    either call site to the fail-safe default True changed no answer.

    Here the checkpoint exists, is well-formed and is non-empty, but has no
    NETS section — so the routing question has no answer in it, and a resume
    that elides floorplan..detailed_route on the strength of it would run the
    tail over a design it never established was routed."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair",
                            route_checkpoint="unclassifiable")
    assert len(calls) == 1, \
        ("resumed from a checkpoint whose routing could not be determined — "
         "'unclassifiable' was read as 'routed'")
    assert res.status == "FAIL"
    assert "no routed signal geometry" in (res.detail or "").lower()


def test_a_resume_output_that_cannot_be_classified_is_not_a_success(
        tmp_path, monkeypatch):
    """The OUTPUT side of the same policy. The resumed session exited 0 and
    wrote a final DEF, but that DEF carries no NETS section, so nothing in it
    establishes the design is routed. rc=0 plus an unreadable file is the
    weakest evidence in the flow and must not be the strongest verdict."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair",
                            resume_def_classifiable=False)
    assert len(calls) == 2, "fixture invalid: the resume must have been tried"
    assert res.status == "FAIL", \
        "an unclassifiable resume output was accepted as routed"
    assert "no routed signal geometry" in (res.detail or "").lower()


def test_a_resume_that_produces_an_unrouted_def_is_not_a_success(
        tmp_path, monkeypatch):
    """The output side of the same question. The resumed session exited 0 and
    a final DEF is on disk — the entire pre-existing success test — but that
    DEF carries no routing. rc=0 plus a file is not evidence."""
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_drv_repair",
                            resume_def_routed=False)
    assert len(calls) == 2, "fixture invalid: the resume must have been tried"
    assert res.status == "FAIL", \
        f"an unrouted resume output was accepted as {res.status}"


def test_a_crash_in_a_load_bearing_stage_is_not_resumed_past(
        tmp_path, monkeypatch):
    """The guard the PR calls load-bearing, DRIVEN. `postroute_antenna_repair`
    is not one of the stages pnr.tcl declares best-effort — its output is in
    the shipped geometry — so omitting it would change what was built.

    Without this test the refusal branch had no driver at all: replacing the
    whole condition with `if False:` (i.e. omit ANY stage, load-bearing or
    not) left every test green."""
    res, calls, project = _drive(tmp_path, monkeypatch, first_rc=139,
                                 stage="postroute_antenna_repair")
    assert len(calls) == 1, \
        "a load-bearing stage was omitted and the tail re-run without it"
    assert res.status == "FAIL"
    detail = (res.detail or "")
    assert "postroute_antenna_repair" in detail and "load-bearing" in detail, \
        f"the refusal does not name the stage or why: {detail[:400]!r}"
    att = mod._pl.reports_dir(project) / "phase3" / "pnr_fatal_signal.json"
    assert "NOT_ATTEMPTED" in att.read_text()


def test_a_kill_sentinel_inside_the_signal_window_is_still_not_a_signal(
        tmp_path, monkeypatch):
    """The runner's kill sentinels are excluded from the 128+N decoding. With
    today's values (124/198/199) and NSIG=65 the window is 129..192, so all
    three fall outside it and the exclusion never fires — deleting it changed
    no answer, which is why it was untested.

    A sentinel that DOES land in the window is the state the exclusion exists
    for, and it is one a test can create. Here the watchdog gains one at 139,
    the exact status a SIGSEGV produces: the runner must still report its own
    kill as a kill."""
    monkeypatch.setattr(mod._wd, "RC_TEST_SENTINEL_IN_WINDOW", 139,
                        raising=False)
    assert mod._fatal_signal_from_rc(139) is None, \
        ("a status the RUNNER uses to say it killed the tool was decoded as "
         "SIGSEGV — a watchdog kill reported as an OpenROAD crash")
    # and the real ones stay excluded
    for name in ("RC_CEILING", "RC_ABORTED", "RC_STALLED"):
        assert mod._fatal_signal_from_rc(getattr(mod._wd, name)) is None
    # while a genuine signal death is still decoded
    assert mod._fatal_signal_from_rc(137) == 9


def _tcl_evals(tmp_path, body, name):
    script = tmp_path / name
    script.write_text('proc unknown {args} { return "" }\n'
                      + body.replace("\nexit\n", "\nputs PNR_TCL_END\n"))
    # The parse is a `tclsh` syntax check over one file and measures well
    # under a second; 30 s is two orders of magnitude of headroom and stays
    # under the harness's per-call ceiling (bound/3).
    r = _pr.run([tclsh, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "PNR_TCL_END" in r.stdout


@pytest.mark.skipif(tclsh is None, reason="tclsh not installed")
@pytest.mark.parametrize("probe", [True, False])
@pytest.mark.parametrize("stage", sorted(mod._PNR_NONFATAL_STAGES))
def test_both_the_pnr_and_the_resume_script_are_valid_tcl(
        tmp_path, monkeypatch, probe, stage):
    """Whatever the runner hands OpenROAD has to parse — the emitted pnr.tcl
    AND every resume derived from it. A resume built by cutting regions out of
    a working script is only safe if every cut removes a brace-balanced
    region, so it is proven on the real emission, across BOTH outcomes of the
    fork-repair probe (which decides whether whole blocks are emitted at all)
    and for every stage the resume is allowed to omit.

    Not every (probe, stage) pair yields a resume — on stock upstream the
    blocks those stages live in are not emitted at all, so no resume can be
    derived from the script and the runner says so instead of building half a
    one. EVERY script the runner did hand the tool is parsed, whichever those
    turn out to be."""
    _res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139, stage=stage,
                             probe=probe)
    assert calls, "fixture invalid: no script was emitted at all"
    for i, call in enumerate(calls):
        _tcl_evals(tmp_path, call["body"], f"tcl_check_{i}.tcl")


@pytest.mark.skipif(tclsh is None, reason="tclsh not installed")
def test_the_resume_script_itself_is_reached_and_parses(tmp_path, monkeypatch):
    """...and the matrix above must not degenerate into "pnr.tcl parses" only.
    This pins one configuration in which a resume IS built."""
    _res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                             stage="postroute_drv_repair", probe=True)
    assert len(calls) == 2, "no resume was built in the configuration that has one"
    assert mod._PNR_RESUME_TCL in calls[1]["script"]
    _tcl_evals(tmp_path, calls[1]["body"], "resume_check.tcl")


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


def test_splitting_the_reconverge_block_did_not_drop_the_second_antenna_pass(
        tmp_path, monkeypatch):
    """The DRV re-convergence loop and the antenna pass that follows it used
    to be ONE concatenated template string; they are now two slots so the
    resume sentinels can bracket the loop alone. The claim attached to that
    change is that the emitted Tcl is BYTE-IDENTICAL — slot A then slot B,
    same order, same text — and nothing measured it: `repair_antennas` still
    appeared via slot A, so emptying slot B (the SECOND, load-bearing antenna
    pass) left every test green while silently halving the antenna repair.

    Two passes means the antenna block is emitted TWICE and the two copies are
    byte-identical, which is exactly what the claim says. Both halves are
    measured on the real emission and both are cut out by their sentinels, so
    neither depends on counting a token that also occurs elsewhere."""
    _res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                             stage="postroute_drv_repair")
    body = calls[0]["body"]
    a_open = f'puts "{_MARKER} postroute_antenna_repair"\n'
    b_open = f'puts "{_MARKER} postroute_antenna_reconverge"\n'
    rc_begin = mod._pnr_stage_begin("postroute_drv_reconverge")
    rc_end = mod._pnr_stage_end("postroute_drv_reconverge")
    for needle in (a_open, b_open, rc_begin, rc_end):
        assert needle in body, f"the emission carries no {needle!r}"
    slot_a = body[body.index(a_open) + len(a_open):body.index(rc_begin)]
    assert slot_a.strip(), "the FIRST antenna pass is empty"
    _b0 = body.index(b_open) + len(b_open)
    assert body[_b0:_b0 + len(slot_a)] == slot_a, (
        "the SECOND (post-reconverge) antenna pass is not the byte-identical "
        "re-emission of the first — the split was claimed to change nothing "
        "about the emitted Tcl, and `repair_antennas` still appearing via the "
        "first slot is why an emptied second slot went unnoticed")


def test_the_second_antenna_pass_is_breadcrumbed_and_load_bearing(
        tmp_path, monkeypatch):
    """The second antenna pass had NO breadcrumb of its own, so the last stage
    in force while it ran was `postroute_drv_reconverge` — which pnr.tcl DOES
    declare best-effort. A crash in this load-bearing pass was therefore
    diagnosed as a crash in an omittable one and sent straight to the resume
    that the load-bearing guard exists to refuse."""
    assert "postroute_antenna_reconverge" not in mod._PNR_NONFATAL_STAGES
    res, calls, _p = _drive(tmp_path, monkeypatch, first_rc=139,
                            stage="postroute_antenna_reconverge")
    assert len(calls) == 1, \
        "a crash in the second antenna pass was resumed past"
    assert res.status == "FAIL"
    assert "load-bearing" in (res.detail or "")


def test_the_signal_window_has_an_upper_bound_and_it_is_the_platforms(
        tmp_path):
    """128+N decoding is only valid for N in the platform's signal range. The
    upper bound was correct and unpinned: raising it (or dropping it) let an
    ordinary large exit status be reported as a signal death, which routes a
    tool ERROR down the crash-and-resume path.

    NSIG is read from the platform, so the boundary is computed here too
    rather than written as a Linux literal."""
    import signal as _sig
    nsig = int(getattr(_sig, "NSIG", 65))
    sentinels = mod._runner_kill_sentinels()
    top_sig = nsig - 1
    assert 128 + top_sig not in sentinels, "test's own boundary is a sentinel"
    assert mod._fatal_signal_from_rc(128 + top_sig) == top_sig, \
        "the highest real signal is not decoded"
    assert mod._fatal_signal_from_rc(128 + nsig) is None, \
        (f"rc={128 + nsig} is above the platform's signal range (NSIG="
         f"{nsig}) and was still decoded as a signal death")
    assert mod._fatal_signal_from_rc(128) is None, "128 is 128+0, not a signal"
    assert mod._fatal_signal_from_rc(1) is None


# ---------------------------------------------------------------------------
# ONE DEF WIRING GRAMMAR
# ---------------------------------------------------------------------------
# The routing predicates hand-rolled the DEF 5.8 `regularWiring` STATUS token
# as substring tests, and each rolled it differently. MEASURED over the 531
# tracked DEFs in this repo: `+ NEW` occurs ZERO times — the continuation is
# spelled `NEW`, with no plus — so half of one predicate's grammar could never
# match anything. Meanwhile FIXED / COVER / NOSHIELD wiring, and a `+  ROUTED`
# written with two spaces, all read as UNROUTED: a false REFUSAL for the
# resume gate and a false BLOCK for the LVS guard.
def _nets_def(wiring: str) -> str:
    return ("VERSION 5.8 ;\nDESIGN widget ;\nNETS 2 ;\n"
            f"- n0 ( u0 Y ) ( u1 A )\n{wiring}\n  ;\n"
            "- n1 ( u1 Y ) ( u2 A )\n  ;\n"
            "END NETS\nEND DESIGN\n")


@pytest.mark.parametrize("wiring,routed,why", [
    ("  + ROUTED met1 ( 0 0 ) ( 100 0 )", True, "the ordinary case"),
    ("  + FIXED met1 ( 0 0 ) ( 100 0 )", True, "pre-routed, legal DEF 5.8"),
    ("  + COVER met1 ( 0 0 ) ( 100 0 )", True, "pre-routed and unshapeable"),
    ("  + NOSHIELD met1 ( 0 0 ) ( 100 0 )", True, "shield wiring"),
    ("  +  ROUTED met1 ( 0 0 ) ( 100 0 )", True, "two spaces is still legal"),
    ("  + ROUTED met1 ( 0 0 ) ( 100 0 )\n  NEW met2 ( 100 0 ) ( 100 90 )",
     True, "the real continuation grammar: bare NEW, never `+ NEW`"),
    ("  + USE SIGNAL", False, "a property, not wiring"),
    ("  + SOURCE TIMING", False, "a property, not wiring"),
])
def test_one_def_wiring_grammar_for_every_routing_predicate(
        tmp_path, wiring, routed, why):
    p = tmp_path / "w.def"
    p.write_text(_nets_def(wiring))
    got, _n = mod._def_signal_routing_stats(p, unknown_is_routed=False)
    assert got is routed, f"{why}: classified routed={got}"


def test_the_unclassifiable_policy_is_the_callers_not_the_predicates(
        tmp_path):
    """The two policies, driven directly. Same file, same scan, opposite
    answers — which is the whole reason the parameter exists."""
    p = tmp_path / "nonets.def"
    p.write_text(_def_text_no_nets_section())
    assert mod._def_signal_routing_stats(p, unknown_is_routed=True) == (True, 0)
    assert mod._def_signal_routing_stats(p, unknown_is_routed=False) == (False, 0)
    missing = tmp_path / "nope.def"
    assert mod._def_signal_routing_stats(missing, unknown_is_routed=True)[0] is True
    assert mod._def_signal_routing_stats(missing, unknown_is_routed=False)[0] is False


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
def test_the_crash_attestation_has_a_reader_not_only_a_pointer(
        tmp_path, monkeypatch):
    """`reports/phase3/pnr_fatal_signal.json` was WRITE-ONLY: step_pnr emitted
    it, a note pointed a human at it, and no program in the tree ever opened
    it. So the one shape it exists to make visible — a crash that nevertheless
    left a COMPLETE per-stage DEF set, because it landed after the sign-off
    writes or because the resume finished the tail — arrived at
    canonicalisation looking exactly like an ordinary clean run and drew no
    note at all.

    Driven end-to-end: a project with every stage DEF present PLUS the
    attestation, through the real step."""
    project = _build_project(tmp_path, "widget")
    out_dir = mod._pl.pnr_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("floorplan.def", "placed.def", "post_cts.def",
                 "post_hold.def", "routed.def", "widget.def"):
        (out_dir / name).write_text(_def_text(routed=True))
    rpt = mod._pl.reports_dir(project) / "phase3"
    rpt.mkdir(parents=True, exist_ok=True)

    def _run():
        monkeypatch.setattr(mod, "_docker_exec",
                            lambda *a, **k: (0, "", ""), raising=True)
        monkeypatch.setattr(mod, "_to_container_path", lambda s, c: s,
                            raising=True)
        return mod.step_canonicalize_artefacts(project, "widget",
                                               _sky130_pdk(), "iic")

    clean = _run()
    assert "PnR CRASHED" not in (clean.detail or ""), \
        "the note fires with no attestation on disk"

    (rpt / "pnr_fatal_signal.json").write_text(json.dumps({
        "finding": "PNR_TOOL_FATAL_SIGNAL", "rc": 139, "signal": 11,
        "signal_name": "SIGSEGV", "stage": "postroute_setup_repair_estimate",
        "crashed_after_signoff_writes": True,
        "stage_is_nonfatal_by_template": True,
        "detail_route_completed": True}))
    crashed = _run()
    detail = crashed.detail or ""
    assert "PnR CRASHED" in detail, \
        ("a complete stage-DEF set produced by a CRASHED session drew no "
         "note — the attestation still has no reader")
    assert "SIGSEGV" in detail and "postroute_setup_repair_estimate" in detail


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
