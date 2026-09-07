"""vibe-ic#2082 — the stuck-at ATPG's wall budget stopped the engine.

`step11_dft_insertion` reported

    SKIP  "Fault ATPG exceeded its 1800s wall budget -> disclosed-skip
           (budget, not capability)"

on a design (sha256, lane rbsha2, 2026-09-07) whose AT-SPEED ATPG ran 52
minutes on the same tree and PASSED. A clock decided that a progressing job's
product does not exist -- and the step then recorded the absence as a
capability gap, which is a machine-readable claim about the ENGINE.

v1.17.70 removed the RUNNER's outer wall around this producer (CZT-10/CZT-11).
The producer's OWN wall was left: `run_fault` launched `fault atpg` through
`_run_docker(..., timeout=_atpg_wall)`, which puts coreutils `timeout` inside
the container as the engine's parent and signals it at the number. That is the
correct way to enforce a deadline and the wrong thing to be doing at all, and
it is the site this file pins.

THE RULING (cztimeout / czstarve / vibe-ic#2051): a progressing job is never
cut off. The ceiling RECORDS the crossing, announces it once, and the job
continues; only a job with NO forward progress is stopped, by the watchdog that
reads its progress. So the declared budget is not raised and not deleted --
what it DOES changes.

MEASURED, both directions, on a real `fault atpg` (spm cut netlist, -v 2000,
~37 s) in the pinned image on 8HD-9. Same engine, same argv, same container in
both arms; the only variable is what the declared number does:

    declared budget 10 s, PRE-FIX (the wall)   rc 124 at 10.5 s, NO product
    declared budget 10 s, this fix (recorded)  rc   0 at 37.7 s, product
                                               written, crossing recorded

and, stopped rather than slow (`docker pause` on the container this call
minted, stall grace 60 s):

    stopped        rc 199 (RC_STALLED) at 75.4 s, reaped, container gone,
                   "WATCHDOG_STALLED ... watched=output+cpu
                    since_last_progress_s=60.112"
    not stopped    rc 0 at 39.7 s, product written, not reaped

Evidence scripts: evidence/proof_A_ceiling_is_recorded.py,
proof_B_stopped_atpg_is_reaped.py, proof_C_cpu_probe_is_load_bearing.py.
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import fault_atpg_run as F          # noqa: E402
import _docker_watchdog as DWD      # noqa: E402
import _watchdog as W               # noqa: E402


# ── 1. THE LAUNCH SITE CARRIES NO TERMINATING DEADLINE ──────────────────────
def _atpg_launch_call() -> ast.Call:
    """The `_run_docker` call that launches the ATPG ENGINE, found by the
    argument it passes -- `[atpg_shell]` -- not by line number, so a rewrite
    above it cannot silently make this test measure a different call."""
    tree = ast.parse((_PROGRAMS / "fault_atpg_run.py").read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        if name != "_run_docker" or len(node.args) < 2:
            continue
        arg = node.args[1]
        if (isinstance(arg, ast.List) and len(arg.elts) == 1
                and isinstance(arg.elts[0], ast.Name)
                and arg.elts[0].id == "atpg_shell"):
            found.append(node)
    assert len(found) == 1, (
        f"expected exactly one `_run_docker(project, [atpg_shell], ...)` "
        f"launch, found {len(found)}")
    return found[0]


def test_the_atpg_engine_is_launched_supervised_and_unclocked():
    """THE DEFECT, as a property of the call that had it.

    `timeout=` here is a wall the container enforces on the engine. Its
    presence is the issue; its absence with `supervised=True` is the fix."""
    call = _atpg_launch_call()
    kw = {k.arg: k for k in call.keywords}
    assert "timeout" not in kw, (
        "the ATPG launch passes a `timeout=` again — that is a clock the "
        "container enforces on the engine, which is vibe-ic#2082 restored")
    assert isinstance(kw.get("supervised", None) and kw["supervised"].value,
                      ast.Constant) or (
        "supervised" in kw and getattr(kw["supervised"].value, "value", None) is True), (
        "the ATPG launch is not supervised")
    assert "ceiling_s" in kw, (
        "the declared budget is not passed as a RECORDED ceiling, so the "
        "number the run was sized against is no longer anywhere in the record")
    assert "ceiling_notice" in kw, (
        "nothing announces the crossing; a budget nobody is told about was "
        "crossed is not a record, it is a deleted number")


def test_a_reintroduced_clock_at_the_launch_site_is_caught():
    """THE NEGATIVE CONTROL for the test above. A guard that cannot fail is
    not a guard, so put the defect back and require the finding."""
    src = (_PROGRAMS / "fault_atpg_run.py").read_text()
    mutated = src.replace(
        "ec, out, err = _run_docker(project, [atpg_shell], pdk_dir=pdk_dir,\n"
        "                                   supervised=True, ceiling_s=_atpg_wall,",
        "ec, out, err = _run_docker(project, [atpg_shell], pdk_dir=pdk_dir,\n"
        "                                   timeout=_atpg_wall, ceiling_s=_atpg_wall,",
        1)
    assert mutated != src, "the mutation did not apply — update this control"
    tree = ast.parse(mutated)
    saw_timeout = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) == "_run_docker"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.List)
                and getattr(getattr(node.args[1].elts[0], "id", None), "__str__", str)() == "atpg_shell"):
            saw_timeout |= any(k.arg == "timeout" for k in node.keywords)
    assert saw_timeout, (
        "the mutated tree does not show the clock this test claims to detect")


# ── 2. A SUPERVISED LAUNCH HAS NO CONTAINER-SIDE DEADLINE ───────────────────
class _Rec:
    """Capture the argv a launcher was handed."""

    def __init__(self):
        self.argv = None
        self.kw = {}

    def supervised(self, cmd, **kw):
        self.argv, self.kw = cmd, kw
        return W.SupervisedResult(0, "", "", "natural", 0.0)

    def plain(self, argv, **kw):
        self.argv, self.kw = argv, kw
        return subprocess.CompletedProcess(argv, 0, "", "")


def _force_container_route(monkeypatch):
    monkeypatch.setattr(F._CE, "no_container_route", lambda: False)


def test_a_supervised_launch_disables_the_container_side_deadline(
        monkeypatch, tmp_path):
    """`timeout 0` is GNU's documented "disable", so the SAME argv expresses
    both states and no second execution path appears. MEASURED in the pinned
    image (coreutils 9.4): `timeout -k 5 3 sleep 8` -> 124, `timeout -k 5 0
    sleep 8` -> 0 after 8 s."""
    _force_container_route(monkeypatch)
    rec = _Rec()
    monkeypatch.setattr(F._wd, "run_host_supervised", rec.supervised)
    F._run_docker(tmp_path, ["fault atpg"], supervised=True, ceiling_s=99)
    shell = rec.argv[-1]
    assert shell.startswith(f"timeout -k {F._CE.DEFAULT_KILL_GRACE_S} 0 bash -c "), shell
    assert rec.kw["hard_ceiling_s"] == 99.0, rec.kw


def test_an_unsupervised_launch_still_carries_its_deadline(monkeypatch, tmp_path):
    """THE OTHER DIRECTION. Every other caller of `_run_docker` is a short
    probe and keeps the deadline vibe-ic#623 put inside the container; this
    change is opt-in, and a change that quietly disarmed them all would be a
    different and worse defect."""
    _force_container_route(monkeypatch)
    rec = _Rec()
    monkeypatch.setattr(F.subprocess, "run", rec.plain)
    F._run_docker(tmp_path, ["fault", "atpg", "--help"], timeout=10,
                  flush_grace_s=20)
    assert f"timeout -k {F._CE.DEFAULT_KILL_GRACE_S} 30 bash -c " in rec.argv[-1]


def test_the_deadline_arithmetic_still_cannot_produce_zero():
    """The clamp that makes 0 unreachable BY ACCIDENT is untouched. 0 is now a
    value one caller asks for on purpose, which is the opposite of arriving at
    it by arithmetic nobody checked."""
    assert F.atpg_container_deadline(0, -5) == 1
    assert F.atpg_container_deadline(1800, 600) == 2400
    assert F.ATPG_NO_CONTAINER_DEADLINE == 0


def test_a_timeout_handed_to_a_supervised_launch_is_refused(tmp_path):
    """Accepted-and-ignored is how a deadline comes to exist only in a
    caller's belief — the exact defect `_run_docker`'s own docstring is about.
    `_progress_run` set the precedent: refuse, do not drop."""
    with pytest.raises(TypeError) as exc:
        F._run_docker(tmp_path, ["fault atpg"], timeout=42, supervised=True)
    assert "42" in str(exc.value)


# ── 3. THE TWO DIRECTIONS, EXECUTED ON REAL HOST PROCESSES ──────────────────
# Driven through the LOCAL route, so these run anywhere (in-image included)
# without a docker daemon. The supervision logic, the ceiling record and the
# reap are the same objects the container route uses.
def _force_local_route(monkeypatch):
    monkeypatch.setattr(F._CE, "no_container_route", lambda: True)
    monkeypatch.setattr(F, "_announce_local_atpg_route", lambda *_a, **_k: None)
    monkeypatch.setattr(F, "_localise_mounted_paths",
                        lambda inner, *_a, **_k: inner)
    monkeypatch.setattr(F, "ENV_PREAMBLE", "")


def test_a_slow_but_progressing_job_runs_PAST_its_budget_and_delivers(
        monkeypatch, tmp_path):
    """DIRECTION ONE. The job outlives its declared budget by several times
    over, is not touched, produces its output, and the crossing is RECORDED.

    This is the sha256 case in miniature: the engine was working the whole
    time, and the only thing the old code did with that fact was throw it
    away."""
    _force_local_route(monkeypatch)
    crossed = []
    # ~3 s of steady output; the declared budget is 1 s.
    job = ("python3 -c \"import sys,time\n"
           "for i in range(15): sys.stdout.write('tick %d\\n' % i); "
           "sys.stdout.flush(); time.sleep(0.2)\n"
           "sys.stdout.write('DONE\\n')\"")
    rc, out, _err = F._run_docker(
        tmp_path, [job], supervised=True, ceiling_s=1.0,
        ceiling_notice=lambda e: crossed.append(round(float(e), 2)),
        stall_grace_s=4.0)
    assert rc == 0, out
    assert "DONE" in out, "the job's product was lost — it was cut off"
    assert crossed, ("the declared budget was crossed and NOTHING recorded it; "
                     "a budget nobody is told about is a deleted number")
    assert crossed[0] >= 1.0, crossed
    assert len(crossed) == 1, f"the crossing must be announced ONCE: {crossed}"


def test_a_job_that_stops_making_progress_is_reaped_and_named_a_stall(
        monkeypatch, tmp_path):
    """DIRECTION TWO. Progress supervision is not "never stop anything": a job
    that goes completely still IS stopped, under the supervisor's own distinct
    rc, with the evidence on the record. Without this direction the fix would
    be an unbounded run wearing a supervisor's name."""
    _force_local_route(monkeypatch)
    # Prints once (so the launch is visible), then stops itself dead. Every
    # readable signal — output, CPU, I/O — is flat from that moment.
    job = "echo started; kill -STOP $$; sleep 600"
    rc, _out, err = F._run_docker(tmp_path, [job], supervised=True,
                                  ceiling_s=600.0, stall_grace_s=3.0)
    assert rc == W.RC_STALLED, f"rc={rc}: a stopped job was not reaped as stalled"
    assert "WATCHDOG_STALLED" in err, err
    assert "since_last_progress_s" in err, (
        "the reap does not say what it saw — a stop that cannot answer 'for how "
        "long did nothing move' is an assertion, not a measurement")


def test_a_stall_is_never_read_as_a_transient_crash():
    """RC_STALLED is 199 = 128+71, which sits above the signal-death floor and
    names a signal that does not exist. Left in, a stalled engine would be
    RETRIED — three times — which is the most expensive possible response to a
    job already known to be going nowhere."""
    assert F.atpg_exit_is_signal_death(W.RC_STALLED, "") is False
    # CONTROL: a genuine signal death still is one, and still gets its retry.
    assert F.atpg_exit_is_signal_death(139, "") is True
    assert F.atpg_exit_is_signal_death(137, "") is True


# ── 4. THE EPHEMERAL-CONTAINER PROBE AND REAP ───────────────────────────────
_STAT = ("12 (fault) R 1 12 12 0 -1 4194304 100 0 0 0 %d %d 0 0 20 0 1 0 900 "
         "0 0 18446744073709551615 1 1 0 0 0 0 0 0 0 0 0 0 17 3 0 0 0 0 0\n")


class _ExecRec:
    def __init__(self, rc, stdout):
        self.rc, self.stdout, self.calls = rc, stdout, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, "")


def test_a_vanishing_pid_does_not_blind_the_cpu_probe():
    """THE MEASURED DEFECT, pinned. `cat /proc/[0-9]*/stat` exits NON-ZERO
    whenever any one pid disappears between the glob and the open — which in a
    container running an EDA tool is most of the time (measured: 7 of 12 looks
    against a real `fault atpg`, each carrying 27-38 kB of good stat lines).
    Judging the reading by that exit code discarded every one of them and left
    the supervisor watching output alone, silently, in the direction that kills
    a working job."""
    ticks = os.sysconf("SC_CLK_TCK")
    rec = _ExecRec(1, _STAT % (3 * ticks, 1 * ticks))
    probe = DWD.ephemeral_container_cpu_probe("c", runner=rec)
    assert probe(None) == pytest.approx(4.0), (
        "a non-zero exit with real stat lines was read as NO READING")


def test_an_absent_container_is_no_reading_not_zero():
    """THE OTHER DIRECTION, and it is not symmetric. None is carried forward by
    `ProgressMeter`; 0.0 would look like a progress RESET and could keep a
    genuinely hung job alive forever."""
    rec = _ExecRec(1, "")
    assert DWD.ephemeral_container_cpu_probe("c", runner=rec)(None) is None
    rec = _ExecRec(0, "not a stat line at all\n")
    assert DWD.ephemeral_container_cpu_probe("c", runner=rec)(None) is None


def test_the_reap_names_the_container_this_call_minted():
    """Killing the `docker run` client leaves the engine inside the container
    holding its cores, and `--rm` makes that leak look like self-cleaning. The
    victim is chosen by the unique name this invocation minted — an identity,
    never a command-line match, which is the rule one run's watchdog broke by
    SIGTERMing another run's healthy tool."""
    class _P:
        def __init__(self): self.killed = False
        def kill(self): self.killed = True

    rec = _ExecRec(0, "")
    proc = _P()
    DWD.ephemeral_container_reap("vibeic_atpg_1_beef", runner=rec)(proc, "stalled")
    assert proc.killed, "the docker client was left running"
    assert rec.calls == [["docker", "rm", "-f", "vibeic_atpg_1_beef"]], rec.calls


def test_two_invocations_never_share_a_container_name():
    a = DWD.ephemeral_container_name("vibeic_atpg")
    b = DWD.ephemeral_container_name("vibeic_atpg")
    assert a != b and a.startswith("vibeic_atpg_") and str(os.getpid()) in a
