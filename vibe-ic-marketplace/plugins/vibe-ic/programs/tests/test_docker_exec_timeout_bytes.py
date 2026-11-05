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

from programs import phase3_one_shot_runner as R
from programs.phase3_one_shot_runner import _docker_exec


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


def test_docker_exec_normal_bytes_streams_decoded(monkeypatch) -> None:
    """Even on the success path, a bytes stdout/stderr (text=False
    fallback) is decoded to str.

    THE STUB ANSWERS THE ARGV IT IS ASKED, AND NEVER THE HOST (vibe-ic#2106,
    then vibe-ic#2145). `_docker_exec` does not reach `subprocess.run` first:
    `_exec_argv` decides a ROUTE and then builds the argv through
    `_container_exec.docker_exec_argv`, which asks `_eda_pin` whether the
    container is running the pinned bytes — a `docker inspect` of its own. Two
    different callers, and each has to be answered with something its real
    caller could actually receive:

      * `docker exec …` — THE SUBJECT. Bytes on a `text=True` call, which is
        exactly the condition this test exists for and the one CPython really
        produces when a stream is killed mid-decode.
      * `docker inspect …` — the pin probe. `rc=1` with STR streams is docker's
        own "no such container", which `container_pin_state` classifies
        UNREADABLE. Deliberately not a MISMATCH: `docker_exec_argv` RAISES on a
        measured mismatch, so a stub that faked a wrong image would replace this
        test's subject with the refusal path and never decode anything.
      * anything else — REFUSED, loudly. There is no third caller on this path,
        and an `else` that quietly answers one is how this test stopped being
        about the decoder at all.

    THE ROUTE IS PINNED, BECAUSE IT WAS THE HOST THAT WAS BEING MEASURED.
    #2106's version of this stub keyed on `"exec" in argv` with a silent `else`,
    and `_exec_argv` asks `_local_exec_mode()` -> `no_container_route()` ->
    `shutil.which("docker") is None` BEFORE it builds anything. On a host with a
    docker client the argv is `docker exec …` and the test passed; with no
    docker client on PATH the route is LOCAL, the argv is `["bash","-lc",…]`,
    it carries no `exec` element, and the silent `else` handed THE SUBJECT
    docker's rc=1 "no such container". MEASURED 2026-09-07 on 8hd-3, both
    directions, one tree per commit:

                    | host (docker on PATH) | pinned image (no docker client)
        ebb00b1b4^  | FAIL (#2106)          | PASS
        ebb00b1b4   | PASS                  | FAIL   <- vibe-ic#2145

    So `_LOCAL_EXEC_MODE` is set explicitly here. That is not narrowing the
    population: the container route is this test's SUBJECT — a route with no
    `docker exec` in it cannot be the one whose result is being decoded — and
    the other route is covered by its own arm below, so both are asserted
    instead of one being decided by whatever host the suite lands on.
    """
    class _ExecCP:
        returncode = 0
        stdout = b"ok-bytes"
        stderr = bytearray(b"warn-bytes")

    class _NoSuchContainerCP:
        returncode = 1
        stdout = ""
        stderr = "Error: No such object: vibeic-eda"

    asked = []

    def _answer(argv, *_a, **_kw):
        argv = list(argv)
        asked.append(argv)
        if argv[:2] == ["docker", "exec"]:
            return _ExecCP()
        if argv[:2] == ["docker", "inspect"]:
            return _NoSuchContainerCP()
        raise AssertionError(
            "the stub was reached for an argv it has no honest answer to: "
            f"{argv!r}. Only `docker exec` (the subject) and `docker inspect` "
            "(the pin probe) run on this path; anything else means the route "
            "changed and this test is no longer measuring the decoder.")

    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", False)
    with patch("subprocess.run", side_effect=_answer):
        rc, out, err = _docker_exec("vibeic-eda", "echo ok")
    assert (rc, isinstance(out, str), isinstance(err, str)) == (0, True, True)
    assert out == "ok-bytes"
    assert err == "warn-bytes"
    # THE SUBJECT WAS ACTUALLY REACHED. Without this the assertions above are
    # satisfiable by a path that never issued a `docker exec` at all.
    assert any(a[:2] == ["docker", "exec"] for a in asked), asked


def test_local_exec_route_also_decodes_bytes_streams(monkeypatch) -> None:
    """The OTHER route decodes too, and it is asserted rather than assumed.

    In LOCAL mode (`no_container_route()` — no docker client on PATH, which is
    what running inside the image itself looks like) `_exec_argv` returns
    `["bash","-lc",…]` and nothing is `docker exec`ed. `_as_text` is the same
    normalizer on both routes, and this arm is what stops the pair above from
    being one route measured twice: the route is pinned in each, so neither can
    silently become the other when the host changes.
    """
    class _BashCP:
        returncode = 0
        stdout = b"local-bytes"
        stderr = bytearray(b"local-warn")

    asked = []

    def _answer(argv, *_a, **_kw):
        argv = list(argv)
        asked.append(argv)
        if argv[:2] == ["bash", "-lc"]:
            return _BashCP()
        raise AssertionError(
            "LOCAL mode must not reach docker at all; the stub was asked "
            f"{argv!r}")

    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", True)
    with patch("subprocess.run", side_effect=_answer):
        rc, out, err = _docker_exec("vibeic-eda", "echo ok")
    assert (rc, out, err) == (0, "local-bytes", "local-warn")
    assert asked and asked[0][:2] == ["bash", "-lc"], asked


def test_docker_exec_none_streams_become_empty_str() -> None:
    exc = subprocess.TimeoutExpired(cmd="x", timeout=2)
    exc.stdout = None
    with patch("subprocess.run", side_effect=exc):
        rc, out, err = _docker_exec("vibeic-eda", "x", timeout=2)
    assert out == ""
    assert isinstance(err, str)
