#!/usr/bin/env python3
"""vibe-ic#2083 — a `docker exec` stall verdict must be about the TOOL.

MEASURED 2026-09-07 on 8HD-8, lane cz2083, image
`sha256:8c5694ab…` (vibeic-eda 0.3.48), re-running the magic LEF extraction of
the sha256 35 MB GDS that lane rbsha2 recorded as

    ENV_UNAVAILABLE digital_hardmacro_gen
    STALLED: no forward progress across 12 consecutive looks
    (15.00s apart, 705.8s elapsed); signals readable: cpu,io,output

Sampled every 5 s from the host, the tool and its supervisor disagreed totally::

    t+29s   magic cpu= 28.8s rss=1.15GB | docker exec client cpu=0.01 io=0/0
    t+99s   magic cpu= 99.2s rss=2.35GB | docker exec client cpu=0.01 io=0/0
    t+124s  magic cpu=124.3s rss=2.31GB | docker exec client cpu=0.01 io=0/0
    …and the client relayed 0 new bytes for 162 s straight.

magic held a full 1.00 CPU-second per second throughout. The reason the
supervisor saw none of it is structural and is visible in one line of /proc::

    /proc/<magic>/stat ppid -> /usr/bin/containerd-shim-runc-v2

The tool is NOT a descendant of the `docker exec` client, so the client's
process tree — the only thing `_progress_run._host_probe` can walk — never
contains it. Client CPU, client I/O and relayed output are three signals about
a relay, and the stall verdict was a finding about the relay printed as a
finding about magic.

So `_container_exec.run_in_container` now injects `container_tree_probe`, which
sums CPU/I/O over the host processes belonging to that container that started
after the launch. These tests hold both directions:

  * a silent, idle child with NO extra channel still stalls (the detector keeps
    its teeth — this is the negative control, and it FAILS against the fix if
    the fix ever starts vouching for everything);
  * the same child with a MOVING channel is never stalled and runs to its own
    exit;
  * the container probe refuses to count work that predates the launch, so a
    sibling already running in a shared container cannot vouch for ours;
  * `run_in_container` actually passes the probe — the wiring, not the docstring.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _container_exec as ce  # noqa: E402
import _progress_run as pr  # noqa: E402


# ── the plumbing, both directions ──────────────────────────────────────────
def test_a_silent_idle_child_with_no_extra_channel_still_stalls():
    """THE NEGATIVE CONTROL. Without this the fix could not be shown to be one.

    `sleep` writes nothing, burns no CPU and does no block I/O, so every signal
    `_host_probe` can read sits flat. It must still be called stalled — a
    supervisor that stopped reporting this would have been repaired by being
    switched off.
    """
    with pytest.raises(pr.Stalled) as exc:
        pr.run([sys.executable, "-c", "import time; time.sleep(30)"],
               stall_looks=2, poll_s=0.25)
    assert "no forward progress" in str(exc.value)


def test_the_same_child_is_not_stalled_when_an_injected_channel_moves():
    """The fix, on the same subject the control stalls: only the channel differs."""
    calls = {"n": 0}

    def factory(signals):
        def probe(_proc):
            calls["n"] += 1
            signals["container"] = True
            return float(calls["n"])   # a channel that advances every look
        return probe

    cp = pr.run([sys.executable, "-c", "import time; time.sleep(2)"],
                stall_looks=2, poll_s=0.25, progress_probe=factory)
    assert cp.returncode == 0
    assert calls["n"] >= 2, "the injected probe was never consulted"


def test_an_injected_channel_that_sits_still_does_not_rescue_a_stalled_child():
    """A probe is a MEASUREMENT, not a licence. A flat one changes nothing."""
    def factory(signals):
        def probe(_proc):
            signals["container"] = True
            return 7.0                 # readable, and never moves
        return probe

    with pytest.raises(pr.Stalled):
        pr.run([sys.executable, "-c", "import time; time.sleep(30)"],
               stall_looks=2, poll_s=0.25, progress_probe=factory)


def test_fuse_probes_advances_when_any_part_advances_and_is_none_when_all_are():
    seq = iter([1.0, 2.0])
    fused = pr.fuse_probes(lambda _p: None, lambda _p: next(seq))
    assert fused(None) == 1.0
    assert fused(None) == 2.0
    assert pr.fuse_probes(lambda _p: None, lambda _p: None)(None) is None


# ── the container probe's scoping rule ─────────────────────────────────────
def _fake_proc_tree(monkeypatch, pids, since=1000.0):
    """`pids` maps pid -> (starttime_ticks, cpu_ticks, in_this_container)."""
    monkeypatch.setattr(ce, "container_id", lambda _c: "d" * 64)
    monkeypatch.setattr(ce, "_uptime_ticks", lambda: since)
    monkeypatch.setattr(ce.os, "listdir", lambda _p: [str(p) for p in pids])
    monkeypatch.setattr(
        ce, "_in_container", lambda pid, _cid: pids[int(pid)][2])

    def stat_fields(pid):
        start, cpu, _ = pids[int(pid)]
        f = [b"S"] * 22
        f[11] = str(int(cpu)).encode()
        f[12] = b"0"
        f[19] = str(int(start)).encode()
        return f
    monkeypatch.setattr(ce, "_stat_fields", stat_fields)


def test_container_probe_counts_work_started_after_the_launch(monkeypatch):
    signals = {}
    _fake_proc_tree(monkeypatch, {42: (1500.0, 300, True)})
    probe = ce.container_tree_probe("c")(signals)
    assert probe(None) == pytest.approx(3.0)
    assert signals["container"] is True


def test_container_probe_ignores_a_sibling_that_predates_the_launch(monkeypatch):
    """A SHARED container must not let somebody else's job vouch for ours.

    Without the start-time filter, one busy sibling in the same container would
    make every stall unreportable — which is the same defect as this issue with
    its sign flipped: a verdict about a process that is not the subject.
    """
    signals = {}
    _fake_proc_tree(monkeypatch, {7: (10.0, 999999, True)})
    assert ce.container_tree_probe("c")(signals)(None) is None
    assert signals == {}


def test_container_probe_ignores_a_process_outside_this_container(monkeypatch):
    signals = {}
    _fake_proc_tree(monkeypatch, {8: (1500.0, 999999, False)})
    assert ce.container_tree_probe("c")(signals)(None) is None


def test_an_unreadable_container_id_degrades_loudly_not_silently(monkeypatch):
    """NOT_MEASURED is not zero. The channel reports absent, and says so."""
    monkeypatch.setattr(ce, "container_id", lambda _c: None)
    signals = {}
    assert ce.container_tree_probe("c")(signals)(None) is None
    assert "container" not in signals, (
        "an unreadable channel must not claim to have been readable")


# ── the wiring ─────────────────────────────────────────────────────────────
def test_run_in_container_hands_the_container_channel_to_the_supervisor(
        monkeypatch):
    """The DOCSTRING is not the fix; the argument is."""
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ce._pin, "container_attach_refusal", lambda _c: None)
    monkeypatch.setattr(ce._pr, "run", fake_run)
    ce.run_in_container("some-container", "true", deadline_s=5)
    assert seen.get("progress_probe") is not None, (
        "a docker-exec launch supervised only by the client's own counters is "
        "the vibe-ic#2083 defect: the tool is parented by the container "
        "runtime's shim and appears in no process tree the client owns")
    monkeypatch.setattr(ce, "container_id", lambda _c: None)
    assert callable(seen["progress_probe"]({}))
