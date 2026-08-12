#!/usr/bin/env python3
"""The ONE owner of "a declared artefact appears under its final name only when
it is complete" (vibe-ic#1082).

THE DEFECT, IN ONE SENTENCE
===========================
`p.write_text(json.dumps(report))` creates `p` and then fills it. Between those
two events `p` EXISTS and is short. If the process dies there — SIGKILL, a
harness tearing down the process group, a disk filling, an exception raised
while building the string — the file survives under its FINAL name, truncated
or empty, and every later reader treats it as the step's output.

`flow_compliance_check.check_step` resolves a step by asking whether its
`required_outputs` are present. So a step that died mid-write audits the same
as a step that finished. That is the empty-tree shape at the artefact level:
the file exists, so the check proceeds, and it proceeds over nothing.

WHAT THIS MODULE GUARANTEES, AND WHAT IT DOES NOT
=================================================
GUARANTEES. The final path is created by `os.replace`, which is atomic on POSIX
within a filesystem. A reader either sees the previous content (or nothing) or
sees the whole new content. There is no window in which the final name holds a
partial artefact.

DOES NOT. This is not durability. `os.replace` orders the RENAME, not the data
against a power cut; `fsync=True` adds the data barrier for callers that want
it, at a cost, and is off by default because the failure this module exists for
is a dying PROCESS, not a dying machine — a process death cannot lose data the
kernel already has.

DOES NOT. It cannot make a WRONG artefact right. A step that completes and
writes nonsense writes the nonsense atomically. The invariant bought here is
narrow and worth stating plainly: **the final name means the writer reached the
end**, so `required_outputs` becomes a statement about what happened rather
than about what a filesystem happened to contain.

WHY A TEMP FILE IN THE SAME DIRECTORY. `os.replace` is only atomic within one
filesystem. `/tmp` is frequently a different one (tmpfs), so a temp file there
would make the "rename" a copy — with exactly the partial-file window this
module removes. The temp file is therefore a sibling of the destination, and
`reserve()`-style scratch is deliberately NOT used.

WHY THE TEMP NAME IS DOT-PREFIXED AND PID-STAMPED. Dot-prefixed so a glob for
`*.json` in the output directory — which several consumers do — cannot see a
half-written file even while it is being written. PID-stamped so two processes
writing the same declared output do not corrupt each other's temp file; the
last `replace` wins, which is the same race the direct write already had, minus
the truncation.

CRASH LEFTOVERS. A dead process leaves `.<name>.<pid>.tmp` behind. That is litter,
never a false artefact: it does not match the declared name, so no consumer
reads it, and no `required_outputs` check counts it. `sweep_stale_temps()` is
provided for callers that want the tree tidy; nothing depends on it running.

USAGE
=====
    from _atomic_artifact import atomic_write_json, atomic_write_text, atomic_output

    atomic_write_json(out_path, report)          # the common case
    atomic_write_text(out_path, rendered)

    with atomic_output(out_path) as fh:          # streaming / large writes
        for row in rows:
            fh.write(row)
    # ^ the final name appears only if the block exits without raising
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Union

__all__ = [
    "atomic_output", "atomic_write_bytes", "atomic_write_json",
    "atomic_write_text", "sweep_stale_temps", "temp_name_for",
]

_PathLike = Union[str, "os.PathLike[str]"]

#: Suffix every in-flight artefact carries. Checked by
#: `atomic_artifact_write_check`, so it is defined here and nowhere else.
TEMP_SUFFIX = ".tmp"


def temp_name_for(final: Path) -> Path:
    """The sibling temp path for `final`. Dot-prefixed, pid-stamped, same dir."""
    return final.with_name(f".{final.name}.{os.getpid()}{TEMP_SUFFIX}")


@contextmanager
def atomic_output(path: _PathLike, mode: str = "w", *,
                  encoding: str | None = "utf-8",
                  fsync: bool = False) -> Iterator[Any]:
    """Yield a writable handle whose content appears at `path` only on success.

    On ANY exception the temp file is removed and `path` is left exactly as it
    was — which, for a first write, means ABSENT. That absence is the point: it
    is what makes "declared output missing" an accurate report of a step that
    died, rather than a filesystem accident.
    """
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_name_for(final)
    binary = "b" in mode
    fh = open(tmp, mode, **({} if binary else {"encoding": encoding}))
    try:
        yield fh
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt or a SystemExit
        # mid-write is exactly the case that used to leave a truncated
        # artefact under the final name.
        fh.close()
        tmp.unlink(missing_ok=True)
        raise
    else:
        fh.close()
        os.replace(tmp, final)


def atomic_write_bytes(path: _PathLike, data: bytes, *,
                       fsync: bool = False) -> Path:
    with atomic_output(path, "wb", encoding=None, fsync=fsync) as fh:
        fh.write(data)
    return Path(path)


def atomic_write_text(path: _PathLike, text: str, *,
                      encoding: str = "utf-8", fsync: bool = False) -> Path:
    with atomic_output(path, "w", encoding=encoding, fsync=fsync) as fh:
        fh.write(text)
    return Path(path)


def atomic_write_json(path: _PathLike, obj: Any, *, indent: int | None = 2,
                      sort_keys: bool = False, fsync: bool = False,
                      newline: bool = True) -> Path:
    """Serialise FIRST, then write.

    Deliberate ordering: `json.dumps` on an object carrying something
    unserialisable raises, and if that happened while streaming into an already
    -created final file the artefact would be left half-rendered under its
    final name. Rendering to a string first means the failure happens before
    any file exists at all.
    """
    body = json.dumps(obj, indent=indent, sort_keys=sort_keys, default=str)
    if newline:
        body += "\n"
    return atomic_write_text(path, body, fsync=fsync)


def sweep_stale_temps(directory: _PathLike) -> list[Path]:
    """Remove in-flight temps whose writer is gone; return what was removed.

    A temp whose pid is still alive is LEFT and not reported as removed — a
    cleanup that races a live writer is worse than the litter it removes. Same
    reasoning as `_crash_safe_scratch.reap`, one mechanism smaller: a pid probe
    is enough here because the temp name carries the writer's pid, and a
    mis-read (pid reused) costs one file that no consumer reads either way.
    """
    removed: list[Path] = []
    for tmp in Path(directory).glob(f".*{TEMP_SUFFIX}"):
        parts = tmp.name.split(".")
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[-2])
        except ValueError:
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            tmp.unlink(missing_ok=True)
            removed.append(tmp)
        except PermissionError:
            continue          # alive, owned by someone else
    return removed
