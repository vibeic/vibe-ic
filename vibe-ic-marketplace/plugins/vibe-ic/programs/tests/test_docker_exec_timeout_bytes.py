"""tests/test_docker_exec_timeout_bytes.py — v0.2.36

Regression for the str/bytes crash that killed a long phase3 PnR run.

Root cause: on `subprocess.TimeoutExpired`, the partial captured
`stdout`/`stderr` can come back as BYTES even though `text=True` was
requested (the streams are killed mid-decode). The old `_docker_exec`
returned that bytes value verbatim, which then poisoned every
downstream `out + err` string concat — notably
`step_pnr` → `_extract_overutil_pct(out + err)` →
`TypeError: can't concat str to bytes`. That TypeError crashed the
runner AFTER OpenROAD had already launched a multi-hour route, so the
process died with no `routed.def`.

Fix: `_docker_exec` now decodes any bytes partial → str so all callers
always receive `str`. Chip-AGNOSTIC pure I/O-type hygiene."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

from programs.phase3_one_shot_runner import (
    _docker_exec, _extract_overutil_pct,
)


def test_docker_exec_timeout_bytes_stdout_returns_str() -> None:
    """TimeoutExpired with a BYTES stdout partial must still return a
    `str` for both out and err so `out + err` never raises."""
    exc = subprocess.TimeoutExpired(cmd="x", timeout=1)
    exc.stdout = b"partial route output \xff captured before kill"
    exc.stderr = None
    with patch("subprocess.run", side_effect=exc):
        rc, out, err = _docker_exec("vibeic-eda", "openroad ...", timeout=1)
    assert rc == 124
    assert isinstance(out, str)
    assert isinstance(err, str)
    # the exact poison the bug tripped on:
    _ = out + err  # must not raise TypeError
    assert "partial route output" in out
    assert "TIMEOUT after 1s" in err


def test_docker_exec_normal_bytes_streams_decoded() -> None:
    """Even on the success path, a bytes stdout/stderr (text=False
    fallback) is decoded to str."""
    class _CP:
        returncode = 0
        stdout = b"ok-bytes"
        stderr = bytearray(b"warn-bytes")
    with patch("subprocess.run", return_value=_CP()):
        rc, out, err = _docker_exec("vibeic-eda", "echo ok")
    assert (rc, isinstance(out, str), isinstance(err, str)) == (0, True, True)
    assert out == "ok-bytes"
    assert err == "warn-bytes"


def test_docker_exec_none_streams_become_empty_str() -> None:
    exc = subprocess.TimeoutExpired(cmd="x", timeout=2)
    exc.stdout = None
    with patch("subprocess.run", side_effect=exc):
        rc, out, err = _docker_exec("vibeic-eda", "x", timeout=2)
    assert out == ""
    assert isinstance(err, str)


def test_overutil_extract_consumes_docker_exec_timeout_output() -> None:
    """End-to-end: the exact call site that crashed
    (`_extract_overutil_pct(out + err)`) now runs cleanly when the
    timeout handed back a bytes partial."""
    exc = subprocess.TimeoutExpired(cmd="x", timeout=1)
    exc.stdout = b"[INFO DRT-0195] Start 2nd optimization iteration."
    with patch("subprocess.run", side_effect=exc):
        _, out, err = _docker_exec("vibeic-eda", "openroad ...", timeout=1)
    # no GPL-0301 in this output → None, but crucially: NO TypeError.
    assert _extract_overutil_pct(out + err) is None
