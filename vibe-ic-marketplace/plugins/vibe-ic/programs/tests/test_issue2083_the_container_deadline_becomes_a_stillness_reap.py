#!/usr/bin/env python3
"""vibe-ic#2083 (owner ruling, 2026-09-07) — the second half.

Fixing the false stall alone still left the hard macro un-produced, for an
independent reason. `digital_hardmacro_gen` spent ONE `timeout_s` (default 900)
two different ways:

  * host path, l.1111: `run_host_supervised(stall_grace_s=float(timeout_s))`
    — a STALL GRACE. A magic that keeps computing is never stopped.
  * container path — the one a flow run actually takes — via
    `_container_exec.run_in_container(deadline_s=timeout_s)`:
        docker exec <c> timeout -k 5 900 bash -lc 'magic …'
    — a HARD WALL CLOCK inside the container, booked as
    `magic did not complete: the 900s deadline expired`.

MEASURED (8HD-8, image sha256:8c5694ab / 0.3.48): that extraction, run with
nothing in front of it, takes **5187.5 s** at a steady 1.000 CPU-second per
second and finishes cleanly — exit 0, `DIGITAL_LEF_WRITE_DONE`, a 21494-byte
abstract with 84 pins. The 900 s deadline lands at **17.4%** of the job. So the
step was cutting healthy tools in half and reporting the cut as the tool's own
failure.

The ruling: convert the site to the supervised shape — identity stamp then
`exec`, NO outer clock — reaped only on STILLNESS and only BY IDENTITY, with
the old value kept as a RECORDED ceiling. The orphan contract the deadline
existed for is kept and sharpened: a still tool is reaped where it lives, a
computing one is never cut.

These tests hold every load-bearing half of that, and the register clause that
makes putting the clock back a RED.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _container_exec as ce  # noqa: E402
import _progress_run as pr  # noqa: E402


# ── the shape of the launch ────────────────────────────────────────────────
def test_the_supervised_launch_carries_no_clock_and_stamps_its_identity(
        monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "out", "")

    monkeypatch.setattr(ce._pin, "container_attach_refusal", lambda _c: None)
    monkeypatch.setattr(ce._pr, "run", fake_run)
    cp = ce.run_in_container_supervised("c", "magic -noconsole x.tcl",
                                        ceiling_s=900.0)
    assert cp.returncode == 0
    joined = " ".join(seen["cmd"])
    assert "timeout" not in joined, (
        "the supervised path must carry NO outer clock: a `timeout` here "
        "SIGKILLs a job that may be working perfectly, which is the class "
        "vibe-ic#2051 removed (and which cut the real magic run at 17.4%)")
    assert ".pid" in joined and "__vic_st" in joined, (
        "the identity stamp is what lets the reap select THIS job rather than "
        "pattern-matching a command line")
    assert seen["hard_ceiling_s"] == 900.0, (
        "the old deadline value must survive as a RECORDED ceiling")
    assert seen.get("progress_probe") is not None, (
        "stillness must be read from the container's own work")


def test_a_stall_is_reaped_by_identity_and_never_reported_as_the_tools_rc(
        monkeypatch):
    """The orphan contract. A supervisor that gives up without reaping leaves
    exactly the orphan the container-side deadline existed to prevent."""
    reaped = {}

    def fake_run(cmd, **kw):
        raise pr.Stalled(cmd, 4, 5.0, 20.0, {"container": True, "cpu": True},
                         "partial", "")

    monkeypatch.setattr(ce._pin, "container_attach_refusal", lambda _c: None)
    monkeypatch.setattr(ce._pr, "run", fake_run)
    import _docker_watchdog as dw
    monkeypatch.setattr(dw, "kill_supervised_job",
                        lambda container, pidfile, **kw: reaped.setdefault(
                            "out", f"VIBEIC_REAP TERM 152 171") or reaped["out"])
    monkeypatch.setattr(dw, "cleanup_job_pidfile",
                        lambda *a, **k: reaped.setdefault("cleaned", True))

    cp = ce.run_in_container_supervised("c", "magic x.tcl", ceiling_s=900.0)
    assert cp.returncode == ce.STALLED_RC
    assert cp.returncode != 0 and cp.returncode != 124, (
        "a stall must never arrive wearing the tool's own rc, nor the rc that "
        "means `the clock ran out` — they are different findings")
    assert "VIBEIC_REAP" in cp.stderr, (
        "the reap evidence must reach the caller: 'I gave up watching' without "
        "'and I killed it where it lives' is how an orphan is made")
    assert "no forward progress" in cp.stderr
    assert reaped.get("cleaned") is True


def test_the_stall_rc_describes_stillness_not_elapsed_time():
    why = ce.describe_result(
        subprocess.CompletedProcess("x", ce.STALLED_RC), 900)
    assert why and "no forward progress" in why
    assert "deadline" not in why and "900" not in why, (
        "naming a number that stopped nothing tells the reader the run was cut "
        "when it was not")
    # …and the deadline entry still says what IT means, unchanged.
    other = ce.describe_result(
        subprocess.CompletedProcess("x", ce.TIMEOUT_EXPIRED_RC), 900)
    assert "deadline" in other


# ── the producer actually takes that route ─────────────────────────────────
def _magic_site_sh_body() -> str:
    src = (PROGRAMS / "digital_hardmacro_gen.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "MagicSite":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "sh":
                    return ast.unparse(fn)
    raise AssertionError("MagicSite.sh not found")


def test_the_hardmacro_producer_launches_magic_supervised_not_on_a_clock():
    body = _magic_site_sh_body()
    assert "run_in_container_supervised" in body
    assert "deadline_s" not in body, (
        "a deadline at this site cuts a 5187 s extraction at 900 s and books "
        "it as the tool's own failure")


def test_the_producer_reports_a_stall_as_a_stall():
    src = (PROGRAMS / "digital_hardmacro_gen.py").read_text(encoding="utf-8")
    assert "_container_exec.STALLED_RC" in src
    assert "deadline expired" not in src, (
        "the step may no longer claim a deadline expired: nothing there "
        "expires any more")


# ── the register clause: putting the clock back is a RED ───────────────────
