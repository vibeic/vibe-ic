"""A3's simulator launch is SUPERVISED, and its budget is a record that is
actually said out loud (vibe-ic#2117).

WHAT WAS WRONG, IN TWO PARTS.

1. THE LAUNCH WALKED AWAY FROM A LIVE SIMULATOR. `verify_with_ngspice` entered
   the container through `container_deadline_argv(..., deadline_s=0)` and
   `_progress_run.run`. No clock fired — `deadline_s=0` is GNU `timeout`'s
   documented "disable the associated timeout" — but on a stall `_pr.run`
   RAISED and the function RETURNED `SIMULATION_STALLED`, leaving the still
   ngspice running inside the container. That is precisely the orphan
   `_container_exec` exists to prevent, now with a verdict written about it.
   The site was recorded in `watchdog_container_deadline_baseline.json` as
   CONTAINER_DEADLINE 4 rather than converted, because converting a live
   ngspice launch wanted its own proof. This file is that proof.

   MEASURED 2026-09-07 on 8HD-9, image sha256:8c5694ab (0.3.48), a real
   ngspice on the real `ldo` deck, SIGSTOPped inside the container:

       pre-fix  : SIMULATION_STALLED, ngspice pid 162 state T, STILL ALIVE
       post-fix : SIMULATION_STALLED, reap evidence `VIBEIC_REAP TERM 162`,
                  ZERO ngspice left in the container

2. THE BUDGET WAS ANNOUNCED TO NOBODY. `run_in_container_supervised` documented
   `ceiling_s` as "recorded and announced once"; `_watchdog` does call an
   INJECTED `ceiling_notice` — and `_progress_run.run`, the entry point that
   path reaches the supervisor through, passed none and does not carry the
   supervisor's `observations` back on the `CompletedProcess`. So every
   `ceiling_s` ever handed to that function was a declared control nothing
   could observe. MEASURED, same host, same image, the real `ldo` deck through
   `verify_with_ngspice`:

       ceiling_s=2      elapsed 10.5 s  CONVERGED, 1 measurement,
                        1 x VIBEIC_CEILING_CROSSED at elapsed_s=2
       ceiling_s=10000  elapsed 10.7 s  CONVERGED, 1 measurement, 0 announcements

   The second row is the control: the announcement is caused by the CROSSING,
   not by the code path existing.

Nothing here needs a docker client: the announcement is proven end to end
against a REAL local subprocess, and the container-shaped assertions inject
the supervisor rather than stubbing the answer.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _container_exec as CE
import _progress_run as PR
import analog_a3_netlist_emit as A3

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))
REGISTER = PROGRAMS / "watchdog_container_deadline_baseline.json"


# ═══ the budget is announced, and only when it is crossed ═════════════════

def test_the_crossing_is_announced_against_a_real_child():
    """END TO END, no injection: a real subprocess that outlives its recorded
    budget. The notice fires ONCE and the child runs to its own completion."""
    seen = []
    t0 = time.monotonic()
    cp = PR.run(["bash", "-lc", "sleep 3; echo finished"],
                capture_output=True, text=True,
                hard_ceiling_s=0.5, poll_s=0.2, stall_looks=200,
                ceiling_notice=seen.append)
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "finished", cp.stdout
    assert time.monotonic() - t0 >= 2.5, "the child was cut short"
    assert len(seen) == 1, seen
    assert 0.5 <= seen[0] < 3.0, seen


def test_a_child_that_stays_inside_its_budget_announces_nothing():
    """THE CONTROL. Same call, same wiring, a budget the child never reaches.
    Without this, a notice that fired unconditionally would pass the test
    above."""
    seen = []
    cp = PR.run(["bash", "-lc", "sleep 1; echo finished"],
                capture_output=True, text=True,
                hard_ceiling_s=600.0, poll_s=0.2, stall_looks=200,
                ceiling_notice=seen.append)
    assert cp.returncode == 0
    assert seen == [], seen


def test_the_notice_names_the_container_the_budget_and_the_elapsed_time():
    """A mark with no numbers is a mark a reader cannot act on."""
    out = io.StringIO()
    CE.default_ceiling_notice("c_alpha", 900.0, out=out)(1234.0)
    line = out.getvalue().strip()
    assert line.startswith(CE.CEILING_CROSSED_MARK), line
    assert "container=c_alpha" in line
    assert "ceiling_s=900" in line
    assert "elapsed_s=1234" in line
    assert "NOT signalled" in line, (
        "the whole point of the mark is that the job is still running")


def test_the_supervised_container_run_installs_a_notice(monkeypatch):
    """`run_in_container_supervised` is where the two halves meet: it is the
    only place that knows both the container and the budget. Asserted on the
    kwargs the primitive is CALLED with, so a notice that is built and dropped
    cannot satisfy it."""
    seen = {}

    def _fake_run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(CE._pin, "container_attach_refusal", lambda *a, **k: "")
    monkeypatch.setattr(CE._pr, "run", _fake_run)
    CE.run_in_container_supervised("c_alpha", "true", ceiling_s=42.0)
    assert seen.get("hard_ceiling_s") == 42.0, seen
    notice = seen.get("ceiling_notice")
    assert callable(notice), seen
    out = io.StringIO()
    CE.default_ceiling_notice("c_alpha", 42.0, out=out)(43.0)
    assert CE.CEILING_CROSSED_MARK in out.getvalue()


def test_a_caller_supplied_notice_wins(monkeypatch):
    """The default is a default. A caller routing the crossing into its own
    record must not also get it printed by somebody else."""
    seen = {}
    monkeypatch.setattr(CE._pin, "container_attach_refusal", lambda *a, **k: "")
    monkeypatch.setattr(CE._pr, "run",
                        lambda argv, **kw: (seen.update(kw) or
                                            subprocess.CompletedProcess(
                                                argv, 0, "", "")))
    mine = []

    def _mine(elapsed_s):
        mine.append(elapsed_s)

    CE.run_in_container_supervised("c_alpha", "true", ceiling_s=1.0,
                                   ceiling_notice=_mine)
    assert seen.get("ceiling_notice") is _mine, seen


# ═══ A3 routes through the supervised primitive and reads its rc ══════════

def _drive(monkeypatch, rc, stderr="", stdout=""):
    """Drive `verify_with_ngspice` past its probes to the launch, with the
    launch's own result supplied. Everything before the launch is the shipped
    code; only the container's answer is injected."""
    monkeypatch.setattr(A3.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(A3, "_docker_ok", lambda _c: True)
    monkeypatch.setattr(
        A3._pr, "run_best_effort",
        lambda argv, *a, **k: subprocess.CompletedProcess(argv, 0, "yes", ""))
    monkeypatch.setattr(
        A3._ce, "run_in_container_supervised",
        lambda *a, **k: subprocess.CompletedProcess(["docker"], rc,
                                                    stdout, stderr))
    monkeypatch.setattr(A3._ce, "docker_exec_argv",
                        lambda c, *r, **k: ["docker", "exec", c, *r])
    return A3.verify_with_ngspice("c_alpha", "blk_alpha", "* sp", "* tb")


def test_a_stalled_simulator_is_named_a_stall_and_carries_the_reap(monkeypatch):
    """`STALLED_RC` is not the tool's rc and must never be read as one. The
    reap evidence travels with the verdict, because "we stopped it" and "we
    gave up on it" are different facts and only one leaves the host clean."""
    got = _drive(monkeypatch, CE.STALLED_RC,
                 stderr="no forward progress\nVIBEIC_REAP TERM 162 171")
    assert got["simulation_status"] == "SIMULATION_STALLED"
    assert got["simulation_verified"] is False
    assert "VIBEIC_REAP TERM 162 171" in got["detail"], got["detail"]


def test_a_stall_is_not_a_netlist_that_did_not_converge(monkeypatch):
    """The failure this replaces. A stall reaching the log reader would find
    no `MEAS` line in an empty log and answer DID_NOT_CONVERGE — which deletes
    the deck, charging a design for a host condition."""
    got = _drive(monkeypatch, CE.STALLED_RC, stderr="no forward progress")
    assert got["simulation_status"] != "DID_NOT_CONVERGE"
    assert got["simulation_status"] != "NOT_VERIFIED_NO_SIMULATOR"


def test_a_normal_exit_still_reads_the_log(monkeypatch):
    """THE PAIRED ARM. A rc-0 run must still be judged on its own output — a
    stall branch that swallowed every result would pass the two above."""
    log = ("Initial Transient Solution\n"
           "xdut.n_a                              0.4\n"
           "MEAS vout = 1.8\n")
    got = _drive(monkeypatch, 0, stdout=log)
    assert got["simulation_status"] == "CONVERGED", got
    assert got["simulation_verified"] is True
    assert got["measurements"] == ["MEAS vout = 1.8"]


# ═══ the register shrank with the fix ═════════════════════════════════════

@pytest.mark.consistency
def test_the_a3_site_is_no_longer_on_the_container_deadline_record():
    """A converted site that stays on the record is a row the gate prints
    forever with a remedy nobody owes; `watchdog_ceiling_semantics_check`
    refuses a recorded key it can no longer find. The register may only ever
    SHRINK, and this is the row this commit removes."""
    rec = json.loads(REGISTER.read_text(encoding="utf-8"))["recorded"]
    assert not [k for k in rec if k.startswith("analog_a3_netlist_emit.py::")], (
        sorted(rec))
    # ... and the two that remain are other lanes' and are still named, so a
    # "shrink" that emptied the file would not pass either.
    assert len(rec) == 2, sorted(rec)
    assert not [k for k in rec if k.startswith(
        "input_doc_pdk_claim_vs_installed_pdk_check.py::")], sorted(rec)




# ═══ the reap the conversion depends on ═══════════════════════════════════
#
# THIS SECTION EXISTS BECAUSE THE PROOF #2117 ASKED FOR FAILED. Converting A3
# to `run_in_container_supervised` is only worth anything if the stall reap
# actually reaps, and MEASURED on 8HD-9 in the pinned image it did not:
#
#     E2, pre-fix : SIGSTOP ngspice mid-run -> SIMULATION_STALLED,
#                   `VIBEIC_REAP TERM 43 62`, `VIBEIC_REAP_SKIP already_gone`,
#                   ngspice 62 STILL ALIVE in state T
#
# Two independent causes, and either alone is enough to leave the orphan:
#
#   * A STOPPED PROCESS CANNOT ACT ON A TERM. The signal is queued and the
#     grace elapses against a process that was never able to answer.
#   * THE KILL PASS IS GATED ON THE ROOT. `supervised_container_command` execs
#     `bash -lc <cmd>`, so the stamped pid is that SHELL for any command that
#     is not a single simple command -- which is the normal case, and it is the
#     process that DOES obey the TERM. The escalation then reads the stamp,
#     finds the root gone, prints `already_gone` and signals nothing.

import _docker_watchdog as DW  # noqa: E402


class _Raw:
    """A recording `docker_exec_raw`. Answers each pass the way the measured
    container did: the TERM lists the tree, the root is gone by the KILL."""

    def __init__(self):
        self.cmds = []

    def __call__(self, container, cmd, timeout=15):
        self.cmds.append(cmd)
        if "VIBEIC_REAP_ID" in cmd and "-TERM" in cmd:
            return 0, ("VIBEIC_REAP_ID 43:100\nVIBEIC_REAP_ID 62:105\n"
                       "VIBEIC_REAP TERM 43 62\n"), ""
        if "VIBEIC_REAP_ID" in cmd and "-KILL" in cmd:
            return 0, "VIBEIC_REAP_SKIP already_gone\n", ""
        return 0, "VIBEIC_SWEEP KILL 62\n", ""


def test_the_kill_escalation_is_not_abandoned_when_the_root_is_gone():
    raw = _Raw()
    out = DW.kill_supervised_job("c_alpha", "/tmp/p.pid", docker_exec_raw=raw,
                                 term_grace_s=0.0)
    assert len(raw.cmds) == 3, raw.cmds
    sweep = raw.cmds[2]
    assert "kill -KILL 62" in sweep, sweep
    assert "105" in sweep, "the sweep dropped the identity it was given"
    assert "VIBEIC_SWEEP KILL 62" in out, out


def test_a_reap_whose_root_survives_still_only_does_what_it_did():
    """THE PAIRED ARM. The sweep is an ADDITION, not a replacement: when the
    root is still there the first two passes are unchanged, and the sweep can
    only ever re-signal pids that were already selected by identity."""
    raw = _Raw()
    DW.kill_supervised_job("c_alpha", "/tmp/p.pid", docker_exec_raw=raw,
                           term_grace_s=0.0)
    assert "-TERM" in raw.cmds[0] and "VIBEIC_REAP_ID" in raw.cmds[0]
    assert "-KILL" in raw.cmds[1]
    # every pid the sweep names came from the TERM pass's own listing
    assert set(DW.reaped_pids("VIBEIC_REAP TERM 43 62")) >= {43, 62}


def test_the_term_pass_continues_a_stopped_job_and_the_kill_pass_does_not():
    """CONT belongs with the TERM and nowhere else: a KILL needs no
    cooperation, and continuing a process after killing it is noise."""
    assert "kill -CONT" in DW.reap_command("/tmp/p.pid", "TERM")
    term = DW.reap_command("/tmp/p.pid", "TERM")
    kill = DW.reap_command("/tmp/p.pid", "KILL")
    # The guard is written once and reads its own signal, so assert on the
    # BEHAVIOUR of each rendered script rather than on the template.
    assert "if [ TERM = TERM ]" in term, term[-400:]
    assert "if [ KILL = TERM ]" in kill, kill[-400:]


def test_no_identities_means_no_sweep():
    """A reap that learned nothing must not invent a third pass, and must say
    that it learned nothing rather than reporting an empty success."""
    class _Silent(_Raw):
        def __call__(self, container, cmd, timeout=15):
            self.cmds.append(cmd)
            return 0, "VIBEIC_REAP_SKIP no_stamp\n", ""

    raw = _Silent()
    DW.kill_supervised_job("c_alpha", "/tmp/p.pid", docker_exec_raw=raw,
                           term_grace_s=0.0)
    assert len(raw.cmds) == 2, raw.cmds
    assert "VIBEIC_SWEEP_SKIP no_identities" in DW._sweep_command([], "KILL")


def test_reap_identities_drops_a_pid_it_could_not_identify():
    """A pid with no starttime is a pid that cannot be verified later. Keeping
    it would turn the sweep into a kill-by-number, which is the thing the whole
    identity mechanism exists to avoid."""
    got = DW.reap_identities("VIBEIC_REAP_ID 43:100\n"
                             "VIBEIC_REAP_ID 62:\n"
                             "VIBEIC_REAP_ID x:5\n"
                             "VIBEIC_REAP TERM 43 62\n")
    assert got == [(43, "100")], got


def _starttime(pid: int) -> str:
    field = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    return field[19]                       # field 22 overall, 20 after the name


@pytest.mark.skipif(not Path("/proc/self/stat").exists(),
                    reason="NOT_VERIFIED: no procfs to read a starttime from")
def test_the_sweep_kills_the_recorded_job_and_spares_a_stranger():
    """DRIVEN AGAINST REAL PROCESSES, both directions, on this host — no
    container needed, because the sweep is a shell script and its subject is a
    pid. A stranger is modelled the only way that matters: the SAME pid with a
    starttime that no longer matches."""
    victim = subprocess.Popen(["sleep", "120"])
    try:
        time.sleep(0.3)
        st = _starttime(victim.pid)

        # ... a pid whose identity does NOT match is left alone.
        wrong = str(int(st) + 1)
        subprocess.run(["bash", "-c", DW._sweep_command(
            [(victim.pid, wrong)], "KILL")], capture_output=True, text=True)
        time.sleep(0.3)
        assert victim.poll() is None, (
            "the sweep signalled a pid whose starttime did not match — it is "
            "killing by number, not by identity")

        # ... and the one that DOES match is reaped.
        cp = subprocess.run(["bash", "-c", DW._sweep_command(
            [(victim.pid, st)], "KILL")], capture_output=True, text=True)
        assert f"VIBEIC_SWEEP KILL {victim.pid}" in cp.stdout, cp.stdout
        assert victim.wait(timeout=10) is not None
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait(timeout=10)


@pytest.mark.skipif(not Path("/proc/self/stat").exists(),
                    reason="NOT_VERIFIED: no procfs to read a starttime from")
def test_a_stopped_process_is_actually_reaped():
    """THE MEASURED CASE, reduced to its mechanism.

    THE VICTIM CATCHES SIGTERM, and that is not incidental. A process that
    leaves SIGTERM at its default action is killed by the kernel even while
    stopped, so a bare `sleep` would prove nothing here — MEASURED while
    writing this test: `sleep` SIGSTOPped then SIGTERMed exits -15 straight
    away. ngspice installs a handler, so its TERM stays PENDING until
    something continues it, and the reap's grace elapses against a process
    that was structurally unable to answer. The sweep's KILL cannot be caught
    or blocked, and reaches it.
    """
    import signal as _sig
    victim = subprocess.Popen(
        [sys.executable, "-c",
         "import signal, time; signal.signal(signal.SIGTERM, lambda *a: None);"
         " time.sleep(120)"])
    try:
        time.sleep(1.0)
        st = _starttime(victim.pid)
        victim.send_signal(_sig.SIGSTOP)
        victim.send_signal(_sig.SIGTERM)     # queued behind the stop
        time.sleep(0.5)
        assert victim.poll() is None, (
            "the victim died on a TERM it was supposed to catch — this test "
            "is not modelling the measured case")
        subprocess.run(["bash", "-c", DW._sweep_command(
            [(victim.pid, st)], "KILL")], capture_output=True, text=True)
        assert victim.wait(timeout=10) is not None
    finally:
        if victim.poll() is None:
            victim.send_signal(_sig.SIGCONT)
            victim.kill()
            victim.wait(timeout=10)
