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
import resource
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

mod = importlib.import_module("phase3_one_shot_runner")


# The harness must run identically against the PRE-fix runner, or the
# negative control degenerates into "the new symbol does not exist yet".
# Every fixture below is written in terms of the tool's own output, with
# the breadcrumb defaulting to the literal the fix emits.
_MARKER = getattr(mod, "_PNR_STAGE_MARKER", "PNR_STAGE:")


# ---------------------------------------------------------------------------
# Fixtures — a PnR project and a fake OpenROAD that can die on a signal
# ---------------------------------------------------------------------------
def _sky130_pdk(project: Path):
    # Timing setup now validates the selected Liberty before launching PnR.
    # Keep this synthetic session self-contained, but give that validation a
    # real, readable subject instead of the old never-existing placeholder.
    liberty = project / "input" / "pdk" / "sky130_fd_sc_hd__tt.lib"
    liberty.parent.mkdir(parents=True, exist_ok=True)
    liberty.write_text("library(sky130_fd_sc_hd__tt) {}\n")
    return mod.PdkConfig(
        name="sky130A",
        liberty=str(liberty),
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






# ---------------------------------------------------------------------------
# THE SIGNAL PATH — measured, not assumed
# ---------------------------------------------------------------------------
def _no_core_dumps() -> None:
    """Child-side: refuse to write a core file however the host is configured.

    Set in the CHILD because `RLIMIT_CORE` is inherited, and inherited is
    exactly the problem — `ulimit -c` is 0 on this fleet's hosts and
    `unlimited` inside the pinned image, so the same test writes a core file in
    one place and not the other.
    """
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def test_a_process_killed_by_a_signal_reaches_the_runner_as_128_plus_n(
        tmp_path):
    """The premise the whole fix rests on, EXERCISED rather than described: a
    real process that dies on SIGSEGV inside the exact pipeline shape
    `_docker_exec` builds (`<tool> 2>&1 | tee <log>` under `set -o pipefail`)
    is reported to the caller as 128+11.

    This one is true of the pre-fix runner too — that is the point. The signal
    was always arriving as 139; nothing was reading it as a signal.

    IT REALLY SEGFAULTS A PROCESS, so it really produces a core file wherever
    the kernel is told to put one. `/proc/sys/kernel/core_pattern` is the bare
    relative name `core` on this fleet, which means THE DYING PROCESS'S CWD,
    and this test used to inherit pytest's — the plugin root, inside the git
    tree. MEASURED 2026-09-07 on 8HD-9 through the repo's own container
    harness: `core.39`, 557056 bytes, left in
    `vibe-ic-marketplace/plugins/vibe-ic/`, where `suite_write_guard` named it
    and a later chip-agnostic scan reads it as tree content. It did not appear
    on the host arm because `ulimit -c` is 0 there and `unlimited` in the
    image — so the host arm is not evidence that this is clean.

    Three things, because none of them is sufficient alone: the child drops its
    own `RLIMIT_CORE` (the host's `core_pattern` is not ours to set), the child
    runs in `tmp_path` so a dump the kernel writes anyway lands outside the
    tree, and the tree is CHECKED afterwards rather than assumed."""
    inner = "bash -c 'kill -SEGV $$' 2>&1 | tee /dev/null"
    wrapped = mod._tool_status_not_the_log_sinks(inner)
    assert wrapped.startswith("set -o pipefail")
    plugin_root = Path(mod.__file__).resolve().parent.parent
    before = {p.name for p in plugin_root.glob("core*")}
    rc = subprocess.run(["bash", "-lc", wrapped],
                        capture_output=True, cwd=str(tmp_path),
                        preexec_fn=_no_core_dumps).returncode
    assert rc == 139, "a SIGSEGV in the tee pipeline must surface as 128+11"
    after = {p.name for p in plugin_root.glob("core*")}
    assert after == before, (
        f"this test segfaults a process and left {sorted(after - before)} in "
        f"{plugin_root}. A test that writes into the tree it is measuring "
        f"poisons every later scan of the same checkout.")
    dumped = sorted(p.name for p in tmp_path.glob("core*"))
    assert not dumped, (
        f"RLIMIT_CORE was set to 0 in the child and it dumped anyway: {dumped}. "
        f"The dump is outside the tree, so nothing is poisoned, but the limit "
        f"is not doing what this test says it does.")




# ---------------------------------------------------------------------------
# THE VERDICT — what the next reader is told
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# THE RESUME — the mechanism the advice promised
# ---------------------------------------------------------------------------












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












# ---------------------------------------------------------------------------
# A FAILED RESUME LEAVES NOTHING ON A CANONICAL PATH
# ---------------------------------------------------------------------------
# The resume runs the post-route TAIL, whose last commands are the writes. So a
# resume that dies late, or exits 0 having produced an UNROUTED DEF, can leave
# `<top>.def` and `routed.def` sitting on the paths seven downstream steps key
# on — files that exist ONLY because the resume put them there, from a session
# the runner has just declared failed. This is the identical hazard
# `_docker_timeout_isolate` was written for on the stall path (#570).








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






















# ---------------------------------------------------------------------------
# The emitted pnr.tcl must carry what the resume needs to find
# ---------------------------------------------------------------------------








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








# ---------------------------------------------------------------------------
# The advice must not outrun the mechanism
# ---------------------------------------------------------------------------
