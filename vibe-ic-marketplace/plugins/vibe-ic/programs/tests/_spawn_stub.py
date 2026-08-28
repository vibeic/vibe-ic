"""_spawn_stub.py — stub a gate launch at the SPAWN, not at a dispatcher.

WHY THIS EXISTS (owner ruling, 2026-08-28)
==========================================
Every test that wanted to answer "what did the P0 umbrella dispatch, and what
did it do with the answer" used to stub the compliance module's ``subprocess``
attribute::

    monkeypatch.setattr(flow_compliance_check.subprocess, "run", _fake_run)

That binds the stub to WHOEVER HAPPENED TO CALL subprocess THAT DAY. When the
timeout-as-verdict campaign moved the umbrella's launch from
``subprocess.run(argv, timeout=60)`` to ``_watchdog.run_host_supervised(argv)``,
the gates still ran — the seam simply moved one module down — and five tests
across three files went red at once while the behaviour they assert was
unchanged. Measured: all five pass with the seam reverted and fail with it
moved.

So the stub is installed on ``subprocess.Popen`` itself, on the stdlib module
object. Every route converges there:

    flow_compliance_check.subprocess.run(argv, ...)   ─┐
    _watchdog.run_supervised -> popen_factory(cmd)     ├─> subprocess.Popen
    <whatever the campaign moves it to tomorrow>      ─┘

``subprocess.run`` resolves ``Popen`` as a module GLOBAL and ``_watchdog``'s
default ``popen_factory`` is ``lambda c, **kw: subprocess.Popen(c, **kw)`` over
the same module object, so ONE rebinding serves both seams and any third. The
same anchor and the same reasoning are used by
``test_matrix_d1_wiring.py``, which owns the falsification legs
(``test_probe_the_anchor_sees_both_seams``,
``test_probe_an_in_process_gate_call_is_not_a_dispatch``,
``test_probe_no_spawn_primitive_bypasses_the_anchor``). This module is the
consumer-facing helper; it deliberately does not restate those proofs.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple


class _StubbedPopen:
    """A ``Popen`` that creates no process and answers from the caller.

    Satisfies both consumer shapes: ``subprocess.run`` passes ``stdout=PIPE``
    (an int) and reads ``communicate()``/``poll()``; ``_watchdog`` passes real
    FILE OBJECTS, polls ``wait(timeout)`` and re-reads those files afterwards —
    so the stubbed stdout is written INTO the caller's sink when one is given.
    ``pid`` is None so a CPU probe declines rather than reading an unrelated
    live process.
    """

    def __init__(self, argv, rc: int, out: str, **kw):
        self.args = argv
        self.returncode = rc
        self.pid = None
        self.stdin = self.stdout = self.stderr = None
        text = bool(kw.get("text") or kw.get("universal_newlines")
                    or kw.get("encoding") or kw.get("errors"))
        self._out = out if text else out.encode()
        self._err = "" if text else b""
        sink = kw.get("stdout")
        if hasattr(sink, "write"):
            try:
                sink.write(out.encode())
            except TypeError:  # pragma: no cover - a text-mode sink
                sink.write(out)

    def communicate(self, input=None, timeout=None):
        return self._out, self._err

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass

    terminate = kill

    def send_signal(self, _sig):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def stub_spawn(monkeypatch,
               rc_for: Callable[[str], Tuple[int, str]],
               record: Optional[List[str]] = None) -> None:
    """Answer every gate launch from `rc_for(stem) -> (returncode, stdout)`.

    `record`, when given, receives the ``programs/<stem>.py`` basename of every
    launch IN ORDER — which is the dispatch fact most callers actually want.
    Anything that is not a gate-program launch is handed to the real ``Popen``
    and really runs, so an unrelated spawn inside the window still works.
    """
    real = subprocess.Popen

    def _factory(argv, **kw):
        try:
            listed = [str(a) for a in argv]
        except TypeError:  # pragma: no cover - a shell=True string command
            return real(argv, **kw)
        if len(listed) < 2 or not listed[1].endswith(".py"):
            return real(argv, **kw)
        stem = Path(listed[1]).stem
        if record is not None:
            record.append(stem)
        rc, out = rc_for(stem)
        return _StubbedPopen(listed, rc, out, **kw)

    monkeypatch.setattr(subprocess, "Popen", _factory)
