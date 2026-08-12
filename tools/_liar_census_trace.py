#!/usr/bin/env python3
"""_liar_census_trace.py — run one gate program and record WHAT IT ACTUALLY TOUCHED.

Used by `liar_census.probe_pass_without_reading` and `probe_content_blind_pass`,
which ask the shape-12 question: *does this gate measure the property, or
something adjacent to it?*  Both need one fact that cannot be inferred from
source and must not be guessed at — **which files the gate really opened, and
whether it read them or only looked at them.**

WHY A SHIM AND NOT STATIC ANALYSIS
==================================
A gate's subject arrives through argv, `_path_layout`, a glob, an env var, a
default constant, and four import layers of helper. Deciding statically what a
program reads means re-implementing its path resolution — and being wrong about
it quietly, which is the family of defect this census exists to find. The
audit-hook answer is observed rather than inferred: it is what the process did.

The program still runs AS A SUBPROCESS, exactly as `liar_census._run` runs it.
This file is only a wrapper inside that subprocess. `sys.path[0]` is set to the
program's own directory, which is what `python3 <prog>.py` does and what the
gates' `sys.path.insert(0, Path(__file__).parent)` idiom depends on.

FOUR CHANNELS, and the distinction between them is the whole point
==================================================================
    READ    an `open()` in a read mode -> the gate consulted the CONTENT
    WRITE   an `open()` in a write/append mode -> the gate PRODUCED this
    LOOK    `os.stat`/`os.lstat`/`os.access`/`os.listdir`/`os.scandir`/
            `Path.glob`/`Path.exists` -> the gate observed PRESENCE only
    SPAWN   `subprocess.Popen`/`os.system`/`os.exec*` -> a child process did
            work this hook CANNOT see

`LOOK` without `READ` is "existence stood in for substance". `SPAWN` means the
trace is INCOMPLETE and the census must refuse to score the clause rather than
accuse a gate whose real work happened in a child it cannot follow.

DEGRADES LOUDLY, NEVER SILENTLY
===============================
`pathlib` binds `os.stat` at import time on some CPython versions (3.10 uses
`pathlib._normal_accessor`), so a `Path.exists()` can be invisible to a plain
`os.stat` patch. An unobserved LOOK would make a gate that checks presence look
like a gate that touched NOTHING — i.e. it would UPGRADE the severity of the
finding, silently, on some hosts. So every channel is SELF-TESTED against a
scratch directory before the target runs, and any channel that fails its own
self-test is named in `instrumentation`; the census then scores that clause N/A
and says so, rather than judging a gate through an instrument it just proved is
partly blind.
"""
from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile

_READ, _WRITE, _LOOK, _SPAWN = "read", "write", "look", "spawn"

#: path -> set of channels. Recording is suppressed while the shim itself works.
_seen: dict = {}
_recording = False


def _note(channel: str, path) -> None:
    if not _recording:
        return
    try:
        p = os.fspath(path)
    except TypeError:
        return
    if not isinstance(p, str):
        try:
            p = p.decode()
        except Exception:
            return
    _seen.setdefault(p, set()).add(channel)


def _open_channel(mode, flags) -> str:
    """Read or write, from `open()`'s own arguments.

    `open` audit args are (path, mode, flags). `mode` is the text mode string
    for builtins.open and None for os.open, where `flags` carries O_WRONLY /
    O_RDWR / O_CREAT / O_APPEND instead. Both spellings are read here because a
    gate that writes through `os.open` is still a producer.
    """
    if isinstance(mode, str) and mode:
        return _WRITE if any(c in mode for c in "wxa+") else _READ
    if isinstance(flags, int):
        w = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_TRUNC", 0)
        return _WRITE if flags & w else _READ
    return _READ


def _hook(event: str, args) -> None:
    if event == "open":
        path = args[0] if args else None
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else None
        _note(_open_channel(mode, flags), path)
    elif event in ("os.listdir", "os.scandir", "pathlib.Path.glob"):
        if args:
            _note(_LOOK, args[0])
    elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
        _note(_SPAWN, args[0] if args else "<child>")


def _wrap_stat() -> None:
    """Record `os.stat`-family calls, including the ones pathlib binds early.

    There is no audit event for `stat`, so this is the one channel that has to
    be patched rather than observed. Every patch site is self-tested below.
    """
    for mod, name in _stat_sites():
        orig = getattr(mod, name, None)
        if orig is None or getattr(orig, "_liar_census_wrapped", False):
            continue

        def make(orig=orig):
            def wrapper(path, *a, **kw):
                _note(_LOOK, path)
                return orig(path, *a, **kw)
            wrapper._liar_census_wrapped = True     # type: ignore[attr-defined]
            return wrapper

        try:
            setattr(mod, name, make())
        except Exception:                            # pragma: no cover
            pass


def _stat_sites():
    import pathlib
    sites = [(os, "stat"), (os, "lstat"), (os, "access")]
    acc = getattr(pathlib, "_normal_accessor", None)   # CPython <= 3.10
    if acc is not None:
        sites += [(acc, "stat"), (acc, "lstat")]
    return sites


def _self_test() -> list:
    """Prove each channel is observable HERE before trusting any of them."""
    import pathlib
    dark = []
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, "probe.txt")
        with open(probe, "w") as fh:
            fh.write("x")
        if _seen.get(probe, set()) != {_WRITE}:
            dark.append("write")
        _seen.pop(probe, None)
        with open(probe) as fh:
            fh.read()
        if _READ not in _seen.get(probe, set()):
            dark.append("read")
        _seen.pop(probe, None)
        os.listdir(td)
        if _LOOK not in _seen.get(td, set()):
            dark.append("listdir")
        _seen.pop(td, None)
        list(pathlib.Path(td).glob("*.txt"))
        if _LOOK not in _seen.get(td, set()):
            dark.append("glob")
        _seen.pop(td, None)
        pathlib.Path(probe).exists()
        if _LOOK not in _seen.get(probe, set()):
            dark.append("pathlib-exists")
        _seen.pop(probe, None)
        os.path.isfile(probe)
        if _LOOK not in _seen.get(probe, set()):
            dark.append("os.path-isfile")
        _seen.pop(probe, None)
    return dark


def main() -> int:
    global _recording
    if len(sys.argv) < 3:
        print("usage: _liar_census_trace.py <program.py> <trace.json> [args…]",
              file=sys.stderr)
        return 2
    target, out = sys.argv[1], sys.argv[2]

    sys.addaudithook(_hook)
    _wrap_stat()
    _recording = True
    dark = _self_test()
    _seen.clear()

    # exactly what `python3 <program>.py` does, and what the gates' own
    # `sys.path.insert(0, Path(__file__).resolve().parent)` idiom assumes
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    sys.argv = [target] + sys.argv[3:]

    rc = 0
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException as exc:                     # the gate crashed
        rc = 70
        print(f"<TRACED-CRASH {type(exc).__name__}: {exc}>", file=sys.stderr)

    _recording = False
    payload = {
        "instrumentation": "COMPLETE" if not dark else "INCOMPLETE: " + ",".join(dark),
        "rc": rc,
        "touched": {p: sorted(c) for p, c in sorted(_seen.items())},
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return rc


if __name__ == "__main__":
    sys.exit(main())
